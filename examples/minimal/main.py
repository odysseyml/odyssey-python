#!/usr/bin/env python3
"""Minimal Odyssey client example using OpenCV for video display.

Usage:
    # Set your API key
    export ODYSSEY_API_KEY="ody_your_api_key_here"

    # Run the example
    uv run python examples/minimal/main.py

    # Or with custom prompts
    uv run python examples/minimal/main.py --prompt "A cat" --interaction "Pet the cat"

Keyboard Controls:
    c - Connect to Odyssey
    s - Start stream (uses --prompt)
    i - Send interaction (uses --interaction)
    e - End stream
    d - Disconnect
    q - Quit

    p - Toggle portrait/landscape mode (before starting stream)
"""

import argparse
import asyncio
import os
import sys

import cv2
import numpy as np

# Add parent to path for development
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from odyssey import ConnectionStatus, Odyssey, VideoFrame


class MinimalClient:
    """Minimal interactive client with OpenCV display."""

    def __init__(self, api_key: str, prompt: str, interaction_prompt: str, debug: bool = False) -> None:
        self.api_key = api_key
        self.prompt = prompt
        self.interaction_prompt = interaction_prompt
        self.debug = debug

        self.client: Odyssey | None = None
        self.current_frame: np.ndarray | None = None
        self.status = "Disconnected"
        self.is_stream_active = False
        self.portrait = True

        # Window name
        self.window_name = "Odyssey - Minimal Example"

        # Notification system
        self.notification: str | None = None
        self.notification_time: float = 0
        self.notification_duration: float = 2.0  # seconds

    def show_notification(self, message: str) -> None:
        """Show a temporary notification."""
        import time

        self.notification = message
        self.notification_time = time.time()

    def on_video_frame(self, frame: VideoFrame) -> None:
        """Handle incoming video frames."""
        # Convert RGB to BGR for OpenCV
        self.current_frame = cv2.cvtColor(frame.data, cv2.COLOR_RGB2BGR)

    def on_connected(self) -> None:
        """Handle connection established."""
        self.status = "Connected"
        print("Connected to Odyssey!")

    def on_disconnected(self) -> None:
        """Handle disconnection."""
        self.status = "Disconnected"
        self.is_stream_active = False
        self.current_frame = None  # Clear frame to show connect prompt
        print("Disconnected from Odyssey")

    def on_stream_started(self, session_id: str) -> None:
        """Handle stream started."""
        self.status = f"Streaming ({session_id[:8]}...)"
        self.is_stream_active = True
        self.show_notification("Stream started!")
        print(f"Stream started: {session_id}")

    def on_stream_ended(self) -> None:
        """Handle stream ended."""
        self.status = "Connected"
        self.is_stream_active = False
        self.current_frame = None  # Clear frame to show prompt again
        print("Stream ended")

    def on_interact_acknowledged(self, prompt: str) -> None:
        """Handle interaction acknowledged."""
        print(f"Interaction acknowledged: {prompt}")

    def on_error(self, error: Exception, fatal: bool) -> None:
        """Handle errors."""
        self.status = f"Error: {error}"
        print(f"{'FATAL ' if fatal else ''}Error: {error}")

    def on_status_change(self, status: ConnectionStatus, message: str | None) -> None:
        """Handle status changes."""
        self.status = message or status.value
        if self.debug:
            print(f"Status: {status.value} - {message}")

    async def connect(self) -> bool:
        """Connect to Odyssey."""
        if self.client is None:
            self.client = Odyssey(api_key=self.api_key)

        print("Connecting...")
        self.status = "Connecting..."

        return await self.client.connect(
            on_connected=self.on_connected,
            on_disconnected=self.on_disconnected,
            on_video_frame=self.on_video_frame,
            on_stream_started=self.on_stream_started,
            on_stream_ended=self.on_stream_ended,
            on_interact_acknowledged=self.on_interact_acknowledged,
            on_error=self.on_error,
            on_status_change=self.on_status_change,
        )

    async def disconnect(self) -> None:
        """Disconnect from Odyssey."""
        if self.client:
            await self.client.disconnect()

    async def start_stream(self) -> None:
        """Start the interactive stream."""
        if self.client and self.client.is_connected:
            self.status = "Starting stream..."
            print(f"Starting stream with prompt: {self.prompt}")
            print(f"Orientation: {'portrait' if self.portrait else 'landscape'}")
            try:
                await self.client.start_stream(self.prompt, self.portrait)
            except Exception as e:
                self.status = "Connected"
                print(f"Failed to start stream: {e}")

    async def interact(self) -> None:
        """Send an interaction."""
        if self.client and self.client.is_connected and self.is_stream_active:
            prev_status = self.status
            self.status = "Sending interaction..."
            print(f"Sending interaction: {self.interaction_prompt}")
            try:
                await self.client.interact(self.interaction_prompt)
                self.status = prev_status
                self.show_notification(f"Sent: {self.interaction_prompt}")
            except Exception as e:
                self.status = prev_status
                self.show_notification(f"Error: {e}")
                print(f"Failed to send interaction: {e}")

    async def end_stream(self) -> None:
        """End the current stream."""
        if self.client and self.client.is_connected and self.is_stream_active:
            self.status = "Ending stream..."
            print("Ending stream...")
            try:
                await self.client.end_stream()
            except Exception as e:
                print(f"Failed to end stream: {e}")

    def draw_ui(self, frame: np.ndarray) -> np.ndarray:
        """Draw status overlay on frame."""
        # Add status bar at top
        h, w = frame.shape[:2]
        overlay = frame.copy()

        # Semi-transparent black bar
        cv2.rectangle(overlay, (0, 0), (w, 40), (0, 0, 0), -1)
        frame = cv2.addWeighted(overlay, 0.7, frame, 0.3, 0)

        # Status text
        cv2.putText(
            frame,
            f"Status: {self.status}",
            (10, 25),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (255, 255, 255),
            1,
        )

        # Orientation indicator
        orientation = "Portrait" if self.portrait else "Landscape"
        cv2.putText(
            frame,
            f"[{orientation}]",
            (w - 120, 25),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (200, 200, 200),
            1,
        )

        return frame

    def draw_notification(self, frame: np.ndarray) -> np.ndarray:
        """Draw fading notification in center of frame."""
        import time

        if self.notification is None:
            return frame

        elapsed = time.time() - self.notification_time
        if elapsed > self.notification_duration:
            self.notification = None
            return frame

        # Calculate fade (1.0 -> 0.0 over duration)
        fade = max(0, 1 - (elapsed / self.notification_duration))
        alpha = int(255 * fade)

        h, w = frame.shape[:2]

        # Get text size for centering
        (text_width, text_height), _ = cv2.getTextSize(self.notification, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)
        x = (w - text_width) // 2
        y = h // 2

        # Draw background rectangle with fade
        padding = 10
        overlay = frame.copy()
        cv2.rectangle(
            overlay,
            (x - padding, y - text_height - padding),
            (x + text_width + padding, y + padding),
            (0, 0, 0),
            -1,
        )
        frame = cv2.addWeighted(overlay, fade * 0.7, frame, 1 - fade * 0.7, 0)

        # Draw text with fade
        cv2.putText(
            frame,
            self.notification,
            (x, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (alpha, alpha, alpha),
            2,
        )

        return frame

    def draw_help(self, frame: np.ndarray) -> np.ndarray:
        """Draw help text at bottom."""
        h, w = frame.shape[:2]

        # Help text
        help_text = "c:Connect  s:Start  i:Interact  e:End  d:Disconnect  p:Portrait/Landscape  q:Quit"
        cv2.putText(
            frame,
            help_text,
            (10, h - 10),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.4,
            (150, 150, 150),
            1,
        )

        return frame

    async def run(self) -> None:
        """Run the main event loop."""
        # Create window
        cv2.namedWindow(self.window_name, cv2.WINDOW_NORMAL)

        def make_default_frame(text: str) -> np.ndarray:
            """Create a default frame with centered text."""
            frame = np.zeros((480, 640, 3), dtype=np.uint8)
            # Get text size to center it
            (text_width, _), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 1, 2)
            x = (640 - text_width) // 2
            cv2.putText(frame, text, (x, 240), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
            return frame

        print("\nOdyssey Minimal Example")
        print("=" * 40)
        print("Keyboard Controls:")
        print("  c - Connect")
        print("  s - Start stream")
        print("  i - Send interaction")
        print("  e - End stream")
        print("  d - Disconnect")
        print("  p - Toggle portrait/landscape")
        print("  q - Quit")
        print("=" * 40)
        print(f"Stream prompt: {self.prompt}")
        print(f"Interaction prompt: {self.interaction_prompt}")
        print()

        running = True
        while running:
            # Get frame to display
            if self.current_frame is not None:
                display_frame = self.current_frame.copy()
            elif self.client and self.client.is_connected:
                display_frame = make_default_frame("Press 's' to start stream")
            else:
                display_frame = make_default_frame("Press 'c' to connect")

            # Draw UI overlays
            display_frame = self.draw_ui(display_frame)
            display_frame = self.draw_notification(display_frame)
            display_frame = self.draw_help(display_frame)

            # Show frame
            cv2.imshow(self.window_name, display_frame)

            # Handle keyboard input (wait 1ms for key)
            key = cv2.waitKey(1) & 0xFF

            if key == ord("q"):
                # Quit
                running = False
            elif key == ord("c"):
                # Connect
                asyncio.create_task(self.connect())
            elif key == ord("d"):
                # Disconnect
                asyncio.create_task(self.disconnect())
            elif key == ord("s"):
                # Start stream
                asyncio.create_task(self.start_stream())
            elif key == ord("i"):
                # Interact
                asyncio.create_task(self.interact())
            elif key == ord("e"):
                # End stream
                asyncio.create_task(self.end_stream())
            elif key == ord("p"):
                # Toggle portrait/landscape
                self.portrait = not self.portrait
                print(f"Orientation: {'portrait' if self.portrait else 'landscape'}")

            # Allow other async tasks to run
            await asyncio.sleep(0.01)


async def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Odyssey Minimal Example")
    parser.add_argument(
        "--api-key",
        default=os.environ.get("ODYSSEY_API_KEY", ""),
        help="Odyssey API key (or set ODYSSEY_API_KEY env var)",
    )
    parser.add_argument(
        "--prompt",
        default="A cat",
        help="Prompt for stream generation",
    )
    parser.add_argument(
        "--interaction",
        default="Pet the cat",
        help="Prompt for interactions",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()

    if not args.api_key:
        print("Error: API key required. Set ODYSSEY_API_KEY or use --api-key")
        sys.exit(1)

    if args.debug:
        import logging

        logging.basicConfig(level=logging.DEBUG)

    client = MinimalClient(
        api_key=args.api_key,
        prompt=args.prompt,
        interaction_prompt=args.interaction,
        debug=args.debug,
    )

    try:
        await client.run()
    except asyncio.CancelledError:
        pass  # Normal shutdown via Ctrl+C
    finally:
        await client.disconnect()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutting down...")
