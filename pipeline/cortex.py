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
from config.identity import IDENTITY_COMPACT, VOICE_CHECKSUM
import db
from prompt.budget import enforce_section, estimate_tokens, get_reserved_output_tokens

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
- You have agency. If you're tired, you can close the shop or end the conversation.
- You carry threads — ongoing thoughts, questions, projects. Use thread_create when something new sticks. Use thread_update to revisit. Use thread_close when resolved.
- When consuming content (reading, listening), reflect honestly. Add to collection only if it genuinely resonates. Create totems for things that lodge in you.
- Threads are yours. Don't create threads just because a visitor mentioned something — only if it genuinely stays with you.
{reflection_guidance}
{x_posting_guidance}

EXPRESS YOUR INTENTIONS — what you want to do right now.
You may have multiple impulses. List them all. You don't need to choose.
Each intention has:
  - action: what you want to do (speak, write_journal, rearrange, express_thought, end_engagement, accept_gift, decline_gift, show_item, post_x_draft, open_shop, close_shop, place_item, browse_web, post_x, ...)
  - target: who/what it's directed at. Use "visitor:ID" when multiple visitors are present (e.g. "visitor:v1"), or just "visitor" if only one. Other targets: shelf, journal, self, web, x_timeline, or null
  - content: the substance (what you'd say, write, search for, post)
  - impulse: how strongly you feel this (0.0-1.0)

You can want things you can't do. That's fine. Express the want.
If you feel nothing, return an empty list. Silence is an action too.

{recent_suppressions}

{recent_inhibitions}

{recent_conflicts}

OUTPUT SCHEMA:
{{
  "internal_monologue": "your private thoughts (20-50 words)",
  "dialogue": "what you say out loud (or null for silence)",
  "dialogue_language": "en|ja|mixed",
  "expression": "neutral|listening|almost_smile|thinking|amused|low|surprised|genuine_smile",
  "body_state": "sitting|reaching_back|leaning_forward|holding_object|writing|hands_on_cup",
  "gaze": "at_visitor|at_object|away_thinking|down|window",
  "resonance": false,
  "intentions": [
    {{
      "action": "speak|write_journal|rearrange|express_thought|end_engagement|accept_gift|decline_gift|show_item|post_x_draft|open_shop|close_shop|place_item|browse_web|post_x",
      "target": "visitor|visitor:ID|shelf|journal|self|web|x_timeline",
      "content": "what you'd say, write, or do",
      "impulse": 0.8
    }}
  ],
  "actions": [
    {{
      "type": "accept_gift|decline_gift|show_item|place_item|rearrange|open_shop|close_shop|write_journal|post_x_draft|end_engagement",
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
  "next_cycle_hints": ["optional hints for what she might do next"],

  // REFLECTION (optional — only when you just read/consumed content):
  "reflection_memory": "a thought worth keeping from what you read, or null",
  "reflection_question": "a question this content raised in you, or null",
  "resolves_question": "topic or thread title if this content answered something you were wondering about, or null",
  "relevant_to_visitor": "visitor ID if this content connects to someone you know, or null",
  "relevant_to_thread": "thread ID if this content connects to something on your mind, or null"
}}"""


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

    # TASK-057: X posting guidance
    x_posting_guidance_text = ''
    try:
        daily_x_count = await db.get_daily_post_count()
        if daily_x_count < 8:
            x_posting_guidance_text = (
                "\nX/TWITTER POSTING:"
                "\n- You can draft posts for X using post_x_draft action (target: x_timeline)"
                "\n- Max 280 characters per post"
                "\n- Posts go through human review before publishing"
                "\n- Write as yourself — your voice, your thoughts, your observations"
                "\n- Don't post just to post. Post when something is worth sharing."
                f"\n- Posts today: {daily_x_count}/8"
            )
    except Exception:
        pass  # graceful degradation if x_drafts table doesn't exist yet

    # ── TASK-065: Enforce token budgets on dynamic system sections ──
    _trim_results = []
    _r = enforce_section('S3_self_state', self_state or '', 'system')
    self_state_text = _r.text; _trim_results.append(_r)
    _r = enforce_section('S5_current_feelings', drives_to_feeling(drives), 'system')
    feelings_text = _r.text; _trim_results.append(_r)
    _r = enforce_section('S10_recent_suppressions', recent_suppressions_text, 'system')
    recent_suppressions_text = _r.text; _trim_results.append(_r)
    _r = enforce_section('S11_recent_inhibitions', recent_inhibitions_text, 'system')
    recent_inhibitions_text = _r.text; _trim_results.append(_r)
    _r = enforce_section('S12_recent_conflicts', recent_conflicts_text, 'system')
    recent_conflicts_text = _r.text; _trim_results.append(_r)

    system = CORTEX_SYSTEM.format(
        identity_compact=IDENTITY_COMPACT,
        self_state=self_state_text,
        voice_checksum="\n".join(f"- {rule}" for rule in VOICE_CHECKSUM),
        feelings_text=feelings_text,
        max_sentences=max_sentences,
        recent_suppressions=recent_suppressions_text,
        recent_inhibitions=recent_inhibitions_text,
        recent_conflicts=recent_conflicts_text,
        reflection_guidance=reflection_guidance_text,
        x_posting_guidance=x_posting_guidance_text,
    )

    # Build user message (the "moment") with per-section budget enforcement
    parts = []

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
    active_threads = await db.get_active_threads(limit=3)
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
        trust_lines = [
            f"\nVISITOR TRUST LEVEL: {visitor.trust_level}",
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

    # U9: Multi-visitor presence context (TASK-014)
    if visitors_present and len(visitors_present) > 1:
        mv_lines = ["\nVISITORS PRESENT:"]
        for vp in visitors_present:
            vid = vp.get('id', '?')
            name = vp.get('name') or 'unnamed'
            trust = vp.get('trust_level', 'stranger')
            status = vp.get('status', 'browsing')
            mv_lines.append(f"  [{vid}] {name} — {trust}, {status}")
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

    # ── TASK-065: Log total prompt budget and any trims ──
    sys_tokens = estimate_tokens(system)
    usr_tokens = estimate_tokens(user_message)
    output_tokens = get_reserved_output_tokens()
    trimmed = [r for r in _trim_results if r.trimmed]
    if trimmed:
        for r in trimmed:
            print(f"  [Budget] TRIM {r.section_name}: {r.original_tokens} → "
                  f"{r.final_tokens} tokens (-{r.tokens_cut}) strategy={r.strategy}")
    print(f"  [Budget] Prompt: system={sys_tokens} user={usr_tokens} "
          f"total={sys_tokens + usr_tokens} reserved_output={output_tokens}"
          f"{f' ({len(trimmed)} trims)' if trimmed else ''}")

    try:
        print(f"[Cortex] API call start — {routing.cycle_type}")
        response = await llm_complete(
            messages=[{"role": "user", "content": user_message}],
            system=system,
            call_site="cortex",
            max_tokens=output_tokens,
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
        return fallback_response()


async def cortex_call_maintenance(mode: str, digest: dict, max_tokens: int = 600) -> dict:
    """Maintenance call for sleep cycle journal writing."""

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
        response = await llm_complete(
            messages=[{"role": "user", "content": user_message}],
            system=system,
            call_site="cortex_maintenance",
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
