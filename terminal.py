#!/usr/bin/env python3
"""Terminal — CLI with the Subconscious Stream (MRI dashboard).

Two modes:
  1. Standalone: python terminal.py (starts heartbeat in-process)
  2. Client:     python terminal.py --connect (connects to running heartbeat_server.py)
"""

import asyncio
import hashlib
import json
import os
import re
import sys
import random

from colorama import Fore, Style, init as colorama_init

from models.event import Event
from pipeline.ack import on_visitor_message, on_visitor_connect, on_visitor_disconnect
from pipeline.enrich import fetch_url_metadata
import db
from heartbeat import Heartbeat
from seed import seed, check_needs_seed

colorama_init()

SERVER_HOST = 'localhost'
SERVER_PORT = 9999

# ─── Visitor ID ───

def get_or_create_visitor_id() -> str:
    """Generate a stable visitor ID from machine identity."""
    machine = os.environ.get('USER', 'anonymous') + '-terminal'
    return 'v_' + hashlib.sha256(machine.encode()).hexdigest()[:12]


# ─── ACK Display (instant, zero compute) ───

ACK_LINES = {
    'glance_toward': f"  {Fore.CYAN}She looks up.{Style.RESET_ALL}",
    'listening':     f"  {Fore.CYAN}She\u2019s listening.{Style.RESET_ALL}",
    'busy_ack':      f"  {Fore.CYAN}She glances at you briefly, then turns back.{Style.RESET_ALL}",
}


def print_ack(body_type: str):
    """Print immediate body cue. Synchronous. Costs nothing."""
    line = ACK_LINES.get(body_type, f"  {Fore.CYAN}...{Style.RESET_ALL}")
    print(line)
    sys.stdout.flush()


# ─── Progressive Stage Display ───

async def on_stage(stage: str, data: dict):
    """Called by heartbeat after each pipeline stage. Prints immediately."""

    if stage == 'sensorium':
        print(f"  {Fore.CYAN}[Sensorium]{Style.RESET_ALL} "
              f"Salience: {data.get('focus_salience', 0):.1f} | "
              f"Type: {data.get('focus_type', 'none')}")

    elif stage == 'drives':
        print(f"  {Fore.YELLOW}[Drives]{Style.RESET_ALL} "
              f"Social: {data.get('social_hunger', 0):.1f} | "
              f"Energy: {data.get('energy', 0):.1f} | "
              f"Mood: {data.get('mood_valence', 0):+.1f}")

    elif stage == 'thalamus':
        print(f"  {Fore.MAGENTA}[Thalamus]{Style.RESET_ALL} "
              f"Route: {data.get('routing_focus', '?')} | "
              f"Budget: {data.get('token_budget', 0)}tk | "
              f"Memories: {data.get('memory_count', 0)}")

    elif stage == 'cortex':
        monologue = data.get('internal_monologue', '')
        if monologue:
            display = monologue[:90]
            if len(monologue) > 90:
                display += '...'
            print(f"  {Fore.GREEN}[Cortex]{Style.RESET_ALL} "
                  f"\u2727 {display}")
        if data.get('resonance'):
            print(f"  {Fore.BLUE}[Resonance]{Style.RESET_ALL} Something resonated.")

    elif stage == 'actions':
        for action in data.get('approved', []):
            print(f"  {Fore.WHITE}[Action]{Style.RESET_ALL} {action}")
        for dropped in data.get('dropped', []):
            if isinstance(dropped, dict):
                print(f"  {Fore.RED}[Dropped]{Style.RESET_ALL} "
                      f"{dropped.get('reason', '?')}")
        if data.get('_entropy_warning'):
            print(f"  {Fore.RED}[Entropy]{Style.RESET_ALL} "
                  f"{data['_entropy_warning']}")

    elif stage == 'dialogue':
        dialogue = data.get('dialogue')
        body_desc = data.get('body_description')
        if dialogue:
            expr = data.get('expression', 'neutral')
            print()
            print(f"  {Fore.WHITE}[{expr}]{Style.RESET_ALL}")
            print(f"  {Fore.WHITE}\u300c{dialogue}\u300d{Style.RESET_ALL}")
            print()
        elif body_desc:
            # Silence fidget — body-only, no dialogue
            print(f"  {Fore.CYAN}{body_desc}{Style.RESET_ALL}")

    elif stage == 'sleep':
        status = data.get('status', '')
        if status == 'entering_sleep':
            print(f"\n  {Fore.BLUE}[Sleep]{Style.RESET_ALL} She closes her eyes...")
        elif status == 'woke_up':
            print(f"  {Fore.BLUE}[Sleep]{Style.RESET_ALL} Morning. She stirs.\n")

    elif stage == 'end_engagement':
        farewell = data.get('farewell', '')
        if farewell:
            print(f"\n  {Fore.WHITE}{farewell}{Style.RESET_ALL}")
            print(f"  {Fore.WHITE}(The conversation has ended. Type 'leave' to go.){Style.RESET_ALL}\n")

    sys.stdout.flush()


