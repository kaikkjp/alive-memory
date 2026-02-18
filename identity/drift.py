"""identity.drift — Drift detection engine.

Compares current behavioral patterns against a rolling baseline.
Detects sustained divergence (not single-cycle noise) and emits
events when thresholds are crossed.

TASK-062: Drift is information, not correction.
"""

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional

import clock
import db
from models.event import Event

# ─── Config ───

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'drift_config.json')
_DATA_DIR = os.environ.get('SHOPKEEPER_DATA_DIR',
                           os.path.join(os.path.dirname(__file__), '..', 'data'))
_BASELINE_PATH = os.path.join(_DATA_DIR, 'self_model.json')

_EPSILON = 0.01  # Avoid division by zero


def _load_config() -> dict:
    """Load drift config from JSON file."""
    with open(_CONFIG_PATH, 'r') as f:
        return json.load(f)


# ─── Behavioral Baseline (self-model stub for TASK-061) ───

@dataclass
class BehavioralBaseline:
    """Minimal self-model: rolling averages of behavioral signals.

    When TASK-061 (persistent self-model) is implemented, this will be
    replaced by the full SelfModel class. For now, it tracks just enough
    to support drift detection.
    """
    action_frequencies: dict[str, float] = field(default_factory=dict)
    avg_dialogue_length: float = 0.0
    avg_mood_valence: float = 0.0
    avg_energy: float = 0.8
    avg_cycles_per_day: float = 0.0
    cycle_count: int = 0
    last_event_cycle: int = 0  # cycle_count when last drift event was emitted

    def save(self, path: str = _BASELINE_PATH) -> None:
        """Persist baseline to disk."""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            json.dump(asdict(self), f, indent=2)

    @classmethod
    def load(cls, path: str = _BASELINE_PATH) -> 'BehavioralBaseline':
        """Load baseline from disk. Returns fresh instance if not found."""
        if not os.path.exists(path):
            return cls()
        try:
            with open(path, 'r') as f:
                data = json.load(f)
            return cls(**data)
        except (json.JSONDecodeError, TypeError, KeyError):
            return cls()

    def update_from_window(self, window_actions: dict[str, float],
                           window_dialogue_len: float,
                           window_mood: float,
                           window_energy: float,
                           window_cycles_per_day: float,
                           alpha: float = 0.05) -> None:
        """Update baseline using exponential moving average.

        On first call (cycle_count < min_cycles), uses faster alpha to
        bootstrap the baseline quickly.
        """
        # Bootstrap phase: use faster alpha for first 10 cycles
        effective_alpha = min(alpha * 5, 0.5) if self.cycle_count < 10 else alpha

        # Action frequencies
        all_actions = set(self.action_frequencies) | set(window_actions)
        for action in all_actions:
            old = self.action_frequencies.get(action, 0.0)
            new = window_actions.get(action, 0.0)
            self.action_frequencies[action] = (
                old * (1 - effective_alpha) + new * effective_alpha
            )

        # Prune near-zero actions from baseline
        self.action_frequencies = {
            k: v for k, v in self.action_frequencies.items() if v > 0.001
        }

        # Scalar averages
        self.avg_dialogue_length = (
            self.avg_dialogue_length * (1 - effective_alpha)
            + window_dialogue_len * effective_alpha
        )
        self.avg_mood_valence = (
            self.avg_mood_valence * (1 - effective_alpha)
            + window_mood * effective_alpha
        )
        self.avg_energy = (
            self.avg_energy * (1 - effective_alpha)
            + window_energy * effective_alpha
        )
        self.avg_cycles_per_day = (
            self.avg_cycles_per_day * (1 - effective_alpha)
            + window_cycles_per_day * effective_alpha
        )

        self.cycle_count += 1


# ─── Drift Scoring ───

@dataclass
class DriftResult:
    """Result of a single drift check."""
    composite: float
    metrics: dict[str, float]
    level: str  # 'none' | 'notable' | 'significant'
    summary: Optional[str] = None


