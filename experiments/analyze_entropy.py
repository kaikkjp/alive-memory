"""Analyze behavioral entropy from exported cycle JSONL files.

Computes Shannon entropy H(A) = -sum(p(a) * log2(p(a))) over routing_focus
and action distributions. Generates a multi-panel matplotlib figure.

Usage:
    python -m experiments.analyze_entropy --isolation experiments/logs/run.jsonl --baseline experiments/logs/baseline.jsonl
"""

import argparse
import json
import math
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


# ─── Entropy computation ───

def shannon_entropy(counts: Counter) -> float:
    """Compute Shannon entropy H = -sum(p * log2(p)) from a Counter of category counts."""
    total = sum(counts.values())
    if total == 0:
        return 0.0
    h = 0.0
    for count in counts.values():
        if count > 0:
            p = count / total
            h -= p * math.log2(p)
    return h


def load_jsonl(path: str) -> list[dict]:
    """Load a JSONL file into a list of dicts."""
    records = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records


# ─── Sliding window analysis ───

def sliding_window_entropy(
    records: list[dict],
    key: str,
    window_hours: float = 24.0,
    step_hours: float = 4.0,
    flatten_actions: bool = False,
) -> tuple[list[float], list[float]]:
    """Compute entropy over sliding time windows.

    Returns (center_hours, entropies) where center_hours is the center of each window.
    If flatten_actions=True, the key field is treated as a list and each element is counted.
    """
    if not records:
        return [], []

    max_hours = max(r["elapsed_hours"] for r in records)
    centers = []
    entropies = []

    start = 0.0
    while start + window_hours <= max_hours + step_hours:
        end = start + window_hours
        center = start + window_hours / 2.0

        counts = Counter()
        for r in records:
            if start <= r["elapsed_hours"] < end:
                if flatten_actions:
                    vals = r.get(key, [])
                    if not vals:
                        counts["_none_"] += 1
                    else:
                        for v in vals:
                            counts[v] += 1
                else:
                    counts[r.get(key, "unknown")] += 1

        if sum(counts.values()) > 0:
            centers.append(center)
            entropies.append(shannon_entropy(counts))

        start += step_hours

    return centers, entropies


def compute_block_distributions(
    records: list[dict],
    block_hours: float = 24.0,
) -> tuple[list[float], list[dict[str, int]]]:
    """Compute routing_focus distribution per time block.

    Returns (block_starts, block_counts) where block_counts is a list of Counters.
    """
    if not records:
        return [], []

    max_hours = max(r["elapsed_hours"] for r in records)
    block_starts = []
    block_counts = []

    start = 0.0
    while start < max_hours:
        end = start + block_hours
        counts = Counter()
        for r in records:
            if start <= r["elapsed_hours"] < end:
                counts[r.get("routing_focus", "idle")] += 1

        if sum(counts.values()) > 0:
            block_starts.append(start)
            block_counts.append(dict(counts))

        start += block_hours

    return block_starts, block_counts


def extract_drive_trajectories(records: list[dict]) -> dict[str, tuple[list[float], list[float]]]:
    """Extract drive values over time.

    Returns {drive_name: (hours, values)}.
    """
    drive_names = [
        "social_hunger", "curiosity", "expression_need",
        "rest_need", "energy", "mood_valence", "mood_arousal",
    ]
    trajectories = {}
    for name in drive_names:
        hours = []
        values = []
        for r in records:
            drives = r.get("drives", {})
            if name in drives:
                hours.append(r["elapsed_hours"])
                values.append(drives[name])
        trajectories[name] = (hours, values)
    return trajectories


# ─── Summary statistics ───

