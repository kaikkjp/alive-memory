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
**Status:** DONE (2026-02-15)
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
**Status:** DONE (2026-02-15)
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
**Status:** DONE (2026-02-15)
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
**Status:** DONE (2026-02-14)
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
**Status:** DONE (2026-02-14)
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

### TASK-011a: Body Phase 4a — Habit tracking + formation
**Status:** DONE (2026-02-14)
**Priority:** Medium
**Depends on:** TASK-010
**Design doc:** `body-spec-v2.md` §2.2 (Habit System), §10 Phase 4
**Description:** Track repeated action patterns and form habits with nonlinear strength curves.
- `track_action_pattern()` in output processing: after every executed action, check if habit should form or strengthen. Second occurrence in similar context → habit at 0.1. Nonlinear strength curve (fast 0→0.4, medium 0.4→0.6, slow 0.6→0.8).
- Trigger context is coarse-grained: energy band, mood band, mode, time band, visitor_present. Too specific = habits never form.
- Migration: add `habits` table to `010_body.sql`.
- DB CRUD for habits (get, upsert, delete, list).
**Scope (files you may touch):**
- `pipeline/output.py` (add `track_action_pattern()`)
- `db.py` (add habit functions — at END of file)
- `migrations/010_body.sql` (add habits table)
- `models/pipeline.py` (add habit-related dataclasses)
**Scope (files you may NOT touch):**
- `pipeline/cortex.py`
- `pipeline/validator.py`
- `pipeline/sensorium.py`
- `pipeline/basal_ganglia.py`
- `heartbeat.py`
- `heartbeat_server.py`
- `terminal.py`
- `window/`
**Tests:** Add `tests/test_habits.py`: after N repetitions of same action in same context, habit forms. Habit strength follows nonlinear curve.
**Definition of done:** Habits form from repeated behavior. Strength curve works. Habits table populated with correct trigger context.

---

### TASK-011b: Body Phase 4b — Habit auto-fire in basal ganglia
**Status:** DONE (2026-02-14)
**Priority:** Medium
**Depends on:** TASK-011a
**Design doc:** `body-spec-v2.md` §2.2 (Habit System), §10 Phase 4
**Description:** Strong habits bypass cortex entirely — reflexes, not thoughts.
- `check_habits()` in basal ganglia BEFORE cortex call: if strong habit matches (strength ≥ 0.6), return MotorPlan directly. Cortex skipped entirely — reflex, not thought.
- Trigger context matching against current state (energy band, mood band, mode, time band, visitor_present).
- `habits` peek command in terminal.
**Scope (files you may touch):**
- `pipeline/basal_ganglia.py` (add `check_habits()`)
- `heartbeat.py` (add habit check before cortex call in `run_cycle`)
- `terminal.py` (add `habits` peek command)
- `tests/` (extend habit tests)
**Scope (files you may NOT touch):**
- `pipeline/cortex.py`
- `pipeline/validator.py`
- `pipeline/sensorium.py`
- `pipeline/output.py`
- `db.py`
- `heartbeat_server.py`
- `window/`
**Tests:** Extend `tests/test_habits.py`: after strength ≥ 0.6, habit auto-fires and cortex is skipped. Peek command shows all habits with strength and trigger context.
**Definition of done:** Strong habits skip cortex (cost savings). `habits` peek command shows all habits with strength and trigger context.

---

### TASK-012: Engagement Phase 1 — visitor_connect as perception, not state change
**Status:** DONE (2026-02-14)
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
**Status:** DONE (2026-02-14)
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
**Status:** DONE (2026-02-14)
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
**Status:** DONE (2026-02-15)
**Priority:** Medium
**Depends on:** TASK-002 (dashboard routes extracted), TASK-011b (habits complete)
**Design doc:** `body-spec-v2.md` §9

**Description:** Add two new dashboard panels showing body state and learned behaviors. All data sources already exist in the DB (action_log, habits, inhibitions tables from TASK-009/010/011). This is read-only data display — no pipeline changes.

**Implementation steps (in order):**

**Step 1 — DB query functions.** Add to end of `db.py`:
- `get_actions_today(db) -> list[dict]` — query action_log for today (UTC), group by action_type, return [{type, count, total_energy}]
- `get_action_capabilities(db) -> list[dict]` — read ACTION_REGISTRY, join with action_log for cooldown status, return [{action, enabled, ready, cooling_until, energy_cost}]
- `get_top_habits(db, limit=5) -> list[dict]` — habits ordered by strength desc, return [{action, trigger_context, strength, last_fired, fire_count}]
- `get_active_inhibitions(db) -> list[dict]` — inhibitions with strength > 0.05, ordered by strength desc, return [{action, context, strength, trigger_count, formed_at}]
- `get_recent_suppressions(db, limit=10, min_impulse=0.5) -> list[dict]` — action_log where suppressed=true AND impulse >= min_impulse, ordered by timestamp desc, return [{action, impulse, reason, timestamp}]
- `get_habit_skip_count_today(db) -> int` — count cycles today where habit auto-fired (cortex_skipped=true in cycle_log or equivalent marker)
- `get_energy_budget(db) -> dict` — {spent_today, budget} from action_log + config

**Step 2 — REST endpoints.** Add to dashboard routes (in `api/dashboard_routes.py` if TASK-002 is done, otherwise `heartbeat_server.py`):
- `GET /api/dashboard/body` — returns JSON:
  ```json
  {
    "capabilities": [{"action": "speak", "enabled": true, "ready": true, "cooling_until": null, "energy_cost": 1}],
    "energy": {"spent_today": 42, "budget": 100},
    "actions_today": [{"type": "speak", "count": 15, "total_energy": 15}]
  }
  ```
- `GET /api/dashboard/behavioral` — returns JSON:
  ```json
  {
    "habits": [{"action": "...", "trigger_context": {}, "strength": 0.72, "last_fired": "...", "fire_count": 8}],
    "inhibitions": [{"action": "...", "context": "...", "strength": 0.35, "trigger_count": 3}],
    "suppressions": [{"action": "...", "impulse": 0.7, "reason": "...", "timestamp": "..."}],
    "habit_skips_today": 4
  }
  ```

**Step 3 — TypeScript types.** Add to `window/src/lib/types.ts`:
- `ActionCapabilityView` — {action, enabled, ready, cooling_until, energy_cost}
- `BodyPanelData` — {capabilities: ActionCapabilityView[], energy: {spent_today, budget}, actions_today: {type, count, total_energy}[]}
- `HabitView` — {action, trigger_context, strength, last_fired, fire_count}
- `InhibitionView` — {action, context, strength, trigger_count}
- `SuppressionView` — {action, impulse, reason, timestamp}
- `BehavioralPanelData` — {habits: HabitView[], inhibitions: InhibitionView[], suppressions: SuppressionView[], habit_skips_today: number}

