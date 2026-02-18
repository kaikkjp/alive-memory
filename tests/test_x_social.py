"""Tests for X/Twitter social channel (TASK-057).

Covers: fingerprinting, char limit, dedup, daily cap, cooldown,
approve/reject endpoints, output.py persistence constants.
"""

import json
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Fingerprinting ──

class TestTextFingerprint:
    """Unit: fingerprint normalization strips case, punctuation, whitespace."""

    def test_same_text_same_fingerprint(self):
        from db.social import _text_fingerprint
        fp1 = _text_fingerprint("Hello, world!")
        fp2 = _text_fingerprint("hello world")
        assert fp1 == fp2

    def test_different_text_different_fingerprint(self):
        from db.social import _text_fingerprint
        fp1 = _text_fingerprint("Hello world")
        fp2 = _text_fingerprint("Goodbye world")
        assert fp1 != fp2

    def test_punctuation_stripped(self):
        from db.social import _text_fingerprint
        fp1 = _text_fingerprint("Hello! World?")
        fp2 = _text_fingerprint("hello world")
        assert fp1 == fp2

    def test_extra_whitespace_normalized(self):
        from db.social import _text_fingerprint
        fp1 = _text_fingerprint("hello   world")
        fp2 = _text_fingerprint("hello world")
        assert fp1 == fp2

    def test_returns_hex_string(self):
        from db.social import _text_fingerprint
        fp = _text_fingerprint("test")
        assert len(fp) == 32
        assert all(c in '0123456789abcdef' for c in fp)


# ── Char limit ──

class TestCharLimit:
    """Unit: draft creation respects 280 char limit."""

    def test_output_max_chars_constant(self):
        from pipeline.output import X_DRAFT_MAX_CHARS
        assert X_DRAFT_MAX_CHARS == 280

    async def test_insert_draft_stores_text(self):
        """Draft within 280 chars is stored as-is."""
        now = datetime(2025, 1, 1, tzinfo=timezone.utc)
        with patch('db.social._connection') as mock_conn, \
             patch('db.social.clock') as mock_clock:
            mock_clock.now_utc.return_value = now
            mock_conn._exec_write = AsyncMock()

            from db.social import insert_x_draft
            text = "A" * 280
            result = await insert_x_draft(text)
            assert result['draft_text'] == text
            assert len(result['draft_text']) == 280
            mock_conn._exec_write.assert_called_once()


# ── Dedup ──

class TestDedup:
    """Unit: dedup rejects similar drafts within 24h."""

    async def test_dedup_finds_existing(self):
        now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
        mock_db = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=(1,))
        mock_db.execute = AsyncMock(return_value=mock_cursor)

        with patch('db.social._connection') as mock_conn, \
             patch('db.social.clock') as mock_clock:
            mock_clock.now_utc.return_value = now
            mock_conn.get_db = AsyncMock(return_value=mock_db)

            from db.social import check_dedup
            result = await check_dedup("Hello world")
            assert result is True  # duplicate found

    async def test_dedup_no_existing(self):
        now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
        mock_db = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=(0,))
        mock_db.execute = AsyncMock(return_value=mock_cursor)

        with patch('db.social._connection') as mock_conn, \
             patch('db.social.clock') as mock_clock:
            mock_clock.now_utc.return_value = now
            mock_conn.get_db = AsyncMock(return_value=mock_db)

            from db.social import check_dedup
            result = await check_dedup("Hello world")
            assert result is False  # no duplicate


# ── Daily cap ──

class TestDailyCap:
    """Unit: daily cap of 8 posts enforced."""

    def test_daily_cap_constant(self):
        from pipeline.output import X_DRAFT_DAILY_CAP
        assert X_DRAFT_DAILY_CAP == 8

    async def test_daily_count_returns_value(self):
        now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
        mock_db = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=(8,))
        mock_db.execute = AsyncMock(return_value=mock_cursor)

        with patch('db.social._connection') as mock_conn, \
             patch('db.social.clock') as mock_clock:
            mock_clock.now_utc.return_value = now
            mock_conn.get_db = AsyncMock(return_value=mock_db)
            mock_conn.JST = timezone(timedelta(hours=9))

            from db.social import get_daily_post_count
            count = await get_daily_post_count()
            assert count == 8


# ── Cooldown ──

class TestCooldown:
    """Unit: cooldown of 30 min between posts."""

    def test_cooldown_constant(self):
        from pipeline.output import X_DRAFT_COOLDOWN_SECONDS
        assert X_DRAFT_COOLDOWN_SECONDS == 1800

    async def test_cooldown_active(self):
        now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
        mock_db = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=(1,))
        mock_db.execute = AsyncMock(return_value=mock_cursor)

        with patch('db.social._connection') as mock_conn, \
             patch('db.social.clock') as mock_clock:
            mock_clock.now_utc.return_value = now
            mock_conn.get_db = AsyncMock(return_value=mock_db)

            from db.social import check_cooldown
            result = await check_cooldown(1800)
            assert result is True  # still cooling

    async def test_cooldown_expired(self):
        now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
        mock_db = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=(0,))
        mock_db.execute = AsyncMock(return_value=mock_cursor)

        with patch('db.social._connection') as mock_conn, \
             patch('db.social.clock') as mock_clock:
            mock_clock.now_utc.return_value = now
            mock_conn.get_db = AsyncMock(return_value=mock_db)

            from db.social import check_cooldown
            result = await check_cooldown(1800)
            assert result is False  # cooldown expired


