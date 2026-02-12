"""Sleep Cycle — daily consolidation. Runs 03:00-06:00 JST."""

from datetime import datetime, timezone
import db
from pipeline.cortex import cortex_call_maintenance


async def sleep_cycle():
    """Daily consolidation."""

    # 1. Build day digest (code-first, no LLM)
    today_events = await db.get_events_today()

    # Thread summary for digest
    thread_counts = await db.get_thread_count_by_status()
    active_threads = await db.get_active_threads(limit=5)
    thread_titles = [t.title for t in active_threads]

    digest = {
        'visitors_today': count_unique_visitors(today_events),
        'visitor_bucket': bucket_visitors(today_events),
        'top_topics': extract_topics(today_events),
        'emotional_arc': compute_emotional_arc(today_events),
        'gifts_received': count_gifts(today_events),
        'thread_counts': thread_counts,
        'active_thread_titles': thread_titles,
        'pool_stats': await db.get_pool_stats(),
    }

    # 2. Cortex writes journal (single call, budget-capped)
    result = await cortex_call_maintenance(
        mode='sleep',
        digest=digest,
        max_tokens=600,
    )

    # 3. Save journal
    journal_text = result.get('journal', 'Today happened. I am still here.')
    journal_id = await db.insert_journal(
        content=journal_text,
        mood='reflective',
        tags=['daily', 'sleep_cycle'],
    )

    # 4. Save summary
    summary = result.get('summary', {})
    summary['journal_entry_id'] = journal_id
    summary['date'] = datetime.now(timezone.utc).date().isoformat()
    await db.insert_daily_summary(summary)

    # 5. Trait stability review (code-first)
    await review_trait_stability()

    # 6. Thread lifecycle management
    await manage_thread_lifecycle()

    # 7. Content pool cleanup
    await cleanup_content_pool()

    # 8. Reset drives for morning
    await reset_drives_for_morning()


def count_unique_visitors(events: list) -> int:
    visitors = set()
    for e in events:
        if e.source.startswith('visitor:'):
            visitors.add(e.source)
    return len(visitors)


def bucket_visitors(events: list) -> str:
    count = count_unique_visitors(events)
    if count == 0:
        return 'none'
    elif count == 1:
        return '1'
    elif count <= 3:
        return '2-3'
    elif count <= 7:
        return '4-7'
    else:
        return '8+'


def extract_topics(events: list) -> list[str]:
    """Extract rough topic keywords from visitor speech."""
    words = {}
    for e in events:
        if e.event_type == 'visitor_speech':
            text = e.payload.get('text', '').lower()
            for word in text.split():
                if len(word) > 4:
                    words[word] = words.get(word, 0) + 1
    sorted_words = sorted(words.items(), key=lambda x: x[1], reverse=True)
    return [w for w, _ in sorted_words[:5]]


def compute_emotional_arc(events: list) -> str:
    """Compute a rough emotional arc from action_body events."""
    expressions = []
    for e in events:
        if e.event_type == 'action_body':
            expr = e.payload.get('expression', 'neutral')
            expressions.append(expr)
    if not expressions:
        return 'quiet'
    return ' → '.join(dict.fromkeys(expressions))  # deduplicate while preserving order


def count_gifts(events: list) -> int:
    count = 0
    for e in events:
        if e.event_type == 'visitor_speech':
            text = e.payload.get('text', '').lower()
            if any(w in text for w in ['gift', 'brought', 'for you', 'listen to', 'check this']):
                count += 1
            elif 'http' in text:
                count += 1
    return count


async def review_trait_stability():
    """Update trait stability based on repetition patterns."""
    active_traits = await db.get_all_active_traits()

    for trait in active_traits:
        observations = await db.get_trait_history(
            trait.visitor_id, trait.trait_category, trait.trait_key
        )

        if len(observations) >= 3:
            # observations are DESC (most recent first), so [:3] = 3 most recent
            recent_three = observations[:3]
            consistent = all(
                o.trait_value == recent_three[0].trait_value
                for o in recent_three
            )
            if consistent:
                new_stability = min(1.0, trait.stability + 0.2)
                await db.update_trait_stability(trait.id, new_stability)

        # Check for unconfirmed anomalies (> 7 days old)
        if trait.status == 'anomaly':
            days_old = (datetime.now(timezone.utc) - trait.observed_at).days
            if days_old > 7:
                await db.update_trait_status(trait.id, 'archived')


async def manage_thread_lifecycle():
    """Transition dormant and archive stale threads during sleep.

    - Threads untouched >48hr → dormant
    - Dormant threads >7 days → archived
    """
    # Transition untouched threads to dormant
    dormant_candidates = await db.get_dormant_threads(older_than_days=2)
    for thread in dormant_candidates:
        if thread.status in ('open', 'active'):
            await db.touch_thread(
                thread.id,
                reason='sleep_cycle_dormant',
                status='dormant',
            )

    # Archive stale dormant threads
    archived_count = await db.archive_stale_threads(older_than_days=7)
    if archived_count > 0:
        print(f"  [Sleep] Archived {archived_count} stale threads.")


async def cleanup_content_pool():
    """Clean up expired and excess pool items during sleep."""
    await db.expire_pool_items()
    await db.cap_unseen_pool()


async def reset_drives_for_morning():
    """Reset drives to morning defaults."""
    drives = await db.get_drives_state()
    drives.social_hunger = 0.5
    drives.curiosity = 0.5
    drives.expression_need = 0.3
    drives.rest_need = 0.2
    drives.energy = 0.8
    # Keep mood — it carries over
    await db.save_drives_state(drives)
