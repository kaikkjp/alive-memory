# TASKS — The Shopkeeper

> **For AI agents:** Pick the first task with status `READY`. Do NOT skip ahead. Do NOT work on multiple tasks. See `CLAUDE.md` for the full protocol.
>
> **For the operator (Heo):** Add new tasks at the bottom. Set status to `READY` when you want an agent to pick it up. Only one task should be `READY` at a time unless you're intentionally running parallel non-overlapping scopes.

## Status Key

| Status | Meaning |
|--------|---------|
| `READY` | Next agent session should pick this up |
| `IN_PROGRESS` | An agent is currently working on this |
| `DONE` | Completed and merged |
| `BLOCKED` | Waiting on something (see notes) |
| `BACKLOG` | Planned but not ready to start |

---

## Task Queue

### TASK-001: Wire threads into window_state broadcast
**Status:** DONE (2026-02-14)
**Priority:** Low
**Description:** `window_state.py:129` has a TODO: threads are hardcoded to empty list. Wire up `db.get_active_threads()` and include in the WebSocket broadcast so the dashboard ThreadsPanel shows real data.
**Scope (files you may touch):**
- `window_state.py`
- `window/src/components/dashboard/ThreadsPanel.tsx` (if data shape changes)
- `window/src/lib/types.ts` (if TypeScript types need updating)
**Scope (files you may NOT touch):**
- `db.py` (thread functions already exist)
- `heartbeat_server.py`
- `heartbeat.py`
**Tests:** Add a test in `tests/test_window_state.py` (new file) verifying threads appear in broadcast payload.
**Definition of done:** ThreadsPanel shows live thread data from the running system.

---

### TASK-002: Split heartbeat_server.py HTTP routes into separate module
**Status:** BACKLOG
**Priority:** Medium
**Description:** `heartbeat_server.py` is 1092 lines mixing TCP, WebSocket, and HTTP concerns. Extract all `_http_dashboard_*` methods (lines 920-1070) into a new `api/dashboard_routes.py` module. The `ShopkeeperServer` class should delegate to it.
**Scope (files you may touch):**
- `heartbeat_server.py` (remove dashboard methods, add imports)
- `api/__init__.py` (new)
- `api/dashboard_routes.py` (new)
**Scope (files you may NOT touch):**
- `heartbeat.py`
- `db.py`
- `window/` (frontend unchanged — same HTTP endpoints)
**Tests:** Existing dashboard tests must still pass. Add `tests/test_dashboard_routes.py`.
**Definition of done:** All `_http_dashboard_*` methods live in `api/dashboard_routes.py`. Server delegates to them. All endpoints return identical responses.

---

### TASK-003: Split db.py into submodules
**Status:** BACKLOG
**Priority:** High (but risky — schedule when no other work is in flight)
**Description:** `db.py` is 2291 lines with 100+ functions. Split into:
- `db/__init__.py` — re-exports everything (backward compat)
- `db/connection.py` — get_db, close_db, transaction, migrations
- `db/events.py` — event store, inbox
- `db/state.py` — room_state, drives_state, engagement_state
- `db/memory.py` — journal, totems, collection, visitor traits, cold memory, day memory
- `db/content.py` — threads, content pool, feed items
- `db/analytics.py` — llm cost tracking, cycle logs, stats
**Scope (files you may touch):**
- `db.py` → `db/` directory (all new files)
**Scope (files you may NOT touch):**
- Everything else — the `db/__init__.py` re-exports must make this a zero-change refactor for all importers
**Tests:** `python -m pytest tests/ -v` — ALL existing tests must pass unchanged. No import changes anywhere else.
**Definition of done:** `db.py` is gone, replaced by `db/` package. `from db import get_db` still works. `import db; db.get_events_since(...)` still works. Zero changes to any other file.

---

