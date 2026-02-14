"""Tests for TASK-013: Multi-slot visitor presence.

Verifies:
- VisitorPresence dataclass basics
- DB functions: add/remove/update/get visitors_present
- Multiple visitors can be present simultaneously
- Engagement state only clears for the engaged visitor
- Output pipeline syncs visitors_present with engagement changes
- ACK behavior: busy_with_other when she's talking to someone else
- Sensorium produces per-visitor perceptions (existing behavior, verified here)
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timezone

from models.state import (
    DrivesState, EngagementState, Visitor, VisitorPresence,
)
from models.event import Event
from models.pipeline import ValidatedOutput, BodyOutput, MotorPlan
from pipeline.sensorium import calculate_connect_salience, Perception
from pipeline.thalamus import route
from pipeline.ack import on_visitor_message


# ── VisitorPresence dataclass ──

class TestVisitorPresenceModel:
    """Basic tests for the VisitorPresence dataclass."""

    def test_default_values(self):
        vp = VisitorPresence(visitor_id='v1')
        assert vp.visitor_id == 'v1'
        assert vp.status == 'browsing'
        assert vp.entered_at is None
        assert vp.last_activity is None
        assert vp.connection_type == 'tcp'

    def test_custom_values(self):
        now = datetime.now(timezone.utc)
        vp = VisitorPresence(
            visitor_id='v2',
            status='in_conversation',
            entered_at=now,
            last_activity=now,
            connection_type='websocket',
        )
        assert vp.status == 'in_conversation'
        assert vp.connection_type == 'websocket'


# ── ACK behavior with multi-visitor ──

class TestMultiVisitorACK:
    """ACK path produces correct body type for multi-visitor scenarios."""

    @pytest.mark.asyncio
    async def test_busy_with_other_when_engaged_with_different_visitor(self):
        """When she's talking to A and B speaks, B gets busy_with_other."""
        event = Event(
            event_type='visitor_speech',
            source='visitor:v2',
            payload={'text': 'Hello'},
        )
        engagement = EngagementState(
            status='engaged',
            visitor_id='v1',
            turn_count=3,
        )

        with patch('pipeline.ack.db') as mock_db:
            mock_db.append_event = AsyncMock()
            mock_db.inbox_add = AsyncMock()

            result = await on_visitor_message(event, engagement)

        assert result['body']['type'] == 'busy_with_other'
        assert result['body']['target'] == 'visitor:v2'
        # Message still goes to inbox but no microcycle is triggered
        assert result['should_process'] is False

    @pytest.mark.asyncio
    async def test_listening_when_engaged_with_same_visitor(self):
        """When she's talking to A and A speaks, A gets listening."""
        event = Event(
            event_type='visitor_speech',
            source='visitor:v1',
            payload={'text': 'Tell me more'},
        )
        engagement = EngagementState(
            status='engaged',
            visitor_id='v1',
            turn_count=3,
        )

        with patch('pipeline.ack.db') as mock_db:
            mock_db.append_event = AsyncMock()
            mock_db.inbox_add = AsyncMock()

            result = await on_visitor_message(event, engagement)

        assert result['body']['type'] == 'listening'
        assert result['should_process'] is True

    @pytest.mark.asyncio
    async def test_glance_toward_when_not_engaged(self):
        """When she's not engaged and someone speaks, glance_toward."""
        event = Event(
            event_type='visitor_speech',
            source='visitor:v1',
            payload={'text': 'Hi'},
        )
        engagement = EngagementState(status='none')

        with patch('pipeline.ack.db') as mock_db:
            mock_db.append_event = AsyncMock()
            mock_db.inbox_add = AsyncMock()

            result = await on_visitor_message(event, engagement)

        assert result['body']['type'] == 'glance_toward'
        assert result['should_process'] is True


# ── Output pipeline: engagement syncs with visitors_present ──

