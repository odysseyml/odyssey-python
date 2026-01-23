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
