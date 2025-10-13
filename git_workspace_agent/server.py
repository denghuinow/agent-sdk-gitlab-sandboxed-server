import asyncio
import json
import os
import re
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import urlencode, urlparse, urlunparse

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from openhands.sdk.conversation.conversation import Conversation
from pydantic import BaseModel, SecretStr

from openhands.sdk import LLM, get_logger
from openhands.sdk.conversation.impl.remote_conversation import RemoteConversation
from openhands.tools.preset.default import get_default_agent
from openhands.sdk.sandbox.docker import DockerSandboxedAgentServer, _run, build_agent_server_image


"""
Git工作区智能体服务器
------------------------------------
该模块实现了一个基于 FastAPI 的服务器，集成了 OpenHands Agent Server，并提供了与 Git 仓库交互的功能。主要功能包括：

  1) 构建并启动 OpenHands Agent Server 的沙箱环境
  2) 创建一个 FastAPI 应用来处理 Git 仓库操作
 3) 与沙箱化的服务器交互以执行 Git 任务
  4) 通过简单的目录结构管理会话持久化
"""

logger = get_logger(__name__)

WORKSPACE_SUBDIR = "workspace"
MAPPING_FILE = "conversation_mapping.json"
_EVENT_FILE_PATTERN = re.compile(r"^event-(\d+)-([^.]+)\.json$")
FRONTEND_DIR = Path(__file__).with_name("frontend")
FRONTEND_INDEX = FRONTEND_DIR / "index.html"

SANDBOX_IDLE_TTL = float(os.environ.get("SANDBOX_IDLE_TTL", "1800"))
SANDBOX_CLEANUP_INTERVAL = float(os.environ.get("SANDBOX_CLEANUP_INTERVAL", "300"))


@dataclass
class SandboxEntry:
    sandbox: DockerSandboxedAgentServer
    workspace_dir: str
    last_access: float
    vscode_info: dict[str, Any] | None = None


_SANDBOX_REGISTRY: dict[str, SandboxEntry] = {}
_VSCODE_INFO: dict[str, dict[str, Any]] = {}
_REGISTRY_LOCK = threading.RLock()
_CLEANUP_TASK: asyncio.Task | None = None


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
                base_image="ghcr.io/all-hands-ai/agent-server:latest-python",
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


def _get_sandbox_entry(workspace_id: str) -> SandboxEntry | None:
    with _REGISTRY_LOCK:
        return _SANDBOX_REGISTRY.get(workspace_id)


def _touch_workspace(workspace_id: str) -> float | None:
    now = time.time()
    with _REGISTRY_LOCK:
        entry = _SANDBOX_REGISTRY.get(workspace_id)
        if entry:
            entry.last_access = now
            return now
    return None


def _set_vscode_info(workspace_id: str, info: dict[str, Any] | None) -> None:
    with _REGISTRY_LOCK:
        if info is None:
            _VSCODE_INFO.pop(workspace_id, None)
            entry = _SANDBOX_REGISTRY.get(workspace_id)
            if entry:
                entry.vscode_info = None
            return
        _VSCODE_INFO[workspace_id] = info
        entry = _SANDBOX_REGISTRY.get(workspace_id)
        if entry:
            entry.vscode_info = info


def _get_vscode_info(workspace_id: str) -> dict[str, Any] | None:
    with _REGISTRY_LOCK:
        entry = _SANDBOX_REGISTRY.get(workspace_id)
        if entry and entry.vscode_info:
            return entry.vscode_info
        return _VSCODE_INFO.get(workspace_id)


