# CLAUDE.md — Instructions for AI Agents

> **READ THIS FIRST.** If you are Claude Code, Codex, Cowork, or any AI agent working on this codebase, these are your standing orders. Read `ARCHITECTURE.md` next.

## Project: The Shopkeeper

A persistent AI character engine. Python 3.12+ backend, Next.js frontend. Single LLM call per cognitive cycle. SQLite database. Deployed on VPS via Docker.

## Before You Write Any Code

1. **Read `ARCHITECTURE.md`** — understand what every module does
2. **Read `TASKS.md`** — find your assigned task and its SCOPE
3. **You may ONLY modify files listed in the task's SCOPE** — touching anything else is a bug, not a feature
4. **Run tests before and after** — `python -m pytest tests/ -v`
5. **When done, run the doc update** — `python scripts/update_docs.py`
6. **Mark your task DONE in `TASKS.md`** — add completion date

## Task Protocol (MANDATORY)

Every coding session follows this exact sequence. No exceptions.

### Step 1: Identify your task
Open `TASKS.md`. Find the first task with status `READY`. If no task is READY, STOP and ask the operator what to work on. Do NOT freelance.

### Step 2: Announce scope
Before writing any code, list the files you will modify. Cross-check against the task's `scope:` field. If you need to touch a file not in scope, STOP and explain why to the operator.

### Step 3: Run tests (before)
```bash
python -m pytest tests/ -v
```
Note any pre-existing failures. You are not responsible for those — but you must not add new ones.

### Step 4: Do the work
Implement the task. Stay within scope. If you discover a bug in an out-of-scope file, document it in `TASKS.md` as a new task with its own scope — do NOT fix it now.

### Step 5: Run tests (after)
```bash
python -m pytest tests/ -v
```
All previously-passing tests must still pass. New tests for your work should also pass.

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

## Critical Rules

### DO NOT touch these files unless your task explicitly requires it:
- `db.py` — God module, 2291 lines. Changes here risk breaking everything. If your task requires a new DB function, add it at the END of the file only.
- `heartbeat.py` — The brain's main loop. Extremely sensitive to race conditions. See `bugs-and-fixes.md` for examples of what goes wrong.
- `config/identity.py` — Character soul. Changes alter her personality.
- `config/prompts.yaml` — Visual identity. Changes alter her appearance.
- `pipeline/cortex.py` — The LLM call. The most expensive code path ($). Test thoroughly.

### Pipeline modification rules:
- Each pipeline stage has a single responsibility. Don't merge stages.
- `pipeline/validator.py` is pure logic (imports only `re`). Keep it that way.
- `pipeline/sanitize.py` is pure logic. Keep it that way.
- If you add a new pipeline stage, add it to the flow in `heartbeat.py` `run_cycle()` and document it in `ARCHITECTURE.md`.
- Cortex output format changes MUST be reflected in validator.py AND executor.py simultaneously.

### Database rules:
- All DB access goes through `db.py`. Never use raw aiosqlite elsewhere.
- New tables need a migration file in `migrations/`.
- Use `async with db.transaction()` for multi-step writes.
- All timestamps are UTC in storage, JST for display/logic (see `clock.py`).

### Frontend rules:
- Frontend lives in `window/`. It's a Next.js app.
- Backend communication: WebSocket (live updates) + HTTP REST (dashboard data).
- WebSocket messages are defined by `window_state.py` on the backend.
- If you change backend state shape, update `window/src/lib/types.ts`.

## Common Tasks

### "Add a new action the shopkeeper can take"
1. Add action type to cortex prompt in `prompt_assembler.py`
2. Add validation rule in `pipeline/validator.py`
3. Add execution logic in `pipeline/executor.py`
4. Add any DB persistence in `db.py` (at end of file)
5. Add test in `tests/`

### "Add a new dashboard panel"
1. Create component in `window/src/components/dashboard/`
2. Add API endpoint in `heartbeat_server.py` (in the dashboard routes section)
3. Add API client function in `window/src/lib/dashboard-api.ts`
4. Add panel to `window/src/app/dashboard/page.tsx`

### "Fix a bug in the cognitive cycle"
1. Read `bugs-and-fixes.md` for patterns of known race conditions
2. The most common bug: ambient/silence cycles stealing visitor events from inbox
3. Always check `self.pending_microcycle.is_set()` before running background cycles
4. Test with `simulate.py` before testing live

### "Add a new memory type"
1. Define dataclass in `models/state.py`
2. Add table creation in `db.py` `run_migrations()`
3. Add migration file in `migrations/`
4. Add recall logic in `pipeline/hippocampus.py`
5. Add consolidation logic in `pipeline/hippocampus_write.py`
6. Add to prompt context in `prompt_assembler.py`

## Code Style

- Python: asyncio everywhere. Type hints on function signatures.
- No global mutable state except through `db.py`.
- Pipeline stages are functions, not classes (except `Heartbeat`).
- Logging: use print with `[ModuleName]` prefix (legacy pattern, don't refactor).
- Tests: pytest + pytest-asyncio. Test files mirror source files.

## Running

```bash
# Development (standalone)
python terminal.py

# Development (server + client)
python heartbeat_server.py    # Terminal 1
python terminal.py --connect  # Terminal 2

# Tests
python -m pytest tests/ -v

# Simulation (no server needed)
python simulate.py --cycles 10
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes | Claude API key for cortex calls |
| `SHOPKEEPER_DB_PATH` | No | SQLite DB path (default: `data/shopkeeper.db`) |
| `COLD_SEARCH_ENABLED` | No | Enable vector search (`true`/`false`, default `false`) |
| `FAL_KEY` | For visuals | fal.ai API key for image generation |
| `OPENAI_API_KEY` | For embeddings | OpenAI API key for text embeddings |

## Git Workflow

- `main` — stable, deployable
- `feat/*` — feature branches, one per task
- Always branch from the latest `main` unless building on an unmerged feature
- Squash merge to main
- Run tests before pushing: `python -m pytest tests/ -v`

## What NOT to Do

- Don't refactor db.py into smaller modules (planned but not now — too risky mid-flight)
- Don't add new pip dependencies without documenting in requirements.txt
- Don't change the single-LLM-call-per-cycle architecture
- Don't add direct API calls in pipeline stages (only cortex.py calls the LLM)
- Don't use `time.time()` or `datetime.now()` — use `clock.now()` for simulation compat
- Don't add print statements without `[ModuleName]` prefix
- Don't modify the character bible or identity without owner approval