### TASK-004: Add typed pipeline contracts
**Status:** DONE (2026-02-14)
**Priority:** Medium
**Description:** Pipeline stages pass data through dicts and implicit conventions. Define explicit dataclasses:
- `CortexInput` — what goes into the LLM call
- `CortexOutput` — what comes out (speech, body, internal_monologue, actions)
- `ValidatedOutput` — post-validation output
- `ExecutionResult` — what executor returns
**Scope (files you may touch):**
- `models/pipeline.py` (new — dataclass definitions)
- `pipeline/cortex.py` (return `CortexOutput` instead of dict)
- `pipeline/validator.py` (accept `CortexOutput`, return `ValidatedOutput`)
- `pipeline/executor.py` (accept `ValidatedOutput`, return `ExecutionResult`)
- `heartbeat.py` (update `run_cycle` to use typed objects)
**Scope (files you may NOT touch):**
- `db.py`
- `heartbeat_server.py`
- `window/`
**Tests:** Update `tests/test_validator.py` and `tests/test_cortex_timeout.py` to use new types. All tests pass.
**Definition of done:** Pipeline stages communicate through typed dataclasses. Breaking changes caught at import time, not at runtime.

---

### TASK-005: VPS deployment hardening
**Status:** DONE (2026-02-14)
**Priority:** High
**Description:** Finalize Docker + nginx + TLS deployment per `DEPLOY_VPS.md` spec. Ensure `docker-compose.yml` builds cleanly, nginx proxies WebSocket correctly, and TLS certs auto-renew.
**Scope (files you may touch):**
- `Dockerfile`
- `docker-compose.yml`
- `deploy/*`
- `nginx/*`
- `DEPLOY_VPS.md`
**Scope (files you may NOT touch):**
- All Python source
- `window/` (except `next.config.ts` if build config needs tweaking)
**Tests:** `docker compose build` succeeds. `docker compose up` starts server. WebSocket connects through nginx. Dashboard loads.
**Definition of done:** One-command deploy from a fresh Ubuntu 24 VPS.

---

### TASK-006: Post-merge documentation sweep
**Status:** BACKLOG (run after every other task)
**Priority:** Routine
**Description:** Run `python scripts/update_docs.py` and review ARCHITECTURE.md for accuracy. Update any module descriptions that have changed. Add any new files to the module map.
**Scope (files you may touch):**
- `ARCHITECTURE.md`
- `README.md` (if project structure section is outdated)
**Scope (files you may NOT touch):**
- All source code
**Tests:** N/A
**Definition of done:** ARCHITECTURE.md line counts match reality. All files in repo are documented. Dependency graph is accurate.

---

### TASK-007: Sleep tuning — reflective not summarizing
**Status:** DONE (2026-02-14)
**Priority:** Medium
**Depends on:** Nothing (standalone)
**Description:** Two changes to `sleep.py`:
1. Raise `MIN_SLEEP_SALIENCE` from 0.4 to 0.65. Day recording stays at 0.4 (wide net), but only the top moments get reflected on at night. This cuts LLM calls during sleep and focuses reflection on what actually mattered.
2. Each `sleep_reflect()` result writes its OWN journal entry (one per moment), instead of `write_daily_summary()` concatenating all reflections into one blob. The daily_summary record becomes a lightweight index (date, moment count, moment IDs, emotional arc) not a narrative.
**Scope (files you may touch):**
- `sleep.py` (threshold change, refactor `write_daily_summary()`)
- `db.py` — only `insert_daily_summary()` if the summary schema changes (add at END of file)
**Scope (files you may NOT touch):**
- `pipeline/day_memory.py` (day recording unchanged)
- `heartbeat.py`
- `pipeline/cortex.py`
**Tests:** Update `tests/test_sleep_cold_memory.py`. Verify: each moment produces its own journal entry. Daily summary contains moment IDs not concatenated text. Moments below 0.65 salience are not reflected on.
**Definition of done:** Sleep cycle produces N individual journal entries for N moments (not 1 blob). Daily summary is an index. Low-salience moments are recorded during the day but skipped at night.

---