# ── Approve/Reject endpoints ──

class TestDashboardXDraftEndpoints:
    """Unit: approve/reject endpoints work."""

    async def test_approve_endpoint_success(self):
        server = MagicMock()
        server._http_json = AsyncMock()
        writer = MagicMock()

        with patch('api.dashboard_routes.check_dashboard_auth', return_value=True), \
             patch('api.dashboard_routes.db') as mock_db:
            mock_db.approve_draft = AsyncMock(return_value=True)

            from api.dashboard_routes import handle_approve_x_draft
            body = json.dumps({'draft_id': 'test-id'}).encode()
            await handle_approve_x_draft(server, writer, 'Bearer token', body)

            server._http_json.assert_called_once()
            args = server._http_json.call_args[0]
            assert args[1] == 200
            assert args[2]['approved'] is True
            assert args[2]['draft_id'] == 'test-id'

    async def test_approve_endpoint_not_found(self):
        server = MagicMock()
        server._http_json = AsyncMock()
        writer = MagicMock()

        with patch('api.dashboard_routes.check_dashboard_auth', return_value=True), \
             patch('api.dashboard_routes.db') as mock_db:
            mock_db.approve_draft = AsyncMock(return_value=False)

            from api.dashboard_routes import handle_approve_x_draft
            body = json.dumps({'draft_id': 'nonexistent'}).encode()
            await handle_approve_x_draft(server, writer, 'Bearer token', body)

            args = server._http_json.call_args[0]
            assert args[1] == 404

    async def test_reject_endpoint_success(self):
        server = MagicMock()
        server._http_json = AsyncMock()
        writer = MagicMock()

        with patch('api.dashboard_routes.check_dashboard_auth', return_value=True), \
             patch('api.dashboard_routes.db') as mock_db:
            mock_db.reject_draft = AsyncMock(return_value=True)

            from api.dashboard_routes import handle_reject_x_draft
            body = json.dumps({'draft_id': 'test-id', 'reason': 'off-brand'}).encode()
            await handle_reject_x_draft(server, writer, 'Bearer token', body)

            args = server._http_json.call_args[0]
            assert args[1] == 200
            assert args[2]['rejected'] is True

    async def test_approve_endpoint_unauthorized(self):
        server = MagicMock()
        server._http_json = AsyncMock()
        writer = MagicMock()

        with patch('api.dashboard_routes.check_dashboard_auth', return_value=False):
            from api.dashboard_routes import handle_approve_x_draft
            body = json.dumps({'draft_id': 'test-id'}).encode()
            await handle_approve_x_draft(server, writer, '', body)

            args = server._http_json.call_args[0]
            assert args[1] == 401

    async def test_approve_missing_draft_id(self):
        server = MagicMock()
        server._http_json = AsyncMock()
        writer = MagicMock()

        with patch('api.dashboard_routes.check_dashboard_auth', return_value=True):
            from api.dashboard_routes import handle_approve_x_draft
            body = json.dumps({}).encode()
            await handle_approve_x_draft(server, writer, 'Bearer token', body)

            args = server._http_json.call_args[0]
            assert args[1] == 400


# ── Output.py persistence ──

