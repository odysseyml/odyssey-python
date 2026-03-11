"""Session management client for Odyssey."""

import asyncio
import logging
import time
from dataclasses import dataclass
from http import HTTPStatus

import aiohttp

from ..exceptions import raise_for_usage_error
from .auth import AuthClient
from .regions import measure_region_latencies

logger = logging.getLogger(__name__)


@dataclass
class SessionInfo:
    """Information about a streaming session."""

    session_id: str
    signaling_url: str
    session_token: str


class SessionClient:
    """Handles session requests and queue polling."""

    def __init__(
        self,
        auth: AuthClient,
        api_url: str,
        queue_timeout_s: int = 120,
        debug: bool = False,
    ) -> None:
        """Create a SessionClient.

        Args:
            auth: AuthClient for authentication.
            api_url: Base URL for the Odyssey API.
            queue_timeout_s: Timeout for waiting in queue for a streamer.
            debug: Enable debug logging.
        """
        self._auth = auth
        self._api_url = api_url
        self._queue_timeout_s = queue_timeout_s
        self._debug = debug

        # HTTP session
        self._http_session: aiohttp.ClientSession | None = None

        # Region latency cache (persists across reconnections)
        self._region_latency_cache: dict[str, int] = {}
        self._region_latency_lock = asyncio.Lock()

    def _log(self, msg: str) -> None:
        """Log a debug message."""
        if self._debug:
            logger.debug(f"[Session] {msg}")

    def _error(self, msg: str) -> None:
        """Log an error message."""
        logger.error(f"[Session] {msg}")

    async def _get_http_session(self) -> aiohttp.ClientSession:
        """Get or create HTTP session."""
        if self._http_session is None or self._http_session.closed:
            self._http_session = aiohttp.ClientSession()
        return self._http_session

    async def fetch_session_token(self, session_id: str) -> str:
        """Fetch session token for WebSocket authentication.

        Args:
            session_id: The session ID to get a token for.

        Returns:
            Session token string.
        """
        auth_token = self._auth.auth_token
        if not auth_token:
            raise ValueError("Auth token not available")

        self._log(f"Fetching session token for session {session_id}...")

        session = await self._get_http_session()
        url = f"{self._api_url}/sessions/token"

        async with session.post(
            url,
            json={"session_id": session_id},
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {auth_token}",
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

    async def _fetch_region_latencies(self) -> dict[str, int]:
        async with self._region_latency_lock:
            if self._region_latency_cache:
                self._log(f"Using cached region latencies: {self._region_latency_cache}")
                return dict(self._region_latency_cache)

            auth_token = self._auth.auth_token
            if not auth_token:
                return {}

            session = await self._get_http_session()
            latencies = await measure_region_latencies(
                api_url=self._api_url,
                auth_token=auth_token,
                http_session=session,
                debug=self._debug,
            )

            if latencies:
                self._region_latency_cache = latencies

            return latencies

    async def _request_session_once(
        self,
        region_latencies_task: asyncio.Task[dict[str, int]] | None = None,
    ) -> dict[str, str] | None:
        """Request session from API (single attempt).

        Returns:
            Dict with session_id and signaling_url, or None if no streamers available.
        """
        self._log(f"Requesting session from API at {self._api_url}")

        auth_token = self._auth.auth_token
        if not auth_token:
            raise ValueError("Auth token not available. Call exchange_api_key_for_token first.")

        session = await self._get_http_session()
        url = f"{self._api_url}/sessions/request"

        body: dict[str, dict[str, int]] = {}
        if region_latencies_task:
            region_latencies = await region_latencies_task
            if region_latencies:
                body["region_latencies"] = region_latencies

        async with session.post(
            url,
            json=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {auth_token}",
            },
        ) as response:
            self._log(f"API response status: {response.status} {response.reason}")

            if response.status == HTTPStatus.SERVICE_UNAVAILABLE:
                return None

            if response.status == 429:
                data = await response.json()
                # FastAPI wraps HTTPException detail in {"detail": ...}
                detail = data.get("detail", data)
                raise_for_usage_error(response.status, detail)
                # Fallback if response doesn't match usage error format
                msg = detail if isinstance(detail, str) else "Request limit exceeded"
                raise ValueError(msg)

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
        await self._auth.exchange_api_key_for_token()

        # Start fetching region latencies in parallel with session request
        region_latencies_task = asyncio.create_task(self._fetch_region_latencies())

        start_time = time.time()

        result = await self._request_session_once(region_latencies_task)
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

            result = await self._request_session_once(region_latencies_task)
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
