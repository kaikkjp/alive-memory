# Bug & Fix Log

> All bugs discovered and fixes applied in this repository are documented here.
> Entries are in reverse chronological order (newest first).
> See `CLAUDE.md` §18 for the required format.

---

### BUG-2026-02-12-sim-db-filename-collision

| Field           | Value |
|-----------------|-------|
| **Date**        | 2026-02-12 |
| **Severity**    | High |
| **Status**      | Fixed |
| **Branch**      | `feat/simulation-mode` |
| **PR**          | #14 |
| **Commit**      | N/A |

**Symptom:** Running `python simulate.py --days 0 --quiet` twice on the same day crashed with `sqlite3.IntegrityError: UNIQUE constraint failed: collection_items.id`.

**Root Cause:** DB filename was derived only from `start` time (`sim_YYYYMMDD_HHMMSS.db`). With default start at 07:00 JST, rerunning on the same day reused the same DB file. `seed()` inserts fixed collection IDs which collide on second run.

**Fix:** Append a short UUID (`run_id = str(uuid.uuid4())[:8]`) to the DB and log filenames: `sim_{ts}_{run_id}.db`.

**Files Affected:**
- `simulate.py` — added uuid import, appended run_id to db/log filenames

**Tests Added:**
- [ ] Run `simulate.py --days 0` twice — both succeed with different filenames

**Follow-ups / Notes:**
- Found by Codex review of PR #14. Confidence 0.98.

---

### BUG-2026-02-12-sim-start-timezone-not-normalized

| Field           | Value |
|-----------------|-------|
| **Date**        | 2026-02-12 |
| **Severity**    | Medium |
| **Status**      | Fixed |
| **Branch**      | `feat/simulation-mode` |
| **PR**          | #14 |
| **Commit**      | N/A |

**Symptom:** `--start 2026-02-12T08:00:00+00:00` was printed as `08:00 JST` in output, and sleep windows (03:00-06:00 JST) were shifted by the timezone offset.

**Root Cause:** `main()` only added JST when `tzinfo` was `None`. Timezone-aware inputs in other zones were kept as-is but treated/labeled as JST throughout simulation.

**Fix:** Added `else: start = start.astimezone(JST)` to normalize all timezone-aware inputs to JST.

**Files Affected:**
- `simulate.py` — added astimezone(JST) normalization for tz-aware --start

**Tests Added:**
- [ ] Run with `--start 2026-02-12T08:00:00+00:00` — should show `17:00 JST`

**Follow-ups / Notes:**
- Found by Codex review of PR #14. Confidence 0.96.

---

### BUG-2026-02-12-sim-deferred-sleep-advances-clock

| Field           | Value |
|-----------------|-------|
| **Date**        | 2026-02-12 |
| **Severity**    | Medium |
| **Status**      | Fixed |
| **Branch**      | `feat/simulation-mode` |
| **PR**          | #14 |
| **Commit**      | N/A |

**Symptom:** When `sleep_cycle()` returned `False` (deferred), the simulation still advanced the clock by 3 hours and logged a wake event, skipping daily consolidation while pretending it happened.

**Root Cause:** `clock.advance(SLEEP_ADVANCE_SECONDS)` and `tl.log_wake()` were unconditional — they ran whether sleep succeeded or not.

**Fix:** Only advance past sleep window and log wake when `hb._last_sleep_date == today_str` (sleep actually ran). On deferral, advance 60s and retry on next loop iteration.

**Files Affected:**
- `simulate.py` — conditional clock advance based on sleep success

**Tests Added:**
- [ ] Verify deferred sleep retries on next iteration

**Follow-ups / Notes:**
- Found by Codex review of PR #14. Confidence 0.93.

---

### BUG-2026-02-12-day-memory-leaks-across-days

| Field           | Value |
|-----------------|-------|
| **Date**        | 2026-02-12 |
| **Severity**    | High |
| **Status**      | Fixed |
| **Branch**      | `feat/three-tier-memory-phase1` |
| **PR**          | #7 |
| **Commit**      | N/A |

**Symptom:** Day memory entries from previous days could appear in "Earlier today" recall, contaminating conversation context with stale moments.

**Root Cause:** `get_day_memory()` and `get_unprocessed_day_memory()` in `db.py` had no date filter. Sleep only processes top-7 moments by salience, and `flush_day_memory()` only deletes processed rows. Unprocessed rows from previous days persisted indefinitely.

**Fix:** Added `_jst_today_start_utc()` helper that computes midnight JST in UTC. Both query functions now filter `AND ts >= ?` to scope results to the current JST day. Added `delete_stale_day_memory(max_age_days=2)` as a safety net, called during `flush_day_memory()` to clean up any rows older than 2 days regardless of processed status.

**Files Affected:**
- `db.py` — added `_jst_today_start_utc()`, date filter on both queries, `delete_stale_day_memory()`
- `sleep.py` — `flush_day_memory()` now calls `delete_stale_day_memory()`

**Tests Added:**
- [ ] Verify yesterday's day_memory excluded from `get_day_memory()`
- [ ] Verify stale rows cleaned up by `delete_stale_day_memory()`

**Follow-ups / Notes:**
- Found by Codex review of PR #7. P1 severity — incorrect temporal context in conversations.
---

