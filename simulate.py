#!/usr/bin/env python3
"""Simulation Mode — run days/weeks of autonomous shopkeeper life in minutes.

Usage:
    python simulate.py --days 7
    python simulate.py --days 3 --content content/readings.txt
    python simulate.py --days 1 --start 2026-02-10T07:00 --quiet

The shopkeeper runs the real pipeline with real LLM calls against a
separate simulation DB, using a virtual clock that advances instantly
instead of waiting. No visitors — pure autonomous life.
"""

import argparse
import asyncio
import os
import pathlib
import sys
import uuid
from datetime import datetime, timedelta, timezone

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


async def run_simulation(
    days: int,
    content_files: list[str] = None,
    start: datetime = None,
    quiet: bool = False,
):
    """Main simulation loop."""

    # 1. Initialize virtual clock
    if start is None:
        start = datetime.now(JST).replace(
            hour=7, minute=0, second=0, microsecond=0
        )
    clock.init_clock(simulate=True, start=start)
    target = start + timedelta(days=days)

    # 2. Create simulation DB (run_id ensures uniqueness across reruns)
    run_id = str(uuid.uuid4())[:8]
    ts_str = start.strftime('%Y%m%d_%H%M%S')
    sim_db_dir = pathlib.Path('data/sim')
    sim_db_dir.mkdir(parents=True, exist_ok=True)
    sim_db_path = str(sim_db_dir / f'sim_{ts_str}_{run_id}.db')
    db.set_db_path(sim_db_path)
    await db.init_db()

    # 3. Seed DB
    await seed()

    # 4. Pre-load content pool from files
    if content_files:
        from feed_ingester import ingest_from_file
        for filepath in content_files:
            count = await ingest_from_file(filepath)
            print(f"  Loaded {count} items from {filepath}")

    # 5. Create timeline logger
    log_path = str(sim_db_dir / f'timeline_{ts_str}_{run_id}.log')
    tl = TimelineLogger(log_path, start)

    # 6. Initialize heartbeat (no event loop task)
    hb = Heartbeat()
    await hb.start_for_simulation()

    # 7. Inject initial weather event
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

    # 8. Main simulation loop
    cycle_count = 0
    sleep_count = 0

    print(f"\n  Simulating {days} day(s) starting {start.strftime('%Y-%m-%d %H:%M JST')}")
    print(f"  DB: {sim_db_path}")
    print(f"  Target: {target.strftime('%Y-%m-%d %H:%M JST')}")
    print()

    while clock.now() < target:
        now_jst = clock.now()
        hour = now_jst.hour

        # Sleep window: 03:00-06:00 JST
        if SLEEP_START_HOUR <= hour < SLEEP_END_HOUR:
            today_str = now_jst.date().isoformat()

            # Attempt sleep if not done today
            if hb._last_sleep_date != today_str:
                try:
                    ran = await sleep_cycle()
                    if ran:
                        hb._last_sleep_date = today_str
                        sleep_count += 1
                        tl.log_sleep(now_jst, 0, quiet=quiet)
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

        # Normal cycle
        try:
            result = await hb.run_one_cycle()
            cycle_count += 1
            tl.log_cycle(now_jst, result, quiet=quiet)

            # Advance clock by the sleep_seconds from the cycle result
            clock.advance(result.sleep_seconds)

        except KeyboardInterrupt:
            print("\n  Simulation interrupted by user.")
            break
        except Exception as e:
            print(f"  [Sim] Cycle error: {e}")
            # Advance 5 min to avoid infinite loop on persistent errors
            clock.advance(300)

    # 9. Summary
    try:
        journal_count = await db.count_journal_entries()
    except Exception:
        journal_count = '?'
    try:
        cycle_log_count = await db.count_cycle_logs()
    except Exception:
        cycle_log_count = '?'

    tl.log_summary({
        'total_cycles': cycle_count,
        'days': days,
        'journal_count': journal_count,
        'cycle_log_count': cycle_log_count,
        'db_path': sim_db_path,
    })

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
  python simulate.py --days 1 --start 2026-02-10T07:00 --quiet
        """,
    )
    parser.add_argument('--days', type=int, default=1, help='Days to simulate (default: 1)')
    parser.add_argument('--content', nargs='*', help='Content files to pre-load into pool')
    parser.add_argument('--start', help='Start time in ISO format (default: today 07:00 JST)')
    parser.add_argument('--quiet', action='store_true', help='Suppress per-cycle output')
    args = parser.parse_args()

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
        start=start,
        quiet=args.quiet,
    ))


if __name__ == '__main__':
    main()
