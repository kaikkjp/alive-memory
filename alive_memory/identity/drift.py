"""Drift detection — detect when behavioral traits are changing.

Extracted from engine/identity/drift.py.
Enhanced with DriftDetector class, TVD metric, composite scoring,
configurable thresholds and cooldown.

Pure functions: tvd(), scalar_drift().
DriftDetector class: instantiate with config, call detect().
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from alive_memory.config import AliveConfig
from alive_memory.storage.base import BaseStorage

# ── Data types ────────────────────────────────────────────────────


@dataclass
class DriftReport:
    """Report of detected behavioral drift (backward compat)."""

    trait: str
    direction: str  # "increase" or "decrease"
    magnitude: float  # absolute change
    old_value: float
    new_value: float
    confidence: float  # 0-1, how confident the drift is real
    window_cycles: int  # how many cycles the window covers
    detected_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )


@dataclass
class DriftConfig:
    """Configuration for drift detection."""

    notable_threshold: float = 0.3
    significant_threshold: float = 0.6
    cooldown_cycles: int = 5
    baseline_window: int = 50


@dataclass
class BehavioralBaseline:
    """Rolling average baselines for drift comparison."""

    action_frequencies: dict[str, float] = field(default_factory=dict)
    scalar_metrics: dict[str, float] = field(default_factory=dict)
    sample_count: int = 0
    last_updated_cycle: int = 0


@dataclass
class MetricResult:
    """Result from a single drift metric computation."""

    name: str
    score: float  # 0-1 normalized drift score
    weight: float
    details: str = ""


@dataclass
class DriftResult:
    """Full drift detection result with per-metric breakdown."""

    composite_score: float
    severity: str  # "none", "notable", "significant"
    metric_results: list[MetricResult] = field(default_factory=list)
    summary: str = ""
    cycle: int = 0
    detected_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )


# ── Protocols ─────────────────────────────────────────────────────


class DriftMetric(Protocol):
    """Protocol for custom drift metrics."""

    name: str
    weight: float

    async def compute(
        self, current: dict[str, Any], baseline: dict[str, Any]
    ) -> float: ...


# ── Pure functions ────────────────────────────────────────────────


def tvd(p: dict[str, float], q: dict[str, float]) -> float:
    """Total Variation Distance between two frequency distributions.

    TVD = 0.5 * sum(|p_i - q_i|) for all keys in union(p, q).
    Returns 0-1.
    """
    if not p and not q:
        return 0.0
    all_keys = set(p) | set(q)
    return 0.5 * sum(abs(p.get(k, 0.0) - q.get(k, 0.0)) for k in all_keys)


def scalar_drift(
    current: float, baseline: float, range_size: float = 1.0
) -> float:
    """Normalized absolute difference for a continuous metric.

    Returns |current - baseline| / range_size, clamped to [0, 1].
    """
    if range_size <= 0:
        return 0.0
    return min(1.0, abs(current - baseline) / range_size)


# ── Built-in DriftMetric implementations ─────────────────────────


class TVDMetric:
    """Drift metric using Total Variation Distance for frequency distributions."""

    def __init__(self, name: str, weight: float, freq_key: str):
        self.name = name
        self.weight = weight
        self._freq_key = freq_key

    async def compute(
        self, current: dict[str, Any], baseline: dict[str, Any]
    ) -> float:
        return tvd(
            current.get(self._freq_key, {}),
            baseline.get(self._freq_key, {}),
        )


class ScalarDriftMetric:
    """Drift metric for continuous scalar values."""

    def __init__(
        self,
        name: str,
        weight: float,
        metric_key: str,
        range_size: float = 1.0,
    ):
        self.name = name
        self.weight = weight
        self._metric_key = metric_key
        self._range_size = range_size

    async def compute(
        self, current: dict[str, Any], baseline: dict[str, Any]
    ) -> float:
        return scalar_drift(
            current.get(self._metric_key, 0.0),
            baseline.get(self._metric_key, 0.0),
            self._range_size,
        )


# ── DriftDetector class ──────────────────────────────────────────


class DriftDetector:
    """Configurable drift detection with composite scoring."""

    def __init__(
        self,
        storage: BaseStorage,
        config: DriftConfig | None = None,
        metrics: list[Any] | None = None,
    ):
        self._storage = storage
        self._config = config or DriftConfig()
        self._metrics: list[Any] = metrics or []
        self._last_drift_cycle: int | None = None

    async def update_baseline(
        self, current_data: dict[str, Any], cycle: int
    ) -> BehavioralBaseline:
        """Update rolling baseline with new observations."""
        raw = await self._storage.get_drift_baseline()
        baseline = BehavioralBaseline(
            action_frequencies=raw.get("action_frequencies", {}),
            scalar_metrics=raw.get("scalar_metrics", {}),
            sample_count=raw.get("sample_count", 0),
            last_updated_cycle=raw.get("last_updated_cycle", 0),
        )

        n = baseline.sample_count + 1
        alpha = 1.0 / n if n < self._config.baseline_window else (
            2.0 / (self._config.baseline_window + 1)
        )

        # Update action frequencies if provided
        freq = current_data.get("action_frequencies")
        if isinstance(freq, dict):
            for k, v in freq.items():
                old = baseline.action_frequencies.get(k, float(v))
                baseline.action_frequencies[k] = alpha * float(v) + (1 - alpha) * old

        # Update scalar metrics
        for k, v in current_data.items():
            if k == "action_frequencies":
                continue
            if isinstance(v, (int, float)):
                old = baseline.scalar_metrics.get(k, v)
                baseline.scalar_metrics[k] = alpha * v + (1 - alpha) * old

        baseline.sample_count = n
        baseline.last_updated_cycle = cycle

        await self._storage.save_drift_baseline({
            "action_frequencies": baseline.action_frequencies,
            "scalar_metrics": baseline.scalar_metrics,
            "sample_count": baseline.sample_count,
            "last_updated_cycle": baseline.last_updated_cycle,
        })

        return baseline

    async def detect(
        self, current_data: dict[str, Any], cycle: int
    ) -> DriftResult:
        """Run all drift metrics, compute composite score, check thresholds."""
        raw = await self._storage.get_drift_baseline()
        baseline_data: dict[str, Any] = {
            "action_frequencies": raw.get("action_frequencies", {}),
            **raw.get("scalar_metrics", {}),
        }

        if not self._metrics:
            return DriftResult(
                composite_score=0.0,
                severity="none",
                summary="No drift metrics configured.",
                cycle=cycle,
            )

        # Run each metric
        results: list[MetricResult] = []
        for metric in self._metrics:
            score = await metric.compute(current_data, baseline_data)
            results.append(MetricResult(
                name=metric.name,
                score=score,
                weight=metric.weight,
                details=f"{metric.name}: {score:.3f}",
            ))

        # Composite weighted score
        total_weight = sum(r.weight for r in results)
        if total_weight > 0:
            composite = sum(r.score * r.weight for r in results) / total_weight
        else:
            composite = 0.0

        # Classify severity
        cfg = self._config
        if composite >= cfg.significant_threshold:
            severity = "significant"
        elif composite >= cfg.notable_threshold:
            severity = "notable"
        else:
            severity = "none"

        # Check cooldown (skip on first detection)
        if (
            severity != "none"
            and self._last_drift_cycle is not None
            and cycle - self._last_drift_cycle < cfg.cooldown_cycles
        ):
            severity = "none"

        summary = self._build_summary(results, severity)

        # Log drift event if notable+
        if severity != "none":
            self._last_drift_cycle = cycle
            await self._storage.log_evolution_decision({
                "action": "drift_detected",
                "trait": "composite",
                "reason": summary,
                "composite_score": composite,
                "severity": severity,
                "cycle": cycle,
            })

        return DriftResult(
            composite_score=composite,
            severity=severity,
            metric_results=results,
            summary=summary,
            cycle=cycle,
        )

    def _build_summary(
        self, results: list[MetricResult], severity: str
    ) -> str:
        """Build natural language summary from metric results."""
        if severity == "none":
            return "No significant drift detected."

        parts = [f"Drift severity: {severity}."]
        top = sorted(results, key=lambda r: r.score * r.weight, reverse=True)
        for r in top[:3]:
            if r.score > 0:
                parts.append(f"{r.name} drift={r.score:.2f} (weight={r.weight:.1f})")
        return " ".join(parts)


# ── Backward-compatible free function ────────────────────────────


async def detect_drift(
    storage: BaseStorage,
    *,
    config: AliveConfig | None = None,
) -> list[DriftReport]:
    """Detect behavioral drift by comparing current traits to recent history.

    Backward compat: reads from model.drift_history directly.
    """
    cfg = config or AliveConfig()
    threshold = cfg.get("identity.drift_threshold", 0.15)
    window = cfg.get("identity.drift_window", 50)

    model = await storage.get_self_model()
    reports: list[DriftReport] = []

    if not model.drift_history:
        return reports

    # Group drift events by trait
    trait_deltas: dict[str, list[dict]] = {}
    for entry in model.drift_history[-window:]:
        trait = entry.get("trait", "")
        if trait:
            trait_deltas.setdefault(trait, []).append(entry)

    for trait, deltas in trait_deltas.items():
        if len(deltas) < 2:
            continue

        # Compute net drift
        total_delta = sum(d.get("delta", 0) for d in deltas)
        magnitude = abs(total_delta)

        if magnitude >= threshold:
            # Compute consistency (are all deltas in the same direction?)
            same_direction = sum(
                1 for d in deltas
                if (d.get("delta", 0) > 0) == (total_delta > 0)
            )
            consistency = same_direction / len(deltas)
            confidence = min(1.0, consistency * (magnitude / threshold))

            current = model.traits.get(trait, 0.5)
            old_value = current - total_delta

            reports.append(DriftReport(
                trait=trait,
                direction="increase" if total_delta > 0 else "decrease",
                magnitude=magnitude,
                old_value=old_value,
                new_value=current,
                confidence=confidence,
                window_cycles=len(deltas),
            ))

    return reports
