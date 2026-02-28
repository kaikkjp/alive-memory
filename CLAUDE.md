# CLAUDE.md — Instructions for AI Agents

> **READ THIS FIRST.** If you are Claude Code, Codex, Cowork, or any AI agent working on this codebase, these are your standing orders. Read `ARCHITECTURE.md` next.

## Project: The Shopkeeper

A persistent AI character engine. Python 3.12+ backend, Next.js frontend. Single LLM call per cognitive cycle. SQLite database. Deployed on VPS via Docker.

## Repository Structure

The repo has a hard boundary between platform code and instance-specific code. See `BOUNDARY.md` for full details.

- **`engine/`** — All platform Python code (heartbeat, pipeline, db, config, models, etc.)
- **`demo/`** — Shopkeeper instance (identity YAML, prompts, frontend, nginx, content)
- **`lounge/`** — Manager dashboard (Next.js, separate concern)
- **`config/`** — Platform YAML templates (NOT a Python package — no `__init__.py`)
- **`tests/`**, **`scripts/`**, **`deploy/`**, **`sim/`**, **`experiments/`** — stay at top level

**The rule: `engine/` never imports from `demo/`.** Verify with `grep -r "from demo" engine/`.

## Before You Write Any Code

1. **Read `ARCHITECTURE.md`** — understand what every module does
2. **Read `TASKS.md`** — find your assigned task and its SCOPE
3. **You may ONLY modify files listed in the task's SCOPE** — touching anything else is a bug, not a feature
4. **Run tests before and after** — `python -m pytest tests/ -v`
5. **When done, run the doc update** — `python scripts/update_docs.py`
6. **Mark your task DONE in `TASKS.md`** — add completion date

## Scope Enforcement

Every agent session MUST be associated with a TASK-XXX ID. Before committing:

1. Run `./scripts/scope-check.sh TASK-XXX` to validate all changed files are within your task's clearance
2. If you get a VIOLATION, you touched a file outside your scope. Revert it.
3. If you get an ESCALATION, stop and notify the operator.

To check a specific file's risk tier: `./scripts/scope-check.sh --classify path/to/file.py`

Risk tiers are defined in `risk-policy.json`. Do not modify `risk-policy.json` without operator approval.

## Task Protocol (MANDATORY)

Every coding session follows this exact sequence. No exceptions.

### Step 1: Identify your task
Open `TASKS.md`. Find the first task with status `READY`. If no task is READY, STOP and ask the operator what to work on. Do NOT freelance.

### Step 2: Announce scope
Before writing any code, list the files you will modify. Cross-check against the task's `scope:` field. If you need to touch a file not in scope, STOP and explain why to the operator.

### Step 3: Run tests (before)
```bash
python -m pytest tests/test_<module>.py -v
```
Run only the tests for files you're about to touch. Note any pre-existing failures. You are not responsible for those — but you must not add new ones.

### Step 4: Do the work
Implement the task. Stay within scope. If you discover a bug in an out-of-scope file, document it in `TASKS.md` as a new task with its own scope — do NOT fix it now.

**Plan Mode for sensitive tasks:** If the task is marked `Priority: High`, OR touches `db.py`, OR touches any `pipeline/*` file, use Plan Mode (Shift+Tab twice) before writing any code. Draft a plan showing which files you'll change, what each change does, and the order of operations. Show the plan. Wait for operator approval before proceeding.

Skip Plan Mode if the task spec already contains numbered implementation steps — follow those directly.

### Step 5: Run tests (after)
```bash
python -m pytest tests/test_<module>.py -v      # targeted — run first
python -m pytest tests/ --tb=short              # full suite — run before commit
```
All previously-passing tests must still pass. New tests for your work should also pass. If the full suite fails on tests unrelated to your changes, note them and proceed.

### Step 6: Update docs
```bash
python scripts/update_docs.py
```
This refreshes line counts and module listings in ARCHITECTURE.md.

### Step 7: Mark task done
In `TASKS.md`, change your task status from `READY` to `DONE` and add the date.

### Step 8: Commit
```bash
git add -A
git commit -m "feat: <task title> [TASK-XXX]"
```

### Step 9: Chain or Stop
Follow the **Task Chaining** rules below. Either pick up the next task or stop and report.

