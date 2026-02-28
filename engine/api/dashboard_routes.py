"""Dashboard HTTP route handlers.

Extracted from heartbeat_server.py (TASK-002). Each handler is an async
function that receives the server instance (for response helpers and
heartbeat access), the StreamWriter, and any request-specific arguments.

All endpoints return identical JSON responses to before extraction.
"""

import asyncio
import hmac
import json
import os
import secrets
import time

import clock
import db

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from api.api_auth import ApiKeyManager


# ─── Token management ───

_dashboard_tokens: dict[str, float] = {}
_DASHBOARD_TOKEN_TTL = 86400  # 24 hours

# Multi-agent mode: API keys can also authenticate dashboard requests.
# Set via set_api_key_manager() during server init.
_api_key_manager: 'ApiKeyManager | None' = None


def set_api_key_manager(manager: 'ApiKeyManager') -> None:
    """Register the API key manager for dashboard auth fallback."""
    global _api_key_manager
    _api_key_manager = manager


def _create_dashboard_token() -> str:
    """Generate session token, store with 24h expiry, prune expired."""
    now = time.time()
    expired = [t for t, exp in _dashboard_tokens.items() if exp < now]
    for t in expired:
        _dashboard_tokens.pop(t, None)
    token = secrets.token_urlsafe(32)
    _dashboard_tokens[token] = now + _DASHBOARD_TOKEN_TTL
    return token


def _check_dashboard_token(token: str) -> bool:
    """Validate token against active set."""
    if not token:
        return False
    expiry = _dashboard_tokens.get(token)
    if expiry is None:
        return False
    if time.time() > expiry:
        _dashboard_tokens.pop(token, None)
        return False
    return True


def check_dashboard_auth(authorization: str) -> bool:
    """Extract Bearer token from Authorization header and validate.

    Accepts either a dashboard session token (from password auth) or a valid
    API key (multi-agent/lounge context where the portal proxies with API keys).
    """
    if not authorization:
        return False
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != 'bearer':
        return False
    token = parts[1]
    # Primary: dashboard session token
    if _check_dashboard_token(token):
        return True
    # Fallback: API key (multi-agent mode — lounge proxy sends API keys)
    if _api_key_manager and _api_key_manager.validate(token) is not None:
        return True
    return False


# ─── Rate limiting ───

_auth_attempts: dict[str, list[float]] = {}
_AUTH_MAX_ATTEMPTS = 10
_AUTH_WINDOW_SECONDS = 300  # 5 minutes


def _check_rate_limit(client_ip: str) -> bool:
    """Return True if request is allowed, False if rate-limited."""
    now = time.time()
    cutoff = now - _AUTH_WINDOW_SECONDS
    attempts = _auth_attempts.get(client_ip, [])
    attempts = [t for t in attempts if t > cutoff]
    _auth_attempts[client_ip] = attempts
    return len(attempts) < _AUTH_MAX_ATTEMPTS


def _record_auth_attempt(client_ip: str) -> None:
    """Record a failed auth attempt for rate limiting."""
    _auth_attempts.setdefault(client_ip, []).append(time.time())


def _reset_auth_attempts(client_ip: str) -> None:
    """Clear rate-limit state after successful auth."""
    _auth_attempts.pop(client_ip, None)


# ─── Route handlers ───


async def handle_auth(server, writer: asyncio.StreamWriter,
                      body_bytes: bytes, client_ip: str):
    """Handle POST /api/dashboard/auth — validate dashboard password."""
    if not _check_rate_limit(client_ip):
        await server._http_json(writer, 429, {
            'error': 'too many attempts, try again later',
        })
        return

    try:
        data = json.loads(body_bytes.decode('utf-8'))
        password = data.get('password', '')
        if not isinstance(password, str):
            await server._http_json(writer, 400, {'error': 'bad request'})
            return
    except (json.JSONDecodeError, UnicodeDecodeError):
        await server._http_json(writer, 400, {'error': 'bad request'})
        return

    expected = os.environ.get('DASHBOARD_PASSWORD')
    if not expected:
        await server._http_json(writer, 503, {
            'error': 'DASHBOARD_PASSWORD not configured',
        })
        return

    if hmac.compare_digest(password, expected):
        _reset_auth_attempts(client_ip)
        token = _create_dashboard_token()
        await server._http_json(writer, 200, {
            'authenticated': True,
            'token': token,
        })
    else:
        _record_auth_attempt(client_ip)
        await server._http_json(writer, 401, {'authenticated': False})


async def handle_vitals(server, writer: asyncio.StreamWriter,
                        authorization: str):
    """Handle GET /api/dashboard/vitals — return vitals panel data."""
    if not check_dashboard_auth(authorization):
        await server._http_json(writer, 401, {'error': 'unauthorized'})
        return
    days_alive = await db.get_days_alive()
    visitor_count_today = await db.get_visitor_count_today()
    cycle_count = await db.get_flashbulb_count_today()
    llm_calls_today = await db.get_llm_call_count_today()
    cost_today = await db.get_llm_call_cost_today()

    await server._http_json(writer, 200, {
        'days_alive': days_alive,
        'visitors_today': visitor_count_today,
        'cycles_today': cycle_count,
        'llm_calls_today': llm_calls_today,
        'cost_today': cost_today,
    })


async def handle_drives(server, writer: asyncio.StreamWriter,
                        authorization: str):
    """Handle GET /api/dashboard/drives — return drives state."""
    if not check_dashboard_auth(authorization):
        await server._http_json(writer, 401, {'error': 'unauthorized'})
        return
    drives = await db.get_drives_state()
    await server._http_json(writer, 200, {
        'social_hunger': drives.social_hunger,
        'curiosity': drives.curiosity,
        'expression_need': drives.expression_need,
        'rest_need': drives.rest_need,
        'energy': drives.energy,
        'mood_valence': drives.mood_valence,
        'mood_arousal': drives.mood_arousal,
        'updated_at': drives.updated_at.isoformat() if drives.updated_at else None,
    })


async def handle_costs(server, writer: asyncio.StreamWriter,
                       authorization: str):
    """Handle GET /api/dashboard/costs — return cost tracking data."""
    if not check_dashboard_auth(authorization):
        await server._http_json(writer, 401, {'error': 'unauthorized'})
        return
    summary = await db.get_llm_costs_summary()
    daily = await db.get_llm_daily_costs(days=30)
    await server._http_json(writer, 200, {
        'summary': summary,
        'daily': daily,
    })


async def handle_threads(server, writer: asyncio.StreamWriter,
                         authorization: str):
    """Handle GET /api/dashboard/threads — return active threads from threads table."""
    if not check_dashboard_auth(authorization):
        await server._http_json(writer, 401, {'error': 'unauthorized'})
        return
    active_threads = await db.get_active_threads(limit=20)
    threads = [{
        'id': t.id,
        'title': t.title,
        'status': t.status,
        'thread_type': t.thread_type,
        'tags': t.tags,
        'touch_count': t.touch_count,
        'last_touched': t.last_touched.isoformat() if t.last_touched else None,
    } for t in active_threads]
    await server._http_json(writer, 200, {'threads': threads})


async def handle_pool(server, writer: asyncio.StreamWriter,
                      authorization: str):
    """Handle GET /api/dashboard/pool — return day memory pool."""
    if not check_dashboard_auth(authorization):
        await server._http_json(writer, 401, {'error': 'unauthorized'})
        return
    moments = await db.get_day_memory_dashboard(limit=20)
    pool = [{
        'id': m.id,
        'summary': m.summary,
        'salience': m.salience,
        'moment_type': m.moment_type,
        'visitor_id': m.visitor_id,
        'ts': m.ts.isoformat(),
    } for m in moments]
    await server._http_json(writer, 200, {'pool': pool})


async def handle_collection(server, writer: asyncio.StreamWriter,
                            authorization: str):
    """Handle GET /api/dashboard/collection — return collection items."""
    if not check_dashboard_auth(authorization):
        await server._http_json(writer, 401, {'error': 'unauthorized'})
        return
    items = await db.search_collection(query='', limit=20)
    collection = [{
        'id': item.id,
        'title': item.title,
        'item_type': item.item_type,
        'location': item.location,
        'origin': item.origin,
        'her_feeling': item.her_feeling,
        'created_at': item.created_at.isoformat() if item.created_at else None,
    } for item in items]
    await server._http_json(writer, 200, {'collection': collection})


