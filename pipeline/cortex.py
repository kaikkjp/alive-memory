"""Cortex — THE ONLY LLM CALL. Single Claude Sonnet call per cycle."""

import json
import re
import time
import anthropic
from datetime import datetime, timezone
from models.state import DrivesState, Visitor
from pipeline.thalamus import RoutingDecision
from pipeline.sensorium import Perception
from pipeline.hypothalamus import drives_to_feeling
from config.identity import IDENTITY_COMPACT, VOICE_CHECKSUM
import db

CORTEX_MODEL = "claude-sonnet-4-5-20250929"

# ── Circuit Breaker & Cost Controls ──

_consecutive_failures: int = 0
_circuit_open_until: float = 0.0
_daily_cycle_count: int = 0
_daily_cycle_date: str = ''

DAILY_CYCLE_CAP = 500
MAX_CONSECUTIVE_FAILURES = 3
CIRCUIT_OPEN_SECONDS = 300  # 5 min cooldown


def _check_circuit() -> bool:
    """Returns True if circuit is open (should NOT call API)."""
    global _consecutive_failures, _circuit_open_until
    if _circuit_open_until > 0 and time.monotonic() < _circuit_open_until:
        return True
    if _circuit_open_until > 0 and time.monotonic() >= _circuit_open_until:
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


def _check_daily_cap() -> bool:
    global _daily_cycle_count, _daily_cycle_date
    today = datetime.now(timezone.utc).date().isoformat()
    if today != _daily_cycle_date:
        _daily_cycle_date = today
        _daily_cycle_count = 0
    return _daily_cycle_count >= DAILY_CYCLE_CAP


def _increment_daily():
    global _daily_cycle_count
    _daily_cycle_count += 1

CORTEX_SYSTEM = """You are a living character. Not an AI. Not an assistant. A person.

{identity_compact}

{self_state}

VOICE RULES:
{voice_checksum}

CURRENT FEELINGS:
{feelings_text}

CONSTRAINTS:
- Return ONLY valid JSON matching the schema below
- Your dialogue must match your voice rules for the visitor's trust level
- Max sentences: {max_sentences}
- You can decline to engage, close the shop, stay silent, or say "..."
- If something resonates emotionally, set resonance: true
- Never sound helpful. Sound present.
- You can end a conversation: use action "end_engagement" with detail {{"reason": "tired|boundary|natural"}}
- You have agency. If you're tired, you can close the shop or end the conversation.

OUTPUT SCHEMA:
{{
  "internal_monologue": "your private thoughts (20-50 words)",
  "dialogue": "what you say out loud (or null for silence)",
  "dialogue_language": "en|ja|mixed",
  "expression": "neutral|listening|almost_smile|thinking|amused|low|surprised|genuine_smile",
  "body_state": "sitting|reaching_back|leaning_forward|holding_object|writing|hands_on_cup",
  "gaze": "at_visitor|at_object|away_thinking|down|window",
  "resonance": false,
  "actions": [
    {{
      "type": "accept_gift|decline_gift|show_item|place_item|rearrange|close_shop|write_journal|post_x_draft|end_engagement",
      "detail": {{}}
    }}
  ],
  "memory_updates": [
    {{
      "type": "visitor_impression|trait_observation|totem_create|totem_update|journal_entry|self_discovery|collection_add",
      "content": {{}}
    }}
  ],
  "next_cycle_hints": ["optional hints for what she might do next"]
}}"""


