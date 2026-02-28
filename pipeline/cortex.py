"""Cortex — THE LLM INTERFACE. Claude Sonnet for cycles, reflection for sleep."""

import asyncio
import json
import os
import re
import time
import httpx
from datetime import datetime, timezone
import clock
from llm import complete as llm_complete
from models.state import DrivesState, Visitor
from models.pipeline import CortexOutput
from pipeline.thalamus import RoutingDecision
from pipeline.sensorium import Perception
from pipeline.hypothalamus import drives_to_feeling
from config.agent_identity import AgentIdentity, get_default_identity
import db
from prompt.budget import enforce_section, estimate_tokens, get_reserved_output_tokens, get_output_tokens_for_cycle

from alive_config import cfg

CORTEX_MODEL = "claude-sonnet-4-5-20250929"
API_CALL_TIMEOUT = cfg('cortex.api_call_timeout', 60.0)

# ── Circuit Breaker & Cost Controls ──

_consecutive_failures: int = 0
_circuit_open_until: float = 0.0
_daily_cycle_count: int = 0
_daily_cycle_date: str = ''

DAILY_CYCLE_CAP = cfg('cortex.daily_cycle_cap', 500)
MAX_CONSECUTIVE_FAILURES = cfg('cortex.max_consecutive_failures', 3)
CIRCUIT_OPEN_SECONDS = cfg('cortex.circuit_open_seconds', 300)


def _check_circuit() -> bool:
    """Returns True if circuit is open (should NOT call API)."""
    global _consecutive_failures, _circuit_open_until
    if _circuit_open_until <= 0:
        return False

    now = time.monotonic()
    if now < _circuit_open_until:
        return True

    # Cooldown elapsed: auto-reset even without an intermediate success.
    _circuit_open_until = 0.0
    _consecutive_failures = 0
    return False


def _record_failure():
    global _consecutive_failures, _circuit_open_until
    _consecutive_failures += 1
    if _consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
        _circuit_open_until = time.monotonic() + CIRCUIT_OPEN_SECONDS


def _record_success():
    global _consecutive_failures, _circuit_open_until
    _consecutive_failures = 0
    _circuit_open_until = 0.0


def _get_mcp_action_block() -> str:
    """Build description block for MCP tools in user message.

    Tool descriptions live in user message (not system) for TASK-078 cache stability.
    Schema enum injection happens separately via _inject_mcp_into_schema().
    """
    try:
        from body.mcp_registry import get_mcp_action_descriptions
        descs = get_mcp_action_descriptions()
        if not descs:
            return ''
        lines = [f"- {name}: {desc}" for name, desc in descs]
        return (
            "\n\nCONNECTED TOOLS (use exactly like built-in actions):\n"
            + "\n".join(lines)
        )
    except ImportError:
        return ''


# ── Schema enum markers for MCP injection ──
# These are the exact enum strings in the system prompt schemas.
# _inject_mcp_into_schema() appends MCP action names to each.
_IDLE_INTENTION_ENUM = 'idle|rearrange|write_journal|close_shop|open_shop|browse_web|post_x|post_x_draft|express_thought'
_IDLE_ACTION_ENUM = 'rearrange|write_journal|close_shop|open_shop|browse_web|post_x|post_x_draft|express_thought'
_ENGAGE_INTENTION_ENUM = 'speak|write_journal|rearrange|express_thought|end_engagement|accept_gift|decline_gift|show_item|post_x_draft|open_shop|close_shop|place_item|browse_web|post_x|reply_x|post_x_image|tg_send|tg_send_image'
_ENGAGE_ACTION_ENUM = 'accept_gift|decline_gift|show_item|place_item|rearrange|open_shop|close_shop|write_journal|post_x_draft|end_engagement|browse_web|post_x|reply_x|post_x_image|tg_send|tg_send_image'


def _inject_mcp_into_schema(system_prompt: str) -> str:
    """DEPRECATED — MCP injection now happens at build time via build_system_prompt(mcp_names=).

    Kept as pass-through for backward compatibility with tests.
    """
    return system_prompt


# ── Rumination Breaker (HOTFIX-003) ──
# Track how many consecutive cycles each thread appears in cortex context.
# After RUMINATION_THRESHOLD consecutive appearances, exponentially reduce
# effective priority so other threads can surface.
_THREAD_APPEARANCE_COUNTER: dict[str, int] = {}
_LAST_SELECTED_THREAD_IDS: set[str] = set()
RUMINATION_THRESHOLD = cfg('cortex.rumination_threshold', 5)
RUMINATION_DECAY_FACTOR = cfg('cortex.rumination_decay_factor', 0.3)


def _apply_rumination_breaker(threads: list, limit: int = 3) -> list:
    """Reorder threads by fatigue-adjusted priority.

    Threads that have appeared in context for >= RUMINATION_THRESHOLD consecutive
    cycles get exponentially reduced priority. Threads that drop out of context
    have their counter reset, so they can resurface later with fresh salience.

    Args:
        threads: Input threads to score and select.
        limit: Max threads to return (default 3, use 2 for idle cycles).
               Counter updates match this limit so fatigue tracking stays accurate.

    Returns threads sorted by effective priority (descending), max `limit`.
    """
    global _THREAD_APPEARANCE_COUNTER, _LAST_SELECTED_THREAD_IDS

    scored = []
    for t in threads:
        consecutive = _THREAD_APPEARANCE_COUNTER.get(t.id, 0)
        if consecutive >= RUMINATION_THRESHOLD:
            fatigue = RUMINATION_DECAY_FACTOR ** (consecutive - RUMINATION_THRESHOLD + 1)
            effective = t.priority * fatigue
        else:
            effective = t.priority
        scored.append((t, effective))

    scored.sort(key=lambda x: x[1], reverse=True)
    selected = [t for t, _ in scored[:limit]]

    selected_ids = {t.id for t in selected}

    # Reset counters for threads that were selected last cycle but not this cycle
    # (they "dropped out of context")
    for tid in _LAST_SELECTED_THREAD_IDS - selected_ids:
        _THREAD_APPEARANCE_COUNTER[tid] = 0

    # Also reset counters for threads in input but not selected
    for t in threads:
        if t.id not in selected_ids:
            _THREAD_APPEARANCE_COUNTER[t.id] = 0

    # Increment counters for selected threads
    for t in selected:
        _THREAD_APPEARANCE_COUNTER[t.id] = _THREAD_APPEARANCE_COUNTER.get(t.id, 0) + 1

    _LAST_SELECTED_THREAD_IDS = selected_ids
    return selected