async def handle_timeline(server, writer: asyncio.StreamWriter,
                          authorization: str):
    """Handle GET /api/dashboard/timeline — return recent events."""
    if not check_dashboard_auth(authorization):
        await server._http_json(writer, 401, {'error': 'unauthorized'})
        return
    events = await db.get_recent_events(limit=50)
    timeline = [{
        'id': e.id,
        'event_type': e.event_type,
        'source': e.source,
        'ts': e.ts.isoformat(),
        'payload': e.payload,
    } for e in events]
    await server._http_json(writer, 200, {'timeline': timeline})


async def handle_trigger_cycle(server, writer: asyncio.StreamWriter,
                               authorization: str):
    """Handle POST /api/dashboard/controls/cycle — manually trigger a cycle."""
    if not check_dashboard_auth(authorization):
        await server._http_json(writer, 401, {'error': 'unauthorized'})
        return
    await server.heartbeat.schedule_microcycle()
    await server._http_json(writer, 200, {'triggered': True})


async def handle_status(server, writer: asyncio.StreamWriter,
                        authorization: str):
    """Handle GET /api/dashboard/controls/status — return heartbeat status."""
    if not check_dashboard_auth(authorization):
        await server._http_json(writer, 401, {'error': 'unauthorized'})
        return
    engagement = await db.get_engagement_state()
    room = await db.get_room_state()

    # ─── Heartbeat liveness from actual cycle timestamps ───
    # Use operator-configured interval (with 2x headroom for jitter/rest).
    _EXPECTED_INTERVAL = int(server.heartbeat.get_cycle_interval() * 2)
    last_cycle_ts = None
    seconds_since_last_cycle = None
    heartbeat_status = 'inactive'

    conn = await db.get_db()
    cursor = await conn.execute(
        "SELECT ts FROM cycle_log ORDER BY ts DESC LIMIT 1"
    )
    row = await cursor.fetchone()
    if row and row['ts']:
        from datetime import datetime, timezone
        try:
            ts_str = row['ts']
            # Parse ISO format timestamp (stored as UTC)
            if ts_str.endswith('+00:00') or ts_str.endswith('Z'):
                last_cycle_dt = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
            else:
                last_cycle_dt = datetime.fromisoformat(ts_str).replace(tzinfo=timezone.utc)
            last_cycle_ts = ts_str
            now_utc = clock.now_utc()
            seconds_since_last_cycle = (now_utc - last_cycle_dt).total_seconds()

            if seconds_since_last_cycle <= _EXPECTED_INTERVAL:
                heartbeat_status = 'active'
            elif seconds_since_last_cycle <= _EXPECTED_INTERVAL * 3:
                heartbeat_status = 'late'
            else:
                heartbeat_status = 'inactive'
        except (ValueError, TypeError):
            pass  # malformed timestamp — fall through to inactive

    await server._http_json(writer, 200, {
        'heartbeat_active': server.heartbeat.running,
        'heartbeat_status': heartbeat_status,
        'last_cycle_ts': last_cycle_ts,
        'seconds_since_last_cycle': round(seconds_since_last_cycle) if seconds_since_last_cycle is not None else None,
        'expected_interval': _EXPECTED_INTERVAL,
        'cycle_interval': server.heartbeat.get_cycle_interval(),
        'engagement_status': engagement.status,
        'shop_status': room.shop_status,
        'active_visitor': engagement.visitor_id,
    })


async def handle_get_cycle_interval(server, writer: asyncio.StreamWriter,
                                     authorization: str):
    """Handle GET /api/dashboard/controls/cycle-interval — return current interval."""
    if not check_dashboard_auth(authorization):
        await server._http_json(writer, 401, {'error': 'unauthorized'})
        return
    hb = server.heartbeat
    await server._http_json(writer, 200, {
        'interval_seconds': hb.get_cycle_interval(),
        'min': hb.INTERVAL_MIN,
        'max': hb.INTERVAL_MAX,
    })


async def handle_set_cycle_interval(server, writer: asyncio.StreamWriter,
                                     authorization: str, body_bytes: bytes):
    """Handle POST /api/dashboard/controls/cycle-interval — update cycle interval."""
    if not check_dashboard_auth(authorization):
        await server._http_json(writer, 401, {'error': 'unauthorized'})
        return
    try:
        data = json.loads(body_bytes.decode('utf-8'))
        interval = data.get('interval_seconds')
        if not isinstance(interval, (int, float)):
            await server._http_json(writer, 400, {'error': 'interval_seconds must be a number'})
            return
        interval = int(interval)
    except (json.JSONDecodeError, UnicodeDecodeError):
        await server._http_json(writer, 400, {'error': 'bad request'})
        return

    hb = server.heartbeat
    if interval < hb.INTERVAL_MIN or interval > hb.INTERVAL_MAX:
        await server._http_json(writer, 400, {
            'error': f'interval_seconds must be between {hb.INTERVAL_MIN} and {hb.INTERVAL_MAX}',
        })
        return

    actual = hb.set_cycle_interval(interval)
    await server._http_json(writer, 200, {
        'interval_seconds': actual,
        'min': hb.INTERVAL_MIN,
        'max': hb.INTERVAL_MAX,
    })


async def handle_body(server, writer: asyncio.StreamWriter,
                      authorization: str):
    """Handle GET /api/dashboard/body — return body capabilities and budget."""
    if not check_dashboard_auth(authorization):
        await server._http_json(writer, 401, {'error': 'unauthorized'})
        return
    capabilities = await db.get_action_capabilities()
    budget = await db.get_budget_remaining()
    actions_today = await db.get_actions_today()
    await server._http_json(writer, 200, {
        'capabilities': capabilities,
        'budget': budget,
        'actions_today': actions_today,
    })


async def handle_content_pool(server, writer: asyncio.StreamWriter,
                               authorization: str):
    """Handle GET /api/dashboard/content-pool — return content pool overview."""
    if not check_dashboard_auth(authorization):
        await server._http_json(writer, 401, {'error': 'unauthorized'})
        return
    data = await db.get_content_pool_dashboard()
    await server._http_json(writer, 200, data)


async def handle_feed(server, writer: asyncio.StreamWriter,
                       authorization: str):
    """Handle GET /api/dashboard/feed — return feed pipeline health."""
    if not check_dashboard_auth(authorization):
        await server._http_json(writer, 401, {'error': 'unauthorized'})
        return
    data = await db.get_feed_pipeline_dashboard()
    await server._http_json(writer, 200, data)


async def handle_consumption_history(server, writer: asyncio.StreamWriter,
                                      authorization: str):
    """Handle GET /api/dashboard/consumption-history — return consumed content with outcomes."""
    if not check_dashboard_auth(authorization):
        await server._http_json(writer, 401, {'error': 'unauthorized'})
        return
    entries = await db.get_consumption_history(limit=20)
    await server._http_json(writer, 200, {'entries': entries})


async def handle_behavioral(server, writer: asyncio.StreamWriter,
                             authorization: str):
    """Handle GET /api/dashboard/behavioral — return habits, inhibitions, suppressions."""
    if not check_dashboard_auth(authorization):
        await server._http_json(writer, 401, {'error': 'unauthorized'})
        return
    habits = await db.get_top_habits(limit=5)
    inhibitions = await db.get_active_inhibitions()
    suppressions = await db.get_recent_suppressions_dashboard(limit=10, min_impulse=0.5)
    habit_skips_today = await db.get_habit_skip_count_today()
    await server._http_json(writer, 200, {
        'habits': habits,
        'inhibitions': inhibitions,
        'suppressions': suppressions,
        'habit_skips_today': habit_skips_today,
    })


async def handle_get_budget(server, writer: asyncio.StreamWriter,
                             authorization: str):
    """Handle GET /api/dashboard/budget — return real-dollar budget status."""
    if not check_dashboard_auth(authorization):
        await server._http_json(writer, 401, {'error': 'unauthorized'})
        return
    budget = await db.get_budget_remaining()
    await server._http_json(writer, 200, budget)


async def handle_set_budget(server, writer: asyncio.StreamWriter,
                             authorization: str, body_bytes: bytes):
    """Handle POST /api/dashboard/budget — update daily dollar budget."""
    if not check_dashboard_auth(authorization):
        await server._http_json(writer, 401, {'error': 'unauthorized'})
        return
    try:
        data = json.loads(body_bytes.decode('utf-8'))
        daily_budget = data.get('daily_budget')
        if not isinstance(daily_budget, (int, float)) or daily_budget <= 0:
            await server._http_json(writer, 400, {
                'error': 'daily_budget must be a positive number',
            })
            return
    except (json.JSONDecodeError, UnicodeDecodeError):
        await server._http_json(writer, 400, {'error': 'bad request'})
        return

    await db.set_setting('daily_budget', str(round(daily_budget, 2)))
    budget = await db.get_budget_remaining()
    await server._http_json(writer, 200, budget)


