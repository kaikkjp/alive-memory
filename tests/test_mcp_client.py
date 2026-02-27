"""Tests for body/mcp_client.py — MCP JSON-RPC transport."""

import asyncio
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from body.mcp_client import McpClient, McpServerInfo, McpToolSchema, McpToolResult


class TestMcpClientCircuitBreaker(unittest.TestCase):
    """Circuit breaker logic (sync, no network)."""

    def test_breaker_closed_initially(self):
        client = McpClient()
        self.assertFalse(client._is_circuit_open('http://test'))

    def test_breaker_opens_after_threshold(self):
        client = McpClient()
        for _ in range(3):
            client._record_failure('http://test')
        self.assertTrue(client._is_circuit_open('http://test'))

    def test_breaker_resets_on_success(self):
        client = McpClient()
        for _ in range(2):
            client._record_failure('http://test')
        client._record_success('http://test')
        self.assertFalse(client._is_circuit_open('http://test'))
        self.assertEqual(client._failure_counts.get('http://test'), 0)

    def test_breaker_resets_after_cooldown(self):
        client = McpClient()
        client.BREAKER_COOLDOWN = 0.01  # 10ms for test
        for _ in range(3):
            client._record_failure('http://test')
        self.assertTrue(client._is_circuit_open('http://test'))
        time.sleep(0.02)
        self.assertFalse(client._is_circuit_open('http://test'))

    def test_breaker_per_url(self):
        client = McpClient()
        for _ in range(3):
            client._record_failure('http://a')
        self.assertTrue(client._is_circuit_open('http://a'))
        self.assertFalse(client._is_circuit_open('http://b'))


class TestMcpClientConnect(unittest.IsolatedAsyncioTestCase):
    """Connect flow (mocked aiohttp)."""

    @patch('body.mcp_client.McpClient.TIMEOUT', 5)
    async def test_connect_success(self):
        """Successful connect returns McpServerInfo with tools."""
        client = McpClient()

        init_response = {
            "jsonrpc": "2.0", "id": 1,
            "result": {"serverInfo": {"name": "TestServer"}, "protocolVersion": "2024-11-05"}
        }
        tools_response = {
            "jsonrpc": "2.0", "id": 3,
            "result": {"tools": [
                {"name": "search", "description": "Search things", "inputSchema": {}},
                {"name": "fetch", "description": "Fetch data", "inputSchema": {}},
            ]}
        }

        mock_resp = AsyncMock()
        mock_resp.json = AsyncMock(side_effect=[init_response, tools_response])
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.post = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch('aiohttp.ClientSession', return_value=mock_session):
            info = await client.connect('http://test-server')

        self.assertEqual(info.name, 'TestServer')
        self.assertEqual(info.url, 'http://test-server')
        self.assertEqual(len(info.tools), 2)
        self.assertEqual(info.tools[0].name, 'search')
        self.assertEqual(info.tools[1].name, 'fetch')

    async def test_connect_failure_records(self):
        """Connection failure increments failure count."""
        client = McpClient()

        with patch('aiohttp.ClientSession') as mock_cls:
            mock_session = AsyncMock()
            mock_session.post = MagicMock(side_effect=Exception("connection refused"))
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_session

            with self.assertRaises(ConnectionError):
                await client.connect('http://bad')

        self.assertEqual(client._failure_counts.get('http://bad'), 1)

    async def test_connect_blocked_by_breaker(self):
        """Connect raises when circuit breaker is open."""
        client = McpClient()
        for _ in range(3):
            client._record_failure('http://test')

        with self.assertRaises(ConnectionError) as ctx:
            await client.connect('http://test')
        self.assertIn('Circuit breaker', str(ctx.exception))


class TestMcpClientCallTool(unittest.IsolatedAsyncioTestCase):
    """Tool call flow (mocked aiohttp)."""

    async def test_call_tool_success(self):
        """Successful tool call returns content."""
        client = McpClient()

        tool_response = {
            "jsonrpc": "2.0", "id": 1,
            "result": {"content": [{"type": "text", "text": "Found 3 items"}]}
        }

        mock_resp = AsyncMock()
        mock_resp.json = AsyncMock(return_value=tool_response)
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.post = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch('aiohttp.ClientSession', return_value=mock_session):
            result = await client.call_tool('http://test', 'search', {'query': 'hello'})

        self.assertTrue(result.success)
        self.assertEqual(result.content, 'Found 3 items')
        self.assertEqual(result.error, '')

    async def test_call_tool_error_response(self):
        """JSON-RPC error response returns failure result."""
        client = McpClient()

        error_response = {
            "jsonrpc": "2.0", "id": 1,
            "error": {"code": -1, "message": "Tool not found"}
        }

        mock_resp = AsyncMock()
        mock_resp.json = AsyncMock(return_value=error_response)
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.post = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch('aiohttp.ClientSession', return_value=mock_session):
            result = await client.call_tool('http://test', 'bad_tool', {})

        self.assertFalse(result.success)
        self.assertIn('Tool not found', result.error)

    async def test_call_tool_network_error(self):
        """Network error returns failure result, not exception."""
        client = McpClient()

        with patch('aiohttp.ClientSession') as mock_cls:
            mock_session = AsyncMock()
            mock_session.post = MagicMock(side_effect=Exception("timeout"))
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_session

            result = await client.call_tool('http://test', 'search', {})

        self.assertFalse(result.success)
        self.assertIn('timeout', result.error)

    async def test_call_tool_breaker_blocks(self):
        """Tool call blocked when circuit breaker open."""
        client = McpClient()
        for _ in range(3):
            client._record_failure('http://test')

        result = await client.call_tool('http://test', 'search', {})
        self.assertFalse(result.success)
        self.assertIn('circuit_breaker', result.error)


if __name__ == '__main__':
    unittest.main()
