# Bug & Fix Log

> All bugs discovered and fixes applied in this repository are documented here.
> Entries are in reverse chronological order (newest first).
> See `CLAUDE.md` §18 for the required format.

---

### BUG-2025-02-12-fidget-mismatch-hijacks-routing

| Field           | Value |
|-----------------|-------|
| **Date**        | 2025-02-12 |
| **Severity**    | High |
| **Status**      | Fixed |
| **Branch**      | `fix/memory-identity-fidgets-journal` |
| **PR**          | Pending |
| **Commit**      | Pending |

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
| **PR**          | Pending |
| **Commit**      | Pending |

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
| **PR**          | Pending |
| **Commit**      | Pending |

**Symptom:** Fidget ring stored `(behavior, description, ts)` tuples but matching ignored the timestamp. In low-fidget periods, stale fidgets from much earlier could trigger mismatch perceptions.

**Root Cause:** `check_fidget_reference` iterated all entries in `recent_fidgets` without checking `ts` against current time.

**Fix:** Added a 5-minute (`FIDGET_RECENCY_SECONDS = 300`) time window. Fidgets older than 5 minutes are skipped during matching.

**Files Affected:**
- `pipeline/sensorium.py` — added time-window enforcement in `check_fidget_reference`

**Tests Added:**
- [ ] No test infrastructure in repo yet

**Follow-ups / Notes:**
- Found by Codex review. Confidence 0.82.
