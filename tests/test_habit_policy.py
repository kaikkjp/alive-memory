"""Tests for pipeline/habit_policy.py — TASK-082 journaling as homeostatic reflex."""

import pytest
from models.state import DrivesState
from pipeline.habit_policy import (
    evaluate_journal_habit,
    HabitProposal,
    JOURNAL_EXPRESSION_THRESHOLD,
    JOURNAL_COOLDOWN_CYCLES,
    JOURNAL_NO_VISITOR_WINDOW,
    JOURNAL_MAX_PER_DAY,
    JOURNAL_PRIORITY,
    JOURNAL_DIMINISHING_FACTOR,
)


# ── Fixtures ──

@pytest.fixture
def high_expression_drives():
    """Drives with expression_need above threshold."""
    return DrivesState(expression_need=0.75, mood_valence=0.1)


@pytest.fixture
def low_expression_drives():
    """Drives with expression_need below threshold."""
    return DrivesState(expression_need=0.3, mood_valence=0.1)


@pytest.fixture
def negative_mood_drives():
    """Drives with high expression and negative mood."""
    return DrivesState(expression_need=0.75, mood_valence=-0.4)


# ── Tests ──

def test_journal_fires_when_conditions_met(high_expression_drives):
    """expression_need high, cooldown passed, no visitor -> fires."""
    result = evaluate_journal_habit(
        drives=high_expression_drives,
        cycles_since_last_journal=100,
        cycles_since_last_visitor=10,
        journals_today=0,
    )
    assert result is not None
    assert isinstance(result, HabitProposal)
    assert result.action == 'write_journal'
    assert result.priority == pytest.approx(JOURNAL_PRIORITY, abs=0.01)


def test_journal_blocked_by_cooldown(high_expression_drives):
    """expression_need high but cooldown not elapsed -> None."""
    result = evaluate_journal_habit(
        drives=high_expression_drives,
        cycles_since_last_journal=30,  # < JOURNAL_COOLDOWN_CYCLES (80)
        cycles_since_last_visitor=10,
        journals_today=0,
    )
    assert result is None


def test_journal_blocked_by_visitor(high_expression_drives):
    """expression_need high but visitor recent -> None."""
    result = evaluate_journal_habit(
        drives=high_expression_drives,
        cycles_since_last_journal=100,
        cycles_since_last_visitor=2,  # < JOURNAL_NO_VISITOR_WINDOW (5)
        journals_today=0,
    )
    assert result is None


def test_journal_blocked_by_daily_cap(high_expression_drives):
    """3 journals already today -> None."""
    result = evaluate_journal_habit(
        drives=high_expression_drives,
        cycles_since_last_journal=100,
        cycles_since_last_visitor=10,
        journals_today=JOURNAL_MAX_PER_DAY,
    )
    assert result is None


def test_journal_blocked_by_budget_emergency(high_expression_drives):
    """budget_emergency=True -> None."""
    result = evaluate_journal_habit(
        drives=high_expression_drives,
        cycles_since_last_journal=100,
        cycles_since_last_visitor=10,
        journals_today=0,
        budget_emergency=True,
    )
    assert result is None


def test_journal_blocked_by_low_expression(low_expression_drives):
    """expression_need below threshold -> None."""
    result = evaluate_journal_habit(
        drives=low_expression_drives,
        cycles_since_last_journal=100,
        cycles_since_last_visitor=10,
        journals_today=0,
    )
    assert result is None


def test_diminishing_returns(high_expression_drives):
    """2nd journal in a day has lower priority than 1st."""
    first = evaluate_journal_habit(
        drives=high_expression_drives,
        cycles_since_last_journal=100,
        cycles_since_last_visitor=10,
        journals_today=0,
    )
    second = evaluate_journal_habit(
        drives=high_expression_drives,
        cycles_since_last_journal=100,
        cycles_since_last_visitor=10,
        journals_today=1,
    )
    assert first is not None
    assert second is not None
    assert second.priority < first.priority
    # Verify the exact diminishing factor
    assert second.priority == pytest.approx(
        JOURNAL_PRIORITY * JOURNAL_DIMINISHING_FACTOR, abs=0.01
    )


def test_mood_boost(negative_mood_drives):
    """Negative mood increases journal priority."""
    normal_drives = DrivesState(expression_need=0.75, mood_valence=0.1)
    result_normal = evaluate_journal_habit(
        drives=normal_drives,
        cycles_since_last_journal=100,
        cycles_since_last_visitor=10,
        journals_today=0,
    )
    result_negative = evaluate_journal_habit(
        drives=negative_mood_drives,
        cycles_since_last_journal=100,
        cycles_since_last_visitor=10,
        journals_today=0,
    )
    assert result_normal is not None
    assert result_negative is not None
    assert result_negative.priority > result_normal.priority
    # Mood boost is +0.1 when valence < -0.2
    assert result_negative.priority == pytest.approx(
        JOURNAL_PRIORITY + 0.1, abs=0.01
    )


def test_drive_deltas_on_completion():
    """expression_need drops, mood lifts after journal.

    Tests that the hypothalamus expression_relief dict contains the right
    keys for write_journal — the actual delta values are parameterized.
    """
    from pipeline.hypothalamus import _build_expression_relief
    relief = _build_expression_relief()
    assert 'write_journal' in relief
    journal_relief = relief['write_journal']
    # expression_need should decrease (negative delta)
    assert journal_relief['expression_need'] < 0
    # mood_valence should increase (positive delta)
    assert journal_relief['mood_valence'] > 0