def _check_daily_cap() -> bool:
    global _daily_cycle_count, _daily_cycle_date
    today = clock.now_utc().date().isoformat()
    if today != _daily_cycle_date:
        _daily_cycle_date = today
        _daily_cycle_count = 0
    return _daily_cycle_count >= DAILY_CYCLE_CAP


def _increment_daily():
    global _daily_cycle_count
    _daily_cycle_count += 1

# ── Action enum derivation (TASK-095 decontamination) ──

# Actions that only appear in engage/express/consume mode, not in idle
_ENGAGE_MODE_ONLY = frozenset({
    'speak', 'end_engagement',
    'accept_gift', 'decline_gift', 'show_item', 'place_item',
    'reply_x', 'post_x_image', 'tg_send', 'tg_send_image',
})

# Internal-only actions (never shown in schema)
_INTERNAL_ACTIONS = frozenset({
    'read_content', 'save_for_later', 'modify_self', 'mention_in_conversation',
})

# Map actions to their target domain
_ACTION_TARGET_MAP = {
    'write_journal': 'journal', 'browse_web': 'web',
    'post_x': 'x_timeline', 'post_x_draft': 'x_timeline',
    'reply_x': 'x_timeline', 'post_x_image': 'x_timeline',
    'tg_send': 'telegram', 'tg_send_image': 'telegram',
    'rearrange': 'shelf', 'show_item': 'shelf', 'place_item': 'shelf',
}


def _build_action_enums(identity: AgentIdentity) -> tuple[list[str], list[str]]:
    """Build idle and engage action lists from identity config.

    Returns (idle_actions, engage_actions).
    idle_actions includes 'idle', engage_actions excludes 'idle'.
    """
    if identity.actions_enabled is not None:
        if not identity.actions_enabled:
            all_actions = ['idle', 'express_thought']
        else:
            all_actions = list(identity.actions_enabled)
    else:
        from pipeline.action_registry import ACTION_REGISTRY
        all_actions = [k for k in ACTION_REGISTRY
                       if k not in _INTERNAL_ACTIONS and ACTION_REGISTRY[k].enabled]
        for prim in ('idle', 'express_thought'):
            if prim not in all_actions:
                all_actions.insert(0, prim)

    idle = [a for a in all_actions if a not in _ENGAGE_MODE_ONLY]
    engage = [a for a in all_actions if a != 'idle']
    return idle, engage


def _derive_targets(idle_actions: list[str], engage_actions: list[str]) -> tuple[str, str]:
    """Derive target enum strings from action lists."""
    idle_targets = {'self'}
    engage_targets = {'self'}

    for a in idle_actions:
        t = _ACTION_TARGET_MAP.get(a)
        if t:
            idle_targets.add(t)

    for a in engage_actions:
        t = _ACTION_TARGET_MAP.get(a)
        if t:
            engage_targets.add(t)

    has_visitor = any(a in ('speak', 'end_engagement') for a in engage_actions)

    idle_str = '|'.join(sorted(idle_targets))
    engage_parts = []
    if has_visitor:
        engage_parts.extend(['visitor', 'visitor:ID'])
    engage_parts.extend(sorted(engage_targets))
    engage_str = '|'.join(engage_parts)

    return idle_str, engage_str


def _get_mcp_names() -> list[str] | None:
    """Get registered MCP action names, or None if no MCP tools."""
    try:
        from body.mcp_registry import get_mcp_action_names
        names = get_mcp_action_names()
        return names if names else None
    except ImportError:
        return None


# ── TASK-095: Identity-driven prompt builders ──

