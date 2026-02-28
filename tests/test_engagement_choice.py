"""Tests for TASK-012 + TASK-014: engagement choice.

TASK-012: visitor_connect as perception, not state change.
TASK-014: choice-based engagement via drives and basal ganglia.

Verifies:
- Sensorium: visitor_connect salience factors in trust, social hunger, absorption
- Thalamus: visitor_connect competes instead of auto-winning engage routing
- Thalamus: visitor_silence salience-gated (TASK-014)
- Executor: engagement state set on speak, not on connect
- Basal ganglia: visitor-directed priority modulation (TASK-014)
- Cortex: multi-visitor prompt context (TASK-014)
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch
from datetime import datetime, timezone

from models.state import DrivesState, EngagementState, Visitor
from models.event import Event
from models.pipeline import (
    ValidatedOutput, ActionRequest, MemoryUpdate, Intention, ActionDecision,
)
from pipeline.sensorium import calculate_connect_salience, Perception
from pipeline.thalamus import route
from pipeline.basal_ganglia import _calculate_priority, _is_visitor_target


# ── Sensorium: calculate_connect_salience ──

class TestConnectSalience:
    """visitor_connect salience factors in trust, social hunger, and absorption."""

    def test_stranger_neutral_drives(self):
        """Stranger with neutral drives gets moderate salience."""
        drives = DrivesState(social_hunger=0.5, expression_need=0.3, energy=0.8)
        salience = calculate_connect_salience(drives, 'stranger')
        assert 0.3 <= salience <= 0.5

    def test_familiar_high_social_hunger(self):
        """Familiar face + high social hunger = high salience."""
        drives = DrivesState(social_hunger=0.8, expression_need=0.3, energy=0.8)
        salience = calculate_connect_salience(drives, 'familiar')
        assert salience >= 0.8

    def test_stranger_absorbed(self):
        """Stranger + high expression_need (absorbed) = low salience."""
        drives = DrivesState(social_hunger=0.3, expression_need=0.8, energy=0.8)
        salience = calculate_connect_salience(drives, 'stranger')
        assert salience < 0.3

    def test_trust_increases_salience(self):
        """Higher trust level always means higher salience, same drives."""
        drives = DrivesState(social_hunger=0.5, expression_need=0.3, energy=0.8)
        stranger = calculate_connect_salience(drives, 'stranger')
        returner = calculate_connect_salience(drives, 'returner')
        regular = calculate_connect_salience(drives, 'regular')
        familiar = calculate_connect_salience(drives, 'familiar')
        assert stranger < returner < regular < familiar

    def test_social_hunger_increases_salience(self):
        """Higher social hunger means higher salience for same visitor."""
        low_hunger = DrivesState(social_hunger=0.2, expression_need=0.3, energy=0.8)
        high_hunger = DrivesState(social_hunger=0.8, expression_need=0.3, energy=0.8)
        sal_low = calculate_connect_salience(low_hunger, 'stranger')
        sal_high = calculate_connect_salience(high_hunger, 'stranger')
        assert sal_high > sal_low

    def test_low_energy_dampens(self):
        """Low energy dampens arrival salience."""
        normal = DrivesState(social_hunger=0.5, expression_need=0.3, energy=0.8)
        tired = DrivesState(social_hunger=0.5, expression_need=0.3, energy=0.2)
        sal_normal = calculate_connect_salience(normal, 'stranger')
        sal_tired = calculate_connect_salience(tired, 'stranger')
        assert sal_tired < sal_normal

    def test_clamped_to_unit_range(self):
        """Salience never exceeds [0, 1]."""
        # Max everything
        drives = DrivesState(social_hunger=1.0, expression_need=0.0, energy=1.0)
        assert calculate_connect_salience(drives, 'familiar') <= 1.0
        # Min everything
        drives = DrivesState(social_hunger=0.0, expression_need=1.0, energy=0.0)
        assert calculate_connect_salience(drives, 'stranger') >= 0.0


# ── Thalamus: visitor_connect routing ──

class TestConnectRouting:
    """visitor_connect competes via salience instead of auto-winning engage."""

    @pytest.mark.asyncio
    async def test_high_salience_connect_routes_to_engage(self):
        """High salience visitor_connect → engage cycle."""
        perceptions = [
            Perception(
                p_type='visitor_connect',
                source='visitor:v1',
                ts=datetime.now(timezone.utc),
                content='Someone new enters the shop.',
                features={'is_arrival': True},
                salience=0.7,
            ),
        ]
        drives = DrivesState()
        engagement = EngagementState(status='none')

        with patch('pipeline.thalamus.db') as mock_db:
            mock_db.get_flashbulb_count_today = AsyncMock(return_value=0)
            routing = await route(perceptions, drives, engagement)

        assert routing.cycle_type == 'engage'

    @pytest.mark.asyncio
    async def test_low_salience_connect_routes_to_idle(self):
        """Low salience visitor_connect → idle cycle (she continues what she was doing)."""
        perceptions = [
            Perception(
                p_type='visitor_connect',
                source='visitor:v1',
                ts=datetime.now(timezone.utc),
                content='Someone new enters the shop.',
                features={'is_arrival': True},
                salience=0.3,
            ),
        ]
        drives = DrivesState()
        engagement = EngagementState(status='none')

        with patch('pipeline.thalamus.db') as mock_db:
            mock_db.get_flashbulb_count_today = AsyncMock(return_value=0)
            routing = await route(perceptions, drives, engagement)

        assert routing.cycle_type == 'idle'

    @pytest.mark.asyncio
    async def test_borderline_salience_routes_to_engage(self):
        """Salience exactly at threshold (0.5) → engage."""
        perceptions = [
            Perception(
                p_type='visitor_connect',
                source='visitor:v1',
                ts=datetime.now(timezone.utc),
                content='Someone walks in.',
                features={'is_arrival': True},
                salience=0.5,
            ),
        ]
        drives = DrivesState()
        engagement = EngagementState(status='none')

        with patch('pipeline.thalamus.db') as mock_db:
            mock_db.get_flashbulb_count_today = AsyncMock(return_value=0)
            routing = await route(perceptions, drives, engagement)

        assert routing.cycle_type == 'engage'


# ── Output: engagement set on speak, not on connect ──

class TestEngagementOnSpeak:
    """Engagement state is set by output processing when she speaks, not on connect."""

    @pytest.mark.asyncio
    async def test_engagement_set_on_first_speak(self):
        """When she speaks to a visitor for the first time, engagement begins."""
        validated = ValidatedOutput(
            dialogue='Welcome.',

            expression='warm',
            body_state='standing',
            gaze='at_visitor',
            resonance=False,
            internal_monologue='Someone is here.',
        )

        with patch('pipeline.output.db') as mock_db, \
             patch('pipeline.output.clock') as mock_clock, \
             patch('pipeline.output.hippocampus_consolidate', new_callable=AsyncMock):

            now = datetime(2026, 2, 14, 12, 0, 0, tzinfo=timezone.utc)
            mock_clock.now_utc.return_value = now
            mock_db.get_engagement_state = AsyncMock(return_value=EngagementState(
                status='none', visitor_id=None,
            ))
            mock_db.update_engagement_state = AsyncMock()
            mock_db.update_visitor_present = AsyncMock()

            from models.pipeline import BodyOutput
            body_output = BodyOutput()
            from pipeline.output import process_output
            await process_output(body_output, validated, visitor_id='v1')

            # Should set engagement with started_at and turn_count=1
            mock_db.update_engagement_state.assert_any_call(
                status='engaged',
                visitor_id='v1',
                started_at=now,
                last_activity=now,
                turn_count=1,
            )

    @pytest.mark.asyncio
    async def test_engagement_increments_on_subsequent_speak(self):
        """When she speaks again, turn count increments but started_at is not reset."""
        validated = ValidatedOutput(
            dialogue='Tell me more.',

            expression='curious',
            body_state='leaning_forward',
            gaze='at_visitor',
            resonance=False,
            internal_monologue='Interesting.',
        )

        with patch('pipeline.output.db') as mock_db, \
             patch('pipeline.output.clock') as mock_clock, \
             patch('pipeline.output.hippocampus_consolidate', new_callable=AsyncMock):

            now = datetime(2026, 2, 14, 12, 5, 0, tzinfo=timezone.utc)
            mock_clock.now_utc.return_value = now
            mock_db.get_engagement_state = AsyncMock(return_value=EngagementState(
                status='engaged',
                visitor_id='v1',
                turn_count=3,
                started_at=datetime(2026, 2, 14, 12, 0, 0, tzinfo=timezone.utc),
            ))
            mock_db.update_engagement_state = AsyncMock()
            mock_db.update_visitor_present = AsyncMock()

            from models.pipeline import BodyOutput
            body_output = BodyOutput()
            from pipeline.output import process_output
            await process_output(body_output, validated, visitor_id='v1')

            # Should increment turn count without resetting started_at
            mock_db.update_engagement_state.assert_any_call(
                last_activity=now,
                turn_count=4,
            )

    @pytest.mark.asyncio
    async def test_no_engagement_on_silence(self):
        """Silence (no dialogue or '...') doesn't trigger engagement."""
        validated = ValidatedOutput(
            dialogue='...',

            expression='neutral',
            body_state='sitting',
            gaze='at_window',
            resonance=False,
            internal_monologue='Someone is here but I am busy.',
        )

        with patch('pipeline.output.db') as mock_db, \
             patch('pipeline.output.clock') as mock_clock, \
             patch('pipeline.output.hippocampus_consolidate', new_callable=AsyncMock):

            now = datetime(2026, 2, 14, 12, 0, 0, tzinfo=timezone.utc)
            mock_clock.now_utc.return_value = now
            mock_db.get_engagement_state = AsyncMock(return_value=EngagementState(
                status='none', visitor_id=None,
            ))
            mock_db.update_engagement_state = AsyncMock()
            # Quiet cycle (no actions, dialogue='...') triggers drive relief
            mock_db.get_drives_state = AsyncMock(return_value=DrivesState())
            mock_db.save_drives_state = AsyncMock()

            from models.pipeline import BodyOutput
            body_output = BodyOutput()
            from pipeline.output import process_output
            await process_output(body_output, validated, visitor_id='v1')

            # update_engagement_state should NOT have been called with status='engaged'
            for call in mock_db.update_engagement_state.call_args_list:
                if call.kwargs.get('status') == 'engaged' or \
                   (call.args and len(call.args) > 0 and call.args[0] == 'engaged'):
                    pytest.fail("Engagement should not be set when dialogue is '...'")


