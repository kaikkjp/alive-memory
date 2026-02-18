"""Tests for db/actions.py — Dynamic action registry CRUD.

Mocks db.actions._connection so no real DB is required.
Pattern follows test_x_social.py.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Helpers ──

def _make_row(data: dict):
    """Return a MagicMock that behaves like an aiosqlite Row (supports dict())."""
    row = MagicMock()
    row.keys.return_value = list(data.keys())
    row.__iter__ = lambda self: iter(data.values())
    # dict(row) calls keys() + iteration — patch __getitem__ too
    row.__getitem__ = lambda self, k: data[k]
    # Make dict(row) work via mapping protocol
    row.items = MagicMock(return_value=data.items())
    # aiosqlite.Row supports dict() via mapping; simulate with a subclass approach
    # Simplest: return a plain dict wrapped in a MagicMock that dict() can use
    return data  # return real dict — aiosqlite rows converted via dict(row)


_NOW = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
_NOW_ISO = _NOW.isoformat()

_SAMPLE_ROW = {
    'action_name': 'fly',
    'alias_for': None,
    'body_state': None,
    'status': 'pending',
    'attempt_count': 1,
    'promote_threshold': 5,
    'first_seen': _NOW_ISO,
    'last_seen': _NOW_ISO,
    'resolved_by': None,
    'notes': None,
}


def _mock_cursor(rows):
    """Return an AsyncMock cursor whose fetchall/fetchone return rows."""
    cursor = AsyncMock()
    if isinstance(rows, list):
        cursor.fetchall = AsyncMock(return_value=rows)
        cursor.fetchone = AsyncMock(return_value=rows[0] if rows else None)
    else:
        cursor.fetchone = AsyncMock(return_value=rows)
        cursor.fetchall = AsyncMock(return_value=[rows] if rows else [])
    return cursor


def _mock_db(rows=None):
    """Return an AsyncMock connection whose execute() returns _mock_cursor(rows)."""
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=_mock_cursor(rows or []))
    return mock_db


# ── Tests ──


class TestGetDynamicAction:

    @pytest.mark.asyncio
    async def test_get_dynamic_action_returns_none_for_unknown(self):
        """Returns None when row not found."""
        mock_db = AsyncMock()
        cursor = AsyncMock()
        cursor.fetchone = AsyncMock(return_value=None)
        mock_db.execute = AsyncMock(return_value=cursor)

        with patch('db.actions._connection') as mock_conn:
            mock_conn.get_db = AsyncMock(return_value=mock_db)

            from db.actions import get_dynamic_action
            result = await get_dynamic_action('nonexistent_action')

        assert result is None

    @pytest.mark.asyncio
    async def test_get_dynamic_action_returns_dict_for_known(self):
        """Returns dict when row is found."""
        mock_db = AsyncMock()
        cursor = AsyncMock()
        cursor.fetchone = AsyncMock(return_value=_SAMPLE_ROW)
        mock_db.execute = AsyncMock(return_value=cursor)

        with patch('db.actions._connection') as mock_conn:
            mock_conn.get_db = AsyncMock(return_value=mock_db)

            from db.actions import get_dynamic_action
            result = await get_dynamic_action('fly')

        assert result == _SAMPLE_ROW
        assert result['action_name'] == 'fly'
        assert result['status'] == 'pending'


class TestRecordUnknownAction:

    @pytest.mark.asyncio
    async def test_record_unknown_action_creates_entry(self):
        """First call inserts a new row with status='pending', attempt_count=1."""
        inserted_row = dict(_SAMPLE_ROW, action_name='teleport', attempt_count=1)

        mock_db = AsyncMock()
        # First call to get_dynamic_action (inside record_unknown_action) → None
        # Second call (after insert) → the inserted row
        none_cursor = AsyncMock()
        none_cursor.fetchone = AsyncMock(return_value=None)
        row_cursor = AsyncMock()
        row_cursor.fetchone = AsyncMock(return_value=inserted_row)

        call_count = {'n': 0}

        async def execute_side_effect(sql, params=()):
            call_count['n'] += 1
            if call_count['n'] <= 1:
                return none_cursor
            return row_cursor

        mock_db.execute = execute_side_effect

        with patch('db.actions._connection') as mock_conn, \
             patch('db.actions.clock') as mock_clock:
            mock_clock.now_utc.return_value = _NOW
            mock_conn.get_db = AsyncMock(return_value=mock_db)
            mock_conn._exec_write = AsyncMock()

            from db.actions import record_unknown_action
            result = await record_unknown_action('teleport')

        # INSERT was called once
        mock_conn._exec_write.assert_called_once()
        insert_sql = mock_conn._exec_write.call_args[0][0]
        assert 'INSERT INTO dynamic_actions' in insert_sql
        assert result['action_name'] == 'teleport'

    @pytest.mark.asyncio
    async def test_record_unknown_action_increments_on_repeat(self):
        """Second call updates attempt_count and last_seen."""
        existing_row = dict(_SAMPLE_ROW, action_name='fly', attempt_count=3)
        updated_row = dict(existing_row, attempt_count=4)

        mock_db = AsyncMock()
        call_count = {'n': 0}

        existing_cursor = AsyncMock()
        existing_cursor.fetchone = AsyncMock(return_value=existing_row)
        updated_cursor = AsyncMock()
        updated_cursor.fetchone = AsyncMock(return_value=updated_row)

        async def execute_side_effect(sql, params=()):
            call_count['n'] += 1
            if call_count['n'] <= 1:
                return existing_cursor
            return updated_cursor

        mock_db.execute = execute_side_effect

        with patch('db.actions._connection') as mock_conn, \
             patch('db.actions.clock') as mock_clock:
            mock_clock.now_utc.return_value = _NOW
            mock_conn.get_db = AsyncMock(return_value=mock_db)
            mock_conn._exec_write = AsyncMock()

            from db.actions import record_unknown_action
            result = await record_unknown_action('fly')

        # UPDATE was called, not INSERT
        mock_conn._exec_write.assert_called_once()
        update_sql = mock_conn._exec_write.call_args[0][0]
        assert 'UPDATE dynamic_actions' in update_sql
        assert 'attempt_count = attempt_count + 1' in update_sql


class TestResolveAction:

    @pytest.mark.asyncio
    async def test_resolve_action_sets_status(self):
        """resolve_action updates status, alias_for, body_state, resolved_by."""
        resolved_row = dict(_SAMPLE_ROW, status='alias', alias_for='read_content',
                            resolved_by='operator')
        mock_db = AsyncMock()
        cursor = AsyncMock()
        cursor.fetchone = AsyncMock(return_value=resolved_row)
        mock_db.execute = AsyncMock(return_value=cursor)

        with patch('db.actions._connection') as mock_conn, \
             patch('db.actions.clock') as mock_clock:
            mock_clock.now_utc.return_value = _NOW
            mock_conn.get_db = AsyncMock(return_value=mock_db)
            mock_conn._exec_write = AsyncMock()

            from db.actions import resolve_action
            result = await resolve_action('fly', 'alias', alias_for='read_content')

        mock_conn._exec_write.assert_called_once()
        sql = mock_conn._exec_write.call_args[0][0]
        assert 'UPDATE dynamic_actions' in sql
        assert result['status'] == 'alias'
        assert result['alias_for'] == 'read_content'


class TestPromotePendingActions:

    @pytest.mark.asyncio
    async def test_promote_pending_actions_promotes_above_threshold(self):
        """Actions with attempt_count >= threshold get promoted to 'promoted'."""
        candidate = dict(_SAMPLE_ROW, action_name='hover', attempt_count=10,
                         status='pending')
        promoted = dict(candidate, status='promoted', resolved_by='auto')

        mock_db = AsyncMock()
        # First execute: SELECT candidates
        candidates_cursor = AsyncMock()
        candidates_cursor.fetchall = AsyncMock(return_value=[candidate])
        # Second execute (inside get_dynamic_action after update): SELECT promoted row
        promoted_cursor = AsyncMock()
        promoted_cursor.fetchone = AsyncMock(return_value=promoted)

        call_count = {'n': 0}

        async def execute_side_effect(sql, params=()):
            call_count['n'] += 1
            if call_count['n'] == 1:
                return candidates_cursor
            return promoted_cursor

        mock_db.execute = execute_side_effect

        with patch('db.actions._connection') as mock_conn, \
             patch('db.actions.clock') as mock_clock:
            mock_clock.now_utc.return_value = _NOW
            mock_conn.get_db = AsyncMock(return_value=mock_db)
            mock_conn._exec_write = AsyncMock()

            from db.actions import promote_pending_actions
            result = await promote_pending_actions(threshold=5)

        # One write per candidate
        assert mock_conn._exec_write.call_count == 1
        write_sql = mock_conn._exec_write.call_args[0][0]
        assert "status = 'promoted'" in write_sql
        assert len(result) == 1
        assert result[0]['status'] == 'promoted'

    @pytest.mark.asyncio
    async def test_promote_pending_actions_skips_below_threshold(self):
        """Actions with attempt_count < threshold are not promoted."""
        mock_db = AsyncMock()
        empty_cursor = AsyncMock()
        empty_cursor.fetchall = AsyncMock(return_value=[])
        mock_db.execute = AsyncMock(return_value=empty_cursor)

        with patch('db.actions._connection') as mock_conn, \
             patch('db.actions.clock') as mock_clock:
            mock_clock.now_utc.return_value = _NOW
            mock_conn.get_db = AsyncMock(return_value=mock_db)
            mock_conn._exec_write = AsyncMock()

            from db.actions import promote_pending_actions
            result = await promote_pending_actions(threshold=5)

        mock_conn._exec_write.assert_not_called()
        assert result == []


class TestGetActionStats:

    @pytest.mark.asyncio
    async def test_get_action_stats_returns_totals(self):
        """get_action_stats returns total count, by_status dict, and top_pending."""
        status_rows = [
            {'status': 'pending', 'count': 3},
            {'status': 'alias', 'count': 2},
        ]
        total_row = {'total': 5}
        top_pending_rows = [
            {'action_name': 'hover', 'attempt_count': 10},
            {'action_name': 'fly', 'attempt_count': 7},
        ]

        mock_db = AsyncMock()
        call_count = {'n': 0}

        def _cursor_for(rows, is_list=True):
            c = AsyncMock()
            if is_list:
                c.fetchall = AsyncMock(return_value=rows)
            else:
                c.fetchone = AsyncMock(return_value=rows)
            return c

        async def execute_side_effect(sql, params=()):
            call_count['n'] += 1
            if call_count['n'] == 1:
                return _cursor_for(status_rows)
            elif call_count['n'] == 2:
                return _cursor_for(total_row, is_list=False)
            else:
                return _cursor_for(top_pending_rows)

        mock_db.execute = execute_side_effect

        with patch('db.actions._connection') as mock_conn:
            mock_conn.get_db = AsyncMock(return_value=mock_db)

            from db.actions import get_action_stats
            stats = await get_action_stats()

        assert stats['total'] == 5
        assert stats['by_status'] == {'pending': 3, 'alias': 2}
        assert len(stats['top_pending']) == 2
        assert stats['top_pending'][0]['action_name'] == 'hover'

    @pytest.mark.asyncio
    async def test_get_action_stats_empty_db(self):
        """Returns zeros when table is empty."""
        mock_db = AsyncMock()
        call_count = {'n': 0}

        async def execute_side_effect(sql, params=()):
            call_count['n'] += 1
            c = AsyncMock()
            if call_count['n'] == 1:
                c.fetchall = AsyncMock(return_value=[])
            elif call_count['n'] == 2:
                c.fetchone = AsyncMock(return_value={'total': 0})
            else:
                c.fetchall = AsyncMock(return_value=[])
            return c

        mock_db.execute = execute_side_effect

        with patch('db.actions._connection') as mock_conn:
            mock_conn.get_db = AsyncMock(return_value=mock_db)

            from db.actions import get_action_stats
            stats = await get_action_stats()

        assert stats['total'] == 0
        assert stats['by_status'] == {}
        assert stats['top_pending'] == []


class TestSeedData:

    @pytest.mark.asyncio
    async def test_seed_data_present(self):
        """browse_web exists in DB after migration (simulated via mock)."""
        browse_web_row = {
            'action_name': 'browse_web',
            'alias_for': 'read_content',
            'body_state': None,
            'status': 'alias',
            'attempt_count': 242,
            'promote_threshold': 5,
            'first_seen': _NOW_ISO,
            'last_seen': _NOW_ISO,
            'resolved_by': 'seed',
            'notes': None,
        }
        mock_db = AsyncMock()
        cursor = AsyncMock()
        cursor.fetchone = AsyncMock(return_value=browse_web_row)
        mock_db.execute = AsyncMock(return_value=cursor)

        with patch('db.actions._connection') as mock_conn:
            mock_conn.get_db = AsyncMock(return_value=mock_db)

            from db.actions import get_dynamic_action
            result = await get_dynamic_action('browse_web')

        assert result is not None
        assert result['action_name'] == 'browse_web'
        assert result['alias_for'] == 'read_content'
        assert result['status'] == 'alias'
        assert result['attempt_count'] == 242
