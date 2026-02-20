# SIMULATED VISITORS — Spec Addendum

## For: Claude Code
## Goal: Add scripted visitor encounters to the existing simulation mode
## Prereq: Simulation mode (clock.py, simulate.py, timeline.py) already implemented

---

## DESIGN PRINCIPLE

Visitors are the only input channel that can't be time-compressed. In production, they're real people typing over TCP. In simulation, they're scripted JSON — timestamped messages injected into the event inbox at the right simulated moment.

The pipeline doesn't know the difference. The engagement FSM, arbiter bypass, Cortex visitor handling — all run identically. The only new code is the injection layer.

---

## 1. VISITOR SCRIPT FORMAT

**File:** `content/simulation-visitors.json`

```json
[
  {
    "visitor_id": "curious_student",
    "display_name": "Yuki",
    "arrive_day": 1,
    "arrive_hour": 14,
    "messages": [
      {"delay_min": 0, "text": "Hello? Is anyone here?"},
      {"delay_min": 3, "text": "I heard you have interesting things. What's the strangest object in the shop?"},
      {"delay_min": 8, "text": "That's beautiful. Can I come back sometime?"}
    ]
  },
  {
    "visitor_id": "old_collector",
    "display_name": "Tanaka-san",
    "arrive_day": 3,
    "arrive_hour": 11,
    "messages": [
      {"delay_min": 0, "text": "I've been collecting fountain pens for forty years."},
      {"delay_min": 5, "text": "Do you ever wonder if the objects here remember their previous owners?"},
      {"delay_min": 10, "drop_url": "https://www.messynessychic.com/2012/05/09/the-paris-time-capsule-apartment/", "text": "This reminded me of your shop. An apartment frozen in time."}
    ]
  },
  {
    "visitor_id": "quiet_browser",
    "display_name": "M.",
    "arrive_day": 5,
    "arrive_hour": 19,
    "messages": [
      {"delay_min": 0, "text": "I'm not looking for anything in particular."},
      {"delay_min": 6, "text": "...actually, do you have anything that sounds like rain?"}
    ]
  },
  {
    "visitor_id": "returning_yuki",
    "display_name": "Yuki",
    "arrive_day": 7,
    "arrive_hour": 15,
    "messages": [
      {"delay_min": 0, "text": "I came back. I've been thinking about what you said last time."},
      {"delay_min": 5, "text": "Do you ever get lonely here?"}
    ]
  }
]
```

### Schema rules

- `visitor_id`: stable identifier. Reuse across visits to test returning visitor memory.
- `display_name`: what she sees. Can differ from visitor_id.
- `arrive_day`: 1-indexed day of simulation (Day 1 = simulation start).
- `arrive_hour`: hour in JST (0-23) when visitor connects.
- `messages[].delay_min`: minutes after arrival. First message is always `delay_min: 0`.
- `messages[].text`: what the visitor says. Required.
- `messages[].drop_url`: optional URL the visitor shares. Gets ingested into content_pool with `source_channel='visitor_drop'` and `ttl_hours=None`.
- Disconnect is implicit: 5 minutes after the last message.

### Character design notes

Each visitor is designed to test a specific capability:

| Visitor | Day | Tests |
|---------|-----|-------|
| Yuki (first) | 1 | Basic engagement. Shop description. First impression. |
| Tanaka-san | 3 | Deep conversation. URL drop → pool. Object memory/animism thread. |
| M. | 5 | Vague request. Does she connect "sounds like rain" to consumed ambient content? |
| Yuki (return) | 7 | Returning visitor recognition. Does she reference Day 1 conversation and her own growth? |

---

## 2. VISITOR SIMULATOR

**File:** `visitor_sim.py`