**Step 4 — API client.** Add to `window/src/lib/dashboard-api.ts`:
- `fetchBodyData(): Promise<BodyPanelData>`
- `fetchBehavioralData(): Promise<BehavioralPanelData>`

**Step 5 — React panels.**
- `window/src/components/dashboard/BodyPanel.tsx`:
  - Capability grid: rows for each action. Green dot = enabled+ready. Yellow dot = cooling down (show remaining seconds). Grey dot = disabled. Columns: action name, status dot, energy cost, times used today.
  - Energy bar: horizontal bar showing spent/budget with percentage.
  - Actions today: simple table sorted by count desc.
  - Auto-refresh every 10s.

- `window/src/components/dashboard/BehavioralPanel.tsx`:
  - Top habits: table with strength shown as a colored bar (0-1 scale, green ≥0.6 = auto-fire territory). Columns: action, trigger context (compact), strength bar, fire count.
  - Active inhibitions: table sorted by strength. Columns: action, context, strength, trigger count.
  - "She almost..." feed: reverse-chronological list of suppressions. Each item shows action name, impulse strength, reason it was suppressed, how long ago. Style like an activity feed.
  - Cost savings: single number showing habit-skip count today with label "Cortex calls saved by habits."
  - Auto-refresh every 10s.

**Step 6 — Wire into dashboard page.** Add both panels to `window/src/app/dashboard/page.tsx` in the grid layout. Place BodyPanel after the existing Drives panel. Place BehavioralPanel after BodyPanel.

**Scope (files you may touch):**
- `db.py` (add query functions — at END of file only)
- `api/dashboard_routes.py` (if exists after TASK-002) OR `heartbeat_server.py` (if 002 not done)
- `window/src/components/dashboard/BodyPanel.tsx` (new)
- `window/src/components/dashboard/BehavioralPanel.tsx` (new)
- `window/src/app/dashboard/page.tsx`
- `window/src/lib/dashboard-api.ts`
- `window/src/lib/types.ts`

**Scope (files you may NOT touch):**
- `heartbeat.py`
- `pipeline/*` (all pipeline files)
- `sleep.py`
- `models/*`

**Tests:**
- `tests/test_dashboard_body.py`: verify `/api/dashboard/body` returns correct JSON shape. Test with empty action_log (fresh day). Test with seeded action_log entries.
- `tests/test_dashboard_behavioral.py`: verify `/api/dashboard/behavioral` returns correct JSON shape. Test with no habits/inhibitions. Test with seeded data. Verify suppressions filter by min_impulse.
- Verify existing dashboard tests still pass.

**Definition of done:**
- Both panels render on the dashboard without errors.
- Endpoints return correct data from real DB tables.
- Capability grid shows accurate ready/cooling/disabled status.
- "She almost..." feed shows suppressed actions with impulse > 0.5.
- Habit-skip cost savings counter works.
- Auto-refresh doesn't break WebSocket or cause memory leaks.

---

### TASK-016: Reconcile DailySummary dataclass with new index schema
**Status:** DONE (2026-02-14)
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
**Status:** DONE (2026-02-15)
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
**Status:** DONE (2026-02-14)
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
**Status:** DONE (2026-02-15)
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

### TASK-020: Post-review cleanup (009 + 012)
**Status:** DONE (2026-02-14)
**Priority:** Low
**Description:** Minor items from code reviews:
- Extract 0.5 salience threshold in thalamus.py to named constant
- Update ARCHITECTURE.md debt item #4 (engagement no longer forced)
- Add test_engagement_choice.py to ARCHITECTURE.md test table
- Fix summary table Total row
- Double save_drives_state in output.py — consolidate to single call
- Stale module descriptions in ARCHITECTURE.md
**Scope (files you may touch):**
- `thalamus.py`
- `output.py`
- `ARCHITECTURE.md`
**Scope (files you may NOT touch):**
- Everything else
**Tests:** Existing tests pass.
**Definition of done:** All nits resolved.

---

### TASK-021: Fix update_docs.py to use tracked files only
**Status:** BACKLOG
**Priority:** Low
**Description:** Two bugs in `scripts/update_docs.py`:
1. `os.walk()` scans the filesystem and picks up untracked files (e.g. `visitor_sim.py`, untracked `docs/*.md`), inflating summary counts. Should use `git ls-files` instead.
2. The Total row regex `\| \*\*Total\*\*.*?\|` matches only up to the first `|` after `**Total**`, leaving the rest of the old row intact. Each run appends new columns to the Total row instead of replacing it. Fix: use a greedy match to end of line.
3. `db/` package is classified as "Other" because `classify_file()` has no rule for `db/` paths. Add a `db/` classification.
**Scope (files you may touch):**
- `scripts/update_docs.py`
**Scope (files you may NOT touch):**
- Everything else
**Tests:** Run `python scripts/update_docs.py` twice — summary table should be identical both times. Total row should have exactly 3 columns.
**Definition of done:** Summary counts reflect tracked files only. Total row doesn't grow on repeated runs. `db/` appears as its own area.

---

### TASK-021a: Scene compositor component + asset pipeline
**Status:** DONE (2026-02-15)
**Priority:** High
**Depends on:** None (frontend-only, uses existing scaffolding)
**Design doc:** `scene-config.json` (locked composition parameters)
**Description:** Build the multi-layer scene compositor as a presentational React component and prepare all static assets. The compositor renders a 6-layer stack in a responsive viewport. No pipeline connection yet — accepts a `spriteState` prop and renders the correct sprite.

**Layer stack (bottom to top):**
- Layer 0: Outdoor scenery — dynamic background visible through shop windows. Time-of-day variants (morning, afternoon, evening, night). Sits BEHIND the shop interior. Requires `shop_back.png` window regions to have transparency or a window mask asset.
- Layer 1: `shop_interior.png` — shop interior base with transparent/semi-transparent window areas so Layer 0 shows through.
- Layer 2: Character sprite — swapped based on `spriteState` prop. Positioned per `scene-config.json` (x: 594, y: 213 at 1440×900, 55% canvas height). CSS filter for color grade (red 1.05, blue 0.92). Drop shadow (5,5 offset, 0.3 opacity, 6px blur).
- Layer 3: Counter foreground — everything below y=72% of `shop_back.png`, with 6px fade at cut edge. Occludes character's lower body.
- Layer 4: CSS radial-gradient vignette (35% transparent center, edge `rgba(8,6,4,0.65)`).
- Layer 5: Canvas dust particles (35 particles, `rgba(255,210,150)`, max opacity 0.3, slow upward drift).

**Implementation steps:**

**Step 1 — Asset prep scripts.**
- Create `scripts/slice_counter.py`: Load `shop_back.png`, make everything above y=72% transparent, apply 6px fade zone at cut edge, save as `public/assets/counter_foreground.png` (RGBA PNG). Run once, commit output.
- Create `scripts/cut_window_mask.py`: Load `shop_back.png`, identify window regions, create a version where window areas are transparent so the outdoor scenery layer shows through. Save as `public/assets/shop_interior.png` (RGBA PNG). Alternative: if too complex for automated cutting, create a manually-painted alpha mask `public/assets/window_mask.png`.