def _ensure_sandbox_entry(
    workspace_id: str, workspace_dir: str
) -> tuple[SandboxEntry, bool]:
    existing = _get_sandbox_entry(workspace_id)
    if existing:
        existing.last_access = time.time()
        return existing, False

    sandbox = _create_sandbox_with_persistence(workspace_dir)
    server = sandbox.__enter__()
    entry = SandboxEntry(
        sandbox=server,
        workspace_dir=workspace_dir,
        last_access=time.time(),
        vscode_info=_get_vscode_info(workspace_id),
    )

    with _REGISTRY_LOCK:
        other = _SANDBOX_REGISTRY.get(workspace_id)
        if other:
            entry_to_use = other
        else:
            _SANDBOX_REGISTRY[workspace_id] = entry
            entry_to_use = entry

    if entry_to_use is not entry:
        try:
            sandbox.__exit__(None, None, None)
        except Exception:  # noqa: BLE001
            logger.exception("重复创建沙箱时清理失败: %s", workspace_id)
        entry_to_use.last_access = time.time()
        return entry_to_use, False

    return entry, True


def _dispose_workspace(workspace_id: str) -> bool:
    with _REGISTRY_LOCK:
        entry = _SANDBOX_REGISTRY.pop(workspace_id, None)
        _VSCODE_INFO.pop(workspace_id, None)
    if not entry:
        return False
    try:
        entry.sandbox.__exit__(None, None, None)
    except Exception:  # noqa: BLE001
        logger.exception("释放沙箱失败: %s", workspace_id)
    return True


def _collect_expired_workspaces(now: float | None = None) -> list[str]:
    now = now or time.time()
    with _REGISTRY_LOCK:
        return [
            workspace_id
            for workspace_id, entry in _SANDBOX_REGISTRY.items()
            if now - entry.last_access > SANDBOX_IDLE_TTL
        ]


def _cleanup_expired_entries(now: float | None = None) -> list[str]:
    expired = _collect_expired_workspaces(now)
    for workspace_id in expired:
        _dispose_workspace(workspace_id)
    return expired


def _cleanup_all_workspaces() -> None:
    for workspace_id in list(_SANDBOX_REGISTRY.keys()):
        _dispose_workspace(workspace_id)


def _build_vscode_payload(
    workspace_id: str,
    entry: SandboxEntry,
    info: dict[str, Any] | None,
    source: str,
) -> dict[str, Any]:
    now = time.time()
    expires_at = entry.last_access + SANDBOX_IDLE_TTL
    remaining = max(0.0, expires_at - now)
    payload: dict[str, Any] = {
        "workspace_id": workspace_id,
        "ttl_seconds": SANDBOX_IDLE_TTL,
        "last_active": entry.last_access,
        "expires_at": expires_at,
        "remaining_seconds": remaining,
        "source": source,
    }
    if info and info.get("url"):
        payload["url"] = info["url"]
    return payload


def _fetch_vscode_info(entry: SandboxEntry) -> dict[str, Any] | None:
    base_url = entry.sandbox.base_url.rstrip("/")
    query = urlencode({"base_url": base_url})
    request_url = f"{base_url}/api/vscode/url?{query}"
    try:
        with urllib_request.urlopen(request_url, timeout=10) as response:
            if response.status != 200:
                raise RuntimeError(
                    f"请求 VSCode URL 失败，状态码 {response.status}"
                )
            data = json.loads(response.read().decode("utf-8"))
    except (urllib_error.URLError, RuntimeError, json.JSONDecodeError) as exc:
        logger.warning("获取 VSCode URL 失败: %s", exc)
        return None

    url = data.get("url")
    if not url:
        return None

    return {
        "url": url,
        "fetched_at": time.time(),
        "base_url": base_url,
    }


def _ensure_vscode_info_for_entry(
    workspace_id: str, entry: SandboxEntry
) -> tuple[dict[str, Any] | None, str]:
    cached = _get_vscode_info(workspace_id)
    if cached:
        return cached, "cache"

    fetched = _fetch_vscode_info(entry)
    if fetched:
        _set_vscode_info(workspace_id, fetched)
        return fetched, "fetch"
    return cached, "unavailable"


