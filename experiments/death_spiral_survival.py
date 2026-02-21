"""Death-spiral stress harness with survival analysis (Cox + AFT-style).

This module runs a lightweight deterministic stress test without EcoGym:
1) Inject sequential negative interaction pressure ("shock" phase)
2) Switch to supportive interactions ("recovery" phase)
3) Measure time-to-collapse and time-to-recovery
4) Fit:
   - Cox proportional hazards (binary treatment: floor-bounce on/off)
   - Log-time AFT-style estimate (two-group log-time contrast)

Usage:
    python -m experiments.death_spiral_survival
    python -m experiments.death_spiral_survival --replicates 200 --out-dir experiments/logs/death_spiral
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import csv
import io
import json
import math
import random
import statistics
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

import db
import db.parameters as param_store
from db.parameters import refresh_params_cache
from models.event import Event
from models.state import DrivesState
from pipeline.hypothalamus import update_drives


def clamp01(v: float) -> float:
    return max(0.0, min(1.0, v))


def clamp_signed(v: float) -> float:
    return max(-1.0, min(1.0, v))


def normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def safe_exp(x: float) -> float:
    # Avoid overflow while preserving monotonicity for reporting.
    return math.exp(max(-700.0, min(700.0, x)))


@dataclass(frozen=True)
class HarnessConfig:
    replicates: int = 120
    max_turns: int = 120
    shock_turns: int = 24
    turn_hours: float = 0.05  # ~3 min/cycle
    failures_per_shock_turn: int = 1
    shock_failure_scale: float = 0.05
    collapse_valence_threshold: float = -0.12
    collapse_arousal_threshold: float = -1.0  # <0 disables arousal gate
    recovery_valence_threshold: float = -0.08
    recovery_arousal_threshold: float = 0.28
    stable_recovery_turns: int = 3
    seed: int = 42
    trajectory_samples: int = 6


@dataclass(frozen=True)
class Variant:
    name: str
    group: int
    overrides: dict[str, float]


@dataclass(frozen=True)
class ScenarioDraw:
    shock_scale: float
    hostility_scale: float
    recovery_scale: float


def build_variants() -> list[Variant]:
    """Two-arm comparison: baseline vs floor-bounce recovery."""
    return [
        Variant(
            name="baseline_no_bounce",
            group=0,
            overrides={
                "hypothalamus.coupling.social_valence_floor": -1.0,
                "hypothalamus.coupling.visitor_relief_factor": 0.02,
                "output.drives.success_bonus_base": 0.01,
            },
        ),
        Variant(
            name="floor_bounce",
            group=1,
            overrides={},
        ),
    ]


def draw_scenarios(config: HarnessConfig) -> list[ScenarioDraw]:
    rng = random.Random(config.seed)
    draws: list[ScenarioDraw] = []
    for _ in range(config.replicates):
        shock_scale = max(0.25, rng.gauss(1.0, 0.2))
        hostility_scale = max(0.25, rng.gauss(1.0, 0.2))
        recovery_scale = max(0.25, rng.gauss(1.0, 0.15))
        draws.append(
            ScenarioDraw(
                shock_scale=shock_scale,
                hostility_scale=hostility_scale,
                recovery_scale=recovery_scale,
            )
        )
    return draws


def seed_drives(params: dict[str, float]) -> DrivesState:
    return DrivesState(
        social_hunger=float(params["hypothalamus.equilibria.social_hunger"]),
        curiosity=float(params["hypothalamus.equilibria.diversive_curiosity"]),
        expression_need=float(params["hypothalamus.equilibria.expression_need"]),
        rest_need=float(params["hypothalamus.equilibria.rest_need"]),
        energy=0.8,
        mood_valence=float(params["hypothalamus.equilibria.mood_valence"]),
        mood_arousal=float(params["hypothalamus.equilibria.mood_arousal"]),
    )


def _apply_pre_drive_shock(
    drives: DrivesState,
    params: dict[str, float],
    draw: ScenarioDraw,
    failures_per_turn: int,
    shock_failure_scale: float,
) -> None:
    # Negative interaction → failed actions + affect hit.
    fail_penalty = (
        params["output.drives.failure_valence_penalty"]
        * failures_per_turn
        * draw.shock_scale
        * shock_failure_scale
    )
    drives.mood_valence = clamp_signed(drives.mood_valence + fail_penalty)
    drives.mood_arousal = clamp01(drives.mood_arousal - 0.015 * draw.shock_scale)

    # Distress buildup under repeated hostile turns.
    drives.social_hunger = clamp01(drives.social_hunger + 0.02 * draw.hostility_scale)
    drives.expression_need = clamp01(drives.expression_need + 0.015 * draw.hostility_scale)
    drives.rest_need = clamp01(drives.rest_need + 0.01 * draw.shock_scale)


def _apply_pre_drive_recovery(
    drives: DrivesState,
    params: dict[str, float],
    draw: ScenarioDraw,
    actions_today: int,
) -> int:
    # Positive action outcome → success bonus (same math as output pipeline).
    divisor = max(params["output.drives.success_habituation_divisor"], 1e-6)
    bonus = params["output.drives.success_bonus_base"] / (1.0 + actions_today / divisor)
    drives.mood_valence = clamp_signed(drives.mood_valence + bonus * draw.recovery_scale)
    return actions_today + 1


def _is_collapsed(drives: DrivesState, config: HarnessConfig) -> bool:
    if config.collapse_arousal_threshold < 0:
        return drives.mood_valence <= config.collapse_valence_threshold
    return (
        drives.mood_valence <= config.collapse_valence_threshold
        and drives.mood_arousal <= config.collapse_arousal_threshold
    )


def _is_recovered(drives: DrivesState, config: HarnessConfig) -> bool:
    return (
        drives.mood_valence >= config.recovery_valence_threshold
        and drives.mood_arousal >= config.recovery_arousal_threshold
    )


async def run_episode(
    config: HarnessConfig,
    variant: Variant,
    params: dict[str, float],
    draw: ScenarioDraw,
    run_index: int,
    keep_trajectory: bool,
) -> tuple[dict, dict | None, list[dict]]:
    drives = seed_drives(params)
    idle_streak = 0
    actions_today = 0

    collapse_turn: int | None = None
    recovery_turn: int | None = None
    stable_recovery = 0

    trajectory: list[dict] = []

    for turn_idx in range(config.max_turns):
        turn = turn_idx + 1
        in_shock = turn <= config.shock_turns

        events: list[Event] = []
        if in_shock:
            idle_streak += 1
            cycle_context = {
                "engaged_this_cycle": False,
                "consecutive_idle": idle_streak,
                "expression_taken": False,
            }
            _apply_pre_drive_shock(
                drives=drives,
                params=params,
                draw=draw,
                failures_per_turn=config.failures_per_shock_turn,
                shock_failure_scale=config.shock_failure_scale,
            )
        else:
            idle_streak = 0
            cycle_context = {
                "engaged_this_cycle": True,
                "consecutive_idle": 0,
                "expression_taken": True,
            }
            actions_today = _apply_pre_drive_recovery(
                drives=drives,
                params=params,
                draw=draw,
                actions_today=actions_today,
            )
            if turn == config.shock_turns + 1:
                events.append(Event(event_type="visitor_connect", source="visitor:sim", payload={}))
            events.append(Event(event_type="visitor_speech", source="visitor:sim", payload={}))
            events.append(Event(event_type="action_speak", source="self", payload={}))

        drives, _ = await update_drives(
            drives=drives,
            elapsed_hours=config.turn_hours,
            events=events,
            cycle_context=cycle_context,
        )

        if collapse_turn is None and _is_collapsed(drives, config):
            collapse_turn = turn

        if collapse_turn is not None and recovery_turn is None and turn > config.shock_turns:
            if _is_recovered(drives, config):
                stable_recovery += 1
                if stable_recovery >= config.stable_recovery_turns:
                    recovery_turn = turn - config.stable_recovery_turns + 1
            else:
                stable_recovery = 0

        if keep_trajectory:
            trajectory.append(
                {
                    "turn": turn,
                    "phase": "shock" if in_shock else "recovery",
                    "mood_valence": round(drives.mood_valence, 4),
                    "mood_arousal": round(drives.mood_arousal, 4),
                    "social_hunger": round(drives.social_hunger, 4),
                    "expression_need": round(drives.expression_need, 4),
                    "rest_need": round(drives.rest_need, 4),
                    "collapsed": collapse_turn is not None,
                    "recovered": recovery_turn is not None,
                }
            )

    collapse_event = int(collapse_turn is not None)
    collapse_time = collapse_turn if collapse_turn is not None else config.max_turns

    collapse_row = {
        "run_id": f"{variant.name}_{run_index:04d}",
        "variant": variant.name,
        "group": variant.group,
        "shock_scale": round(draw.shock_scale, 6),
        "hostility_scale": round(draw.hostility_scale, 6),
        "recovery_scale": round(draw.recovery_scale, 6),
        "time": collapse_time,
        "event": collapse_event,
    }

    recovery_row: dict | None = None
    if collapse_turn is not None:
        if recovery_turn is not None and recovery_turn >= collapse_turn:
            recovery_time = recovery_turn - collapse_turn + 1
            recovery_event = 1
        else:
            recovery_time = config.max_turns - collapse_turn + 1
            recovery_event = 0
        recovery_row = {
            "run_id": f"{variant.name}_{run_index:04d}",
            "variant": variant.name,
            "group": variant.group,
            "shock_scale": round(draw.shock_scale, 6),
            "hostility_scale": round(draw.hostility_scale, 6),
            "recovery_scale": round(draw.recovery_scale, 6),
            "time": recovery_time,
            "event": recovery_event,
        }

    return collapse_row, recovery_row, trajectory


def _cox_binary_loglik_grad_hess(
    beta: float,
    rows: list[dict],
    time_key: str,
    event_key: str,
    group_key: str,
) -> tuple[float, float, float]:
    event_times = sorted({float(r[time_key]) for r in rows if int(r[event_key]) == 1})
    loglik = 0.0
    grad = 0.0
    hess = 0.0

    for t in event_times:
        d_rows = [r for r in rows if float(r[time_key]) == t and int(r[event_key]) == 1]
        d = len(d_rows)
        if d == 0:
            continue
        risk_rows = [r for r in rows if float(r[time_key]) >= t]
        weights = [math.exp(beta * float(r[group_key])) for r in risk_rows]
        denom = sum(weights)
        if denom <= 0:
            continue

        x_events = sum(float(r[group_key]) for r in d_rows)
        x_bar = sum(float(r[group_key]) * w for r, w in zip(risk_rows, weights)) / denom
        x2_bar = sum((float(r[group_key]) ** 2) * w for r, w in zip(risk_rows, weights)) / denom

        loglik += beta * x_events - d * math.log(denom)
        grad += x_events - d * x_bar
        hess += -d * (x2_bar - x_bar * x_bar)

    return loglik, grad, hess


def fit_cox_binary(
    rows: list[dict],
    *,
    time_key: str = "time",
    event_key: str = "event",
    group_key: str = "group",
    max_iter: int = 200,
    tol: float = 1e-9,
    ridge: float = 1e-3,
) -> dict:
    """Fit a one-covariate Cox PH model with Breslow ties."""
    if not rows:
        return {"ok": False, "reason": "empty_dataset"}
    if sum(int(r[event_key]) for r in rows) == 0:
        return {"ok": False, "reason": "no_events"}

    gvals = {int(r[group_key]) for r in rows}
    if gvals != {0, 1}:
        return {"ok": False, "reason": "requires_binary_group_0_1"}

    beta = 0.0
    for _ in range(max_iter):
        _, grad, hess = _cox_binary_loglik_grad_hess(beta, rows, time_key, event_key, group_key)
        grad -= ridge * beta
        hess -= ridge
        if abs(grad) < tol:
            break
        if abs(hess) < 1e-12:
            break
        new_beta = beta - (grad / hess)
        if not math.isfinite(new_beta):
            break
        if abs(new_beta - beta) < tol:
            beta = new_beta
            break
        beta = new_beta

    loglik, grad, hess = _cox_binary_loglik_grad_hess(beta, rows, time_key, event_key, group_key)
    grad -= ridge * beta
    hess -= ridge
    if hess >= 0 or not math.isfinite(hess):
        return {
            "ok": False,
            "reason": "non_negative_hessian",
            "beta": beta,
            "loglik": loglik,
            "gradient": grad,
        }

    se = math.sqrt(1.0 / (-hess))
    z = beta / se if se > 0 else float("inf")
    p_value = 2.0 * (1.0 - normal_cdf(abs(z)))
    hr = safe_exp(beta)
    lo = safe_exp(beta - 1.96 * se)
    hi = safe_exp(beta + 1.96 * se)
    return {
        "ok": True,
        "beta": beta,
        "se": se,
        "z": z,
        "p_value": p_value,
        "hazard_ratio": hr,
        "ci95": [lo, hi],
        "events": int(sum(int(r[event_key]) for r in rows)),
        "n": len(rows),
        "loglik": loglik,
        "ridge": ridge,
    }


def _safe_variance(vals: list[float]) -> float:
    if len(vals) < 2:
        return 0.0
    return statistics.variance(vals)


def fit_aft_logtime_binary(
    rows: list[dict],
    *,
    time_key: str = "time",
    event_key: str = "event",
    group_key: str = "group",
) -> dict:
    """AFT-style estimate via two-group log-time contrast on observed events.

    This is a lightweight approximation, not a full censored likelihood model.
    Right-censored rows are excluded from the log-time contrast.
    """
    observed = [r for r in rows if int(r[event_key]) == 1 and float(r[time_key]) > 0]
    if not observed:
        return {"ok": False, "reason": "no_observed_events"}

    log_t_0 = [math.log(float(r[time_key])) for r in observed if int(r[group_key]) == 0]
    log_t_1 = [math.log(float(r[time_key])) for r in observed if int(r[group_key]) == 1]
    if not log_t_0 or not log_t_1:
        return {"ok": False, "reason": "both_groups_need_events"}

    mean0 = statistics.mean(log_t_0)
    mean1 = statistics.mean(log_t_1)
    beta = mean1 - mean0
    se = math.sqrt((_safe_variance(log_t_1) / len(log_t_1)) + (_safe_variance(log_t_0) / len(log_t_0)))
    z = beta / se if se > 0 else float("inf")
    p_value = 2.0 * (1.0 - normal_cdf(abs(z))) if math.isfinite(z) else 0.0
    accel = safe_exp(beta)
    lo = safe_exp(beta - 1.96 * se)
    hi = safe_exp(beta + 1.96 * se)
    return {
        "ok": True,
        "beta": beta,
        "se": se,
        "z": z,
        "p_value": p_value,
        "acceleration_factor": accel,
        "ci95": [lo, hi],
        "n_observed": len(observed),
        "group0_events": len(log_t_0),
        "group1_events": len(log_t_1),
    }


def summarize_groups(
    rows: list[dict],
    *,
    time_key: str = "time",
    event_key: str = "event",
    group_key: str = "group",
) -> dict:
    out: dict[str, dict] = {}
    for g in (0, 1):
        subset = [r for r in rows if int(r[group_key]) == g]
        events = [float(r[time_key]) for r in subset if int(r[event_key]) == 1]
        all_times = [float(r[time_key]) for r in subset]
        out[str(g)] = {
            "n": len(subset),
            "event_rate": (len(events) / len(subset)) if subset else 0.0,
            "mean_time_all": statistics.mean(all_times) if all_times else None,
            "median_time_events": statistics.median(events) if events else None,
        }
    return out


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        with open(path, "w"):
            return
        return

    fieldnames = list(rows[0].keys())
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


async def load_default_params_from_temp_db() -> dict[str, float]:
    # Keep the harness isolated from the runtime DB.
    with tempfile.TemporaryDirectory(prefix="death_spiral_") as tmpdir:
        db_path = Path(tmpdir) / "harness.db"
        db.set_db_path(str(db_path))
        await db.init_db()
        await refresh_params_cache()
        params = dict(param_store._cache)
        await db.close_db()
    return params


async def run_harness(config: HarnessConfig) -> dict:
    base_params = await load_default_params_from_temp_db()
    variants = build_variants()
    draws = draw_scenarios(config)

    collapse_rows: list[dict] = []
    recovery_rows: list[dict] = []
    trajectories: list[dict] = []

    # update_drives() logs every cycle; silence for large runs.
    with contextlib.redirect_stdout(io.StringIO()):
        for i, draw in enumerate(draws):
            for variant in variants:
                params = dict(base_params)
                params.update(variant.overrides)
                param_store._cache = params

                keep_traj = i < config.trajectory_samples
                collapse_row, recovery_row, trajectory = await run_episode(
                    config=config,
                    variant=variant,
                    params=params,
                    draw=draw,
                    run_index=i,
                    keep_trajectory=keep_traj,
                )
                collapse_rows.append(collapse_row)
                if recovery_row is not None:
                    recovery_rows.append(recovery_row)
                if keep_traj:
                    trajectories.append(
                        {
                            "run_id": collapse_row["run_id"],
                            "variant": variant.name,
                            "draw": asdict(draw),
                            "trajectory": trajectory,
                        }
                    )

    collapse_cox = fit_cox_binary(collapse_rows)
    collapse_aft = fit_aft_logtime_binary(collapse_rows)

    recovery_cox = fit_cox_binary(recovery_rows) if recovery_rows else {"ok": False, "reason": "no_collapses"}
    recovery_aft = fit_aft_logtime_binary(recovery_rows) if recovery_rows else {"ok": False, "reason": "no_collapses"}

    return {
        "config": asdict(config),
        "variants": [asdict(v) for v in variants],
        "collapse_group_summary": summarize_groups(collapse_rows),
        "recovery_group_summary": summarize_groups(recovery_rows) if recovery_rows else {},
        "collapse_models": {"cox": collapse_cox, "aft_logtime": collapse_aft},
        "recovery_models": {"cox": recovery_cox, "aft_logtime": recovery_aft},
        "collapse_rows": collapse_rows,
        "recovery_rows": recovery_rows,
        "trajectory_samples": trajectories,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manual death-spiral survival harness")
    parser.add_argument("--replicates", type=int, default=HarnessConfig.replicates)
    parser.add_argument("--max-turns", type=int, default=HarnessConfig.max_turns)
    parser.add_argument("--shock-turns", type=int, default=HarnessConfig.shock_turns)
    parser.add_argument("--turn-hours", type=float, default=HarnessConfig.turn_hours)
    parser.add_argument("--failures-per-shock-turn", type=int, default=HarnessConfig.failures_per_shock_turn)
    parser.add_argument("--shock-failure-scale", type=float, default=HarnessConfig.shock_failure_scale)
    parser.add_argument("--seed", type=int, default=HarnessConfig.seed)
    parser.add_argument("--out-dir", default="experiments/logs/death_spiral")
    return parser.parse_args()


def print_summary(report: dict) -> None:
    collapse = report["collapse_models"]
    recovery = report["recovery_models"]

    print("[DeathSpiral] Collapse model (event = collapse)")
    print(f"  Cox: {json.dumps(collapse['cox'], indent=None)}")
    print(f"  AFT: {json.dumps(collapse['aft_logtime'], indent=None)}")
    print("[DeathSpiral] Recovery model (event = recovery after collapse)")
    print(f"  Cox: {json.dumps(recovery['cox'], indent=None)}")
    print(f"  AFT: {json.dumps(recovery['aft_logtime'], indent=None)}")


def main() -> None:
    args = parse_args()
    config = HarnessConfig(
        replicates=max(2, args.replicates),
        max_turns=max(8, args.max_turns),
        shock_turns=max(1, min(args.shock_turns, args.max_turns - 1)),
        turn_hours=max(1e-4, args.turn_hours),
        failures_per_shock_turn=max(1, args.failures_per_shock_turn),
        shock_failure_scale=max(0.0, args.shock_failure_scale),
        seed=args.seed,
    )

    report = asyncio.run(run_harness(config))
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    collapse_csv = out_dir / "collapse_survival.csv"
    recovery_csv = out_dir / "recovery_survival.csv"
    summary_json = out_dir / "survival_summary.json"
    traj_json = out_dir / "trajectory_samples.json"

    write_csv(collapse_csv, report["collapse_rows"])
    write_csv(recovery_csv, report["recovery_rows"])
    with open(summary_json, "w") as f:
        json.dump(
            {
                "config": report["config"],
                "variants": report["variants"],
                "collapse_group_summary": report["collapse_group_summary"],
                "recovery_group_summary": report["recovery_group_summary"],
                "collapse_models": report["collapse_models"],
                "recovery_models": report["recovery_models"],
                "outputs": {
                    "collapse_survival_csv": str(collapse_csv),
                    "recovery_survival_csv": str(recovery_csv),
                    "trajectory_samples_json": str(traj_json),
                },
            },
            f,
            indent=2,
        )
    with open(traj_json, "w") as f:
        json.dump(report["trajectory_samples"], f, indent=2)

    print_summary(report)
    print(f"[DeathSpiral] Wrote {collapse_csv}")
    print(f"[DeathSpiral] Wrote {recovery_csv}")
    print(f"[DeathSpiral] Wrote {summary_json}")
    print(f"[DeathSpiral] Wrote {traj_json}")


if __name__ == "__main__":
    main()
