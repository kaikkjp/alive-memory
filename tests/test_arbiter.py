"""Tests for pipeline/arbiter.py cap removal and pacing behavior."""

from unittest.mock import AsyncMock, patch

import pytest

import clock
from models.state import DrivesState
from pipeline.arbiter import ArbiterFocus, decide_cycle_focus, update_arbiter_after_cycle


def _base_state() -> dict:
    return {
        'consume_count_today': 0,
        'news_engage_count_today': 0,
        'thread_focus_count_today': 0,
        'express_count_today': 0,
        'last_consume_ts': None,
        'last_news_engage_ts': None,
        'last_thread_focus_ts': None,
        'last_express_ts': None,
        'recent_focus_keywords': [],
        'current_date_jst': clock.now().date().isoformat(),
    }


@pytest.mark.asyncio
async def test_no_daily_cap_enforcement():
    """Old cap counters do not block channel selection anymore."""
    state = _base_state()
    state['consume_count_today'] = 100
    state['news_engage_count_today'] = 100
    state['thread_focus_count_today'] = 100
    state['express_count_today'] = 100
    drives = DrivesState(expression_need=0.8, energy=0.8, mood_arousal=0.0)

    with patch('pipeline.arbiter.db.get_active_threads',
               new=AsyncMock(return_value=[])), \
            patch('pipeline.arbiter.db.get_unseen_news',
                  new=AsyncMock(return_value=[])):
        focus = await decide_cycle_focus(drives, state)

    assert focus.channel == 'express'


@pytest.mark.asyncio
async def test_cooldown_still_gates():
    """Cooldown pacing still blocks selection until elapsed."""
    state = _base_state()
    state['last_express_ts'] = clock.now_utc()
    drives = DrivesState(expression_need=0.8, energy=0.8, mood_arousal=0.0)

    with patch('pipeline.arbiter.db.get_active_threads',
               new=AsyncMock(return_value=[])), \
            patch('pipeline.arbiter.db.get_unseen_news',
                  new=AsyncMock(return_value=[])):
        focus = await decide_cycle_focus(drives, state)

    assert focus.channel == 'idle'


def test_daily_counters_still_increment():
    """Counters are still populated for observability/dashboard use."""
    state = _base_state()
    focus = ArbiterFocus(
        channel='thread',
        pipeline_mode='express',
        payload={'title': 'thread focus example'},
    )

    update_arbiter_after_cycle(state, focus)

    assert state['thread_focus_count_today'] == 1
    assert state['last_thread_focus_ts'] is not None