### BUG-2026-02-12-explicit-commit-inside-transaction

| Field           | Value |
|-----------------|-------|
| **Date**        | 2026-02-12 |
| **Severity**    | High |
| **Status**      | Fixed |
| **Branch**      | `feat/three-tier-memory-phase1` |
| **PR**          | #7 |
| **Commit**      | N/A |

**Symptom:** `insert_day_memory()` could prematurely commit an outer transaction if called within a nested `async with transaction()` block.

**Root Cause:** The function called `await conn.commit()` explicitly inside `async with transaction()`. The `transaction().__aexit__` already handles commit/rollback. An explicit commit could finalize work from an enclosing transaction prematurely.

**Fix:** Removed `await conn.commit()`, replaced with comment noting that commit is handled by `transaction().__aexit__`.

**Files Affected:**
- `db.py` — removed explicit `conn.commit()` from `insert_day_memory()`

**Tests Added:**
- [ ] Verify no explicit `commit()` calls inside `async with transaction()` blocks

**Follow-ups / Notes:**
- Found by Codex re-review. Currently `insert_day_memory()` is only called from `maybe_record_moment()` which has no outer transaction, but the fix prevents future breakage.
---

### BUG-2026-02-12-had-contradiction-timing-note

| Field           | Value |
|-----------------|-------|
| **Date**        | 2026-02-12 |
| **Severity**    | Low |
| **Status**      | Fixed |
| **Branch**      | `feat/three-tier-memory-phase1` |
| **PR**          | #7 |
| **Commit**      | N/A |

**Symptom:** Codex flagged that `had_contradiction` signal in `_build_cycle_context()` might never fire because `internal_shift_candidate` events are emitted during the same cycle's execution, after unread was fetched.

**Root Cause:** `internal_shift_candidate` is emitted by `hippocampus_consolidate()` during `execute()`, but `unread` is fetched at cycle start. The event appears in the *next* cycle's unread, not the current one.

**Fix:** Analysis confirmed the signal works correctly — it fires one cycle late, boosting the salience of the follow-up moment. This is acceptable because the follow-up cycle is contextually adjacent. Added explanatory comment documenting this intentional timing behavior.

**Files Affected:**
- `heartbeat.py` — added timing comment on `had_contradiction` check

**Tests Added:**
- [ ] Code review verification only

**Follow-ups / Notes:**
- Found by Codex review of PR #7. The behavior is by-design, not a bug. Comment prevents future confusion.
---

### BUG-2026-02-12-insert-day-memory-non-atomic

| Field           | Value |
|-----------------|-------|
| **Date**        | 2026-02-12 |
| **Severity**    | Low |
| **Status**      | Fixed |
| **Branch**      | `feat/three-tier-memory-phase1` |
| **PR**          | #7 |
| **Commit**      | N/A |

**Symptom:** Under theoretical concurrent inserts, `day_memory` table could exceed the 30-row cap by 1-2 rows.

**Root Cause:** `insert_day_memory()` did count → evict → insert as 3 separate `_exec_write` calls. Two concurrent inserts could both see count=30, both evict, then both insert.

**Fix:** Wrapped count + evict + insert in a single `async with transaction()` block using `conn.execute()` directly (not `_exec_write()` which acquires its own lock).

**Files Affected:**
- `db.py` — `insert_day_memory()` now uses transaction for atomicity

**Tests Added:**
- [ ] Verify count never exceeds 30 under rapid inserts

**Follow-ups / Notes:**
- Found by Codex review of PR #7. Low severity — soft cap overshoot is brief and harmless.
---

### BUG-2026-02-12-sleep-date-filter-drops-waking-period

| Field           | Value |
|-----------------|-------|
| **Date**        | 2026-02-12 |
| **Severity**    | Critical |
| **Status**      | Fixed |
| **Branch**      | `feat/three-tier-memory-phase1` |
| **PR**          | #7 |
| **Commit**      | N/A |

**Symptom:** Sleep consolidation at 03:00 JST dropped most moments from the prior waking period. Only moments from 00:00–03:00 JST were included.

**Root Cause:** `get_unprocessed_day_memory()` filtered `ts >= _jst_today_start_utc()` (midnight JST). At 03:00 JST, this excluded the entire prior day's moments (06:00–23:59 JST), which span the previous calendar day. The shopkeeper's waking period crosses midnight.

**Fix:** Removed the JST date filter from `get_unprocessed_day_memory()` — sleep should consolidate ALL unprocessed moments regardless of calendar day. The `delete_stale_day_memory(max_age_days=2)` safety net prevents unbounded accumulation. The date filter remains on `get_day_memory()` (waking-hours recall) where "Earlier today" semantics are correct.

**Files Affected:**
- `db.py` — removed date filter from `get_unprocessed_day_memory()`

**Tests Added:**
- [ ] Verify moments from 18:00 JST (previous day) included in sleep consolidation at 03:00 JST

**Follow-ups / Notes:**
- Found by Codex re-review of the fix commit. The original P1 fix was too aggressive — date filter was correct for waking recall but wrong for overnight consolidation.
---

### BUG-2026-02-12-sleep-deferral-starves-microcycles

