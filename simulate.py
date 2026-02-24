#!/usr/bin/env python3
"""Simulation Mode — run days/weeks of autonomous shopkeeper life in minutes.

Usage:
    python simulate.py --days 7
    python simulate.py --days 3 --content content/readings.txt
    python simulate.py --days 7 --visitors experiments/visitors.json
    python simulate.py --days 1 --start 2026-02-10T07:00 --quiet
    python simulate.py --days 7 --daily-budget 2.0 --output experiments/run_a/
    python simulate.py --days 7 --daily-budget 1.00 --run-label tight --output experiments/

The shopkeeper runs the real pipeline with real LLM calls against a
separate simulation DB, using a virtual clock that advances instantly
instead of waiting. With --visitors, scripted visitor interactions are
injected at the correct simulated times. With --daily-budget, the daily
dollar budget is overridden via the settings table (default: 2.00).
With --run-label, output files use the label as filename (e.g.
tight.db) instead of timestamp+uuid.
"""

import argparse
import asyncio
import json
import os
import pathlib
import sys
import uuid
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
load_dotenv()

import clock
from clock import JST
import db
from seed import seed
from heartbeat import Heartbeat
from sleep import sleep_cycle
from timeline import TimelineLogger


SLEEP_START_HOUR = 3
SLEEP_END_HOUR = 6
SLEEP_ADVANCE_SECONDS = 3 * 3600  # 3 hours for sleep consolidation
VISITOR_DEPART_DELAY_MIN = 5  # minutes after last message before departure

PRODUCTION_DB_NAMES = frozenset({"shopkeeper.db", "shopkeeper-prod.db"})


def _validate_sim_db_path(path: str) -> None:
    """Hard guard: refuse to open anything that looks like the production DB."""
    basename = os.path.basename(path)
    if basename in PRODUCTION_DB_NAMES:
        raise RuntimeError(
            f"REFUSED: simulation tried to open production DB '{path}'. "
            f"Use --db to specify a separate file."
        )


def load_visitor_schedule(visitor_file: str, sim_start: datetime) -> list[dict]:
    """Load visitor script from JSON and build a flat, sorted event schedule.

    Returns a list of dicts, each with:
        sim_time: datetime (JST) when the event fires
        event_type: 'arrive' | 'message' | 'depart'
        visitor_id: str
        display_name: str
        text: str (for message events, empty otherwise)
    """
    with open(visitor_file, 'r') as f:
        visitors = json.load(f)

    schedule = []
    for entry in visitors:
        vid = entry['visitor_id']
        name = entry['display_name']
        day = entry['arrive_day']
        hour = entry['arrive_hour']

        # Compute arrival time: sim_start day 1 = arrive_day 1
        arrival = sim_start.replace(
            hour=hour, minute=0, second=0, microsecond=0
        ) + timedelta(days=day - 1)

        # Arrival event
        schedule.append({
            'sim_time': arrival,
            'event_type': 'arrive',
            'visitor_id': vid,
            'display_name': name,
            'text': '',
        })

        # Message events
        last_msg_time = arrival
        for msg in entry['messages']:
            msg_time = arrival + timedelta(minutes=msg['delay_min'])
            schedule.append({
                'sim_time': msg_time,
                'event_type': 'message',
                'visitor_id': vid,
                'display_name': name,
                'text': msg['text'],
            })
            last_msg_time = msg_time

        # Departure: VISITOR_DEPART_DELAY_MIN after last message
        depart_time = last_msg_time + timedelta(minutes=VISITOR_DEPART_DELAY_MIN)
        schedule.append({
            'sim_time': depart_time,
            'event_type': 'depart',
            'visitor_id': vid,
            'display_name': name,
            'text': '',
        })

    # Sort by time, with arrive before message before depart for same timestamp
    type_order = {'arrive': 0, 'message': 1, 'depart': 2}
    schedule.sort(key=lambda e: (e['sim_time'], type_order[e['event_type']]))
    return schedule


