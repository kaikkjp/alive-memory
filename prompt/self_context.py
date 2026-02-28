"""Self-context assembler — TASK-060.

Builds a natural-language self-context block for injection into the Cortex
prompt each cycle.  The block gives her awareness of her own state as a
coherent snapshot:

  1. Identity — who she is (static seed, evolves in 061+)
  2. Current state — body, energy, mood, drives
  3. Recent behavior — last actions, habits
  4. Temporal — cycle count, time, time since sleep

The block is read-only.  She sees herself but doesn't modify herself.

Output is structured prose, NOT JSON — the LLM reads it as natural language.
Missing data → line omitted (no "N/A").
"""

import time
from datetime import datetime, timezone
from typing import Optional

import clock
import db
from config.identity import IDENTITY_COMPACT
from memory_translator import mood_word as _mood_word, drive_level as _drive_level, energy_word as _energy_word

# ── Token budget ──
# Character-estimate heuristic: ~4 chars per token on average.
# Hard cap ensures we stay within TASK-065 allocation when it lands.
SELF_CONTEXT_MAX_CHARS = 1200  # ~300 tokens
SELF_CONTEXT_MAX_TOKENS = 300  # informational; char cap is enforced


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token."""
    return len(text) // 4


def _truncate_to_budget(text: str, max_chars: int = SELF_CONTEXT_MAX_CHARS) -> str:
    """Truncate text to fit within character budget, cutting from the end."""
    if len(text) <= max_chars:
        return text
    # Cut at last newline before budget
    truncated = text[:max_chars]
    last_nl = truncated.rfind('\n')
    if last_nl > max_chars // 2:
        truncated = truncated[:last_nl]
    return truncated


# ── Diegetic mappings (migrated from heartbeat.py) ──

_GAZE_MAP = {
    'at_visitor': 'at the visitor',
    'at_object': 'at something on the shelf',
    'away_thinking': 'away, thinking',
    'down': 'down',
    'window': 'out the window',
}

_ACTION_MAP_BASE = {
    'write_journal': 'wrote in your journal',
    'accept_gift': 'accepted a gift',
    'decline_gift': 'declined a gift',
    'show_item': 'showed an item',
    'place_item': 'put something down',
    'rearrange': 'rearranged something',
    'post_x_draft': 'drafted a post',
    'end_engagement': 'ended the conversation',
    'browse_web': 'browsed the web',
    'express_thought': 'expressed a thought',
}


def _action_map(world=None) -> dict:
    """Action map with world-conditional close/open labels."""
    m = dict(_ACTION_MAP_BASE)
    if world:
        m['close_shop'] = world.close_action_text or 'closed the shop'
        m['open_shop'] = world.open_action_text or 'opened the shop'
    else:
        m['close_shop'] = 'closed the shop'
        m['open_shop'] = 'opened the shop'
    return m


# ── Main assembler ──

async def assemble_self_context(
    visitor=None,
    habit_boost=None,
    *,
    world=None,
    identity_compact: str = '',
) -> str:
    """Assemble the self-context block for the Cortex prompt.

    Returns a natural-language text block (~150-300 tokens).
    Returns empty string on first boot or total failure.

    Args:
        visitor: Current visitor object (for hands_state).
        habit_boost: Optional HabitBoost from basal_ganglia check_habits().
        world: WorldConfig from identity (conditions Shop line).
        identity_compact: Identity compact string. Falls back to config import.
    """
    sections = []

    # ── Section 1: Identity (static seed) ──
    # Pull the first sentence as a compact identity line.
    ic = identity_compact or IDENTITY_COMPACT
    identity_line = ic.split('\n')[0].strip()
    sections.append(f'[Self-context]\n{identity_line}')

    # ── Section 2: Current state ──
    state_parts = []

    # 2a. Drives + mood + energy
    try:
        drives = await db.get_drives_state()
        mood = _mood_word(drives.mood_valence, drives.mood_arousal)

        # Energy from real budget
        try:
            budget_info = await db.get_budget_remaining()
            energy_ratio = budget_info['remaining'] / budget_info['budget'] if budget_info['budget'] > 0 else 0.0
            energy_word = _energy_word(energy_ratio)
        except Exception:
            energy_word = _energy_word(drives.energy)

        state_parts.append(
            f'Energy: {energy_word} | Mood: {mood}'
            f' | Social hunger: {_drive_level(drives.social_hunger)}'
        )

        # Additional drives only if notable
        if drives.diversive_curiosity > 0.5:
            state_parts.append(f'Curiosity: {_drive_level(drives.diversive_curiosity)}')
        if drives.expression_need > 0.5:
            state_parts.append(f'Expression need: {_drive_level(drives.expression_need)}')
        if drives.rest_need > 0.6:
            state_parts.append(f'Rest need: {_drive_level(drives.rest_need)}')
    except Exception:
        pass  # drives table may not exist in tests

    # 2b. Body state (from last cycle log)
    try:
        last_log = await db.get_last_cycle_log()
        if last_log:
            body_line = f'Body: {last_log["body_state"]}'
            if last_log.get('expression') and last_log['expression'] != 'neutral':
                body_line += f', expression {last_log["expression"]}'
            gaze_text = _GAZE_MAP.get(last_log.get('gaze', ''), last_log.get('gaze', ''))
            if gaze_text:
                body_line += f', looking {gaze_text}'
            state_parts.append(body_line)

            # Hands
            if visitor and getattr(visitor, 'hands_state', None):
                state_parts.append(f'Holding: {visitor.hands_state}')
    except Exception:
        pass

    # 2c. Room state
    try:
        room = await db.get_room_state()
        now_jst = clock.now()
        time_str = now_jst.strftime('%H:%M')
        location_label = (world.location_label if world else 'Shop') or ''
        if location_label:
            state_parts.append(f'{location_label}: {room.shop_status} | Time: {time_str}')
        else:
            state_parts.append(f'Time: {time_str}')
    except Exception:
        pass

    # 2d. Drift summary (TASK-062: significant behavioral drift)
    try:
        from identity.drift import get_detector
        drift_summary = get_detector().get_drift_summary()
        if drift_summary:
            state_parts.append(drift_summary)
    except Exception:
        pass  # Drift module not loaded or not ready — skip silently

    if state_parts:
        sections.append('\n'.join(state_parts))

    # ── Section 3: Recent behavior ──
    behavior_parts = []

    # 3a. Recent executed actions (last 5)
    try:
        recent_actions = await db.get_action_log(limit=5, status_filter='executed')
        if recent_actions:
            action_words = []
            seen = set()
            for a in recent_actions:
                action_type = a.get('action', '')
                if action_type not in seen:
                    word = _action_map(world).get(action_type, action_type.replace('_', ' '))
                    action_words.append(word)
                    seen.add(action_type)
            if action_words:
                behavior_parts.append(f'Recent: {", ".join(action_words[:4])}')
    except Exception:
        pass

    # 3b. Habits (top 3 by strength)
    try:
        habits = await db.get_top_habits(limit=3)
        if habits:
            habit_strs = []
            for h in habits:
                if h.get('strength', 0) > 0.3:
                    action = h['action'].replace('_', ' ')
                    ctx = h.get('trigger_context', '')
                    if ctx:
                        habit_strs.append(f'{action} ({ctx})')
                    else:
                        habit_strs.append(action)
            if habit_strs:
                behavior_parts.append(f'Habits: {", ".join(habit_strs)}')
    except Exception:
        pass

    # 3c. Habit boost nudge (from basal_ganglia check_habits)
    if habit_boost:
        nudge_action = getattr(habit_boost, 'action', '').replace('_', ' ')
        if nudge_action:
            behavior_parts.append(
                f'You feel drawn to {nudge_action} — it\'s becoming a habit.'
            )

    if behavior_parts:
        sections.append('\n'.join(behavior_parts))

    # ── Section 4: Temporal awareness ──
    temporal_parts = []

    try:
        cycle_count = await db.count_cycle_logs()
        if cycle_count > 0:
            days_alive = await db.get_days_alive()
            temporal_parts.append(f'Cycle {cycle_count}')
            if days_alive > 0:
                temporal_parts.append(f'Day {days_alive}')
    except Exception:
        pass

    # Time since last sleep
    try:
        last_sleep_str = await db.get_setting('last_sleep_reset')
        if last_sleep_str:
            last_sleep_dt = datetime.fromisoformat(last_sleep_str)
            if last_sleep_dt.tzinfo is None:
                last_sleep_dt = last_sleep_dt.replace(tzinfo=timezone.utc)
            now_utc = clock.now_utc()
            delta = now_utc - last_sleep_dt
            hours_since = delta.total_seconds() / 3600
            if hours_since >= 1.0:
                temporal_parts.append(f'{hours_since:.1f}h since sleep')
            else:
                mins_since = delta.total_seconds() / 60
                temporal_parts.append(f'{mins_since:.0f}m since sleep')
    except Exception:
        pass

    if temporal_parts:
        sections.append(' | '.join(temporal_parts))

    # ── Assemble final block ──
    if len(sections) <= 1:
        return ''  # only identity header, no state — first boot

    block = '\n'.join(sections)
    block = _truncate_to_budget(block)

    token_est = _estimate_tokens(block)
    print(f'  [SelfContext] {len(block)} chars, ~{token_est} tokens')

    return block


# ── TASK-076: Self-context cache for idle cycles ──

_cache: tuple[str, float, int] | None = None  # (text, timestamp, cache_key_hash)
_CACHE_TTL = 300  # 5 minutes


async def assemble_self_context_cached(
    visitor=None,
    habit_boost=None,
    force_refresh: bool = False,
    *,
    world=None,
    identity_compact: str = '',
) -> str:
    """Cached wrapper. Only caches when no visitor (idle cycles).

    Engaged cycles always rebuild fresh (visitor context changes per turn).
    Cache is keyed on identity fingerprint to prevent cross-agent leaks.
    """
    global _cache
    now = time.monotonic()

    _kw = dict(world=world, identity_compact=identity_compact)

    # Cache key: hash of full identity + world so different agents never share cache
    _cache_key = hash((identity_compact, world))

    # Always rebuild when visitor present or force requested.
    # Also invalidate cache so next idle cycle gets fresh context
    # (drives/actions change during engagement).
    if visitor is not None or habit_boost is not None or force_refresh:
        result = await assemble_self_context(visitor=visitor, habit_boost=habit_boost, **_kw)
        _cache = None  # stale after engagement — next idle rebuilds fresh
        return result

    # Check cache for idle cycles
    if _cache is not None:
        text, ts, key = _cache
        if now - ts < _CACHE_TTL and key == _cache_key:
            print(f'  [SelfContext] cache hit ({now - ts:.0f}s old)')
            return text

    # Cache miss — rebuild and store
    result = await assemble_self_context(visitor=visitor, habit_boost=habit_boost, **_kw)
    _cache = (result, now, _cache_key)
    return result


def invalidate_self_context_cache():
    """Call after sleep cycle or significant state change."""
    global _cache
    _cache = None