async def handle_parameters(server, writer: asyncio.StreamWriter,
                             authorization: str):
    """Handle GET /api/dashboard/parameters — return all self_parameters."""
    if not check_dashboard_auth(authorization):
        await server._http_json(writer, 401, {'error': 'unauthorized'})
        return
    all_params = await db.get_all_params()
    modifications = await db.get_modification_log(limit=20)

    # Group by category
    categories: dict[str, list] = {}
    for param in all_params:
        cat = param.get('category', 'uncategorized')
        categories.setdefault(cat, []).append(param)

    await server._http_json(writer, 200, {
        'categories': categories,
        'recent_modifications': modifications,
        'total_count': len(all_params),
    })


async def handle_set_parameter(server, writer: asyncio.StreamWriter,
                                authorization: str, body_bytes: bytes):
    """Handle POST /api/dashboard/parameters — set or reset a parameter."""
    if not check_dashboard_auth(authorization):
        await server._http_json(writer, 401, {'error': 'unauthorized'})
        return
    try:
        data = json.loads(body_bytes.decode('utf-8'))
        key = data.get('key')
        if not key:
            await server._http_json(writer, 400, {'error': 'key required'})
            return

        if data.get('reset'):
            result = await db.reset_param(key, modified_by='dashboard')
        else:
            value = data.get('value')
            if value is None:
                await server._http_json(writer, 400, {'error': 'value required'})
                return
            reason = data.get('reason', '')
            result = await db.set_param(key, float(value),
                                         modified_by='dashboard', reason=reason)

        await server._http_json(writer, 200, result)
    except ValueError as e:
        await server._http_json(writer, 400, {'error': str(e)})
    except (json.JSONDecodeError, UnicodeDecodeError):
        await server._http_json(writer, 400, {'error': 'bad request'})


# ── X Drafts (TASK-057) ──

async def handle_x_drafts(server, writer: asyncio.StreamWriter,
                          authorization: str):
    """Handle GET /api/dashboard/x-drafts — return X draft queue."""
    if not check_dashboard_auth(authorization):
        await server._http_json(writer, 401, {'error': 'unauthorized'})
        return
    drafts = await db.get_all_drafts(limit=50)
    pending_count = await db.get_pending_count()
    await server._http_json(writer, 200, {
        'drafts': drafts,
        'pending_count': pending_count,
    })


async def handle_approve_x_draft(server, writer: asyncio.StreamWriter,
                                  authorization: str, body_bytes: bytes):
    """Handle POST /api/dashboard/x-drafts/approve — approve and optionally post."""
    if not check_dashboard_auth(authorization):
        await server._http_json(writer, 401, {'error': 'unauthorized'})
        return
    try:
        data = json.loads(body_bytes.decode('utf-8'))
        draft_id = data.get('draft_id', '')
        auto_post = data.get('auto_post', False)
    except (json.JSONDecodeError, UnicodeDecodeError):
        await server._http_json(writer, 400, {'error': 'bad request'})
        return

    if not draft_id:
        await server._http_json(writer, 400, {'error': 'draft_id required'})
        return

    success = await db.approve_draft(draft_id)
    if not success:
        await server._http_json(writer, 404, {'error': 'draft not found or not pending'})
        return

    post_result = None
    if auto_post:
        try:
            from workers.x_poster import post_tweet
            post_result = await post_tweet(draft_id)
        except Exception as e:
            post_result = {'success': False, 'error': str(e)}

    await server._http_json(writer, 200, {
        'approved': True,
        'draft_id': draft_id,
        'post_result': post_result,
    })


async def handle_reject_x_draft(server, writer: asyncio.StreamWriter,
                                 authorization: str, body_bytes: bytes):
    """Handle POST /api/dashboard/x-drafts/reject — reject a draft."""
    if not check_dashboard_auth(authorization):
        await server._http_json(writer, 401, {'error': 'unauthorized'})
        return
    try:
        data = json.loads(body_bytes.decode('utf-8'))
        draft_id = data.get('draft_id', '')
        reason = data.get('reason', '')
    except (json.JSONDecodeError, UnicodeDecodeError):
        await server._http_json(writer, 400, {'error': 'bad request'})
        return

    if not draft_id:
        await server._http_json(writer, 400, {'error': 'draft_id required'})
        return

    success = await db.reject_draft(draft_id, reason)
    if not success:
        await server._http_json(writer, 404, {'error': 'draft not found or not pending'})
        return

    await server._http_json(writer, 200, {
        'rejected': True,
        'draft_id': draft_id,
    })


# ── Dynamic Actions (TASK-056) ──

async def handle_actions(server, writer: asyncio.StreamWriter,
                         authorization: str) -> None:
    """GET /api/dashboard/actions — return dynamic action registry."""
    if not check_dashboard_auth(authorization):
        await server._http_json(writer, 401, {'error': 'unauthorized'})
        return

    all_actions = await db.get_all_dynamic_actions()
    stats = await db.get_action_stats()

    await server._http_json(writer, 200, {
        'actions': all_actions,
        'stats': stats,
    })


async def handle_resolve_action(server, writer: asyncio.StreamWriter,
                                authorization: str, body_bytes: bytes) -> None:
    """POST /api/dashboard/actions/resolve — resolve a pending action."""
    if not check_dashboard_auth(authorization):
        await server._http_json(writer, 401, {'error': 'unauthorized'})
        return

    try:
        data = json.loads(body_bytes.decode('utf-8'))
    except (json.JSONDecodeError, UnicodeDecodeError):
        await server._http_json(writer, 400, {'error': 'invalid JSON'})
        return

    action_name = data.get('action_name')
    status = data.get('status')
    if not action_name or not status:
        await server._http_json(writer, 400, {'error': 'action_name and status required'})
        return

    valid_statuses = {'alias', 'body_state', 'promoted', 'rejected'}
    if status not in valid_statuses:
        await server._http_json(writer, 400, {'error': f'status must be one of {sorted(valid_statuses)}'})
        return

    # Per-status required-field validation
    if status == 'alias' and not data.get('alias_for'):
        await server._http_json(writer, 400, {'error': 'alias_for required when status is alias'})
        return
    if status == 'body_state':
        bs = data.get('body_state')
        if not bs:
            await server._http_json(writer, 400, {'error': 'body_state required when status is body_state'})
            return
        if not isinstance(bs, dict):
            await server._http_json(writer, 400, {'error': 'body_state must be a JSON object'})
            return

    # Verify the action exists before attempting to resolve
    existing = await db.get_dynamic_action(action_name)
    if existing is None:
        await server._http_json(writer, 404, {'error': f'action not found: {action_name}'})
        return

    result = await db.resolve_action(
        action_name, status,
        alias_for=data.get('alias_for'),
        body_state=data.get('body_state'),
        resolved_by='dashboard',
    )
    await server._http_json(writer, 200, result)


# ─── External Actions (TASK-069) ───

async def handle_external_actions(server, writer: asyncio.StreamWriter,
                                   authorization: str):
    """Handle GET /api/dashboard/external-actions — rate limits, channels, recent log."""
    if not check_dashboard_auth(authorization):
        await server._http_json(writer, 401, {'error': 'unauthorized'})
        return

    from body.rate_limiter import (
        get_rate_limit_status, get_all_channel_status, RATE_LIMITS,
    )

    # Rate limit status for each external action
    rate_limits = []
    for action_name in RATE_LIMITS:
        status = await get_rate_limit_status(action_name)
        rate_limits.append(status)

    # Channel status (kill switches)
    channels = await get_all_channel_status()

    # Recent external action log
    import db.connection as _conn
    conn = await _conn.get_db()
    cursor = await conn.execute(
        """SELECT action_name, timestamp, success, channel, error
           FROM external_action_log
           ORDER BY timestamp DESC LIMIT 20"""
    )
    rows = await cursor.fetchall()
    recent_log = [
        {
            'action': row[0],
            'timestamp': row[1],
            'success': bool(row[2]),
            'channel': row[3],
            'error': row[4],
        }
        for row in rows
    ]

    await server._http_json(writer, 200, {
        'rate_limits': rate_limits,
        'channels': channels,
        'recent_log': recent_log,
    })


async def handle_channel_toggle(server, writer: asyncio.StreamWriter,
                                  authorization: str, body_bytes: bytes):
    """Handle POST /api/dashboard/channel-toggle — enable/disable a channel."""
    if not check_dashboard_auth(authorization):
        await server._http_json(writer, 401, {'error': 'unauthorized'})
        return

    try:
        data = json.loads(body_bytes.decode('utf-8'))
        channel_name = data.get('channel', '')
        enabled = data.get('enabled')
    except (json.JSONDecodeError, UnicodeDecodeError):
        await server._http_json(writer, 400, {'error': 'bad request'})
        return

    if not channel_name or enabled is None:
        await server._http_json(writer, 400, {'error': 'channel and enabled required'})
        return

    from body.rate_limiter import set_channel_enabled
    await set_channel_enabled(channel_name, bool(enabled), changed_by='dashboard')

    await server._http_json(writer, 200, {
        'channel': channel_name,
        'enabled': bool(enabled),
    })


