"""Tests for MCP dashboard route handlers in api/dashboard_routes.py."""

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from pipeline.action_registry import ACTION_REGISTRY, ActionCapability
import body.mcp_registry as registry
from api.dashboard_routes import (
    check_dashboard_auth,
    handle_toggle_capability,
    handle_mcp_servers_list,
    handle_mcp_connect,
    handle_mcp_server_toggle,
    handle_mcp_server_delete,
    handle_mcp_tool_toggle,
)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_server():
    server = MagicMock()
    server._http_json = AsyncMock()
    server.heartbeat = MagicMock()
    server.heartbeat._identity = MagicMock()
    server.heartbeat._identity.actions_enabled = None  # None = all allowed
    server._agent_config_dir = None
    return server


def _cleanup_mcp():
    to_remove = [k for k in ACTION_REGISTRY if k.startswith('mcp_')]
    for k in to_remove:
        del ACTION_REGISTRY[k]
    registry._servers.clear()


# ── /capabilities guard ──

class TestCapabilitiesMcpGuard(unittest.TestCase):
    """POST /capabilities rejects mcp_* action names with 400."""

    def setUp(self):
        _cleanup_mcp()

    def tearDown(self):
        _cleanup_mcp()

    @patch('api.dashboard_routes.check_dashboard_auth', return_value=True)
    def test_mcp_action_rejected(self, _auth):
        server = _make_server()
        writer = MagicMock()
        body = json.dumps({'action': 'mcp_5_search', 'enabled': True}).encode()
        _run(handle_toggle_capability(server, writer, 'Bearer valid', body))
        args = server._http_json.call_args[0]
        self.assertEqual(args[1], 400)
        self.assertIn('mcp', args[2]['error'].lower())

    @patch('api.dashboard_routes.check_dashboard_auth', return_value=True)
    def test_non_mcp_action_passes_guard(self, _auth):
        """Non-mcp actions don't hit the mcp guard (may 404 for unknown)."""
        server = _make_server()
        writer = MagicMock()
        body = json.dumps({'action': 'speak', 'enabled': True}).encode()
        _run(handle_toggle_capability(server, writer, 'Bearer valid', body))
        args = server._http_json.call_args[0]
        # Should NOT be 400 with mcp error — either 404 (unknown) or 200
        if args[1] == 400:
            self.assertNotIn('mcp', args[2].get('error', '').lower())


# ── GET /mcp/servers ──

class TestMcpServersList(unittest.TestCase):

    @patch('api.dashboard_routes.check_dashboard_auth', return_value=True)
    @patch('db.get_mcp_servers', new_callable=AsyncMock)
    @patch('db.get_mcp_tool_usage_counts', new_callable=AsyncMock)
    def test_list_empty(self, mock_counts, mock_servers, _auth):
        mock_servers.return_value = []
        server = _make_server()
        writer = MagicMock()
        _run(handle_mcp_servers_list(server, writer, 'Bearer valid'))
        args = server._http_json.call_args[0]
        self.assertEqual(args[1], 200)
        self.assertEqual(args[2], [])

    @patch('api.dashboard_routes.check_dashboard_auth', return_value=True)
    @patch('db.get_mcp_servers', new_callable=AsyncMock)
    @patch('db.get_mcp_tool_usage_counts', new_callable=AsyncMock)
    def test_list_with_server(self, mock_counts, mock_servers, _auth):
        mock_servers.return_value = [{
            'id': 1, 'name': 'Test', 'url': 'http://test',
            'enabled': 1, 'connected_at': '2026-01-01',
            'discovered_tools': [
                {'name': 'search', 'description': 'Search', 'enabled': True,
                 'action_suffix': 'search'},
            ],
        }]
        mock_counts.return_value = {'search': 5}

        server = _make_server()
        writer = MagicMock()
        _run(handle_mcp_servers_list(server, writer, 'Bearer valid'))
        args = server._http_json.call_args[0]
        self.assertEqual(args[1], 200)
        result = args[2]
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['id'], 1)
        self.assertEqual(result[0]['tools'][0]['usage_count'], 5)

    @patch('api.dashboard_routes.check_dashboard_auth', return_value=False)
    def test_unauthorized(self, _auth):
        server = _make_server()
        writer = MagicMock()
        _run(handle_mcp_servers_list(server, writer, ''))
        args = server._http_json.call_args[0]
        self.assertEqual(args[1], 401)


