"""db — Shopkeeper database package.

Re-exports all public functions from submodules for backward compatibility.
All existing ``import db`` and ``from db import X`` patterns continue to work
unchanged.
"""

import sys
import types

import aiosqlite  # noqa: F401  — tests patch db.aiosqlite

# ── connection ──
from db.connection import (
    JST,
    SCHEMA,
    add_column_if_missing,
    close_db,
    get_db,
    init_db,
    run_migrations,
    set_db_path,
    transaction,
    _exec_write,
    _write_lock,
)

# ── events ──
from db.events import (
    _row_to_event,
    append_event,
    get_events_since,
    get_events_today,
    get_recent_events,
    inbox_add,
    inbox_flush_stale_visitor_events,
    inbox_get_unread,
    inbox_mark_read,
    update_event_outcome,
)

# ── state ──
from db.state import (
    get_drives_state,
    get_engagement_state,
    get_room_state,
    save_drives_state,
    update_engagement_state,
    update_room_state,
)

# ── memory ──
from db.memory import (
    _jst_today_start_utc,
    _row_to_collection,
    _row_to_daily_summary,
    _row_to_day_memory,
    _row_to_totem,
    _row_to_trait,
    add_visitor_present,
    append_conversation,
    append_self_discovery,
    assign_shelf_slot,
    clear_all_visitors_present,
    consume_chat_token,
    create_chat_token,
    create_visitor,
    delete_processed_day_memory,
    delete_stale_day_memory,
    get_all_active_traits,
    get_all_journal,
    get_all_totems,
    get_cold_embedding_count,
    get_collection_by_location,
    get_conversation_context,
    get_cycle_by_id,
    get_daily_summary_for_today,
    get_day_memory,
    get_day_memory_dashboard,
    get_days_alive,
    get_flashbulb_count_today,
    get_latest_trait,
    get_recent_conversation,
    get_recent_internal_conflicts,
    get_recent_journal,
    get_recent_text_fragments,
    get_self_discoveries,
    get_shelf_assignments,
    get_taste_knowledge,
    get_totems,
    get_trait_history,
    get_unembedded_conversations,
    get_unembedded_monologues,
    get_unprocessed_day_memory,
    get_visitor,
    get_visitor_count_today,
    get_visitor_traits,
    get_visitors_present,
    increment_day_memory_retry,
    increment_visit,
    insert_cold_embedding,
    insert_collection_item,
    insert_daily_summary,
    insert_day_memory,
    insert_journal,
    insert_text_fragment,
    insert_totem,
    insert_trait,
    mark_day_memory_processed,
    mark_session_boundary,
    remove_visitor_present,
    search_collection,
    update_shelf_sprite,
    update_totem,
    update_trait_stability,
    update_trait_status,
    update_visitor,
    update_visitor_present,
    validate_and_consume_chat_token,
    validate_chat_token,
    vector_search_cold_memory,
)

# ── content ──
from db.content import (
    _row_to_pool_item,
    _row_to_thread,
    add_to_content_pool,
    archive_stale_threads,
    cap_unseen_pool,
    create_thread,
    expire_pool_items,
    get_active_threads,
    get_consumption_history,
    get_content_pool_dashboard,
    get_dormant_threads,
    get_enriched_text_for_url,
    get_feed_pipeline_dashboard,
    get_pool_item_by_id,
    get_pool_items,
    get_pool_stats,
    get_thread_by_id,
    get_thread_by_title,
    get_thread_count_by_status,
    get_unseen_news,
    load_arbiter_state,
    save_arbiter_state,
    touch_thread,
    update_pool_item,
)

# ── analytics ──
from db.analytics import (
    count_cycle_logs,
    count_journal_entries,
    create_habit,
    create_inhibition,
    delete_habit,
    delete_inhibition,
    find_matching_habit,
    find_matching_inhibition,
    get_action_capabilities,
    get_action_log,
    get_actions_today,
    get_active_inhibitions,
    get_all_habits,
    get_all_inhibitions,
    get_energy_budget,
    get_executed_action_count_today,
    get_habit_skip_count_today,
    get_habits_for_action,
    get_inhibitions_for_action,
    get_last_creative_cycle,
    get_last_cycle_log,
    get_llm_call_cost_today,
    get_llm_call_count_today,
    get_llm_costs_summary,
    get_llm_daily_costs,
    get_recent_inhibitions,
    get_recent_suppressions,
    get_recent_suppressions_dashboard,
    get_top_habits,
    insert_llm_call_log,
    log_action,
    log_cycle,
    update_habit,
    update_inhibition,
)


# ─── Mutable state proxy ───
# Tests write ``db._db = None`` and ``db.DB_PATH = "..."``. After the split
# these module-level variables live in ``db.connection``, so writes to the
# ``db`` namespace must be forwarded to ``db.connection`` for ``get_db()``
# (which reads ``connection._db``) to see them.

import db.connection as _connection  # noqa: E402

_MUTABLE_STATE = frozenset({
    '_db', 'DB_PATH', '_write_lock', '_tx_depth', 'COLD_SEARCH_ENABLED',
})

# Names that tests may patch on ``db`` via ``patch.object(db, name, ...)``.
# Writes are forwarded to ``db.connection`` so submodules using late-bound
# ``_connection.get_db()`` pick up the mock.
_CONNECTION_PATCHABLE = frozenset({
    'get_db', '_exec_write',
})

_PROXIED = _MUTABLE_STATE | _CONNECTION_PATCHABLE


class _DbModule(types.ModuleType):
    """Module subclass that proxies writes to connection module state."""

    def __setattr__(self, name, value):
        if name in _PROXIED:
            setattr(_connection, name, value)
        super().__setattr__(name, value)

    def __getattr__(self, name):
        if name in _MUTABLE_STATE:
            return getattr(_connection, name)
        raise AttributeError(f"module 'db' has no attribute {name!r}")


# Replace this module in sys.modules with the proxy.
_proxy = _DbModule(__name__)
_proxy.__dict__.update({
    k: v for k, v in globals().items()
    if not k.startswith('__') or k in ('__doc__', '__file__', '__path__',
                                        '__package__', '__spec__')
})
# Remove mutable-state names so reads always fall through to __getattr__,
# which delegates to db.connection — avoids stale values after set_db_path().
for _name in _MUTABLE_STATE:
    _proxy.__dict__.pop(_name, None)
# Preserve package identity
_proxy.__path__ = __path__
_proxy.__file__ = __file__
_proxy.__package__ = __package__
_proxy.__spec__ = __spec__
sys.modules[__name__] = _proxy
