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

---
---

# HOTFIX-004 — Telegram/X adapters don't wake the heartbeat loop

Date: 2026-02-20
Files changed: `body/telegram.py`, `body/x_social.py`, `heartbeat_server.py`

---

## Symptoms

Production VPS: heartbeat loop silently stops cycling for minutes to hours while the process stays alive. `/api/health` returns `{"status": "alive"}` but no Cortex calls fire. Telegram and X messages sit in the inbox unprocessed.

Observed timeline (2026-02-20 JST):

| Time | Event |
|------|-------|
| 10:01 | Normal cycling, val=-0.96, reading Thich Nhat Hanh |
| 10:03 | X rate limit 429 → shutdown/restart |
| 10:04 | Restart PID 112556. Engage cycle: `「I'm closed.」` to spam visitor |
| 10:07 | Shutdown → Restart PID 112922 |
| 10:24 | Restart PID 113469. X poller pulls 13 spam mentions simultaneously |
| 10:25 | She replies: `「I said I'm closed. Twice. These links are not welcome here.」` |
| 10:29 | 13 spam visitors timeout. **No further cycles for 65 minutes.** |
| 11:35 | Process killed by systemd. Restart PID 114701 |
| 11:42 | 2 cycles run (rest), then **loop hangs again for 6+ minutes** |
| 11:43 | Telegram message from T: "How's your day?" — **never responded** |
| 11:49 | T's visitor timed out (335s) without ever being engaged |
| 11:50 | Manual restart PID 115640. Engage cycles run but loop hangs again |
| 11:56 | 13 spam visitors timeout (same mentions re-fetched on restart) |
| 11:56 | Telegram message from Xno — **sits unprocessed** |

## Bug 4 — Telegram adapter doesn't call schedule_microcycle()

### Where
`body/telegram.py:65-103` — `TelegramAdapter._handle_message()`

### Problem
The Telegram adapter creates a `visitor_speech` event and adds it to the inbox, but **never calls `heartbeat.schedule_microcycle()`**. The heartbeat loop only learns about the message when the next natural cycle fires — up to 450s later in rest mode (180s base * 2.5 rest multiplier * 1.25 jitter).

Compare with the WebSocket chat handler (`heartbeat_server.py:921`) which correctly calls `schedule_microcycle()` after every visitor message.

### Sequence
1. Telegram user sends message to group
2. `TelegramAdapter._handle_message()` creates event, adds to inbox
3. Heartbeat loop is in `_interruptible_sleep(sleep_seconds)` — waiting on `pending_microcycle` Event or timeout
4. Nobody sets `pending_microcycle` — the loop sleeps for the full timeout
5. Visitor times out after 300s idle (unengaged) before the loop wakes up

### Fix
Pass heartbeat reference to `TelegramAdapter`. After injecting the event, call `schedule_microcycle()` to wake the loop immediately.

---

## Bug 5 — X mention poller doesn't call schedule_microcycle()

### Where
`body/x_social.py:219-275` — `XMentionPoller._poll_once()`

### Problem
Same as Bug 4. The X mention poller creates `visitor_speech` events and adds them to the inbox but never wakes the heartbeat loop.

When 13 mentions arrive simultaneously (as in the spam flood), 13 `visitors_present` entries are created but the loop may be mid-sleep. The next cycle sees visitors but engagement is `none`, enters the visitors-present wait path (15-45s timeout), runs one autonomous cycle, then sleeps for the full rest interval again (337-562s). The loop technically cycles but at autonomous pace, not microcycle pace — visitors timeout before being engaged.

### Fix
Pass heartbeat reference to `XMentionPoller`. After processing each batch of mentions, call `schedule_microcycle()` once.

---

## Bug 6 — Long silent hangs (65+ minutes) with no log output

### Where
`heartbeat.py:267-285` — `_interruptible_sleep()`, `heartbeat.py:329-453` — `_main_loop`

### Problem
The 65-minute gap (10:29–11:35 JST) cannot be explained by normal cycle timing (max rest sleep is ~9 min). The process was alive (37s CPU consumed) but produced zero log output. Possible causes:

1. **Event race in `_interruptible_sleep`**: The method wraps `pending_microcycle.wait()` in `asyncio.create_task()` (line 273), then cancels pending tasks on exit (lines 280-285). If `schedule_microcycle()` fires during the cancellation window, the Event's set state and the Task's completion state can become inconsistent. The signal is lost and the loop sleeps for the full timeout.

2. **Exception in `run_one_cycle` or `run_cycle` caught by generic handler**: Lines 465-468 catch all exceptions and apply exponential backoff (5s→10s→20s→40s→60s). If the exception keeps recurring, the backoff caps at 60s — not 65 minutes. So this alone doesn't explain it.

