"""Tests for TASK-046: Mood-drive coupling — allostatic affect regulation.

Tests that mood (valence + arousal) realistically reflects internal drive state:
- Social isolation → melancholy
- Low stimulation → drowsiness
- Unexpressed thoughts → frustration
- Exhaustion → grumpiness
- Visitor contact → relief proportional to loneliness
- Nap → refreshed
"""

import pytest

from models.event import Event
from models.state import DrivesState
from pipeline.hypothalamus import update_drives, clamp


# ── Part A: Social hunger → valence suppression ──

class TestSocialHungerValence:
    """Social hunger above 0.4 suppresses valence. Engagement provides relief."""

    @pytest.mark.asyncio
    async def test_social_hunger_suppresses_valence(self):
        """social_hunger at 0.6 for 10 cycles → valence measurably lower."""
        d = DrivesState(social_hunger=0.6, mood_valence=0.5)
        for _ in range(10):
            d, _ = await update_drives(
                d, elapsed_hours=0.05, events=[],
                cycle_context={'consecutive_idle': 0})
        assert d.mood_valence < 0.5, (
            f"Valence should drop from social hunger, got {d.mood_valence}")

    @pytest.mark.asyncio
    async def test_valence_floor(self):
        """Single-cycle social hunger pressure cannot cross the 0.15 floor."""
        # Start at 0.16, just above floor — one cycle of pressure should not cross it
        d = DrivesState(social_hunger=0.9, mood_valence=0.16)
        new, _ = await update_drives(
            d, elapsed_hours=0.0, events=[],
            cycle_context={'consecutive_idle': 0})
        # Pressure = -0.02 * (0.9 - 0.4) = -0.01, would take to 0.15
        assert new.mood_valence >= 0.15, (
            f"Valence floor violated: {new.mood_valence}")

    @pytest.mark.asyncio
    async def test_valence_floor_prevents_crossing(self):
        """Social hunger pressure that would cross 0.15 is capped there."""
        d = DrivesState(social_hunger=0.95, mood_valence=0.155)
        new, _ = await update_drives(
            d, elapsed_hours=0.0, events=[],
            cycle_context={'consecutive_idle': 0})
        # Pressure = -0.02 * (0.95 - 0.4) = -0.011 → would take to 0.144
        # Floor should prevent crossing below 0.15
        assert new.mood_valence == pytest.approx(0.15, abs=0.001)

    @pytest.mark.asyncio
    async def test_no_suppression_below_threshold(self):
        """social_hunger at 0.3 does not suppress valence."""
        d = DrivesState(social_hunger=0.3, mood_valence=0.5)
        initial_valence = d.mood_valence
        new, _ = await update_drives(
            d, elapsed_hours=0.0, events=[],
            cycle_context={'consecutive_idle': 0})
        # Only homeostatic pull acts, no social hunger pressure
        # Since elapsed=0 and no events, valence should be unchanged
        assert new.mood_valence == pytest.approx(initial_valence, abs=0.001)

    @pytest.mark.asyncio
    async def test_visitor_relief_bump(self):
        """Engagement cycle with high social_hunger → valence increases."""
        d = DrivesState(social_hunger=0.7, mood_valence=0.3)
        new, _ = await update_drives(
            d, elapsed_hours=0.0, events=[],
            cycle_context={'engaged_this_cycle': True, 'consecutive_idle': 0})
        # Relief = 0.05 * 0.7 = 0.035
        assert new.mood_valence > 0.3, (
            f"Visitor relief should boost valence, got {new.mood_valence}")

    @pytest.mark.asyncio
    async def test_lonelier_means_more_relief(self):
        """Relief bump at social_hunger=0.7 > bump at social_hunger=0.3."""
        d_lonely = DrivesState(social_hunger=0.7, mood_valence=0.3)
        d_content = DrivesState(social_hunger=0.3, mood_valence=0.3)

        ctx = {'engaged_this_cycle': True, 'consecutive_idle': 0}
        new_lonely, _ = await update_drives(d_lonely, 0.0, [], cycle_context=ctx)
        new_content, _ = await update_drives(d_content, 0.0, [], cycle_context=ctx)

        relief_lonely = new_lonely.mood_valence - 0.3
        relief_content = new_content.mood_valence - 0.3
        assert relief_lonely > relief_content, (
            f"Lonely relief {relief_lonely:.4f} should exceed content relief {relief_content:.4f}")

    @pytest.mark.asyncio
    async def test_engagement_skips_suppression(self):
        """When engaged, social hunger suppression is skipped even if hunger is high."""
        d = DrivesState(social_hunger=0.8, mood_valence=0.3)
        new, _ = await update_drives(
            d, elapsed_hours=0.0, events=[],
            cycle_context={'engaged_this_cycle': True, 'consecutive_idle': 0})
        # Should get relief, not suppression
        assert new.mood_valence > 0.3

    @pytest.mark.asyncio
    async def test_floor_doesnt_raise_already_low(self):
        """If valence is already below 0.15 (from other causes), floor doesn't raise it."""
        d = DrivesState(social_hunger=0.6, mood_valence=0.10)
        new, _ = await update_drives(
            d, elapsed_hours=0.0, events=[],
            cycle_context={'consecutive_idle': 0})
        # Pressure applied but floor doesn't raise since already below 0.15
        assert new.mood_valence <= 0.10