**Step 2 — Outdoor scenery assets.** Place time-of-day background variants in `public/assets/scenery/`: `morning.png`, `afternoon.png`, `evening.png`, `night.png`. Sized to fill the viewport (1440×900). If assets aren't ready yet, use CSS gradient fallbacks per time period.

**Step 3 — SceneCanvas component.** Update `window/src/components/SceneCanvas.tsx`:
- Render 1440×900 viewport with CSS `aspect-ratio: 16/10`, scales responsively.
- All 6 layers as `position:absolute` children with explicit z-index.
- Layer 0: `<img>` or `<div>` for outdoor scenery, full fill.
- Layer 1: `<img>` for `shop_interior.png`, full fill.
- Layer 2: `<img>` for current sprite, percentage-based positioning from `scene-config.json`. CSS filter for color grade. CSS drop-shadow. Crossfade via opacity 0.3s on swap.
- Layer 3: `<img>` for `counter_foreground.png`, full fill.
- Layer 4: `<div>` with CSS radial-gradient for vignette.
- Layer 5: `<canvas>` for dust particles (≤35 particles, `requestAnimationFrame`).
- Props: `spriteState: SpriteState`, `timeOfDay: TimeOfDay`.
- All magic numbers from `scene-constants.ts` — no raw pixel values.

**Step 4 — Sprite state type + constants.** Add `SpriteState` and `TimeOfDay` types to `window/src/lib/types.ts`. Create `window/src/lib/scene-constants.ts` — export all `scene-config.json` values as typed constants.

**Step 5 — Verify composition.** Add a `?debug=scene` query param handler in `page.tsx` that renders SceneCanvas with a sprite state selector dropdown (dev only).

**Sprite file map** (placed in `public/assets/sprites/`):
- `engaged.png` → `char-1-cropped.png`
- `tired.png` → `char-2-cropped.png`
- `thinking.png` → `char-3-cropped.png`
- `curious.png` → `char-4-cropped.png`
- `surprised.png` → `char-5-cropped.png`
- `focused.png` → `char-6-cropped.png`

**Scope (files you may touch):**
- `scripts/slice_counter.py` (new)
- `scripts/cut_window_mask.py` (new)
- `window/src/components/SceneCanvas.tsx` (rewrite)
- `window/src/lib/scene-constants.ts` (new)
- `window/src/lib/types.ts` (add `SpriteState`, `TimeOfDay` types)
- `window/src/lib/compositor.ts` (update if needed)
- `window/src/hooks/useParticles.ts` (update particle config)
- `window/src/hooks/useSceneTransition.ts` (update for sprite crossfade)
- `window/src/app/page.tsx` (add debug scene viewer behind query param)
- `public/assets/` (new asset files)
**Scope (files you may NOT touch):**
- `pipeline/*` (no server-side changes)
- `window_state.py`
- `heartbeat_server.py`
- `heartbeat.py`
- `db.py`
- `compositing.py`
**Tests:**
- Visual: SceneCanvas renders all 6 layers without layout shift on sprite swap.
- Visual: Counter foreground correctly occludes sprite below y=72%.
- Visual: Outdoor scenery visible through window regions of shop interior.
- Visual: Dust particles render at ≤35 count, no frame drops.
- Visual: Viewport scales responsively — test at 1440×900, 1024×640, 768×480.
- Unit: `scene-constants.ts` exports match `scene-config.json` values.
- `scripts/slice_counter.py` produces valid RGBA PNG with correct dimensions.
**Definition of done:** SceneCanvas renders the full 6-layer composite with correct z-ordering. Sprite swaps crossfade without layout shift. Outdoor scenery shows through shop windows, changes with `timeOfDay` prop. Counter foreground occludes sprite naturally. Dust particles and vignette render as overlays. All positioning is percentage-based and responsive. Component works standalone with hardcoded props (no pipeline dependency). All z-indexes documented in `scene-constants.ts`.

---

### TASK-021b: Wire scene compositor to ALIVE pipeline state
**Status:** DONE (2026-02-16)
**Priority:** High
**Depends on:** TASK-021a (compositor component exists and works standalone)
**Description:** Connect the scene compositor to live ALIVE pipeline state. Sprite resolution happens server-side in `pipeline/scene.py` (which already has access to drives, mood, activity, visitors). The resolved sprite state is broadcast via `window_state.py` WebSocket payload. Frontend reads it and passes to SceneCanvas. Time-of-day is derived server-side from `clock.py`.

**Implementation steps:**

**Step 1 — Server-side sprite resolution.** Update `pipeline/scene.py`:
- Add `resolve_sprite_state(drives, engagement, room_state, recent_events) -> str`.
- Priority order: surprised (unexpected event in last 2 cycles) > tired (energy < 30) > engaged (has_visitor AND in conversation) > curious (has_visitor AND not yet engaged) > focused (thread_work/arranging/creative cycle) > thinking (default idle).

**Step 2 — Time-of-day resolution.** Add to `pipeline/scene.py`:
- `resolve_time_of_day() -> str` using `clock.py`.
- JST-based: morning (6-11), afternoon (11-17), evening (17-20), night (20-6).

**Step 3 — Broadcast via window_state.** Update `window_state.py`:
- Add `sprite_state: str` and `time_of_day: str` fields to broadcast payload.

**Step 4 — TypeScript types.** Update `window/src/lib/types.ts`:
- Add `sprite_state: SpriteState` and `time_of_day: TimeOfDay` to the WebSocket payload type.

**Step 5 — Wire frontend.** Update `window/src/app/page.tsx`:
- Read `sprite_state` and `time_of_day` from socket state, pass to `<SceneCanvas>`.
- Remove debug hardcoding from TASK-021a (keep `?debug=scene` override).

**Scope (files you may touch):**
- `pipeline/scene.py` (add sprite + time resolution functions)
- `window_state.py` (add fields to broadcast payload)
- `window/src/lib/types.ts` (add fields to WebSocket payload type)
- `window/src/app/page.tsx` (wire socket state → SceneCanvas props)
- `window/src/hooks/useShopkeeperSocket.ts` (only if payload parsing needs update)
**Scope (files you may NOT touch):**
- `pipeline/cortex.py`
- `pipeline/basal_ganglia.py`
- `pipeline/output.py`
- `heartbeat.py`
- `heartbeat_server.py`
- `db.py`
- `window/src/components/SceneCanvas.tsx` (should work with props from 021a)
- `compositing.py`
**Tests:**
- `tests/test_scene_sprite.py` (new): `resolve_sprite_state` returns correct state for each priority case. Surprised beats tired. Tired beats engaged. Curious requires visitor present but not engaged. Default is thinking.
- `tests/test_window_state.py`: verify `sprite_state` and `time_of_day` appear in broadcast payload with valid values.
- Integration: run heartbeat, connect WebSocket, verify `sprite_state` changes when drives/visitors change.
**Definition of done:** Scene compositor shows the correct sprite based on live pipeline state. Outdoor scenery changes with real time of day. Sprite transitions happen smoothly when pipeline state changes. No client-side sprite resolution logic — all resolution is server-side. `?debug=scene` override still works for testing.

