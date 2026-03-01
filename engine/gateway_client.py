"""Gateway client — runs inside each agent process.

Connects to the Gateway via persistent WebSocket, handles incoming RPC
requests by forwarding them to the local HTTP handler, and sends periodic
health heartbeats.

This module is opt-in: only activated when GATEWAY_URL env var is set.
If the Gateway is unreachable, the agent continues running in standalone
mode — no crash, just logged warnings with exponential backoff.
"""

import asyncio
import base64
import json
import time
from typing import Any, Callable, Awaitable, Optional


# Reconnect backoff: 1s → 2s → 4s → ... → 30s max
_BACKOFF_INITIAL = 1.0
_BACKOFF_MAX = 30.0
_BACKOFF_FACTOR = 2.0

# Health heartbeat interval
_HEARTBEAT_INTERVAL = 15.0


class GatewayClient:
    """Client that connects an agent to the Gateway.

    Args:
        gateway_url: WebSocket URL of the Gateway (e.g. ws://gateway:8001)
        agent_id: This agent's unique identifier
        agent_token: Auth token for this agent
        heartbeat: Reference to the Heartbeat instance (for get_health_status)
        local_handler: Async callable (method, path, headers, body)
            -> (status, body_bytes, content_type) that processes RPC requests
            locally using the agent's HTTP routing.
    """

    def __init__(
        self,
        gateway_url: str,
        agent_id: str,
        agent_token: str,
        heartbeat: Any,
        local_handler: Callable[
            [str, str, dict, str], Awaitable[tuple[int, bytes, str]]
        ],
    ):
        self._gateway_url = gateway_url
        self._agent_id = agent_id
        self._agent_token = agent_token
        self._heartbeat = heartbeat
        self._local_handler = local_handler
        self._ws: Optional[Any] = None
        self._task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self):
        """Start the connection loop as a background task."""
        self._running = True
        self._task = asyncio.create_task(self._connect_loop())

    async def stop(self):
        """Stop the client gracefully."""
        self._running = False

        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_task = None

        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _connect_loop(self):
        """Reconnect loop with exponential backoff."""
        backoff = _BACKOFF_INITIAL

        while self._running:
            try:
                import websockets
                async with websockets.connect(self._gateway_url) as ws:
                    self._ws = ws
                    backoff = _BACKOFF_INITIAL  # reset on successful connect

                    # Send handshake
                    await self._send_handshake()

                    # Wait for handshake response
                    raw = await asyncio.wait_for(ws.recv(), timeout=10)
                    resp = json.loads(raw)
                    if resp.get('type') == 'handshake_reject':
                        print(f"  [Gateway] Handshake rejected: "
                              f"{resp.get('message', 'unknown')}")
                        self._running = False
                        return
                    elif resp.get('type') != 'handshake_ok':
                        print(f"  [Gateway] Unexpected handshake response: "
                              f"{resp.get('type')}")
                        # Will retry
                        await asyncio.sleep(backoff)
                        backoff = min(backoff * _BACKOFF_FACTOR, _BACKOFF_MAX)
                        continue

                    print(f"  [Gateway] Connected to {self._gateway_url}")

                    # Start heartbeat sender
                    self._heartbeat_task = asyncio.create_task(
                        self._heartbeat_loop()
                    )

                    # Receive loop
                    await self._receive_loop()

            except asyncio.CancelledError:
                return
            except Exception as e:
                if not self._running:
                    return
                err_name = type(e).__name__
                if err_name not in ('ConnectionClosed', 'ConnectionClosedOK',
                                    'ConnectionClosedError'):
                    print(f"  [Gateway] Connection error ({err_name}): {e}")
                else:
                    print(f"  [Gateway] Disconnected from gateway")

            # Stop heartbeat on disconnect
            if self._heartbeat_task:
                self._heartbeat_task.cancel()
                try:
                    await self._heartbeat_task
                except asyncio.CancelledError:
                    pass
                self._heartbeat_task = None

            self._ws = None

            if not self._running:
                return

            print(f"  [Gateway] Reconnecting in {backoff:.0f}s...")
            await asyncio.sleep(backoff)
            backoff = min(backoff * _BACKOFF_FACTOR, _BACKOFF_MAX)

    async def _send_handshake(self):
        """Send the initial handshake message."""
        await self._ws.send(json.dumps({
            'type': 'handshake',
            'agent_id': self._agent_id,
            'token': self._agent_token,
        }))

    async def _heartbeat_loop(self):
        """Send health heartbeats every _HEARTBEAT_INTERVAL seconds."""
        while self._running and self._ws:
            try:
                payload = self._heartbeat.get_health_status()
                await self._ws.send(json.dumps({
                    'type': 'heartbeat',
                    'payload': payload,
                }))
            except asyncio.CancelledError:
                return
            except Exception as e:
                print(f"  [Gateway] Heartbeat send error: {e}")
            await asyncio.sleep(_HEARTBEAT_INTERVAL)

    async def _receive_loop(self):
        """Process incoming messages from the Gateway."""
        async for raw in self._ws:
            try:
                msg = json.loads(raw)
                msg_type = msg.get('type')

                if msg_type == 'rpc_request':
                    # Handle in background so we don't block receiving
                    asyncio.create_task(self._handle_rpc_request(msg))

            except (json.JSONDecodeError, KeyError) as e:
                print(f"  [Gateway] Bad message from gateway: {e}")

    async def _handle_rpc_request(self, msg: dict):
        """Handle an RPC request from the Gateway by forwarding to local handler."""
        req_id = msg.get('id', '')
        method = msg.get('method', 'GET')
        path = msg.get('path', '/')
        headers = msg.get('headers', {})
        body = msg.get('body', '')

        try:
            status, resp_body_bytes, content_type = await self._local_handler(
                method, path, headers, body
            )
        except Exception as e:
            print(f"  [Gateway] RPC handler error: {e}")
            status = 500
            resp_body_bytes = json.dumps({'error': 'internal handler error'}).encode()
            content_type = 'application/json'

        # Encode body for JSON transport.
        # Binary content types use base64; text/JSON stays as UTF-8 string.
        is_text = (content_type.startswith('text/')
                   or content_type.startswith('application/json'))
        if is_text:
            resp_body = resp_body_bytes.decode('utf-8', errors='replace')
            encoding = 'utf-8'
        else:
            resp_body = base64.b64encode(resp_body_bytes).decode('ascii')
            encoding = 'base64'

        # Send response back to Gateway
        try:
            if self._ws:
                await self._ws.send(json.dumps({
                    'type': 'rpc_response',
                    'id': req_id,
                    'status': status,
                    'body': resp_body,
                    'content_type': content_type,
                    'encoding': encoding,
                }))
        except Exception as e:
            print(f"  [Gateway] RPC response send error: {e}")