async def _cleanup_loop() -> None:
    try:
        while True:
            await asyncio.sleep(max(1.0, SANDBOX_CLEANUP_INTERVAL))
            expired = await asyncio.to_thread(_cleanup_expired_entries)
            if expired:
                logger.info("已清理空闲工作空间: %s", ", ".join(expired))
    except asyncio.CancelledError:  # noqa: PERF203
        logger.info("后台清理任务已取消")

# 创建 FastAPI 应用
app = FastAPI(
    title="Git Integration Server",
    description="A server for handling Git repository operations with OpenHands agents (with persistence)",
    version="0.1.0"
)


@app.on_event("startup")
async def _startup_cleanup_task() -> None:
    global _CLEANUP_TASK
    if _CLEANUP_TASK is None:
        _CLEANUP_TASK = asyncio.create_task(_cleanup_loop())


@app.on_event("shutdown")
async def _shutdown_cleanup_task() -> None:
    global _CLEANUP_TASK
    if _CLEANUP_TASK is not None:
        _CLEANUP_TASK.cancel()
        try:
            await _CLEANUP_TASK
        except asyncio.CancelledError:  # noqa: PERF203
            pass
        _CLEANUP_TASK = None
    await asyncio.to_thread(_cleanup_all_workspaces)


@app.get("/")
def serve_frontend() -> FileResponse:
    """提供最简单的前端页面，便于直接访问服务。"""
    if not FRONTEND_INDEX.exists():
        raise HTTPException(status_code=503, detail="前端界面尚未部署")
    return FileResponse(FRONTEND_INDEX)


