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

    # Create and process speech event
    speech_event = Event(
        event_type='visitor_speech',
        source=f'visitor:{visitor_id}',
        payload={'text': text},
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

    # Trigger microcycle and wait for response
    await server.heartbeat.schedule_microcycle()

    log = await server.heartbeat.wait_for_cycle_log(visitor_id, timeout=30)

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
