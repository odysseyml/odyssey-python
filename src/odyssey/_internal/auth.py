"""Authentication client for Odyssey."""

import logging
import time

import aiohttp

logger = logging.getLogger(__name__)

# Buffer time before token expiry to consider it invalid (in seconds)
AUTH_TOKEN_EXPIRY_BUFFER_S = 60


class AuthClient:
    """Handles authentication with the Odyssey API."""

    def __init__(
        self,
        api_key: str,
        api_url: str,
        debug: bool = False,
    ) -> None:
        """Create an AuthClient.

        Args:
            api_key: API key for authentication.
            api_url: Base URL for the Odyssey API.
            debug: Enable debug logging.
        """
        self._api_key = api_key
        self._api_url = api_url
        self._debug = debug

        # Auth state
        self._auth_token: str | None = None
        self._auth_token_expiry: float | None = None

        # HTTP session
        self._http_session: aiohttp.ClientSession | None = None

    @property
    def auth_token(self) -> str | None:
        """Current auth token, or None if not authenticated."""
        return self._auth_token

    def _log(self, msg: str) -> None:
        """Log a debug message."""
        if self._debug:
            logger.debug(f"[Auth] {msg}")

    def _error(self, msg: str) -> None:
        """Log an error message."""
        logger.error(f"[Auth] {msg}")

    def _is_auth_token_valid(self) -> bool:
        """Check if auth token is valid (exists and not expired)."""
        if not self._auth_token or not self._auth_token_expiry:
            return False
        return time.time() < (self._auth_token_expiry - AUTH_TOKEN_EXPIRY_BUFFER_S)

    async def _get_http_session(self) -> aiohttp.ClientSession:
        """Get or create HTTP session."""
        if self._http_session is None or self._http_session.closed:
            self._http_session = aiohttp.ClientSession()
        return self._http_session

    async def exchange_api_key_for_token(self) -> None:
        """Exchange API key for auth token."""
        if self._is_auth_token_valid():
            self._log("Using existing auth token")
            return

        self._log("Exchanging API key for auth token...")

        session = await self._get_http_session()
        url = f"{self._api_url}/auth/token"

        async with session.post(
            url,
            json={"api_key": self._api_key},
            headers={"Content-Type": "application/json"},
        ) as response:
            if response.status == 401:
                raise ValueError("Invalid API key")
            if response.status == 403:
                data = await response.json()
                raise ValueError(data.get("detail", "API key access denied"))
            if response.status == 422:
                raise ValueError("Invalid API key format. Please check your API key is correct.")
            if not response.ok:
                raise ConnectionError(f"Authentication failed: {response.status} {response.reason}")

            data = await response.json()

        if "access_token" not in data:
            raise ValueError("Invalid auth response: missing access_token")

        self._auth_token = data["access_token"]
        self._auth_token_expiry = time.time() + data.get("expires_in", 3600)

        self._log(f"Auth token obtained, expires in {data.get('expires_in', 3600)}s")

    async def close(self) -> None:
        """Close HTTP session."""
        if self._http_session:
            await self._http_session.close()
            self._http_session = None
