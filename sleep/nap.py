"""Nap consolidation — lighter mid-cycle consolidation.

Processes the top N unprocessed day moments by salience, runs the same
sleep_reflect() LLM call on each, writes individual journal entries,
and marks them as nap_processed so night sleep won't re-process them.
"""

import sys

import db
from db.parameters import p


async def nap_consolidate(top_n: int = None) -> int:
    """Nap consolidation — process top moments mid-day.

    Fetches the top N unprocessed day moments by salience, runs the same
    sleep_reflect() LLM call on each, writes individual journal entries,
    and marks them as nap_processed so night sleep won't re-process them.

    Returns the number of moments processed.
    """
    # Late-bind through package namespace so tests can patch sleep.X names
    _pkg = sys.modules['sleep']
    gather_hot_context = _pkg.gather_hot_context
    sleep_reflect = _pkg.sleep_reflect
    hippocampus_consolidate = _pkg.hippocampus_consolidate

    if top_n is None:
        top_n = int(p('sleep.consolidation.nap_top_n'))
    moments = await db.get_top_unprocessed_moments(limit=top_n)
    if not moments:
        print("[Nap] No unprocessed moments to consolidate.")
        return 0

    max_retries = int(p('sleep.consolidation.max_retries'))
    processed_ids = []
    for moment in moments:
        if moment.retry_count >= max_retries:
            processed_ids.append(moment.id)
            print(f"[Nap] Poison moment {moment.id} skipped")
            continue

        try:
            hot_ctx = await gather_hot_context(moment)
            reflection = await sleep_reflect(moment, hot_ctx, cold_echoes=[])

            async with db.transaction():
                reflection_text = reflection.get('reflection', '')
                if reflection_text:
                    await db.insert_journal(
                        content=reflection_text,
                        mood='reflective',
                        tags=['nap_reflection', moment.moment_type] + (moment.tags or []),
                    )
                for update in reflection.get('memory_updates', []):
                    await hippocampus_consolidate(update, moment.visitor_id)
                await db.mark_day_memory_processed(moment.id)

            processed_ids.append(moment.id)
        except Exception as e:
            await db.increment_day_memory_retry(moment.id)
            print(f"[Nap] Moment {moment.id} failed: {e}")

    # Mark all successfully processed moments as nap_processed
    if processed_ids:
        await db.mark_moments_nap_processed(processed_ids)

    print(f"[Nap] Consolidated {len(processed_ids)} moments.")
    return len(processed_ids)