# ─── Drift Detection (TASK-062) ───

async def handle_drift(server, writer, authorization):
    """GET /api/dashboard/drift — current drift state."""
    if not check_dashboard_auth(authorization):
        await server._http_json(writer, 401, {'error': 'unauthorized'})
        return
    from identity.drift import get_drift_state
    state = await get_drift_state()
    await server._http_json(writer, 200, state)


# ─── Liveness Metrics (TASK-071) ───

async def handle_metrics(server, writer, authorization):
    """GET /api/dashboard/metrics — current liveness metrics + trends."""
    if not check_dashboard_auth(authorization):
        await server._http_json(writer, 401, {'error': 'unauthorized'})
        return
    from metrics.collector import collect_all, get_metric_trend
    snapshot = await collect_all()
    trends = {}
    for name in ('uptime', 'initiative_rate', 'emotional_range'):
        trends[name] = await get_metric_trend(name, days=30, period='daily')
    await server._http_json(writer, 200, {
        'snapshot': snapshot.to_dict(),
        'trends': trends,
    })


async def handle_metrics_public(server, writer):
    """GET /api/metrics/public — public liveness dashboard (no auth)."""
    from metrics.public import get_public_liveness
    data = await get_public_liveness()
    await server._http_json(writer, 200, data)


async def handle_metrics_backfill(server, writer, authorization):
    """POST /api/dashboard/metrics/backfill — run historical backfill."""
    if not check_dashboard_auth(authorization):
        await server._http_json(writer, 401, {'error': 'unauthorized'})
        return
    from metrics.backfill import backfill_all
    result = await backfill_all()
    await server._http_json(writer, 200, result)


# ─── Meta-Controller (TASK-090) ───


async def handle_meta_controller(server, writer, authorization):
    """GET /api/dashboard/meta-controller — meta-controller status and history."""
    if not check_dashboard_auth(authorization):
        await server._http_json(writer, 401, {'error': 'unauthorized'})
        return

    from alive_config import cfg_section
    mc_config = cfg_section('meta_controller')

    # Fetch recent experiments
    recent = await db.get_recent_experiments(limit=10)

    # Fetch pending experiments count
    pending = await db.get_pending_experiments()

    # Build target status from latest metrics
    targets_status = {}
    targets = mc_config.get('targets', {})
    for target_name, target in targets.items():
        metric_name = target.get('metric')
        if not metric_name:
            continue

        # Get latest metric value
        row = await db.get_latest_metric_value(metric_name)
        current_value = row['value'] if row else None
        status = 'unknown'
        if current_value is not None:
            if current_value < target.get('min', 0):
                status = 'low'
            elif current_value > target.get('max', 1):
                status = 'high'
            else:
                status = 'ok'

        targets_status[target_name] = {
            'min': target.get('min'),
            'max': target.get('max'),
            'metric': metric_name,
            'current': current_value,
            'status': status,
            'last_updated': row['timestamp'] if row else None,
        }

    await server._http_json(writer, 200, {
        'enabled': mc_config.get('enabled', True),
        'targets': targets_status,
        'recent_adjustments': recent,
        'pending_count': len(pending),
        'config': {
            'evaluation_window': mc_config.get('evaluation_window', 50),
            'cooldown_cycles': mc_config.get('cooldown_cycles', 200),
            'max_adjustments_per_sleep': mc_config.get('max_adjustments_per_sleep', 2),
        },
    })


# ─── Experiment History (TASK-091) ───


async def handle_experiment_history(server, writer, authorization):
    """GET /api/dashboard/experiment-history — experiment history with outcomes."""
    if not check_dashboard_auth(authorization):
        await server._http_json(writer, 401, {'error': 'unauthorized'})
        return

    experiments = await db.get_experiment_history(limit=50)
    confidence = await db.get_all_confidence()

    await server._http_json(writer, 200, {
        'experiments': experiments,
        'confidence': confidence,
    })


async def handle_identity_evolution(server, writer, authorization):
    """GET /api/dashboard/identity-evolution — identity evolution status (TASK-092)."""
    if not check_dashboard_auth(authorization):
        await server._http_json(writer, 401, {'error': 'unauthorized'})
        return

    from alive_config import cfg_section
    from sleep.meta_controller import _get_cycle_count

    ie_config = cfg_section('identity_evolution') or {}
    cycle_count = await _get_cycle_count()

    # Active conscious protection windows
    protection_cycles = ie_config.get('conscious_protection_cycles', 500)
    try:
        conscious_mods = await db.get_conscious_modifications(
            window_cycles=protection_cycles,
            cycle_count=cycle_count,
        )
    except Exception:
        conscious_mods = []
    protections = []
    for mod in conscious_mods:
        protections.append({
            'param': mod['param_key'],
            'new_value': mod['new_value'],
            'modified_at': mod['ts'],
        })

    # Recent evolution events from event store
    evolution_events = []
    try:
        conn = await db.connection.get_db()
        cursor = await conn.execute(
            """SELECT payload, ts FROM events
               WHERE event_type = 'identity_evolution'
               ORDER BY ts DESC LIMIT 20"""
        )
        rows = await cursor.fetchall()
        import json as _json
        for row in rows:
            payload = row['payload']
            if isinstance(payload, str):
                try:
                    payload = _json.loads(payload)
                except (ValueError, TypeError):
                    payload = {}
            evolution_events.append({
                'type': payload.get('type', 'unknown'),
                'payload': payload,
                'ts': row['ts'],
            })
    except Exception:
        pass

    # Current drift status
    window = ie_config.get('baseline_shift_window', 1000)
    min_drift = ie_config.get('drift_magnitude_threshold', 0.05)
    try:
        drifted = await db.get_drifted_params(
            window_cycles=window,
            cycle_count=cycle_count,
            min_drift=min_drift,
        )
    except Exception:
        drifted = []

    await server._http_json(writer, 200, {
        'enabled': ie_config.get('enabled', False),
        'config': {
            'conscious_protection_cycles': protection_cycles,
            'baseline_shift_window': window,
            'organic_growth_threshold': ie_config.get('organic_growth_threshold', 0.15),
            'max_updates_per_sleep': ie_config.get('max_updates_per_sleep', 1),
            'protected_traits': ie_config.get('protected_traits', []),
        },
        'conscious_protections': protections,
        'recent_decisions': evolution_events,
        'current_drift': drifted,
        'cycle_count': cycle_count,
    })


# ─── Public Live Dashboard ───

# Action type categories for the live dashboard feed
_ACTION_TYPE_MAP = {
    # social
    'speak': 'social', 'greet': 'social', 'farewell': 'social',
    'end_engagement': 'social', 'decline_gift': 'social',
    # explore
    'browse_web': 'explore', 'browse_content': 'explore', 'read_content': 'explore',
    # express
    'write_journal': 'express', 'journal': 'express',
    'post_x_draft': 'express', 'post_x': 'express',
    'express_thought': 'express', 'modify_self': 'express',
    # maintain
    'rearrange': 'maintain', 'make_tea': 'maintain', 'light_clean': 'maintain',
    'show_item': 'maintain', 'room_delta': 'maintain', 'place_item': 'maintain',
    'open_shop': 'maintain', 'close_shop': 'maintain',
    # inner
    'idle': 'inner', 'sleep': 'inner', 'drift': 'inner', 'nap': 'inner',
    'body': 'inner',
}