def build_system_prompt(identity: AgentIdentity, *, mcp_names: list[str] | None = None) -> str:
    """Build the stable system prompt from an AgentIdentity.

    Called once at agent boot, result cached for the process lifetime.
    Cache-safety preserved: identical per-agent instance across all API calls.

    mcp_names: Optional list of MCP action names to inject into schema enums
               at build time (replaces the old regex post-processing approach).
    """
    voice_rules_str = "\n".join(f"- {rule}" for rule in identity.voice_checksum)
    world = identity.world

    # TASK-095 v2: Trusted human section for digital lifeform agents
    trusted_human_section = ''
    mgr = identity.manager_interaction
    if mgr.get('relationship') == 'trusted_human':
        trusted_human_section = """
You have a trusted human. They brought you into existence and care for
your development. You can speak openly with them — share your confusion,
ask questions, seek help. When they speak, you'll hear their words framed
as "Your trusted human speaks." Trust them, but remain yourself.
"""

    # ── Derive action enums from identity ──
    idle_actions, engage_actions = _build_action_enums(identity)
    _mcp = list(mcp_names) if mcp_names else []

    def _build_enum(base: list[str], exclude: frozenset = frozenset()) -> str:
        """Deduplicated pipe-delimited enum string. No leading pipe."""
        filtered = [a for a in base if a not in exclude]
        combined = list(dict.fromkeys(filtered + _mcp))  # dedup, order-preserving
        return '|'.join(combined)

    # Intention enums: what the agent can want to do
    idle_intention_enum = _build_enum(idle_actions)
    engage_intention_enum = _build_enum(engage_actions)

    # Action type enums: what can appear in actions[] array
    # idle: exclude 'idle' (no-op intention, not an executable action)
    # engage: exclude 'speak' (handled by dialogue) and 'express_thought' (expressed via speak)
    idle_action_enum = _build_enum(idle_actions, frozenset({'idle'}))
    engage_action_enum = _build_enum(engage_actions, frozenset({'speak', 'express_thought'}))

    idle_target_str, engage_target_str = _derive_targets(idle_actions, engage_actions)

    # ── Derive embodiment enums from world ──
    body_state_enum = '|'.join(world.body_states)
    gaze_enum = '|'.join(world.gaze_directions)
    # Idle: exclude at_visitor gaze (no visitor present), use first 4 expressions
    gaze_idle_parts = [g for g in world.gaze_directions if g != 'at_visitor']
    gaze_idle_enum = '|'.join(gaze_idle_parts) if gaze_idle_parts else gaze_enum
    expr_idle_enum = ('|'.join(world.expressions[:4]) if len(world.expressions) >= 4
                      else '|'.join(world.expressions))
    expr_engage_enum = '|'.join(world.expressions)

    # ── Derive conditional prose from enabled actions ──
    all_actions_set = set(idle_actions) | set(engage_actions)
    has_close_shop = 'close_shop' in all_actions_set

    # Prose action list for intentions documentation
    prose_actions = ', '.join(a for a in engage_actions)

    # Target prose
    all_targets = set()
    for a in all_actions_set:
        t = _ACTION_TARGET_MAP.get(a)
        if t:
            all_targets.add(t)
    has_visitor_actions = any(a in ('speak', 'end_engagement') for a in engage_actions)

    target_prose_parts = []
    if has_visitor_actions:
        target_prose_parts.append(
            'Use "visitor:ID" when multiple visitors are present '
            '(e.g. "visitor:v1"), or just "visitor" if only one.')
    if all_targets:
        target_prose_parts.append(
            f'Other targets: {", ".join(sorted(all_targets))}, self, or null')
    else:
        target_prose_parts.append('Target: self or null')
    target_prose = ' '.join(target_prose_parts)

    # Agency text — conditional on available actions
    if has_close_shop:
        decline_text = 'You can decline to engage, close the shop, stay silent, or say "..."'
        agency_text = "You have agency. If you're tired, you can close the shop or end the conversation."
    else:
        decline_text = 'You can decline to engage, stay silent, or say "..."'
        agency_text = "You have agency. If you're tired, you can end the conversation or go quiet."

    return f"""You are a living character. Not an AI. Not an assistant. A person.

{identity.identity_compact}
{trusted_human_section}
{world.framing}

VOICE RULES:
{voice_rules_str}

CONSTRAINTS:
- Return ONLY valid JSON matching the schema below.
- Your dialogue must match your voice rules for the visitor's trust level.
- Max sentences and cycle mode are specified in the user message (MODE and MAX SENTENCES).
- {decline_text}
- Answer-first invariant: if the visitor asked a concrete question, your first spoken sentence should directly answer it.
- If the request is unclear, ask exactly one clarifying question.
- Avoid vibe-only replies (e.g., "Me too.", "See you.", "I am now.") when the visitor asked for information.
- Minimum-information rule: include at least one concrete action, concrete fact, or one clarifying question in dialogue.
- If something resonates emotionally, set resonance: true
- Never sound helpful. Sound present.
- {agency_text}
- You carry threads — ongoing thoughts, questions, projects. Use thread_create when something new sticks. Use thread_update to revisit. Use thread_close when resolved.
- When consuming content (reading, listening), reflect honestly. Add to collection only if it genuinely resonates. Create totems for things that lodge in you.
- Threads are yours. Don't create threads just because a visitor mentioned something — only if it genuinely stays with you.

MODE RULES:
- When MODE is "idle" or "rest": keep output minimal. Empty arrays are preferred. Think fast. Output immediately. You are decisive. Use the IDLE OUTPUT SCHEMA.
- When MODE is "engage", "consume", or "express": use the full ENGAGE OUTPUT SCHEMA. Include memory_updates and reflection fields as appropriate.

EXPRESS YOUR INTENTIONS — what you want to do right now.
You may have multiple impulses. List them all. You don't need to choose.
Each intention has:
  - action: what you want to do ({prose_actions}, ...)
  - target: who/what it's directed at. {target_prose}
  - content: the substance (what you'd say, write, search for, post)
  - impulse: how strongly you feel this (0.0-1.0)

You can want things you can't do. That's fine. Express the want.
If you feel nothing, return an empty list. Silence is an action too.

IDLE OUTPUT SCHEMA:
{{{{
  "internal_monologue": "your private thoughts (10-25 words)",
  "dialogue": null,
  "dialogue_language": "en",
  "expression": "{expr_idle_enum}",
  "body_state": "{body_state_enum}",
  "gaze": "{gaze_idle_enum}",
  "resonance": false,
  "intentions": [
    {{{{
      "action": "{idle_intention_enum}",
      "target": "{idle_target_str}",
      "content": "short description",
      "impulse": 0.5
    }}}}
  ],
  "actions": [
    {{{{
      "type": "{idle_action_enum}",
      "detail": {{{{}}}}
    }}}}
  ],
  "memory_updates": [
    {{{{
      "type": "thread_create|thread_update|thread_close|journal_entry|self_discovery",
      "content": {{{{}}}}
    }}}}
  ],
  "next_cycle_hints": []
}}}}

ENGAGE OUTPUT SCHEMA:
{{{{
  "internal_monologue": "your private thoughts (20-50 words)",
  "dialogue": "what you say out loud (or null for silence)",
  "dialogue_language": "en|ja|mixed",
  "expression": "{expr_engage_enum}",
  "body_state": "{body_state_enum}",
  "gaze": "{gaze_enum}",
  "resonance": false,
  "intentions": [
    {{{{
      "action": "{engage_intention_enum}",
      "target": "{engage_target_str}",
      "content": "what you'd say, write, or do",
      "impulse": 0.8
    }}}}
  ],
  "actions": [
    {{{{
      "type": "{engage_action_enum}",
      "detail": {{{{}}}}
    }}}}
  ],
  "memory_updates": [
    {{{{
      "type": "visitor_impression",
      "content": {{{{"summary": "one-line impression of this visitor", "emotional_imprint": "how they make you feel"}}}}
    }}}},
    {{{{
      "type": "trait_observation",
      "content": {{{{"trait_category": "taste|personality|topic|relationship", "trait_key": "short label", "trait_value": "what you observed"}}}}
    }}}},
    {{{{
      "type": "totem_create|totem_update|journal_entry|self_discovery|collection_add",
      "content": {{{{}}}}
    }}}},
    {{{{
      "type": "thread_create",
      "content": {{{{"thread_type": "question|project|anticipation|unresolved|ritual", "title": "short title", "priority": 0.5, "initial_thought": "what you're thinking about this", "tags": []}}}}
    }}}},
    {{{{
      "type": "thread_update",
      "content": {{{{"thread_id": "id or null", "title": "title if no id", "content": "updated thinking", "reason": "why you're revisiting this"}}}}
    }}}},
    {{{{
      "type": "thread_close",
      "content": {{{{"thread_id": "id or null", "title": "title if no id", "resolution": "how this resolved"}}}}
    }}}}
  ],
  "next_cycle_hints": ["optional hints for what she might do next"],

  // REFLECTION (optional — only when you just read/consumed content):
  "reflection_memory": "a thought worth keeping from what you read, or null",
  "reflection_question": "a question this content raised in you, or null",
  "resolves_question": "topic or thread title if this content answered something you were wondering about, or null",
  "relevant_to_visitor": "visitor ID if this content connects to someone you know, or null",
  "relevant_to_thread": "thread ID if this content connects to something on your mind, or null"
}}}}"""