async def handle_visitor_arrive(hb, tl, entry: dict, quiet: bool):
    """Process a visitor arrival event."""
    from models.event import Event

    vid = entry['visitor_id']
    name = entry['display_name']
    now = clock.now()

    tl.log_visitor_arrive(now, name, quiet=quiet)

    # Create visitor in DB if not exists
    visitor = await db.get_visitor(vid)
    if visitor is None:
        await db.create_visitor(vid)
        await db.update_visitor(vid, name=name)
    else:
        # Returning visitor — increment visit count
        await db.increment_visit(vid)

    # Add to visitors_present
    await db.add_visitor_present(vid, connection_type='simulation')

    # Set engagement state
    await db.update_engagement_state(
        status='engaged',
        visitor_id=vid,
        started_at=clock.now_utc(),
        last_activity=clock.now_utc(),
        turn_count=0,
    )

    # Insert visitor_connect event into inbox
    connect_event = Event(
        event_type='visitor_connect',
        source=f'visitor:{vid}',
        payload={'visitor_id': vid, 'display_name': name},
        channel='visitor',
        salience_base=0.8,
    )
    await db.append_event(connect_event)

    # Run a micro cycle so she processes the arrival
    try:
        await hb.run_cycle('micro')
    except Exception as e:
        print(f"  [Sim] Visitor arrive cycle error: {e}")


async def handle_visitor_message(hb, tl, entry: dict, quiet: bool):
    """Process a visitor message event."""
    from models.event import Event

    vid = entry['visitor_id']
    name = entry['display_name']
    text = entry['text']
    now = clock.now()

    tl.log_visitor_message(now, name, text, quiet=quiet)

    # Store conversation turn
    await db.append_conversation(vid, 'visitor', text)

    # Update engagement last_activity
    await db.update_engagement_state(last_activity=clock.now_utc())
    await db.update_visitor_present(vid, last_activity=clock.now_utc().isoformat())

    # Insert visitor_speech event into inbox
    speech_event = Event(
        event_type='visitor_speech',
        source=f'visitor:{vid}',
        payload={
            'visitor_id': vid,
            'display_name': name,
            'text': text,
        },
        channel='visitor',
        salience_base=0.9,
    )
    await db.append_event(speech_event)

    # Run a micro cycle so she responds
    try:
        await hb.run_cycle('micro')
    except Exception as e:
        print(f"  [Sim] Visitor message cycle error: {e}")


async def handle_visitor_depart(hb, tl, entry: dict, quiet: bool):
    """Process a visitor departure event."""
    from models.event import Event

    vid = entry['visitor_id']
    name = entry['display_name']
    now = clock.now()

    tl.log_visitor_depart(now, name, quiet=quiet)

    # Mark conversation session boundary
    await db.mark_session_boundary(vid)

    # Insert visitor_disconnect event
    disconnect_event = Event(
        event_type='visitor_disconnect',
        source=f'visitor:{vid}',
        payload={'visitor_id': vid, 'display_name': name},
        channel='visitor',
        salience_base=0.6,
    )
    await db.append_event(disconnect_event)

    # Remove from visitors_present
    await db.remove_visitor_present(vid)

    # Clear engagement state
    await db.update_engagement_state(
        status='none', visitor_id=None, turn_count=0,
        started_at=None, last_activity=None,
    )

    # Run a micro cycle so she processes the departure
    try:
        await hb.run_cycle('micro')
    except Exception as e:
        print(f"  [Sim] Visitor depart cycle error: {e}")