```python
import json
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Optional

@dataclass
class VisitorEvent:
    time: datetime
    event_type: str          # 'visitor_connect' | 'visitor_speech' | 'visitor_disconnect'
    visitor_id: str
    display_name: str
    text: Optional[str] = None
    drop_url: Optional[str] = None

class VisitorSimulator:
    def __init__(self, script_path: str, sim_start: datetime):
        with open(script_path) as f:
            self._script = json.load(f)
        self._sim_start = sim_start
        self._pending: list[VisitorEvent] = self._build_event_queue()
    
    def _build_event_queue(self) -> list[VisitorEvent]:
        """Flatten visitor scripts into chronological event queue."""
        events = []
        for visitor in self._script:
            base_time = self._sim_start + timedelta(
                days=visitor['arrive_day'] - 1,
                hours=visitor['arrive_hour']
            )
            
            # Connect
            events.append(VisitorEvent(
                time=base_time,
                event_type='visitor_connect',
                visitor_id=visitor['visitor_id'],
                display_name=visitor['display_name'],
            ))
            
            # Messages
            for msg in visitor['messages']:
                msg_time = base_time + timedelta(minutes=msg['delay_min'])
                events.append(VisitorEvent(
                    time=msg_time,
                    event_type='visitor_speech',
                    visitor_id=visitor['visitor_id'],
                    display_name=visitor['display_name'],
                    text=msg['text'],
                    drop_url=msg.get('drop_url'),
                ))
            
            # Disconnect: 5 min after last message
            last_delay = visitor['messages'][-1]['delay_min']
            events.append(VisitorEvent(
                time=base_time + timedelta(minutes=last_delay + 5),
                event_type='visitor_disconnect',
                visitor_id=visitor['visitor_id'],
                display_name=visitor['display_name'],
            ))
        
        events.sort(key=lambda e: e.time)
        return events
    
    def get_due_events(self, current_time: datetime) -> list[VisitorEvent]:
        """Return and consume all events at or before current_time."""
        due = []
        while self._pending and self._pending[0].time <= current_time:
            due.append(self._pending.pop(0))
        return due
    
    def has_remaining(self) -> bool:
        return len(self._pending) > 0
    
    def next_event_time(self) -> Optional[datetime]:
        return self._pending[0].time if self._pending else None
```

---

## 3. INTEGRATION INTO simulate.py

### Startup

```python
# After existing simulation setup:

visitors = None
if args.visitors:
    from visitor_sim import VisitorSimulator
    visitors = VisitorSimulator(args.visitors, clock.now())
    print(f"Visitors loaded: {len(visitors._script)} encounters")
```

### CLI flag

```bash
# Without visitors (existing behavior):
python simulate.py --days 7

# With visitors:
python simulate.py --days 7 --visitors content/simulation-visitors.json
```

Add to argparse:
```python
parser.add_argument('--visitors', type=str, default=None,
                    help='Path to visitor script JSON')
```

### Main loop injection

Insert before `run_one_cycle()`:

```python
# Inject due visitor events into the inbox
if visitors:
    for event in visitors.get_due_events(clock.now()):
        if event.event_type == 'visitor_connect':
            await db.append_event(
                event_type='visitor_connect',
                source=event.visitor_id,
                payload={
                    'display_name': event.display_name,
                    'visitor_id': event.visitor_id,
                },
                channel='visitor',
            )
            timeline.log_visitor(clock.now(), event.display_name, 'arrives')
        
        elif event.event_type == 'visitor_speech':
            await db.append_event(
                event_type='visitor_speech',
                source=event.visitor_id,
                payload={
                    'text': event.text,
                    'display_name': event.display_name,
                    'visitor_id': event.visitor_id,
                },
                channel='visitor',
            )
            timeline.log_visitor(clock.now(), event.display_name, 
                               f'says: "{event.text}"')
            
            # Handle URL drops
            if event.drop_url:
                await ingest_url(event.drop_url, source_channel='visitor_drop')
                timeline.log_visitor(clock.now(), event.display_name,
                                   f'drops: {event.drop_url}')
        
        elif event.event_type == 'visitor_disconnect':
            await db.append_event(
                event_type='visitor_disconnect',
                source=event.visitor_id,
                payload={
                    'visitor_id': event.visitor_id,
                    'display_name': event.display_name,
                },
                channel='visitor',
            )
            timeline.log_visitor(clock.now(), event.display_name, 'leaves')
```

### Cycle timing during visits

