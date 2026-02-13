"""Tests for pipeline/hypothalamus.py — deterministic drive math."""

import pytest

from models.event import Event
from models.state import DrivesState
from pipeline.hypothalamus import clamp, drives_to_feeling, update_drives


class TestClamp:
    """clamp() bounds values to [lo, hi]."""

    def test_within_range(self):
        assert clamp(0.5) == 0.5

    def test_below_min(self):
        assert clamp(-0.3) == 0.0

    def test_above_max(self):
        assert clamp(1.5) == 1.0

    def test_custom_range(self):
        assert clamp(-2.0, -1.0, 1.0) == -1.0
        assert clamp(2.0, -1.0, 1.0) == 1.0

    def test_exact_boundaries(self):
        assert clamp(0.0) == 0.0
        assert clamp(1.0) == 1.0


class TestDrivesToFeeling:
    """drives_to_feeling() translates numeric drives into diegetic text."""

    def test_high_social_hunger_lonely(self):
        d = DrivesState(social_hunger=0.85)
        feeling = drives_to_feeling(d)
        assert "lonely" in feeling.lower()

    def test_low_energy_tired(self):
        d = DrivesState(energy=0.2)
        feeling = drives_to_feeling(d)
        assert "tired" in feeling.lower()

    def test_high_energy_sharp(self):
        d = DrivesState(energy=0.9)
        feeling = drives_to_feeling(d)
        assert "sharp" in feeling.lower()

    def test_high_expression_need(self):
        d = DrivesState(expression_need=0.8)
        feeling = drives_to_feeling(d)
        assert "write" in feeling.lower() or "building" in feeling.lower()

    def test_neutral_state_steady(self):
        d = DrivesState()  # defaults
        feeling = drives_to_feeling(d)
        assert "steady" in feeling.lower()

    def test_negative_mood_dim(self):
        d = DrivesState(mood_valence=-0.7)
        feeling = drives_to_feeling(d)
        assert "dim" in feeling.lower()


class TestUpdateDrives:
    """update_drives() applies time decay and event-driven changes."""

    @pytest.mark.asyncio
    async def test_time_decay_increases_social_hunger(self):
        d = DrivesState(social_hunger=0.5)
        new, _ = await update_drives(d, elapsed_hours=1.0, events=[])
        assert new.social_hunger > 0.5

    @pytest.mark.asyncio
    async def test_time_decay_decreases_energy_during_activity(self):
        d = DrivesState(energy=0.8)
        events = [Event(event_type='visitor_speech', source='visitor:x', payload={})]
        new, _ = await update_drives(d, elapsed_hours=0.1, events=events)
        assert new.energy < 0.8

    @pytest.mark.asyncio
    async def test_visitor_speech_reduces_social_hunger(self):
        d = DrivesState(social_hunger=0.5)
        events = [Event(event_type='visitor_speech', source='visitor:x', payload={})]
        new, _ = await update_drives(d, elapsed_hours=0.0, events=events)
        assert new.social_hunger < 0.5

    @pytest.mark.asyncio
    async def test_resonance_boosts_mood(self):
        d = DrivesState(mood_valence=0.0)
        new, _ = await update_drives(d, elapsed_hours=0.0, events=[], cortex_flags={'resonance': True})
        assert new.mood_valence > 0.0

    @pytest.mark.asyncio
    async def test_rest_recovery_during_idle(self):
        d = DrivesState(rest_need=0.5, energy=0.5)
        new, _ = await update_drives(d, elapsed_hours=1.0, events=[])
        assert new.rest_need < 0.5
        assert new.energy > 0.5

    @pytest.mark.asyncio
    async def test_drives_stay_clamped(self):
        d = DrivesState(social_hunger=0.99, energy=0.01)
        events = [Event(event_type='visitor_disconnect', source='visitor:x', payload={})]
        new, _ = await update_drives(d, elapsed_hours=2.0, events=events)
        assert 0.0 <= new.social_hunger <= 1.0
        assert 0.0 <= new.energy <= 1.0

    @pytest.mark.asyncio
    async def test_original_drives_unchanged(self):
        d = DrivesState(energy=0.5)
        new, _ = await update_drives(d, elapsed_hours=1.0, events=[])
        assert d.energy == 0.5  # original unchanged
