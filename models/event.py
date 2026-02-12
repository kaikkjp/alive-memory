from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
import uuid


@dataclass
class Event:
    event_type: str       # visitor_speech | ambient | internal | action_* | memory_*
    source: str           # visitor:<id> | system | self | ambient
    payload: dict         # flexible per event type
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    # Living Loop extensions (backward-compatible defaults)
    channel: str = 'system'          # news | consume | ambient | thread | visitor | system
    salience_base: float = 0.5
    salience_dynamic: float = 0.0
    ttl_hours: Optional[float] = None   # NULL = no expiry
    engaged_at: Optional[datetime] = None
    outcome: Optional[str] = None       # engaged | ignored | expired (pool-level detail in content_pool.status)

    @property
    def effective_salience(self) -> float:
        return max(0.0, min(1.0, self.salience_base + self.salience_dynamic))


# Event types:
# visitor_connect, visitor_disconnect, visitor_speech,
# ambient_time, ambient_weather,
# internal_thought, internal_drive_update, internal_shift_candidate,
# action_speak, action_body, action_show_item, action_room_delta, action_post_x,
# memory_create, memory_update, memory_consolidate
#
# Channels (Living Loop):
# visitor, news, consume, ambient, thread, system
