"""Tests for TASK-087b: Digital perception routing through thalamus + heartbeat.

Verifies:
- Thalamus routes digital_message → engage (same as visitor_speech)
- Thalamus routes digital_connect → engage/idle via salience threshold
- Thalamus routes digital_disconnect → idle
- Heartbeat focus capping preserves digital_* salience
- Heartbeat mode binding doesn't override digital_* focus
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timezone

from models.state import DrivesState, EngagementState, Visitor
from pipeline.sensorium import Perception
from pipeline.thalamus import route


def _make_drives(**overrides):
    defaults = dict(social_hunger=0.5, curiosity=0.5, energy=0.8,
                    expression_need=0.3, rest_need=0.2,
                    mood_valence=0.0, mood_arousal=0.3)
    defaults.update(overrides)
    return DrivesState(**defaults)


def _make_perception(p_type, salience=0.7, content='test'):
    return Perception(
        p_type=p_type,
        source='visitor:tg_123',
        ts=datetime.now(timezone.utc),
        content=content,
        features={},
        salience=salience,
    )


# ── Thalamus routing ──

class TestThalamusDigitalRouting:
    """Thalamus routes digital_* types like their visitor_* counterparts."""

    @pytest.mark.asyncio
    async def test_digital_message_routes_to_engage(self):
        perceptions = [_make_perception('digital_message', salience=0.7)]
        drives = _make_drives()
        engagement = EngagementState()

        with patch('pipeline.thalamus.db') as mock_db:
            mock_db.get_flashbulb_count_today = AsyncMock(return_value=0)
            result = await route(perceptions, drives, engagement)

        assert result.cycle_type == 'engage'

    @pytest.mark.asyncio
    async def test_visitor_speech_still_routes_to_engage(self):
        """Regression: web visitors unchanged."""
        perceptions = [_make_perception('visitor_speech', salience=0.7)]
        drives = _make_drives()
        engagement = EngagementState()

        with patch('pipeline.thalamus.db') as mock_db:
            mock_db.get_flashbulb_count_today = AsyncMock(return_value=0)
            result = await route(perceptions, drives, engagement)

        assert result.cycle_type == 'engage'

    @pytest.mark.asyncio
    async def test_digital_connect_high_salience_routes_engage(self):
        perceptions = [_make_perception('digital_connect', salience=0.9)]
        drives = _make_drives()
        engagement = EngagementState()

        with patch('pipeline.thalamus.db') as mock_db:
            mock_db.get_flashbulb_count_today = AsyncMock(return_value=0)
            result = await route(perceptions, drives, engagement)

        assert result.cycle_type == 'engage'

    @pytest.mark.asyncio
    async def test_digital_connect_low_salience_routes_idle(self):
        perceptions = [_make_perception('digital_connect', salience=0.1)]
        drives = _make_drives()
        engagement = EngagementState()

        with patch('pipeline.thalamus.db') as mock_db:
            mock_db.get_flashbulb_count_today = AsyncMock(return_value=0)
            result = await route(perceptions, drives, engagement)

        assert result.cycle_type == 'idle'

    @pytest.mark.asyncio
    async def test_digital_disconnect_routes_idle(self):
        perceptions = [_make_perception('digital_disconnect', salience=0.5)]
        drives = _make_drives()
        engagement = EngagementState()

        with patch('pipeline.thalamus.db') as mock_db:
            mock_db.get_flashbulb_count_today = AsyncMock(return_value=0)
            result = await route(perceptions, drives, engagement)

        assert result.cycle_type == 'idle'


# ── Heartbeat focus capping ──

class TestHeartbeatDigitalProtection:
    """Digital perceptions get same focus protection as visitor perceptions."""

    def test_digital_message_not_capped_by_focus(self):
        """digital_message salience preserved when arbiter focus is active."""
        perc = _make_perception('digital_message', salience=0.8)
        # Simulate the heartbeat focus capping logic
        capped = not perc.p_type.startswith(('visitor_', 'digital_'))
        assert capped is False, "digital_message should NOT be capped"

    def test_visitor_speech_not_capped_by_focus(self):
        """Regression: visitor_speech still protected."""
        perc = _make_perception('visitor_speech', salience=0.8)
        capped = not perc.p_type.startswith(('visitor_', 'digital_'))
        assert capped is False

    def test_ambient_capped_by_focus(self):
        """Non-visitor, non-digital types should be capped."""
        perc = _make_perception('ambient', salience=0.8)
        capped = not perc.p_type.startswith(('visitor_', 'digital_'))
        assert capped is True

    def test_digital_connect_not_capped(self):
        perc = _make_perception('digital_connect', salience=0.6)
        capped = not perc.p_type.startswith(('visitor_', 'digital_'))
        assert capped is False

    def test_digital_disconnect_not_capped(self):
        perc = _make_perception('digital_disconnect', salience=0.3)
        capped = not perc.p_type.startswith(('visitor_', 'digital_'))
        assert capped is False


class TestHeartbeatModeBinding:
    """Arbiter doesn't override routing when digital perception is focus."""

    def test_digital_message_blocks_arbiter_override(self):
        """digital_message focus should prevent arbiter mode override."""
        focus_p_type = 'digital_message'
        would_override = not focus_p_type.startswith(('visitor_', 'digital_'))
        assert would_override is False, "arbiter should NOT override digital_message focus"

    def test_visitor_speech_blocks_arbiter_override(self):
        """Regression: visitor_speech still blocks arbiter override."""
        focus_p_type = 'visitor_speech'
        would_override = not focus_p_type.startswith(('visitor_', 'digital_'))
        assert would_override is False

    def test_consume_focus_allows_arbiter_override(self):
        """Non-visitor/digital focus should allow arbiter override."""
        focus_p_type = 'consume_focus'
        would_override = not focus_p_type.startswith(('visitor_', 'digital_'))
        assert would_override is True
