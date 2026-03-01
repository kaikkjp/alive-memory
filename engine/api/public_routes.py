"""Public API route handlers for agent endpoints.

TASK-095 Phase 3: POST /api/chat and GET /api/public-state endpoints
with API key authentication. These are the external-facing endpoints
that third-party apps use to interact with an agent.
"""

import asyncio
import json
import uuid

import clock
import db
from models.event import Event
from pipeline.ack import on_visitor_message
from pipeline.sanitize import sanitize_input


async def _wait_for_dialogue(heartbeat, subscriber_id: str, timeout: float = 30.0,
                             *, required_visitor_id: str | None = None) -> dict | None:
    """Wait for a cycle log that contains dialogue, skipping non-dialogue cycles.

    The subscriber queue receives logs from ALL cycle types (idle, ambient,
    habit, engage). Only engage cycles produce dialogue. We drain non-dialogue
    logs until we find one with actual speech or the timeout expires.

    TASK-104: When required_visitor_id is set, only accept logs where the
    cycle's visitor_id matches. This prevents manager handlers from
    receiving dialogue intended for a different visitor's engagement.
    """
    import time
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        log = await heartbeat.wait_for_cycle_log(subscriber_id, timeout=remaining)
        if log is None:
            return None
        # Got a log — check if it has dialogue
        dialogue = log.get('dialogue')
        if not dialogue:
            # No dialogue — could be a habit/idle cycle. Keep waiting.
            continue
        # TASK-104: Filter by visitor_id when specified
        if required_visitor_id and log.get('visitor_id') != required_visitor_id:
            # Dialogue from a different visitor's cycle — skip it
            continue
        return log


async def handle_chat(server, writer, body_bytes: bytes, api_key_meta: dict):
    """Handle POST /api/chat — send a message and get the agent's response.

    Request body: {"message": "hello", "visitor_id": "optional-id"}
    Response: {"response": "...", "visitor_id": "...", "timestamp": "..."}
    """
    try:
        body = json.loads(body_bytes)
    except (json.JSONDecodeError, ValueError):
        await server._http_json(writer, 400, {'error': 'invalid JSON body'})
        return

    message = body.get('message', '').strip()
    if not message:
        await server._http_json(writer, 400, {'error': 'message field required'})
        return

    text = sanitize_input(message)
    if not text:
        await server._http_json(writer, 400, {'error': 'message was empty after sanitization'})
        return

    # Use provided visitor_id or generate one from API key name
    visitor_id = body.get('visitor_id', '').strip()
    if not visitor_id:
        visitor_id = f"api-{api_key_meta.get('name', 'anon')}-{uuid.uuid4().hex[:8]}"

    # Ensure visitor exists
    visitor = await db.get_visitor(visitor_id)
    if not visitor:
        await db.upsert_visitor(visitor_id, name=api_key_meta.get('name', 'API User'))

    # Log conversation
    await db.append_conversation(visitor_id, 'visitor', text)

    # TASK-095 v2: Tag manager messages in event payload
    # If source='manager' in request body, sensorium will frame it as
    # trusted human speech instead of regular visitor speech.
    # Trusted because: API keys are secrets controlled by the manager;
    # only the lounge portal (which validates manager auth) sends this flag.
    event_payload = {'text': text}
    request_source = body.get('source', '').strip()
    if request_source == 'manager':
        event_payload['source'] = 'manager'

    # Create and process speech event
    speech_event = Event(
        event_type='visitor_speech',
        source=f'visitor:{visitor_id}',
        payload=event_payload,
    )
    engagement = await db.get_engagement_state()
    ack_result = await on_visitor_message(speech_event, engagement)

    if not ack_result['should_process']:
        await server._http_json(writer, 200, {
            'response': None,
            'status': 'busy',
            'message': 'Agent is occupied. Message queued.',
            'visitor_id': visitor_id,
            'timestamp': clock.now_utc().isoformat(),
        })
        return

    # Trigger microcycle and wait for response.
    # Subscribe BEFORE scheduling so we don't miss the publish.
    server.heartbeat.subscribe_cycle_logs(visitor_id)
    try:
        await server.heartbeat.schedule_microcycle()
        log = await _wait_for_dialogue(server.heartbeat, visitor_id, timeout=30)
    finally:
        server.heartbeat.unsubscribe_cycle_logs(visitor_id)

    if log:
        dialogue = log.get('dialogue', '')
        await server._http_json(writer, 200, {
            'response': dialogue if dialogue else None,
            'visitor_id': visitor_id,
            'timestamp': clock.now_utc().isoformat(),
            'internal': {
                'expression': log.get('expression'),
                'body_state': log.get('body_state'),
                'gaze': log.get('gaze'),
            },
        })
    else:
        await server._http_json(writer, 200, {
            'response': None,
            'status': 'timeout',
            'message': 'Agent did not respond in time.',
            'visitor_id': visitor_id,
            'timestamp': clock.now_utc().isoformat(),
        })


