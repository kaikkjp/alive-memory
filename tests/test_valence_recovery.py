"""Tests for HOTFIX-002: Valence death spiral prevention.

Verifies the four mechanisms that prevent catatonic states:
1. Exponential homeostatic spring at extremes
2. Per-cycle valence delta clamp
3. Hard floor at -0.85
4. Action success micro-boost at extreme negative valence
"""

import pytest

from models.state import DrivesState
from models.pipeline import ActionResult, BodyOutput
from pipeline.hypothalamus import (
    _homeostatic_pull, update_drives, clamp,
    VALENCE_HARD_FLOOR, MAX_VALENCE_DELTA_PER_CYCLE,
)


# ── Mechanism 1: Exponential spring at extremes ──

class TestExponentialSpring:

    def test_spring_stronger_at_extreme_than_mild(self):
        """Spring force at valence=-1.0 should be much stronger than at -0.3."""
        elapsed = 0.08  # ~5 min cycle
        equilibrium = 0.05

        # At extreme: distance = 1.05
        result_extreme = _homeostatic_pull(-1.0, equilibrium, elapsed, -1.0, 1.0)
        force_extreme = result_extreme - (-1.0)

        # At mild: distance = 0.35 (below 0.5, linear spring)
        result_mild = _homeostatic_pull(-0.3, equilibrium, elapsed, -1.0, 1.0)
        force_mild = result_mild - (-0.3)

        assert force_extreme > force_mild * 3, (
            f"Extreme spring ({force_extreme:.4f}) should be >3x mild ({force_mild:.4f})"
        )

    def test_linear_spring_in_normal_range(self):
        """Within ±0.5 of equilibrium, spring should behave linearly."""
        equilibrium = 0.05
        elapsed = 0.08

        # At -0.3: distance = 0.35 (within 0.5, linear)
        result = _homeostatic_pull(-0.3, equilibrium, elapsed, -1.0, 1.0)
        force = result - (-0.3)

        # Expected linear: (0.05 - -0.3) * 0.15 * 0.08 = 0.0042
        expected = 0.35 * 0.15 * 0.08
        assert abs(force - expected) < 0.001, (
            f"Linear spring expected {expected:.4f}, got {force:.4f}"
        )

    def test_exponential_kicks_in_past_half(self):
        """Spring at distance=0.6 should be stronger than linear would predict."""
        equilibrium = 0.05
        elapsed = 1.0

        # At -0.55: distance = 0.60 (just past 0.5 threshold)
        result = _homeostatic_pull(-0.55, equilibrium, elapsed, -1.0, 1.0)
        force = result - (-0.55)

        # Linear would be: 0.60 * 0.15 * 1.0 = 0.09
        linear_force = 0.60 * 0.15 * 1.0
        # Exponential: multiplier = 1 + (0.60 * 3) = 2.8
        # So force = 0.09 * 2.8 = 0.252
        assert force > linear_force * 2, (
            f"Exponential spring ({force:.4f}) should be >2x linear ({linear_force:.4f})"
        )


# ── Mechanism 2: Per-cycle valence clamp ──

class TestValenceClamp:

    @pytest.mark.asyncio
    async def test_clamp_limits_downward_swing(self):
        """Coupling forces cannot swing valence more than 0.10 down per cycle."""
        # Start at -0.5 with conditions that would push valence way down:
        # high social hunger + high expression need + no visitor
        d = DrivesState(
            mood_valence=-0.5,
            social_hunger=0.9,
            expression_need=0.9,
        )
        ctx = {
            'engaged_this_cycle': False,
            'consecutive_idle': 10,
            'expression_taken': False,
        }
        new, _ = await update_drives(d, elapsed_hours=0.08, events=[], cycle_context=ctx)
        delta = new.mood_valence - (-0.5)
        # Delta could be positive (spring) or negative (coupling) but limited
        assert delta >= -MAX_VALENCE_DELTA_PER_CYCLE - 0.001, (
            f"Valence dropped by {abs(delta):.4f}, exceeding clamp of {MAX_VALENCE_DELTA_PER_CYCLE}"
        )

    @pytest.mark.asyncio
    async def test_clamp_allows_upward_recovery(self):
        """Spring pulling up is also clamped but still allows recovery."""
        d = DrivesState(mood_valence=-0.85)
        new, _ = await update_drives(d, elapsed_hours=0.08, events=[])
        # Spring should pull up, clamped to +0.10 max
        assert new.mood_valence >= -0.85, "Valence should not drop below entry"
        delta = new.mood_valence - (-0.85)
        assert delta <= MAX_VALENCE_DELTA_PER_CYCLE + 0.001

    @pytest.mark.asyncio
    async def test_normal_range_unaffected(self):
        """In normal range (-0.3 to +0.3), small changes go through unclamped."""
        d = DrivesState(mood_valence=0.0)
        new, _ = await update_drives(d, elapsed_hours=0.08, events=[])
        # Near equilibrium, spring force is tiny — should pass through clamp
        delta = abs(new.mood_valence - 0.0)
        assert delta < MAX_VALENCE_DELTA_PER_CYCLE, (
            "Small changes in normal range should be within clamp"
        )


