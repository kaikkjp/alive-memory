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


# ─── Token management ───

_dashboard_tokens: dict[str, float] = {}
_DASHBOARD_TOKEN_TTL = 86400  # 24 hours


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
    """Extract Bearer token from Authorization header and validate."""
    if not authorization:
        return False
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != 'bearer':
        return False
    return _check_dashboard_token(parts[1])


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
    cost_today = await db.get_llm_call_cost_today()
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
        """SELECT ts FROM cycle_log
           WHERE mode IN ('sleep', 'nap')
           ORDER BY ts DESC LIMIT 1"""
    )
    sleep_row = await cursor.fetchone()
    last_sleep = None
    if sleep_row and sleep_row['ts']:
        try:
            sleep_dt = datetime.fromisoformat(sleep_row['ts'].replace('Z', '+00:00'))
            if sleep_dt.tzinfo is None:
                sleep_dt = sleep_dt.replace(tzinfo=timezone.utc)
            hours_ago = (clock.now_utc() - sleep_dt).total_seconds() / 3600
            last_sleep = {
                'hoursAgo': round(hours_ago, 1),
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
        'costToday': round(cost_today, 2),
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