### TASK-008: Body Phase 1 — Refactor (zero behavior change)
**Status:** DONE (2026-02-14)
**Priority:** High
**Depends on:** TASK-004 (typed pipeline contracts)
**Design doc:** `body-spec-v2.md` §10, Phase 1
**Description:** Split the current executor into the brain/body architecture without changing any behavior. This is pure structural refactoring.
- Create `pipeline/action_registry.py` — extract `ActionCapability` dataclass and `ACTION_REGISTRY` dict from executor.py. Currently enabled actions only (speak, journal_write, arrange_shelf, express_thought, end_engagement). Future actions listed but `enabled=False`.
- Create `pipeline/body.py` — move executor functions into `execute()` with `ActionResult` and `BodyOutput` dataclasses. Pure execution, no decision logic.
- Create `pipeline/basal_ganglia.py` — STUB that wraps the single implicit cortex action as a single-item `MotorPlan` and passes it through. All gates return approved. No filtering.
- Create `pipeline/output.py` — STUB that does what executor currently does post-action (drive adjustments, hippocampus_write call).
- Update `heartbeat.py` to call: Validator → Basal Ganglia → Body → Output.
- Deprecate `pipeline/executor.py` (keep file, add deprecation notice, import from new locations).
**Scope (files you may touch):**
- `pipeline/action_registry.py` (new)
- `pipeline/body.py` (new)
- `pipeline/basal_ganglia.py` (new)
- `pipeline/output.py` (new)
- `pipeline/executor.py` (deprecate, re-route imports)
- `heartbeat.py` (update `run_cycle` call chain)
- `models/pipeline.py` (add `MotorPlan`, `ActionDecision`, `ActionResult`, `BodyOutput`, `CycleOutput`)
**Scope (files you may NOT touch):**
- `pipeline/cortex.py` (still outputs same format)
- `pipeline/validator.py` (still same checks)
- `db.py`
- `heartbeat_server.py`
- `window/`
**Tests:** ALL existing tests pass with zero changes. Add `tests/test_body.py` and `tests/test_basal_ganglia.py` verifying stub passthrough produces identical results to old executor.
**Definition of done:** New pipeline stages exist and are wired in. Every existing behavior is identical. `simulate.py --cycles 10` produces same quality output.

---

### TASK-009: Body Phase 2 — Multi-intention + Basal Ganglia selection
**Status:** BACKLOG
**Priority:** High
**Depends on:** TASK-008
**Design doc:** `body-spec-v2.md` §2.2, §4, §10 Phase 2
**Description:** Cortex now outputs `intentions[]` with impulse strengths. Basal Ganglia selects which fire.
- Update cortex prompt in `prompt_assembler.py`: add "EXPRESS YOUR INTENTIONS" instruction, `intentions[]` schema with action/target/content/impulse.
- Basal Ganglia: implement Gates 1-5 (capability check, enabled check, prerequisites, cooldown, energy gating). No inhibition yet (Gate 6 is Phase 3).
- Suppression logging to `action_log` table.
- Output processing: drive adjustments from outcomes, suppressed high-impulse actions → `inject_self_reflection_seed()` for next cycle.
- Add `recent_suppressions` block to cortex prompt context in `prompt_assembler.py` so she can journal about "what I almost did."
- Migration: `migrations/010_body.sql` (action_log table only).
- Peek commands in `terminal.py`: `body`, `suppressed`, `action-log`.
**Scope (files you may touch):**
- `pipeline/basal_ganglia.py` (full implementation)
- `pipeline/output.py` (full implementation)
- `pipeline/action_registry.py` (add prerequisite checks)
- `pipeline/cortex.py` (parse new intentions[] format, backward compat with old format)
- `prompt_assembler.py` (add intentions instruction + recent_suppressions context)
- `heartbeat.py` (wire suppression seed injection)
- `db.py` (add action_log functions — at END of file)
- `migrations/010_body.sql` (new)
- `terminal.py` (add peek commands)
- `models/pipeline.py` (update if needed)
**Scope (files you may NOT touch):**
- `pipeline/sensorium.py`
- `pipeline/thalamus.py`
- `pipeline/hippocampus.py`
- `sleep.py`
- `window/` (no frontend changes yet)
**Tests:** Add `tests/test_basal_ganglia_selection.py`. Test: multi-intention input → strongest fires, others suppressed with reasons. Energy gating works. Cooldown enforcement works. Suppression log populated.
**Definition of done:** She expresses multiple wants per cycle. Strongest fires. Others logged as suppressed. She can journal about "I almost did X."

---