def compute_summary(records: list[dict], baseline: list[dict]) -> dict:
    """Compute summary statistics for stdout."""
    # Coarse entropy over full run
    focus_counts = Counter(r.get("routing_focus", "idle") for r in records)
    coarse_h = shannon_entropy(focus_counts)

    # Fine entropy over full run (actions)
    action_counts = Counter()
    for r in records:
        actions = r.get("actions", [])
        if not actions:
            action_counts["_none_"] += 1
        else:
            for a in actions:
                action_counts[a] += 1
    fine_h = shannon_entropy(action_counts)

    # Sliding window coarse entropy stats
    _, window_entropies = sliding_window_entropy(records, "routing_focus")
    if window_entropies:
        mean_h = np.mean(window_entropies)
        std_h = np.std(window_entropies)
    else:
        mean_h = 0.0
        std_h = 0.0

    # Baseline entropy
    baseline_focus = Counter(r.get("routing_focus", "idle") for r in baseline)
    baseline_h = shannon_entropy(baseline_focus)

    # Drive ranges
    drive_ranges = {}
    for name in ["social_hunger", "curiosity", "expression_need", "rest_need", "energy", "mood_valence", "mood_arousal"]:
        vals = [r["drives"].get(name, 0.0) for r in records if "drives" in r]
        if vals:
            drive_ranges[name] = {"min": round(min(vals), 3), "max": round(max(vals), 3)}

    # Counts
    budget_rest_count = sum(1 for r in records if r.get("is_budget_rest"))
    habit_fire_count = sum(1 for r in records if r.get("is_habit_fired"))

    # Per-day action counts (24h blocks)
    max_hours = max(r["elapsed_hours"] for r in records) if records else 0
    num_days = max(1, int(max_hours / 24) + 1)
    daily_action_counts = [0] * num_days
    for r in records:
        day_idx = min(int(r["elapsed_hours"] / 24), num_days - 1)
        daily_action_counts[day_idx] += len(r.get("actions", []))

    return {
        "cycle_count": len(records),
        "coarse_entropy_full": round(coarse_h, 4),
        "fine_entropy_full": round(fine_h, 4),
        "mean_coarse_entropy_windowed": round(float(mean_h), 4),
        "std_coarse_entropy_windowed": round(float(std_h), 4),
        "max_possible_coarse_entropy": round(math.log2(max(len(focus_counts), 1)), 4),
        "max_possible_fine_entropy": round(math.log2(max(len(action_counts), 1)), 4),
        "focus_distribution": dict(focus_counts.most_common()),
        "action_distribution": dict(action_counts.most_common()),
        "drive_ranges": drive_ranges,
        "budget_rest_count": budget_rest_count,
        "habit_fire_count": habit_fire_count,
        "daily_action_counts": daily_action_counts,
        "baseline_entropy": round(baseline_h, 4),
    }


# ─── Figure generation ───

FOCUS_CATEGORIES = ["idle", "rest", "express", "consume", "thread", "news", "engage", "nap"]
FOCUS_COLORS = {
    "idle": "#7eb3c9",
    "rest": "#b8b8b8",
    "express": "#e8a87c",
    "consume": "#85c88a",
    "thread": "#c9a0dc",
    "news": "#f0d264",
    "engage": "#e06060",
    "nap": "#6b7b8d",
}

DRIVE_COLORS = {
    "social_hunger": "#e06060",
    "curiosity": "#7eb3c9",
    "expression_need": "#e8a87c",
    "rest_need": "#b8b8b8",
    "energy": "#85c88a",
    "mood_valence": "#c9a0dc",
    "mood_arousal": "#f0d264",
}


def generate_figure(
    records: list[dict],
    baseline: list[dict],
    out_path: str,
) -> str:
    """Generate the multi-panel entropy figure. Returns the output path."""
    fig, axes = plt.subplots(3, 1, figsize=(14, 14), constrained_layout=True)
    fig.suptitle("Shopkeeper Isolation Experiment — Behavioral Diversity", fontsize=14, fontweight="bold")

    # Panel 1: Coarse entropy over time (sliding window)
    ax1 = axes[0]
    centers_iso, h_iso = sliding_window_entropy(records, "routing_focus")
    centers_bl, h_bl = sliding_window_entropy(baseline, "routing_focus")

    n_focus = len(set(r.get("routing_focus", "idle") for r in records))
    max_h = math.log2(max(n_focus, 2))

    ax1.plot(centers_iso, h_iso, "o-", color="#e06060", linewidth=2, markersize=4, label="Shopkeeper")
    if centers_bl:
        ax1.plot(centers_bl, h_bl, "s--", color="#b8b8b8", linewidth=1.5, markersize=3, label="Baseline (null)")
    ax1.axhline(y=max_h, color="#cccccc", linestyle=":", alpha=0.6, label=f"Max H = {max_h:.2f} bits")
    ax1.set_xlabel("Elapsed Hours")
    ax1.set_ylabel("Action Entropy H(A) (bits)")
    ax1.set_ylim(0, max_h * 1.15)
    ax1.set_title("Coarse Entropy (routing_focus, 24h sliding window)")
    ax1.legend(loc="upper right")
    ax1.grid(True, alpha=0.3)

    # Panel 2: Stacked bar — routing_focus distribution per 24h block
    ax2 = axes[1]
    block_starts, block_counts = compute_block_distributions(records)

    if block_starts:
        all_cats = sorted(set(cat for bc in block_counts for cat in bc), key=lambda c: FOCUS_CATEGORIES.index(c) if c in FOCUS_CATEGORIES else 99)
        bottoms = np.zeros(len(block_starts))
        bar_width = 20  # slightly less than 24 for visual spacing

        for cat in all_cats:
            vals = [bc.get(cat, 0) for bc in block_counts]
            color = FOCUS_COLORS.get(cat, "#999999")
            ax2.bar(block_starts, vals, bottom=bottoms, width=bar_width, label=cat, color=color, edgecolor="white", linewidth=0.5)
            bottoms += np.array(vals)

        ax2.set_xlabel("Elapsed Hours")
        ax2.set_ylabel("Cycle Count")
        ax2.set_title("Routing Focus Distribution (24h blocks)")
        ax2.legend(loc="upper right", ncol=4, fontsize=8)
        ax2.grid(True, alpha=0.3, axis="y")

    # Panel 3: Drive trajectories
    ax3 = axes[2]
    trajectories = extract_drive_trajectories(records)

    for name, (hours, values) in trajectories.items():
        if hours:
            color = DRIVE_COLORS.get(name, "#999999")
            ax3.plot(hours, values, linewidth=1.2, alpha=0.8, color=color, label=name)

    ax3.set_xlabel("Elapsed Hours")
    ax3.set_ylabel("Drive Value")
    ax3.set_ylim(-0.1, 1.1)
    ax3.set_title("Drive Trajectories Over Time")
    ax3.legend(loc="upper right", ncol=4, fontsize=8)
    ax3.grid(True, alpha=0.3)

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out_path