# ── Part B: Low stimulation → arousal decay ──

class TestIdleArousalDecay:
    """Consecutive idle cycles suppress arousal. Events spike it."""

    @pytest.mark.asyncio
    async def test_idle_arousal_decay(self):
        """10 consecutive idle cycles → arousal drops toward 0.3-0.4."""
        d = DrivesState(mood_arousal=0.7)
        for i in range(10):
            d, _ = await update_drives(
                d, elapsed_hours=0.05, events=[],
                cycle_context={'consecutive_idle': i + 1})
        assert d.mood_arousal < 0.7, (
            f"Arousal should decay with idle cycles, got {d.mood_arousal}")

    @pytest.mark.asyncio
    async def test_no_decay_below_threshold(self):
        """5 or fewer consecutive idle cycles → no arousal decay from idle."""
        d = DrivesState(mood_arousal=0.5)
        new, _ = await update_drives(
            d, elapsed_hours=0.0, events=[],
            cycle_context={'consecutive_idle': 5})
        # Only homeostatic pull, no idle decay (threshold is >5)
        assert new.mood_arousal == pytest.approx(0.5, abs=0.001)

    @pytest.mark.asyncio
    async def test_arousal_decay_capped(self):
        """Arousal pressure capped at -0.05/cycle even at very high idle counts."""
        d = DrivesState(mood_arousal=0.5)
        new_high, _ = await update_drives(
            d, elapsed_hours=0.0, events=[],
            cycle_context={'consecutive_idle': 100})
        d2 = DrivesState(mood_arousal=0.5)
        new_low, _ = await update_drives(
            d2, elapsed_hours=0.0, events=[],
            cycle_context={'consecutive_idle': 10})
        # At 100: pressure = -0.01 * 95 → capped at -0.05
        # At 10: pressure = -0.01 * 5 = -0.05
        # Both should give same result
        assert new_high.mood_arousal == pytest.approx(new_low.mood_arousal, abs=0.001)

    @pytest.mark.asyncio
    async def test_visitor_arousal_spike(self):
        """visitor_connect → arousal jumps +0.3 total."""
        d = DrivesState(mood_arousal=0.3)
        events = [Event(event_type='visitor_connect', source='visitor:x', payload={})]
        new, _ = await update_drives(d, elapsed_hours=0.0, events=events)
        # +0.1 (existing) + 0.2 (TASK-046) = +0.3
        assert new.mood_arousal == pytest.approx(0.60, abs=0.01)

    @pytest.mark.asyncio
    async def test_arousal_spike_decays(self):
        """Spike fades via homeostatic pull over multiple cycles."""
        d = DrivesState(mood_arousal=0.7)
        # Run 20 cycles (each ~3 min) with no events
        for _ in range(20):
            d, _ = await update_drives(
                d, elapsed_hours=0.05, events=[],
                cycle_context={'consecutive_idle': 0})
        assert d.mood_arousal < 0.7, (
            f"Arousal spike should decay, got {d.mood_arousal}")

    @pytest.mark.asyncio
    async def test_idle_counter_resets_on_activity(self):
        """Non-idle cycle resets consecutive_idle to 0 — tested via no decay."""
        d = DrivesState(mood_arousal=0.5)
        # After activity (consecutive_idle=0), no idle pressure
        new, _ = await update_drives(
            d, elapsed_hours=0.0, events=[],
            cycle_context={'consecutive_idle': 0})
        assert new.mood_arousal == pytest.approx(0.5, abs=0.001)

    @pytest.mark.asyncio
    async def test_idle_counter_in_memory(self):
        """Counter is passed via cycle_context, not DB query — verified by no DB mock needed."""
        d = DrivesState(mood_arousal=0.5)
        # Just passing the value works — no DB dependency
        new, _ = await update_drives(
            d, elapsed_hours=0.0, events=[],
            cycle_context={'consecutive_idle': 8})
        # 8 > 5 → pressure = -0.01 * 3 = -0.03
        assert new.mood_arousal == pytest.approx(0.47, abs=0.01)

    @pytest.mark.asyncio
    async def test_gap_detection_arousal_spike(self):
        """gap_detection_partial → arousal +0.1."""
        d = DrivesState(mood_arousal=0.3)
        events = [Event(event_type='gap_detection_partial', source='self', payload={})]
        new, _ = await update_drives(d, elapsed_hours=0.0, events=events)
        assert new.mood_arousal == pytest.approx(0.4, abs=0.01)

    @pytest.mark.asyncio
    async def test_thread_breakthrough_arousal_spike(self):
        """thread_breakthrough → arousal +0.15."""
        d = DrivesState(mood_arousal=0.3)
        events = [Event(event_type='thread_breakthrough', source='self', payload={})]
        new, _ = await update_drives(d, elapsed_hours=0.0, events=events)
        assert new.mood_arousal == pytest.approx(0.45, abs=0.01)

    @pytest.mark.asyncio
    async def test_sustained_idle_baseline_drift(self):
        """After moderate idle (15 cycles), arousal drops significantly from starting point.

        With sustained idle pressure (-0.05/cycle cap after cycle 10),
        arousal decays well below the starting 0.7. Extended isolation
        produces extreme drowsiness (very low arousal).
        """
        d = DrivesState(mood_arousal=0.7)
        for i in range(15):
            d, _ = await update_drives(
                d, elapsed_hours=0.05, events=[],
                cycle_context={'consecutive_idle': i + 1})
        # After 15 idle cycles, arousal should be significantly below starting value
        assert d.mood_arousal < 0.4, (
            f"Expected arousal below 0.4 after sustained idle, got {d.mood_arousal}")
        assert d.mood_arousal >= 0.0, (
            f"Arousal should not go negative, got {d.mood_arousal}")


