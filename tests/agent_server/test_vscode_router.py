"""Tests for VSCode router."""

import asyncio
import json
import time
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from openhands.agent_server.api import create_app
from openhands.agent_server.config import Config
from openhands.agent_server.vscode_router import (
    get_vscode_status,
    get_vscode_url,
)

from git_workspace_agent import server as workspace_server


def run_async(coro):
    """Execute an async coroutine in a synchronous test."""

    return asyncio.run(coro)


@pytest.fixture
def client():
    """Create a test client."""
    config = Config()
    app = create_app(config)
    return TestClient(app)


@pytest.fixture
def mock_vscode_service():
    """Mock VSCode service for testing."""
    with patch("openhands.agent_server.vscode_router.get_vscode_service") as mock:
        yield mock.return_value


def test_get_vscode_url_success(mock_vscode_service):
    """Test getting VSCode URL successfully."""

    async def scenario() -> None:
        mock_vscode_service.get_connection_token.return_value = "test-token"
        mock_vscode_service.get_vscode_url.return_value = (
            "http://localhost:8001/?tkn=test-token&folder=/workspace"
        )

        response = await get_vscode_url("http://localhost")

        assert (
            response.url
            == "http://localhost:8001/?tkn=test-token&folder=/workspace"
        )
        mock_vscode_service.get_vscode_url.assert_called_once_with("http://localhost")

    run_async(scenario())


def test_get_vscode_url_error(mock_vscode_service):
    """Test getting VSCode URL with service error."""

    async def scenario() -> None:
        mock_vscode_service.get_connection_token.side_effect = Exception(
            "Service error"
        )

        with pytest.raises(HTTPException) as exc_info:
            await get_vscode_url()

        assert exc_info.value.status_code == 500
        assert "Failed to get VSCode URL" in str(exc_info.value.detail)

    run_async(scenario())


def test_get_vscode_status_running(mock_vscode_service):
    """Test getting VSCode status when running."""

    async def scenario() -> None:
        mock_vscode_service.is_running.return_value = True

        response = await get_vscode_status()

        assert response == {"running": True, "enabled": True}
        mock_vscode_service.is_running.assert_called_once()

    run_async(scenario())


def test_get_vscode_status_not_running(mock_vscode_service):
    """Test getting VSCode status when not running."""

    async def scenario() -> None:
        mock_vscode_service.is_running.return_value = False

        response = await get_vscode_status()

        assert response == {"running": False, "enabled": True}

    run_async(scenario())


def test_get_vscode_status_error(mock_vscode_service):
    """Test getting VSCode status with service error."""

    async def scenario() -> None:
        mock_vscode_service.is_running.side_effect = Exception("Service error")

        with pytest.raises(HTTPException) as exc_info:
            await get_vscode_status()

        assert exc_info.value.status_code == 500
        assert "Failed to get VSCode status" in str(exc_info.value.detail)

    run_async(scenario())


def test_vscode_router_endpoints_integration(client):
    """Test VSCode router endpoints through the API."""
    # Patch both the router import and the service module
    with (
        patch(
            "openhands.agent_server.vscode_router.get_vscode_service"
        ) as mock_service_getter,
        patch("openhands.agent_server.api.get_vscode_service") as mock_api_service,
    ):
        mock_service = mock_service_getter.return_value
        mock_service.get_vscode_url.return_value = (
            "http://localhost:8001/?tkn=integration-token"
        )
        mock_service.is_running.return_value = True

        # Mock the API service to avoid startup
        mock_api_service.return_value.start.return_value = True
        mock_api_service.return_value.stop.return_value = None

        # Test URL endpoint
        response = client.get("/api/vscode/url")
        assert response.status_code == 200
        data = response.json()
        assert data["url"] == "http://localhost:8001/?tkn=integration-token"

        # Test URL endpoint with custom base URL
        response = client.get("/api/vscode/url?base_url=http://example.com")
        assert response.status_code == 200

        # Test status endpoint
        response = client.get("/api/vscode/status")
        assert response.status_code == 200
        data = response.json()
        assert data["running"] is True


def test_vscode_router_endpoints_with_errors(client):
    """Test VSCode router endpoints with service errors."""
    # Patch both the router import and the service module
    with (
        patch(
            "openhands.agent_server.vscode_router.get_vscode_service"
        ) as mock_service_getter,
        patch("openhands.agent_server.api.get_vscode_service") as mock_api_service,
    ):
        mock_service = mock_service_getter.return_value
        mock_service.is_running.side_effect = Exception("Service down")

        # Mock the API service to avoid startup
        mock_api_service.return_value.start.return_value = True
        mock_api_service.return_value.stop.return_value = None

        # Test URL endpoint error
        response = client.get("/api/vscode/url")
        assert response.status_code == 500
        data = response.json()
        assert data["detail"] == "Internal Server Error"

        # Test status endpoint error
        response = client.get("/api/vscode/status")
        assert response.status_code == 500
        data = response.json()
        assert data["detail"] == "Internal Server Error"


