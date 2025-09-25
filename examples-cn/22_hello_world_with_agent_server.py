import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from pydantic import SecretStr

from openhands.sdk import LLM, Conversation, get_logger
from openhands.sdk.conversation.impl.remote_conversation import RemoteConversation
from openhands.sdk.preset.default import get_default_agent


logger = get_logger(__name__)


def _stream_output(stream, prefix, target_stream):
    """将子进程输出带前缀地写入目标流。"""
    try:
        for line in iter(stream.readline, ""):
            if line:
                target_stream.write(f"[{prefix}] {line}")
                target_stream.flush()
    except Exception as e:
        print(f"转发 {prefix} 输出时出错：{e}", file=sys.stderr)
    finally:
        stream.close()


class ManagedAPIServer:
    """用于管理 OpenHands API 服务器子进程的上下文管理器。"""

    def __init__(self, port: int = 8000, host: str = "127.0.0.1"):
        self.port = port
        self.host = host
        self.process = None
        self.base_url = f"http://{host}:{port}"
        self.stdout_thread = None
        self.stderr_thread = None

    def __enter__(self):
        """启动 API 服务器子进程。"""
        print(f"正在 {self.base_url} 启动 OpenHands API 服务器…")

        # 启动服务器进程
        self.process = subprocess.Popen(
            [
                "python",
                "-m",
                "openhands.agent_server",
                "--port",
                str(self.port),
                "--host",
                self.host,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={"LOG_JSON": "true", **os.environ},
        )

        # 启动线程转发 stdout 与 stderr
        self.stdout_thread = threading.Thread(
            target=_stream_output,
            args=(self.process.stdout, "SERVER", sys.stdout),
            daemon=True,
        )
        self.stderr_thread = threading.Thread(
            target=_stream_output,
            args=(self.process.stderr, "SERVER", sys.stderr),
            daemon=True,
        )

        self.stdout_thread.start()
        self.stderr_thread.start()

        # 等待服务器准备就绪
        max_retries = 30
        for _ in range(max_retries):
            try:
                import httpx

                response = httpx.get(f"{self.base_url}/health", timeout=1.0)
                if response.status_code == 200:
                    print(f"API 服务器已就绪：{self.base_url}")
                    return self
            except Exception:
                pass

            if self.process.poll() is not None:
                # 进程已经退出
                raise RuntimeError(
                    "服务器进程意外终止。请查看上方日志了解详情。"
                )

            time.sleep(1)

        raise RuntimeError(f"服务器在 {max_retries} 秒内未成功启动")

    def __exit__(self, exc_type, exc_val, exc_tb):
        """停止 API 服务器子进程。"""
        if self.process:
            print("正在停止 API 服务器…")
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                print("强制终止 API 服务器…")
                self.process.kill()
                self.process.wait()

            # 等待转发线程结束（它们是守护线程，会自动停止），
            # 但稍作等待以便刷新剩余输出
            time.sleep(0.5)
            print("API 服务器已停止。")


api_key = os.getenv("LITELLM_API_KEY")
assert api_key is not None, "未设置 LITELLM_API_KEY 环境变量。"

llm = LLM(
    service_id="main-llm",
    model="openai/qwen3-235b-a22b-instruct-2507",
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    api_key=SecretStr(api_key),
)

# 使用托管的 API 服务器
with ManagedAPIServer(port=8001) as server:
    # 创建 Agent
    agent = get_default_agent(
        llm=llm,
        working_dir=str(Path.cwd()),
        cli_mode=True,  # 为简洁起见禁用浏览器工具
    )

    # 定义回调以测试 WebSocket 功能
    received_events = []
    event_tracker = {"last_event_time": time.time()}

    def event_callback(event):
        """捕获事件以便测试。"""
        event_type = type(event).__name__
        logger.info(f"🔔 回调收到事件：{event_type}\n{event}")
        received_events.append(event)
        event_tracker["last_event_time"] = time.time()

    # 创建带回调的 RemoteConversation
    conversation = Conversation(
        agent=agent,
        host=server.base_url,
        callbacks=[event_callback],
        visualize=True,
    )
    assert isinstance(conversation, RemoteConversation)

    try:
        logger.info(f"\n📋 对话 ID：{conversation.state.id}")

        # 发送第一条消息并运行
        logger.info("📝 正在发送第一条消息…")
        conversation.send_message(
            "阅读当前仓库，并将关于该项目的 3 个事实写入 FACTS.txt。"
        )

        logger.info("🚀 正在运行对话…")
        conversation.run()

        logger.info("✅ 第一个任务完成！")
        logger.info(f"Agent 状态：{conversation.state.agent_status}")

        # 等待事件停止（2 秒内无事件）
        logger.info("⏳ 正在等待事件停止…")
        while time.time() - event_tracker["last_event_time"] < 2.0:
            time.sleep(0.1)
        logger.info("✅ 事件已停止")

        logger.info("🚀 再次运行对话…")
        conversation.send_message("太好了！现在删除那个文件。")
        conversation.run()
        logger.info("✅ 第二个任务完成！")

        # 演示 state.events 功能
        logger.info("\n" + "=" * 50)
        logger.info("📊 展示状态事件 API")
        logger.info("=" * 50)

        # 统计事件总数
        total_events = len(conversation.state.events)
        logger.info(f"📈 对话中的事件总数：{total_events}")

        # 获取最近 5 个事件
        logger.info("\n🔍 获取最近 5 个事件…")
        all_events = conversation.state.events
        recent_events = all_events[-5:] if len(all_events) >= 5 else all_events

        for i, event in enumerate(recent_events, 1):
            event_type = type(event).__name__
            timestamp = getattr(event, "timestamp", "Unknown")
            logger.info(f"  {i}. {event_type} at {timestamp}")

        # 查看事件类型
        logger.info("\n🔍 事件类型如下：")
        event_types = set()
        for event in recent_events:
            event_type = type(event).__name__
            event_types.add(event_type)
        for event_type in sorted(event_types):
            logger.info(f"  - {event_type}")

    finally:
        # 清理
        print("\n🧹 正在清理对话…")
        conversation.close()
