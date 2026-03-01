"""Tests for pipeline/hypothalamus.py — deterministic drive math."""

import pytest

from models.event import Event
from models.state import DrivesState
from db.parameters import p
from pipeline.hypothalamus import (
    clamp, drives_to_feeling, update_drives,
    _homeostatic_pull,
)


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

    def test_neutral_state_sharp_or_steady(self):
        d = DrivesState()  # defaults: energy=0.8, ≥0.6 threshold → "sharp"
        feeling = drives_to_feeling(d)
        assert "sharp" in feeling.lower() or "steady" in feeling.lower()

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
    async def test_energy_unchanged_by_hypothalamus(self):
        """TASK-050: energy is display-only, not modified by hypothalamus."""
        d = DrivesState(energy=0.8)
        events = [Event(event_type='visitor_speech', source='visitor:x', payload={})]
        new, _ = await update_drives(d, elapsed_hours=0.1, events=events)
        assert new.energy == 0.8

    @pytest.mark.asyncio
    async def test_visitor_speech_reduces_social_hunger(self):
        d = DrivesState(social_hunger=0.5)
        events = [Event(event_type='visitor_speech', source='visitor:x', payload={})]
        new, _ = await update_drives(d, elapsed_hours=0.0, events=events)
        assert new.social_hunger < 0.5

    @pytest.mark.asyncio
    async def test_resonance_boosts_arousal(self):
        """Resonance in hypothalamus now only boosts arousal (social/valence moved to output.py)."""
        d = DrivesState(mood_arousal=0.3)
        new, _ = await update_drives(d, elapsed_hours=0.0, events=[], cortex_flags={'resonance': True})
        assert new.mood_arousal > 0.3

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


class TestHomeostaticPull:
    """Homeostatic pull prevents drive saturation at extremes."""

    def test_pull_toward_equilibrium_from_above(self):
        """Value above equilibrium is pulled down."""
        result = _homeostatic_pull(1.0, 0.5, elapsed_hours=1.0)
        assert result < 1.0

    def test_pull_toward_equilibrium_from_below(self):
        """Value below equilibrium is pulled up."""
        result = _homeostatic_pull(0.0, 0.5, elapsed_hours=1.0)
        assert result > 0.0

    def test_at_equilibrium_no_change(self):
        """Value at equilibrium has zero pull."""
        result = _homeostatic_pull(0.5, 0.5, elapsed_hours=1.0)
        assert result == 0.5

    def test_pull_proportional_to_distance(self):
        """Further from equilibrium = stronger pull."""
        far_pull = abs(_homeostatic_pull(1.0, 0.5, 1.0) - 1.0)
        near_pull = abs(_homeostatic_pull(0.6, 0.5, 1.0) - 0.6)
        assert far_pull > near_pull

    def test_pull_scales_with_elapsed_time(self):
        """More elapsed time = more pull."""
        short = _homeostatic_pull(1.0, 0.5, elapsed_hours=0.1)
        long = _homeostatic_pull(1.0, 0.5, elapsed_hours=2.0)
        assert long < short  # more pull = lower value (pulling from 1.0 toward 0.5)

    def test_clamped_to_bounds(self):
        """Result stays within [lo, hi]."""
        assert _homeostatic_pull(0.0, 0.5, 1.0) >= 0.0
        assert _homeostatic_pull(1.0, 0.5, 1.0) <= 1.0
        # Custom bounds
        assert _homeostatic_pull(-1.0, 0.0, 1.0, -1.0, 1.0) >= -1.0

    @pytest.mark.asyncio
    async def test_high_curiosity_pulled_down(self):
        """Curiosity at 1.0 should decrease after update."""
        d = DrivesState(curiosity=1.0)
        new, _ = await update_drives(d, elapsed_hours=1.0, events=[])
        assert new.curiosity < 1.0, f"Curiosity should decrease from 1.0, got {new.curiosity}"

    @pytest.mark.asyncio
    async def test_energy_not_pulled_by_homeostasis(self):
        """TASK-050: Energy is display-only, no homeostatic pull."""
        d = DrivesState(energy=0.0)
        new, _ = await update_drives(d, elapsed_hours=1.0, events=[])
        assert new.energy == 0.0, f"Energy should stay at 0.0 (display-only), got {new.energy}"

    @pytest.mark.asyncio
    async def test_expression_at_zero_pulled_up(self):
        """Expression need at 0.0 should increase toward equilibrium."""
        d = DrivesState(expression_need=0.0)
        new, _ = await update_drives(d, elapsed_hours=1.0, events=[])
        assert new.expression_need > 0.0, f"Expression need should increase from 0.0, got {new.expression_need}"

    @pytest.mark.asyncio
    async def test_no_drive_stuck_after_3_cycles(self):
        """No drive should stay at 0% or 100% for 3 consecutive short cycles."""
        d = DrivesState(curiosity=1.0, expression_need=0.0, energy=0.0)
        for _ in range(3):
            d, _ = await update_drives(d, elapsed_hours=0.05, events=[])
        assert d.curiosity < 1.0, "Curiosity stuck at 1.0 after 3 cycles"
        assert d.expression_need > 0.0, "Expression need stuck at 0.0 after 3 cycles"
        # TASK-050: energy is display-only, stays at initial value
        assert d.energy == 0.0, "Energy should remain unchanged (display-only)"

    @pytest.mark.asyncio
    async def test_drives_converge_over_20_cycles(self):
        """From extremes, drives move meaningfully toward equilibrium over ~1hr."""
        d = DrivesState(curiosity=1.0, energy=0.0, expression_need=0.0)
        initial = d.copy()
        for _ in range(20):
            d, _ = await update_drives(d, elapsed_hours=0.05, events=[])
        # After 1 hour, drives should have moved significantly from extremes
        assert d.curiosity < initial.curiosity - 0.02
        # TASK-050: energy is display-only, stays at initial value
        assert d.energy == initial.energy
        assert d.expression_need > initial.expression_need + 0.01

    @pytest.mark.asyncio
    async def test_near_equilibrium_minimal_pull(self):
        """Drives near equilibrium have negligible homeostatic pull."""
        d = DrivesState(
            social_hunger=p('hypothalamus.equilibria.social_hunger'),
            curiosity=p('hypothalamus.equilibria.diversive_curiosity'),
            expression_need=p('hypothalamus.equilibria.expression_need'),
            energy=p('hypothalamus.equilibria.energy'),
        )
        new, _ = await update_drives(d, elapsed_hours=0.05, events=[])
        # Time-based forces still apply but homeostatic pull is near zero.
        # Values should change only slightly from time forces.
        assert abs(new.curiosity - d.curiosity) < 0.01