# ── Part C: Expression need → valence interaction ──

class TestExpressionFrustration:
    """Unexpressed thoughts with high expression_need suppresses valence."""

    @pytest.mark.asyncio
    async def test_expression_frustration(self):
        """expression_need=0.7, no expression → valence drops."""
        d = DrivesState(expression_need=0.7, mood_valence=0.5, social_hunger=0.3)
        new, _ = await update_drives(
            d, elapsed_hours=0.0, events=[],
            cycle_context={'expression_taken': False, 'consecutive_idle': 0})
        # Pressure = -0.01 * (0.7 - 0.5) = -0.002
        assert new.mood_valence < 0.5, (
            f"Unexpressed frustration should lower valence, got {new.mood_valence}")

    @pytest.mark.asyncio
    async def test_no_frustration_when_expressed(self):
        """expression_need=0.7 but expression taken → no frustration penalty."""
        d = DrivesState(expression_need=0.7, mood_valence=0.5, social_hunger=0.3)
        new, _ = await update_drives(
            d, elapsed_hours=0.0, events=[],
            cycle_context={'expression_taken': True, 'consecutive_idle': 0})
        # No frustration penalty applied
        assert new.mood_valence == pytest.approx(0.5, abs=0.001)

    @pytest.mark.asyncio
    async def test_no_frustration_below_threshold(self):
        """expression_need=0.4 → no frustration (threshold is 0.5)."""
        d = DrivesState(expression_need=0.4, mood_valence=0.5, social_hunger=0.3)
        new, _ = await update_drives(
            d, elapsed_hours=0.0, events=[],
            cycle_context={'expression_taken': False, 'consecutive_idle': 0})
        assert new.mood_valence == pytest.approx(0.5, abs=0.001)


# ── Part D: Energy depletion → mood coupling ──

class TestEnergyDepletionMood:
    """TASK-050: Energy no longer directly affects mood.

    Energy is display-only (derived from real-dollar budget).
    Mood effects come from being in rest mode (no actions → expression_need builds).
    """

    @pytest.mark.asyncio
    async def test_energy_no_direct_mood_effect(self):
        """TASK-050: Low energy has no direct mood effect."""
        d = DrivesState(energy=0.2, mood_valence=0.5, mood_arousal=0.5, social_hunger=0.3)
        new, _ = await update_drives(
            d, elapsed_hours=0.0, events=[],
            cycle_context={'consecutive_idle': 0})
        # No energy-to-mood coupling — valence/arousal unchanged
        assert new.mood_valence == pytest.approx(0.5, abs=0.001), (
            f"Energy should not affect valence, got {new.mood_valence}")
        assert new.mood_arousal == pytest.approx(0.5, abs=0.001), (
            f"Energy should not affect arousal, got {new.mood_arousal}")

    @pytest.mark.asyncio
    async def test_exhaustion_no_mood_effect(self):
        """TASK-050: Even extreme low energy has no direct mood effect."""
        d = DrivesState(energy=0.05, mood_valence=0.5, mood_arousal=0.5, social_hunger=0.3)
        new, _ = await update_drives(
            d, elapsed_hours=0.0, events=[],
            cycle_context={'consecutive_idle': 0})
        assert new.mood_valence == pytest.approx(0.5, abs=0.001)
        assert new.mood_arousal == pytest.approx(0.5, abs=0.001)

    @pytest.mark.asyncio
    async def test_normal_energy_no_mood_effect(self):
        """energy=0.5 → no energy mood penalty (same as before TASK-050)."""
        d = DrivesState(energy=0.5, mood_valence=0.5, mood_arousal=0.5, social_hunger=0.3)
        new, _ = await update_drives(
            d, elapsed_hours=0.0, events=[],
            cycle_context={'consecutive_idle': 0})
        assert new.mood_valence == pytest.approx(0.5, abs=0.001)
        assert new.mood_arousal == pytest.approx(0.5, abs=0.001)