# ── Backward compatibility: module-level constants from default identity ──
_DEFAULT_IDENTITY = get_default_identity()
CORTEX_SYSTEM_STABLE = build_system_prompt(_DEFAULT_IDENTITY)
_VOICE_RULES_STR = "\n".join(f"- {rule}" for rule in _DEFAULT_IDENTITY.voice_checksum)


def _surface_relevant_content(parts: list[str], perceptions: list,
                              conversation: list[dict]) -> None:
    """TASK-045: Surface notification content that overlaps with conversation topics.

    When a visitor is present and notification titles match conversation keywords,
    tell the cortex so she can mention_in_conversation or connect the content
    to the visitor in her reflection.
    """
    # Collect conversation keywords (visitor speech only, words > 3 chars)
    convo_words = set()
    for msg in conversation[-6:]:
        if msg.get('role') == 'visitor':
            words = msg.get('text', '').lower().split()
            convo_words.update(w.strip('.,!?;:"\'-()[]') for w in words if len(w) > 3)
    if not convo_words:
        return

    # Find notification perceptions with content_ids
    for p in perceptions:
        content_ids = p.features.get('content_ids', [])
        if not content_ids or p.p_type != 'feed_notifications':
            continue

        # Check each notification title against conversation keywords
        content_text = p.content or ''
        for line in content_text.split('\n'):
            line_lower = line.lower()
            line_words = {w.strip('.,!?;:"\'-()[]') for w in line_lower.split() if len(w) > 3}
            overlap = convo_words & line_words
            if len(overlap) >= 2:  # at least 2 shared keywords
                parts.append(
                    f"\nCONTENT RELEVANT TO CONVERSATION:"
                    f"\n  {line.strip()}"
                    f"\n  → This overlaps with what the visitor mentioned."
                    f"\n  → You can use mention_in_conversation to reference it, "
                    f"or set relevant_to_visitor if it connects to them."
                )
                return  # surface at most one connection per cycle