class TestMoodArousal:
    """mood_arousal responds to events, resonance, and settles back to equilibrium."""

    @pytest.mark.asyncio
    async def test_visitor_connect_spikes_arousal(self):
        d = DrivesState(mood_arousal=0.30)
        events = [Event(event_type='visitor_connect', source='visitor:x', payload={})]
        new, _ = await update_drives(d, elapsed_hours=0.0, events=events)
        # +0.1 (existing) + 0.2 (TASK-046 drive coupling) = +0.3 total
        assert new.mood_arousal == pytest.approx(0.60, abs=0.01)

    @pytest.mark.asyncio
    async def test_visitor_disconnect_lowers_arousal(self):
        d = DrivesState(mood_arousal=0.40)
        events = [Event(event_type='visitor_disconnect', source='visitor:x', payload={})]
        new, _ = await update_drives(d, elapsed_hours=0.0, events=events)
        assert new.mood_arousal == pytest.approx(0.35, abs=0.01)

    @pytest.mark.asyncio
    async def test_resonance_boosts_arousal(self):
        d = DrivesState(mood_arousal=0.30)
        new, _ = await update_drives(d, elapsed_hours=0.0, events=[],
                                     cortex_flags={'resonance': True})
        assert new.mood_arousal == pytest.approx(0.38, abs=0.01)

    @pytest.mark.asyncio
    async def test_content_consumed_boosts_arousal(self):
        d = DrivesState(mood_arousal=0.30)
        events = [Event(event_type='content_consumed', source='self', payload={})]
        new, _ = await update_drives(d, elapsed_hours=0.0, events=events)
        assert new.mood_arousal == pytest.approx(0.35, abs=0.01)

    @pytest.mark.asyncio
    async def test_thread_updated_boosts_arousal(self):
        d = DrivesState(mood_arousal=0.30)
        events = [Event(event_type='thread_updated', source='self', payload={})]
        new, _ = await update_drives(d, elapsed_hours=0.0, events=events)
        assert new.mood_arousal == pytest.approx(0.34, abs=0.01)

    @pytest.mark.asyncio
    async def test_action_variety_boosts_arousal(self):
        d = DrivesState(mood_arousal=0.30)
        new, _ = await update_drives(d, elapsed_hours=0.0, events=[],
                                     cortex_flags={'action_variety': True})
        assert new.mood_arousal == pytest.approx(0.33, abs=0.01)

    @pytest.mark.asyncio
    async def test_arousal_settles_back_to_equilibrium(self):
        """Elevated arousal should decay back toward 0.30 over several hours."""
        d = DrivesState(mood_arousal=0.60)
        # Simulate 3 hours (36 cycles at 5min each)
        for _ in range(36):
            d, _ = await update_drives(d, elapsed_hours=0.083, events=[])
        # Spring pull is gradual — after 3h from 0.60, expect ~0.49
        assert d.mood_arousal < 0.55, f"Arousal should decay from 0.60 over 3h, got {d.mood_arousal}"
        assert d.mood_arousal > 0.30, f"Arousal shouldn't undershoot equilibrium, got {d.mood_arousal}"
        # After 8 more hours (total ~11h), should be much closer to equilibrium
        for _ in range(96):
            d, _ = await update_drives(d, elapsed_hours=0.083, events=[])
        assert d.mood_arousal < 0.38, f"Arousal should near 0.30 after ~11h, got {d.mood_arousal}"

    @pytest.mark.asyncio
    async def test_combined_stimulation_reaches_target_range(self):
        """A busy cycle with visitor + resonance + content should push arousal into 0.60-0.85 range.
        TASK-046 adds +0.2 arousal on visitor_connect (total +0.3), so target is higher.
        """
        d = DrivesState(mood_arousal=0.30)
        events = [
            Event(event_type='visitor_connect', source='visitor:x', payload={}),
            Event(event_type='content_consumed', source='self', payload={}),
        ]
        new, _ = await update_drives(d, elapsed_hours=0.0, events=events,
                                     cortex_flags={'resonance': True, 'action_variety': True})
        assert 0.60 <= new.mood_arousal <= 0.85, f"Expected 0.60-0.85, got {new.mood_arousal}"