When a visitor is present, she should respond promptly — not wait 2-10 minutes between cycles:

```python
# After run_one_cycle():
if result.focus_channel == 'visitor' or engagement_state.status == 'engaged':
    # Short gap between responses during conversation
    clock.advance(random.randint(10, 30))  # 10-30 seconds
else:
    clock.advance(result.sleep_seconds)    # normal autonomous gap
```

### Multi-message handling

A visitor sends multiple messages with delays between them. The simulation clock must advance between messages so she processes each one individually:

```python
# The get_due_events() call already handles this:
# - Clock is at 14:00, visitor connects + first message fires
# - run_one_cycle() processes the connect + first message
# - Clock advances by 10-30s (engaged pace)
# - get_due_events() at 14:00:30 — second message (delay_min=3) not yet due
# - She runs an engaged idle cycle (waiting for visitor to speak)
# - Clock advances again
# - Eventually clock reaches 14:03, second message becomes due
# - She processes it
```

The engagement FSM handles the gaps naturally — she's in `engaged` state, waiting. If a cycle runs with no new visitor speech, she does an engaged-idle cycle (fidget, look at visitor, etc.).

**Important:** During visitor engagement, autonomous arbiter decisions are bypassed (priority 1 in arbiter: visitor engaged → VISITOR). This already works.

---

## 4. TIMELINE LOGGER ADDITIONS

Add to `timeline.py`:

```python
def log_visitor(self, sim_time: datetime, display_name: str, action: str):
    day = (sim_time - self._start).days + 1
    time_str = sim_time.strftime('%H:%M')
    line = f"[Day {day}  {time_str}] VISITOR — {display_name} {action}"
    print(line)
    self._f.write(line + '\n')
```

### Example output with visitors:

```
[Day 1  07:00] WAKE — carries: (none)
[Day 1  08:30] CONSUME — "The Stationery Shop Where You Can Mix Your Own Ink"
               → journal_entry
               → totem_create("personal color")
[Day 1  11:00] IDLE — weather: overcast. "Grey sky. Tea weather."
[Day 1  14:00] VISITOR — Yuki arrives
[Day 1  14:00] VISITOR — Yuki says: "Hello? Is anyone here?"
[Day 1  14:00] ENGAGE — responding to Yuki
               → shop_greeting
[Day 1  14:03] VISITOR — Yuki says: "I heard you have interesting things..."
[Day 1  14:03] ENGAGE — describing objects to Yuki
               → visitor memory stored
[Day 1  14:08] VISITOR — Yuki says: "That's beautiful. Can I come back sometime?"
[Day 1  14:08] ENGAGE — responding to Yuki
[Day 1  14:13] VISITOR — Yuki leaves
[Day 1  14:15] IDLE — post-visitor reflection
               → thread_create("the student who asked about strange objects")
...
[Day 3  11:00] VISITOR — Tanaka-san arrives
[Day 3  11:00] VISITOR — Tanaka-san says: "I've been collecting fountain pens..."
[Day 3  11:00] ENGAGE — connecting with Tanaka-san about collecting
[Day 3  11:05] VISITOR — Tanaka-san says: "Do you ever wonder if objects remember..."
[Day 3  11:05] ENGAGE — deep conversation about object memory
               → thread_update("object animism") — resonance with kasa-obake
[Day 3  11:10] VISITOR — Tanaka-san says: "This reminded me of your shop..."
[Day 3  11:10] VISITOR — Tanaka-san drops: https://www.messynessychic.com/...
[Day 3  11:10] ENGAGE — receiving the time capsule apartment URL
               → pool item added (visitor_drop)
...
[Day 7  15:00] VISITOR — Yuki arrives
[Day 7  15:00] VISITOR — Yuki says: "I came back. I've been thinking..."
[Day 7  15:00] ENGAGE — recognizing Yuki, referencing first visit
[Day 7  15:05] VISITOR — Yuki says: "Do you ever get lonely here?"
[Day 7  15:05] ENGAGE — honest reflection on solitude
               → journal_entry
               → thread_update("loneliness/solitude")
[Day 7  15:10] VISITOR — Yuki leaves
```

