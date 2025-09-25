import os
import time

from pydantic import SecretStr

from openhands.sdk import (
    LLM,
    Conversation,
    get_logger,
)
from openhands.sdk.conversation.impl.remote_conversation import RemoteConversation
from openhands.sdk.preset.default import get_default_agent
from openhands.sdk.sandbox import DockerSandboxedAgentServer


"""
示例 23：在沙箱化的 Agent Server（Docker）中运行 Hello World

本例演示如何：
  1) 构建并启动 OpenHands Agent Server 的 DEV（源码）Docker 镜像
  2) 自动获取镜像名称
  3) 启动 Docker 容器
  4) 连接到容器内的服务器并与之交互
  5) 运行与示例 22 相同的对话流程

先决条件：
  - 已安装 Docker 与 docker buildx
  - shell 环境中已设置 LITELLM_API_KEY（供 Agent 使用）

说明：
  - 我们将当前仓库挂载到容器内的 /workspace，使 Agent 的操作影响本地文件，
    这与示例 22 的行为一致。
  - dev 镜像目标会在容器内使用虚拟环境直接运行源码，便于快速迭代。
"""

logger = get_logger(__name__)


def main() -> None:
    # 1) 确保我们拥有 LLM API Key
    api_key = os.getenv("LITELLM_API_KEY")
    assert api_key is not None, "未设置 LITELLM_API_KEY 环境变量。"

    llm = LLM(
        service_id="main-llm",
        model="openai/qwen3-235b-a22b-instruct-2507",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key=SecretStr(api_key),
    )

    # 2) 通过 SDK 帮助器在 Docker 中启动 dev 镜像并等待健康检查
    #    将 LITELLM_API_KEY 转发进容器，方便远程工具使用。
    with DockerSandboxedAgentServer(
        base_image="nikolaik/python-nodejs:python3.12-nodejs22",
        host_port=8010,
        # TODO: 如果不是 linux/arm64，请换成你的平台
        # platform="linux/arm64",
    ) as server:
        # 3) 创建 Agent —— 关键：working_dir 必须是容器内挂载仓库的位置
        agent = get_default_agent(
            llm=llm,
            working_dir="/",
            cli_mode=True,
        )
        agent = agent.model_copy(update={"mcp_config": {}})
        # 4) 与示例 22 相同，设置回调以收集事件
        received_events: list = []
        last_event_time = {"ts": time.time()}

        def event_callback(event) -> None:
            event_type = type(event).__name__
            logger.info(f"🔔 回调收到事件：{event_type}\n{event}")
            received_events.append(event)
            last_event_time["ts"] = time.time()

        # 5) 创建 RemoteConversation 并执行相同的两步任务
        conversation = Conversation(
            agent=agent,
            host=server.base_url,
            callbacks=[event_callback],
            visualize=True,
        )
        assert isinstance(conversation, RemoteConversation)

        try:
            logger.info(f"\n📋 对话 ID：{conversation.state.id}")
            logger.info("📝 正在发送第一条消息…")
            conversation.send_message(
                "阅读当前仓库，并将关于该项目的 3 个事实写入 FACTS.txt。"
            )
            logger.info("🚀 正在运行对话…")
            conversation.run()
            logger.info("✅ 第一个任务完成！")
            logger.info(f"Agent 状态：{conversation.state.agent_status}")

            # 等待事件稳定（2 秒内无事件）
            logger.info("⏳ 正在等待事件停止…")
            while time.time() - last_event_time["ts"] < 2.0:
                time.sleep(0.1)
            logger.info("✅ 事件已停止")

            logger.info("🚀 再次运行对话…")
            conversation.send_message("太好了！现在删除那个文件。")
            conversation.run()
            logger.info("✅ 第二个任务完成！")
        finally:
            print("\n🧹 正在清理对话…")
            conversation.close()


if __name__ == "__main__":
    main()