### TASK-010: Body Phase 3 — Inhibition + Metacognitive Monitor
**Status:** BACKLOG
**Priority:** High
**Depends on:** TASK-009
**Design doc:** `body-spec-v2.md` §2.2 (Inhibition System), plus new metacognitive monitor design
**Description:** Two systems that make her learn from experience and notice her own inconsistencies.

**Inhibition system (from body spec):**
- Gate 6 in Basal Ganglia: `check_inhibition()` — DB lookup against learned inhibitions.
- Output processing: `detect_negative_signal()` (visitor left quickly, cortex expressed regret), `detect_positive_signal()` (visitor responded, journal completed), `maybe_form_inhibition()`.
- Inhibition strength: +0.15 on negative signal, -0.1 on positive signal. Delete below 0.05.
- Inhibition seeds stored as structured data, not narrative templates. Cortex narrates them naturally.
- Migration: add `inhibitions` table to `010_body.sql`.

**Metacognitive monitor (new):**
- New component in `pipeline/output.py`: `check_self_consistency()`.
- After body executes, compare executed actions + cortex speech against `config/identity.py` voice rules and character-bible constraints.
- Divergences produce `internal_conflict` event → inbox with high salience.
- `pipeline/day_memory.py`: add `internal_conflict` as a moment type with salience boost (+0.4) so it always gets reflected on at night.
- `prompt_assembler.py`: inject recent internal conflicts into cortex context so she can process them during idle cycles.
- The validator stays format-only. It does NOT strip out-of-character behavior. The metacognitive monitor catches it after the fact.

**Validator change:**
- Remove character-rule enforcement from `pipeline/validator.py`. Keep format/schema checks only.
- Character rules move to metacognitive monitor as detection patterns (not gates).
**Scope (files you may touch):**
- `pipeline/basal_ganglia.py` (add Gate 6)
- `pipeline/output.py` (inhibition formation + metacognitive monitor)
- `pipeline/validator.py` (remove character rules, keep format checks)
- `pipeline/day_memory.py` (add `internal_conflict` moment type, salience boost)
- `prompt_assembler.py` (add recent_inhibitions + recent_conflicts to context)
- `config/identity.py` (extract voice rules into machine-readable format for monitor)
- `db.py` (add inhibition functions — at END of file)
- `migrations/010_body.sql` (add inhibitions table)
- `models/pipeline.py` (add `InhibitionCheck`, `SelfConsistencyResult`)
- `terminal.py` (add `inhibitions` peek command)
**Scope (files you may NOT touch):**
- `pipeline/cortex.py` (no prompt changes beyond what prompt_assembler provides)
- `pipeline/sensorium.py`
- `pipeline/thalamus.py`
- `heartbeat_server.py`
- `sleep.py` (sleep already reflects on high-salience moments — internal conflicts flow through existing path)
- `window/`
**Tests:** Add `tests/test_inhibition.py`: after negative signal, matching inhibition forms. After positive signal, it weakens. Add `tests/test_metacognitive.py`: out-of-character speech produces internal_conflict event. Conflict appears in day_memory with boosted salience.
**Definition of done:** She learns from bad outcomes (inhibitions form). She notices when she contradicts herself (internal conflicts). Both feed into night reflection via existing sleep pipeline. Validator no longer silently strips behavior.

---

