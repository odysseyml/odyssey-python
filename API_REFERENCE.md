# Odyssey Client - API Reference

Complete API reference for the `odyssey` Python client library.

## Table of Contents

- [Installation](#installation)
- [API Summary](#api-summary)
- [Quick Start](#quick-start)
- [Odyssey Class](#odyssey-class)
  - [Constructor](#constructor)
  - [Interactive Streaming Methods](#methods)
  - [Simulation Methods](#simulatescript-scripts-script_url-portrait)
  - [Properties](#properties)
- [Types & Interfaces](#types--interfaces)
- [Usage Examples](#usage-examples)
- [Error Handling](#error-handling)

---

## Installation

```bash
pip install git+https://github.com/odysseyml/odyssey-python.git
```

Or with uv:

```bash
uv pip install git+https://github.com/odysseyml/odyssey-python.git
```

---

## API Summary

### Interactive Streaming Methods

| Signature | Description |
|-----------|-------------|
| `connect(**handlers) -> None` | Connect to a streaming session (raises on failure) |
| `disconnect() -> None` | Disconnect and clean up resources |
| `start_stream(prompt, portrait?, image?, image_path?) -> str` | Start an interactive stream |
| `interact(prompt) -> str` | Send a prompt to update the video |
| `end_stream() -> None` | End the current stream session |
| `get_recording(stream_id) -> Recording` | Get recording URLs for a stream |
| `list_stream_recordings(limit?, offset?) -> StreamRecordingsList` | List user's stream recordings |

### Simulation Methods (No Connection Required)

| Signature | Description |
|-----------|-------------|
| `simulate(script?, scripts?, script_url?, portrait?) -> SimulationJobDetail` | Submit an async simulation job |
| `get_simulate_status(job_id) -> SimulationJobDetail` | Get job status and output URLs |
| `list_simulations(status?, active?, limit?, offset?) -> SimulationJobsList` | List user's simulation jobs |
| `cancel_simulation(job_id) -> SimulationJobInfo` | Cancel a pending/dispatched job |

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `is_connected` | `bool` | Whether connected and ready |
| `current_status` | `ConnectionStatus` | Current connection status |
| `current_session_id` | `str \| None` | Current session ID |

### Event Handlers

| Handler | Parameters | Description |
|---------|------------|-------------|
| `on_connected` | - | WebRTC connection established |
| `on_disconnected` | - | Connection closed |
| `on_video_frame` | `frame: VideoFrame` | Video frame received |
| `on_stream_started` | `stream_id: str` | Interactive stream ready |
| `on_stream_ended` | - | Interactive stream ended |
| `on_interact_acknowledged` | `prompt: str` | Interaction processed |
| `on_stream_error` | `reason, message` | Stream error occurred |
| `on_error` | `error: Exception, fatal: bool` | General error |
| `on_status_change` | `status: ConnectionStatus, message: str \| None` | Connection status changed |

### Exceptions

| Exception | Description |
|-----------|-------------|
| `OdysseyError` | Base exception for all Odyssey errors |
| `OdysseyAuthError` | Authentication failed (invalid API key) |
| `OdysseyConnectionError` | Connection failed (no streamers, timeout) |
| `OdysseyStreamError` | Stream operation failed |

---

## Quick Start

```python
import asyncio
from odyssey import Odyssey, OdysseyAuthError, OdysseyConnectionError

async def main():
    client = Odyssey(api_key="ody_your_api_key_here")

    try:
        await client.connect(
            on_video_frame=lambda frame: print(f"Frame: {frame.width}x{frame.height}"),
            on_stream_started=lambda stream_id: print(f"Ready: {stream_id}"),
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

asyncio.run(main())
```

---

## Odyssey Class

The main client class for connecting to Odyssey's audio-visual intelligence platform.

### Constructor

```python
Odyssey(api_key: str, **kwargs)
```

Creates a new Odyssey client instance with the provided API key.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `api_key` | `str` | API key for authentication (required) |
| `**kwargs` | | Additional configuration options |

**Example:**

```python
client = Odyssey(api_key="ody_your_api_key_here")
```

---

### Methods

#### `connect(**handlers)`

Connect to a streaming session. The Odyssey API automatically assigns an available session.

```python
async def connect(
    on_connected: Callable[[], None] | None = None,
    on_disconnected: Callable[[], None] | None = None,
    on_video_frame: Callable[[VideoFrame], None] | None = None,
    on_stream_started: Callable[[str], None] | None = None,
    on_stream_ended: Callable[[], None] | None = None,
    on_interact_acknowledged: Callable[[str], None] | None = None,
    on_stream_error: Callable[[str, str], None] | None = None,
    on_error: Callable[[Exception, bool], None] | None = None,
    on_status_change: Callable[[ConnectionStatus, str | None], None] | None = None,
) -> None
```

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `on_connected` | `Callable[[], None]` | Called when connection is established |
| `on_disconnected` | `Callable[[], None]` | Called when connection is closed |
| `on_video_frame` | `Callable[[VideoFrame], None]` | Called for each video frame |
| `on_stream_started` | `Callable[[str], None]` | Called when stream starts |
| `on_stream_ended` | `Callable[[], None]` | Called when stream ends |
| `on_interact_acknowledged` | `Callable[[str], None]` | Called when interaction is acknowledged |
| `on_stream_error` | `Callable[[str, str], None]` | Called on stream error (reason, message) |
| `on_error` | `Callable[[Exception, bool], None]` | Called on error (error, fatal) |
| `on_status_change` | `Callable[[ConnectionStatus, str \| None], None]` | Called on status change |

**Raises:**

| Exception | Description |
|-----------|-------------|
| `OdysseyAuthError` | Authentication failed (invalid API key) |
| `OdysseyConnectionError` | Connection failed (no streamers, timeout, etc.) |

**Example:**

```python
try:
    await client.connect(
        on_video_frame=lambda frame: process_frame(frame),
        on_stream_error=lambda reason, msg: print(f"Stream error: {reason} - {msg}"),
        on_status_change=lambda status, msg: print(f"Status: {status.value}"),
    )
except OdysseyAuthError:
    print("Invalid API key")
except OdysseyConnectionError as e:
    print(f"Connection failed: {e}")
```

---

#### `disconnect()`

Disconnect from the session and clean up resources.

```python
async def disconnect() -> None
```

**Example:**

```python
await client.disconnect()
```

---

#### `start_stream(prompt, portrait?, image?, image_path?)`

Start an interactive stream session. Optionally provide an image for image-to-video (i2v) generation.

```python
async def start_stream(
    prompt: str = "",
    portrait: bool = True,
    image: str | bytes | PIL.Image.Image | np.ndarray | None = None,
    image_path: str | None = None,  # Deprecated
) -> str
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `prompt` | `str` | `""` | Initial prompt to generate video content |
| `portrait` | `bool` | `True` | `True` for portrait (704x1280), `False` for landscape (1280x704) |
| `image` | `Any \| None` | `None` | Image for i2v generation (see supported formats below) |
| `image_path` | `str \| None` | `None` | **Deprecated.** Use `image` instead. Path to local image file. |

**Supported Image Formats:**

| Type | Description |
|------|-------------|
| `str` | File path or base64 data URL (`data:image/...;base64,...`) |
| `bytes` | Raw image bytes (JPEG, PNG, etc.) |
| `PIL.Image.Image` | PIL/Pillow Image object |
| `numpy.ndarray` | RGB uint8 array with shape (H, W, 3) |

**Returns:** `str` - Stream ID when the stream is ready. Use this ID for recordings.

**Raises:**
- `OdysseyStreamError` - If not connected or stream fails to start.
- `ValueError` - If image format unsupported, file not found, or too large (max 25MB).

**Example:**

```python
# Text-to-video
stream_id = await client.start_stream("A cat sleeping", portrait=True)

# Image-to-video with file path
stream_id = await client.start_stream(
    prompt="The robot starts dancing",
    portrait=False,
    image="/path/to/robot.jpg",
)

# Image-to-video with PIL Image
from PIL import Image
img = Image.open("robot.jpg")
stream_id = await client.start_stream(prompt="Robot dancing", image=img)

# Image-to-video with numpy array (e.g., from OpenCV)
frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
stream_id = await client.start_stream(prompt="Animate this", image=frame_rgb)
```

---

#### `interact(prompt)`

Send an interaction prompt to update the video content.

```python
async def interact(prompt: str) -> str
```

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `prompt` | `str` | The interaction prompt |

**Returns:** `str` - The acknowledged prompt when processed.

**Raises:** `OdysseyStreamError` - If not connected or no active stream.

**Example:**

```python
try:
    ack_prompt = await client.interact("Pet the cat")
    print(f"Interaction acknowledged: {ack_prompt}")
except OdysseyStreamError as e:
    print(f"Failed to interact: {e}")
```

---

#### `end_stream()`

End the current interactive stream session.

```python
async def end_stream() -> None
```

**Raises:** `OdysseyStreamError` - If not connected.

**Example:**

```python
await client.end_stream()
```

---

#### `get_recording(stream_id)`

Get recording data for a stream with presigned URLs.

```python
async def get_recording(stream_id: str) -> Recording
```

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `stream_id` | `str` | The stream ID to get recording for (from `start_stream`) |

**Returns:** `Recording` - Recording data with presigned URLs valid for ~1 hour.

**Note:** This method can be called without an active connection. It only requires a valid API key.

**Example:**

```python
recording = await client.get_recording("stream-123")
if recording.video_url:
    print(f"Video: {recording.video_url}")
    print(f"Duration: {recording.duration_seconds}s")
```

---

#### `list_stream_recordings(limit?, offset?)`

List stream recordings for the authenticated user.

```python
async def list_stream_recordings(
    limit: int | None = None,
    offset: int | None = None
) -> StreamRecordingsList
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | `int \| None` | `None` | Maximum number of recordings to return |
| `offset` | `int \| None` | `None` | Number of recordings to skip for pagination |

**Returns:** `StreamRecordingsList` - Paginated list of stream recordings.

**Note:** This method can be called without an active connection. It only requires a valid API key.

**Example:**

```python
result = await client.list_stream_recordings(limit=10)
for rec in result.recordings:
    print(f"{rec.stream_id}: {rec.duration_seconds}s ({rec.width}x{rec.height})")
print(f"Total: {result.total}")
```

---

#### `simulate(script?, scripts?, script_url?, portrait?)`

Submit an asynchronous simulation job. Simulations generate video server-side without requiring a live WebRTC connection.

```python
async def simulate(
    *,
    script: list[dict] | None = None,
    scripts: list[list[dict]] | None = None,
    script_url: str | None = None,
    portrait: bool = True,
) -> SimulationJobDetail
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `script` | `list[dict] \| None` | `None` | Single script to run |
| `scripts` | `list[list[dict]] \| None` | `None` | Batch mode - multiple scripts |
| `script_url` | `str \| None` | `None` | URL to script JSON file |
| `portrait` | `bool` | `True` | `True` for portrait (704x1280), `False` for landscape (1280x704) |

**Script Format:**

A script is a list of entries that define the video generation timeline. Each entry has a `timestamp_ms` and exactly one action type:

| Entry Type | Required Fields | Description |
|------------|-----------------|-------------|
| `start` | `prompt` | Begins video generation. Must be the first entry (timestamp 0). |
| `interact` | `prompt` | Changes the scene mid-video. Can have multiple. |
| `end` | *(none)* | Ends the video. Must be the last entry. |

```python
# Start entry - begins the video (required, must be first at timestamp 0)
{"timestamp_ms": 0, "start": {"prompt": "Description", "image": <optional>}}

# Interact entry - changes the scene (optional, can have multiple)
{"timestamp_ms": 5000, "interact": {"prompt": "Something happens"}}

# End entry - ends the video (required, must be last)
{"timestamp_ms": 10000, "end": {}}
```

**Timing Rules:**
- `timestamp_ms: 0` — First entry must be `start` at time 0
- Entries must be in chronological order
- The `end` entry's timestamp determines video duration
- Minimum recommended gap between interactions: 3000ms (3 seconds)

**Supported Image Formats (start entry only):**

The `image` field in start entries accepts:
- `str` — File path (e.g., `/path/to/image.jpg`) or base64 data URL
- `bytes` — Raw image bytes (PNG, JPEG, WebP)
- `PIL.Image.Image` — PIL Image object
- `numpy.ndarray` — RGB uint8 array with shape (height, width, 3)

Images are automatically resized server-side to match the selected orientation.

**Returns:** `SimulationJobDetail` - Job info including `job_id` for tracking.

**Raises:** `ValueError` - If invalid script options. `ConnectionError` - If API request fails.

**Note:** This method can be called without an active connection. It only requires a valid API key.

**Example:**

```python
# Text-to-video
job = await client.simulate(
    script=[
        {"timestamp_ms": 0, "start": {"prompt": "A cat sleeping"}},
        {"timestamp_ms": 5000, "interact": {"prompt": "The cat wakes up"}},
        {"timestamp_ms": 10000, "end": {}},
    ]
)

# Image-to-video with file path
job = await client.simulate(
    script=[
        {"timestamp_ms": 0, "start": {"prompt": "Robot dancing", "image": "/path/to/robot.jpg"}},
        {"timestamp_ms": 10000, "end": {}},
    ],
    portrait=False,
)

# Image-to-video with PIL Image
from PIL import Image
img = Image.open("photo.jpg")
job = await client.simulate(
    script=[
        {"timestamp_ms": 0, "start": {"prompt": "Animate this", "image": img}},
        {"timestamp_ms": 10000, "end": {}},
    ]
)
```

---

#### `get_simulate_status(job_id)`

Get the status of a simulation job, including output URLs when complete.

```python
async def get_simulate_status(job_id: str) -> SimulationJobDetail
```

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `job_id` | `str` | The job ID from `simulate()` |

**Returns:** `SimulationJobDetail` - Job status with output streams if completed.

**Raises:** `ValueError` - If job not found or not authorized. `ConnectionError` - If API request fails.

**Note:** This method can be called without an active connection.

**Example:**

```python
status = await client.get_simulate_status(job.job_id)
print(f"Status: {status.status.value}")

if status.status == SimulationJobStatus.COMPLETED:
    print(f"Video URL: {status.streams[0].video_url}")
```

---

#### `list_simulations(status?, active?, limit?, offset?)`

List the user's simulation jobs with optional filtering.

```python
async def list_simulations(
    *,
    status: SimulationJobStatus | None = None,
    active: bool | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> SimulationJobsList
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `status` | `SimulationJobStatus \| None` | `None` | Filter by job status |
| `active` | `bool \| None` | `None` | Only show active jobs (pending/dispatched/processing) |
| `limit` | `int \| None` | `None` | Maximum jobs to return (default: 20, max: 100) |
| `offset` | `int \| None` | `None` | Number of jobs to skip for pagination |

**Returns:** `SimulationJobsList` - Paginated list of simulation jobs.

**Raises:** `ValueError` - If invalid parameters or not authorized. `ConnectionError` - If API request fails.

**Note:** This method can be called without an active connection.

**Example:**

```python
# List all simulations
result = await client.list_simulations(limit=10)
for job in result.jobs:
    print(f"{job.job_id}: {job.status.value}")

# List only active jobs
active = await client.list_simulations(active=True)
```

---

#### `cancel_simulation(job_id)`

Cancel a pending or dispatched simulation job.

```python
async def cancel_simulation(job_id: str) -> SimulationJobInfo
```

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `job_id` | `str` | The job ID to cancel |

**Returns:** `SimulationJobInfo` - Cancellation confirmation.

**Raises:** `ValueError` - If job not found, not authorized, or cannot be cancelled (already processing/completed).

**Note:** This method can be called without an active connection.

**Example:**

```python
try:
    result = await client.cancel_simulation(job.job_id)
    print(f"Cancelled: {result.status.value}")
except ValueError as e:
    print(f"Cannot cancel: {e}")
```

---

### Properties

#### `is_connected`

```python
@property
def is_connected(self) -> bool
```

Whether the client is currently connected and ready.

---

#### `current_status`

```python
@property
def current_status(self) -> ConnectionStatus
```

Current connection status.

**Possible Values:** `AUTHENTICATING`, `CONNECTING`, `RECONNECTING`, `CONNECTED`, `DISCONNECTED`, `FAILED`

---

#### `current_session_id`

```python
@property
def current_session_id(self) -> str | None
```

Current session ID, or `None` if not connected.

---

## Types & Interfaces

### VideoFrame

Video frame data received from the stream.

```python
@dataclass(frozen=True, slots=True)
class VideoFrame:
    data: np.ndarray      # RGB uint8 array, shape (height, width, 3)
    width: int            # Frame width in pixels
    height: int           # Frame height in pixels
    timestamp_ms: int     # Presentation timestamp in milliseconds
```

**Example usage:**

```python
def on_frame(frame: VideoFrame) -> None:
    # OpenCV (note: OpenCV uses BGR)
    cv2.imshow("video", cv2.cvtColor(frame.data, cv2.COLOR_RGB2BGR))

    # PIL
    image = Image.fromarray(frame.data)

    # Headless processing
    processed = some_ml_model(frame.data)
```

---

### Recording

Recording data with presigned URLs for a stream.

```python
@dataclass(frozen=True, slots=True)
class Recording:
    stream_id: str              # Unique stream identifier
    video_url: str | None       # Presigned URL for video file
    events_url: str | None      # Presigned URL for events JSON
    thumbnail_url: str | None   # Presigned URL for thumbnail image
    preview_url: str | None     # Presigned URL for preview video
    frame_count: int | None     # Total number of frames
    duration_seconds: float | None  # Duration in seconds
```

**Note:** URLs are valid for a limited time (typically 1 hour).

---

### StreamRecordingInfo

Summary info for a stream recording in a list.

```python
@dataclass(frozen=True, slots=True)
class StreamRecordingInfo:
    stream_id: str              # Unique stream identifier
    width: int                  # Video width in pixels
    height: int                 # Video height in pixels
    started_at: str             # ISO 8601 timestamp
    ended_at: str | None        # ISO 8601 timestamp or None if active
    duration_seconds: float | None  # Duration in seconds
```

---

### StreamRecordingsList

Paginated list of stream recordings.

```python
@dataclass(frozen=True, slots=True)
class StreamRecordingsList:
    recordings: list[StreamRecordingInfo]  # List of recording info
    total: int                              # Total recordings available
    limit: int                              # Max per request
    offset: int                             # Recordings skipped
```

---

### ConnectionStatus

```python
class ConnectionStatus(str, Enum):
    AUTHENTICATING = "authenticating"  # Authenticating with Odyssey API
    CONNECTING = "connecting"          # Connecting to signaling server
    RECONNECTING = "reconnecting"      # Reconnecting after disconnect
    CONNECTED = "connected"            # Connected and ready
    DISCONNECTED = "disconnected"      # Disconnected (clean)
    FAILED = "failed"                  # Connection failed (fatal)
```

---

### SimulationJobStatus

```python
class SimulationJobStatus(str, Enum):
    PENDING = "pending"          # Job is queued, waiting to be dispatched
    DISPATCHED = "dispatched"    # Job has been dispatched to a worker
    PROCESSING = "processing"    # Job is currently being processed
    COMPLETED = "completed"      # Job completed successfully
    FAILED = "failed"            # Job failed
    CANCELLED = "cancelled"      # Job was cancelled by user
```

---

### SimulationStream

Output stream from a completed simulation job.

```python
@dataclass(frozen=True, slots=True)
class SimulationStream:
    stream_id: str                    # Unique stream identifier
    video_url: str | None             # Presigned URL for video file
    events_url: str | None            # Presigned URL for events JSON
    thumbnail_url: str | None         # Presigned URL for thumbnail
    preview_url: str | None           # Presigned URL for preview video
    frame_count: int | None           # Total frames in video
    duration_seconds: float | None    # Duration in seconds
    script_index: int                 # Index in batch mode (0 for single)
```

**Note:** URLs are presigned and valid for approximately 1 hour.

---

### SimulationJobInfo

Summary information for a simulation job (used in lists).

```python
@dataclass(frozen=True, slots=True)
class SimulationJobInfo:
    job_id: str                       # Unique job identifier
    status: SimulationJobStatus       # Current job status
    priority: str                     # Job priority level
    created_at: str                   # ISO 8601 timestamp
    completed_at: str | None          # ISO 8601 timestamp or None
    error_message: str | None         # Error message if failed
```

---

### SimulationJobDetail

Detailed information for a simulation job (includes output streams).

```python
@dataclass(frozen=True, slots=True)
class SimulationJobDetail:
    job_id: str                       # Unique job identifier
    status: SimulationJobStatus       # Current job status
    priority: str                     # Job priority level
    created_at: str                   # ISO 8601 timestamp
    dispatched_at: str | None         # When job was dispatched
    started_at: str | None            # When processing started
    completed_at: str | None          # When job completed
    error_message: str | None         # Error message if failed
    assigned_region: str | None       # Processing region
    retry_count: int                  # Number of retries
    streams: list[SimulationStream]   # Output streams (populated when complete)
    estimated_wait_minutes: float | None  # Estimated queue wait time
```

---

### SimulationJobsList

Paginated list of simulation jobs.

```python
@dataclass(frozen=True, slots=True)
class SimulationJobsList:
    jobs: list[SimulationJobInfo]     # List of job summaries
    total: int                        # Total jobs available
    limit: int                        # Max per request
    offset: int                       # Jobs skipped
```

---

### ClientConfig

Configuration for the Odyssey client.

```python
@dataclass
class ClientConfig:
    api_key: str                        # API key for authentication (required)
    api_url: str = "https://api.odyssey.ml"  # API URL
    dev: DevConfig = DevConfig()        # Development settings
    advanced: AdvancedConfig = AdvancedConfig()  # Advanced settings
```

---

### DevConfig

Development/debug settings.

```python
@dataclass
class DevConfig:
    signaling_url: str | None = None  # Direct signaling URL (bypasses API)
    session_id: str | None = None     # Session ID for direct connection
    debug: bool = False               # Enable debug logging
```

---

### AdvancedConfig

Advanced connection settings.

```python
@dataclass
class AdvancedConfig:
    max_retries: int = 5              # Max retry attempts
    initial_retry_delay_ms: int = 1000  # Initial retry delay
    max_retry_delay_ms: int = 2000    # Max retry delay
    retry_backoff_multiplier: float = 2.0  # Backoff multiplier
    queue_timeout_s: int = 30         # Queue timeout in seconds
```

---

## Usage Examples

### Complete Application

```python
import asyncio
import cv2
from odyssey import (
    Odyssey, VideoFrame, ConnectionStatus,
    OdysseyAuthError, OdysseyConnectionError, OdysseyStreamError,
)

class VideoApp:
    def __init__(self, api_key: str):
        self.client = Odyssey(api_key=api_key)
        self.current_frame = None
        self.running = True

    def on_frame(self, frame: VideoFrame) -> None:
        self.current_frame = cv2.cvtColor(frame.data, cv2.COLOR_RGB2BGR)

    def on_status(self, status: ConnectionStatus, message: str | None) -> None:
        print(f"Status: {status.value} - {message or ''}")

    def on_stream_error(self, reason: str, message: str) -> None:
        print(f"Stream error: {reason} - {message}")

    async def run(self) -> None:
        try:
            await self.client.connect(
                on_video_frame=self.on_frame,
                on_stream_error=self.on_stream_error,
                on_status_change=self.on_status,
            )

            await self.client.start_stream("A serene mountain landscape")

            while self.running:
                if self.current_frame is not None:
                    cv2.imshow("Odyssey", self.current_frame)

                key = cv2.waitKey(1) & 0xFF
                if key == ord("q"):
                    self.running = False
                elif key == ord("i"):
                    await self.client.interact("Add a waterfall")

                await asyncio.sleep(0.01)

            await self.client.end_stream()
        except OdysseyAuthError:
            print("Invalid API key")
        except OdysseyConnectionError as e:
            print(f"Connection failed: {e}")
        except OdysseyStreamError as e:
            print(f"Stream error: {e}")
        finally:
            await self.client.disconnect()
            cv2.destroyAllWindows()

async def main():
    app = VideoApp(api_key="ody_your_api_key_here")
    await app.run()

asyncio.run(main())
```

### Headless Processing

```python
import asyncio
from odyssey import Odyssey, VideoFrame, OdysseyConnectionError

frames_collected = []

def collect_frame(frame: VideoFrame) -> None:
    frames_collected.append(frame.data.copy())

async def main():
    client = Odyssey(api_key="ody_your_api_key_here")

    try:
        await client.connect(on_video_frame=collect_frame)
        await client.start_stream("A busy city street")

        # Collect frames for 10 seconds
        await asyncio.sleep(10)

        await client.end_stream()
    except OdysseyConnectionError as e:
        print(f"Connection failed: {e}")
    finally:
        await client.disconnect()

    print(f"Collected {len(frames_collected)} frames")
    # Process frames...

asyncio.run(main())
```

### Simulation Job

```python
import asyncio
from odyssey import Odyssey, SimulationJobStatus

async def main():
    client = Odyssey(api_key="ody_your_api_key_here")

    try:
        # Submit job
        job = await client.simulate(
            script=[
                {"timestamp_ms": 0, "start": {"prompt": "A cat sleeping on a couch"}},
                {"timestamp_ms": 5000, "interact": {"prompt": "The cat wakes up and stretches"}},
                {"timestamp_ms": 10000, "end": {}},
            ]
        )
        print(f"Job submitted: {job.job_id}")

        # Poll for completion
        while True:
            status = await client.get_simulate_status(job.job_id)
            print(f"Status: {status.status.value}")

            if status.status == SimulationJobStatus.COMPLETED:
                stream = status.streams[0]
                print(f"Video URL: {stream.video_url}")
                print(f"Duration: {stream.duration_seconds}s")
                break
            elif status.status == SimulationJobStatus.FAILED:
                print(f"Failed: {status.error_message}")
                break
            elif status.status == SimulationJobStatus.CANCELLED:
                print("Job was cancelled")
                break

            await asyncio.sleep(5)
    finally:
        await client.disconnect()

asyncio.run(main())
```

### Image-to-Video Simulation

```python
import asyncio
from PIL import Image
from odyssey import Odyssey, SimulationJobStatus

async def main():
    client = Odyssey(api_key="ody_your_api_key_here")

    # Load image (supports: file path, bytes, PIL Image, numpy array)
    img = Image.open("robot.jpg")

    try:
        job = await client.simulate(
            script=[
                {"timestamp_ms": 0, "start": {"prompt": "Robot starts dancing", "image": img}},
                {"timestamp_ms": 5000, "interact": {"prompt": "Robot does a spin"}},
                {"timestamp_ms": 10000, "end": {}},
            ],
            portrait=False,  # Landscape
        )
        print(f"Job submitted: {job.job_id}")

        # Wait for completion...
    finally:
        await client.disconnect()

asyncio.run(main())
```

---

## Error Handling

### Exceptions

The client raises exceptions for connection and stream errors:

| Exception | When Raised |
|-----------|-------------|
| `OdysseyAuthError` | Invalid API key during `connect()` |
| `OdysseyConnectionError` | Connection fails during `connect()` |
| `OdysseyStreamError` | Stream operation fails (`start_stream()`, `interact()`, `end_stream()`) |

### Async Stream Errors

For errors that occur asynchronously during streaming (e.g., server-side issues), use the `on_stream_error` callback:

```python
def on_stream_error(reason: str, message: str) -> None:
    print(f"Stream error: {reason} - {message}")

await client.connect(on_stream_error=on_stream_error)
```

### Fatal vs Non-Fatal Errors

The `on_error` handler receives a `fatal` boolean parameter:

| Fatal | Description | Action Required |
|-------|-------------|-----------------|
| `True` | Connection cannot continue | Reconnect or exit |
| `False` | Recoverable error | May retry or notify user |

### Common Errors

| Error | Description |
|-------|-------------|
| `OdysseyAuthError` | API key is invalid or expired |
| `OdysseyConnectionError: No streamers available` | No streamers available, try again later |
| `OdysseyConnectionError: Timed out waiting for a streamer` | Queue timeout expired |
| `OdysseyStreamError: Cannot start stream: client is disconnected` | Attempted operation while disconnected |

---

## Environment Variables

| Variable | Description |
|----------|-------------|
| `ODYSSEY_API_URL` | Override default API URL |
| `ODYSSEY_API_KEY` | Default API key (used by examples) |

---

## Python Version

Requires Python 3.12 or later.
