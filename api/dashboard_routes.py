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
    from pipeline.day_memory import DayMemoryEntry
    moments = await db.get_day_memory(limit=20)
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
    # Expected max interval between cycles is ~600s (10 min).
    # 1x interval → active, 2x → late, 3x → inactive.
    _EXPECTED_INTERVAL = 600  # seconds
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
        'engagement_status': engagement.status,
        'shop_status': room.shop_status,
        'active_visitor': engagement.visitor_id,
    })


async def handle_body(server, writer: asyncio.StreamWriter,
                      authorization: str):
    """Handle GET /api/dashboard/body — return body capabilities and energy."""
    if not check_dashboard_auth(authorization):
        await server._http_json(writer, 401, {'error': 'unauthorized'})
        return
    capabilities = await db.get_action_capabilities()
    energy = await db.get_energy_budget()
    actions_today = await db.get_actions_today()
    await server._http_json(writer, 200, {
        'capabilities': capabilities,
        'energy': energy,
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
