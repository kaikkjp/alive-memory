"""Meta-controller — metric-driven self-tuning (TASK-090, TASK-091).

Sleep Phase 4: reads behavioral metrics, compares against target ranges,
proposes bounded parameter adjustments. Implements Tier 2 of the
three-tier self-regulation hierarchy.

    Tier 1: Operator hard floor (alive_config.yaml — immutable bounds)
    Tier 2: Meta-controller homeostasis (this module — sleep-phase adjustments)
    Tier 3: Conscious modify_self (TASK-056 — deliberate, reflection-required)

TASK-091 adds Phase 4b: evaluate pending experiments, classify outcomes,
revert bad adjustments, update confidence, detect side effects.
"""

import clock
import db
import db.connection as _connection
from alive_config import cfg, cfg_section
from db.parameters import p_or
from models.event import Event

# Relative change threshold for "neutral" classification
_NEUTRAL_THRESHOLD = 0.05


# ── Metric collection bridge ──

async def _collect_metrics(target_names: dict[str, dict]) -> dict[str, float]:
    """Read the latest metric values from the metrics_snapshots table.

    Returns a dict mapping metric_name -> NORMALIZED value (0–1 scale).
    Raw collector values are divided by the ``normalize`` factor from config.
    Only returns metrics that have snapshots in the DB.
    """
    conn = await _connection.get_db()
    metrics: dict[str, float] = {}

    # Build metric->normalize map
    normalize_map: dict[str, float] = {}
    needed = set()
    for target in target_names.values():
        metric = target.get('metric')
        if metric:
            needed.add(metric)
            normalize_map[metric] = target.get('normalize', 1.0)

    for metric_name in needed:
        cursor = await conn.execute(
            """SELECT value FROM metrics_snapshots
               WHERE metric_name = ?
               ORDER BY timestamp DESC
               LIMIT 1""",
            (metric_name,),
        )
        row = await cursor.fetchone()
        if row is not None:
            raw = row['value']
            divisor = normalize_map.get(metric_name, 1.0)
            metrics[metric_name] = raw / divisor if divisor else raw

    return metrics


async def _get_cycle_count() -> int:
    """Get total cycle count from cycle_log table."""
    conn = await _connection.get_db()
    cursor = await conn.execute("SELECT COUNT(*) FROM cycle_log")
    row = await cursor.fetchone()
    return row[0] if row else 0


# ── Side effect detection (TASK-091) ──

def detect_side_effects(
    experiment: dict,
    all_metrics_before: dict[str, float],
    all_metrics_after: dict[str, float],
    targets: dict[str, dict],
) -> list[dict]:
    """Check if an adjustment caused other metrics to leave their target range.

    Only flags metrics that were in range before and are out of range now.
    """
    side_effects = []
    target_metric = experiment.get('target_metric', '')

    for target_name, target in targets.items():
        metric_name = target.get('metric')
        if not metric_name or metric_name == target_metric:
            continue

        before = all_metrics_before.get(metric_name)
        after = all_metrics_after.get(metric_name)
        if before is None or after is None:
            continue

        t_min = target.get('min', 0.0)
        t_max = target.get('max', 1.0)
        was_in_range = t_min <= before <= t_max
        now_out_of_range = after < t_min or after > t_max

        if was_in_range and now_out_of_range:
            side_effects.append({
                'metric': metric_name,
                'before': before,
                'after': after,
                'target': [t_min, t_max],
            })

    return side_effects


# ── Adaptive cooldown (TASK-091) ──

def compute_adaptive_cooldown(base_cooldown: int, confidence: float) -> int:
    """Cooldown scales inversely with confidence.

    High confidence (0.9): cooldown * 1.3 — can adjust again soon
    Low confidence (0.3): cooldown * 3.1 — back off
    No data yet (0.5 default): cooldown * 2.5 — cautious
    """
    return round(base_cooldown * (1 + (1 - confidence) * 3))


# ── Outcome classification (TASK-091) ──

