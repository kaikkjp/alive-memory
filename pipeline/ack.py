"""ACK Path — immediate body response, no LLM, <1s."""

import random
from models.event import Event
from models.state import EngagementState
from pipeline.hippocampus_write import clear_trait_cooldown
import db


async def on_visitor_message(event: Event, engagement: EngagementState) -> dict:
    """<1s response. No LLM. Just body language. Returns body event payload."""

    # Record event
    await db.append_event(event)
    await db.inbox_add(event.id, priority=0.9)

    # Immediate body ACK
    if engagement.status == 'none':
        body = {"type": "glance_toward", "target": event.source}
    elif engagement.is_engaged_with(event.source):
        body = {"type": "listening", "target": event.source}
    elif engagement.status == 'engaged':
        # She's in conversation with someone else
        body = {"type": "busy_with_other", "target": event.source}
    else:
        body = {"type": "busy_ack", "target": event.source}

    # Emit body event
    body_event = Event(
        event_type='action_body',
        source='self',
        payload=body,
    )
    await db.append_event(body_event)

    # Determine if this message should trigger a microcycle.
    # All messages enter the inbox (via inbox_add above).
    # Schedule microcycle if she's free or talking to this visitor.
    # If talking to someone else, the message waits in inbox for
    # next cycle — she'll process it via salience competition.
    should_process = (
        engagement.is_engaged_with(event.source)
        or engagement.status == 'none'
    )
    delay = random.randint(3, 15) if should_process else 0

    return {
        "body": body,
        "should_process": should_process,
        "delay": delay,
    }


async def on_visitor_connect(event: Event):
    """Handle visitor connection."""
    await db.append_event(event)
    await db.inbox_add(event.id, priority=0.7)

    vid = event.source.split(':')[1] if ':' in event.source else event.source
    # Reset trait cooldown so returning visitors get fresh observations
    clear_trait_cooldown(vid)
    visitor = await db.get_visitor(vid)
    if visitor:
        await db.increment_visit(vid)
    else:
        await db.create_visitor(vid)


async def on_visitor_disconnect(event: Event):
    """Handle visitor disconnection."""
    await db.append_event(event)
    await db.inbox_add(event.id, priority=0.5)
