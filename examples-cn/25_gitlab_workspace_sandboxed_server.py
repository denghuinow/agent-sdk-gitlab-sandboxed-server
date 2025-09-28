import os
import subprocess
import time
import uuid
import json
from collections.abc import Iterable
from pathlib import Path
from urllib.parse import urlparse, urlunparse
from urllib.request import urlopen
from fastapi import FastAPI, HTTPException
from openhands.sdk.conversation.conversation import Conversation
from pydantic import BaseModel, SecretStr

from openhands.sdk import LLM, get_logger
from openhands.sdk.conversation.impl.remote_conversation import RemoteConversation
from openhands.sdk.preset.default import get_default_agent
from openhands.sdk.sandbox import DockerSandboxedAgentServer
from openhands.sdk.sandbox.docker import _run, find_available_tcp_port, build_agent_server_image


"""
示例 24：在沙箱化的 Agent Server 中运行 GitLab 集成（支持会话状态持久化）

本例演示如何：
  1) 构建并启动 OpenHands Agent Server 的 DEV（源码）Docker 镜像
  2) 创建一个 FastAPI 应用程序来处理 GitLab 相关操作
  3) 与沙箱化的服务器交互以执行 GitLab 任务
  4) 将会话状态持久化到宿主机文件系统，即使重新创建容器也能保留对话状态

注意：这是扩展版本，通过继承 DockerSandboxedAgentServer 实现持久化，
而不需要修改 SDK 核心代码。
"""

logger = get_logger(__name__)

WORKSPACE_SUBDIR = "workspace"
CONVERSATION_MAPPING_FILE = "conversation_mapping.json"


class ConversationRequest(BaseModel):
    message: str
    git_repos: list[str] | None = None
    git_token: str | None = None
    workspace_id: str | None = None
    conversation_id: str | None = None


class ConversationResponse(BaseModel):
    conversation_id: str
    workspace_id: str


def _get_host_workspace_base() -> str:
    base_dir = os.environ.get(
        "HOST_WORKSPACE_DIR",
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
    )
    host_workspace = os.path.abspath(base_dir)
    workspace_root = os.path.join(host_workspace, WORKSPACE_SUBDIR)
    os.makedirs(workspace_root, exist_ok=True)
    return host_workspace


def _load_conversation_mapping(file_path: str) -> dict[str, str]:
    if not os.path.exists(file_path):
        return {}
    try:
        with open(file_path, "r", encoding="utf-8") as file:
            return json.load(file)
    except json.JSONDecodeError as exc:
        logger.error("对话映射文件格式错误: %s", exc)
        raise HTTPException(status_code=500, detail="对话映射文件格式错误") from exc
    except OSError as exc:
        logger.error("读取对话映射失败: %s", exc)
        raise HTTPException(status_code=500, detail="读取对话映射失败") from exc


def _save_conversation_mapping(file_path: str, mapping: dict[str, str]) -> None:
    try:
        with open(file_path, "w", encoding="utf-8") as file:
            json.dump(mapping, file, ensure_ascii=False, indent=2)
    except OSError as exc:
        logger.error("保存对话映射失败: %s", exc)
        raise HTTPException(status_code=500, detail="保存对话映射失败") from exc


def _prepare_git_repos(host_dir: str, git_repos: list[str] | None, git_token: str | None) -> None:
    if not git_repos:
        return

    token = (git_token or "").strip()
    for idx, repo_url in enumerate(git_repos):
        repo_url = repo_url.strip()
        if not repo_url:
            continue

        repo_name = repo_url.rstrip("/").split("/")[-1] or f"repo_{idx}"
        if repo_name.endswith(".git"):
            repo_name = repo_name[:-4]

        dest_path = os.path.join(host_dir, repo_name)
        if os.path.exists(dest_path):
            logger.info("仓库已存在，跳过克隆：%s", repo_url)
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
                cwd=host_dir,
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

