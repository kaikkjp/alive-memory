#!/usr/bin/env python3
"""Heartbeat Server — the shopkeeper's life. Runs forever.

Start: python heartbeat_server.py
She lives. She journals at 3am. Her drives shift overnight.
Terminal connects when you want to visit.
Close the terminal, she keeps living.
"""

import asyncio
import json
import os
import signal
import sys
from datetime import datetime, timezone

from colorama import Fore, Style, init as colorama_init

import db
from heartbeat import Heartbeat
from seed import seed, check_needs_seed
from models.event import Event
from pipeline.ack import on_visitor_message, on_visitor_connect, on_visitor_disconnect
from pipeline.enrich import fetch_url_metadata

colorama_init()

HOST = 'localhost'
PORT = 9999


class ShopkeeperServer:
    """TCP server that bridges visitor terminals to the heartbeat."""

    def __init__(self):
        self.heartbeat = Heartbeat()
        self.connections: dict[str, asyncio.StreamWriter] = {}  # visitor_id → writer
        self._active_visitor_id: str | None = None
        self._server = None

    async def start(self):
        """Initialize DB, seed, start heartbeat and TCP server."""
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

        # Start heartbeat — she begins living
        await self.heartbeat.start()
        print(f"  {Fore.CYAN}[Heartbeat]{Style.RESET_ALL} She wakes up.")

        # Start TCP server
        self._server = await asyncio.start_server(
            self._handle_connection, HOST, PORT
        )
        print(f"  {Fore.CYAN}[Server]{Style.RESET_ALL} Listening on {HOST}:{PORT}")
        print(f"  {Fore.WHITE}She lives whether you visit or not.{Style.RESET_ALL}\n")

        # Run forever
        try:
            async with self._server:
                await self._server.serve_forever()
        except asyncio.CancelledError:
            pass

    async def shutdown(self):
        """Graceful shutdown."""
        print(f"\n  {Fore.CYAN}[Server]{Style.RESET_ALL} Shutting down...")
        await self.heartbeat.stop()

        # Close all client connections
        for vid, writer in list(self.connections.items()):
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
        self.connections.clear()

        if self._server:
            self._server.close()
            await self._server.wait_closed()

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
                    text = msg.get('text', '')
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


async def run_server():
    server = ShopkeeperServer()

    loop = asyncio.get_event_loop()

    # Handle SIGINT/SIGTERM gracefully
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(server.shutdown()))

    await server.start()


if __name__ == '__main__':
    asyncio.run(run_server())
