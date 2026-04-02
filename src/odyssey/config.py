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
        advanced: Advanced connection settings.
    """

    api_key: str = ""
    """API key for authentication. Empty is allowed for credential-based connections."""

    api_url: str = field(default_factory=_get_default_api_url)
    """API URL (defaults to https://api.odyssey.ml or ODYSSEY_API_URL env var)."""

    debug: bool = False
    """Enable debug logging."""

    advanced: AdvancedConfig = field(default_factory=AdvancedConfig)
    """Advanced connection settings."""

    def __post_init__(self) -> None:
        """Validate configuration."""
        if not isinstance(self.api_key, str):
            raise TypeError("api_key must be a string")

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