### Step 10: Code review (MANDATORY before merge)
Spawn the code-reviewer sub-agent:
```
Use the code-reviewer agent to review changes for TASK-XXX.
Check: (1) all changed files within scope in TASKS.md,
(2) python -m pytest tests/ -v passes,
(3) no architectural violations per ARCHITECTURE.md.
Output VERDICT: PASS or VERDICT: FAIL with reasons.
```
Do not merge without `VERDICT: PASS`. If it flags issues, fix and re-request.

### Step 11: Clear context
Run `/clear` before starting any new task.

---

## Task Chaining

After completing a task (Step 8), check if you should continue or stop.

### When to chain (pick up the next task):
1. Another task in TASKS.md has status `READY`
2. Its scope does NOT overlap with files you just modified (no shared files)
3. You have not already completed 3 tasks this session
4. All tests passed after your just-completed task

If all four conditions are met: pick up the next `READY` task. No need to ask the operator — the `READY` status IS permission.

### When to STOP:
- No task has status `READY` → stop, report completion
- Next `READY` task's scope overlaps with files you just changed → stop, let operator verify first
- You've completed 3 tasks this session → stop for operator review
- ANY test failed → stop immediately, do not chain
- You're unsure about scope overlap → stop and ask

### Operator's role:
The operator pre-loads chains by setting multiple tasks to `READY` before a session. If only one task is `READY`, you do that task and stop. The operator controls the chain, not the agent.

---

## Sub-Agent Rules

### Allowed sub-agent uses:
- Code review (Step 10)
- Running the full test suite while you continue editing
- Generating boilerplate (e.g. TypeScript types from Python dataclasses)
- File moves / renames that don't require judgment
- Doc updates (`scripts/update_docs.py`)

### Prohibited sub-agent uses:
- Modifying `engine/pipeline/*` files (cognitive architecture — requires full context)
- Changing `engine/prompt_assembler.py` or `engine/config/identity.py` (affects LLM behavior)
- Any change that affects LLM call content or frequency
- `engine/db/` modifications (merge conflict risk)
- Parallel edits to the same file

### General:
- Do NOT parallelize file edits on the same file
- Background test runs with Ctrl+B when they're slow

---

## Critical Rules

### DO NOT touch these files unless your task explicitly requires it:
- `engine/db/` — Persistence package, ~3300 lines. Changes here risk breaking everything. If your task requires a new DB function, add it at the END of the relevant module. Full refactor is TASK-003 — do not attempt outside that task.
- `engine/heartbeat.py` — The brain's main loop. Extremely sensitive to race conditions. See `bugs-and-fixes.md` for examples of what goes wrong.
- `engine/config/identity.py` — Character soul. Changes alter her personality.
- `demo/config/prompts.yaml` — Visual identity. Changes alter her appearance.
- `engine/pipeline/cortex.py` — The LLM call. The most expensive code path ($). Test thoroughly.

### Pipeline modification rules:
- Each pipeline stage has a single responsibility. Don't merge stages.
- `engine/pipeline/validator.py` checks format/schema ONLY. Character-rule enforcement is in the metacognitive monitor (`engine/pipeline/output.py`).
- `engine/pipeline/sanitize.py` is pure logic. Keep it that way.
- If you add a new pipeline stage, add it to the flow in `engine/heartbeat.py` `run_cycle()` and document it in `ARCHITECTURE.md`.
- The cognitive pipeline is: Cortex → Validator → Basal Ganglia → Body → Output. Changes to this chain must be reflected across all stages simultaneously.
- `engine/pipeline/executor.py` is **DEPRECATED**. Use `engine/pipeline/basal_ganglia.py` → `engine/pipeline/body.py` → `engine/pipeline/output.py`.

### Simulation safety rules:
- **NEVER run simulation code against the production DB.** `engine/db/connection.py` has a hard guard in `set_db_path()` that rejects filenames matching `shopkeeper.db` or `shopkeeper-prod.db`. Do not bypass this.
- When using `engine/simulate.py`, always use `--db` or `--output` to specify an isolated path. Default is `data/sim/` (safe).
- The `sim/` module uses in-memory SQLite only — safe by construction.
- On VPS: never run experiment scripts as root. Use the `shopkeeper` user. Root processes corrupt directory ownership and lock the DB. See INCIDENT-006 in `bugs-and-fixes.md`.

### Database rules:
- All DB access goes through `engine/db/`. Never use raw aiosqlite elsewhere.
- New tables need a migration file in `migrations/`.
- Use `async with db.transaction()` for multi-step writes.
- All timestamps are UTC in storage, JST for display/logic (see `engine/clock.py`).