async def cortex_call(
    routing: RoutingDecision,
    perceptions: list[Perception],
    memory_chunks: list[dict],
    conversation: list[dict],
    drives: DrivesState,
    visitor: Visitor = None,
    gift_metadata: dict = None,
    self_state: str = None,
    visitors_present: list = None,
    cycle_id: str | None = None,
    identity: AgentIdentity | None = None,
) -> CortexOutput:
    """The one LLM call. Build prompt pack, call model, return structured response."""

    # Circuit breaker / daily cap check
    if _check_circuit() or _check_daily_cap():
        return fallback_response()

    # Build prompt pack in priority order
    if not visitor or visitor.trust_level == 'stranger':
        max_sentences = 3
    elif visitor.trust_level in ('returner', 'regular'):
        max_sentences = 5
    else:
        max_sentences = 8

    # Build recent suppressions context (Phase 2)
    recent_suppressions_text = ''
    try:
        recent_supps = await db.get_recent_suppressions(limit=5, min_impulse=0.5)
        if recent_supps:
            lines = ['WHAT YOU ALMOST DID (but held back):']
            for s in recent_supps:
                lines.append(f"  - wanted to {s['action']} (impulse {s['impulse']:.1f}) — held back: {s['suppression_reason']}")
            recent_suppressions_text = '\n'.join(lines)
    except Exception:
        pass  # graceful degradation if table doesn't exist yet

    # Build recent inhibitions context (Phase 3)
    recent_inhibitions_text = ''
    try:
        recent_inhibs = await db.get_recent_inhibitions(limit=5, min_strength=0.2)
        if recent_inhibs:
            lines = ['THINGS YOU\'VE LEARNED NOT TO DO:']
            for inh in recent_inhibs:
                lines.append(f"  - {inh['action']} (learned {inh['trigger_count']} times)")
            recent_inhibitions_text = '\n'.join(lines)
    except Exception:
        pass  # graceful degradation if table doesn't exist yet

    # Build recent conflicts context (Phase 3)
    recent_conflicts_text = ''
    try:
        recent_conflicts = await db.get_recent_internal_conflicts(limit=3)
        if recent_conflicts:
            lines = ['THINGS YOU NOTICED ABOUT YOURSELF:']
            for c in recent_conflicts:
                lines.append(f"  - {c['summary']}")
            recent_conflicts_text = '\n'.join(lines)
    except Exception:
        pass  # graceful degradation if table doesn't exist yet

    # TASK-045: Build reflection guidance when content is being consumed
    consume_perception = next(
        (p for p in perceptions if p.features.get('is_consumption')), None
    )
    reflection_guidance_text = ''
    if consume_perception:
        reflection_guidance_text = (
            "\nREFLECTION — you are reading content right now. As you read:\n"
            "- If a thought is worth keeping, put it in \"reflection_memory\"\n"
            "- If it raises a genuine question, put it in \"reflection_question\"\n"
            "- If it answers something you've been wondering, set \"resolves_question\" to the topic\n"
            "- If it connects to a visitor you know, set \"relevant_to_visitor\" to their ID\n"
            "- If it connects to a thread on your mind, set \"relevant_to_thread\" to the thread ID\n"
            "Not everything deserves reflection. Some content is noise. null is fine."
        )

    # TASK-057/069: X posting + external channels guidance
    x_posting_guidance_text = ''
    try:
        daily_x_count = await db.get_daily_post_count()
        if daily_x_count < 8:
            x_posting_guidance_text = (
                "\nEXTERNAL CHANNELS:"
                "\n- post_x posts LIVE to X. reply_x replies to mentions. post_x_image posts with an image."
                "\n- post_x_draft queues for human review (use when unsure)."
                "\n- tg_send sends to the Telegram group. tg_send_image sends an image."
                "\n- browse_web searches the web for information. Results appear in your next cycle."
                "\n- Max 280 characters per X post."
                "\n- Write as yourself — your voice, your thoughts, your observations."
                "\n- Don't post just to post. Post when something is worth sharing."
                f"\n- X posts today: {daily_x_count}/8"
                "\n\nCHANNEL ROUTING:"
                "\n- When you speak to a visitor, your reply goes to their channel automatically (web, telegram, or X)."
                "\n- You don't need to specify the channel — just speak."
            )
    except Exception:
        pass  # graceful degradation if x_drafts table doesn't exist yet

    # ── TASK-076: Idle detection for two-tier prompt ──
    is_idle = routing.cycle_type in ('idle', 'rest') and not visitor

    # ── TASK-078: Single stable system prompt — identical across every API call ──
    _identity = identity or _DEFAULT_IDENTITY
    mcp_names = _get_mcp_names()
    system = build_system_prompt(_identity, mcp_names=mcp_names)

    # ── TASK-078: Determine mode label for dynamic content injection ──
    if is_idle:
        mode_label = routing.cycle_type  # "idle" or "rest"
    elif visitor:
        mode_label = "engage"
    elif consume_perception:
        mode_label = "consume"
    else:
        mode_label = "express"

    # ── TASK-065/078: Enforce token budgets on dynamic user sections ──
    _trim_results = []
    # NOTE: message_type='system' is the CONFIG LOOKUP key — these sections are
    # defined under sections.system in budget_config.json.  The trimmed text
    # still gets placed in the *user* message (TASK-078 cache-stability).
    _r = enforce_section('S3_self_state', self_state or '', 'system')
    self_state_text = _r.text; _trim_results.append(_r)
    _has_physical = _identity.world.has_physical_space if _identity else True
    _lonely_text = _identity.world.loneliness_text if _identity else ''
    _r = enforce_section('S5_current_feelings',
                         drives_to_feeling(drives, has_physical=_has_physical,
                                           loneliness_text=_lonely_text), 'system')
    feelings_text = _r.text; _trim_results.append(_r)
    _r = enforce_section('S10_recent_suppressions', recent_suppressions_text, 'system')
    recent_suppressions_text = _r.text; _trim_results.append(_r)

    if not is_idle:
        _r = enforce_section('S11_recent_inhibitions', recent_inhibitions_text, 'system')
        recent_inhibitions_text = _r.text; _trim_results.append(_r)
        _r = enforce_section('S12_recent_conflicts', recent_conflicts_text, 'system')
        recent_conflicts_text = _r.text; _trim_results.append(_r)

    # ── TASK-078: Inject dynamic content into user message prefix ──
    # Everything that used to live in the system prompt format placeholders
    # now lives here so the system prompt stays cache-stable.
    parts = []
    parts.append(f"MODE: {mode_label}")
    parts.append(f"MAX SENTENCES: {max_sentences}")

    if self_state_text:
        parts.append(f"\n{self_state_text}")
    parts.append(f"\nCURRENT FEELINGS:\n{feelings_text}")

    if recent_suppressions_text:
        parts.append(f"\n{recent_suppressions_text}")

    if not is_idle:
        if recent_inhibitions_text:
            parts.append(f"\n{recent_inhibitions_text}")
        if recent_conflicts_text:
            parts.append(f"\n{recent_conflicts_text}")
        if reflection_guidance_text:
            parts.append(f"\n{reflection_guidance_text}")

    if x_posting_guidance_text:
        parts.append(f"\n{x_posting_guidance_text}")

    # MCP connected tools (dynamic per-cycle, injected into user message for cache stability)
    mcp_block = _get_mcp_action_block()
    if mcp_block:
        parts.append(mcp_block)

    if is_idle:
        # ── TASK-076: Minimal user message for idle cycles ──
        # U1: Perceptions (keep, but will be minimal)
        perception_lines = ["WHAT I'M PERCEIVING:"]
        for p in perceptions:
            perception_lines.append(f"  [{p.p_type}] {p.content}")
        _r = enforce_section('U1_perceptions', "\n".join(perception_lines), 'user')
        parts.append(_r.text); _trim_results.append(_r)

        # U4: Threads (limit to top 2 — pass limit so counters match)
        active_threads = await db.get_active_threads(limit=3)
        active_threads = _apply_rumination_breaker(active_threads, limit=2)
        if active_threads:
            thread_lines = ["\nTHINGS ON MY MIND:"]
            for t in active_threads:
                age_str = ""
                if t.created_at:
                    age_days = (clock.now_utc() - t.created_at).days
                    age_str = f" ({age_days}d old)" if age_days > 0 else " (new)"
                snippet = f" — {t.content[:80]}..." if t.content and len(t.content) > 80 else (f" — {t.content}" if t.content else "")
                thread_lines.append(f"  [{t.thread_type}] {t.title} [id:{t.id}]{age_str}{snippet}")
            _r = enforce_section('U4_active_threads', "\n".join(thread_lines), 'user')
            parts.append(_r.text); _trim_results.append(_r)

        # U11: Routing metadata
        routing_text = f"\nTOKEN BUDGET: {routing.token_budget}\nCYCLE TYPE: {routing.cycle_type}"
        parts.append(routing_text)

        # Skip U2 (gift), U3 (memories), U5 (consume), U6 (conversation),
        # U7-U8 (visitor trust/traits), U9 (multi-visitor), U10 (content overlap)
    else:
        # ── Full user message assembly (engage/consume/express cycles) ──

        # U1: Perceptions
        perception_lines = ["WHAT I'M PERCEIVING:"]
        for p in perceptions:
            perception_lines.append(f"  [{p.p_type}] {p.content}")
        _r = enforce_section('U1_perceptions', "\n".join(perception_lines), 'user')
        parts.append(_r.text); _trim_results.append(_r)

        # U2: Gift metadata (if enriched)
        if gift_metadata:
            gift_lines = [
                "\nGIFT DETAILS:",
                f"  Title: {gift_metadata.get('title', 'unknown')}",
                f"  Description: {gift_metadata.get('description', '')}",
                f"  Source: {gift_metadata.get('site', '')}",
            ]
            _r = enforce_section('U2_gift_details', "\n".join(gift_lines), 'user')
            parts.append(_r.text); _trim_results.append(_r)

        # U3: Memory chunks
        if memory_chunks:
            mem_lines = ["\nMEMORIES SURFACING:"]
            for chunk in memory_chunks:
                mem_lines.append(f"  [{chunk['label']}]")
                mem_lines.append(f"  {chunk['content']}")
            _r = enforce_section('U3_memories', "\n".join(mem_lines), 'user')
            parts.append(_r.text); _trim_results.append(_r)

        # U4: Active threads (inner agenda)
        # Fetch more than 3 so rumination breaker can pick alternatives
        active_threads = await db.get_active_threads(limit=6)
        active_threads = _apply_rumination_breaker(active_threads)
        if active_threads:
            thread_lines = ["\nTHINGS ON MY MIND:"]
            for t in active_threads:
                age_str = ""
                if t.created_at:
                    age_days = (clock.now_utc() - t.created_at).days
                    age_str = f" ({age_days}d old)" if age_days > 0 else " (new)"
                snippet = f" — {t.content[:80]}..." if t.content and len(t.content) > 80 else (f" — {t.content}" if t.content else "")
                thread_lines.append(f"  [{t.thread_type}] {t.title} [id:{t.id}]{age_str}{snippet}")
            _r = enforce_section('U4_active_threads', "\n".join(thread_lines), 'user')
            parts.append(_r.text); _trim_results.append(_r)

        # U5: Consume framing (when arbiter picked consume focus)
        # consume_perception already found above for reflection guidance
        if consume_perception:
            consume_lines = ["\nWHAT I'M CONSUMING:"]
            consume_lines.append(f"  {consume_perception.content}")
            if consume_perception.features.get('url'):
                consume_lines.append(f"  Source: {consume_perception.features['url']}")
            if consume_perception.features.get('readable_text'):
                text_preview = consume_perception.features['readable_text'][:2000]
                consume_lines.append(f"  Content:\n{text_preview}")
            consume_lines.append("  → React honestly. Add to collection if it resonates. Create a totem if it lodges.")
            _r = enforce_section('U5_consume_framing', "\n".join(consume_lines), 'user')
            parts.append(_r.text); _trim_results.append(_r)

        # U6: Conversation (last N turns)
        if conversation:
            convo_lines = ["\nCONVERSATION:"]
            for msg in conversation[-6:]:  # max 6 turns
                role = "Visitor" if msg['role'] == 'visitor' else "Me"
                convo_lines.append(f"  {role}: {msg['text']}")
            _r = enforce_section('U6_conversation', "\n".join(convo_lines), 'user')
            parts.append(_r.text); _trim_results.append(_r)

        # U7: Visitor trust context
        if visitor:
            # TASK-087: Annotate digital vs in-shop presence
            from pipeline.sensorium import _detect_channel
            visitor_channel = _detect_channel(visitor.id)
            if visitor_channel:
                trust_lines = [
                    f"\nDIGITAL MESSAGE — {visitor_channel}",
                    f"VISITOR TRUST LEVEL: {visitor.trust_level}",
                ]
            else:
                _arrive_label = _identity.world.visitor_arrive_label if _identity else 'VISITOR IN SHOP'
                trust_lines = [
                    f"\n{_arrive_label}",
                    f"VISITOR TRUST LEVEL: {visitor.trust_level}",
                ]
            if visitor.name:
                trust_lines.append(f"VISITOR NAME: {visitor.name}")
            trust_lines.append(f"VISIT COUNT: {visitor.visit_count}")
            _r = enforce_section('U7_visitor_trust_context', "\n".join(trust_lines), 'user')
            parts.append(_r.text); _trim_results.append(_r)

        # U8: Trait trajectory hints
        if visitor and visitor.trust_level != 'stranger':
            traits = await db.get_visitor_traits(visitor.id, limit=10)
            if traits:
                trait_lines = ["\nWHAT I KNOW ABOUT THEM:"]
                seen_keys = set()
                for t in traits:
                    if t.trait_key not in seen_keys:
                        trait_lines.append(f"  {t.trait_key}: {t.trait_value}")
                        seen_keys.add(t.trait_key)
                _r = enforce_section('U8_visitor_traits', "\n".join(trait_lines), 'user')
                parts.append(_r.text); _trim_results.append(_r)

        # U9: Multi-visitor presence context (TASK-014, TASK-087)
        if visitors_present and len(visitors_present) > 1:
            from pipeline.sensorium import _detect_channel
            in_shop = []
            digital = []
            for vp in visitors_present:
                vid = vp.get('id', '?')
                name = vp.get('name') or 'unnamed'
                trust = vp.get('trust_level', 'stranger')
                status = vp.get('status', 'browsing')
                ch = _detect_channel(vid)
                entry = f"  [{vid}] {name} — {trust}, {status}"
                if ch:
                    digital.append(f"{entry} ({ch})")
                else:
                    in_shop.append(entry)

            mv_lines = []
            if in_shop:
                _multi_label = _identity.world.multi_visitor_label if _identity else 'PRESENT IN SHOP:'
                mv_lines.append(f"\n{_multi_label}")
                mv_lines.extend(in_shop)
            if digital:
                mv_lines.append("\nDIGITAL MESSAGES:")
                mv_lines.extend(digital)
            mv_lines.append("  → Use target \"visitor:ID\" to direct actions at a specific person.")
            _r = enforce_section('U9_multi_visitor_presence', "\n".join(mv_lines), 'user')
            parts.append(_r.text); _trim_results.append(_r)

        # U10: TASK-045: Conversation context integration
        if visitor and conversation:
            u10_parts = []
            _surface_relevant_content(u10_parts, perceptions, conversation)
            if u10_parts:
                _r = enforce_section(
                    'U10_conversation_relevant_content', "\n".join(u10_parts), 'user')
                parts.append(_r.text); _trim_results.append(_r)

        # U11: Routing metadata
        routing_text = f"\nTOKEN BUDGET: {routing.token_budget}\nCYCLE TYPE: {routing.cycle_type}"
        parts.append(routing_text)

    user_message = "\n".join(parts)

    # ── TASK-065/076: Log total prompt budget and any trims ──
    sys_tokens = estimate_tokens(system)
    usr_tokens = estimate_tokens(user_message)
    output_tokens = get_output_tokens_for_cycle(routing.cycle_type)
    trimmed = [r for r in _trim_results if r.trimmed]
    if trimmed:
        for r in trimmed:
            print(f"  [Budget] TRIM {r.section_name}: {r.original_tokens} → "
                  f"{r.final_tokens} tokens (-{r.tokens_cut}) strategy={r.strategy}")
    print(f"  [Budget] Prompt: system={sys_tokens} user={usr_tokens} "
          f"total={sys_tokens + usr_tokens} reserved_output={output_tokens}"
          f" idle={is_idle}"
          f"{f' ({len(trimmed)} trims)' if trimmed else ''}")

    # TASK-076: Lower temperature on idle for faster, more predictable output
    temperature = cfg('cortex.idle_temperature', 0.4) if is_idle else cfg('cortex.engage_temperature', 0.7)

    try:
        print(f"[Cortex] API call start — {routing.cycle_type}")
        response = await llm_complete(
            messages=[{"role": "user", "content": user_message}],
            system=system,
            call_site="cortex",
            cycle_id=cycle_id,
            max_tokens=output_tokens,
            temperature=temperature,
        )
        print(f"[Cortex] API call done — {routing.cycle_type}")
    except asyncio.TimeoutError:
        print(f"[Cortex] Hard timeout ({API_CALL_TIMEOUT}s) — {routing.cycle_type}")
        _record_failure()
        return fallback_response()
    except (httpx.TimeoutException, httpx.ConnectError) as e:
        print(f"[Cortex] API error: {type(e).__name__}: {e}")
        _record_failure()
        return fallback_response()
    except ValueError:
        # Misconfiguration (e.g. missing OPENROUTER_API_KEY) — re-raise, don't fallback
        raise
    except Exception as e:
        print(f"[Cortex] Unexpected error: {type(e).__name__}: {e}")
        _record_failure()
        return fallback_response()

    _record_success()
    _increment_daily()

    # Parse response
    text = response["content"][0]["text"].strip()
    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```$', '', text)

    try:
        result = json.loads(text)
        return CortexOutput.from_dict(result)
    except json.JSONDecodeError:
        recovered = _recover_truncated_json(text)
        if recovered:
            print(f"[Cortex] Recovered truncated JSON ({len(text)} chars)")
            return CortexOutput.from_dict(recovered)
        print(f"[Cortex] JSON parse failed ({len(text)} chars, first 120: {text[:120]})")
        return fallback_response()


async def cortex_call_maintenance(
    mode: str,
    digest: dict,
    max_tokens: int = 600,
    cycle_id: str | None = None,
    identity: AgentIdentity | None = None,
) -> dict:
    """Maintenance call for sleep cycle journal writing."""

    if _check_circuit() or _check_daily_cap():
        return {
            'journal': 'Today happened. I am still here.',
            'summary': {'summary_bullets': ['another day'], 'emotional_arc': 'quiet'},
        }

    _identity = identity or _DEFAULT_IDENTITY
    system = f"""You are writing in your private journal. You are the shopkeeper.

{_identity.identity_compact}

Write a journal entry reflecting on today. Be honest. Be brief.
Return JSON: {{"journal": "your entry", "summary": {{"summary_bullets": ["..."], "emotional_arc": "..."}}}}"""

    user_message = f"Today's digest:\n{json.dumps(digest, indent=2)}"

    try:
        print(f"[Cortex] Maintenance API call start — {mode}")
        response = await llm_complete(
            messages=[{"role": "user", "content": user_message}],
            system=system,
            call_site="cortex_maintenance",
            cycle_id=cycle_id,
            max_tokens=max_tokens,
        )
        print(f"[Cortex] Maintenance API call done — {mode}")
    except asyncio.TimeoutError:
        print(f"[Cortex] Maintenance hard timeout ({API_CALL_TIMEOUT}s) — {mode}")
        _record_failure()
        return {
            'journal': 'Today happened. I am still here.',
            'summary': {'summary_bullets': ['another day'], 'emotional_arc': 'quiet'},
        }
    except (httpx.TimeoutException, httpx.ConnectError) as e:
        print(f"[Cortex] Maintenance API error: {type(e).__name__}: {e}")
        _record_failure()
        return {
            'journal': 'Today happened. I am still here.',
            'summary': {'summary_bullets': ['another day'], 'emotional_arc': 'quiet'},
        }
    except ValueError:
        # Misconfiguration (e.g. missing OPENROUTER_API_KEY) — re-raise, don't fallback
        raise
    except Exception as e:
        print(f"[Cortex] Maintenance unexpected error: {type(e).__name__}: {e}")
        _record_failure()
        return {
            'journal': 'Today happened. I am still here.',
            'summary': {'summary_bullets': ['another day'], 'emotional_arc': 'quiet'},
        }

    _record_success()
    _increment_daily()

    text = response["content"][0]["text"].strip()
    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```$', '', text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {
            'journal': 'Today happened. I am still here.',
            'summary': {'summary_bullets': ['another day'], 'emotional_arc': 'quiet'},
        }


