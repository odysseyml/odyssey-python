"""Python client for Odyssey's audio-visual intelligence platform.

Example:
    ```python
    from odyssey import Odyssey, VideoFrame, OdysseyAuthError, OdysseyConnectionError

    client = Odyssey(api_key="ody_...")

    def on_frame(frame: VideoFrame) -> None:
        # Process frame.data (numpy array, RGB, shape: H x W x 3)
        pass

    try:
        await client.connect(
            on_video_frame=on_frame,
            on_stream_started=lambda sid: print(f"Stream started: {sid}"),
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

from .client import Odyssey, OdysseyEventHandlers
from .config import AdvancedConfig, ClientConfig, DevConfig
from .exceptions import OdysseyAuthError, OdysseyConnectionError, OdysseyError, OdysseyStreamError
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
    VideoFrame,
    VideoFrameCallback,
)

__all__ = [
    # Main client
    "Odyssey",
    "OdysseyEventHandlers",
    # Exceptions
    "OdysseyError",
    "OdysseyAuthError",
    "OdysseyConnectionError",
    "OdysseyStreamError",
    # Configuration
    "ClientConfig",
    "DevConfig",
    "AdvancedConfig",
    # Types
    "VideoFrame",
    "ConnectionStatus",
    "Recording",
    "StreamRecordingInfo",
    "StreamRecordingsList",
    # Callback types
    "VideoFrameCallback",
    "ConnectedCallback",
    "DisconnectedCallback",
    "StreamStartedCallback",
    "StreamEndedCallback",
    "StreamErrorCallback",
    "InteractAcknowledgedCallback",
    "ErrorCallback",
    "StatusChangeCallback",
]

__version__ = "0.1.0"