def _compute_action_frequency_drift(
    baseline_freqs: dict[str, float],
    window_freqs: dict[str, float],
) -> float:
    """Total variation distance between two frequency distributions.

    Returns value in [0, 1]. 0 = identical, 1 = completely different.
    """
    if not baseline_freqs and not window_freqs:
        return 0.0
    all_actions = set(baseline_freqs) | set(window_freqs)
    total_diff = sum(
        abs(baseline_freqs.get(a, 0.0) - window_freqs.get(a, 0.0))
        for a in all_actions
    )
    # TVD = sum(|p-q|) / 2, already normalized to [0, 1]
    return min(total_diff / 2.0, 1.0)


def _compute_scalar_drift(current: float, baseline: float) -> float:
    """Per-metric drift score for a scalar value.

    Returns abs(current - baseline) / max(|baseline|, epsilon), capped at 1.0.
    """
    denom = max(abs(baseline), _EPSILON)
    return min(abs(current - baseline) / denom, 1.0)


def _build_drift_summary(metrics: dict[str, float],
                          composite: float,
                          window_actions: dict[str, float],
                          baseline_actions: dict[str, float]) -> str:
    """Generate a natural language drift summary for self-context injection."""
    parts = []

    # Find the most drifted metric
    top_metric = max(metrics, key=metrics.get)

    if top_metric == 'action_frequency':
        # Find which actions changed most
        all_actions = set(baseline_actions) | set(window_actions)
        diffs = {}
        for a in all_actions:
            old = baseline_actions.get(a, 0.0)
            new = window_actions.get(a, 0.0)
            if abs(new - old) > 0.05:
                diffs[a] = new - old
        if diffs:
            biggest = max(diffs, key=lambda k: abs(diffs[k]))
            direction = 'more' if diffs[biggest] > 0 else 'less'
            action_label = biggest.replace('_', ' ')
            parts.append(f"I've been doing '{action_label}' {direction} than usual")
    elif top_metric == 'drive_response':
        parts.append("My emotional patterns have shifted from my usual baseline")
    elif top_metric == 'conversation_style':
        parts.append("My way of speaking has changed from how I usually communicate")
    elif top_metric == 'sleep_wake_rhythm':
        parts.append("My activity rhythm has been different from my usual pattern")

    if not parts:
        parts.append("My behavior has been different from my usual patterns")

    return parts[0]


# ─── Drift Detector ───

