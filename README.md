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

## Requirements

- Python 3.12+
- WebRTC-capable environment

## API Overview

### Methods

| Method | Description |
|--------|-------------|
| `connect(**handlers)` | Connect to a streaming session (raises on failure) |
| `disconnect()` | Disconnect and clean up resources |
| `start_stream(prompt, portrait?)` | Start an interactive stream |
| `interact(prompt)` | Send a prompt to update the video |
| `end_stream()` | End the current stream session |
| `get_recording(stream_id)` | Get recording URLs for a stream |
| `list_stream_recordings(limit?, offset?)` | List user's stream recordings |

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

## Links

- [API Reference](API_REFERENCE.md)
- [Developer Documentation](DEVELOPER.md)
- [Get an API key](https://documentation.api.odyssey.ml/)
