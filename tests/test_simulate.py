"""Tests for the ergonomic simulate API."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from odyssey import Odyssey


@pytest.fixture
def mock_auth_and_simulations():
    """Mock auth and simulations clients."""
    with patch.object(Odyssey, "_ensure_simulations_client", new_callable=AsyncMock) as mock_ensure:
        yield mock_ensure


@pytest.fixture
def client():
    """Create an Odyssey client for testing."""
    return Odyssey(api_key="ody_test_key")


class TestSimulateErgonomicAPI:
    """Tests for the simple prompt array form of simulate()."""

    async def test_converts_simple_prompt_array_to_script_format(self, client, mock_auth_and_simulations):
        """Simple prompt array should convert to proper script format."""
        captured_script = None

        async def capture_submit(script=None, scripts=None, script_url=None, portrait=True):
            nonlocal captured_script
            captured_script = script
            return {
                "job_id": "test-job-123",
                "status": "pending",
                "priority": "normal",
                "created_at": "2024-01-01T00:00:00Z",
            }

        client._simulations = MagicMock()
        client._simulations.submit_job = AsyncMock(side_effect=capture_submit)

        await client.simulate(["First prompt", "Second prompt", "Third prompt"])

        # Should have 4 entries: start, interact, interact, auto-appended end
        assert captured_script is not None
        assert len(captured_script) == 4

        # First entry is start at 0ms
        assert captured_script[0]["timestamp_ms"] == 0
        assert captured_script[0]["start"]["prompt"] == "First prompt"

        # Second entry is interact at 3000ms (default interval)
        assert captured_script[1]["timestamp_ms"] == 3000
        assert captured_script[1]["interact"]["prompt"] == "Second prompt"

        # Third entry is interact at 6000ms
        assert captured_script[2]["timestamp_ms"] == 6000
        assert captured_script[2]["interact"]["prompt"] == "Third prompt"

        # Fourth entry is auto-appended end at last timestamp + 3000ms
        assert captured_script[3]["timestamp_ms"] == 9000
        assert "end" in captured_script[3]

    async def test_respects_custom_interval_for_prompt_array(self, client, mock_auth_and_simulations):
        """Custom interval should be respected when converting prompts."""
        captured_script = None

        async def capture_submit(script=None, scripts=None, script_url=None, portrait=True):
            nonlocal captured_script
            captured_script = script
            return {
                "job_id": "test-job-123",
                "status": "pending",
                "priority": "normal",
                "created_at": "2024-01-01T00:00:00Z",
            }

        client._simulations = MagicMock()
        client._simulations.submit_job = AsyncMock(side_effect=capture_submit)

        await client.simulate(["A", "B", "C"], interval=5000)

        assert captured_script is not None
        assert captured_script[0]["timestamp_ms"] == 0
        assert captured_script[1]["timestamp_ms"] == 5000
        assert captured_script[2]["timestamp_ms"] == 10000
        # Auto-appended end at 10000 + 3000 = 13000
        assert captured_script[3]["timestamp_ms"] == 13000


class TestSimulateAutoAppendEnd:
    """Tests for auto-appending end entry."""

    async def test_auto_appends_end_when_script_does_not_end_with_end(self, client, mock_auth_and_simulations):
        """Scripts without end should have end auto-appended."""
        captured_script = None

        async def capture_submit(script=None, scripts=None, script_url=None, portrait=True):
            nonlocal captured_script
            captured_script = script
            return {
                "job_id": "test-job-123",
                "status": "pending",
                "priority": "normal",
                "created_at": "2024-01-01T00:00:00Z",
            }

        client._simulations = MagicMock()
        client._simulations.submit_job = AsyncMock(side_effect=capture_submit)

        await client.simulate(
            script=[
                {"timestamp_ms": 0, "start": {"prompt": "Start"}},
                {"timestamp_ms": 5000, "interact": {"prompt": "Middle"}},
                # No end entry
            ]
        )

        # Should have auto-appended end
        assert captured_script is not None
        assert len(captured_script) == 3
        assert captured_script[2]["timestamp_ms"] == 8000  # 5000 + 3000
        assert "end" in captured_script[2]

    async def test_does_not_duplicate_end_when_script_already_has_one(self, client, mock_auth_and_simulations):
        """Scripts with end should not get another end appended."""
        captured_script = None

        async def capture_submit(script=None, scripts=None, script_url=None, portrait=True):
            nonlocal captured_script
            captured_script = script
            return {
                "job_id": "test-job-123",
                "status": "pending",
                "priority": "normal",
                "created_at": "2024-01-01T00:00:00Z",
            }

        client._simulations = MagicMock()
        client._simulations.submit_job = AsyncMock(side_effect=capture_submit)

        await client.simulate(
            script=[
                {"timestamp_ms": 0, "start": {"prompt": "Start"}},
                {"timestamp_ms": 5000, "interact": {"prompt": "Middle"}},
                {"timestamp_ms": 10000, "end": {}},  # Already has end
            ]
        )

        # Should keep the original 3 entries without adding another end
        assert captured_script is not None
        assert len(captured_script) == 3
        assert captured_script[2]["timestamp_ms"] == 10000


class TestSimulateFullOptions:
    """Tests for the full options form of simulate()."""

    async def test_full_options_form_still_works(self, client, mock_auth_and_simulations):
        """Full options form should work as before."""
        captured_kwargs = {}

        async def capture_submit(**kwargs):
            nonlocal captured_kwargs
            captured_kwargs = kwargs
            return {
                "job_id": "test-job-123",
                "status": "pending",
                "priority": "normal",
                "created_at": "2024-01-01T00:00:00Z",
            }

        client._simulations = MagicMock()
        client._simulations.submit_job = AsyncMock(side_effect=capture_submit)

        await client.simulate(
            script=[
                {"timestamp_ms": 0, "start": {"prompt": "A bird flying"}},
                {"timestamp_ms": 4000, "interact": {"prompt": "The bird lands"}},
                {"timestamp_ms": 8000, "end": {}},
            ],
            portrait=False,
        )

        assert captured_kwargs["portrait"] is False
        assert captured_kwargs["script"] is not None
        assert len(captured_kwargs["script"]) == 3