# ─── Display ───

def show_banner():
    print()
    print(f"  {Fore.WHITE}{'=' * 52}{Style.RESET_ALL}")
    print(f"  {Fore.WHITE}  A small shop. Somewhere between real and dream.{Style.RESET_ALL}")
    print(f"  {Fore.WHITE}  The door is open. Someone is inside.{Style.RESET_ALL}")
    print(f"  {Fore.WHITE}{'=' * 52}{Style.RESET_ALL}")
    print()


# ─── Drop Command ───

async def handle_drop(text: str, visitor_id: str):
    """Handle drop/drop-file commands."""
    # Parse command
    if text.startswith('drop-file '):
        filepath = text[len('drop-file '):].strip()
        if not os.path.isfile(filepath):
            print(f"  {Fore.RED}File not found: {filepath}{Style.RESET_ALL}")
            return
        with open(filepath, 'r') as f:
            lines = [l.strip() for l in f.readlines() if l.strip()]
        for line in lines:
            await _drop_single(line, visitor_id)
        print(f"  {Fore.WHITE}You leave {len(lines)} things on the counter and step out.{Style.RESET_ALL}\n")
        return

    if text.startswith('drop '):
        content = text[len('drop '):].strip()
        if not content:
            print(f"  {Fore.WHITE}Drop what? Usage: drop <url or text>{Style.RESET_ALL}")
            return
        await _drop_single(content, visitor_id)
        print(f"  {Fore.WHITE}You leave something on the counter and step out.{Style.RESET_ALL}\n")


async def _drop_single(content: str, visitor_id: str):
    """Drop a single item (URL or text) on the counter."""
    is_url = bool(re.match(r'https?://', content))

    payload = {
        'type': 'url' if is_url else 'text',
        'raw': content,
    }

    if is_url:
        meta = await fetch_url_metadata(content)
        payload['url'] = content
        payload['title'] = meta.get('title', 'unknown')
        payload['description'] = meta.get('description', '')
    else:
        # Remove surrounding quotes if present
        if content.startswith('"') and content.endswith('"'):
            content = content[1:-1]
        payload['title'] = content[:80]

    event = Event(
        event_type='ambient_discovery',
        source='world',
        payload=payload,
    )
    await db.append_event(event)
    await db.inbox_add(event.id, priority=0.5)


# ─── Client Mode (connects to heartbeat_server) ───

async def client_mode():
    """Connect to a running heartbeat_server."""
    visitor_id = get_or_create_visitor_id()

    try:
        reader, writer = await asyncio.open_connection(SERVER_HOST, SERVER_PORT)
    except ConnectionRefusedError:
        print(f"\n  {Fore.RED}[Error]{Style.RESET_ALL} Can't connect to heartbeat_server at {SERVER_HOST}:{SERVER_PORT}")
        print(f"  Start the server first: python heartbeat_server.py\n")
        return

    show_banner()

    # Send connect
    await _client_send(writer, {
        'type': 'visitor_connect',
        'visitor_id': visitor_id,
    })

    # Start background reader for server messages
    display_task = asyncio.create_task(_client_reader(reader))

    try:
        while True:
            try:
                user_input = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: input(f"  {Fore.WHITE}you:{Style.RESET_ALL} ").strip()
                )
            except EOFError:
                break

            if not user_input:
                continue

            if user_input.lower() in ('quit', 'exit', 'leave'):
                await _client_send(writer, {
                    'type': 'visitor_disconnect',
                    'visitor_id': visitor_id,
                })
                await asyncio.sleep(2)  # wait for farewell
                print(f"\n  {Fore.WHITE}The door closes softly behind you.{Style.RESET_ALL}\n")
                break

            if user_input.startswith('drop'):
                # Parse drop for client mode
                is_url = bool(re.search(r'https?://', user_input))
                content = user_input.split(' ', 1)[1] if ' ' in user_input else ''
                await _client_send(writer, {
                    'type': 'drop',
                    'content': content,
                    'drop_type': 'url' if is_url else 'text',
                })
                continue

            # Send speech
            await _client_send(writer, {
                'type': 'visitor_speech',
                'visitor_id': visitor_id,
                'text': user_input,
            })

    except KeyboardInterrupt:
        print(f"\n\n  {Fore.WHITE}You slip out quietly.{Style.RESET_ALL}\n")

    display_task.cancel()
    writer.close()
    try:
        await writer.wait_closed()
    except Exception:
        pass


