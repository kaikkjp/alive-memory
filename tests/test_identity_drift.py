"""Tests for enhanced drift detection (TVD, scalar drift, DriftDetector)."""

from __future__ import annotations

import os
import tempfile

import pytest

from alive_memory.identity.drift import (
    DriftConfig,
    DriftDetector,
    ScalarDriftMetric,
    TVDMetric,
    detect_drift,
    scalar_drift,
    tvd,
)
from alive_memory.storage.sqlite import SQLiteStorage


@pytest.fixture
def tmp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    os.unlink(path)


@pytest.fixture
async def storage(tmp_db):
    s = SQLiteStorage(tmp_db)
    await s.initialize()
    yield s
    await s.close()


# ── TVD pure function ────────────────────────────────────────────


def test_tvd_identical_distributions():
    assert tvd({"a": 0.5, "b": 0.5}, {"a": 0.5, "b": 0.5}) == 0.0


def test_tvd_completely_different():
    assert tvd({"a": 1.0}, {"b": 1.0}) == pytest.approx(1.0)


def test_tvd_partial_overlap():
    # p = {a: 0.7, b: 0.3}, q = {a: 0.3, b: 0.7}
    # TVD = 0.5 * (|0.7-0.3| + |0.3-0.7|) = 0.5 * (0.4 + 0.4) = 0.4
    result = tvd({"a": 0.7, "b": 0.3}, {"a": 0.3, "b": 0.7})
    assert result == pytest.approx(0.4, abs=0.001)


def test_tvd_empty_distributions():
    assert tvd({}, {}) == 0.0


def test_tvd_one_empty():
    # p = {a: 1.0}, q = {} → TVD = 0.5 * |1.0| = 0.5
    assert tvd({"a": 1.0}, {}) == pytest.approx(0.5)


# ── Scalar drift pure function ──────────────────────────────────


def test_scalar_drift_no_change():
    assert scalar_drift(0.5, 0.5) == 0.0


def test_scalar_drift_full_range():
    assert scalar_drift(0.0, 1.0) == pytest.approx(1.0)


def test_scalar_drift_custom_range():
    assert scalar_drift(0.0, 1.0, range_size=2.0) == pytest.approx(0.5)


def test_scalar_drift_clamped():
    # With range_size=0.5, drift=1.0 → 1.0/0.5=2.0 → clamped to 1.0
    assert scalar_drift(0.0, 1.0, range_size=0.5) == 1.0


def test_scalar_drift_zero_range():
    assert scalar_drift(0.0, 1.0, range_size=0.0) == 0.0


# ── DriftDetector with no metrics ───────────────────────────────


@pytest.mark.asyncio
async def test_drift_detector_no_metrics(storage):
    detector = DriftDetector(storage, metrics=[])
    result = await detector.detect({}, cycle=1)
    assert result.composite_score == 0.0
    assert result.severity == "none"


# ── DriftDetector with single metric ────────────────────────────


@pytest.mark.asyncio
async def test_drift_detector_single_metric(storage):
    # Set up baseline
    await storage.save_drift_baseline({
        "action_frequencies": {"greet": 0.5, "trade": 0.5},
        "scalar_metrics": {},
        "sample_count": 10,
        "last_updated_cycle": 5,
    })

    metric = TVDMetric("action_freq", weight=1.0, freq_key="action_frequencies")
    detector = DriftDetector(storage, metrics=[metric])

    # Completely different distribution
    result = await detector.detect(
        {"action_frequencies": {"greet": 0.0, "trade": 0.0, "fight": 1.0}},
        cycle=10,
    )
    assert result.composite_score > 0
    assert result.metric_results[0].name == "action_freq"


# ── DriftDetector composite scoring ─────────────────────────────


@pytest.mark.asyncio
async def test_drift_detector_composite_scoring(storage):
    await storage.save_drift_baseline({
        "action_frequencies": {"greet": 0.5, "trade": 0.5},
        "scalar_metrics": {"energy": 0.5},
        "sample_count": 10,
        "last_updated_cycle": 5,
    })

    m1 = TVDMetric("action_freq", weight=0.6, freq_key="action_frequencies")
    m2 = ScalarDriftMetric("energy", weight=0.4, metric_key="energy")
    detector = DriftDetector(storage, metrics=[m1, m2])

    result = await detector.detect(
        {"action_frequencies": {"greet": 1.0, "trade": 0.0}, "energy": 0.8},
        cycle=10,
    )
    # Composite = (tvd * 0.6 + scalar * 0.4) / (0.6 + 0.4)
    assert len(result.metric_results) == 2
    assert result.composite_score >= 0.0


# ── DriftDetector threshold classification ───────────────────────


