#!/usr/bin/env python3
"""Gateway — standalone router process for multi-agent alive deployments.

Agents connect UP to the Gateway via persistent WebSocket. The Gateway:
- Tracks which agents are alive (they're connected)
- Forwards HTTP requests from Lounge/clients as RPC-over-WS to agents
- Collects health heartbeats and exposes a unified health endpoint

No business logic, no DB writes, no LLM calls — router only.

Start: python engine/gateway.py

Auth model:
    Gateway admin auth uses the X-Gateway-Token header (NOT Authorization).
    The Authorization header passes through transparently to agents, so
    agent-level auth (dashboard tokens, API keys) works without conflict.

Environment variables:
    GATEWAY_HTTP_PORT   — HTTP port for Lounge/client requests (default 8000)
    GATEWAY_WS_PORT     — WS port for agent connections (default 8001)
    GATEWAY_ADMIN_TOKEN — Required. Shared secret for HTTP API auth
    GATEWAY_TOKENS_PATH — Path to agent_tokens.json (default ./agent_tokens.json)
"""

import asyncio
import base64
import hmac
import json
import os
import signal
import sys
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

HTTP_PORT = int(os.environ.get('GATEWAY_HTTP_PORT', '8000'))
WS_PORT = int(os.environ.get('GATEWAY_WS_PORT', '8001'))
ADMIN_TOKEN = os.environ.get('GATEWAY_ADMIN_TOKEN', '')
TOKENS_PATH = os.environ.get('GATEWAY_TOKENS_PATH', './agent_tokens.json')
RPC_TIMEOUT = 30  # seconds
HEALTH_STALE_SECONDS = 45

# HTTP safety limits (match heartbeat_server.py)
_MAX_BODY_BYTES = 256 * 1024  # 256 KB — larger than agent limit, we're a proxy
_MAX_HEADER_COUNT = 50
_MAX_HEADER_BYTES = 8192


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class AgentConnection:
    """A connected agent's WS session."""
    agent_id: str
    websocket: Any  # websockets.WebSocketServerProtocol
    connected_at: float = field(default_factory=time.monotonic)


# ---------------------------------------------------------------------------
# GatewayServer
# ---------------------------------------------------------------------------

