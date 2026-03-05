# odyssey

Python client for Odyssey's audio-visual intelligence platform.

## Install

```bash
pip install git+https://github.com/odysseyml/odyssey-python.git
```

Or with uv:

```bash
uv pip install git+https://github.com/odysseyml/odyssey-python.git
```

## Quick Start

```python
import asyncio
from odyssey import Odyssey, OdysseyAuthError, OdysseyConnectionError

async def main():
    client = Odyssey(api_key="ody_your_api_key_here")

    try:
        await client.connect(
            on_video_frame=lambda frame: print(f"Frame: {frame.width}x{frame.height}"),
            on_stream_started=lambda stream_id: print(f"Stream started: {stream_id}"),
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

## Display with OpenCV

```python
import asyncio
import cv2
from odyssey import Odyssey, VideoFrame, OdysseyConnectionError

current_frame = None

def on_frame(frame: VideoFrame) -> None:
    global current_frame
    # Convert RGB to BGR for OpenCV
    current_frame = cv2.cvtColor(frame.data, cv2.COLOR_RGB2BGR)

async def main():
    client = Odyssey(api_key="ody_your_api_key_here")

    try:
        await client.connect(on_video_frame=on_frame)
        await client.start_stream("A serene beach at sunset")

        # Display loop
        while True:
            if current_frame is not None:
                cv2.imshow("Odyssey", current_frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

        await client.end_stream()
    except OdysseyConnectionError as e:
        print(f"Connection failed: {e}")
    finally:
        await client.disconnect()
        cv2.destroyAllWindows()

asyncio.run(main())
```

## Image-to-Video (i2v)

Start a stream from an image (supports file path, bytes, PIL Image, or numpy array):

```python
# From file path
await client.start_stream(
    prompt="The robot starts dancing",
    portrait=False,
    image="/path/to/robot.jpg",
)

# From PIL Image
from PIL import Image
img = Image.open("robot.jpg")
await client.start_stream(prompt="Robot dancing", image=img)

# From numpy array (e.g., OpenCV frame)
frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
await client.start_stream(prompt="Animate this", image=frame_rgb)
```

## Broadcast Mode (Spectators)

Enable broadcast to allow spectators to watch via WebRTC/HLS without a direct Odyssey connection:

```python
from odyssey import Odyssey, BroadcastInfo

def on_broadcast_ready(info: BroadcastInfo) -> None:
    print(f"WebRTC: {info.webrtc_url}")
    print(f"HLS: {info.hls_url}")

await client.connect(on_broadcast_ready=on_broadcast_ready)
await client.start_stream("A sunset", broadcast=True)
```

**Note:** Requires MediaMTX running with `ODYSSEY_ENABLE_BROADCAST=true` on the streamer.

## Requirements

- Python 3.12+
- WebRTC-capable environment

## Simulation (Async Video Generation)

Generate video asynchronously without a live connection:

```python
import asyncio
from odyssey import Odyssey, SimulationJobStatus

async def main():
    client = Odyssey(api_key="ody_your_api_key_here")

    # Submit a simulation job
    job = await client.simulate(
        script=[
            {"timestamp_ms": 0, "start": {"prompt": "A cat sleeping on a couch"}},
            {"timestamp_ms": 5000, "interact": {"prompt": "The cat wakes up"}},
            {"timestamp_ms": 10000, "end": {}},
        ]
    )
    print(f"Job submitted: {job.job_id}")

    # Poll for completion
    while True:
        status = await client.get_simulate_status(job.job_id)
        print(f"Status: {status.status.value}")

        if status.status == SimulationJobStatus.COMPLETED:
            print(f"Video URL: {status.streams[0].video_url}")
            break
        elif status.status in (SimulationJobStatus.FAILED, SimulationJobStatus.CANCELLED):
            print(f"Job failed: {status.error_message}")
            break

        await asyncio.sleep(5)

    await client.disconnect()

asyncio.run(main())
```

## API Overview

### Interactive Streaming Methods

| Method | Description |
|--------|-------------|
| `connect(**handlers)` | Connect to a streaming session (raises on failure) |
| `disconnect()` | Disconnect and clean up resources |
| `start_stream(prompt, portrait?, image?, broadcast?)` | Start an interactive stream |
| `interact(prompt)` | Send a prompt to update the video |
| `end_stream()` | End the current stream session |
| `get_recording(stream_id)` | Get recording URLs for a stream |
| `list_stream_recordings(limit?, offset?)` | List user's stream recordings |

### Simulation Methods (No Connection Required)

| Method | Description |
|--------|-------------|
| `simulate(script?, scripts?, script_url?, portrait?)` | Submit an async simulation job |
| `get_simulate_status(job_id)` | Get job status and output URLs |
| `list_simulations(status?, active?, limit?, offset?)` | List user's simulation jobs |
| `cancel_simulation(job_id)` | Cancel a pending/dispatched job |

### Exceptions

| Exception | Description |
|-----------|-------------|
| `OdysseyError` | Base exception for all Odyssey errors |
| `OdysseyAuthError` | Authentication failed (invalid API key) |
| `OdysseyConnectionError` | Connection failed (no streamers, timeout) |
| `OdysseyStreamError` | Stream operation failed |

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
| `on_broadcast_ready` | `info: BroadcastInfo` | Broadcast URLs available |
| `on_interact_acknowledged` | `prompt: str` | Interaction processed |
| `on_stream_error` | `reason, message` | Stream error occurred |
| `on_error` | `error, fatal` | Transient error occurred |
| `on_status_change` | `status, message` | Connection status changed |

### VideoFrame

```python
@dataclass
class VideoFrame:
    data: np.ndarray      # RGB uint8 array, shape (H, W, 3)
    width: int
    height: int
    timestamp_ms: int
```

### BroadcastInfo

```python
@dataclass
class BroadcastInfo:
    hls_url: str | None           # HLS playback URL (may be None if HLS disabled)
    webrtc_url: str | None        # WebRTC/WHEP playback URL
    spectator_token: str | None   # Authentication token for spectator access
```

## Links

- [API Reference](API_REFERENCE.md)
- [Get an API key](https://documentation.api.odyssey.ml/)
