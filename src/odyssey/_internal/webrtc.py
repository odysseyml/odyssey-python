"""WebRTC connection handling for Odyssey client."""

import asyncio
import contextlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import aiohttp
from aiortc import RTCConfiguration, RTCIceCandidate, RTCIceServer, RTCPeerConnection, RTCSessionDescription
from aiortc.mediastreams import MediaStreamTrack
from aiortc.sdp import candidate_from_sdp

from ..exceptions import OdysseyStreamError
from ..types import VideoFrame

logger = logging.getLogger(__name__)


@dataclass
class WebRTCCallbacks:
    """Callbacks for WebRTC events."""

    on_connected: Callable[[], None] | None = None
    on_video_frame: Callable[[VideoFrame], None] | None = None
    on_stream_started: Callable[[str], None] | None = None
    on_stream_ended: Callable[[], None] | None = None
    on_interact_acknowledged: Callable[[str], None] | None = None
    on_stream_error: Callable[[str, str], None] | None = None  # reason, message
    on_error: Callable[[Exception, bool], None] | None = None


class WebRTCConnection:
    """Manages WebRTC peer connection and data channels."""

    def __init__(self, debug: bool = False) -> None:
        """Create a WebRTCConnection.

        Args:
            debug: Enable debug logging.
        """
        self._debug = debug
        self._pc: RTCPeerConnection | None = None
        self._ice_servers: list[dict[str, Any]] = []
        self._callbacks = WebRTCCallbacks()

        # Data channels
        self._client_to_streamer_channel: Any = None
        self._streamer_to_client_channel: Any = None

        # Video frame task
        self._frame_task: asyncio.Task[None] | None = None

        # Promise-like futures for async operations
        self._stream_start_future: asyncio.Future[str] | None = None
        self._interact_future: asyncio.Future[str] | None = None
        self._stream_end_future: asyncio.Future[None] | None = None

    def _log(self, msg: str) -> None:
        """Log a debug message."""
        if self._debug:
            logger.debug(f"[WebRTC] {msg}")

    def set_callbacks(self, callbacks: WebRTCCallbacks) -> None:
        """Set event callbacks."""
        self._callbacks = callbacks

    async def fetch_ice_servers(self, signaling_url: str) -> None:
        """Fetch ICE servers from signaling server."""
        try:
            # Convert ws:// or wss:// to http:// or https://
            http_url = signaling_url.replace("ws://", "http://").replace("wss://", "https://")

            async with aiohttp.ClientSession() as session, session.get(f"{http_url}/config") as response:
                config = await response.json()
                self._ice_servers = config.get("iceServers", [])
                self._log(f"Fetched ICE servers: {self._ice_servers}")

        except Exception as e:
            # Fallback to Google STUN if config fetch fails
            self._ice_servers = [{"urls": "stun:stun.l.google.com:19302"}]
            self._log(f"Failed to fetch ICE servers, using fallback: {e}")

    async def handle_offer(self, sdp: str, signaling_send: Callable[[dict[str, Any]], Any]) -> None:
        """Handle SDP offer from server.

        Args:
            sdp: The SDP offer string.
            signaling_send: Callback to send messages via signaling.
        """
        # Create peer connection with ICE servers
        ice_servers = [RTCIceServer(urls=server["urls"]) for server in self._ice_servers if "urls" in server]
        config = RTCConfiguration(iceServers=ice_servers) if ice_servers else None
        self._pc = RTCPeerConnection(configuration=config)

        # Setup event handlers
        @self._pc.on("track")
        def on_track(track: MediaStreamTrack) -> None:
            self._log(f"Received track: {track.kind}")
            if track.kind == "video":
                self._frame_task = asyncio.create_task(self._process_video_track(track))

        @self._pc.on("connectionstatechange")
        async def on_connection_state_change() -> None:
            if self._pc:
                state = self._pc.connectionState
                self._log(f"Connection state: {state}")

                if state == "connected" and self._callbacks.on_connected:
                    self._callbacks.on_connected()

        @self._pc.on("iceconnectionstatechange")
        async def on_ice_connection_state_change() -> None:
            if self._pc:
                self._log(f"ICE connection state: {self._pc.iceConnectionState}")

        @self._pc.on("icecandidate")
        async def on_ice_candidate(candidate: RTCIceCandidate | None) -> None:
            if candidate:
                self._log("Sending ICE candidate")
                candidate_str = getattr(candidate, "candidate", "")
                sdp_mid = getattr(candidate, "sdpMid", None)
                sdp_m_line_index = getattr(candidate, "sdpMLineIndex", None)
                await signaling_send(
                    {
                        "type": "ice_candidate",
                        "candidate": candidate_str,
                        "sdpMid": sdp_mid,
                        "sdpMLineIndex": sdp_m_line_index,
                    }
                )

        @self._pc.on("datachannel")
        def on_datachannel(channel: Any) -> None:
            label = channel.label
            self._log(f"Data channel received: {label}")

            if label == "clientToStreamer":
                self._client_to_streamer_channel = channel
                self._setup_client_to_streamer_channel()
            elif label == "streamerToClient":
                self._streamer_to_client_channel = channel
                self._setup_streamer_to_client_channel()
            else:
                self._log(f"Unknown data channel: {label}")

        # Set remote description
        await self._pc.setRemoteDescription(RTCSessionDescription(sdp=sdp, type="offer"))

        # Create and send answer
        answer = await self._pc.createAnswer()
        await self._pc.setLocalDescription(answer)

        await signaling_send(
            {
                "type": "answer",
                "sdp": self._pc.localDescription.sdp,
            }
        )

        self._log("Sent answer")

    async def handle_ice_candidate(self, candidate_str: str, sdp_mid: str | None, sdp_m_line_index: int | None) -> None:
        """Handle ICE candidate from server."""
        if self._pc and candidate_str:
            # aiortc parses ICE candidates from SDP format
            if not candidate_str.startswith("candidate:"):
                candidate_str = f"candidate:{candidate_str}"

            try:
                candidate = candidate_from_sdp(candidate_str)
                candidate.sdpMid = sdp_mid
                candidate.sdpMLineIndex = sdp_m_line_index
                await self._pc.addIceCandidate(candidate)
                self._log("Added ICE candidate")
            except Exception as e:
                self._log(f"Failed to parse ICE candidate: {e}")

    async def _process_video_track(self, track: MediaStreamTrack) -> None:
        """Process video frames from track."""
        self._log("Starting video frame processing")
        try:
            while True:
                frame = await track.recv()

                if self._callbacks.on_video_frame:
                    # Convert frame to numpy array (RGB)
                    img = frame.to_ndarray(format="rgb24")  # type: ignore[union-attr]

                    # Calculate timestamp
                    timestamp_ms = 0
                    pts = getattr(frame, "pts", None)
                    time_base = getattr(frame, "time_base", None)
                    if pts is not None and time_base is not None:
                        timestamp_ms = int(pts * 1000 / time_base.denominator)

                    video_frame = VideoFrame(
                        data=img,
                        width=img.shape[1],
                        height=img.shape[0],
                        timestamp_ms=timestamp_ms,
                    )

                    self._callbacks.on_video_frame(video_frame)

        except Exception as e:
            self._log(f"Video track ended: {e}")

    def _setup_client_to_streamer_channel(self) -> None:
        """Setup client -> streamer data channel."""
        if not self._client_to_streamer_channel:
            return

        @self._client_to_streamer_channel.on("open")  # type: ignore[untyped-decorator]
        def on_open() -> None:
            self._log("Client -> Streamer channel open")

        @self._client_to_streamer_channel.on("close")  # type: ignore[untyped-decorator]
        def on_close() -> None:
            self._log("Client -> Streamer channel closed")

    def _setup_streamer_to_client_channel(self) -> None:
        """Setup streamer -> client data channel."""
        if not self._streamer_to_client_channel:
            return

        @self._streamer_to_client_channel.on("open")  # type: ignore[untyped-decorator]
        def on_open() -> None:
            self._log("Streamer -> Client channel open")

        @self._streamer_to_client_channel.on("close")  # type: ignore[untyped-decorator]
        def on_close() -> None:
            self._log("Streamer -> Client channel closed")

        @self._streamer_to_client_channel.on("message")  # type: ignore[untyped-decorator]
        def on_message(message: str) -> None:
            try:
                data = json.loads(message)
                self._log(f"Received message from streamer: {data}")

                msg_type = data.get("type")

                if msg_type == "stream_started":
                    stream_id = data.get("stream_id", "")
                    if self._stream_start_future and not self._stream_start_future.done():
                        self._stream_start_future.set_result(stream_id)
                    if self._callbacks.on_stream_started:
                        self._callbacks.on_stream_started(stream_id)

                elif msg_type == "update_acknowledged":
                    prompt = data.get("prompt", "")
                    if self._interact_future and not self._interact_future.done():
                        self._interact_future.set_result(prompt)
                    if self._callbacks.on_interact_acknowledged:
                        self._callbacks.on_interact_acknowledged(prompt)

                elif msg_type == "stream_ended":
                    if self._stream_end_future and not self._stream_end_future.done():
                        self._stream_end_future.set_result(None)
                    if self._callbacks.on_stream_ended:
                        self._callbacks.on_stream_ended()

                elif msg_type == "interactive_stream_error":
                    reason = data.get("reason", "unknown")
                    err_message = data.get("message", "Stream error occurred")
                    logger.error(f"Interactive stream error: {reason} - {err_message}")

                    # Reject pending futures with exception
                    stream_err = OdysseyStreamError(f"{reason}: {err_message}")
                    if self._stream_start_future and not self._stream_start_future.done():
                        self._stream_start_future.set_exception(stream_err)
                    if self._interact_future and not self._interact_future.done():
                        self._interact_future.set_exception(stream_err)

                    # Call the stream error callback
                    if self._callbacks.on_stream_error:
                        self._callbacks.on_stream_error(reason, err_message)

            except Exception as e:
                if self._callbacks.on_error:
                    self._callbacks.on_error(e, False)

    def send_event(self, event: dict[str, Any]) -> None:
        """Send an event to the streamer via data channel."""
        if not self._client_to_streamer_channel:
            raise ConnectionError("Client to streamer channel not open")

        self._log(f"Sending event: {event}")
        self._client_to_streamer_channel.send(json.dumps(event))

    async def start_stream(self, prompt: str, portrait: bool) -> str:
        """Start an interactive stream session.

        Returns:
            Session ID when the stream is ready.
        """
        self._stream_start_future = asyncio.get_event_loop().create_future()

        self.send_event(
            {
                "type": "interactive_stream_start",
                "prompt": prompt,
                "portrait": portrait,
            }
        )

        return await self._stream_start_future

    async def interact(self, prompt: str) -> str:
        """Send an interaction prompt.

        Returns:
            The acknowledged prompt.
        """
        self._interact_future = asyncio.get_event_loop().create_future()

        self.send_event(
            {
                "type": "update",
                "prompt": prompt,
            }
        )

        return await self._interact_future

    async def end_stream(self) -> None:
        """End the current interactive stream session."""
        self._stream_end_future = asyncio.get_event_loop().create_future()

        self.send_event(
            {
                "type": "interactive_stream_end",
            }
        )

        await self._stream_end_future

    async def close(self) -> None:
        """Close the WebRTC connection."""
        # Cancel frame task
        if self._frame_task:
            self._frame_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._frame_task
            self._frame_task = None

        # Clear futures
        self._stream_start_future = None
        self._interact_future = None
        self._stream_end_future = None

        # Close data channels
        self._client_to_streamer_channel = None
        self._streamer_to_client_channel = None

        # Close peer connection
        if self._pc:
            await self._pc.close()
            self._pc = None

    @property
    def is_data_channel_open(self) -> bool:
        """Check if data channel is ready."""
        return self._client_to_streamer_channel is not None
