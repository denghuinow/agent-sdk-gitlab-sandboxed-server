import os
import re
import subprocess
import time
import uuid
import json
from pathlib import Path
from urllib.parse import urlparse, urlunparse
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from openhands.sdk.conversation.conversation import Conversation
from pydantic import BaseModel, SecretStr

from openhands.sdk import LLM, get_logger
from openhands.sdk.conversation.impl.remote_conversation import RemoteConversation
from openhands.tools.preset.default import get_default_agent
from openhands.sdk.sandbox.docker import DockerSandboxedAgentServer, _run, build_agent_server_image


"""
示例 25：GitLab 工作空间沙箱服务器（优化版）

本例演示如何：
  1) 构建并启动 OpenHands Agent Server 的沙箱环境
  2) 创建一个 FastAPI 应用来处理 GitLab 相关操作
  3) 与沙箱化的服务器交互以执行 GitLab 任务
  4) 通过简单的目录结构管理会话持久化
"""

logger = get_logger(__name__)

WORKSPACE_SUBDIR = "workspace"
MAPPING_FILE = "conversation_mapping.json"
_EVENT_FILE_PATTERN = re.compile(r"^event-(\d+)-([^.]+)\.json$")


class ConversationRequest(BaseModel):
    message: str
    git_repos: list[str] | None = None
    git_token: str | None = None
    workspace_id: str | None = None
    conversation_id: str | None = None


class ConversationResponse(BaseModel):
    conversation_id: str
    workspace_id: str


def _validate_workspace_id(workspace_id: str) -> str:
    """验证并清理工作空间 ID，确保目录命名规范。"""
    if not workspace_id or not workspace_id.strip():
        raise HTTPException(status_code=400, detail="工作空间 ID 不能为空")

    # 只保留字母数字和下划线，避免路径遍历攻击
    clean_id = re.sub(r'[^a-zA-Z0-9_]', '', workspace_id.strip())
    if not clean_id:
        raise HTTPException(status_code=400, detail="工作空间 ID 包含无效字符")

    return clean_id


def _validate_conversation_id(conversation_id: str) -> str:
    """验证会话 ID，防止路径遍历。"""
    if not conversation_id or not conversation_id.strip():
        raise HTTPException(status_code=400, detail="会话 ID 不能为空")

    clean_id = conversation_id.strip()
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", clean_id):
        raise HTTPException(status_code=400, detail="会话 ID 包含无效字符")

    return clean_id


def _get_workspace_root() -> str:
    """获取工作空间根目录，确保目录存在。"""
    base_dir = os.environ.get("HOST_WORKSPACE_DIR", os.path.dirname(__file__))
    workspace_root = os.path.join(base_dir, WORKSPACE_SUBDIR)
    os.makedirs(workspace_root, exist_ok=True)
    return workspace_root