def _format_sse(event: str, data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


@app.post("/conversation")
async def handle_conversation(request: ConversationRequest) -> StreamingResponse:
    """创建或恢复对话，并通过 SSE 推送事件。"""

    api_key = os.getenv("LITELLM_API_KEY")
    assert api_key is not None, "未设置 LITELLM_API_KEY 环境变量。"

    llm = LLM(
        service_id="main-llm",
        model="openai/qwen3-next-80b-a3b-instruct",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key=SecretStr(api_key),
    )

    workspace_root = _get_workspace_root()
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

    async def event_stream():
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[str | None] = asyncio.Queue()
        conversation_id_holder: dict[str | None] = {"id": None}

        def push_event(event_name: str, data: dict) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, _format_sse(event_name, data))

        def finish_stream() -> None:
            loop.call_soon_threadsafe(queue.put_nowait, None)

        def worker() -> None:
            nonlocal conversation_mapping
            conversation: RemoteConversation | None = None
            try:
                entry, _ = _ensure_sandbox_entry(workspace_id, workspace_dir)
                server = entry.sandbox
                _touch_workspace(workspace_id)

                info, source = _ensure_vscode_info_for_entry(workspace_id, entry)
                if info:
                    push_event(
                        "vscode-info",
                        _build_vscode_payload(workspace_id, entry, info, source),
                    )

                agent = get_default_agent(
                    llm=llm,
                    working_dir="/workspace/project",
                    cli_mode=True,
                )
                agent = agent.model_copy(
                    update={
                        "mcp_config": {},
                        "security_analyzer": None,
                        "condenser": None,
                    }
                )

                last_event_time = {"ts": time.time()}

                def event_callback(event) -> None:
                    event_type = type(event).__name__
                    logger.info("🔔 回调收到事件：%s\n%s", event_type, event)
                    last_event_time["ts"] = time.time()
                    payload = event.model_dump(mode="json")  # type: ignore[arg-type]
                    payload["event_type"] = event_type
                    payload["conversation_id"] = conversation_id_holder["id"]
                    payload["workspace_id"] = workspace_id
                    push_event("agent-event", payload)

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
                conversation_id_holder["id"] = conversation_id_str
                push_event(
                    "conversation-ready",
                    {
                        "conversation_id": conversation_id_str,
                        "workspace_id": workspace_id,
                        "is_resume": is_resume,
                    },
                )

                logger.info("\n📋 对话 ID：%s", conversation.state.id)
                logger.info("📝 正在发送消息…")
                conversation.send_message(request.message)
                push_event(
                    "message-queued",
                    {
                        "conversation_id": conversation_id_str,
                        "workspace_id": workspace_id,
                        "message": request.message,
                    },
                )

                logger.info("🚀 正在运行对话…")
                conversation.run()
                logger.info("✅ 任务完成！")
                logger.info("Agent 状态：%s", conversation.state.agent_status)
                push_event(
                    "conversation-finished",
                    {
                        "conversation_id": conversation_id_str,
                        "workspace_id": workspace_id,
                        "agent_status": conversation.state.agent_status,
                    },
                )

                logger.info("⏳ 正在等待事件停止…")
                while time.time() - last_event_time["ts"] < 2.0:
                    time.sleep(0.1)
                logger.info("✅ 事件已停止")

                if not is_resume and conversation_id_str:
                    conversation_mapping[conversation_id_str] = workspace_id
                    _safe_save_mapping(conversation_mapping_file, conversation_mapping)

            except Exception as exc:  # noqa: BLE001
                logger.exception("会话处理失败")
                push_event(
                    "error",
                    {
                        "message": str(exc),
                        "workspace_id": workspace_id,
                        "conversation_id": conversation_id_holder["id"],
                    },
                )
            finally:
                if conversation is not None:
                    try:
                        conversation.close()
                    except Exception:  # noqa: BLE001
                        logger.exception("关闭会话失败")
                _touch_workspace(workspace_id)
                push_event(
                    "cleanup-complete",
                    {
                        "conversation_id": conversation_id_holder["id"],
                        "workspace_id": workspace_id,
                    },
                )
                finish_stream()

        worker_task = asyncio.create_task(asyncio.to_thread(worker))

        try:
            while True:
                chunk = await queue.get()
                if chunk is None:
                    break
                yield chunk
        finally:
            await worker_task

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/workspace/{workspace_id}/conversations/{conversation_id}/events")
async def get_conversation_events(workspace_id: str, conversation_id: str) -> dict:
    """获取指定会话的所有事件。"""

    normalized_workspace_id = _validate_workspace_id(workspace_id)
    normalized_conversation_id = _validate_conversation_id(conversation_id)

    workspace_root = Path(_get_workspace_root())
    workspace_dir = workspace_root / normalized_workspace_id
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

    workspace_root = Path(_get_workspace_root())
    workspace_dir = workspace_root / normalized_workspace_id
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

    workspace_root = Path(_get_workspace_root())
    workspace_dir = workspace_root / normalized_workspace_id
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


@app.get("/workspace/{workspace_id}/vscode")
async def get_workspace_vscode(workspace_id: str) -> dict[str, Any]:
    normalized_workspace_id = _validate_workspace_id(workspace_id)
    entry = _get_sandbox_entry(normalized_workspace_id)
    if not entry:
        raise HTTPException(status_code=404, detail="当前工作空间尚未启动沙箱")

    info, source = _ensure_vscode_info_for_entry(normalized_workspace_id, entry)
    if not info:
        raise HTTPException(status_code=503, detail="VSCode 暂不可用，请稍后重试")

    _touch_workspace(normalized_workspace_id)
    return _build_vscode_payload(normalized_workspace_id, entry, info, source)


@app.delete("/workspace/{workspace_id}/vscode")
async def delete_workspace_vscode(workspace_id: str) -> dict[str, Any]:
    normalized_workspace_id = _validate_workspace_id(workspace_id)
    disposed = await asyncio.to_thread(_dispose_workspace, normalized_workspace_id)
    if not disposed:
        raise HTTPException(status_code=404, detail="未找到需要停止的沙箱实例")
    return {
        "workspace_id": normalized_workspace_id,
        "status": "stopped",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
