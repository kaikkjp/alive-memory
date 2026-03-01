"""Tests for engine/gateway_client.py — GatewayClient."""

import asyncio
import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'engine'))

from gateway_client import GatewayClient, _BACKOFF_INITIAL, _BACKOFF_MAX


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeHeartbeat:
    """Minimal heartbeat mock with get_health_status."""

    def get_health_status(self) -> dict:
        return {'status': 'alive', 'reason': 'ok', 'uptime': 42}


class FakeWSServer:
    """Fake WebSocket server for testing the client."""

    def __init__(self):
        self._client_inbox: asyncio.Queue = asyncio.Queue()
        self._server_outbox: list[str] = []
        self._connected = False
        self._closed = False
        self._close_event = asyncio.Event()

    async def recv(self):
        msg = await self._client_inbox.get()
        if msg is None:
            raise Exception("ConnectionClosed")
        return msg

    async def send(self, data: str):
        self._server_outbox.append(data)

    def feed_to_client(self, data: str):
        """Feed a message that the client will receive."""
        self._client_inbox.put_nowait(data)

    async def close(self):
        self._closed = True
        self._close_event.set()
        try:
            self._client_inbox.put_nowait(None)
        except asyncio.QueueFull:
            pass

    @property
    def sent_messages(self) -> list[dict]:
        return [json.loads(m) for m in self._server_outbox]

    def __aiter__(self):
        return self

    async def __anext__(self):
        msg = await self._client_inbox.get()
        if msg is None or self._closed:
            raise StopAsyncIteration
        return msg


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def heartbeat():
    return FakeHeartbeat()


@pytest.fixture
def local_handler():
    """Default local handler that returns 200 OK for any request."""
    async def handler(method, path, headers, body):
        resp = json.dumps({'handled': True, 'path': path})
        return 200, resp.encode(), 'application/json'
    return handler


@pytest.fixture
def client(heartbeat, local_handler):
    return GatewayClient(
        gateway_url='ws://localhost:9999',
        agent_id='test-agent',
        agent_token='test-token',
        heartbeat=heartbeat,
        local_handler=local_handler,
    )


# ---------------------------------------------------------------------------
# Handshake
# ---------------------------------------------------------------------------

class TestHandshake:
    @pytest.mark.asyncio
    async def test_handshake_sent_on_connect(self, client):
        """Client sends handshake as first message after connecting."""
        ws = FakeWSServer()
        client._ws = ws

        await client._send_handshake()

        msgs = ws.sent_messages
        assert len(msgs) == 1
        assert msgs[0]['type'] == 'handshake'
        assert msgs[0]['agent_id'] == 'test-agent'
        assert msgs[0]['token'] == 'test-token'


# ---------------------------------------------------------------------------
# Health heartbeats
# ---------------------------------------------------------------------------

class TestHealthHeartbeats:
    @pytest.mark.asyncio
    async def test_heartbeat_sent(self, client, heartbeat):
        """Health heartbeat is sent over WS."""
        ws = FakeWSServer()
        client._ws = ws
        client._running = True

        # Run heartbeat loop briefly
        async def stop_after():
            await asyncio.sleep(0.05)
            client._running = False

        asyncio.create_task(stop_after())

        with patch('gateway_client._HEARTBEAT_INTERVAL', 0.01):
            await client._heartbeat_loop()

        # Should have sent at least one heartbeat
        hb_msgs = [m for m in ws.sent_messages if m.get('type') == 'heartbeat']
        assert len(hb_msgs) >= 1
        assert hb_msgs[0]['payload']['status'] == 'alive'
        assert hb_msgs[0]['payload']['uptime'] == 42


# ---------------------------------------------------------------------------
# RPC handling
# ---------------------------------------------------------------------------