# ── Integration: sensorium + thalamus pipeline ──

class TestEngagementChoiceIntegration:
    """End-to-end: visitor connects → salience → routing decision."""

    def test_idle_visitor_connects_she_engages(self):
        """Idle, moderate social hunger → high enough salience → engage."""
        drives = DrivesState(
            social_hunger=0.6,
            expression_need=0.2,
            energy=0.7,
        )
        salience = calculate_connect_salience(drives, 'returner')
        # returner + moderate hunger should exceed 0.5 threshold
        assert salience >= 0.5, f"Expected salience >= 0.5, got {salience}"

    def test_absorbed_stranger_connects_she_continues(self):
        """Absorbed in writing, low social hunger, stranger → low salience → idle."""
        drives = DrivesState(
            social_hunger=0.2,
            expression_need=0.8,
            energy=0.6,
        )
        salience = calculate_connect_salience(drives, 'stranger')
        # stranger + absorbed + low social hunger should be below 0.5
        assert salience < 0.5, f"Expected salience < 0.5, got {salience}"

    def test_familiar_face_always_high_salience(self):
        """Familiar visitor always gets high salience even with neutral drives."""
        drives = DrivesState(
            social_hunger=0.5,
            expression_need=0.5,
            energy=0.5,
        )
        salience = calculate_connect_salience(drives, 'familiar')
        assert salience >= 0.5, f"Expected salience >= 0.5 for familiar, got {salience}"