async def handle_live_dashboard(server, writer):
    """GET /api/live — public live dashboard (no auth required)."""
    from datetime import datetime, timezone
    conn = await db.get_db()

    # ─── Uptime ───
    cursor = await conn.execute(
        "SELECT MIN(ts) as first, COUNT(*) as total FROM cycle_log"
    )
    row = await cursor.fetchone()
    first_cycle_ts = row['first'] if row and row['first'] else None
    total_cycles = row['total'] if row else 0

    started_at = None
    if first_cycle_ts:
        try:
            dt = datetime.fromisoformat(first_cycle_ts.replace('Z', '+00:00'))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            started_at = dt.isoformat()
        except (ValueError, TypeError):
            pass

    # ─── Drives ───
    drives = await db.get_drives_state()

    # ─── Engagement & Room State ───
    engagement = await db.get_engagement_state()
    room = await db.get_room_state()

    # Status: awake/sleeping based on engagement or mode
    cursor = await conn.execute(
        "SELECT mode FROM cycle_log ORDER BY ts DESC LIMIT 1"
    )
    mode_row = await cursor.fetchone()
    last_mode = mode_row['mode'] if mode_row and mode_row['mode'] else 'ambient'
    if last_mode in ('sleep', 'nap'):
        status = 'sleeping'
    else:
        status = 'awake'

    # ─── Latest Monologue + Body State ───
    last_log = await db.get_last_cycle_log()
    monologue = ''
    expression = 'neutral'
    body_state = 'sitting'
    gaze = 'middle_distance'
    if last_log:
        monologue = last_log.get('internal_monologue') or ''
        expression = last_log.get('expression') or 'neutral'
        body_state = last_log.get('body_state') or 'sitting'
        gaze = last_log.get('gaze') or 'middle_distance'

    # ─── Costs ───
    budget_info = await db.get_budget_remaining()
    cost_summary = await db.get_llm_costs_summary()
    cost_total = cost_summary.get('30d_total', 0.0)

    # ─── Recent Actions (last 10 from events) ───
    recent_events = await db.get_recent_events(limit=50)
    recent_actions = []
    for e in reversed(recent_events):  # newest first
        if e.event_type.startswith('action_'):
            # Derive action name from event_type (e.g. action_speak → speak)
            action_name = e.event_type[len('action_'):]
            detail = ''
            if isinstance(e.payload, dict):
                # Override with payload action if present (e.g. action_room_delta)
                action_name = e.payload.get('action', action_name)
                detail = (e.payload.get('detail', '')
                          or e.payload.get('description', '')
                          or e.payload.get('text', '')
                          or e.payload.get('reason', '')
                          or e.payload.get('draft', ''))
            elif isinstance(e.payload, str):
                detail = e.payload
            ts_str = ''
            if e.ts:
                try:
                    dt = e.ts if isinstance(e.ts, datetime) else datetime.fromisoformat(str(e.ts))
                    # Convert to JST for display
                    from datetime import timedelta
                    jst = dt + timedelta(hours=9) if dt.tzinfo else dt
                    ts_str = jst.strftime('%-I:%M %p')
                except (ValueError, TypeError):
                    ts_str = str(e.ts)
            action_type = _ACTION_TYPE_MAP.get(action_name, 'inner')
            recent_actions.append({
                'time': ts_str,
                'action': action_name,
                'detail': detail,
                'type': action_type,
            })
            if len(recent_actions) >= 10:
                break

    # If no action_taken events, try cycle_log actions field
    if not recent_actions:
        cursor = await conn.execute(
            """SELECT ts, actions FROM cycle_log
               WHERE actions IS NOT NULL AND actions != '[]'
               ORDER BY ts DESC LIMIT 10"""
        )
        rows = await cursor.fetchall()
        for row in rows:
            try:
                actions_list = json.loads(row['actions']) if row['actions'] else []
                ts_str = ''
                if row['ts']:
                    dt = datetime.fromisoformat(row['ts'].replace('Z', '+00:00'))
                    from datetime import timedelta
                    jst = dt + timedelta(hours=9)
                    ts_str = jst.strftime('%-I:%M %p')
                for act in actions_list:
                    act_name = act if isinstance(act, str) else (act.get('action', '') if isinstance(act, dict) else '')
                    act_detail = act.get('detail', '') if isinstance(act, dict) else ''
                    recent_actions.append({
                        'time': ts_str,
                        'action': act_name,
                        'detail': act_detail,
                        'type': _ACTION_TYPE_MAP.get(act_name, 'inner'),
                    })
            except (json.JSONDecodeError, TypeError):
                continue

    # ─── Active Threads ───
    active_threads = await db.get_active_threads(limit=10)
    threads = []
    for t in active_threads:
        age = ''
        if t.last_touched:
            now = clock.now_utc()
            last = t.last_touched if t.last_touched.tzinfo else t.last_touched.replace(tzinfo=timezone.utc)
            delta = now - last
            if delta.days > 0:
                age = f'{delta.days}d'
            else:
                hours = delta.seconds // 3600
                age = f'{hours}h' if hours > 0 else f'{delta.seconds // 60}m'
        threads.append({
            'title': t.title,
            'type': t.thread_type or 'thought',
            'age': age,
            'priority': round(t.touch_count / max(1, t.touch_count + 3), 2),
        })

    # ─── Memory Stats ───
    cursor = await conn.execute("SELECT COUNT(*) as cnt FROM visitors")
    row = await cursor.fetchone()
    total_impressions = row['cnt'] if row else 0

    cursor = await conn.execute("SELECT COUNT(*) as cnt FROM visitor_traits")
    row = await cursor.fetchone()
    total_traits = row['cnt'] if row else 0

    cursor = await conn.execute("SELECT COUNT(*) as cnt FROM totems")
    row = await cursor.fetchone()
    totems_count = row['cnt'] if row else 0

    cursor = await conn.execute(
        "SELECT COUNT(*) as cnt FROM journal_entries "
        "WHERE tags LIKE '%identity%' OR tags LIKE '%self_discovery%'"
    )
    row = await cursor.fetchone()
    self_discoveries_count = row['cnt'] if row else 0

    journals_count = await db.count_journal_entries()

    # ─── Inhibitions ───
    inhibitions_raw = await db.get_active_inhibitions()
    inhibitions = [inh.get('context', inh.get('action', '')) for inh in inhibitions_raw]

    # ─── Last Sleep ───
    cursor = await conn.execute(
        """SELECT created_at, emotional_arc, summary_bullets FROM daily_summaries
           ORDER BY created_at DESC LIMIT 1"""
    )
    sleep_row = await cursor.fetchone()
    last_sleep = None
    if sleep_row and sleep_row['created_at']:
        try:
            sleep_dt = datetime.fromisoformat(sleep_row['created_at'].replace('Z', '+00:00'))
            if sleep_dt.tzinfo is None:
                sleep_dt = sleep_dt.replace(tzinfo=timezone.utc)
            hours_ago = (clock.now_utc() - sleep_dt).total_seconds() / 3600
            import json as _json
            bullets = _json.loads(sleep_row['summary_bullets']) if sleep_row['summary_bullets'] else {}
            last_sleep = {
                'hoursAgo': round(hours_ago, 1),
                'emotionalArc': sleep_row['emotional_arc'] or '',
                'momentCount': bullets.get('moment_count', 0),
            }
        except (ValueError, TypeError):
            pass

    # ─── Visitors ───
    visitors_today = await db.get_visitor_count_today()
    cursor = await conn.execute(
        "SELECT COUNT(DISTINCT source) as cnt FROM events WHERE event_type = 'visitor_connect'"
    )
    row = await cursor.fetchone()
    total_visitors = row['cnt'] if row else 0

    cursor = await conn.execute(
        """SELECT COUNT(DISTINCT v.id) as cnt FROM visitors v
           WHERE v.visit_count > 1"""
    )
    row = await cursor.fetchone()
    returning_visitors = row['cnt'] if row else 0

    currently_present = 1 if engagement.status == 'engaged' else 0

    # ─── Assemble response ───
    await server._http_json(writer, 200, {
        'uptime': {
            'started_at': started_at,
            'totalCycles': total_cycles,
        },
        'status': status,
        'expression': expression,
        'bodyState': body_state,
        'gaze': gaze,
        'shopOpen': room.shop_status == 'open',
        'timeOfDay': room.time_of_day or 'afternoon',
        'budget': {
            'spent': round(budget_info['spent'], 4),
            'cap': round(budget_info['budget'], 2),
            'remaining': round(budget_info['remaining'], 4),
        },
        'cost30d': round(cost_total, 2),
        'drives': {
            'social_hunger': drives.social_hunger,
            'curiosity': drives.curiosity,
            'expression_need': drives.expression_need,
            'rest_need': drives.rest_need,
            'energy': drives.energy,
            'mood_valence': drives.mood_valence,
            'mood_arousal': drives.mood_arousal,
        },
        'recentActions': recent_actions[:10],
        'threads': threads,
        'memory': {
            'totalImpressions': total_impressions,
            'totalTraits': total_traits,
            'totems': totems_count,
            'selfDiscoveries': self_discoveries_count,
            'journals': journals_count,
        },
        'inhibitions': inhibitions,
        'lastSleep': last_sleep,
        'visitors': {
            'today': visitors_today,
            'total': total_visitors,
            'returning': returning_visitors,
            'currentlyPresent': currently_present,
        },
        'monologue': monologue,
    })


# ── TASK-095 v2: Force Sleep, Whispers, Memories, Capabilities ──

