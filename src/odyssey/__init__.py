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

Two-phase auth (server mints credentials, client connects directly)::

    ```python
    # Server-side (trusted, has API key)
    server = Odyssey(api_key="ody_...")
    credentials = await server.create_client_credentials()
    # Send credentials.to_dict() to the client (e.g., via your API)

    # Client-side (no API key needed)
    credentials = ClientCredentials.from_dict(data_from_server)
    client = Odyssey()
    await client.connect_with_credentials(
        credentials=credentials,
        on_video_frame=on_frame,
    )
    await client.start_stream("A cat")
    ```
"""

from .client import Odyssey, OdysseyEventHandlers
from .config import AdvancedConfig, ClientConfig
from .exceptions import (
    AccountSuspendedError,
    ConcurrentLimitReachedError,
    MonthlyLimitReachedError,
    OdysseyAuthError,
    OdysseyConnectionError,
    OdysseyError,
    OdysseyStreamError,
    OdysseyUsageError,
    RateLimitError,
    StreamDurationExceededError,
)
from .types import (
    BroadcastInfo,
    BroadcastReadyCallback,
    ClientCredentials,
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
    SpectatorConnection,
    StatusChangeCallback,
    StreamEndedCallback,
    StreamerCapabilities,
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
    # Spectator playback
    "connect_to_stream",
    "SpectatorConnection",
    # Exceptions
    "OdysseyError",
    "OdysseyAuthError",
    "OdysseyConnectionError",
    "OdysseyStreamError",
    # Usage/Account Limit Errors (with branded ASCII art)
    "OdysseyUsageError",
    "MonthlyLimitReachedError",
    "ConcurrentLimitReachedError",
    "StreamDurationExceededError",
    "AccountSuspendedError",
    "RateLimitError",
    # Configuration
    "ClientConfig",
    "AdvancedConfig",
    # Types
    "ClientCredentials",
    "VideoFrame",
    "ConnectionStatus",
    "Recording",
    "StreamRecordingInfo",
    "StreamRecordingsList",
    "BroadcastInfo",
    "StreamerCapabilities",
    # Simulation types
    "SimulationJobStatus",
    "SimulationStream",
    "SimulationJobInfo",
    "SimulationJobDetail",
    "SimulationJobsList",
    # Callback types
    "VideoFrameCallback",
    "ConnectedCallback",
    "DisconnectedCallback",
    "StreamStartedCallback",
    "StreamEndedCallback",
    "StreamErrorCallback",
    "InteractAcknowledgedCallback",
    "BroadcastReadyCallback",
    "ErrorCallback",
    "StatusChangeCallback",
]

__version__ = "1.2.0"


async def connect_to_stream(
    webrtc_url: str,
    spectator_token: str,
    on_video_frame: VideoFrameCallback | None = None,
    on_disconnected: DisconnectedCallback | None = None,
    debug: bool = False,
) -> SpectatorConnection:
    """Connect to a broadcast stream as a spectator using WHEP.

    This function creates a receive-only WebRTC connection to view a
    broadcast stream without requiring a full Odyssey client instance.
    Use this when you have the webrtc_url and spectator_token from an
    on_broadcast_ready callback.

    Args:
        webrtc_url: The WebRTC/WHEP base URL from on_broadcast_ready.
        spectator_token: Authentication token for spectator access.
        on_video_frame: Callback invoked for each received video frame.
        on_disconnected: Callback invoked when the connection ends.
        debug: Enable debug logging.

    Returns:
        SpectatorConnection for managing the playback session.

    Raises:
        ValueError: If the spectator token is invalid (401).
        ConnectionError: If the stream is not found (404) or connection fails.

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
    from ._internal.whep import WhepConnection

    whep = WhepConnection(
        on_video_frame=on_video_frame,
        on_disconnected=on_disconnected,
        debug=debug,
    )
    await whep.connect(webrtc_url, spectator_token)
    return SpectatorConnection(_whep=whep)
