"""Tests for TASK-087: Channel-aware perception.

Verifies:
- _detect_channel() returns platform name for tg_/x_ prefixes, None for web
- visitor_speech from Telegram → digital_message perception
- visitor_speech from X → digital_message perception
- visitor_speech from web → visitor_speech perception (unchanged)
- visitor_connect from Telegram → digital_connect perception
- visitor_connect from web → visitor_connect perception (unchanged)
- visitor_disconnect from Telegram → digital_disconnect perception
- visitor_disconnect from web → visitor_disconnect perception (unchanged)
"""

import pytest
from unittest.mock import AsyncMock, patch
from datetime import datetime, timezone

from models.state import DrivesState, Visitor
from models.event import Event
from pipeline.sensorium import (
    _detect_channel,
    build_perceptions,
    Perception,
)


# ── _detect_channel unit tests ──

class TestDetectChannel:
    def test_telegram_prefix(self):
        assert _detect_channel('tg_12345') == 'Telegram'

    def test_x_prefix(self):
        assert _detect_channel('x_67890') == 'X'

    def test_web_visitor_no_prefix(self):
        assert _detect_channel('v1') is None

    def test_websocket_visitor(self):
        assert _detect_channel('abc123') is None

    def test_empty_string(self):
        assert _detect_channel('') is None

    def test_prefix_only(self):
        assert _detect_channel('tg_') == 'Telegram'

    def test_x_in_middle_not_detected(self):
        """Only prefix matters, not substring."""
        assert _detect_channel('fox_123') is None


# ── Perception type tests ──

def _make_drives():
    return DrivesState(social_hunger=0.5, curiosity=0.5, energy=0.8)


def _make_visitor(vid, name=None, trust='stranger'):
    return Visitor(id=vid, name=name, trust_level=trust, visit_count=1)


def _mock_db(visitor=None):
    """Return a patch context for pipeline.sensorium.db."""
    mock = AsyncMock()
    mock.get_visitor = AsyncMock(return_value=visitor)
    return patch('pipeline.sensorium.db', mock)


class TestVisitorSpeechChannel:
    """visitor_speech events produce different p_types by channel."""

    @pytest.mark.asyncio
    async def test_web_visitor_speech_unchanged(self):
        event = Event(
            event_type='visitor_speech',
            source='visitor:v1',
            payload={'text': 'Hello'},
        )
        visitor = _make_visitor('v1', name='Alice')
        with _mock_db(visitor):
            perceptions = await build_perceptions([event], _make_drives())

        speech = [p for p in perceptions if p.p_type == 'visitor_speech']
        assert len(speech) == 1
        assert speech[0].content == 'Hello'
        assert 'is_digital' not in speech[0].features

    @pytest.mark.asyncio
    async def test_telegram_speech_becomes_digital_message(self):
        event = Event(
            event_type='visitor_speech',
            source='visitor:tg_999',
            payload={'text': 'Hey there'},
        )
        visitor = _make_visitor('tg_999', name='Bob')
        with _mock_db(visitor):
            perceptions = await build_perceptions([event], _make_drives())

        digital = [p for p in perceptions if p.p_type == 'digital_message']
        assert len(digital) == 1
        assert 'Telegram' in digital[0].content
        assert 'Bob' in digital[0].content
        assert 'Hey there' in digital[0].content
        assert digital[0].features['channel'] == 'Telegram'
        assert digital[0].features['is_digital'] is True

    @pytest.mark.asyncio
    async def test_x_speech_becomes_digital_message(self):
        event = Event(
            event_type='visitor_speech',
            source='visitor:x_555',
            payload={'text': 'Nice shop'},
        )
        visitor = _make_visitor('x_555', name='@jazz_fan')
        with _mock_db(visitor):
            perceptions = await build_perceptions([event], _make_drives())

        digital = [p for p in perceptions if p.p_type == 'digital_message']
        assert len(digital) == 1
        assert 'X' in digital[0].content
        assert '@jazz_fan' in digital[0].content
        assert digital[0].features['channel'] == 'X'

    @pytest.mark.asyncio
    async def test_telegram_speech_no_name_uses_id(self):
        """If visitor has no name, fall back to visitor_id."""
        event = Event(
            event_type='visitor_speech',
            source='visitor:tg_111',
            payload={'text': 'Hi'},
        )
        visitor = _make_visitor('tg_111', name=None)
        with _mock_db(visitor):
            perceptions = await build_perceptions([event], _make_drives())

        digital = [p for p in perceptions if p.p_type == 'digital_message']
        assert len(digital) == 1
        assert 'tg_111' in digital[0].content


