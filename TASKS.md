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

**Status:** IN_PROGRESS (code changes done 2026-02-17; simulation runs pending)
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
**Status:** BACKLOG
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

### TASK-061: Cognitive organ awareness (Frame 3)
**Status:** BACKLOG
**Priority:** High
**Complexity:** Medium
**Branch:** `feat/organ-awareness`
**Depends on:** TASK-060
**Spec:** `tasks/TASK-061-organ-awareness.md`
**Description:** She has no introspective access to her own cognitive process. Add a `[Cognitive state this cycle]` prompt section showing which organs are active/dormant/suppressed and why. She can request organ changes via `modify_self(target="organ", ...)`. Invariant organs (Cortex, Validator, Affect, Hippocampus) silently reject modification — no error, just no effect. Meta-sleep surfaces evidence when dormant organs cause gaps. Cognitive state block is hard-capped at 200 tokens to prevent prompt bloat.
**Scope (files you may touch):**
- `models/pipeline.py` (add CognitiveStateReport, OrganState dataclasses)
- `heartbeat.py` (generate CognitiveStateReport at cycle start, read organ_preferences)
- `pipeline/prompt_assembler.py` (assemble_cognitive_state_block, enforce 200-token cap)
- `pipeline/output.py` (extend modify_self handler for organ targets)
- `db/organs.py` (new — organ_preferences CRUD)
- `sleep.py` (review_organ_preferences phase)
- `migrations/` (organ_preferences table)
- `window/src/components/dashboard/OrganPanel.tsx` (new)
- `api/dashboard_routes.py` (new /api/dashboard/organs endpoint)
**Scope (files you may NOT touch):**
- `pipeline/cortex.py`
- `pipeline/basal_ganglia.py`
- `simulate.py`
**Tests:**
- Unit: invariant organs return no_effect silently, no error raised
- Unit: organ_preferences table correctly overrides default activation
- Unit: CognitiveStateReport reflects actual cycle state
- Unit: prompt block renders correctly and stays under 200 tokens
- Unit: meta-sleep generates journal entry when gaps detected after disabling organ
- Integration: disable cold_search → 20 cycles → cold_search absent from all cycles
- Integration: re-enable cold_search → appears in next cycle
**Definition of done:** Cortex prompt includes cognitive state block every cycle (≤200 tokens). She can see which organs are active, dormant, or suppressed. She can request organ changes via modify_self. Invariant organs silently reject modification. Meta-sleep surfaces evidence when dormant organs cause gaps. Dashboard shows organ state history.

---

### TASK-062: Intra-cycle cognitive loops (Frame 2)
**Status:** BACKLOG
**Priority:** High
**Complexity:** Large
**Branch:** `feat/cognitive-loops`
**Depends on:** TASK-061
**Spec:** `tasks/TASK-062-cognitive-loops.md`
**Description:** Every cycle is a single linear pass. Add three registered loop types (reflection, question, deliberation) that re-enter pipeline subsets within the same heartbeat. Controlled by `cycle.max_llm_calls` parameter (default 1, max 4) and daily LLM call hard cap. She enables/disables loops via `modify_self`. Deliberation trigger threshold stored in `self_parameters` (not hardcoded) for tuning.
**Key design constraints:**
- `cycle.max_llm_calls` in self_parameters: default 1, min 1, max 4
- `cycle.daily_llm_cap` in self_parameters: default 100, min 20, max 400
- `loops.deliberation_salience_gap` in self_parameters: default 0.10, min 0.02, max 0.30
- Loop priority order: reflection > question > deliberation
- Each loop type has energy cost multiplier (reflection 1.5x, question 2.0x, deliberation 1.8x)
- Cost tracked per loop type in loop_preferences table
**Scope (files you may touch):**
- `heartbeat.py` (run_loops() after body execution, daily call counter, budget enforcement)
- `pipeline/output.py` (extend modify_self for loop targets)
- `pipeline/action_registry.py` (no new actions — loops are automatic, not cortex-initiated)
- `pipeline/prompt_assembler.py` (extend cognitive state block with loop status + cost)
- `db/loops.py` (new — loop_preferences CRUD, loop cost tracking)
- `db/parameters.py` (seed cycle.max_llm_calls, cycle.daily_llm_cap, loops.deliberation_salience_gap)
- `sleep.py` (loop cost review)
- `migrations/` (loop_preferences table, new self_parameters seeds)
- `window/src/components/dashboard/LoopsPanel.tsx` (new)
- `api/dashboard_routes.py` (new /api/dashboard/loops endpoint)
**Scope (files you may NOT touch):**
- `pipeline/cortex.py` (loops call cortex via existing interface)
- `pipeline/basal_ganglia.py` (deliberation loop calls it externally)
- `simulate.py`
**Tests:**
- Unit: reflection loop fires when write_journal in cycle output
- Unit: question loop fires when ask_question with epistemic_id in output
- Unit: deliberation loop fires when intention salience gap < threshold
- Unit: no loop fires when calls_used >= max_calls
- Unit: no loop fires when daily cap reached
- Unit: enabling loop blocked when budget insufficient, journal entry written
- Unit: loop cost tracked per loop_id
- Unit: deliberation threshold reads from self_parameters
- Integration: reflection loop — journal + reaction in same cycle
- Integration: question loop — cold search attempted, curiosity resolved or escalated
- Integration: 100 cycles with reflection enabled, verify daily cost stays within cap
**Definition of done:** Three loop types available and functional. Loop activation requires cycle budget headroom. Daily LLM call hard cap prevents runaway cost. She enables/disables loops via modify_self. Deliberation trigger threshold tunable via self_parameters. Cognitive state block shows loop status and cumulative cost. Dashboard shows loop history and per-loop cost breakdown.

---

### TASK-063: Evolvable fitness function (Frame 5)
**Status:** BACKLOG
**Priority:** High
**Complexity:** Large
**Branch:** `feat/fitness-function`
**Depends on:** TASK-062 + philosophical gate (see below)
**Spec:** `tasks/TASK-063-fitness-function.md`
**Description:** She currently optimizes for an implicit function (wellbeing + coherence) chosen by the designer. Give her a versioned, explicit fitness function she can read, critique, and propose changes to. Two-sleep review process for activation. She can revert to any previous version.
**Philosophical gate — do NOT start implementation until ALL of these are true:**
- 60+ days of live operation with TASK-056 merged
- At least 5 self-modifications recorded
- At least 1 self-modification reverted by meta-sleep
- At least 1 self-modification sustained across multiple meta-sleep reviews
**Spec note:** Implementation details are intentionally omitted. The metric registry, computation functions, and review prompts should be designed after 60 days of live data from TASK-060/061/062. What we know now: versioned fitness_function table, weighted metrics she can adjust, two-sleep review gate, `propose_fitness_change` action (energy 0.20, cooldown 86400s), dashboard with version history and score tracking. Full spec to be written when philosophical gate conditions are met.
**Definition of done:** She can propose changes to her own fitness function. Proposals require two consecutive sleep approvals. Active fitness function visible in cortex prompt. Fitness score tracked over time and compared across versions. Philosophical gate enforced in code. Dashboard shows full fitness history. System behavior plausibly shifts over months based on her chosen function.

---

### TASK-064: Sleep Phase Extraction
**Status:** BACKLOG
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
**Status:** BACKLOG
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