# ── Mechanism 3: Hard floor ──

class TestHardFloor:

    @pytest.mark.asyncio
    async def test_valence_never_below_floor(self):
        """Valence never drops below -0.85 regardless of forces."""
        d = DrivesState(
            mood_valence=-0.84,
            social_hunger=1.0,
            expression_need=1.0,
        )
        ctx = {
            'engaged_this_cycle': False,
            'consecutive_idle': 20,
            'expression_taken': False,
        }
        new, _ = await update_drives(d, elapsed_hours=1.0, events=[], cycle_context=ctx)
        assert new.mood_valence >= VALENCE_HARD_FLOOR, (
            f"Valence {new.mood_valence:.4f} breached floor {VALENCE_HARD_FLOOR}"
        )

    @pytest.mark.asyncio
    async def test_floor_holds_over_50_cycles(self):
        """50 hostile cycles starting at floor — valence stays at or above floor."""
        valence = VALENCE_HARD_FLOOR
        for i in range(50):
            d = DrivesState(
                mood_valence=valence,
                social_hunger=0.8,
                expression_need=0.7,
            )
            ctx = {
                'engaged_this_cycle': False,
                'consecutive_idle': i,
                'expression_taken': False,
            }
            new, _ = await update_drives(d, elapsed_hours=0.08, events=[], cycle_context=ctx)
            valence = new.mood_valence
            assert valence >= VALENCE_HARD_FLOOR, (
                f"Cycle {i}: valence {valence:.4f} breached floor"
            )

    @pytest.mark.asyncio
    async def test_floor_at_entry_below(self):
        """If valence somehow starts below floor (legacy data), floor corrects it."""
        d = DrivesState(mood_valence=-1.0)
        new, _ = await update_drives(d, elapsed_hours=0.08, events=[])
        assert new.mood_valence >= VALENCE_HARD_FLOOR


# ── Mechanism 4: Action success micro-boost ──

class TestActionSuccessBoost:

    @pytest.mark.asyncio
    async def test_success_boost_at_extreme(self):
        """Completing an action at extreme negative valence gives +0.05."""
        import db
        from unittest.mock import AsyncMock, patch

        drives = DrivesState(mood_valence=-0.85)
        body_output = BodyOutput(
            executed=[ActionResult(action='rearrange', success=True)]
        )

        with patch.object(db, 'get_drives_state', new_callable=AsyncMock, return_value=drives), \
             patch.object(db, 'save_drives_state', new_callable=AsyncMock) as mock_save, \
             patch.object(db, 'get_executed_action_count_today', new_callable=AsyncMock, return_value=0), \
             patch.object(db, 'get_engagement_state', new_callable=AsyncMock), \
             patch.object(db, 'get_all_habits', new_callable=AsyncMock, return_value=[]), \
             patch.object(db, 'log_action', new_callable=AsyncMock), \
             patch.object(db, 'count_cycle_logs', new_callable=AsyncMock, return_value=0):

            from pipeline.output import process_output
            from models.pipeline import ValidatedOutput, MotorPlan, ActionDecision

            validated = ValidatedOutput(dialogue='...')
            motor_plan = MotorPlan(
                actions=[ActionDecision(action='rearrange', impulse=0.5)]
            )

            await process_output(body_output, validated, motor_plan=motor_plan, cycle_id='test')

            # Check that save was called with boosted valence
            if mock_save.called:
                saved_drives = mock_save.call_args[0][0]
                assert saved_drives.mood_valence > -0.85, (
                    f"Expected valence > -0.85 after success boost, got {saved_drives.mood_valence}"
                )

    @pytest.mark.asyncio
    async def test_speak_action_gets_extra_boost(self):
        """Speak action at extreme valence gets +0.10 total (0.05 base + 0.05 dialogue)."""
        import db
        from unittest.mock import AsyncMock, patch

        drives = DrivesState(mood_valence=-0.85)
        body_output = BodyOutput(
            executed=[ActionResult(action='speak', success=True)]
        )

        with patch.object(db, 'get_drives_state', new_callable=AsyncMock, return_value=drives), \
             patch.object(db, 'save_drives_state', new_callable=AsyncMock) as mock_save, \
             patch.object(db, 'get_executed_action_count_today', new_callable=AsyncMock, return_value=0), \
             patch.object(db, 'get_engagement_state', new_callable=AsyncMock), \
             patch.object(db, 'get_all_habits', new_callable=AsyncMock, return_value=[]), \
             patch.object(db, 'log_action', new_callable=AsyncMock), \
             patch.object(db, 'count_cycle_logs', new_callable=AsyncMock, return_value=0):

            from pipeline.output import process_output
            from models.pipeline import ValidatedOutput, MotorPlan, ActionDecision

            validated = ValidatedOutput(dialogue='...')
            motor_plan = MotorPlan(
                actions=[ActionDecision(action='speak', impulse=0.5)]
            )

            await process_output(body_output, validated, motor_plan=motor_plan, cycle_id='test')

            if mock_save.called:
                saved_drives = mock_save.call_args[0][0]
                # speak at extreme: +0.05 base + 0.05 dialogue = +0.10
                assert saved_drives.mood_valence >= -0.76, (
                    f"Expected valence >= -0.76 after speak boost, got {saved_drives.mood_valence}"
                )


