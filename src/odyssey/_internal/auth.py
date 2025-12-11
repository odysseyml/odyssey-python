"""Authentication and API client for Odyssey."""

import asyncio
import logging
import time
from dataclasses import dataclass

import aiohttp

logger = logging.getLogger(__name__)

# HTTP status code returned when no streamers are available
HTTP_SERVICE_UNAVAILABLE = 503

# Buffer time before token expiry to consider it invalid (in seconds)
AUTH_TOKEN_EXPIRY_BUFFER_S = 60


@dataclass
class SessionInfo:
    """Information about a streaming session."""

    session_id: str
    signaling_url: str
    session_token: str


class AuthClient:
    """Handles authentication and session management with the Odyssey API."""

    def __init__(self, api_key: str, api_url: str, queue_timeout_s: int = 120, debug: bool = False) -> None:
        """Create an AuthClient.

        Args:
            api_key: API key for authentication.
            api_url: Base URL for the Odyssey API.
            queue_timeout_s: Timeout for waiting in queue for a streamer.
            debug: Enable debug logging.
        """
        self._api_key = api_key
        self._api_url = api_url
        self._queue_timeout_s = queue_timeout_s
        self._debug = debug

        # Auth state
        self._auth_token: str | None = None
        self._auth_token_expiry: float | None = None

        # HTTP session
        self._http_session: aiohttp.ClientSession | None = None

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

    async def fetch_session_token(self, session_id: str) -> str:
        """Fetch session token for WebSocket authentication."""
        if not self._auth_token:
            raise ValueError("Auth token not available")

        self._log(f"Fetching session token for session {session_id}...")

        session = await self._get_http_session()
        url = f"{self._api_url}/sessions/token"

        async with session.post(
            url,
            json={"session_id": session_id},
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._auth_token}",
            },
        ) as response:
            if response.status == 404:
                raise ValueError("Session not found or not authorized")
            if not response.ok:
                raise ConnectionError(f"Failed to get session token: {response.status} {response.reason}")

            data = await response.json()

        if "session_token" not in data:
            raise ValueError("Invalid session token response")

        self._log(f"Session token obtained, expires in {data.get('expires_in', 300)}s")
        return str(data["session_token"])

    async def _request_session_once(self) -> dict[str, str] | None:
        """Request session from API (single attempt).

        Returns:
            Dict with session_id and signaling_url, or None if no streamers available.
        """
        self._log(f"Requesting session from API at {self._api_url}")

        if not self._auth_token:
            raise ValueError("Auth token not available. Call exchange_api_key_for_token first.")

        session = await self._get_http_session()
        url = f"{self._api_url}/sessions/request"

        async with session.post(
            url,
            json={},
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._auth_token}",
            },
        ) as response:
            self._log(f"API response status: {response.status} {response.reason}")

            if response.status == HTTP_SERVICE_UNAVAILABLE:
                return None

            if response.status == 429:
                data = await response.json()
                raise ValueError(data.get("detail", "Request limit exceeded"))

            if not response.ok:
                raise ConnectionError(f"API request failed: {response.status} {response.reason}")

            data = await response.json()

        if "session_id" not in data or "signalling_url" not in data:
            self._error(f"Invalid API response: {data}")
            raise ValueError("Invalid API response: missing session_id or signalling_url")

        self._log(f"Received session from API: {data}")

        return {
            "session_id": data["session_id"],
            "signaling_url": data["signalling_url"],
        }

    async def request_session(self) -> SessionInfo:
        """Request session from API with queue support.

        Returns:
            SessionInfo with session_id, signaling_url, and session_token.
        """
        # Ensure we have auth token
        await self.exchange_api_key_for_token()

        start_time = time.time()

        # First attempt
        result = await self._request_session_once()
        if result:
            session_token = await self.fetch_session_token(result["session_id"])
            return SessionInfo(
                session_id=result["session_id"],
                signaling_url=result["signaling_url"],
                session_token=session_token,
            )

        # No streamers available - start polling if timeout > 0
        if self._queue_timeout_s <= 0:
            raise ConnectionError("No streamers available. Please try again later.")

        self._log(f"No streamers available, waiting up to {self._queue_timeout_s}s...")

        while time.time() - start_time < self._queue_timeout_s:
            await asyncio.sleep(1.0)

            result = await self._request_session_once()
            if result:
                session_token = await self.fetch_session_token(result["session_id"])
                return SessionInfo(
                    session_id=result["session_id"],
                    signaling_url=result["signaling_url"],
                    session_token=session_token,
                )

            elapsed = int(time.time() - start_time)
            self._log(f"Still waiting for streamer... ({elapsed}s/{self._queue_timeout_s}s)")

        raise ConnectionError(f"Timed out waiting for a streamer ({self._queue_timeout_s}s)")

    async def close(self) -> None:
        """Close HTTP session."""
        if self._http_session:
            await self._http_session.close()
            self._http_session = None