---

### TASK-022: Fix heartbeat status indicator
**Status:** DONE (2026-02-16)
**Priority:** High
**Description:** The "Heartbeat" field in the Controls panel shows "Inactive" even while cycles are actively running. Read actual heartbeat/cron state (e.g., last cycle timestamp vs expected interval) and display accurate status.
**Acceptance criteria:**
- If last cycle fired within 1 expected interval → show "Active" (green)
- If last cycle fired within 2 intervals → show "Late" (yellow)
- If no cycle within 3 intervals → show "Inactive" (red)
- Display time since last cycle next to status
**Scope (files you may touch):**
- `window/src/components/dashboard/ControlsPanel.tsx` (or equivalent Controls panel component)
- `api/dashboard_routes.py` (heartbeat status endpoint)
- `heartbeat_server.py` (if dashboard routes not yet extracted)
**Scope (files you may NOT touch):**
- `heartbeat.py`
- `db.py`
- `pipeline/*`
**Tests:** Verify heartbeat status reflects actual cycle state. Active cycles show "Active" (green). Stale cycles show correct degraded status.
**Definition of done:** Controls panel shows real-time heartbeat status with color-coded indicator and time since last cycle.

---

### TASK-023: Fix Threads panel — surface thread titles and summaries
**Status:** DONE (2026-02-16)
**Priority:** Medium
**Description:** All 7 threads show "..." with status "open" but no title or content. Each thread should display meaningful information.
**Acceptance criteria:**
- Each thread displays its title (or first ~60 chars of its seed content if no title field exists)
- Each thread displays thread type or topic tag if available
- Each thread displays message count or last activity timestamp
- If title/summary fields are null in DB, investigate whether cycle processing is supposed to write them and fix the write path
**Scope (files you may touch):**
- `window/src/components/dashboard/ThreadsPanel.tsx`
- `api/dashboard_routes.py` (threads endpoint)
- `heartbeat_server.py` (if dashboard routes not yet extracted)
- `window_state.py` (if thread data shape in broadcast needs updating)
**Scope (files you may NOT touch):**
- `heartbeat.py`
- `pipeline/*` (unless thread write path fix is required — document scope expansion first)
**Tests:** Verify threads endpoint returns title/type/activity data. Panel renders thread titles instead of "...".
**Definition of done:** ThreadsPanel shows real thread titles, types/tags, and activity timestamps instead of placeholder content.

---

### TASK-024: Investigate drive boundary clamping
**Status:** DONE (2026-02-15)
**Priority:** High
**Description:** Curiosity pinned at 100%, Expression Need at 0%, Rest Need at 100%. Drives appear to not decay or recharge after cycles.
**Acceptance criteria:**
- Trace the drive update path: cycle completes → drive modulation function → DB write
- Confirm modulation is actually executing (add logging if needed)
- Confirm updated values are written to DB, not just held in memory
- After fix: trigger 3 manual cycles, verify at least 2 drive values change between cycles
- No drive should remain at 0% or 100% for more than 3 consecutive cycles under normal operation
**Scope (files you may touch):**
- `pipeline/output.py` (drive modulation logic)
- `pipeline/hypothalamus.py` (drive computation)
- `db.py` (drive state read/write — at END of file only)
- `models/state.py` (DrivesState if schema needs fixing)
**Scope (files you may NOT touch):**
- `pipeline/cortex.py`
- `heartbeat_server.py`
- `window/`
**Tests:** Add/update tests verifying drive values change after cycle execution. No drive stays pinned at boundary for >3 consecutive cycles.
**Definition of done:** Drive values modulate correctly after each cycle. Dashboard shows varying drive levels.

---

### TASK-025: Investigate flat memory resonance scores
**Status:** DONE (2026-02-16)
**Priority:** Medium
**Description:** All visible memories show identical 55% resonance. No variance means retrieval has no signal.
**Acceptance criteria:**
- Determine if resonance is calculated at creation time (static) or at retrieval time (contextual)
- If static: fix the scoring function — it should factor in content type, emotional valence, drive alignment, recency
- If contextual: fix the query context being passed — it may be empty or identical each time
- After fix: memory pool should show at least 3 distinct resonance values across entries
- Document how resonance is calculated (formula/factors) in a code comment
**Scope (files you may touch):**
- `pipeline/hippocampus.py` (memory retrieval/scoring)
- `db.py` (memory query functions — at END of file only)
- `api/dashboard_routes.py` (memory pool endpoint)
- `heartbeat_server.py` (if dashboard routes not yet extracted)
**Scope (files you may NOT touch):**
- `pipeline/cortex.py`
- `heartbeat.py`
- `window/` (display should auto-update when data improves)
**Tests:** Verify resonance scoring produces distinct values for memories with different content types, ages, and emotional valence.
**Definition of done:** Memory pool shows varied resonance scores. Scoring formula is documented in code comments.

---

### TASK-026: Add Content Pool panel
**Status:** DONE (2026-02-16)
**Priority:** Medium
**Description:** New dashboard panel showing available unconsumed content. Data source: Feed/content tables — items that have been fetched but not yet ingested by a cycle.
**Acceptance criteria:**
- Panel title: "Content Pool"
- Show: total items in pool
- Show: breakdown by content type (article, image, music, quote, etc.)
- Show: last 5 recently added items with title, type, and timestamp added
- Show: age of oldest unconsumed item
- Auto-refresh on same interval as other panels
**Scope (files you may touch):**
- `window/src/components/dashboard/ContentPoolPanel.tsx` (new)
- `window/src/app/dashboard/page.tsx` (add panel to grid — middle row alongside Memory Pool and Collection)
- `window/src/lib/dashboard-api.ts` (add fetch function)
- `window/src/lib/types.ts` (add ContentPoolData type)
- `api/dashboard_routes.py` (add `/api/dashboard/content-pool` endpoint)
- `db.py` (add content pool query function — at END of file only)
**Scope (files you may NOT touch):**
- `heartbeat.py`
- `pipeline/*`
- `sleep.py`
**Tests:** Verify `/api/dashboard/content-pool` returns correct JSON shape. Panel renders without errors.
**Definition of done:** Content Pool panel displays in the dashboard middle row showing pool size, type breakdown, recent additions, and oldest item age.

---

