"""Tests for day_memory salience scoring (TASK-025).

Verifies that compute_moment_salience produces distinct values for
different content types, emotional intensities, and action diversity.
"""

import pytest
from pipeline.day_memory import compute_moment_salience


def _base_result(**overrides):
    """Minimal cycle result dict."""
    r = {'resonance': False, 'actions': [], 'internal_monologue': '', 'dialogue': ''}
    r.update(overrides)
    return r


def _base_ctx(**overrides):
    """Minimal cycle context dict."""
    c = {
        'has_internal_conflict': False,
        'had_contradiction': False,
        'trust_level': 'stranger',
        'max_drive_delta': 0.0,
        'mode': 'idle',
    }
    c.update(overrides)
    return c


class TestDistinctSalienceValues:
    """The core TASK-025 requirement: different inputs → different scores."""

    def test_at_least_three_distinct_scores(self):
        """Five representative cycles produce at least 3 distinct salience values."""
        # Scenario 1: bare idle cycle (no resonance, no actions, no delta)
        s1 = compute_moment_salience(_base_result(), _base_ctx())

        # Scenario 2: resonance + journal write (the old "always 0.55" case)
        s2 = compute_moment_salience(
            _base_result(resonance=True, actions=[{'type': 'write_journal'}]),
            _base_ctx(),
        )

        # Scenario 3: resonance + long monologue + engage mode + moderate delta
        s3 = compute_moment_salience(
            _base_result(
                resonance=True,
                internal_monologue='word ' * 60,  # 60 words
                dialogue='hello there visitor how are you',
                actions=[{'type': 'speak'}, {'type': 'write_journal'}],
            ),
            _base_ctx(mode='engage', max_drive_delta=0.15, trust_level='regular'),
        )

        # Scenario 4: internal conflict with no other signals
        s4 = compute_moment_salience(
            _base_result(),
            _base_ctx(has_internal_conflict=True),
        )

        # Scenario 5: small delta + familiar visitor + no resonance
        s5 = compute_moment_salience(
            _base_result(
                internal_monologue='a brief thought',
                actions=[{'type': 'speak'}],
            ),
            _base_ctx(trust_level='familiar', max_drive_delta=0.08, mode='engage'),
        )

        scores = {round(s, 4) for s in [s1, s2, s3, s4, s5]}
        assert len(scores) >= 3, (
            f"Expected at least 3 distinct salience values, got {len(scores)}: "
            f"{sorted(scores)}"
        )


class TestContinuousFactors:
    """Continuous factors produce gradual variance, not flat steps."""

    def test_drive_delta_scales_linearly(self):
        """Different drive deltas produce different scores."""
        s_low = compute_moment_salience(
            _base_result(), _base_ctx(max_drive_delta=0.05),
        )
        s_mid = compute_moment_salience(
            _base_result(), _base_ctx(max_drive_delta=0.15),
        )
        s_high = compute_moment_salience(
            _base_result(), _base_ctx(max_drive_delta=0.30),
        )
        assert s_low < s_mid < s_high

    def test_drive_delta_caps_at_025(self):
        """Extreme drive delta caps contribution at 0.25."""
        s_cap = compute_moment_salience(
            _base_result(), _base_ctx(max_drive_delta=0.5),
        )
        s_extreme = compute_moment_salience(
            _base_result(), _base_ctx(max_drive_delta=1.0),
        )
        assert s_cap == s_extreme

    def test_monologue_length_affects_score(self):
        """Longer monologue = higher salience."""
        s_short = compute_moment_salience(
            _base_result(internal_monologue='brief'),
            _base_ctx(),
        )
        s_long = compute_moment_salience(
            _base_result(internal_monologue='word ' * 80),
            _base_ctx(),
        )
        assert s_long > s_short

    def test_dialogue_length_affects_score(self):
        """Longer dialogue = higher salience."""
        s_none = compute_moment_salience(
            _base_result(dialogue=''),
            _base_ctx(),
        )
        s_long = compute_moment_salience(
            _base_result(dialogue='word ' * 50),
            _base_ctx(),
        )
        assert s_long > s_none

    def test_action_diversity_affects_score(self):
        """More distinct action types = higher salience."""
        s_one = compute_moment_salience(
            _base_result(actions=[{'type': 'speak'}]),
            _base_ctx(),
        )
        s_two = compute_moment_salience(
            _base_result(actions=[{'type': 'speak'}, {'type': 'write_journal'}]),
            _base_ctx(),
        )
        assert s_two > s_one

    def test_mode_bonus_varies(self):
        """Different cycle modes produce different base scores."""
        s_idle = compute_moment_salience(_base_result(), _base_ctx(mode='idle'))
        s_engage = compute_moment_salience(_base_result(), _base_ctx(mode='engage'))
        s_express = compute_moment_salience(_base_result(), _base_ctx(mode='express'))
        assert s_engage > s_idle
        assert s_express > s_idle