class DriftDetector:
    """Checks for behavioral drift after each cycle."""

    def __init__(self, config: Optional[dict] = None,
                 baseline_path: str = _BASELINE_PATH):
        self._config = config or _load_config()
        self._baseline_path = baseline_path
        self._baseline = BehavioralBaseline.load(baseline_path)
        self._last_result: Optional[DriftResult] = None

    @property
    def baseline(self) -> BehavioralBaseline:
        return self._baseline

    @property
    def last_result(self) -> Optional[DriftResult]:
        return self._last_result

    async def check(self, cycle_log: dict, drives) -> Optional[DriftResult]:
        """Run drift detection after a cycle completes.

        Args:
            cycle_log: The cycle log dict from run_cycle().
            drives: DrivesState after the cycle.

        Returns:
            DriftResult if drift was computed, None if insufficient data.
        """
        config = self._config
        window_size = config['window_size']
        min_cycles = config['min_cycles_for_detection']
        alpha = config.get('baseline_ema_alpha', 0.05)

        # ── Gather window data from DB ──
        window_data = await _query_recent_window(window_size)
        if not window_data['cycle_count']:
            return None

        window_actions = window_data['action_frequencies']
        window_dialogue_len = window_data['avg_dialogue_length']
        window_mood = window_data['avg_mood_valence']
        window_energy = window_data['avg_energy']
        window_cpd = window_data['cycles_per_day']

        # ── Not enough data for scoring yet? ──
        # We still update the baseline to bootstrap it, but skip scoring.
        next_cycle = self._baseline.cycle_count + 1
        if next_cycle <= min_cycles:
            self._baseline.update_from_window(
                window_actions=window_actions,
                window_dialogue_len=window_dialogue_len,
                window_mood=window_mood,
                window_energy=window_energy,
                window_cycles_per_day=window_cpd,
                alpha=alpha,
            )
            self._baseline.save(self._baseline_path)
            self._last_result = DriftResult(
                composite=0.0,
                metrics={k: 0.0 for k in config['metric_weights']},
                level='none',
            )
            return self._last_result

        # ── Compute per-metric drift BEFORE updating baseline ──
        # Scoring against the pre-update baseline prevents the current
        # window from damping its own divergence measurement.
        metrics = {}
        metrics['action_frequency'] = _compute_action_frequency_drift(
            self._baseline.action_frequencies, window_actions,
        )
        metrics['drive_response'] = (
            _compute_scalar_drift(window_mood, self._baseline.avg_mood_valence)
            + _compute_scalar_drift(window_energy, self._baseline.avg_energy)
        ) / 2.0
        metrics['conversation_style'] = _compute_scalar_drift(
            window_dialogue_len, self._baseline.avg_dialogue_length,
        )
        metrics['sleep_wake_rhythm'] = _compute_scalar_drift(
            window_cpd, self._baseline.avg_cycles_per_day,
        )

        # ── Composite ──
        weights = config['metric_weights']
        composite = sum(
            metrics.get(k, 0.0) * weights.get(k, 0.0)
            for k in weights
        )
        composite = min(composite, 1.0)

        # ── Determine level ──
        thresholds = config['thresholds']
        if composite >= thresholds['significant']:
            level = 'significant'
        elif composite >= thresholds['notable']:
            level = 'notable'
        else:
            level = 'none'

        # ── Build summary ──
        summary = None
        if level != 'none':
            summary = _build_drift_summary(
                metrics, composite, window_actions,
                self._baseline.action_frequencies,
            )

        result = DriftResult(
            composite=composite,
            metrics=metrics,
            level=level,
            summary=summary,
        )
        self._last_result = result

        # ── Emit event if above threshold and past cooldown ──
        cooldown = config['cooldown_cycles_between_events']
        cycles_since_event = (
            self._baseline.cycle_count - self._baseline.last_event_cycle
        )

        if level != 'none' and cycles_since_event > cooldown:
            event_type = f'drift_{level}'
            event = Event(
                event_type=event_type,
                source='self',
                channel='system',
                payload={
                    'composite': round(composite, 3),
                    'metrics': {k: round(v, 3) for k, v in metrics.items()},
                    'summary': summary or '',
                    'baseline_cycles': self._baseline.cycle_count,
                },
                salience_base=0.4 if level == 'notable' else 0.6,
            )
            await db.append_event(event)
            self._baseline.last_event_cycle = self._baseline.cycle_count
            print(f"  [Drift] {level} drift detected: composite={composite:.3f}")

        # ── Now update baseline EMA (after scoring) ──
        self._baseline.update_from_window(
            window_actions=window_actions,
            window_dialogue_len=window_dialogue_len,
            window_mood=window_mood,
            window_energy=window_energy,
            window_cycles_per_day=window_cpd,
            alpha=alpha,
        )

        # ── Persist ──
        self._baseline.save(self._baseline_path)

        return result

    def get_drift_summary(self) -> Optional[str]:
        """Return natural language drift summary if drift is currently active.

        Only returns text for significant drift (injected into self-context).
        """
        if self._last_result and self._last_result.level == 'significant':
            return self._last_result.summary
        return None


# ─── DB Queries ───