def classify_outcome(
    metric_value_at_change: float,
    metric_value_after: float,
    target_min: float,
    target_max: float,
) -> str:
    """Classify the outcome of an experiment.

    Returns: 'improved', 'degraded', or 'neutral'.
    Side effects are checked separately.
    """
    # Distance from target range
    def distance_from_range(val):
        if val < target_min:
            return target_min - val
        elif val > target_max:
            return val - target_max
        return 0.0

    dist_before = distance_from_range(metric_value_at_change)
    dist_after = distance_from_range(metric_value_after)

    # In range now?
    in_range_after = target_min <= metric_value_after <= target_max

    if in_range_after and dist_before > 0:
        return 'improved'

    # Closer to range?
    if dist_before > 0 and dist_after < dist_before:
        # Check if improvement is meaningful (>5% relative)
        relative_change = (dist_before - dist_after) / dist_before if dist_before > 0 else 0
        if relative_change > _NEUTRAL_THRESHOLD:
            return 'improved'
        return 'neutral'

    # Further from range?
    if dist_after > dist_before:
        relative_change = (dist_after - dist_before) / max(dist_before, 0.001)
        if relative_change > _NEUTRAL_THRESHOLD:
            return 'degraded'
        return 'neutral'

    return 'neutral'


# ── Evaluation sub-phase (TASK-091 — Phase 4b) ──

async def evaluate_experiments() -> list[dict]:
    """Evaluate pending experiments. Returns list of evaluation results.

    For each pending experiment older than evaluation_window cycles:
    1. Collect current metric value
    2. Classify outcome (improved/degraded/neutral)
    3. Check for side effects
    4. Revert if degraded or side_effect
    5. Update confidence
    6. Emit events for cortex awareness
    """
    mc = cfg_section('meta_controller')
    if not mc.get('enabled', True):
        return []

    evaluation_window = mc.get('evaluation_window', 50)
    cycle_count = await _get_cycle_count()
    targets = mc.get('targets', {})
    hard_floor = mc.get('hard_floor', {})

    pending = await db.get_pending_experiments()
    if not pending:
        print("  [MetaController] No pending experiments to evaluate")
        return []

    # Collect current metrics for all targets (for side-effect detection)
    all_metrics_now = await _collect_metrics(targets)

    # Build a map of metric values at experiment time (from the experiments themselves)
    results: list[dict] = []

    for exp in pending:
        age = cycle_count - exp['cycle_at_change']
        if age < evaluation_window:
            print(f"  [MetaController] Experiment {exp['id']} too young "
                  f"({age}/{evaluation_window} cycles)")
            continue

        target_metric = exp['target_metric']
        metric_now = all_metrics_now.get(target_metric)
        if metric_now is None:
            print(f"  [MetaController] No current metric for {target_metric}, skipping")
            continue

        # Find target range
        target_range = None
        for t_name, t_cfg in targets.items():
            if t_cfg.get('metric') == target_metric:
                target_range = t_cfg
                break
        if not target_range:
            continue

        t_min = target_range.get('min', 0.0)
        t_max = target_range.get('max', 1.0)

        # Classify outcome
        outcome = classify_outcome(
            exp['metric_value_at_change'], metric_now, t_min, t_max,
        )

        # Build "before" metrics for side-effect detection
        # Use metric_value_at_change for the target, and assume others were in range
        metrics_before: dict[str, float] = {}
        for t_name, t_cfg in targets.items():
            m = t_cfg.get('metric')
            if m == target_metric:
                metrics_before[m] = exp['metric_value_at_change']
            elif m in all_metrics_now:
                # Approximate: assume other metrics were at their current value
                # minus any drift (conservative — may miss some side effects)
                metrics_before[m] = all_metrics_now[m]

        # Check side effects
        side_effects = detect_side_effects(exp, metrics_before, all_metrics_now, targets)

        # Override outcome if side effects detected
        if side_effects and outcome != 'degraded':
            outcome = 'side_effect'

        effect_size = metric_now - exp['metric_value_at_change']
        reverted_at_cycle = None

        # Act on outcome
        if outcome in ('degraded', 'side_effect'):
            # Revert to old value
            try:
                await db.set_param(
                    exp['param_name'], exp['old_value'],
                    modified_by='meta_controller',
                    reason=f"revert: experiment {exp['id']} {outcome}",
                )
                reverted_at_cycle = cycle_count
                print(f"  [MetaController] Reverted {exp['param_name']}: "
                      f"{exp['new_value']:.4f} -> {exp['old_value']:.4f} "
                      f"(outcome: {outcome})")

                # Log revert as its own experiment entry
                await db.record_experiment(
                    cycle_at_change=cycle_count,
                    param_name=exp['param_name'],
                    old_value=exp['new_value'],
                    new_value=exp['old_value'],
                    reason=f"revert: {exp['id']}",
                    target_metric=exp['target_metric'],
                    metric_value_at_change=metric_now,
                )
            except Exception as e:
                print(f"  [MetaController] Revert failed for {exp['param_name']}: {e}")

        elif outcome == 'improved':
            print(f"  [MetaController] Experiment {exp['id']} improved: "
                  f"{exp['param_name']} {exp['metric_value_at_change']:.3f} -> "
                  f"{metric_now:.3f}")

        else:  # neutral
            print(f"  [MetaController] Experiment {exp['id']} neutral: "
                  f"{exp['param_name']} ({effect_size:+.4f})")

        # Update experiment record
        await db.update_experiment_outcome(
            experiment_id=exp['id'],
            outcome=outcome,
            metric_value_after=metric_now,
            evaluation_cycle=cycle_count,
            side_effects=side_effects if side_effects else None,
            reverted_at_cycle=reverted_at_cycle,
        )

        # Update confidence
        try:
            await db.update_confidence(
                param_name=exp['param_name'],
                target_metric=exp['target_metric'],
                outcome=outcome if outcome != 'side_effect' else 'degraded',
                effect_size=effect_size,
                cycle=cycle_count,
            )
        except Exception as e:
            print(f"  [MetaController] Confidence update failed: {e}")

        results.append({
            'experiment_id': exp['id'],
            'param': exp['param_name'],
            'outcome': outcome,
            'metric_before': exp['metric_value_at_change'],
            'metric_after': metric_now,
            'effect_size': effect_size,
            'side_effects': side_effects,
            'reverted': reverted_at_cycle is not None,
        })

    # Emit events for cortex awareness
    if results:
        event = Event(
            event_type='meta_controller_evaluation',
            source='self',
            payload={
                'evaluations': results,
                'cycle_count': cycle_count,
            },
            channel='system',
            salience_base=0.6,
        )
        await db.append_event(event)
        try:
            await db.inbox_add(event.id, priority=0.6)
        except Exception:
            pass

    print(f"  [MetaController] Evaluated {len(results)} experiment(s)")
    return results