| Field           | Value |
|-----------------|-------|
| **Date**        | 2026-02-12 |
| **Severity**    | Critical |
| **Status**      | Fixed |
| **Branch**      | `feat/three-tier-memory-phase1` |
| **PR**          | #7 |
| **Commit**      | N/A |

**Symptom:** During 03:00–06:00 JST, if the shopkeeper was engaged in conversation, the heartbeat loop entered an infinite tight loop calling `sleep_cycle()` → getting `False` (deferred) → `continue` → back to sleep check. Visitor microcycles (messages) were never processed for up to 3 hours.

**Root Cause:** The sleep check (`_should_sleep()`) was the first branch in the `while self.running` loop at `heartbeat.py:232`. When sleep deferred, the `continue` at line 247 looped back to the top, hitting the sleep check again immediately. The microcycle check at lines 249–260 was unreachable.

**Fix:** Restructured the loop to check microcycles FIRST, before sleep. Microcycles now have unconditional top priority. The sleep window idle block was simplified since microcycles are handled above it.

**Files Affected:**
- `heartbeat.py` — reordered loop: microcycle → sleep → sleep-window-idle → autonomous

**Tests Added:**
- [ ] Verify microcycle runs during 03:00–06:00 when engaged
- [ ] Verify sleep still executes when no microcycle pending

**Follow-ups / Notes:**
- Found by Codex review of PR #7. P0 severity — could stall active conversations for hours.
---

### BUG-2026-02-12-sleep-dispatch-stamps-before-run

| Field           | Value |
|-----------------|-------|
| **Date**        | 2026-02-12 |
| **Severity**    | High |
| **Status**      | Fixed |
| **Branch**      | `feat/three-tier-memory-phase1` |
| **PR**          | N/A |
| **Commit**      | N/A |

**Symptom:** If the sleep cycle was deferred (visitor engaged at 03:00 JST) or crashed, `_last_sleep_date` was already stamped, consuming the entire night's sleep window with no retry.

**Root Cause:** `heartbeat.py` set `_last_sleep_date` BEFORE calling `sleep_cycle()`. The stamp was unconditional — deferral and exceptions both left it set.

**Fix:** Moved `_last_sleep_date` assignment to AFTER `sleep_cycle()` returns `True`. Deferral (`False`) and exceptions no longer stamp, allowing retry on the next heartbeat iteration within the 03:00-06:00 window.

**Files Affected:**
- `heartbeat.py` — moved `_last_sleep_date` assignment inside success branch

**Tests Added:**
- [ ] Verify `_last_sleep_date` not set when `sleep_cycle()` returns False
- [ ] Verify `_last_sleep_date` not set when `sleep_cycle()` raises

**Follow-ups / Notes:**
- Discovered during three-tier memory implementation. The new `sleep_cycle()` returns `bool` (True=ran, False=deferred), making this fix natural.
---

### BUG-2026-02-12-sleep-returns-true-on-all-fail

| Field           | Value |
|-----------------|-------|
| **Date**        | 2026-02-12 |
| **Severity**    | Medium |
| **Status**      | Fixed |
| **Branch**      | `feat/three-tier-memory-phase1` |
| **PR**          | #7 |
| **Commit**      | N/A |

**Symptom:** If all moment reflections failed during sleep (e.g. API outage), `sleep_cycle()` still returned `True`, stamping `_last_sleep_date` and preventing retry until the next day.

**Root Cause:** The function returned `True` unconditionally after the moment loop, regardless of how many moments were actually processed. `all_reflections` being empty didn't change the return value.

**Fix:** Added `processed_count` tracker. If moments existed but zero were processed successfully, return `False` to allow retry within the same sleep window. Poison-skipped moments count as "handled" to prevent infinite retry loops.

**Files Affected:**
- `sleep.py` — added `processed_count` tracking and early `return False` on all-fail

**Tests Added:**
- [ ] Verify `sleep_cycle()` returns False when all moments raise
- [ ] Verify poison-skipped moments still allow completion

**Follow-ups / Notes:**
- Found by Codex review of PR #7. Medium severity — missed consolidation until next day.
### BUG-2026-02-12-thread-update-empty-string-swallowed

| Field           | Value |
|-----------------|-------|
| **Date**        | 2026-02-12 |
| **Severity**    | Medium |
| **Status**      | Fixed |
| **Branch**      | `fix/codex-review-living-loop` |
| **PR**          | N/A |
| **Commit**      | N/A |

**Symptom:** If the LLM output `"content": ""` to clear a thread's content, the empty string was silently swallowed and the old content persisted.

**Root Cause:** The `or` fallback pattern (`content.get('content') or content.get('new_content')`) treats empty string as falsy, falling through to the legacy field name or `None`. Meanwhile, `db.touch_thread()` explicitly checks `if content is not None`, so `""` is a valid "clear this field" value.

**Fix:** Switched from `or` fallback to key-presence checks: `content.get('content') if 'content' in content else content.get('new_content')`. This preserves empty strings while still falling through to legacy field names when the key is absent.

**Files Affected:**
- `pipeline/hippocampus_write.py` — key-presence checks for reason, content, status fields

**Tests Added:**
- [ ] Unit test: `{"content": ""}` clears thread content
- [ ] Unit test: absent key falls through to legacy field name

