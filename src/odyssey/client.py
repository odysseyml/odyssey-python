"""Main Odyssey client for connecting to Odyssey's audio-visual intelligence platform."""

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from ._internal import AuthClient, RecordingsClient, SignalingClient, WebRTCConnection
from ._internal.webrtc import WebRTCCallbacks
from .config import ClientConfig
from .exceptions import OdysseyAuthError, OdysseyConnectionError, OdysseyStreamError
from .types import (
    ConnectedCallback,
    ConnectionStatus,
    DisconnectedCallback,
    ErrorCallback,
    InteractAcknowledgedCallback,
    Recording,
    StatusChangeCallback,
    StreamEndedCallback,
    StreamErrorCallback,
    StreamRecordingInfo,
    StreamRecordingsList,
    StreamStartedCallback,
    VideoFrameCallback,
)

logger = logging.getLogger(__name__)


@dataclass
class OdysseyEventHandlers:
    """Event handlers for the Odyssey client."""

    on_connected: ConnectedCallback | None = None
    on_disconnected: DisconnectedCallback | None = None
    on_video_frame: VideoFrameCallback | None = None
    on_stream_started: StreamStartedCallback | None = None
    on_stream_ended: StreamEndedCallback | None = None
    on_interact_acknowledged: InteractAcknowledgedCallback | None = None
    on_stream_error: StreamErrorCallback | None = None
    on_error: ErrorCallback | None = None
    on_status_change: StatusChangeCallback | None = None