### TASK-011: Body Phase 4 — Habits
**Status:** BACKLOG
**Priority:** Medium
**Depends on:** TASK-010
**Design doc:** `body-spec-v2.md` §2.2 (Habit System), §10 Phase 4
**Description:** Repeated patterns crystallize into reflexes that skip cortex.
- `track_action_pattern()` in output processing: after every executed action, check if habit should form or strengthen. Second occurrence in similar context → habit at 0.1. Nonlinear strength curve (fast 0→0.4, medium 0.4→0.6, slow 0.6→0.8).
- `check_habits()` in heartbeat BEFORE cortex call: if strong habit matches (strength ≥ 0.6), return MotorPlan directly. Cortex skipped entirely — reflex, not thought.
- Trigger context is coarse-grained: energy band, mood band, mode, time band, visitor_present. Too specific = habits never form.
- Migration: add `habits` table to `010_body.sql`.
**Scope (files you may touch):**
- `pipeline/basal_ganglia.py` (add `check_habits()`)
- `pipeline/output.py` (add `track_action_pattern()`)
- `heartbeat.py` (add habit check before cortex call in `run_cycle`)
- `db.py` (add habit functions — at END of file)
- `migrations/010_body.sql` (add habits table)
- `models/pipeline.py` (add habit-related dataclasses)
- `terminal.py` (add `habits` peek command)
**Scope (files you may NOT touch):**
- `pipeline/cortex.py`
- `pipeline/validator.py`
- `pipeline/sensorium.py`
- `heartbeat_server.py`
- `window/`
**Tests:** Add `tests/test_habits.py`: after N repetitions of same action in same context, habit forms. After strength ≥ 0.6, habit auto-fires and cortex is skipped. Habit strength follows nonlinear curve.
**Definition of done:** Habits form from repeated behavior. Strong habits skip cortex (cost savings). `habits` peek command shows all habits with strength and trigger context.

---

### TASK-012: Engagement Phase 1 — visitor_connect as perception, not state change
**Status:** BACKLOG
**Priority:** High
**Depends on:** TASK-008 (body refactor provides the action registry / motor plan structure)
**Description:** Currently `heartbeat_server.py` forces `engagement.status='engaged'` the instant a visitor connects. She has no choice. Change this so visitor_connect goes through the normal pipeline.
- `heartbeat_server.py`: stop calling `db.update_engagement_state(status='engaged')` on connect. Instead, only append the `visitor_connect` event to inbox (already happens) and let the pipeline handle it.
- `pipeline/sensorium.py`: visitor_connect salience should factor in visitor trust level, social hunger drive, and what she's currently doing. Familiar face + high social hunger = high salience. Stranger + she's absorbed in reading = low salience.
- `pipeline/thalamus.py`: visitor_connect no longer auto-routes to `engage`. It competes with other perceptions. If it wins, cycle type is `engage` and she greets them. If it loses, she acknowledges presence but continues what she was doing.
- `pipeline/ack.py`: still sends instant ack to visitor (so they know the system received their connection), but ack is "she noticed you" not "she's talking to you."
- Engagement state update moves to `pipeline/executor.py` (or `pipeline/body.py` post-Phase-1): only set when she actually chooses to engage via a `speak` action directed at the visitor.
**Scope (files you may touch):**
- `heartbeat_server.py` (remove forced engagement on connect)
- `pipeline/sensorium.py` (update visitor_connect salience computation)
- `pipeline/thalamus.py` (visitor_connect competes instead of auto-wins)
- `pipeline/ack.py` (ack = "noticed" not "engaged")
- `pipeline/body.py` or `pipeline/executor.py` (engagement state set on speak action)
- `models/state.py` (if EngagementState needs new fields)
**Scope (files you may NOT touch):**
- `pipeline/cortex.py`
- `db.py` (engagement functions already exist)
- `window/` (frontend unchanged — still gets state updates via WebSocket)
- `sleep.py`
**Tests:** Add `tests/test_engagement_choice.py`: visitor connects while she's idle → she engages. Visitor connects while she's absorbed (low social hunger, high expression need) → she acknowledges but doesn't engage. Visitor with high trust connects → higher salience than stranger.
**Definition of done:** She can choose not to immediately engage with a visitor. The pipeline decides, not the server.

---