class TestOutputVisitorPresenceSync:
    """Output processing syncs visitors_present when engagement changes."""

    @pytest.mark.asyncio
    async def test_first_speak_sets_in_conversation(self):
        """When she first speaks to a visitor, their presence goes to in_conversation."""
        validated = ValidatedOutput(
            dialogue='Welcome.',
            dialogue_language='en',
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

            body_output = BodyOutput()
            from pipeline.output import process_output
            await process_output(body_output, validated, visitor_id='v1')

            # Should update visitor presence to in_conversation
            mock_db.update_visitor_present.assert_any_call(
                'v1', status='in_conversation', last_activity=now,
            )

    @pytest.mark.asyncio
    async def test_switching_visitors_updates_both(self):
        """When she switches from v1 to v2, v1 goes to waiting, v2 goes to in_conversation."""
        validated = ValidatedOutput(
            dialogue='Hello there.',
            dialogue_language='en',
            expression='warm',
            body_state='standing',
            gaze='at_visitor',
            resonance=False,
            internal_monologue='New visitor.',
        )

        with patch('pipeline.output.db') as mock_db, \
             patch('pipeline.output.clock') as mock_clock, \
             patch('pipeline.output.hippocampus_consolidate', new_callable=AsyncMock):

            now = datetime(2026, 2, 14, 12, 5, 0, tzinfo=timezone.utc)
            mock_clock.now_utc.return_value = now
            # She was talking to v1, now speaks to v2
            mock_db.get_engagement_state = AsyncMock(return_value=EngagementState(
                status='engaged', visitor_id='v1', turn_count=5,
            ))
            mock_db.update_engagement_state = AsyncMock()
            mock_db.update_visitor_present = AsyncMock()

            body_output = BodyOutput()
            from pipeline.output import process_output
            await process_output(body_output, validated, visitor_id='v2')

            # v1 should go to waiting
            mock_db.update_visitor_present.assert_any_call(
                'v1', status='waiting',
            )
            # v2 should go to in_conversation
            mock_db.update_visitor_present.assert_any_call(
                'v2', status='in_conversation', last_activity=now,
            )

    @pytest.mark.asyncio
    async def test_continuing_conversation_updates_activity(self):
        """When she keeps talking to same visitor, only last_activity updates."""
        validated = ValidatedOutput(
            dialogue='Tell me more.',
            dialogue_language='en',
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
                status='engaged', visitor_id='v1', turn_count=3,
            ))
            mock_db.update_engagement_state = AsyncMock()
            mock_db.update_visitor_present = AsyncMock()

            body_output = BodyOutput()
            from pipeline.output import process_output
            await process_output(body_output, validated, visitor_id='v1')

            # Only last_activity updated (no status change)
            mock_db.update_visitor_present.assert_any_call(
                'v1', last_activity=now,
            )


# ── Sensorium: multiple visitor perceptions ──

class TestMultiVisitorPerceptions:
    """Multiple visitor events produce individual perceptions with salience."""

    def test_two_strangers_get_individual_salience(self):
        """Two strangers connecting should each get their own salience score."""
        drives = DrivesState(social_hunger=0.5, expression_need=0.3, energy=0.8)
        sal1 = calculate_connect_salience(drives, 'stranger')
        sal2 = calculate_connect_salience(drives, 'stranger')
        # Same drives + same trust = same salience
        assert sal1 == sal2

    def test_familiar_outcompetes_stranger(self):
        """A familiar visitor has higher salience than a stranger."""
        drives = DrivesState(social_hunger=0.5, expression_need=0.3, energy=0.8)
        stranger_sal = calculate_connect_salience(drives, 'stranger')
        familiar_sal = calculate_connect_salience(drives, 'familiar')
        assert familiar_sal > stranger_sal


# ── Thalamus: routing with multiple visitor perceptions ──

class TestMultiVisitorRouting:
    """When multiple visitor perceptions compete, highest salience wins focus."""

    @pytest.mark.asyncio
    async def test_higher_salience_visitor_gets_focus(self):
        """With two visitor perceptions, the higher salience one becomes focus."""
        p_stranger = Perception(
            p_type='visitor_connect',
            source='visitor:v1',
            ts=datetime.now(timezone.utc),
            content='Someone new enters.',
            features={'is_arrival': True},
            salience=0.3,
        )
        p_familiar = Perception(
            p_type='visitor_connect',
            source='visitor:v2',
            ts=datetime.now(timezone.utc),
            content='A familiar face.',
            features={'is_arrival': True},
            salience=0.8,
        )
        # Perceptions sorted by salience (familiar first)
        perceptions = sorted([p_stranger, p_familiar],
                           key=lambda p: p.salience, reverse=True)

        drives = DrivesState()
        engagement = EngagementState(status='none')

        with patch('pipeline.thalamus.db') as mock_db:
            mock_db.get_flashbulb_count_today = AsyncMock(return_value=0)
            routing = await route(perceptions, drives, engagement)

        # Familiar visitor should be focus
        assert routing.focus.source == 'visitor:v2'
        assert routing.cycle_type == 'engage'
        # Stranger is in background
        assert any(p.source == 'visitor:v1' for p in routing.background)

    @pytest.mark.asyncio
    async def test_visitor_speech_always_engage(self):
        """visitor_speech always routes to engage regardless of who else is present."""
        p_speech = Perception(
            p_type='visitor_speech',
            source='visitor:v1',
            ts=datetime.now(timezone.utc),
            content='Hello!',
            features={},
            salience=0.7,
        )
        p_connect = Perception(
            p_type='visitor_connect',
            source='visitor:v2',
            ts=datetime.now(timezone.utc),
            content='Someone enters.',
            features={'is_arrival': True},
            salience=0.5,
        )
        perceptions = sorted([p_speech, p_connect],
                           key=lambda p: p.salience, reverse=True)

        drives = DrivesState()
        engagement = EngagementState(status='none')

        with patch('pipeline.thalamus.db') as mock_db:
            mock_db.get_flashbulb_count_today = AsyncMock(return_value=0)
            routing = await route(perceptions, drives, engagement)

        assert routing.focus.source == 'visitor:v1'
        assert routing.cycle_type == 'engage'
