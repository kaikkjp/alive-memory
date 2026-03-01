"""Wake transition — drive reset, memory flush, thread lifecycle, content pool.

Phase 5 of the sleep cycle: everything that happens after reflection and review,
preparing the system for the next day.
"""

import sys

import clock
import db
from db.parameters import p


async def run_wake_transition() -> None:
    """Run all wake transition steps in order.

    Uses late-bound references through the sleep package so tests can patch
    sleep.manage_thread_lifecycle, sleep.reset_drives_for_morning, etc.
    """
    _pkg = sys.modules['sleep']

    # 5. Thread lifecycle management
    await _pkg.manage_thread_lifecycle()

    # 6. Content pool cleanup
    await _pkg.cleanup_content_pool()

    # 7. Reset drives for morning
    await _pkg.reset_drives_for_morning()

    # 7b. Write last_sleep_reset timestamp for budget tracking.
    await db.set_setting('last_sleep_reset', clock.now_utc().isoformat())

    # 8. Embed today's cold memory entries (Phase 2)
    if _pkg.COLD_SEARCH_ENABLED:
        try:
            from pipeline.embed_cold import embed_new_cold_entries
            stats = await embed_new_cold_entries()
            print(f"[Sleep] Embedded {stats['conversations_embedded']} convos + "
                  f"{stats['monologues_embedded']} monologues")
        except Exception as e:
            print(f"[Sleep] Embedding pipeline failed: {e}")

    # 9. Flush processed day memory + stale cleanup
    await _pkg.flush_day_memory()

    # 10. Update conscious self-memory files
    await _update_self_memory_files()


async def reset_drives_for_morning():
    """Reset drives to morning defaults."""
    drives = await db.get_drives_state()
    drives.social_hunger = p('sleep.morning.social_hunger')
    drives.curiosity = p('sleep.morning.curiosity')
    drives.expression_need = p('sleep.morning.expression_need')
    # NOTE: rest_need removed (TASK-106). Dollar budget is energy.
    # NOTE: energy is now a display-only derived value from real-dollar budget
    # (TASK-050). After sleep reset writes last_sleep_reset, budget is full,
    # so energy will read as 1.0 on next cycle's budget check.
    drives.energy = p('sleep.morning.energy')  # display hint — actual value derived from budget
    # Keep mood — it carries over
    await db.save_drives_state(drives)


async def flush_day_memory() -> None:
    """Clear processed day memory entries + stale unprocessed rows.

    The stale cleanup is a safety net: if sleep only processes top-K moments,
    unprocessed rows from previous days would otherwise leak into "Earlier today"
    recall (day_context queries now filter by JST date, but this prevents
    unbounded accumulation).
    """
    await db.delete_processed_day_memory()
    await db.delete_stale_day_memory(max_age_days=int(p('sleep.cleanup.stale_day_memory_days')))


async def manage_thread_lifecycle():
    """Transition dormant and archive stale threads during sleep.

    - Threads untouched >48hr → dormant
    - Dormant threads >7 days → archived
    """
    # Transition untouched threads to dormant
    dormant_candidates = await db.get_dormant_threads(
        older_than_hours=int(p('sleep.cleanup.dormant_thread_hours')))
    for thread in dormant_candidates:
        if thread.status in ('open', 'active'):
            await db.touch_thread(
                thread.id,
                reason='sleep_cycle_dormant',
                status='dormant',
            )

    # Archive stale dormant threads
    archived_count = await db.archive_stale_threads(
        older_than_days=int(p('sleep.cleanup.archive_thread_days')))
    if archived_count > 0:
        print(f"  [Sleep] Archived {archived_count} stale threads.")


async def cleanup_content_pool():
    """Clean up expired and excess pool items during sleep."""
    from config.feeds import MAX_POOL_UNSEEN
    await db.expire_pool_items()
    await db.cap_unseen_pool(max_unseen=MAX_POOL_UNSEEN)


async def _update_self_memory_files():
    """Update conscious self-knowledge files during wake transition.

    Reads identity narrative from self-discoveries in DB,
    translates to natural language, and writes to self/ MD files.
    """
    try:
        from memory_writer import get_memory_writer
        from memory_translator import scrub_numbers
        writer = get_memory_writer()

        # Identity file — self-discoveries as narrative
        try:
            discoveries_text = await db.get_self_discoveries()
            if discoveries_text:
                content = f"# Who I Am\n\n{scrub_numbers(discoveries_text)}\n"
                await writer.write_self_file('identity.md', content)
        except Exception as e:
            print(f"  [Memory] Self identity write failed: {e}")

    except Exception as e:
        print(f"  [Memory] Self memory files update failed: {e}")