### TASK-013: Engagement Phase 2 — multi-slot visitor presence
**Status:** BACKLOG
**Priority:** Medium
**Depends on:** TASK-012
**Description:** Replace the singleton `EngagementState` with a multi-visitor presence model. Multiple people can be in the shop simultaneously.
- New table `visitors_present` (visitor_id, status: browsing|in_conversation|waiting|left, entered_at, last_activity).
- `EngagementState` singleton becomes a computed view: "who is she actively talking to right now" derived from visitors_present.
- `heartbeat_server.py` WebSocket: support multiple concurrent window chat sessions. Each visitor gets their own token and presence record.
- Arbiter: visitors compete for attention alongside threads, content, creative. A cycle might address one visitor while others browse.
- Sensorium: multiple visitor events in same inbox batch get individual perceptions with salience.
**Scope (files you may touch):**
- `models/state.py` (add `VisitorPresence`, refactor `EngagementState`)
- `db.py` (add visitors_present table and functions — at END)
- `migrations/011_multi_visitor.sql` (new)
- `heartbeat_server.py` (multi-session WebSocket, TCP)
- `heartbeat.py` (adapt main loop for multi-visitor awareness)
- `pipeline/sensorium.py` (multi-visitor perception)
- `pipeline/thalamus.py` (visitor as one of many attention targets)
- `pipeline/arbiter.py` (visitors compete for cycle allocation)
- `terminal.py` (show who's in the shop)
**Scope (files you may NOT touch):**
- `pipeline/cortex.py` (prompt just sees "who's here" — assembler handles)
- `sleep.py`
- `window/src/components/` (frontend gets state via WebSocket, adapts)
**Tests:** Add `tests/test_multi_visitor.py`: two visitors connect → both appear in visitors_present. She talks to one, the other sees "she's busy." Second visitor says something interesting → arbiter can switch attention.
**Definition of done:** Multiple visitors can be in the shop. She allocates attention across them. The singleton engagement model is gone.

---

### TASK-014: Engagement Phase 3 — choice-based engagement via drives and basal ganglia
**Status:** BACKLOG
**Priority:** Medium
**Depends on:** TASK-009 (basal ganglia selection) + TASK-013 (multi-slot visitors)
**Description:** Full integration of visitor choice with the drive system and basal ganglia.
- `speak` action directed at a specific visitor has impulse modulated by: social hunger, visitor trust level, conversation interest, curiosity about what they said.
- Basal ganglia selects which visitor to address if multiple are present and multiple speak actions have impulse > 0.
- She can choose to talk to a familiar face more than a stranger. Or an interesting stranger more than a boring returner. Drives determine the weighting.
- She can actively disengage ("I need to get back to this") if expression_need or curiosity is high and the conversation isn't stimulating.
- Prompt assembler includes all present visitors with trust levels so cortex can express differentiated impulses.
**Scope (files you may touch):**
- `pipeline/basal_ganglia.py` (visitor-directed action selection)
- `pipeline/output.py` (track visitor engagement patterns for habit formation)
- `prompt_assembler.py` (include all present visitors in context)
- `pipeline/cortex.py` (parse visitor-targeted intentions)
- `pipeline/thalamus.py` (remove any remaining visitor-priority hardcoding)
**Scope (files you may NOT touch):**
- `db.py`
- `heartbeat_server.py`
- `sleep.py`
- `window/`
**Tests:** Extend `tests/test_engagement_choice.py`: two visitors present, one familiar + one stranger. With high social hunger, she addresses the familiar. With high curiosity and the stranger saying something interesting, she addresses the stranger. With low social hunger and high expression need, she continues her own work.
**Definition of done:** Visitor engagement is fully drive-modulated and arbiter-routed. She's a shopkeeper, not an escort.

---

### TASK-015: Body Phase 5 — Dashboard panels
**Status:** BACKLOG
**Priority:** Low
**Depends on:** TASK-011 (habits complete)
**Design doc:** `body-spec-v2.md` §9
**Description:** Add two new dashboard panels:
- **Body Panel:** Capability grid (green/yellow/grey for enabled+ready/cooling/disabled), energy spent today vs budget, actions executed today by type.
- **Behavioral Panel:** Top 5 habits by strength with sparklines, active inhibitions (strongest first with trigger count), "She almost..." feed (suppressed actions with impulse > 0.5), habit cycles today (cortex-skipped count = cost savings).
**Scope (files you may touch):**
- `window/src/components/dashboard/BodyPanel.tsx` (new)
- `window/src/components/dashboard/BehavioralPanel.tsx` (new)
- `window/src/app/dashboard/page.tsx` (add panels)
- `window/src/lib/dashboard-api.ts` (add API calls)
- `window/src/lib/types.ts` (add TypeScript types)
- `heartbeat_server.py` (add `_http_dashboard_body` and `_http_dashboard_behavioral` endpoints)
- `db.py` (add query functions for action_log, habits, inhibitions — at END)
**Scope (files you may NOT touch):**
- `heartbeat.py`
- `pipeline/*`
- `sleep.py`
**Tests:** Verify endpoints return correct JSON. Panels render without errors.
**Definition of done:** Dashboard shows body state and behavioral data. "She almost..." feed works.

---

### TASK-016: Reconcile DailySummary dataclass with new index schema
**Status:** BACKLOG
**Priority:** Low
**Description:** TASK-007 changed daily_summary from narrative blob to lightweight index, but `DailySummary` dataclass in `models/state.py` and the `summary_bullets` column name still reflect the old shape. Rename field and update dataclass to match actual data.
**Scope (files you may touch):**
- `models/state.py`
- `db.py` (only the `insert_daily_summary` / `get_daily_summary` functions)
- `sleep.py` (update references if field name changes)
**Scope (files you may NOT touch):**
- Everything else
**Tests:** Existing sleep tests pass. Add test verifying round-trip of new index structure.
**Definition of done:** `DailySummary` fields match what `sleep.py` actually stores.

---

### TASK-017: Verify unengaged visitor timeout path
**Status:** BACKLOG
**Priority:** Medium
**Depends on:** TASK-012
**Description:** After TASK-012, a visitor can connect but never be engaged (salience < 0.5). Verify that heartbeat_server.py has a connection timeout that disconnects unengaged visitors after a reasonable period (e.g. 5 minutes). If not, add one. Without this, a visitor could sit in the shop forever with no interaction and no cleanup.
**Scope (files you may touch):**
- `heartbeat_server.py`
**Scope (files you may NOT touch):**
- Everything else
**Tests:** Test that an unengaged visitor connection is cleaned up after timeout.
**Definition of done:** Unengaged visitors don't linger forever.

---

### TASK-018: Dashboard and WebSocket authentication enforcement
**Status:** BACKLOG
**Priority:** High
**Description:** Security audit found that dashboard HTTP endpoints (`/api/dashboard/*`) have NO server-side auth enforcement — the `DASHBOARD_PASSWORD` is validated by `/api/dashboard/auth` but never checked on data endpoints. WebSocket connections (port 8765) are also unauthenticated. Any client can connect and receive full application state.
Fix: (1) Extract+validate `Authorization: Bearer` header on all `_http_dashboard_*` handlers. (2) Require a valid token on WebSocket handshake. (3) Refuse to start (or warn loudly) if `DASHBOARD_PASSWORD` is unset.
**Scope (files you may touch):**
- `heartbeat_server.py`
**Scope (files you may NOT touch):**
- `heartbeat.py`
- `db.py`
- `pipeline/*`
**Tests:** Add `tests/test_dashboard_auth.py` verifying 401 on unauthenticated requests.
**Definition of done:** Dashboard endpoints return 401 without valid auth. WebSocket rejects unauthenticated connections.

---

### TASK-019: Restrict CORS to production domain
**Status:** BACKLOG
**Priority:** Medium
**Description:** Both nginx and the Python HTTP handler set `Access-Control-Allow-Origin: *`, allowing any website to make cross-origin API requests. Replace with specific domain allowlist.
**Scope (files you may touch):**
- `heartbeat_server.py` (CORS headers in `_http_json`, `_http_bytes`, `_http_cors_preflight`)
- `deploy/nginx.conf` (CORS headers in `/api/` location)
**Scope (files you may NOT touch):**
- `heartbeat.py`
- `db.py`
**Tests:** Verify CORS headers reflect allowed origin, not wildcard.
**Definition of done:** CORS restricted to production domain. Wildcard removed.

---

## Completed Tasks

_None yet._

---

## How to Add a Task

Copy this template and add it above the "Completed Tasks" section:

```markdown
### TASK-XXX: Title
**Status:** BACKLOG
**Priority:** Low / Medium / High
**Description:** What needs to happen and why.
**Scope (files you may touch):**
- file1.py
- file2.py
**Scope (files you may NOT touch):**
- file3.py (reason)
**Tests:** What tests to add or verify.
**Definition of done:** How you know it's finished.
```
