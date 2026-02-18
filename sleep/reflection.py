"""Sleep reflection — LLM call, daily summary, context gathering helpers.

Contains:
- gather_hot_context()    — assemble hot memory for a moment (no LLM)
- format_traits_for_sleep() — visitor trait formatting
- sleep_reflect()         — per-moment LLM reflection call
- write_daily_summary()   — lightweight daily summary index
- compute_emotional_arc_from_moments() — emotional arc derivation
- extract_totems_from_reflections()    — totem extraction from memory_updates
"""

import sys

import clock
import db
from db.parameters import p
from pipeline.cortex import cortex_call_reflect as _cortex_call_reflect  # noqa: F401
from pipeline.cortex import SLEEP_REFLECTION_SYSTEM
from pipeline.hippocampus import (
    compress_visitor, format_totems, format_journal_entries, relative_time,
)
from config.identity import IDENTITY_COMPACT


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

    # Late-bind through package so tests can patch sleep.cortex_call_reflect
    _call = sys.modules['sleep'].cortex_call_reflect
    return await _call(system=system, prompt=user_message, max_tokens=800)


async def write_daily_summary(moments: list, reflections: list,
                              journal_entry_ids: list) -> None:
    """Write a lightweight daily summary index.

    The daily summary is now an index (date, moment count, moment IDs,
    journal entry IDs, emotional arc) — NOT a concatenated narrative.
    Individual reflections are already stored as separate journal entries.
    """
    days_alive = await db.get_days_alive()
    today_jst = clock.now().date().isoformat()
    moment_ids = [m.id for m in moments]

    await db.insert_daily_summary({
        'day_number': days_alive,
        'date': today_jst,
        'moment_count': len(moments),
        'moment_ids': moment_ids,
        'journal_entry_ids': journal_entry_ids,
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
