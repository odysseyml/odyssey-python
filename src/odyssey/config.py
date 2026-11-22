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
        api_key: API key for authentication. Required for ``connect()`` and
            API-key-gated methods. May be omitted when using
            ``connect_with_credentials()`` with pre-minted session tokens.
        api_url: API URL (defaults to production).
        debug: Enable debug logging.
        target_width: Optional WebRTC output width.
        target_height: Optional WebRTC output height.
        target_fps: Optional maximum WebRTC output frame rate.
        advanced: Advanced connection settings.
        model: Optional Streaming model; omitted to use the server default.
    """

    api_key: str = ""
    """API key for authentication. Empty is allowed for credential-based connections."""

    api_url: str = field(default_factory=_get_default_api_url)
    """API URL (defaults to https://api.odyssey.ml or ODYSSEY_API_URL env var)."""

    debug: bool = False
    """Enable debug logging."""

    target_width: int | None = None
    """Optional WebRTC output width. Must be even and supplied with target_height."""

    target_height: int | None = None
    """Optional WebRTC output height. Must be even and supplied with target_width."""

    target_fps: int | None = None
    """Optional maximum WebRTC output frame rate. Must be from 1 through 60."""

    advanced: AdvancedConfig = field(default_factory=AdvancedConfig)
    """Advanced connection settings."""

    model: str | None = None
    """Optional Streaming model. Simulation uses its server-assigned execution profile."""

    def __post_init__(self) -> None:
        """Validate configuration."""
        if self.model is not None and (not isinstance(self.model, str) or not self.model.strip()):
            raise ValueError("model must be a nonblank string when provided")
        if not isinstance(self.api_key, str):
            raise TypeError("api_key must be a string")
        if (self.target_width is None) != (self.target_height is None):
            raise ValueError("target_width and target_height must be provided together")
        for name, value in (("target_width", self.target_width), ("target_height", self.target_height)):
            if value is not None and (not isinstance(value, int) or value < 16 or value > 4096 or value % 2):
                raise ValueError(f"{name} must be an even integer between 16 and 4096")
        if (
            self.target_fps is not None
            and (
                not isinstance(self.target_fps, int)
                or isinstance(self.target_fps, bool)
                or self.target_fps < 1
                or self.target_fps > 60
            )
        ):
            raise ValueError("target_fps must be an integer between 1 and 60")

    def require_api_key(self) -> str:
        """Return the API key, raising if it is empty or blank.

        Raises:
            ValueError: If ``api_key`` was not provided.
        """
        if not self.api_key or self.api_key.strip() == "":
            raise ValueError(
                "api_key is required for this operation. "
                "Pass an API key to the Odyssey constructor, or use "
                "connect_with_credentials() for pre-minted session tokens."
            )
        return self.api_key
