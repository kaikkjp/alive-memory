"""Body executor dispatcher — routes action names to executor functions.

All executors are registered via the @register decorator.  The dispatcher
looks up the action name, calls the matching executor, and falls back to
the dynamic body_state handler for actions from the dynamic_actions table.
"""

from __future__ import annotations

import json
from typing import Callable, Awaitable

import clock
from models.pipeline import ActionRequest, ActionResult
from models.event import Event
import db

# ── Registry ──

EXECUTORS: dict[str, Callable[..., Awaitable[ActionResult]]] = {}


def register(name: str):
    """Decorator: register an async function as the executor for *name*."""
    def wrapper(fn: Callable[..., Awaitable[ActionResult]]):
        EXECUTORS[name] = fn
        return fn
    return wrapper


async def dispatch_action(action: ActionRequest, visitor_id: str = None,
                          monologue: str = '') -> ActionResult:
    """Dispatch a single approved action to the matching executor.

    Falls back to the dynamic body_state handler when the action carries
    a ``_body_state_update`` key in its detail dict (set by basal_ganglia
    for dynamic-action resolutions).

    Returns an ActionResult in all cases — never raises.
    """
    executor = EXECUTORS.get(action.type)
    if executor:
        try:
            return await executor(action, visitor_id, monologue)
        except Exception as e:
            return ActionResult(
                action=action.type,
                success=False,
                error=f"{type(e).__name__}: {e}",
                timestamp=clock.now_utc(),
            )

    # Fallback: dynamic body_state actions (from dynamic_actions table)
    detail = action.detail
    if '_body_state_update' in detail:
        return await _handle_body_state(action)

    # Unknown action — nothing to execute
    return ActionResult(
        action=action.type,
        success=False,
        error=f'no executor for {action.type}',
        timestamp=clock.now_utc(),
    )


async def _handle_body_state(action: ActionRequest) -> ActionResult:
    """Execute a dynamic body_state action."""
    result = ActionResult(action=action.type, timestamp=clock.now_utc())
    try:
        state_update = json.loads(action.detail['_body_state_update'])
        if not isinstance(state_update, dict):
            result.success = False
            result.error = 'body_state_update must be a JSON object'
        else:
            await db.append_event(Event(
                event_type='action_body',
                source='self',
                payload=state_update,
            ))
            result.payload = state_update
            if 'body_state' in state_update:
                result.payload['body_state_update'] = state_update['body_state']
            result.side_effects.append('body_state_updated')
            result.success = True
    except Exception as e:
        result.success = False
        result.error = f"{type(e).__name__}: {e}"
        print(f"  [Body] Dynamic body_state action failed: {e}")
    return result
