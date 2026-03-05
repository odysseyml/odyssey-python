"""WHEP-based WebRTC spectator connection for broadcast playback.

This module provides a WHEP (WebRTC-HTTP Egress Protocol) client for
connecting to broadcast streams as a spectator. It's used by the
connect_to_stream() function to enable low-latency viewing of
Odyssey broadcasts.
"""

import asyncio
import contextlib
import logging
from collections.abc import Callable
from typing import Any
from urllib.parse import quote, urljoin, urlparse

import aiohttp
from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection, RTCSessionDescription
from aiortc.mediastreams import MediaStreamTrack

from ..types import VideoFrame

logger = logging.getLogger(__name__)


class WhepConnection:
    """Manages WHEP-based WebRTC connection for spectator playback.

    This class handles the WHEP handshake and video frame processing
    for spectator connections. It creates a receive-only WebRTC
    connection using bundled ICE (waiting for all candidates before
    sending the offer).

    Args:
        on_video_frame: Callback invoked for each received video frame.
        on_disconnected: Callback invoked when the connection ends.
        debug: Enable debug logging.
    """

    def __init__(
        self,
        on_video_frame: Callable[[VideoFrame], None] | None = None,
        on_disconnected: Callable[[], None] | None = None,
        debug: bool = False,
    ) -> None:
        self._debug = debug
        self._pc: RTCPeerConnection | None = None
        self._frame_task: asyncio.Task[None] | None = None
        self._on_video_frame = on_video_frame
        self._on_disconnected = on_disconnected
        self._connected = False
        self._disconnect_notified = False
        self._session_url: str | None = None
        self._http_session: aiohttp.ClientSession | None = None

    @property
    def peer_connection(self) -> RTCPeerConnection | None:
        """The underlying RTCPeerConnection, or None if not connected."""
        return self._pc

    def _log(self, msg: str) -> None:
        """Log a debug message."""
        if self._debug:
            logger.debug(f"[WHEP] {msg}")

    async def _fetch_ice_servers(self, webrtc_url: str) -> list[RTCIceServer]:
        """Fetch ICE server configuration from the broadcast server.

        Queries the /config endpoint to get TURN credentials for NAT traversal.
        Falls back to STUN-only on failure.

        Args:
            webrtc_url: The WebRTC base URL (origin is extracted for /config).

        Returns:
            List of RTCIceServer instances.
        """
        try:
            # Extract origin from URL (e.g., "https://broadcast.example.com/live/stream" -> "https://broadcast.example.com")
            parsed = urlparse(webrtc_url)
            config_url = f"{parsed.scheme}://{parsed.netloc}/config"
            self._log(f"Fetching ICE config from {config_url}")

            assert self._http_session is not None
            async with self._http_session.get(config_url, timeout=aiohttp.ClientTimeout(total=5)) as response:
                if response.ok:
                    config = await response.json()
                    ice_servers_data = config.get("iceServers", [])
                    if ice_servers_data:
                        servers = []
                        for server in ice_servers_data:
                            urls = server.get("urls", server.get("url", ""))
                            kwargs: dict[str, Any] = {"urls": urls}
                            if "username" in server:
                                kwargs["username"] = server["username"]
                            if "credential" in server:
                                kwargs["credential"] = server["credential"]
                            servers.append(RTCIceServer(**kwargs))
                        self._log(f"Got {len(servers)} ICE server(s) from config")
                        return servers
        except Exception as e:
            self._log(f"ICE config fetch failed: {e}")

        # Fall back to STUN-only
        self._log("Falling back to STUN-only ICE config")
        return [RTCIceServer(urls="stun:stun.l.google.com:19302")]

    async def connect(self, webrtc_url: str, spectator_token: str) -> None:
        """Connect to broadcast stream via WHEP.

        This performs the WHEP handshake:
        1. Fetch ICE servers from /config (TURN for NAT traversal)
        2. Create RTCPeerConnection with recvonly transceivers
        3. Create SDP offer
        4. Wait for ICE gathering (bundled ICE)
        5. POST offer to WHEP endpoint
        6. Set remote description from answer

        Args:
            webrtc_url: The WebRTC/WHEP base URL from onBroadcastReady.
            spectator_token: Authentication token for spectator access.

        Raises:
            ValueError: If the spectator token is invalid (401).
            ConnectionError: If the stream is not found (404) or WHEP fails.
        """
        self._log(f"Connecting to {webrtc_url}")

        # Create a shared HTTP session for all requests during connection
        self._http_session = aiohttp.ClientSession()

        try:
            # Fetch ICE servers (includes TURN for NAT traversal)
            ice_servers = await self._fetch_ice_servers(webrtc_url)
            config = RTCConfiguration(iceServers=ice_servers)
            self._pc = RTCPeerConnection(configuration=config)

            # Add receive-only transceivers for video and audio
            self._pc.addTransceiver("video", direction="recvonly")
            self._pc.addTransceiver("audio", direction="recvonly")

            @self._pc.on("track")
            def on_track(track: MediaStreamTrack) -> None:
                self._log(f"Received track: {track.kind}")
                if track.kind == "video":
                    self._frame_task = asyncio.create_task(self._process_video_track(track))

            @self._pc.on("connectionstatechange")
            async def on_state_change() -> None:
                if self._pc:
                    state = self._pc.connectionState
                    self._log(f"Connection state: {state}")
                    if state == "connected":
                        self._connected = True
                    elif state in ("failed", "closed"):
                        self._connected = False
                        self._notify_disconnected()

            # Create SDP offer
            offer = await self._pc.createOffer()
            await self._pc.setLocalDescription(offer)

            # Wait for ICE gathering to complete (bundled ICE approach)
            await self._wait_for_ice_gathering()

            # POST offer to WHEP endpoint
            whep_url = f"{webrtc_url}/whep?token={quote(spectator_token)}"
            async with self._http_session.post(
                whep_url,
                data=self._pc.localDescription.sdp,
                headers={"Content-Type": "application/sdp"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status == 401:
                    await self.close()
                    raise ValueError("Invalid spectator token")
                if response.status == 404:
                    await self.close()
                    raise ConnectionError("Stream not found")
                if not response.ok:
                    await self.close()
                    raise ConnectionError(f"WHEP connection failed: {response.status}")
                answer_sdp = await response.text()

                # Store WHEP session URL for teardown (per WHEP spec, Location header points to session resource)
                location = response.headers.get("Location")
                if location:
                    self._session_url = urljoin(whep_url, location)
                    self._log(f"WHEP session URL: {self._session_url}")

            # Set remote description from WHEP answer
            await self._pc.setRemoteDescription(RTCSessionDescription(sdp=answer_sdp, type="answer"))
            self._log("WHEP handshake complete, waiting for ICE connection...")

            # Wait for ICE connectivity checks + TURN relay setup to complete.
            # Without this, connect() returns before the media path is established
            # and callers think they're connected when TURN may have failed.
            await self._wait_for_connection()

            # Request an immediate keyframe via RTCP PLI so spectators joining
            # mid-stream don't have to wait for the next natural IDR frame.
            await self._request_keyframe()
        except Exception:
            await self.close()
            raise

    def _notify_disconnected(self) -> None:
        """Fire the on_disconnected callback at most once."""
        if not self._disconnect_notified and self._on_disconnected:
            self._disconnect_notified = True
            self._on_disconnected()

    async def _request_keyframe(self) -> None:
        """Send a PLI (Picture Loss Indication) to request an immediate keyframe.

        Uses aiortc's internal receiver API to send RTCP PLI feedback.
        Tested against aiortc 1.9.x — if the API changes or isn't available,
        we silently fall back to waiting for the next natural keyframe.
        """
        if not self._pc:
            return
        try:
            for transceiver in self._pc.getTransceivers():
                receiver = transceiver.receiver
                if receiver and getattr(receiver, "_track", None) and receiver._track.kind == "video":  # type: ignore[union-attr]
                    # aiortc's RTCRtpReceiver exposes _send_rtcp_pli internally
                    send_pli = getattr(receiver, "_send_rtcp_pli", None)
                    if callable(send_pli):
                        result = send_pli(0)
                        # _send_rtcp_pli is async in aiortc — await if coroutine
                        if asyncio.iscoroutine(result):
                            await result
                        self._log("Sent PLI keyframe request")
                        return
            self._log("No video receiver found for PLI")
        except Exception as e:
            self._log(f"PLI request failed (will wait for natural keyframe): {e}")

    async def _wait_for_ice_gathering(self) -> None:
        """Wait for ICE gathering to complete.

        Uses bundled ICE approach - waits for all candidates to be gathered
        before proceeding. Falls back to a 5 second timeout if gathering
        doesn't complete (e.g., in some network configurations).
        """
        if not self._pc or self._pc.iceGatheringState == "complete":
            return

        done = asyncio.Event()

        @self._pc.on("icegatheringstatechange")
        def check() -> None:
            if self._pc and self._pc.iceGatheringState == "complete":
                done.set()

        try:
            await asyncio.wait_for(done.wait(), timeout=5.0)
        except TimeoutError:
            self._log("ICE gathering timeout, proceeding with available candidates")

    async def _wait_for_connection(self) -> None:
        """Wait for the WebRTC connection to be established.

        After the WHEP handshake, ICE connectivity checks and TURN relay
        setup happen asynchronously.  This method blocks until the
        connection state reaches 'connected' — or raises if it fails.

        Raises:
            ConnectionError: If ICE negotiation fails (e.g. TURN 403).
        """
        if not self._pc:
            return
        if self._pc.connectionState == "connected":
            return

        done = asyncio.Event()
        failure_reason: list[str] = []

        @self._pc.on("connectionstatechange")
        async def on_state() -> None:
            if not self._pc:
                return
            state = self._pc.connectionState
            self._log(f"Connection state (waiting): {state}")
            if state == "connected":
                done.set()
            elif state in ("failed", "closed"):
                failure_reason.append(state)
                done.set()

        try:
            await asyncio.wait_for(done.wait(), timeout=15.0)
        except TimeoutError:
            await self.close()
            raise ConnectionError("WebRTC connection timed out waiting for ICE") from None

        if failure_reason:
            await self.close()
            raise ConnectionError(f"WebRTC connection {failure_reason[0]} (ICE/TURN negotiation failed)")

        self._log("WebRTC connection established")

    async def _process_video_track(self, track: MediaStreamTrack) -> None:
        """Process video frames from the track.

        Converts each frame to a VideoFrame and invokes the callback.
        Continues until the track ends or an error occurs.
        """
        self._log("Starting video frame processing")
        try:
            while True:
                frame = await track.recv()
                if self._on_video_frame:
                    # Convert frame to numpy array (RGB)
                    img = frame.to_ndarray(format="rgb24")  # type: ignore[union-attr]

                    # Calculate timestamp in milliseconds
                    pts = getattr(frame, "pts", None)
                    time_base = getattr(frame, "time_base", None)
                    timestamp_ms = 0
                    if pts is not None and time_base is not None:
                        timestamp_ms = int(pts * float(time_base) * 1000)

                    try:
                        self._on_video_frame(
                            VideoFrame(
                                data=img,
                                width=img.shape[1],
                                height=img.shape[0],
                                timestamp_ms=timestamp_ms,
                            )
                        )
                    except Exception as cb_err:
                        self._log(f"on_video_frame callback error: {cb_err}")
        except Exception as e:
            self._log(f"Video track ended: {e}")
            self._connected = False
            self._notify_disconnected()

    @property
    def is_connected(self) -> bool:
        """Check if the connection is currently active."""
        return self._connected

    async def close(self) -> None:
        """Close the WHEP connection and clean up resources.

        Sends a WHEP DELETE to tear down the server-side session, then closes the local peer connection.
        """
        # Only send WHEP DELETE if the connection is still active (spectator is voluntarily leaving).
        # When the stream ends, MediaMTX tears down all WHEP sessions first, which triggers our
        # ICE disconnect — so by the time close() is called, the session is already gone.
        if self._session_url and self._connected and self._http_session:
            try:
                async with self._http_session.delete(self._session_url, timeout=aiohttp.ClientTimeout(total=5)):
                    self._log("WHEP session deleted")
            except Exception as e:
                self._log(f"WHEP DELETE failed (session will time out): {e}")
        self._session_url = None
        self._connected = False
        self._disconnect_notified = False

        # Cancel frame processing task
        if self._frame_task:
            self._frame_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._frame_task
            self._frame_task = None

        # Close peer connection
        if self._pc:
            await self._pc.close()
            self._pc = None

        # Close shared HTTP session
        if self._http_session:
            await self._http_session.close()
            self._http_session = None
