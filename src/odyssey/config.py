"""Configuration management for the Odyssey client."""

import os
from dataclasses import dataclass, field

# Default API URL
DEFAULT_API_URL = "https://api.odyssey.ml"


def _get_default_api_url() -> str:
    """Get API URL from environment or use default.

    Priority:
    1. ODYSSEY_API_URL environment variable
    2. Production default
    """
    return os.environ.get("ODYSSEY_API_URL", DEFAULT_API_URL)


@dataclass(frozen=True, slots=True)
class DevConfig:
    """Development/debug settings for the client.

    These settings should not be exposed in production interfaces.
    """

    signaling_url: str | None = None
    """WebSocket signaling server URL - when provided, bypasses API for direct connection."""

    session_id: str | None = None
    """Session ID to use with signaling_url (required when signaling_url is set)."""

    debug: bool = False
    """Enable debug logging."""


@dataclass(frozen=True, slots=True)
class AdvancedConfig:
    """Advanced connection settings."""

    max_retries: int = 5
    """Maximum number of connection retry attempts (set to 0 to disable retries)."""

    initial_retry_delay_ms: int = 1000
    """Initial delay between retries in milliseconds."""

    max_retry_delay_ms: int = 2000
    """Maximum delay between retries in milliseconds."""

    retry_backoff_multiplier: float = 2.0
    """Backoff multiplier for exponential retry delay."""

    queue_timeout_s: int = 30
    """How long to wait for a streamer to become available in seconds (set to 0 to fail immediately)."""


@dataclass(slots=True)
class ClientConfig:
    """Configuration for the Odyssey client.

    Attributes:
        api_key: API key for authentication (required).
        api_url: API URL (defaults to production).
        dev: Development/debug settings.
        advanced: Advanced connection settings.
    """

    api_key: str
    """API key for authentication (required)."""

    api_url: str = field(default_factory=_get_default_api_url)
    """API URL (defaults to https://api.odyssey.ml or ODYSSEY_API_URL env var)."""

    dev: DevConfig = field(default_factory=DevConfig)
    """Development/debug settings."""

    advanced: AdvancedConfig = field(default_factory=AdvancedConfig)
    """Advanced connection settings."""

    def __post_init__(self) -> None:
        """Validate configuration."""
        if not self.api_key:
            raise ValueError("api_key is required")
        if not isinstance(self.api_key, str):
            raise TypeError("api_key must be a string")
        if self.api_key.strip() == "":
            raise ValueError("api_key cannot be empty")

        # Validate dev config
        if self.dev.signaling_url and not self.dev.session_id:
            raise ValueError("dev.session_id is required when dev.signaling_url is set")