@pytest.mark.asyncio
async def test_drift_detector_notable_threshold(storage):
    await storage.save_drift_baseline({
        "action_frequencies": {"a": 0.5, "b": 0.5},
        "scalar_metrics": {},
        "sample_count": 10,
        "last_updated_cycle": 0,
    })

    # TVD of {a:1.0} vs {a:0.5, b:0.5} = 0.5 * (|1.0-0.5| + |0.0-0.5|) = 0.5
    # Composite = 0.5, above notable=0.3 but below significant=0.6
    metric = TVDMetric("freq", weight=1.0, freq_key="action_frequencies")
    config = DriftConfig(notable_threshold=0.3, significant_threshold=0.6)
    detector = DriftDetector(storage, config=config, metrics=[metric])

    result = await detector.detect(
        {"action_frequencies": {"a": 1.0}},
        cycle=10,
    )
    assert result.severity == "notable"


@pytest.mark.asyncio
async def test_drift_detector_significant_threshold(storage):
    await storage.save_drift_baseline({
        "action_frequencies": {"a": 1.0},
        "scalar_metrics": {},
        "sample_count": 10,
        "last_updated_cycle": 0,
    })

    # TVD of {b:1.0} vs {a:1.0} = 0.5 * (1.0 + 1.0) = 1.0
    metric = TVDMetric("freq", weight=1.0, freq_key="action_frequencies")
    config = DriftConfig(notable_threshold=0.3, significant_threshold=0.6)
    detector = DriftDetector(storage, config=config, metrics=[metric])

    result = await detector.detect(
        {"action_frequencies": {"b": 1.0}},
        cycle=10,
    )
    assert result.severity == "significant"


# ── DriftDetector cooldown ───────────────────────────────────────


@pytest.mark.asyncio
async def test_drift_detector_cooldown(storage):
    await storage.save_drift_baseline({
        "action_frequencies": {"a": 1.0},
        "scalar_metrics": {},
        "sample_count": 10,
        "last_updated_cycle": 0,
    })

    metric = TVDMetric("freq", weight=1.0, freq_key="action_frequencies")
    config = DriftConfig(cooldown_cycles=5)
    detector = DriftDetector(storage, config=config, metrics=[metric])

    # First detect — should trigger
    r1 = await detector.detect({"action_frequencies": {"b": 1.0}}, cycle=1)
    assert r1.severity != "none"

    # Second detect within cooldown — should be "none"
    r2 = await detector.detect({"action_frequencies": {"b": 1.0}}, cycle=3)
    assert r2.severity == "none"

    # After cooldown passes
    r3 = await detector.detect({"action_frequencies": {"b": 1.0}}, cycle=7)
    assert r3.severity != "none"


# ── DriftDetector baseline update ────────────────────────────────


@pytest.mark.asyncio
async def test_drift_detector_baseline_update(storage):
    detector = DriftDetector(storage)
    baseline = await detector.update_baseline(
        {"action_frequencies": {"greet": 0.8, "trade": 0.2}, "energy": 0.7},
        cycle=1,
    )
    assert baseline.sample_count == 1
    assert baseline.last_updated_cycle == 1
    assert "greet" in baseline.action_frequencies
    assert "energy" in baseline.scalar_metrics

    # Second update should blend
    baseline2 = await detector.update_baseline(
        {"action_frequencies": {"greet": 0.2, "trade": 0.8}, "energy": 0.3},
        cycle=2,
    )
    assert baseline2.sample_count == 2
    # Greet should have moved toward 0.2
    assert baseline2.action_frequencies["greet"] < 0.8


# ── DriftDetector summary builder ────────────────────────────────


@pytest.mark.asyncio
async def test_drift_detector_summary_builder(storage):
    await storage.save_drift_baseline({
        "action_frequencies": {"a": 1.0},
        "scalar_metrics": {},
        "sample_count": 10,
        "last_updated_cycle": 0,
    })

    metric = TVDMetric("freq", weight=1.0, freq_key="action_frequencies")
    detector = DriftDetector(storage, metrics=[metric])

    result = await detector.detect({"action_frequencies": {"b": 1.0}}, cycle=10)
    assert isinstance(result.summary, str)
    assert len(result.summary) > 0


# ── Backward-compat detect_drift ─────────────────────────────────


@pytest.mark.asyncio
async def test_backward_compat_detect_drift(storage):
    reports = await detect_drift(storage)
    assert reports == []


@pytest.mark.asyncio
async def test_backward_compat_detect_drift_with_history(storage):
    model = await storage.get_self_model()
    model.traits = {"warmth": 0.8}
    model.drift_history = [
        {"trait": "warmth", "delta": 0.1},
        {"trait": "warmth", "delta": 0.1},
        {"trait": "warmth", "delta": 0.1},
    ]
    await storage.save_self_model(model)

    reports = await detect_drift(storage)
    assert len(reports) == 1
    assert reports[0].trait == "warmth"
    assert reports[0].direction == "increase"


# ── DriftConfig from AliveConfig ─────────────────────────────────


def test_drift_config_from_alive_config():
    from alive_memory.config import AliveConfig
    cfg = AliveConfig()
    dc = DriftConfig(
        notable_threshold=cfg.get("identity.notable_threshold", 0.3),
        significant_threshold=cfg.get("identity.significant_threshold", 0.6),
        cooldown_cycles=cfg.get("identity.cooldown_cycles", 5),
    )
    assert dc.notable_threshold == 0.3
    assert dc.significant_threshold == 0.6
    assert dc.cooldown_cycles == 5
