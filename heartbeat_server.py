#!/usr/bin/env python3
"""Heartbeat Server — the shopkeeper's life. Runs forever.

Start: python heartbeat_server.py
She lives. She journals at 3am. Her drives shift overnight.
Terminal connects when you want to visit.
Close the terminal, she keeps living.

Window viewers connect via WebSocket on SHOPKEEPER_WS_PORT (default 8765).
REST API available on SHOPKEEPER_HTTP_PORT (default 8080).
"""

import asyncio
import errno
import json
import os
import signal
import sys
from datetime import datetime, timezone
from dotenv import load_dotenv

from colorama import Fore, Style, init as colorama_init

# Load environment variables from .env file
load_dotenv()

import db
from heartbeat import Heartbeat
from seed import seed, check_needs_seed
from models.event import Event
from pipeline.ack import on_visitor_message, on_visitor_connect, on_visitor_disconnect
from pipeline.enrich import fetch_url_metadata
from pipeline.sanitize import sanitize_input

colorama_init()

HOST = 'localhost'
PORT = 9999
WS_PORT = int(os.environ.get('SHOPKEEPER_WS_PORT', '8765'))
HTTP_PORT = int(os.environ.get('SHOPKEEPER_HTTP_PORT', '8080'))


class ShopkeeperServer:
    """TCP server that bridges visitor terminals to the heartbeat.
    Also serves WebSocket for window viewers and HTTP for REST API.
    """

    def __init__(self):
        self.heartbeat = Heartbeat()
        self.connections: dict[str, asyncio.StreamWriter] = {}  # visitor_id → writer
        self._active_visitor_id: str | None = None
        self._server = None
        self._ws_server = None
        self._http_server = None
        self._window_clients: set = set()  # WebSocket connections for window viewers
        self._sprite_gen_task = None

    async def start(self):
        """Initialize DB, seed, start heartbeat, TCP, WebSocket, and HTTP servers."""
        # Check API key
        if not os.environ.get('ANTHROPIC_API_KEY'):
            print(f"\n  {Fore.RED}[Error]{Style.RESET_ALL} ANTHROPIC_API_KEY not set.")
            print(f"  Run: export ANTHROPIC_API_KEY='sk-ant-...'")
            return

        # Initialize database
        await db.init_db()

        # Seed if fresh
        if await check_needs_seed():
            await seed()
            print(f"  {Fore.CYAN}[System]{Style.RESET_ALL} Shop initialized. Objects placed on shelves.")

        # Set stage callback for server-side logging
        self.heartbeat.set_stage_callback(self._on_stage)

        # Set window broadcast callback
        self.heartbeat.set_window_broadcast(self._broadcast_to_window)

        # Start sprite generation worker
        try:
            from pipeline.sprite_gen import sprite_gen_worker
            self._sprite_gen_task = asyncio.create_task(sprite_gen_worker())
            print(f"  {Fore.CYAN}[SpriteGen]{Style.RESET_ALL} Worker started.")
        except ImportError:
            print(f"  {Fore.YELLOW}[SpriteGen]{Style.RESET_ALL} Skipped (missing dependencies).")

        # Start heartbeat — she begins living
        await self.heartbeat.start()
        print(f"  {Fore.CYAN}[Heartbeat]{Style.RESET_ALL} She wakes up.")

        # Start TCP server (terminal clients)
        try:
            self._server = await asyncio.start_server(
                self._handle_connection, HOST, PORT
            )
        except OSError as e:
            if e.errno == errno.EADDRINUSE:
                print(f"\n  {Fore.RED}[Error]{Style.RESET_ALL} Port {PORT} already in use.")
                print(f"  Another shopkeeper instance may be running.")
                print(f"  Try: lsof -ti :{PORT} | xargs kill")
                await self.heartbeat.stop()
                await db.close_db()
                return
            raise
        print(f"  {Fore.CYAN}[Server]{Style.RESET_ALL} TCP on {HOST}:{PORT}")

        # Start WebSocket server (window viewers)
        servers = [self._server.serve_forever()]
        try:
            import websockets
            self._ws_server = await websockets.serve(
                self._handle_window_client, '0.0.0.0', WS_PORT
            )
            servers.append(self._ws_server.serve_forever())
            print(f"  {Fore.CYAN}[Window]{Style.RESET_ALL} WebSocket on 0.0.0.0:{WS_PORT}")
        except ImportError:
            print(f"  {Fore.YELLOW}[Window]{Style.RESET_ALL} WebSocket skipped (pip install websockets).")
        except OSError as e:
            print(f"  {Fore.YELLOW}[Window]{Style.RESET_ALL} WebSocket port {WS_PORT} in use, skipped.")

        # Start HTTP server (REST API)
        try:
            http_server = await asyncio.start_server(
                self._handle_http, '0.0.0.0', HTTP_PORT
            )
            servers.append(http_server.serve_forever())
            self._http_server = http_server
            print(f"  {Fore.CYAN}[API]{Style.RESET_ALL} HTTP on 0.0.0.0:{HTTP_PORT}")
        except OSError as e:
            print(f"  {Fore.YELLOW}[API]{Style.RESET_ALL} HTTP port {HTTP_PORT} in use, skipped.")

        print(f"  {Fore.WHITE}She lives whether you visit or not.{Style.RESET_ALL}\n")

        # Run all servers forever
        try:
            await asyncio.gather(*servers)
        except asyncio.CancelledError:
            pass

    async def shutdown(self):
        """Graceful shutdown."""
        print(f"\n  {Fore.CYAN}[Server]{Style.RESET_ALL} Shutting down...")
        await self.heartbeat.stop()

        # Stop sprite gen worker
        if self._sprite_gen_task:
            self._sprite_gen_task.cancel()
            try:
                await self._sprite_gen_task
            except asyncio.CancelledError:
                pass

        # Close all TCP client connections
        for vid, writer in list(self.connections.items()):
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
        self.connections.clear()

        # Close all WebSocket connections
        for ws in list(self._window_clients):
            try:
                await ws.close()
            except Exception:
                pass
        self._window_clients.clear()

        if self._server:
            self._server.close()
            await self._server.wait_closed()

        if self._ws_server:
            self._ws_server.close()
            try:
                await self._ws_server.wait_closed()
            except Exception:
                pass

        if self._http_server:
            self._http_server.close()
            try:
                await self._http_server.wait_closed()
            except Exception:
                pass

        await db.close_db()
        print(f"  {Fore.CYAN}[Server]{Style.RESET_ALL} Goodbye.")

    async def _handle_connection(self, reader: asyncio.StreamReader,
                                  writer: asyncio.StreamWriter):
        """Handle a single terminal connection."""
        addr = writer.get_extra_info('peername')
        visitor_id = None

        try:
            while True:
                line = await reader.readline()
                if not line:
                    break  # connection closed

                try:
                    msg = json.loads(line.decode().strip())
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue

                msg_type = msg.get('type')

                if msg_type == 'visitor_connect':
                    visitor_id = msg.get('visitor_id', 'v_unknown')

                    # Enforce single-visitor: reject if anyone is already engaged
                    if self._active_visitor_id:
                        if self._active_visitor_id != visitor_id:
                            reason = 'The shop is occupied. Someone else is inside. Try again later.'
                        else:
                            reason = 'You are already inside. Only one connection at a time.'
                        await self._send(writer, {
                            'type': 'rejected',
                            'body': reason,
                        })
                        break

                    self.connections[visitor_id] = writer
                    self._active_visitor_id = visitor_id
                    self.heartbeat.subscribe_cycle_logs(visitor_id)

                    # Mark session boundary so Cortex only sees current conversation
                    await db.mark_session_boundary(visitor_id)

                    # Handle connect (creates/increments visitor)
                    connect_event = Event(
                        event_type='visitor_connect',
                        source=f'visitor:{visitor_id}',
                        payload={},
                    )
                    await on_visitor_connect(connect_event)

                    # Set engagement
                    await db.update_engagement_state(
                        status='engaged',
                        visitor_id=visitor_id,
                        started_at=datetime.now(timezone.utc),
                        last_activity=datetime.now(timezone.utc),
                        turn_count=0,
                    )

                    # ACK
                    await self._send(writer, {
                        'type': 'ack',
                        'body': 'She looks up.',
                    })

                    # Trigger entrance cycle
                    await self.heartbeat.schedule_microcycle()

                    # Wait for cycle and send results
                    log = await self.heartbeat.wait_for_cycle_log(visitor_id, timeout=45)
                    if log:
                        await self._send_cycle_log(writer, log)

                elif msg_type == 'visitor_speech':
                    if not visitor_id:
                        continue
                    text = sanitize_input(msg.get('text', ''))
                    if not text:
                        continue

                    # Log conversation
                    await db.append_conversation(visitor_id, 'visitor', text)

                    # ACK path
                    speech_event = Event(
                        event_type='visitor_speech',
                        source=f'visitor:{visitor_id}',
                        payload={'text': text},
                    )
                    engagement = await db.get_engagement_state()
                    ack_result = await on_visitor_message(speech_event, engagement)

                    # Send ACK
                    body_type = ack_result['body'].get('type', 'listening')
                    ack_lines = {
                        'glance_toward': 'She looks up.',
                        'listening': 'She\u2019s listening.',
                        'busy_ack': 'She glances at you briefly, then turns back.',
                    }
                    await self._send(writer, {
                        'type': 'ack',
                        'body': ack_lines.get(body_type, '...'),
                    })

                    if not ack_result['should_process']:
                        await self._send(writer, {
                            'type': 'busy',
                            'body': 'She\'s occupied. Your message waits.',
                        })
                        continue

                    # Web version: add 3-15s pacing between ACK and response
                    # Terminal: subconscious stream provides natural delay
                    await asyncio.sleep(0.5)

                    # Trigger cycle
                    await self.heartbeat.schedule_microcycle()

                    # Wait for cycle and send results
                    log = await self.heartbeat.wait_for_cycle_log(visitor_id, timeout=45)
                    if log:
                        await self._send_cycle_log(writer, log)
                    else:
                        await self._send(writer, {
                            'type': 'timeout',
                            'body': 'She seems lost in thought.',
                        })

                elif msg_type == 'visitor_disconnect':
                    if not visitor_id:
                        continue

                    disconnect_event = Event(
                        event_type='visitor_disconnect',
                        source=f'visitor:{visitor_id}',
                        payload={},
                    )
                    await on_visitor_disconnect(disconnect_event)
                    await self.heartbeat.schedule_microcycle()

                    log = await self.heartbeat.wait_for_cycle_log(visitor_id, timeout=30)
                    if log:
                        await self._send_cycle_log(writer, log)

                    await self._send(writer, {
                        'type': 'farewell',
                        'body': 'The door closes softly behind you.',
                    })

                    # Clean up
                    self.connections.pop(visitor_id, None)
                    self.heartbeat.unsubscribe_cycle_logs(visitor_id)
                    self._active_visitor_id = None
                    await db.update_engagement_state(
                        status='none', visitor_id=None, turn_count=0
                    )
                    break

                elif msg_type == 'drop':
                    # Drop command — leave something on the counter
                    await self._handle_drop(msg, visitor_id, writer)

        except (ConnectionResetError, BrokenPipeError, asyncio.IncompleteReadError):
            pass
        except Exception as e:
            print(f"  [Server] Connection error: {e}")
        finally:
            # Only clean up if THIS writer owns the connection slot.
            # A rejected duplicate has visitor_id set but never got added
            # to self.connections, so this guard prevents it from tearing
            # down the original active session.
            if visitor_id and self.connections.get(visitor_id) is writer:
                self.connections.pop(visitor_id, None)
                self.heartbeat.unsubscribe_cycle_logs(visitor_id)
                if self._active_visitor_id == visitor_id:
                    self._active_visitor_id = None
                try:
                    await db.update_engagement_state(
                        status='none', visitor_id=None, turn_count=0
                    )
                except Exception:
                    pass
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def _handle_drop(self, msg: dict, visitor_id: str,
                           writer: asyncio.StreamWriter):
        """Handle drop command — leave something on the counter."""
        raw = msg.get('content', '')
        drop_type = msg.get('drop_type', 'text')  # url or text

        payload = {
            'type': drop_type,
            'raw': raw,
        }

        # If URL, enrich metadata
        if drop_type == 'url':
            meta = await fetch_url_metadata(raw)
            payload['url'] = raw
            payload['title'] = meta.get('title', 'unknown')
            payload['description'] = meta.get('description', '')
        else:
            payload['title'] = raw[:80]

        # Create ambient_discovery event
        event = Event(
            event_type='ambient_discovery',
            source='world',
            payload=payload,
        )
        await db.append_event(event)
        await db.inbox_add(event.id, priority=0.5)

        await self._send(writer, {
            'type': 'drop_ack',
            'body': 'You leave something on the counter and step out.',
        })

    async def _send(self, writer: asyncio.StreamWriter, msg: dict):
        """Send a JSON line to the client."""
        try:
            line = json.dumps(msg) + '\n'
            writer.write(line.encode())
            await writer.drain()
        except (ConnectionResetError, BrokenPipeError):
            pass

    async def _send_cycle_log(self, writer: asyncio.StreamWriter, log: dict):
        """Send cycle log as a series of stream messages."""
        # Sensorium
        await self._send(writer, {
            'type': 'stream',
            'stage': 'Sensorium',
            'data': f"Salience: {log.get('focus_salience', 0):.1f} | "
                    f"Type: {log.get('focus_type', 'none')}",
        })

        # Drives
        drives = log.get('drives', {})
        await self._send(writer, {
            'type': 'stream',
            'stage': 'Drives',
            'data': f"Social: {drives.get('social_hunger', 0):.1f} | "
                    f"Energy: {drives.get('energy', 0):.1f} | "
                    f"Mood: {drives.get('mood_valence', 0):+.1f}",
        })

        # Thalamus
        await self._send(writer, {
            'type': 'stream',
            'stage': 'Thalamus',
            'data': f"Route: {log.get('routing_focus', '?')} | "
                    f"Budget: {log.get('token_budget', 0)}tk | "
                    f"Memories: {log.get('memory_count', 0)}",
        })

        # Cortex
        monologue = log.get('internal_monologue', '')
        if monologue:
            await self._send(writer, {
                'type': 'stream',
                'stage': 'Cortex',
                'data': monologue[:90],
            })

        # Actions
        for action in log.get('actions', []):
            await self._send(writer, {
                'type': 'stream',
                'stage': 'Action',
                'data': action,
            })

        # Dialogue
        dialogue = log.get('dialogue')
        if dialogue:
            await self._send(writer, {
                'type': 'dialogue',
                'text': dialogue,
                'expression': log.get('expression', 'neutral'),
            })

    async def _on_stage(self, stage: str, data: dict):
        """Stage callback — log to server console and push to connected clients."""
        if stage == 'sleep':
            status = data.get('status', '')
            if status == 'entering_sleep':
                print(f"  {Fore.BLUE}[Sleep]{Style.RESET_ALL} She closes her eyes...")
            elif status == 'woke_up':
                print(f"  {Fore.BLUE}[Sleep]{Style.RESET_ALL} Morning. She stirs.")

        elif stage == 'dialogue':
            dialogue = data.get('dialogue')
            body_desc = data.get('body_description')
            if dialogue:
                expr = data.get('expression', 'neutral')
                print(f"  {Fore.WHITE}[{expr}] \u300c{dialogue}\u300d{Style.RESET_ALL}")
            elif body_desc:
                print(f"  {Fore.CYAN}{body_desc}{Style.RESET_ALL}")

        elif stage == 'sensorium':
            salience = data.get('focus_salience', 0)
            ftype = data.get('focus_type', 'none')
            print(f"  {Fore.CYAN}[Sensorium]{Style.RESET_ALL} "
                  f"Salience: {salience:.1f} | Type: {ftype}")

        # Push to the active visitor's terminal (or broadcast autonomous stages)
        target = self._active_visitor_id
        for vid, writer in list(self.connections.items()):
            if target and vid != target and stage not in ('sleep',):
                continue
            try:
                await self._send(writer, {
                    'type': 'stream',
                    'stage': stage,
                    'data': data,
                })
            except Exception:
                pass


    # ─── WebSocket handler (window viewers) ───

    async def _handle_window_client(self, websocket):
        """Handle a window viewer WebSocket connection."""
        self._window_clients.add(websocket)
        remote = websocket.remote_address
        print(f"  {Fore.GREEN}[Window]{Style.RESET_ALL} Viewer connected from {remote}")
        try:
            # Send current state on connect
            from window_state import build_initial_state
            state = await build_initial_state()
            await websocket.send(json.dumps(state))

            # Listen for chat messages (if authenticated)
            async for raw_message in websocket:
                try:
                    data = json.loads(raw_message)
                    if data.get('type') == 'visitor_message':
                        await self._handle_ws_chat(data, websocket)
                except (json.JSONDecodeError, KeyError):
                    pass
        except Exception:
            pass
        finally:
            self._window_clients.discard(websocket)
            print(f"  {Fore.GREEN}[Window]{Style.RESET_ALL} Viewer disconnected")

    async def _handle_ws_chat(self, data: dict, websocket):
        """Handle a chat message from a WebSocket visitor."""
        token = data.get('token', '')
        text = sanitize_input(data.get('text', ''))
        if not text or not token:
            return

        # Validate token
        token_info = await db.validate_chat_token(token)
        if not token_info:
            await websocket.send(json.dumps({
                'type': 'chat_error',
                'message': "The door doesn't open.",
            }))
            return

        # Consume token use
        await db.consume_chat_token(token)

        display_name = token_info['display_name']
        visitor_id = f'web_{display_name.lower().replace(" ", "_")}'

        # Write visitor speech as text fragment (visible to all window viewers)
        from window_state import build_text_fragment_message
        visitor_frag = build_text_fragment_message(
            content=f'"{text}"',
            fragment_type='visitor_speech',
        )
        await self._broadcast_to_window(visitor_frag)

        # Create visitor speech event for the pipeline
        await db.append_conversation(visitor_id, 'visitor', text)
        speech_event = Event(
            event_type='visitor_speech',
            source=f'visitor:{visitor_id}',
            payload={'text': text},
        )
        await db.append_event(speech_event)
        await db.inbox_add(speech_event.id, priority=0.8)

        # Trigger a microcycle
        await self.heartbeat.schedule_microcycle()

    async def _broadcast_to_window(self, message: dict):
        """Broadcast a JSON message to all connected window viewers."""
        if not self._window_clients:
            return
        payload = json.dumps(message)
        # Send to all, ignore individual failures
        to_remove = set()
        for ws in list(self._window_clients):
            try:
                await ws.send(payload)
            except Exception:
                to_remove.add(ws)
        self._window_clients -= to_remove

    # ─── HTTP handler (REST API) ───

    async def _handle_http(self, reader: asyncio.StreamReader,
                            writer: asyncio.StreamWriter):
        """Simple HTTP handler for REST API endpoints."""
        try:
            request_line = await asyncio.wait_for(reader.readline(), timeout=10)
            if not request_line:
                return

            # Read headers, capture Content-Length for POST body
            content_length = 0
            while True:
                line = await asyncio.wait_for(reader.readline(), timeout=5)
                if line == b'\r\n' or line == b'\n' or not line:
                    break
                header = line.decode('utf-8', errors='replace').strip().lower()
                if header.startswith('content-length:'):
                    try:
                        content_length = int(header.split(':', 1)[1].strip())
                    except ValueError:
                        pass

            request_text = request_line.decode('utf-8', errors='replace').strip()
            parts = request_text.split()
            method = parts[0] if parts else 'GET'
            path = parts[1] if len(parts) > 1 else '/'

            # Read POST body if present
            body_bytes = b''
            if content_length > 0:
                body_bytes = await asyncio.wait_for(
                    reader.readexactly(content_length), timeout=10
                )

            # Handle CORS preflight
            if method == 'OPTIONS':
                await self._http_cors_preflight(writer)
            elif path == '/api/state' and method == 'GET':
                await self._http_state(writer)
            elif path == '/api/health' and method == 'GET':
                await self._http_json(writer, 200, {'status': 'alive'})
            elif path == '/api/validate-token' and method == 'POST':
                await self._http_validate_token(writer, body_bytes)
            elif path == '/api/og' and method == 'GET':
                await self._http_og_image(writer)
            else:
                await self._http_json(writer, 404, {'error': 'not found'})
        except (asyncio.TimeoutError, ConnectionResetError, BrokenPipeError):
            pass
        except Exception as e:
            try:
                await self._http_json(writer, 500, {'error': str(e)})
            except Exception:
                pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def _http_state(self, writer: asyncio.StreamWriter):
        """Handle GET /api/state — return full window state."""
        from window_state import build_initial_state
        state = await build_initial_state()
        await self._http_json(writer, 200, state)

    async def _http_og_image(self, writer: asyncio.StreamWriter):
        """Handle GET /api/og — return server-side composed PNG for social preview."""
        try:
            from window_state import build_initial_state
            from compositing import composite_scene
            state = await build_initial_state()
            layers = state.get('layers', {})
            png_bytes = composite_scene(layers)
            response = (
                'HTTP/1.1 200 OK\r\n'
                'Content-Type: image/png\r\n'
                f'Content-Length: {len(png_bytes)}\r\n'
                'Cache-Control: public, max-age=300\r\n'
                'Access-Control-Allow-Origin: *\r\n'
                'Connection: close\r\n'
                '\r\n'
            )
            writer.write(response.encode())
            writer.write(png_bytes)
            await writer.drain()
        except ImportError:
            await self._http_json(writer, 503, {
                'error': 'Pillow not installed (pip install Pillow)',
            })
        except Exception as e:
            await self._http_json(writer, 500, {'error': str(e)})

    async def _http_validate_token(self, writer: asyncio.StreamWriter,
                                    body_bytes: bytes):
        """Handle POST /api/validate-token — check chat token validity."""
        try:
            data = json.loads(body_bytes.decode('utf-8'))
            token = data.get('token', '')
        except (json.JSONDecodeError, UnicodeDecodeError):
            await self._http_json(writer, 400, {'error': 'bad request'})
            return

        if not token:
            await self._http_json(writer, 400, {'error': 'token required'})
            return

        token_info = await db.validate_chat_token(token)
        if token_info:
            await self._http_json(writer, 200, {
                'valid': True,
                'display_name': token_info['display_name'],
            })
        else:
            await self._http_json(writer, 403, {'valid': False})

    async def _http_cors_preflight(self, writer: asyncio.StreamWriter):
        """Handle OPTIONS preflight for CORS."""
        response = (
            'HTTP/1.1 204 No Content\r\n'
            'Access-Control-Allow-Origin: *\r\n'
            'Access-Control-Allow-Methods: GET, POST, OPTIONS\r\n'
            'Access-Control-Allow-Headers: Content-Type\r\n'
            'Access-Control-Max-Age: 86400\r\n'
            'Content-Length: 0\r\n'
            'Connection: close\r\n'
            '\r\n'
        )
        writer.write(response.encode())
        await writer.drain()

    async def _http_json(self, writer: asyncio.StreamWriter,
                          status: int, body: dict):
        """Send an HTTP JSON response."""
        payload = json.dumps(body)
        status_text = {
            200: 'OK', 204: 'No Content', 400: 'Bad Request',
            403: 'Forbidden', 404: 'Not Found', 500: 'Internal Server Error',
        }
        response = (
            f'HTTP/1.1 {status} {status_text.get(status, "Unknown")}\r\n'
            f'Content-Type: application/json\r\n'
            f'Content-Length: {len(payload)}\r\n'
            f'Access-Control-Allow-Origin: *\r\n'
            f'Access-Control-Allow-Methods: GET, POST, OPTIONS\r\n'
            f'Access-Control-Allow-Headers: Content-Type\r\n'
            f'Connection: close\r\n'
            f'\r\n'
            f'{payload}'
        )
        writer.write(response.encode())
        await writer.drain()


async def run_server():
    server = ShopkeeperServer()

    loop = asyncio.get_event_loop()

    # Handle SIGINT/SIGTERM gracefully
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(server.shutdown()))

    await server.start()


if __name__ == '__main__':
    asyncio.run(run_server())
