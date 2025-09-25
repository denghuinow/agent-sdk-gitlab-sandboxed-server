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
from pydantic import SecretStr

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
            # "--rm",  # 注意：我们仍然使用 --rm，但数据通过挂载卷持久化
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
    host_working_dir = os.path.join(
        host_workspace, "workspace", str(workspace_id))
    os.makedirs(host_working_dir, exist_ok=True)
    
    # 保存对话ID到工作目录的映射
    conversation_mapping_file = os.path.join(host_workspace, "conversation_mapping.json")
    conversation_id_str = None
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
        model="openai/Qwen3-Next-80B-A3B-Instruct-FP8",
        base_url="https://oneapi.wchat.cc/v1",
        api_key=SecretStr(api_key),
    )

    # 2) 为持久化创建宿主机目录
    host_workspace = os.path.abspath(base_dir)
    host_agent_workspace = os.path.join(
        host_workspace, ".conversations")
    os.makedirs(host_agent_workspace, exist_ok=True)

    # 3) 使用相同的持久化目录启动容器
    with PersistentDockerSandboxedAgentServer(
        base_image="ghcr.io/all-hands-ai/agent-server:4864c6f-custom-dev",
        mount_dir=host_working_dir,
        persistent_dirs={
            "/agent-server/workspace/conversations": host_agent_workspace,       # 持久化Agent工作区数据
        },
    ) as server:
        # 4) 创建 Agent —— 关键：working_dir 必须是容器内挂载仓库的位置
        agent = get_default_agent(
            llm=llm,
            working_dir="/workspace",
            cli_mode=True,
        )
        agent = agent.model_copy(
            update={"mcp_config": {}, "security_analyzer": None})
        # 5) 与示例 22 相同，设置回调以收集事件
        received_events: list = []
        last_event_time = {"ts": time.time()}

        def event_callback(event) -> None:
            event_type = type(event).__name__
            logger.info(f"🔔 回调收到事件：{event_type}\n{event}")
            received_events.append(event)
            last_event_time["ts"] = time.time()

        # 6) 创建 RemoteConversation 并执行相同的两步任务
        conversation = Conversation(
            agent=agent,
            host=server.base_url,
            callbacks=[event_callback],
            # visualize=True,
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
    
    # 保存对话ID到工作目录的映射
    try:
        # 读取现有映射
        if os.path.exists(conversation_mapping_file):
            with open(conversation_mapping_file, 'r', encoding='utf-8') as f:
                mapping = json.load(f)
        else:
            mapping = {}
        
        # 添加新的映射
        mapping[conversation_id_str] = str(workspace_id)
        
        # 保存映射
        with open(conversation_mapping_file, 'w', encoding='utf-8') as f:
            json.dump(mapping, f, ensure_ascii=False, indent=2)
        
        logger.info(f"已保存对话映射: {conversation_id_str} -> {workspace_id}")
    except Exception as e:
        logger.error(f"保存对话映射失败: {e}")
    
    return conversation_id_str


@app.get("/resumeConversation")
async def resume_conversation(conversation_id: str, message: str) -> str:
    """恢复一个已有的对话"""
    # 1) 确保我们拥有 LLM API Key
    api_key = os.getenv("LITELLM_API_KEY")
    assert api_key is not None, "未设置 LITELLM_API_KEY 环境变量。"

    llm = LLM(
        service_id="main-llm",
        model="openai/Qwen3-Next-80B-A3B-Instruct-FP8",
        base_url="https://oneapi.wchat.cc/v1",
        api_key=SecretStr(api_key),
    )
    
    # 获取会话对应的工作目录
    base_dir = os.environ.get(
        "HOST_WORKSPACE_DIR",
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
    )
    host_workspace = os.path.abspath(base_dir)
    conversation_mapping_file = os.path.join(host_workspace, "conversation_mapping.json")
    
    try:
        # 读取对话映射
        if os.path.exists(conversation_mapping_file):
            with open(conversation_mapping_file, 'r', encoding='utf-8') as f:
                mapping = json.load(f)
            
            if conversation_id in mapping:
                workspace_id = mapping[conversation_id]
                host_working_dir = os.path.join(host_workspace, "workspace", workspace_id)
                
                # 检查工作目录是否存在
                if not os.path.exists(host_working_dir):
                    raise HTTPException(
                        status_code=404,
                        detail=f"工作目录不存在: {host_working_dir}"
                    )
                
                logger.info(f"找到对话映射: {conversation_id} -> {workspace_id}")
            else:
                raise HTTPException(
                    status_code=404,
                    detail=f"未找到对话ID的映射: {conversation_id}"
                )
        else:
            raise HTTPException(
                status_code=404,
                detail=f"对话映射文件不存在: {conversation_mapping_file}"
            )
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=500,
            detail="对话映射文件格式错误"
        )
    except Exception as e:
        logger.error(f"获取对话映射失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"获取对话映射失败: {str(e)}"
        )
    
    # 2) 为持久化创建宿主机目录
    host_agent_workspace = os.path.join(host_workspace, ".conversations")
    os.makedirs(host_agent_workspace, exist_ok=True)

    # 3) 使用相同的持久化目录启动容器
    with PersistentDockerSandboxedAgentServer(
        base_image="ghcr.io/all-hands-ai/agent-server:4864c6f-custom-dev",
        mount_dir=host_working_dir,
        persistent_dirs={
            "/agent-server/workspace/conversations": host_agent_workspace,       # 持久化Agent工作区数据
        },
    ) as server:
        # 4) 创建 Agent
        agent = get_default_agent(
            llm=llm,
            working_dir="/workspace",
            cli_mode=True,
        )
        agent = agent.model_copy(
            update={"mcp_config": {}, "security_analyzer": None})

        # 5) 设置回调
        received_events: list = []
        last_event_time = {"ts": time.time()}

        def event_callback(event) -> None:
            event_type = type(event).__name__
            logger.info(f"🔔 回调收到事件：{event_type}\n{event}")
            received_events.append(event)
            last_event_time["ts"] = time.time()

        # 6) 恢复远程对话
        conversation = Conversation(
            agent=agent,
            host=server.base_url,
            callbacks=[event_callback],
            # visualize=True,
            conversation_id=conversation_id  # 指定要恢复的对话ID
        )
        assert isinstance(conversation, RemoteConversation)

        try:
            logger.info(f"\n📋 恢复对话 ID：{conversation.state.id}")
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
    return conversation_id


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
