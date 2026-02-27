"""Sleep consolidation — moment iteration, journal writes, daily summary.

Phase 1 of the sleep cycle: fetch unprocessed day memories ranked by salience,
reflect on each via LLM, write individual journal entries, then produce a
daily summary index.
"""

import sys

import db
from db.parameters import p
from alive_config import cfg


async def run_consolidation(*, identity_compact: str = '',
                            has_physical: bool = True) -> int:
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
    reset_drives_for_morning = _pkg.reset_drives_for_morning
    flush_day_memory = _pkg.flush_day_memory

    # 1. Get unprocessed day memories ranked by salience
    moments = await db.get_unprocessed_day_memory(
        min_salience=p('sleep.consolidation.min_salience'),
        limit=int(p('sleep.consolidation.max_reflections')),
    )

    if not moments:
        # Quiet day — write minimal entry if no summary exists yet
        existing_summary = await db.get_daily_summary_for_today()
        if not existing_summary:
            if has_physical:
                _quiet_text = "Nothing happened today. The shop was quiet. I existed."
            else:
                _quiet_text = "Nothing happened today. It was quiet. I existed."
            await db.insert_journal(
                content=_quiet_text,
                mood='still',
                tags=['daily', 'sleep_cycle', 'quiet_day'],
            )
            # MD write — quiet day journal
            try:
                from memory_writer import get_memory_writer
                writer = get_memory_writer()
                await writer.append_journal(_quiet_text, mood_desc='still',
                                            tags=['daily', 'quiet_day'])
            except Exception as e:
                print(f"  [Memory] MD quiet day write failed: {e}")
            await write_daily_summary([], [], [])
        await reset_drives_for_morning()
        await flush_day_memory()
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
            if _pkg.COLD_SEARCH_ENABLED:
                try:
                    from pipeline.cold_search import search_cold_memory
                    cold_echoes = await search_cold_memory(
                        query=moment.summary,
                        limit=int(cfg('sleep_consolidation.cold_search_limit', 3)),
                        exclude_today=True,
                    )
                except Exception as e:
                    print(f"[Sleep] Cold search failed, proceeding without: {e}")

            # c. Reflect (LLM call)
            reflection = await sleep_reflect(moment, hot_ctx, cold_echoes,
                                             identity_compact=identity_compact)
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
                    # MD write — conscious reflection
                    try:
                        from memory_writer import get_memory_writer
                        from memory_translator import scrub_numbers
                        import clock as _clock
                        writer = get_memory_writer()
                        date_str = _clock.now().strftime('%Y-%m-%d')
                        await writer.append_reflection(date_str, 'night',
                                                        scrub_numbers(reflection_text))
                    except Exception as e:
                        print(f"  [Memory] MD reflection write failed: {e}")
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

    # 4. Journal → sleep consolidation feedback (TASK-082)
    # Waking-hour journals are pre-digested reflections — richer consolidation
    # material. When present, they improve sleep quality via mood boost.
    # reset_drives_for_morning() keeps mood, so this persists into next day.
    try:
        today_journals = await db.get_journals_from_current_day()
        if today_journals:
            per_journal = cfg('sleep_consolidation.journal_mood_bonus', 0.04)
            bonus_cap = cfg('sleep_consolidation.journal_mood_bonus_cap', 0.1)
            sleep_quality_bonus = min(bonus_cap, len(today_journals) * per_journal)
            drives = await db.get_drives_state()
            drives.mood_valence = min(1.0, max(-1.0, drives.mood_valence + sleep_quality_bonus))
            await db.save_drives_state(drives)
            print(f"[Sleep] Journal consolidation: {len(today_journals)} waking journals, "
                  f"mood boost +{sleep_quality_bonus:.2f}")
    except Exception as e:
        print(f"[Sleep] Journal consolidation feedback failed: {e}")

    return processed_count
