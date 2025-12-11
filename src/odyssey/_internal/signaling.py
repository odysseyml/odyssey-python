"""WebSocket signaling client for WebRTC negotiation."""

import asyncio
import contextlib
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlencode

import websockets
from websockets.asyncio.client import ClientConnection

logger = logging.getLogger(__name__)

# Heartbeat interval in seconds
HEARTBEAT_INTERVAL_S = 10.0

type SignalingMessage = dict[str, Any]
type MessageHandler = Callable[[SignalingMessage], Awaitable[None] | None]


class SignalingClient:
    """WebSocket client for WebRTC signaling.

    Handles connection to the signaling server, message routing,
    and keepalive heartbeats.
    """

    def __init__(
        self,
        debug: bool = False,
        on_close: Callable[[int, str], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
    ) -> None:
        """Initialize the signaling client.

        Args:
            debug: Enable debug logging.
            on_close: Callback when connection closes (code, reason).
            on_error: Callback when an error occurs.
        """
        self._debug = debug
        self._on_close = on_close
        self._on_error = on_error

        self._ws: ClientConnection | None = None
        self._message_handlers: dict[str, list[MessageHandler]] = {}
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._receive_task: asyncio.Task[None] | None = None
        self._connected = False

    def _log(self, msg: str, *args: Any) -> None:
        """Log a debug message."""
        if self._debug:
            logger.debug(f"[Signaling] {msg}", *args)

    def _error(self, msg: str, *args: Any) -> None:
        """Log an error message."""
        logger.error(f"[Signaling] {msg}", *args)

    def _normalize_url(self, url: str) -> str:
        """Normalize signaling URL to ensure it uses ws:// or wss:// protocol."""
        # Remove trailing slashes
        url = url.rstrip("/")

        # If already has ws:// or wss://, return as is
        if url.startswith("ws://") or url.startswith("wss://"):
            return url

        # Replace http:// with ws:// and https:// with wss://
        if url.startswith("https://"):
            return url.replace("https://", "wss://", 1)
        if url.startswith("http://"):
            return url.replace("http://", "ws://", 1)

        # No protocol specified, add ws://
        return f"ws://{url}"

    async def connect(
        self,
        signaling_url: str,
        session_id: str,
        session_token: str | None = None,
    ) -> None:
        """Connect to the signaling server.

        Args:
            signaling_url: WebSocket URL of the signaling server.
            session_id: Session ID to connect to.
            session_token: Optional session token for authentication.

        Raises:
            ConnectionError: If connection fails.
        """
        normalized_url = self._normalize_url(signaling_url)
        url = f"{normalized_url}/client/{session_id}"

        # Add session token as query parameter if provided
        if session_token:
            url += f"?{urlencode({'token': session_token})}"

        self._log(f"Connecting to {url}")

        try:
            self._ws = await websockets.connect(url)
            self._connected = True
            self._log("WebSocket connection opened")

            # Start heartbeat and receive tasks
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            self._receive_task = asyncio.create_task(self._receive_loop())

        except Exception as e:
            self._error(f"Connection failed: {e}")
            raise ConnectionError(f"Failed to connect to signaling server: {e}") from e

    async def _heartbeat_loop(self) -> None:
        """Send periodic heartbeat messages."""
        self._log(f"Started heartbeat (interval: {HEARTBEAT_INTERVAL_S}s)")
        try:
            while self._connected and self._ws:
                await asyncio.sleep(HEARTBEAT_INTERVAL_S)
                if self._connected and self._ws:
                    try:
                        await self._ws.send(json.dumps({"type": "keepalive"}))
                        self._log("Sent keepalive")
                    except Exception as e:
                        self._log(f"Failed to send keepalive: {e}")
                        break
        except asyncio.CancelledError:
            self._log("Heartbeat cancelled")
        finally:
            self._log("Stopped heartbeat")

    async def _receive_loop(self) -> None:
        """Receive and dispatch messages from the server."""
        try:
            if not self._ws:
                return

            async for raw_message in self._ws:
                if isinstance(raw_message, bytes):
                    raw_message = raw_message.decode("utf-8")

                try:
                    message: SignalingMessage = json.loads(raw_message)
                    self._log(f"Received: {message}")
                    await self._handle_message(message)
                except json.JSONDecodeError as e:
                    self._error(f"Failed to parse message: {e}")

        except websockets.ConnectionClosed as e:
            self._log(f"Connection closed: code={e.code}, reason={e.reason}")
            self._connected = False
            if self._on_close:
                self._on_close(e.code, e.reason)

        except Exception as e:
            self._error(f"Receive error: {e}")
            self._connected = False
            if self._on_error:
                self._on_error(e)

    async def _handle_message(self, message: SignalingMessage) -> None:
        """Dispatch message to registered handlers."""
        msg_type = message.get("type")
        if not msg_type:
            self._log("Message missing type field")
            return

        handlers = self._message_handlers.get(msg_type, [])
        for handler in handlers:
            try:
                result = handler(message)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                self._error(f"Handler error for {msg_type}: {e}")

    def on(self, msg_type: str, handler: MessageHandler) -> None:
        """Register a handler for a specific message type.

        Args:
            msg_type: Message type to handle (e.g., "offer", "ice_candidate").
            handler: Callback function (can be sync or async).
        """
        if msg_type not in self._message_handlers:
            self._message_handlers[msg_type] = []
        self._message_handlers[msg_type].append(handler)

    def off(self, msg_type: str, handler: MessageHandler) -> None:
        """Remove a handler for a specific message type.

        Args:
            msg_type: Message type.
            handler: Handler to remove.
        """
        if msg_type in self._message_handlers:
            with contextlib.suppress(ValueError):
                self._message_handlers[msg_type].remove(handler)

    async def send(self, message: SignalingMessage) -> None:
        """Send a message to the signaling server.

        Args:
            message: Message to send (will be JSON-encoded).

        Raises:
            ConnectionError: If not connected.
        """
        if not self._ws or not self._connected:
            raise ConnectionError("Signaling client not connected")

        self._log(f"Sending: {message}")
        await self._ws.send(json.dumps(message))

    async def close(self) -> None:
        """Close the signaling connection."""
        self._connected = False

        # Cancel background tasks
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._heartbeat_task
            self._heartbeat_task = None

        if self._receive_task:
            self._receive_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._receive_task
            self._receive_task = None

        # Close WebSocket
        if self._ws:
            await self._ws.close(1000, "Client disconnect")
            self._ws = None

        self._log("Connection closed")

    @property
    def is_connected(self) -> bool:
        """Check if connected to the signaling server."""
        return self._connected and self._ws is not None
