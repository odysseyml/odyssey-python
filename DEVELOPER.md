# Developer Documentation

Internal documentation for developers working on the Odyssey Python client library.

## Architecture Overview

This library is a Python port of the JavaScript `@odysseyml/odyssey` client library. The architecture mirrors the JS implementation closely to maintain consistency across language clients.

### Module Mapping

| Python Module | JavaScript Equivalent | Purpose |
|---------------|----------------------|---------|
| `client.py` | `odyssey.ts` | Main Odyssey client class |
| `_internal/auth.py` | (part of odyssey.ts) | Authentication and API client |
| `_internal/signaling.py` | `signaling.ts` | WebSocket signaling for WebRTC |
| `_internal/webrtc.py` | (part of odyssey.ts) | WebRTC peer connection handling |
| `_internal/recordings.py` | (part of odyssey.ts) | Recordings API client |
| `config.py` | `config.ts` | Configuration management |
| `types.py` | (inline in odyssey.ts) | Type definitions |

### Connection Flow

```
1. User calls client.connect()
2. Exchange API key for auth token (POST /auth/token)
3. Request session from broker (POST /sessions/request)
4. Get session token (POST /sessions/token)
5. Connect to signaling WebSocket
6. Receive SDP offer from streamer
7. Create WebRTC peer connection
8. Send SDP answer
9. Exchange ICE candidates
10. Receive video track
11. Data channels established (clientToStreamer, streamerToClient)
12. Connection complete - on_connected callback fired
```

### Data Channels

| Channel | Direction | Purpose |
|---------|-----------|---------|
| `clientToStreamer` | Client → Streamer | Send commands (start_stream, interact, end_stream) |
| `streamerToClient` | Streamer → Client | Receive events (stream_started, update_acknowledged, stream_ended) |

### Message Types

**Client → Streamer:**
- `interactive_stream_start` - Start a new stream
- `update` - Send interaction prompt
- `interactive_stream_end` - End the stream

**Streamer → Client:**
- `stream_started` - Stream is ready
- `update_acknowledged` - Interaction was processed
- `stream_ended` - Stream has ended
- `interactive_stream_error` - Stream error occurred

## Development Setup

### Prerequisites

- Python 3.12+
- uv (recommended) or pip

### Install Dependencies

```bash
cd monolith/interactive-client/python

# With uv (recommended)
uv sync

# Or with pip
pip install -e ".[dev,examples]"
```

### Run Tests

```bash
uv run pytest
```

### Lint and Format

```bash
# Lint
uv run ruff check src

# Auto-fix
uv run ruff check --fix src

# Format
uv run ruff format src

# Type check
uv run mypy src
```

### Run Example

```bash
export ODYSSEY_API_KEY="ody_your_api_key"
uv run python examples/minimal/main.py
```

## Code Structure

```
src/odyssey/
├── __init__.py           # Public exports
├── client.py             # Main Odyssey class and OdysseyEventHandlers
├── config.py             # Configuration (ClientConfig, DevConfig, AdvancedConfig)
├── types.py              # Type definitions (VideoFrame, Recording, etc.)
└── _internal/            # Internal implementation modules
    ├── __init__.py       # Internal exports
    ├── auth.py           # AuthClient - API key exchange and session management
    ├── signaling.py      # SignalingClient - WebSocket signaling for WebRTC
    ├── webrtc.py         # WebRTCConnection - Peer connection and media handling
    └── recordings.py     # RecordingsClient - Recordings API
```

## Key Design Decisions

### Async-First API

The library uses Python's native `asyncio` for all async operations. This matches the JavaScript Promise-based API and is the standard for modern Python async code.

```python
# All connection and stream methods are async
connected = await client.connect(...)
await client.start_stream(...)
await client.interact(...)
await client.end_stream()
await client.disconnect()
```

### Renderer-Agnostic Frame Delivery

Video frames are delivered as raw numpy arrays to support any rendering backend:

```python
class VideoFrame:
    data: np.ndarray      # RGB uint8, shape (H, W, 3)
    width: int
    height: int
    timestamp_ms: int
```

Users can adapt to their preferred renderer:
- OpenCV: `cv2.cvtColor(frame.data, cv2.COLOR_RGB2BGR)`
- Pygame: `pygame.surfarray.make_surface(np.transpose(frame.data, (1, 0, 2)))`
- PIL: `Image.fromarray(frame.data)`

### WebRTC via aiortc

