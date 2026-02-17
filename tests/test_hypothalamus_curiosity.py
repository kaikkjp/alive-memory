"""Tests for hypothalamus stimulus-driven curiosity updates.

TASK-042: Verifies that curiosity is driven by gap detection deltas,
not by a timer. Also checks passive decay rate.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.event import Event
from models.state import DrivesState
from pipeline.hypothalamus import update_drives, clamp, DRIVE_EQUILIBRIA


@pytest.fixture(autouse=True)
def _patch_hypo_deps():
    """Patch db at the pipeline.hypothalamus module level."""
    mock_db = MagicMock()
    with patch('pipeline.hypothalamus._db', mock_db):
        yield mock_db


def _make_drives(**overrides):
    """Create a DrivesState with defaults that won't trigger edge effects."""
    defaults = dict(
        social_hunger=0.5,
        curiosity=0.5,
        expression_need=0.3,
        rest_need=0.2,
        energy=0.7,
        mood_valence=0.0,
        mood_arousal=0.3,
    )
    defaults.update(overrides)
    return DrivesState(**defaults)


class TestGapDrivenCuriosity:
    """Stimulus-driven curiosity updates from gap detection."""

    @pytest.mark.asyncio
    async def test_gap_driven_curiosity_increase(self):
        """Partial matches increase curiosity via gap_curiosity_deltas."""
        drives = _make_drives(curiosity=0.5)
        new, _ = await update_drives(
            drives, elapsed_hours=0.05, events=[],
            gap_curiosity_deltas=[0.10, 0.05],
        )

        # Curiosity should increase by the sum of deltas (minus small decay)
        expected_increase = 0.15  # 0.10 + 0.05
        # Account for small passive decay and homeostatic pull
        assert new.curiosity > drives.curiosity
        assert new.curiosity > 0.6  # should be meaningfully higher

    @pytest.mark.asyncio
    async def test_no_gap_no_increase(self):
        """Foreign/known content (empty deltas) doesn't move curiosity."""
        drives = _make_drives(curiosity=0.5)
        new, _ = await update_drives(
            drives, elapsed_hours=0.05, events=[],
            gap_curiosity_deltas=[],
        )

        # Curiosity should drift slightly down (passive decay + homeostatic pull)
        # but NOT increase
        assert new.curiosity <= drives.curiosity + 0.01  # small tolerance for float

    @pytest.mark.asyncio
    async def test_passive_decay_slow(self):
        """Curiosity decays at 0.005/hr, not the old fast rate."""
        drives = _make_drives(curiosity=0.8)
        # Run for 1 hour with no stimuli
        new, _ = await update_drives(
            drives, elapsed_hours=1.0, events=[],
        )

        # Should have decayed by ~0.005 from passive + homeostatic pull toward 0.50
        # Homeostatic pull: (0.50 - 0.80) * 0.15 * 1.0 = -0.045
        # Passive decay: -0.005
        # Total: ~-0.05
        assert new.curiosity < drives.curiosity  # should decrease
        # But not too fast: should still be above 0.7 after 1hr at 0.8
        assert new.curiosity > 0.7

    @pytest.mark.asyncio
    async def test_curiosity_accumulates(self):
        """Multiple partial matches in one cycle sum up."""
        drives = _make_drives(curiosity=0.3)
        deltas = [0.15, 0.15, 0.10]  # total 0.40
        new, _ = await update_drives(
            drives, elapsed_hours=0.05, events=[],
            gap_curiosity_deltas=deltas,
        )

        # Curiosity should jump significantly from 0.3
        assert new.curiosity > 0.6

    @pytest.mark.asyncio
    async def test_curiosity_clamped_at_one(self):
        """Curiosity never exceeds 1.0 even with large deltas."""
        drives = _make_drives(curiosity=0.9)
        deltas = [0.15, 0.15, 0.15]  # total 0.45
        new, _ = await update_drives(
            drives, elapsed_hours=0.05, events=[],
            gap_curiosity_deltas=deltas,
        )

        assert new.curiosity <= 1.0

    @pytest.mark.asyncio
    async def test_none_deltas_no_crash(self):
        """gap_curiosity_deltas=None doesn't crash."""
        drives = _make_drives(curiosity=0.5)
        new, _ = await update_drives(
            drives, elapsed_hours=0.05, events=[],
            gap_curiosity_deltas=None,
        )
        # Should work fine, same as not providing deltas
        assert isinstance(new.curiosity, float)
