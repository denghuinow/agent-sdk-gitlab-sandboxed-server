"""VSCode service for managing OpenVSCode Server in the agent server."""

import asyncio
import os
import uuid
from pathlib import Path

from openhands.sdk.logger import get_logger


logger = get_logger(__name__)


class VSCodeService:
    """Service to manage VSCode server startup and token generation."""

    def __init__(
        self,
        workspace_path: Path,
        port: int = 8001,
        create_workspace: bool = False,
    ):
        """Initialize VSCode service.

        Args:
            port: Port to run VSCode server on (default: 8001)
            workspace_path: Path to the workspace directory
            create_workspace: Whether to create the workspace directory if it doesn't
                exist
        """
        self.port = port
        self.workspace_path = workspace_path.resolve()
        if not self.workspace_path.exists():
            if create_workspace:
                self.workspace_path.mkdir(parents=True, exist_ok=True)
            else:
                raise ValueError(f"Workspace path {workspace_path} does not exist")
        self.connection_token: str | None = None
        self.process: asyncio.subprocess.Process | None = None
        self.openvscode_server_root = Path("/openhands/.openvscode-server")

    async def start(self) -> bool:
        """Start the VSCode server.

        Returns:
            True if started successfully, False otherwise
        """
        try:
            # Check if VSCode server binary exists
            if not self._check_vscode_available():
                logger.warning(
                    "VSCode server binary not found, VSCode will be disabled"
                )
                return False

            # Generate connection token
            self.connection_token = str(uuid.uuid4())

            # Check if port is available
            if not await self._is_port_available():
                logger.warning(
                    f"Port {self.port} is not available, VSCode will be disabled"
                )
                return False

            # Setup VSCode settings
            self._setup_vscode_settings()

            # Start VSCode server
            await self._start_vscode_process()

            logger.info(
                f"VSCode server started successfully on port {self.port}"
                f" for workspace {self.workspace_path}"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to start VSCode server: {e}")
            return False

    async def stop(self) -> None:
        """Stop the VSCode server."""
        if self.process:
            try:
                self.process.terminate()
                await asyncio.wait_for(self.process.wait(), timeout=5.0)
                logger.info("VSCode server stopped successfully")
            except TimeoutError:
                logger.warning("VSCode server did not stop gracefully, killing process")
                self.process.kill()
                await self.process.wait()
            except Exception as e:
                logger.error(f"Error stopping VSCode server: {e}")
            finally:
                self.process = None

    def get_vscode_url(self, base_url: str = "http://localhost:8001") -> str | None:
        """Get the VSCode URL with authentication token.

        Args:
            base_url: Base URL for the VSCode server

        Returns:
            VSCode URL with token, or None if not available
        """
        if not self.connection_token:
            return None

        return f"{base_url}/?tkn={self.connection_token}&folder={self.workspace_path}"

    def is_running(self) -> bool:
        """Check if VSCode server is running.

        Returns:
            True if running, False otherwise
        """
        return self.process is not None and self.process.returncode is None

    def _check_vscode_available(self) -> bool:
        """Check if VSCode server binary is available.

        Returns:
            True if available, False otherwise
        """
        vscode_binary = self.openvscode_server_root / "bin" / "openvscode-server"
        return vscode_binary.exists() and vscode_binary.is_file()

    async def _is_port_available(self) -> bool:
        """Check if the specified port is available.

        Returns:
            True if port is available, False otherwise
        """
        try:
            # Try to bind to the port
            server = await asyncio.start_server(
                lambda r, w: None, "localhost", self.port
            )
            server.close()
            await server.wait_closed()
            return True
        except OSError:
            return False

    def _setup_vscode_settings(self) -> None:
        """Set up VSCode settings by creating .vscode directory and settings."""
        try:
            # Create .vscode directory in workspace
            vscode_dir = self.workspace_path / ".vscode"
            vscode_dir.mkdir(parents=True, exist_ok=True)

            # Create basic settings.json
            settings_content = {
                "workbench.colorTheme": "Default Dark+",
                "editor.fontSize": 14,
                "editor.tabSize": 4,
                "files.autoSave": "afterDelay",
                "files.autoSaveDelay": 1000,
            }

            settings_file = vscode_dir / "settings.json"
            import json

            with open(settings_file, "w") as f:
                json.dump(settings_content, f, indent=2)

            # Make settings file readable and writable
            os.chmod(settings_file, 0o666)

            logger.debug(f"VSCode settings created at {settings_file}")

        except Exception as e:
            logger.warning(f"Failed to setup VSCode settings: {e}")

    async def _start_vscode_process(self) -> None:
        """Start the VSCode server process."""
        # Ensure workspace directory exists
        self.workspace_path.mkdir(parents=True, exist_ok=True)

        # Build the command to start VSCode server
        cmd = (
            f"exec {self.openvscode_server_root}/bin/openvscode-server "
            f"--host 0.0.0.0 "
            f"--connection-token {self.connection_token} "
            f"--port {self.port} "
            f"--disable-workspace-trust\n"
        )

        # Start the process
        self.process = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        # Wait for server to start (look for startup message)
        await self._wait_for_startup()

    async def _wait_for_startup(self) -> None:
        """Wait for VSCode server to start up."""
        if not self.process or not self.process.stdout:
            return

        try:
            # Read output until we see the server is ready
            timeout = 30  # 30 second timeout
            start_time = asyncio.get_event_loop().time()

            while (
                self.process.returncode is None
                and (asyncio.get_event_loop().time() - start_time) < timeout
            ):
                try:
                    line_bytes = await asyncio.wait_for(
                        self.process.stdout.readline(), timeout=1.0
                    )
                    if not line_bytes:
                        break

                    line = line_bytes.decode("utf-8", errors="ignore").strip()
                    logger.debug(f"VSCode server output: {line}")

                    # Look for startup indicators
                    if "Web UI available at" in line or "Server bound to" in line:
                        logger.info("VSCode server startup detected")
                        break

                except TimeoutError:
                    continue

        except Exception as e:
            logger.warning(f"Error waiting for VSCode startup: {e}")


# Global VSCode service instance
_vscode_service: VSCodeService | None = None


def get_vscode_service() -> VSCodeService | None:
    """Get the global VSCode service instance.

    Returns:
        VSCode service instance if enabled, None if disabled
    """
    global _vscode_service
    if _vscode_service is None:
        from openhands.agent_server.config import (
            get_default_config,
        )

        config = get_default_config()

        if not config.enable_vscode:
            logger.info("VSCode is disabled in configuration")
            return None
        else:
            _vscode_service = VSCodeService(
                workspace_path=config.workspace_path, create_workspace=True
            )
    return _vscode_service
