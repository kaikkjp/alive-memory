"""DEPRECATED — Use pipeline.body and pipeline.output instead.

This module is kept for backward compatibility. The execute() function now
delegates to the new brain/body pipeline:
  select_actions() → execute_body() → process_output()

New code should import from:
  - pipeline.body (execute_body, END_ENGAGEMENT_LINES)
  - pipeline.basal_ganglia (select_actions)
  - pipeline.output (process_output)
"""

import warnings

from models.pipeline import ValidatedOutput, ExecutionResult, ActionRequest
from models.state import DrivesState
from pipeline.body import END_ENGAGEMENT_LINES, _execute_single_action as execute_action
from pipeline.basal_ganglia import select_actions
from pipeline.body import execute_body
from pipeline.output import process_output
import db


async def execute(validated_output: ValidatedOutput, visitor_id: str = None,
                  cycle_id: str = None) -> ExecutionResult:
    """DEPRECATED: Use select_actions → execute_body → process_output instead.

    This wrapper preserves the old call signature for backward compatibility.
    """
    warnings.warn(
        "pipeline.executor.execute() is deprecated. "
        "Use select_actions() → execute_body() → process_output() instead.",
        DeprecationWarning,
        stacklevel=2,
    )

    # Get drives for basal ganglia stub
    drives = await db.get_drives_state()

    motor_plan = await select_actions(validated_output, drives)
    body_output = await execute_body(motor_plan, validated_output, visitor_id, cycle_id=cycle_id)
    cycle_output = await process_output(body_output, validated_output, visitor_id)

    # Map back to legacy ExecutionResult
    result = ExecutionResult()
    result.events_emitted = body_output.events_emitted
    result.actions_executed = [r.action for r in body_output.executed]
    result.memory_updates_processed = cycle_output.memory_updates_processed
    result.memory_update_failures = cycle_output.memory_update_failures
    result.resonance_applied = cycle_output.resonance_applied
    result.pool_outcome = cycle_output.pool_outcome
    return result
