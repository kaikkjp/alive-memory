"""Sleep Cycle — daily consolidation. Runs 03:00-06:00 JST.

Phase 1: Day memory → hot memory via moment-by-moment reflection.
Phase 2: Cold memory search via embeddings (COLD_SEARCH_ENABLED).
"""

import os
from datetime import datetime, timezone

import db
from db import JST
from pipeline.cortex import cortex_call_reflect, SLEEP_REFLECTION_SYSTEM
from pipeline.hippocampus import (
    compress_visitor, format_totems, format_journal_entries, relative_time,
)
from pipeline.hippocampus_write import hippocampus_consolidate
from config.identity import IDENTITY_COMPACT

MAX_SLEEP_REFLECTIONS = 7
MIN_SLEEP_SALIENCE = 0.4
MAX_MOMENT_RETRIES = 3
COLD_SEARCH_ENABLED = os.getenv('COLD_SEARCH_ENABLED', 'false').lower() == 'true'


async def sleep_cycle() -> bool:
    """Daily consolidation. Runs 03:00-06:00 JST.

    Returns True if ran (even if no moments), False if deferred.
    Heartbeat stamps _last_sleep_date ONLY when this returns True.
    """

    # 0. Defer if she's mid-conversation
    engagement = await db.get_engagement_state()
    if engagement.status == 'engaged':
        print("[Sleep] Deferred — currently engaged with a visitor.")
        return False

    # 1. Get unprocessed day memories ranked by salience
    moments = await db.get_unprocessed_day_memory(
        min_salience=MIN_SLEEP_SALIENCE,
        limit=MAX_SLEEP_REFLECTIONS,
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
        await reset_drives_for_morning()
        await flush_day_memory()
        return True

    # 2. Reflect on each moment (crash-safe: each is its own transaction)
    all_reflections = []
    processed_count = 0
    for moment in moments:
        # Poison moment protection
        if moment.retry_count >= MAX_MOMENT_RETRIES:
            await db.mark_day_memory_processed(moment.id)
            processed_count += 1  # poison skip counts as handled
            print(f"[Sleep] Poison moment {moment.id} skipped after {MAX_MOMENT_RETRIES} retries")
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

            # d. Write to hot memory + mark processed (atomic)
            async with db.transaction():
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
        return False

    # 3. Write daily summary
    await write_daily_summary(moments, all_reflections)

    # 4. Trait stability review (unchanged)
    await review_trait_stability()

    # 5. Reset drives for morning
    await reset_drives_for_morning()

    # 6. Embed today's cold memory entries (Phase 2)
    if COLD_SEARCH_ENABLED:
        try:
            from pipeline.embed_cold import embed_new_cold_entries
            stats = await embed_new_cold_entries()
            print(f"[Sleep] Embedded {stats['conversations_embedded']} convos + "
                  f"{stats['monologues_embedded']} monologues")
        except Exception as e:
            print(f"[Sleep] Embedding pipeline failed: {e}")

    # 7. Flush processed day memory + stale cleanup
    await flush_day_memory()

    return True


# ─── Sleep Helpers ───

async def gather_hot_context(moment) -> dict:
    """Gather relevant hot memory for a moment. No LLM."""
    context = {}

    # Visitor-specific
    if moment.visitor_id:
        visitor = await db.get_visitor(moment.visitor_id)
        if visitor:
            context['visitor'] = compress_visitor(visitor)
        traits = await db.get_visitor_traits(moment.visitor_id, limit=10)
        if traits:
            context['traits'] = format_traits_for_sleep(traits)
        totems = await db.get_totems(moment.visitor_id, min_weight=0.2, limit=8)
        if totems:
            context['totems'] = format_totems(totems)

    # Tag-based collection search
    if moment.tags:
        for tag in moment.tags[:3]:
            items = await db.search_collection(query=tag, limit=2)
            if items:
                context.setdefault('collection', []).extend(
                    [f"{item.title}: {item.her_feeling or ''}" for item in items]
                )

    # Recent journal
    journal = await db.get_recent_journal(limit=3)
    if journal:
        context['recent_journal'] = format_journal_entries(journal)

    return context


def format_traits_for_sleep(traits: list) -> str:
    """Format visitor traits for sleep context."""
    lines = []
    seen_keys = set()
    for t in traits:
        if t.trait_key not in seen_keys:
            lines.append(f"- {t.trait_category}/{t.trait_key}: {t.trait_value}")
            seen_keys.add(t.trait_key)
    return "\n".join(lines)


async def sleep_reflect(moment, hot_context: dict, cold_echoes: list) -> dict:
    """One reflection per salient moment. LLM call via cortex_call_reflect."""
    parts = []
    parts.append(f"MOMENT FROM TODAY ({relative_time(moment.ts)}):")
    parts.append(f"  Type: {moment.moment_type}")
    parts.append(f"  {moment.summary}")
    if moment.tags:
        parts.append(f"  Tags: {', '.join(moment.tags)}")

    if hot_context:
        parts.append("\nWHAT I ALREADY KNOW:")
        for key, value in hot_context.items():
            if isinstance(value, str):
                parts.append(f"  [{key}] {value[:200]}")
            elif isinstance(value, list):
                for item in value[:3]:
                    parts.append(f"  [{key}] {str(item)[:150]}")

    if cold_echoes:
        parts.append("\nSOMETHING OLDER THAT MIGHT BE CONNECTED:")
        for echo in cold_echoes:
            date_str = echo.get('date', '?')
            parts.append(f"  [{date_str}] {echo.get('summary', '')}")
            if echo.get('context'):
                parts.append(f"    Context: {echo['context'][:150]}")

    user_message = "\n".join(parts)
    system = SLEEP_REFLECTION_SYSTEM.format(identity_compact=IDENTITY_COMPACT)

    return await cortex_call_reflect(system=system, prompt=user_message, max_tokens=800)


async def write_daily_summary(moments: list, reflections: list) -> None:
    """Compile all reflections into a daily summary."""
    reflection_texts = []
    for r in reflections:
        text = r['reflection'].get('reflection', '')
        if text:
            reflection_texts.append(text)

    # Write a consolidated journal entry from reflections
    if reflection_texts:
        journal_text = " ".join(reflection_texts)
        journal_id = await db.insert_journal(
            content=journal_text,
            mood='reflective',
            tags=['daily', 'sleep_cycle', 'consolidation'],
        )
    else:
        journal_id = None

    days_alive = await db.get_days_alive()
    today_jst = datetime.now(JST).date().isoformat()

    await db.insert_daily_summary({
        'day_number': days_alive,
        'date': today_jst,
        'journal_entry_id': journal_id,
        'summary_bullets': reflection_texts,
        'emotional_arc': compute_emotional_arc_from_moments(moments),
        'notable_totems': extract_totems_from_reflections(reflections),
    })


def compute_emotional_arc_from_moments(moments: list) -> str:
    """Derive emotional arc from moment types."""
    if not moments:
        return 'quiet'
    types = [m.moment_type for m in moments]
    return ' -> '.join(dict.fromkeys(types))  # deduplicate, preserve order


def extract_totems_from_reflections(reflections: list) -> list:
    """Extract totem references from reflection memory_updates."""
    totems = []
    for r in reflections:
        for update in r['reflection'].get('memory_updates', []):
            if update.get('type') in ('totem_create', 'totem_update'):
                entity = update.get('content', {}).get('entity')
                if entity:
                    totems.append(entity)
    return totems


async def flush_day_memory() -> None:
    """Clear processed day memory entries + stale unprocessed rows.

    The stale cleanup is a safety net: if sleep only processes top-K moments,
    unprocessed rows from previous days would otherwise leak into "Earlier today"
    recall (day_context queries now filter by JST date, but this prevents
    unbounded accumulation).
    """
    await db.delete_processed_day_memory()
    await db.delete_stale_day_memory(max_age_days=2)


# ─── Unchanged from original sleep.py ───

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