async def _client_send(writer: asyncio.StreamWriter, msg: dict):
    """Send JSON line to server."""
    line = json.dumps(msg) + '\n'
    writer.write(line.encode())
    await writer.drain()


async def _client_reader(reader: asyncio.StreamReader):
    """Read and display messages from the server."""
    try:
        while True:
            line = await reader.readline()
            if not line:
                break
            try:
                msg = json.loads(line.decode().strip())
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue

            msg_type = msg.get('type')

            if msg_type == 'ack':
                print(f"  {Fore.CYAN}{msg.get('body', '...')}{Style.RESET_ALL}")
                sys.stdout.flush()

            elif msg_type == 'stream':
                stage = msg.get('stage', '')
                data = msg.get('data', '')
                color = {
                    'Sensorium': Fore.CYAN,
                    'Drives': Fore.YELLOW,
                    'Thalamus': Fore.MAGENTA,
                    'Cortex': Fore.GREEN,
                    'Action': Fore.WHITE,
                }.get(stage, Fore.WHITE)
                print(f"  {color}[{stage}]{Style.RESET_ALL} {data}")
                sys.stdout.flush()

            elif msg_type == 'dialogue':
                expr = msg.get('expression', 'neutral')
                text = msg.get('text', '...')
                print()
                print(f"  {Fore.WHITE}[{expr}]{Style.RESET_ALL}")
                print(f"  {Fore.WHITE}\u300c{text}\u300d{Style.RESET_ALL}")
                print()
                sys.stdout.flush()

            elif msg_type == 'farewell':
                print(f"\n  {Fore.WHITE}{msg.get('body', '')}{Style.RESET_ALL}")
                sys.stdout.flush()

            elif msg_type == 'drop_ack':
                print(f"  {Fore.WHITE}{msg.get('body', '')}{Style.RESET_ALL}\n")
                sys.stdout.flush()

            elif msg_type == 'busy':
                print(f"  {Fore.WHITE}{msg.get('body', '')}{Style.RESET_ALL}\n")
                sys.stdout.flush()

            elif msg_type == 'timeout':
                print(f"\n  {Fore.RED}[Timeout]{Style.RESET_ALL} {msg.get('body', '')}\n")
                sys.stdout.flush()

            elif msg_type == 'rejected':
                print(f"\n  {Fore.RED}{msg.get('body', 'Connection rejected.')}{Style.RESET_ALL}\n")
                sys.stdout.flush()
                return

    except asyncio.CancelledError:
        pass
    except Exception:
        pass


# ─── Standalone Mode (original behavior + improvements) ───

