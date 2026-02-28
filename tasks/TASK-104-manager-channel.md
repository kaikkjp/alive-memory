# TASK-104: Manager Channel — Separate from Visitor Engagement

**Status:** READY
**Priority:** P1
**Branch:** `fix/manager-channel`

---

## Problem

Lounge "private chat" sends manager messages through the visitor engagement system. The agent treats the manager as a visitor — creates an engagement, expects WebSocket presence, and when the Lounge HTTP request doesn't maintain a persistent WebSocket connection, the heartbeat's ghost detection clears it. Loop: Lounge sends message → engagement created → no WebSocket presence → ghost cleared → next message recreates engagement.

The manager is not a visitor. She shouldn't greet her manager, track them in visitors_present, or run ghost detection on them.

---

## Design

Manager messages are a separate perception channel. They bypass the engagement system entirely.

### Message flow

**Current (broken):**
```
Lounge chat → heartbeat_server /api/chat → create engagement → sensorium sees visitor → 
ghost detector sees no WebSocket → clears engagement → repeat
```

**Target:**
```
Lounge chat → heartbeat_server /api/manager-message → write to event_log as type 'manager_message' →
sensorium perceives as manager input → cortex responds → response returned via API
```

No engagement. No visitor record. No ghost detection involvement.

### Sensorium handling

Manager messages get a dedicated perception type:

```python
# In pipeline/sensorium.py
if event.event_type == "manager_message":
    return Perception(
        source="manager",
        content=event.data["text"],
        salience=0.9,          # manager always gets attention
        channel="manager"
    )
```

The cortex prompt frames this differently from visitors:

```
[Manager note]: "How are you feeling today?"
```

Not:
```
A visitor says: "How are you feeling today?"
```

She knows this is her manager, not a customer. Her response tone can differ — more direct, less performative.

### Response path

Manager messages don't go through the normal cycle-wait-respond flow. Two options:

**Option A — Synchronous (simpler):** The `/api/manager-message` endpoint injects the message, triggers an immediate mini-cycle (sensorium → cortex → response), returns the response in the HTTP response. Manager doesn't wait for the next heartbeat tick.

**Option B — Async via next cycle (safer):** Message goes to event_log, next heartbeat cycle picks it up, response is stored and retrievable via `/api/manager-response/{message_id}`. Lounge polls or uses SSE.

**Recommend Option B.** It doesn't create a second cortex-call pathway. The message enters the normal cycle like any other perception, just tagged differently. The Lounge already polls for state updates — add manager responses to that poll.

### What to change

**heartbeat_server.py:**
- New endpoint: `POST /api/manager-message` — writes event_log entry with `event_type='manager_message'`
- Do NOT create engagement, do NOT touch visitors_present
- Return `{message_id, status: "queued"}`
- New endpoint: `GET /api/manager-response/{message_id}` — returns response when available

**pipeline/sensorium.py:**
- Handle `manager_message` event type
- Create Perception with `channel="manager"`, high salience
- Do NOT increment visitor count or touch engagement state

**prompt_assembler.py (or equivalent):**
- Format manager messages distinctly: `[Manager note]:` prefix
- Do not use visitor conversation template

**pipeline/body.py or output.py:**
- When cortex response is to a manager message, write response to a retrievable location (new table `manager_messages` or tag in `text_fragments` with `fragment_type='manager_response'`)

**Lounge frontend:**
- Update chat component to call `/api/manager-message` instead of the visitor chat endpoint
- Poll `/api/manager-response/{id}` for reply (or switch to SSE)

### What NOT to change

- Visitor engagement system — leave it alone, it works for window visitors
- Ghost detection — no changes needed, manager messages never create engagements
- Sensorium visitor handling — untouched
- Cortex — just sees different prompt framing, no code change

---

## Verification

1. Send message via Lounge chat → no engagement created (check `visitors_present` table)
2. Agent responds within next cycle → response retrievable via API
3. Ghost detection log is clean — no create/clear loop
4. Send message via window chat → normal visitor engagement still works
5. Agent's response to manager uses appropriate tone (not "welcome to the shop")

---

## Risk

Low. New endpoint + new event type + sensorium branch. Doesn't touch existing visitor flow. Main risk is the Lounge frontend change — make sure the old visitor chat endpoint isn't called from other places.
