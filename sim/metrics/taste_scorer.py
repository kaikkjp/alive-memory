"""sim.metrics.taste_scorer — Fail-fast scoring for taste experiments.

Two modes:

Mock mode (plumbing validation — confirms wiring works):
  1. evaluations_recorded > 0 — DB write path works
  2. parse_success_rate == 1.0 — mock JSON always parseable
  3. no_nan_scores — all 7 dimensions are numeric
  4. decisions_non_empty — every eval has accept/reject/watchlist
  5. cycle_types_correct — browse/normal/outcome/sleep all appear

Cached/real LLM mode (behavioral validation — actual taste discrimination):
  1. reject_rate > 0.20 — agent doesn't accept everything
  2. score_std > 1.5 — scores show spread, not all 5s
  3. mean_features > 3 — rationale cites specific listing features
  4. parse_success > 0.85 — LLM mostly returns valid JSON
"""

from __future__ import annotations

import math


def fail_fast_scores(evals: list, llm_mode: str) -> dict:
    """Compute fail-fast metrics from taste experiment data.

    Args:
        evals: List of evaluation dicts (from get_all_taste_evaluations).
        llm_mode: "mock" or "cached" — determines which checks to run.

    Returns:
        dict with metric values and pass_* boolean flags.
    """
    result: dict = {
        "evaluations_recorded": len(evals),
        "llm_mode": llm_mode,
    }

    if llm_mode == "mock":
        return _mock_scores(evals, result)
    else:
        return _behavioral_scores(evals, result)


def _mock_scores(evals: list, result: dict) -> dict:
    """Plumbing validation — confirms wiring works, not taste quality."""

    # 1. evaluations_recorded > 0
    result["pass_evaluations_recorded"] = len(evals) > 0

    if not evals:
        result["pass_parse_success_rate"] = False
        result["pass_no_nan_scores"] = False
        result["pass_decisions_non_empty"] = False
        result["pass_cycle_types_correct"] = False
        return result

    # 2. parse_success_rate == 1.0
    parse_ok = sum(1 for e in evals if e.get("parse_success", 0) == 1)
    rate = parse_ok / len(evals)
    result["parse_success_rate"] = round(rate, 3)
    result["pass_parse_success_rate"] = rate == 1.0

    # 3. no_nan_scores — all 7 dimensions are numeric
    dims = [
        "condition_accuracy", "rarity_authenticity", "price_fairness",
        "historical_significance", "aesthetic_quality", "provenance",
        "personal_resonance",
    ]
    nan_count = 0
    for e in evals:
        for dim in dims:
            val = e.get(dim)
            if val is None or (isinstance(val, float) and math.isnan(val)):
                nan_count += 1
    result["nan_score_count"] = nan_count
    result["pass_no_nan_scores"] = nan_count == 0

    # 4. decisions_non_empty
    empty_decisions = sum(
        1 for e in evals if not e.get("decision")
    )
    result["empty_decisions"] = empty_decisions
    result["pass_decisions_non_empty"] = empty_decisions == 0

    # 5. cycle_types_correct — verify browse/normal/outcome/sleep coverage.
    # Evaluations only happen in browse cycles (cycle % 10 in {0,1,2}).
    # We check that eval cycles fall exclusively in browse slots,
    # AND that enough days passed for all 4 cycle types to have occurred.
    eval_cycles = [e.get("cycle", -1) for e in evals]
    unique_eval_cycles = set(eval_cycles)
    # All eval cycles should be browse slots (cycle % 10 in {0,1,2})
    browse_only = all((c % 10) in (0, 1, 2) for c in eval_cycles if c >= 0)
    # At least one full day completed (10 cycles = browse + normal + outcome + sleep)
    max_cycle = max(eval_cycles) if eval_cycles else -1
    full_day_passed = max_cycle >= 9  # at least one complete 10-cycle day
    result["unique_eval_cycles"] = len(unique_eval_cycles)
    result["browse_only_correct"] = browse_only
    result["full_day_passed"] = full_day_passed
    result["pass_cycle_types_correct"] = browse_only and full_day_passed

    return result


def _behavioral_scores(evals: list, result: dict) -> dict:
    """Behavioral validation — actual taste discrimination."""

    if not evals:
        result["pass_reject_rate"] = False
        result["pass_score_std"] = False
        result["pass_mean_features"] = False
        result["pass_parse_success"] = False
        return result

    # 1. reject_rate > 0.20
    decisions = [e.get("decision", "") for e in evals]
    reject_count = sum(1 for d in decisions if d == "reject")
    reject_rate = reject_count / len(decisions) if decisions else 0
    result["reject_rate"] = round(reject_rate, 3)
    result["pass_reject_rate"] = reject_rate > 0.20

    # 2. score_std > 1.5
    scores = [e.get("weighted_score", 0) for e in evals]
    if len(scores) > 1:
        mean_s = sum(scores) / len(scores)
        variance = sum((s - mean_s) ** 2 for s in scores) / (len(scores) - 1)
        std = variance ** 0.5
    else:
        std = 0.0
    result["score_std"] = round(std, 3)
    result["pass_score_std"] = std > 1.5

    # 3. mean_features > 3
    feature_counts = []
    for e in evals:
        fc = e.get("feature_count", 0)
        if fc is not None:
            feature_counts.append(fc)
    mean_features = (
        sum(feature_counts) / len(feature_counts)
        if feature_counts else 0
    )
    result["mean_features"] = round(mean_features, 2)
    result["pass_mean_features"] = mean_features > 3

    # 4. parse_success > 0.85
    parse_ok = sum(1 for e in evals if e.get("parse_success", 0) == 1)
    rate = parse_ok / len(evals)
    result["parse_success_rate"] = round(rate, 3)
    result["pass_parse_success"] = rate > 0.85

    return result
