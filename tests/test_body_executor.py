"""Tests for body/executor.py — dispatch routing."""

import pytest
from unittest.mock import AsyncMock, patch
from datetime import datetime, timezone

from models.pipeline import ActionRequest, ActionResult


@pytest.fixture(autouse=True)
def _patch_clock():
    """Ensure clock.now_utc() returns a stable datetime."""
    with patch('body.executor.clock') as mock_clock:
        mock_clock.now_utc.return_value = datetime(2025, 1, 1, tzinfo=timezone.utc)
        yield mock_clock


@pytest.fixture(autouse=True)
def _patch_db():
    """Prevent real DB access."""
    with patch('body.executor.db'):
        yield


class TestDispatchAction:
    """Test dispatch_action routing."""

    @pytest.mark.asyncio
    async def test_routes_to_registered_executor(self):
        """Known action types route to their registered executor."""
        from body.executor import dispatch_action
        action = ActionRequest(type='write_journal', detail={'text': 'test entry'})
        with patch('body.internal.db') as mock_db, \
             patch('body.internal.clock') as mock_clock:
            mock_clock.now_utc.return_value = datetime(2025, 1, 1, tzinfo=timezone.utc)
            mock_db.write_journal = AsyncMock()
            result = await dispatch_action(action, visitor_id=None, monologue='')
        assert isinstance(result, ActionResult)
        assert result.action == 'write_journal'

    @pytest.mark.asyncio
    async def test_unknown_action_returns_error(self):
        """Unknown action type returns error ActionResult."""
        from body.executor import dispatch_action
        action = ActionRequest(type='fly_to_moon', detail={})
        result = await dispatch_action(action, visitor_id=None, monologue='')
        assert result.success is False
        assert 'no executor' in result.error

    @pytest.mark.asyncio
    async def test_body_state_fallback(self):
        """Actions with _body_state_update use dynamic handler."""
        from body.executor import dispatch_action
        action = ActionRequest(
            type='wiggle_toes',
            detail={'_body_state_update': {'body_state': 'wiggling'}},
        )
        with patch('body.executor.db') as mock_db:
            mock_db.log_dynamic_action = AsyncMock()
            result = await dispatch_action(action, visitor_id=None, monologue='')
        assert result.action == 'wiggle_toes'
        # Should either succeed or be handled by body_state fallback

    @pytest.mark.asyncio
    async def test_exception_in_executor_returns_error(self):
        """If an executor raises, dispatch returns error result."""
        from body.executor import EXECUTORS, dispatch_action
        original = EXECUTORS.get('write_journal')
        try:
            async def _boom(*args, **kwargs):
                raise RuntimeError('boom')
            EXECUTORS['write_journal'] = _boom
            action = ActionRequest(type='write_journal', detail={'text': 'test'})
            result = await dispatch_action(action, visitor_id=None, monologue='')
            assert result.success is False
            assert 'RuntimeError' in result.error
        finally:
            if original:
                EXECUTORS['write_journal'] = original


class TestRegisterDecorator:
    """Test the @register decorator."""

    def test_register_adds_to_executors(self):
        from body.executor import EXECUTORS
        # Internal actions should be registered
        assert 'write_journal' in EXECUTORS
        assert 'accept_gift' in EXECUTORS
        assert 'close_shop' in EXECUTORS

    def test_external_actions_registered(self):
        from body.executor import EXECUTORS
        # External actions should be registered via body/__init__.py imports
        assert 'browse_web' in EXECUTORS
        assert 'post_x' in EXECUTORS
        assert 'reply_x' in EXECUTORS
        assert 'tg_send' in EXECUTORS