# ── POST /mcp/connect ──

class TestMcpConnect(unittest.TestCase):

    def setUp(self):
        _cleanup_mcp()

    def tearDown(self):
        _cleanup_mcp()

    @patch('api.dashboard_routes.check_dashboard_auth', return_value=True)
    @patch('db.get_mcp_server_by_url', new_callable=AsyncMock, return_value=None)
    @patch('db.create_mcp_server', new_callable=AsyncMock, return_value=10)
    @patch('db.get_mcp_server', new_callable=AsyncMock)
    def test_connect_new_server(self, mock_get, mock_create, mock_by_url, _auth):
        from body.mcp_client import McpServerInfo, McpToolSchema

        mock_tools = [McpToolSchema(name='search', description='Search', input_schema={})]
        mock_info = McpServerInfo(url='http://test', name='TestMCP', tools=mock_tools)

        mock_get.return_value = {
            'id': 10, 'url': 'http://test', 'enabled': 1,
            'discovered_tools': [
                {'name': 'search', 'description': 'Search', 'input_schema': {},
                 'enabled': True, 'action_suffix': 'search'},
            ],
        }

        with patch('body.mcp_registry.get_client') as mock_client_fn:
            mock_client = MagicMock()
            mock_client.connect = AsyncMock(return_value=mock_info)
            mock_client_fn.return_value = mock_client

            server = _make_server()
            writer = MagicMock()
            body = json.dumps({'url': 'http://test', 'name': 'TestMCP'}).encode()
            _run(handle_mcp_connect(server, writer, 'Bearer valid', body))

        args = server._http_json.call_args[0]
        self.assertEqual(args[1], 200)
        self.assertEqual(args[2]['id'], 10)
        self.assertEqual(args[2]['name'], 'TestMCP')
        self.assertEqual(len(args[2]['tools']), 1)

    @patch('api.dashboard_routes.check_dashboard_auth', return_value=True)
    @patch('db.get_mcp_server_by_url', new_callable=AsyncMock)
    @patch('db.update_mcp_server', new_callable=AsyncMock)
    @patch('db.get_mcp_server', new_callable=AsyncMock)
    def test_connect_idempotent_same_url(self, mock_get, mock_update, mock_by_url, _auth):
        """POST same URL twice → updates existing, doesn't create new."""
        from body.mcp_client import McpServerInfo, McpToolSchema

        mock_by_url.return_value = {'id': 5}
        mock_tools = [McpToolSchema(name='fetch', description='Fetch', input_schema={})]
        mock_info = McpServerInfo(url='http://test', name='Updated', tools=mock_tools)

        mock_get.return_value = {
            'id': 5, 'url': 'http://test', 'enabled': 1,
            'discovered_tools': [
                {'name': 'fetch', 'description': 'Fetch', 'input_schema': {},
                 'enabled': True, 'action_suffix': 'fetch'},
            ],
        }

        with patch('body.mcp_registry.get_client') as mock_client_fn:
            mock_client = MagicMock()
            mock_client.connect = AsyncMock(return_value=mock_info)
            mock_client_fn.return_value = mock_client

            server = _make_server()
            writer = MagicMock()
            body = json.dumps({'url': 'http://test'}).encode()
            _run(handle_mcp_connect(server, writer, 'Bearer valid', body))

        args = server._http_json.call_args[0]
        self.assertEqual(args[1], 200)
        self.assertEqual(args[2]['id'], 5)
        mock_update.assert_called_once()

    @patch('api.dashboard_routes.check_dashboard_auth', return_value=True)
    def test_connect_missing_url(self, _auth):
        server = _make_server()
        writer = MagicMock()
        body = json.dumps({'name': 'NoUrl'}).encode()
        _run(handle_mcp_connect(server, writer, 'Bearer valid', body))
        args = server._http_json.call_args[0]
        self.assertEqual(args[1], 400)

    @patch('api.dashboard_routes.check_dashboard_auth', return_value=True)
    def test_connect_server_unreachable(self, _auth):
        """Connection failure returns 502."""
        with patch('body.mcp_registry.get_client') as mock_client_fn:
            mock_client = MagicMock()
            mock_client.connect = AsyncMock(side_effect=ConnectionError("refused"))
            mock_client_fn.return_value = mock_client

            server = _make_server()
            writer = MagicMock()
            body = json.dumps({'url': 'http://dead'}).encode()
            _run(handle_mcp_connect(server, writer, 'Bearer valid', body))

        args = server._http_json.call_args[0]
        self.assertEqual(args[1], 502)