# ── TASK-014: Visitor target parsing ──

class TestVisitorTargetParsing:
    """_is_visitor_target correctly parses target strings."""

    def test_specific_visitor(self):
        is_v, vid = _is_visitor_target('visitor:v1')
        assert is_v is True
        assert vid == 'v1'

    def test_generic_visitor(self):
        is_v, vid = _is_visitor_target('visitor')
        assert is_v is True
        assert vid is None

    def test_non_visitor_shelf(self):
        is_v, vid = _is_visitor_target('shelf')
        assert is_v is False
        assert vid is None

    def test_none_target(self):
        is_v, vid = _is_visitor_target(None)
        assert is_v is False
        assert vid is None

    def test_self_target(self):
        is_v, vid = _is_visitor_target('self')
        assert is_v is False
        assert vid is None

    def test_visitor_with_long_id(self):
        is_v, vid = _is_visitor_target('visitor:abc-123-def')
        assert is_v is True
        assert vid == 'abc-123-def'


# ── TASK-014: Visitor-directed priority modulation ──

class TestVisitorDirectedPriority:
    """Basal ganglia priority modulated by trust, interest, and drives."""

    def test_familiar_over_stranger_with_social_hunger(self):
        """Familiar visitor gets higher priority than stranger, same impulse."""
        drives = DrivesState(social_hunger=0.7, energy=0.8)
        context = {
            'visitor_trust': {'v1': 'familiar', 'v2': 'stranger'},
            'visitor_features': {},
        }

        i_familiar = Intention(action='speak', target='visitor:v1', impulse=0.6)
        i_stranger = Intention(action='speak', target='visitor:v2', impulse=0.6)

        p_familiar = _calculate_priority(i_familiar, drives, context)
        p_stranger = _calculate_priority(i_stranger, drives, context)

        assert p_familiar > p_stranger, (
            f"Familiar ({p_familiar}) should outprioritize stranger ({p_stranger})"
        )

    def test_interesting_stranger_beats_boring_returner(self):
        """Stranger asking a question with high impulse beats returner with low impulse."""
        drives = DrivesState(social_hunger=0.5, curiosity=0.7, energy=0.8)
        context = {
            'visitor_trust': {'v1': 'returner', 'v2': 'stranger'},
            'visitor_features': {
                'v2': {'contains_question': True},
            },
        }

        # Returner says something boring (low impulse)
        i_returner = Intention(action='speak', target='visitor:v1', impulse=0.3)
        # Stranger asks an interesting question (high impulse)
        i_stranger = Intention(action='speak', target='visitor:v2', impulse=0.7)

        p_returner = _calculate_priority(i_returner, drives, context)
        p_stranger = _calculate_priority(i_stranger, drives, context)

        assert p_stranger > p_returner, (
            f"Interesting stranger ({p_stranger}) should beat boring returner ({p_returner})"
        )

    def test_disengage_when_expression_need_high(self):
        """High expression_need + low impulse conversation = dampened speak priority."""
        drives = DrivesState(
            social_hunger=0.3, expression_need=0.8, energy=0.8,
        )
        context = {
            'visitor_trust': {'v1': 'stranger'},
            'visitor_features': {},
        }

        # Low impulse speak (boring conversation)
        i_speak = Intention(action='speak', target='visitor:v1', impulse=0.3)
        # Journal writing intention
        i_journal = Intention(action='write_journal', target='journal', impulse=0.6)

        p_speak = _calculate_priority(i_speak, drives, context)
        p_journal = _calculate_priority(i_journal, drives, context)

        assert p_journal > p_speak, (
            f"Journal ({p_journal}) should beat dampened speak ({p_speak})"
        )

    def test_social_hunger_boosts_visitor_actions(self):
        """High social hunger significantly boosts visitor-directed priority."""
        drives_hungry = DrivesState(social_hunger=0.9, energy=0.8)
        drives_sated = DrivesState(social_hunger=0.1, energy=0.8)

        intention = Intention(action='speak', target='visitor:v1', impulse=0.5)

        p_hungry = _calculate_priority(intention, drives_hungry)
        p_sated = _calculate_priority(intention, drives_sated)

        assert p_hungry > p_sated, (
            f"Hungry ({p_hungry}) should exceed sated ({p_sated})"
        )

    def test_generic_visitor_target_still_boosted(self):
        """Plain 'visitor' target (no ID) still gets social hunger boost."""
        drives = DrivesState(social_hunger=0.8, energy=0.8)
        intention = Intention(action='speak', target='visitor', impulse=0.5)

        p = _calculate_priority(intention, drives)

        # Should include social hunger boost: 0.5 + 0.8*0.3 = 0.74
        assert p > 0.7, f"Expected > 0.7 with social hunger boost, got {p}"


