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


class TestJournalNoSalienceBoost:
    """write_journal no longer inflates salience — content speaks for itself."""

    def test_write_journal_no_bonus(self):
        """write_journal action alone contributes only action_diversity, not +0.08."""
        s_base = compute_moment_salience(_base_result(), _base_ctx())
        s_journal = compute_moment_salience(
            _base_result(actions=[{'type': 'write_journal'}]),
            _base_ctx(),
        )
        # Only action_diversity bonus (0.05), no self-expression bonus
        assert abs((s_journal - s_base) - 0.05) < 0.001

    def test_post_x_draft_still_gets_bonus(self):
        """post_x_draft retains the +0.08 self-expression boost."""
        s_base = compute_moment_salience(_base_result(), _base_ctx())
        s_post = compute_moment_salience(
            _base_result(actions=[{'type': 'post_x_draft'}]),
            _base_ctx(),
        )
        # action_diversity (0.05) + self-expression (0.08) + rare_action (0.08) = 0.21
        assert abs((s_post - s_base) - 0.21) < 0.001


class TestSoloCycleSignals:
    """Solo cycle signals let her form memories without visitors."""

    def test_thread_touch_adds_012(self):
        """Thread update/create/close contributes +0.12 (TASK-047 boost)."""
        s_base = compute_moment_salience(_base_result(), _base_ctx())
        s_thread = compute_moment_salience(
            _base_result(actions=[{'type': 'thread_update'}]),
            _base_ctx(),
        )
        # thread_touch (0.12) + action_diversity (0.05) + rare_action (0.08)
        expected_delta = 0.12 + 0.05 + 0.08
        assert abs((s_thread - s_base) - expected_delta) < 0.001

    def test_thread_create_also_counts(self):
        """thread_create triggers the thread touch signal too."""
        s_base = compute_moment_salience(_base_result(), _base_ctx())
        s_create = compute_moment_salience(
            _base_result(actions=[{'type': 'thread_create'}]),
            _base_ctx(),
        )
        assert s_create > s_base + 0.12  # at least thread_touch bonus

    def test_content_consumed_adds_014(self):
        """Consume mode contributes +0.14 content + 0.04 mode (TASK-047 boost)."""
        s_base = compute_moment_salience(_base_result(), _base_ctx(mode='idle'))
        s_consume = compute_moment_salience(
            _base_result(), _base_ctx(mode='consume'),
        )
        # consume mode bonus (0.04) + content_consumed (0.14) = 0.18
        assert abs((s_consume - s_base) - 0.18) < 0.001

    def test_news_mode_also_counts(self):
        """News mode also triggers the content consumed signal."""
        s_consume = compute_moment_salience(
            _base_result(), _base_ctx(mode='consume'),
        )
        s_news = compute_moment_salience(
            _base_result(), _base_ctx(mode='news'),
        )
        # Both get content_consumed (+0.14), but news has no mode_bonus while consume has +0.04
        # news mode_bonus is 0.0, consume mode_bonus is 0.04
        assert abs(s_consume - s_news - 0.04) < 0.001

    def test_rare_action_adds_008(self):
        """Actions beyond write_journal/express_thought contribute +0.08 (TASK-047 boost)."""
        s_journal = compute_moment_salience(
            _base_result(actions=[{'type': 'write_journal'}]),
            _base_ctx(),
        )
        s_rare = compute_moment_salience(
            _base_result(actions=[{'type': 'rearrange'}]),
            _base_ctx(),
        )
        # Both get action_diversity (0.05), but rearrange also gets rare_action (0.08)
        assert abs((s_rare - s_journal) - 0.08) < 0.001

    def test_express_thought_is_routine(self):
        """express_thought does NOT trigger rare action bonus."""
        s_base = compute_moment_salience(_base_result(), _base_ctx())
        s_express = compute_moment_salience(
            _base_result(actions=[{'type': 'express_thought'}]),
            _base_ctx(),
        )
        # Only action_diversity (0.05), no rare_action
        assert abs((s_express - s_base) - 0.05) < 0.001

    def test_journal_with_content_adds_012(self):
        """write_journal with non-empty detail.text contributes +0.12 (TASK-047 boost)."""
        s_empty_journal = compute_moment_salience(
            _base_result(actions=[{'type': 'write_journal'}]),
            _base_ctx(),
        )
        s_content_journal = compute_moment_salience(
            _base_result(actions=[{
                'type': 'write_journal',
                'detail': {'text': 'Today I noticed something about the way light falls.'},
            }]),
            _base_ctx(),
        )
        assert abs((s_content_journal - s_empty_journal) - 0.12) < 0.001

    def test_journal_with_empty_detail_no_bonus(self):
        """write_journal with empty/whitespace detail.text gets no journal-content bonus."""
        s_empty = compute_moment_salience(
            _base_result(actions=[{'type': 'write_journal', 'detail': {'text': ''}}]),
            _base_ctx(),
        )
        s_whitespace = compute_moment_salience(
            _base_result(actions=[{'type': 'write_journal', 'detail': {'text': '   '}}]),
            _base_ctx(),
        )
        s_no_detail = compute_moment_salience(
            _base_result(actions=[{'type': 'write_journal'}]),
            _base_ctx(),
        )
        assert s_empty == s_no_detail
        assert s_whitespace == s_no_detail


class TestSoloCycleThresholdScenarios:
    """Verify the target score ranges from the spec."""

    def test_solo_thread_journal_above_threshold(self):
        """Solo cycle with thread touch + journal about it scores well above 0.35 (TASK-047 boost)."""
        score = compute_moment_salience(
            _base_result(
                resonance=True,
                internal_monologue='word ' * 30,
                actions=[
                    {'type': 'thread_update'},
                    {'type': 'write_journal', 'detail': {'text': 'The thread keeps pulling.'}},
                ],
            ),
            _base_ctx(mode='express', max_drive_delta=0.05),
        )
        assert score >= 0.35, f"Thread+journal solo cycle scored {score}, expected >= 0.35"
        # Should be well above threshold
        assert score > 0.40, f"Thread+journal solo cycle scored {score}, expected > 0.40"

    def test_routine_express_thought_barely_above(self):
        """Routine express_thought with resonance scores ~0.38-0.43 — above threshold but moderate."""
        score = compute_moment_salience(
            _base_result(
                resonance=True,
                internal_monologue='word ' * 25,
                actions=[{'type': 'express_thought'}],
            ),
            _base_ctx(mode='express', max_drive_delta=0.04),
        )
        assert score >= 0.35, f"Routine express cycle scored {score}, expected >= 0.35"
        # Should be close to threshold, not way above
        assert score < 0.45, f"Routine express cycle scored {score}, expected < 0.45"

    def test_truly_empty_cycle_below_threshold(self):
        """Empty idle cycle with no signals scores ~0.0 — well below threshold."""
        score = compute_moment_salience(_base_result(), _base_ctx())
        assert score < 0.35, f"Empty cycle scored {score}, expected < 0.35"

    def test_consume_cycle_above_threshold(self):
        """Consume cycle with resonance and content scores above threshold."""
        score = compute_moment_salience(
            _base_result(
                resonance=True,
                internal_monologue='This article about ceramics reminded me of something.',
                actions=[{'type': 'collection_add'}],
            ),
            _base_ctx(mode='consume', max_drive_delta=0.06),
        )
        assert score >= 0.35, f"Consume cycle scored {score}, expected >= 0.35"


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