### TASK-027: Add Feed Pipeline panel
**Status:** DONE (2026-02-16)
**Priority:** Medium
**Description:** New dashboard panel showing ingestion pipeline health. Data source: Feed pipeline state, job queue, error logs.
**Acceptance criteria:**
- Panel title: "Feed"
- Show: pipeline status — Running / Paused / Error (with color indicator)
- Show: queue depth (items waiting for processing)
- Show: last successful ingestion timestamp
- Show: failed items count in last 24h (if >0, show last error message)
- Show: ingestion rate — items processed in last 24h
- Auto-refresh on same interval as other panels
**Scope (files you may touch):**
- `window/src/components/dashboard/FeedPanel.tsx` (new)
- `window/src/app/dashboard/page.tsx` (add panel to grid — bottom row alongside Timeline and Controls)
- `window/src/lib/dashboard-api.ts` (add fetch function)
- `window/src/lib/types.ts` (add FeedPanelData type)
- `api/dashboard_routes.py` (add `/api/dashboard/feed` endpoint)
- `db.py` (add feed pipeline query functions — at END of file only)
**Scope (files you may NOT touch):**
- `heartbeat.py`
- `pipeline/*`
- `sleep.py`
**Tests:** Verify `/api/dashboard/feed` returns correct JSON shape. Panel renders without errors.
**Definition of done:** Feed panel displays in the dashboard bottom row showing pipeline status, queue depth, ingestion stats, and error info.

---

### TASK-028: Add Consumption History panel
**Status:** DONE (2026-02-16)
**Priority:** Medium
**Description:** New dashboard panel showing what she consumed and what it produced. Data source: Ingestion logs joined with output records (memories, collection items, thread references).
**Acceptance criteria:**
- Panel title: "Consumption History"
- Chronological list, most recent first
- Each entry shows: timestamp, content type icon/label, source title (truncated to ~80 chars), outcome tag ("→ memory", "→ collection", "→ thread", "→ no output")
- Show last 20 entries by default
- If an item produced multiple outputs, show all outcome tags
- Scrollable within panel
**Scope (files you may touch):**
- `window/src/components/dashboard/ConsumptionHistoryPanel.tsx` (new)
- `window/src/app/dashboard/page.tsx` (add panel to grid — middle row, may need grid restructure)
- `window/src/lib/dashboard-api.ts` (add fetch function)
- `window/src/lib/types.ts` (add ConsumptionHistoryData type)
- `api/dashboard_routes.py` (add `/api/dashboard/consumption-history` endpoint)
- `db.py` (add consumption history query function — at END of file only)
**Scope (files you may NOT touch):**
- `heartbeat.py`
- `pipeline/*`
- `sleep.py`
**Tests:** Verify `/api/dashboard/consumption-history` returns correct JSON shape with outcome tags. Panel renders and scrolls without errors.
**Definition of done:** Consumption History panel shows chronological feed of ingested content with outcome tags, scrollable, auto-refreshing.

---

### TASK-029: Drive history sparklines
**Status:** BACKLOG
**Priority:** Low
**Depends on:** TASK-024 (drives must actually be changing for sparklines to be meaningful)
**Description:** Add inline 72h time-series mini-charts to each drive bar in the Drives panel.
**Acceptance criteria:**
- Small sparkline (~100x20px) next to each drive showing value over last 72h
- Data from drive state history table (requires drive values to be logged per-cycle, not just current state — if not logged, add logging first)
- Visual: thin line chart, no axes, just shape
**Scope (files you may touch):**
- `window/src/components/dashboard/DrivesPanel.tsx`
- `window/src/lib/dashboard-api.ts` (add drive history fetch)
- `window/src/lib/types.ts` (add DriveHistory type)
- `api/dashboard_routes.py` (add `/api/dashboard/drive-history` endpoint)
- `db.py` (add drive history query + possibly per-cycle logging — at END of file only)
**Scope (files you may NOT touch):**
- `heartbeat.py`
- `pipeline/*` (unless per-cycle drive logging must be added to output.py)
- `sleep.py`
**Tests:** Verify drive history endpoint returns time-series data. Sparklines render without layout shift.
**Definition of done:** Each drive bar has an inline sparkline showing 72h trend. Data is sourced from per-cycle drive state history.

---

### TASK-030: Cycle detail drill-down
**Status:** BACKLOG
**Priority:** Low
**Description:** Click a timeline entry → expand or modal showing full cycle details.
**Acceptance criteria:**
- Shows: trigger type, active drives at cycle start, cortex prompt/output summary, actions taken, drive state after cycle
- Accessible from Timeline panel entries
- Read-only view, no mutations
**Scope (files you may touch):**
- `window/src/components/dashboard/TimelinePanel.tsx` (add click handler + expand/modal)
- `window/src/components/dashboard/CycleDetailView.tsx` (new)
- `window/src/lib/dashboard-api.ts` (add cycle detail fetch)
- `window/src/lib/types.ts` (add CycleDetail type)
- `api/dashboard_routes.py` (add `/api/dashboard/cycle/:id` endpoint)
- `db.py` (add cycle detail query — at END of file only)
**Scope (files you may NOT touch):**
- `heartbeat.py`
- `pipeline/*`
- `sleep.py`
**Tests:** Verify cycle detail endpoint returns correct JSON shape. Click interaction opens detail view. View is read-only.
**Definition of done:** Timeline entries are clickable. Clicking opens a detail view showing full cycle information including trigger, drives, cortex summary, actions, and post-cycle state.

---

### TASK-031: Cost trend chart
**Status:** BACKLOG
**Priority:** Low
**Description:** Add daily cost history chart to Costs panel.
**Acceptance criteria:**
- Bar or line chart showing daily cost for last 30 days
- Current day highlighted
- Shows trend direction (increasing/decreasing)
**Scope (files you may touch):**
- `window/src/components/dashboard/CostsPanel.tsx`
- `window/src/lib/dashboard-api.ts` (add cost history fetch)
- `window/src/lib/types.ts` (add CostHistory type)
- `api/dashboard_routes.py` (add `/api/dashboard/cost-history` endpoint)
- `db.py` (add cost history query — at END of file only)
**Scope (files you may NOT touch):**
- `heartbeat.py`
- `pipeline/*`
- `sleep.py`
**Tests:** Verify cost history endpoint returns 30-day daily breakdown. Chart renders without errors.
**Definition of done:** Costs panel includes a 30-day trend chart with current day highlighted and trend direction indicator.

---

### TASK-032: Tag actions as reflexive vs generative in action registry
**Status:** DONE (2026-02-16)
**Priority:** High
**Depends on:** TASK-011b (habit auto-fire)
**Description:** Habit auto-fire currently skips cortex for all actions, but generative actions (write_journal, speak, post_x_draft) need LLM output to produce meaningful results. A journaling habit that skips the brain writes nothing.

Fix: Add a `generative: bool` field to `ActionCapability` in `pipeline/action_registry.py`. Tag each action:
- Reflexive (`generative=False`): rearrange, end_engagement, express_thought — can auto-fire without cortex.
- Generative (`generative=True`): write_journal, speak, post_x_draft — require cortex output.

