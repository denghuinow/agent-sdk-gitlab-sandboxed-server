import os
import subprocess
import time
import uuid
from urllib.parse import urlparse, urlunparse
from fastapi import FastAPI, HTTPException
from openhands.sdk.conversation.conversation import Conversation
from pydantic import SecretStr

from openhands.sdk import LLM, get_logger
from openhands.sdk.conversation.impl.remote_conversation import RemoteConversation
from openhands.sdk.preset.default import get_default_agent
from openhands.sdk.sandbox import DockerSandboxedAgentServer


"""
示例 24：在沙箱化的 Agent Server 中运行 GitLab 集成

本例演示如何：
  1) 构建并启动 OpenHands Agent Server 的 DEV（源码）Docker 镜像
  2) 创建一个 FastAPI 应用程序来处理 GitLab 相关操作
  3) 与沙箱化的服务器交互以执行 GitLab 任务

先决条件：
  - 已安装 Docker 与 docker buildx
  - shell 环境中已设置 LITELLM_API_KEY（供 Agent 使用）
  - GitLab 访问令牌已配置

说明：
  - 此示例展示了一个基本的 FastAPI 结构，用于 GitLab 集成
  - Agent 将在沙箱环境中执行 GitLab 操作
"""

logger = get_logger(__name__)

# 创建 FastAPI 应用
app = FastAPI(
    title="GitLab Integration Server",
    description="A server for handling GitLab operations with OpenHands agents",
    version="0.1.0"
)


@app.get("/createConversation")
async def create_conversation(message: str, git_repos: list[str], git_token: str) -> str:
    """创建一个新的对话"""
    # 1)创建会话对应的工作目录
    base_dir = os.environ.get(
        "HOST_WORKSPACE_DIR",
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
    )
    host_workspace = os.path.abspath(base_dir)
    workspace_id = uuid.uuid4()
    host_working_dir = os.path.join(host_workspace, "workspace", str(workspace_id))
    os.makedirs(host_working_dir, exist_ok=True)
    token = (git_token or "").strip()
    for idx, repo_url in enumerate(git_repos):
        repo_url = repo_url.strip()
        if not repo_url:
            continue
        repo_name = repo_url.rstrip("/").split("/")[-1] or f"repo_{idx}"
        if repo_name.endswith(".git"):
            repo_name = repo_name[:-4]
        dest_path = os.path.join(host_working_dir, repo_name)
        if os.path.exists(dest_path):
            logger.info(f"仓库已存在，跳过克隆：{repo_url}")
            continue
        clone_url = repo_url
        if token and token.lower() != "none":
            parsed = urlparse(repo_url)
            if parsed.scheme in {"http", "https"} and not parsed.username and parsed.hostname:
                port = f":{parsed.port}" if parsed.port else ""
                netloc = f"oauth2:{token}@{parsed.hostname}{port}"
                clone_url = urlunparse(parsed._replace(netloc=netloc))
        try:
            subprocess.run(
                ["git", "clone", "--depth", "1", clone_url, dest_path],
                check=True,
                cwd=host_working_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            detail = exc.stderr or str(exc)
            if token:
                detail = detail.replace(token, "***")
                detail = detail.replace(f"oauth2:{token}", "oauth2:***")
            raise HTTPException(
                status_code=400,
                detail=f"克隆仓库失败: {repo_url}\n{detail}",
            ) from exc
    
    
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
        # ghcr.io/all-hands-ai/agent-server:4864c6f-custom-dev
        base_image="ghcr.io/all-hands-ai/agent-server:4864c6f-custom-dev",
        mount_dir=host_working_dir,
        # host_port=8010,
        # TODO: 如果不是 linux/arm64，请换成你的平台
        # platform="linux/arm64",
    ) as server:
        # 3) 创建 Agent —— 关键：working_dir 必须是容器内挂载仓库的位置
        agent = get_default_agent(
            llm=llm,
            working_dir="/workspace",
            cli_mode=True,
        )
        agent = agent.model_copy(update={"mcp_config": {}, "security_analyzer": None})
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
        # TODO 避免阻塞线程
        conversation_id_str = str(conversation.state.id)
        try:
            logger.info(f"\n📋 对话 ID：{conversation.state.id}")
            logger.info("📝 正在发送消息…")
            conversation.send_message(message)
            logger.info("🚀 正在运行对话…")
            conversation.run()
            logger.info("✅ 任务完成！")
            logger.info(f"Agent 状态：{conversation.state.agent_status}")

            # 等待事件稳定（2 秒内无事件）
            logger.info("⏳ 正在等待事件停止…")
            while time.time() - last_event_time["ts"] < 2.0:
                time.sleep(0.1)
            logger.info("✅ 事件已停止")

        finally:
            print("\n🧹 正在清理对话…")
            conversation.close()
    return conversation_id_str
