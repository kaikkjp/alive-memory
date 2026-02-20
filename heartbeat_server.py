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
import base64
from collections import deque
import errno
import hmac
import json
import mimetypes
import os
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit
from dotenv import load_dotenv

import clock

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
from api import dashboard_routes

# Re-export dashboard auth functions for backward compatibility.
# These now live in api.dashboard_routes but existing code/tests may
# import them from heartbeat_server.
_create_dashboard_token = dashboard_routes._create_dashboard_token
_check_dashboard_token = dashboard_routes._check_dashboard_token
_check_dashboard_auth = dashboard_routes.check_dashboard_auth
_dashboard_tokens = dashboard_routes._dashboard_tokens
_DASHBOARD_TOKEN_TTL = dashboard_routes._DASHBOARD_TOKEN_TTL
_check_rate_limit = dashboard_routes._check_rate_limit
_record_auth_attempt = dashboard_routes._record_auth_attempt
_reset_auth_attempts = dashboard_routes._reset_auth_attempts
_auth_attempts = dashboard_routes._auth_attempts
_AUTH_MAX_ATTEMPTS = dashboard_routes._AUTH_MAX_ATTEMPTS
_AUTH_WINDOW_SECONDS = dashboard_routes._AUTH_WINDOW_SECONDS

colorama_init()

DEFAULT_HOST = '127.0.0.1'
DEFAULT_PORT = 9999
TOKEN_ENV_VAR = 'SHOPKEEPER_SERVER_TOKEN'
WS_PORT = int(os.environ.get('SHOPKEEPER_WS_PORT', '8765'))
HTTP_PORT = int(os.environ.get('SHOPKEEPER_HTTP_PORT', '8080'))
ASSET_ROOT = Path(os.environ.get('ASSET_DIR', 'assets')).resolve()
ASSET_MISS_LOG_LIMIT = 2048
VISITOR_IDLE_TIMEOUT = 300  # 5 minutes — unengaged visitors cleaned up after this

# CORS: allowed origins (comma-separated).  Empty / unset → wildcard for dev.
_CORS_ALLOWED_ORIGINS: set[str] = set()
_cors_raw = os.environ.get('CORS_ALLOWED_ORIGINS', '').strip()
if _cors_raw:
    _CORS_ALLOWED_ORIGINS = {o.strip().rstrip('/') for o in _cors_raw.split(',') if o.strip()}


def _cors_origin_for(request_origin: str) -> str:
    """Return the Access-Control-Allow-Origin value for a request.

    If CORS_ALLOWED_ORIGINS is configured, echo the origin only when it
    appears in the allowlist.  Otherwise fall back to ``*`` (dev mode).
    """
    if not _CORS_ALLOWED_ORIGINS:
        return '*'
    # Normalise: strip trailing slash for comparison
    normalised = request_origin.rstrip('/') if request_origin else ''
    if normalised in _CORS_ALLOWED_ORIGINS:
        return request_origin  # echo back the exact origin
    return ''  # not allowed — omit the header


TRANSPARENT_PNG = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+lm1sAAAAASUVORK5CYII='
)

def _load_bind_address() -> tuple[str, int]:
    """Load host/port from env with validation."""
    host = os.environ.get('SHOPKEEPER_HOST', DEFAULT_HOST).strip() or DEFAULT_HOST
    raw_port = os.environ.get('SHOPKEEPER_PORT', str(DEFAULT_PORT)).strip()

    try:
        port = int(raw_port)
    except ValueError as exc:
        raise RuntimeError(f"Invalid SHOPKEEPER_PORT: {raw_port!r}") from exc

    if port < 1 or port > 65535:
        raise RuntimeError(f"SHOPKEEPER_PORT must be 1-65535, got: {port}")

    return host, port