# ── TASK-014: Visitor silence routing ──

class TestVisitorSilenceRouting:
    """visitor_silence salience-gated: boring silence → idle, invested → engage."""

    @pytest.mark.asyncio
    async def test_low_salience_silence_routes_idle(self):
        """Low salience visitor_silence → idle (boring conversation, she drifts)."""
        perceptions = [
            Perception(
                p_type='visitor_silence',
                source='visitor:v1',
                ts=datetime.now(timezone.utc),
                content='Silence.',
                features={},
                salience=0.2,
            ),
        ]
        drives = DrivesState()
        engagement = EngagementState(status='engaged', visitor_id='v1')

        with patch('pipeline.thalamus.db') as mock_db:
            mock_db.get_flashbulb_count_today = AsyncMock(return_value=0)
            routing = await route(perceptions, drives, engagement)

        assert routing.cycle_type == 'idle'

    @pytest.mark.asyncio
    async def test_high_salience_silence_routes_engage(self):
        """High salience visitor_silence → engage (invested in conversation)."""
        perceptions = [
            Perception(
                p_type='visitor_silence',
                source='visitor:v1',
                ts=datetime.now(timezone.utc),
                content='Silence.',
                features={},
                salience=0.6,
            ),
        ]
        drives = DrivesState()
        engagement = EngagementState(status='engaged', visitor_id='v1')

        with patch('pipeline.thalamus.db') as mock_db:
            mock_db.get_flashbulb_count_today = AsyncMock(return_value=0)
            routing = await route(perceptions, drives, engagement)

        assert routing.cycle_type == 'engage'

    @pytest.mark.asyncio
    async def test_borderline_silence_routes_engage(self):
        """Salience at threshold (0.4) → engage."""
        perceptions = [
            Perception(
                p_type='visitor_silence',
                source='visitor:v1',
                ts=datetime.now(timezone.utc),
                content='Silence.',
                features={},
                salience=0.4,
            ),
        ]
        drives = DrivesState()
        engagement = EngagementState(status='engaged', visitor_id='v1')

        with patch('pipeline.thalamus.db') as mock_db:
            mock_db.get_flashbulb_count_today = AsyncMock(return_value=0)
            routing = await route(perceptions, drives, engagement)

        assert routing.cycle_type == 'engage'


