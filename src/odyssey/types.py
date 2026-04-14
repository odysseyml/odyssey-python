"""Type definitions for the Odyssey client library."""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

import numpy as np
from numpy.typing import NDArray

if TYPE_CHECKING:
    from ._internal.whep import WhepConnection


def _extract_session_id(token: str) -> str:
    """Extract session_id from a JWT session token without signature verification.

    The token is a standard JWT (header.payload.signature). The payload is
    base64url-encoded JSON containing a ``session_id`` claim.

    Signature verification is intentionally skipped because the JWT is signed
    with an HS256 secret that only the server possesses. The client reads the
    ``session_id`` for routing only — the signaling server verifies the full
    signature when the token is presented during WebSocket connection.

    Raises:
        ValueError: If the token is malformed or missing the session_id claim.
    """
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("session_token is not a valid JWT (expected 3 dot-separated parts)")
    payload_b64 = parts[1]
    # JWT uses base64url encoding — add padding as needed
    padding = 4 - len(payload_b64) % 4
    if padding != 4:
        payload_b64 += "=" * padding
    try:
        payload_bytes = base64.urlsafe_b64decode(payload_b64)
        payload = json.loads(payload_bytes)
    except Exception as e:
        raise ValueError(f"Failed to decode session_token JWT payload: {e}") from e
    session_id = payload.get("session_id")
    if not session_id or not isinstance(session_id, str):
        raise ValueError("session_token JWT does not contain a valid 'session_id' claim")
    result: str = session_id
    return result


@dataclass(frozen=True, slots=True)
class VideoFrame:
    """A video frame received from the interactive stream.

    Attributes:
        data: RGB uint8 array with shape (height, width, 3).
        width: Frame width in pixels.
        height: Frame height in pixels.
        timestamp_ms: Presentation timestamp in milliseconds.

    Example:
        # Display with OpenCV (note: OpenCV uses BGR)
        cv2.imshow("video", cv2.cvtColor(frame.data, cv2.COLOR_RGB2BGR))

        # Convert to PIL Image
        Image.fromarray(frame.data)
    """

    data: NDArray[np.uint8]
    width: int
    height: int
    timestamp_ms: int


@dataclass(frozen=True, slots=True)
class BroadcastInfo:
    """Broadcast URLs and token for spectator viewing.

    When broadcast mode is enabled, these URLs allow spectators to watch
    the stream without participating in the interactive session.

    Attributes:
        hls_url: HLS playlist URL for broad compatibility (~5-10s latency). May be None if HLS disabled.
        webrtc_url: WebRTC/WHEP URL for low-latency viewing (~1s latency).
        spectator_token: Token for authenticated broadcast playback.
    """

    hls_url: str | None
    webrtc_url: str
    spectator_token: str


@dataclass(frozen=True, slots=True)
class Recording:
    """Recording data with presigned URLs for a stream.

    URLs are valid for a limited time (typically 1 hour).

    Attributes:
        stream_id: Unique identifier for the stream.
        video_url: Presigned URL for the video file, or None if not available.
        events_url: Presigned URL for the events JSON file, or None if not available.
        thumbnail_url: Presigned URL for the thumbnail image, or None if not available.
        preview_url: Presigned URL for the preview video, or None if not available.
        frame_count: Total number of frames in the recording, or None if not available.
        duration_seconds: Duration of the recording in seconds, or None if not available.

    Example:
        recording = await client.get_recording("stream-123")
        if recording.video_url:
            # Download or stream the video
            response = requests.get(recording.video_url)
    """

    stream_id: str
    video_url: str | None
    events_url: str | None
    thumbnail_url: str | None
    preview_url: str | None
    frame_count: int | None
    duration_seconds: float | None


@dataclass(frozen=True, slots=True)
class StreamRecordingInfo:
    """Summary info for a stream recording in a list.

    Attributes:
        stream_id: Unique identifier for the stream.
        width: Video width in pixels.
        height: Video height in pixels.
        started_at: ISO 8601 timestamp when the stream started.
        ended_at: ISO 8601 timestamp when the stream ended, or None if still active.
        duration_seconds: Duration of the recording in seconds, or None if still active.
    """

    stream_id: str
    width: int
    height: int
    started_at: str
    ended_at: str | None
    duration_seconds: float | None


@dataclass(frozen=True, slots=True)
class StreamRecordingsList:
    """Paginated list of stream recordings.

    Attributes:
        recordings: List of stream recording info.
        total: Total number of recordings available.
        limit: Maximum number of recordings returned per request.
        offset: Number of recordings skipped.
    """

    recordings: list[StreamRecordingInfo]
    total: int
    limit: int
    offset: int


