"""Ablation suite — full component ablation over N autonomous cycles.

Variants:
  full             All subsystems enabled (baseline)
  no_affect        Affect lens disabled (perceptions unmodified by drives)
  no_drives        Drive dynamics frozen (no decay, no event-driven updates)
  no_sleep         Sleep consolidation skipped
  no_basal_ganglia Basal ganglia bypassed (no action selection / habit gating)
  no_memory        Hippocampus recall returns empty (no memory context)

Usage:
  # Set model via env (OpenRouter ID):
  LLM_CORTEX_MODEL=minimax/minimax-01 python -m experiments.ablation_suite
  LLM_CORTEX_MODEL=minimax/minimax-01 python -m experiments.ablation_suite \\
      --cycles 1000 --out-dir experiments/ablation/
  # Dry-run (smoke test, 5 cycles):
  python -m experiments.ablation_suite --cycles 5 --variants full
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
import tempfile
import time
import uuid
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch, AsyncMock, MagicMock

from dotenv import load_dotenv
load_dotenv()

# ── Variant definitions ────────────────────────────────────────────────────────

ALL_VARIANTS = ["full", "no_affect", "no_drives", "no_sleep", "no_basal_ganglia", "no_memory"]

SLEEP_START_HOUR = 3
SLEEP_END_HOUR = 6
SLEEP_ADVANCE_SECONDS = 3 * 3600
CYCLE_ADVANCE_DEFAULT = 180  # seconds to advance per cycle (3 min sim time)


# ── Patch helpers ──────────────────────────────────────────────────────────────

def _identity_affect_lens(perceptions, drives):
    """no_affect: return perceptions unchanged."""
    return perceptions


async def _frozen_drives(drives, elapsed_hours, events, cortex_flags=None,
                         gap_curiosity_deltas=None, cycle_context=None):
    """no_drives: return drives unchanged, empty feelings string."""
    return drives, ""


async def _empty_recall(memory_requests):
    """no_memory: return empty memory chunks."""
    return []


async def _noop_select_actions(validated, drives, context=None):
    """no_basal_ganglia: return empty motor plan."""
    from models.pipeline import MotorPlan
    return MotorPlan(actions=[], suppressed=[])


async def _noop_check_habits(drives, engagement):
    """no_basal_ganglia: no habit firings."""
    return None


async def _noop_sleep_cycle(*args, **kwargs):
    """no_sleep: skip consolidation, signal as if done."""
    return 0


async def _noop_nap(*args, **kwargs):
    """no_sleep: skip nap consolidation."""
    return 0


# Maps variant name → list of (target, replacement) patch specs.
# Targets use the "from X import Y" form as used in heartbeat.py,
# so we patch the name in the heartbeat namespace.
PATCH_SPECS: dict[str, list[tuple[str, Any]]] = {
    "full": [],
    "no_affect": [
        ("heartbeat.apply_affect_lens", _identity_affect_lens),
    ],
    "no_drives": [
        ("heartbeat.update_drives", _frozen_drives),
    ],
    # no_sleep: sleep_cycle is called directly in run_variant_sim() loop,
    # not through heartbeat — we skip it via the variant name check there.
    "no_sleep": [],
    "no_basal_ganglia": [
        ("heartbeat.select_actions", _noop_select_actions),
        ("heartbeat.check_habits", _noop_check_habits),
    ],
    "no_memory": [
        ("heartbeat.recall", _empty_recall),
    ],
}


@contextmanager
def apply_patches(variant: str):
    """Context manager: apply variant patches, restore on exit."""
    specs = PATCH_SPECS[variant]
    patchers = [patch(target, new_callable=lambda r=repl: (lambda *a, **kw: r)) for target, repl in specs]
    # Use patch() with new= directly instead
    active_patches = []
    try:
        for target, repl in specs:
            p = patch(target, repl)
            p.start()
            active_patches.append(p)
        yield
    finally:
        for p in reversed(active_patches):
            p.stop()


# ── Simulation runner ──────────────────────────────────────────────────────────

async def run_variant_sim(
    variant: str,
    n_cycles: int,
    sim_db_path: str,
    start_jst: datetime,
) -> list[dict]:
    """Run N cycles for one variant. Returns raw cycle_log rows."""
    import clock
    from clock import JST
    import db as dbmod
    from seed import seed
    from heartbeat import Heartbeat
    from sleep import sleep_cycle, nap_consolidate

    # Init virtual clock
    clock.init_clock(simulate=True, start=start_jst)

    # Init DB
    dbmod.set_db_path(sim_db_path)
    await dbmod.init_db()
    await seed()

    # Heartbeat
    hb = Heartbeat()
    await hb.start_for_simulation()

    last_sleep_date: str | None = None
    cycle_count = 0

    print(f"  [{variant}] Starting {n_cycles} cycles …", flush=True)
    t0 = time.monotonic()

    with apply_patches(variant):
        while cycle_count < n_cycles:
            now_jst = clock.now()
            hour = now_jst.hour

            # ── Sleep window ──
            if SLEEP_START_HOUR <= hour < SLEEP_END_HOUR:
                today_str = now_jst.date().isoformat()
                if last_sleep_date != today_str:
                    if variant == "no_sleep":
                        # Ablation: skip consolidation, just advance past window
                        last_sleep_date = today_str
                    else:
                        try:
                            ran = await sleep_cycle()
                            if ran >= 0:
                                last_sleep_date = today_str
                        except Exception as e:
                            print(f"  [{variant}] Sleep error: {e}", flush=True)
                            last_sleep_date = today_str  # don't retry on error

                if last_sleep_date == today_str:
                    clock.advance(SLEEP_ADVANCE_SECONDS)
                else:
                    clock.advance(60)
                continue

            # ── Normal cycle ──
            try:
                result = await hb.run_one_cycle()
                cycle_count += 1
                advance = max(1, result.sleep_seconds)
                clock.advance(advance)

                if cycle_count % 100 == 0:
                    elapsed = time.monotonic() - t0
                    print(f"  [{variant}] {cycle_count}/{n_cycles} cycles "
                          f"({elapsed:.0f}s elapsed)", flush=True)

            except KeyboardInterrupt:
                print(f"\n  [{variant}] Interrupted at cycle {cycle_count}.", flush=True)
                break
            except Exception as e:
                print(f"  [{variant}] Cycle error: {e}", flush=True)
                clock.advance(CYCLE_ADVANCE_DEFAULT)

    elapsed_total = time.monotonic() - t0
    print(f"  [{variant}] Done: {cycle_count} cycles in {elapsed_total:.0f}s", flush=True)

    # Export cycle_log rows before closing
    rows = await _export_cycle_rows()

    await dbmod.close_db()
    return rows


async def _export_cycle_rows() -> list[dict]:
    """Pull all cycle_log rows via the open aiosqlite connection."""
    from db.connection import get_db
    conn = await get_db()
    cursor = await conn.execute("SELECT * FROM cycle_log ORDER BY ts ASC")
    raw = await cursor.fetchall()

    if not raw:
        return []

    # first_ts for elapsed_hours
    try:
        first_ts = datetime.fromisoformat(str(raw[0]["ts"]))
    except Exception:
        first_ts = datetime.utcnow()

    records = []
    for row in raw:
        r = dict(row)
        ts_str = r.get("ts") or ""
        try:
            ts = datetime.fromisoformat(ts_str)
        except Exception:
            ts = first_ts
        elapsed = (ts - first_ts).total_seconds() / 3600.0

        try:
            drives = json.loads(r.get("drives") or "{}")
        except Exception:
            drives = {}
        try:
            actions = json.loads(r.get("actions") or "[]")
        except Exception:
            actions = []
        actions = [a.replace("action_", "") if a.startswith("action_") else a for a in actions]

        token_budget = r.get("token_budget") or 0
        routing_focus = r.get("routing_focus") or "idle"

        records.append({
            "cycle_id": r.get("id"),
            "ts": ts_str,
            "elapsed_hours": round(elapsed, 3),
            "routing_focus": routing_focus,
            "actions": actions,
            "drives": {
                "social_hunger": drives.get("social_hunger", 0.0),
                "curiosity": drives.get("curiosity", 0.0),
                "expression_need": drives.get("expression_need", 0.0),
                "rest_need": drives.get("rest_need", 0.0),
                "energy": drives.get("energy", 0.0),
                "mood_valence": drives.get("mood_valence", 0.0),
                "mood_arousal": drives.get("mood_arousal", 0.0),
            },
            "token_budget": token_budget,
            "is_budget_rest": token_budget == 0 and routing_focus == "rest",
            "is_habit_fired": token_budget == 0 and len(actions) > 0,
        })

    return records


# ── Metrics ────────────────────────────────────────────────────────────────────

def shannon_entropy(counts: Counter) -> float:
    total = sum(counts.values())
    if total == 0:
        return 0.0
    h = 0.0
    for c in counts.values():
        if c > 0:
            p = c / total
            h -= p * math.log2(p)
    return h


def compute_metrics(records: list[dict]) -> dict:
    """Compute ablation table metrics from cycle records."""
    n = len(records)
    if n == 0:
        return {"n": 0, "h_focus": 0.0, "h_action": 0.0, "actions_per_cycle": 0.0,
                "mean_valence": 0.0, "mean_drive_std": 0.0, "habit_fires": 0,
                "budget_rest": 0, "focus_dist": {}, "action_dist": {}}

    focus_counts = Counter(r["routing_focus"] for r in records)
    h_focus = shannon_entropy(focus_counts)

    action_counts: Counter = Counter()
    for r in records:
        acts = r.get("actions", [])
        if acts:
            for a in acts:
                action_counts[a] += 1
        else:
            action_counts["_none_"] += 1
    h_action = shannon_entropy(action_counts)

    actions_per_cycle = sum(len(r.get("actions", [])) for r in records) / n

    valences = [r["drives"]["mood_valence"] for r in records if "drives" in r]
    mean_valence = sum(valences) / len(valences) if valences else 0.0

    # Drive variance: mean across drives of per-drive std
    drive_keys = ["social_hunger", "curiosity", "expression_need", "rest_need",
                  "energy", "mood_valence", "mood_arousal"]
    drive_stds = []
    for k in drive_keys:
        vals = [r["drives"][k] for r in records if k in r.get("drives", {})]
        if len(vals) > 1:
            mean = sum(vals) / len(vals)
            std = math.sqrt(sum((v - mean) ** 2 for v in vals) / len(vals))
            drive_stds.append(std)
    mean_drive_std = sum(drive_stds) / len(drive_stds) if drive_stds else 0.0

    habit_fires = sum(1 for r in records if r.get("is_habit_fired"))
    budget_rest = sum(1 for r in records if r.get("is_budget_rest"))

    return {
        "n": n,
        "h_focus": round(h_focus, 4),
        "h_action": round(h_action, 4),
        "actions_per_cycle": round(actions_per_cycle, 3),
        "mean_valence": round(mean_valence, 4),
        "mean_drive_std": round(mean_drive_std, 4),
        "habit_fires": habit_fires,
        "budget_rest": budget_rest,
        "focus_dist": dict(focus_counts.most_common()),
        "action_dist": dict(action_counts.most_common(10)),
    }


# ── Output helpers ─────────────────────────────────────────────────────────────

def write_jsonl(records: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def print_table(results: dict[str, dict]) -> None:
    variants = list(results.keys())
    col_w = 18

    header = f"{'Variant':<20}" + "".join(
        f"{'H_focus':>{col_w}}{'H_action':>{col_w}}{'act/cy':>{col_w}}"
        f"{'valence':>{col_w}}{'drive_std':>{col_w}}{'cycles':>{col_w}}"
    )
    divider = "-" * (20 + col_w * 6)

    print("\n" + divider)
    print(f"{'Variant':<20}{'H_focus':>{col_w}}{'H_action':>{col_w}}"
          f"{'act/cy':>{col_w}}{'valence':>{col_w}}{'drive_std':>{col_w}}"
          f"{'cycles':>{col_w}}")
    print(divider)

    for v in variants:
        m = results[v]
        print(
            f"{v:<20}"
            f"{m.get('h_focus', 0):>{col_w}.4f}"
            f"{m.get('h_action', 0):>{col_w}.4f}"
            f"{m.get('actions_per_cycle', 0):>{col_w}.3f}"
            f"{m.get('mean_valence', 0):>{col_w}.4f}"
            f"{m.get('mean_drive_std', 0):>{col_w}.4f}"
            f"{m.get('n', 0):>{col_w}}"
        )

    print(divider)
    print("H_focus  = Shannon entropy over routing_focus distribution")
    print("H_action = Shannon entropy over action type distribution")
    print("act/cy   = mean actions per cycle")
    print("valence  = mean mood_valence")
    print("drive_std = mean per-drive std deviation\n")


# ── Main ───────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ablation suite: 6 component-ablation variants × N cycles"
    )
    parser.add_argument("--cycles", type=int, default=1000,
                        help="Cycles per variant (default: 1000)")
    parser.add_argument("--variants", nargs="+", default=ALL_VARIANTS,
                        choices=ALL_VARIANTS,
                        help="Which variants to run (default: all)")
    parser.add_argument("--out-dir", default="experiments/ablation",
                        help="Output directory for JSONL and summary (default: experiments/ablation)")
    parser.add_argument("--seed", type=int, default=42,
                        help="Random seed (currently for future use)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    from clock import JST
    # Fixed start time: 2026-01-01 07:00 JST (canonical sim start)
    start_jst = datetime(2026, 1, 1, 7, 0, 0, tzinfo=JST)

    all_results: dict[str, dict] = {}
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    for variant in args.variants:
        print(f"\n{'='*60}")
        print(f"  VARIANT: {variant}  ({args.cycles} cycles)")
        print(f"{'='*60}")

        # Fresh temp DB per variant
        with tempfile.TemporaryDirectory(prefix=f"ablation_{variant}_") as tmpdir:
            db_path = str(Path(tmpdir) / "ablation.db")

            try:
                records = asyncio.run(
                    run_variant_sim(
                        variant=variant,
                        n_cycles=args.cycles,
                        sim_db_path=db_path,
                        start_jst=start_jst,
                    )
                )
            except Exception as e:
                print(f"  [{variant}] FAILED: {e}", flush=True)
                import traceback; traceback.print_exc()
                all_results[variant] = {"n": 0, "error": str(e)}
                continue

        # Save JSONL
        jsonl_path = out_dir / f"{variant}_{run_id}.jsonl"
        write_jsonl(records, jsonl_path)
        print(f"  [{variant}] Wrote {len(records)} records → {jsonl_path}")

        # Compute metrics
        metrics = compute_metrics(records)
        all_results[variant] = metrics
        n = metrics.get("n", 0)
        if n > 0:
            print(f"  [{variant}] H_focus={metrics['h_focus']:.4f}  "
                  f"H_action={metrics['h_action']:.4f}  "
                  f"act/cy={metrics['actions_per_cycle']:.3f}")
        else:
            print(f"  [{variant}] 0 logged cycles (all fidgets — will retry in full run)")

    # Summary JSON
    summary_path = out_dir / f"ablation_summary_{run_id}.json"
    with open(summary_path, "w") as f:
        json.dump({
            "run_id": run_id,
            "cycles_per_variant": args.cycles,
            "variants": args.variants,
            "results": all_results,
        }, f, indent=2)
    print(f"\n  Summary written → {summary_path}")

    # Print comparison table
    print_table({v: all_results[v] for v in args.variants if v in all_results})


if __name__ == "__main__":
    main()
