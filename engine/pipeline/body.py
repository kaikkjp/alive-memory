"""Body — execute approved actions, emit events, write text fragments.

Position: after Basal Ganglia.
Question it answers: "Can I physically do this, and what happened when I tried?"

The Body is thin. It receives approved actions from the MotorPlan and executes them.
It does NOT decide. It does NOT inhibit. It does NOT prioritize.
All of that already happened in the brain (Basal Ganglia).

Dialogue/monologue/body_state event emissions are body actions — they live here
permanently. Memory consolidation, pool updates, drive adjustments, and engagement
state updates live in output.py.

Individual action handlers live in the body/ package (body/internal.py for
existing actions, body/web.py, body/x_social.py, body/telegram.py for external).
"""

import re
from datetime import datetime, timezone

import clock
from models.event import Event
from models.pipeline import (
    ValidatedOutput, ActionRequest, MotorPlan,
    ActionResult, BodyOutput,
)
from pipeline.hypothalamus import apply_expression_relief
from pipeline.basal_ganglia import report_action_failure, report_action_success
from body import dispatch_action
from body.internal import END_ENGAGEMENT_LINES  # noqa: F401 — backward compat
import db
from runtime_context import hash_text


# ── TASK-075: Error-to-perception translation ──
# Raw exception strings must NEVER reach cortex. Body translates technical
# errors into character-aligned descriptions suitable for perception injection.
_ERROR_TRANSLATIONS: dict[str, str] = {
    'timeout': 'A wave of mental fatigue washes over you. The effort to reach out fizzled.',
    'rate_limit': 'You feel overstimulated — too many attempts, too fast. Rest would help.',
    'connection': 'Something feels disconnected. The world beyond feels unreachable right now.',
    'auth': 'A door you expected to be open feels locked. Something changed.',
    'server': 'The world outside feels unresponsive, like shouting into fog.',
}

# Default when no specific pattern matches
_ERROR_FALLBACK = 'A subtle resistance. Something you tried to do didn\'t work.'


def translate_error_to_perception(error_str: str | None) -> str:
    """Translate a raw error string into a character-aligned perception.

    Never exposes raw exception types, HTTP codes, or stack traces.
    """
    if not error_str:
        return _ERROR_FALLBACK
    lowered = error_str.lower()
    for key, translation in _ERROR_TRANSLATIONS.items():
        if key in lowered:
            return translation
    return _ERROR_FALLBACK


_RECALL_STOPWORDS = {
    'about', 'after', 'before', 'being', 'could', 'first', 'from', 'have',
    'into', 'just', 'like', 'more', 'that', 'their', 'there', 'these',
    'they', 'this', 'what', 'when', 'where', 'which', 'with', 'would',
}


def _tokenize_words(text: str | None) -> set[str]:
    if not text:
        return set()
    parts = re.split(r'[^a-zA-Z0-9_]+', text.lower())
    return {p for p in parts if len(p) >= 4 and p not in _RECALL_STOPWORDS}


def _as_utc_datetime(value: datetime | str | None) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        try:
            dt = datetime.fromisoformat(raw.replace('Z', '+00:00'))
        except ValueError:
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return None


