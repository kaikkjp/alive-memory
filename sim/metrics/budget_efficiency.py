"""sim.metrics.budget_efficiency — N4: Budget Utilization Efficiency.

Measures meaningful actions per dollar of budget spent.  "Meaningful"
actions are those that advance the character's life: dialogue, browse,
express, post, journal.  Rearrange and idle are excluded.

Computed per simulated day (cycles between sleeps) and aggregated.

Usage:
    from sim.metrics.budget_efficiency import BudgetEfficiencyMetric
    n4 = BudgetEfficiencyMetric.compute(cycles)
    print(n4.overall_efficiency)   # meaningful actions per dollar
    print(n4.daily_efficiencies)   # per-day breakdown
"""

from __future__ import annotations

from dataclasses import dataclass, field


# Actions that count as "meaningful" for budget efficiency
MEANINGFUL_ACTIONS = frozenset({
    "dialogue", "browse", "post", "journal",     # cycle types
    "read_content", "browse_web",                 # action names
    "write_journal",
    "post_x", "reply_x", "post_x_image",
    "tg_send", "tg_send_image",
    "express_thought",
    "speak",
})

# Actions / cycle types that are NOT meaningful
NON_MEANINGFUL = frozenset({
    "idle", "rearrange", "rest", "sleep",
})


@dataclass
class DayEfficiency:
    """Budget efficiency for a single simulated day."""
    day_index: int
    meaningful_actions: int
    total_actions: int
    budget_spent: float           # dollars spent this day
    efficiency: float             # meaningful_actions / budget_spent
    meaningful_pct: float         # % of actions that are meaningful


@dataclass
class BudgetEfficiencyResult:
    """N4 metric result."""
    overall_efficiency: float     # meaningful_actions / total_budget_spent
    overall_meaningful_pct: float  # % of non-sleep actions that are meaningful
    total_meaningful: int
    total_actions: int
    total_budget_spent: float
    daily_efficiencies: list[DayEfficiency] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "overall_efficiency": self.overall_efficiency,
            "overall_meaningful_pct": self.overall_meaningful_pct,
            "total_meaningful": self.total_meaningful,
            "total_actions": self.total_actions,
            "total_budget_spent": self.total_budget_spent,
            "num_days": len(self.daily_efficiencies),
        }


class BudgetEfficiencyMetric:
    """N4: Budget Utilization Efficiency.

    Operates on a list of cycle dicts, each with:
        - "type" or "cycle_type": str
        - "action": str | None
        - "budget_spent_usd": float (cumulative since last sleep)
        - "budget_remaining_usd": float
    """

    @staticmethod
    def compute(cycles: list[dict]) -> BudgetEfficiencyResult:
        """Compute N4 from a list of cycle dicts."""
        days = BudgetEfficiencyMetric._split_days(cycles)

        daily_results: list[DayEfficiency] = []
        total_meaningful = 0
        total_actions = 0
        total_spent = 0.0

        for day_idx, day_cycles in enumerate(days):
            meaningful, actions, spent = (
                BudgetEfficiencyMetric._day_stats(day_cycles)
            )
            total_meaningful += meaningful
            total_actions += actions
            total_spent += spent

            meaningful_pct = (
                round(100.0 * meaningful / actions, 2) if actions > 0 else 0.0
            )
            efficiency = (
                round(meaningful / spent, 2) if spent > 0 else 0.0
            )

            daily_results.append(DayEfficiency(
                day_index=day_idx,
                meaningful_actions=meaningful,
                total_actions=actions,
                budget_spent=round(spent, 6),
                efficiency=efficiency,
                meaningful_pct=meaningful_pct,
            ))

        overall_eff = (
            round(total_meaningful / total_spent, 2)
            if total_spent > 0 else 0.0
        )
        overall_pct = (
            round(100.0 * total_meaningful / total_actions, 2)
            if total_actions > 0 else 0.0
        )

        return BudgetEfficiencyResult(
            overall_efficiency=overall_eff,
            overall_meaningful_pct=overall_pct,
            total_meaningful=total_meaningful,
            total_actions=total_actions,
            total_budget_spent=round(total_spent, 6),
            daily_efficiencies=daily_results,
        )

    @staticmethod
    def _split_days(cycles: list[dict]) -> list[list[dict]]:
        """Split cycles into per-day groups using sleep boundaries.

        A "day" runs from one sleep cycle to the next.
        """
        if not cycles:
            return []

        days: list[list[dict]] = []
        current_day: list[dict] = []

        for c in cycles:
            ctype = c.get("type") or c.get("cycle_type", "idle")
            if ctype == "sleep":
                if current_day:
                    days.append(current_day)
                current_day = []
            else:
                current_day.append(c)

        # Final partial day
        if current_day:
            days.append(current_day)

        return days

    @staticmethod
    def _day_stats(
        day_cycles: list[dict],
    ) -> tuple[int, int, float]:
        """Count meaningful actions, total actions, and budget spent for a day.

        Returns (meaningful_count, total_count, budget_spent_usd).
        """
        meaningful = 0
        total = 0
        max_spent = 0.0

        for c in day_cycles:
            ctype = c.get("type") or c.get("cycle_type", "idle")
            action = c.get("action")

            # Skip rest cycles for action counting
            if ctype == "rest":
                total += 1
                continue

            total += 1

            if BudgetEfficiencyMetric._is_meaningful(ctype, action):
                meaningful += 1

            # Track cumulative budget spent (monotonically increasing per day)
            spent = c.get("budget_spent_usd", 0.0)
            if isinstance(spent, (int, float)):
                max_spent = max(max_spent, float(spent))

        return meaningful, total, max_spent

    @staticmethod
    def _is_meaningful(cycle_type: str, action: str | None) -> bool:
        """Check if a cycle/action combo counts as meaningful."""
        if cycle_type in MEANINGFUL_ACTIONS:
            return True
        if action and action in MEANINGFUL_ACTIONS:
            return True
        return False

    @staticmethod
    def from_result(result: dict) -> BudgetEfficiencyResult:
        """Compute N4 from an exported simulation result dict."""
        cycles = result.get("cycles", [])
        return BudgetEfficiencyMetric.compute(cycles)