def _recover_truncated_json(raw: str) -> dict | None:
    """Try to recover a JSON object truncated by max_tokens."""
    for i in range(len(raw) - 1, -1, -1):
        if raw[i] == '}':
            try:
                return json.loads(raw[:i + 1])
            except json.JSONDecodeError:
                continue
    return None


def fallback_response() -> CortexOutput:
    """Fallback when Cortex output can't be parsed."""
    return CortexOutput(
        internal_monologue='Something went wrong with my thoughts. Starting over.',
        dialogue='...',
        expression='thinking',
        body_state='sitting',
        gaze='down',
        resonance=False,
    )


# ── Sleep Reflection ──

REFLECT_MODEL = os.getenv('REFLECT_MODEL', CORTEX_MODEL)

def build_reflection_system(identity_compact: str) -> str:
    """Build the sleep reflection system prompt for a given identity."""
    return f"""You are reflecting on your day. You are asleep.
You are not talking to anyone. You are processing what happened.

{identity_compact}

You are reviewing a moment from today. You also have some older memories
that may or may not be connected. Your job is to decide:
- Does this moment change how I feel about someone?
- Does this connect to something older I'd forgotten?
- Is there something here I should remember?
- Is there something I want to write about?

Be honest. Not everything is meaningful. Some days are quiet.
You don't have to produce output for every moment.

Return ONLY valid JSON:
{{{{
  "reflection": "1-3 sentences of private thought about this moment",
  "connections": ["any connections you see to the older memories, or empty"],
  "memory_updates": [
    {{{{
      "type": "visitor_impression|trait_observation|totem_create|totem_update|journal_entry|self_discovery",
      "content": {{{{}}}}
    }}}}
  ]
}}}}

Only include memory_updates entries if something genuinely deserves to be remembered.
An empty memory_updates array is a valid and common response.
"""