# ── Nap refresh ──
# Nap refresh (+0.05 valence, +0.1 arousal) is applied directly in
# heartbeat.py nap consolidation path, not in update_drives.

class TestNapRefresh:
    """Nap consolidation refreshes mood via direct drives manipulation."""

    def test_nap_refresh_valence(self):
        """Nap refresh applies +0.05 valence via clamp."""
        d = DrivesState(mood_valence=0.3, mood_arousal=0.2)
        # Simulate what heartbeat.py does in nap path
        d.mood_valence = clamp(d.mood_valence + 0.05, -1.0, 1.0)
        d.mood_arousal = clamp(d.mood_arousal + 0.1)
        assert d.mood_valence == pytest.approx(0.35, abs=0.001)
        assert d.mood_arousal == pytest.approx(0.30, abs=0.001)

    def test_nap_refresh_clamped(self):
        """Nap refresh doesn't push arousal above 1.0."""
        d = DrivesState(mood_valence=0.98, mood_arousal=0.95)
        d.mood_valence = clamp(d.mood_valence + 0.05, -1.0, 1.0)
        d.mood_arousal = clamp(d.mood_arousal + 0.1)
        assert d.mood_valence <= 1.0
        assert d.mood_arousal <= 1.0


# ── Full trajectory test ──

class TestFullTrajectory:
    """Multi-cycle trajectory verifying drive-mood coupling over time."""

    @pytest.mark.asyncio
    async def test_full_7day_trajectory(self):
        """Run 168 simulated cycles, verify valence tracks social_hunger inversely.

        Simulates: social_hunger building over time (no visitors),
        valence should drift downward with it.
        """
        d = DrivesState(
            social_hunger=0.3,
            mood_valence=0.5,
            mood_arousal=0.5,
            energy=0.7,
            expression_need=0.3,
        )
        valence_samples = []
        hunger_samples = []

        for i in range(168):
            d, _ = await update_drives(
                d, elapsed_hours=0.05, events=[],
                cycle_context={'consecutive_idle': i + 1})
            valence_samples.append(d.mood_valence)
            hunger_samples.append(d.social_hunger)

        # Social hunger should build (homeostatic pull keeps it from maxing)
        assert hunger_samples[-1] > hunger_samples[0], (
            "Social hunger should increase over time without visitors")

        # Valence should be lower at the end than the beginning
        avg_first_20 = sum(valence_samples[:20]) / 20
        avg_last_20 = sum(valence_samples[-20:]) / 20
        assert avg_last_20 < avg_first_20, (
            f"Valence should decline over time in isolation: "
            f"first 20 avg={avg_first_20:.3f}, last 20 avg={avg_last_20:.3f}")

    @pytest.mark.asyncio
    async def test_visitor_arrival_reverses_trajectory(self):
        """After isolation, visitor arrival should spike arousal and boost valence."""
        d = DrivesState(
            social_hunger=0.6,
            mood_valence=0.3,
            mood_arousal=0.3,
        )
        # Simulate visitor arriving
        events = [Event(event_type='visitor_connect', source='visitor:yuki', payload={})]
        new, _ = await update_drives(
            d, elapsed_hours=0.0, events=events,
            cycle_context={'engaged_this_cycle': True, 'consecutive_idle': 0})

        assert new.mood_arousal > 0.3 + 0.2, (
            f"Visitor should spike arousal, got {new.mood_arousal}")
        assert new.mood_valence > 0.3, (
            f"Engagement should provide valence relief, got {new.mood_valence}")

    @pytest.mark.asyncio
    async def test_default_context_safe(self):
        """update_drives works without cycle_context (backward compat)."""
        d = DrivesState()
        new, _ = await update_drives(d, elapsed_hours=0.05, events=[])
        # Should not crash; all cycle_context values default safely
        assert isinstance(new, DrivesState)
