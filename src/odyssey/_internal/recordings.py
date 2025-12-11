"""Recordings API client for Odyssey."""

import logging
from typing import Any

import aiohttp

from .auth import AuthClient

logger = logging.getLogger(__name__)


class RecordingsClient:
    """Handles recordings API operations."""

    def __init__(self, auth: AuthClient, api_url: str, debug: bool = False) -> None:
        """Create a RecordingsClient.

        Args:
            auth: AuthClient for authentication.
            api_url: Base URL for the Odyssey API.
            debug: Enable debug logging.
        """
        self._auth = auth
        self._api_url = api_url
        self._debug = debug
        self._http_session: aiohttp.ClientSession | None = None

    def _log(self, msg: str) -> None:
        """Log a debug message."""
        if self._debug:
            logger.debug(f"[Recordings] {msg}")

    async def _get_http_session(self) -> aiohttp.ClientSession:
        """Get or create HTTP session."""
        if self._http_session is None or self._http_session.closed:
            self._http_session = aiohttp.ClientSession()
        return self._http_session

    async def _get_auth_headers(self) -> dict[str, str]:
        """Get authorization headers."""
        await self._auth.exchange_api_key_for_token()
        return {"Authorization": f"Bearer {self._auth._auth_token}"}

    async def get_recording(self, stream_id: str) -> dict[str, Any]:
        """Get recording data for a stream.

        Args:
            stream_id: The stream ID to get recording for.

        Returns:
            Dict with recording data including presigned URLs.

        Raises:
            ValueError: If recording not found or not authorized.
            ConnectionError: If API request fails.
        """
        self._log(f"Getting recording for stream {stream_id}")

        session = await self._get_http_session()
        headers = await self._get_auth_headers()
        url = f"{self._api_url}/recordings/{stream_id}"

        async with session.get(url, headers=headers) as response:
            if response.status == 404:
                raise ValueError("Recording not found")
            if response.status == 401:
                raise ValueError("Not authorized")
            if not response.ok:
                raise ConnectionError(f"Failed to get recording: {response.status} {response.reason}")

            return await response.json()

    async def list_stream_recordings(self, limit: int | None = None, offset: int | None = None) -> dict[str, Any]:
        """List stream recordings for the authenticated user.

        Args:
            limit: Maximum number of recordings to return.
            offset: Number of recordings to skip.

        Returns:
            Dict with recordings list and pagination info.

        Raises:
            ValueError: If not authorized.
            ConnectionError: If API request fails.
        """
        self._log("Listing stream recordings")

        session = await self._get_http_session()
        headers = await self._get_auth_headers()

        # Build query params
        params = {}
        if limit is not None:
            params["limit"] = str(limit)
        if offset is not None:
            params["offset"] = str(offset)

        url = f"{self._api_url}/stream-recordings"
        if params:
            query = "&".join(f"{k}={v}" for k, v in params.items())
            url = f"{url}?{query}"

        async with session.get(url, headers=headers) as response:
            if response.status == 401:
                raise ValueError("Not authorized")
            if not response.ok:
                raise ConnectionError(f"Failed to list stream recordings: {response.status} {response.reason}")

            return await response.json()

    async def close(self) -> None:
        """Close HTTP session."""
        if self._http_session:
            await self._http_session.close()
            self._http_session = None