async def run_simulation(
    days: int,
    content_files: list[str] = None,
    visitor_file: str = None,
    start: datetime = None,
    quiet: bool = False,
    daily_budget: float = None,
    output_dir: str = None,
    run_label: str = None,
    db_path: str = None,
):
    """Main simulation loop."""

    # 1. Initialize virtual clock
    if start is None:
        start = datetime.now(JST).replace(
            hour=7, minute=0, second=0, microsecond=0
        )
    clock.init_clock(simulate=True, start=start)
    target = start + timedelta(days=days)

    # 2. Create simulation DB
    if db_path:
        # Explicit --db path takes priority
        sim_db_path = str(pathlib.Path(db_path).resolve())
        sim_db_dir = pathlib.Path(sim_db_path).parent
        sim_db_dir.mkdir(parents=True, exist_ok=True)
        log_base = pathlib.Path(sim_db_path).stem
    else:
        sim_db_dir = pathlib.Path(output_dir) if output_dir else pathlib.Path('data/sim')
        sim_db_dir.mkdir(parents=True, exist_ok=True)
        if run_label:
            # Named run: deterministic filenames for easy reference
            sim_db_path = str(sim_db_dir / f'{run_label}.db')
            log_base = run_label
        else:
            # Default: unique filenames via timestamp + uuid
            run_id = str(uuid.uuid4())[:8]
            ts_str = start.strftime('%Y%m%d_%H%M%S')
            sim_db_path = str(sim_db_dir / f'sim_{ts_str}_{run_id}.db')
            log_base = f'timeline_{ts_str}_{run_id}'
    _validate_sim_db_path(sim_db_path)
    db.set_db_path(sim_db_path)
    await db.init_db()

    # 3. Seed DB
    await seed()

    # 3b. Override daily budget if specified (TASK-049: uses real-dollar budget via settings table)
    if daily_budget is not None:
        await db.set_setting('daily_budget', str(round(daily_budget, 2)))

    # 4. Pre-load content pool from files
    if content_files:
        from feed_ingester import ingest_from_file
        for filepath in content_files:
            count = await ingest_from_file(filepath)
            print(f"  Loaded {count} items from {filepath}")

    # 5. Load visitor schedule
    visitor_schedule = []
    if visitor_file:
        visitor_schedule = load_visitor_schedule(visitor_file, start)
        print(f"  Loaded {len(visitor_schedule)} visitor events from {visitor_file}")

    # 6. Create timeline logger
    log_path = str(sim_db_dir / f'{log_base}.log')
    tl = TimelineLogger(log_path, start)

    # 7. Initialize heartbeat (no event loop task)
    hb = Heartbeat()
    await hb.start_for_simulation()

    # 8. Inject initial weather event
    from pipeline.ambient import fetch_ambient_context
    from models.event import Event
    ambient = await fetch_ambient_context()
    if ambient:
        weather_event = Event(
            event_type='ambient_weather',
            source='ambient',
            payload={
                'condition': ambient.condition,
                'temp_c': ambient.temp_c,
                'diegetic_text': ambient.diegetic_text,
                'season': ambient.season,
                'season_text': ambient.season_text,
            },
            channel='ambient',
            salience_base=0.1,
            ttl_hours=1.0,
        )
        await db.append_event(weather_event)

    # 9. Main simulation loop
    cycle_count = 0
    sleep_count = 0
    visitor_event_count = 0
    schedule_idx = 0  # pointer into sorted visitor_schedule

    print(f"\n  Simulating {days} day(s) starting {start.strftime('%Y-%m-%d %H:%M JST')}")
    print(f"  DB: {sim_db_path}")
    print(f"  Target: {target.strftime('%Y-%m-%d %H:%M JST')}")
    if daily_budget is not None:
        print(f"  Daily budget: ${daily_budget:.2f} (overridden)")
    if visitor_schedule:
        unique_visitors = len(set(
            (e['visitor_id'], e['sim_time'].date()) for e in visitor_schedule
            if e['event_type'] == 'arrive'
        ))
        print(f"  Visitor interactions: {unique_visitors}")
    print()

    while clock.now() < target:
        now_jst = clock.now()
        hour = now_jst.hour

        # ── Process any pending visitor events at current time ──
        while schedule_idx < len(visitor_schedule):
            entry = visitor_schedule[schedule_idx]
            if entry['sim_time'] > now_jst:
                break  # not yet time

            schedule_idx += 1
            visitor_event_count += 1
            etype = entry['event_type']

            if etype == 'arrive':
                await handle_visitor_arrive(hb, tl, entry, quiet)
            elif etype == 'message':
                await handle_visitor_message(hb, tl, entry, quiet)
            elif etype == 'depart':
                await handle_visitor_depart(hb, tl, entry, quiet)

        # ── Sleep window: 03:00-06:00 JST ──
        if SLEEP_START_HOUR <= hour < SLEEP_END_HOUR:
            today_str = now_jst.date().isoformat()

            # Attempt sleep if not done today
            if hb._last_sleep_date != today_str:
                try:
                    moment_count = await sleep_cycle()
                    if moment_count >= 0:
                        hb._last_sleep_date = today_str
                        sleep_count += 1
                        tl.log_sleep(now_jst, moment_count, quiet=quiet)
                except Exception as e:
                    print(f"  [Sim] Sleep error: {e}")

            if hb._last_sleep_date == today_str:
                # Sleep done — advance past window + inject fresh weather
                clock.advance(SLEEP_ADVANCE_SECONDS)
                tl.log_wake(clock.now(), quiet=quiet)

                ambient = await fetch_ambient_context()
                if ambient:
                    weather_event = Event(
                        event_type='ambient_weather',
                        source='ambient',
                        payload={
                            'condition': ambient.condition,
                            'temp_c': ambient.temp_c,
                            'diegetic_text': ambient.diegetic_text,
                            'season': ambient.season,
                            'season_text': ambient.season_text,
                        },
                        channel='ambient',
                        salience_base=0.1,
                        ttl_hours=1.0,
                    )
                    await db.append_event(weather_event)
            else:
                # Sleep deferred — advance 60s and retry next iteration
                clock.advance(60)
            continue

        # ── Normal cycle ──
        try:
            # Check if next visitor event is soon — advance to it if closer
            # than the normal cycle interval, to avoid overshooting
            next_visitor_time = None
            if schedule_idx < len(visitor_schedule):
                next_visitor_time = visitor_schedule[schedule_idx]['sim_time']

            result = await hb.run_one_cycle()
            cycle_count += 1
            tl.log_cycle(now_jst, result, quiet=quiet)

            # Advance clock, but don't overshoot next visitor event
            advance_secs = result.sleep_seconds
            if next_visitor_time is not None:
                secs_to_visitor = (next_visitor_time - clock.now()).total_seconds()
                if secs_to_visitor > 0:
                    advance_secs = min(advance_secs, int(secs_to_visitor))
            clock.advance(max(1, advance_secs))

        except KeyboardInterrupt:
            print("\n  Simulation interrupted by user.")
            break
        except Exception as e:
            print(f"  [Sim] Cycle error: {e}")
            # Advance a small amount to avoid infinite loop on persistent errors
            # but don't overshoot visitor events
            advance = 300
            if schedule_idx < len(visitor_schedule):
                secs_to_visitor = (visitor_schedule[schedule_idx]['sim_time'] - clock.now()).total_seconds()
                if secs_to_visitor > 0:
                    advance = min(advance, int(secs_to_visitor))
            clock.advance(max(1, advance))

    # 10. Summary
    try:
        journal_count = await db.count_journal_entries()
    except Exception:
        journal_count = '?'
    try:
        cycle_log_count = await db.count_cycle_logs()
    except Exception:
        cycle_log_count = '?'

    stats = {
        'total_cycles': cycle_count,
        'days': days,
        'journal_count': journal_count,
        'cycle_log_count': cycle_log_count,
        'db_path': sim_db_path,
    }
    if visitor_schedule:
        stats['visitor_events'] = visitor_event_count

    tl.log_summary(stats)

    tl.close()
    await db.close_db()

    return sim_db_path


