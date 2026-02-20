# Project Brief: Code Factory — Risk-Aware Agent Pipeline

## Context
We run multi-agent Claude Code workflows using git worktrees with different models routed to different tasks. We need a formalized control plane so agents can write, validate, and review code with deterministic, auditable standards. Inspired by Ryan Carson's "Code Factory" pattern.

## Objective
Set up the repo infrastructure so coding agents can implement, validate, and be reviewed automatically with risk-tiered gating, SHA-pinned validation, and a remediation loop.

---

## Tasks

### 1. Create `risk-policy.json` (root of repo)
A single machine-readable contract defining:
- **Risk tiers by path**: Map file paths/globs to `high` / `medium` / `low` risk tiers
  - `high`: Core architecture files (e.g., `src/core/**`, `src/cognitive/**`, `db/schema.*`, `server/websocket/**`, any files touching persistence, state machines, or money/transactions)
  - `medium`: Game logic, API routes, agent behaviors
  - `low`: Config, docs, tests, UI copy, scripts
- **Merge policy per tier**: Which checks are required before merge
  - `high` → `[risk-policy-gate, tests, build, code-review-agent, browser-evidence (if UI)]`
  - `medium` → `[risk-policy-gate, tests, build]`
  - `low` → `[risk-policy-gate, tests]`
- **Model routing hints** (custom extension): Which model class to use for review per tier
  - `high` → opus-level review
  - `medium` → sonnet-level review  
  - `low` → haiku-level review
- **Docs drift rules**: If any file in `risk-policy.json`, CI configs, or policy scripts changes, require docs update check

### 2. Create `scripts/risk-policy-gate.ts` (or `.sh`)
Preflight gate script that:
- Reads `risk-policy.json`
- Takes a list of changed files (from git diff or CI env)
- Computes the highest risk tier touched
- Outputs required checks for that tier
- Validates docs drift rules (if policy files changed, ensure docs are also updated)
- Exits non-zero if any required check is missing or policy is violated
- **Must run BEFORE expensive CI jobs** (tests, build, security scans)

### 3. Create `scripts/sha-validate.ts` (or `.sh`)
SHA discipline enforcement:
- Accept `headSha` as input
- Verify that any review state / evidence artifacts are tagged to this exact SHA
- Reject stale review comments or artifacts from older commits
- Provide a helper function `isCurrentHead(sha: string): boolean`

### 4. Create `scripts/rerun-deduper.ts`
Single canonical rerun-comment writer:
- Uses marker comment pattern: `<!-- agent-review-rerun -->`
- Dedupes by `sha:<headSha>` within the marker
- Prevents duplicate bot comments when multiple workflows trigger simultaneously
- Works with GitHub PR comment API (or can be adapted to other platforms)

### 5. Create `scripts/remediation-loop.ts`
Automated fix loop (the high-leverage piece):
- Reads review findings (from code review agent output)
- Filters to only actionable findings for current head SHA
- For each finding:
  - Extract file path, line range, issue description
  - Generate a patch prompt for the coding agent
  - Run focused validation (typecheck + relevant tests only)
  - If passing, stage the fix commit
- Push all fix commits to the same PR branch
- Trigger rerun of review via the deduper
- **Constraints**:
  - Pin model + effort level (read from `risk-policy.json` model routing)
  - Never bypass policy gates
  - Skip stale comments not matching current head
  - Max 3 remediation attempts per finding before flagging for human review

### 6. Create `scripts/harness-gap.ts`
Incident-to-test-case pipeline:
- Accept incident description (from issue template or CLI)
- Generate a skeleton test case file in the appropriate test directory
- Add entry to `harness-gaps.json` tracking file with:
  - incident ID / link
  - date opened
  - test case file path
  - SLA target (default: 48h for high tier, 1 week for others)
  - status: `open` | `case-written` | `verified`
- Provide a `harness:weekly-metrics` script that reports on gap SLA compliance

### 7. Create GitHub Actions workflows (or equivalent CI config)

#### `.github/workflows/risk-policy-gate.yml`
- Triggers on PR open / synchronize
- Runs `risk-policy-gate` script
- Must complete before all other CI jobs
- Sets output for downstream jobs (risk tier, required checks)

#### `.github/workflows/agent-review-rerun.yml`  
- Triggers on PR synchronize (new push)
- Runs `rerun-deduper` to request fresh review
- Single canonical source of rerun requests

#### `.github/workflows/auto-resolve-threads.yml`
- Triggers after review check passes on current head
- Auto-resolves unresolved PR threads where ALL comments are from bots
- Never touches human-participated threads
- Reruns policy gate after resolving

### 8. Add npm scripts to `package.json`
```json
{
  "scripts": {
    "harness:risk-tier": "ts-node scripts/risk-policy-gate.ts",
    "harness:sha-validate": "ts-node scripts/sha-validate.ts",
    "harness:remediate": "ts-node scripts/remediation-loop.ts",
    "harness:gap:add": "ts-node scripts/harness-gap.ts --add",
    "harness:gap:status": "ts-node scripts/harness-gap.ts --status",
    "harness:weekly-metrics": "ts-node scripts/harness-gap.ts --metrics"
  }
}
```

---

## Technical Constraints
- TypeScript preferred (we already use it), shell scripts acceptable for simple glue
- Must work with git worktree-based parallel development
- No external service dependencies for the core pipeline (review agent integration is pluggable)
- All scripts should be idempotent and safe to rerun
- Include clear error messages and exit codes

## File Structure
```
├── risk-policy.json
├── scripts/
│   ├── risk-policy-gate.ts
│   ├── sha-validate.ts
│   ├── rerun-deduper.ts
│   ├── remediation-loop.ts
│   └── harness-gap.ts
├── harness-gaps.json          (tracking file, initially empty array)
├── .github/workflows/
│   ├── risk-policy-gate.yml
│   ├── agent-review-rerun.yml
│   └── auto-resolve-threads.yml
```

## Success Criteria
- `npm run harness:risk-tier` correctly classifies any set of changed files
- Policy gate blocks merge when required checks are missing
- SHA validation rejects stale review artifacts
- Rerun deduper prevents duplicate bot comments
- Remediation loop can read findings and generate fix commits
- Harness gap tracker maintains incident-to-test-case traceability
- All workflows trigger in correct order (preflight → CI fanout → review → resolve)