async def handle_force_sleep(server, writer: asyncio.StreamWriter,
                             authorization: str):
    """Handle POST /api/dashboard/force-sleep — trigger sleep cycle.

    If not engaged: runs sleep immediately, returns results.
    If engaged: queues sleep for after engagement ends.
    """
    if not check_dashboard_auth(authorization):
        await server._http_json(writer, 401, {'error': 'unauthorized'})
        return

    engagement = await db.get_engagement_state()
    if engagement.status == 'engaged':
        # Queue sleep for after conversation
        server.heartbeat._sleep_queued = True
        await server._http_json(writer, 200, {
            'queued': True,
            'reason': 'in conversation',
            'message': 'Will rest after current conversation.',
        })
        return

    # Not engaged — run immediately
    try:
        from sleep import sleep_cycle
        from sleep.whisper import process_whispers
        whispers = await db.get_pending_whispers()
        ran = await sleep_cycle()
        if ran >= 0:
            server.heartbeat._last_sleep_date = clock.now().strftime('%Y-%m-%d')
        await server._http_json(writer, 200, {
            'queued': False,
            'processed': ran,
            'whispers_applied': len(whispers),
        })
    except Exception as e:
        await server._http_json(writer, 500, {'error': f'sleep failed: {e}'})


async def handle_get_whispers(server, writer: asyncio.StreamWriter,
                              authorization: str):
    """Handle GET /api/dashboard/whispers — list pending whispers."""
    if not check_dashboard_auth(authorization):
        await server._http_json(writer, 401, {'error': 'unauthorized'})
        return

    pending = await db.get_pending_whispers()
    await server._http_json(writer, 200, {'whispers': pending})


async def handle_create_whisper(server, writer: asyncio.StreamWriter,
                                authorization: str, body_bytes: bytes):
    """Handle POST /api/dashboard/whispers — create a pending whisper."""
    if not check_dashboard_auth(authorization):
        await server._http_json(writer, 401, {'error': 'unauthorized'})
        return

    try:
        body = json.loads(body_bytes)
    except (json.JSONDecodeError, ValueError):
        await server._http_json(writer, 400, {'error': 'invalid JSON'})
        return

    param_path = body.get('param_path', '').strip()
    new_value = body.get('new_value')
    if not param_path or new_value is None:
        await server._http_json(writer, 400, {
            'error': 'param_path and new_value required',
        })
        return

    # Look up current value for perception generation
    try:
        from db.parameters import p_or
        old_value = str(p_or(param_path, 0.0))
    except Exception:
        old_value = None

    whisper_id = await db.create_whisper(
        param_path=param_path,
        old_value=old_value,
        new_value=str(new_value),
    )
    await server._http_json(writer, 200, {
        'whisper_id': whisper_id,
        'param_path': param_path,
        'old_value': old_value,
        'new_value': str(new_value),
    })


async def handle_get_memories(server, writer: asyncio.StreamWriter,
                              authorization: str):
    """Handle GET /api/dashboard/memories — list memories by origin."""
    if not check_dashboard_auth(authorization):
        await server._http_json(writer, 401, {'error': 'unauthorized'})
        return

    # Default: both origins
    manager = await db.get_manager_memories()
    organic = await db.get_organic_memories(limit=50)
    await server._http_json(writer, 200, {
        'backstory': manager,
        'organic': organic,
    })


async def handle_inject_memory(server, writer: asyncio.StreamWriter,
                               authorization: str, body_bytes: bytes):
    """Handle POST /api/dashboard/memories — inject backstory memory."""
    if not check_dashboard_auth(authorization):
        await server._http_json(writer, 401, {'error': 'unauthorized'})
        return

    try:
        body = json.loads(body_bytes)
    except (json.JSONDecodeError, ValueError):
        await server._http_json(writer, 400, {'error': 'invalid JSON'})
        return

    text = body.get('text', '').strip()
    title = body.get('title', '').strip()
    if not text:
        await server._http_json(writer, 400, {'error': 'text required'})
        return

    source_id = await db.inject_manager_memory(text=text, title=title)
    await server._http_json(writer, 200, {
        'source_id': source_id,
        'title': title,
        'text': text,
        'origin': 'manager_injected',
    })


async def handle_delete_memory(server, writer: asyncio.StreamWriter,
                               authorization: str, body_bytes: bytes):
    """Handle DELETE /api/dashboard/memories — delete a backstory memory."""
    if not check_dashboard_auth(authorization):
        await server._http_json(writer, 401, {'error': 'unauthorized'})
        return

    try:
        body = json.loads(body_bytes)
    except (json.JSONDecodeError, ValueError):
        await server._http_json(writer, 400, {'error': 'invalid JSON'})
        return

    source_id = body.get('source_id', '').strip()
    if not source_id:
        await server._http_json(writer, 400, {'error': 'source_id required'})
        return

    deleted = await db.delete_manager_memory(source_id)
    if deleted:
        await server._http_json(writer, 200, {'deleted': True, 'source_id': source_id})
    else:
        await server._http_json(writer, 404, {
            'error': 'not found or not deletable (organic memories cannot be deleted)',
        })


async def handle_get_capabilities(server, writer: asyncio.StreamWriter,
                                  authorization: str):
    """Handle GET /api/dashboard/capabilities — list actions with enabled state."""
    if not check_dashboard_auth(authorization):
        await server._http_json(writer, 401, {'error': 'unauthorized'})
        return

    from pipeline.action_registry import ACTION_REGISTRY
    identity = server.heartbeat._identity

    capabilities = []
    for name, cap in ACTION_REGISTRY.items():
        # MCP actions managed via /mcp/* endpoints, not /capabilities
        if name.startswith('mcp_'):
            continue
        # Determine if action is enabled based on identity's actions_enabled
        if identity.actions_enabled is None:
            enabled = cap.enabled  # Fall back to registry default
        elif not identity.actions_enabled:
            enabled = False  # Empty list = all blocked
        else:
            enabled = name in identity.actions_enabled

        capabilities.append({
            'name': name,
            'description': cap.description,
            'energy_cost': getattr(cap, 'energy_cost', 0.0),
            'enabled': enabled,
        })

    await server._http_json(writer, 200, {'capabilities': capabilities})


async def handle_toggle_capability(server, writer: asyncio.StreamWriter,
                                    authorization: str, body_bytes: bytes):
    """Handle POST /api/dashboard/capabilities — toggle action enabled/disabled.

    Updates identity.yaml on disk and reloads the frozen AgentIdentity.
    """
    if not check_dashboard_auth(authorization):
        await server._http_json(writer, 401, {'error': 'unauthorized'})
        return

    try:
        body = json.loads(body_bytes)
    except (json.JSONDecodeError, ValueError):
        await server._http_json(writer, 400, {'error': 'invalid JSON'})
        return

    action_name = body.get('action', '').strip()
    enabled = body.get('enabled')
    if not action_name or enabled is None:
        await server._http_json(writer, 400, {
            'error': 'action and enabled required',
        })
        return

    # Guard: MCP actions must be toggled via /mcp endpoints, not /capabilities
    if action_name.startswith('mcp_'):
        await server._http_json(writer, 400, {
            'error': 'Use /mcp/:id or /mcp/:id/tools/:suffix to toggle MCP actions',
        })
        return

    from pipeline.action_registry import ACTION_REGISTRY
    if action_name not in ACTION_REGISTRY:
        await server._http_json(writer, 404, {
            'error': f'unknown action: {action_name}',
        })
        return

    identity = server.heartbeat._identity

    # Build updated actions list
    if identity.actions_enabled is None:
        # Was None (all allowed) — switch to explicit list, respecting
        # each capability's default enabled state from the registry
        current_enabled = [name for name, cap in ACTION_REGISTRY.items() if cap.enabled]
    else:
        current_enabled = list(identity.actions_enabled)

    if enabled and action_name not in current_enabled:
        current_enabled.append(action_name)
    elif not enabled and action_name in current_enabled:
        current_enabled.remove(action_name)

    # Persist: update identity.yaml on disk and reload frozen identity
    _persist_actions_enabled(server, current_enabled)

    await server._http_json(writer, 200, {
        'action': action_name,
        'enabled': bool(enabled),
        'actions_enabled': current_enabled,
    })


async def handle_delete_memory_by_id(server, writer: asyncio.StreamWriter,
                                      authorization: str, source_id: str):
    """Handle DELETE /api/dashboard/memories/:id — delete backstory by path param."""
    if not check_dashboard_auth(authorization):
        await server._http_json(writer, 401, {'error': 'unauthorized'})
        return

    if not source_id:
        await server._http_json(writer, 400, {'error': 'source_id required'})
        return

    deleted = await db.delete_manager_memory(source_id)
    if deleted:
        await server._http_json(writer, 200, {'deleted': True, 'source_id': source_id})
    else:
        await server._http_json(writer, 404, {
            'error': 'not found or not deletable (organic memories cannot be deleted)',
        })