# ── Core algorithm (TASK-090, updated for TASK-091 adaptive cooldown) ──

async def run_meta_controller() -> list[dict]:
    """Run the meta-controller during sleep. Returns list of adjustments made.

    Algorithm:
    1. Check if enabled + minimum cycles met
    2. Collect latest metrics
    3. Compare each metric against target ranges
    4. For out-of-range metrics, find adjustment candidates
    5. Apply adjustments (bounded by hard floor + self_parameters bounds)
    6. Log experiments + emit event
    """
    mc = cfg_section('meta_controller')
    if not mc.get('enabled', True):
        print("  [MetaController] Disabled in config")
        return []

    # Check minimum cycles
    cycle_count = await _get_cycle_count()
    min_cycles = mc.get('min_cycles_before_adjust', 100)
    if cycle_count < min_cycles:
        print(f"  [MetaController] Too early — {cycle_count}/{min_cycles} cycles")
        return []

    targets = mc.get('targets', {})
    if not targets:
        print("  [MetaController] No targets configured")
        return []

    # 1. Collect recent metrics
    metrics = await _collect_metrics(targets)
    if not metrics:
        print("  [MetaController] No metric data available")
        return []

    print(f"  [MetaController] Metrics collected: {metrics}")

    # 2. Check each target
    adjustments: list[dict] = []
    max_adj = mc.get('max_adjustments_per_sleep', 2)
    base_cooldown = mc.get('cooldown_cycles', 200)
    adjustment_defs = mc.get('adjustments', {})
    hard_floor = mc.get('hard_floor', {})

    for target_name, target in targets.items():
        if len(adjustments) >= max_adj:
            break

        metric_name = target.get('metric')
        if not metric_name or metric_name not in metrics:
            continue

        value = metrics[metric_name]
        target_min = target.get('min', 0.0)
        target_max = target.get('max', 1.0)

        if target_min <= value <= target_max:
            continue  # In range, no action needed

        direction = 'raise' if value < target_min else 'lower'

        # 3. Find adjustment candidates
        candidates = adjustment_defs.get(target_name, [])
        if not candidates:
            continue

        # Sort by priority (lower number = higher priority)
        sorted_candidates = sorted(candidates, key=lambda c: c.get('priority', 99))

        for candidate in sorted_candidates:
            if len(adjustments) >= max_adj:
                break

            param_name = candidate.get('param')
            if not param_name:
                continue

            # TASK-091: Check confidence — skip low-confidence links
            confidence_rec = await db.get_confidence(param_name, metric_name)
            confidence = 0.5  # default for unknown links
            if confidence_rec:
                confidence = confidence_rec['confidence']
                if confidence < 0.3 and confidence_rec['attempts'] >= 5:
                    print(f"  [MetaController] Skipping {param_name}->{metric_name}: "
                          f"low confidence ({confidence:.2f}, {confidence_rec['attempts']} attempts)")
                    continue

            # TASK-091: Adaptive cooldown based on confidence
            effective_cooldown = compute_adaptive_cooldown(base_cooldown, confidence)

            # Cooldown check
            last_cycle = await db.get_last_adjustment_cycle(param_name)
            if last_cycle is not None and (cycle_count - last_cycle) < effective_cooldown:
                print(f"  [MetaController] Cooldown active for {param_name} "
                      f"(last: cycle {last_cycle}, need {effective_cooldown} gap, "
                      f"confidence: {confidence:.2f})")
                continue

            # Get current value from self_parameters
            current_value = p_or(param_name, None)
            if current_value is None:
                print(f"  [MetaController] Parameter {param_name} not in cache, skipping")
                continue

            # Compute adjustment
            step = candidate.get('step', 0.01)
            param_direction = candidate.get('direction', 1)
            if direction == 'raise':
                delta = step * param_direction
            else:
                delta = -step * param_direction
            new_value = current_value + delta

            # self_parameters bounds enforcement (inner bounds from TASK-055)
            param_record = await db.get_param(param_name)
            if param_record:
                if param_record.get('min_bound') is not None:
                    new_value = max(param_record['min_bound'], new_value)
                if param_record.get('max_bound') is not None:
                    new_value = min(param_record['max_bound'], new_value)

            # Hard floor enforcement (Tier 1 — absolute, applied LAST)
            # Hard floor overrides all other bounds including self_parameters
            floor_bounds = hard_floor.get(param_name)
            if floor_bounds and isinstance(floor_bounds, list) and len(floor_bounds) == 2:
                new_value = max(floor_bounds[0], min(floor_bounds[1], new_value))

            # Round to avoid float drift
            new_value = round(new_value, 4)

            if new_value == current_value:
                continue

            adjustments.append({
                'param': param_name,
                'old_value': current_value,
                'new_value': new_value,
                'reason': (f"{target_name} is {value:.3f}, "
                           f"target [{target_min}, {target_max}]"),
                'target_metric': metric_name,
                'metric_value': value,
                'confidence': confidence,
            })
            break  # One adjustment per metric, highest priority wins

    if not adjustments:
        print("  [MetaController] All metrics in range — no adjustments needed")
        return []

    # 4. Apply adjustments
    for adj in adjustments:
        try:
            await db.set_param(
                adj['param'], adj['new_value'],
                modified_by='meta_controller',
                reason=adj['reason'],
            )
            print(f"  [MetaController] Adjusted {adj['param']}: "
                  f"{adj['old_value']:.4f} → {adj['new_value']:.4f} "
                  f"({adj['reason']})")
        except Exception as e:
            print(f"  [MetaController] Failed to adjust {adj['param']}: {e}")
            continue

        # Log experiment (with confidence at time of change)
        try:
            await db.record_experiment(
                cycle_at_change=cycle_count,
                param_name=adj['param'],
                old_value=adj['old_value'],
                new_value=adj['new_value'],
                reason=adj['reason'],
                target_metric=adj['target_metric'],
                metric_value_at_change=adj['metric_value'],
                confidence_at_change=adj.get('confidence'),
            )
        except Exception as e:
            print(f"  [MetaController] Failed to log experiment: {e}")

    # 5. Emit event for cortex awareness
    event = Event(
        event_type='meta_controller_adjustment',
        source='self',
        payload={
            'adjustments': adjustments,
            'cycle_count': cycle_count,
        },
        channel='system',
        salience_base=0.6,
    )
    await db.append_event(event)
    try:
        await db.inbox_add(event.id, priority=0.6)
    except Exception:
        pass  # inbox_add may not exist in all contexts

    print(f"  [MetaController] {len(adjustments)} adjustment(s) applied and logged")
    return adjustments
