# 069-A: Body Executor Framework

## Goal
Create `body/` package with pluggable executor interface. Extract existing internal actions from `pipeline/body.py` into the new package. After this, `pipeline/body.py` becomes a thin delegator. All existing tests must still pass — this is a refactor with an extension point for future real-world executors.

## Context
Read these files first:
- `ARCHITECTURE.md` — system overview
- `tasks/TASK-069-real-body-actions.md` — full spec (Phase 1)
- `pipeline/body.py` — current body execution (extract from here)
- `pipeline/action_registry.py` — existing action definitions
- `models/pipeline.py` — `ActionDecision`, `ActionResult`, `MotorPlan`, `BodyOutput`

## Files to Create

### `body/__init__.py`
Re-export key classes for backward compat.

### `body/executor.py`
```python
class BodyExecutor:
    action_name: str
    requires_energy: float
    cooldown_seconds: int
    requires_online: bool = False
    
    async def can_execute(self, context) -> tuple[bool, str]: ...
    async def execute(self, intention, context) -> ActionResult: ...

EXECUTOR_REGISTRY: dict[str, BodyExecutor] = {}

def register_executor(executor: BodyExecutor): ...
def resolve_executor(action_name: str) -> BodyExecutor | None: ...
```

### `body/internal.py`
Extract all existing action handlers from `pipeline/body.py`:
- `dialogue` — emit speech to visitor
- `journal_write` — write journal entry
- `update_room_state` — change posture/location/activity
- `gift_response` — handle gifts
- Any other actions currently in body.py

Each becomes a `BodyExecutor` subclass registered in `EXECUTOR_REGISTRY`.

### `body/rate_limiter.py`
```python
class RateLimiter:
    async def check(self, action_name: str) -> tuple[bool, str]:
        """Check max/hour, max/day, cooldown. Returns (allowed, reason_if_not)."""
    async def record(self, action_name: str): ...
    
# Config: per-action limits
RATE_LIMITS = {
    "browse_web": {"max_per_hour": 20, "max_per_day": 100},
    "post_x": {"max_per_hour": 12, "max_per_day": 50},
    ...
}
```

### `tests/test_body_executor.py`
- Executor registration and resolution
- Internal action execution produces correct ActionResult
- Unknown action returns None from resolve

### `tests/test_rate_limiter.py`
- Rate limit check passes within limits
- Rate limit check fails when exceeded
- Cooldown enforcement

## Files to Modify

### `pipeline/body.py`
Replace inline action handling with delegation to executor registry:
```python
from body.executor import resolve_executor

async def execute_action(intention, context):
    executor = resolve_executor(intention.action_name)
    if executor is None:
        return ActionResult(success=False, reason="incapable")
    can, reason = await executor.can_execute(context)
    if not can:
        return ActionResult(success=False, reason=reason)
    return await executor.execute(intention, context)
```
Keep all existing function signatures. Existing callers should not need changes.

## Files NOT to Touch
- `pipeline/cortex.py`
- `pipeline/basal_ganglia.py`
- `pipeline/output.py`
- `heartbeat.py`
- `heartbeat_server.py`
- `sleep.py`
- `simulate.py`
- `db/*`
- `window/*`

## Done Signal
- All existing tests pass (especially `test_body.py`, `test_basal_ganglia*.py`)
- New executor registry resolves all internal actions
- `body/` package importable
- Rate limiter enforces limits in unit tests
- `pipeline/body.py` delegates to registry (no inline action handling remains)