class ShopkeeperServer:
    """TCP server that bridges visitor terminals to the heartbeat.
    Also serves WebSocket for window viewers and HTTP for REST API.
    """

    def __init__(self):
        self.heartbeat = Heartbeat()
        self.connections: dict[str, asyncio.StreamWriter] = {}  # visitor_id → writer
        self._server = None
        self._ws_server = None
        self._http_server = None
        self._window_clients: set = set()  # WebSocket connections for window viewers
        self._ws_visitor_map: dict = {}  # websocket → {visitor_id, display_name, token}
        self._chat_history: list[dict] = []  # Recent chat messages (visitor + shopkeeper)
        self._CHAT_HISTORY_MAX = 50
        self._weather_cache: dict = {}  # {data, fetched_at}
        self._WEATHER_CACHE_TTL = 600  # 10 minutes
        self._last_chat_response_content: str = ''  # dedup tracker
        self._sprite_gen_task = None
        self._visitor_timeout_task = None
        self._metrics_task = None
        self._missing_assets_logged: set[str] = set()
        self._missing_assets_queue: deque[str] = deque()
        self._current_origin = ''  # set per-request in _handle_http
        self.host, self.port = _load_bind_address()
        self._server_token = os.environ.get(TOKEN_ENV_VAR, '').strip()

    async def start(self):
        """Initialize DB, seed, start heartbeat, TCP, WebSocket, and HTTP servers."""
        # Check API key
        if not os.environ.get('OPENROUTER_API_KEY'):
            print(f"\n  {Fore.RED}[Error]{Style.RESET_ALL} OPENROUTER_API_KEY not set.")
            print(f"  Run: export OPENROUTER_API_KEY='sk-or-v1-...'")
            return

        if not self._server_token:
            print(f"\n  {Fore.RED}[Error]{Style.RESET_ALL} {TOKEN_ENV_VAR} not set.")
            print(f"  Run: export {TOKEN_ENV_VAR}='a-long-random-token'")
            return

        if not os.environ.get('DASHBOARD_PASSWORD'):
            print(f"  {Fore.YELLOW}[Warning]{Style.RESET_ALL} "
                  f"DASHBOARD_PASSWORD not set. Dashboard auth disabled.")

        # Initialize database
        await db.init_db()

        # Clear stale visitor presence from previous session
        await db.clear_all_visitors_present()

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

        # Start visitor idle timeout checker
        self._visitor_timeout_task = asyncio.create_task(self._visitor_timeout_loop())

        # Start Telegram adapter if configured (TASK-069)
        self._tg_adapter = None
        try:
            tg_token = os.environ.get('TELEGRAM_BOT_TOKEN')
            tg_chat = os.environ.get('TELEGRAM_GROUP_CHAT_ID')
            if tg_token and tg_chat:
                from body.telegram import TelegramAdapter
                self._tg_adapter = TelegramAdapter(group_chat_id=tg_chat, heartbeat=self.heartbeat)
                asyncio.create_task(self._tg_adapter.start_polling())
                print(f"  {Fore.CYAN}[Telegram]{Style.RESET_ALL} Adapter polling started.")
            else:
                print(f"  {Fore.YELLOW}[Telegram]{Style.RESET_ALL} Skipped (no TELEGRAM_BOT_TOKEN/TELEGRAM_GROUP_CHAT_ID).")
        except Exception as e:
            print(f"  {Fore.YELLOW}[Telegram]{Style.RESET_ALL} Skipped ({e}).")

        # Start X mention poller if configured (TASK-069)
        self._x_poller = None
        try:
            if os.environ.get('X_BEARER_TOKEN'):
                from body.x_social import XMentionPoller
                self._x_poller = XMentionPoller(heartbeat=self.heartbeat)
                asyncio.create_task(self._x_poller.start_polling())
                print(f"  {Fore.CYAN}[X/Twitter]{Style.RESET_ALL} Mention poller started.")
            else:
                print(f"  {Fore.YELLOW}[X/Twitter]{Style.RESET_ALL} Skipped (no X_BEARER_TOKEN).")
        except Exception as e:
            print(f"  {Fore.YELLOW}[X/Twitter]{Style.RESET_ALL} Skipped ({e}).")

        # Start hourly metrics collection (TASK-071)
        self._metrics_task = asyncio.create_task(self._metrics_collection_loop())

        # Start heartbeat — she begins living
        await self.heartbeat.start()
        print(f"  {Fore.CYAN}[Heartbeat]{Style.RESET_ALL} She wakes up.")

        # Start TCP server (terminal clients)
        try:
            self._server = await asyncio.start_server(
                self._handle_connection, self.host, self.port
            )
        except OSError as e:
            if e.errno == errno.EADDRINUSE:
                print(f"\n  {Fore.RED}[Error]{Style.RESET_ALL} Port {self.port} already in use.")
                print(f"  Another shopkeeper instance may be running.")
                print(f"  Try: lsof -ti :{self.port} | xargs kill")
                await self.heartbeat.stop()
                await db.close_db()
                return
            raise
        print(f"  {Fore.CYAN}[Server]{Style.RESET_ALL} TCP on {self.host}:{self.port}")

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

        # Stop visitor timeout checker
        if self._visitor_timeout_task:
            self._visitor_timeout_task.cancel()
            try:
                await self._visitor_timeout_task
            except asyncio.CancelledError:
                pass

        # Stop metrics collection (TASK-071)
        if self._metrics_task:
            self._metrics_task.cancel()
            try:
                await self._metrics_task
            except asyncio.CancelledError:
                pass

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
        self._ws_visitor_map.clear()
        self._chat_history.clear()
        self._weather_cache.clear()

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
                    if not self._is_authorized(msg.get('token', '')):
                        await self._send(writer, {
                            'type': 'rejected',
                            'body': 'Unauthorized. Missing or invalid token.',
                        })
                        break

                    visitor_id = msg.get('visitor_id', 'v_unknown')

                    # Reject duplicate connection for same visitor
                    if visitor_id in self.connections:
                        await self._send(writer, {
                            'type': 'rejected',
                            'body': 'You are already inside. Only one connection at a time.',
                        })
                        break

                    self.connections[visitor_id] = writer
                    self.heartbeat.subscribe_cycle_logs(visitor_id)

                    # Mark session boundary so Cortex only sees current conversation
                    await db.mark_session_boundary(visitor_id)

                    # Track visitor presence (multi-slot)
                    await db.add_visitor_present(visitor_id, 'tcp')

                    # Handle connect (creates/increments visitor)
                    connect_event = Event(
                        event_type='visitor_connect',
                        source=f'visitor:{visitor_id}',
                        payload={},
                    )
                    await on_visitor_connect(connect_event)

                    # No forced engagement — the pipeline decides whether
                    # to engage via sensorium salience + thalamus routing.
                    # Engagement state is set by executor when she speaks.

                    # ACK — "she noticed you", not "she's talking to you"
                    await self._send(writer, {
                        'type': 'ack',
                        'body': 'She glances toward the door.',
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

                    # Update last_activity for idle timeout tracking
                    await db.update_visitor_present(visitor_id, last_activity=clock.now().isoformat())

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
                        'busy_with_other': 'She\u2019s talking to someone else. She nods toward you.',
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
                    await db.remove_visitor_present(visitor_id)
                    # Only clear engagement if this visitor was the engaged one
                    engagement = await db.get_engagement_state()
                    if engagement.visitor_id == visitor_id:
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
                try:
                    await db.remove_visitor_present(visitor_id)
                    # Only clear engagement if this visitor was the engaged one
                    engagement = await db.get_engagement_state()
                    if engagement.visitor_id == visitor_id:
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

    def _is_authorized(self, token: str) -> bool:
        """Constant-time auth check for incoming client token."""
        if not self._server_token:
            return False
        return hmac.compare_digest(token or '', self._server_token)

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
                self._chat_history.clear()
                from window_state import build_status_message
                await self._broadcast_to_window(
                    build_status_message('sleeping', 'She closes her eyes...'))
            elif status == 'woke_up':
                print(f"  {Fore.BLUE}[Sleep]{Style.RESET_ALL} Morning. She stirs.\n")
                from window_state import build_status_message
                await self._broadcast_to_window(
                    build_status_message('awake', 'Morning. She stirs.'))
            elif status == 'deferred':
                print(f"  {Fore.BLUE}[Sleep]{Style.RESET_ALL} Sleep deferred — she's still engaged with a visitor.")

        elif stage == 'dialogue':
            dialogue = data.get('dialogue')
            body_desc = data.get('body_description')
            if dialogue:
                expr = data.get('expression', 'neutral')
                print(f"  {Fore.WHITE}[{expr}] \u300c{dialogue}\u300d{Style.RESET_ALL}")
                # Broadcast chat_response to all window viewers
                chat_resp = {
                    'type': 'chat_response',
                    'content': dialogue,
                    'expression': expr,
                    'timestamp': clock.now_utc().isoformat(),
                }
                await self._broadcast_to_window(chat_resp)
                # Append to chat history buffer
                self._chat_history.append(chat_resp)
                if len(self._chat_history) > self._CHAT_HISTORY_MAX:
                    self._chat_history = self._chat_history[-self._CHAT_HISTORY_MAX:]
            elif body_desc:
                print(f"  {Fore.CYAN}{body_desc}{Style.RESET_ALL}")

        elif stage == 'sensorium':
            salience = data.get('focus_salience', 0)
            ftype = data.get('focus_type', 'none')
            print(f"  {Fore.CYAN}[Sensorium]{Style.RESET_ALL} "
                  f"Salience: {salience:.1f} | Type: {ftype}")

        # Push stages to all connected visitors
        for vid, writer in list(self.connections.items()):
            try:
                await self._send(writer, {
                    'type': 'stream',
                    'stage': stage,
                    'data': data,
                })
            except Exception:
                pass


    # ─── Visitor idle timeout ───

    async def _visitor_timeout_loop(self):
        """Periodic check: disconnect unengaged visitors idle beyond VISITOR_IDLE_TIMEOUT."""
        while True:
            try:
                await asyncio.sleep(60)  # check every minute
                await self._check_visitor_timeouts()
            except asyncio.CancelledError:
                return
            except Exception as e:
                print(f"  [Server] Visitor timeout check error: {e}")

    async def _metrics_collection_loop(self):
        """Hourly liveness metrics collection (TASK-071)."""
        await asyncio.sleep(10)  # brief startup delay
        while True:
            try:
                from metrics.collector import collect_hourly
                snapshot = await collect_hourly()
                count = len(snapshot.metrics)
                print(f"  [Metrics] Collected {count} metrics ({snapshot.period})")
            except asyncio.CancelledError:
                return
            except Exception as e:
                print(f"  [Metrics] Collection error: {e}")
            await asyncio.sleep(3600)  # every hour

    async def _check_visitor_timeouts(self):
        """Clean up visitors who have been idle too long without engagement."""
        visitors = await db.get_visitors_present()
        if not visitors:
            return

        engagement = await db.get_engagement_state()
        now = clock.now()

        for v in visitors:
            # Skip visitors the shopkeeper is actively engaged with
            if engagement.visitor_id == v.visitor_id:
                continue

            # Parse last_activity timestamp
            last_active = v.last_activity
            if last_active is None:
                last_active = v.entered_at
            if last_active is None:
                continue

            # Ensure timezone-aware comparison
            if isinstance(last_active, str):
                last_active = datetime.fromisoformat(last_active)
            if last_active.tzinfo is None:
                last_active = last_active.replace(tzinfo=timezone.utc)

            idle_seconds = (now - last_active).total_seconds()
            if idle_seconds < VISITOR_IDLE_TIMEOUT:
                continue

            # Timed out — clean up
            print(f"  {Fore.YELLOW}[Server]{Style.RESET_ALL} "
                  f"Visitor {v.visitor_id} timed out after "
                  f"{int(idle_seconds)}s idle (unengaged)")

            # Remove from presence table
            await db.remove_visitor_present(v.visitor_id)

            # Create disconnect event so the pipeline knows
            disconnect_event = Event(
                event_type='visitor_disconnect',
                source=f'visitor:{v.visitor_id}',
                payload={'reason': 'idle_timeout'},
            )
            await on_visitor_disconnect(disconnect_event)

            # Close TCP connection if one exists
            writer = self.connections.pop(v.visitor_id, None)
            if writer:
                self.heartbeat.unsubscribe_cycle_logs(v.visitor_id)
                try:
                    await self._send(writer, {
                        'type': 'timeout_disconnect',
                        'body': 'The shop grows quiet. You drift away.',
                    })
                    writer.close()
                    await writer.wait_closed()
                except Exception:
                    pass

    # ─── WebSocket handler (window viewers) ───

    async def _handle_window_client(self, websocket):
        """Handle a window viewer WebSocket connection.

        Auth is optional: dashboard clients send {"type": "auth", "token": "..."}
        to authenticate. Public shop window viewers connect without auth.
        Sensitive data (vitals, costs, drives) goes through auth-gated HTTP
        endpoints — WebSocket only broadcasts scene updates and text fragments.
        """
        self._window_clients.add(websocket)
        remote = websocket.remote_address
        is_dashboard = False  # Set on successful auth; reserved for future WS content gating
        ws_visitor_id = None  # Track visitor_id if this WS sent chat messages
        print(f"  {Fore.GREEN}[Window]{Style.RESET_ALL} Viewer connected from {remote}")
        try:
            # Send current state on connect (includes chat history)
            from window_state import build_initial_state
            state = await build_initial_state(chat_history=list(self._chat_history))
            await websocket.send(json.dumps(state))

            # Listen for auth, chat messages, and disconnect signals
            async for raw_message in websocket:
                try:
                    data = json.loads(raw_message)
                    msg_type = data.get('type')
                    if msg_type == 'auth':
                        if _check_dashboard_token(data.get('token', '')):
                            is_dashboard = True
                            await websocket.send(json.dumps({
                                'type': 'auth_ok',
                            }))
                        else:
                            await websocket.send(json.dumps({
                                'type': 'error',
                                'message': 'unauthorized',
                            }))
                    elif msg_type == 'visitor_message':
                        await self._handle_ws_chat(data, websocket)
                        # Track visitor_id for cleanup on socket drop.
                        # Derive from token the same way _handle_ws_chat does.
                        if not ws_visitor_id:
                            token = data.get('token', '')
                            if token:
                                token_info = await db.validate_chat_token(token)
                                if token_info:
                                    ws_visitor_id = f'web_{token_info["display_name"].lower().replace(" ", "_")}'
                    elif msg_type == 'visitor_disconnect':
                        await self._handle_ws_disconnect(data)
                        ws_visitor_id = None  # Explicit disconnect handled
                except (json.JSONDecodeError, KeyError):
                    pass
        except Exception as e:
            # websockets library raises ConnectionClosed on normal disconnect,
            # only log unexpected errors
            err_name = type(e).__name__
            if err_name not in ('ConnectionClosed', 'ConnectionClosedOK', 'ConnectionClosedError'):
                print(f"  {Fore.YELLOW}[Window]{Style.RESET_ALL} WS error: {err_name}: {e}")
        finally:
            self._window_clients.discard(websocket)
            # Clean up visitor map entry for this websocket
            had_visitor = websocket in self._ws_visitor_map
            if had_visitor:
                del self._ws_visitor_map[websocket]
            # Clean up ghost engagement if this WS had an active visitor
            if ws_visitor_id:
                try:
                    print(f"  {Fore.YELLOW}[Window]{Style.RESET_ALL} "
                          f"Socket dropped for {ws_visitor_id} — cleaning up")
                    await db.remove_visitor_present(ws_visitor_id)
                    disconnect_event = Event(
                        event_type='visitor_disconnect',
                        source=f'visitor:{ws_visitor_id}',
                        payload={'reason': 'ws_dropped'},
                    )
                    await on_visitor_disconnect(disconnect_event)
                    await self.heartbeat.schedule_microcycle()
                    engagement = await db.get_engagement_state()
                    if engagement.visitor_id == ws_visitor_id:
                        await db.update_engagement_state(
                            status='none', visitor_id=None, turn_count=0
                        )
                except Exception:
                    pass
            # Broadcast updated presence if a visitor was removed
            if had_visitor:
                try:
                    await self._broadcast_visitor_presence()
                except Exception:
                    pass
            print(f"  {Fore.GREEN}[Window]{Style.RESET_ALL} Viewer disconnected")

    async def _handle_ws_chat(self, data: dict, websocket):
        """Handle a chat message from a WebSocket visitor."""
        token = data.get('token', '')
        text = sanitize_input(data.get('text', ''))
        if not text or not token:
            return

        # Atomically validate and consume one token use
        token_info = await db.validate_and_consume_chat_token(token)
        if not token_info:
            await websocket.send(json.dumps({
                'type': 'chat_error',
                'message': "The door doesn't open.",
            }))
            return

        display_name = token_info['display_name']
        visitor_id = f'web_{display_name.lower().replace(" ", "_")}'

        # Register in visitor map (first valid message = join)
        is_new_visitor = websocket not in self._ws_visitor_map
        if is_new_visitor:
            self._ws_visitor_map[websocket] = {
                'visitor_id': visitor_id,
                'display_name': display_name,
                'token': token,
            }

            # HOTFIX-005: Create/increment visitor record via on_visitor_connect
            # Previously missing — visitors were never registered for WebSocket,
            # so all downstream memory writes (traits, totems, impressions) silently failed.
            connect_event = Event(
                event_type='visitor_connect',
                source=f'visitor:{visitor_id}',
                payload={'display_name': display_name},
            )
            await on_visitor_connect(connect_event)
            await db.update_visitor(visitor_id, name=display_name)
            await db.mark_session_boundary(visitor_id)

        # Track visitor presence (multi-slot) — idempotent via INSERT OR REPLACE
        await db.add_visitor_present(visitor_id, 'websocket')

        # Update last_activity for idle timeout tracking
        await db.update_visitor_present(visitor_id, last_activity=clock.now().isoformat())

        # Broadcast visitor_presence if this is a new join
        if is_new_visitor:
            await self._broadcast_visitor_presence()

        # Broadcast chat_message to all window viewers (room-style)
        from window_state import build_chat_message
        chat_msg = build_chat_message(
            sender=display_name,
            sender_type='visitor',
            content=text,
            timestamp=clock.now_utc().isoformat(),
        )
        await self._broadcast_to_window(chat_msg)

        # Append to chat history buffer
        self._chat_history.append(chat_msg)
        if len(self._chat_history) > self._CHAT_HISTORY_MAX:
            self._chat_history = self._chat_history[-self._CHAT_HISTORY_MAX:]

        # Write visitor speech as text fragment (activity stream)
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

    async def _handle_ws_disconnect(self, data: dict):
        """Handle a visitor disconnect from a WebSocket client."""
        token = data.get('token', '')
        if not token:
            return

        # Look up visitor identity from the token.
        # Use raw DB query instead of validate_chat_token() because
        # validate rejects uses_remaining<=0, but disconnect must work
        # even after the last message consumed the final use.
        # Still enforce expiry — expired tokens must not trigger disconnects.
        conn = await db.get_db()
        cursor = await conn.execute(
            "SELECT display_name, expires_at FROM chat_tokens WHERE token = ?",
            (token,),
        )
        row = await cursor.fetchone()
        if not row:
            return

        if row['expires_at']:
            from datetime import datetime, timezone
            expires = datetime.fromisoformat(row['expires_at'])
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if expires < clock.now_utc():
                return

        display_name = row['display_name']
        visitor_id = f'web_{display_name.lower().replace(" ", "_")}'

        print(f"  {Fore.GREEN}[Window]{Style.RESET_ALL} "
              f"Visitor {display_name} left the shop")

        # Remove from visitor presence table
        await db.remove_visitor_present(visitor_id)

        # Create disconnect event for the pipeline
        disconnect_event = Event(
            event_type='visitor_disconnect',
            source=f'visitor:{visitor_id}',
            payload={},
        )
        await on_visitor_disconnect(disconnect_event)

        # Trigger microcycle FIRST so the perception cycle sees
        # the real engagement context (turn_count, visitor_id)
        # before we clear it — matching the TCP handler order.
        await self.heartbeat.schedule_microcycle()

        # Only clear engagement if THIS visitor was the engaged one
        engagement = await db.get_engagement_state()
        if engagement.visitor_id == visitor_id:
            await db.update_engagement_state(
                status='none', visitor_id=None, turn_count=0
            )

        # Remove ALL sockets for this visitor (handles multi-tab / reconnect overlap)
        for ws, info in list(self._ws_visitor_map.items()):
            if info['visitor_id'] == visitor_id:
                del self._ws_visitor_map[ws]
        await self._broadcast_visitor_presence()

    async def _broadcast_to_window(self, message: dict):
        """Broadcast a JSON message to all connected window viewers.

        Includes dedup: if a chat_response was just sent, suppress the same
        content appearing as current_thought in the next scene_update to
        prevent the frontend from showing the dialogue twice.
        """
        # Dedup: suppress matching current_thought in scene_update
        if message.get('type') == 'scene_update' and self._last_chat_response_content:
            text_block = message.get('text', {})
            ct = text_block.get('current_thought', '')
            if ct and ct.startswith(self._last_chat_response_content[:50]):
                message = {**message, 'text': {**text_block, 'current_thought': ''}}
            # Always clear after first scene_update following a chat_response,
            # whether or not it matched — prevents stale state from suppressing
            # unrelated future thoughts.
            self._last_chat_response_content = ''

        if not self._window_clients:
            return

        # Track chat_response content for dedup — set AFTER the early return
        # so dedup state is only armed when clients actually received the message.
        if message.get('type') == 'chat_response':
            self._last_chat_response_content = message.get('content', '')
        payload = json.dumps(message)
        # Send to all, ignore individual failures
        to_remove = set()
        for ws in list(self._window_clients):
            try:
                await ws.send(payload)
            except Exception:
                to_remove.add(ws)
        self._window_clients -= to_remove

    async def _broadcast_visitor_presence(self):
        """Broadcast current visitor list and count to all window clients."""
        from window_state import build_visitor_presence_message
        visitors = [
            {'display_name': info['display_name'], 'visitor_id': info['visitor_id']}
            for info in self._ws_visitor_map.values()
        ]
        await self._broadcast_to_window(
            build_visitor_presence_message(visitors, clock.now_utc().isoformat())
        )

    # ─── HTTP handler (REST API) ───

    # HTTP safety limits
    _MAX_BODY_BYTES = 64 * 1024  # 64 KB max POST body
    _MAX_HEADER_COUNT = 50       # max headers per request
    _MAX_HEADER_BYTES = 8192     # max single header line length

    async def _handle_http(self, reader: asyncio.StreamReader,
                            writer: asyncio.StreamWriter):
        """Simple HTTP handler for REST API endpoints."""
        try:
            request_line = await asyncio.wait_for(reader.readline(), timeout=10)
            if not request_line:
                return

            # Read headers, capture Content-Length, Authorization, and Origin
            content_length = 0
            authorization = ''
            self._current_origin = ''
            header_count = 0
            while True:
                line = await asyncio.wait_for(reader.readline(), timeout=5)
                if line == b'\r\n' or line == b'\n' or not line:
                    break
                header_count += 1
                if header_count > self._MAX_HEADER_COUNT:
                    await self._http_json(writer, 431, {'error': 'too many headers'})
                    return
                if len(line) > self._MAX_HEADER_BYTES:
                    await self._http_json(writer, 431, {'error': 'header too large'})
                    return
                header = line.decode('utf-8', errors='replace').strip()
                header_lower = header.lower()
                if header_lower.startswith('content-length:'):
                    try:
                        content_length = int(header.split(':', 1)[1].strip())
                    except ValueError:
                        pass
                elif header_lower.startswith('authorization:'):
                    authorization = header.split(':', 1)[1].strip()
                elif header_lower.startswith('origin:'):
                    self._current_origin = header.split(':', 1)[1].strip()

            request_text = request_line.decode('utf-8', errors='replace').strip()
            parts = request_text.split()
            method = parts[0] if parts else 'GET'
            raw_path = parts[1] if len(parts) > 1 else '/'
            path = urlsplit(raw_path).path

            # Enforce body size limit
            if content_length > self._MAX_BODY_BYTES:
                await self._http_json(writer, 413, {'error': 'payload too large'})
                return

            # Read POST body if present
            body_bytes = b''
            if content_length > 0:
                body_bytes = await asyncio.wait_for(
                    reader.readexactly(content_length), timeout=10
                )

            # Handle CORS preflight
            if method == 'OPTIONS':
                await self._http_cors_preflight(writer)
            elif path.startswith('/assets/') and method == 'GET':
                await self._http_asset(writer, path)
            elif path == '/api/state' and method == 'GET':
                await self._http_state(writer)
            elif path == '/api/health' and method == 'GET':
                await self._http_json(writer, 200, {'status': 'alive'})
            elif path == '/api/validate-token' and method == 'POST':
                await self._http_validate_token(writer, body_bytes)
            elif path == '/api/og' and method == 'GET':
                await self._http_og_image(writer)
            # Dashboard API endpoints (token-protected) — delegated to api.dashboard_routes
            elif path == '/api/dashboard/auth' and method == 'POST':
                peername = writer.get_extra_info('peername')
                client_ip = peername[0] if peername else 'unknown'
                await dashboard_routes.handle_auth(self, writer, body_bytes, client_ip)
            elif path == '/api/dashboard/vitals' and method == 'GET':
                await dashboard_routes.handle_vitals(self, writer, authorization)
            elif path == '/api/dashboard/drives' and method == 'GET':
                await dashboard_routes.handle_drives(self, writer, authorization)
            elif path == '/api/dashboard/costs' and method == 'GET':
                await dashboard_routes.handle_costs(self, writer, authorization)
            elif path == '/api/dashboard/threads' and method == 'GET':
                await dashboard_routes.handle_threads(self, writer, authorization)
            elif path == '/api/dashboard/pool' and method == 'GET':
                await dashboard_routes.handle_pool(self, writer, authorization)
            elif path == '/api/dashboard/collection' and method == 'GET':
                await dashboard_routes.handle_collection(self, writer, authorization)
            elif path == '/api/dashboard/timeline' and method == 'GET':
                await dashboard_routes.handle_timeline(self, writer, authorization)
            elif path == '/api/dashboard/controls/cycle' and method == 'POST':
                await dashboard_routes.handle_trigger_cycle(self, writer, authorization)
            elif path == '/api/dashboard/controls/status' and method == 'GET':
                await dashboard_routes.handle_status(self, writer, authorization)
            elif path == '/api/dashboard/controls/cycle-interval' and method == 'GET':
                await dashboard_routes.handle_get_cycle_interval(self, writer, authorization)
            elif path == '/api/dashboard/controls/cycle-interval' and method == 'POST':
                await dashboard_routes.handle_set_cycle_interval(self, writer, authorization, body_bytes)
            elif path == '/api/dashboard/body' and method == 'GET':
                await dashboard_routes.handle_body(self, writer, authorization)
            elif path == '/api/dashboard/behavioral' and method == 'GET':
                await dashboard_routes.handle_behavioral(self, writer, authorization)
            elif path == '/api/dashboard/content-pool' and method == 'GET':
                await dashboard_routes.handle_content_pool(self, writer, authorization)
            elif path == '/api/dashboard/feed' and method == 'GET':
                await dashboard_routes.handle_feed(self, writer, authorization)
            elif path == '/api/dashboard/consumption-history' and method == 'GET':
                await dashboard_routes.handle_consumption_history(self, writer, authorization)
            elif path == '/api/dashboard/budget' and method == 'GET':
                await dashboard_routes.handle_get_budget(self, writer, authorization)
            elif path == '/api/dashboard/budget' and method == 'POST':
                await dashboard_routes.handle_set_budget(self, writer, authorization, body_bytes)
            elif path == '/api/dashboard/parameters' and method == 'GET':
                await dashboard_routes.handle_parameters(self, writer, authorization)
            elif path == '/api/dashboard/parameters' and method == 'POST':
                await dashboard_routes.handle_set_parameter(self, writer, authorization, body_bytes)
            elif path == '/api/dashboard/x-drafts' and method == 'GET':
                await dashboard_routes.handle_x_drafts(self, writer, authorization)
            elif path == '/api/dashboard/x-drafts/approve' and method == 'POST':
                await dashboard_routes.handle_approve_x_draft(self, writer, authorization, body_bytes)
            elif path == '/api/dashboard/x-drafts/reject' and method == 'POST':
                await dashboard_routes.handle_reject_x_draft(self, writer, authorization, body_bytes)
            elif path == '/api/dashboard/actions' and method == 'GET':
                await dashboard_routes.handle_actions(self, writer, authorization)
            elif path == '/api/dashboard/actions/resolve' and method == 'POST':
                await dashboard_routes.handle_resolve_action(self, writer, authorization, body_bytes)
            elif path == '/api/dashboard/drift' and method == 'GET':
                await dashboard_routes.handle_drift(self, writer, authorization)
            elif path == '/api/dashboard/external-actions' and method == 'GET':
                await dashboard_routes.handle_external_actions(self, writer, authorization)
            elif path == '/api/dashboard/channel-toggle' and method == 'POST':
                await dashboard_routes.handle_channel_toggle(self, writer, authorization, body_bytes)
            elif path == '/api/dashboard/metrics' and method == 'GET':
                await dashboard_routes.handle_metrics(self, writer, authorization)
            elif path == '/api/dashboard/metrics/backfill' and method == 'POST':
                await dashboard_routes.handle_metrics_backfill(self, writer, authorization)
            elif path == '/api/metrics/public' and method == 'GET':
                await dashboard_routes.handle_metrics_public(self, writer)
            elif path == '/api/weather' and method == 'GET':
                await self._http_weather(writer)
            elif path == '/api/outdoor' and method == 'GET':
                await self._http_outdoor(writer)
            else:
                await self._http_json(writer, 404, {'error': 'not found'})
        except (asyncio.TimeoutError, ConnectionResetError, BrokenPipeError):
            pass
        except Exception as e:
            print(f'  [HTTP] Request error: {e}')
            try:
                await self._http_json(writer, 500, {'error': 'internal server error'})
            except Exception:
                pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def _http_state(self, writer: asyncio.StreamWriter):
        """Handle GET /api/state — return full window state (mirrors WS initial payload)."""
        from window_state import build_initial_state
        state = await build_initial_state(chat_history=list(self._chat_history))
        await self._http_json(writer, 200, state)

    async def _http_og_image(self, writer: asyncio.StreamWriter):
        """Handle GET /api/og — return server-side composed PNG for social preview."""
        try:
            from window_state import build_initial_state
            from compositing import composite_scene
            state = await build_initial_state()
            layers = state.get('layers', {})
            png_bytes = composite_scene(layers)
            allowed = _cors_origin_for(getattr(self, '_current_origin', ''))
            cors_header = f'Access-Control-Allow-Origin: {allowed}\r\n' if allowed else ''
            vary_header = 'Vary: Origin\r\n' if allowed and allowed != '*' else ''
            response = (
                'HTTP/1.1 200 OK\r\n'
                'Content-Type: image/png\r\n'
                f'Content-Length: {len(png_bytes)}\r\n'
                'Cache-Control: public, max-age=300\r\n'
                f'{cors_header}'
                f'{vary_header}'
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
            print(f'  [OG] Compositing error: {e}')
            await self._http_json(writer, 500, {'error': 'compositing failed'})

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
            # Keep invalid-token responses as 200 so UI validation attempts
            # don't show browser-level 4xx resource errors.
            await self._http_json(writer, 200, {'valid': False})

    async def _fetch_tokyo_weather(self) -> dict:
        """Fetch Tokyo weather from wttr.in, cached for WEATHER_CACHE_TTL seconds."""
        # Wall-clock time intentional: weather cache should expire on real time,
        # not simulation time (clock.now), so live and simulated modes share cache.
        import time as _time
        now = _time.time()
        if self._weather_cache and (now - self._weather_cache.get('fetched_at', 0)) < self._WEATHER_CACHE_TTL:
            return self._weather_cache['data']

        try:
            import urllib.request
            url = 'https://wttr.in/Tokyo?format=j1'
            req = urllib.request.Request(url, headers={'User-Agent': 'ShopkeeperBot/1.0'})
            resp_data = await asyncio.to_thread(
                lambda: urllib.request.urlopen(req, timeout=5).read()
            )
            raw = json.loads(resp_data.decode())
            current = raw.get('current_condition', [{}])[0]
            data = {
                'temp_c': int(current.get('temp_C', 0)),
                'temp_f': int(current.get('temp_F', 32)),
                'condition': current.get('weatherDesc', [{}])[0].get('value', 'Unknown'),
                'humidity': int(current.get('humidity', 0)),
                'wind_kmph': int(current.get('windspeedKmph', 0)),
                'feels_like_c': int(current.get('FeelsLikeC', 0)),
                'observation_time': current.get('observation_time', ''),
                'location': 'Tokyo, Japan',
            }
            self._weather_cache = {'data': data, 'fetched_at': now}
            return data
        except Exception as e:
            print(f"  {Fore.YELLOW}[Weather]{Style.RESET_ALL} Fetch error: {e}")
            if self._weather_cache:
                return self._weather_cache['data']
            return {'error': 'weather unavailable', 'location': 'Tokyo, Japan'}

    async def _http_weather(self, writer: asyncio.StreamWriter):
        """Handle GET /api/weather — return current Tokyo weather."""
        data = await self._fetch_tokyo_weather()
        await self._http_json(writer, 200, data)

    async def _http_outdoor(self, writer: asyncio.StreamWriter):
        """Handle GET /api/outdoor — return outdoor context for scene."""
        weather = await self._fetch_tokyo_weather()
        room = await db.get_room_state()
        await self._http_json(writer, 200, {
            'weather': weather,
            'shop_weather': room.weather,
            'time_of_day': room.time_of_day,
            'shop_status': room.shop_status,
        })

    async def _http_asset(self, writer: asyncio.StreamWriter, path: str):
        """Handle GET /assets/* by serving generated scene layers.

        Missing assets return HTTP 404 with a transparent placeholder body.
        The canvas can keep rendering while observers and monitors still see
        true missing-resource semantics.
        """
        rel = unquote(path[len('/assets/'):]).lstrip('/')
        rel_path = Path(rel)

        if not rel or rel_path.is_absolute() or any(p in ('', '.', '..') for p in rel_path.parts):
            await self._http_json(writer, 400, {'error': 'bad asset path'})
            return

        abs_path = (ASSET_ROOT / rel_path).resolve()
        try:
            abs_path.relative_to(ASSET_ROOT)
        except ValueError:
            await self._http_json(writer, 403, {'error': 'forbidden'})
            return

        if abs_path.is_file():
            mime, _ = mimetypes.guess_type(str(abs_path))
            payload = await asyncio.to_thread(abs_path.read_bytes)
            await self._http_bytes(
                writer,
                200,
                payload,
                mime or 'application/octet-stream',
                cache_control='public, max-age=300',
            )
            return

        self._log_missing_asset(rel)

        await self._http_bytes(
            writer,
            404,
            TRANSPARENT_PNG,
            'image/png',
            cache_control='no-store',
            extra_headers={'X-Asset-Missing': '1'},
        )

    def _log_missing_asset(self, rel: str):
        """Log each missing asset once, with bounded memory usage."""
        if rel in self._missing_assets_logged:
            return

        if len(self._missing_assets_logged) >= ASSET_MISS_LOG_LIMIT:
            oldest = self._missing_assets_queue.popleft()
            self._missing_assets_logged.discard(oldest)

        self._missing_assets_logged.add(rel)
        self._missing_assets_queue.append(rel)
        print(f"  {Fore.YELLOW}[Asset]{Style.RESET_ALL} Missing: {rel}")

    async def _http_cors_preflight(self, writer: asyncio.StreamWriter):
        """Handle OPTIONS preflight for CORS."""
        allowed = _cors_origin_for(getattr(self, '_current_origin', ''))
        headers = [
            'HTTP/1.1 204 No Content\r\n',
            'Access-Control-Allow-Methods: GET, POST, OPTIONS\r\n',
            'Access-Control-Allow-Headers: Content-Type, Authorization\r\n',
            'Access-Control-Max-Age: 86400\r\n',
            'Content-Length: 0\r\n',
            'Connection: close\r\n',
        ]
        if allowed:
            headers.insert(1, f'Access-Control-Allow-Origin: {allowed}\r\n')
            if allowed != '*':
                headers.insert(2, 'Vary: Origin\r\n')
        headers.append('\r\n')
        writer.write(''.join(headers).encode())
        await writer.drain()

    async def _http_json(self, writer: asyncio.StreamWriter,
                          status: int, body: dict):
        """Send an HTTP JSON response."""
        payload = json.dumps(body)
        status_text = {
            200: 'OK', 204: 'No Content', 400: 'Bad Request',
            401: 'Unauthorized',
            403: 'Forbidden', 404: 'Not Found',
            413: 'Payload Too Large', 431: 'Request Header Fields Too Large',
            429: 'Too Many Requests',
            500: 'Internal Server Error', 503: 'Service Unavailable',
        }
        allowed = _cors_origin_for(getattr(self, '_current_origin', ''))
        cors_headers = ''
        if allowed:
            cors_headers = (
                f'Access-Control-Allow-Origin: {allowed}\r\n'
                f'Access-Control-Allow-Methods: GET, POST, OPTIONS\r\n'
                f'Access-Control-Allow-Headers: Content-Type, Authorization\r\n'
            )
            if allowed != '*':
                cors_headers += 'Vary: Origin\r\n'
        response = (
            f'HTTP/1.1 {status} {status_text.get(status, "Unknown")}\r\n'
            f'Content-Type: application/json\r\n'
            f'Content-Length: {len(payload)}\r\n'
            f'{cors_headers}'
            f'Connection: close\r\n'
            f'\r\n'
            f'{payload}'
        )
        writer.write(response.encode())
        await writer.drain()

    async def _http_bytes(
        self,
        writer: asyncio.StreamWriter,
        status: int,
        payload: bytes,
        content_type: str,
        cache_control: str = 'no-store',
        extra_headers: dict[str, str] | None = None,
    ):
        """Send an HTTP response with raw bytes."""
        status_text = {
            200: 'OK',
            400: 'Bad Request',
            403: 'Forbidden',
            404: 'Not Found',
            500: 'Internal Server Error',
        }
        allowed = _cors_origin_for(getattr(self, '_current_origin', ''))
        headers = [
            f'HTTP/1.1 {status} {status_text.get(status, "Unknown")}\r\n',
            f'Content-Type: {content_type}\r\n',
            f'Content-Length: {len(payload)}\r\n',
            f'Cache-Control: {cache_control}\r\n',
            'Connection: close\r\n',
        ]
        if allowed:
            headers.insert(4, f'Access-Control-Allow-Origin: {allowed}\r\n')
            if allowed != '*':
                headers.insert(5, 'Vary: Origin\r\n')
        if extra_headers:
            for key, value in extra_headers.items():
                headers.append(f'{key}: {value}\r\n')
        headers.append('\r\n')

        writer.write(''.join(headers).encode())
        writer.write(payload)
        await writer.drain()


async def run_server():
    try:
        server = ShopkeeperServer()
    except RuntimeError as e:
        print(f"\n  {Fore.RED}[Error]{Style.RESET_ALL} {e}")
        return

    loop = asyncio.get_event_loop()

    # Handle SIGINT/SIGTERM gracefully
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(server.shutdown()))

    await server.start()


if __name__ == '__main__':
    asyncio.run(run_server())