def test_get_vscode_url_disabled():
    """Test getting VSCode URL when VSCode is disabled."""

    async def scenario() -> None:
        with patch(
            "openhands.agent_server.vscode_router.get_vscode_service"
        ) as mock_service:
            mock_service.return_value = None

            with pytest.raises(HTTPException) as exc_info:
                await get_vscode_url()

            assert exc_info.value.status_code == 503
            assert "VSCode is disabled in configuration" in str(exc_info.value.detail)

    run_async(scenario())


def test_get_vscode_status_disabled():
    """Test getting VSCode status when VSCode is disabled."""

    async def scenario() -> None:
        with patch(
            "openhands.agent_server.vscode_router.get_vscode_service"
        ) as mock_service:
            mock_service.return_value = None

            response = await get_vscode_status()

            assert response == {
                "running": False,
                "enabled": False,
                "message": "VSCode is disabled in configuration",
            }

    run_async(scenario())


def test_vscode_router_disabled_integration(client):
    """Test VSCode router endpoints when VSCode is disabled."""
    with (
        patch(
            "openhands.agent_server.vscode_router.get_vscode_service"
        ) as mock_router_service,
        patch("openhands.agent_server.api.get_vscode_service") as mock_api_service,
    ):
        # Configure VSCode as disabled
        mock_router_service.return_value = None

        # Mock the API service to avoid startup
        mock_api_service.return_value = None

        # Test URL endpoint returns 503 when disabled
        response = client.get("/api/vscode/url")
        assert response.status_code == 503
        data = response.json()
        # The error message might be in different fields depending on FastAPI error
        # handling
        error_message = data.get("detail", data.get("message", ""))
        assert (
            "VSCode is disabled" in error_message
            or "Internal Server Error" in error_message
        )

        # Test status endpoint returns disabled status
        response = client.get("/api/vscode/status")
        assert response.status_code == 200
        data = response.json()
        assert data["running"] is False
        assert data["enabled"] is False
        assert "VSCode is disabled in configuration" in data["message"]


@pytest.fixture
def workspace_registry_cleanup():
    """Ensure the workspace sandbox registry is cleared after tests."""

    with workspace_server._REGISTRY_LOCK:
        workspace_server._SANDBOX_REGISTRY.clear()
        workspace_server._VSCODE_INFO.clear()

    yield

    with workspace_server._REGISTRY_LOCK:
        workspace_server._SANDBOX_REGISTRY.clear()
        workspace_server._VSCODE_INFO.clear()


def test_workspace_vscode_endpoint_uses_cached_url(workspace_registry_cleanup):
    """VSCode URL remains accessible from cache after a conversation finishes."""

    class DummySandbox:
        def __init__(self) -> None:
            self.base_url = "http://127.0.0.1:12345"
            self.closed = False

        def __exit__(self, exc_type, exc, tb) -> None:  # noqa: D401
            self.closed = True

    async def scenario() -> None:
        workspace_id = "demo"
        info = {
            "url": "http://127.0.0.1:9001/?tkn=test",
            "ttl_seconds": workspace_server.SANDBOX_IDLE_TTL,
            "fetched_at": time.time(),
            "base_url": "http://127.0.0.1:12345",
        }
        entry = workspace_server.SandboxEntry(
            sandbox=DummySandbox(),
            workspace_dir="/tmp/demo",
            last_access=time.time(),
            vscode_info=info,
        )
        with workspace_server._REGISTRY_LOCK:
            workspace_server._SANDBOX_REGISTRY[workspace_id] = entry
            workspace_server._VSCODE_INFO[workspace_id] = info

        response = await workspace_server.get_workspace_vscode(workspace_id)

        assert response["url"] == info["url"]
        assert response["workspace_id"] == workspace_id
        assert response["ttl_seconds"] == workspace_server.SANDBOX_IDLE_TTL
        assert response["source"] == "cache"

    run_async(scenario())


def test_workspace_vscode_endpoint_restarts_missing_sandbox(
    workspace_registry_cleanup, tmp_path, monkeypatch
):
    """VSCode endpoint should restart sandbox when none is running."""

    class DummySandbox:
        def __init__(self) -> None:
            self.base_url = "http://127.0.0.1:6789"

        def __exit__(self, exc_type, exc, tb) -> None:  # noqa: D401
            return None

    workspace_id = "revive"
    workspace_dir = tmp_path / workspace_id
    workspace_dir.mkdir(parents=True, exist_ok=True)

    entry = workspace_server.SandboxEntry(
        sandbox=DummySandbox(),
        workspace_dir=str(workspace_dir),
        last_access=time.time(),
        vscode_info=None,
    )

    created: dict[str, bool] = {"called": False}

    def fake_ensure_sandbox_entry(w_id: str, w_dir: str):  # noqa: D401
        assert w_id == workspace_id
        assert w_dir == str(workspace_dir)
        created["called"] = True
        with workspace_server._REGISTRY_LOCK:
            workspace_server._SANDBOX_REGISTRY[w_id] = entry
        return entry, True

    def fake_ensure_vscode_info_for_entry(w_id: str, sandbox_entry):  # noqa: D401
        assert sandbox_entry is entry
        return {"url": "http://public.example:9100"}, "fetch"

    monkeypatch.setattr(
        workspace_server,
        "_ensure_sandbox_entry",
        fake_ensure_sandbox_entry,
    )
    monkeypatch.setattr(
        workspace_server,
        "_ensure_vscode_info_for_entry",
        fake_ensure_vscode_info_for_entry,
    )
    monkeypatch.setattr(
        workspace_server,
        "_get_workspace_root",
        lambda: str(tmp_path),
    )

    async def scenario() -> None:
        response = await workspace_server.get_workspace_vscode(workspace_id)
        assert response["url"] == "http://public.example:9100"
        assert response["source"] == "fetch"

    run_async(scenario())
    assert created["called"] is True


