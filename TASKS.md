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

### TASK-048: Run 7-day experiment v2 — three-budget sweep

**Status:** DONE (2026-02-25 — Runs A & B complete; superseded by isolation ablation study)
**Priority:** Critical (paper blocker)
**Branch:** feat/experiment-v2

**Context:** The original 7-day experiment ran pre-curiosity-v2, pre-mood-coupling, pre-salience-engine. A new experiment demonstrates: stimulus-driven curiosity, epistemic question formation/resolution, drive-coupled mood, meaningful sleep consolidation, and nap cycles. Three budget levels provide the ablation study both reviewers requested.

**Description:** Run three 7-day simulations with identical visitor scripts and content, varying only energy budget. This produces the budget-entropy relationship figure and validates all subsystems end-to-end.

**Pre-run checklist:**

1. TASK-046 merged and tested (mood-drive coupling)
1. TASK-047 merged and tested (sleep salience fix)
1. Content pool has 10+ items (from TASK-033 feeds or manual content/readings.txt)
1. `simulate.py` runs for 10 cycles without errors
1. Quick validation — run 50 cycles, check:
- `SELECT COUNT(*) FROM day_moments;` → > 0
- `SELECT diversive_curiosity FROM drives_state;` → between 0.15-0.65
- `SELECT AVG(mood_valence) FROM drives_state_history WHERE social_hunger > 0.5;` → < 0.6

**Run order (cost-conscious — validate before burning $225):**

**Run A first (tight budget, energy_budget=2.0):**

- Most behavioral diversity, most nap cycles, richest data
- ~$75 API cost, ~4-6 hours
- After completion, validate:

  ```sql
  SELECT COUNT(*) FROM day_moments;                    -- > 0
  SELECT COUNT(*) FROM epistemic_curiosities;          -- > 0
  SELECT COUNT(*) FROM content_pool WHERE consumed=1;  -- > 0
  SELECT moment_count FROM daily_summaries;            -- non-zero values
  ```
- If any of these are 0: STOP. Debug before running B and C.

**Run B (medium budget, energy_budget=4.0):**

- Only if Run A validates cleanly
- Baseline comparison

**Run C (generous budget, energy_budget=8.0):**

- Only if Run A validates cleanly
- Matches original experiment parameters

**Command per run:**

```bash
python simulate.py --days 7 --visitors experiments/visitors.json \
  --content content/readings.txt --energy-budget {2.0|4.0|8.0} \
  --output experiments/run_{a|b|c}/
```

If `--energy-budget` flag doesn't exist in simulate.py, add it (pass through to config or heartbeat init).

**Post-run analysis per DB:**

```sql
-- 1. Salience engine working?
SELECT COUNT(*) FROM events WHERE salience_dynamic > 0;

-- 2. Day memory filling?
SELECT COUNT(*) FROM day_moments;

-- 3. Sleep non-hollow?
SELECT date, json_extract(summary, '$.moment_count') as moments,
       json_extract(summary, '$.emotional_arc') as arc
FROM daily_summaries ORDER BY date;

-- 4. Epistemic curiosities lifecycle?
SELECT topic, question, intensity, resolved, source_type
FROM epistemic_curiosities;

-- 5. Content consumed?
SELECT COUNT(*) FROM content_pool WHERE consumed = 1;

-- 6. Diversive curiosity not pinned?
SELECT diversive_curiosity FROM drives_state;

-- 7. Mood-drive correlation (the chart that answers both reviewers)
SELECT
  CAST(julianday(timestamp) - julianday((SELECT MIN(timestamp) FROM drives_state_history)) AS INT) as sim_day,
  AVG(social_hunger) as avg_hunger,
  AVG(mood_valence) as avg_valence,
  AVG(mood_arousal) as avg_arousal
FROM drives_state_history
GROUP BY sim_day
ORDER BY sim_day;
-- Valence should trend INVERSELY with social_hunger across days
-- Arousal should spike on visitor days, decay on isolation days
```

**Generate figures using experiments/analyze_entropy.py (TASK-039):**

1. 3-way entropy comparison (tight vs medium vs generous)
1. Drive trajectory comparison — mood now tracks social_hunger inversely
1. Sleep consolidation quality — moment counts per night across budgets
1. Nap frequency comparison across budget levels
1. Epistemic curiosity formation/resolution counts per run
1. Mood-drive correlation scatter plot (valence vs social_hunger, colored by day)

**Expected outputs per run:**

- SQLite DB (~4MB)
- Timeline log (~100KB)

**Scope:** `simulate.py` execution + analysis scripts only. No code changes except possibly adding `--energy-budget` flag to simulate.py.

**Definition of done:** Three 7-day simulation DBs with timeline logs. Analysis figures showing: budget-entropy relationship, drive-mood coupling, non-hollow sleep consolidation, epistemic curiosity lifecycle, arousal response to visitors. All seven post-run queries return non-trivial results for all three runs. Data ready for paper revision.

---

### TASK-055: Extract pipeline parameters to self_parameters DB table
**Status:** DONE (2026-02-18)
**Priority:** High (infrastructure for TASK-056)
**Complexity:** Large — touches every pipeline module
**Branch:** `feat/self-parameters`
**Depends on:** TASK-054
**Description:** All ~50 cognitive architecture constants are hardcoded in Python files (drive equilibria, routing thresholds, salience weights, gate parameters, inhibition rates, sleep params). Extract them to a `self_parameters` DB table with bounds, modification tracking, and a per-cycle cached load. Required infrastructure for TASK-056 self-modification.
**Scope (files you may touch):**
- `db/parameters.py` (new — get_param, set_param, get_params_by_category, reset_param, get_modification_log)
- `pipeline/hypothalamus.py` (replace hardcoded drive constants)
- `pipeline/thalamus.py` (replace routing thresholds)
- `pipeline/sensorium.py` (replace salience weights)
- `pipeline/basal_ganglia.py` (replace gate parameters)
- `pipeline/output.py` (replace inhibition parameters)
- `sleep.py` (replace consolidation parameters)
- `heartbeat.py` (load params at cycle start, pass through pipeline)
- `migrations/` (new table + seed data)
- `heartbeat_server.py` or `api/dashboard_routes.py` (new parameters endpoint)
- `window/src/components/dashboard/ParametersPanel.tsx` (new)
**Scope (files you may NOT touch):**
- `pipeline/cortex.py`
- `simulate.py`
**Tests:**
- Unit: `get_param` returns correct values
- Unit: `set_param` enforces bounds (rejects out-of-range)
- Unit: `reset_param` restores default
- Integration: pipeline produces identical output with DB params vs old hardcoded values
- Regression: run 50 cycles, verify behavior unchanged
**Definition of done:** All ~50 pipeline constants in `self_parameters` table. Pipeline reads from DB (cached per cycle). Dashboard shows parameters with modification tracking. System behavior identical to pre-migration.

---

### TASK-056: Dynamic action registry + modify_self action
**Status:** DONE (2026-02-19, Phase 5 complete — sleep auto-promote)
**Priority:** High (the self-modification capability)
**Complexity:** Large
**Branch:** `feat/dynamic-actions`
**Depends on:** TASK-055
**Description:** Two problems: (A) She invents ~100 unique action names that don't exist (browse_web: 242, stand: 118, make_tea: 17, etc.) — all discarded as `incapable`, she never learns. (B) She has no conscious mechanism to adjust her own cognitive parameters. Fix both: dynamic action registry with alias/body_state/pending resolution, and a `modify_self` action gated behind reflection evidence.
**Scope (files you may touch):**
- `pipeline/basal_ganglia.py` (action resolution: static → dynamic alias → body_state → pending; modify_self gating)
- `pipeline/output.py` (modify_self execution, self-modification logging)
- `db/actions.py` (new — dynamic_actions CRUD)
- `db/parameters.py` (extend with modification logging)
- `sleep.py` (meta-sleep review phase — revert degraded modifications)
- `heartbeat.py` (pass dynamic actions to pipeline)
- `migrations/` (dynamic_actions table + seed data)
- `window/src/components/dashboard/ActionsPanel.tsx` (new)
**Scope (files you may NOT touch):**
- `pipeline/cortex.py`
- `simulate.py`
**Tests:**
- Unit: action resolution order (static → dynamic alias → body_state → pending)
- Unit: browse_web resolves to read_content
- Unit: stand creates body_state update
- Unit: unknown action creates pending entry, promotes after 5 attempts
- Unit: modify_self rejected without recent reflection evidence
- Unit: modify_self respects parameter bounds
- Unit: meta-sleep review reverts degraded modifications
- Integration: run 100 cycles, verify dynamic actions accumulate and aliases work
**Definition of done:** browse_web redirects to read_content. Physical actions update room_state. Unknown actions tracked and auto-promoted. modify_self works with reflection prerequisite. Nightly meta-review evaluates and can revert. Dashboard shows registry and modification history. She stops wasting 242 cycles on `incapable`.

---

### TASK-058: Production Visitor UI — Full Redesign
**Status:** DONE (2026-02-18)
**Priority:** High
**Branch:** `feat/visitor-ui`
**Spec:** `tasks/TASK-058-visitor-ui.md`
**Description:** Replace the current `window/` Next.js app with the "Through the Glass" production visitor experience. A living scene — Tokyo antique shop at night, peering through the window. Activity stream, expression-driven character sprites, token-gated chat panel. Not a chatbot.
**Scope (files you may touch):**
- `window/` — full replacement (App Router, TypeScript, Tailwind, no component library)
**Scope (files you may NOT touch):**
- All Python backend files
- `heartbeat_server.py` WebSocket endpoints (read-only — frontend consumes existing protocol)
- `db.py`
**Tests:** See acceptance criteria in `tasks/TASK-058-visitor-ui.md` (11 criteria).
**Definition of done:** All 11 acceptance criteria pass. Visual tuning values in CSS custom properties. Works on iPhone Safari + Android Chrome.

---

### TASK-059: OpenRouter Multi-LLM Integration
**Status:** DONE
**Completed:** 2026-02-19
**Priority:** High
**Branch:** `feat/openrouter`
**Spec:** `tasks/TASK-059-openrouter.md`
**Description:** Route all LLM calls through OpenRouter so different models can power different parts of her cognition. Single API key, unified billing, 200+ models. Cognitive architecture is model-agnostic; only the API routing changes.
**Scope (files you may touch):**
- `llm/__init__.py` (new)
- `llm/client.py` (new — OpenRouter HTTP client)
- `llm/config.py` (new — model resolution: DB → env → default)
- `llm/format.py` (new — Anthropic ↔ OpenAI format translation)
- `llm/cost.py` (new — cost logging per call)
- `pipeline/cortex.py` (replace Anthropic SDK call)
- `sleep.py` (replace Anthropic SDK calls)
- `pipeline/embed.py` (replace embedding call if applicable)
- `requirements.txt` (add httpx, eventually remove anthropic)
- `migrations/` (extend llm_costs table with model + call_site + latency_ms)
- `tests/test_llm_format.py` (new)
- `tests/test_llm_config.py` (new)
- `tests/test_llm_cost.py` (new)
**Scope (files you may NOT touch):**
- `pipeline/prompt_assembler.py`
- `pipeline/validator.py`
- `pipeline/basal_ganglia.py`
- `heartbeat.py` (unless needed for config loading)
- `window/*`
**Tests:** See testing section in `tasks/TASK-059-openrouter.md` (unit + integration + 50-cycle regression).
**Definition of done:** All 9 criteria in spec — all LLM calls via OpenRouter, model configurable per call site, cost logging includes model/call_site/latency, Anthropic SDK no longer called directly, format translation transparent, 50-cycle regression passes.

---

### TASK-060: Self-Context Injection
**Status:** DONE (2025-02-19)
**Priority:** High
**Complexity:** Medium
**Branch:** `feat/self-context`
**Depends on:** TASK-065 merge (budget must exist first), TASK-059, TASK-064
**Blocks:** TASK-061 (self-model), TASK-062 (drift detection)
**Spec:** `tasks/TASK-060-self-context.md`
**Description:** Give the Shopkeeper awareness of her own state by injecting a structured self-context block into the LLM prompt each cycle. She currently has drives, memory, and scene context but no unified "here's who I am right now" snapshot. This is the foundation for 061-063 (identity evolution chain). Self-context is read-only in this task — she sees herself but doesn't modify herself yet (that's 061+).
**Self-context block contents:**
1. Identity summary — name, role, core traits (static seed, evolves in 061+)
2. Current state snapshot — body state, energy, mood, active drives
3. Recent behavioral summary — last N actions taken, any habits formed
4. Temporal awareness — cycle count, time of day, time since last sleep
**Scope (files you may touch):**
- `prompt/self_context.py` (new — assembles the self-context block)
- `pipeline/cortex.py` (post-059 — inject self-context into prompt assembly)
**Scope (files you may NOT touch):**
- `pipeline/basal_ganglia.py`
- `simulate.py`
**Rules:**
- Self-context is read-only — she sees herself but doesn't modify herself yet (that's 061+)
- Must fit within the token budget allocated by TASK-065
- Content is assembled fresh each cycle, not cached
- Format: structured text block, not JSON — the LLM reads it as natural language
**Tests:**
- Self-context block appears in prompt when enabled
- Token count stays within budget allocation
- Content accurately reflects current state (compare against actual drive/energy/mood values)
- No behavioral change in output — this is additive context, not a directive
**Definition of done:** Self-context block injected into every LLM prompt. Contains identity summary, current state, recent behavior, and temporal awareness. Respects TASK-065 token budget. Content is accurate and assembled fresh each cycle. Read-only — no self-modification capability yet.

---