In `pipeline/basal_ganglia.py` `check_habits()`: if a matching habit's action is generative, do NOT auto-fire. Instead, inject a `habit_boost` into the cycle context so the cortex call includes it. The habit increases impulse for that action (+0.3 to base impulse) rather than bypassing cortex entirely.

In `prompt_assembler.py`: if `habit_boost` is present, add a line to cortex context: "You feel drawn to [action] — it's becoming a habit." This gives cortex a nudge without forcing the action.

**Scope (files you may touch):**
- `pipeline/action_registry.py` (add `generative` field to ActionCapability, tag all actions)
- `pipeline/basal_ganglia.py` (check_habits splits on generative flag)
- `prompt_assembler.py` (inject habit_boost context)
- `heartbeat.py` (pass habit_boost through to cortex call if needed)
- `models/pipeline.py` (add habit_boost to CortexInput if needed)

**Scope (files you may NOT touch):**
- `pipeline/cortex.py`
- `pipeline/output.py`
- `db.py`
- `window/`

**Tests:** Add to `tests/test_habits.py`:
- test_reflexive_habit_autofires — rearrange habit at strength 0.6 skips cortex
- test_generative_habit_boosts_impulse — write_journal habit at strength 0.6 does NOT skip cortex, instead adds habit_boost to cycle context
- test_habit_boost_in_prompt — when habit_boost present, prompt assembler includes habit nudge text

**Definition of done:** Generative actions never auto-fire. Strong generative habits boost impulse instead. Reflexive actions auto-fire as before. She tends to journal rather than reflexively journaling nothing.

---

### TASK-033: Wire feed ingestion into heartbeat loop + populate feed sources
**Status:** DONE (2026-02-16)
**Priority:** High
**Depends on:** TASK-027 (Feed dashboard panel)
**Description:** `run_feed_ingestion()` in `feed_ingester.py` is fully built but never fires because `FEED_SOURCES` in `config/feeds.py` is empty (all commented out). The heartbeat loop already has the call site (lines 450-465 of `heartbeat.py`) that imports and calls `run_feed_ingestion()` on a 1-hour interval, and handles pool expiry + capping. But with an empty source list, nothing happens.

Fix:
1. Populate `FEED_SOURCES` in `config/feeds.py` with 3-5 real RSS feeds appropriate for the shopkeeper character (art, Tokyo culture, literature, antiques, curiosities).
2. Verify that after one ingestion cycle, `content_pool` has >0 rows and the Content Pool dashboard panel shows items.

The heartbeat wiring already exists — this task is about populating the config and verifying end-to-end flow.

**Scope (files you may touch):**
- `config/feeds.py` (populate FEED_SOURCES with real RSS feeds)

**Scope (files you may NOT touch):**
- `feed_ingester.py` (already complete)
- `db/content.py` (already complete)
- `heartbeat.py` (wiring already exists)
- `pipeline/*`
- `window/`

**Tests:** Run `python -c "import asyncio; from feed_ingester import run_feed_ingestion; print(asyncio.run(run_feed_ingestion()))"` and verify return value > 0. Check `content_pool` table has rows. Content Pool dashboard panel shows items after ingestion.
**Definition of done:** `FEED_SOURCES` contains 3-5 working RSS feeds. Feed ingestion runs successfully and populates the content pool. Dashboard reflects the ingested content.

---

### TASK-034: Integrate markdown.new into feed enrichment pipeline
**Status:** DONE (2026-02-16)
**Priority:** Medium
**Depends on:** TASK-033 (feed pipeline live)
**Description:** Replace or augment the current `fetch_readable_text()` in `pipeline/enrich.py` with markdown.new API calls. Current enrichment fetches raw HTML and extracts text — wasteful on tokens and blind to multimedia content.
markdown.new converts any URL to clean markdown. Benefits:
- **Articles/essays:** Strips nav, ads, footers. Clean prose only. Major token savings.
- **YouTube/video:** Extracts transcript + metadata (title, channel, duration). She can "watch" videos.
- **Music links (Spotify, Bandcamp, SoundCloud):** Extracts track metadata, descriptions, liner notes. She can "listen" to music.
- **Image-heavy pages:** Extracts alt text, captions, surrounding context. She can "see" visual content.
This unlocks new content types in the feed. Currently FEED_SOURCES are text-only RSS. After this, you can add YouTube channels, Spotify playlists, music blogs with embedded players — she consumes them all as markdown.
**Implementation:**
1. Add `fetch_via_markdown_new(url: str) -> str` to `pipeline/enrich.py`. Call `https://markdown.new/api/v1/convert?url={url}` (or equivalent endpoint). Return clean markdown string.
2. Update `fetch_readable_text()` to try markdown.new first, fall back to current extraction if the service is unavailable or returns error.
3. Update `feed_ingester.py` content type detection: if markdown.new returns a transcript → tag as `video`. If it returns track metadata → tag as `music`. If it returns prose → tag as `article`. Store the content type in `content_pool.content_type`.
4. Update `config/feeds.py`: add 2-3 multimedia sources as examples:
   - A YouTube channel RSS (e.g., NHK World, Tokyo street walks, ambient music mixes)
   - A music blog or Bandcamp tag feed
5. Add rate limiting / caching: don't hit markdown.new more than once per URL. Store the converted markdown in `content_pool.enriched_text` (add column if needed via migration).
**Scope (files you may touch):**
- `pipeline/enrich.py` (add markdown.new fetch, update fallback chain)
- `feed_ingester.py` (content type detection from enriched output)
- `config/feeds.py` (add multimedia feed sources)
- `db/content.py` (add enriched_text column query if needed)
- `migrations/` (new migration if schema change needed)
**Scope (files you may NOT touch):**
- `pipeline/cortex.py`
- `pipeline/basal_ganglia.py`
- `heartbeat.py`
- `heartbeat_server.py`
- `window/`
**Tests:**
- test_markdown_new_article — URL returns clean markdown, stripped of HTML
- test_markdown_new_video — YouTube URL returns transcript + metadata
- test_markdown_new_fallback — service unavailable, falls back to current extraction
- test_content_type_detection — video transcript tagged as "video", music as "music", prose as "article"
- test_no_duplicate_enrichment — same URL not fetched twice
**Definition of done:** Feed pipeline enriches URLs via markdown.new. She can consume articles, videos, and music from the same pipeline. Content pool shows mixed content types. Token usage per item drops measurably vs raw HTML extraction.

---