def _safe_load_mapping(mapping_file: str) -> dict:
    """安全加载会话映射文件。"""
    if not os.path.exists(mapping_file):
        return {}
    
    try:
        with open(mapping_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            # 验证数据格式
            if not isinstance(data, dict):
                raise ValueError("映射文件格式错误：应为字典类型")
            return data
    except (json.JSONDecodeError, ValueError) as e:
        logger.error("映射文件格式错误: %s", e)
        raise HTTPException(status_code=500, detail="映射文件格式错误") from e
    except OSError as e:
        logger.error("读取映射文件失败: %s", e)
        raise HTTPException(status_code=500, detail="读取映射失败") from e


def _safe_save_mapping(mapping_file: str, mapping: dict) -> None:
    """安全保存会话映射文件。"""
    try:
        with open(mapping_file, "w", encoding="utf-8") as f:
            json.dump(mapping, f, ensure_ascii=False, indent=2)
    except OSError as e:
        logger.error("保存映射文件失败: %s", e)
        raise HTTPException(status_code=500, detail="保存映射失败") from e


def _event_file_sort_key(path: Path) -> tuple[int, str]:
    match = _EVENT_FILE_PATTERN.match(path.name)
    if match:
        return int(match.group(1)), match.group(2)
    return 10**12, path.name


def _load_events_from_directory(events_dir: Path) -> list[dict]:
    event_files = sorted(events_dir.glob("event-*-*.json"), key=_event_file_sort_key)
    events: list[dict] = []
    for event_file in event_files:
        try:
            with event_file.open("r", encoding="utf-8") as f:
                events.append(json.load(f))
        except json.JSONDecodeError as exc:
            logger.error("事件文件格式错误: %s", event_file)
            raise HTTPException(status_code=500, detail=f"事件文件格式错误: {event_file.name}") from exc
        except OSError as exc:
            logger.error("读取事件文件失败: %s", event_file)
            raise HTTPException(status_code=500, detail="读取事件文件失败") from exc
    return events


def _clone_repos_safe(project_dir: str, git_repos: list[str], git_token: str = None) -> None:
    """安全地克隆 Git 仓库到项目目录。"""
    if not git_repos:
        return

    token = git_token.strip() if git_token else ""
    
    for repo_url in git_repos:
        repo_url = repo_url.strip()
        if not repo_url:
            continue

        # 提取仓库名，防止路径注入
        repo_name = os.path.basename(repo_url.rstrip('/')).replace('.git', '')
        if not repo_name:
            continue
            
        # 验证仓库名的安全性
        import re
        if not re.match(r'^[a-zA-Z0-9_-]+$', repo_name):
            logger.warning("跳过不安全的仓库名: %s", repo_name)
            continue

        dest_path = os.path.join(project_dir, repo_name)
        if os.path.exists(dest_path):
            logger.info("仓库已存在，跳过: %s", repo_url)
            continue

        # 处理认证
        clone_url = repo_url
        if token and token.lower() != "none":
            parsed = urlparse(repo_url)
            if parsed.scheme in {"http", "https"} and not parsed.username:
                clone_url = urlunparse(parsed._replace(
                    netloc=f"oauth2:{token}@{parsed.netloc}"
                ))

        try:
            result = subprocess.run([
                "git", "clone", "--depth", "1", clone_url, dest_path
            ], check=True, capture_output=True, text=True, timeout=300)
            logger.info("成功克隆仓库: %s", repo_url)
        except subprocess.TimeoutExpired:
            raise HTTPException(status_code=408, detail=f"克隆超时: {repo_url}")
        except subprocess.CalledProcessError as e:
            error_msg = e.stderr
            if token:
                error_msg = error_msg.replace(token, "***")
            raise HTTPException(
                status_code=400, 
                detail=f"克隆失败: {repo_url}\n{error_msg}"
            ) from e


def _create_sandbox_with_persistence(mount_dir: str):
    """创建带有持久化挂载的沙箱服务器。"""
    class PersistentSandbox(DockerSandboxedAgentServer):
        def __init__(self, mount_dir: str):
            super().__init__(
                base_image="nikolaik/python-nodejs:python3.12-nodejs22",
                mount_dir=mount_dir,
                host_port=0,  # 自动分配端口
            )
            self._mount_dir = mount_dir

        def __enter__(self):
            # 验证 Docker
            if _run(["docker", "version"]).returncode != 0:
                raise RuntimeError("Docker 未运行，请启动 Docker 服务")

            # 构建镜像（如果需要）
            if self._image and "ghcr.io/all-hands-ai/agent-server" not in self._image:
                self._image = build_agent_server_image(
                    base_image=self._image,
                    target=self._target,
                    platforms=self._platform,
                )

            # 准备 Docker 运行参数
            flags = ["-v", f"{self._mount_dir}:/workspace"]
            
            # 添加环境变量
            for key in self._forward_env:
                if key in os.environ:
                    flags.extend(["-e", f"{key}={os.environ[key]}"])

            # 运行容器
            run_cmd = [
                "docker", "run", "--user", "0:0", "-d", "--platform", self._platform,
                "--rm", "--name", f"agent-server-{int(time.time())}-{uuid.uuid4().hex[:8]}",
                "-p", f"{self.host_port}:8000", *flags, self._image,
                "--host", "0.0.0.0", "--port", "8000"
            ]
            
            proc = _run(run_cmd)
            if proc.returncode != 0:
                raise RuntimeError(f"启动容器失败: {proc.stderr}")

            self.container_id = proc.stdout.strip()
            logger.info("启动容器: %s", self.container_id)

            # 启动日志线程
            if self.detach_logs:
                from threading import Thread
                self._logs_thread = Thread(target=self._stream_docker_logs, daemon=True)
                self._logs_thread.start()

            self._wait_for_health()
            logger.info("API 服务器就绪: %s", self.base_url)
            return self

    return PersistentSandbox(mount_dir)


# 创建 FastAPI 应用
app = FastAPI(
    title="GitLab Integration Server",
    description="A server for handling GitLab operations with OpenHands agents (with persistence)",
    version="0.1.0"
)


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

    host_workspace = _get_workspace_root()
    workspace_root = os.path.join(host_workspace, WORKSPACE_SUBDIR)
    conversation_mapping_file = os.path.join(
        workspace_root, MAPPING_FILE
    )
    conversation_mapping = _safe_load_mapping(conversation_mapping_file)

    is_resume = bool(request.conversation_id)
    workspace_id = request.workspace_id
    if workspace_id:
        workspace_id = _validate_workspace_id(workspace_id)
    conversation_id = request.conversation_id

    if is_resume:
        if conversation_id not in conversation_mapping:
            raise HTTPException(
                status_code=404,
                detail=f"未找到对话ID的映射: {conversation_id}",
            )
        mapped_workspace_id = _validate_workspace_id(conversation_mapping[conversation_id])
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
            workspace_id = uuid.uuid4().hex
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
        _clone_repos_safe(project_dir, request.git_repos or [], request.git_token)

    conversation_id_str: str | None = None
    with _create_sandbox_with_persistence(workspace_dir) as server:
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
        _safe_save_mapping(conversation_mapping_file, conversation_mapping)

    assert conversation_id_str is not None
    return ConversationResponse(
        conversation_id=conversation_id_str,
        workspace_id=workspace_id,
    )


@app.get("/workspace/{workspace_id}/conversations/{conversation_id}/events")
async def get_conversation_events(workspace_id: str, conversation_id: str) -> dict:
    """获取指定会话的所有事件。"""

    normalized_workspace_id = _validate_workspace_id(workspace_id)
    normalized_conversation_id = _validate_conversation_id(conversation_id)

    host_workspace = _get_workspace_root()
    workspace_dir = Path(host_workspace) / WORKSPACE_SUBDIR / normalized_workspace_id
    if not workspace_dir.exists() or not workspace_dir.is_dir():
        raise HTTPException(status_code=404, detail="工作空间不存在")

    conversation_dir = workspace_dir / "conversations" / normalized_conversation_id
    if not conversation_dir.exists() or not conversation_dir.is_dir():
        raise HTTPException(status_code=404, detail="会话不存在")

    events_dir = conversation_dir / "event_service" / "events"
    if not events_dir.exists() or not events_dir.is_dir():
        raise HTTPException(status_code=404, detail="未找到事件目录")

    events = _load_events_from_directory(events_dir)

    return {
        "workspace_id": normalized_workspace_id,
        "conversation_id": normalized_conversation_id,
        "event_count": len(events),
        "events": events,
    }


@app.get("/workspace/{workspace_id}/conversations/{conversation_id}/state")
async def get_conversation_state(workspace_id: str, conversation_id: str) -> dict:
    """获取指定会话的基础状态。"""

    normalized_workspace_id = _validate_workspace_id(workspace_id)
    normalized_conversation_id = _validate_conversation_id(conversation_id)

    host_workspace = _get_workspace_root()
    workspace_dir = Path(host_workspace) / WORKSPACE_SUBDIR / normalized_workspace_id
    if not workspace_dir.exists() or not workspace_dir.is_dir():
        raise HTTPException(status_code=404, detail="工作空间不存在")

    conversation_dir = workspace_dir / "conversations" / normalized_conversation_id
    if not conversation_dir.exists() or not conversation_dir.is_dir():
        raise HTTPException(status_code=404, detail="会话不存在")

    state_file = conversation_dir / "event_service" / "base_state.json"
    if not state_file.exists() or not state_file.is_file():
        raise HTTPException(status_code=404, detail="未找到状态文件")

    try:
        with state_file.open("r", encoding="utf-8") as f:
            state_data = json.load(f)
    except json.JSONDecodeError as exc:
        logger.error("状态文件格式错误: %s", state_file)
        raise HTTPException(status_code=500, detail="状态文件格式错误") from exc
    except OSError as exc:
        logger.error("读取状态文件失败: %s", state_file)
        raise HTTPException(status_code=500, detail="读取状态文件失败") from exc

    return {
        "workspace_id": normalized_workspace_id,
        "conversation_id": normalized_conversation_id,
        "state": state_data,
    }


@app.get("/workspace/{workspace_id}/project/file")
async def download_project_file(workspace_id: str, file_path: str) -> FileResponse:
    """下载指定工作空间 project 目录中的文件。"""

    normalized_workspace_id = _validate_workspace_id(workspace_id)
    relative_path = file_path.strip()
    if not relative_path:
        raise HTTPException(status_code=400, detail="文件路径不能为空")

    host_workspace = _get_workspace_root()
    workspace_dir = Path(host_workspace) / WORKSPACE_SUBDIR / normalized_workspace_id
    project_dir = workspace_dir / "project"

    if not workspace_dir.exists():
        raise HTTPException(status_code=404, detail="工作空间不存在")
    if not project_dir.exists():
        raise HTTPException(status_code=404, detail="project 目录不存在")

    try:
        project_dir_resolved = project_dir.resolve(strict=True)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="project 目录不存在") from exc

    requested_path = (project_dir / relative_path).resolve(strict=False)
    try:
        requested_path.relative_to(project_dir_resolved)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="文件路径越界") from exc

    if not requested_path.exists() or not requested_path.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")

    return FileResponse(path=requested_path, filename=requested_path.name)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
