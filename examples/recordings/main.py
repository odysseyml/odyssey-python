#!/usr/bin/env python3
"""Example CLI for listing and retrieving stream recordings.

Usage:
    # Set your API key
    export ODYSSEY_API_KEY="ody_your_api_key_here"

    # List your recordings
    uv run python examples/recordings/main.py list

    # List with pagination
    uv run python examples/recordings/main.py list --limit 5 --offset 0

    # Get a specific recording
    uv run python examples/recordings/main.py get <stream_id>

    # Download a recording video
    uv run python examples/recordings/main.py download <stream_id> --output video.mp4
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

import aiohttp

from odyssey import Odyssey, Recording


async def list_recordings(client: Odyssey, limit: int | None, offset: int | None) -> None:
    """List stream recordings."""
    print("Fetching recordings...")
    result = await client.list_stream_recordings(limit=limit, offset=offset)

    if not result.recordings:
        print("No recordings found.")
        return

    print(f"\nFound {result.total} recordings (showing {len(result.recordings)}):\n")
    print(f"{'Stream ID':<40} {'Size':<12} {'Duration':<12} {'Started':<20}")
    print("-" * 84)

    for rec in result.recordings:
        size = f"{rec.width}x{rec.height}"
        duration = f"{rec.duration_seconds:.1f}s" if rec.duration_seconds else "N/A"
        started = rec.started_at[:19].replace("T", " ") if rec.started_at else "N/A"
        print(f"{rec.stream_id:<40} {size:<12} {duration:<12} {started:<20}")

    print()
    if result.total > len(result.recordings):
        print(f"Use --offset {result.offset + len(result.recordings)} to see more.")


async def get_recording(client: Odyssey, stream_id: str) -> Recording:
    """Get recording details."""
    print(f"Fetching recording {stream_id}...")
    recording = await client.get_recording(stream_id)

    print(f"\nRecording: {recording.stream_id}")
    print("-" * 50)

    if recording.duration_seconds:
        print(f"Duration: {recording.duration_seconds:.1f} seconds")
    if recording.frame_count:
        print(f"Frames: {recording.frame_count}")

    print("\nURLs (valid for ~1 hour):")
    if recording.video_url:
        print(f"  Video: {recording.video_url[:80]}...")
    if recording.thumbnail_url:
        print(f"  Thumbnail: {recording.thumbnail_url[:80]}...")
    if recording.preview_url:
        print(f"  Preview: {recording.preview_url[:80]}...")
    if recording.events_url:
        print(f"  Events: {recording.events_url[:80]}...")

    return recording


async def download_recording(client: Odyssey, stream_id: str, output: str) -> None:
    """Download a recording video."""
    recording = await client.get_recording(stream_id)

    if not recording.video_url:
        print(f"Error: No video URL available for {stream_id}")
        sys.exit(1)

    output_path = Path(output)
    print(f"Downloading {stream_id} to {output_path}...")

    async with (
        aiohttp.ClientSession() as session,
        session.get(recording.video_url) as response,
    ):
        if not response.ok:
            print(f"Error: Failed to download: {response.status} {response.reason}")
            sys.exit(1)

        total_size = int(response.headers.get("content-length", 0))
        downloaded = 0

        with open(output_path, "wb") as f:
            async for chunk in response.content.iter_chunked(8192):
                f.write(chunk)
                downloaded += len(chunk)
                if total_size:
                    pct = (downloaded / total_size) * 100
                    print(f"\rDownloading: {pct:.1f}% ({downloaded:,} / {total_size:,} bytes)", end="")

    print(f"\nSaved to {output_path}")


async def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Odyssey Recordings CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s list                     List all recordings
  %(prog)s list --limit 10          List first 10 recordings
  %(prog)s get <stream_id>          Get recording details
  %(prog)s download <stream_id>     Download recording video
        """,
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("ODYSSEY_API_KEY", ""),
        help="Odyssey API key (or set ODYSSEY_API_KEY env var)",
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # List command
    list_parser = subparsers.add_parser("list", help="List stream recordings")
    list_parser.add_argument("--limit", type=int, help="Maximum number of recordings to return")
    list_parser.add_argument("--offset", type=int, help="Number of recordings to skip")

    # Get command
    get_parser = subparsers.add_parser("get", help="Get recording details")
    get_parser.add_argument("stream_id", help="Stream ID to get recording for")

    # Download command
    download_parser = subparsers.add_parser("download", help="Download recording video")
    download_parser.add_argument("stream_id", help="Stream ID to download")
    download_parser.add_argument(
        "--output", "-o", default="recording.mp4", help="Output filename (default: recording.mp4)"
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if not args.api_key:
        print("Error: API key required. Set ODYSSEY_API_KEY or use --api-key")
        sys.exit(1)

    client = Odyssey(api_key=args.api_key)

    try:
        if args.command == "list":
            await list_recordings(client, args.limit, args.offset)
        elif args.command == "get":
            await get_recording(client, args.stream_id)
        elif args.command == "download":
            await download_recording(client, args.stream_id, args.output)
    finally:
        await client.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nCancelled.")