class TestOutputXDraftPersist:
    """Unit: output.py _persist_x_draft extracts text from motor_plan."""

    async def test_persist_skips_non_x_actions(self):
        """Actions other than post_x_draft are ignored."""
        from models.pipeline import BodyOutput, ActionResult, MotorPlan, ActionDecision
        from pipeline.output import _persist_x_draft

        body_output = BodyOutput()
        body_output.executed = [
            ActionResult(action='write_journal', success=True),
        ]
        motor_plan = MotorPlan(actions=[
            ActionDecision(action='write_journal', status='approved', source='cortex'),
        ])

        with patch('pipeline.output.db') as mock_db:
            mock_db.check_dedup = AsyncMock(return_value=False)
            mock_db.get_daily_post_count = AsyncMock(return_value=0)
            mock_db.check_cooldown = AsyncMock(return_value=False)
            mock_db.insert_x_draft = AsyncMock()

            await _persist_x_draft(body_output, motor_plan=motor_plan, cycle_id='c1')
            mock_db.insert_x_draft.assert_not_called()

    async def test_persist_extracts_text_from_motor_plan(self):
        """Draft text is read from motor_plan ActionDecision detail."""
        from models.pipeline import BodyOutput, ActionResult, MotorPlan, ActionDecision
        from pipeline.output import _persist_x_draft

        body_output = BodyOutput()
        body_output.executed = [
            ActionResult(action='post_x_draft', success=True),
        ]
        motor_plan = MotorPlan(actions=[
            ActionDecision(
                action='post_x_draft', status='approved', source='cortex',
                detail={'text': 'The rain today sounds different.'},
            ),
        ])

        with patch('pipeline.output.db') as mock_db:
            mock_db.check_dedup = AsyncMock(return_value=False)
            mock_db.get_daily_post_count = AsyncMock(return_value=0)
            mock_db.check_cooldown = AsyncMock(return_value=False)
            mock_db.insert_x_draft = AsyncMock(return_value={'id': 'abc', 'draft_text': 'test'})

            await _persist_x_draft(body_output, motor_plan=motor_plan, cycle_id='c1')
            mock_db.insert_x_draft.assert_called_once_with(
                'The rain today sounds different.', cycle_id='c1',
            )

    async def test_persist_skips_duplicate(self):
        """Dedup check prevents duplicate drafts."""
        from models.pipeline import BodyOutput, ActionResult, MotorPlan, ActionDecision
        from pipeline.output import _persist_x_draft

        body_output = BodyOutput()
        body_output.executed = [
            ActionResult(action='post_x_draft', success=True),
        ]
        motor_plan = MotorPlan(actions=[
            ActionDecision(
                action='post_x_draft', status='approved', source='cortex',
                detail={'text': 'Same thought again'},
            ),
        ])

        with patch('pipeline.output.db') as mock_db:
            mock_db.check_dedup = AsyncMock(return_value=True)  # duplicate!
            mock_db.insert_x_draft = AsyncMock()

            await _persist_x_draft(body_output, motor_plan=motor_plan, cycle_id='c1')
            mock_db.insert_x_draft.assert_not_called()

    async def test_persist_skips_when_daily_cap_reached(self):
        """Daily cap of 8 prevents new drafts."""
        from models.pipeline import BodyOutput, ActionResult, MotorPlan, ActionDecision
        from pipeline.output import _persist_x_draft

        body_output = BodyOutput()
        body_output.executed = [
            ActionResult(action='post_x_draft', success=True),
        ]
        motor_plan = MotorPlan(actions=[
            ActionDecision(
                action='post_x_draft', status='approved', source='cortex',
                detail={'text': 'Over the limit'},
            ),
        ])

        with patch('pipeline.output.db') as mock_db:
            mock_db.check_dedup = AsyncMock(return_value=False)
            mock_db.get_daily_post_count = AsyncMock(return_value=8)  # cap reached!
            mock_db.insert_x_draft = AsyncMock()

            await _persist_x_draft(body_output, motor_plan=motor_plan, cycle_id='c1')
            mock_db.insert_x_draft.assert_not_called()

    async def test_persist_skips_when_cooldown_active(self):
        """Cooldown prevents new drafts within 30 min."""
        from models.pipeline import BodyOutput, ActionResult, MotorPlan, ActionDecision
        from pipeline.output import _persist_x_draft

        body_output = BodyOutput()
        body_output.executed = [
            ActionResult(action='post_x_draft', success=True),
        ]
        motor_plan = MotorPlan(actions=[
            ActionDecision(
                action='post_x_draft', status='approved', source='cortex',
                detail={'text': 'Too soon'},
            ),
        ])

        with patch('pipeline.output.db') as mock_db:
            mock_db.check_dedup = AsyncMock(return_value=False)
            mock_db.get_daily_post_count = AsyncMock(return_value=0)
            mock_db.check_cooldown = AsyncMock(return_value=True)  # still cooling!
            mock_db.insert_x_draft = AsyncMock()

            await _persist_x_draft(body_output, motor_plan=motor_plan, cycle_id='c1')
            mock_db.insert_x_draft.assert_not_called()

    async def test_persist_truncates_long_draft(self):
        """Drafts over 280 chars are truncated."""
        from models.pipeline import BodyOutput, ActionResult, MotorPlan, ActionDecision
        from pipeline.output import _persist_x_draft

        long_text = "A" * 300
        body_output = BodyOutput()
        body_output.executed = [
            ActionResult(action='post_x_draft', success=True),
        ]
        motor_plan = MotorPlan(actions=[
            ActionDecision(
                action='post_x_draft', status='approved', source='cortex',
                detail={'text': long_text},
            ),
        ])

        with patch('pipeline.output.db') as mock_db:
            mock_db.check_dedup = AsyncMock(return_value=False)
            mock_db.get_daily_post_count = AsyncMock(return_value=0)
            mock_db.check_cooldown = AsyncMock(return_value=False)
            mock_db.insert_x_draft = AsyncMock(return_value={'id': 'abc', 'draft_text': 'A' * 280})

            await _persist_x_draft(body_output, motor_plan=motor_plan, cycle_id='c1')
            call_args = mock_db.insert_x_draft.call_args[0]
            assert len(call_args[0]) == 280