def main():
    parser = argparse.ArgumentParser(
        description='Run shopkeeper simulation',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python simulate.py --days 7
  python simulate.py --days 3 --content content/readings.txt
  python simulate.py --days 7 --visitors experiments/visitors.json
  python simulate.py --days 1 --start 2026-02-10T07:00 --quiet
  python simulate.py --days 7 --daily-budget 2.0 --output experiments/run_a/
  python simulate.py --days 7 --daily-budget 1.00 --run-label tight --output experiments/
        """,
    )
    parser.add_argument('--days', type=int, default=1, help='Days to simulate (default: 1)')
    parser.add_argument('--content', nargs='*', help='Content files to pre-load into pool')
    parser.add_argument('--visitors', help='Visitor script JSON file')
    parser.add_argument('--start', help='Start time in ISO format (default: today 07:00 JST)')
    parser.add_argument('--quiet', action='store_true', help='Suppress per-cycle output')
    parser.add_argument('--daily-budget', type=float, default=None,
                        help='Override daily dollar budget (default: 2.00)')
    parser.add_argument('--output', default=None,
                        help='Output directory for DB and timeline log (default: data/sim/)')
    parser.add_argument('--run-label', default=None,
                        help='Label for output files (e.g. sim_v2_tight → sim_v2_tight.db)')
    parser.add_argument('--db', default=None,
                        help='Explicit DB path (overrides --output/--run-label)')
    args = parser.parse_args()

    if args.daily_budget is not None and args.daily_budget <= 0:
        parser.error('--daily-budget must be > 0')

    start = None
    if args.start:
        start = datetime.fromisoformat(args.start)
        if start.tzinfo is None:
            start = start.replace(tzinfo=JST)
        else:
            start = start.astimezone(JST)

    asyncio.run(run_simulation(
        days=args.days,
        content_files=args.content,
        visitor_file=args.visitors,
        start=start,
        quiet=args.quiet,
        daily_budget=args.daily_budget,
        output_dir=args.output,
        run_label=args.run_label,
        db_path=args.db,
    ))


if __name__ == '__main__':
    main()