class TestBooleanSignals:
    """Boolean signals still work correctly after rebalancing."""

    def test_internal_conflict_adds_04(self):
        """Internal conflict contributes +0.4."""
        s_base = compute_moment_salience(_base_result(), _base_ctx())
        s_conflict = compute_moment_salience(
            _base_result(), _base_ctx(has_internal_conflict=True),
        )
        assert abs((s_conflict - s_base) - 0.4) < 0.001

    def test_resonance_adds_02(self):
        """Cortex resonance flag contributes +0.2 (reduced from old 0.4)."""
        s_base = compute_moment_salience(_base_result(), _base_ctx())
        s_reso = compute_moment_salience(
            _base_result(resonance=True), _base_ctx(),
        )
        assert abs((s_reso - s_base) - 0.2) < 0.001

    def test_contradiction_adds_03(self):
        """Contradiction contributes +0.3."""
        s_base = compute_moment_salience(_base_result(), _base_ctx())
        s_contra = compute_moment_salience(
            _base_result(), _base_ctx(had_contradiction=True),
        )
        assert abs((s_contra - s_base) - 0.3) < 0.001

    def test_gift_adds_025(self):
        """Gift action contributes +0.25."""
        s_base = compute_moment_salience(_base_result(), _base_ctx())
        s_gift = compute_moment_salience(
            _base_result(actions=[{'type': 'accept_gift'}]), _base_ctx(),
        )
        # gift (0.25) + action_diversity (0.05) = 0.30
        assert (s_gift - s_base) >= 0.25

    def test_dropped_actions_adds_01(self):
        """Dropped actions contribute +0.1."""
        s_base = compute_moment_salience(_base_result(), _base_ctx())
        s_drop = compute_moment_salience(
            _base_result(_dropped_actions=[{'action': {'type': 'x'}, 'reason': 'y'}]),
            _base_ctx(),
        )
        assert abs((s_drop - s_base) - 0.1) < 0.001


class TestScoreBounds:
    """Score is always in [0.0, 1.0]."""

    def test_empty_cycle_has_zero_score(self):
        """Bare idle cycle with no signals scores 0.0."""
        s = compute_moment_salience(_base_result(), _base_ctx())
        assert s == 0.0

    def test_maximum_signals_capped_at_1(self):
        """Stacking every signal caps at 1.0."""
        result = _base_result(
            resonance=True,
            internal_monologue='word ' * 200,
            dialogue='word ' * 200,
            actions=[
                {'type': 'accept_gift'},
                {'type': 'write_journal'},
                {'type': 'speak'},
            ],
            _dropped_actions=[{'action': {'type': 'x'}, 'reason': 'y'}],
        )
        ctx = _base_ctx(
            has_internal_conflict=True,
            had_contradiction=True,
            trust_level='familiar',
            max_drive_delta=0.5,
            mode='engage',
        )
        s = compute_moment_salience(result, ctx)
        assert s == 1.0


class TestOldFlatScoreFixed:
    """Verify the specific bug scenario is fixed: resonance+journal != always 0.55."""

    def test_resonance_journal_no_longer_identical(self):
        """Two resonance+journal cycles with different content produce different scores."""
        # Cycle A: resonance + journal, short monologue
        s_a = compute_moment_salience(
            _base_result(
                resonance=True,
                internal_monologue='brief thought',
                actions=[{'type': 'write_journal'}],
            ),
            _base_ctx(max_drive_delta=0.02),
        )

        # Cycle B: resonance + journal, long monologue, some drive movement
        s_b = compute_moment_salience(
            _base_result(
                resonance=True,
                internal_monologue='word ' * 50,
                actions=[{'type': 'write_journal'}],
            ),
            _base_ctx(max_drive_delta=0.12),
        )

        assert s_a != s_b, f"Both scored {s_a} — still flat!"