async def _log_recall_probe(visitor_id: str, dialogue: str, cycle_id: str | None) -> None:
    """Best-effort delayed-recall test logging from live dialogue turns."""
    try:
        convo = await db.get_recent_conversation(visitor_id, limit=8)
        question = ''
        for row in reversed(convo):
            if row.get('role') == 'visitor' and '?' in (row.get('text') or ''):
                question = row.get('text') or ''
                break
        if not question:
            return

        traits = await db.get_visitor_traits(visitor_id, limit=30)
        if not traits:
            return

        answer_tokens = _tokenize_words(dialogue)
        if not answer_tokens:
            return

        best = None
        best_score = 0.0
        best_shared = 0
        best_fact_token_count = 0
        for trait in traits:
            fact_tokens = _tokenize_words(f"{trait.trait_key} {trait.trait_value}")
            if not fact_tokens:
                continue
            shared_count = len(answer_tokens & fact_tokens)
            overlap = shared_count / max(len(fact_tokens), 1)
            if overlap > best_score or (overlap == best_score and shared_count > best_shared):
                best_score = overlap
                best_shared = shared_count
                best_fact_token_count = len(fact_tokens)
                best = trait

        if not best:
            return

        min_shared = 1 if best_fact_token_count <= 2 else 2
        min_overlap = 0.5 if best_fact_token_count <= 2 else 0.35
        retrieved = best_shared >= min_shared and best_score >= min_overlap

        observed_at = _as_utc_datetime(getattr(best, 'observed_at', None))
        horizon = 0
        if observed_at:
            horizon = int(max((clock.now_utc() - observed_at).total_seconds(), 0) // 3600)

        question_id = f"{visitor_id}:{hash_text(question)[:12]}:{int(clock.now_utc().timestamp())}"
        await db.log_recall_test(
            question_id=question_id,
            fact_id=best.id,
            retrieved=retrieved,
            answer_correctness_score=round(best_score, 3),
            used_in_answer=retrieved,
            horizon_hours=max(horizon, 0),
            cycle_id=cycle_id,
            payload={
                'visitor_id': visitor_id,
                'question_hash': hash_text(question),
                'answer_hash': hash_text(dialogue),
            },
        )
    except Exception as e:
        # Recall probing is observability-only and must never break body execution.
        print(f"  [RecallProbe] logging skipped: {type(e).__name__}: {e}")
        return


async def _execute_single_action(action: ActionRequest, visitor_id: str,
                                 monologue: str = '') -> ActionResult:
    """Backward-compat wrapper — delegates to body/executor dispatch."""
    return await dispatch_action(action, visitor_id, monologue)


async def execute_body(motor_plan: MotorPlan, validated: ValidatedOutput,
                       visitor_id: str = None, cycle_id: str = None) -> BodyOutput:
    """Execute approved actions from the motor plan. Emit events. Write text fragments.

    This is the body's work: dialogue emission, body state broadcast, and
    individual action execution. Post-action side effects (memory, drives,
    engagement) are handled by output.py.
    """
    output = BodyOutput()

    # ── Emit dialogue ──
    dialogue = validated.dialogue
    if dialogue and dialogue != '...':
        event = Event(
            event_type='action_speak',
            source='self',
            payload={
                'text': dialogue,
                'language': 'en',
                'target': visitor_id,
            },
        )
        await db.append_event(event)
        output.events_emitted += 1

        # Immediate drive relief — she spoke, expression need drops
        await apply_expression_relief('action_speak')

        # Log to conversation
        if visitor_id:
            await db.append_conversation(visitor_id, 'shopkeeper', dialogue)
            await _log_recall_probe(visitor_id, dialogue, cycle_id=cycle_id)

        # Write text fragment for window display
        frag_type = 'response' if visitor_id else 'thought'
        try:
            await db.insert_text_fragment(
                content=dialogue,
                fragment_type=frag_type,
                cycle_id=cycle_id,
                visitor_id=visitor_id,
            )
        except Exception as e:
            print(f"  [TextFragment] Failed to write dialogue fragment: {e}")

    # Write internal monologue as thought fragment (if no dialogue)
    monologue = validated.internal_monologue
    if monologue and not (dialogue and dialogue != '...'):
        try:
            await db.insert_text_fragment(
                content=monologue,
                fragment_type='thought',
                cycle_id=cycle_id,
            )
        except Exception as e:
            print(f"  [TextFragment] Failed to write thought fragment: {e}")

    # ── Emit body state ──
    body_event = Event(
        event_type='action_body',
        source='self',
        payload={
            'expression': validated.expression,
            'body_state': validated.body_state,
            'gaze': validated.gaze,
        },
    )
    await db.append_event(body_event)
    output.events_emitted += 1

    # ── Execute approved actions from motor plan ──
    # Cognitive primitives (idle, express_thought) are internal signals with
    # no executor — skip them to avoid false failure noise.
    _SKIP_DISPATCH = frozenset({'idle', 'express_thought'})

    for decision in motor_plan.actions:
        if decision.action in _SKIP_DISPATCH:
            continue

        # Use detail dict carried on ActionDecision (set by basal_ganglia)
        action_req = ActionRequest(type=decision.action, detail=decision.detail)
        result = await dispatch_action(action_req, visitor_id, monologue=monologue)
        if result.payload.get('body_state_update'):
            validated.body_state = result.payload['body_state_update']

        # TASK-075: Report success/failure to circuit breaker
        if result.success:
            report_action_success(decision.action)
        else:
            report_action_failure(decision.action)
            # Sanitize error — never let raw exceptions reach cortex
            if result.error:
                result.error = translate_error_to_perception(result.error)

        output.executed.append(result)

    return output
