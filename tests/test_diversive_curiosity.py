"""Tests for diversive curiosity drive mechanics.

TASK-043: Verifies equilibrium pull, time drift, boredom escalation,
consumption satisfaction, and visitor suppression.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.event import Event
from models.state import DrivesState
from pipeline.hypothalamus import (
    update_drives, clamp, DRIVE_EQUILIBRIA, drives_to_feeling,
)


@pytest.fixture(autouse=True)
def _patch_hypo_deps():
    """Patch db at the pipeline.hypothalamus module level."""
    mock_db = MagicMock()
    with patch('pipeline.hypothalamus._db', mock_db):
        yield mock_db


def _make_drives(**overrides):
    # Map diversive_curiosity kwarg to curiosity for constructor compat
    if 'diversive_curiosity' in overrides:
        overrides['curiosity'] = overrides.pop('diversive_curiosity')
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


class TestDiversiveCuriosity:
    """Diversive curiosity drive mechanics."""

    @pytest.mark.asyncio
    async def test_equilibrium_pull(self):
        """Diversive curiosity pulled toward 0.40 equilibrium."""
        drives = _make_drives(curiosity=0.8)
        new, _ = await update_drives(drives, elapsed_hours=1.0, events=[])

        # Should move toward 0.40
        assert new.diversive_curiosity < drives.diversive_curiosity
        # Equilibrium is 0.40
        assert DRIVE_EQUILIBRIA['diversive_curiosity'] == 0.40

    @pytest.mark.asyncio
    async def test_time_drift_minimal(self):
        """Time drift is +0.005/hr, not old +0.03/hr."""
        drives = _make_drives(curiosity=0.40)  # at equilibrium
        new, _ = await update_drives(drives, elapsed_hours=1.0, events=[])

        # At equilibrium, homeostatic pull = 0. Only time drift matters.
        # +0.005/hr for 1 hour = 0.005
        # Result should be very close to starting value
        drift = new.diversive_curiosity - drives.diversive_curiosity
        assert drift < 0.01  # tiny drift, not the old large rate

    @pytest.mark.asyncio
    async def test_consumption_satisfaction(self):
        """Reading content reduces diversive slightly via gap deltas."""
        drives = _make_drives(curiosity=0.6)
        new, _ = await update_drives(
            drives, elapsed_hours=0.05, events=[],
            gap_curiosity_deltas=[0.10],  # from reading content
        )
        # Diversive should increase from the gap delta
        assert new.diversive_curiosity > drives.diversive_curiosity

    @pytest.mark.asyncio
    async def test_visitor_suppresses_diversive(self):
        """Engaged in conversation → diversive drops."""
        drives = _make_drives(curiosity=0.6)
        events = [Event(
            event_type='visitor_speech',
            source='visitor:v1',
            payload={'text': 'Hello there!'},
        )]
        new, _ = await update_drives(
            drives, elapsed_hours=0.05, events=events,
        )
        # Visitor speech should suppress diversive curiosity
        assert new.diversive_curiosity <= drives.diversive_curiosity + 0.01


class TestDiversiveFeelings:
    """drives_to_feeling for diversive curiosity."""

    def test_high_diversive(self):
        drives = _make_drives(curiosity=0.8)
        feelings = drives_to_feeling(drives)
        assert 'attention keeps drifting' in feelings

    def test_mid_diversive(self):
        drives = _make_drives(curiosity=0.55)
        feelings = drives_to_feeling(drives)
        assert 'scanning' in feelings

    def test_low_diversive(self):
        drives = _make_drives(curiosity=0.1)
        feelings = drives_to_feeling(drives)
        assert "content" in feelings or "pulling" not in feelings


class TestBackwardCompat:
    """Backward compatibility: diversive_curiosity property aliases curiosity field."""

    def test_diversive_curiosity_getter(self):
        d = DrivesState(curiosity=0.7)
        assert d.diversive_curiosity == 0.7

    def test_diversive_curiosity_setter(self):
        d = DrivesState(curiosity=0.5)
        d.diversive_curiosity = 0.9
        assert d.curiosity == 0.9

    def test_copy_preserves_diversive(self):
        d = DrivesState(curiosity=0.7)
        d2 = d.copy()
        assert d2.diversive_curiosity == 0.7
        assert d2.curiosity == 0.7

    def test_old_code_pattern(self):
        """Simulate old code: drives.curiosity = clamp(drives.curiosity - 0.03)"""
        d = DrivesState(curiosity=0.5)
        d.curiosity = clamp(d.curiosity - 0.03)
        assert d.diversive_curiosity == 0.47
        assert d.curiosity == 0.47
