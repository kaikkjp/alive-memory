"""Sleep consolidation — moment iteration, journal writes, daily summary.

Phase 1 of the sleep cycle: fetch unprocessed day memories ranked by salience,
reflect on each via LLM, write individual journal entries, then produce a
daily summary index.
"""

import os
import sys

import db
from db.parameters import p

COLD_SEARCH_ENABLED = os.getenv('COLD_SEARCH_ENABLED', 'false').lower() == 'true'


async def run_consolidation() -> int:
    """Run the full consolidation phase of the sleep cycle.

    Returns number of moments consolidated (>=0) if successful, -1 if all
    moments failed and we should defer for retry.
    """
    # Late-bind through package namespace so tests can patch sleep.X names
    _pkg = sys.modules['sleep']
    gather_hot_context = _pkg.gather_hot_context
    sleep_reflect = _pkg.sleep_reflect
    write_daily_summary = _pkg.write_daily_summary
    hippocampus_consolidate = _pkg.hippocampus_consolidate

    # 1. Get unprocessed day memories ranked by salience
    moments = await db.get_unprocessed_day_memory(
        min_salience=p('sleep.consolidation.min_salience'),
        limit=int(p('sleep.consolidation.max_reflections')),
    )

    if not moments:
        # Quiet day — write minimal entry if no summary exists yet
        existing_summary = await db.get_daily_summary_for_today()
        if not existing_summary:
            await db.insert_journal(
                content="Nothing happened today. The shop was quiet. I existed.",
                mood='still',
                tags=['daily', 'sleep_cycle', 'quiet_day'],
            )
            await write_daily_summary([], [], [])
        # Drive reset + memory flush handled by run_wake_transition() in orchestrator
        return 0

    # 2. Reflect on each moment (crash-safe: each is its own transaction)
    all_reflections = []
    journal_entry_ids = []
    processed_count = 0
    max_retries = int(p('sleep.consolidation.max_retries'))
    for moment in moments:
        # Poison moment protection
        if moment.retry_count >= max_retries:
            await db.mark_day_memory_processed(moment.id)
            processed_count += 1  # poison skip counts as handled
            print(f"[Sleep] Poison moment {moment.id} skipped after {max_retries} retries")
            continue

        try:
            # a. Gather hot memory context
            hot_ctx = await gather_hot_context(moment)

            # b. Cold search (Phase 2 — semantic search over past conversations)
            cold_echoes = []
            if COLD_SEARCH_ENABLED:
                try:
                    from pipeline.cold_search import search_cold_memory
                    cold_echoes = await search_cold_memory(
                        query=moment.summary, limit=3, exclude_today=True,
                    )
                except Exception as e:
                    print(f"[Sleep] Cold search failed, proceeding without: {e}")

            # c. Reflect (LLM call)
            reflection = await sleep_reflect(moment, hot_ctx, cold_echoes)
            all_reflections.append({
                'moment': moment,
                'reflection': reflection,
            })

            # d. Write individual journal entry + hot memory + mark processed (atomic)
            async with db.transaction():
                reflection_text = reflection.get('reflection', '')
                if reflection_text:
                    journal_id = await db.insert_journal(
                        content=reflection_text,
                        mood='reflective',
                        tags=['sleep_reflection', moment.moment_type] + (moment.tags or []),
                    )
                    journal_entry_ids.append(journal_id)
                for update in reflection.get('memory_updates', []):
                    await hippocampus_consolidate(update, moment.visitor_id)
                await db.mark_day_memory_processed(moment.id)

            processed_count += 1

        except Exception as e:
            # Increment retry OUTSIDE the failed transaction (separate write)
            await db.increment_day_memory_retry(moment.id)
            print(f"[Sleep] Moment {moment.id} failed (retry {moment.retry_count + 1}): {e}")

    # If we had moments but processed none, defer to allow retry
    if moments and processed_count == 0:
        print("[Sleep] All moments failed — deferring for retry.")
        return -1

    # 3. Write daily summary (lightweight index, not narrative)
    await write_daily_summary(moments, all_reflections, journal_entry_ids)

    return processed_count
