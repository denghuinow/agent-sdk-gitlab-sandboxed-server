import os
from pathlib import Path

from pydantic import BaseModel, Field

from openhands.agent_server.env_parser import from_env


# Environment variable constants
SESSION_API_KEY_ENV = "SESSION_API_KEY"
ENVIRONMENT_VARIABLE_PREFIX = "OH"


def _default_session_api_keys():
    # Legacy fallback for compability with old runtime API
    result = []
    session_api_key = os.getenv(SESSION_API_KEY_ENV)
    if session_api_key:
        result.append(session_api_key)
    return result


class WebhookSpec(BaseModel):
    """Spec to create a webhook. All webhook requests use POST method."""

    # General parameters
    event_buffer_size: int = Field(
        default=10,
        ge=1,
        description=(
            "The number of events to buffer locally before posting to the webhook"
        ),
    )
    base_url: str = Field(
        description="The base URL of the webhook service. Events will be sent to "
        "{base_url}/events and conversation info to {base_url}/conversations"
    )
    headers: dict[str, str] = Field(default_factory=dict)
    flush_delay: float = Field(
        default=30.0,
        gt=0,
        description=(
            "The delay in seconds after which buffered events will be flushed to "
            "the webhook, even if the buffer is not full. Timer is reset on each "
            "new event."
        ),
    )

    # Retry parameters
    num_retries: int = Field(
        default=3,
        ge=0,
        description="The number of times to retry if the post operation fails",
    )
    retry_delay: int = Field(default=5, ge=0, description="The delay between retries")


class Config(BaseModel):
    """
    Immutable configuration for a server running in local mode.
    (Typically inside a sandbox).
    """

    session_api_keys: list[str] = Field(
        default_factory=_default_session_api_keys,
        description=(
            "List of valid session API keys used to authenticate incoming requests. "
            "Empty list implies the server will be unsecured. Any key in this list "
            "will be accepted for authentication."
        ),
    )
    allow_cors_origins: list[str] = Field(
        default_factory=list,
        description=(
            "Set of CORS origins permitted by this server (Anything from localhost is "
            "always accepted regardless of what's in here)."
        ),
    )
    conversations_path: Path = Field(
        default=Path("workspace/conversations"),
        description=(
            "The location of the directory where conversations and events are stored."
        ),
    )
    workspace_path: Path = Field(
        default=Path("workspace/project"),
        description=(
            "The location of the project directory where the agent reads/writes. "
            "Defaults to 'workspace/project'."
        ),
    )
    bash_events_dir: Path = Field(
        default=Path("workspace/bash_events"),
        description=(
            "The location of the directory where bash events are stored as files. "
            "Defaults to 'workspace/bash_events'."
        ),
    )
    static_files_path: Path | None = Field(
        default=None,
        description=(
            "The location of the directory containing static files to serve. "
            "If specified and the directory exists, static files will be served "
            "at the /static/ endpoint."
        ),
    )
    webhooks: list[WebhookSpec] = Field(
        default_factory=list,
        description="Webhooks to invoke in response to events",
    )
    enable_vscode: bool = Field(
        default=True,
        description="Whether to enable VSCode server functionality",
    )
    model_config = {"frozen": True}


_default_config: Config | None = None


def get_default_config() -> Config:
    """Get the default local server config shared across the server"""
    global _default_config
    if _default_config is None:
        # Get the config from the environment variables
        _default_config = from_env(Config, ENVIRONMENT_VARIABLE_PREFIX)
        assert _default_config is not None
    return _default_config