# ── PATCH /mcp/:id (server toggle) ──

class TestMcpServerToggle(unittest.TestCase):

    def setUp(self):
        _cleanup_mcp()

    def tearDown(self):
        _cleanup_mcp()

    @patch('api.dashboard_routes.check_dashboard_auth', return_value=True)
    @patch('db.get_mcp_server', new_callable=AsyncMock)
    @patch('db.update_mcp_server', new_callable=AsyncMock)
    def test_disable_server(self, mock_update, mock_get, _auth):
        mock_get.return_value = {
            'id': 1, 'url': 'http://test', 'enabled': 1,
            'discovered_tools': [
                {'name': 's', 'description': 'S', 'input_schema': {},
                 'enabled': True, 'action_suffix': 's'},
            ],
        }
        # Register first so there's something to unregister
        registry.register_server(1, mock_get.return_value)

        server = _make_server()
        writer = MagicMock()
        body = json.dumps({'enabled': False}).encode()
        _run(handle_mcp_server_toggle(server, writer, 'Bearer valid', body, 1))

        args = server._http_json.call_args[0]
        self.assertEqual(args[1], 200)
        self.assertFalse(args[2]['enabled'])

    @patch('api.dashboard_routes.check_dashboard_auth', return_value=True)
    @patch('db.get_mcp_server', new_callable=AsyncMock, return_value=None)
    def test_toggle_nonexistent(self, mock_get, _auth):
        server = _make_server()
        writer = MagicMock()
        body = json.dumps({'enabled': True}).encode()
        _run(handle_mcp_server_toggle(server, writer, 'Bearer valid', body, 999))
        args = server._http_json.call_args[0]
        self.assertEqual(args[1], 404)


# ── DELETE /mcp/:id ──

class TestMcpServerDelete(unittest.TestCase):

    def setUp(self):
        _cleanup_mcp()

    def tearDown(self):
        _cleanup_mcp()

    @patch('api.dashboard_routes.check_dashboard_auth', return_value=True)
    @patch('db.get_mcp_server', new_callable=AsyncMock)
    @patch('db.delete_mcp_server', new_callable=AsyncMock)
    def test_delete_server(self, mock_delete, mock_get, _auth):
        mock_get.return_value = {
            'id': 1, 'url': 'http://test', 'enabled': 1,
            'discovered_tools': [
                {'name': 'a', 'description': 'A', 'input_schema': {},
                 'enabled': True, 'action_suffix': 'a'},
            ],
        }
        registry.register_server(1, mock_get.return_value)

        server = _make_server()
        writer = MagicMock()
        _run(handle_mcp_server_delete(server, writer, 'Bearer valid', 1))

        args = server._http_json.call_args[0]
        self.assertEqual(args[1], 200)
        self.assertTrue(args[2]['deleted'])
        mock_delete.assert_called_once_with(1)
        # Runtime cache should be cleaned
        self.assertNotIn(1, registry._servers)

    @patch('api.dashboard_routes.check_dashboard_auth', return_value=True)
    @patch('db.get_mcp_server', new_callable=AsyncMock, return_value=None)
    def test_delete_nonexistent(self, mock_get, _auth):
        server = _make_server()
        writer = MagicMock()
        _run(handle_mcp_server_delete(server, writer, 'Bearer valid', 999))
        args = server._http_json.call_args[0]
        self.assertEqual(args[1], 404)