3. **Combination**: After the spam flood, 13 visitor disconnect events fire simultaneously at 10:29:48. The next cycle processes them, and the autonomous path returns a rest-mode sleep (~450s). If the `_interruptible_sleep` Event race fires at exactly this point, the loop could miss its wake signal and sleep indefinitely until the next `schedule_microcycle()` call — which never comes because neither Telegram nor X call it (Bugs 4-5).

**Most likely scenario**: The loop entered rest sleep, the Event signal was lost to the race condition, and no external adapter called `schedule_microcycle()` to wake it. Only a systemd restart or a WebSocket visitor (which does call `schedule_microcycle()`) could break the deadlock.

### Mitigation
Fixing Bugs 4-5 removes the primary trigger (external messages will now wake the loop). Additionally, `_interruptible_sleep` could be hardened with a maximum sleep cap or a watchdog that detects long gaps between cycles.

---

## Root Cause Pattern

This is the same architectural tension documented in the original Bug 1-3: **concurrent producers inject events into the inbox without coordinating with the heartbeat loop's sleep/wake mechanism.** The WebSocket handler got the fix (it calls `schedule_microcycle()`), but the Telegram and X adapters — added later in TASK-069 — were built by mimicking the event injection pattern without the wake call.

---

## HOTFIX-005 — Visitors never registered (total memory loss)

Date: 2026-02-20
Files changed: `heartbeat_server.py`, `body/telegram.py`, `body/x_social.py`

### Symptom
The shopkeeper has no memory of any visitor across conversations. She treats every return visit as a first meeting. `visitors` table is empty, `visitor_traits` is empty, visitor-linked `totems` are empty, `data/memory/visitors/` has no MD files. But `conversation_log` has 37+ messages — she can talk, she just can't remember.

### Root Cause (3 bugs, same effect)

**Bug A — WebSocket visitors never registered** (`heartbeat_server.py:849`)

`_handle_ws_chat()` processes WebSocket messages but never calls `on_visitor_connect()`. Compare to the TCP flow (line 373-378) which does. Without the `on_visitor_connect()` call, `db.create_visitor()` never fires, so no row is ever inserted into the `visitors` table.

Also missing: `db.mark_session_boundary()` — so stale conversation history from previous sessions bleeds into the cortex's 6-turn window.

**Bug B — Telegram and X call a function that doesn't exist** (`body/telegram.py:79`, `body/x_social.py:253`)

Both adapters call `db.insert_visitor()` which is not defined anywhere in the codebase. The actual function is `db.create_visitor()`. The `AttributeError` is silently swallowed by a double `try/except/pass` pattern:

```python
try:
    visitor = await db.get_visitor(visitor_id)
    if not visitor:
        await db.insert_visitor(visitor_id, name=display_name)  # ← doesn't exist
except Exception:
    try:
        await db.insert_visitor(visitor_id, name=display_name)  # ← still doesn't exist
    except Exception:
        pass  # silently swallowed
```

Neither adapter calls `on_visitor_connect()` or `mark_session_boundary()`.

**Bug C — Downstream memory writes fail silently** (`pipeline/hippocampus_write.py`)

Even when the cortex outputs visitor impressions, trait observations, and totems, they can't be persisted:

| Cortex output | DB call | Result without visitor row |
|---|---|---|
| `visitor_impression` | `db.update_visitor()` | UPDATE 0 rows — silent no-op |
| `trait_observation` | `db.insert_trait()` | FK violation → `IntegrityError` |
| `totem_create` | `db.insert_totem()` | FK violation → `IntegrityError` |

The FK errors are caught in `pipeline/output.py:105` and logged as `[Memory Error]`, but execution continues. The only working flow was terminal standalone (`terminal.py:951`) which properly calls `on_visitor_connect()`.

### Cascade
```
Visitor connects via WS/Telegram/X
  → visitor row never created
  → engagement FSM works (no FK constraint)
  → conversation_log works (no FK constraint)
  → cortex sees last 6 turns ✓
  → cortex outputs trait/impression/totem observations
  → hippocampus_write fails on FK or no-ops on UPDATE
  → all visitor memory silently lost
  → next cycle: hippocampus recalls nothing
  → she has no idea who she's talking to
```

### Fix
All three entry points now route through `on_visitor_connect()` from `pipeline/ack.py`, matching the working TCP/terminal pattern:

1. `on_visitor_connect()` calls `db.create_visitor()` (INSERT OR IGNORE) or `db.increment_visit()`
2. `db.update_visitor()` sets the display name
3. `db.mark_session_boundary()` scopes the conversation window

The broken `db.insert_visitor()` calls and double-`try/except/pass` patterns are removed.