**Follow-ups / Notes:**
- Found by Codex review (suggestion). Also applies to `reason` and `status` fields.

---

### BUG-2026-02-12-event-outcome-vocabulary-mismatch

| Field           | Value |
|-----------------|-------|
| **Date**        | 2026-02-12 |
| **Severity**    | Medium |
| **Status**      | Fixed |
| **Branch**      | `fix/codex-review-living-loop` |
| **PR**          | N/A |
| **Commit**      | N/A |

**Symptom:** Executor wrote pool status names (`accepted`, `reflected`) to `events.outcome`, but the model and spec define event outcomes as `engaged | ignored | expired`. The two vocabularies were conflated.

**Root Cause:** When implementing pool↔event coupling (Fix #4), the `outcome` variable (pool status) was passed directly to `update_event_outcome()` instead of using the spec's event outcome vocabulary.

**Fix:** Always write `'engaged'` to `events.outcome` — the spec value for "this perception event was acted upon". Pool-level detail (`accepted`/`reflected`) is already captured in `content_pool.status`. Also clarified the `models/event.py` outcome comment.

**Files Affected:**
- `pipeline/executor.py` — write `'engaged'` instead of pool status to event outcome
- `models/event.py` — clarified outcome comment to reference content_pool.status

**Tests Added:**
- [ ] Unit test: event outcome is always 'engaged', never 'accepted'/'reflected'

**Follow-ups / Notes:**
- Found by manual diff review after Codex review fixes.

---

### BUG-2026-02-12-migration-runner-drops-ddl

| Field           | Value |
|-----------------|-------|
| **Date**        | 2026-02-12 |
| **Severity**    | Critical |
| **Status**      | Fixed |
| **Branch**      | `fix/codex-review-living-loop` |
| **PR**          | N/A |
| **Commit**      | N/A |

**Symptom:** Migration SQL files starting with a `-- comment` line had their first `CREATE TABLE` statement silently dropped, leaving tables uncreated.

**Root Cause:** `sql.split(';')` produces segments like `"-- comment\nCREATE TABLE..."`. After `.strip()`, the segment starts with `--`, so `startswith('--')` skipped the entire segment — including the DDL below the comment.

**Fix:** Strip comment-only lines from each segment before checking emptiness. Each line starting with `--` is removed, then the remaining text is checked. This preserves inline comments while correctly executing multi-line segments that have leading comments.

**Files Affected:**
- `db.py` — rewrote migration statement parsing to strip comment lines per-segment

**Tests Added:**
- [ ] Unit test: migration file with leading comment executes CREATE TABLE
- [ ] Regression test: pure comment-only segments are still skipped

**Follow-ups / Notes:**
- Found by Codex review (P0). All 3 migration files (001, 003, 004) start with comments and were affected.

---

### BUG-2026-02-12-creative-cooldown-kills-thread-focus

| Field           | Value |
|-----------------|-------|
| **Date**        | 2026-02-12 |
| **Severity**    | High |
| **Status**      | Fixed |
| **Branch**      | `fix/codex-review-living-loop` |
| **PR**          | N/A |
| **Commit**      | N/A |

**Symptom:** Arbiter thread focus cycles were silently downgraded from `express` to `idle`, preventing the shopkeeper from ever working on her threads during creative cooldown.

**Root Cause:** Arbiter sets `routing.cycle_type = 'express'` for thread focus. The creative cooldown gate then unconditionally overrides express→idle. Thread focus was killed every time creative cooldown was active.

**Fix:** Added `and not focus_context` guard to the creative cooldown gate, so arbiter-directed express cycles are preserved.

**Files Affected:**
- `heartbeat.py` — added focus_context exception to creative cooldown gate

**Tests Added:**
- [ ] Unit test: thread focus express survives creative cooldown
- [ ] Regression test: non-arbiter express still blocked by cooldown

**Follow-ups / Notes:**
- Found by Codex review (P1).

---

### BUG-2026-02-12-sleep-thread-lifecycle-crash

| Field           | Value |
|-----------------|-------|
| **Date**        | 2026-02-12 |
| **Severity**    | High |
| **Status**      | Fixed |
| **Branch**      | `fix/codex-review-living-loop` |
| **PR**          | N/A |
| **Commit**      | N/A |

**Symptom:** Sleep cycle crashed with `TypeError` when trying to manage thread lifecycle, preventing thread dormancy transitions.

**Root Cause:** Caller used `older_than_days=2` but `db.get_dormant_threads()` signature expects `older_than_hours: int = 48`. Python raised TypeError on the unexpected keyword argument.

**Fix:** Changed to `older_than_hours=48` to match the function signature.

**Files Affected:**
- `sleep.py` — fixed kwarg name in `manage_thread_lifecycle()`

**Tests Added:**
- [ ] Unit test: `manage_thread_lifecycle()` runs without TypeError
- [ ] Regression test: dormant threads are correctly identified

**Follow-ups / Notes:**
- Found by Codex review (P1). Would have crashed on every sleep cycle.

---

### BUG-2026-02-12-pool-event-outcome-coupling

| Field           | Value |
|-----------------|-------|
| **Date**        | 2026-02-12 |
| **Severity**    | High |
| **Status**      | Fixed |
| **Branch**      | `fix/codex-review-living-loop` |
| **PR**          | N/A |
| **Commit**      | N/A |

**Symptom:** When the shopkeeper consumed content and added it to her collection or reflected on it, the content_pool status was updated but the linked event's `outcome` and `engaged_at` fields were never set.

**Root Cause:** Executor updated `content_pool.status` but had no code to propagate the outcome back to the source event via `events.outcome` / `events.engaged_at`.

**Fix:** Added `db.update_event_outcome()` function. Executor now sets `engaged_at=now` on pool updates and looks up the pool item's `source_event_id` to also update the linked event.

**Files Affected:**
- `db.py` — added `update_event_outcome()` function
- `pipeline/executor.py` — added engaged_at to pool updates, added event outcome coupling

**Tests Added:**
- [ ] Unit test: pool acceptance propagates outcome to source event
- [ ] Regression test: pool items without source_event_id don't crash

**Follow-ups / Notes:**
- Found by Codex review (P1). Spec §3.4 requires both sides to be updated together.

---

### BUG-2026-02-12-thread-id-format-parens

| Field           | Value |
|-----------------|-------|
| **Date**        | 2026-02-12 |
| **Severity**    | Medium |
| **Status**      | Fixed |
| **Branch**      | `fix/codex-review-living-loop` |
| **PR**          | N/A |
| **Commit**      | N/A |

**Symptom:** Thread IDs in the THINGS ON MY MIND section used parentheses `(id:X)` instead of brackets `[id:X]`, reducing LLM round-trip parsing reliability.

**Root Cause:** Format string used parentheses. Spec requires square brackets for reliable parsing.

**Fix:** Changed `(id:{t.id})` to `[id:{t.id}]` in the cortex prompt builder.

**Files Affected:**
- `pipeline/cortex.py` — fixed thread ID format string

**Tests Added:**
- [ ] Unit test: thread context uses bracket format

**Follow-ups / Notes:**
- Found by Codex review (P2).

---

### BUG-2026-02-12-thread-update-field-mismatch

| Field           | Value |
|-----------------|-------|
| **Date**        | 2026-02-12 |
| **Severity**    | Medium |
| **Status**      | Fixed |
| **Branch**      | `fix/codex-review-living-loop` |
| **PR**          | N/A |
| **Commit**      | N/A |

**Symptom:** Thread updates from Cortex were silently lost — the LLM emitted `content` + `reason` + `status` fields but the handler read `new_content` + `touch_reason` + `new_status`.

**Root Cause:** Schema mismatch between Cortex output (which uses `content`, `reason`, `status`) and hippocampus_write handler (which expected `new_content`, `touch_reason`, `new_status`).

**Fix:** Added fallback reads: `content.get('reason') or content.get('touch_reason', ...)` etc., so both field naming conventions work.

**Files Affected:**
- `pipeline/hippocampus_write.py` — added fallback field reads in thread_update handler

**Tests Added:**
- [ ] Unit test: thread_update with `reason` field works
- [ ] Unit test: thread_update with `touch_reason` field works (backward compat)

**Follow-ups / Notes:**
- Found by Codex review (P2). Silent data loss — no error raised, fields just came through as None.

---

### BUG-2026-02-12-novelty-penalty-hard-gate

| Field           | Value |
|-----------------|-------|
| **Date**        | 2026-02-12 |
| **Severity**    | Medium |
| **Status**      | Fixed |
| **Branch**      | `fix/codex-review-living-loop` |
| **PR**          | N/A |
| **Commit**      | N/A |

**Symptom:** Spec says novelty penalty should "reduce by 0.3" but implementation used a hard gate at all priority slots, including the final slot for each channel. At the last slot (e.g. P5 LRU thread), the hard gate eliminated the candidate entirely instead of deprioritizing it.

**Root Cause:** All 3 novelty penalty call sites used `if penalty < 0.3: return focus`, which was correct for higher-priority slots (candidate falls through to a lower slot) but wrong for the final slot (candidate is eliminated with no fallback).

**Fix:** Removed the novelty gate at P5 (LRU thread) — the last thread slot. P6 (low-salience news) already had no gate. Updated `_novelty_penalty` docstring to explain waterfall semantics: higher slots gate to skip/deprioritize, final slots omit the gate so candidates are still selected.

**Files Affected:**
- `pipeline/arbiter.py` — removed novelty gate at P5 LRU thread, updated docstring

**Tests Added:**
- [ ] Unit test: repetitive thread still selected at P5 when P2 skips it

**Follow-ups / Notes:**
- Found by Codex review (P2). Initial fix was docstring-only; updated to behavioral fix after manual review.

---

### BUG-2026-02-12-missing-requirements-txt

| Field           | Value |
|-----------------|-------|
| **Date**        | 2026-02-12 |
| **Severity**    | Medium |
| **Status**      | Fixed |
| **Branch**      | `fix/codex-review-living-loop` |
| **PR**          | N/A |
| **Commit**      | N/A |

**Symptom:** No dependency declaration file existed, forcing manual discovery of required packages.

**Root Cause:** `requirements.txt` was never created during initial development.

**Fix:** Created `requirements.txt` with runtime deps: `aiosqlite`, `anthropic` (required), `aiohttp`, `feedparser`, `colorama` (optional, with comments explaining graceful degradation).

**Files Affected:**
- `requirements.txt` — new file

**Tests Added:**
- [ ] N/A (config file)

**Follow-ups / Notes:**
- Found by Codex review (P2). Optional deps are imported inside functions with try/except.

---

### BUG-2026-02-12-max-pool-unseen-not-wired

| Field           | Value |
|-----------------|-------|
| **Date**        | 2026-02-12 |
| **Severity**    | Low |
| **Status**      | Fixed |
| **Branch**      | `fix/codex-review-living-loop` |
| **PR**          | N/A |
| **Commit**      | N/A |

**Symptom:** `MAX_POOL_UNSEEN` config value (50) defined in `config/feeds.py` but never used — `cap_unseen_pool()` was called with its default (also 50).

**Root Cause:** Config import was missing at both call sites.

**Fix:** Imported `MAX_POOL_UNSEEN` from `config.feeds` and passed it to `cap_unseen_pool()` in both `heartbeat.py` and `sleep.py`.

**Files Affected:**
- `heartbeat.py` — import and pass MAX_POOL_UNSEEN
- `sleep.py` — import and pass MAX_POOL_UNSEEN

**Tests Added:**
- [ ] Unit test: changing MAX_POOL_UNSEEN config affects cap behavior

**Follow-ups / Notes:**
- Found by Codex review (P3). Currently no-op since default matches config, but wiring prevents silent divergence if config changes.

---

### BUG-2026-02-13-simulation-api-timeout-hang

| Field           | Value |
|-----------------|-------|
| **Date**        | 2026-02-13 |
| **Severity**    | Critical |
| **Status**      | Fixed |
| **Branch**      | `fix/cortex-api-timeout-hang` |
| **PR**          | #18 |
| **Commit**      | `590249e` |

**Symptom:** Simulation hangs indefinitely after ~0.5 simulated days (57 cycles, 1hr 3min wall time). Process freezes at Day 1 19:26 JST with 6 TCP connections stuck in CLOSE_WAIT to Anthropic API. 99.8% wait time, 0.1% CPU, no errors logged, no recovery.

**Root Cause:** Four compounding issues: (1) Exception handlers only catch 4 specific types, missing `anthropic.APIError` base class, `httpx.TimeoutException`, and generic `Exception`. (2) Synchronous `client.messages.create()` called from async functions blocks the entire event loop — no other coroutines can run while waiting. (3) `timeout=30.0` on the client is per-socket-operation, not per-request; stuck connections can wait forever. (4) New `Anthropic()` client created every call, leaking connections in CLOSE_WAIT state.

**Fix:** Five changes to `pipeline/cortex.py`:
1. Singleton async client via `_get_client()` — reuses one `anthropic.AsyncAnthropic` instance, prevents connection pool exhaustion.
2. Native async `await client.messages.create()` — replaces sync call, no event loop blocking, true cancellation on timeout.
3. `asyncio.wait_for(..., timeout=60.0)` — hard 60-second ceiling per request, cancels the underlying httpx request (not just an orphaned thread).
4. Broader exception handling — catches `anthropic.APIError` (base), `httpx.TimeoutException`, and generic `Exception` as final safety net.
5. Logging — prints `[Cortex]` markers for API call start/finish/error to track where hangs occur.

**Files Affected:**
- `pipeline/cortex.py` — singleton client, async wrapping, broadened exceptions, logging at both `cortex_call` and `cortex_call_maintenance`

**Tests Added:**
- [ ] Manual test: simulation runs past 1 hour without hanging
- [x] Test: API timeout triggers fallback response within 60s (`test_cortex_call_timeout_returns_fallback`, `test_maintenance_call_timeout_returns_fallback`)
- [x] Test: connection reuse (single client instance across calls) (`test_singleton_client_reused`)
- [x] Soak: 200 cycles with mixed success/timeout/error patterns (`test_soak_200_cycles_no_leak_no_hang`)
- [x] Soak: 50 maintenance cycles with intermittent failures (`test_soak_maintenance_50_cycles`)
- [x] Exception handling: APIError, httpx.TimeoutException, generic Exception
- [x] Circuit breaker opens after consecutive failures

**Follow-ups / Notes:**
- Now uses `anthropic.AsyncAnthropic` (available in `anthropic==0.79.0`) for true cancellable async — no orphaned threads on timeout.
- Simulation data from before the hang was valid (3 items consumed, 2 threads, 46 journal entries, 3 totems, 4 collection items).

---

### BUG-2026-02-12-canonical-identity-contradiction

| Field           | Value |
|-----------------|-------|
| **Date**        | 2026-02-12 |
| **Severity**    | Medium |
| **Status**      | Fixed |
| **Branch**      | `fix/engagement-state-and-sanitization` |
| **PR**          | #4 |
| **Commit**      | N/A |

**Symptom:** Shopkeeper could deny canonical physical traits (e.g. "I don't wear glasses") because Cortex hallucinated and validator had no guardrail.

**Root Cause:** `validator.py` had no check against stable identity traits from `IDENTITY_COMPACT`. The LLM could contradict established physical appearance.

**Fix:** Added `CANONICAL_TRAITS` list with denial-pattern regexes and a `canonical_consistency_check()` stage in `validate()`. Contradicting dialogue is flagged via `_canonical_contradiction`. Codex review improved this: regex broadened to catch uncontracted "I do not" forms, and sentence-level removal preserves valid dialogue instead of blanking to `'...'`.

**Files Affected:**
- `pipeline/validator.py` — added canonical trait patterns, consistency check stage, sentence-level removal

**Tests Added:**
- [ ] Unit test covering denial patterns (glasses, height)
- [ ] Regression test: dialogue contradicting glasses → offending sentence removed, rest preserved

**Follow-ups / Notes:**
- Only covers glasses and height for now. Extend `CANONICAL_TRAITS` as more stable traits are established.
- Does not cover subtle contradictions ("my eyes are fine") — only explicit denials.
- Known false positive: third-person speech like "she doesn't wear glasses" would be flagged.

---

### BUG-2026-02-12-port-conflict-traceback

| Field           | Value |
|-----------------|-------|
| **Date**        | 2026-02-12 |
| **Severity**    | Low |
| **Status**      | Fixed |
| **Branch**      | `fix/engagement-state-and-sanitization` |
| **PR**          | #4 |
| **Commit**      | N/A |

**Symptom:** Starting `heartbeat_server.py` when port 9999 was already in use produced a raw Python traceback with no recovery guidance.

**Root Cause:** `asyncio.start_server()` at line 65 had no `try/except` for `OSError`/`EADDRINUSE`.

**Fix:** Wrapped `start_server` in `try/except OSError`, prints friendly error with `lsof` hint, then cleanly shuts down heartbeat and DB before returning. Codex review improved this: replaced hardcoded errno `48` (macOS-only) with portable `errno.EADDRINUSE` constant.

**Files Affected:**
- `heartbeat_server.py` — added port conflict handling around `start_server`, portable errno

**Tests Added:**
- [ ] Manual test: start two instances, second prints friendly error
- [ ] Regression test: no traceback on `EADDRINUSE`

**Follow-ups / Notes:**
- Could add auto-retry on a different port, but explicit failure is better for now.

---

### BUG-2026-02-12-ansi-control-chars-in-memory

| Field           | Value |
|-----------------|-------|
| **Date**        | 2026-02-12 |
| **Severity**    | Medium |
| **Status**      | Fixed |
| **Branch**      | `fix/engagement-state-and-sanitization` |
| **PR**          | #4 |
| **Commit**      | N/A |

**Symptom:** Terminal escape sequences (arrow keys producing `^[[A`, etc.) leaked into `conversation_log` and could appear in Cortex prompt context.

**Root Cause:** `terminal.py` only called `.strip()` on input, and `heartbeat_server.py` passed raw `msg.get('text')` directly to DB. No ANSI/control character sanitization.

**Fix:** Created `pipeline/sanitize.py` with `sanitize_input()` that strips ANSI escape sequences and control characters. Applied at both intake boundaries: `terminal.py` (client + standalone modes) and `heartbeat_server.py`. Codex review improved this: extended regex to cover C1 control range (`\x7f-\x9f`) and `\x9b` CSI variant, preventing terminal injection via non-ESC CSI sequences.

**Files Affected:**
- `pipeline/sanitize.py` — new module, ANSI + C1 control char stripping
- `terminal.py` — sanitize at both input paths
- `heartbeat_server.py` — sanitize at speech intake

**Tests Added:**
- [ ] Unit test: `^[[A` stripped from input
- [ ] Unit test: normal text preserved
- [ ] Regression test: control chars never reach `conversation_log`

**Follow-ups / Notes:**
- Drop command content (`drop <text>`) is not sanitized — could be a follow-up.

---

### BUG-2026-02-12-stale-conversation-on-connect

| Field           | Value |
|-----------------|-------|
| **Date**        | 2026-02-12 |
| **Severity**    | High |
| **Status**      | Fixed |
| **Branch**      | `fix/engagement-state-and-sanitization` |
| **PR**          | #4 |
| **Commit**      | N/A |

**Symptom:** On reconnect, shopkeeper immediately referenced topics from the previous session (e.g. "New York" appearing on first connect cycle) because old conversation was loaded into Cortex prompt.

**Root Cause:** `db.get_recent_conversation()` fetched last 10 messages from `conversation_log` with no session scoping. On `visitor_connect`, old messages from previous visits leaked into the Cortex context.

**Fix:** Added `db.mark_session_boundary()` which inserts a `__session_boundary__` marker row. Updated `get_recent_conversation()` to only return messages after the most recent boundary. Both `heartbeat_server.py` and `terminal.py` now call `mark_session_boundary()` on connect.

**Files Affected:**
- `db.py` — added `mark_session_boundary()`, updated `get_recent_conversation()` to scope by session
- `heartbeat_server.py` — calls `mark_session_boundary` on connect
- `terminal.py` — calls `mark_session_boundary` on connect

**Tests Added:**
- [ ] Unit test: messages before boundary are excluded
- [ ] Unit test: first session (no boundary) returns all messages
- [ ] Regression test: no old topic carryover on reconnect

**Follow-ups / Notes:**
- Old conversation is still in DB for memory/sleep consolidation. Only Cortex prompt context is scoped.

---

### BUG-2026-02-12-end-engagement-state-collision

| Field           | Value |
|-----------------|-------|
| **Date**        | 2026-02-12 |
| **Severity**    | High |
| **Status**      | Fixed |
| **Branch**      | `fix/engagement-state-and-sanitization` |
| **PR**          | #4 |
| **Commit**      | N/A |

**Symptom:** When shopkeeper ended a conversation, engagement state was briefly set to `engaged` (with turn count incremented) before `end_engagement` action set it to `cooldown`. Dirty state could cause next-cycle confusion.

**Root Cause:** In `executor.py`, the engagement update block (lines 70-79) unconditionally set `status='engaged'` and incremented turn count whenever dialogue existed with a visitor. This fired even when `end_engagement` was in the approved actions list, writing `engaged` before the action handler wrote `cooldown`.

**Fix:** Added an `ending` guard that checks if `end_engagement` is in `_approved_actions`. When true, the engagement update block is skipped entirely — no spurious `engaged` write, no turn count increment on farewell.

**Files Affected:**
- `pipeline/executor.py` — guarded engagement update with `ending` check

**Tests Added:**
- [ ] Unit test: `end_engagement` approved → no `engaged` write
- [ ] Regression test: cooldown persists after `end_engagement`

**Follow-ups / Notes:**
- The actual "undo" was mitigated by execution order (cooldown wrote second), but the dirty intermediate state and unnecessary turn increment were real bugs.

---

### BUG-2025-02-12-fidget-mismatch-hijacks-routing

| Field           | Value |
|-----------------|-------|
| **Date**        | 2025-02-12 |
| **Severity**    | High |
| **Status**      | Fixed |
| **Branch**      | `fix/memory-identity-fidgets-journal` |
| **PR**          | #3 |
| **Commit**      | `453422d` |

**Symptom:** `fidget_mismatch` perception (salience 0.7) outranked `visitor_speech` (salience 0.5–0.6), becoming cycle focus. Since `route()` had no branch for `fidget_mismatch`, cycles fell through to drive-based routing (idle/rest/express), causing engaged conversations to be processed as non-engaged.

**Root Cause:** Two issues: (1) `fidget_mismatch` salience was 0.7, higher than typical speech. (2) `thalamus.route()` had no explicit branch for `fidget_mismatch`, so it fell to drive-based default.

**Fix:**
- Lowered `fidget_mismatch` salience from 0.7 to 0.4 so it augments speech as background context rather than replacing it as focus.
- Added explicit `fidget_mismatch` → `engage` branch in `thalamus.route()` as a safety net.

**Files Affected:**
- `pipeline/sensorium.py` — lowered fidget_mismatch salience to 0.4
- `pipeline/thalamus.py` — added fidget_mismatch routing branch

**Tests Added:**
- [ ] No test infrastructure in repo yet

**Follow-ups / Notes:**
- Found by Codex review. Confidence 0.97.

---

### BUG-2025-02-12-memory-update-errors-permanently-lost

| Field           | Value |
|-----------------|-------|
| **Date**        | 2025-02-12 |
| **Severity**    | Medium |
| **Status**      | Fixed |
| **Branch**      | `fix/memory-identity-fidgets-journal` |
| **PR**          | #3 |
| **Commit**      | `453422d` |

**Symptom:** Memory consolidation errors were logged to console but not persisted. Since the cycle then marks inbox events as read, transient DB/runtime failures in memory writes became permanent data loss with no replay path.

**Root Cause:** Per-update `try/except` only logged `type+message` to stdout. No durable record was created, and the cycle committed normally afterward.

**Fix:** Failed memory updates now emit a `memory_consolidation_failed` event via `db.append_event()`, preserving the original update payload, error details, and visitor_id in the append-only event log for diagnosis and potential retry.

**Files Affected:**
- `pipeline/executor.py` — emit event on memory consolidation failure

**Tests Added:**
- [ ] No test infrastructure in repo yet

**Follow-ups / Notes:**
- A future retry mechanism could read `memory_consolidation_failed` events and re-attempt consolidation.
- Found by Codex review. Confidence 0.91.

---

### BUG-2025-02-12-fidget-ring-no-recency-check

| Field           | Value |
|-----------------|-------|
| **Date**        | 2025-02-12 |
| **Severity**    | Low |
| **Status**      | Fixed |
| **Branch**      | `fix/memory-identity-fidgets-journal` |
| **PR**          | #3 |
| **Commit**      | `453422d` |

**Symptom:** Fidget ring stored `(behavior, description, ts)` tuples but matching ignored the timestamp. In low-fidget periods, stale fidgets from much earlier could trigger mismatch perceptions.

**Root Cause:** `check_fidget_reference` iterated all entries in `recent_fidgets` without checking `ts` against current time.

**Fix:** Added a 5-minute (`FIDGET_RECENCY_SECONDS = 300`) time window. Fidgets older than 5 minutes are skipped during matching.

**Files Affected:**
- `pipeline/sensorium.py` — added time-window enforcement in `check_fidget_reference`

**Tests Added:**
- [ ] No test infrastructure in repo yet

**Follow-ups / Notes:**
- Found by Codex review. Confidence 0.82.