### TASK-035: Shop open/close as pipeline choice, not auto-managed
**Status:** DONE (2026-02-16)
**Priority:** High
**Depends on:** TASK-032 (generative/reflexive tagging)
**Description:** The shop auto-reopens every cycle via heartbeat.py:412-415 if energy > 0.5, creating an oscillation loop with the close_shop habit (14 closes/day on already-closed shop). Same design flaw as pre-TASK-012 engagement — forced state change instead of pipeline choice.
Fix: Remove auto-reopen from heartbeat.py entirely. Add `open_shop` as a new reflexive action. She decides when to open and close through the normal pipeline.
**Implementation:**
1. **heartbeat.py** — Remove the auto-reopen block at lines 412-415. Shop status only changes via actions.
2. **pipeline/action_registry.py** — Add `open_shop` action:
   - `enabled=True`
   - `generative=False` (reflexive — no LLM output needed)
   - `energy_cost=0.0`
   - Prerequisite: shop must be currently closed
3. **pipeline/body.py** — Add `open_shop` execution handler. Sets shop status to 'open' in room_state. Mirror of close_shop handler.
4. **pipeline/basal_ganglia.py** — Add drive gates:
   - `open_shop`: require `energy > 0.3` AND `rest_need < 0.6`
   - `close_shop`: require shop is open (already exists, verify it works without auto-reopen)
5. **prompt_assembler.py** — Ensure current shop status and time of day are in cortex context so she can reason about when to open/close. Add a light hint: "The shop is currently [open/closed]. It is [time]." No instruction on when to open — she figures that out.
6. **pipeline/hypothalamus.py** — No new drive needed. Opening the shop is motivated by existing drives: social_hunger (want visitors), energy (have capacity), rest_need (not exhausted).
**Expected emergent behavior:**
- She opens in the morning when energy is high and social hunger has built overnight
- She closes at night when energy drops or rest need rises
- These form habits naturally: open_shop in morning context, close_shop in evening/night context
- On low-energy days she might open late or not at all — genuine variation
**Scope (files you may touch):**
- `heartbeat.py` (remove auto-reopen)
- `pipeline/action_registry.py` (add open_shop)
- `pipeline/body.py` (add open_shop handler)
- `pipeline/basal_ganglia.py` (add drive gates)
- `prompt_assembler.py` (ensure shop status + time in context)
- `db.py` (only if room_state update needs a new function — at END of file)
- `models/pipeline.py` (if ActionCapability needs updating)
**Scope (files you may NOT touch):**
- `pipeline/cortex.py`
- `pipeline/sensorium.py`
- `sleep.py`
- `heartbeat_server.py`
- `window/`
**Tests:**
- test_auto_reopen_removed — shop stays closed after close_shop, no auto-reopen on next cycle
- test_open_shop_action — open_shop changes room_state from closed to open
- test_open_shop_drive_gate — blocked when energy < 0.3 or rest_need > 0.6
- test_open_shop_prerequisite — blocked when shop already open
- test_close_shop_prerequisite — blocked when shop already closed
**Definition of done:** No auto-reopen in heartbeat. Shop status changes only through pipeline actions. open_shop and close_shop are both reflexive, drive-gated actions. She decides her own hours.

---

### TASK-036: System brakes — habit decay, mood scaling, energy budget enforcement
**Status:** DONE (2026-02-16)
**Priority:** High
**Depends on:** TASK-024 (homeostatic pull), TASK-032 (drive gates)
**Description:** The system has no natural braking mechanism. Actions create drive relief → more actions → stronger habits → habits never decay → positive feedback loop. Three fixes that add brakes.
**Part A — Habit decay**
In `pipeline/output.py`, after `track_action_pattern()`: for every habit in the DB that was NOT fired this cycle, apply time-based decay:
- `strength -= 0.01 * elapsed_hours`
- A habit at 0.9 that stops firing drops below 0.6 auto-fire threshold in ~30 hours
- Delete habits that fall below 0.05
- Only decay habits that haven't fired in the current cycle (don't decay what just strengthened)
**Part B — Mood success bonus scaling**
In `pipeline/output.py`, replace the flat +0.02 mood bonus per successful action with a diminishing formula:
- `bonus = 0.02 / (1 + actions_today / 10)`
- First 10 actions: near-full bonus (~0.02–0.01)
- After 30 actions: bonus drops to ~0.005
- This models emotional habituation — the 40th journal doesn't feel as good as the first
- Get `actions_today` count from db (or pass it in from heartbeat) before applying bonus
**Part C — Energy budget enforcement**
In `heartbeat.py`, before calling cortex in `run_cycle()`:
- Check energy spent today vs daily budget (from config or db)
- If `spent >= budget`: force rest mode — skip cortex entirely, apply rest recovery to drives (`rest_need -= 0.05`, `energy += 0.03`), log `[Heartbeat] Resting — energy budget exceeded`
- Exception: high-salience events (visitor connect with salience > 0.8) override the rest mode — she can still wake up for important moments
- This gives the energy budget actual teeth instead of being display-only
**Scope (files you may touch):**
- `pipeline/output.py` (habit decay + mood scaling)
- `heartbeat.py` (budget enforcement)
- `db/analytics.py` (if energy budget query needs updating)
- `db/memory.py` (if habit deletion function needed — at END of file)
- `models/pipeline.py` (if CycleOutput needs a rest_mode flag)
**Scope (files you may NOT touch):**
- `pipeline/cortex.py`
- `pipeline/basal_ganglia.py`
- `pipeline/sensorium.py`
- `heartbeat_server.py`
- `window/`
- `sleep.py`
**Tests:**
Part A:
- test_unfired_habit_decays — habit not fired loses strength over time
- test_fired_habit_no_decay — habit that just fired doesn't decay in same cycle
- test_habit_deleted_below_threshold — habit at 0.05 decays and is removed
- test_decay_rate — 0.9 strength drops below 0.6 within ~30 simulated hours
Part B:
- test_mood_bonus_first_action — near +0.02 when actions_today is low
- test_mood_bonus_diminishes — significantly less after 30+ actions
- test_mood_bonus_never_negative — formula always returns positive value
Part C:
- test_budget_exceeded_forces_rest — no cortex call when budget exceeded
- test_rest_mode_recovers_drives — rest_need decreases and energy increases during rest
- test_high_salience_overrides_rest — visitor event with salience > 0.8 still triggers cortex
- test_under_budget_runs_normally — normal cycle when budget not exceeded
**Definition of done:** Habits weaken when unused. Mood bonus diminishes with repetition. Energy budget forces rest when exceeded (except for important events). The positive feedback loop is broken — the system has natural brakes.

---