# ── TASK-014: Multi-visitor basal ganglia selection ──

class TestMultiVisitorSelection:
    """When multiple speak intentions target different visitors, priority sorts them."""

    @pytest.mark.asyncio
    async def test_highest_priority_visitor_wins(self):
        """With two speak intentions, highest priority gets approved first."""
        from pipeline.basal_ganglia import select_actions

        validated = ValidatedOutput(
            intentions=[
                Intention(action='speak', target='visitor:v1', content='Hi', impulse=0.6),
                Intention(action='speak', target='visitor:v2', content='Hello', impulse=0.8),
            ],
            approved_actions=[
                ActionRequest(type='speak', detail={'text': 'Hi', 'target': 'visitor:v1'}),
                ActionRequest(type='speak', detail={'text': 'Hello', 'target': 'visitor:v2'}),
            ],
        )
        drives = DrivesState(social_hunger=0.5, energy=0.8)
        context = {
            'visitor_present': True,
            'visitor_trust': {'v1': 'stranger', 'v2': 'familiar'},
            'visitor_features': {},
        }

        with patch('pipeline.basal_ganglia.db') as mock_db:
            mock_db.get_inhibitions_for_action = AsyncMock(return_value=[])
            plan = await select_actions(validated, drives, context)

        # Both approved but only one speak per cycle (max_per_cycle=1)
        approved_speaks = [a for a in plan.actions if a.action == 'speak']
        assert len(approved_speaks) == 1
        # v2 (familiar, higher impulse) should win
        assert approved_speaks[0].target == 'visitor:v2'
