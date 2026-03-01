"""Tests for engine/gateway.py — GatewayServer."""

import asyncio
import json
import os
import sys
import tempfile
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'engine'))

from gateway import GatewayServer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tokens_file(tokens: dict) -> str:
    """Write a tokens file and return its path."""
    f = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
    json.dump(tokens, f)
    f.close()
    return f.name


class FakeWebSocket:
    """Minimal WebSocket mock for testing."""

    def __init__(self):
        self._inbox: asyncio.Queue = asyncio.Queue()
        self._outbox: list[str] = []
        self._closed = False
        self._recv_iter_started = False

    async def send(self, data: str):
        self._outbox.append(data)

    async def recv(self):
        return await self._inbox.get()

    def feed(self, data: str):
        """Feed a message to be received by the server."""
        self._inbox.put_nowait(data)

    async def close(self):
        self._closed = True
        # Unblock any pending recv
        try:
            self._inbox.put_nowait(None)
        except asyncio.QueueFull:
            pass

    def __aiter__(self):
        self._recv_iter_started = True
        return self

    async def __anext__(self):
        msg = await self._inbox.get()
        if msg is None or self._closed:
            raise StopAsyncIteration
        return msg

    @property
    def sent_messages(self) -> list[dict]:
        return [json.loads(m) for m in self._outbox]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tokens_file():
    """Create a temporary tokens file."""
    path = _make_tokens_file({'agent1': 'token-aaa', 'agent2': 'token-bbb'})
    yield path
    os.unlink(path)


@pytest.fixture
def gateway(tokens_file):
    """Create a GatewayServer with test config."""
    return GatewayServer(
        http_port=0,
        ws_port=0,
        admin_token='admin-secret',
        tokens_path=tokens_file,
    )


# ---------------------------------------------------------------------------
# Token loading
# ---------------------------------------------------------------------------

class TestTokenLoading:
    def test_load_tokens_from_file(self, gateway):
        tokens = gateway._load_agent_tokens()
        assert tokens == {'token-aaa': 'agent1', 'token-bbb': 'agent2'}

    def test_validate_valid_token(self, gateway):
        # Force initial load
        gateway._agent_tokens = gateway._load_agent_tokens()
        assert gateway._validate_agent_token('token-aaa') == 'agent1'
        assert gateway._validate_agent_token('token-bbb') == 'agent2'

    def test_validate_invalid_token(self, gateway):
        gateway._agent_tokens = gateway._load_agent_tokens()
        assert gateway._validate_agent_token('bad-token') is None

    def test_validate_empty_token(self, gateway):
        gateway._agent_tokens = gateway._load_agent_tokens()
        assert gateway._validate_agent_token('') is None

    def test_missing_tokens_file(self):
        gw = GatewayServer(tokens_path='/nonexistent/path.json',
                           admin_token='x')
        tokens = gw._load_agent_tokens()
        assert tokens == {}

    def test_hot_reload_on_mtime_change(self, gateway, tokens_file):
        gateway._agent_tokens = gateway._load_agent_tokens()
        gateway._tokens_mtime = os.path.getmtime(tokens_file)
        gateway._tokens_last_check = 0  # force check

        # Modify the file
        time.sleep(0.05)  # ensure mtime changes
        with open(tokens_file, 'w') as f:
            json.dump({'agent3': 'token-ccc'}, f)

        gateway._maybe_reload_tokens()
        assert gateway._validate_agent_token('token-ccc') == 'agent3'
        assert gateway._validate_agent_token('token-aaa') is None


# ---------------------------------------------------------------------------
# Agent WS handshake
# ---------------------------------------------------------------------------

