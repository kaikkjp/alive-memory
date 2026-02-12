"""Cycle Arbiter — deterministic per-cycle planner. No LLM.

Runs at the top of every non-visitor autonomous cycle.
Decides what the cycle is *for* before perceptions are built.
Focus channels map to existing pipeline modes — no new modes.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional

from db import JST
from models.state import DrivesState


@dataclass
class ArbiterFocus:
    """What this cycle should focus on."""
    channel: str           # consume | thread | news | express | rest | idle
    pipeline_mode: str     # engage | express | idle | rest (existing modes only)
    payload: Optional[dict] = None
    token_budget_hint: Optional[int] = None


# Focus channels map to existing pipeline modes.
# No new pipeline modes are introduced.
CHANNEL_TO_MODE = {
    'consume': 'engage',    # she's engaging with content
    'thread':  'express',   # thread work is self-expression
    'news':    'idle',      # noticed, not deeply engaged
    'express': 'express',   # existing creative expression
    'rest':    'rest',      # existing rest behavior
    'idle':    'idle',      # existing ambient behavior
}

# Hard caps per JST day
DAILY_CAPS = {
    'consume': 3,
    'news': 10,
    'thread': 8,
    'express': 6,
}

# Per-channel cooldowns in seconds
CHANNEL_COOLDOWNS = {
    'consume': 7200,   # 2 hours
    'news': 1800,      # 30 min
    'thread': 2700,    # 45 min
    'express': 7200,   # 2 hours
}

# Novelty penalty: keyword overlap threshold
NOVELTY_OVERLAP_THRESHOLD = 0.6
MAX_RECENT_KEYWORDS = 20


def _cooldown_elapsed(last_ts: Optional[datetime], cooldown_seconds: int,
                      mood_arousal: float = 0.0) -> bool:
    """Check if cooldown has elapsed since last timestamp."""
    if last_ts is None:
        return True
    elapsed = (datetime.now(timezone.utc) - last_ts).total_seconds()
    # High arousal shortens thread cooldown
    if mood_arousal > 0.7:
        cooldown_seconds = int(cooldown_seconds * 0.6)
    return elapsed >= cooldown_seconds


def _check_daily_budget(state: dict, channel: str) -> bool:
    """Check if daily budget allows another cycle of this channel type."""
    count_key = {
        'consume': 'consume_count_today',
        'news': 'news_engage_count_today',
        'thread': 'thread_focus_count_today',
        'express': 'express_count_today',
    }.get(channel)
    if not count_key:
        return True
    return state.get(count_key, 0) < DAILY_CAPS.get(channel, 999)


def _reset_if_new_day(state: dict) -> dict:
    """Reset daily counters if JST date has changed."""
    today = datetime.now(JST).date().isoformat()
    if state.get('current_date_jst') != today:
        state['consume_count_today'] = 0
        state['news_engage_count_today'] = 0
        state['thread_focus_count_today'] = 0
        state['express_count_today'] = 0
        state['current_date_jst'] = today
    return state


def _extract_keywords(text: str) -> set[str]:
    """Extract simple keywords from text for novelty checking."""
    if not text:
        return set()
    words = text.lower().split()
    # Only keep words > 3 chars (skip articles, prepositions)
    return {w.strip('.,!?;:"\'-()[]') for w in words if len(w) > 3}


def _novelty_penalty(payload: Optional[dict], recent_keywords: list[str]) -> float:
    """Reduce priority if topic overlaps heavily with recent focuses."""
    if not payload or not recent_keywords:
        return 0.0

    # Build keyword set from payload
    text_parts = [
        payload.get('title', ''),
        payload.get('content', ''),
        payload.get('headline', ''),
    ]
    new_keywords = set()
    for part in text_parts:
        new_keywords |= _extract_keywords(part)

    if not new_keywords:
        return 0.0

    recent_set = set(recent_keywords)
    overlap = len(new_keywords & recent_set)
    overlap_ratio = overlap / len(new_keywords) if new_keywords else 0.0

    if overlap_ratio > NOVELTY_OVERLAP_THRESHOLD:
        return 0.3  # penalty
    return 0.0


async def decide_cycle_focus(drives: DrivesState, arbiter_state: dict) -> ArbiterFocus:
    """Deterministic cycle focus decision. No LLM.

    Priority order (spec Section 1):
    1. Rest guard (rest_need > 0.8 OR energy < 0.2)
    2. Active thread with deadline today (Phase 2 — stub for now)
    3. Unread high-salience news (Phase 5 — stub for now)
    4. Reading urge (Phase 4 — stub for now)
    5. Active thread LRU (Phase 2 — stub for now)
    6. Unread news (Phase 5 — stub for now)
    7. Creative pressure
    8. Default: ambient idle
    """

    # Reset daily caps if new JST day
    _reset_if_new_day(arbiter_state)

    # ── Priority 1: Rest guard ──
    if drives.rest_need > 0.8 or drives.energy < 0.2:
        return ArbiterFocus(channel='rest', pipeline_mode='rest')

    # ── Priority 2: Active thread with deadline today ──
    # (Stub — Phase 2 will add thread queries)

    # ── Priority 3: Unread high-salience news ──
    # (Stub — Phase 5 will add news queries)

    # ── Priority 4: Reading urge ──
    # (Stub — Phase 4 will add consume selection)

    # ── Priority 5: Active thread (LRU, cooldown elapsed) ──
    # (Stub — Phase 2 will add thread queries)

    # ── Priority 6: Unread news (lower salience) ──
    # (Stub — Phase 5 will add news queries)

    # ── Priority 7: Creative pressure ──
    if (_check_daily_budget(arbiter_state, 'express')
            and _cooldown_elapsed(arbiter_state.get('last_express_ts'),
                                  CHANNEL_COOLDOWNS['express'],
                                  drives.mood_arousal)
            and (drives.expression_need > 0.6)):
        return ArbiterFocus(channel='express', pipeline_mode='express')

    # ── Priority 8: Default — ambient idle ──
    return ArbiterFocus(channel='idle', pipeline_mode='idle')


def update_arbiter_after_cycle(arbiter_state: dict, focus: ArbiterFocus):
    """Update arbiter counters after a focused cycle completes.

    Call this in heartbeat.py after run_cycle for non-idle/non-rest channels.
    """
    now = datetime.now(timezone.utc)

    if focus.channel == 'consume':
        arbiter_state['consume_count_today'] = arbiter_state.get('consume_count_today', 0) + 1
        arbiter_state['last_consume_ts'] = now
    elif focus.channel == 'thread':
        arbiter_state['thread_focus_count_today'] = arbiter_state.get('thread_focus_count_today', 0) + 1
        arbiter_state['last_thread_focus_ts'] = now
    elif focus.channel == 'news':
        arbiter_state['news_engage_count_today'] = arbiter_state.get('news_engage_count_today', 0) + 1
        arbiter_state['last_news_engage_ts'] = now
    elif focus.channel == 'express':
        arbiter_state['express_count_today'] = arbiter_state.get('express_count_today', 0) + 1
        arbiter_state['last_express_ts'] = now

    # Update novelty keywords from payload
    if focus.payload:
        text_parts = [
            focus.payload.get('title', ''),
            focus.payload.get('content', ''),
            focus.payload.get('headline', ''),
        ]
        new_keywords = set()
        for part in text_parts:
            new_keywords |= _extract_keywords(part)
        existing = arbiter_state.get('recent_focus_keywords', [])
        updated = list(new_keywords) + existing
        arbiter_state['recent_focus_keywords'] = updated[:MAX_RECENT_KEYWORDS]
