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
import ssl
import sys
import random

from datetime import datetime, timezone, timedelta
from colorama import Fore, Style, init as colorama_init

from models.event import Event
from pipeline.ack import on_visitor_message, on_visitor_connect, on_visitor_disconnect
from pipeline.enrich import fetch_url_metadata
from pipeline.sanitize import sanitize_input
import db
from heartbeat import Heartbeat
from seed import seed, check_needs_seed

colorama_init()

def _get_server_port() -> int:
    raw_port = os.environ.get('SHOPKEEPER_PORT', '9999').strip()
    try:
        port = int(raw_port)
    except ValueError:
        return 9999
    return port if 1 <= port <= 65535 else 9999


SERVER_HOST = os.environ.get('SHOPKEEPER_HOST', '127.0.0.1')
SERVER_PORT = _get_server_port()
SERVER_TOKEN = os.environ.get('SHOPKEEPER_SERVER_TOKEN', '').strip()
_input_prompt_active = False

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


def _ensure_async_line_break():
    """Avoid async stage output being appended onto the active input prompt."""
    if _input_prompt_active:
        print()


# ─── Progressive Stage Display ───

async def on_stage(stage: str, data: dict):
    """Called by heartbeat after each pipeline stage. Prints immediately."""
    _ensure_async_line_break()

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


# ─── Peek Commands (read-only, no engagement triggered) ───

JST = timezone(timedelta(hours=9))

PEEK_COMMANDS = ('journal', 'drives', 'collection', 'backroom', 'status', 'totems', 'events', 'threads', 'weather', 'pool')


def _fmt_time(dt) -> str:
    """Format a datetime for peek display, converting to JST."""
    if not dt:
        return '?'
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt)
    jst = dt.astimezone(JST)
    return jst.strftime('%I:%M %p').lstrip('0').lower()


def _fmt_date(dt) -> str:
    """Format a date for peek display."""
    if not dt:
        return '?'
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt)
    jst = dt.astimezone(JST)
    return jst.strftime('%b %d')


def _bar(value: float, width: int = 12) -> str:
    """Render a 0-1 float as a small bar."""
    filled = int(value * width)
    return '█' * filled + '░' * (width - filled)


_peek_db_ready = False


async def handle_peek(cmd: str) -> bool:
    """Handle read-only peek commands. Returns True if handled."""
    global _peek_db_ready
    cmd = cmd.strip().lower()

    # Ensure DB is accessible (client mode doesn't call init_db)
    if not _peek_db_ready:
        await db.init_db()
        _peek_db_ready = True

    if cmd == 'journal':
        await _peek_journal(last_n=3)
    elif cmd == 'journal all':
        await _peek_journal(all_entries=True)
    elif cmd == 'drives':
        await _peek_drives()
    elif cmd == 'collection':
        await _peek_collection('shelf')
    elif cmd == 'backroom':
        await _peek_collection('backroom')
    elif cmd == 'status':
        await _peek_status()
    elif cmd == 'totems':
        await _peek_totems()
    elif cmd == 'events':
        await _peek_events()
    elif cmd == 'threads':
        await _peek_threads()
    elif cmd == 'weather':
        await _peek_weather()
    elif cmd == 'pool':
        await _peek_pool()
    else:
        return False
    return True


async def _peek_journal(last_n: int = 3, all_entries: bool = False):
    if all_entries:
        entries = await db.get_all_journal()
    else:
        entries = await db.get_recent_journal(limit=last_n)
        entries = list(reversed(entries))  # chronological order

    if not entries:
        print(f"\n  {Fore.WHITE}(No journal entries yet.){Style.RESET_ALL}\n")
        return

    print()
    for e in entries:
        day = f"Day {e.day_alive}" if e.day_alive else "Day ?"
        time = _fmt_time(e.created_at)
        mood = e.mood or '...'
        print(f"  {Fore.YELLOW}[{day} — {time} — mood: {mood}]{Style.RESET_ALL}")
        for line in e.content.strip().split('\n'):
            print(f"  {Fore.WHITE}{line}{Style.RESET_ALL}")
        print()


async def _peek_drives():
    d = await db.get_drives_state()
    print()
    print(f"  {Fore.YELLOW}── Drives ──{Style.RESET_ALL}")
    print(f"  social hunger  {_bar(d.social_hunger)} {d.social_hunger:.2f}")
    print(f"  curiosity      {_bar(d.curiosity)} {d.curiosity:.2f}")
    print(f"  expression     {_bar(d.expression_need)} {d.expression_need:.2f}")
    print(f"  rest need      {_bar(d.rest_need)} {d.rest_need:.2f}")
    print(f"  energy         {_bar(d.energy)} {d.energy:.2f}")
    valence_label = "bright" if d.mood_valence > 0 else "dark" if d.mood_valence < 0 else "neutral"
    print(f"  mood           {d.mood_valence:+.2f} ({valence_label})")
    print(f"  arousal        {_bar(d.mood_arousal)} {d.mood_arousal:.2f}")
    if d.updated_at:
        print(f"  {Fore.CYAN}updated: {_fmt_time(d.updated_at)}{Style.RESET_ALL}")
    print()