class TestRPCHandling:
    @pytest.mark.asyncio
    async def test_rpc_request_forwarded_to_local_handler(self, heartbeat):
        """RPC request received → local handler called → response sent back."""
        called_with = {}

        async def handler(method, path, headers, body):
            called_with['method'] = method
            called_with['path'] = path
            return 200, json.dumps({'result': 'ok'}).encode(), 'application/json'

        client = GatewayClient(
            gateway_url='ws://localhost:9999',
            agent_id='test-agent',
            agent_token='test-token',
            heartbeat=heartbeat,
            local_handler=handler,
        )

        ws = FakeWSServer()
        client._ws = ws

        rpc_msg = {
            'type': 'rpc_request',
            'id': 'req-abc',
            'method': 'GET',
            'path': '/api/health',
            'headers': {},
            'body': '',
        }

        await client._handle_rpc_request(rpc_msg)

        assert called_with['method'] == 'GET'
        assert called_with['path'] == '/api/health'

        # Check response was sent
        responses = [m for m in ws.sent_messages if m.get('type') == 'rpc_response']
        assert len(responses) == 1
        assert responses[0]['id'] == 'req-abc'
        assert responses[0]['status'] == 200

    @pytest.mark.asyncio
    async def test_rpc_handler_error_returns_500(self, heartbeat):
        """If local handler raises, return 500."""
        async def bad_handler(method, path, headers, body):
            raise RuntimeError("boom")

        client = GatewayClient(
            gateway_url='ws://localhost:9999',
            agent_id='test-agent',
            agent_token='test-token',
            heartbeat=heartbeat,
            local_handler=bad_handler,
        )

        ws = FakeWSServer()
        client._ws = ws

        await client._handle_rpc_request({
            'type': 'rpc_request',
            'id': 'req-err',
            'method': 'GET',
            'path': '/bad',
            'headers': {},
            'body': '',
        })

        responses = [m for m in ws.sent_messages if m.get('type') == 'rpc_response']
        assert len(responses) == 1
        assert responses[0]['status'] == 500

    @pytest.mark.asyncio
    async def test_receive_loop_dispatches_rpc(self, heartbeat, local_handler):
        """The receive loop dispatches rpc_request messages."""
        client = GatewayClient(
            gateway_url='ws://localhost:9999',
            agent_id='test-agent',
            agent_token='test-token',
            heartbeat=heartbeat,
            local_handler=local_handler,
        )

        ws = FakeWSServer()
        client._ws = ws

        # Feed an RPC request then close
        ws.feed_to_client(json.dumps({
            'type': 'rpc_request',
            'id': 'req-loop',
            'method': 'GET',
            'path': '/api/test',
            'headers': {},
            'body': '',
        }))

        async def close_after():
            await asyncio.sleep(0.05)
            await ws.close()

        asyncio.create_task(close_after())
        await client._receive_loop()

        # Give the background task a moment to complete
        await asyncio.sleep(0.05)

        responses = [m for m in ws.sent_messages if m.get('type') == 'rpc_response']
        assert len(responses) == 1
        assert responses[0]['id'] == 'req-loop'


# ---------------------------------------------------------------------------
# Reconnection
# ---------------------------------------------------------------------------

class TestReconnection:
    @pytest.mark.asyncio
    async def test_backoff_increases(self):
        """Verify exponential backoff logic."""
        backoff = _BACKOFF_INITIAL
        values = []
        for _ in range(5):
            values.append(backoff)
            backoff = min(backoff * 2.0, _BACKOFF_MAX)

        assert values == [1.0, 2.0, 4.0, 8.0, 16.0]
        # Next would be 30 (capped)
        assert min(32.0, _BACKOFF_MAX) == _BACKOFF_MAX


# ---------------------------------------------------------------------------
# Standalone mode (no GATEWAY_URL)
# ---------------------------------------------------------------------------

class TestStandaloneMode:
    def test_no_crash_without_gateway_url(self, heartbeat, local_handler):
        """Creating a client without a URL doesn't crash."""
        client = GatewayClient(
            gateway_url='',
            agent_id='test',
            agent_token='',
            heartbeat=heartbeat,
            local_handler=local_handler,
        )
        assert client._gateway_url == ''

    @pytest.mark.asyncio
    async def test_graceful_stop_without_start(self, client):
        """Stopping a client that was never started doesn't crash."""
        await client.stop()
        assert client._running is False


# ---------------------------------------------------------------------------
# Graceful stop
# ---------------------------------------------------------------------------

class TestGracefulStop:
    @pytest.mark.asyncio
    async def test_stop_cancels_tasks(self, client):
        """stop() cancels running tasks cleanly."""
        client._running = True
        client._task = asyncio.create_task(asyncio.sleep(100))
        client._heartbeat_task = asyncio.create_task(asyncio.sleep(100))

        await client.stop()

        assert client._running is False
        assert client._task is None
        assert client._heartbeat_task is None

    @pytest.mark.asyncio
    async def test_stop_closes_websocket(self, client):
        """stop() closes the WS connection."""
        ws = FakeWSServer()
        client._ws = ws
        client._running = True

        await client.stop()
        assert ws._closed is True
        assert client._ws is None
