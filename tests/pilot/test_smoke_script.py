"""Tests for scripts/pilot_smoke.py."""

import pytest

from scripts.pilot_smoke import run_smoke_test


@pytest.mark.asyncio
async def test_run_smoke_test_in_memory() -> None:
    success = await run_smoke_test(db_path=":memory:")
    assert success is True