# ─── Fine-grained action histogram (optional Panel 4) ───

def generate_action_histogram(records: list[dict], out_path: str) -> str:
    """Generate a standalone action type histogram. Returns the output path."""
    action_counts = Counter()
    for r in records:
        for a in r.get("actions", []):
            action_counts[a] += 1
    if not action_counts:
        action_counts["_none_"] = len(records)

    fig, ax = plt.subplots(figsize=(12, 5), constrained_layout=True)
    labels, counts = zip(*action_counts.most_common())
    x = np.arange(len(labels))
    ax.bar(x, counts, color="#7eb3c9", edgecolor="white")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=9)
    ax.set_ylabel("Count")
    ax.set_title("Action Type Distribution (Full Run)")
    ax.grid(True, alpha=0.3, axis="y")

    hist_path = out_path.replace(".png", "_actions.png")
    Path(hist_path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(hist_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return hist_path


# ─── Main ───

def print_summary(summary: dict) -> None:
    """Print summary statistics to stdout."""
    print("\n=== Isolation Experiment Summary ===\n")
    print(f"  Cycles:           {summary['cycle_count']}")
    print(f"  Budget rest:      {summary['budget_rest_count']}")
    print(f"  Habit fires:      {summary['habit_fire_count']}")
    print(f"\n  Coarse entropy (full run): {summary['coarse_entropy_full']:.4f} bits")
    print(f"  Max possible:              {summary['max_possible_coarse_entropy']:.4f} bits")
    print(f"  Mean coarse (windowed):    {summary['mean_coarse_entropy_windowed']:.4f} +/- {summary['std_coarse_entropy_windowed']:.4f}")
    print(f"\n  Fine entropy (full run):   {summary['fine_entropy_full']:.4f} bits")
    print(f"  Max possible:              {summary['max_possible_fine_entropy']:.4f} bits")
    print(f"\n  Baseline entropy:          {summary['baseline_entropy']:.4f} bits")
    print(f"\n  Focus distribution:")
    for focus, count in summary["focus_distribution"].items():
        print(f"    {focus:12s}: {count}")
    print(f"\n  Action distribution:")
    for action, count in summary["action_distribution"].items():
        print(f"    {action:20s}: {count}")
    print(f"\n  Drive ranges:")
    for drive, rng in summary["drive_ranges"].items():
        print(f"    {drive:20s}: [{rng['min']:.3f}, {rng['max']:.3f}]")
    print(f"\n  Daily action counts: {summary['daily_action_counts']}")
    print()


def main():
    parser = argparse.ArgumentParser(description="Analyze behavioral entropy from exported cycles")
    parser.add_argument("--isolation", required=True, help="Isolation run JSONL")
    parser.add_argument("--baseline", required=True, help="Baseline JSONL")
    parser.add_argument("--out", default=None, help="Output figure path (default: auto-timestamped)")
    args = parser.parse_args()

    for path in [args.isolation, args.baseline]:
        if not Path(path).exists():
            print(f"[Entropy] File not found: {path}", file=sys.stderr)
            sys.exit(1)

    records = load_jsonl(args.isolation)
    baseline = load_jsonl(args.baseline)

    if not records:
        print("[Entropy] No records in isolation file.", file=sys.stderr)
        sys.exit(1)

    summary = compute_summary(records, baseline)
    print_summary(summary)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = args.out or f"experiments/figures/entropy_{timestamp}.png"

    fig_path = generate_figure(records, baseline, out_path)
    print(f"[Entropy] Main figure saved to {fig_path}")

    hist_path = generate_action_histogram(records, out_path)
    print(f"[Entropy] Action histogram saved to {hist_path}")


if __name__ == "__main__":
    main()
