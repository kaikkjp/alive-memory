"""Tests for day_memory salience scoring (TASK-025, updated TASK-050).

Verifies that compute_moment_salience produces distinct values for
different content types using the base-salience model.

TASK-050 replaced the additive model with a base-salience model:
- Each action type gets a guaranteed minimum salience (base)
- Modulation adds up to ~0.20 on top
- Idle fidgets stay at 0.0 → below threshold → no moment
"""

import pytest
from pipeline.day_memory import compute_moment_salience, MOMENT_THRESHOLD


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
        # Scenario 1: bare idle cycle
        s1 = compute_moment_salience(_base_result(), _base_ctx())

        # Scenario 2: resonance + journal write
        s2 = compute_moment_salience(
            _base_result(resonance=True, actions=[{
                'type': 'write_journal',
                'detail': {'text': 'Something happened today.'},
            }]),
            _base_ctx(),
        )

        # Scenario 3: visitor interaction + long monologue + drive delta
        s3 = compute_moment_salience(
            _base_result(
                resonance=True,
                internal_monologue='word ' * 60,
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

        # Scenario 5: small delta + familiar visitor
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


class TestBaseSalienceHierarchy:
    """Base salience values follow the priority hierarchy from the spec."""

    def test_internal_conflict_highest(self):
        """Internal conflict (0.80) is the highest base salience."""
        s = compute_moment_salience(_base_result(), _base_ctx(has_internal_conflict=True))
        assert s >= 0.80

    def test_contradiction_high(self):
        """Contradiction (0.75) is high priority."""
        s = compute_moment_salience(_base_result(), _base_ctx(had_contradiction=True))
        assert s >= 0.75

    def test_visitor_interaction(self):
        """Visitor interaction (engage mode) gets base 0.70."""
        s = compute_moment_salience(_base_result(), _base_ctx(mode='engage'))
        assert s >= 0.70

    def test_gift_interaction(self):
        """Gift actions get base 0.70."""
        s = compute_moment_salience(
            _base_result(actions=[{'type': 'accept_gift'}]),
            _base_ctx(),
        )
        assert s >= 0.70

    def test_content_consumed(self):
        """Consume channel gets base 0.60 (TASK-053: channel, not mode)."""
        s = compute_moment_salience(_base_result(), _base_ctx(channel='consume'))
        assert s >= 0.60

    def test_news_channel_also_consumes(self):
        """News channel also triggers content consumed base."""
        s = compute_moment_salience(_base_result(), _base_ctx(channel='news'))
        assert s >= 0.60

    def test_read_content_action_also_consumes(self):
        """read_content action gets base 0.60 regardless of mode/channel."""
        s = compute_moment_salience(
            _base_result(actions=[{'type': 'read_content'}]),
            _base_ctx(),
        )
        assert s >= 0.60

    def test_thread_work(self):
        """Thread actions get base 0.55."""
        s = compute_moment_salience(
            _base_result(actions=[{'type': 'thread_update'}]),
            _base_ctx(),
        )
        assert s >= 0.55

    def test_journal_with_content(self):
        """write_journal with text gets base 0.50."""
        s = compute_moment_salience(
            _base_result(actions=[{
                'type': 'write_journal',
                'detail': {'text': 'Today I noticed something about the way light falls.'},
            }]),
            _base_ctx(),
        )
        assert s >= 0.50

    def test_post_x_draft(self):
        """post_x_draft gets base 0.50."""
        s = compute_moment_salience(
            _base_result(actions=[{'type': 'post_x_draft'}]),
            _base_ctx(),
        )
        assert s >= 0.50

    def test_express_thought_with_content(self):
        """express_thought with substantial monologue gets base 0.40."""
        s = compute_moment_salience(
            _base_result(
                actions=[{'type': 'express_thought'}],
                internal_monologue='I was thinking about how things change over time quite a lot',
            ),
            _base_ctx(),
        )
        assert s >= 0.40

    def test_hierarchy_ordering(self):
        """Higher-priority triggers produce higher base scores than lower ones."""
        s_conflict = compute_moment_salience(
            _base_result(), _base_ctx(has_internal_conflict=True))
        s_visitor = compute_moment_salience(
            _base_result(), _base_ctx(mode='engage'))
        s_consume = compute_moment_salience(
            _base_result(), _base_ctx(channel='consume'))
        s_thread = compute_moment_salience(
            _base_result(actions=[{'type': 'thread_update'}]), _base_ctx())
        s_journal = compute_moment_salience(
            _base_result(actions=[{
                'type': 'write_journal',
                'detail': {'text': 'content here'},
            }]), _base_ctx())

        assert s_conflict > s_visitor
        assert s_visitor > s_consume
        assert s_consume > s_thread
        assert s_thread > s_journal


class TestModulationFactors:
    """Modulation adds variance on top of base salience."""

    def test_drive_delta_adds_modulation(self):
        """Different drive deltas produce different scores for same base."""
        s_low = compute_moment_salience(
            _base_result(), _base_ctx(mode='engage', max_drive_delta=0.0))
        s_high = compute_moment_salience(
            _base_result(), _base_ctx(mode='engage', max_drive_delta=0.30))
        assert s_high > s_low

    def test_drive_delta_capped(self):
        """Drive delta modulation caps — extreme values don't run away."""
        s_cap = compute_moment_salience(
            _base_result(), _base_ctx(mode='engage', max_drive_delta=0.5))
        s_extreme = compute_moment_salience(
            _base_result(), _base_ctx(mode='engage', max_drive_delta=1.0))
        assert abs(s_cap - s_extreme) < 0.001

    def test_trust_adds_modulation(self):
        """Higher trust adds more modulation."""
        s_stranger = compute_moment_salience(
            _base_result(), _base_ctx(mode='engage', trust_level='stranger'))
        s_familiar = compute_moment_salience(
            _base_result(), _base_ctx(mode='engage', trust_level='familiar'))
        assert s_familiar > s_stranger

    def test_content_richness_adds_modulation(self):
        """Longer monologue/dialogue adds modulation."""
        s_bare = compute_moment_salience(
            _base_result(), _base_ctx(mode='engage'))
        s_rich = compute_moment_salience(
            _base_result(
                internal_monologue='word ' * 80,
                dialogue='word ' * 50,
            ),
            _base_ctx(mode='engage'))
        assert s_rich > s_bare

    def test_resonance_adds_modulation(self):
        """Resonance flag adds modulation when base already set."""
        s_no_reso = compute_moment_salience(
            _base_result(resonance=False), _base_ctx(mode='engage'))
        s_reso = compute_moment_salience(
            _base_result(resonance=True), _base_ctx(mode='engage'))
        assert s_reso > s_no_reso

    def test_event_salience_adds_modulation(self):
        """TASK-045 event salience adds modulation."""
        s_no_event = compute_moment_salience(
            _base_result(), _base_ctx(mode='engage'))
        s_event = compute_moment_salience(
            _base_result(), _base_ctx(mode='engage', event_salience_dynamic=0.9))
        assert s_event > s_no_event


class TestIdleFidgetNoMoment:
    """Idle fidgets produce base=0.0 → below threshold → no moment."""

    def test_empty_cycle_zero(self):
        """Bare idle cycle with no signals scores 0.0."""
        s = compute_moment_salience(_base_result(), _base_ctx())
        assert s == 0.0

    def test_idle_with_tiny_delta_still_zero(self):
        """Idle cycle with small drive delta but no meaningful action scores 0.0."""
        s = compute_moment_salience(
            _base_result(), _base_ctx(max_drive_delta=0.02))
        assert s == 0.0

    def test_idle_below_threshold(self):
        """Even with small signals, idle stays below threshold."""
        s = compute_moment_salience(_base_result(), _base_ctx())
        assert s < MOMENT_THRESHOLD


class TestResonanceAndDropped:
    """Resonance-only and dropped-action cycles get base 0.36."""

    def test_resonance_alone_above_threshold(self):
        """Resonance alone gets base 0.36 — above the 0.35 threshold."""
        s = compute_moment_salience(
            _base_result(resonance=True), _base_ctx())
        assert s >= 0.36
        assert s >= MOMENT_THRESHOLD

    def test_dropped_actions_above_threshold(self):
        """Dropped actions get base 0.36 — frustrated intent is worth noting."""
        s = compute_moment_salience(
            _base_result(_dropped_actions=[{'action': {'type': 'x'}, 'reason': 'y'}]),
            _base_ctx(),
        )
        assert s >= 0.36
        assert s >= MOMENT_THRESHOLD


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
                {'type': 'write_journal', 'detail': {'text': 'rich content'}},
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
            event_salience_dynamic=1.0,
        )
        s = compute_moment_salience(result, ctx)
        assert s == 1.0


class TestJournalContentMatters:
    """write_journal gets different bases depending on content."""

    def test_journal_without_content_no_base(self):
        """write_journal without content text gets no journal-specific base."""
        s = compute_moment_salience(
            _base_result(actions=[{'type': 'write_journal'}]),
            _base_ctx(),
        )
        # No text → doesn't trigger the 0.50 base for journal-with-content
        assert s < MOMENT_THRESHOLD

    def test_journal_with_content_gets_base(self):
        """write_journal with content text gets base 0.50."""
        s = compute_moment_salience(
            _base_result(actions=[{
                'type': 'write_journal',
                'detail': {'text': 'Today I noticed something about the way light falls.'},
            }]),
            _base_ctx(),
        )
        assert s >= 0.50

    def test_journal_empty_detail_no_base(self):
        """write_journal with empty/whitespace detail.text gets no journal base."""
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


class TestOldFlatScoreFixed:
    """Verify the specific bug scenario is fixed: resonance+journal != always 0.55."""

    def test_resonance_journal_no_longer_identical(self):
        """Two resonance+journal cycles with different content produce different scores."""
        # Cycle A: resonance + journal, short monologue
        s_a = compute_moment_salience(
            _base_result(
                resonance=True,
                internal_monologue='brief thought',
                actions=[{
                    'type': 'write_journal',
                    'detail': {'text': 'short'},
                }],
            ),
            _base_ctx(max_drive_delta=0.02),
        )

        # Cycle B: resonance + journal, long monologue, some drive movement
        s_b = compute_moment_salience(
            _base_result(
                resonance=True,
                internal_monologue='word ' * 50,
                actions=[{
                    'type': 'write_journal',
                    'detail': {'text': 'much longer content here'},
                }],
            ),
            _base_ctx(max_drive_delta=0.12),
        )

        assert s_a != s_b, f"Both scored {s_a} — still flat!"


class TestThresholdScenarios:
    """Verify the target score ranges from the spec."""

    def test_solo_thread_journal_above_threshold(self):
        """Solo cycle with thread touch + journal about it scores well above 0.35."""
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
        assert score >= MOMENT_THRESHOLD
        assert score > 0.50  # thread_update has base 0.55

    def test_truly_empty_cycle_below_threshold(self):
        """Empty idle cycle with no signals scores ~0.0 — well below threshold."""
        score = compute_moment_salience(_base_result(), _base_ctx())
        assert score < MOMENT_THRESHOLD

    def test_consume_cycle_above_threshold(self):
        """Consume channel cycle scores above threshold (TASK-053: channel not mode)."""
        score = compute_moment_salience(
            _base_result(
                resonance=True,
                internal_monologue='This article about ceramics reminded me of something.',
                actions=[{'type': 'collection_add'}],
            ),
            _base_ctx(channel='consume', max_drive_delta=0.06),
        )
        assert score >= MOMENT_THRESHOLD


class TestTask053ChannelFix:
    """TASK-053: channel-based content detection replaces broken mode check."""

    def test_channel_consume_gets_content_base(self):
        """channel='consume' triggers base 0.60."""
        s = compute_moment_salience(_base_result(), _base_ctx(channel='consume'))
        assert s >= 0.60

    def test_channel_news_gets_content_base(self):
        """channel='news' triggers base 0.60."""
        s = compute_moment_salience(_base_result(), _base_ctx(channel='news'))
        assert s >= 0.60

    def test_mode_consume_no_longer_works(self):
        """mode='consume' alone does NOT trigger content base (that's the bug)."""
        s = compute_moment_salience(_base_result(), _base_ctx(mode='consume'))
        # Without channel or read_content action, this is just idle
        assert s < MOMENT_THRESHOLD

    def test_read_content_action_works_without_channel(self):
        """read_content action triggers 0.60 base regardless of channel."""
        s = compute_moment_salience(
            _base_result(actions=[{'type': 'read_content'}]),
            _base_ctx(mode='idle'),  # typical production mode for content
        )
        assert s >= 0.60

    def test_executed_action_types_from_context(self):
        """executed_action_types in context also triggers base salience."""
        s = compute_moment_salience(
            _base_result(),
            _base_ctx(executed_action_types=['read_content']),
        )
        assert s >= 0.60


class TestTask053ConflictDetection:
    """TASK-053: has_internal_conflict is now reachable."""

    def test_internal_conflict_reachable(self):
        """has_internal_conflict=True reaches the 0.80 base tier."""
        s = compute_moment_salience(
            _base_result(), _base_ctx(has_internal_conflict=True))
        assert s >= 0.80

    def test_conflict_higher_than_visitor(self):
        """Internal conflict outranks visitor interaction."""
        s_conflict = compute_moment_salience(
            _base_result(), _base_ctx(has_internal_conflict=True))
        s_visitor = compute_moment_salience(
            _base_result(), _base_ctx(mode='engage'))
        assert s_conflict > s_visitor


class TestTask053ClassifyMoment:
    """TASK-053: classify_moment uses action types, not just resonance."""

    def test_classify_journal_not_resonance(self):
        """write_journal → 'self_expression', not 'resonance'."""
        from pipeline.day_memory import classify_moment
        mt = classify_moment(
            _base_result(
                resonance=True,
                actions=[{'type': 'write_journal',
                          'detail': {'text': 'some thought'}}],
            ),
            _base_ctx(),
        )
        assert mt == 'self_expression'

    def test_classify_read_content(self):
        """read_content → 'content_engagement'."""
        from pipeline.day_memory import classify_moment
        mt = classify_moment(
            _base_result(actions=[{'type': 'read_content'}]),
            _base_ctx(),
        )
        assert mt == 'content_engagement'

    def test_classify_consume_channel(self):
        """channel='consume' → 'content_engagement'."""
        from pipeline.day_memory import classify_moment
        mt = classify_moment(
            _base_result(),
            _base_ctx(channel='consume'),
        )
        assert mt == 'content_engagement'

    def test_classify_thread(self):
        """thread_update → 'thread_work'."""
        from pipeline.day_memory import classify_moment
        mt = classify_moment(
            _base_result(actions=[{'type': 'thread_update'}]),
            _base_ctx(),
        )
        assert mt == 'thread_work'

    def test_classify_rearrange(self):
        """rearrange → 'environmental_agency'."""
        from pipeline.day_memory import classify_moment
        mt = classify_moment(
            _base_result(actions=[{'type': 'rearrange'}]),
            _base_ctx(),
        )
        assert mt == 'environmental_agency'

    def test_classify_resonance_only(self):
        """Resonance without specific action → 'resonance'."""
        from pipeline.day_memory import classify_moment
        mt = classify_moment(
            _base_result(resonance=True),
            _base_ctx(),
        )
        assert mt == 'resonance'

    def test_conflict_still_highest(self):
        """Internal conflict classification still highest priority."""
        from pipeline.day_memory import classify_moment
        mt = classify_moment(
            _base_result(
                resonance=True,
                actions=[{'type': 'write_journal',
                          'detail': {'text': 'thought'}}],
            ),
            _base_ctx(has_internal_conflict=True),
        )
        assert mt == 'internal_conflict'

    def test_classify_executed_actions_from_context(self):
        """executed_action_types in context feeds classify_moment."""
        from pipeline.day_memory import classify_moment
        mt = classify_moment(
            _base_result(),
            _base_ctx(executed_action_types=['write_journal']),
        )
        assert mt == 'self_expression'


class TestTask053WiderModulation:
    """TASK-053: Modulation range is wider — spread > 0.15."""

    def test_modulation_wider_spread(self):
        """Same base (engage), varied modulation → spread > 0.15."""
        s_minimal = compute_moment_salience(
            _base_result(),
            _base_ctx(mode='engage', max_drive_delta=0.0, trust_level='stranger'),
        )
        s_maximal = compute_moment_salience(
            _base_result(
                resonance=True,
                internal_monologue='word ' * 100,
                dialogue='word ' * 100,
            ),
            _base_ctx(
                mode='engage',
                max_drive_delta=0.5,
                trust_level='familiar',
                mood_valence=0.7,
                event_salience_dynamic=1.0,
                executed_action_types=['speak', 'write_journal', 'show_item'],
            ),
        )
        spread = s_maximal - s_minimal
        assert spread > 0.15, f"Spread {spread:.3f} too narrow"

    def test_action_count_modulation(self):
        """More executed actions → higher modulation."""
        s_one = compute_moment_salience(
            _base_result(), _base_ctx(mode='engage', executed_action_types=['speak']))
        s_three = compute_moment_salience(
            _base_result(),
            _base_ctx(mode='engage',
                      executed_action_types=['speak', 'write_journal', 'show_item']))
        assert s_three > s_one

    def test_mood_extremes_modulation(self):
        """Mood valence extremes add modulation."""
        s_neutral = compute_moment_salience(
            _base_result(), _base_ctx(mode='engage', mood_valence=0.0))
        s_extreme_neg = compute_moment_salience(
            _base_result(), _base_ctx(mode='engage', mood_valence=-0.5))
        s_extreme_pos = compute_moment_salience(
            _base_result(), _base_ctx(mode='engage', mood_valence=0.7))
        assert s_extreme_neg > s_neutral
        assert s_extreme_pos > s_neutral