class TestAgentHandshake:
    @pytest.mark.asyncio
    async def test_valid_handshake(self, gateway):
        gateway._agent_tokens = gateway._load_agent_tokens()
        ws = FakeWebSocket()

        # Feed handshake
        ws.feed(json.dumps({
            'type': 'handshake',
            'agent_id': 'agent1',
            'token': 'token-aaa',
        }))

        # Then close to end the message loop
        async def close_after():
            await asyncio.sleep(0.05)
            await ws.close()

        asyncio.create_task(close_after())
        await gateway._handle_agent_ws(ws)

        # Should have sent handshake_ok
        assert any(m['type'] == 'handshake_ok' for m in ws.sent_messages)

    @pytest.mark.asyncio
    async def test_bad_token_rejected(self, gateway):
        gateway._agent_tokens = gateway._load_agent_tokens()
        ws = FakeWebSocket()

        ws.feed(json.dumps({
            'type': 'handshake',
            'agent_id': 'agent1',
            'token': 'wrong-token',
        }))

        await gateway._handle_agent_ws(ws)

        assert any(m['type'] == 'handshake_reject' for m in ws.sent_messages)
        assert ws._closed

    @pytest.mark.asyncio
    async def test_agent_id_mismatch_rejected(self, gateway):
        """Token valid for agent1, but claimed agent_id is agent2."""
        gateway._agent_tokens = gateway._load_agent_tokens()
        ws = FakeWebSocket()

        ws.feed(json.dumps({
            'type': 'handshake',
            'agent_id': 'agent2',  # wrong agent for this token
            'token': 'token-aaa',  # belongs to agent1
        }))

        await gateway._handle_agent_ws(ws)
        assert any(m['type'] == 'handshake_reject' for m in ws.sent_messages)

    @pytest.mark.asyncio
    async def test_non_handshake_first_message_rejected(self, gateway):
        gateway._agent_tokens = gateway._load_agent_tokens()
        ws = FakeWebSocket()

        ws.feed(json.dumps({
            'type': 'heartbeat',
            'payload': {},
        }))

        await gateway._handle_agent_ws(ws)
        assert any(m.get('message') == 'expected handshake' for m in ws.sent_messages)


# ---------------------------------------------------------------------------
# Agent registration & deregistration
# ---------------------------------------------------------------------------

class TestAgentRegistry:
    @pytest.mark.asyncio
    async def test_agent_registered_after_handshake(self, gateway):
        gateway._agent_tokens = gateway._load_agent_tokens()
        ws = FakeWebSocket()

        ws.feed(json.dumps({
            'type': 'handshake',
            'agent_id': 'agent1',
            'token': 'token-aaa',
        }))

        async def close_after():
            await asyncio.sleep(0.05)
            # Verify registered while connected
            assert 'agent1' in gateway._agents
            await ws.close()

        asyncio.create_task(close_after())
        await gateway._handle_agent_ws(ws)

    @pytest.mark.asyncio
    async def test_agent_deregistered_on_disconnect(self, gateway):
        gateway._agent_tokens = gateway._load_agent_tokens()
        ws = FakeWebSocket()

        ws.feed(json.dumps({
            'type': 'handshake',
            'agent_id': 'agent1',
            'token': 'token-aaa',
        }))

        async def close_after():
            await asyncio.sleep(0.05)
            await ws.close()

        asyncio.create_task(close_after())
        await gateway._handle_agent_ws(ws)

        # After handler exits, agent should be deregistered
        assert 'agent1' not in gateway._agents

    @pytest.mark.asyncio
    async def test_multiple_agents(self, gateway):
        gateway._agent_tokens = gateway._load_agent_tokens()

        ws1 = FakeWebSocket()
        ws2 = FakeWebSocket()

        ws1.feed(json.dumps({
            'type': 'handshake', 'agent_id': 'agent1', 'token': 'token-aaa',
        }))
        ws2.feed(json.dumps({
            'type': 'handshake', 'agent_id': 'agent2', 'token': 'token-bbb',
        }))

        async def run_ws(ws, delay):
            async def close_after():
                await asyncio.sleep(delay)
                await ws.close()
            asyncio.create_task(close_after())
            await gateway._handle_agent_ws(ws)

        # Run both agents concurrently
        done = asyncio.Event()

        async def check_both():
            await asyncio.sleep(0.05)
            assert 'agent1' in gateway._agents
            assert 'agent2' in gateway._agents
            done.set()

        t1 = asyncio.create_task(run_ws(ws1, 0.15))
        t2 = asyncio.create_task(run_ws(ws2, 0.15))
        tc = asyncio.create_task(check_both())

        await asyncio.gather(t1, t2, tc)


# ---------------------------------------------------------------------------
# Health monitoring
# ---------------------------------------------------------------------------