# ── PATCH /mcp/:id/tools/:suffix ──

class TestMcpToolToggle(unittest.TestCase):

    def setUp(self):
        _cleanup_mcp()

    def tearDown(self):
        _cleanup_mcp()

    @patch('api.dashboard_routes.check_dashboard_auth', return_value=True)
    @patch('db.get_mcp_server', new_callable=AsyncMock)
    @patch('db.update_mcp_tool_enabled', new_callable=AsyncMock)
    def test_disable_tool(self, mock_update, mock_get, _auth):
        mock_get.return_value = {
            'id': 1, 'url': 'http://test', 'enabled': 1,
            'discovered_tools': [
                {'name': 'search', 'description': 'Search', 'input_schema': {},
                 'enabled': True, 'action_suffix': 'search'},
            ],
        }
        registry.register_server(1, mock_get.return_value)
        self.assertIn('mcp_1_search', ACTION_REGISTRY)

        server = _make_server()
        writer = MagicMock()
        body = json.dumps({'enabled': False}).encode()
        _run(handle_mcp_tool_toggle(server, writer, 'Bearer valid', body, 1, 'search'))

        args = server._http_json.call_args[0]
        self.assertEqual(args[1], 200)
        self.assertFalse(args[2]['enabled'])
        self.assertNotIn('mcp_1_search', ACTION_REGISTRY)

    @patch('api.dashboard_routes.check_dashboard_auth', return_value=True)
    @patch('db.get_mcp_server', new_callable=AsyncMock)
    @patch('db.update_mcp_tool_enabled', new_callable=AsyncMock)
    def test_enable_tool(self, mock_update, mock_get, _auth):
        mock_get.return_value = {
            'id': 1, 'url': 'http://test', 'enabled': 1,
            'discovered_tools': [
                {'name': 'search', 'description': 'Search', 'input_schema': {},
                 'enabled': False, 'action_suffix': 'search'},
            ],
        }
        registry.register_server(1, mock_get.return_value)
        # search is disabled, so not in ACTION_REGISTRY
        self.assertNotIn('mcp_1_search', ACTION_REGISTRY)

        server = _make_server()
        writer = MagicMock()
        body = json.dumps({'enabled': True}).encode()
        _run(handle_mcp_tool_toggle(server, writer, 'Bearer valid', body, 1, 'search'))

        args = server._http_json.call_args[0]
        self.assertEqual(args[1], 200)
        self.assertTrue(args[2]['enabled'])
        self.assertIn('mcp_1_search', ACTION_REGISTRY)

    @patch('api.dashboard_routes.check_dashboard_auth', return_value=True)
    @patch('db.get_mcp_server', new_callable=AsyncMock, return_value=None)
    def test_toggle_tool_server_not_found(self, mock_get, _auth):
        server = _make_server()
        writer = MagicMock()
        body = json.dumps({'enabled': True}).encode()
        _run(handle_mcp_tool_toggle(server, writer, 'Bearer valid', body, 999, 'search'))
        args = server._http_json.call_args[0]
        self.assertEqual(args[1], 404)

    @patch('api.dashboard_routes.check_dashboard_auth', return_value=True)
    @patch('db.get_mcp_server', new_callable=AsyncMock)
    def test_enable_tool_rejected_when_server_disabled(self, mock_get, _auth):
        """Can't enable a tool when its parent server is disabled (409)."""
        mock_get.return_value = {
            'id': 1, 'url': 'http://test', 'enabled': 0,
            'discovered_tools': [
                {'name': 'search', 'description': 'Search', 'input_schema': {},
                 'enabled': False, 'action_suffix': 'search'},
            ],
        }
        registry.register_server(1, mock_get.return_value)

        server = _make_server()
        writer = MagicMock()
        body = json.dumps({'enabled': True}).encode()
        _run(handle_mcp_tool_toggle(server, writer, 'Bearer valid', body, 1, 'search'))

        args = server._http_json.call_args[0]
        self.assertEqual(args[1], 409)
        self.assertIn('disabled', args[2]['error'].lower())


if __name__ == '__main__':
    unittest.main()
