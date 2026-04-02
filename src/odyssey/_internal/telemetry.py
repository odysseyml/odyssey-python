"""Fire-and-forget telemetry reporter for SDK client events.

Reports errors and lifecycle events back to the Odyssey API so they appear
in the server-side analytics pipeline. Designed to never interfere with
user code:

- All reporting is async and fire-and-forget
- Errors during reporting are silently logged, never raised
- Enabled by default (can be disabled with enable_telemetry=False)
- Bounded: at most 3 in-flight reports at a time
"""

import asyncio
import logging
import platform
import sys
import time
from enum import Enum
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)


class ClientErrorType(str, Enum):
    """Error categories reported by the SDK to the telemetry endpoint."""

    AUTH = "auth"
    CONNECTION = "connection"
    STREAM = "stream"
    USAGE = "usage"
    UNKNOWN = "unknown"


class ClientEventType(str, Enum):
    """Lifecycle event types reported by the SDK."""

    SESSION_CONNECTING = "session_connecting"
    SESSION_CONNECTED = "session_connected"
    SESSION_DISCONNECTED = "session_disconnected"


class TelemetryReporter:
    """Reports SDK events to the server-side analytics pipeline.

    Sends both error reports and lifecycle events so the internal team
    can reconstruct a full client-side session timeline:

    1. session_connecting — auth + session request started (includes api_key_prefix)
    2. session_connected — fully ready (video track + data channel), includes timing
    3. client.error.* — any error that occurred
    4. session_disconnected — clean disconnect with session duration
    """

    def __init__(self, api_url: str, sdk_version: str, debug: bool = False) -> None:
        self._api_url = api_url
        self._sdk_version = sdk_version
        self._debug = debug
        self._auth_token: str | None = None
        self._session_id: str | None = None
        self._api_key_prefix: str | None = None
        self._http_session: aiohttp.ClientSession | None = None
        self._platform_info = f"{platform.system()} {platform.release()} / Python {sys.version.split()[0]}"
        self._semaphore: asyncio.Semaphore | None = None

        # Timing for connect duration measurement
        self._connect_start_time: float | None = None

    def _log(self, msg: str) -> None:
        if self._debug:
            logger.debug(f"[Telemetry] {msg}")

    def set_auth_token(self, token: str | None) -> None:
        """Set the auth token for authenticated telemetry."""
        self._auth_token = token

    def set_session_id(self, session_id: str | None) -> None:
        """Set the current session ID for context."""
        self._session_id = session_id

    def set_api_key_prefix(self, api_key: str) -> None:
        """Store first 8 chars of the API key for pre-auth error identification."""
        if api_key and len(api_key) >= 8:
            self._api_key_prefix = api_key[:8]

    async def _get_http_session(self) -> aiohttp.ClientSession:
        if self._http_session is None or self._http_session.closed:
            self._http_session = aiohttp.ClientSession()
        return self._http_session

    def _get_semaphore(self) -> asyncio.Semaphore:
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(3)
        return self._semaphore

    def _base_event(self) -> dict[str, Any]:
        """Build base event dict with common fields."""
        event: dict[str, Any] = {
            "sdk_version": self._sdk_version,
            "sdk_platform": "python",
            "platform_info": self._platform_info,
        }
        if self._session_id:
            event["session_id"] = self._session_id
        if self._api_key_prefix:
            event["api_key_prefix"] = self._api_key_prefix
        return event

    # ── Error reporting ──────────────────────────────────────────────

    def report_error(
        self,
        error_type: ClientErrorType,
        error_message: str,
        *,
        error_code: str | None = None,
        connection_status: str | None = None,
    ) -> None:
        """Fire-and-forget: schedule an error report.

        Args:
            error_type: Error category.
            error_message: Human-readable error description.
            error_code: Structured code (e.g., MONTHLY_LIMIT_REACHED).
            connection_status: Client connection status at time of error.
        """
        event = self._base_event()
        event["error_type"] = error_type.value
        event["error_message"] = error_message[:2000]
        if error_code:
            event["error_code"] = error_code
        if connection_status:
            event["connection_status"] = connection_status
        self._schedule_send(event)

    # ── Lifecycle reporting ──────────────────────────────────────────

    def report_connecting(self) -> None:
        """Report that the client is starting to connect (auth + session request)."""
        self._connect_start_time = time.monotonic()
        event = self._base_event()
        event["event"] = ClientEventType.SESSION_CONNECTING.value
        self._schedule_send(event)

    def report_connected(self) -> None:
        """Report that the client is fully connected (video + data channel ready)."""
        event = self._base_event()
        event["event"] = ClientEventType.SESSION_CONNECTED.value
        if self._connect_start_time is not None:
            event["connect_duration_ms"] = int((time.monotonic() - self._connect_start_time) * 1000)
            self._connect_start_time = None
        self._schedule_send(event)

    def report_disconnected(self, duration_seconds: float | None = None) -> None:
        """Report that the client has disconnected cleanly."""
        event = self._base_event()
        event["event"] = ClientEventType.SESSION_DISCONNECTED.value
        if duration_seconds is not None:
            event["session_duration_seconds"] = round(duration_seconds, 1)
        self._schedule_send(event)

    # ── Transport ────────────────────────────────────────────────────

    def _schedule_send(self, event: dict[str, Any]) -> None:
        """Schedule an event to be sent. Returns immediately."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self._send(event))

    async def _send(self, event: dict[str, Any]) -> None:
        """Send a single event to the telemetry endpoint. Never raises."""
        try:
            sem = self._get_semaphore()
            if sem.locked():
                self._log("Dropping telemetry event (in-flight limit reached)")
                return

            async with sem:
                session = await self._get_http_session()
                url = f"{self._api_url}/telemetry"

                headers: dict[str, str] = {"Content-Type": "application/json"}
                if self._auth_token:
                    headers["Authorization"] = f"Bearer {self._auth_token}"

                async with session.post(
                    url,
                    json={"events": [event]},
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as response:
                    self._log(f"Telemetry event sent: {response.status}")

        except Exception as e:
            # Never crash user code
            self._log(f"Failed to send telemetry: {e}")

    async def close(self) -> None:
        """Close the HTTP session."""
        if self._http_session:
            await self._http_session.close()
            self._http_session = None
