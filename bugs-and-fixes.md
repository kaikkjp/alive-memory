# Bugs & Fixes — Heartbeat/Terminal Race Conditions

Date: 2025-02-11
Files changed: `heartbeat.py`, `terminal.py`

---

## Session Symptoms

User input gets misattributed or ignored. Typical broken trace:

```
yo  [Cortex] ...            ← user input on same line as background output
[Sensorium] Salience: 0.1 | Type: ambient     ← ambient cycle, not speech
...
[Sensorium] Salience: 0.7 | Type: visitor_connect  ← "yo" seen as arrival, not speech
```

The shopkeeper responds to arrivals when she should respond to speech, or ignores input entirely.

---

## Bug 1 — Startup idle cycle eats the visitor_connect event

### Where
`heartbeat.py` `_main_loop`, lines 112-118 (pre-fix)

### Sequence
1. `terminal.py` emits `visitor_connect` event and adds it to inbox
2. `terminal.py` sets engagement to `engaged`
3. `terminal.py` starts heartbeat — `_main_loop` fires an idle cycle **immediately**
4. Idle cycle reads inbox, **consumes** the `visitor_connect` event
5. `terminal.py` calls `schedule_microcycle()` — but the event is already eaten
6. `wait_for_cycle_log()` grabs the idle cycle's log, not the microcycle's

### Result
First greeting is from an idle cycle that happened to eat the connect event. Works by accident but is fragile — sometimes the idle cycle treats it as ambient instead of a real arrival.

### Fix
Guard the startup idle cycle: skip it if engagement is already `engaged` or if a microcycle is already pending.

```python
# Before (always ran idle on startup)
if self.running:
    await self.run_cycle('idle')

# After (skip when terminal already set up engagement)
if self.running and not self.pending_microcycle.is_set():
    engagement = await db.get_engagement_state()
    if engagement.status != 'engaged':
        await self.run_cycle('idle')
```

---

## Bug 2 — Ambient/silence cycles steal visitor speech from inbox

### Where
`heartbeat.py` `_main_loop`, engaged timeout path (line ~167)

### Sequence
1. Heartbeat enters engaged wait: `wait_for(pending_microcycle.wait(), timeout=30-90s)`
2. User types a message in terminal
3. `terminal.py` appends speech event to inbox, does ACK, sleeps 0.3-0.8s
4. During that sleep, the heartbeat timeout **expires**
5. Heartbeat enters ambient/silence cycle path
6. Ambient cycle calls `inbox_get_unread()` — **grabs the visitor_speech event**
7. `terminal.py` wakes up, calls `schedule_microcycle()`
8. Microcycle runs but inbox is empty — speech event already consumed by ambient
9. Ambient cycle processed the speech as low-salience background noise

### Result
User input is swallowed. The shopkeeper fidgets or talks to herself instead of responding. When she does "respond," it's to the ambient perception, not to what the user said.

### Fix
Before running ambient/silence cycles, re-check for microcycle signals and unread visitor events in the inbox. If either exists, yield back to the main loop.

```python
except asyncio.TimeoutError:
    # NEW: guard against race with terminal
    if self.pending_microcycle.is_set():
        continue
    unread = await db.inbox_get_unread()
    has_visitor_event = any(
        e.event_type in ('visitor_speech', 'visitor_connect', 'visitor_disconnect')
        for e in unread
    )
    if has_visitor_event:
        continue
    # ... then proceed with silence/ambient logic
```

---

## Bug 3 — Silence timer drifts because last_activity only updates on shopkeeper response

### Where
`terminal.py` speech handling path, `pipeline/executor.py:71-76`

### Problem
`last_activity` is only updated when the shopkeeper **responds** (in `executor.py`), not when the visitor **speaks**. This means:

- If the shopkeeper takes 10s to process, the silence timer thinks the visitor has been silent for 10s longer than they have
- If the shopkeeper's response gets dropped/filtered, `last_activity` never updates at all
- Subsequent silence cycles may fire prematurely based on stale timestamps

### Fix
Update `last_activity` in `terminal.py` when the visitor speaks, before triggering the pipeline:

```python
# terminal.py, after appending conversation
await db.update_engagement_state(
    last_activity=datetime.now(timezone.utc),
)
```

The executor still updates it again on shopkeeper response, which is fine — the timestamp stays fresh from both directions.

---

## Root Cause Pattern

All three bugs stem from the same architectural tension: **the heartbeat loop and terminal input loop are concurrent coroutines sharing the inbox as a work queue, with no locking or ownership semantics**.

The inbox is append-only from the writer side (events go in), but `inbox_get_unread` + `inbox_mark_read` is a non-atomic read-then-claim pattern. Both the microcycle path (visitor-triggered) and the ambient path (timer-triggered) call `run_cycle`, which drains the inbox indiscriminately.

The fixes above are targeted guards. A deeper fix would be to separate visitor-directed events from ambient events at the inbox level, or to use a dedicated channel for visitor speech that only microcycles can consume. Not needed now, but worth noting if more race conditions surface.

---
---

# Codex Review Fixes — 24/7 Deployment Hardening

Date: 2026-02-11
Files changed: `heartbeat.py`, `heartbeat_server.py`, `terminal.py`, `db.py`, `pipeline/cortex.py`

---

## P0-1 — Unbounded memory growth in cycle log queue

### Where
`heartbeat.py:49` — `asyncio.Queue()` with no maxsize