async def _peek_collection(location: str):
    items = await db.get_collection_by_location(location)
    label = 'Shelf' if location == 'shelf' else 'Backroom'

    if not items:
        print(f"\n  {Fore.WHITE}({label} is empty.){Style.RESET_ALL}\n")
        return

    print()
    print(f"  {Fore.YELLOW}── {label} ({len(items)} items) ──{Style.RESET_ALL}")
    for item in items:
        origin_tag = f" [{item.origin}]" if item.origin != 'appeared' else ''
        print(f"  {Fore.WHITE}• {item.title}{origin_tag}{Style.RESET_ALL}")
        if item.her_feeling:
            print(f"    {Fore.CYAN}\"{item.her_feeling}\"{Style.RESET_ALL}")
        if item.url:
            print(f"    {Fore.BLUE}{item.url}{Style.RESET_ALL}")
    print()


async def _peek_status():
    drives = await db.get_drives_state()
    room = await db.get_room_state()
    engagement = await db.get_engagement_state()
    days = await db.get_days_alive()
    visitors_today = await db.get_visitor_count_today()
    creative = await db.get_last_creative_cycle()

    valence_label = "bright" if drives.mood_valence > 0 else "dark" if drives.mood_valence < 0 else "neutral"

    print()
    print(f"  {Fore.YELLOW}── Status ──{Style.RESET_ALL}")
    print(f"  days alive     {days}")
    print(f"  shop           {room.shop_status}")
    print(f"  time of day    {room.time_of_day}")
    print(f"  weather        {room.weather}")
    if room.ambient_music:
        print(f"  music          {room.ambient_music}")
    print()
    print(f"  {Fore.YELLOW}── Drives ──{Style.RESET_ALL}")
    print(f"  energy         {_bar(drives.energy)} {drives.energy:.2f}")
    print(f"  mood           {drives.mood_valence:+.2f} ({valence_label})")
    print(f"  social hunger  {_bar(drives.social_hunger)} {drives.social_hunger:.2f}")
    print(f"  curiosity      {_bar(drives.curiosity)} {drives.curiosity:.2f}")
    print()
    print(f"  {Fore.YELLOW}── Engagement ──{Style.RESET_ALL}")
    print(f"  status         {engagement.status}")
    print(f"  visitors today {visitors_today}")
    if engagement.visitor_id:
        print(f"  current        {engagement.visitor_id}")
        print(f"  turns          {engagement.turn_count}")
    print()
    if creative:
        print(f"  {Fore.YELLOW}── Last Creative Cycle ──{Style.RESET_ALL}")
        print(f"  time           {_fmt_time(creative['ts'])}")
        if creative.get('internal_monologue'):
            mono = creative['internal_monologue'][:120]
            if len(creative['internal_monologue']) > 120:
                mono += '...'
            print(f"  thought        {mono}")
        print()


async def _peek_totems():
    totems = await db.get_all_totems()

    if not totems:
        print(f"\n  {Fore.WHITE}(No totems yet.){Style.RESET_ALL}\n")
        return

    print()
    print(f"  {Fore.YELLOW}── Totems ({len(totems)}) ──{Style.RESET_ALL}")
    for t in totems:
        weight_bar = '●' * int(t.weight * 5) + '○' * (5 - int(t.weight * 5))
        cat = f" [{t.category}]" if t.category and t.category != 'general' else ''
        ctx = f"  — {t.context}" if t.context else ''
        visitor = f" (visitor)" if t.visitor_id else ''
        print(f"  {Fore.WHITE}{weight_bar} {t.entity}{cat}{visitor}{Style.RESET_ALL}")
        if ctx:
            print(f"       {Fore.CYAN}{ctx}{Style.RESET_ALL}")
    print()


async def _peek_events():
    events = await db.get_recent_events(limit=20)

    if not events:
        print(f"\n  {Fore.WHITE}(No events yet.){Style.RESET_ALL}\n")
        return

    print()
    print(f"  {Fore.YELLOW}── Recent Events (last 20) ──{Style.RESET_ALL}")
    for e in events:
        time = _fmt_time(e.ts)
        source_short = e.source.split(':')[-1][:16] if ':' in e.source else e.source[:16]
        payload_preview = ''
        if e.payload:
            if 'text' in e.payload:
                payload_preview = f" \"{e.payload['text'][:40]}\""
            elif 'title' in e.payload:
                payload_preview = f" \"{e.payload['title'][:40]}\""
        print(f"  {Fore.CYAN}{time}{Style.RESET_ALL} {e.event_type:<24} "
              f"{Fore.WHITE}{source_short}{Style.RESET_ALL}{payload_preview}")
    print()


