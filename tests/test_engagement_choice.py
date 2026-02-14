"""Tests for TASK-012: visitor_connect as perception, not state change.

Verifies:
- Sensorium: visitor_connect salience factors in trust, social hunger, absorption
- Thalamus: visitor_connect competes instead of auto-winning engage routing
- Executor: engagement state set on speak, not on connect
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch
from datetime import datetime, timezone

from models.state import DrivesState, EngagementState, Visitor
from models.event import Event
from models.pipeline import ValidatedOutput, ActionRequest, MemoryUpdate
from pipeline.sensorium import calculate_connect_salience, Perception
from pipeline.thalamus import route


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
            dialogue_language='en',
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