# 创建 FastAPI 应用
app = FastAPI(
    title="GitLab Integration Server",
    description="A server for handling GitLab operations with OpenHands agents (with persistence)",
    version="0.1.0"
)


class PersistentDockerSandboxedAgentServer(DockerSandboxedAgentServer):
    """
    扩展 DockerSandboxedAgentServer 以支持持久化目录挂载
    """

    def __init__(
        self,
        *,
        base_image: str,
        host_port: int | None = None,
        host: str = "127.0.0.1",
        forward_env: Iterable[str] | None = None,
        mount_dir: str | None = None,
        detach_logs: bool = True,
        target: str = "source",
        platform: str = "linux/amd64",
        persistent_dirs: dict[str, str] | None = None,  # 新增：持久化目录映射
    ) -> None:
        super().__init__(
            base_image=base_image,
            host_port=host_port,
            host=host,
            forward_env=forward_env,
            mount_dir=mount_dir,
            detach_logs=detach_logs,
            target=target,
            platform=platform,
        )
        # 持久化目录映射：容器路径 -> 宿主机路径
        self.persistent_dirs = persistent_dirs or {}

    def __enter__(self) -> 'PersistentDockerSandboxedAgentServer':
        # 确保 docker 存在
        docker_ver = _run(["docker", "version"]).returncode
        if docker_ver != 0:
            raise RuntimeError(
                "Docker is not available. Please install and start "
                "Docker Desktop/daemon."
            )

        # 构建镜像（如果需要）
        if self._image and "ghcr.io/all-hands-ai/agent-server" not in self._image:
            self._image = build_agent_server_image(
                base_image=self._image,
                target=self._target,
                # 我们只支持单平台
                platforms=self._platform,
            )

        # 准备环境标志
        flags: list[str] = []
        for key in self._forward_env:
            if key in os.environ:
                flags += ["-e", f"{key}={os.environ[key]}"]

        # 准备挂载标志 - 包括工作目录和持久化目录
        if self.mount_dir:
            mount_path = "/workspace"
            flags += ["-v", f"{self.mount_dir}:{mount_path}"]
            logger.info(
                "挂载宿主机目录 %s 到容器路径 %s", self.mount_dir, mount_path
            )

        # 添加持久化目录挂载
        for container_path, host_path in self.persistent_dirs.items():
            os.makedirs(host_path, exist_ok=True)  # 确保宿主机目录存在
            flags += ["-v", f"{host_path}:{container_path}"]
            logger.info(
                "持久化挂载宿主机目录 %s 到容器路径 %s", host_path, container_path
            )

        # 运行容器
        run_cmd = [
            "docker",
            "run",
            "--user", "0:0",
            "-d",
            "--platform",
            self._platform,
            "--rm",
            "--name",
            f"agent-server-{int(time.time())}",
            "-p",
            f"{self.host_port}:8000",
            *flags,
            self._image,
            "--host",
            "0.0.0.0",
            "--port",
            "8000",
        ]
        proc = _run(run_cmd)
        if proc.returncode != 0:
            raise RuntimeError(
                f"Failed to run docker container: {proc.stderr}")

        self.container_id = proc.stdout.strip()
        logger.info("Started container: %s", self.container_id)

        # 可选地在后台流式传输日志
        if self.detach_logs:
            from threading import Thread, Event
            self._logs_thread = Thread(
                target=self._stream_docker_logs, daemon=True
            )
            self._logs_thread.start()

        # 等待健康检查
        self._wait_for_health()
        logger.info("API server is ready at %s", self.base_url)
        return self