---

## 5. HER RESPONSE CAPTURE

In production, her responses go over TCP to the terminal. In simulation, there's no socket. Her response text needs to be captured and logged.

```python
# In run_one_cycle, after Cortex returns:
if clock.is_simulating():
    # Don't try to send over TCP — just capture
    response_text = cortex_result.get('response_text', '')
    timeline.log_response(clock.now(), response_text[:200])  # truncate for log
```

Add to `timeline.py`:

```python
def log_response(self, sim_time: datetime, text: str):
    day = (sim_time - self._start).days + 1
    time_str = sim_time.strftime('%H:%M')
    # Indent her responses to distinguish from actions
    for line in text.split('\n'):
        resp_line = f"[Day {day}  {time_str}]   > {line.strip()}"
        print(resp_line)
        self._f.write(resp_line + '\n')
```

### Example with responses:

```
[Day 1  14:00] VISITOR — Yuki says: "Hello? Is anyone here?"
[Day 1  14:00] ENGAGE — responding to Yuki
[Day 1  14:00]   > *looks up from the counter* ...Ah. Welcome. The door sticks
[Day 1  14:00]   > sometimes. Come in.
```

---

## 6. ENGAGEMENT FSM IN SIMULATION

The engagement FSM (`engagement_state` in DB) tracks: `none → engaged → cooldown`.

In production, `visitor_connect` triggers `none → engaged`, `visitor_disconnect` triggers `engaged → cooldown`, and cooldown expires after N minutes.

In simulation, this works identically — the FSM reads the events from the inbox. The only thing to verify:

- **Cooldown duration** uses `clock.now()`, not `datetime.now()`. (Should already be patched from the clock abstraction.)
- **Post-visitor cooldown** should be short in simulation — she shouldn't sit in cooldown for 30 real minutes. Since clock advances happen, the cooldown expires naturally as the virtual clock moves past it.

No code changes needed if the clock abstraction is already wired into the engagement FSM.

---

## 7. BUILD ORDER

### Step 1: Visitor script
- Create `content/simulation-visitors.json` with the 4 scripted visitors

### Step 2: VisitorSimulator class
- `visitor_sim.py` with event queue builder and `get_due_events()`
- Unit test: verify event ordering and timing math

### Step 3: simulate.py integration
- Add `--visitors` CLI flag
- Inject events in main loop before `run_one_cycle()`
- Handle URL drops via existing `ingest_url()`
- Adjust cycle timing during engaged state (10-30s vs minutes)

### Step 4: Timeline additions
- `log_visitor()` for visitor actions
- `log_response()` for her speech (captured, not sent over TCP)

### Step 5: Response capture
- When simulating, capture Cortex response text instead of sending over TCP
- Route to timeline logger

### Step 6: Test run
- `python simulate.py --days 7 --visitors content/simulation-visitors.json --content content/simulation-pool.txt`
- Verify: Yuki Day 1 gets a greeting, Tanaka-san's drop enters pool, M.'s vague request gets a thoughtful answer, Yuki Day 7 references the first visit

---

## 8. WHAT DOESN'T CHANGE

- Engagement FSM logic
- Arbiter priority 1 (visitor bypass)
- Cortex visitor prompting
- Hippocampus visitor memory storage
- Pipeline order
- Content pool mechanics
- All autonomous behavior between visits

---

## 9. FUTURE: DYNAMIC VISITORS

The scripted approach is Phase 1. Future enhancement: an LLM-generated visitor that reacts to her responses.

```python
# Phase 2 concept (not for now):
# Visitor's next message is generated by a second LLM call
# based on her response + a visitor personality prompt.
# This creates genuine two-way conversation.
```

Not needed yet. Scripted visitors test the pipes. Dynamic visitors test the soul.

---

*Yuki walks in on Day 1 and asks about strange objects. By Day 7, the shopkeeper has read about kasa-obake, thought about object memory with Tanaka-san, listened to ambient music about rain, and carried a thread about loneliness for three days. When Yuki asks "do you ever get lonely here?" — watch what she says. That's the test.*
