"""Tests for pipeline/habit_policy.py — TASK-082 journaling as homeostatic reflex."""

import pytest
import pytest_asyncio
import aiosqlite
from unittest.mock import AsyncMock, patch, MagicMock
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


# ── Integration tests for DB queries (Bug fixes) ──

@pytest_asyncio.fixture
async def memory_db():
    """In-memory DB with cycle_log and action_log tables for query testing."""
    conn = await aiosqlite.connect(':memory:')
    conn.row_factory = aiosqlite.Row
    await conn.execute("""
        CREATE TABLE cycle_log (
            id TEXT PRIMARY KEY,
            mode TEXT NOT NULL DEFAULT 'ambient',
            ts TIMESTAMP NOT NULL
        )
    """)
    await conn.execute("""
        CREATE TABLE action_log (
            id TEXT PRIMARY KEY,
            cycle_id TEXT NOT NULL,
            action TEXT NOT NULL,
            status TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'cortex',
            impulse REAL,
            priority REAL,
            content TEXT,
            target TEXT,
            suppression_reason TEXT,
            energy_cost REAL,
            success BOOLEAN,
            error TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await conn.execute("""
        CREATE TABLE events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            source TEXT,
            ts TIMESTAMP NOT NULL,
            payload TEXT
        )
    """)
    await conn.commit()
    yield conn
    await conn.close()


@pytest.mark.asyncio
async def test_get_cycles_since_last_journal_uses_ts_column(memory_db):
    """Verify query uses cycle_log.ts (not created_at) and action_log status='executed'."""
    # Insert an executed journal action
    await memory_db.execute(
        "INSERT INTO action_log (id, cycle_id, action, status, created_at) "
        "VALUES ('a1', 'c1', 'write_journal', 'executed', '2026-02-22 10:00:00')"
    )
    # Insert cycles after it — using 'ts' column
    for i in range(5):
        await memory_db.execute(
            "INSERT INTO cycle_log (id, mode, ts) VALUES (?, 'ambient', ?)",
            (f'cyc{i}', f'2026-02-22 10:0{i+1}:00')
        )
    await memory_db.commit()

    # Patch the db connection to use our in-memory db
    with patch('db.analytics._connection.get_db', return_value=memory_db):
        from db.analytics import get_cycles_since_last_journal
        count = await get_cycles_since_last_journal()

    assert count == 5


@pytest.mark.asyncio
async def test_get_cycles_since_last_journal_ignores_approved_status(memory_db):
    """An action with status='approved' (not yet executed) should not count."""
    await memory_db.execute(
        "INSERT INTO action_log (id, cycle_id, action, status, created_at) "
        "VALUES ('a1', 'c1', 'write_journal', 'approved', '2026-02-22 10:00:00')"
    )
    await memory_db.commit()

    with patch('db.analytics._connection.get_db', return_value=memory_db):
        from db.analytics import get_cycles_since_last_journal
        count = await get_cycles_since_last_journal()

    assert count == 9999  # no executed journal → returns sentinel


@pytest.mark.asyncio
async def test_get_cycles_since_last_visitor_uses_ts_column(memory_db):
    """Verify visitor cycle query uses cycle_log.ts (not created_at)."""
    await memory_db.execute(
        "INSERT INTO events (event_type, source, ts) "
        "VALUES ('visitor_speech', 'visitor', '2026-02-22 10:00:00')"
    )
    for i in range(3):
        await memory_db.execute(
            "INSERT INTO cycle_log (id, mode, ts) VALUES (?, 'ambient', ?)",
            (f'cyc{i}', f'2026-02-22 10:0{i+1}:00')
        )
    await memory_db.commit()

    with patch('db.analytics._connection.get_db', return_value=memory_db):
        from db.analytics import get_cycles_since_last_visitor
        count = await get_cycles_since_last_visitor()

    assert count == 3


# ── Integration test for check_habits reachability ──

@pytest.mark.asyncio
async def test_check_habits_reaches_habit_policy_without_learned_habits():
    """HabitPolicy fires even when no learned habits match (bug #3 regression)."""
    from pipeline.basal_ganglia import check_habits
    from models.pipeline import HabitBoost
    from models.state import EngagementState

    drives = DrivesState(expression_need=0.8, mood_valence=0.0)
    engagement = EngagementState(status='none')

    with patch('pipeline.basal_ganglia.db') as mock_db:
        mock_db.get_all_habits = AsyncMock(return_value=[])  # no learned habits
        mock_db.get_cycles_since_last_journal = AsyncMock(return_value=200)
        mock_db.get_cycles_since_last_visitor = AsyncMock(return_value=50)
        mock_db.get_journals_today = AsyncMock(return_value=0)

        result = await check_habits(drives, engagement=engagement)

    assert result is not None
    assert isinstance(result, HabitBoost)
    assert result.action == 'write_journal'


# ── Integration test for select_actions no empty injection ──

@pytest.mark.asyncio
async def test_select_actions_does_not_inject_empty_journal():
    """HabitPolicy in select_actions only boosts, never injects empty content (bug #4)."""
    from pipeline.basal_ganglia import select_actions
    from models.pipeline import ActionDecision, Intention, ValidatedOutput

    # Cortex produced no write_journal — only a monologue
    validated = ValidatedOutput(
        intentions=[Intention(action='speak', target='self', content='thinking...')],
        internal_monologue='Just pondering things.',
        actions=[],
        dropped_actions=[],
    )
    drives = DrivesState(expression_need=0.8, mood_valence=0.0)

    with patch('pipeline.basal_ganglia.db') as mock_db:
        mock_db.resolve_dynamic_action = AsyncMock(return_value=None)
        mock_db.get_cycles_since_last_journal = AsyncMock(return_value=200)
        mock_db.get_cycles_since_last_visitor = AsyncMock(return_value=50)
        mock_db.get_journals_today = AsyncMock(return_value=0)

        motor_plan = await select_actions(validated, drives, context={})

    # Should NOT contain a write_journal with empty content
    journal_actions = [a for a in motor_plan.actions if a.action == 'write_journal']
    assert len(journal_actions) == 0