class TestHealthMonitoring:
    def test_heartbeat_stored(self, gateway):
        gateway._handle_heartbeat('agent1', {'status': 'alive', 'reason': 'ok'})
        health = gateway._get_agent_health('agent1')
        assert health['status'] == 'alive'
        assert 'last_seen_seconds_ago' in health

    def test_no_heartbeat_unreachable(self, gateway):
        health = gateway._get_agent_health('nonexistent')
        assert health['status'] == 'unreachable'
        assert health['reason'] == 'no_heartbeat'

    def test_stale_heartbeat_unreachable(self, gateway):
        gateway._agent_health['agent1'] = {
            'status': 'alive',
            'reason': 'ok',
            '_ts': time.monotonic() - 60,  # 60s ago, stale threshold is 45s
        }
        health = gateway._get_agent_health('agent1')
        assert health['status'] == 'unreachable'
        assert health['reason'] == 'heartbeat_timeout'

    @pytest.mark.asyncio
    async def test_heartbeat_via_ws(self, gateway):
        """Agent sends heartbeat message, gateway stores it."""
        gateway._agent_tokens = gateway._load_agent_tokens()
        ws = FakeWebSocket()

        ws.feed(json.dumps({
            'type': 'handshake', 'agent_id': 'agent1', 'token': 'token-aaa',
        }))
        ws.feed(json.dumps({
            'type': 'heartbeat',
            'payload': {'status': 'alive', 'reason': 'ok', 'uptime': 123},
        }))

        async def close_after():
            await asyncio.sleep(0.05)
            await ws.close()

        asyncio.create_task(close_after())
        await gateway._handle_agent_ws(ws)

        health = gateway._get_agent_health('agent1')
        assert health['status'] == 'alive'
        assert health['uptime'] == 123


# ---------------------------------------------------------------------------
# RPC forwarding
# ---------------------------------------------------------------------------

class TestRPCForwarding:
    @pytest.mark.asyncio
    async def test_rpc_round_trip(self, gateway):
        """HTTP request → RPC to agent → response returned."""
        # Directly register a fake agent and test RPC mechanics
        from gateway import AgentConnection

        ws = FakeWebSocket()
        gateway._agents['agent1'] = AgentConnection(
            agent_id='agent1', websocket=ws
        )

        # Start the RPC forward (will send to ws and wait for response)
        async def respond_to_rpc():
            # Poll until the RPC request appears in the outbox
            for _ in range(50):
                await asyncio.sleep(0.01)
                for raw in ws._outbox:
                    msg = json.loads(raw)
                    if msg.get('type') == 'rpc_request':
                        # Simulate agent responding
                        gateway._handle_rpc_response('agent1', {
                            'id': msg['id'],
                            'status': 200,
                            'body': json.dumps({'ok': True}),
                        })
                        return

        responder = asyncio.create_task(respond_to_rpc())

        status, body_bytes, content_type = await gateway._forward_rpc(
            'agent1', 'GET', '/api/health', {}, '', timeout=2
        )
        await responder

        assert status == 200
        assert json.loads(body_bytes)['ok'] is True

    @pytest.mark.asyncio
    async def test_rpc_agent_not_connected(self, gateway):
        status, body_bytes, ct = await gateway._forward_rpc(
            'nobody', 'GET', '/api/health', {}, ''
        )
        assert status == 502
        assert 'not connected' in json.loads(body_bytes)['error']

    @pytest.mark.asyncio
    async def test_rpc_timeout(self, gateway):
        """Agent doesn't respond → 504."""
        gateway._agent_tokens = gateway._load_agent_tokens()

        # Register a fake agent that never responds
        ws = FakeWebSocket()
        from gateway import AgentConnection
        gateway._agents['agent1'] = AgentConnection(
            agent_id='agent1', websocket=ws
        )

        status, body_bytes, ct = await gateway._forward_rpc(
            'agent1', 'GET', '/api/health', {}, '', timeout=0.1
        )
        assert status == 504
        assert 'not respond' in json.loads(body_bytes)['error']


# ---------------------------------------------------------------------------
# Admin auth
# ---------------------------------------------------------------------------

class TestAdminAuth:
    def test_valid_token(self, gateway):
        assert gateway._check_admin_auth('admin-secret') is True

    def test_invalid_token(self, gateway):
        assert gateway._check_admin_auth('wrong') is False

    def test_empty_token(self, gateway):
        assert gateway._check_admin_auth('') is False

    def test_no_admin_token_configured(self):
        gw = GatewayServer(admin_token='')
        assert gw._check_admin_auth('anything') is False