@app.post("/conversation", response_model=ConversationResponse)
async def handle_conversation(request: ConversationRequest) -> ConversationResponse:
    """创建或恢复对话。"""

    api_key = os.getenv("LITELLM_API_KEY")
    assert api_key is not None, "未设置 LITELLM_API_KEY 环境变量。"

    llm = LLM(
        service_id="main-llm",
        model="openai/qwen3-next-80b-a3b-instruct",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key=SecretStr(api_key),
    )

    host_workspace = _get_host_workspace_base()
    workspace_root = os.path.join(host_workspace, WORKSPACE_SUBDIR)
    conversation_mapping_file = os.path.join(
        workspace_root, CONVERSATION_MAPPING_FILE
    )
    conversation_mapping = _load_conversation_mapping(conversation_mapping_file)

    is_resume = bool(request.conversation_id)
    workspace_id = request.workspace_id
    conversation_id = request.conversation_id

    if is_resume:
        if conversation_id not in conversation_mapping:
            raise HTTPException(
                status_code=404,
                detail=f"未找到对话ID的映射: {conversation_id}",
            )
        mapped_workspace_id = conversation_mapping[conversation_id]
        if workspace_id and workspace_id != mapped_workspace_id:
            raise HTTPException(
                status_code=400,
                detail=(
                    "传入的 workspace_id 与会话映射不一致: "
                    f"{workspace_id} ≠ {mapped_workspace_id}"
                ),
            )
        workspace_id = mapped_workspace_id
    else:
        if workspace_id:
            logger.info("使用已有工作空间: %s", workspace_id)
        else:
            workspace_id = str(uuid.uuid4())
            logger.info("创建新的工作空间: %s", workspace_id)

    workspace_dir = os.path.join(workspace_root, workspace_id)
    if is_resume:
        if not os.path.exists(workspace_dir):
            raise HTTPException(
                status_code=404,
                detail=f"工作目录不存在: {workspace_dir}",
            )
    else:
        if request.workspace_id:
            if not os.path.exists(workspace_dir):
                raise HTTPException(
                    status_code=404,
                    detail=f"工作目录不存在: {workspace_dir}",
                )
        else:
            os.makedirs(workspace_dir, exist_ok=True)
    project_dir = os.path.join(workspace_dir, "project")
    os.makedirs(project_dir, exist_ok=True)
    if not is_resume:
        _prepare_git_repos(project_dir, request.git_repos, request.git_token)

    conversation_id_str: str | None = None
    with PersistentDockerSandboxedAgentServer(
        base_image="nikolaik/python-nodejs:python3.12-nodejs22",
        mount_dir=workspace_dir,
    ) as server:
        agent = get_default_agent(
            llm=llm,
            working_dir="/workspace/project",
            cli_mode=True,
        )
        agent = agent.model_copy(
            update={"mcp_config": {}, "security_analyzer": None, "condenser": None}
        )

        received_events: list = []
        last_event_time = {"ts": time.time()}

        def event_callback(event) -> None:
            event_type = type(event).__name__
            logger.info("🔔 回调收到事件：%s\n%s", event_type, event)
            received_events.append(event)
            last_event_time["ts"] = time.time()

        conversation_kwargs = dict(
            agent=agent,
            host=server.base_url,
            callbacks=[event_callback],
            visualize=True,
        )
        if is_resume and conversation_id:
            conversation_kwargs["conversation_id"] = conversation_id

        conversation = Conversation(**conversation_kwargs)
        assert isinstance(conversation, RemoteConversation)
        conversation_id_str = str(conversation.state.id)

        try:
            logger.info("\n📋 对话 ID：%s", conversation.state.id)
            logger.info("📝 正在发送消息…")
            conversation.send_message(request.message)
            logger.info("🚀 正在运行对话…")
            conversation.run()
            logger.info("✅ 任务完成！")
            logger.info("Agent 状态：%s", conversation.state.agent_status)

            logger.info("⏳ 正在等待事件停止…")
            while time.time() - last_event_time["ts"] < 2.0:
                time.sleep(0.1)
            logger.info("✅ 事件已停止")

        finally:
            print("\n🧹 正在清理对话…")
            conversation.close()

    if not is_resume and conversation_id_str:
        conversation_mapping[conversation_id_str] = workspace_id
        _save_conversation_mapping(conversation_mapping_file, conversation_mapping)

    assert conversation_id_str is not None
    return ConversationResponse(
        conversation_id=conversation_id_str,
        workspace_id=workspace_id,
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
