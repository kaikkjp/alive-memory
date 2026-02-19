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

import clock
from models.event import Event
from models.pipeline import (
    ValidatedOutput, ActionRequest, MotorPlan,
    ActionResult, BodyOutput,
)
from pipeline.hypothalamus import apply_expression_relief
from body import dispatch_action
from body.internal import END_ENGAGEMENT_LINES  # noqa: F401 — backward compat
import db


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
                'language': validated.dialogue_language,
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
    for decision in motor_plan.actions:
        # Use detail dict carried on ActionDecision (set by basal_ganglia)
        action_req = ActionRequest(type=decision.action, detail=decision.detail)
        result = await dispatch_action(action_req, visitor_id, monologue=monologue)
        if result.payload.get('body_state_update'):
            validated.body_state = result.payload['body_state_update']
        output.executed.append(result)

    return output