class TestVisitorConnectChannel:
    """visitor_connect events produce different p_types by channel."""

    @pytest.mark.asyncio
    async def test_web_connect_unchanged(self):
        event = Event(
            event_type='visitor_connect',
            source='visitor:v1',
            payload={},
        )
        visitor = _make_visitor('v1', name='Alice', trust='stranger')
        with _mock_db(visitor):
            perceptions = await build_perceptions([event], _make_drives())

        connects = [p for p in perceptions if p.p_type == 'visitor_connect']
        assert len(connects) == 1
        assert 'enters the shop' in connects[0].content

    @pytest.mark.asyncio
    async def test_telegram_connect_becomes_digital_connect(self):
        event = Event(
            event_type='visitor_connect',
            source='visitor:tg_222',
            payload={},
        )
        visitor = _make_visitor('tg_222', name='Carol', trust='regular')
        with _mock_db(visitor):
            perceptions = await build_perceptions([event], _make_drives())

        connects = [p for p in perceptions if p.p_type == 'digital_connect']
        assert len(connects) == 1
        assert 'Telegram' in connects[0].content
        assert 'Carol' in connects[0].content
        assert connects[0].features['is_digital'] is True

    @pytest.mark.asyncio
    async def test_x_connect_becomes_digital_connect(self):
        event = Event(
            event_type='visitor_connect',
            source='visitor:x_333',
            payload={},
        )
        visitor = _make_visitor('x_333', name='@dave')
        with _mock_db(visitor):
            perceptions = await build_perceptions([event], _make_drives())

        connects = [p for p in perceptions if p.p_type == 'digital_connect']
        assert len(connects) == 1
        assert 'X' in connects[0].content


class TestVisitorDisconnectChannel:
    """visitor_disconnect events produce different p_types by channel."""

    @pytest.mark.asyncio
    async def test_web_disconnect_unchanged(self):
        event = Event(
            event_type='visitor_disconnect',
            source='visitor:v1',
            payload={},
        )
        visitor = _make_visitor('v1', name='Alice')
        with _mock_db(visitor):
            perceptions = await build_perceptions([event], _make_drives())

        disconnects = [p for p in perceptions if p.p_type == 'visitor_disconnect']
        assert len(disconnects) == 1
        assert 'left' in disconnects[0].content

    @pytest.mark.asyncio
    async def test_telegram_disconnect_becomes_digital_disconnect(self):
        event = Event(
            event_type='visitor_disconnect',
            source='visitor:tg_444',
            payload={},
        )
        visitor = _make_visitor('tg_444', name='Eve')
        with _mock_db(visitor):
            perceptions = await build_perceptions([event], _make_drives())

        disconnects = [p for p in perceptions if p.p_type == 'digital_disconnect']
        assert len(disconnects) == 1
        assert 'quiet' in disconnects[0].content
        assert 'Telegram' in disconnects[0].content
        assert disconnects[0].features['is_digital'] is True
        # Digital disconnect has lower salience than physical departure
        assert disconnects[0].salience == 0.2

    @pytest.mark.asyncio
    async def test_web_disconnect_higher_salience_than_digital(self):
        """Physical departures are more salient than digital ones going quiet."""
        web_event = Event(
            event_type='visitor_disconnect',
            source='visitor:v1',
            payload={},
        )
        tg_event = Event(
            event_type='visitor_disconnect',
            source='visitor:tg_444',
            payload={},
        )
        visitor = _make_visitor('v1', name='Alice')
        tg_visitor = _make_visitor('tg_444', name='Bob')

        with patch('pipeline.sensorium.db') as mock_db:
            mock_db.get_visitor = AsyncMock(side_effect=lambda vid: visitor if vid == 'v1' else tg_visitor)
            web_perceptions = await build_perceptions([web_event], _make_drives())
            tg_perceptions = await build_perceptions([tg_event], _make_drives())

        web_disc = [p for p in web_perceptions if p.p_type == 'visitor_disconnect'][0]
        tg_disc = [p for p in tg_perceptions if p.p_type == 'digital_disconnect'][0]
        assert web_disc.salience > tg_disc.salience
