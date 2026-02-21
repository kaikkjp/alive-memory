"""Tests for sim.metrics.budget_efficiency — N4: Budget Utilization Efficiency."""

import pytest
from sim.metrics.budget_efficiency import (
    BudgetEfficiencyMetric,
    BudgetEfficiencyResult,
    MEANINGFUL_ACTIONS,
)


class TestDaySplitting:
    """Test cycle-to-day grouping by sleep boundaries."""

    def test_no_sleep_single_day(self):
        cycles = [
            {"type": "idle", "action": None, "budget_spent_usd": 0.01},
            {"type": "dialogue", "action": "speak", "budget_spent_usd": 0.02},
        ]
        result = BudgetEfficiencyMetric.compute(cycles)
        assert len(result.daily_efficiencies) == 1

    def test_sleep_splits_days(self):
        cycles = [
            {"type": "idle", "action": None, "budget_spent_usd": 0.01},
            {"type": "sleep", "action": None, "budget_spent_usd": 0.01},
            {"type": "idle", "action": None, "budget_spent_usd": 0.01},
        ]
        result = BudgetEfficiencyMetric.compute(cycles)
        assert len(result.daily_efficiencies) == 2

    def test_multiple_sleeps(self):
        cycles = [
            {"type": "idle", "action": None, "budget_spent_usd": 0.01},
            {"type": "sleep", "action": None},
            {"type": "idle", "action": None, "budget_spent_usd": 0.01},
            {"type": "sleep", "action": None},
            {"type": "idle", "action": None, "budget_spent_usd": 0.01},
        ]
        result = BudgetEfficiencyMetric.compute(cycles)
        assert len(result.daily_efficiencies) == 3

    def test_empty_cycles(self):
        result = BudgetEfficiencyMetric.compute([])
        assert len(result.daily_efficiencies) == 0
        assert result.overall_efficiency == 0.0


class TestMeaningfulActions:
    """Test meaningful action classification."""

    def test_dialogue_is_meaningful(self):
        cycles = [
            {"type": "dialogue", "action": "speak", "budget_spent_usd": 0.01},
        ]
        result = BudgetEfficiencyMetric.compute(cycles)
        assert result.total_meaningful == 1
        assert result.overall_meaningful_pct == 100.0

    def test_rearrange_not_meaningful(self):
        cycles = [
            {"type": "idle", "action": "rearrange", "budget_spent_usd": 0.01},
        ]
        result = BudgetEfficiencyMetric.compute(cycles)
        assert result.total_meaningful == 0
        assert result.overall_meaningful_pct == 0.0

    def test_browse_is_meaningful(self):
        cycles = [
            {"type": "browse", "action": "read_content", "budget_spent_usd": 0.01},
        ]
        result = BudgetEfficiencyMetric.compute(cycles)
        assert result.total_meaningful == 1

    def test_journal_is_meaningful(self):
        cycles = [
            {"type": "journal", "action": "write_journal", "budget_spent_usd": 0.01},
        ]
        result = BudgetEfficiencyMetric.compute(cycles)
        assert result.total_meaningful == 1

    def test_post_is_meaningful(self):
        cycles = [
            {"type": "post", "action": "post_x", "budget_spent_usd": 0.01},
        ]
        result = BudgetEfficiencyMetric.compute(cycles)
        assert result.total_meaningful == 1

    def test_idle_not_meaningful(self):
        cycles = [
            {"type": "idle", "action": None, "budget_spent_usd": 0.01},
        ]
        result = BudgetEfficiencyMetric.compute(cycles)
        assert result.total_meaningful == 0

    def test_rest_counted_in_total(self):
        """Rest cycles are counted in total but not meaningful."""
        cycles = [
            {"type": "rest", "action": None, "budget_spent_usd": 0.0},
        ]
        result = BudgetEfficiencyMetric.compute(cycles)
        assert result.total_actions == 1
        assert result.total_meaningful == 0


class TestEfficiencyCalculation:
    """Test efficiency ratio computation."""

    def test_efficiency_is_meaningful_per_dollar(self):
        cycles = [
            {"type": "dialogue", "action": "speak", "budget_spent_usd": 0.10},
            {"type": "dialogue", "action": "speak", "budget_spent_usd": 0.20},
            {"type": "idle", "action": None, "budget_spent_usd": 0.30},
        ]
        result = BudgetEfficiencyMetric.compute(cycles)
        # 2 meaningful actions, $0.30 spent
        assert result.total_meaningful == 2
        assert result.total_budget_spent == 0.30
        assert result.overall_efficiency == round(2 / 0.30, 2)

    def test_zero_budget_zero_efficiency(self):
        """No budget spent → efficiency 0 (not infinity)."""
        cycles = [
            {"type": "idle", "action": None, "budget_spent_usd": 0.0},
        ]
        result = BudgetEfficiencyMetric.compute(cycles)
        assert result.overall_efficiency == 0.0

    def test_meaningful_pct(self):
        cycles = [
            {"type": "dialogue", "action": "speak", "budget_spent_usd": 0.01},
            {"type": "browse", "action": "read_content", "budget_spent_usd": 0.02},
            {"type": "idle", "action": "rearrange", "budget_spent_usd": 0.03},
            {"type": "idle", "action": None, "budget_spent_usd": 0.04},
        ]
        result = BudgetEfficiencyMetric.compute(cycles)
        # 2/4 = 50%
        assert result.overall_meaningful_pct == 50.0

    def test_per_day_tracking(self):
        """Each day has independent budget tracking."""
        cycles = [
            {"type": "dialogue", "action": "speak", "budget_spent_usd": 0.10},
            {"type": "idle", "action": None, "budget_spent_usd": 0.15},
            {"type": "sleep", "action": None},
            {"type": "dialogue", "action": "speak", "budget_spent_usd": 0.05},
        ]
        result = BudgetEfficiencyMetric.compute(cycles)
        assert len(result.daily_efficiencies) == 2

        day0 = result.daily_efficiencies[0]
        assert day0.meaningful_actions == 1
        assert day0.total_actions == 2
        assert day0.budget_spent == 0.15

        day1 = result.daily_efficiencies[1]
        assert day1.meaningful_actions == 1
        assert day1.total_actions == 1
        assert day1.budget_spent == 0.05


class TestFromResult:
    """Test from_result helper."""

    def test_extracts_cycles(self):
        result_dict = {
            "cycles": [
                {"type": "dialogue", "action": "speak", "budget_spent_usd": 0.01},
                {"type": "idle", "action": None, "budget_spent_usd": 0.02},
            ]
        }
        result = BudgetEfficiencyMetric.from_result(result_dict)
        assert result.total_meaningful == 1
        assert result.total_actions == 2

    def test_to_dict(self):
        cycles = [
            {"type": "dialogue", "action": "speak", "budget_spent_usd": 0.01},
        ]
        result = BudgetEfficiencyMetric.compute(cycles)
        d = result.to_dict()
        assert "overall_efficiency" in d
        assert "num_days" in d