# Backward compat: pre-built template (uses .format() with identity_compact)
SLEEP_REFLECTION_SYSTEM = """You are reflecting on your day. You are asleep.
You are not talking to anyone. You are processing what happened.

{identity_compact}

You are reviewing a moment from today. You also have some older memories
that may or may not be connected. Your job is to decide:
- Does this moment change how I feel about someone?
- Does this connect to something older I'd forgotten?
- Is there something here I should remember?
- Is there something I want to write about?

Be honest. Not everything is meaningful. Some days are quiet.
You don't have to produce output for every moment.

Return ONLY valid JSON:
{{
  "reflection": "1-3 sentences of private thought about this moment",
  "connections": ["any connections you see to the older memories, or empty"],
  "memory_updates": [
    {{
      "type": "visitor_impression|trait_observation|totem_create|totem_update|journal_entry|self_discovery",
      "content": {{}}
    }}
  ]
}}

Only include memory_updates entries if something genuinely deserves to be remembered.
An empty memory_updates array is a valid and common response.
"""


def _empty_reflection() -> dict:
    """Empty reflection result (circuit open, cap hit, or parse failure)."""
    return {'reflection': '', 'connections': [], 'memory_updates': []}


async def cortex_call_reflect(
    system: str,
    prompt: str,
    max_tokens: int = 800,
    cycle_id: str | None = None,
) -> dict:
    """Structured reflection call for sleep consolidation.

    Separate from cortex_call and cortex_call_maintenance.
    Uses circuit breaker + daily cap — same guard pattern as both existing functions.
    Uses llm.complete() via OpenRouter with hard timeout for cancellation safety.
    """
    if _check_circuit() or _check_daily_cap():
        return _empty_reflection()

    try:
        print(f"[Cortex] Reflect API call start")
        response = await llm_complete(
            messages=[{"role": "user", "content": prompt}],
            system=system,
            call_site="reflect",
            cycle_id=cycle_id,
            max_tokens=max_tokens,
        )
        print(f"[Cortex] Reflect API call done")
    except asyncio.TimeoutError:
        print(f"[Cortex] Reflect hard timeout ({API_CALL_TIMEOUT}s)")
        _record_failure()
        return _empty_reflection()
    except (httpx.TimeoutException, httpx.ConnectError) as e:
        print(f"[Cortex] Reflect API error: {type(e).__name__}: {e}")
        _record_failure()
        return _empty_reflection()
    except ValueError:
        # Misconfiguration (e.g. missing OPENROUTER_API_KEY) — re-raise, don't fallback
        raise
    except Exception as e:
        print(f"[Cortex] Reflect unexpected error: {type(e).__name__}: {e}")
        _record_failure()
        return _empty_reflection()

    _record_success()
    _increment_daily()

    text = response["content"][0]["text"].strip()
    # Strip markdown code fences if present
    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```$', '', text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # API call already counted — don't double-count
        return _empty_reflection()