### TASK-037: Dashboard cycle interval control
**Status:** DONE (2026-02-16)
**Priority:** Medium
**Description:** Add a cycle interval slider/input to the Controls panel so the operator can adjust heartbeat frequency from the dashboard without SSH. Currently the interval is hardcoded in config.
**Implementation:**
1. **Controls panel** — Add an input field showing current cycle interval in seconds. Editable. Min 10s, max 600s. Apply button or debounced auto-apply.
2. **API endpoint** — `POST /api/dashboard/cycle-interval` accepts `{interval_seconds: number}`. Auth required. Validates min/max bounds.
3. **heartbeat.py** — Read interval from a mutable source (DB setting or in-memory variable) instead of hardcoded config. API endpoint updates this value. Takes effect on next cycle without restart.
4. **Controls panel display** — Show current interval next to heartbeat status. "Every 30s" / "Every 3m" etc.
**Scope (files you may touch):**
- `window/src/components/dashboard/ControlsPanel.tsx`
- `api/dashboard_routes.py`
- `heartbeat_server.py` (route dispatch)
- `heartbeat.py` (read mutable interval)
- `config/` (default interval value)
- `db.py` (if persisting interval as a setting — at END of file only)
- `window/src/lib/types.ts`
- `window/src/lib/dashboard-api.ts`
**Scope (files you may NOT touch):**
- `pipeline/*`
- `sleep.py`
**Tests:**
- test_interval_update_api — POST changes interval, GET reflects new value
- test_interval_bounds — rejects below 10s and above 600s
- test_interval_auth — returns 401 without auth
**Definition of done:** Operator can change cycle interval from dashboard. Change takes effect next cycle. No restart needed.

---

### TASK-038: Replace rest mode with nap consolidation
**Status:** DONE (2026-02-16)
**Priority:** High
**Depends on:** TASK-036 (budget enforcement)
**Description:** When energy budget is exceeded, the system enters empty rest loops — no LLM call, no actions, no thoughts, just a hardcoded placeholder string cycling every 20s until midnight. She's effectively lobotomized. Replace with nap behavior: she processes recent moments, writes real reflections, wakes with partial budget.
**Implementation:**
1. **sleep.py** — Add `nap_consolidate(db, top_n=3)`:
   - Fetch top 3 unprocessed day_moments by salience
   - Run `sleep_reflect()` on each (same LLM reflection as night sleep)
   - Write reflections as individual journal entries
   - Mark moments as `nap_processed=True` (don't re-process during night sleep)
   - Return number of moments processed
2. **heartbeat.py** — Replace rest mode:
   - When budget exceeded: check nap cooldown (minimum 2 hours since last nap)
   - If cooldown elapsed: trigger `nap_consolidate()`, restore 1.0 energy budget, log `[Heartbeat] Nap — consolidated N moments, budget restored to X`
   - If cooldown not elapsed: skip cycle entirely (no empty rest loop). Just sleep the interval and check again. Log `[Heartbeat] Resting — nap cooldown (Xm remaining)`
   - Remove the empty rest loop path entirely — no more token_budget=0 placeholder cycles
3. **pipeline/day_memory.py** — Add `nap_processed` handling:
   - `maybe_record_moment()` unchanged
   - Night sleep query: exclude moments where `nap_processed=True` (already reflected on)
   - Or: let night sleep re-process nap moments at deeper level (design choice — start with exclude)
4. **db/memory.py** — Add `nap_processed` column to day_moments if needed (migration). Add `mark_moments_nap_processed(ids)` function. Add `get_top_unprocessed_moments(limit)` that excludes nap_processed.
5. **Timeline event** — Nap cycles should appear as `action_nap` in the timeline, distinct from `action_body`. The dashboard should show naps as a visible event.
6. **Visitor override** — Salience > 0.8 still wakes her from nap cooldown. If a visitor arrives during cooldown, skip the cooldown and run a normal cycle.
**Expected behavior:**
- Active morning: ~2 hours of cycles, hits budget
- Nap: consolidates top 3 moments, reflections written, wakes with +1.0 budget
- Active afternoon: another ~2 hours, hits budget again
- Second nap: consolidates next batch
- Evening: winds down, closes shop
- Night: full sleep consolidation of remaining unprocessed moments
**Scope (files you may touch):**
- `heartbeat.py` (replace rest mode with nap trigger)
- `sleep.py` (add nap_consolidate function)
- `pipeline/day_memory.py` (nap_processed handling)
- `db/memory.py` (new query functions, migration if needed)
- `migrations/` (add nap_processed column if needed)
- `models/pipeline.py` (if nap event type needed)
**Scope (files you may NOT touch):**
- `pipeline/cortex.py`
- `pipeline/basal_ganglia.py`
- `pipeline/output.py`
- `heartbeat_server.py`
- `window/`
**Tests:**
- test_nap_triggers_on_budget_exceeded — budget exceeded + cooldown elapsed → nap runs
- test_nap_cooldown_enforced — budget exceeded + cooldown not elapsed → skip, no empty loop
- test_nap_restores_partial_budget — after nap, budget has +1.0 headroom
- test_nap_processes_top_moments — top 3 by salience are reflected on
- test_nap_moments_excluded_from_night_sleep — nap_processed moments not re-processed
- test_visitor_overrides_nap_cooldown — high salience visitor wakes her during cooldown
- test_no_empty_rest_loops — budget exceeded never produces token_budget=0 placeholder cycles
**Definition of done:** Budget exceeded triggers nap consolidation, not lobotomy. She processes moments, writes real reflections, wakes with partial budget. Timeline shows nap events. No more empty rest loops. Natural rhythm of active → nap → active → full night sleep.

---

### TASK-039: Isolation Experiment Analysis Pipeline
**Status:** READY
**Priority:** High (paper blocker)
**Branch:** feat/experiment-analysis
**Context:** For the research paper, we need to prove The Shopkeeper generates diverse, non-repetitive behavior without user input. The data already exists in cycle_log — we just need export + analysis + visualization.
**FILES TO CREATE:**
1. `experiments/export_cycles.py` — Reads SQLite DB, exports cycle_log to JSONL
2. `experiments/generate_baseline.py` — Generates null-hypothesis baseline from timestamps
3. `experiments/analyze_entropy.py` — Computes Shannon entropy, generates matplotlib figures
**FILES TO MODIFY:** None. Read-only access to DB via sqlite3 (not the async db module).
**DEPENDENCIES:** matplotlib, numpy (add to requirements.txt if missing)
**DO NOT MODIFY:** Any existing source files. This is a pure analysis layer that reads the DB the system already populates.
**Scope (files you may touch):**
- `experiments/export_cycles.py` (new)
- `experiments/generate_baseline.py` (new)
- `experiments/analyze_entropy.py` (new)
- `experiments/__init__.py` (new)
- `tests/test_export_cycles.py` (new)
- `tests/test_entropy.py` (new)
- `tests/test_baseline.py` (new)
- `requirements.txt` (add matplotlib, numpy)
**Scope (files you may NOT touch):**
- All existing Python source files
- `db/` (read-only access via sqlite3)
- `pipeline/*`
- `heartbeat.py`
- `window/`
**Tests:**
- test_export reads a test DB with 10 known cycles, verifies JSONL output matches
- test_entropy with a hand-crafted 4-action uniform distribution verifies H = 2.0 bits
- test_baseline verifies all routing_focus values are "idle"
**Definition of done:** Three standalone scripts that export, baseline, and analyze cycle_log data. Shannon entropy figure shows non-trivial behavioral diversity. All tests pass.

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