async def _query_recent_window(window_size: int) -> dict:
    """Query recent cycles from DB for drift computation.

    Returns aggregated window data: action frequencies, avg dialogue length,
    avg mood/energy, cycles per day.
    """
    conn = await db.get_db()

    # Get recent cycle logs
    cursor = await conn.execute(
        """SELECT dialogue, drives, ts
           FROM cycle_log
           ORDER BY ts DESC
           LIMIT ?""",
        (window_size,),
    )
    cycle_rows = await cursor.fetchall()

    if not cycle_rows:
        return {
            'cycle_count': 0,
            'action_frequencies': {},
            'avg_dialogue_length': 0.0,
            'avg_mood_valence': 0.0,
            'avg_energy': 0.0,
            'cycles_per_day': 0.0,
        }

    # Get recent executed actions
    cursor = await conn.execute(
        """SELECT action, COUNT(*) as cnt
           FROM action_log
           WHERE status = 'executed'
           AND cycle_id IN (
               SELECT id FROM cycle_log ORDER BY ts DESC LIMIT ?
           )
           GROUP BY action""",
        (window_size,),
    )
    action_rows = await cursor.fetchall()

    # Action frequencies (normalized)
    total_actions = sum(r['cnt'] for r in action_rows) if action_rows else 0
    action_freqs = {}
    if total_actions > 0:
        for r in action_rows:
            action_freqs[r['action']] = r['cnt'] / total_actions

    # Dialogue length
    dialogue_lengths = []
    mood_vals = []
    energy_vals = []
    for row in cycle_rows:
        dialogue = row['dialogue'] or ''
        dialogue_lengths.append(len(dialogue))
        try:
            drives_data = json.loads(row['drives']) if row['drives'] else {}
            mood_vals.append(drives_data.get('mood_valence', 0.0))
            energy_vals.append(drives_data.get('energy', 0.8))
        except (json.JSONDecodeError, TypeError):
            pass

    avg_dialogue = sum(dialogue_lengths) / len(dialogue_lengths) if dialogue_lengths else 0.0
    avg_mood = sum(mood_vals) / len(mood_vals) if mood_vals else 0.0
    avg_energy = sum(energy_vals) / len(energy_vals) if energy_vals else 0.8

    # Cycles per day estimate
    timestamps = []
    for row in cycle_rows:
        try:
            ts = datetime.fromisoformat(row['ts'])
            timestamps.append(ts)
        except (ValueError, TypeError):
            pass

    cycles_per_day = 0.0
    if len(timestamps) >= 2:
        time_span = (timestamps[0] - timestamps[-1]).total_seconds()
        if time_span > 0:
            days = time_span / 86400.0
            cycles_per_day = len(timestamps) / max(days, 0.01)

    return {
        'cycle_count': len(cycle_rows),
        'action_frequencies': action_freqs,
        'avg_dialogue_length': avg_dialogue,
        'avg_mood_valence': avg_mood,
        'avg_energy': avg_energy,
        'cycles_per_day': cycles_per_day,
    }


# ─── Module-level singleton ───

_detector: Optional[DriftDetector] = None


def get_detector(config: Optional[dict] = None,
                 baseline_path: str = _BASELINE_PATH) -> DriftDetector:
    """Get or create the module-level DriftDetector singleton."""
    global _detector
    if _detector is None:
        _detector = DriftDetector(config=config, baseline_path=baseline_path)
    return _detector


def reset_detector() -> None:
    """Reset the singleton (for testing)."""
    global _detector
    _detector = None


async def get_drift_state() -> dict:
    """Get current drift state for dashboard API.

    Returns dict with composite score, per-metric breakdown,
    baseline maturity, and level.
    """
    detector = get_detector()
    result = detector.last_result
    min_cycles = detector._config.get('min_cycles_for_detection', 10)

    baseline = detector.baseline
    if result is None:
        return {
            'composite': 0.0,
            'metrics': {
                'action_frequency': 0.0,
                'drive_response': 0.0,
                'conversation_style': 0.0,
                'sleep_wake_rhythm': 0.0,
            },
            'level': 'none',
            'summary': None,
            'baseline_cycles': baseline.cycle_count,
            'baseline_mature': baseline.cycle_count >= min_cycles,
        }

    return {
        'composite': round(result.composite, 3),
        'metrics': {k: round(v, 3) for k, v in result.metrics.items()},
        'level': result.level,
        'summary': result.summary,
        'baseline_cycles': baseline.cycle_count,
        'baseline_mature': baseline.cycle_count >= min_cycles,
    }