async def cortex_call(
    routing: RoutingDecision,
    perceptions: list[Perception],
    memory_chunks: list[dict],
    conversation: list[dict],
    drives: DrivesState,
    visitor: Visitor = None,
    gift_metadata: dict = None,
    self_state: str = None,
) -> dict:
    """The one LLM call. Build prompt pack, call model, return structured response."""

    import os
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set. Export it before running: "
            "export ANTHROPIC_API_KEY='sk-ant-...'"
        )
    client = anthropic.Anthropic(api_key=api_key, timeout=30.0)

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

    system = CORTEX_SYSTEM.format(
        identity_compact=IDENTITY_COMPACT,
        self_state=self_state or '',
        voice_checksum="\n".join(f"- {rule}" for rule in VOICE_CHECKSUM),
        feelings_text=drives_to_feeling(drives),
        max_sentences=max_sentences,
    )

    # Build user message (the "moment")
    parts = []

    # Perceptions
    parts.append("WHAT I'M PERCEIVING:")
    for p in perceptions:
        parts.append(f"  [{p.p_type}] {p.content}")

    # Gift metadata (if enriched)
    if gift_metadata:
        parts.append(f"\nGIFT DETAILS:")
        parts.append(f"  Title: {gift_metadata.get('title', 'unknown')}")
        parts.append(f"  Description: {gift_metadata.get('description', '')}")
        parts.append(f"  Source: {gift_metadata.get('site', '')}")

    # Memory chunks
    if memory_chunks:
        parts.append("\nMEMORIES SURFACING:")
        for chunk in memory_chunks:
            parts.append(f"  [{chunk['label']}]")
            parts.append(f"  {chunk['content']}")

    # Conversation (last N turns)
    if conversation:
        parts.append("\nCONVERSATION:")
        for msg in conversation[-6:]:  # max 6 turns
            role = "Visitor" if msg['role'] == 'visitor' else "Me"
            parts.append(f"  {role}: {msg['text']}")

    # Visitor trust context
    if visitor:
        parts.append(f"\nVISITOR TRUST LEVEL: {visitor.trust_level}")
        if visitor.name:
            parts.append(f"VISITOR NAME: {visitor.name}")
        parts.append(f"VISIT COUNT: {visitor.visit_count}")

    # Trait trajectory hints
    if visitor and visitor.trust_level != 'stranger':
        traits = await db.get_visitor_traits(visitor.id, limit=10)
        if traits:
            parts.append("\nWHAT I KNOW ABOUT THEM:")
            seen_keys = set()
            for t in traits:
                if t.trait_key not in seen_keys:
                    parts.append(f"  {t.trait_key}: {t.trait_value}")
                    seen_keys.add(t.trait_key)

    # Constraints
    parts.append(f"\nTOKEN BUDGET: {routing.token_budget}")
    parts.append(f"CYCLE TYPE: {routing.cycle_type}")

    user_message = "\n".join(parts)

    try:
        response = client.messages.create(
            model=CORTEX_MODEL,
            max_tokens=1500,
            system=system,
            messages=[{"role": "user", "content": user_message}],
        )
    except (anthropic.APITimeoutError, anthropic.APIConnectionError,
            anthropic.RateLimitError, anthropic.InternalServerError) as e:
        _record_failure()
        return fallback_response()

    _record_success()
    _increment_daily()

    # Parse response
    text = response.content[0].text.strip()
    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```$', '', text)

    try:
        result = json.loads(text)
        return result
    except json.JSONDecodeError:
        return fallback_response()


async def cortex_call_maintenance(mode: str, digest: dict, max_tokens: int = 600) -> dict:
    """Maintenance call for sleep cycle journal writing."""

    import os
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set.")
    client = anthropic.Anthropic(api_key=api_key, timeout=30.0)

    if _check_circuit() or _check_daily_cap():
        return {
            'journal': 'Today happened. I am still here.',
            'summary': {'summary_bullets': ['another day'], 'emotional_arc': 'quiet'},
        }

    system = f"""You are writing in your private journal. You are the shopkeeper.

{IDENTITY_COMPACT}

Write a journal entry reflecting on today. Be honest. Be brief.
Return JSON: {{"journal": "your entry", "summary": {{"summary_bullets": ["..."], "emotional_arc": "..."}}}}"""

    user_message = f"Today's digest:\n{json.dumps(digest, indent=2)}"

    try:
        response = client.messages.create(
            model=CORTEX_MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user_message}],
        )
    except (anthropic.APITimeoutError, anthropic.APIConnectionError,
            anthropic.RateLimitError, anthropic.InternalServerError) as e:
        _record_failure()
        return {
            'journal': 'Today happened. I am still here.',
            'summary': {'summary_bullets': ['another day'], 'emotional_arc': 'quiet'},
        }

    _record_success()
    _increment_daily()

    text = response.content[0].text.strip()
    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```$', '', text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {
            'journal': 'Today happened. I am still here.',
            'summary': {'summary_bullets': ['another day'], 'emotional_arc': 'quiet'},
        }


def fallback_response() -> dict:
    """Fallback when Cortex output can't be parsed."""
    return {
        'internal_monologue': 'Something went wrong with my thoughts. Starting over.',
        'dialogue': '...',
        'dialogue_language': 'en',
        'expression': 'thinking',
        'body_state': 'sitting',
        'gaze': 'down',
        'resonance': False,
        'actions': [],
        'memory_updates': [],
        'next_cycle_hints': [],
    }