@dataclass(frozen=True, slots=True)
class StreamerCapabilities:
    """Streamer capabilities advertised by the connected session.

    Used to determine what features are available.

    Attributes:
        image_to_video: Whether the model supports image-to-video generation.
    """

    image_to_video: bool = False

    def to_dict(self) -> dict[str, bool]:
        """Serialize to a plain dict."""
        return {"image_to_video": self.image_to_video}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StreamerCapabilities:
        """Deserialize from a plain dict."""
        raw = data.get("image_to_video", False)
        return cls(image_to_video=raw if isinstance(raw, bool) else False)


@dataclass(frozen=True, slots=True)
class ClientCredentials:
    """Pre-minted credentials for client-side connections.

    Created server-side via ``Odyssey.create_client_credentials()`` and passed
    to the client (e.g., browser) for direct connection without an API key.

    The ``session_id`` is automatically extracted from the JWT session token,
    so callers only need to provide ``signaling_url``, ``session_token``, and
    ``expires_in``.

    Attributes:
        signaling_url: WebSocket URL for the signaling server.
        session_token: Short-lived JWT for session authentication.
            Must contain a ``session_id`` claim in its payload.
        expires_in: Token lifetime in seconds.
        capabilities: Streamer capabilities from the provisioned session.
        session_id: Derived from the JWT — do not provide manually.

    Example:
        Server-side (has API key)::

            server = Odyssey(api_key="ody_...")
            credentials = await server.create_client_credentials()
            # Send credentials.to_dict() to the client application

        Client-side (no API key)::

            credentials = ClientCredentials.from_dict(data_from_server)
            client = Odyssey()
            await client.connect_with_credentials(
                credentials=credentials,
                on_video_frame=handle_frame,
            )
    """

    signaling_url: str
    session_token: str
    expires_in: int
    capabilities: StreamerCapabilities | None = None
    session_id: str = field(init=False)

    def __post_init__(self) -> None:
        """Validate inputs and extract session_id from the JWT."""
        if not isinstance(self.session_token, str) or not self.session_token.strip():
            raise ValueError("session_token must be a non-empty string")
        if not isinstance(self.signaling_url, str) or not self.signaling_url.strip():
            raise ValueError("signaling_url must be a non-empty string")
        object.__setattr__(self, "session_id", _extract_session_id(self.session_token))

    def __repr__(self) -> str:
        """Redact session_token to prevent accidental credential leakage in logs."""
        token_preview = self.session_token[:8] + "..." if len(self.session_token) > 8 else "***"
        return (
            f"ClientCredentials(session_id={self.session_id!r}, "
            f"signaling_url={self.signaling_url!r}, "
            f"session_token={token_preview!r}, "
            f"expires_in={self.expires_in})"
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict for transport (e.g., JSON API response).

        Includes ``session_id`` for convenience (e.g., so JavaScript clients
        don't need to decode the JWT). The full ``session_token`` is included —
        only call this when you intend to transmit credentials to the client.
        """
        d: dict[str, Any] = {
            "session_id": self.session_id,
            "signaling_url": self.signaling_url,
            "session_token": self.session_token,
            "expires_in": self.expires_in,
        }
        if self.capabilities is not None:
            d["capabilities"] = self.capabilities.to_dict()
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ClientCredentials:
        """Deserialize from a plain dict (e.g., received from server API).

        The ``session_id`` in the dict is ignored — it is re-derived from
        the JWT to ensure consistency.

        Args:
            data: Dict with signaling_url, session_token, expires_in,
                and optionally capabilities
                (session_id is optional and ignored).

        Raises:
            KeyError: If a required field is missing.
            ValueError: If the session_token is not a valid JWT.
        """
        caps_raw = data.get("capabilities")
        capabilities = StreamerCapabilities.from_dict(caps_raw) if isinstance(caps_raw, dict) else None
        return cls(
            signaling_url=str(data["signaling_url"]),
            session_token=str(data["session_token"]),
            expires_in=int(data["expires_in"]),
            capabilities=capabilities,
        )


class ConnectionStatus(str, Enum):
    """Connection status of the Odyssey client."""

    AUTHENTICATING = "authenticating"
    """Authenticating with Odyssey API."""

    CONNECTING = "connecting"
    """Connecting to signaling server."""

    RECONNECTING = "reconnecting"
    """Reconnecting after a disconnect."""

    CONNECTED = "connected"
    """Connected and ready."""

    DISCONNECTED = "disconnected"
    """Disconnected (clean)."""

    FAILED = "failed"
    """Connection failed (fatal)."""


class SimulationJobStatus(str, Enum):
    """Status of a simulation job."""

    PENDING = "pending"
    """Job is queued and waiting to be dispatched."""

    DISPATCHED = "dispatched"
    """Job has been dispatched to a worker."""

    PROCESSING = "processing"
    """Job is currently being processed."""

    COMPLETED = "completed"
    """Job has completed successfully."""

    FAILED = "failed"
    """Job has failed."""

    CANCELLED = "cancelled"
    """Job was cancelled by the user."""


@dataclass(frozen=True, slots=True)
class SimulationStream:
    """Output stream from a simulation job.

    Attributes:
        stream_id: Unique identifier for the stream.
        video_url: Presigned URL for the video file, or None if not yet available.
        events_url: Presigned URL for the events JSON file, or None if not available.
        thumbnail_url: Presigned URL for the thumbnail image, or None if not available.
        preview_url: Presigned URL for the preview video, or None if not available.
        frame_count: Total number of frames in the video, or None if not available.
        duration_seconds: Duration of the video in seconds, or None if not available.
        script_index: Index of the script in batch mode (0 for single script).
    """

    stream_id: str
    video_url: str | None
    events_url: str | None
    thumbnail_url: str | None
    preview_url: str | None
    frame_count: int | None
    duration_seconds: float | None
    script_index: int


@dataclass(frozen=True, slots=True)
class SimulationJobInfo:
    """Summary information for a simulation job in a list.

    Attributes:
        job_id: Unique identifier for the job.
        status: Current status of the job.
        priority: Priority level of the job.
        created_at: ISO 8601 timestamp when the job was created.
        completed_at: ISO 8601 timestamp when the job completed, or None if not completed.
        error_message: Error message if the job failed, or None otherwise.
    """

    job_id: str
    status: SimulationJobStatus
    priority: str
    created_at: str
    completed_at: str | None
    error_message: str | None


@dataclass(frozen=True, slots=True)
class SimulationJobDetail:
    """Detailed information for a simulation job.

    Attributes:
        job_id: Unique identifier for the job.
        status: Current status of the job.
        priority: Priority level of the job.
        created_at: ISO 8601 timestamp when the job was created.
        dispatched_at: ISO 8601 timestamp when the job was dispatched, or None.
        started_at: ISO 8601 timestamp when processing started, or None.
        completed_at: ISO 8601 timestamp when the job completed, or None.
        error_message: Error message if the job failed, or None otherwise.
        assigned_region: Region where the job is being processed, or None.
        retry_count: Number of times the job has been retried.
        streams: List of output streams from the simulation.
        estimated_wait_minutes: Estimated wait time in minutes, or None if not available.
    """

    job_id: str
    status: SimulationJobStatus
    priority: str
    created_at: str
    dispatched_at: str | None
    started_at: str | None
    completed_at: str | None
    error_message: str | None
    assigned_region: str | None
    retry_count: int
    streams: list[SimulationStream]
    estimated_wait_minutes: float | None = None


@dataclass(frozen=True, slots=True)
class SimulationJobsList:
    """Paginated list of simulation jobs.

    Attributes:
        jobs: List of simulation job summaries.
        total: Total number of jobs available.
        limit: Maximum number of jobs returned per request.
        offset: Number of jobs skipped.
    """

    jobs: list[SimulationJobInfo]
    total: int
    limit: int
    offset: int


@dataclass(frozen=True, slots=True)
class SpectatorConnection:
    """Active spectator connection to a broadcast stream.

    This class wraps a WHEP-based WebRTC connection for viewing
    broadcast streams. Use connect_to_stream() to create instances.

    Example:
        ```python
        from odyssey import connect_to_stream

        def handle_frame(frame):
            cv2.imshow("Broadcast", frame.data)
            cv2.waitKey(1)

        connection = await connect_to_stream(
            webrtc_url="http://localhost:8889/live/stream123",
            spectator_token="spectator_abc...",
            on_video_frame=handle_frame,
        )

        # Later:
        await connection.disconnect()
        ```
    """

    _whep: WhepConnection

    @property
    def is_connected(self) -> bool:
        """Check if the connection is currently active."""
        return self._whep.is_connected

    @property
    def peer_connection(self) -> object | None:
        """The underlying RTCPeerConnection, or None if not connected.

        Useful for collecting WebRTC stats via ``pc.getStats()``.
        Returns an opaque object to avoid coupling callers to aiortc internals.
        """
        return self._whep.peer_connection

    async def disconnect(self) -> None:
        """Disconnect from the broadcast stream.

        Call this when done viewing to clean up resources.
        """
        await self._whep.close()


# Type aliases for callbacks
type VideoFrameCallback = Callable[[VideoFrame], None]
type StreamStartedCallback = Callable[[str], None]  # stream_id
type StreamEndedCallback = Callable[[], None]
type StreamErrorCallback = Callable[[str, str], None]  # reason, message
type InteractAcknowledgedCallback = Callable[[str], None]  # prompt
type BroadcastReadyCallback = Callable[[BroadcastInfo], None]  # broadcast_info
type ErrorCallback = Callable[[Exception, bool], None]  # error, fatal
type StatusChangeCallback = Callable[[ConnectionStatus, str | None], None]  # status, message
type ConnectedCallback = Callable[[], None]
type DisconnectedCallback = Callable[[], None]