class Odyssey:
    """Client for connecting to Odyssey's audio-visual intelligence platform.

    Example:
        ```python
        from odyssey import Odyssey, OdysseyAuthError, OdysseyConnectionError

        client = Odyssey(api_key="ody_...")

        try:
            await client.connect(
                on_video_frame=lambda frame: cv2.imshow("video", frame.data),
                on_stream_started=lambda stream_id: print(f"Started: {stream_id}"),
            )
            await client.start_stream("A cat", portrait=True)
            await client.interact("Pet the cat")
            await client.end_stream()
        except OdysseyAuthError:
            print("Invalid API key")
        except OdysseyConnectionError as e:
            print(f"Connection failed: {e}")
        finally:
            await client.disconnect()
        ```
    """

    def __init__(self, api_key: str, **kwargs: Any) -> None:
        """Create a new Odyssey client.

        Args:
            api_key: API key for authentication (required).
            **kwargs: Additional configuration options passed to ClientConfig.

        Raises:
            ValueError: If api_key is empty or invalid.
        """
        self._config = ClientConfig(api_key=api_key, **kwargs)
        self._handlers = OdysseyEventHandlers()

        # Connection state
        self._status = ConnectionStatus.DISCONNECTED
        self._session_id: str | None = None
        self._current_signaling_url: str | None = None

        # Internal clients
        self._auth: AuthClient | None = None
        self._signaling: SignalingClient | None = None
        self._webrtc: WebRTCConnection | None = None
        self._recordings: RecordingsClient | None = None

        # Retry state
        self._retry_count = 0

        # Connect future - stores exception on failure
        self._connect_future: asyncio.Future[None] | None = None
        self._connect_error: Exception | None = None

    def _log(self, msg: str) -> None:
        """Log a debug message."""
        if self._config.dev.debug:
            logger.debug(f"[Client] {msg}")

    def _error(self, msg: str) -> None:
        """Log an error message."""
        logger.error(f"[Client] {msg}")

    def _set_status(self, status: ConnectionStatus, message: str | None = None, error: Exception | None = None) -> None:
        """Set connection status and notify handlers."""
        self._status = status
        if error:
            self._connect_error = error
        if self._handlers.on_status_change:
            self._handlers.on_status_change(status, message)

        # Resolve connect future when connection completes or fails
        if self._connect_future and not self._connect_future.done():
            if status == ConnectionStatus.CONNECTED:
                self._connect_future.set_result(None)
            elif status == ConnectionStatus.FAILED:
                self._connect_future.set_result(None)  # Error stored in _connect_error

    async def connect(
        self,
        on_connected: ConnectedCallback | None = None,
        on_disconnected: DisconnectedCallback | None = None,
        on_video_frame: VideoFrameCallback | None = None,
        on_stream_started: StreamStartedCallback | None = None,
        on_stream_ended: StreamEndedCallback | None = None,
        on_interact_acknowledged: InteractAcknowledgedCallback | None = None,
        on_stream_error: StreamErrorCallback | None = None,
        on_error: ErrorCallback | None = None,
        on_status_change: StatusChangeCallback | None = None,
    ) -> None:
        """Connect to a streaming session.

        Args:
            on_connected: Called when WebRTC connection is established.
            on_disconnected: Called when connection is closed.
            on_video_frame: Called for each video frame received.
            on_stream_started: Called when the interactive stream starts.
            on_stream_ended: Called when the interactive stream ends.
            on_interact_acknowledged: Called when an interaction is acknowledged.
            on_stream_error: Called when a stream error occurs (reason, message).
            on_error: Called on transient errors during streaming.
            on_status_change: Called when connection status changes.

        Raises:
            OdysseyAuthError: If authentication fails (invalid API key).
            OdysseyConnectionError: If connection fails (no streamers, timeout, etc.).
        """
        # Check if already connecting or connected
        if self._status in (
            ConnectionStatus.AUTHENTICATING,
            ConnectionStatus.CONNECTING,
            ConnectionStatus.RECONNECTING,
            ConnectionStatus.CONNECTED,
        ):
            self._log(f"connect() called while already {self._status.value}, ignoring")
            if self._status == ConnectionStatus.CONNECTED:
                return
            raise OdysseyConnectionError(f"Already {self._status.value}")

        # Reset error state
        self._connect_error = None

        # Set handlers
        self._handlers = OdysseyEventHandlers(
            on_connected=on_connected,
            on_disconnected=on_disconnected,
            on_video_frame=on_video_frame,
            on_stream_started=on_stream_started,
            on_stream_ended=on_stream_ended,
            on_interact_acknowledged=on_interact_acknowledged,
            on_stream_error=on_stream_error,
            on_error=on_error,
            on_status_change=on_status_change,
        )

        self._retry_count = 0

        # Check if using direct signaling (development mode)
        if self._config.dev.signaling_url:
            self._current_signaling_url = self._config.dev.signaling_url
            self._session_id = self._config.dev.session_id
            self._log(f"Using direct signaling URL {self._current_signaling_url} (bypassing API)")
        else:
            # Request session from API
            self._set_status(ConnectionStatus.AUTHENTICATING, "Connecting to Odyssey...")

            try:
                self._log("Authenticating with API key...")
                self._auth = AuthClient(
                    api_key=self._config.api_key,
                    api_url=self._config.api_url,
                    queue_timeout_s=self._config.advanced.queue_timeout_s,
                    debug=self._config.dev.debug,
                )

                session_info = await self._auth.request_session()

                self._session_id = session_info.session_id
                self._current_signaling_url = session_info.signaling_url

                self._log(f"Using API-assigned session {self._session_id} at {self._current_signaling_url}")

            except Exception as e:
                error_msg = str(e)
                # Determine if this is an auth error or connection error
                if "401" in error_msg or "403" in error_msg or "invalid" in error_msg.lower():
                    err = OdysseyAuthError(error_msg)
                else:
                    err = OdysseyConnectionError(error_msg)
                self._set_status(ConnectionStatus.FAILED, error_msg, error=err)
                if self._handlers.on_error:
                    self._handlers.on_error(err, True)
                raise err from e

        # Set connecting status
        self._set_status(ConnectionStatus.CONNECTING, "Connecting to signaling server...")

        # Create connect future
        self._connect_future = asyncio.get_event_loop().create_future()

        # Attempt connection
        await self._attempt_connection()

        # Wait for connection to complete
        await self._connect_future

        # Check if connection failed
        if self._status == ConnectionStatus.FAILED:
            error = self._connect_error or OdysseyConnectionError("Connection failed")
            raise error

    async def _attempt_connection(self) -> None:
        """Attempt to establish connection."""
        self._log("=== ENTERED _attempt_connection() ===")

        if not self._current_signaling_url:
            raise ValueError("No signaling URL")

        self._set_status(ConnectionStatus.CONNECTING)

        try:
            # Create WebRTC connection
            self._webrtc = WebRTCConnection(debug=self._config.dev.debug)
            self._webrtc.set_callbacks(
                WebRTCCallbacks(
                    on_connected=self._on_webrtc_connected,
                    on_video_frame=self._handlers.on_video_frame,
                    on_stream_started=self._handlers.on_stream_started,
                    on_stream_ended=self._handlers.on_stream_ended,
                    on_interact_acknowledged=self._handlers.on_interact_acknowledged,
                    on_stream_error=self._handlers.on_stream_error,
                    on_error=self._handlers.on_error,
                )
            )

            # Fetch ICE servers
            await self._webrtc.fetch_ice_servers(self._current_signaling_url)

            # Create signaling client
            self._signaling = SignalingClient(
                debug=self._config.dev.debug,
                on_close=self._handle_signaling_close,
            )

            # Setup message handlers
            self._signaling.on("offer", self._handle_offer)
            self._signaling.on("ice_candidate", self._handle_ice_candidate)
            self._signaling.on("error", self._handle_signaling_error)

            # Get session token if we have auth client
            session_token = None
            if self._auth and self._session_id:
                session_token = await self._auth.fetch_session_token(self._session_id)

            # Connect to signaling server
            await self._signaling.connect(
                self._current_signaling_url,
                self._session_id or "",
                session_token,
            )

            self._retry_count = 0
            self._log(f"Successfully connected to session {self._session_id}")

        except Exception as e:
            self._log(f"Connection attempt {self._retry_count + 1} failed: {e}")

            # Check if we should retry
            if self._retry_count < self._config.advanced.max_retries:
                delay_ms = min(
                    self._config.advanced.initial_retry_delay_ms
                    * (self._config.advanced.retry_backoff_multiplier**self._retry_count),
                    self._config.advanced.max_retry_delay_ms,
                )
                self._retry_count += 1

                self._log(f"Retrying in {delay_ms}ms (attempt {self._retry_count}/{self._config.advanced.max_retries})")

                await asyncio.sleep(delay_ms / 1000)
                await self._attempt_connection()
            else:
                self._error(f"Connection failed after {self._config.advanced.max_retries} retries")
                err = OdysseyConnectionError(str(e))
                self._set_status(ConnectionStatus.FAILED, str(e), error=err)
                if self._handlers.on_error:
                    self._handlers.on_error(err, True)

    def _on_webrtc_connected(self) -> None:
        """Handle WebRTC connection established."""
        self._set_status(ConnectionStatus.CONNECTED)
        if self._handlers.on_connected:
            self._handlers.on_connected()

    def _handle_signaling_close(self, code: int, reason: str) -> None:
        """Handle signaling connection close."""
        self._log(f"Signaling closed (code: {code}, reason: {reason})")

        is_normal_closure = code in (1000, 1001)

        if is_normal_closure:
            if self._status != ConnectionStatus.FAILED:
                self._set_status(ConnectionStatus.DISCONNECTED)
            return

        # If connecting/reconnecting, let retry logic handle it
        if self._status in (ConnectionStatus.CONNECTING, ConnectionStatus.RECONNECTING):
            return

        # Abnormal closure - this is fatal
        asyncio.create_task(self._cleanup())

        error_message = f"Signaling disconnected: {reason}" if reason else "Disconnected from signaling server"
        err = OdysseyConnectionError(error_message)

        if self._status != ConnectionStatus.FAILED:
            self._set_status(ConnectionStatus.FAILED, error_message, error=err)

        if self._handlers.on_error and self._status == ConnectionStatus.FAILED:
            self._handlers.on_error(err, True)

    def _handle_signaling_error(self, msg: dict[str, Any]) -> None:
        """Handle error messages from signaling server."""
        reason = msg.get("reason", "unknown")
        error_messages = {
            "streamer_not_available": "Streamer not available. Please ensure the streamer is running.",
            "streamer_disconnected": "Streamer has disconnected.",
            "unknown": "An unknown error occurred.",
        }
        error_message = error_messages.get(reason, f"Server error: {reason}")
        err = OdysseyConnectionError(error_message)

        self._set_status(ConnectionStatus.FAILED, error_message, error=err)
        self._error(f"Signaling error: {reason}")

        if self._handlers.on_error:
            self._handlers.on_error(err, True)

    async def _handle_offer(self, msg: dict[str, Any]) -> None:
        """Handle SDP offer from server."""
        if self._webrtc and self._signaling:
            await self._webrtc.handle_offer(msg.get("sdp", ""), self._signaling.send)

    async def _handle_ice_candidate(self, msg: dict[str, Any]) -> None:
        """Handle ICE candidate from server."""
        if self._webrtc:
            await self._webrtc.handle_ice_candidate(
                msg.get("candidate", ""),
                msg.get("sdpMid"),
                msg.get("sdpMLineIndex"),
            )

    async def start_stream(self, prompt: str = "", portrait: bool = True) -> str:
        """Start an interactive stream session.

        Args:
            prompt: Initial prompt to generate video content.
            portrait: True for portrait (480x832), False for landscape (832x480).

        Returns:
            Stream ID when the stream is ready. Use this for recordings.

        Raises:
            OdysseyStreamError: If not connected or stream fails to start.
        """
        if self._status != ConnectionStatus.CONNECTED:
            raise OdysseyStreamError(f"Cannot start stream: client is {self._status.value}, expected connected")

        if not self._webrtc:
            raise OdysseyStreamError("WebRTC connection not established")

        return await self._webrtc.start_stream(prompt, portrait)

    async def interact(self, prompt: str) -> str:
        """Send an interaction prompt.

        Args:
            prompt: The interaction prompt.

        Returns:
            The acknowledged prompt.

        Raises:
            OdysseyStreamError: If not connected or no active stream.
        """
        if self._status != ConnectionStatus.CONNECTED:
            raise OdysseyStreamError(f"Cannot interact: client is {self._status.value}, expected connected")

        if not self._webrtc:
            raise OdysseyStreamError("WebRTC connection not established")

        return await self._webrtc.interact(prompt)

    async def end_stream(self) -> None:
        """End the current interactive stream session.

        Raises:
            OdysseyStreamError: If not connected.
        """
        if self._status != ConnectionStatus.CONNECTED:
            raise OdysseyStreamError(f"Cannot end stream: client is {self._status.value}, expected connected")

        if not self._webrtc:
            raise OdysseyStreamError("WebRTC connection not established")

        await self._webrtc.end_stream()

    async def _ensure_recordings_client(self) -> None:
        """Ensure recordings client is initialized."""
        if not self._auth:
            self._auth = AuthClient(
                api_key=self._config.api_key,
                api_url=self._config.api_url,
                queue_timeout_s=self._config.advanced.queue_timeout_s,
                debug=self._config.dev.debug,
            )
        if not self._recordings:
            self._recordings = RecordingsClient(
                auth=self._auth,
                api_url=self._config.api_url,
                debug=self._config.dev.debug,
            )

    async def get_recording(self, stream_id: str) -> Recording:
        """Get recording data for a stream.

        Returns presigned URLs for the video, events, thumbnail, and preview
        that are valid for a limited time (typically 1 hour).

        Note: This method can be called without an active connection.
        It only requires a valid API key.

        Args:
            stream_id: The stream ID to get recording for (from start_stream).

        Returns:
            Recording object with presigned URLs.

        Raises:
            ValueError: If recording not found or not authorized.
            ConnectionError: If API request fails.

        Example:
            recording = await client.get_recording("stream-123")
            if recording.video_url:
                # Download or play the video
                print(f"Video URL: {recording.video_url}")
        """
        await self._ensure_recordings_client()
        data = await self._recordings.get_recording(stream_id)  # type: ignore[union-attr]

        return Recording(
            stream_id=data["stream_id"],
            video_url=data.get("video_url"),
            events_url=data.get("events_url"),
            thumbnail_url=data.get("thumbnail_url"),
            preview_url=data.get("preview_url"),
            frame_count=data.get("frame_count"),
            duration_seconds=data.get("duration_seconds"),
        )

    async def list_stream_recordings(self, limit: int | None = None, offset: int | None = None) -> StreamRecordingsList:
        """List stream recordings for the authenticated user.

        Returns a paginated list of streams with recordings, ordered by most recent first.
        Only returns streams from sessions owned by the authenticated user.

        Note: This method can be called without an active connection.
        It only requires a valid API key.

        Args:
            limit: Maximum number of recordings to return (default: server default).
            offset: Number of recordings to skip for pagination.

        Returns:
            StreamRecordingsList with recordings and pagination info.

        Raises:
            ValueError: If not authorized.
            ConnectionError: If API request fails.

        Example:
            result = await client.list_stream_recordings(limit=10)
            for recording in result.recordings:
                print(f"{recording.stream_id}: {recording.duration_seconds}s")
        """
        await self._ensure_recordings_client()
        data = await self._recordings.list_stream_recordings(limit=limit, offset=offset)  # type: ignore[union-attr]

        recordings = [
            StreamRecordingInfo(
                stream_id=r["stream_id"],
                width=r["width"],
                height=r["height"],
                started_at=r["started_at"],
                ended_at=r.get("ended_at"),
                duration_seconds=r.get("duration_seconds"),
            )
            for r in data.get("recordings", [])
        ]

        return StreamRecordingsList(
            recordings=recordings,
            total=data["total"],
            limit=data["limit"],
            offset=data["offset"],
        )

    async def _cleanup(self) -> None:
        """Clean up connections."""
        # Clear connect future
        if self._connect_future and not self._connect_future.done():
            self._connect_future.set_result(None)
        self._connect_future = None

        # Close WebRTC
        if self._webrtc:
            await self._webrtc.close()
            self._webrtc = None

        # Close signaling
        if self._signaling:
            try:
                if self._signaling.is_connected:
                    await self._signaling.send({"type": "client_disconnecting"})
            except Exception:
                pass
            await self._signaling.close()
            self._signaling = None

    async def disconnect(self) -> None:
        """Disconnect from the session."""
        await self._cleanup()

        # Close recordings client
        if self._recordings:
            await self._recordings.close()
            self._recordings = None

        # Close auth client
        if self._auth:
            await self._auth.close()
            self._auth = None

        # Reset state
        self._current_signaling_url = None
        self._session_id = None

        self._set_status(ConnectionStatus.DISCONNECTED)
        self._log("Disconnected")

    @property
    def is_connected(self) -> bool:
        """Check if connected."""
        return self._status == ConnectionStatus.CONNECTED

    @property
    def current_status(self) -> ConnectionStatus:
        """Get current connection status."""
        return self._status

    @property
    def current_session_id(self) -> str | None:
        """Get current session ID."""
        return self._session_id