async def handle_manager_message(server, writer, body_bytes: bytes, api_key_meta: dict):
    """Handle POST /api/manager-message — manager channel that bypasses engagement.

    TASK-104: Manager messages go through a dedicated perception channel.
    No engagement created, no visitor record, no ghost detection involvement.
    The message enters the normal heartbeat cycle tagged as 'manager_message'.

    Request body: {"message": "hello", "visitor_id": "optional-id"}
    Response: {"response": "...", "visitor_id": "...", "timestamp": "..."}
    """
    try:
        body = json.loads(body_bytes)
    except (json.JSONDecodeError, ValueError):
        await server._http_json(writer, 400, {'error': 'invalid JSON body'})
        return

    message = body.get('message', '').strip()
    if not message:
        await server._http_json(writer, 400, {'error': 'message field required'})
        return

    text = sanitize_input(message)
    if not text:
        await server._http_json(writer, 400, {'error': 'message was empty after sanitization'})
        return

    # Use provided visitor_id or generate one
    visitor_id = body.get('visitor_id', '').strip()
    if not visitor_id:
        visitor_id = f"manager-{api_key_meta.get('name', 'anon')}-{uuid.uuid4().hex[:8]}"

    # Ensure visitor exists (for conversation_log continuity)
    visitor = await db.get_visitor(visitor_id)
    if not visitor:
        await db.upsert_visitor(visitor_id, name=api_key_meta.get('name', 'Manager'))
        await db.update_visitor(visitor_id, trust_level='trusted')
    elif visitor.trust_level != 'trusted':
        await db.update_visitor(visitor_id, trust_level='trusted')

    # Log conversation (so cortex sees history in U6)
    await db.append_conversation(visitor_id, 'visitor', text)

    # Create manager_message event — NOT visitor_speech.
    # No engagement, no on_visitor_message(), no ghost detection.
    manager_event = Event(
        event_type='manager_message',
        source=f'visitor:{visitor_id}',
        payload={'text': text},
    )
    await db.append_event(manager_event)
    await db.inbox_add(manager_event.id, priority=0.95)

    # Trigger microcycle and wait for response (same as handle_chat).
    # TASK-104: Filter by visitor_id so manager doesn't receive another visitor's dialogue.
    server.heartbeat.subscribe_cycle_logs(visitor_id)
    try:
        await server.heartbeat.schedule_microcycle()
        log = await _wait_for_dialogue(server.heartbeat, visitor_id, timeout=30,
                                       required_visitor_id=visitor_id)
    finally:
        server.heartbeat.unsubscribe_cycle_logs(visitor_id)

    if log:
        dialogue = log.get('dialogue', '')
        await server._http_json(writer, 200, {
            'response': dialogue if dialogue else None,
            'visitor_id': visitor_id,
            'timestamp': clock.now_utc().isoformat(),
            'internal': {
                'expression': log.get('expression'),
                'body_state': log.get('body_state'),
                'gaze': log.get('gaze'),
            },
        })
    else:
        await server._http_json(writer, 200, {
            'response': None,
            'status': 'timeout',
            'message': 'Agent did not respond in time.',
            'visitor_id': visitor_id,
            'timestamp': clock.now_utc().isoformat(),
        })


async def handle_conversation_history(server, writer, body_bytes: bytes, api_key_meta: dict):
    """Handle POST /api/conversation-history — return past messages for a visitor.

    Request body: {"visitor_id": "lounge-xxx", "limit": 50}
    Response: {"messages": [{"role": "visitor", "text": "...", "ts": "..."}, ...]}
    """
    try:
        body = json.loads(body_bytes)
    except (json.JSONDecodeError, ValueError):
        await server._http_json(writer, 400, {'error': 'invalid JSON body'})
        return

    visitor_id = body.get('visitor_id', '').strip()
    if not visitor_id:
        await server._http_json(writer, 400, {'error': 'visitor_id required'})
        return

    limit = min(int(body.get('limit', 50)), 200)

    conn = await db._connection.get_db()
    cursor = await conn.execute(
        "SELECT role, text, ts FROM conversation_log "
        "WHERE visitor_id = ? AND NOT (role = 'system' AND text = '__session_boundary__') "
        "ORDER BY ts ASC LIMIT ?",
        (visitor_id, limit)
    )
    rows = await cursor.fetchall()
    messages = [{'role': r['role'], 'text': r['text'], 'ts': r['ts']} for r in rows]

    await server._http_json(writer, 200, {'messages': messages, 'visitor_id': visitor_id})


async def handle_public_state(server, writer, api_key_meta: dict):
    """Handle GET /api/public-state — return agent's public-facing state.

    Returns a subset of agent state safe for external consumption.
    """
    try:
        drives = await db.get_drives_state()
        engagement = await db.get_engagement_state()
        health = server.heartbeat.get_health_status()

        # Public-safe subset
        state = {
            'status': 'active' if health.get('alive') else 'inactive',
            'mood': {
                'valence': getattr(drives, 'mood_valence', 0.0),
                'arousal': getattr(drives, 'mood_arousal', 0.3),
            },
            'energy': getattr(drives, 'energy', 0.8),
            'engaged': getattr(engagement, 'status', 'none') != 'none',
            'timestamp': clock.now_utc().isoformat(),
        }

        await server._http_json(writer, 200, state)
    except Exception as e:
        await server._http_json(writer, 500, {'error': 'failed to get state'})