async def standalone_mode():
    """Run with heartbeat in-process."""
    # Check API key
    if not os.environ.get('ANTHROPIC_API_KEY'):
        print(f"\n  {Fore.RED}[Error]{Style.RESET_ALL} ANTHROPIC_API_KEY not set.")
        print(f"  Run: export ANTHROPIC_API_KEY='sk-ant-...'")
        print()
        return

    # Initialize database
    await db.init_db()

    # Seed if fresh
    if await check_needs_seed():
        await seed()
        print(f"  {Fore.CYAN}[System]{Style.RESET_ALL} Shop initialized. Objects placed on shelves.")

    # Get visitor ID — ack.py handles creation/increment
    visitor_id = get_or_create_visitor_id()

    # Emit visitor connect event (ack.py creates visitor if new, increments if returning)
    connect_event = Event(
        event_type='visitor_connect',
        source=f'visitor:{visitor_id}',
        payload={},
    )
    await on_visitor_connect(connect_event)

    # Set engagement BEFORE heartbeat starts
    from datetime import datetime, timezone
    await db.update_engagement_state(
        status='engaged',
        visitor_id=visitor_id,
        started_at=datetime.now(timezone.utc),
        last_activity=datetime.now(timezone.utc),
        turn_count=0,
    )

    show_banner()

    # Check if shop is closed
    room = await db.get_room_state()
    if room.shop_status == 'closed':
        drives = await db.get_drives_state()
        if drives.energy > 0.5:
            await db.update_room_state(shop_status='open')
        else:
            print(f"  {Fore.WHITE}The shop is dark. A small sign reads: closed.{Style.RESET_ALL}\n")

    # Start heartbeat with progressive stage callback
    heartbeat = Heartbeat()
    heartbeat.set_stage_callback(on_stage)
    heartbeat.subscribe_cycle_logs(visitor_id)
    await heartbeat.start()

    # Trigger initial cycle (she notices you walk in)
    await heartbeat.schedule_microcycle()

    # Wait for entrance cycle to complete (stages stream progressively)
    await heartbeat.wait_for_cycle_log(visitor_id, timeout=45)

    # Track if she ended the conversation
    engagement_ended = False

    # Conversation loop
    try:
        while True:
            # Get user input
            try:
                user_input = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: input(f"  {Fore.WHITE}you:{Style.RESET_ALL} ").strip()
                )
            except EOFError:
                break

            if not user_input:
                continue

            if user_input.lower() in ('quit', 'exit', 'leave'):
                # Emit disconnect
                disconnect_event = Event(
                    event_type='visitor_disconnect',
                    source=f'visitor:{visitor_id}',
                    payload={},
                )
                await on_visitor_disconnect(disconnect_event)
                await heartbeat.schedule_microcycle()

                # Wait for farewell (stages stream progressively)
                await heartbeat.wait_for_cycle_log(visitor_id, timeout=30)

                print(f"\n  {Fore.WHITE}The door closes softly behind you.{Style.RESET_ALL}\n")
                break

            # Drop command
            if user_input.startswith('drop'):
                await handle_drop(user_input, visitor_id)
                continue

            # Check engagement state — she may have ended the conversation
            engagement = await db.get_engagement_state()
            if engagement.status in ('cooldown', 'none') or engagement_ended:
                engagement_ended = True
                print(f"  {Fore.WHITE}The shop is closing soon.{Style.RESET_ALL}\n")
                continue

            # Log visitor message to conversation
            await db.append_conversation(visitor_id, 'visitor', user_input)

            # Update last_activity on visitor speech (not just shopkeeper
            # response) so the silence timer doesn't drift during processing
            await db.update_engagement_state(
                last_activity=datetime.now(timezone.utc),
            )

            # Emit speech event through ACK path
            speech_event = Event(
                event_type='visitor_speech',
                source=f'visitor:{visitor_id}',
                payload={'text': user_input},
            )
            engagement = await db.get_engagement_state()
            ack_result = await on_visitor_message(speech_event, engagement)

            # ── INSTANT ACK ── (synchronous print, zero compute, <1ms)
            # Web version: add 3-15s pacing between ACK and response
            # Terminal: subconscious stream provides natural delay
            body_type = ack_result['body'].get('type', 'listening')
            print_ack(body_type)

            if not ack_result['should_process']:
                # She's busy — ACK already printed, skip full cycle
                print(f"  {Fore.WHITE}She's occupied. Your message waits.{Style.RESET_ALL}\n")
                continue

            # Brief pause to feel human (not the LLM wait — just a breath)
            await asyncio.sleep(random.uniform(0.3, 0.8))

            # Trigger the cycle — stages will stream progressively via callback
            await heartbeat.schedule_microcycle()

            # Wait for cycle to complete
            log = await heartbeat.wait_for_cycle_log(visitor_id, timeout=45)

            if not log:
                print(f"\n  {Fore.RED}[Timeout]{Style.RESET_ALL} She seems lost in thought.\n")

            # Check if she ended the engagement this cycle
            if log:
                for action in log.get('actions', []):
                    if action == 'end_engagement':
                        engagement_ended = True

    except KeyboardInterrupt:
        print(f"\n\n  {Fore.WHITE}You slip out quietly.{Style.RESET_ALL}\n")

    # Cleanup — stop heartbeat FIRST, wait for loop to exit, THEN touch DB
    heartbeat.unsubscribe_cycle_logs(visitor_id)
    await heartbeat.stop()
    try:
        await db.update_engagement_state(status='none', visitor_id=None, turn_count=0)
    except Exception:
        pass  # DB may already be closing
    await db.close_db()


# ─── Main ───

async def main():
    if '--connect' in sys.argv:
        await client_mode()
    else:
        await standalone_mode()


if __name__ == '__main__':
    asyncio.run(main())
