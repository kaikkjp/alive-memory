"""Cortex — THE LLM INTERFACE. Claude Sonnet for cycles, reflection for sleep."""

import asyncio
import json
import os
import re
import time
import anthropic
import httpx
from datetime import datetime, timezone
import clock
from models.state import DrivesState, Visitor
from models.pipeline import CortexOutput
from pipeline.thalamus import RoutingDecision
from pipeline.sensorium import Perception
from pipeline.hypothalamus import drives_to_feeling
from config.identity import IDENTITY_COMPACT, VOICE_CHECKSUM
import db
import llm_logger

CORTEX_MODEL = "claude-sonnet-4-5-20250929"
API_CALL_TIMEOUT = 60.0  # Hard timeout per request (seconds)

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


# ── Singleton Async Client ──

_client: anthropic.AsyncAnthropic | None = None


def _get_client() -> anthropic.AsyncAnthropic:
    """Return a reused async Anthropic client.

    Uses AsyncAnthropic so that ``await client.messages.create(...)`` is a
    true coroutine — ``asyncio.wait_for`` can cancel the underlying httpx
    request on timeout instead of leaving an orphaned worker thread.
    """
    global _client
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set. Export it before running: "
            "export ANTHROPIC_API_KEY='sk-ant-...'"
        )
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=api_key, timeout=30.0)
    return _client


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
- You carry threads — ongoing thoughts, questions, projects. Use thread_create when something new sticks. Use thread_update to revisit. Use thread_close when resolved.
- When consuming content (reading, listening), reflect honestly. Add to collection only if it genuinely resonates. Create totems for things that lodge in you.
- Threads are yours. Don't create threads just because a visitor mentioned something — only if it genuinely stays with you.

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
      "type": "visitor_impression",
      "content": {{"summary": "one-line impression of this visitor", "emotional_imprint": "how they make you feel"}}
    }},
    {{
      "type": "trait_observation",
      "content": {{"trait_category": "taste|personality|topic|relationship", "trait_key": "short label", "trait_value": "what you observed"}}
    }},
    {{
      "type": "totem_create|totem_update|journal_entry|self_discovery|collection_add",
      "content": {{}}
    }},
    {{
      "type": "thread_create",
      "content": {{"thread_type": "question|project|anticipation|unresolved|ritual", "title": "short title", "priority": 0.5, "initial_thought": "what you're thinking about this", "tags": []}}
    }},
    {{
      "type": "thread_update",
      "content": {{"thread_id": "id or null", "title": "title if no id", "content": "updated thinking", "reason": "why you're revisiting this"}}
    }},
    {{
      "type": "thread_close",
      "content": {{"thread_id": "id or null", "title": "title if no id", "resolution": "how this resolved"}}
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
) -> CortexOutput:
    """The one LLM call. Build prompt pack, call model, return structured response."""

    client = _get_client()

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

    # Active threads (inner agenda)
    active_threads = await db.get_active_threads(limit=3)
    if active_threads:
        parts.append("\nTHINGS ON MY MIND:")
        for t in active_threads:
            age_str = ""
            if t.created_at:
                age_days = (clock.now_utc() - t.created_at).days
                age_str = f" ({age_days}d old)" if age_days > 0 else " (new)"
            snippet = f" — {t.content[:80]}..." if t.content and len(t.content) > 80 else (f" — {t.content}" if t.content else "")
            parts.append(f"  [{t.thread_type}] {t.title} [id:{t.id}]{age_str}{snippet}")

    # Consume framing (when arbiter picked consume focus)
    consume_perception = next(
        (p for p in perceptions if p.features.get('is_consumption')), None
    )
    if consume_perception:
        parts.append("\nWHAT I'M CONSUMING:")
        parts.append(f"  {consume_perception.content}")
        if consume_perception.features.get('url'):
            parts.append(f"  Source: {consume_perception.features['url']}")
        if consume_perception.features.get('readable_text'):
            text_preview = consume_perception.features['readable_text'][:2000]
            parts.append(f"  Content:\n{text_preview}")
        parts.append("  → React honestly. Add to collection if it resonates. Create a totem if it lodges.")

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
        print(f"[Cortex] API call start — {routing.cycle_type}")
        response = await asyncio.wait_for(
            client.messages.create(
                model=CORTEX_MODEL,
                max_tokens=1500,
                system=system,
                messages=[{"role": "user", "content": user_message}],
            ),
            timeout=API_CALL_TIMEOUT,
        )
        print(f"[Cortex] API call done — {routing.cycle_type}")
    except asyncio.TimeoutError:
        print(f"[Cortex] Hard timeout ({API_CALL_TIMEOUT}s) — {routing.cycle_type}")
        _record_failure()
        return fallback_response()
    except (anthropic.APIError, httpx.TimeoutException) as e:
        print(f"[Cortex] API error: {type(e).__name__}: {e}")
        _record_failure()
        return fallback_response()
    except Exception as e:
        print(f"[Cortex] Unexpected error: {type(e).__name__}: {e}")
        _record_failure()
        return fallback_response()

    _record_success()
    _increment_daily()

    # Log LLM call for cost tracking
    usage = response.usage
    await llm_logger.log_llm_call(
        provider='anthropic',
        model=CORTEX_MODEL,
        purpose='cortex',
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cycle_id=routing.cycle_id if hasattr(routing, 'cycle_id') else None,
    )

    # Parse response
    text = response.content[0].text.strip()
    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```$', '', text)

    try:
        result = json.loads(text)
        return CortexOutput.from_dict(result)
    except json.JSONDecodeError:
        return fallback_response()


async def cortex_call_maintenance(mode: str, digest: dict, max_tokens: int = 600) -> dict:
    """Maintenance call for sleep cycle journal writing."""

    client = _get_client()

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
        print(f"[Cortex] Maintenance API call start — {mode}")
        response = await asyncio.wait_for(
            client.messages.create(
                model=CORTEX_MODEL,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user_message}],
            ),
            timeout=API_CALL_TIMEOUT,
        )
        print(f"[Cortex] Maintenance API call done — {mode}")
    except asyncio.TimeoutError:
        print(f"[Cortex] Maintenance hard timeout ({API_CALL_TIMEOUT}s) — {mode}")
        _record_failure()
        return {
            'journal': 'Today happened. I am still here.',
            'summary': {'summary_bullets': ['another day'], 'emotional_arc': 'quiet'},
        }
    except (anthropic.APIError, httpx.TimeoutException) as e:
        print(f"[Cortex] Maintenance API error: {type(e).__name__}: {e}")
        _record_failure()
        return {
            'journal': 'Today happened. I am still here.',
            'summary': {'summary_bullets': ['another day'], 'emotional_arc': 'quiet'},
        }
    except Exception as e:
        print(f"[Cortex] Maintenance unexpected error: {type(e).__name__}: {e}")
        _record_failure()
        return {
            'journal': 'Today happened. I am still here.',
            'summary': {'summary_bullets': ['another day'], 'emotional_arc': 'quiet'},
        }

    _record_success()
    _increment_daily()

    # Log LLM call for cost tracking
    usage = response.usage
    await llm_logger.log_llm_call(
        provider='anthropic',
        model=CORTEX_MODEL,
        purpose='cortex_maintenance',
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
    )

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


def fallback_response() -> CortexOutput:
    """Fallback when Cortex output can't be parsed."""
    return CortexOutput(
        internal_monologue='Something went wrong with my thoughts. Starting over.',
        dialogue='...',
        dialogue_language='en',
        expression='thinking',
        body_state='sitting',
        gaze='down',
        resonance=False,
    )


# ── Sleep Reflection ──

REFLECT_MODEL = os.getenv('REFLECT_MODEL', CORTEX_MODEL)

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


async def cortex_call_reflect(system: str, prompt: str, max_tokens: int = 800) -> dict:
    """Structured reflection call for sleep consolidation.

    Separate from cortex_call and cortex_call_maintenance.
    Uses circuit breaker + daily cap — same guard pattern as both existing functions.
    Uses shared AsyncAnthropic singleton + hard timeout for cancellation safety.
    """
    if _check_circuit() or _check_daily_cap():
        return _empty_reflection()

    client = _get_client()

    try:
        print(f"[Cortex] Reflect API call start")
        response = await asyncio.wait_for(
            client.messages.create(
                model=REFLECT_MODEL,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            ),
            timeout=API_CALL_TIMEOUT,
        )
        print(f"[Cortex] Reflect API call done")
    except asyncio.TimeoutError:
        print(f"[Cortex] Reflect hard timeout ({API_CALL_TIMEOUT}s)")
        _record_failure()
        return _empty_reflection()
    except (anthropic.APIError, httpx.TimeoutException) as e:
        print(f"[Cortex] Reflect API error: {type(e).__name__}: {e}")
        _record_failure()
        return _empty_reflection()
    except Exception as e:
        print(f"[Cortex] Reflect unexpected error: {type(e).__name__}: {e}")
        _record_failure()
        return _empty_reflection()

    _record_success()
    _increment_daily()

    text = response.content[0].text.strip()
    # Strip markdown code fences if present
    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```$', '', text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # API call already counted — don't double-count
        return _empty_reflection()
