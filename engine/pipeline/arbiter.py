"""Cycle Arbiter — deterministic per-cycle planner. No LLM.

Runs at the top of every non-visitor autonomous cycle.
Decides what the cycle is *for* before perceptions are built.
Focus channels map to existing pipeline modes — no new modes.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional

import clock
from db import JST
from models.state import DrivesState, idle_phase
import db


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
    'consume': 8,
    'news': 10,
    'thread': 8,
    'express': 6,
}

# Per-channel cooldowns in seconds
CHANNEL_COOLDOWNS = {
    'consume': 1200,   # 20 min
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
    elapsed = (clock.now_utc() - last_ts).total_seconds()
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
    today = clock.now().date().isoformat()
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
    """Check topic novelty against recent focuses.

    Returns 0.3 penalty when keyword overlap exceeds the threshold.

    Waterfall semantics: callers at higher-priority slots use this penalty to
    skip the candidate, which naturally falls through to a lower-priority slot.
    At the *lowest* slot for each channel type, the novelty gate is omitted so
    that deprioritized candidates still get selected rather than eliminated.

    Example: a repetitive thread is skipped at P2 (deadline) and falls to P5
    (LRU thread). P5 does not check novelty — the thread was already
    deprioritized by falling here. This implements the spec's "reduce by 0.3"
    intent within a priority waterfall architecture.
    """
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


async def decide_cycle_focus(drives: DrivesState, arbiter_state: dict,
                             idle_streak: int = 0) -> ArbiterFocus:
    """Deterministic cycle focus decision. No LLM.

    Priority order (spec Section 1):
    1. Rest guard (rest_need > 0.8 OR energy < 0.2)
    2. Active thread with deadline today (Phase 2 — stub for now)
    3. Unread high-salience news (Phase 5 — stub for now)
    4. Reading urge (Phase 4 — stub for now)
    5. Active thread LRU (Phase 2 — stub for now)
    6. Unread news (Phase 5 — stub for now)
    7. Creative pressure
    7b. Wander channel (TASK-100: idle arc WANDER phase)
    8. Default: ambient idle
    """

    # Reset daily caps if new JST day
    _reset_if_new_day(arbiter_state)

    # ── Priority 1: Rest guard ──
    if drives.energy < 0.2:
        return ArbiterFocus(channel='rest', pipeline_mode='rest')

    # ── Priority 2: Active thread with deadline today ──
    today_jst = clock.now().date().isoformat()
    if (_check_daily_budget(arbiter_state, 'thread')
            and _cooldown_elapsed(arbiter_state.get('last_thread_focus_ts'),
                                  CHANNEL_COOLDOWNS['thread'],
                                  drives.mood_arousal)):
        active_threads = await db.get_active_threads(limit=5)
        deadline_thread = next(
            (t for t in active_threads if t.target_date == today_jst), None
        )
        if deadline_thread:
            payload = {
                'thread_id': deadline_thread.id,
                'title': deadline_thread.title,
                'content': deadline_thread.content or '',
                'thread_type': deadline_thread.thread_type,
            }
            penalty = _novelty_penalty(payload,
                                       arbiter_state.get('recent_focus_keywords', []))
            if penalty < 0.3:  # not too repetitive
                return ArbiterFocus(
                    channel='thread',
                    pipeline_mode=CHANNEL_TO_MODE['thread'],
                    payload=payload,
                )

    # ── Priority 3: Unread high-salience news ──
    if (_check_daily_budget(arbiter_state, 'news')
            and _cooldown_elapsed(arbiter_state.get('last_news_engage_ts'),
                                  CHANNEL_COOLDOWNS['news'],
                                  drives.mood_arousal)):
        high_sal_news = await db.get_unseen_news(min_salience=0.5, limit=1)
        if high_sal_news:
            item = high_sal_news[0]
            payload = {
                'pool_id': item['id'],
                'title': item.get('title', ''),
                'headline': item.get('content', ''),
                'source_channel': item.get('source_channel', ''),
            }
            penalty = _novelty_penalty(payload,
                                       arbiter_state.get('recent_focus_keywords', []))
            if penalty < 0.3:
                return ArbiterFocus(
                    channel='news',
                    pipeline_mode=CHANNEL_TO_MODE['news'],
                    payload=payload,
                )

    # ── Priority 4: Reading urge — REMOVED (TASK-041) ──
    # Content consumption now happens through read_content action within any
    # cycle type, triggered by notifications in the sensorium. The arbiter
    # no longer schedules consume cycles.

    # ── Priority 5: Active thread (LRU, cooldown elapsed) ──
    if (_check_daily_budget(arbiter_state, 'thread')
            and _cooldown_elapsed(arbiter_state.get('last_thread_focus_ts'),
                                  CHANNEL_COOLDOWNS['thread'],
                                  drives.mood_arousal)):
        active_threads = await db.get_active_threads(limit=3)
        if active_threads:
            # Pick the least-recently-touched thread
            lru_thread = min(active_threads, key=lambda t: t.last_touched or t.created_at)
            payload = {
                'thread_id': lru_thread.id,
                'title': lru_thread.title,
                'content': lru_thread.content or '',
                'thread_type': lru_thread.thread_type,
            }
            # No novelty gate here — P5 is the last thread slot.
            # If the thread was repetitive it was already skipped at P2 (deadline).
            # Gating again here would eliminate it entirely, violating the spec's
            # "reduce priority" intent. See _novelty_penalty docstring.
            return ArbiterFocus(
                channel='thread',
                pipeline_mode=CHANNEL_TO_MODE['thread'],
                payload=payload,
            )

    # ── Priority 6: Unread news (lower salience) ──
    if (_check_daily_budget(arbiter_state, 'news')
            and _cooldown_elapsed(arbiter_state.get('last_news_engage_ts'),
                                  CHANNEL_COOLDOWNS['news'],
                                  drives.mood_arousal)):
        low_sal_news = await db.get_unseen_news(min_salience=0.0, limit=1)
        if low_sal_news:
            item = low_sal_news[0]
            return ArbiterFocus(
                channel='news',
                pipeline_mode=CHANNEL_TO_MODE['news'],
                payload={
                    'pool_id': item['id'],
                    'title': item.get('title', ''),
                    'headline': item.get('content', ''),
                    'source_channel': item.get('source_channel', ''),
                },
            )

    # ── Priority 7: Creative pressure ──
    if (_check_daily_budget(arbiter_state, 'express')
            and _cooldown_elapsed(arbiter_state.get('last_express_ts'),
                                  CHANNEL_COOLDOWNS['express'],
                                  drives.mood_arousal)
            and (drives.expression_need > 0.6)):
        return ArbiterFocus(channel='express', pipeline_mode='express')

    # ── Priority 7b: Wander channel (TASK-100) ──
    # In WANDER phase, inject novelty: pull random totem or unread content.
    if (idle_phase(idle_streak) == 'WANDER'
            and drives.curiosity > 0.6):
        import random as _rng
        # Try a random totem (old memory / meaningful entity)
        try:
            totems = await db.get_totems(min_weight=0.3, limit=10)
            if totems:
                pick = _rng.choice(totems)
                return ArbiterFocus(
                    channel='idle',
                    pipeline_mode='idle',
                    payload={'wander_source': 'totem',
                             'content': f"{pick.entity} — {pick.context or ''}",
                             'title': pick.entity},
                )
        except Exception:
            pass
        # Fallback: unread content pool item
        try:
            pool_items = await db.get_unseen_news(min_salience=0.0, limit=1)
            if pool_items:
                item = pool_items[0]
                return ArbiterFocus(
                    channel='idle',
                    pipeline_mode='idle',
                    payload={'wander_source': 'content_pool',
                             'pool_id': item['id'],
                             'title': item.get('title', ''),
                             'content': item.get('content', '')},
                )
        except Exception:
            pass

    # ── Priority 8: Default — ambient idle ──
    return ArbiterFocus(channel='idle', pipeline_mode='idle')


def update_arbiter_after_cycle(arbiter_state: dict, focus: ArbiterFocus):
    """Update arbiter counters after a focused cycle completes.

    Call this in heartbeat.py after run_cycle for non-idle/non-rest channels.
    """
    now = clock.now_utc()

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