We use [aiortc](https://github.com/aiortc/aiortc) for WebRTC support. This is a pure Python implementation that doesn't require native dependencies like libwebrtc.

### Callback-Based Events

Events are delivered via callbacks passed to `connect()`. This mirrors the JavaScript API and allows users to handle events synchronously without managing async generators.

## Working with Recordings

After a stream ends, you can retrieve recording artifacts. These methods work without an active WebRTC connection - they only require a valid API key.

```python
import asyncio
from odyssey import Odyssey

async def main():
    client = Odyssey(api_key="ody_your_api_key_here")

    # Get a specific recording
    recording = await client.get_recording("stream-123")
    if recording.video_url:
        print(f"Video: {recording.video_url}")
        print(f"Duration: {recording.duration_seconds}s")

    # List all recordings
    result = await client.list_stream_recordings(limit=10)
    for rec in result.recordings:
        print(f"{rec.stream_id}: {rec.duration_seconds}s ({rec.width}x{rec.height})")

    await client.disconnect()

asyncio.run(main())
```

There's also a CLI example for working with recordings:

```bash
# List your recordings
uv run python examples/recordings/main.py list

# Get recording details
uv run python examples/recordings/main.py get <stream_id>

# Download a recording
uv run python examples/recordings/main.py download <stream_id> --output video.mp4
```

## Future: Audio Integration

Audio support is planned but not yet implemented server-side.

## Testing Strategy

### Unit Tests

Test individual components in isolation:
- `test_config.py` - Configuration validation
- `test_types.py` - Type definitions
- `test_signaling.py` - Signaling client (with mocked WebSocket)

### Integration Tests

Test full connection flow with a mock server:
- Mock signaling server
- Mock WebRTC peer connection
- Verify message flow

### Manual Testing

Use the minimal example against a real server:
```bash
export ODYSSEY_API_KEY="ody_..."
uv run python examples/minimal/main.py --debug
```

## Release Process

1. Update version in `pyproject.toml` and `__init__.py`
2. Update CHANGELOG (if maintained)
3. Run full test suite
4. Build package: `uv build`
5. Publish to PyPI: `uv publish`
6. Sync to public repositories (see below)

## Syncing to Public Repositories

The Python client is published to two public GitHub repositories:

| Repository | Purpose | URL |
|------------|---------|-----|
| `odyssey-python` | Public library package | https://github.com/odysseyml/odyssey-python |
| `odyssey-python-client-example` | Example application | https://github.com/odysseyml/odyssey-python-client-example |

### Syncing the Library (`odyssey-python`)

After making changes to the client library, sync the source files:

```bash
# From odyssey/product/monolith/interactive-client/python

# Copy source files
cp -r src/odyssey/* ~/code/odyssey-python-api/src/odyssey/

# Copy documentation (update install URLs after copying)
cp README.md API_REFERENCE.md ~/code/odyssey-python-api/

# Update README.md install instructions (change "pip install odyssey" to GitHub URL)
# The public repo uses: pip install git+https://github.com/odysseyml/odyssey-python.git

# Commit and push
cd ~/code/odyssey-python-api
git add -A
git commit -m "Sync from monolith: <description of changes>"
git push origin main
```

**Files to sync:**
- `src/odyssey/` - All source files
- `README.md` - Update install instructions to use GitHub URL
- `API_REFERENCE.md` - Update install instructions to use GitHub URL
- `pyproject.toml` - If dependencies or metadata changed

**Files NOT to sync:**
- `DEVELOPER.md` - Internal documentation only
- `examples/` - The public repo has its own examples in a different structure

### Syncing the Example App (`odyssey-python-client-example`)

The example app at `~/code/lab/pyodyssey` demonstrates client usage:

```bash
# Update the example if API changes affect usage patterns
cd ~/code/lab/pyodyssey

# Edit main.py as needed

# Commit and push
git add -A
git commit -m "Update example: <description>"
git push origin main
```

### Keeping History Clean

For initial releases or major refactors, you may want a clean single-commit history:

```bash
cd ~/code/odyssey-python-api

# Verify you're the author of the commit you're amending
git log -1 --format='%an %ae'

# Stage and amend
git add -A
git commit --amend --no-edit

# Force push (only do this if repo isn't widely used yet)
git push --force origin main
```

### Checklist for Sync

- [ ] Source files copied (`src/odyssey/`)
- [ ] README.md updated with GitHub install URL
- [ ] API_REFERENCE.md updated with GitHub install URL
- [ ] DEVELOPER.md link removed from public README (internal only)
- [ ] Example app updated if API changed
- [ ] Both repos pushed to GitHub

## Reference Files

JavaScript implementation files for reference:
- [odyssey.ts](../javascript/src/odyssey.ts) - Main client logic
- [signaling.ts](../javascript/src/signaling.ts) - WebSocket signaling
- [config.ts](../javascript/src/config.ts) - Configuration
- [API_REFERENCE.md](../javascript/API_REFERENCE.md) - JS API docs

API types (Python):
- [api-types/](../../api-types/src/odyssey_api_types/) - Message schemas

## Troubleshooting

### Debug Logging

Enable debug logging:
```python
import logging
logging.basicConfig(level=logging.DEBUG)

# Or pass debug=True via dev config
client = Odyssey(api_key="...", dev=DevConfig(debug=True))
```

### Common Issues

**"No module named 'av'"**
- aiortc requires PyAV. Install with: `pip install av`

**"Connection failed: 403"**
- API key may be invalid or suspended

**"No streamers available"**
- No streamers are currently available. Try again later or increase `queue_timeout_s`

**Video frames not received**
- Check `on_video_frame` callback is set
- Verify WebRTC connection state is "connected"
- Check for errors in `on_error` callback
