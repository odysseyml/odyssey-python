import asyncio
import logging
import time

import aiohttp

logger = logging.getLogger(__name__)

FALLBACK_LATENCY_MS = 9999
PING_TIMEOUT_S = 10


async def measure_region_latencies(
    api_url: str,
    auth_token: str,
    http_session: aiohttp.ClientSession,
    deadline_s: float = 1.0,
    debug: bool = False,
) -> dict[str, int]:
    """Fetch available regions and measure latencies to each.

    Pings all regions concurrently and returns at the deadline or when all complete (whichever is first).
    Regions that haven't responded get a fallback value; slower pings continue in background.

    Args:
        api_url: Base URL for the Odyssey API.
        auth_token: Bearer token for authentication.
        http_session: aiohttp session to use for requests.
        deadline_s: Time to wait before returning results.
        debug: Enable debug logging.

    Returns:
        Dict mapping region ID to latency in milliseconds.
    """

    def _log(msg: str) -> None:
        if debug:
            logger.debug(f"[Regions] {msg}")

    try:
        async with http_session.get(
            f"{api_url}/regions",
            headers={"Authorization": f"Bearer {auth_token}"},
        ) as response:
            if not response.ok:
                _log(f"Failed to fetch regions: {response.status}")
                return {}

            data = await response.json()

        regions: list[dict[str, str]] = data.get("regions", [])
        if not regions:
            return {}

        latencies: dict[str, int] = {r["id"]: FALLBACK_LATENCY_MS for r in regions}

        _log(f"Pinging {len(regions)} regions (deadline: {deadline_s}s)...")

        async def ping_region(region: dict[str, str]) -> None:
            try:
                start = time.time()
                timeout = aiohttp.ClientTimeout(total=PING_TIMEOUT_S)
                async with http_session.get(region["ping_url"], timeout=timeout) as ping_response:
                    if ping_response.ok:
                        latencies[region["id"]] = int((time.time() - start) * 1000)
            except Exception:
                pass

        tasks = [asyncio.create_task(ping_region(r)) for r in regions]

        _, pending = await asyncio.wait(tasks, timeout=deadline_s)

        if pending:
            asyncio.ensure_future(asyncio.gather(*pending, return_exceptions=True))

        _log(f"Region latencies: {latencies}")
        return latencies

    except Exception as e:
        _log(f"Failed to measure region latencies: {e}")
        return {}