# ── Integration: Death spiral recovery simulation ──

class TestDeathSpiralRecovery:

    @pytest.mark.asyncio
    async def test_no_breach_50_hostile_cycles(self):
        """50 cycles starting at -0.85 with hostile context — floor holds."""
        valence = VALENCE_HARD_FLOOR
        for i in range(50):
            d = DrivesState(
                mood_valence=valence,
                social_hunger=0.7,
            )
            new, _ = await update_drives(d, elapsed_hours=0.08, events=[])
            valence = new.mood_valence
            assert valence >= VALENCE_HARD_FLOOR

    @pytest.mark.asyncio
    async def test_recovery_with_action_success(self):
        """Starting at floor, one action success should start upward trend."""
        valence = VALENCE_HARD_FLOOR

        # 10 cycles at floor with no actions
        for _ in range(10):
            d = DrivesState(mood_valence=valence)
            new, _ = await update_drives(d, elapsed_hours=0.08, events=[])
            valence = new.mood_valence

        # One action success: +0.05 (the circuit breaker)
        valence = min(valence + 0.05, 1.0)

        # 20 more cycles — spring should be winning now
        for _ in range(20):
            d = DrivesState(mood_valence=valence)
            new, _ = await update_drives(d, elapsed_hours=0.08, events=[])
            valence = new.mood_valence

        assert valence > -0.80, (
            f"After action success + 20 cycles, expected valence > -0.80, got {valence:.4f}"
        )

    @pytest.mark.asyncio
    async def test_spring_alone_recovers_from_floor(self):
        """Even without actions, exponential spring should slowly pull from floor.

        The spring at -0.85 (distance=0.90) with multiplier=3.7 gives
        meaningful upward force that fights the per-cycle clamp.
        Over many cycles, she should drift up.
        """
        valence = VALENCE_HARD_FLOOR
        for _ in range(100):
            d = DrivesState(mood_valence=valence)
            new, _ = await update_drives(d, elapsed_hours=0.08, events=[])
            valence = new.mood_valence

        # After 100 cycles (~8 hours), spring should have pulled up meaningfully
        assert valence > VALENCE_HARD_FLOOR, (
            f"After 100 cycles of spring pull, expected recovery above floor, got {valence:.4f}"
        )

    @pytest.mark.asyncio
    async def test_normal_valence_unchanged_by_hotfix(self):
        """Valence in normal range (-0.3 to +0.3) should behave as before.

        The exponential spring only kicks in past distance=0.5.
        The clamp of ±0.10 doesn't affect small normal-range changes.
        """
        d = DrivesState(mood_valence=0.0)
        new, _ = await update_drives(d, elapsed_hours=0.08, events=[])

        # Near equilibrium (0.05), spring is tiny, no clamp needed
        assert -0.1 < new.mood_valence < 0.1, (
            f"Normal-range valence shouldn't swing wildly, got {new.mood_valence:.4f}"
        )