### Problem
Every cycle (idle, ambient, express, rest, micro) appends a log dict to a single unbounded queue. Only client-triggered microcycles consume from it. Autonomous cycles accumulate indefinitely — OOM over days of 24/7 operation.

### Fix
Replaced single unbounded queue with per-subscriber model (`_cycle_log_subscribers: dict[str, asyncio.Queue]`). Each subscriber gets a bounded queue (maxsize=50). On broadcast, oldest entry is drained if full. Autonomous cycles still produce logs but they're bounded per-subscriber and dropped when no one is listening.

---

## P0-2 — Response/log misrouting across concurrent clients

### Where
`heartbeat_server.py:148,198,219` — all clients call `wait_for_cycle_log()` on shared queue

### Problem
All clients waited on the same queue. Whichever handler woke first got the next cycle log, regardless of who triggered it. Two terminals would receive each other's responses.

### Fix
Per-subscriber queues (same change as P0-1). Each client subscribes with their `visitor_id` on connect, gets their own queue. `wait_for_cycle_log(subscriber_id)` reads from that queue only. Unsubscribe on disconnect/cleanup.

---

## P0-3 — Cross-client stream leakage

### Where
`heartbeat_server.py:380-389` — `_on_stage()` broadcasts to ALL connected terminals

### Problem
Stage events (internal monologue, cortex output, dialogue) leaked between sessions. Every connected client saw every stage from every cycle.

### Fix
Added `_active_visitor_id` tracking to server. Stage broadcasts now filter: only the active visitor's terminal receives conversation stages. Autonomous stages like `sleep` still broadcast to all.

---

## P0-4 — Engagement state singleton allows multi-client overwrites

### Where
`heartbeat_server.py:117-136`, `db.py:80` — `engagement_state` table `CHECK(id=1)`

### Problem
Two terminals connecting simultaneously both overwrote the singleton engagement row. One disconnect could clear state for both. System is designed as single-visitor-at-a-time.

### Fix
Server-level enforcement: if `_active_visitor_id` is set and a different visitor tries to connect, server sends `{type: 'rejected'}` and closes the connection. Terminal handles the `rejected` message type gracefully.

---

## P1-5 — Anthropic outage doesn't degrade gracefully

### Where
`pipeline/cortex.py:148,185` — `client.messages.create()` with no timeout
`heartbeat.py:246-249` — flat 5s retry forever

### Problem
No timeout on API calls (hangs block entire event loop). No retry policy — just sleep 5s and retry infinitely. No circuit breaker. On outage, rapid retry loop wastes resources.

### Fix
- Added `timeout=30.0` to Anthropic client constructor
- Module-level circuit breaker: tracks consecutive failures, opens after 3 failures, recloses after 5 min
- Wrapped both `cortex_call()` and `cortex_call_maintenance()` with try/except for `APITimeoutError`, `APIConnectionError`, `RateLimitError`, `InternalServerError`
- Returns `fallback_response()` on failure (she says "..." and thinks "something went wrong")
- Heartbeat retry backoff: 5s → 10s → 20s → 40s → 60s cap, resets on success

---

## P1-6 — Non-atomic write chains can replay events

### Where
`heartbeat.py:304,431-433` — inbox read at start, mark-read at end

### Problem
Full cycle runs between inbox read and mark-read. If crash occurs mid-cycle, events stay unread and replay on next startup — duplicating conversation entries, drive updates, and memory writes.

### Fix
Moved `inbox_mark_read` to immediately after `inbox_get_unread`, before any processing. Optimistic strategy: losing an event on crash is far safer than replaying it (duplicate dialogue, double drive adjustments). Removed the old post-cycle mark-read block.

---

## P1-7 — SQLite lock resilience is weak

### Where
`db.py:23-26` — WAL enabled, no `busy_timeout`

### Problem
Default SQLite busy_timeout is 0 (instant failure). Under concurrent access from heartbeat + terminal, writes fail with "database is locked".

### Fix
Added `PRAGMA busy_timeout=5000` after WAL setup. SQLite now waits up to 5 seconds for locks to clear before failing.

---

## P1-8 — First-connect race on visitor creation

### Where
`pipeline/ack.py:52-56`, `db.py:404-412` — `get_visitor()` then `create_visitor()` non-atomic

### Problem
Two simultaneous connections for the same visitor_id: both see `None` from `get_visitor()`, both try `INSERT` — second hits unique constraint error and drops the connection.

### Fix
Changed `INSERT INTO visitors` to `INSERT OR IGNORE INTO visitors` in `create_visitor()`. If the row already exists, the insert silently does nothing. The subsequent `get_visitor()` returns whichever row won the race.

---

## P2-9 — Cost runaway risk in idle/silence loops

### Where
`heartbeat.py:233-236` — idle cycles always call Cortex
`heartbeat.py:246-249` — 5s flat retry on failure

### Problem
Ambient/idle cycles call Cortex every 2-10 min autonomously. No daily cost cap. On API failure, 5s retry loop with no backoff. Over 24h, hundreds of unnecessary LLM calls.

### Fix
- Daily cycle cap of 500 calls/day in `cortex.py` — returns fallback when exceeded
- Idle path now has 50% chance to skip Cortex entirely (body-only fidget, zero LLM cost)
- Silence cycles already had 70% fidget skip — unchanged
- Exponential backoff on errors prevents rapid retry loops
