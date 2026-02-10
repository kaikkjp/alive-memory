from dataclasses import dataclass, field
from datetime import datetime, timezone
import uuid


@dataclass
class Event:
    event_type: str       # visitor_speech | ambient | internal | action_* | memory_*
    source: str           # visitor:<id> | system | self | ambient
    payload: dict         # flexible per event type
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# Event types:
# visitor_connect, visitor_disconnect, visitor_speech,
# ambient_time, ambient_weather,
# internal_thought, internal_drive_update, internal_shift_candidate,
# action_speak, action_body, action_show_item, action_room_delta, action_post_x,
# memory_create, memory_update, memory_consolidate
