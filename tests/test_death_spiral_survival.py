import math

from experiments.death_spiral_survival import fit_aft_logtime_binary, fit_cox_binary


def test_collapse_models_show_protection_when_group1_lasts_longer():
    # group=1 has later collapse times than group=0
    rows = [
        {"time": 3, "event": 1, "group": 0},
        {"time": 4, "event": 1, "group": 0},
        {"time": 5, "event": 1, "group": 0},
        {"time": 8, "event": 1, "group": 1},
        {"time": 9, "event": 1, "group": 1},
        {"time": 10, "event": 1, "group": 1},
    ]

    cox = fit_cox_binary(rows)
    aft = fit_aft_logtime_binary(rows)

    assert cox["ok"] is True
    assert aft["ok"] is True
    assert cox["hazard_ratio"] < 1.0
    assert aft["acceleration_factor"] > 1.0


def test_recovery_models_show_faster_recovery_when_group1_is_shorter():
    # event = recovery; lower time means faster recovery
    rows = [
        {"time": 7, "event": 1, "group": 0},
        {"time": 8, "event": 1, "group": 0},
        {"time": 9, "event": 1, "group": 0},
        {"time": 3, "event": 1, "group": 1},
        {"time": 4, "event": 1, "group": 1},
        {"time": 5, "event": 1, "group": 1},
    ]

    cox = fit_cox_binary(rows)
    aft = fit_aft_logtime_binary(rows)

    assert cox["ok"] is True
    assert aft["ok"] is True
    assert cox["hazard_ratio"] > 1.0
    assert aft["acceleration_factor"] < 1.0


def test_cox_handles_right_censoring():
    rows = [
        {"time": 4, "event": 1, "group": 0},
        {"time": 6, "event": 0, "group": 0},
        {"time": 7, "event": 1, "group": 0},
        {"time": 8, "event": 1, "group": 1},
        {"time": 9, "event": 0, "group": 1},
        {"time": 10, "event": 1, "group": 1},
    ]

    cox = fit_cox_binary(rows)
    assert cox["ok"] is True
    assert math.isfinite(cox["hazard_ratio"])

