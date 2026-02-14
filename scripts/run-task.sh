#!/bin/bash
# ============================================================
# run-task.sh — Automated task execution pipeline
# ============================================================
# Usage: ./scripts/run-task.sh
#
# 1. Reads TASKS.md for the READY task
# 2. Creates a feature branch
# 3. Runs implementer agent (M2.5 — cheap)
# 4. Runs tests
# 5. Runs code-reviewer agent (Opus — smart)
# 6. If PASS → merges to main
# 7. If FAIL → stops and shows the review
# ============================================================

set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}═══════════════════════════════════════${NC}"
echo -e "${YELLOW}  SHOPKEEPER — Automated Task Runner   ${NC}"
echo -e "${YELLOW}═══════════════════════════════════════${NC}"
echo ""

# ── Step 0: Check for READY task ──
READY_TASK=$(grep -E "^\*\*Status:\*\* READY" TASKS.md -B 2 | grep "^### TASK-" | head -1)

if [ -z "$READY_TASK" ]; then
    echo -e "${RED}No READY task found in TASKS.md${NC}"
    echo "Flip a task from BACKLOG to READY first."
    exit 1
fi

TASK_ID=$(echo "$READY_TASK" | grep -oE "TASK-[0-9]+")
TASK_TITLE=$(echo "$READY_TASK" | sed "s/### ${TASK_ID}: //")

echo -e "Found: ${GREEN}${TASK_ID}${NC} — ${TASK_TITLE}"
echo ""

# ── Step 1: Create feature branch ──
BRANCH_NAME="feat/${TASK_ID,,}"  # lowercase
echo -e "${YELLOW}[1/6] Creating branch: ${BRANCH_NAME}${NC}"

git checkout main
git pull origin main
git checkout -b "$BRANCH_NAME"

echo ""

# ── Step 2: Run implementer ──
echo -e "${YELLOW}[2/6] Running implementer agent (M2.5)...${NC}"
echo ""

claude -p "You are the implementer agent. Read CLAUDE.md and TASKS.md. Pick up ${TASK_ID} which has status READY. Follow the Task Protocol exactly. Implement the task within scope. Run tests before and after. Run scripts/update_docs.py. Mark the task DONE in TASKS.md. Commit your changes." \
    --agent implementer \
    --output-format text \
    2>&1 | tee "/tmp/${TASK_ID}-implement.log"

IMPLEMENT_EXIT=$?

if [ $IMPLEMENT_EXIT -ne 0 ]; then
    echo -e "${RED}Implementer failed. Check /tmp/${TASK_ID}-implement.log${NC}"
    exit 1
fi

echo ""

# ── Step 3: Run tests ──
echo -e "${YELLOW}[3/6] Running tests...${NC}"
echo ""

python -m pytest tests/ -v 2>&1 | tee "/tmp/${TASK_ID}-tests.log"
TEST_EXIT=${PIPESTATUS[0]}

if [ $TEST_EXIT -ne 0 ]; then
    echo -e "${RED}Tests failed. Check /tmp/${TASK_ID}-tests.log${NC}"
    echo -e "${YELLOW}Fix the failures and re-run, or discard with: git checkout main && git branch -D ${BRANCH_NAME}${NC}"
    exit 1
fi

echo ""

# ── Step 4: Run code reviewer ──
echo -e "${YELLOW}[4/6] Running code reviewer (Opus)...${NC}"
echo ""

REVIEW_OUTPUT=$(claude -p "You are the code-reviewer agent. Review the changes on this branch for ${TASK_ID}. Run git diff main --name-only to see changed files. Cross-reference against the task scope in TASKS.md. Check for bugs, architecture violations, test gaps. End your review with exactly one of these verdicts on its own line: VERDICT: PASS or VERDICT: FAIL" \
    --agent code-reviewer \
    --output-format text \
    2>&1)

echo "$REVIEW_OUTPUT" | tee "/tmp/${TASK_ID}-review.log"

echo ""

# ── Step 5: Check verdict ──
VERDICT=$(echo "$REVIEW_OUTPUT" | grep -oE "VERDICT: (PASS|FAIL)" | tail -1)

if [ "$VERDICT" = "VERDICT: PASS" ]; then
    echo -e "${GREEN}[5/6] Review PASSED${NC}"
    echo ""

    # ── Step 6: Merge ──
    echo -e "${YELLOW}[6/6] Merging to main...${NC}"
    git checkout main
    git merge "$BRANCH_NAME" --no-ff -m "feat: ${TASK_TITLE} [${TASK_ID}]"
    git push origin main
    git branch -d "$BRANCH_NAME"

    echo ""
    echo -e "${GREEN}═══════════════════════════════════════${NC}"
    echo -e "${GREEN}  ${TASK_ID} COMPLETE — merged to main  ${NC}"
    echo -e "${GREEN}═══════════════════════════════════════${NC}"

else
    echo -e "${RED}[5/6] Review FAILED${NC}"
    echo ""
    echo "Review saved to /tmp/${TASK_ID}-review.log"
    echo ""
    echo "Options:"
    echo "  1. Fix issues and re-run:  ./scripts/run-task.sh"
    echo "  2. Fix manually:          (edit files, commit, then run /review in Claude Code)"
    echo "  3. Discard:               git checkout main && git branch -D ${BRANCH_NAME}"
    exit 1
fi