async def _peek_threads():
    active = await db.get_active_threads(limit=10)
    counts = await db.get_thread_count_by_status()

    total = sum(counts.values())
    if total == 0:
        print(f"\n  {Fore.WHITE}(No threads yet.){Style.RESET_ALL}\n")
        return

    print()
    print(f"  {Fore.YELLOW}── Threads ──{Style.RESET_ALL}")
    status_parts = [f"{k}: {v}" for k, v in sorted(counts.items()) if v > 0]
    print(f"  {Fore.CYAN}{' | '.join(status_parts)}{Style.RESET_ALL}")

    if active:
        print()
        for t in active:
            age = ""
            if t.created_at:
                age_days = (datetime.now(timezone.utc) - t.created_at).days
                age = f" ({age_days}d)" if age_days > 0 else " (new)"
            touches = f" ×{t.touch_count}" if t.touch_count > 0 else ""
            snippet = ""
            if t.content:
                s = t.content[:60]
                if len(t.content) > 60:
                    s += '...'
                snippet = f"\n       {Fore.CYAN}{s}{Style.RESET_ALL}"
            print(f"  {Fore.WHITE}[{t.thread_type}] {t.title}{age}{touches}{Style.RESET_ALL}{snippet}")
    print()


async def _peek_weather():
    """Show most recent ambient weather event."""
    events = await db.get_recent_events(limit=50)
    weather_event = next(
        (e for e in events if e.event_type == 'ambient_weather'), None
    )

    if not weather_event:
        print(f"\n  {Fore.WHITE}(No weather data yet.){Style.RESET_ALL}\n")
        return

    p = weather_event.payload
    print()
    print(f"  {Fore.YELLOW}── Weather ──{Style.RESET_ALL}")
    print(f"  condition  {p.get('condition', '?')}")
    print(f"  temp       {p.get('temp_c', '?')}°C")
    print(f"  season     {p.get('season', '?')}")
    if p.get('diegetic_text'):
        print(f"  feeling    {Fore.CYAN}{p['diegetic_text']}{Style.RESET_ALL}")
    if p.get('season_text'):
        print(f"  seasonal   {Fore.CYAN}{p['season_text']}{Style.RESET_ALL}")
    print(f"  fetched    {_fmt_time(weather_event.ts)}")
    print()


async def _peek_pool():
    """Show content pool summary."""
    stats = await db.get_pool_stats()
    total = sum(stats.values())

    if total == 0:
        print(f"\n  {Fore.WHITE}(Content pool is empty.){Style.RESET_ALL}\n")
        return

    print()
    print(f"  {Fore.YELLOW}── Content Pool ({total} items) ──{Style.RESET_ALL}")
    for status, count in sorted(stats.items()):
        print(f"  {status:<12} {count}")

    # Show unseen items
    unseen = await db.get_pool_items(status='unseen', limit=5)
    if unseen:
        print(f"\n  {Fore.CYAN}Unseen:{Style.RESET_ALL}")
        for item in unseen:
            title = item.get('title', item.get('content', '?'))[:50]
            src = item.get('source_channel', '?')
            print(f"  • {title} ({src})")
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

    # Also add to content pool (visitor drops don't expire)
    from feed_ingester import compute_pool_fingerprint
    source_type = 'url' if is_url else 'text'
    fingerprint = compute_pool_fingerprint('visitor_drop', source_type, content)
    await db.add_to_content_pool(
        fingerprint=fingerprint,
        source_type=source_type,
        source_channel='visitor_drop',
        content=content,
        title=payload.get('title', ''),
        metadata=payload,
        source_event_id=event.id,
        tags=['visitor_gift'],
        ttl_hours=None,
    )


# ─── Client Mode (connects to heartbeat_server) ───