def test_cleanup_expired_workspace(workspace_registry_cleanup):
    """Idle workspaces should be cleaned up once TTL has passed."""

    class DummySandbox:
        def __init__(self) -> None:
            self.base_url = "http://127.0.0.1:4567"
            self.closed = False

        def __exit__(self, exc_type, exc, tb) -> None:  # noqa: D401
            self.closed = True

    sandbox = DummySandbox()
    workspace_id = "timeout"
    expired_at = time.time() - (workspace_server.SANDBOX_IDLE_TTL + 5)
    entry = workspace_server.SandboxEntry(
        sandbox=sandbox,
        workspace_dir="/tmp/timeout",
        last_access=expired_at,
        vscode_info=None,
    )
    with workspace_server._REGISTRY_LOCK:
        workspace_server._SANDBOX_REGISTRY[workspace_id] = entry

    cleaned = workspace_server._cleanup_expired_entries(now=time.time())

    assert workspace_id in cleaned
    assert sandbox.closed is True
    with workspace_server._REGISTRY_LOCK:
        assert workspace_id not in workspace_server._SANDBOX_REGISTRY
        assert workspace_id not in workspace_server._VSCODE_INFO


def test_cleanup_skips_active_workspace(workspace_registry_cleanup):
    """Cleanup should skip workspaces that have active conversations."""

    class DummySandbox:
        def __init__(self) -> None:
            self.base_url = "http://127.0.0.1:9999"
            self.closed = False

        def __exit__(self, exc_type, exc, tb) -> None:  # noqa: D401
            self.closed = True

    sandbox = DummySandbox()
    workspace_id = "busy"
    expired_at = time.time() - (workspace_server.SANDBOX_IDLE_TTL + 5)
    entry = workspace_server.SandboxEntry(
        sandbox=sandbox,
        workspace_dir="/tmp/busy",
        last_access=expired_at,
        vscode_info=None,
    )

    with workspace_server._REGISTRY_LOCK:
        workspace_server._SANDBOX_REGISTRY[workspace_id] = entry

    assert workspace_server._acquire_workspace(workspace_id) is True

    with workspace_server._REGISTRY_LOCK:
        workspace_server._SANDBOX_REGISTRY[workspace_id].last_access = expired_at

    cleaned = workspace_server._cleanup_expired_entries(now=time.time())

    assert cleaned == []
    assert sandbox.closed is False

    workspace_server._release_workspace(workspace_id)

    with workspace_server._REGISTRY_LOCK:
        reg_entry = workspace_server._SANDBOX_REGISTRY[workspace_id]
        reg_entry.last_access = expired_at
        reg_entry.active_sessions = 0

    cleaned = workspace_server._cleanup_expired_entries(now=time.time())

    assert workspace_id in cleaned
    assert sandbox.closed is True

    with workspace_server._REGISTRY_LOCK:
        assert workspace_id not in workspace_server._SANDBOX_REGISTRY


def test_fetch_vscode_info_rewrites_public_mapping(monkeypatch):
    """Ensure the VSCode URL host/port matches the public mapping configuration."""

    class DummySandbox:
        def __init__(self) -> None:
            self.base_url = "http://127.0.0.1:34567"
            self.public_host = "sandbox.example"
            self.public_scheme = "https"
            self.vscode_host_port = 45678
            self.vscode_base_url = (
                f"{self.public_scheme}://{self.public_host}:{self.vscode_host_port}"
            )

    entry = workspace_server.SandboxEntry(
        sandbox=DummySandbox(),
        workspace_dir="/tmp/public",
        last_access=time.time(),
        vscode_info=None,
    )

    class DummyResponse:
        def __init__(self) -> None:
            self.status = 200

        def __enter__(self):  # noqa: D401
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: D401
            return False

        def read(self) -> bytes:
            return json.dumps({"url": "http://localhost:8001/?tkn=abc"}).encode("utf-8")

    expected_request = (
        "http://127.0.0.1:34567/api/vscode/url?base_url="
        "https%3A%2F%2Fsandbox.example%3A45678"
    )

    def fake_urlopen(url: str, timeout: float = 10.0):  # noqa: D401
        assert url == expected_request
        assert timeout == 10.0
        return DummyResponse()

    monkeypatch.setattr(workspace_server.urllib_request, "urlopen", fake_urlopen)

    info = workspace_server._fetch_vscode_info(entry)
    assert info is not None
    assert info["base_url"] == "https://sandbox.example:45678"
    assert info["url"] == "https://sandbox.example:45678/?tkn=abc"
