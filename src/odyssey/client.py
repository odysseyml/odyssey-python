"""Main Odyssey client for connecting to Odyssey's audio-visual intelligence platform."""

import asyncio
import base64
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, overload

from ._internal import AuthClient, RecordingsClient, SignalingClient, SimulationsClient, WebRTCConnection
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
    SimulationJobDetail,
    SimulationJobInfo,
    SimulationJobsList,
    SimulationJobStatus,
    SimulationStream,
    StatusChangeCallback,
    StreamEndedCallback,
    StreamErrorCallback,
    StreamRecordingInfo,
    StreamRecordingsList,
    StreamStartedCallback,
    VideoFrameCallback,
)

logger = logging.getLogger(__name__)

I2V_BASE_WIDTH = 1280
I2V_BASE_HEIGHT = 704
I2V_JPEG_QUALITY = 90


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
        self._simulations: SimulationsClient | None = None

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

        # Wait for data channel to open (matching JavaScript client behavior)
        # This ensures start_stream() can use the data channel immediately after connect()
        if self._webrtc:
            try:
                await self._webrtc.wait_for_data_channel_open(timeout=30.0)
            except asyncio.TimeoutError:
                err = OdysseyConnectionError("Timeout waiting for data channel to open")
                self._set_status(ConnectionStatus.FAILED, str(err), error=err)
                if self._handlers.on_error:
                    self._handlers.on_error(err, True)
                raise err

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

    async def start_stream(
        self,
        prompt: str = "",
        portrait: bool = True,
        image: Any | None = None,
        image_path: str | None = None,
    ) -> str:
        """Start an interactive stream session.

        Args:
            prompt: Initial prompt to generate video content.
            portrait: True for portrait (704x1280), False for landscape (1280x704).
            image: Optional image for image-to-video generation. Supports:
                - str: File path or base64 data URL
                - bytes: Raw image bytes
                - PIL.Image.Image: PIL Image object
                - numpy.ndarray: RGB uint8 array (H, W, 3)
            image_path: Deprecated. Use `image` instead. Path to local image file.

        Returns:
            Stream ID when the stream is ready. Use this for recordings.

        Raises:
            OdysseyStreamError: If not connected or stream fails to start.
            ValueError: If image format is unsupported or file not found.
        """
        # Handle deprecated image_path parameter
        if image_path is not None:
            import warnings

            warnings.warn(
                "image_path is deprecated, use image instead",
                DeprecationWarning,
                stacklevel=2,
            )
            if image is None:
                image = image_path

        if self._status != ConnectionStatus.CONNECTED:
            raise OdysseyStreamError(f"Cannot start stream: client is {self._status.value}, expected connected")

        if not self._webrtc:
            raise OdysseyStreamError("WebRTC connection not established")

        if not self._signaling:
            raise OdysseyStreamError("Signaling client not connected")

        # Convert image to base64 if provided
        input_image_base64 = None
        if image is not None:
            input_image_base64 = self._encode_image(image, portrait)

        # Send start message via data channel (text-only) or WebSocket (image or fallback)
        message = {
            "type": "interactive_stream_start",
            "prompt": prompt,
            "portrait": portrait,
            "input_image_base64": input_image_base64,
        }
        message_size = len(json.dumps(message).encode("utf-8"))
        max_message_size = self._webrtc.max_message_size()
        if input_image_base64:
            self._log(f"Starting stream via signaling with prompt: '{prompt[:50]}...'")
            await self._signaling.send(message)
        else:
            if self._webrtc.is_data_channel_open:
                if message_size > max_message_size:
                    self._log(
                        f"start_stream payload {message_size} bytes exceeds data channel max {max_message_size}; "
                        "using signaling"
                    )
                    await self._signaling.send(message)
                else:
                    self._log(f"Starting stream via data channel with prompt: '{prompt[:50]}...'")
                    self._webrtc.send_event(message)
            else:
                self._log("Data channel not open; falling back to signaling for start_stream")
                await self._signaling.send(message)

        # Wait for stream_started response via data channel
        return await self._webrtc.wait_for_stream_start()

    async def _image_to_base64(self, image_path: str, portrait: bool) -> str:
        """Convert an image file to base64 data URL.

        Args:
            image_path: Local file path to the image.
            portrait: True for portrait, False for landscape.

        Returns:
            Base64-encoded data URL (data:image/...;base64,...).

        Raises:
            ValueError: If file not found or too large.
        """
        path = Path(image_path)
        if not path.exists() or not path.is_file():
            raise ValueError(f"Image file not found: {image_path}")

        with open(path, "rb") as f:
            image_bytes = f.read()

        # Validate image size (25MB max)
        max_size = 25 * 1024 * 1024
        if len(image_bytes) > max_size:
            size_mb = len(image_bytes) / (1024 * 1024)
            raise ValueError(f"Image exceeds maximum size of 25MB ({size_mb:.2f}MB provided)")

        resized_bytes = self._resize_image_bytes(image_bytes, portrait)
        content_type = self._detect_image_type(resized_bytes)

        base64_data = base64.b64encode(resized_bytes).decode("ascii")
        return f"data:{content_type};base64,{base64_data}"

    def _target_image_size(self, portrait: bool) -> tuple[int, int]:
        if portrait:
            return (I2V_BASE_HEIGHT, I2V_BASE_WIDTH)
        return (I2V_BASE_WIDTH, I2V_BASE_HEIGHT)

    def _resize_image_bytes(self, image_bytes: bytes, portrait: bool) -> bytes:
        try:
            from io import BytesIO

            from PIL import Image
        except Exception:
            self._log("Pillow not available; skipping client-side resize")
            return image_bytes

        target_width, target_height = self._target_image_size(portrait)

        try:
            with Image.open(BytesIO(image_bytes)) as image:
                if image.width == target_width and image.height == target_height:
                    return image_bytes

                resample = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS  # type: ignore[attr-defined]

                target_ratio = target_width / target_height
                image_ratio = image.width / image.height
                if image_ratio > target_ratio:
                    new_height = target_height
                    new_width = int(image.width * (target_height / image.height))
                else:
                    new_width = target_width
                    new_height = int(image.height * (target_width / image.width))

                resized = image.resize((new_width, new_height), resample=resample)
                left = (new_width - target_width) // 2
                top = (new_height - target_height) // 2
                resized = resized.crop((left, top, left + target_width, top + target_height))
                output = BytesIO()
                fmt = (image.format or "JPEG").upper()
                save_kwargs: dict[str, Any] = {}
                if fmt == "JPEG":
                    save_kwargs["quality"] = I2V_JPEG_QUALITY
                    save_kwargs["optimize"] = True
                resized.save(output, format=fmt, **save_kwargs)
                return output.getvalue()
        except Exception as exc:
            self._log(f"Image resize failed; using original bytes: {exc}")
            return image_bytes

    def _detect_image_type(self, data: bytes) -> str:
        """Detect image MIME type from magic bytes.

        Args:
            data: Raw image bytes.

        Returns:
            MIME type string (e.g., "image/jpeg").
        """
        if len(data) < 12:
            return "application/octet-stream"

        # JPEG: FF D8 FF
        if data[:3] == b"\xff\xd8\xff":
            return "image/jpeg"

        # PNG: 89 50 4E 47 0D 0A 1A 0A
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            return "image/png"

        # GIF: GIF87a or GIF89a
        if data[:6] in (b"GIF87a", b"GIF89a"):
            return "image/gif"

        # WebP: RIFF....WEBP
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            return "image/webp"

        # HEIF/HEIC/AVIF: ftyp box at offset 4
        if data[4:8] == b"ftyp":
            brand = data[8:12].decode("ascii", errors="ignore").lower()
            if brand in ("heic", "heix", "heim", "heis"):
                return "image/heic"
            if brand in ("mif1", "msf1"):
                return "image/heif"
            if brand in ("avif", "avis"):
                return "image/avif"
            # Generic HEIF/HEIC fallback
            return "image/heif"

        # BMP: BM
        if data[:2] == b"BM":
            return "image/bmp"

        # Default to JPEG for unknown formats (server will validate)
        return "image/jpeg"

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

    # =========================================================================
    # Simulation API (don't require active connection)
    # =========================================================================

    async def _ensure_simulations_client(self) -> None:
        """Ensure simulations client is initialized."""
        if not self._auth:
            self._auth = AuthClient(
                api_key=self._config.api_key,
                api_url=self._config.api_url,
                queue_timeout_s=self._config.advanced.queue_timeout_s,
                debug=self._config.dev.debug,
            )
        if not self._simulations:
            self._simulations = SimulationsClient(
                auth=self._auth,
                api_url=self._config.api_url,
                debug=self._config.dev.debug,
            )

    @overload
    async def simulate(
        self,
        prompts: list[str | dict[str, Any]],
        *,
        portrait: bool = True,
        interval: int = 3000,
    ) -> SimulationJobDetail: ...

    @overload
    async def simulate(
        self,
        prompts: None = None,
        *,
        script: list[dict[str, Any]] | None = None,
        scripts: list[list[dict[str, Any]]] | None = None,
        script_url: str | None = None,
        portrait: bool = True,
    ) -> SimulationJobDetail: ...

    async def simulate(
        self,
        prompts: list[str | dict[str, Any]] | None = None,
        *,
        script: list[dict[str, Any]] | None = None,
        scripts: list[list[dict[str, Any]]] | None = None,
        script_url: str | None = None,
        portrait: bool = True,
        interval: int = 3000,
    ) -> SimulationJobDetail:
        """Submit a simulation job to be processed asynchronously.

        Supports two calling styles:

        **Simple (ergonomic):** Pass a list of prompts. The first prompt starts the video,
        subsequent prompts are interactions spaced by `interval` (default 3000ms).

        **Full control:** Pass keyword arguments with explicit script entries and timestamps.

        Note: This method can be called without an active connection.
        It only requires a valid API key.

        Args:
            prompts: Simple mode - list of prompt strings (or dicts with prompt/image).
                First prompt starts the video, subsequent prompts are interactions.
            script: Full control - single script with explicit timestamps.
            scripts: Batch mode - multiple scripts to run in parallel.
            script_url: URL to script JSON file.
            portrait: True for portrait (704x1280), False for landscape (1280x704).
            interval: Time between prompts in simple mode (default 3000ms).

        Returns:
            SimulationJobDetail with job info including job_id.

        Raises:
            ValueError: If invalid options provided.
            ConnectionError: If API request fails.

        Example:
            # Simple: list of prompts (recommended)
            job = await client.simulate(["A cat sleeping", "The cat wakes up", "The cat stretches"])

            # Simple with options
            job = await client.simulate(
                ["A cat sleeping", "The cat yawns"],
                portrait=False,
                interval=5000,
            )

            # Simple with image-to-video (first entry as dict)
            job = await client.simulate([
                {"prompt": "A robot dancing", "image": "/path/to/image.jpg"},
                "The robot spins",
                "The robot bows",
            ])

            # Full control: explicit timestamps
            job = await client.simulate(
                script=[
                    {"timestamp_ms": 0, "start": {"prompt": "A cat sleeping"}},
                    {"timestamp_ms": 5000, "interact": {"prompt": "The cat wakes up"}},
                    {"timestamp_ms": 10000, "end": {}},
                ]
            )
        """
        # Handle simple prompt list form
        if prompts is not None:
            script = []
            for i, entry in enumerate(prompts):
                timestamp_ms = i * interval
                if i == 0:
                    # First entry is 'start'
                    if isinstance(entry, str):
                        script.append({"timestamp_ms": timestamp_ms, "start": {"prompt": entry}})
                    else:
                        script.append({"timestamp_ms": timestamp_ms, "start": entry})
                else:
                    # Subsequent entries are 'interact'
                    prompt = entry if isinstance(entry, str) else entry.get("prompt", "")
                    script.append({"timestamp_ms": timestamp_ms, "interact": {"prompt": prompt}})

        await self._ensure_simulations_client()

        # Process scripts to convert image file paths to base64
        processed_script = await self._process_simulation_script(script, portrait) if script else None
        processed_scripts = None
        if scripts:
            processed_scripts = [await self._process_simulation_script(s, portrait) for s in scripts]

        data = await self._simulations.submit_job(  # type: ignore[union-attr]
            script=processed_script,
            scripts=processed_scripts,
            script_url=script_url,
            portrait=portrait,
        )

        return SimulationJobDetail(
            job_id=data["job_id"],
            status=SimulationJobStatus(data["status"]),
            priority=data["priority"],
            created_at=data["created_at"],
            dispatched_at=data.get("dispatched_at"),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            error_message=data.get("error_message"),
            assigned_region=data.get("assigned_region"),
            retry_count=data.get("retry_count", 0),
            streams=[],
            estimated_wait_minutes=data.get("estimated_wait_minutes"),
        )

    async def _process_simulation_script(self, script: list[dict[str, Any]], portrait: bool) -> list[dict[str, Any]]:
        """Process a simulation script, converting images to base64.

        Args:
            script: List of script entries.
            portrait: True for portrait, False for landscape.

        Returns:
            Processed script with images converted to base64.
        """
        processed: list[dict[str, Any]] = []

        for i, entry in enumerate(script):
            # Validate start entries have required prompt field
            if "start" in entry and "prompt" not in entry["start"]:
                raise ValueError(f"Script entry {i}: 'start' must include a 'prompt' field")

            if "start" in entry and entry["start"].get("image"):
                image = entry["start"]["image"]
                image_base64 = self._encode_image(image, portrait)

                processed.append(
                    {
                        "timestamp_ms": entry["timestamp_ms"],
                        "start": {
                            "prompt": entry["start"]["prompt"],
                            "image": image_base64,
                        },
                    }
                )
            else:
                # Pass through interact/end/start-without-image without modification
                processed.append(entry)

        # Auto-append end entry if missing (ergonomic improvement)
        # The API requires scripts to end with an 'end' action, but users often forget.
        # Rather than throwing a cryptic server error, we silently append it.
        if processed and "end" not in processed[-1]:
            last_timestamp = processed[-1].get("timestamp_ms", 0)
            processed.append({"timestamp_ms": last_timestamp + 3000, "end": {}})

        return processed

    def _encode_image(self, image: Any, portrait: bool) -> str:
        """Encode an image to base64 data URL.

        Supports multiple input types:
        - str: File path or base64 data URL (data:image/...;base64,...)
        - bytes: Raw image bytes
        - PIL.Image.Image: PIL Image object
        - numpy.ndarray: NumPy array (RGB uint8)

        Args:
            image: Image in any supported format.
            portrait: True for portrait, False for landscape.

        Returns:
            Base64-encoded data URL (data:image/...;base64,...).

        Raises:
            ValueError: If image format is unsupported or file not found.
        """
        # Already a base64 data URL - pass through
        if isinstance(image, str) and image.startswith("data:"):
            return image

        # File path - load bytes
        if isinstance(image, str):
            path = Path(image)
            if not path.exists() or not path.is_file():
                raise ValueError(f"Image file not found: {image}")
            with open(path, "rb") as f:
                image_bytes = f.read()
        # Raw bytes
        elif isinstance(image, bytes):
            image_bytes = image
        # PIL Image or numpy array - convert to bytes
        else:
            image_bytes = self._convert_image_to_bytes(image, portrait)

        # Validate size (25MB max)
        max_size = 25 * 1024 * 1024
        if len(image_bytes) > max_size:
            size_mb = len(image_bytes) / (1024 * 1024)
            raise ValueError(f"Image exceeds maximum size of 25MB ({size_mb:.2f}MB provided)")

        # Resize and encode
        resized_bytes = self._resize_image_bytes(image_bytes, portrait)
        content_type = self._detect_image_type(resized_bytes)
        base64_data = base64.b64encode(resized_bytes).decode("ascii")
        return f"data:{content_type};base64,{base64_data}"

    def _convert_image_to_bytes(self, image: Any, portrait: bool) -> bytes:
        """Convert a PIL Image or numpy array to JPEG bytes.

        Args:
            image: PIL Image or numpy array.
            portrait: True for portrait, False for landscape.

        Returns:
            JPEG-encoded bytes.

        Raises:
            ValueError: If image type is unsupported.
        """
        try:
            from io import BytesIO

            from PIL import Image as PILImage
        except ImportError as e:
            raise ValueError("Pillow is required to process PIL Image or numpy array inputs") from e

        # Handle numpy arrays
        if hasattr(image, "dtype") and hasattr(image, "shape"):
            # Assume RGB uint8 numpy array
            pil_image = PILImage.fromarray(image)
        elif hasattr(image, "save") and hasattr(image, "mode"):
            # PIL Image
            pil_image = image
        else:
            raise ValueError(
                f"Unsupported image type: {type(image).__name__}. "
                "Expected str (path), bytes, PIL.Image.Image, or numpy.ndarray"
            )

        # Convert to RGB if necessary
        if pil_image.mode not in ("RGB", "L"):
            pil_image = pil_image.convert("RGB")

        # Save to bytes
        output = BytesIO()
        pil_image.save(output, format="JPEG", quality=I2V_JPEG_QUALITY, optimize=True)
        return output.getvalue()

    async def get_simulate_status(self, job_id: str) -> SimulationJobDetail:
        """Get the status of a simulation job.

        Note: This method can be called without an active connection.
        It only requires a valid API key.

        Args:
            job_id: The job ID from simulate().

        Returns:
            SimulationJobDetail with job status and output streams if completed.

        Raises:
            ValueError: If job not found or not authorized.
            ConnectionError: If API request fails.

        Example:
            status = await client.get_simulate_status(job.job_id)
            if status.status == SimulationJobStatus.COMPLETED:
                print(f"Video URL: {status.streams[0].video_url}")
        """
        await self._ensure_simulations_client()
        data = await self._simulations.get_status(job_id)  # type: ignore[union-attr]

        streams = [
            SimulationStream(
                stream_id=s["stream_id"],
                video_url=s.get("video_url"),
                events_url=s.get("events_url"),
                thumbnail_url=s.get("thumbnail_url"),
                preview_url=s.get("preview_url"),
                frame_count=s.get("frame_count"),
                duration_seconds=s.get("duration_seconds"),
                script_index=s.get("script_index", 0),
            )
            for s in data.get("streams", [])
        ]

        return SimulationJobDetail(
            job_id=data["job_id"],
            status=SimulationJobStatus(data["status"]),
            priority=data["priority"],
            created_at=data["created_at"],
            dispatched_at=data.get("dispatched_at"),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            error_message=data.get("error_message"),
            assigned_region=data.get("assigned_region"),
            retry_count=data.get("retry_count", 0),
            streams=streams,
            estimated_wait_minutes=data.get("estimated_wait_minutes"),
        )

    async def list_simulations(
        self,
        *,
        status: SimulationJobStatus | None = None,
        active: bool | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> SimulationJobsList:
        """List user's simulation jobs.

        Note: This method can be called without an active connection.
        It only requires a valid API key.

        Args:
            status: Filter by job status.
            active: Only show active jobs (pending/dispatched/processing).
            limit: Maximum jobs to return (default: 20, max: 100).
            offset: Offset from start (default: 0).

        Returns:
            SimulationJobsList with paginated job list.

        Raises:
            ValueError: If invalid parameters or not authorized.
            ConnectionError: If API request fails.

        Example:
            # List all simulations
            result = await client.list_simulations(limit=10)
            print(f"Total simulations: {result.total}")

            # List only active jobs
            active = await client.list_simulations(active=True)
        """
        await self._ensure_simulations_client()
        data = await self._simulations.list_jobs(  # type: ignore[union-attr]
            status=status.value if status else None,
            active=active,
            limit=limit,
            offset=offset,
        )

        jobs = [
            SimulationJobInfo(
                job_id=j["job_id"],
                status=SimulationJobStatus(j["status"]),
                priority=j["priority"],
                created_at=j["created_at"],
                completed_at=j.get("completed_at"),
                error_message=j.get("error_message"),
            )
            for j in data.get("jobs", [])
        ]

        return SimulationJobsList(
            jobs=jobs,
            total=data["total"],
            limit=data["limit"],
            offset=data["offset"],
        )

    async def cancel_simulation(self, job_id: str) -> SimulationJobInfo:
        """Cancel a pending or dispatched simulation job.

        Cannot cancel jobs that are already processing or completed.

        Note: This method can be called without an active connection.
        It only requires a valid API key.

        Args:
            job_id: The job ID to cancel.

        Returns:
            SimulationJobInfo with cancellation confirmation.

        Raises:
            ValueError: If job not found, not authorized, or cannot be cancelled.
            ConnectionError: If API request fails.

        Example:
            await client.cancel_simulation(job.job_id)
        """
        await self._ensure_simulations_client()
        data = await self._simulations.cancel_job(job_id)  # type: ignore[union-attr]

        return SimulationJobInfo(
            job_id=data["job_id"],
            status=SimulationJobStatus(data["status"]),
            priority=data.get("priority", "normal"),
            created_at=data.get("created_at", ""),
            completed_at=data.get("completed_at"),
            error_message=data.get("error_message"),
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

        # Close simulations client
        if self._simulations:
            await self._simulations.close()
            self._simulations = None

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