# ─── TASK-095 v3.1 Batch 1: Inner Voice, Feed Drops, Streams ───

async def handle_inner_voice(server, writer: asyncio.StreamWriter,
                             authorization: str, query_params: dict):
    """Handle GET /api/dashboard/inner-voice — recent internal monologue entries."""
    if not check_dashboard_auth(authorization):
        await server._http_json(writer, 401, {'error': 'unauthorized'})
        return

    try:
        limit = max(1, min(int(query_params.get('limit', ['20'])[0]), 100))
    except (ValueError, TypeError):
        await server._http_json(writer, 400, {'error': 'invalid limit'})
        return
    before = query_params.get('before', [None])[0]

    entries = await db.get_inner_voice_history(limit=limit, before=before)
    await server._http_json(writer, 200, entries)


async def handle_feed_drop(server, writer: asyncio.StreamWriter,
                           authorization: str, body_bytes: bytes):
    """Handle POST /api/dashboard/feed/drop — manager drops content into the feed."""
    if not check_dashboard_auth(authorization):
        await server._http_json(writer, 401, {'error': 'unauthorized'})
        return

    try:
        body = json.loads(body_bytes)
    except (json.JSONDecodeError, ValueError):
        await server._http_json(writer, 400, {'error': 'invalid json'})
        return

    title = body.get('title', '').strip()
    url = body.get('url', '').strip()
    text = body.get('text', '').strip()

    if not url and not text:
        await server._http_json(writer, 400, {'error': 'url or text required'})
        return

    content = url or text
    source_type = 'manager_drop'

    from feed_ingester import compute_pool_fingerprint
    fingerprint = compute_pool_fingerprint('manager', source_type, content)

    inserted = await db.add_to_content_pool(
        fingerprint=fingerprint,
        source_type=source_type,
        source_channel='manager',
        content=content,
        title=title or content[:80],
        salience_base=0.8,
    )

    if inserted:
        await server._http_json(writer, 200, {
            'inserted': True,
            'title': title or content[:80],
            'content': content,
        })
    else:
        await server._http_json(writer, 200, {
            'inserted': False,
            'reason': 'duplicate (already in pool)',
        })


async def handle_feed_drops_list(server, writer: asyncio.StreamWriter,
                                  authorization: str, query_params: dict):
    """Handle GET /api/dashboard/feed/drops — list manager-dropped content."""
    if not check_dashboard_auth(authorization):
        await server._http_json(writer, 401, {'error': 'unauthorized'})
        return

    try:
        limit = max(1, min(int(query_params.get('limit', ['50'])[0]), 200))
    except (ValueError, TypeError):
        await server._http_json(writer, 400, {'error': 'invalid limit'})
        return

    drops = await db.get_manager_drops(limit=limit)
    await server._http_json(writer, 200, drops)


async def handle_feed_streams_list(server, writer: asyncio.StreamWriter,
                                    authorization: str):
    """Handle GET /api/dashboard/feed/streams — list configured RSS feeds."""
    if not check_dashboard_auth(authorization):
        await server._http_json(writer, 401, {'error': 'unauthorized'})
        return

    feeds = await db.get_agent_feeds()
    await server._http_json(writer, 200, feeds)


async def handle_feed_streams_create(server, writer: asyncio.StreamWriter,
                                      authorization: str, body_bytes: bytes):
    """Handle POST /api/dashboard/feed/streams — add a new RSS feed."""
    if not check_dashboard_auth(authorization):
        await server._http_json(writer, 401, {'error': 'unauthorized'})
        return

    try:
        body = json.loads(body_bytes)
    except (json.JSONDecodeError, ValueError):
        await server._http_json(writer, 400, {'error': 'invalid json'})
        return

    url = body.get('url', '').strip()
    if not url:
        await server._http_json(writer, 400, {'error': 'url required'})
        return

    label = body.get('label', '').strip() or None
    try:
        poll_interval = max(1, int(body.get('poll_interval_minutes', 60)))
    except (ValueError, TypeError):
        await server._http_json(writer, 400, {'error': 'invalid poll_interval_minutes'})
        return

    try:
        feed_id = await db.create_agent_feed(url=url, label=label,
                                              poll_interval=poll_interval)
        await server._http_json(writer, 200, {
            'id': feed_id,
            'url': url,
            'label': label,
            'active': True,
        })
    except Exception as e:
        if 'UNIQUE' in str(e):
            await server._http_json(writer, 409, {'error': 'feed URL already exists'})
        else:
            await server._http_json(writer, 500, {'error': str(e)})


async def handle_feed_streams_update(server, writer: asyncio.StreamWriter,
                                      authorization: str, body_bytes: bytes,
                                      feed_id: int):
    """Handle PATCH /api/dashboard/feed/streams/:id — toggle active, update label."""
    if not check_dashboard_auth(authorization):
        await server._http_json(writer, 401, {'error': 'unauthorized'})
        return

    try:
        body = json.loads(body_bytes)
    except (json.JSONDecodeError, ValueError):
        await server._http_json(writer, 400, {'error': 'invalid json'})
        return

    updates = {}
    if 'active' in body:
        updates['active'] = 1 if body['active'] else 0
    if 'label' in body:
        updates['label'] = body['label']
    if 'poll_interval_minutes' in body:
        try:
            updates['poll_interval_minutes'] = max(1, int(body['poll_interval_minutes']))
        except (ValueError, TypeError):
            await server._http_json(writer, 400, {'error': 'invalid poll_interval_minutes'})
            return

    if not updates:
        await server._http_json(writer, 400, {'error': 'no fields to update'})
        return

    rows_changed = await db.update_agent_feed(feed_id, **updates)
    if rows_changed == 0:
        await server._http_json(writer, 404, {'error': 'feed not found'})
    else:
        await server._http_json(writer, 200, {'updated': True, 'id': feed_id})


async def handle_feed_streams_delete(server, writer: asyncio.StreamWriter,
                                      authorization: str, feed_id: int):
    """Handle DELETE /api/dashboard/feed/streams/:id — remove an RSS feed."""
    if not check_dashboard_auth(authorization):
        await server._http_json(writer, 401, {'error': 'unauthorized'})
        return

    deleted = await db.delete_agent_feed(feed_id)
    if deleted:
        await server._http_json(writer, 200, {'deleted': True, 'id': feed_id})
    else:
        await server._http_json(writer, 404, {'error': 'feed not found'})


# ─── TASK-095 v3.1 Batch 3: MCP Server Management ───

async def handle_mcp_servers_list(server, writer: asyncio.StreamWriter,
                                  authorization: str):
    """Handle GET /api/dashboard/mcp/servers — list all MCP servers."""
    if not check_dashboard_auth(authorization):
        await server._http_json(writer, 401, {'error': 'unauthorized'})
        return

    servers = await db.get_mcp_servers()
    result = []
    for srv in servers:
        usage_counts = await db.get_mcp_tool_usage_counts(srv['id'])
        tools = []
        for tool in srv.get('discovered_tools', []):
            tools.append({
                'name': tool.get('name', ''),
                'description': tool.get('description', ''),
                'enabled': bool(tool.get('enabled', True)),
                'action_suffix': tool.get('action_suffix', ''),
                'usage_count': usage_counts.get(tool.get('name', ''), 0),
            })
        result.append({
            'id': srv['id'],
            'name': srv['name'],
            'url': srv['url'],
            'enabled': bool(srv['enabled']),
            'connected_at': srv['connected_at'],
            'tools': tools,
        })

    await server._http_json(writer, 200, result)