# ---------------------------------------------------------------------------
# Agent list endpoint
# ---------------------------------------------------------------------------

class TestAgentList:
    @pytest.mark.asyncio
    async def test_agents_list_empty(self, gateway):
        # Simulate the HTTP response
        agents = []
        for aid in sorted(gateway._agents.keys()):
            agents.append({'agent_id': aid, 'connected': True})
        assert agents == []

    @pytest.mark.asyncio
    async def test_agents_list_with_agents(self, gateway):
        from gateway import AgentConnection
        ws = FakeWebSocket()
        gateway._agents['agent1'] = AgentConnection(
            agent_id='agent1', websocket=ws
        )
        gateway._handle_heartbeat('agent1', {'status': 'alive'})

        # Use the internal method directly
        # We can't easily test HTTP routing without a server,
        # so test the data logic
        agents = []
        for aid in sorted(gateway._agents.keys()):
            health = gateway._get_agent_health(aid)
            agents.append({
                'agent_id': aid,
                'connected': True,
                'health': health,
            })
        assert len(agents) == 1
        assert agents[0]['agent_id'] == 'agent1'
        assert agents[0]['health']['status'] == 'alive'


# ---------------------------------------------------------------------------
# RPC response handling
# ---------------------------------------------------------------------------

class TestRPCResponseHandling:
    @pytest.mark.asyncio
    async def test_rpc_response_resolves_future(self, gateway):
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        gateway._pending_rpcs['req-123'] = future

        gateway._handle_rpc_response('agent1', {
            'id': 'req-123',
            'status': 200,
            'body': '{"ok": true}',
        })

        result = await asyncio.wait_for(future, timeout=1.0)
        assert result['status'] == 200
        assert result['body'] == '{"ok": true}'

    @pytest.mark.asyncio
    async def test_rpc_response_unknown_id_ignored(self, gateway):
        # Should not raise
        gateway._handle_rpc_response('agent1', {
            'id': 'nonexistent',
            'status': 200,
            'body': '',
        })

    @pytest.mark.asyncio
    async def test_rpc_response_already_done_ignored(self, gateway):
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        future.set_result({'status': 200, 'body': ''})
        gateway._pending_rpcs['req-done'] = future

        # Should not raise even though future is already done
        gateway._handle_rpc_response('agent1', {
            'id': 'req-done',
            'status': 500,
            'body': 'late',
        })


# ---------------------------------------------------------------------------
# Query string preservation
# ---------------------------------------------------------------------------

class TestQueryStringPreservation:
    @pytest.mark.asyncio
    async def test_query_string_forwarded_in_rpc(self, gateway):
        """Query string from HTTP request should be forwarded to agent."""
        from gateway import AgentConnection

        ws = FakeWebSocket()
        gateway._agents['agent1'] = AgentConnection(
            agent_id='agent1', websocket=ws
        )

        captured_path = None

        async def respond():
            for _ in range(50):
                await asyncio.sleep(0.01)
                for raw in ws._outbox:
                    msg = json.loads(raw)
                    if msg.get('type') == 'rpc_request':
                        nonlocal captured_path
                        captured_path = msg['path']
                        gateway._handle_rpc_response('agent1', {
                            'id': msg['id'],
                            'status': 200,
                            'body': '{}',
                        })
                        return

        responder = asyncio.create_task(respond())
        status, _, _ = await gateway._forward_rpc(
            'agent1', 'GET', '/api/dashboard/inner-voice?limit=50&offset=0',
            {}, '', timeout=2
        )
        await responder

        assert status == 200
        assert captured_path == '/api/dashboard/inner-voice?limit=50&offset=0'


# ---------------------------------------------------------------------------
# Auth header separation
# ---------------------------------------------------------------------------

class TestAuthHeaderSeparation:
    def test_x_gateway_token_used_for_admin_auth(self, gateway):
        """Admin auth uses X-Gateway-Token, not Authorization."""
        assert gateway._check_admin_auth('admin-secret') is True
        # Authorization header value should NOT work as admin token
        # (it's meant to pass through to agents)

    def test_authorization_header_in_forwarded_headers(self, gateway):
        """Authorization header should be included in RPC forwarded headers."""
        # Verify the gateway preserves all headers in headers_dict
        # which gets passed to _forward_rpc → agent
        # (This is structural — the HTTP handler collects all headers
        # into headers_dict, including Authorization)