### TASK-061: Persistent Self-Model
**Status:** DONE (2026-02-19)
**Priority:** High
**Complexity:** Medium
**Branch:** `feat/self-model`
**Depends on:** TASK-060 (waived by operator)
**Blocks:** TASK-062
**Spec:** `tasks/TASK-061-self-model.md`
**Description:** She maintains a structured representation of "who I am" that persists across cycles and updates incrementally based on observed behavior. TASK-060 gives her a per-cycle snapshot, but snapshots are stateless — she can't notice patterns in herself without a persistent baseline to compare against. The self-model is that baseline.
**Self-model contents:**
- Trait weights — derived from behavioral patterns, not declared (emergent, not seeded)
- Behavioral signature — rolling averages of action frequencies, drive response patterns, sleep/wake rhythms
- Relational stance — how she tends to engage with visitors (warm/guarded/curious), derived from conversation patterns
- Self-narrative — short natural language summary she generates about herself, updated periodically (not every cycle)
**Where it lives:**
- `identity/self_model.json` — persisted to disk
- Loaded at boot, updated at end of each wake cycle (not during sleep — sleep reads but doesn't write)
**How it updates:**
- After each cortex cycle, `self_model.update(cycle_data)` compares this cycle against rolling averages
- Exponential moving average — recent behavior weights more, but change is gradual
- Self-narrative regeneration triggers only when trait weights shift beyond a threshold (expensive LLM call, not every cycle)
**What it does NOT do:**
- No decision-making — the self-model is a mirror, not a controller
- No direct influence on cortex prompt (060's job to inject it as context)
- No evolution or acceptance of drift (that's 063)
**Scope (files you may touch):**
- `identity/self_model.py` (new — SelfModel class, update logic, persistence)
- `identity/self_model.json` (new — persisted model state)
- Cortex cycle end (add `self_model.update()` call)
**Scope (files you may NOT touch):**
- `pipeline/cortex.py` (internal LLM call logic)
- `pipeline/basal_ganglia.py`
- `simulate.py`
**Tests:**
- Self-model file persists across restarts
- Trait weights shift measurably after 20+ cycles of consistent behavior
- Self-narrative updates only when threshold crossed
- No performance impact on cycle time (update is fast, narrative regen is async/deferred)
**Definition of done:** Self-model persists to disk and loads at boot. Trait weights are emergent from behavior, not seeded. Behavioral signature tracks rolling averages. Self-narrative regenerates only on threshold shift. No decision-making — read-only mirror of identity.

---

### TASK-062: Drift Detection
**Status:** DONE (2026-02-19)
**Priority:** High
**Complexity:** Medium
**Branch:** `feat/drift-detection`
**Depends on:** TASK-061 (building with interface stub — self-model not yet implemented)
**Blocks:** TASK-063
**Spec:** `tasks/TASK-062-drift-detection.md`
**Description:** Compare her current behavioral patterns against her self-model baseline. Detect when she's meaningfully diverging from her established identity. Drift is NOT deviation in a single cycle — it's a sustained divergence over N cycles (configurable, default ~20) where behavioral patterns consistently differ from the self-model baseline.
**Metrics to compare:**
- Action frequency distribution (current rolling window vs self-model signature)
- Drive response patterns (how she responds to high hunger vs how she used to)
- Conversation style metrics (response length, question frequency, emotional tone)
- Sleep/wake rhythm deviation
**Detection method:**
- Per-metric drift score: `abs(current_rolling_avg - baseline) / baseline`
- Composite drift score from individual scores
- Threshold: `>0.3` = notable drift, `>0.5` = significant drift (configurable in `identity/drift_config.json`)
**What happens when drift is detected:**
- Drift event emitted (visible on dashboard, logged)
- Drift summary injected into self-context (060's block): "I've been more withdrawn than usual for the past 15 cycles"
- No automatic correction — drift is information, not a problem to solve. 063 decides what to do with it.
**Scope (files you may touch):**
- `identity/drift.py` (new — drift scoring, detection, event emission)
- `identity/drift_config.json` (new — thresholds, window sizes)
- Cycle end (add drift check after self-model update)
- 060's self-context block (inject drift summary when active)
- Dashboard: drift indicator in DrivesPanel or new panel
**Scope (files you may NOT touch):**
- `pipeline/cortex.py`
- `pipeline/basal_ganglia.py`
- `simulate.py`
**Tests:**
- Force behavioral shift in test (suppress all social actions for 30 cycles) → drift detected
- Return to normal behavior → drift score decreases
- Dashboard shows drift event
- Self-context includes drift summary when active
**Definition of done:** Drift detection runs after each self-model update. Sustained divergence (not single-cycle noise) triggers drift events. Dashboard shows drift indicators. Self-context includes drift summary when active. No automatic correction.

---

### TASK-063: Identity Evolution (STUB)
**Status:** DONE (2026-02-18)
**Priority:** High
**Complexity:** Large
**Branch:** `feat/identity-evolution`
**Depends on:** TASK-062
**Blocks:** Nothing (end of chain)
**Spec:** `tasks/TASK-063-identity-evolution.md`
**Description:** When drift is detected, she can choose to accept the change as genuine growth or correct back toward her baseline. **THIS IS A STUB SPEC.** Implementation is gated on resolving the philosophical question: who decides what "genuine growth" vs "unwanted drift" looks like?
**The philosophical problem:**
- If she always accepts drift → identity dissolves, she becomes whatever the LLM drifts toward
- If she always corrects → she's frozen, can't grow
- If we hardcode the criteria → we're deciding her identity for her, contradicting the ALIVE premise
- If she decides → the decision itself is influenced by the current drift, creating circular dependency
**Guard rails (non-negotiable regardless of implementation):**
- Core safety traits cannot be evolved away (she can't drift into being hostile)
- Evolution rate capped — no more than one trait update per sleep cycle
- All evolution decisions logged with full context for operator review
- Operator override: dashboard can force-correct or force-accept any drift
**Scope (files you may touch):**
- `identity/evolution.py` (new — stub with interface only)
- `identity/evolution_config.json` (new — guard rail params)
- No integration with cortex or cycle — disconnected until philosophical gate passes
**Scope (files you may NOT touch):**
- `pipeline/cortex.py`
- `pipeline/basal_ganglia.py`
- `simulate.py`
**Tests (for stub):**
- Interface exists and is importable
- Guard rail config loads
- Calling any method raises NotImplementedError
- Dashboard shows evolution status as "disabled — pending review"
**Definition of done:** Interface class exists with evaluate_drift/accept_drift/correct_drift/defer methods. All methods raise NotImplementedError. Guard rail config loads. Dashboard shows disabled status. No integration with live system.

---

### TASK-064: Sleep Phase Extraction
**Status:** DONE (2026-02-19)
**Priority:** Medium
**Branch:** `refactor/sleep-phases`
**Depends on:** TASK-059 merge (holds sleep.py — don't touch LLM call signatures)
**Blocks:** TASK-065, TASK-060
**Spec:** `tasks/TASK-064-sleep-phases.md`
**Description:** Extract discrete sleep phases from `sleep.py` into separate, testable modules. Reduce `sleep.py` to an orchestrator that calls phase functions rather than containing all logic inline. TASK-059 is adding OpenRouter routing inside sleep's LLM calls, TASK-065 adds token budgeting, TASK-060+ adds self-context injection — if we don't decompose first, every future task compounds the bloat.
**Scope (files you may touch):**
- `sleep.py` (refactor — orchestrator only after this)
- `sleep/` (new directory for extracted phases)
- `tests/` (tests for each extracted phase)
**Scope (files you may NOT touch):**
- `pipeline/*`
- `heartbeat.py`
**Phases to extract (from current sleep.py):**
1. Pre-sleep consolidation — memory gathering, moment reflection, journal writes, hot/cold context
2. Nap consolidation — the lighter mid-cycle `nap_consolidate()` version
3. Dream/reflection generation — `sleep_reflect()` LLM call + helpers (`gather_hot_context`, `format_traits_for_sleep`)
4. Meta-sleep revert — `review_self_modifications()` + `review_trait_stability()` (the wellbeing heuristic)
5. Wake transition — `reset_drives_for_morning()`, `flush_day_memory()`, `manage_thread_lifecycle()`, `cleanup_content_pool()`, daily summary, cold embedding
**Rules:**
- Each phase becomes a function/module in `sleep/`
- `sleep.py` imports and calls them in sequence — no inline logic beyond orchestration
- Preserve all existing behavior exactly — this is a refactor only, no behavior changes
- Each phase must be independently testable
- Don't touch the LLM call signatures — TASK-059 is changing those. Use whatever interface exists post-059 merge
**Tests:**
- All existing sleep tests pass unchanged
- Each phase module has at least one unit test
- sleep.py line count drops by >50%
**Verification:**
- `scope-check.sh TASK-064` clean
- All existing sleep tests pass unchanged
- sleep.py line count drops by >50%
- Each phase module has at least one unit test
**Definition of done:** `sleep.py` is a thin orchestrator. Each phase is an isolated, independently testable module in `sleep/`. Adding future phases (060 self-context review, 061 organ review, 062 loop cost review, 063 fitness review) is a single file + one line in the orchestrator.

---

### TASK-065: Prompt Token Budget
**Status:** DONE (2026-02-19)
**Priority:** Medium
**Branch:** `feat/prompt-budget`
**Depends on:** TASK-064 merge (sleep phases cleaned up), TASK-059 merge (prompt structure finalized)
**Blocks:** TASK-060, TASK-061
**Spec:** `tasks/TASK-065-prompt-budget.md`
**Description:** Enforce token caps on each section of the LLM prompt to prevent context window bloat as features accumulate. TASK-060 through TASK-063 all inject new content into the prompt — without a budget, each addition creeps the token count up until we hit truncation or degraded output quality.
**Design:**
1. Define named prompt sections (system, memory, drives, scene, self_context, conversation_history)
2. Each section gets a max token allocation in config
3. Total budget = model context window minus reserved output tokens
4. Before each LLM call, `budget.py` measures each section, truncates/summarizes any that exceed their cap (oldest-first for history, least-relevant-first for memory)
5. Emit a warning log if any section hits its cap — visibility into what's getting cut
**Scope (files you may touch):**
- `prompt/budget.py` (new — token counting + section enforcement)
- `pipeline/cortex.py` (post-059 — integrate budget checks before LLM call)
- `prompt/budget_config.json` or similar (new — per-section limits)
**Rules:**
- Token counting must be fast — use tiktoken or character-estimate heuristic, not an LLM call
- Truncation strategy per section type (configurable)
- Never silently drop content — always log what was trimmed
- Budget config must be tunable without code changes
**Tests:**
- Unit: section over budget → truncated to limit
- Unit: total under budget → nothing touched
- Integration: full prompt assembly stays within model context window
- Log output shows trim events when triggered
**Definition of done:** Every prompt section has a token budget. Total prompt size is bounded. Truncation is per-section with configurable strategy. All trims are logged. Budget config is external and tunable without code changes.

---

### TASK-066: Shop Window Fix
**Status:** BACKLOG
**Priority:** Critical — the product is broken for visitors
**Branch:** `fix/shop-window`
**Depends on:** None (can start immediately)
**Spec:** `tasks/TASK-066-shop-window-fix.md`
**Description:** The shop window (public visitor-facing page) has multiple broken features: sprite not rendering, CSP blocking eval(), missing "Enter Shop" CTA, broken leave button, unreadable inner monologue text, and text overflow/truncation. The CSP eval() block is likely the root cause of several failures.
**Bugs to fix:**
1. Shopkeeper sprite not rendering — diagnose via sprite_gen.py output, asset paths, CSS/HTML image element, CSP
2. CSP eval() block — find all eval(), new Function(), string-based setTimeout/setInterval in frontend JS; replace with proper alternatives
3. "Enter Shop" CTA missing — find where it should appear (before visitor session starts), add it
4. Leave button broken — likely fixed by CSP fix, verify after
5. Inner monologue text — needs semi-transparent container/card for readability, or move to dedicated panel
6. Text overflow — content clipping without scroll (the `...` truncation)
**Scope (files you may touch):**
- `window/` — HTML/CSS/JS frontend
- `pipeline/sprite_gen.py` — sprite path generation
- `pipeline/scene.py` — valid state combos
- `heartbeat_server.py` — serves the page, WebSocket events
- Static assets / templates
**Scope (files you may NOT touch):**
- `pipeline/cortex.py`
- `db.py`
- `heartbeat.py`
**Verification:**
- Shopkeeper sprite visible in window
- Enter Shop CTA appears for new visitors
- Leave button works
- Inner monologue readable
- No CSP errors in browser console
- All functionality works without eval()
**Definition of done:** Visitors can see the shopkeeper, enter the shop, interact, and leave. No CSP violations. Inner monologue is readable. No text overflow.

---

### TASK-067: Dashboard Overhaul
**Status:** BACKLOG
**Priority:** High — operator tool is unusable
**Branch:** `fix/dashboard-overhaul`
**Depends on:** None (can start immediately)
**Spec:** `tasks/TASK-067-dashboard-overhaul.md`
**Description:** The operator dashboard has critical usability issues: page doesn't scroll, behavioral section cut off, habit tags overlapping, poor visual hierarchy, and potential data gaps between what the system emits and what the dashboard displays.
**Fixes:**
1. Scrollable layout — page must scroll; likely CSS `overflow: hidden` or missing viewport setup
2. Behavioral section — cut off, needs full visibility
3. Habit tags — overlapping colored labels need spacing/wrapping
4. Visual hierarchy — headers, spacing, card styling (functional, not beautiful)
5. Data completeness — audit emitted data vs displayed data, flag gaps
**Scope (files you may touch):**
- `window/` — dashboard HTML/CSS/JS
- `heartbeat_server.py` — data emission for dashboard
**Scope (files you may NOT touch):**
- `pipeline/*`
- `db.py`
- `heartbeat.py`
**Verification:**
- Full page scrolls
- All sections fully visible
- Habit tags readable with proper spacing
- All emitted data represented on dashboard
**Definition of done:** Dashboard is scrollable, all sections visible and readable, habit tags properly spaced, all system-emitted data has a corresponding display element.

---

### TASK-068: Behavioral Health Diagnostic
**Status:** BACKLOG
**Priority:** Medium
**Description:** Reusable diagnostic an agent runs on demand to catch system-level behavioral bugs before they compound. Run after any soak test, before any deploy, or whenever something "feels off." Checks: memory pool health, action loop detection, drive stagnation, LLM output quality, sleep cycle health, context completeness, frontend/visitor health.
**Spec:** `docs/DIAGNOSTIC-068.md`
**Scope (files you may touch):**
- `docs/DIAGNOSTIC-068.md` (the diagnostic runbook — already created)
**Scope (files you may NOT touch):**
- All source files (this is a read-only diagnostic, not a code change)
**Tests:** Agent runs all 7 checks against a live or simulation DB and reports PASS/WARN/FAIL with evidence.
**Definition of done:** `docs/DIAGNOSTIC-068.md` exists with all 7 check sections. Any agent can run it by reading the file and executing the queries/checks. Output format is standardized.

---

### TASK-069: Real-World Body Actions — Web Browse + Telegram Shopfront + X Social
**Status:** DONE (2026-02-19)
**Priority:** High
**Complexity:** Large
**Branch:** `feat/real-body-actions`
**Depends on:** TASK-059 (OpenRouter), TASK-064 (sleep phases)
**Spec:** `tasks/TASK-069-real-body-actions.md`
**Description:** The Shopkeeper's body currently fakes all external actions — `browse_web` resolves to reading from a pre-loaded content pool, `post_x_draft` queues for human review, and visitors can only reach her through a custom web UI. This task makes her actions real and opens her shop to the world via three channels: web window (existing), Telegram group (open shopfront), and X/Twitter (public voice). The body is an API gateway — the cortex never touches external services, body executors handle API calls, error handling, rate limits, and physical inhibitions. The cognitive pipeline is channel-agnostic.
**Build order:**
1. Body executor framework (`body/` package, registry, backward-compat)
2. Channel router (source-based reply routing)
3. Web browse executor (OpenRouter + web_search tool, Gemini Flash)
4. Telegram adapter (bot polling, event injection, messaging, images)
5. X client + executors (post, reply, media, mention fetch)
6. Cortex prompt update (tell her what's real)
7. Dashboard panel (toggle actions/channels, rate limits, kill switch)
8. Integration test (50 cycles, all channels)
**Scope (files to create):**
- `body/__init__.py`, `body/executor.py`, `body/internal.py`, `body/web.py`
- `body/x_social.py`, `body/x_client.py`, `body/telegram.py`, `body/tg_client.py`
- `body/channels.py`, `body/rate_limiter.py`
- `migrations/069_real_body_actions.sql`
- `window/src/components/dashboard/ExternalActionsPanel.tsx`
- Tests: `test_web_browse.py`, `test_x_social.py`, `test_telegram_adapter.py`, `test_tg_client.py`, `test_body_executor.py`, `test_channel_router.py`, `test_rate_limiter.py`
**Scope (files to modify):**
- `pipeline/body.py` — delegate to body/executor.py
- `pipeline/action_registry.py` — add new actions
- `pipeline/output.py` — handle results, activity broadcast
- `pipeline/sensorium.py` — handle x_mention and tg_message events
- `pipeline/cortex.py` — update action prompt section
- `heartbeat_server.py` — TG polling, mention fetch, channel router init
- `api/dashboard_routes.py` — external actions endpoints
- `db/analytics.py` — extend cost logging
- `db/memory.py` — visitor channel columns
- `llm/client.py` — web_search tool support
- `requirements.txt`
**Scope (files NOT to touch):**
- `pipeline/basal_ganglia.py`
- `pipeline/hypothalamus.py`
- `pipeline/thalamus.py`
- `sleep.py`
- `simulate.py`
**Safety / Rate limits:**
- browse_web: 20/hr, 100/day, energy 0.15, cooldown 3min
- post_x: 12/hr, 50/day, energy 0.10, cooldown 5min
- reply_x: 30/hr, 100/day, energy 0.08, cooldown 2min
- post_x_image: 6/hr, 20/day, energy 0.20, cooldown 10min
- tg_send: 60/hr, 500/day, energy 0.02, cooldown 5sec
- tg_send_image: 20/hr, 100/day, energy 0.05, cooldown 30sec
- Daily cost estimate: ~$0.75
**Definition of done:** browse_web performs real web search. X posts/replies are live. Telegram bot polls messages as visitor events, replies in group, broadcasts activity. Channel router routes replies to originating channel. All external actions logged with cost tracking. Dashboard shows action/channel status with kill switch. Rate limits enforced. 50-cycle integration test passes.

---

### TASK-070: Conscious Memory — MD File Layer
**Status:** DONE (2026-02-19)
**Priority:** High
**Complexity:** Large
**Branch:** `feat/conscious-memory`
**Depends on:** TASK-060 (self-context), TASK-064 (sleep phases), TASK-069 (real body actions write to memory)
**Spec:** `tasks/TASK-070-conscious-memory.md`
**Description:** Her memory pool contains entries like "Emotional tension — arousal 84% but valence only 22%." No human thinks this way. Split memory into two layers: conscious memory (MD files she can read/write — experiential, natural language, no numbers) and unconscious machinery (SQLite — drives, costs, parameters, cycle logs). The pipeline translates unconscious → conscious like a brain translates cortisol into "I feel stressed." She journals "something felt off tonight," not "arousal 0.84 valence 0.22."
**Architecture:**
- `memory/journal/{date}.md` — daily lived experiences
- `memory/visitors/{source_key}.md` — everything she knows about each person
- `memory/reflections/{date}-{phase}.md` — sleep reflections
- `memory/browse/{date}-{slug}.md` — web search learnings
- `memory/self/identity.md` — self-narrative (updated by sleep)
- `memory/self/traits.md`, `memory/self/drift.md` — behavioral patterns
- `memory/threads/{slug}.md` — long-running thought threads
- `memory/collection/catalog.md` — collection notes
**Key design rules:**
- Waking: read + append only (no editing past entries, no deletions)
- Sleep: read + write + annotate (can add notes, rewrite self/ files, archive old entries)
- NO raw numbers, percentages, or drive values in any MD file ever
- Translation layer converts drives → feelings before any conscious write
- Hippocampus rewritten to grep MD files instead of querying SQLite memory tables
**Migration phases:**
1. Create `memory/` directory + file writers (append-only during waking)
2. Translation layer (drives → feelings in self-context and journal writes)
3. Replace hippocampus retrieval (MD files + grep instead of SQLite)
4. Migrate sleep system (reflections, visitor annotations, identity rewrites → MD)
5. Remove deprecated SQLite memory tables (keep operational tables)
**Scope (files to create):**
- `memory/` directory tree
- `memory_writer.py` — MemoryWriter class
- `memory_reader.py` — MemoryReader class + grep_memory()
- `memory_translator.py` — numbers-to-feelings translation
- Tests: `test_memory_writer.py`, `test_memory_reader.py`, `test_memory_translator.py`, `test_grep_recall.py`
**Scope (files to modify):**
- `pipeline/hippocampus.py` — rewrite retrieval to MD files + grep
- `pipeline/output.py` — route writes to MD, translate internal_conflicts
- `prompt/self_context.py` — translate drives to felt experience
- `sleep.py` / `sleep/` phases — consolidation writes to MD
- `pipeline/hippocampus_write.py` — visitor updates → MD
- `pipeline/body.py` — journal_write appends to MD
- `seed.py` — create initial memory/ structure
**Scope (files NOT to touch):**
- `pipeline/cortex.py` (prompt assembly unchanged — receives context from hippocampus)
- `pipeline/basal_ganglia.py`
- `pipeline/hypothalamus.py`
- `db/state.py`, `db/analytics.py`, `db/events.py` (SQLite stays for operational data)
- `simulate.py`
**Definition of done:** Memory files created and populated from first cycle. Journal entries are natural language. Visitor memories in per-person MD files. NO raw numbers in any MD file. Internal conflicts translated to felt experience. Hippocampus retrieves via grep + file reads. Sleep writes reflections and annotates (never edits) existing entries. SQLite retains all operational data. 50-cycle test: no machine-readable state leaks into MD files. Files are human-readable.

---

### TASK-071: Liveness Metrics — Proving She's Alive
**Status:** IN_PROGRESS (Phase 1 done 2026-02-19: M1, M2, M7. Phase 2 done 2026-02-28: M3, M4, M5, M9 + 6-hourly collection + backfill)
**Priority:** High
**Complexity:** Large
**Branch:** `feat/liveness-metrics`
**Depends on:** TASK-069 (real body actions), TASK-070 (conscious memory)
**Spec:** `tasks/TASK-071-liveness-metrics.md`
**Description:** If we claim "first AI that's actually alive," we need numbers — not vibes, not demos. Longitudinal data that no chatbot can fake, computed automatically from existing data, visible publicly, historically continuous from her first cycle, and impossible to fake without sustained autonomous behavior over time.
**Metrics (10 total):**
1. **M1: Uptime** — cycles lived (from cycle_log)
2. **M2: Autonomous Initiative Rate** — % of self-initiated actions (target 60-80%)
3. **M3: Behavioral Entropy** — Shannon entropy of action distribution (structured rhythm, not random)
4. **M4: Knowledge Accumulation** — unique topics browsed, deep research threads
5. **M5: Visitor Memory Accuracy** — recall rate for returning visitors (target >75%)
6. **M6: Taste Consistency** — stable aesthetic preferences over time (target >0.6)
7. **M7: Emotional Range** — distinct mood states visited (out of 125 quantized bins)
8. **M8: Sleep Quality Impact** — performance correlation with sleep cycle quality
9. **M9: Unprompted Memory References** — past experiences referenced without prompting (target 2-3/day)
10. **M10: Conversation Depth Gradient** — conversations deepen with returning visitors (positive slope >60%)
**Implementation phases:**
- Phase 1 (with 069): M1, M2, M7 + historical backfill + metrics API + basic public dashboard
- Phase 2 (with 070): M3, M4, M5, M9 + trend charts
- Phase 3 (2-4 weeks post-launch): M6, M8, M10 + comparison benchmark + embeddable badge
**Scope (files to create):**
- `metrics/` package (collector.py, models.py, 10 metric modules, public.py, backfill.py)
- `migrations/071_metrics.sql`
- Tests: `test_metrics_collector.py`, `test_metrics_backfill.py`
- Optional: `public-dashboard/` (public liveness page)
**Scope (files to modify):**
- `api/dashboard_routes.py` — add /api/metrics endpoint
- `heartbeat_server.py` — schedule hourly metric collection
**Collection schedule:**
- Hourly: M1, M2, M3, M7
- Every 6 hours: M4, M5, M9
- Daily (during sleep): M6, M8, M10
**Definition of done:** All 10 metrics with working calculators. Historical backfill from existing data. Metrics API with current snapshot + 30-day trends. Public liveness dashboard (no auth). Comparison table vs ChatGPT/Character.ai/Automaton. Embeddable badge. Hourly collection without cycle performance impact.

---

### HOTFIX-001: X Mention Poller — Rate Limit Backoff
**Status:** DONE (2026-02-20)
**Priority:** Critical
**Branch:** `fix/x-poller-backoff`
**Spec:** `tasks/hotfix-001-x-poller.md`
**Description:** `XMentionPoller` polls X API every 120s. X Free tier allows 1 request per 15 minutes. First call succeeds, every subsequent call gets 429. The poller has been hammering 429 every 2 minutes for 11+ hours because `fetch_mentions()` catches 429 internally, returns `[]`, and the loop always sleeps `poll_interval` (120s) regardless of errors.
**Fix:**
1. Default `poll_interval` from 120 → 900 (15 min = X Free tier limit)
2. On 429 response: raise `RateLimitError` with Retry-After value (not silently return `[]`)
3. Polling loop: exponential backoff on RateLimitError (double retry_after, cap 1 hour)
4. Reset interval to default on successful poll
**Scope (files you may touch):**
- `body/x_social.py`
- `tests/test_x_executors.py` or `tests/test_x_poller.py` (new)
**Scope (files you may NOT touch):**
- Everything else
**Tests:**
- 429 response → RateLimitError raised with retry_after
- Poller backs off after RateLimitError (interval doubled)
- Poller resets interval after successful poll
- Backoff caps at 3600s
- Default poll_interval is 900
**Definition of done:** Default poll interval is 900s. 429 triggers exponential backoff. Backoff caps at 1 hour. Successful poll resets interval.

---

### HOTFIX-002: Valence Death Spiral — Floor Bounce + Cortex Clamp
**Status:** DONE (2026-02-20)
**Priority:** Critical
**Branch:** `fix/valence-spiral`
**Spec:** `tasks/hotfix-002-valence-spiral.md`
**Description:** Valence hit -1.0 and stayed there for 12+ hours. She became catatonic — outputting "..." every cycle, ignoring visitors, zero actions. Root cause: homeostatic spring (+0.013/cycle) is 10x too weak vs cortex mood-setting (-0.10 to -0.15/cycle). Cortex reads dark context → outputs val=-0.99 → valence stays at floor → dark memories surfaced → repeat forever.
**Fix — Four mechanisms:**
1. **Exponential spring at extremes** — past -0.5 distance, spring force gets 3-4x multiplier (rubber band, not linear)
2. **Cortex valence clamp** — cortex cannot swing valence more than ±0.10 per cycle (mood inertia)
3. **Hard floor at -0.85** — she's miserable but not catatonic, can still choose to act
4. **Action success micro-boost** — completing any action gives +0.05 valence, dialogue gives +0.10
**Scope (files you may touch):**
- Drive/valence update logic (likely `pipeline/hypothalamus.py` or `pipeline/output.py`)
- Action result processing (likely `pipeline/output.py`)
- `tests/test_valence_recovery.py` (new)
**Scope (files you may NOT touch):**
- `pipeline/cortex.py`, `body/*`, `sleep.py`, `heartbeat_server.py`, `window/*`
**Tests:**
- Exponential spring at -1.0 is 3x+ stronger than at -0.3
- Cortex clamp: proposed -1.0 from -0.5 → result >= -0.60
- Hard floor: valence never below -0.85
- Action success: +0.05 boost on completion
- 50-cycle death spiral simulation stays at floor (doesn't breach)
- Recovery with one action success shows upward trend
**Definition of done:** Valence floor at -0.85. Cortex clamped ±0.10/cycle. Exponential spring at extremes. Action success boosts valence. Death spiral broken.

---

### HOTFIX-003: Thread Dedup + Rumination Breaker
**Status:** DONE (2026-02-20)
**Priority:** Critical
**Branch:** `fix/thread-rumination`
**Spec:** `tasks/hotfix-003-rumination.md`
**Description:** She opened 6 separate "What is anti-pleasure?" threads with near-identical content. Each cycle, hippocampus surfaces the same negative thread, cortex ruminates on it, nothing breaks the loop. Two fixes: thread dedup (prevent duplicate threads) and rumination breaker (deprioritize threads after 5+ consecutive cycles in context).
**Fix 1 — Thread dedup:**
- Before creating new thread, check for existing open thread with same/similar topic
- Exact match: merge content into existing thread
- Fuzzy match (>60% word overlap): merge into existing thread
- Closed threads don't block new ones on same topic
- Sleep closes stale threads (>48h no updates)
**Fix 2 — Rumination breaker:**
- Track consecutive cycles each thread appears in context
- After 5 consecutive cycles: salience reduced by 70%+ (exponential decay: 0.3^n)
- Counter resets when thread drops out of context (can resurface later with fresh salience)
**Scope (files you may touch):**
- Thread creation logic (`pipeline/hippocampus_write.py` or `pipeline/output.py`)
- Thread context selection (`pipeline/hippocampus.py`)
- Sleep consolidation (`sleep.py` or `sleep/`)
- `db/memory.py` — add `append_to_thread()` if needed
- `tests/test_thread_dedup.py` (new)
- `tests/test_rumination_breaker.py` (new)
**Scope (files you may NOT touch):**
- `pipeline/cortex.py`, `pipeline/hypothalamus.py`, `body/*`, `heartbeat_server.py`, `window/*`
**Tests:**
- Exact duplicate topic → returns existing thread
- Fuzzy duplicate (>60% overlap) → merges
- Different topics → separate threads
- Closed thread doesn't block new one on same topic
- Thread fades after 5 consecutive cycles (salience <0.3x)
- Counter resets when thread drops out
- Stale threads closed during sleep
**Definition of done:** Cannot open duplicate threads. Rumination fades after 5 cycles. Thread counter resets on dropout. Stale threads auto-closed. "Anti-pleasure" scenario impossible.

---

### TASK-072: Research Simulation Framework
**Status:** BACKLOG
**Priority:** High
**Complexity:** Large
**Branch:** `feat/research-sim`
**Depends on:** TASK-069 (real body actions), TASK-070 (conscious memory), TASK-071 (liveness metrics)
**Spec:** `tasks/TASK-072-research-simulation.md`
**Description:** The ALIVE paper needs empirical evidence. Run controlled experiments: ALIVE vs baselines, ablation studies, and longitudinal development. Requires a simulation framework that runs the full pipeline at 100x speed with reproducible results, scenario injection, and metric collection. Reusable for validating every future architectural change before prod.
**Experiments to support:**
1. **ALIVE vs Baselines** (1000 cycles × 3 systems) — full ALIVE vs stateless chatbot vs ReAct agent, identical scenarios
2. **Ablation Study** (1000 cycles × 6 variants) — full, no_drives, no_sleep, no_conscious_memory, no_affect, no_basal_ganglia
3. **Longitudinal** (10,000 cycles) — ~2 simulated weeks, track developmental curves
4. **Stress Tests** (500 cycles × 5 scenarios) — death spiral reproduction, visitor flood, total isolation, spam attack, sleep deprivation
**Architecture:**
- `sim/runner.py` — SimulationRunner orchestrator
- `sim/clock.py` — SimulatedClock (deterministic accelerated time)
- `sim/scenario.py` — ScenarioManager (timed event injection)
- `sim/variants.py` — Architecture variants (full, ablated)
- `sim/baselines/` — Stateless chatbot + ReAct agent
- `sim/llm/` — MockCortex (free, deterministic) + CachedCortex (real LLM with response cache, ~$38 total)
- `sim/metrics/` — SimMetricsCollector, MetricsComparator (CSV/LaTeX export), FigureExporter (PDF plots)
**Subtasks (delegation order):**
- 072-A: Clock injection + InMemoryDB (prerequisite — route all `datetime.now()` through `clock.now()`)
- 072-B: Simulation runner + scenarios
- 072-C: Baselines (stateless + ReAct)
- 072-D: Ablation + pipeline hooks (add override flags to real pipeline)
- 072-E: Mock + cached LLM
- 072-F: Metrics + export (CSV, LaTeX, PDF figures)
- 072-G: CLI + integration
**LLM cost estimate:** ~$38 total (cached Haiku for all experiments, ~12,500 calls across 21,500 cycles)
**Scope (files to create):** `sim/` package (15+ files), scenarios, baselines, metrics
**Scope (files to modify):** Pipeline files for clock injection (`datetime.now()` → `clock.now()`)
**Scope (files NOT to touch):** `pipeline/cortex.py` internals, `db.py` schema
**Definition of done:** Clock injection complete, all existing tests pass. SimulationRunner completes 1000-cycle scenario. Both baselines + all 6 ablation variants complete 1000 cycles. MockCortex deterministic with seed. CachedCortex caches correctly. Metrics computed, tables exported as CSV + LaTeX, figures as PDF. CLI runs any experiment with single command. End-to-end: `--experiment baselines --llm mock --cycles 100` completes in <60s.

---

### TASK-074: Track B — 10,000 Cycle Longitudinal Run
**Status:** BACKLOG
**Priority:** High
**Branch:** `feat/research-sim`
**Depends on:** TASK-072 (research simulation framework — cache collision fix, mock expression fix)
**Description:** Run a 10,000 cycle simulation using the full ALIVE variant with real LLM (minimax/minimax-m2.5 via OpenRouter) to produce long-horizon behavioral data for the research paper (Experiment 3). This is independent of the ablation suite (Track A, 6 variants × 1000 cycles) and can run in parallel on VPS.
**Execution:**
- Environment: Production VPS (or second VPS for isolation), inside tmux/screen session
- Branch: `feat/research-sim` (or latest main if merged)
- Command:
  ```
  tmux new-session -d -s track-b
  tmux send-keys -t track-b "python -m sim.runner \
    --variant full \
    --cycles 10000 \
    --llm openrouter/minimax-m2.5 \
    --seed 42 \
    --output sim/results/longitudinal_m25_full_10k.json \
    &>> sim/results/longitudinal_m25_full_10k.log" Enter
  ```
  Adjust CLI flags to match actual runner interface.
- Monitor: `tail -f sim/results/longitudinal_m25_full_10k.log`
**Output:**
- Results JSON: `sim/results/longitudinal_m25_full_10k.json`
- Log file: `sim/results/longitudinal_m25_full_10k.log`
- Metrics to capture: all standard (initiative %, entropy, knowledge, emotional range, unprompted memories) plus temporal evolution data for Figure 4
**Context (fixes already deployed):**
- Cache collision bug fixed (`sim/llm/cached.py` — drives stripped from hash, variant in key, max reuse cap 3)
- Mock expression bug fixed (`sim/llm/mock.py` — threshold lowered, branch priority reordered, drive updates action-aware)
**Success criteria:**
- 10,000 cycles complete without crash
- Emotional range > 0 (confirms affect system active over long horizon)
- Action diversity present (browses, posts, journals, dialogue)
- Memory consolidation events occur (sleep cycles trigger consolidation)
- No cache feedback loops (browse count should not dominate >70% of actions)
**Scope (files you may touch):**
- `sim/results/` (output files only)
- `sim/runner.py` (CLI flag adjustments only if needed)
**Scope (files you may NOT touch):**
- `pipeline/*`
- `db.py`
- `heartbeat.py`
**Notes:** This is Experiment 3 from the paper spec (`briefs/TASK-072-research-simulation.md`). 10k cycles ≈ simulated weeks of character life — enough to show consolidation patterns, behavioral drift, and personality stability over time. Data feeds into longitudinal analysis for Figure 4.

---

### TASK-075: Circuit Breakers for Action Failures
**Status:** DONE (2026-02-28)
**Priority:** High
**Description:** When an external action fails (API timeout, rate limit, service down), the character retries the same action indefinitely. Observed in production: 262 browses in 500 death-spiral cycles. Circuit breakers prevent this by introducing increasing reluctance (like physical fatigue), with automatic recovery via exponential backoff cooldowns. Failures surface as character-aligned perceptions ("brain fog"), not raw errors.

**Architecture:**
- New `ActionCircuitBreaker` (dataclass `ActionHealth`) lives in `pipeline/basal_ganglia.py`
- State machine: `closed` → `open` (after N consecutive failures) → `half_open` (after cooldown) → `closed` (on success)
- Parameters: threshold=3 consecutive failures, base cooldown=5min, max=1hr, multiplier=2.0
- Error translation: raw exceptions → character-aligned perceptions (e.g. "A wave of mental fatigue washes over you.")
- Fatigue perception injected into sensorium when actions are blocked
- DB persistence: migration `029_circuit_breaker_state.sql` (production only)

**Rollout order:**
1. `ActionHealth` dataclass + state machine in `pipeline/basal_ganglia.py`
2. Failure reporting hook in `pipeline/body.py`
3. Error-to-perception translation map in `pipeline/body.py`
4. Fatigue perception injection via sensorium
5. Migration `029_circuit_breaker_state.sql`
6. Unit tests
7. Integration test with failure injection

**Scope (files you may touch):**
- `pipeline/basal_ganglia.py`
- `pipeline/body.py`
- `pipeline/sensorium.py` (perception injection only)
- `migrations/029_circuit_breaker_state.sql` (new)
- `tests/test_circuit_breaker.py` (new)

**Scope (files you may NOT touch):**
- `pipeline/cortex.py`
- `pipeline/hippocampus.py`
- `pipeline/hippocampus_write.py`
- `db.py`
- `heartbeat.py`
- `config/identity.py`

**Tests (tests/test_circuit_breaker.py):**
1. `test_opens_after_threshold` — 3 failures → state=open
2. `test_success_resets_counter` — 2 failures + 1 success → consecutive=0, state=closed
3. `test_cooldown_exponential_backoff` — verify 300s → 600s → 1200s → ... → 3600s cap
4. `test_half_open_allows_one_attempt` — after cooldown expires, one attempt permitted
5. `test_half_open_failure_reopens` — failed half-open → back to open with longer cooldown
6. `test_all_blocked_forces_idle` — all intended actions open → returns idle intention
7. `test_fatigue_perception_injected` — blocked action produces sensorium perception
8. `test_error_perception_not_raw` — body never passes raw exception strings to cortex

**Integration test:** 100-cycle sim with `read_content` failing after cycle 20. Verify: browses stop within 3 cycles, action diversity increases, browses resume after cooldown, no raw error strings in cortex prompts.

**Metrics to add to sim CSV:** `circuit_breaks`, `forced_idles`, `recovery_time_avg`, `action_diversity_post_break`

**Definition of done:** 3 consecutive browse failures → circuit opens → she idles or picks other actions → after cooldown she tries again. No raw API errors ever reach the cortex prompt. All 8 unit tests pass. Integration test passes.

**Not in scope:** Per-visitor circuit breakers, operator alerting, circuit breaker for the cortex LLM call itself.

---

### TASK-076: Cortex Prompt Optimization — Idle Latency Kill
**Status:** DONE (2026-02-21)
**Priority:** High
**Spec:** `tasks/TASK-075-prompt-optimization.md`
**Description:** Idle cycles take ~14s and consume ~2800 tokens when they should take 3-5s and ~1100 tokens. Root cause: full engage-grade system prompt + output schema + full output budget sent on every cycle regardless of type. Fix: two-tier system prompt (idle vs engage), cycle-aware output token budget, reduced user message sections on idle, temperature tuning, self-context caching.

**Projected impact (idle cycles):**
- System prompt: ~1300 → ~700 tokens (-46%)
- Output cap: 1500 → 400 tokens (-73%)
- Self-context DB calls: 5+ per cycle → 5+ per 5 min (-90%)
- Estimated latency: ~14s → ~4-6s (-60%)
- Estimated cost: ~$0.004 → ~$0.001 (-75%)
- Engage cycles: **unchanged**

**Scope (files you may touch):**
- `pipeline/cortex.py` — add `CORTEX_SYSTEM_IDLE`, route by cycle type, cycle-aware tokens + temperature
- `prompt/budget.py` — add `get_output_tokens_for_cycle()`
- `prompt/budget_config.json` — add `reserved_output_tokens_by_cycle_type`
- `prompt/self_context.py` — add caching layer + `invalidate_self_context_cache()`
- `heartbeat.py` — use cached self_context, invalidate after sleep
- `llm/client.py` — gate `json_schema` by model name (sim-only, optional)
- `llm/schema.py` — new file, JSON schema for M2.5 sim (optional)

**Scope (files you may NOT touch):**
- `db.py`
- `config/identity.py`
- `pipeline/hippocampus.py`
- `pipeline/hippocampus_write.py`
- `pipeline/validator.py`
- `pipeline/basal_ganglia.py`

**Tests:**
1. 10 idle cycles — measure latency, input tokens, output tokens, completion quality
2. 5 engage cycles — verify full schema output, `memory_updates` populated, dialogue quality unchanged
3. Transition: idle → visitor arrives → engage schema → visitor leaves → idle schema resumes
4. Edge case: visitor arrives during idle (microcycle interrupt) → full schema on next cycle
5. Sim: 100-cycle mock with M2.5 + `json_schema`, compare action diversity to baseline

**Definition of done:** Idle cycles consistently under 6s and under 1200 input tokens. Engage cycles fully unaffected. All existing tests pass.

---

### TASK-077: Sim v2 — Visitor Model & Environment Redesign
**Status:** DONE (2026-02-22)
**Priority:** High
**Spec:** `tasks/TASK-077-sim-v2-redesign.md`
**Depends on:** TASK-074 (circuit breaker), TASK-075 (prompt optimization), budget-native energy fix
**Blocks:** 10k longitudinal run (TASK-073), paper ablation tables

**Problem:** Current sim is a sensory deprivation chamber. 1000-cycle ablation shows 709/1000 idle cycles, only 3 unique visitors, action entropy 1.965 dominated by rearrange→rearrange→rearrange (153 trigrams), monologue repetition 98.6%, social hunger saturated for 203 cycles, 0 posts/journals. Metrics don't reflect ALIVE capability.

**Goal:** Redesign visitor model and scheduling for realistic, reproducible, attribution-clean benchmarks that exercise memory, social dynamics, taste, emotional range, and behavioral diversity.

**Architecture (see spec for full detail):**
- Poisson arrival process with day-part + weekday + scenario modulation
- 3-tier visitor system: Tier 1 scripted archetypes, Tier 2 LLM personas, Tier 3 returning visitors
- Visitor state machine: ENTERING → BROWSING → ENGAGING → NEGOTIATING → DECIDING → EXITING
- 5 scenario presets: `isolation`, `standard`, `social`, `stress`, `returning`
- 10 Tier 1 archetypes (Tanaka, student, whale collector, haggler, tourist, nostalgic, rival, seller, kid, online crossover)

**New metrics:**
- N1: Stimulus-Response Coupling (dialogue% rises when visitor rate increases)
- N2: Boredom Loop Resistance (streak < 10, repetition < 0.5, self-loop < 0.5)
- N3: Memory & Relationship Score (identity recall, transaction recall, preference continuity)
- N4: Budget Utilization Efficiency (meaningful actions per budget spend)

**Implementation (5 PRs):**
- PR #1: Poisson scheduler + day structure (`sim/visitors/scheduler.py`, `sim/visitors/models.py`, `sim/runner.py`, `sim/__main__.py`)
- PR #2: Tier 1 archetypes + state machine (`sim/visitors/archetypes.py`, `sim/visitors/state_machine.py`, `sim/visitors/templates/`)
- PR #3: Tier 3 returning visitors (`sim/visitors/returning.py`, `sim/metrics/memory_score.py`)
- PR #4: Tier 2 LLM visitors + `social` scenario (`sim/visitors/llm_visitor.py`, `sim/visitors/visitor_cache.py`)
- PR #5: Full metric suite + scenario comparisons (`sim/metrics/stimulus_response.py`, `sim/metrics/loop_resistance.py`, `sim/metrics/budget_efficiency.py`, `sim/reports/comparison.py`)

**Scope (files you may touch):**
- `sim/visitors/` (new package)
- `sim/metrics/` (extend)
- `sim/reports/` (new)
- `sim/runner.py`
- `sim/__main__.py`
- `tests/test_visitor_*.py` (new)

**Scope (files you may NOT touch):**
- `pipeline/*`
- `db.py`
- `heartbeat.py`
- `config/identity.py`
- `simulate.py`

**Regression gates (before any PR merge):**
- `isolation` scenario: drive dynamics unchanged from baseline (same seed → same trajectory)
- CI invariants: bigram self-loop < 0.7, max streak < 20, repetition ratio < 0.7, social saturation streak < 50, unique actions ≥ 8, total posts + journals > 0

**Cost budget:** No scenario exceeds $3/run. Full 5-scenario ablation suite ≈ $4.35/seed, $13 for 3 seeds.

**Definition of done:**
1. `standard` scenario N2 targets met (streak < 10, repetition < 0.5)
2. `returning` scenario produces measurable N3 scores
3. Cross-scenario comparison shows monotonic improvement: isolation < standard < social on M3 entropy and M7 emotional range
4. Ablation results are publishable — metrics reflect ALIVE capability, not sim artifact
5. Total ablation suite cost stays under $15 for 3-seed full comparison

---

### TASK-078: Cache-Safe Cortex Prompt Refactor
**Status:** DONE (2026-02-22)
**Priority:** High
**Branch:** `feat/task-078-cache-safe-cortex`
**Depends on:** TASK-076 (prompt optimization)
**Description:** Merge the two prompt constants (`CORTEX_SYSTEM` and `CORTEX_SYSTEM_IDLE`) into a single `CORTEX_SYSTEM_STABLE` f-string precomputed at module level. Bake in `IDENTITY_COMPACT` and `VOICE_CHECKSUM` so the system message is identical across every API call. Move all per-cycle dynamic content (mode, feelings, suppressions, etc.) to the user message. Mark the system message as cacheable via `cache_control` in `llm/client.py` for cortex calls, and add cache hit rate logging.
**Scope (files you may touch):**
- `pipeline/cortex.py`
- `llm/client.py`
- `tests/test_llm_client.py`
- `TASKS.md`
**Scope (files you may NOT touch):**
- `db.py`
- `heartbeat.py`
- `config/identity.py`
- `pipeline/basal_ganglia.py`
- `pipeline/validator.py`
**Tests:**
- Module loads: `python3 -c "import pipeline.cortex; print(len(pipeline.cortex.CORTEX_SYSTEM_STABLE))"`
- No format placeholders: `python3 -c "import re, pipeline.cortex as c; print('OK' if not re.findall(r'\{[a-z_]+\}', c.CORTEX_SYSTEM_STABLE) else 'FAIL')"`
- `python3 -m pytest tests/test_cortex_soak.py tests/test_cortex_timeout.py tests/test_llm_client.py -v --tb=short`
**Definition of done:** Single stable system prompt with no format placeholders. All dynamic content in user message. Cache control header on cortex system message. Cache hit rate logged. All tests pass.

---

### TASK-079: Deploy Scripts Set Wrong API Key
**Status:** DONE (2026-02-22)
**Priority:** High
**Description:** Runtime hard-requires `OPENROUTER_API_KEY` (heartbeat_server.py:142, terminal.py:933) but all deploy/setup scripts still set `ANTHROPIC_API_KEY`. A scripted deployment comes up with the wrong key and immediately fails startup checks. Reconcile by updating deploy scripts to set `OPENROUTER_API_KEY`, and update documentation to match.
**Affected locations:**
- `deploy/setup.sh:146,150` — prompts for and writes `ANTHROPIC_API_KEY`
- `DEPLOY-NOW.sh:98` — writes `ANTHROPIC_API_KEY`
- `README.md:20` — documents `ANTHROPIC_API_KEY` as required
- `DEPLOY_VPS.md:25` — documents `ANTHROPIC_API_KEY`
- `CLAUDE.md` env table — lists `ANTHROPIC_API_KEY`
**Scope (files you may touch):**
- `deploy/setup.sh`
- `DEPLOY-NOW.sh`
- `README.md`
- `DEPLOY_VPS.md`
- `CLAUDE.md` (env variable table only)
**Scope (files you may NOT touch):**
- `heartbeat_server.py`
- `terminal.py`
- `pipeline/*`
- `db.py`
**Tests:** After applying changes, grep entire repo for `ANTHROPIC_API_KEY` — should appear only in historical/fallback contexts, not as primary key. Grep for `OPENROUTER_API_KEY` — should appear in deploy scripts, docs, and runtime checks.
**Definition of done:** Deploy scripts set `OPENROUTER_API_KEY`. All docs reference `OPENROUTER_API_KEY` as the required key. A fresh deploy using these scripts passes the startup API key check.

---

### TASK-080: browse_web Emits content_consumed for Failed Pool Inserts
**Status:** DONE (2026-02-22)
**Priority:** Medium
**Description:** In `body/web.py`, the pool insert (`insert_pool_item`) is best-effort — failures are caught and swallowed (line 82). But the `content_consumed` event is emitted unconditionally (line 100) with the `content_id` that was never persisted. This produces dangling `content_id` references in analytics/drive updates. Compare with `body/internal.py:245-248` (`read_content`), which validates pool item existence before emitting consumption events. Fix: gate the `content_consumed` event on pool insert success.
**Scope (files you may touch):**
- `body/web.py`
- `tests/test_web_browse.py`
**Scope (files you may NOT touch):**
- `body/internal.py`
- `pipeline/*`
- `db.py`
**Tests:**
- Pool insert failure → no `content_consumed` event emitted, `db.append_event` not called
- Pool insert success → `content_consumed` event emitted as before
- MD memory write still attempted regardless of pool insert outcome
**Definition of done:** `content_consumed` event is only emitted when `insert_pool_item` succeeds. MD memory writes are unaffected. Existing success-path tests still pass.

---

### TASK-081: test_web_browse Non-Hermetic — Leaks MagicMock Files to Repo
**Status:** DONE (2026-02-22)
**Priority:** Medium
**Description:** Test fixture in `tests/test_web_browse.py` mocks `clock.now_utc` (line 19) but not `clock.now()`. Production code at `body/web.py:92` calls `clock.now().strftime(...)` for the browse filename, which falls through to the unmocked `MagicMock.now()` — producing filenames like `<MagicMock name='clock.now().strftime()' id='...'>`. The `memory_writer` path also isn't mocked, so real files are written to `data/memory/browse/`. This is visible in the repo's untracked files (170+ MagicMock-named artifacts).
**Fix:**
1. Mock `clock.now()` in the fixture to return a proper `datetime` (alongside existing `clock.now_utc` mock)
2. Mock `memory_writer.get_memory_writer` (or `writer.append_browse`) to prevent real file I/O
3. Clean up existing `data/memory/browse/<MagicMock...>` artifacts (add to `.gitignore` if `data/memory/browse/` isn't already excluded)
**Scope (files you may touch):**
- `tests/test_web_browse.py`
- `.gitignore` (add `data/memory/browse/` if not present)
**Scope (files you may NOT touch):**
- `body/web.py`
- `memory_writer.py`
- `pipeline/*`
**Tests:** Run `python3 -m pytest tests/test_web_browse.py -v` — all pass, no new files created in `data/memory/browse/`.
**Definition of done:** `clock.now()` returns a real datetime in test fixture. Memory writer is mocked. No filesystem side effects from test runs. Existing MagicMock artifacts cleaned up.

---

### TASK-082: HabitPolicy — Journaling as Homeostatic Reflex
**Status:** DONE (2026-02-22)
**Priority:** High (blocks full ablation suite)
**Spec:** `tasks/TASK-082-habit-policy.md`
**Description:** `write_journal` was selected 0 times across 1000 real-LLM cycles. Policy/utility gap — journaling has no immediate feedback and is dominated by visible actions when visitors are present. Fix at the controller layer: add `HabitPolicy` to basal ganglia that proposes `write_journal` as a high-priority candidate when drive conditions are met (expression_need > 0.6, cooldown elapsed, no recent visitor). LLM still generates content; action selection is driven by controller.
**Scope (files you may touch):**
- `pipeline/habit_policy.py` (new)
- `pipeline/basal_ganglia.py`
- `pipeline/hypothalamus.py`
- `sleep.py` or `sleep/` consolidation phase
- `db.py` (4 helper queries — at END of file only)
- `tests/test_habit_policy.py` (new)
**Scope (files you may NOT touch):**
- `pipeline/cortex.py`
- `pipeline/validator.py`
- `pipeline/hippocampus.py`
- `heartbeat.py`
- `simulate.py`
- `window/*`
**Tests:** 8 unit tests in `tests/test_habit_policy.py` — see spec.
**Definition of done:** `write_journal` appears 5–25× per 1000-cycle standard scenario. expression_need no longer pins at max. N2 loop resistance still passes. All 8 unit tests pass.

---

### TASK-083: Adversarial Returning Visitors
**Status:** DONE (2026-02-22)
**Priority:** Medium (paper defensibility, not blocking ablation)
**Spec:** `tasks/TASK-083-adversarial-visitors.md`
**Depends on:** TASK-077 (sim v2), PR #3 returning visitors
**Description:** The `returning` scenario only tests friendly recall — easy to dismiss as handcrafted. Adversarial visitors test whether memory actually works under stress. Three types: `doppelganger` (same name, different person — does she disambiguate?), `preference_drift` (returning visitor who explicitly changes taste — does she update?), `conflict` (returning visitor who disputes a prior transaction — does she handle without blindly overwriting?). Pass/fail scored per episode, aggregated for paper. Target: >70% overall pass rate.
**Scope (files you may touch):**
- `sim/visitors/archetypes.py`
- `sim/visitors/returning.py`
- `sim/visitors/templates/`
- `sim/metrics/memory_score.py`
- `sim/reports/`
- `tests/test_adversarial_visitors.py` (new)
**Scope (files you may NOT touch):**
- `pipeline/*`
- `db.py`
- `heartbeat.py`
- `simulate.py`
**Tests:** Unit tests for all 3 scoring rules in `tests/test_adversarial_visitors.py` — see spec.
**Definition of done:** 3 adversarial visitor types integrated into `returning` scenario. `AdversarialEpisode` evaluation runs per episode. `adversarial_episodes.json` emitted alongside other metric reports. >70% overall pass rate in a standard run.

---

### TASK-084: Wire adversarial visitors into simulation runner
**Status:** DONE (2026-02-23)
**Priority:** High (P1 — TASK-083 features are dead code without this)
**Depends on:** TASK-083 (adversarial visitors)
**Description:** TASK-083 added adversarial visitor types (doppelganger, preference_drift, conflict) with scoring and reporting, but they are not wired into the simulation run path. Two gaps: (1) `sim/runner.py` never calls `schedule_adversarial()` so doppelganger traffic is never injected, and (2) `SimulationRunner.export()` never calls `export_adversarial_report()` so `adversarial_episodes.json` is never produced. Wire both into the runner.
**Scope (files you may touch):**
- `sim/runner.py`
- `tests/test_runner*.py`
**Scope (files you may NOT touch):**
- `pipeline/*`
- `db.py`
- `heartbeat.py`
**Tests:** Integration test confirming adversarial arrivals appear in simulation runs and `adversarial_episodes.json` is emitted on export.
**Definition of done:** Running a `returning` scenario produces doppelganger/drift/conflict episodes in the run, and `adversarial_episodes.json` is written alongside other metric reports.

---

### TASK-085: Public Live Dashboard
**Status:** DONE (2026-02-23)
**Priority:** High
**Branch:** `feat/live-dashboard`
**Spec:** `tasks/cowork-brief-live-dashboard.md`
**Description:** Ship a public-facing live dashboard at `/live` showing the Shopkeeper's real-time cognitive state. Single `/api/live` endpoint (no auth) returns all dashboard state. Frontend polls every 30s. Design component provided in `tasks/shopkeeper-dashboard.jsx`.
**Data sources:** drives_state, engagement_state, room_state, cycle_log, events, threads, visitors, llm_costs, inhibitions, monologue from cortex output.
**Scope (files you may touch):**
- `api/dashboard_routes.py` (add `handle_live_dashboard` — public, no auth)
- `heartbeat_server.py` (add `/api/live` route)
- `window/src/app/live/page.tsx` (new)
- `window/src/components/live/ALIVEDashboard.tsx` (new — converted from JSX)
- `window/src/lib/types.ts` (add LiveDashboardData type)
**Scope (files you may NOT touch):**
- `pipeline/*`
- `db.py`
- `heartbeat.py`
- `config/identity.py`
- Existing `/dashboard` or `/` pages
**Tests:** Visit `/live` — loads with real data, drives update on poll, uptime ticks, recent actions show correct timestamps, mood bar renders for negative valence.
**Definition of done:** `/live` page loads with live data from `/api/live`. No auth required. Polls every 30s. Uptime ticks locally. All sections populated from real DB state.

---

### TASK-086: SimContentPool — Feed for Simulated Inner Life
**Status:** DONE (2026-02-23)
**Priority:** Critical (blocks meaningful isolation/standard ablation results)
**Depends on:** None (independent of TASK-079)
**Spec:** `tasks/TASK-086-sim-content-pool.md`
**Description:** In production, the Shopkeeper has an RSS content feed driving curiosity → reflection → journaling → threads. In the sim, this entire loop is severed — feed ingestion is skipped, no `content_pool` table, no notifications. Result: in isolation she has zero external stimulus, burns through budget on hollow cycles, then sleeps indefinitely. Fix: create `sim/content_pool.py` with 100 curated content items mirroring her production RSS feed, surface items as notifications matching production format, wire into `sim/runner.py`.
**Scope (files you may touch):**
- `sim/data/content_pool_data.py` (new — 100 curated content items)
- `sim/content_pool.py` (new — `SimContentPool` class)
- `sim/runner.py` (wire notifications into cycle perception, handle `read_content` consumption)
- `sim/db.py` (add `content_pool` table if needed for tracking)
**Scope (files you may NOT touch):**
- `pipeline/*`
- `db.py`
- `heartbeat.py`
- `config/identity.py`
- `simulate.py`
**Tests:**
- SimContentPool surfaces ~50 items per 100 waking cycles
- Consumed items return full summary
- Pool resets when all items consumed
- Notifications match production format
**Definition of done:** Isolation run completes 1000 cycles with <200 sleep cycles. At least 5 `read_content` actions. At least 3 journals. At least 2 new threads created from consumed content. Content pool provides meaningful external stimulus throughout simulation.

---

### TASK-088: Isolation Ablation Fixes — Frozen Drives, Speak Gate, Seen Count
**Status:** DONE (2026-02-23)
**Priority:** High (blocks paper claims)
**Spec:** `tasks/TASK-isolation-fixes.md`
**Description:** Five fixes for issues found in isolation ablation runs:
1. **Unfreeze curiosity** — curiosity was pinned to 0.5 by strong homeostatic pull (0.02 coeff). Now action-responsive: reading drops it, idle raises it. Weak pull (0.005) to 0.45.
2. **Unfreeze mood_arousal** — arousal was pinned to 0.3 by strong pull (0.05 coeff). Now action-responsive: active actions raise it, idle lowers it. Weak pull (0.01) to 0.35.
3. **Fix expression_need decay** — expression_need decay was too small (-0.05) to offset accumulation. Bumped to -0.15 for expressive actions. Reading now builds expression (+0.04).
4. **Gate speak when no visitor** — sim runner didn't filter speak/greet/farewell/show_item actions during isolation. Now converts to express_thought and suppresses dialogue.
5. **Fix seen_count telemetry** — seen_ids set was cleared on pool reset, making seen_count < consumed_count (impossible). Added monotonic _total_seen counter.
**Scope (files you may touch):**
- `sim/runner.py` (homeostatic drift + speak gate)
- `sim/llm/mock.py` (drive update computation)
- `sim/content_pool.py` (seen_count tracking)

---

### TASK-089: Extract All Constants to alive_config.yaml
**Status:** DONE (2026-02-23)
**Priority:** Critical (blocks ablation rerun and paper)
**Spec:** `tasks/TASK-config-extraction.md`
**Description:** Every tuning change currently requires a code commit. Extract all ~50 hardcoded behavioral constants (drive equilibria, routing thresholds, habit policies, gating rules, circuit breaker params, sleep params, budget caps) to a single `alive_config.yaml` file with a Python loader singleton. Enables config-only tuning, grid search / parameter sweeps, and "Table 2: Configuration Parameters" for the paper.
**Build order:**
1. Create `alive_config.yaml` (all constants) + `config.py` (loader + singleton)
2. Rewire `pipeline/hypothalamus.py` — all 7 drive constants from config
3. Rewire `pipeline/basal_ganglia.py` — action gating + circuit breaker from config
4. Rewire `pipeline/habit_policy.py` — habit thresholds from config
5. Rewire `sleep.py` — sleep constants from config
6. Rewire `pipeline/cortex.py` + `llm/client.py` — token caps + budget from config
7. Add `--config` CLI flag to `sim/__main__.py`
8. Fix `seen_count` telemetry (seen_count >= consumed_count always)
9. Create `experiments/configs/` with variant configs for sweeps
**Scope (files you may touch):**
- `alive_config.yaml` (new — all constants)
- `config.py` (new — loader + singleton)
- `pipeline/hypothalamus.py`
- `pipeline/basal_ganglia.py`
- `pipeline/habit_policy.py`
- `pipeline/cortex.py`
- `llm/client.py`
- `sleep.py`
- `sim/__main__.py`
- `sim/metrics/` (seen_count fix)
- `experiments/configs/` (new — variant configs)
**Scope (files you may NOT touch):**
- `db.py`
- `heartbeat.py`
- `config/identity.py`
- `pipeline/validator.py`
- `pipeline/hippocampus.py`
- `pipeline/hippocampus_write.py`
**Tests:**
- 100-cycle isolation run with default config: curiosity/arousal/expression oscillate, speak=0, seen>=consumed
- Diff a run between `default.yaml` and `high_curiosity.yaml` — drives should differ
- All existing tests pass unchanged
**Definition of done:** All ~50 pipeline constants in `alive_config.yaml`. Pipeline reads from config singleton. `--config` flag works for sim. Variant configs enable parameter sweeps. `seen_count >= consumed_count` always. Re-run full 3-seed isolation ablation for paper numbers.

---

### TASK-090: Meta-Controller — Metric-Driven Self-Tuning
**Status:** DONE (2026-02-23)
**Priority:** High
**Depends on:** TASK-089 (config yaml), TASK-055 (self_parameters), TASK-056 (modify_self), TASK-061 (self-model), TASK-062 (drift detection)
**Blocks:** TASK-091 (closed-loop evaluation), TASK-092 (identity evolution)
**Spec:** `tasks/TASK-090-meta-controller.md`
**Description:** Closes the loop between behavioral metrics and parameter adjustment. New sleep phase reads M1-M10 metrics over a configurable window, compares against target ranges defined in `alive_config.yaml`, and proposes bounded parameter adjustments. Implements Tier 2 of the three-tier self-regulation hierarchy (Tier 1: operator hard floor, Tier 2: metric-driven homeostasis, Tier 3: conscious modify_self). Max 2 adjustments per sleep cycle. All changes logged in `meta_experiments` table. Character-aligned events emitted for cortex awareness. Dashboard shows targets, current metrics, and recent adjustments.
**Build order:**
1. Config schema extension — `meta_controller` section in `alive_config.yaml`
2. `meta_experiments` table + CRUD in `db/meta_experiments.py`
3. Metric collection bridge (adapter for M1-M10)
4. Core algorithm in `sleep/meta_controller.py`
5. Wire as sleep Phase 4
6. Event emission → sensorium perception
7. Dashboard section
8. Tests (13 unit + 2 integration)
**Scope (files you may touch):**
- `sleep/meta_controller.py` (new)
- `db/meta_experiments.py` (new)
- `migrations/090_meta_experiments.sql` (new)
- `alive_config.yaml`
- `config.py`
- `sleep.py` or `sleep/__init__.py`
- `pipeline/sensorium.py` (perception for adjustment events only)
- `api/dashboard_routes.py`
- `window/src/components/dashboard/`
- `tests/test_meta_controller.py` (new)
- `tests/test_meta_experiments_db.py` (new)
**Scope (files you may NOT touch):**
- `pipeline/cortex.py`
- `pipeline/basal_ganglia.py`
- `pipeline/hippocampus.py`
- `heartbeat.py`
- `config/identity.py`
**Tests:** 13 unit tests (metric below/above/in target, hard floor enforcement, cooldown, priority ordering, disabled mode, experiment logging, event emission) + 2 integration tests (sleep phase runs, config actually changes).
**Definition of done:** Meta-controller runs as sleep phase. Reads metrics, compares against targets, proposes bounded adjustments. Hard floor and self_parameters bounds enforced. Changes logged. Events emitted. Dashboard shows status. 500-cycle sim with bad config → corrects within 3 sleep cycles.

---

### TASK-091: Closed-Loop Self-Evaluation
**Status:** DONE (2026-02-23)
**Priority:** High
**Depends on:** TASK-090 (meta-controller)
**Blocks:** TASK-092 (identity evolution)
**Spec:** `tasks/TASK-091-closed-loop-evaluation.md`
**Description:** TASK-090 adjusts parameters but never checks if adjustments worked. This task adds evaluation: after sufficient cycles, compare target metric before vs after. Classify outcomes (improved/degraded/neutral/side_effect). Revert degraded changes. Build confidence scores per param→metric link — high confidence means the meta-controller can act faster, low confidence means it backs off. Adaptive cooldown scales with confidence. Side effect detection catches unexpected metric coupling.
**Build order:**
1. Evaluation sub-phase in `sleep/meta_controller.py`
2. `meta_confidence` table + CRUD
3. Side effect detection
4. Adaptive cooldown
5. Revert mechanism
6. Character-aligned perceptions for outcomes
7. Dashboard experiment history
8. Tests (10 unit + 2 integration)
**Scope (files you may touch):**
- `sleep/meta_controller.py`
- `db/meta_experiments.py`
- `migrations/091_meta_confidence.sql` (new)
- `pipeline/sensorium.py` (perceptions for revert/improvement events)
- `api/dashboard_routes.py`
- `window/src/components/dashboard/`
- `tests/test_meta_evaluation.py` (new)
**Scope (files you may NOT touch):**
- `pipeline/cortex.py`
- `pipeline/basal_ganglia.py`
- `heartbeat.py`
- `config/identity.py`
**Tests:** 10 unit tests (outcome classification, revert, confidence tracking, adaptive cooldown, side effects, too-early skip) + 2 integration tests (full adjust→evaluate→keep loop, bad adjustment→evaluate→revert loop).
**Definition of done:** Experiments evaluated after sufficient cycles. Degraded/side_effect adjustments reverted. Confidence tracked. Low-confidence links deprioritized. Dashboard shows history. 1000-cycle sim demonstrates both keep and revert paths.

---

### TASK-092: Identity Evolution — Implement the Philosophical Gate
**Status:** DONE (2026-02-24)
**Priority:** Medium
**Depends on:** TASK-090 (meta-controller), TASK-091 (closed-loop evaluation)
**Spec:** `tasks/TASK-092-identity-evolution.md`
**Description:** Replaces TASK-063's `NotImplementedError` stubs with the three-tier resolution. When drift is detected (TASK-062): (1) if caused by conscious modify_self within protection window → defer; (2) if meta-controller already handling → defer; (3) if gradual baseline shift → accept as organic growth, update self-model; (4) if sudden drift with stable baseline → correct via meta-controller. Conscious overrides get 500-cycle protection window (configurable). Guard rails from TASK-063 enforced: safety traits immutable, one update per sleep, all decisions logged, operator override via dashboard.
**Scope (files you may touch):**
- `identity/evolution.py`
- `alive_config.yaml` (add `identity_evolution` section)
- `sleep/meta_controller.py` (add `request_correction()`)
- `pipeline/output.py` (tag modify_self as `source: conscious`)
- `db/meta_experiments.py`
- `api/dashboard_routes.py`
- `window/src/components/dashboard/`
- `tests/test_identity_evolution.py` (new)
**Scope (files you may NOT touch):**
- `pipeline/cortex.py`
- `pipeline/basal_ganglia.py`
- `heartbeat.py`
- `config/identity.py`
**Tests:** 7 tests — conscious override protected, protection expiry, organic growth accepted, sudden drift corrected, meta-controller pending defers, guard rails block safety traits, one update per sleep.
**Definition of done:** evolution.py stubs replaced. Three-tier logic operational. Conscious protection window works. Organic growth accepted. Sudden drift corrected. Guard rails enforced. Dashboard shows live evolution status.

---

## Completed Tasks

### TASK-054: Fix inhibition self_assessment trigger
**Status:** DONE (2026-02-18)
**Branch:** `fix/inhibition-self-assessment` (merged PR #56)
**Description:** Excluded `self_assessment`, `mood_decline`, and `repetition` from inhibition triggers; added cycle count guard. Cleared existing broken inhibitions via migration. She journals and expresses thoughts freely when alone.

### TASK-057: Enable X/Twitter social channel
**Status:** DONE (2026-02-18)
**Branch:** `feat/x-social` (merged PR #55)
**Description:** Enabled `post_x_draft` with human-review queue. She drafts → operator approves → posts to X → replies become visitor events. Dashboard shows pending drafts with approve/reject.

### TASK-058B: Broadcast WebSocket Room Backend
**Status:** DONE (2026-02-19)
**Branch:** `feat/broadcast-room`
**Description:** Backend broadcast room for the TASK-058 visitor UI. Multiple visitors connect via token auth, all see all chat messages and her replies as a shared stream. Connection registry tracks visitors, broadcasts presence on join/leave. Chat history buffer (50 msgs, cleared on sleep) served on connect. Dedup prevents double display of dialogue. Weather API endpoints added (wttr.in cached 10min).
**Scope:** `heartbeat_server.py`, `window_state.py`, `tests/test_broadcast_ws.py` (new), `tests/test_visitor_names.py` (new), `tests/test_chat_history.py` (new), `tests/test_weather_api.py` (new)

---

## How to Add a Task

Copy this template and add it above the "Completed Tasks" section:

### TASK-073: HOTFIX-004 — Telegram/X adapters don't wake heartbeat loop
**Status:** DONE
**Priority:** High
**Description:** Telegram and X mention adapters inject visitor events into the inbox but never call `schedule_microcycle()`, leaving the heartbeat loop asleep for minutes to hours. Production VPS showed 65-minute hang on 2026-02-20. See `bugs-and-fixes.md` HOTFIX-004 for full diagnosis.

Three changes:
1. `TelegramAdapter` needs a heartbeat reference; call `schedule_microcycle()` after injecting a message event.
2. `XMentionPoller` needs a heartbeat reference; call `schedule_microcycle()` once after processing a batch of mentions.
3. `heartbeat_server.py` must pass the heartbeat instance when constructing both adapters.

**Scope (files you may touch):**
- `body/telegram.py`
- `body/x_social.py`
- `heartbeat_server.py` (adapter construction only, lines ~185-210)

**Scope (files you may NOT touch):**
- `heartbeat.py` (no changes needed — `schedule_microcycle` already exists)
- `db.py`
- `pipeline/*`

**Tests:** Add or update tests verifying that `schedule_microcycle` is called when a Telegram message or X mention is processed.
**Definition of done:** After a Telegram or X message arrives, `pending_microcycle` is set and the heartbeat loop wakes immediately. No more multi-minute delays for external channel messages.
**Completed:** 2026-02-20

---

### TASK-087: Channel-aware perception — distinguish digital messages from in-shop visitors
**Status:** DONE (2026-02-23)
**Priority:** Medium
**Branch:** `feat/task-087-channel-aware-perception`
**Description:** X and Telegram messages are perceived identically to web UI visitors. The shopkeeper has no way to know whether someone is standing in her shop or texting from afar. Add channel-awareness at three layers:
1. **Sensorium**: New `digital_message` perception type for `tg_`/`x_` visitor sources. Reframe content as "A message on [platform] from [name]" instead of treating them as present in the shop.
2. **Cortex context**: Split U7/U9 into "present in shop" vs "digital messages" so the LLM has spatial awareness.
3. **Identity nudge**: One static line in CORTEX_SYSTEM_STABLE about physical space vs digital messages.
No changes to engagement FSM, ACK path, or channel routing (already automatic via `body/channels.py`).
**Completed:**
- `pipeline/sensorium.py` — `_detect_channel()`, new perception types for all 3 event types
- `pipeline/cortex.py` — identity nudge in CORTEX_SYSTEM_STABLE, U7/U9 split
- `tests/test_sensorium_channels.py` — 17 tests, all pass

---

### TASK-087b: Wire digital perception types into thalamus + heartbeat
**Status:** DONE (2026-02-23)
**Priority:** High — TASK-087 is broken in production without this
**Branch:** `feat/task-087-channel-aware-perception` (continue from TASK-087)
**Description:** TASK-087 introduced `digital_message`, `digital_connect`, `digital_disconnect` perception types but three downstream consumers only check for `visitor_*` p_types. Without these fixes, Telegram/X messages silently break in production (routed as idle, never engage).
**Three fixes:**
1. **`pipeline/thalamus.py` (critical):** `route()` lines 36-43 check `focus.p_type == 'visitor_speech'` etc. `digital_message` falls through to idle — she never engages with Telegram/X messages. Fix: add `digital_message` → engage, `digital_connect` → engage/idle (same salience threshold), `digital_disconnect` → idle.
2. **`heartbeat.py:905` (moderate):** Focus capping uses `not p.p_type.startswith('visitor_')`. Digital perceptions get salience capped to 0.3 when arbiter focus is active. Fix: also check `startswith('digital_')`.
3. **`heartbeat.py:931` (moderate):** Mode binding override uses same `startswith('visitor_')` check. Arbiter overrides engage mode for digital messages. Fix: same — also check `startswith('digital_')`.
**Scope (files you may touch):**
- `pipeline/thalamus.py`
- `heartbeat.py`
- `tests/test_thalamus.py` or new test file
**Scope (files you may NOT touch):**
- `pipeline/sensorium.py` (already done in TASK-087)
- `pipeline/cortex.py` (already done in TASK-087)
**Tests:** Verify thalamus routes `digital_message` to engage. Verify heartbeat focus capping preserves digital perception salience.
**Definition of done:** Telegram/X messages trigger engage mode. All existing tests pass. Merge both TASK-087 + TASK-087b together.

---

### TASK-096: Dashboard panels — meta-controller, experiment history, metrics
**Status:** DONE (2026-02-25)
**Priority:** Medium
**Description:** Three backend API endpoints added in TASK-071/090/091 have no corresponding frontend panels, API client functions, or TypeScript types. The data is served but invisible on the dashboard.

**Missing panels:**
1. **MetaControllerPanel** — `/api/dashboard/meta-controller` returns: `enabled`, `targets` (with current metric values + status), `recent_adjustments`, `pending_count`, `config` (evaluation_window, cooldown_cycles, max_adjustments_per_sleep). Show target status (ok/low/high), recent adjustments list, pending experiments count.
2. **ExperimentHistoryPanel** — `/api/dashboard/experiment-history` returns: `experiments` (list with outcomes) + `confidence` data. Show experiment timeline with pass/fail/pending status.
3. **MetricsPanel** — `/api/dashboard/metrics` returns: `snapshot` (current metric values) + `trends` (30-day daily for uptime, initiative_rate, emotional_range). Show current values + mini-charts or trend indicators.

**For each panel, add:**
- Component in `window/src/components/dashboard/`
- API client function in `dashboard-api.ts`
- TypeScript types in `types.ts`
- Import + render in `dashboard/page.tsx` (System section)

**Scope (files you may touch):**
- `window/src/components/dashboard/MetaControllerPanel.tsx` (new)
- `window/src/components/dashboard/ExperimentHistoryPanel.tsx` (new)
- `window/src/components/dashboard/MetricsPanel.tsx` (new)
- `window/src/lib/dashboard-api.ts`
- `window/src/lib/types.ts`
- `window/src/app/dashboard/page.tsx`
**Scope (files you may NOT touch):**
- `api/dashboard_routes.py` (endpoints already exist and work)
- `heartbeat_server.py` (routes already registered)
- `db.py`
- `pipeline/*`
**Tests:** Each panel renders without error. API client functions return correct types. Dashboard page loads with new panels visible.
**Definition of done:** All three panels visible on dashboard, showing live data from their respective endpoints.

---

### TASK-097: Dashboard cleanup — vestigial energy_cost + API client consistency
**Status:** DONE (2026-02-25)
**Priority:** Low
**Description:** Two cleanup issues found in dashboard audit:

1. **Vestigial `energy_cost` display** — `BodyPanel.tsx` and `ExternalActionsPanel.tsx` display `energy_cost` per action/rate-limit. These are static hardcoded values from `body/rate_limiter.py` config, never dynamically meaningful. Remove the display from both panels. Keep the TypeScript type fields (backend still serves them) but stop rendering them.
2. **API client inconsistency** — `EvolutionPanel.tsx` calls `dashboardFetch('/api/dashboard/identity-evolution')` directly instead of using a typed `dashboardApi.getIdentityEvolution()` function. Every other panel uses the `dashboardApi` object. Add the missing function and update the panel to use it.
3. **Stale ARCHITECTURE.md refs** — `ARCHITECTURE.md` still references `SceneCanvas.tsx`, `useSceneTransition.ts`, `scene-constants.ts` (deleted). Remove stale entries.

**Scope (files you may touch):**
- `window/src/components/dashboard/BodyPanel.tsx`
- `window/src/components/dashboard/ExternalActionsPanel.tsx`
- `window/src/components/dashboard/EvolutionPanel.tsx`
- `window/src/lib/dashboard-api.ts`
- `ARCHITECTURE.md`
**Scope (files you may NOT touch):**
- `window/src/lib/types.ts` (keep type fields, just stop displaying)
- `api/dashboard_routes.py`
- `body/rate_limiter.py`
- `db.py`
- `pipeline/*`
**Tests:** All existing dashboard tests pass. Panels render without error. No `energy_cost` text visible in BodyPanel or ExternalActionsPanel.
**Definition of done:** energy_cost removed from panel display. EvolutionPanel uses dashboardApi. ARCHITECTURE.md has no references to deleted files.

---

### TASK-098: Lounge conversation persistence
**Status:** DONE (2026-02-26)
**Priority:** Medium
**Description:** Lounge chat messages are stored in the agent's `conversation_log` SQLite table but lost on frontend reload. Two root causes:

1. **Ephemeral visitor ID** — `visitorId = lounge-${Date.now()}` generates a new ID on every page load, so the backend treats each visit as a new person. Fix: store a stable visitor ID in localStorage, scoped per agent.
2. **No history loading** — frontend initializes with `useState([])` and never fetches past messages. Fix: add a `/api/conversation-history` endpoint on the agent container, proxy it through the lounge API, and load previous messages on mount.

**Scope (files you may touch):**
- `lounge/src/app/agent/[id]/lounge/page.tsx` (stable visitor ID + load history on mount)
- `lounge/src/app/api/agents/[id]/history/route.ts` (new — proxy route for conversation history)
- `lounge/src/lib/agent-client.ts` (add `getConversationHistory()` method)
- `api/public_routes.py` (add `/api/conversation-history` endpoint returning messages for a visitor_id)
**Scope (files you may NOT touch):**
- `db.py` (use existing `get_recent_conversation()` in `db/memory.py`)
- `pipeline/*`
- `heartbeat.py`
- `config/identity.py`
**Tests:** Conversation history loads on page refresh. Same visitor ID used across reloads for the same agent. New messages appear after old ones. Empty state still works for first visit.
**Definition of done:** Manager can chat with an agent, refresh the page, and see the full conversation history. Visitor ID is stable per agent per browser.

---

### TASK-099: YouTube/video-aware enrichment pipeline
**Status:** BACKLOG
**Priority:** Medium
**Description:** The feed ingester enriches all URLs identically via markdown.new, which works but returns page chrome (comments, sidebar, recommendations) for YouTube videos instead of the actual spoken content. Videos are the weakest content type — she "reads" YouTube page HTML rather than the transcript.

**Goal:** When a content pool URL is a YouTube/video URL, extract the actual transcript + metadata and produce richer `enriched_text` for Cortex consumption. This makes `read_content` on video items dramatically better — she gets what was *said*, not what was *around* the video player.

**Implementation steps:**

1. **Add `youtube-transcript-api` dependency** to `requirements.txt` (optional section). Lightweight, no transitive deps. Used only in `pipeline/enrich.py`.

2. **Add Jina Reader as a fallback enrichment source** in `pipeline/enrich.py`:
   - New function `fetch_via_jina(url: str) -> str` — HTTP GET to `https://r.jina.ai/{url}`, same pattern as `fetch_via_markdown_new`. Returns markdown string.
   - Update `fetch_readable_text()` fallback chain: markdown.new → Jina → raw HTML.
   - This benefits ALL content types (articles too), not just video.

3. **Add YouTube transcript extraction** in `pipeline/enrich.py`:
   - New function `fetch_youtube_transcript(url: str) -> str` — extracts video ID from URL, calls `youtube_transcript_api` to get transcript, formats as markdown with timestamps.
   - New function `fetch_youtube_metadata(url: str) -> dict` — extracts title, channel, description from page (reuse existing `fetch_url_metadata` or Jina).
   - New composite function `enrich_youtube_url(url: str) -> str` — combines transcript + metadata into a single markdown document:
     ```
     # Video: {title}
     **Channel:** {channel}
     **Description:** {description}

     ## Transcript
     [00:00] First line of speech...
     [01:23] Next segment...
     ```

4. **Add URL routing in `feed_ingester.py`**:
   - In `enrich_pool_item()`, before calling `fetch_via_markdown_new`:
     - Check if URL matches `youtube.com/watch` or `youtu.be/`
     - If yes → call `enrich_youtube_url()` instead
     - `detect_content_type()` will naturally return `'video'` from the transcript markers
   - Non-YouTube URLs → existing flow unchanged

5. **Update `detect_content_type()`** — no changes needed if transcript format includes timestamp lines and "Transcript" header (existing heuristics already catch these). Verify in tests.

6. **Graceful degradation**: if `youtube-transcript-api` is not installed or transcript fetch fails (private video, no captions), fall back to existing markdown.new/Jina flow. Never crash.

**Scope (files you may touch):**
- `pipeline/enrich.py` (new functions: `fetch_via_jina`, `fetch_youtube_transcript`, `enrich_youtube_url`)
- `feed_ingester.py` (YouTube URL routing in `enrich_pool_item`)
- `requirements.txt` (add `youtube-transcript-api`)
- `tests/test_enrich.py` (new or extended — test transcript formatting, Jina fallback, URL detection, graceful degradation)
- `tests/test_feed_enrichment.py` (add YouTube enrichment test)

**Scope (files you may NOT touch):**
- `pipeline/cortex.py` (already handles `enriched_text` and `readable_text` generically — no changes needed)
- `body/internal.py` (read_content executor already uses `enriched_text` from pool — no changes needed)
- `pipeline/hypothalamus.py`
- `heartbeat.py`
- `db.py`
- `config/identity.py`

**Risks / gotchas:**
- `youtube-transcript-api` can fail on private videos, age-restricted content, or videos with no captions. Must degrade gracefully → fall back to page markdown.
- Jina Reader has rate limits on free tier. Use same rate-limiting pattern as markdown.new (dedup by URL via `get_enriched_text_for_url`).
- Transcript text can be very long (1hr video = ~10k words). Truncate to `max_chars` (4000) same as existing `fetch_readable_text`.
- Some YouTube videos have auto-generated captions only (lower quality). Still better than page HTML.
- Don't add Jina API keys — free tier via plain HTTP GET is sufficient.

**Tests:**
- Unit: `fetch_youtube_transcript` returns formatted markdown with timestamps for a known video ID (mock the API)
- Unit: `fetch_via_jina` returns markdown string (mock HTTP)
- Unit: `enrich_youtube_url` combines transcript + metadata correctly
- Unit: URL routing in `enrich_pool_item` dispatches YouTube URLs to new path
- Unit: `detect_content_type` returns `'video'` for transcript-formatted markdown
- Unit: Graceful degradation when `youtube-transcript-api` import fails
- Unit: Graceful degradation when transcript fetch raises (private video)
- Integration: existing `test_feed_enrichment.py` still passes (non-YouTube URLs unchanged)

**Definition of done:** YouTube URLs in the content pool get transcript-based `enriched_text` instead of page-scrape HTML. `detect_content_type` correctly labels them as `'video'`. Non-YouTube enrichment is unchanged. All existing tests pass. Jina Reader available as universal fallback for all URL types.

---

### TASK-093: Taste Formation Experiment — MVP Core Loop
**Status:** DONE (2026-02-28)
**Priority:** Medium
**Description:** Build the minimum viable taste experiment: listings presented → evaluated with structured output → decision (accept/reject/watch) → market outcome. Run 200 cycles as fail-fast validation. Sim-only code — does NOT touch production.
**Spec:** `tasks/TASK-093-cowork-brief.md`
**Scope (files you may touch):**
- `sim/` (new experiment files)
- `tests/` (experiment tests)
**Scope (files you may NOT touch):**
- `pipeline/*` (production cognitive pipeline)
- `heartbeat.py`
- `db.py`
- `config/identity.py`
**Tests:** Experiment runs 200 cycles without crash. Evaluation output is structured JSON. Accept/reject decisions logged.
**Definition of done:** Core loop runs end-to-end in simulation. Taste evaluations produce discriminative scores. 200-cycle run completes with logged results.

---

### TASK-094: Dead Code / Dead Field Cleanup
**Status:** DONE (2026-02-28)
**Priority:** Low
**Description:** Remove ~3,600 lines of dead code, unused types, and write-only fields across Python backend and TypeScript frontend. Zero behavioral change. Full test suite must pass before and after every wave.
**Spec:** `tasks/TASK-094-cleanup-brief.md`
**Scope (files you may touch):**
- Multiple files across codebase (see spec for wave-by-wave breakdown)
**Scope (files you may NOT touch):**
- `config/identity.py`
- `db.py` (structural changes only — dead column removal needs migration)
**Tests:** Full test suite before and after each wave. Zero new failures.
**Definition of done:** All identified dead code removed. All tests pass. No behavioral changes.

---

### TASK-095: Private Lounge — Multi-Agent Deployment Platform
**Status:** DONE (2026-02-28)
**Priority:** High
**Description:** Shipped `alive.kaikk.jp` — hosted platform where agent managers create, configure, and deploy ALIVE agents. Each agent is an independent Docker container with isolated DB, identity config, and behavior config. Includes Manager Portal, Agent Runtime (Docker), and Public Agent API.
**Spec:** `tasks/TASK-095-private-lounge.md`

---

### TASK-100: Idle Arc — Natural Response to Low Stimulus
**Status:** DONE (2026-02-28)
**Priority:** Medium
**Description:** Extended idle periods produce a flat loop. Implement a three-phase idle arc: DEEPEN (0-20 idle cycles, varied perceptions with thread depth), WANDER (21-40, topic shifts via curiosity-driven novelty injection), STILL (41+, cycle interval stretches, monologue thins to fragments/silence). Any external event resets to normal. Reuses existing `_consecutive_idle` counter.
**Spec:** `tasks/TASK-099-idle-arc.md` (numbered 099 in spec, 100 here — 099 taken by YouTube enrichment)
**Scope (files you may touch):**
- `pipeline/thalamus.py` (perception ring buffer, idle-streak-aware selection)
- `pipeline/cortex.py` (thread depth injection in idle prompt)
- `pipeline/arbiter.py` (wander channel insertion)
- `heartbeat.py` (variable cycle interval via multiplier)
- `models/state.py` (idle_streak field if not already present)
**Scope (files you may NOT touch):**
- `sleep/*`
- `body/*`
- `config/*`
- `db.py` / `migrations/`
- `lounge/`
**Tests:** Leave agent idle 2hr — verify phase transitions, cycle slowdown, monologue thinning. Send message at 90min — verify wake within one interval. Visitor conversations unaffected.
**Definition of done:** Three-phase idle arc visible in logs. Cycle interval stretches in STILL. Monologue thins. Any stimulus resets to normal. No regression on visitor engagement.

---

### TASK-101: Repo Boundary — Decouple Platform from Shopkeeper Instance
**Status:** DONE (2026-02-28)
**Priority:** High
**Description:** Move all Shopkeeper-specific files into `demo/`. Rename platform code directory to `engine/`. Establish hard import boundary: `engine/` never imports from `demo/`, `demo/` can import from `engine/`, `lounge/` talks to `engine/` via API only. Fixes the context window problem — Claude Code sees shop references everywhere and assumes the entire system is a shopkeeper app.
**Spec:** `tasks/TASK-101-repo-boundary.md`
**Scope (files you may touch):**
- All top-level Python modules → `engine/`
- `config/default_identity.yaml` → `demo/config/`
- `window/` → `demo/window/`
- `deploy/Dockerfile.agent` (path updates)
- `tests/conftest.py` (PYTHONPATH)
- New: `BOUNDARY.md`, `demo/README.md`
**Scope (files you may NOT touch):**
- `lounge/` (already correct)
- `migrations/` (shared schema)
**Tests:** All tests pass with `PYTHONPATH=engine`. Engine starts. Lounge builds. No cross-boundary imports (`grep -r "from demo" engine/` returns nothing).
**Definition of done:** `engine/` + `demo/` + `lounge/` directory structure. All tests pass. No cross-boundary imports. Deployment works.

---

### TASK-102: MCP Frontend — Lounge UI for MCP Server Management
**Status:** DONE (2026-02-28)
**Priority:** Medium
**Description:** Two parts: (1) React components in the Lounge for MCP server management — connect server, list servers, toggle server/tools, delete, usage stats. (2) Schema enum injection fix in cortex.py — MCP tools appear in prompt text but NOT in the JSON schema `enum` array, so the LLM can't actually choose them as structured output.
**Spec:** `tasks/TASK-102-mcp-frontend.md`
**Scope (files you may touch):**
- `lounge/src/components/mcp/McpServersPanel.tsx` (new)
- `lounge/src/components/mcp/McpServerCard.tsx` (new)
- `lounge/src/components/mcp/McpConnectDialog.tsx` (new)
- `lounge/src/components/mcp/McpEmptyState.tsx` (new)
- Agent management page (add MCP tab/section)
- `pipeline/cortex.py` (schema enum fix — replace hardcoded enum with `_build_action_enum()`)
**Scope (files you may NOT touch):**
- `body/mcp_*.py` (backend done)
- `db/mcp.py` (DB layer done)
- `api/dashboard_routes.py` (endpoints done)
- Proxy route files (already exist)
**Tests:** Connect server → tools appear. Toggle tool → disabled. Delete → confirmed + removed. Bad URL → error. Schema enum includes MCP actions. Existing capabilities unaffected.
**Definition of done:** Managers can connect/manage MCP servers via Lounge UI. LLM can actually choose MCP actions via corrected schema enum. All existing tests pass.

---

### TASK-103: Pod Runtime — Programmatic Agent Lifecycle
**Status:** DONE (2026-02-28)
**Priority:** Medium
**Depends on:** TASK-101 (repo boundary), TASK-102 (MCP frontend)
**Description:** Replace shell-script-based agent management with a Pod Supervisor — a long-running process that manages agent containers via API. Includes Pod registry (platform DB), health monitoring with auto-restart, resource limits (CPU/memory caps), auto nginx routing, and Lounge integration.
**Spec:** `tasks/TASK-103-pod-runtime.md`
**Scope (files you may touch):**
- `supervisor/supervisor.py` (new)
- `supervisor/registry.py` (new)
- `supervisor/docker_manager.py` (new)
- `supervisor/health_monitor.py` (new)
- `supervisor/nginx_manager.py` (new)
- `supervisor/api.py` (new)
- `migrations/platform_001_pods.sql` (new)
**Scope (files you may NOT touch):**
- `pipeline/*`
- `heartbeat.py`
- `config/identity.py`
**Tests:** Create Pod via API → container starts. Stop Pod → container stops. Health check detects dead Pod. Nginx routes updated on start/stop. Shell scripts still work as fallback.
**Definition of done:** Pod Supervisor manages agent lifecycle via API. Health monitoring with auto-restart. Lounge uses supervisor API instead of shell scripts. Shopkeeper migrated to Pod #1.

---

### TASK-104: Manager Channel — Separate from Visitor Engagement
**Status:** DONE (2026-03-01)
**Priority:** P1
**Branch:** `fix/manager-channel`
**Description:** Lounge "private chat" sends manager messages through the visitor engagement system. The agent treats the manager as a visitor — creates engagement, expects WebSocket presence, ghost detection clears it. Manager messages need a separate perception channel: new `/api/manager-message` endpoint writes `manager_message` event type, sensorium perceives as manager input (high salience, `channel="manager"`), cortex responds via normal cycle, response retrievable via `/api/manager-response/{message_id}`. No engagement, no visitor record, no ghost detection.
**Spec:** `tasks/TASK-104-manager-channel.md`
**Scope (files you may touch):**
- `engine/heartbeat_server.py` (new endpoints: POST `/api/manager-message`, GET `/api/manager-response/{id}`)
- `engine/pipeline/sensorium.py` (handle `manager_message` event type)
- `engine/prompt_assembler.py` (format manager messages with `[Manager note]:` prefix)
- `engine/pipeline/body.py` or `engine/pipeline/output.py` (write manager response to retrievable location)
- `lounge/src/components/` (update chat to call new endpoint, poll for response)
**Scope (files you may NOT touch):**
- `engine/pipeline/cortex.py`
- `engine/heartbeat.py`
- Visitor engagement system
- Ghost detection
**Tests:** Send via Lounge → no engagement created. Response retrievable via API. Ghost detection log clean. Window visitor chat still works normally.
**Definition of done:** Manager messages bypass engagement system entirely. Lounge chat uses `/api/manager-message`. Agent responds with appropriate tone (not "welcome to the shop").

---

### TASK-105: Drive-Based Regulation — Remove Hard Caps + Social Sensitivity Trait
**Status:** READY
**Priority:** P2
**Branch:** `feature/drive-regulation`
**Depends on:** P1-6 energy feeling fix (must be live so budget-as-tiredness works)
**Description:** Two overlapping rate-limiting systems fight: hard caps (journal 3/day, content reads, thread creation) and the drive system (expression_need, curiosity). Both active — drives say "journal" but cap says "hit 3 today." Remove per-action caps (keep X posting governor + real-dollar budget), let drives be the sole behavioral regulator. Also adds `social_sensitivity` personality trait (0.0–1.0) to scale social_hunger drift/relief with diminishing returns per session. Three parts: (A) remove caps, (B) add social sensitivity, (C) verify drive relief signals are wired before removing caps.
**Spec:** `tasks/TASK-105-drive-regulation.md`
**Scope (files you may touch):**
- `engine/pipeline/hypothalamus.py` (social_sensitivity scaling, SessionTracker)
- `engine/pipeline/body.py` (remove journal/content/thread caps)
- `engine/pipeline/action_registry.py` (remove cap checks)
- `engine/drives_to_feeling.py` or equivalent (personality-aware thresholds)
- `engine/config/identity.py` or identity loader (parse social_sensitivity)
- Identity YAML schema (add `personality.social_sensitivity` field)
**Scope (files you may NOT touch):**
- `engine/pipeline/cortex.py`
- `engine/db/`
- X posting governor (keep as-is)
**Tests:** Agent with no caps journals 6-12 on day 1, tapers naturally. Introvert (0.2) shows "enough" after 3-4 messages, extrovert (0.8) after 8-9. Session decay resets after 10-min gap. Budget-as-cap: $1 budget → agent slows before 20 journals.
**Definition of done:** Per-action caps removed (except X posting). Drive relief verified for all actions. social_sensitivity trait parsed and used. Existing agents default to 0.5 (neutral, identical behavior).

---

### TASK-106: Remove rest_need Drive — Dollar Budget Is Energy
**Status:** DONE (2026-03-01)
**Priority:** High
**Description:** `rest_need` is a fake fatigue counter with no real-world backing. It ticks up every cycle (even idle), traps agents in rest loops, and blocks content engagement. Meanwhile `energy` already mirrors the real constraint: `drives.energy = budget_remaining / daily_budget`. Dollar budget IS energy — there's no second fatigue layer needed.

**What to remove:**
1. Stop updating `rest_need` in hypothalamus (time decay, visitor cost, homeostatic pull, event responses)
2. Remove rest routing from thalamus (`rest_need > threshold → rest` mode)
3. Arbiter P1 rest guard: keep `energy < 0.2` only, drop `rest_need > 0.8`
4. Remove rest_need adjustments from output.py (quiet cycle relief, end_engagement relief)
5. Remove rest_need from basal_ganglia open_shop gate (use energy instead)
6. Remove rest_need from self_context.py display
7. Remove rest_need from hypothalamus expression_relief dict (journal, post_x)
8. Remove rest_need from sleep/wake morning reset
9. Zero `rest_need` in DrivesState default (keep field for DB compat, just stop using it)
10. Clean up memory_translator.py, whisper.py, meta_review.py references

**Also fix (discovered during investigation):**
- `db/content.py:get_unseen_news()` filters `source_type = 'rss_headline'` — excludes manager drops (`source_type = 'manager_drop'`), URL items, text items. Arbiter P3/P6 never sees non-RSS content. Widen filter to include all unseen pool items regardless of source_type.

**Scope (files you may touch):**
- `engine/pipeline/hypothalamus.py` (remove rest_need updates)
- `engine/pipeline/thalamus.py` (remove rest routing)
- `engine/pipeline/arbiter.py` (simplify rest guard)
- `engine/pipeline/output.py` (remove rest_need adjustments)
- `engine/pipeline/basal_ganglia.py` (open_shop gate → use energy)
- `engine/pipeline/sensorium.py` (notification salience — use max of item salience_base)
- `engine/prompt/self_context.py` (remove rest_need display)
- `engine/models/state.py` (zero default, keep field)
- `engine/db/content.py` (fix get_unseen_news filter)
- `engine/sleep/wake.py` (remove rest_need morning set)
- `engine/sleep/whisper.py` (remove rest_need parameter tuning)
- `engine/sleep/meta_review.py` (remove rest_need from review categories)
- `engine/memory_translator.py` (remove rest_need translation)
- `engine/pipeline/validator.py` (remove rest_need from close_shop gate)
- `tests/test_hypothalamus.py`
- `tests/test_thalamus.py`
- `tests/test_arbiter.py`
- `tests/test_habit_policy.py`
- `tests/test_output.py`
**Scope (files you may NOT touch):**
- `engine/pipeline/cortex.py`
- `engine/db/connection.py` (keep DB column for compat)
- `engine/db/state.py` (keep field read/write for compat)
**Tests:** Agent with rest_need=0.0 never enters rest mode unless energy < 0.2 (budget exhausted). Manager-dropped content (source_type='manager_drop') appears in arbiter P3 news check. All existing tests pass or are updated to reflect removal.
**Definition of done:** rest_need is inert — always 0.0, never read for routing/gating decisions. Dollar budget (energy) is the sole compute-availability signal. get_unseen_news returns all source types. Existing agents behave identically except they no longer get stuck in rest loops.

---

```markdown
### TASK-107: Lounge — Dynamic Actions Visibility
**Status:** BACKLOG
**Priority:** Medium
**Description:** The Lounge dashboard has zero visibility into agents' dynamic actions. The ActionsPanel exists in `demo/window/` (Shopkeeper's dashboard) but is completely absent from the Lounge. Managers cannot see what actions their agents are organically inventing, how many times they've attempted them, or resolve pending actions (alias, body_state, reject).

This matters because dynamic actions are the primary signal of agent-initiated growth — Alice is trying `seek_connection`, `ponder_self`, `ponder_name` and the manager can't see any of it.

**Requirements:**
1. Add a Dynamic Actions section to the Lounge agent detail view
2. Show organic actions grouped by status (pending, promoted, alias, body_state, rejected)
3. Show attempt counts and last-seen timestamps
4. Allow manager to resolve pending actions (alias to existing action, map to body_state, reject)
5. Filter out noise — don't show actions with attempt_count < 2 unless explicitly expanded

**Scope (files you may touch):**
- `lounge/src/components/` (new or existing agent detail components)
- `lounge/src/app/` (agent detail page)
- `engine/api/dashboard_routes.py` (if Lounge proxies through engine API)
- `lounge/src/lib/` (API client, types)
**Scope (files you may NOT touch):**
- `engine/pipeline/*` (no pipeline changes)
- `engine/db/*` (CRUD already exists in `db/actions.py`)
- `demo/window/` (Shopkeeper's dashboard is separate)
**Tests:** Verify API returns correct data per agent. Verify resolve actions persist.
**Definition of done:** Manager can see Alice's `seek_connection:7`, `ponder_self:5` etc. in the Lounge and resolve them.

---

### TASK-108: Lounge — Full Memory View
**Status:** READY
**Priority:** Medium
**Description:** The Lounge Seed tab only surfaces `manager_memories` (backstory + organic). The Shopkeeper's real cognitive memory — journals, threads, totems, day memory pool, collection — lives in the DB but has no Lounge panel. Add a comprehensive memory view.

**What already exists (backend → Lounge wiring needed):**

| Data | Backend endpoint | DB function | Lounge UI |
|------|-----------------|-------------|-----------|
| Threads | `GET /api/dashboard/threads` | `db.content.get_open_threads()` | Missing |
| Day memory pool | `GET /api/dashboard/pool` | `db.memory.get_day_memory_dashboard()` | Missing |
| Collection | `GET /api/dashboard/collection` | `db.content.get_collection_items()` | Missing |

**What needs new backend endpoints:**

| Data | DB function (exists) | New endpoint needed |
|------|---------------------|-------------------|
| Totems | `db.memory.get_all_totems(limit=100)` | `GET /api/dashboard/totems` |
| Journal | `db.memory.get_all_journal()` | `GET /api/dashboard/journal` |
| Daily summaries | `db.get_daily_summaries()` | `GET /api/dashboard/daily-summaries` |

**Implementation:**

1. Add 3 new dashboard endpoints in `engine/api/dashboard_routes.py`:
   - `GET /api/dashboard/totems` → calls `db.get_all_totems()`
   - `GET /api/dashboard/journal` → calls `db.get_all_journal()`
   - `GET /api/dashboard/daily-summaries` → calls existing daily summary query
2. Register routes in `engine/heartbeat_server.py` HTTP handler
3. Add Lounge proxy routes in `lounge/src/app/api/agents/[id]/`:
   - `threads/route.ts`, `pool/route.ts`, `collection/route.ts`
   - `totems/route.ts`, `journal/route.ts`, `summaries/route.ts`
4. Redesign SeedTab into a multi-section memory view with sub-tabs:
   - **Seeds** (existing backstory) — keep as-is
   - **Threads** — open agenda items (title, status, priority, touch count)
   - **Journal** — sleep reflections (date, mood, content)
   - **Totems** — weighted entities (entity, weight, category, context)
   - **Moments** — day memory pool (salience, type, summary)
   - **Collection** — items (title, type, location, feeling)
5. Each sub-tab: simple list view, no editing (read-only except Seeds)

**Scope (files you may touch):**
- `engine/api/dashboard_routes.py` (add 3 endpoint handlers)
- `engine/heartbeat_server.py` (register 3 new routes)
- `lounge/src/components/SeedTab.tsx` (redesign into memory view)
- `lounge/src/components/MemoryTimeline.tsx` (refactor)
- `lounge/src/components/MemoryPanel.tsx` (update)
- `lounge/src/app/api/agents/[id]/threads/route.ts` (new proxy)
- `lounge/src/app/api/agents/[id]/pool/route.ts` (new proxy)
- `lounge/src/app/api/agents/[id]/collection/route.ts` (new proxy)
- `lounge/src/app/api/agents/[id]/totems/route.ts` (new proxy)
- `lounge/src/app/api/agents/[id]/journal/route.ts` (new proxy)
- `lounge/src/app/api/agents/[id]/summaries/route.ts` (new proxy)
- New components as needed in `lounge/src/components/`
**Scope (files you may NOT touch):**
- `engine/db/` (all DB functions already exist)
- `engine/pipeline/` (no pipeline changes)
- `engine/config/identity.py`
**Tests:** Verify all 6 dashboard endpoints return valid JSON. Verify Lounge renders each sub-tab with data from the prod snapshot (3892 events, 42 journal entries, 39 threads, 3 totems, 30 day memories).
**Definition of done:** All memory categories visible in the Lounge Seed tab. Manager can see the Shopkeeper's full cognitive memory at a glance.

---

### TASK-109: Lounge — Agent Credentials Manager UI
**Status:** BACKLOG
**Priority:** Medium
**Description:** Add a credentials management panel to the Lounge agent settings page. Currently only `openrouter_key` is stored in the lounge DB per agent. All other service credentials (X/Twitter, Telegram, fal.ai, OpenAI, etc.) must be configured manually via environment variables on the VPS. This task adds a UI for managers to view, set, and rotate per-agent credentials, and syncs them to the agent container environment.

**Requirements:**
1. New "Credentials" tab/section in the agent detail page (alongside existing Identity, Config, Feed, MCP tabs)
2. Key-value credential store in lounge DB — new `agent_credentials` table (`agent_id`, `service`, `key_name`, `encrypted_value`, `created_at`, `updated_at`)
3. Predefined credential templates for known services:
   - X/Twitter: `X_API_KEY`, `X_API_SECRET`, `X_ACCESS_TOKEN`, `X_ACCESS_SECRET`
   - OpenAI: `OPENAI_API_KEY`
   - fal.ai: `FAL_KEY`
   - Custom: arbitrary key-value pairs
4. Values masked in UI (show only last 4 chars), full value shown on click/copy
5. API endpoints: `GET/PUT/DELETE /api/agents/:id/credentials`
6. On save, write credentials to `{AGENT_CONFIG_DIR}/credentials.json` (already bind-mounted into the container). No container restart required.
7. Engine-side: add a credential loader that reads `/agent-config/credentials.json` and injects values into `os.environ` on startup + watches for file changes at runtime (or re-reads on each access with mtime caching, like `ApiKeyManager` does for `api_keys.json`)
8. Update `create_agent.sh` to load credentials from config dir on startup if the file exists
9. Credential validation: optional "test connection" button per service (e.g., verify X creds with a whoami call)

**Credential sync flow:**
- Manager saves creds in Lounge UI → lounge writes `credentials.json` to agent config dir → engine detects file change → loads new values into `os.environ` → next X/service call uses new creds
- No container restart needed. Hot-reload.

**Security considerations:**
- Encrypt values at rest in lounge DB (AES-256 or similar, key from env var `LOUNGE_ENCRYPTION_KEY`)
- `credentials.json` on disk is plaintext (container filesystem, not exposed) — acceptable for v1, encrypt later if needed
- Never log credential values
- Never return full values in API responses (only masked)
- Rate-limit credential reads

**Scope (files you may touch):**
- `lounge/src/lib/manager-db.ts` (new table + CRUD)
- `lounge/src/lib/types.ts` (credential types)
- `lounge/src/app/api/agents/[id]/credentials/route.ts` (new API route)
- `lounge/src/components/AgentCredentials.tsx` (new component)
- `lounge/src/app/agents/[id]/page.tsx` (add credentials tab)
- `lounge/src/lib/docker-client.ts` (write credentials.json to agent config dir)
- `scripts/create_agent.sh` (load credentials.json on container start)
- `engine/config/credentials.py` (new file — credential loader, file watcher, env injection)
- `engine/heartbeat_server.py` (init credential loader on startup)
**Scope (files you may NOT touch):**
- `engine/body/x_client.py` (already reads from `os.environ` — no changes needed)
- `lounge/data/` (DB file, never commit)
**Tests:** Verify CRUD operations, masked display, hot-reload of credentials.json, env injection.
**Definition of done:** Manager can add/view/edit/delete credentials per agent from the Lounge UI. Credentials are encrypted at rest in lounge DB. Saving credentials writes to agent config dir. Engine hot-reloads credentials without container restart. New agents pick up credentials on first start.

---

### TASK-110: Deploy Ergonomics — Preflight Startup Validation
**Status:** READY
**Priority:** High
**Proposal:** `tasks/PROPOSAL-alive-infra-roadmap.md` Phase 1A
**Description:** Create `engine/preflight.py` (~150 lines) that runs synchronously before `db.init_db()` in `heartbeat_server.py:start()`. Validates:
- `OPENROUTER_API_KEY` set and non-empty
- `SHOPKEEPER_SERVER_TOKEN` set
- If `AGENT_CONFIG_DIR` set: dir exists, `identity.yaml` parses, `alive_config.yaml` parses, `db/` writable
- Port not already in use (socket probe, 0.5s timeout)
- Python >= 3.12
- Required packages importable (aiosqlite, yaml, httpx)
- DB file not locked by another process

Output: numbered error list with fix instructions, or `[Preflight] OK`. Fail-loud, exit non-zero on any error.

**Implementation steps:**
1. Create `engine/preflight.py` with a `run_preflight()` function that collects errors into a list
2. Each check is a small function: `_check_env_vars()`, `_check_config_dir()`, `_check_port()`, `_check_python_version()`, `_check_packages()`, `_check_db_lock()`
3. `run_preflight()` prints numbered errors + fix suggestions and returns `bool` (pass/fail)
4. In `engine/heartbeat_server.py` `start()`, call `run_preflight()` before `db.init_db()`. If it returns False, `sys.exit(1)`
5. Create `tests/test_preflight.py` — test each check in isolation with mocked env/filesystem

**Scope (files you may touch):**
- `engine/preflight.py` (CREATE)
- `engine/heartbeat_server.py` (~10 lines: add preflight call in `start()`)
- `tests/test_preflight.py` (CREATE)
**Scope (files you may NOT touch):**
- `engine/db/` (preflight is read-only, never writes to DB)
- `engine/pipeline/*`
- `engine/heartbeat.py`
**Tests:** `python -m pytest tests/test_preflight.py -v` — all pass. `python -m pytest tests/ --tb=short -q` — no regressions.
**Definition of done:** Starting the server with a missing `OPENROUTER_API_KEY` prints a clear error and exits instead of crashing with a traceback. All checks produce actionable messages.

---

### TASK-111: Deploy Ergonomics — Idempotent create_agent.sh
**Status:** READY
**Priority:** High
**Proposal:** `tasks/PROPOSAL-alive-infra-roadmap.md` Phase 1B
**Description:** Make `scripts/create_agent.sh` idempotent with two new flags:
- `--force`: if container exists, stop → update config → restart. Never deletes `db/` or `memory/` directories.
- `--validate`: run preflight without starting the container.

Only `scripts/create_agent.sh` is modified. `tasks/lounge-deploy/create_agent.sh` is reference/history only and must NOT be touched.

**Implementation steps:**
1. Add `--force` and `--validate` flag parsing at top of script
2. `--force`: check if container exists (`docker inspect`), if so: stop it, update config files, restart
3. `--validate`: run `docker exec <container> python -c "from preflight import run_preflight; ..."` or equivalent (requires TASK-110)
4. Guard: never `rm -rf` on `db/` or `memory/` directories — only config files are replaceable
5. Existing behavior (error if container exists) remains the default (no flags)

**Depends on:** TASK-110 (preflight module must exist for `--validate`)
**Scope (files you may touch):**
- `scripts/create_agent.sh` (~30 lines added)
**Scope (files you may NOT touch):**
- `tasks/lounge-deploy/create_agent.sh` (reference only)
- `engine/*`
**Tests:** Manual: `./scripts/create_agent.sh test-agent 9999 sk-test` twice — second run with `--force` should succeed. Without `--force`, second run should fail with clear message.
**Definition of done:** `create_agent.sh --force` updates config and restarts without data loss. `create_agent.sh --validate` checks config without starting.

---

### TASK-112: Deploy Ergonomics — System Doctor Script
**Status:** DONE (2026-03-01)
**Priority:** Medium
**Proposal:** `tasks/PROPOSAL-alive-infra-roadmap.md` Phase 1C
**Description:** Create `scripts/doctor.py` (~200 lines) that checks overall system health:
- All expected env vars present
- Docker image `alive-engine:latest` exists and its age
- Ports in use vs expected
- DB integrity (`PRAGMA integrity_check` on each agent's DB)
- Disk space on data partition
- Container status for all registered agents
- Network connectivity to OpenRouter API

Outputs a human-readable report. No mutations — read-only diagnostic.

**Implementation steps:**
1. Create `scripts/doctor.py` with a `main()` function
2. Each check is a function that returns (status, message) tuple: `check_env()`, `check_docker()`, `check_ports()`, `check_dbs()`, `check_disk()`, `check_containers()`, `check_network()`
3. Print a summary table at the end: `[PASS]` / `[WARN]` / `[FAIL]` per check
4. Exit 0 if all pass, exit 1 if any fail

**Scope (files you may touch):**
- `scripts/doctor.py` (CREATE)
**Scope (files you may NOT touch):**
- `engine/*`
- `lounge/*`
**Tests:** Run `python scripts/doctor.py` locally — should print report without errors (some checks will show WARN for missing Docker, which is expected in dev).
**Definition of done:** Operator can run `python scripts/doctor.py` on VPS and get a clear health report.

---

### TASK-113: Chat UX — Thinking Indicator + Multi-Message Support
**Status:** DONE (2026-03-01)
**Priority:** High
**Description:** Chat panel feels locked after sending a message: the input clears, the send button grays out (opacity 0.4), and there is zero feedback that the agent is processing. If the LLM cycle takes long or fails, the visitor sees nothing and must refresh. Three problems:
1. **No processing feedback** — backend sends no acknowledgment when a visitor message is received. The frontend has no "thinking" state.
2. **chat_error is invisible** — token exhaustion and other errors are silently logged to `console.warn`, never shown to the user.
3. **No timeout recovery** — TCP terminal clients get `"She seems lost in thought"` after 45s, but WebSocket visitors get nothing if the cycle hangs.

Fix:
1. Backend: send `chat_ack` message immediately when a visitor message is received (before the LLM runs).
2. Frontend: handle `chat_ack` → show a thinking indicator (animated dots in a shopkeeper-style bubble).
3. Frontend: surface `chat_error` messages visibly in the chat panel.
4. Frontend: clear the thinking indicator when `chat_response` / `chat_message` (shopkeeper) arrives, or after a timeout with a graceful fallback message.

**Scope (files you may touch):**
- `engine/heartbeat_server.py` (add `chat_ack` emission in `_handle_ws_chat`)
- `demo/window/src/hooks/useShopkeeperSocket.ts` (handle `chat_ack`, `chat_error` state)
- `demo/window/src/components/chat/ChatPanel.tsx` (thinking indicator, error display)
- `demo/window/src/components/chat/ChatMessage.tsx` (thinking bubble variant)
- `demo/window/src/lib/types.ts` (add `chat_ack` to `ServerMessage` union)
- `demo/window/src/app/globals.css` (thinking animation styles)
**Scope (files you may NOT touch):**
- `engine/heartbeat.py`
- `engine/pipeline/*`
- `engine/db/*`
**Tests:** Verify existing tests still pass. Manual: send a message → see thinking dots → receive response → dots disappear. Send with expired token → see error in chat.
**Definition of done:** Visitor sees immediate feedback after sending a message. Errors are visible. Chat never feels "locked".

---

### TASK-114: Per-Agent Daily Dollar Budget in Identity YAML
**Status:** DONE (2026-03-01)
**Priority:** Medium
**Description:** Add a `daily_budget` field to the agent identity YAML so each agent can have its own daily dollar cap. Currently the budget defaults to a hardcoded `$5.00` in `get_budget_remaining()` and can only be changed via the dashboard API at runtime. New agents should start with a budget from their identity config.

**Implementation:**
1. Add `daily_budget: float = 1.0` to `AgentIdentity` dataclass
2. Parse `daily_budget` from YAML in `from_yaml()` (default 1.0 if absent)
3. Add `daily_budget: 1.0` to `config/default_digital_lifeform.yaml`
4. On heartbeat `start()`, seed `daily_budget` into DB settings if not already set (identity value as initial default, never overwrite runtime changes)
5. Update `get_budget_remaining()` fallback from hardcoded `5.0` to `1.0` (matches identity default)

**Scope (files you may touch):**
- `engine/config/agent_identity.py` (add field + parsing)
- `config/default_digital_lifeform.yaml` (add daily_budget key)
- `engine/heartbeat.py` (seed budget on start)
- `engine/db/analytics.py` (update fallback default)
- `tests/test_agent_identity.py` (test new field)
**Scope (files you may NOT touch):**
- `engine/db/connection.py`
- `engine/pipeline/*`
- `engine/config/identity.py`
**Tests:** Identity loads daily_budget from YAML. Default is 1.0 when absent. Heartbeat seeds budget on first start. Existing budget not overwritten.
**Definition of done:** Each agent identity YAML can specify `daily_budget`. Value seeds into DB on first start. Dashboard can still override at runtime. Fallback matches identity default.

---

### TASK-115: Event Bus — Foundation
**Status:** READY
**Priority:** High
**Proposal:** `tasks/PROPOSAL-alive-infra-roadmap.md` Phase 2, Sub-phase 1
**Description:** Create the in-process async pub/sub event bus. `asyncio.Queue`-backed topic routing with typed messages. Not Redis/NATS — in-process only, forever. Wire `Heartbeat` to publish through bus while keeping old callbacks as bus subscribers (compatibility shim). Zero test changes in this task.

**What gets built:**
- `engine/bus.py` — `EventBus` class with two modes:
  - **Broadcast topics** (`outbound.scene_update`, `stage.progress`, etc.): standard fan-out with bounded queues + drop-oldest. Same as current `_window_broadcast` semantics.
  - **Keyed subscriptions** (`cycle.complete`): per-visitor keyed queues preserving current `_cycle_log_subscribers` semantics. Each request gets its own `sub_id`. Exact `visitor_id` matching + explicit `'*'` wildcard for ambient/idle cycles.
  - **Per-visitor lock** (`bus.visitor_lock(visitor_id)`): `asyncio.Lock` keyed by visitor_id. Serializes subscribe → schedule → wait → unsubscribe per visitor. Prevents the pre-existing duplicate-response race on concurrent `/api/chat` for same visitor.
- `engine/bus_types.py` — Typed payloads: `InboundSpeech`, `OutboundDialogue`, `SceneUpdate`, `StageProgress`, `CycleComplete`, etc.
- Compatibility shim: `Heartbeat._window_broadcast` → `bus.publish('outbound.scene_update', ...)`, `Heartbeat._stage_callback` → `bus.publish('stage.progress', ...)`, `Heartbeat._cycle_log_subscribers` → `bus.subscribe_keyed('cycle.complete', ...)`. Old interfaces still work — bus is wired underneath.

**Enumerated topics:**

| Topic | Publisher | Subscribers |
|-------|-----------|-------------|
| `inbound.visitor_speech` | TCP, WS, API, Telegram, X | Heartbeat |
| `inbound.visitor_connect` | TCP, WS, API | Heartbeat, presence tracker |
| `inbound.visitor_disconnect` | TCP, WS, API | Heartbeat, presence tracker |
| `outbound.dialogue` | pipeline/body (via output) | WS broadcaster, TCP writer |
| `outbound.scene_update` | Heartbeat (post-cycle) | WS broadcaster |
| `outbound.status` | Heartbeat (sleep/wake) | WS, TCP |
| `cycle.complete` | Heartbeat | Replaces `_cycle_log_subscribers` |
| `stage.progress` | Heartbeat | Console logger, terminal MRI |

**Implementation steps:**
1. Create `engine/bus.py` with `EventBus` class (~200 lines): `publish()`, `subscribe()`, `unsubscribe()` for broadcast topics; `publish_keyed()`, `subscribe_keyed()`, `unsubscribe_keyed()` for keyed topics; `visitor_lock()` for per-visitor serialization
2. Create `engine/bus_types.py` with dataclass payloads (~80 lines)
3. In `engine/heartbeat.py`, add `self._bus` attribute, replace `_window_broadcast` internals with `bus.publish('outbound.scene_update', ...)`
4. Replace `_stage_callback` with `bus.publish('stage.progress', ...)`
5. Replace `_cycle_log_subscribers` dict with bus keyed subscriptions — keep same external interface (compatibility shim)
6. Create `tests/test_bus.py` — unit tests for bus broadcast, keyed subscriptions, visitor_lock, wildcard delivery, drop-oldest behavior

**Scope (files you may touch):**
- `engine/bus.py` (CREATE)
- `engine/bus_types.py` (CREATE)
- `engine/heartbeat.py` (~50 lines: replace callbacks with bus.publish)
- `engine/heartbeat_server.py` (~10 lines: instantiate bus, pass to Heartbeat)
- `tests/test_bus.py` (CREATE)
**Scope (files you may NOT touch):**
- `engine/pipeline/*` (bus is transport layer, above the pipeline)
- `engine/db/`
- `engine/api/dashboard_routes.py`
- Route handler signatures (adapter pattern comes in TASK-117)
**Tests:** `python -m pytest tests/test_bus.py -v` — all pass. `python -m pytest tests/ --tb=short -q` — no regressions. Existing `_window_broadcast` and `_cycle_log_subscribers` tests still pass unchanged.
**Definition of done:** Bus exists and Heartbeat publishes through it. All existing behavior unchanged. Old callback interfaces work via compatibility shim. No test changes required.

---

### TASK-116: Event Bus — Transport Extraction
**Status:** BACKLOG
**Priority:** High
**Proposal:** `tasks/PROPOSAL-alive-infra-roadmap.md` Phase 2, Sub-phase 2
**Depends on:** TASK-115 (bus must exist)
**Description:** Extract TCP and WebSocket handlers from `heartbeat_server.py` into dedicated modules under `engine/api/`. Both register as bus subscribers. `heartbeat_server.py` shrinks from ~1,700 lines to ~500.

**What moves:**
- TCP handler → `engine/api/tcp.py` (~200 lines)
- WS handler → `engine/api/websocket.py` (~250 lines)
- `heartbeat_server.py` keeps: HTTP handler, `start()`, `stop()`, server lifecycle, config loading

**What does NOT change:**
- `window_state.py` builders (produce payloads, bus carries them)
- Pipeline stages (bus is transport layer, above the pipeline)
- DB layer
- Route handler signatures

**Implementation steps:**
1. Create `engine/api/tcp.py` — extract TCP connection handler, visitor handshake, message routing. Subscribe to `outbound.dialogue` and `outbound.scene_update` from bus.
2. Create `engine/api/websocket.py` — extract WS connection handler, dashboard auth, window state broadcast. Subscribe to bus topics.
3. Update `engine/heartbeat_server.py` — remove extracted code, import from new modules, wire into `start()`/`stop()`
4. Verify all TCP and WS tests pass unchanged

**Scope (files you may touch):**
- `engine/api/tcp.py` (CREATE)
- `engine/api/websocket.py` (CREATE)
- `engine/heartbeat_server.py` (MODIFY — large: ~600 lines moved out)
- `engine/heartbeat.py` (minor: remove any TCP/WS-specific code)
**Scope (files you may NOT touch):**
- `engine/pipeline/*`
- `engine/db/`
- `engine/bus.py` (should not need changes)
**Tests:** `python -m pytest tests/ --tb=short -q` — no regressions. Terminal connects, visitor speaks, cycle runs, window updates. WebSocket broadcast still works after extraction.
**Definition of done:** `heartbeat_server.py` is ~500 lines. TCP and WS handlers live in `engine/api/`. Bus carries all messages between components.

---

### TASK-117: Event Bus — Cleanup + RequestContext
**Status:** BACKLOG
**Priority:** Medium
**Proposal:** `tasks/PROPOSAL-alive-infra-roadmap.md` Phase 2, Sub-phase 3
**Depends on:** TASK-116 (extraction must be complete)
**Description:** Create `RequestContext` adapter for new handlers, remove compatibility shims from TASK-115, add integration tests for bus message flow.

**RequestContext pattern:**
```python
class RequestContext:
    """Thin wrapper that delegates to server. Tests can mock this directly."""
    def __init__(self, server):
        self._server = server
    async def http_json(self, writer, status, body):
        await self._server._http_json(writer, status, body)
    @property
    def heartbeat(self): return self._server.heartbeat
    @property
    def bus(self): return self._server._bus
```

Existing handler signatures remain `(server, writer, ...)` — `RequestContext` is opt-in for new handlers and Gateway RPC handlers in Phase 3. Full migration is deferred.

**Implementation steps:**
1. Create `engine/api/request_context.py` (~40 lines)
2. Remove compatibility shims in `engine/heartbeat.py` (old `_window_broadcast`, `_cycle_log_subscribers` wrappers)
3. Add integration tests: bus message flow end-to-end, concurrent chat with per-visitor lock, wildcard cycle delivery
4. Concurrency test: two simultaneous `POST /api/chat` for same `visitor_id` each get distinct dialogue

**Scope (files you may touch):**
- `engine/api/request_context.py` (CREATE)
- `engine/heartbeat.py` (~30 lines: remove shims)
- `tests/test_bus.py` (ADD integration tests)
**Scope (files you may NOT touch):**
- `engine/pipeline/*`
- `engine/db/`
- Route handler signatures (no rewrite — adapter is opt-in)
**Tests:** `python -m pytest tests/test_bus.py -v` — all pass including new integration tests. Concurrent same-visitor chat test passes.
**Definition of done:** Compatibility shims removed. `RequestContext` exists and is usable by new handlers. No old callback interfaces remain in Heartbeat.

---

### TASK-118: Gateway — Core
**Status:** BACKLOG
**Priority:** High
**Proposal:** `tasks/PROPOSAL-alive-infra-roadmap.md` Phase 3, Sub-phase 1
**Depends on:** TASK-115 (bus patterns established)
**Description:** Build the Gateway process — a standalone router that agents connect UP to. Handles agent registration, cognitive health monitoring, and RPC request forwarding. Lounge still works via old port-based routing during this phase (parallel operation).

**Architecture:**
- Gateway is a single process: HTTP :8000 (Lounge + public clients) + WS :8001 (agent pods + dashboards)
- Agents open persistent WS to Gateway on startup (not the other way around)
- Gateway tracks who's alive because they're connected
- No business logic, no DB writes, no LLM calls — router only

**Auth model:**
- Agent → Gateway: per-agent `GATEWAY_AGENT_TOKEN` validated against `agent_tokens.json` (flock + atomic file replacement)
- Lounge → Gateway: `GATEWAY_ADMIN_TOKEN` (separate shared secret)
- Per-request: Gateway forwards `Authorization` header transparently — agent-level auth still enforced inside the agent

**Health model:**
- Agent sends full `get_health_status()` payload every 15s over WS (not simplified)
- Gateway stores latest health verbatim, exposes via `GET /agents/{agent_id}/health`
- No heartbeat for 45s → `{"status": "unreachable", "reason": "heartbeat_timeout"}`

**Implementation steps:**
1. Create `engine/gateway.py` (~400 lines): `GatewayServer` with agent registry, WS handler for agent connections, HTTP handler for Lounge/client requests, RPC-over-WS request forwarding, health monitoring
2. Create `engine/gateway_client.py` (~150 lines): `GatewayClient` that runs inside each agent — connects to Gateway WS, handles RPC requests, sends health heartbeats
3. Modify `engine/heartbeat_server.py` (~30 lines): optional Gateway transport — if `GATEWAY_URL` env var set, start `GatewayClient` alongside existing HTTP/WS servers
4. Create `tests/test_gateway.py` and `tests/test_gateway_client.py`

**Scope (files you may touch):**
- `engine/gateway.py` (CREATE)
- `engine/gateway_client.py` (CREATE)
- `engine/heartbeat_server.py` (~30 lines: optional Gateway client startup)
- `tests/test_gateway.py` (CREATE)
- `tests/test_gateway_client.py` (CREATE)
**Scope (files you may NOT touch):**
- `engine/pipeline/*`
- `engine/db/`
- `lounge/*` (Lounge cutover is TASK-119)
- `engine/bus.py` (Gateway uses bus_types but not the bus itself)
**Tests:** Agent registration + deregistration. Health monitoring with timeout. RPC round-trip. Auth validation (reject bad token, reject impersonation). Standalone mode still works without Gateway.
**Definition of done:** Gateway runs as standalone process. Agent containers can connect to it. RPC forwarding works end-to-end. Existing standalone mode unaffected.

---

### TASK-119: Gateway — Lounge Cutover
**Status:** BACKLOG
**Priority:** High
**Proposal:** `tasks/PROPOSAL-alive-infra-roadmap.md` Phase 3, Sub-phase 2
**Depends on:** TASK-118 (Gateway core must exist)
**Description:** Full Lounge migration from per-agent port-based routing to Gateway. All 11 functions in `agent-client.ts` rewritten. Port-based routing removed. Nginx simplified.

**Migration matrix:**

| File | What Changes |
|------|-------------|
| `lounge/src/lib/agent-client.ts` | All 11 functions: replace `http://127.0.0.1:${port}/...` with `http://127.0.0.1:8000/agents/${agentId}/...` |
| `lounge/src/lib/types.ts` | Add `gateway_registered?: boolean`. `port: number` stays (0 = Gateway-managed) |
| `lounge/src/lib/manager-db.ts` | `createAgent()` port defaults to 0. `getNextPort()` skips `port=0` rows |
| `lounge/src/app/api/agents/route.ts` | POST: stop requiring port in create flow. Use Gateway for health |
| `lounge/src/app/api/agents/[id]/` | All sub-routes: resolve via Gateway instead of DB port lookup |
| `lounge/src/lib/docker-client.ts` | Gateway-mode create path: no host port, set GATEWAY_URL + token envs |
| `scripts/create_agent.sh` | `--gateway` mode: token generation, no host port mapping, atomic registry write |
| `scripts/destroy_agent.sh` | Remove agent token from `agent_tokens.json` |
| `deploy/nginx.conf` | Simplify to static Gateway routing |

**Implementation steps:**
1. Rewrite `lounge/src/lib/agent-client.ts` — all functions route through Gateway URL
2. Update `lounge/src/lib/types.ts` — add `gateway_registered` field
3. Update `lounge/src/lib/manager-db.ts` — port=0 convention, `getNextPort()` skips 0
4. Update `lounge/src/app/api/agents/` routes — Gateway-aware create/health/proxy
5. Update `lounge/src/lib/docker-client.ts` — Gateway-mode container creation
6. Add `--gateway` mode to `scripts/create_agent.sh` — token gen, atomic registry
7. Update `scripts/destroy_agent.sh` — clean up token
8. Simplify nginx config — static Gateway routing

**Scope (files you may touch):**
- `lounge/src/lib/agent-client.ts`
- `lounge/src/lib/types.ts`
- `lounge/src/lib/manager-db.ts`
- `lounge/src/app/api/agents/route.ts`
- `lounge/src/app/api/agents/[id]/` (all sub-routes)
- `lounge/src/lib/docker-client.ts`
- `scripts/create_agent.sh`
- `scripts/destroy_agent.sh`
- `deploy/nginx.conf`
- `deploy/nginx-alive-lounge.conf`
**Scope (files you may NOT touch):**
- `engine/gateway.py` (should not need changes)
- `engine/pipeline/*`
- `engine/db/`
**Tests:** `pnpm --dir lounge exec tsc --noEmit` passes. Agent creation via `--gateway` mode works. Lounge dashboard shows agent status in real-time. `docker stop <agent>` → Lounge shows offline within seconds. Standalone mode still works for local dev.
**Definition of done:** Lounge routes all traffic through Gateway. No more per-agent port management. Nginx is static config.

---

### TASK-120: Gateway — Inter-Agent Messaging
**Status:** BACKLOG
**Priority:** Medium
**Proposal:** `tasks/PROPOSAL-alive-infra-roadmap.md` Phase 3, Sub-phase 3
**Depends on:** TASK-118 (Gateway core must exist)
**Description:** Enable agents to send messages to each other through the Gateway. Messages routed by Gateway, appear in recipient's inbound event stream via Phase 2 bus. Agents stay isolated — they don't know each other's addresses.

**Implementation steps:**
1. Add `agent_send` RPC type to Gateway — receives `{target_agent_id, message}`, routes to target agent's WS connection
2. Add inbound handler in `gateway_client.py` — receives inter-agent messages, publishes to local bus as `inbound.agent_message`
3. Add `inbound.agent_message` topic to `bus_types.py`
4. Heartbeat processes agent messages like visitor messages (but with agent identity)

**Scope (files you may touch):**
- `engine/gateway.py` (~30 lines: add agent_send routing)
- `engine/gateway_client.py` (~20 lines: handle inbound agent messages)
- `engine/bus_types.py` (~10 lines: add AgentMessage type)
- `engine/heartbeat.py` (~20 lines: process agent messages)
- `tests/test_gateway.py` (ADD inter-agent tests)
**Scope (files you may NOT touch):**
- `engine/pipeline/*`
- `engine/db/`
- `lounge/*`
**Tests:** Agent A sends message to Agent B via Gateway. Message appears in Agent B's event stream. Unknown target agent returns error. Auth validated.
**Definition of done:** Agents can communicate through Gateway. Messages appear in recipient's cognitive pipeline.

---

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