### Frontend rules:
- Frontend lives in `demo/window/`. It's a Next.js app.
- Backend communication: WebSocket (live updates) + HTTP REST (dashboard data).
- WebSocket messages are defined by `engine/window_state.py` on the backend.
- If you change backend state shape, update `demo/window/src/lib/types.ts`.

## Common Tasks

### "Add a new action the shopkeeper can take"
1. Add `ActionCapability` entry in `engine/pipeline/action_registry.py`
2. Add action type to cortex prompt in `engine/prompt_assembler.py`
3. Add validation rule in `engine/pipeline/validator.py` (format/schema only)
4. Add execution logic in `engine/pipeline/body.py`
5. Add any DB persistence in `engine/db/` (at end of relevant module)
6. Add test in `tests/`

### "Add a new dashboard panel"
1. Create component in `demo/window/src/components/dashboard/`
2. Add API endpoint in `engine/heartbeat_server.py` (in the dashboard routes section)
3. Add API client function in `demo/window/src/lib/dashboard-api.ts`
4. Add panel to `demo/window/src/app/dashboard/page.tsx`
5. Add TypeScript types in `demo/window/src/lib/types.ts`

### "Fix a bug in the cognitive cycle"
1. Read `bugs-and-fixes.md` for patterns of known race conditions
2. The most common bug: ambient/silence cycles stealing visitor events from inbox
3. Always check `self.pending_microcycle.is_set()` before running background cycles
4. Test with `engine/simulate.py` before testing live

### "Add a new memory type"
1. Define dataclass in `engine/models/state.py`
2. Add table creation in `engine/db/connection.py` `run_migrations()`
3. Add migration file in `migrations/`
4. Add recall logic in `engine/pipeline/hippocampus.py`
5. Add consolidation logic in `engine/pipeline/hippocampus_write.py`
6. Add to prompt context in `engine/prompt_assembler.py`

## Code Style

- Python: asyncio everywhere. Type hints on function signatures.
- No global mutable state except through `db.py`.
- Pipeline stages are functions, not classes (except `Heartbeat`).
- Logging: use print with `[ModuleName]` prefix (legacy pattern, don't refactor).
- Tests: pytest + pytest-asyncio. Test files mirror source files.

## Testing

~1445 tests, ~4s execution. Clean exit (no hang).

**Always run tests with:**
```bash
python3 -m pytest tests/ --tb=short -q 2>&1 || true
```

**During development — run only relevant module tests:**
```bash
python3 -m pytest tests/test_<module>.py -v --tb=short 2>&1 || true
```

**Known failure:** `test_action_read_content.py::test_read_content_cooldown` — pre-existing, ignore.

## Running

```bash
# Development (standalone)
python engine/terminal.py

# Development (server + client)
python engine/heartbeat_server.py    # Terminal 1
python engine/terminal.py --connect  # Terminal 2

# Tests
python -m pytest tests/ -v

# Simulation (no server needed)
python engine/simulate.py --cycles 10
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENROUTER_API_KEY` | Yes | OpenRouter API key for all LLM calls |
| `SHOPKEEPER_DB_PATH` | No | SQLite DB path (default: `data/shopkeeper.db`) |
| `COLD_SEARCH_ENABLED` | No | Enable vector search (`true`/`false`, default `false`) |
| `FAL_KEY` | For visuals | fal.ai API key for image generation |
| `OPENAI_API_KEY` | For embeddings | OpenAI API key for text embeddings |

## Git Workflow

- `main` — stable, deployable
- `feat/*` — feature branches, one per task
- Always branch from the latest `main` unless building on an unmerged feature
- Squash merge to main
- Run full suite before pushing: `python -m pytest tests/ --tb=short`

## What NOT to Do

- Don't refactor db.py outside of TASK-003 — too risky unless that's the active task
- Don't add new pip dependencies without documenting in requirements.txt
- Don't change the single-LLM-call-per-cycle architecture
- Don't add direct API calls in pipeline stages (only cortex.py calls the LLM)
- Don't use `time.time()` or `datetime.now()` — use `clock.now()` for simulation compat
- Don't add print statements without `[ModuleName]` prefix
- Don't modify the character bible or identity without owner approval
- Don't use `engine/pipeline/executor.py` for new code — it's deprecated
- Don't pipe test output through `tail` or `head` in background tasks — use `--tb=short` flag instead
- Don't run `engine/simulate.py` or `experiments/*.py` without `--db` or `--output` pointing to an isolated path — see INCIDENT-006
- Don't run experiment scripts as root on the VPS — use the `shopkeeper` user