class GatewayServer:
    """Multi-agent gateway router.

    HTTP :http_port — Lounge/client requests (admin-token protected)
    WS   :ws_port   — Agent pod connections (per-agent token auth)
    """

    def __init__(
        self,
        http_port: int = HTTP_PORT,
        ws_port: int = WS_PORT,
        admin_token: str = ADMIN_TOKEN,
        tokens_path: str = TOKENS_PATH,
    ):
        self._http_port = http_port
        self._ws_port = ws_port
        self._admin_token = admin_token
        self._tokens_path = tokens_path

        # Agent registry
        self._agents: dict[str, AgentConnection] = {}  # agent_id → connection
        self._pending_rpcs: dict[str, asyncio.Future] = {}  # req_id → Future
        self._agent_health: dict[str, dict] = {}  # agent_id → health payload + _ts

        # Token file hot-reload
        self._agent_tokens: dict[str, str] = {}  # token → agent_id
        self._tokens_mtime: float = 0.0
        self._tokens_last_check: float = 0.0

        # Server handles
        self._http_server = None
        self._ws_server = None

    # ------------------------------------------------------------------
    # Agent token management (file-based, hot-reload on mtime)
    # ------------------------------------------------------------------

    def _load_agent_tokens(self) -> dict[str, str]:
        """Load agent tokens from JSON file. Format: {"agent_id": "token", ...}"""
        try:
            with open(self._tokens_path, 'r') as f:
                data = json.load(f)
            if not isinstance(data, dict):
                print(f"  [Gateway] WARNING: {self._tokens_path} must be a JSON object")
                return {}
            # Invert: we want token → agent_id for lookup
            return {token: agent_id for agent_id, token in data.items()}
        except FileNotFoundError:
            return {}
        except (json.JSONDecodeError, OSError) as e:
            print(f"  [Gateway] Token file error: {e}")
            return {}

    def _maybe_reload_tokens(self):
        """Reload tokens if file changed. Check mtime at most once/sec."""
        now = time.monotonic()
        if now - self._tokens_last_check < 1.0:
            return
        self._tokens_last_check = now
        try:
            mtime = os.path.getmtime(self._tokens_path)
            if mtime != self._tokens_mtime:
                self._agent_tokens = self._load_agent_tokens()
                self._tokens_mtime = mtime
                print(f"  [Gateway] Reloaded {len(self._agent_tokens)} agent tokens")
        except OSError:
            pass

    def _validate_agent_token(self, token: str) -> Optional[str]:
        """Validate an agent token. Returns agent_id if valid, None otherwise."""
        self._maybe_reload_tokens()
        for stored_token, agent_id in self._agent_tokens.items():
            if hmac.compare_digest(token, stored_token):
                return agent_id
        return None

    # ------------------------------------------------------------------
    # WebSocket handler (agent connections)
    # ------------------------------------------------------------------

    async def _handle_agent_ws(self, websocket):
        """Handle an agent WebSocket connection."""
        agent_id = None
        try:
            # Wait for handshake (first message must be handshake)
            raw = await asyncio.wait_for(websocket.recv(), timeout=10)
            msg = json.loads(raw)

            if msg.get('type') != 'handshake':
                await websocket.send(json.dumps({
                    'type': 'error',
                    'message': 'expected handshake',
                }))
                await websocket.close()
                return

            claimed_id = msg.get('agent_id', '')
            token = msg.get('token', '')

            # Validate token
            valid_id = self._validate_agent_token(token)
            if valid_id is None or valid_id != claimed_id:
                await websocket.send(json.dumps({
                    'type': 'handshake_reject',
                    'message': 'invalid token or agent_id mismatch',
                }))
                await websocket.close()
                return

            agent_id = claimed_id

            # Disconnect existing connection for same agent (replace)
            old = self._agents.pop(agent_id, None)
            if old:
                try:
                    await old.websocket.close()
                except Exception:
                    pass
                print(f"  [Gateway] Agent '{agent_id}' reconnected (replaced old)")

            # Register
            conn = AgentConnection(agent_id=agent_id, websocket=websocket)
            self._agents[agent_id] = conn

            await websocket.send(json.dumps({
                'type': 'handshake_ok',
                'message': f'registered as {agent_id}',
            }))
            print(f"  [Gateway] Agent '{agent_id}' connected")

            # Message loop
            async for raw_msg in websocket:
                try:
                    data = json.loads(raw_msg)
                    msg_type = data.get('type')

                    if msg_type == 'heartbeat':
                        self._handle_heartbeat(agent_id, data.get('payload', {}))

                    elif msg_type == 'rpc_response':
                        self._handle_rpc_response(agent_id, data)

                except (json.JSONDecodeError, KeyError) as e:
                    print(f"  [Gateway] Bad message from '{agent_id}': {e}")

        except asyncio.TimeoutError:
            print(f"  [Gateway] Handshake timeout")
        except Exception as e:
            err_name = type(e).__name__
            if err_name not in ('ConnectionClosed', 'ConnectionClosedOK',
                                'ConnectionClosedError'):
                print(f"  [Gateway] Agent WS error: {err_name}: {e}")
        finally:
            if agent_id and self._agents.get(agent_id, None) is not None:
                if self._agents[agent_id].websocket is websocket:
                    del self._agents[agent_id]
                    print(f"  [Gateway] Agent '{agent_id}' disconnected")

    # ------------------------------------------------------------------
    # Health monitoring
    # ------------------------------------------------------------------

    def _handle_heartbeat(self, agent_id: str, payload: dict):
        """Store latest health payload from an agent."""
        self._agent_health[agent_id] = {
            **payload,
            '_ts': time.monotonic(),
        }

    def _get_agent_health(self, agent_id: str) -> dict:
        """Return stored health or unreachable if stale/missing."""
        stored = self._agent_health.get(agent_id)
        if stored is None:
            return {'status': 'unreachable', 'reason': 'no_heartbeat'}

        age = time.monotonic() - stored.get('_ts', 0)
        if age > HEALTH_STALE_SECONDS:
            return {'status': 'unreachable', 'reason': 'heartbeat_timeout',
                    'last_seen_seconds_ago': round(age, 1)}

        # Return without internal timestamp
        result = {k: v for k, v in stored.items() if k != '_ts'}
        result['last_seen_seconds_ago'] = round(age, 1)
        return result

    # ------------------------------------------------------------------
    # RPC forwarding
    # ------------------------------------------------------------------

    async def _forward_rpc(
        self,
        agent_id: str,
        method: str,
        path: str,
        headers: dict,
        body: str,
        timeout: float = RPC_TIMEOUT,
    ) -> tuple[int, bytes, str]:
        """Forward an HTTP request to an agent via WS and wait for response.

        Returns (status_code, response_body_bytes, content_type).
        """
        conn = self._agents.get(agent_id)
        if conn is None:
            err = json.dumps({'error': f'agent {agent_id} not connected'})
            return 502, err.encode(), 'application/json'

        req_id = str(uuid.uuid4())
        envelope = json.dumps({
            'type': 'rpc_request',
            'id': req_id,
            'method': method,
            'path': path,
            'headers': headers,
            'body': body,
        })

        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending_rpcs[req_id] = future

        try:
            await conn.websocket.send(envelope)
            result = await asyncio.wait_for(future, timeout=timeout)
            body_raw = result.get('body', '')
            encoding = result.get('encoding', 'utf-8')
            content_type = result.get('content_type', 'application/json')
            # Decode body from transport encoding
            if encoding == 'base64':
                body_bytes = base64.b64decode(body_raw)
            else:
                body_bytes = body_raw.encode('utf-8') if isinstance(body_raw, str) else body_raw
            return result['status'], body_bytes, content_type
        except asyncio.TimeoutError:
            err = json.dumps({'error': 'agent did not respond in time'})
            return 504, err.encode(), 'application/json'
        except Exception as e:
            err = json.dumps({'error': f'rpc failed: {e}'})
            return 502, err.encode(), 'application/json'
        finally:
            self._pending_rpcs.pop(req_id, None)

    def _handle_rpc_response(self, agent_id: str, msg: dict):
        """Resolve a pending RPC future with the agent's response."""
        req_id = msg.get('id', '')
        future = self._pending_rpcs.get(req_id)
        if future and not future.done():
            future.set_result({
                'status': msg.get('status', 500),
                'body': msg.get('body', ''),
                'content_type': msg.get('content_type', 'application/json'),
                'encoding': msg.get('encoding', 'utf-8'),
            })

    # ------------------------------------------------------------------
    # HTTP handler (Lounge/client requests)
    # ------------------------------------------------------------------

    async def _handle_http(self, reader: asyncio.StreamReader,
                           writer: asyncio.StreamWriter):
        """Handle an incoming HTTP request from Lounge or other clients."""
        try:
            # Parse request line
            request_line = await asyncio.wait_for(reader.readline(), timeout=10)
            if not request_line:
                return

            # Parse headers
            content_length = 0
            gateway_token = ''
            headers_dict: dict[str, str] = {}
            header_count = 0
            while True:
                line = await asyncio.wait_for(reader.readline(), timeout=5)
                if line == b'\r\n' or line == b'\n' or not line:
                    break
                header_count += 1
                if header_count > _MAX_HEADER_COUNT:
                    await self._http_respond(writer, 431, {'error': 'too many headers'})
                    return
                if len(line) > _MAX_HEADER_BYTES:
                    await self._http_respond(writer, 431, {'error': 'header too large'})
                    return
                header = line.decode('utf-8', errors='replace').strip()
                header_lower = header.lower()
                if ':' in header:
                    hname, hval = header.split(':', 1)
                    headers_dict[hname.strip()] = hval.strip()
                if header_lower.startswith('content-length:'):
                    try:
                        content_length = int(header.split(':', 1)[1].strip())
                    except ValueError:
                        pass
                elif header_lower.startswith('x-gateway-token:'):
                    gateway_token = header.split(':', 1)[1].strip()

            request_text = request_line.decode('utf-8', errors='replace').strip()
            parts = request_text.split()
            method = parts[0] if parts else 'GET'
            raw_path = parts[1] if len(parts) > 1 else '/'
            path = raw_path.split('?')[0]  # path without query for routing
            # raw_path preserved with query string for RPC forwarding

            # Body size limit
            if content_length > _MAX_BODY_BYTES:
                await self._http_respond(writer, 413, {'error': 'payload too large'})
                return

            # Read body
            body_str = ''
            if content_length > 0:
                body_bytes = await asyncio.wait_for(
                    reader.readexactly(content_length), timeout=10
                )
                body_str = body_bytes.decode('utf-8', errors='replace')

            # CORS preflight
            if method == 'OPTIONS':
                await self._http_cors_preflight(writer)
                return

            # ── Routing ──

            # Admin auth check for all non-OPTIONS requests
            # Uses X-Gateway-Token header (not Authorization, which passes
            # through transparently to agents for their own auth).
            if not self._check_admin_auth(gateway_token):
                await self._http_respond(writer, 401, {'error': 'unauthorized'})
                return

            if path == '/agents' and method == 'GET':
                await self._http_agents_list(writer)

            elif path.startswith('/agents/'):
                # Extract agent_id and sub-path from the clean path
                remainder = path[len('/agents/'):]
                slash_idx = remainder.find('/')
                if slash_idx == -1:
                    agent_id = remainder
                    sub_path = ''
                else:
                    agent_id = remainder[:slash_idx]
                    sub_path = remainder[slash_idx:]

                if sub_path == '/health' and method == 'GET':
                    await self._http_agent_health(writer, agent_id)
                elif agent_id:
                    # Forward as RPC to agent
                    # Strip /agents/{id} prefix — agent sees its own path space.
                    # Reconstruct with query string so agent gets full URL.
                    prefix = f'/agents/{agent_id}'
                    agent_path = raw_path[len(prefix):] or '/'
                    status, resp_bytes, content_type = await self._forward_rpc(
                        agent_id, method, agent_path, headers_dict, body_str
                    )
                    await self._http_raw_respond(
                        writer, status, resp_bytes, content_type
                    )
                else:
                    await self._http_respond(writer, 400, {'error': 'missing agent_id'})
            else:
                await self._http_respond(writer, 404, {'error': 'not found'})

        except (asyncio.TimeoutError, ConnectionResetError, BrokenPipeError):
            pass
        except Exception as e:
            print(f'  [Gateway] HTTP error: {e}')
            try:
                await self._http_respond(writer, 500, {'error': 'internal server error'})
            except Exception:
                pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    def _check_admin_auth(self, gateway_token: str) -> bool:
        """Validate admin token from X-Gateway-Token header."""
        if not self._admin_token:
            return False
        if not gateway_token:
            return False
        return hmac.compare_digest(gateway_token, self._admin_token)

    async def _http_agents_list(self, writer: asyncio.StreamWriter):
        """GET /agents — list all connected agents with status."""
        agents = []
        for agent_id in sorted(self._agents.keys()):
            health = self._get_agent_health(agent_id)
            agents.append({
                'agent_id': agent_id,
                'connected': True,
                'health': health,
            })
        # Also include agents with health data but not currently connected
        for agent_id in sorted(self._agent_health.keys()):
            if agent_id not in self._agents:
                health = self._get_agent_health(agent_id)
                agents.append({
                    'agent_id': agent_id,
                    'connected': False,
                    'health': health,
                })
        await self._http_respond(writer, 200, {'agents': agents})

    async def _http_agent_health(self, writer: asyncio.StreamWriter,
                                  agent_id: str):
        """GET /agents/{id}/health — return latest health for one agent."""
        if agent_id not in self._agents and agent_id not in self._agent_health:
            await self._http_respond(writer, 404, {
                'error': f'agent {agent_id} not found',
            })
            return
        health = self._get_agent_health(agent_id)
        await self._http_respond(writer, 200, health)

    # ------------------------------------------------------------------
    # HTTP response helpers
    # ------------------------------------------------------------------

    _STATUS_TEXT = {
        200: 'OK', 204: 'No Content', 400: 'Bad Request',
        401: 'Unauthorized', 403: 'Forbidden', 404: 'Not Found',
        413: 'Payload Too Large', 431: 'Request Header Fields Too Large',
        500: 'Internal Server Error', 502: 'Bad Gateway',
        504: 'Gateway Timeout',
    }

    async def _http_respond(self, writer: asyncio.StreamWriter,
                             status: int, body: dict):
        """Send an HTTP JSON response."""
        payload = json.dumps(body)
        status_text = self._STATUS_TEXT.get(status, 'Unknown')
        response = (
            f'HTTP/1.1 {status} {status_text}\r\n'
            f'Content-Type: application/json\r\n'
            f'Content-Length: {len(payload)}\r\n'
            f'Access-Control-Allow-Origin: *\r\n'
            f'Connection: close\r\n'
            f'\r\n'
            f'{payload}'
        )
        writer.write(response.encode())
        await writer.drain()

    async def _http_raw_respond(self, writer: asyncio.StreamWriter,
                                 status: int, body_bytes: bytes,
                                 content_type: str = 'application/json'):
        """Send an HTTP response with raw bytes (proxied from agent)."""
        status_text = self._STATUS_TEXT.get(status, 'Unknown')
        response_header = (
            f'HTTP/1.1 {status} {status_text}\r\n'
            f'Content-Type: {content_type}\r\n'
            f'Content-Length: {len(body_bytes)}\r\n'
            f'Access-Control-Allow-Origin: *\r\n'
            f'Connection: close\r\n'
            f'\r\n'
        )
        writer.write(response_header.encode())
        writer.write(body_bytes)
        await writer.drain()

    async def _http_cors_preflight(self, writer: asyncio.StreamWriter):
        """Handle OPTIONS preflight for CORS."""
        response = (
            'HTTP/1.1 204 No Content\r\n'
            'Access-Control-Allow-Origin: *\r\n'
            'Access-Control-Allow-Methods: GET, POST, PUT, PATCH, DELETE, OPTIONS\r\n'
            'Access-Control-Allow-Headers: Content-Type, Authorization, X-Gateway-Token\r\n'
            'Access-Control-Max-Age: 86400\r\n'
            'Content-Length: 0\r\n'
            'Connection: close\r\n'
            '\r\n'
        )
        writer.write(response.encode())
        await writer.drain()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self):
        """Start HTTP and WS servers."""
        # Load tokens
        self._agent_tokens = self._load_agent_tokens()
        try:
            self._tokens_mtime = os.path.getmtime(self._tokens_path)
        except OSError:
            pass
        print(f"  [Gateway] Loaded {len(self._agent_tokens)} agent tokens"
              f" from {self._tokens_path}")

        if not self._admin_token:
            print(f"  [Gateway] WARNING: GATEWAY_ADMIN_TOKEN not set — "
                  f"all HTTP requests will be rejected")

        # Start HTTP server
        self._http_server = await asyncio.start_server(
            self._handle_http, '0.0.0.0', self._http_port
        )
        print(f"  [Gateway] HTTP on 0.0.0.0:{self._http_port}")

        # Start WS server
        import websockets
        self._ws_server = await websockets.serve(
            self._handle_agent_ws, '0.0.0.0', self._ws_port
        )
        print(f"  [Gateway] WS   on 0.0.0.0:{self._ws_port}")

        print(f"  [Gateway] Ready. Waiting for agents...")

        # Run both servers
        await asyncio.gather(
            self._http_server.serve_forever(),
            self._ws_server.serve_forever(),
        )

    async def shutdown(self):
        """Graceful shutdown."""
        print(f"\n  [Gateway] Shutting down...")

        # Cancel pending RPCs
        for req_id, future in list(self._pending_rpcs.items()):
            if not future.done():
                future.cancel()
        self._pending_rpcs.clear()

        # Close agent connections
        for agent_id, conn in list(self._agents.items()):
            try:
                await conn.websocket.close()
            except Exception:
                pass
        self._agents.clear()

        # Stop servers
        if self._http_server:
            self._http_server.close()
            await self._http_server.wait_closed()

        if self._ws_server:
            self._ws_server.close()
            try:
                await self._ws_server.wait_closed()
            except Exception:
                pass

        print(f"  [Gateway] Stopped.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def run_gateway():
    server = GatewayServer()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(server.shutdown()))

    await server.start()


if __name__ == '__main__':
    asyncio.run(run_gateway())
