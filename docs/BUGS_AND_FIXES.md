# Bug & Fix Log

> All bugs discovered and fixes applied in this repository are documented here.
> Entries are in reverse chronological order (newest first).
> See `CLAUDE.md` §18 for the required format.

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