async def handle_mcp_connect(server, writer: asyncio.StreamWriter,
                             authorization: str, body_bytes: bytes):
    """Handle POST /api/dashboard/mcp/connect — connect to an MCP server.

    Idempotent by URL: if server already registered, reconnect (re-discover tools).
    actions_enabled YAML sync happens here, not in the registry.
    """
    if not check_dashboard_auth(authorization):
        await server._http_json(writer, 401, {'error': 'unauthorized'})
        return

    try:
        body = json.loads(body_bytes)
    except (json.JSONDecodeError, ValueError):
        await server._http_json(writer, 400, {'error': 'invalid JSON'})
        return

    url = (body.get('url') or '').strip()
    name = (body.get('name') or '').strip()
    if not url:
        await server._http_json(writer, 400, {'error': 'url required'})
        return

    # Discover tools from the MCP server
    from body.mcp_registry import get_client, compute_action_suffixes, \
        merge_action_suffixes, unregister_server, register_server

    client = get_client()
    try:
        server_info = await client.connect(url)
    except Exception as e:
        await server._http_json(writer, 502, {
            'error': f'Failed to connect to MCP server: {e}',
        })
        return

    if not name:
        name = server_info.name

    # Idempotent: check if server URL already registered
    existing = await db.get_mcp_server_by_url(url)
    if existing:
        server_id = existing['id']
        # Reconnect: merge with existing suffixes to preserve tool identity
        old_tools = existing.get('discovered_tools', [])
        tools_data, warnings = merge_action_suffixes(server_info.tools, old_tools)
        tools_json = json.dumps(tools_data)
        await db.update_mcp_server(server_id,
                                   name=name,
                                   enabled=1,
                                   discovered_tools=tools_json)
        # Re-register: clear stale → inject fresh
        # MUST prune old mcp_{id}_* names from actions_enabled first
        removed = unregister_server(server_id)
        if removed:
            _sync_actions_enabled_remove(server, removed)
    else:
        # First connect: compute suffixes from scratch
        tools_data, warnings = compute_action_suffixes(server_info.tools)
        tools_json = json.dumps(tools_data)
        server_id = await db.create_mcp_server(name, url, tools_json)

    # Register in runtime ACTION_REGISTRY
    srv_data = await db.get_mcp_server(server_id)
    registered = register_server(server_id, srv_data)

    # Sync actions_enabled in identity YAML
    _sync_actions_enabled_add(server, registered)

    tools_response = []
    for tool in tools_data:
        tools_response.append({
            'name': tool.get('name', ''),
            'description': tool.get('description', ''),
            'enabled': bool(tool.get('enabled', True)),
            'action_suffix': tool.get('action_suffix', ''),
        })

    await server._http_json(writer, 200, {
        'id': server_id,
        'name': name,
        'url': url,
        'tools': tools_response,
        'warnings': warnings,
    })


async def handle_mcp_server_toggle(server, writer: asyncio.StreamWriter,
                                    authorization: str, body_bytes: bytes,
                                    server_id: int):
    """Handle PATCH /api/dashboard/mcp/:id — toggle server enabled/disabled."""
    if not check_dashboard_auth(authorization):
        await server._http_json(writer, 401, {'error': 'unauthorized'})
        return

    try:
        body = json.loads(body_bytes)
    except (json.JSONDecodeError, ValueError):
        await server._http_json(writer, 400, {'error': 'invalid JSON'})
        return

    enabled = body.get('enabled')
    if enabled is None:
        await server._http_json(writer, 400, {'error': 'enabled required'})
        return

    srv = await db.get_mcp_server(server_id)
    if not srv:
        await server._http_json(writer, 404, {'error': 'server not found'})
        return

    from body.mcp_registry import unregister_server, register_server

    await db.update_mcp_server(server_id, enabled=1 if enabled else 0)

    if not enabled:
        removed = unregister_server(server_id)
        _sync_actions_enabled_remove(server, removed)
    else:
        # Re-fetch after DB update and register
        srv = await db.get_mcp_server(server_id)
        registered = register_server(server_id, srv)
        _sync_actions_enabled_add(server, registered)

    await server._http_json(writer, 200, {
        'id': server_id,
        'enabled': bool(enabled),
    })


async def handle_mcp_server_delete(server, writer: asyncio.StreamWriter,
                                    authorization: str, server_id: int):
    """Handle DELETE /api/dashboard/mcp/:id — remove an MCP server.

    DB-first: delete from DB (cascade usage), then unregister from runtime.
    """
    if not check_dashboard_auth(authorization):
        await server._http_json(writer, 401, {'error': 'unauthorized'})
        return

    srv = await db.get_mcp_server(server_id)
    if not srv:
        await server._http_json(writer, 404, {'error': 'server not found'})
        return

    from body.mcp_registry import unregister_server

    # DB-first: durable state updated before runtime mutation
    await db.delete_mcp_server(server_id)
    removed = unregister_server(server_id)
    _sync_actions_enabled_remove(server, removed)

    await server._http_json(writer, 200, {'deleted': True, 'id': server_id})


async def handle_mcp_tool_toggle(server, writer: asyncio.StreamWriter,
                                  authorization: str, body_bytes: bytes,
                                  server_id: int, tool_suffix: str):
    """Handle PATCH /api/dashboard/mcp/:id/tools/:suffix — toggle tool."""
    if not check_dashboard_auth(authorization):
        await server._http_json(writer, 401, {'error': 'unauthorized'})
        return

    try:
        body = json.loads(body_bytes)
    except (json.JSONDecodeError, ValueError):
        await server._http_json(writer, 400, {'error': 'invalid JSON'})
        return

    enabled = body.get('enabled')
    if enabled is None:
        await server._http_json(writer, 400, {'error': 'enabled required'})
        return

    from body.mcp_registry import get_tool_by_suffix, suffix_to_action_name
    from pipeline.action_registry import ACTION_REGISTRY

    # Validate server exists
    srv = await db.get_mcp_server(server_id)
    if not srv:
        await server._http_json(writer, 404, {'error': 'server not found'})
        return

    # Validate tool exists
    tool = get_tool_by_suffix(server_id, tool_suffix)
    if not tool:
        # Cache miss — try reloading from DB
        from body.mcp_registry import register_server
        register_server(server_id, srv)
        tool = get_tool_by_suffix(server_id, tool_suffix)
        if not tool:
            await server._http_json(writer, 404, {'error': 'tool not found'})
            return

    # Guard: can't enable a tool if parent server is disabled
    if enabled and not srv.get('enabled', 1):
        await server._http_json(writer, 409, {
            'error': 'Cannot enable tool: parent server is disabled',
        })
        return

    # Update DB
    await db.update_mcp_tool_enabled(server_id, tool_suffix, bool(enabled))

    action_name = suffix_to_action_name(server_id, tool_suffix)

    if not enabled:
        # Remove from ACTION_REGISTRY + actions_enabled
        ACTION_REGISTRY.pop(action_name, None)
        _sync_actions_enabled_remove(server, [action_name])
    else:
        # Add to ACTION_REGISTRY + actions_enabled
        from pipeline.action_registry import ActionCapability
        ACTION_REGISTRY[action_name] = ActionCapability(
            name=action_name,
            enabled=True,
            cooldown_seconds=0,
            description=tool['description'],
        )
        _sync_actions_enabled_add(server, [action_name])

    await server._http_json(writer, 200, {
        'server_id': server_id,
        'tool_suffix': tool_suffix,
        'enabled': bool(enabled),
        'action_name': action_name,
    })


def _sync_actions_enabled_add(server, action_names: list[str]) -> None:
    """Add MCP action names to identity's actions_enabled and persist."""
    if not action_names:
        return
    identity = server.heartbeat._identity
    if identity.actions_enabled is None:
        return  # None means "all allowed" — no explicit list to update
    current = list(identity.actions_enabled)
    for name in action_names:
        if name not in current:
            current.append(name)
    _persist_actions_enabled(server, current)


def _sync_actions_enabled_remove(server, action_names: list[str]) -> None:
    """Remove MCP action names from identity's actions_enabled and persist."""
    if not action_names:
        return
    identity = server.heartbeat._identity
    if identity.actions_enabled is None:
        return  # None means "all allowed" — no explicit list to update
    current = [n for n in identity.actions_enabled if n not in action_names]
    _persist_actions_enabled(server, current)


def _persist_actions_enabled(server, current_enabled: list[str]) -> None:
    """Write actions_enabled to identity YAML and reload frozen identity.

    Only writes to disk when an agent config dir is set (multi-agent mode).
    For default Shopkeeper (no config dir), updates in-memory only.
    """
    import yaml
    import os
    config_dir = server._agent_config_dir
    if not config_dir:
        # Default Shopkeeper: update in-memory only, don't touch default_identity.yaml
        identity = server.heartbeat._identity
        try:
            import dataclasses
            server.heartbeat._identity = dataclasses.replace(
                identity, actions_enabled=current_enabled
            )
        except TypeError:
            # Frozen dataclass replacement failed — set directly (test mocks)
            identity.actions_enabled = current_enabled
        return

    identity_path = os.path.join(config_dir, 'identity.yaml')

    try:
        with open(identity_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}
        data['actions_enabled'] = current_enabled
        with open(identity_path, 'w', encoding='utf-8') as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True)

        from config.agent_identity import AgentIdentity
        server.heartbeat._identity = AgentIdentity.from_yaml(identity_path)
    except Exception as e:
        print(f"  [MCP] Failed to persist actions_enabled: {e}")
