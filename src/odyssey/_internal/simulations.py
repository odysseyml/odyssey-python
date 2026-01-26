"""Simulations API client for Odyssey."""

import logging
from typing import Any

import aiohttp

from .auth import AuthClient

logger = logging.getLogger(__name__)


class SimulationsClient:
    """Handles simulation job API operations."""

    def __init__(self, auth: AuthClient, api_url: str, debug: bool = False) -> None:
        """Create a SimulationsClient.

        Args:
            auth: AuthClient for authentication.
            api_url: Base URL for the Odyssey API.
            debug: Enable debug logging.
        """
        self._auth = auth
        self._api_url = api_url
        self._debug = debug
        self._http_session: aiohttp.ClientSession | None = None

    def _auto_append_end(self, script: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Auto-append end entry if missing (ergonomic improvement).

        The API requires scripts to end with an 'end' action, but users often forget.
        Rather than throwing a cryptic server error, we silently append it.

        Args:
            script: List of script entries.

        Returns:
            Script with end entry appended if missing.
        """
        if not script:
            return script

        last_entry = script[-1]
        if "end" not in last_entry:
            last_timestamp = last_entry.get("timestamp_ms", 0)
            return [*script, {"timestamp_ms": last_timestamp + 3000, "end": {}}]

        return script

    def _log(self, msg: str) -> None:
        """Log a debug message."""
        if self._debug:
            logger.debug(f"[Simulations] {msg}")

    async def _get_http_session(self) -> aiohttp.ClientSession:
        """Get or create HTTP session."""
        if self._http_session is None or self._http_session.closed:
            self._http_session = aiohttp.ClientSession()
        return self._http_session

    async def _get_auth_headers(self) -> dict[str, str]:
        """Get authorization headers."""
        await self._auth.exchange_api_key_for_token()
        return {
            "Authorization": f"Bearer {self._auth._auth_token}",
            "Content-Type": "application/json",
        }

    async def submit_job(
        self,
        *,
        script: list[dict[str, Any]] | None = None,
        scripts: list[list[dict[str, Any]]] | None = None,
        script_url: str | None = None,
        portrait: bool = True,
    ) -> dict[str, Any]:
        """Submit a simulation job.

        Args:
            script: Single script to run.
            scripts: Batch mode - multiple scripts.
            script_url: URL to script JSON file.
            portrait: Portrait (True) or landscape (False).

        Returns:
            Dict with job info including job_id.

        Raises:
            ValueError: If invalid script options provided.
            ConnectionError: If API request fails.
        """
        # Validate exactly one script source provided
        script_sources = [script, scripts, script_url]
        num_sources = sum(1 for s in script_sources if s is not None)
        if num_sources != 1:
            raise ValueError("Exactly one of script, scripts, or script_url must be provided")

        self._log("Submitting simulation job")

        body: dict[str, Any] = {
            "portrait": portrait,
            "output_video": True,
        }

        if script_url:
            body["script_url"] = script_url
        elif script:
            body["script"] = self._auto_append_end(script)
        elif scripts:
            body["scripts"] = [self._auto_append_end(s) for s in scripts]

        session = await self._get_http_session()
        headers = await self._get_auth_headers()
        url = f"{self._api_url}/simulation-jobs"

        async with session.post(url, headers=headers, json=body) as response:
            if not response.ok:
                error_text = await response.text()
                raise ConnectionError(f"Failed to submit simulation: {response.status} {error_text}")

            return await response.json()

    async def get_status(self, job_id: str) -> dict[str, Any]:
        """Get the status of a simulation job.

        Args:
            job_id: The job ID from submit_job().

        Returns:
            Dict with job status and output streams if completed.

        Raises:
            ValueError: If job not found or not authorized.
            ConnectionError: If API request fails.
        """
        self._log(f"Getting status for job {job_id}")

        session = await self._get_http_session()
        headers = await self._get_auth_headers()
        url = f"{self._api_url}/simulation-jobs/{job_id}"

        async with session.get(url, headers=headers) as response:
            if response.status == 404:
                raise ValueError("Simulation job not found")
            if response.status == 403:
                raise ValueError("Not authorized to access this simulation job")
            if not response.ok:
                raise ConnectionError(f"Failed to get simulation status: {response.status} {response.reason}")

            return await response.json()

    async def list_jobs(
        self,
        *,
        status: str | None = None,
        active: bool | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> dict[str, Any]:
        """List user's simulation jobs.

        Args:
            status: Filter by status.
            active: Only show active jobs (pending/dispatched/processing).
            limit: Maximum jobs to return (default: 20, max: 100).
            offset: Offset from start (default: 0).

        Returns:
            Dict with jobs list and pagination info.

        Raises:
            ValueError: If invalid parameters or not authorized.
            ConnectionError: If API request fails.
        """
        # Validate pagination parameters
        if limit is not None and (limit < 1 or limit > 100):
            raise ValueError("limit must be between 1 and 100")
        if offset is not None and offset < 0:
            raise ValueError("offset must be non-negative")

        self._log("Listing simulation jobs")

        session = await self._get_http_session()
        headers = await self._get_auth_headers()

        # Build query params
        params: dict[str, str] = {}
        if status is not None:
            params["status"] = status
        if active is not None:
            params["active"] = "true" if active else "false"
        if limit is not None:
            params["limit"] = str(limit)
        if offset is not None:
            params["offset"] = str(offset)

        url = f"{self._api_url}/simulation-jobs"
        if params:
            query = "&".join(f"{k}={v}" for k, v in params.items())
            url = f"{url}?{query}"

        async with session.get(url, headers=headers) as response:
            if response.status == 401:
                raise ValueError("Not authorized")
            if not response.ok:
                raise ConnectionError(f"Failed to list simulations: {response.status} {response.reason}")

            return await response.json()

    async def cancel_job(self, job_id: str) -> dict[str, Any]:
        """Cancel a pending or dispatched simulation job.

        Args:
            job_id: The job ID to cancel.

        Returns:
            Dict with cancellation confirmation.

        Raises:
            ValueError: If job not found, not authorized, or cannot be cancelled.
            ConnectionError: If API request fails.
        """
        self._log(f"Cancelling job {job_id}")

        session = await self._get_http_session()
        headers = await self._get_auth_headers()
        url = f"{self._api_url}/simulation-jobs/{job_id}"

        async with session.delete(url, headers=headers) as response:
            if response.status == 404:
                raise ValueError("Simulation job not found")
            if response.status == 403:
                raise ValueError("Not authorized to cancel this simulation job")
            if response.status == 400:
                try:
                    data = await response.json()
                    raise ValueError(data.get("detail", "Cannot cancel this simulation job"))
                except aiohttp.ContentTypeError:
                    raise ValueError("Cannot cancel this simulation job") from None
            if not response.ok:
                raise ConnectionError(f"Failed to cancel simulation: {response.status} {response.reason}")

            return await response.json()

    async def close(self) -> None:
        """Close HTTP session."""
        if self._http_session:
            await self._http_session.close()
            self._http_session = None