async def client_mode():
    """Connect to a running heartbeat_server."""
    global _input_prompt_active
    visitor_id = get_or_create_visitor_id()

    if not SERVER_TOKEN:
        print(f"\n  {Fore.RED}[Error]{Style.RESET_ALL} SHOPKEEPER_SERVER_TOKEN not set.")
        print(f"  Run: export SHOPKEEPER_SERVER_TOKEN='a-long-random-token'\n")
        return

    use_tls = os.environ.get('SHOPKEEPER_TLS', '').lower() in ('1', 'true', 'yes')
    ssl_ctx = ssl.create_default_context() if use_tls else None

    try:
        reader, writer = await asyncio.open_connection(
            SERVER_HOST, SERVER_PORT, ssl=ssl_ctx,
        )
    except ConnectionRefusedError:
        print(f"\n  {Fore.RED}[Error]{Style.RESET_ALL} Can't connect to heartbeat_server at {SERVER_HOST}:{SERVER_PORT}")
        print(f"  Start the server first: python heartbeat_server.py\n")
        return

    show_banner()

    # Shared flag: set by _client_reader when connection is lost or rejected
    disconnected = asyncio.Event()

    # Send connect
    if not await _client_send(writer, {
        'type': 'visitor_connect',
        'visitor_id': visitor_id,
        'token': SERVER_TOKEN,
    }):
        return

    # Start background reader for server messages
    display_task = asyncio.create_task(_client_reader(reader, disconnected))

    try:
        while not disconnected.is_set():
            try:
                _input_prompt_active = True
                user_input = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: input(f"  {Fore.WHITE}you:{Style.RESET_ALL} ").strip()
                )
            except EOFError:
                break
            finally:
                _input_prompt_active = False

            if disconnected.is_set():
                break

            if not user_input:
                continue

            # Peek commands — read-only, no engagement triggered
            if await handle_peek(user_input):
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

            # Send speech (sanitize ANSI/control chars from terminal input)
            await _client_send(writer, {
                'type': 'visitor_speech',
                'visitor_id': visitor_id,
                'text': sanitize_input(user_input),
            })

    except KeyboardInterrupt:
        print(f"\n\n  {Fore.WHITE}You slip out quietly.{Style.RESET_ALL}\n")

    display_task.cancel()
    writer.close()
    try:
        await writer.wait_closed()
    except Exception:
        pass


async def _client_send(writer: asyncio.StreamWriter, msg: dict) -> bool:
    """Send JSON line to server. Returns False on transport failure."""
    try:
        line = json.dumps(msg) + '\n'
        writer.write(line.encode())
        await writer.drain()
        return True
    except (ConnectionResetError, BrokenPipeError, OSError):
        return False


async def _client_reader(reader: asyncio.StreamReader, disconnected: asyncio.Event):
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
                _ensure_async_line_break()
                print(f"  {Fore.CYAN}{msg.get('body', '...')}{Style.RESET_ALL}")
                sys.stdout.flush()

            elif msg_type == 'stream':
                _ensure_async_line_break()
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
                _ensure_async_line_break()
                expr = msg.get('expression', 'neutral')
                text = msg.get('text', '...')
                print()
                print(f"  {Fore.WHITE}[{expr}]{Style.RESET_ALL}")
                print(f"  {Fore.WHITE}\u300c{text}\u300d{Style.RESET_ALL}")
                print()
                sys.stdout.flush()

            elif msg_type == 'farewell':
                _ensure_async_line_break()
                print(f"\n  {Fore.WHITE}{msg.get('body', '')}{Style.RESET_ALL}")
                sys.stdout.flush()

            elif msg_type == 'drop_ack':
                _ensure_async_line_break()
                print(f"  {Fore.WHITE}{msg.get('body', '')}{Style.RESET_ALL}\n")
                sys.stdout.flush()

            elif msg_type == 'busy':
                _ensure_async_line_break()
                print(f"  {Fore.WHITE}{msg.get('body', '')}{Style.RESET_ALL}\n")
                sys.stdout.flush()

            elif msg_type == 'timeout':
                _ensure_async_line_break()
                print(f"\n  {Fore.RED}[Timeout]{Style.RESET_ALL} {msg.get('body', '')}\n")
                sys.stdout.flush()

            elif msg_type == 'rejected':
                _ensure_async_line_break()
                print(f"\n  {Fore.RED}{msg.get('body', 'Connection rejected.')}{Style.RESET_ALL}\n")
                sys.stdout.flush()
                disconnected.set()
                return

    except asyncio.CancelledError:
        pass
    except Exception:
        pass
    finally:
        disconnected.set()


# ─── Standalone Mode (original behavior + improvements) ───

async def standalone_mode():
    """Run with heartbeat in-process."""
    global _input_prompt_active
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

    # Mark session boundary so Cortex only sees current conversation
    await db.mark_session_boundary(visitor_id)

    # Set engagement BEFORE heartbeat starts
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
                _input_prompt_active = True
                user_input = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: input(f"  {Fore.WHITE}you:{Style.RESET_ALL} ").strip()
                )
            except EOFError:
                break
            finally:
                _input_prompt_active = False

            if not user_input:
                continue

            # Peek commands — read-only, no engagement triggered
            if await handle_peek(user_input):
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

            # Sanitize and log visitor message to conversation
            user_input = sanitize_input(user_input)
            if not user_input:
                continue
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