class TestSocialSensitivity:
    """TASK-105: Social sensitivity personality trait scales social hunger dynamics."""

    @pytest.mark.asyncio
    async def test_extrovert_gets_lonely_faster(self):
        """Extrovert (ss=0.8) drift is faster than introvert (ss=0.2)."""
        from unittest.mock import MagicMock
        d = DrivesState(social_hunger=0.3)

        introvert = MagicMock()
        introvert.social_sensitivity = 0.2
        extrovert = MagicMock()
        extrovert.social_sensitivity = 0.8

        new_intro, _ = await update_drives(d, elapsed_hours=1.0, events=[], identity=introvert)
        new_extro, _ = await update_drives(d, elapsed_hours=1.0, events=[], identity=extrovert)

        # Both should increase (time drift), but extrovert increases more
        assert new_extro.social_hunger > new_intro.social_hunger

    @pytest.mark.asyncio
    async def test_introvert_relief_per_message_stronger(self):
        """Introvert (ss=0.2) gets more relief per message than extrovert (ss=0.8)."""
        from unittest.mock import MagicMock
        from pipeline.hypothalamus import _session_tracker
        _session_tracker.sessions.clear()

        d = DrivesState(social_hunger=0.5)

        introvert = MagicMock()
        introvert.social_sensitivity = 0.2
        extrovert = MagicMock()
        extrovert.social_sensitivity = 0.8

        # Use different visitor IDs so session tracker doesn't confound
        intro_events = [Event(event_type='visitor_speech', source='visitor:relief_intro', payload={})]
        extro_events = [Event(event_type='visitor_speech', source='visitor:relief_extro', payload={})]

        new_intro, _ = await update_drives(d, elapsed_hours=0.0, events=intro_events, identity=introvert)
        new_extro, _ = await update_drives(d, elapsed_hours=0.0, events=extro_events, identity=extrovert)

        # Introvert gets more relief (lower social_hunger)
        assert new_intro.social_hunger < new_extro.social_hunger

    @pytest.mark.asyncio
    async def test_session_diminishing_returns(self):
        """5 messages in quick succession give diminishing relief."""
        from unittest.mock import MagicMock
        from pipeline.hypothalamus import _session_tracker
        # Clear session state
        _session_tracker.sessions.clear()

        d = DrivesState(social_hunger=0.8)
        identity = MagicMock()
        identity.social_sensitivity = 0.5

        reliefs = []
        for i in range(5):
            before = d.social_hunger
            events = [Event(event_type='visitor_speech', source='visitor:session_test', payload={})]
            d, _ = await update_drives(d, elapsed_hours=0.0, events=events, identity=identity)
            relief = before - d.social_hunger
            reliefs.append(relief)

        # Each successive message gives less relief
        assert reliefs[0] > reliefs[1] > reliefs[2]

    def test_introvert_feeling_lonely_threshold(self):
        """Introvert only feels lonely at very high social hunger."""
        d = DrivesState(social_hunger=0.7)
        feeling = drives_to_feeling(d, social_sensitivity=0.2)
        # 0.7 < 0.8 threshold for introvert — should NOT be lonely
        assert "lonely" not in feeling.lower()

        d2 = DrivesState(social_hunger=0.85)
        feeling2 = drives_to_feeling(d2, social_sensitivity=0.2)
        assert "lonely" in feeling2.lower()

    def test_extrovert_feeling_lonely_threshold(self):
        """Extrovert feels lonely at lower social hunger."""
        d = DrivesState(social_hunger=0.55)
        feeling = drives_to_feeling(d, social_sensitivity=0.8)
        # 0.55 > 0.5 threshold for extrovert — SHOULD be lonely
        assert "lonely" in feeling.lower()

    def test_introvert_enough_threshold(self):
        """Introvert hits 'enough' at low social hunger."""
        d = DrivesState(social_hunger=0.1, energy=0.8)
        feeling = drives_to_feeling(d, social_sensitivity=0.2)
        assert "space" in feeling.lower() or "enough" in feeling.lower()

    def test_default_sensitivity_matches_neutral(self):
        """Default ss=0.5 gives same thresholds as before TASK-105."""
        d = DrivesState(social_hunger=0.85)
        feeling = drives_to_feeling(d, social_sensitivity=0.5)
        assert "lonely" in feeling.lower()
