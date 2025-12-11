"""Type definitions for the Odyssey client library."""

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

import numpy as np
from numpy.typing import NDArray


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


# Type aliases for callbacks
type VideoFrameCallback = Callable[[VideoFrame], None]
type StreamStartedCallback = Callable[[str], None]  # stream_id
type StreamEndedCallback = Callable[[], None]
type StreamErrorCallback = Callable[[str, str], None]  # reason, message
type InteractAcknowledgedCallback = Callable[[str], None]  # prompt
type ErrorCallback = Callable[[Exception, bool], None]  # error, fatal
type StatusChangeCallback = Callable[[ConnectionStatus, str | None], None]  # status, message
type ConnectedCallback = Callable[[], None]
type DisconnectedCallback = Callable[[], None]
