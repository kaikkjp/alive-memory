#!/usr/bin/env bash
# scope-check.sh — Validates that a branch only touches files within its task's risk clearance.
#
# Usage:
#   ./scripts/scope-check.sh TASK-058              # checks current branch vs main
#   ./scripts/scope-check.sh TASK-056 feat/dynamic-actions   # checks specific branch
#   ./scripts/scope-check.sh --list-tiers          # show all path→tier mappings
#   ./scripts/scope-check.sh --classify FILE...    # classify specific files
#
# Reads: risk-policy.json (repo root)
# Requires: bash 4+, jq, git
#
# Exit codes:
#   0 — all files within clearance
#   1 — scope violation (file exceeds task clearance)
#   2 — escalation triggered (identity, risk-policy, or CLAUDE.md changed)
#   3 — usage error or missing dependencies

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
POLICY_FILE="$REPO_ROOT/risk-policy.json"

# ─── Colors ───
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
DIM='\033[0;90m'
BOLD='\033[1m'
NC='\033[0m'

# ─── Dependency check ───
check_deps() {
    if ! command -v jq &>/dev/null; then
        echo -e "${RED}Error: jq is required. Install with: apt install jq / brew install jq${NC}" >&2
        exit 3
    fi
    if [ ! -f "$POLICY_FILE" ]; then
        echo -e "${RED}Error: risk-policy.json not found at $POLICY_FILE${NC}" >&2
        exit 3
    fi
}

# ─── Tier ordering (for comparison) ───
tier_rank() {
    case "$1" in
        low)    echo 0 ;;
        medium) echo 1 ;;
        high)   echo 2 ;;
        *)      echo -1 ;;
    esac
}

tier_label() {
    case "$1" in
        low)    echo -e "${GREEN}low${NC}" ;;
        medium) echo -e "${YELLOW}medium${NC}" ;;
        high)   echo -e "${RED}high${NC}" ;;
    esac
}

# ─── Match a file against a glob pattern ───
# Supports: *.py, dir/*.py, dir/**, dir/**/*.py, !negation
matches_pattern() {
    local file="$1"
    local pattern="$2"

    # Strip leading ! for negation (handled by caller)
    pattern="${pattern#!}"

    # Convert glob to regex
    local regex="$pattern"

    # Escape dots
    regex="${regex//./\\.}"

    # ** matches any path depth (use placeholder to avoid * replacement)
    regex="${regex//\*\*/__DOUBLESTAR__}"

    # * matches within a single directory (not /)
    regex="${regex//\*/[^/]*}"

    # Now replace placeholder with proper regex
    regex="${regex//__DOUBLESTAR__/.*}"

    # Anchor to full string
    regex="^${regex}$"

    [[ "$file" =~ $regex ]]
}

# ─── Classify a single file into a risk tier ───
classify_file() {
    local file="$1"

    # Check tiers in order: high first (most restrictive wins)
    for tier in high medium low; do
        local paths
        paths=$(jq -r ".tiers.${tier}.paths[]" "$POLICY_FILE" 2>/dev/null)

        # First check negations (! prefix = exclude from this tier)
        local negated=false
        while IFS= read -r pattern; do
            [ -z "$pattern" ] && continue
            if [[ "$pattern" == !* ]] && matches_pattern "$file" "$pattern"; then
                negated=true
                break
            fi
        done <<< "$paths"

        if [ "$negated" = true ]; then
            continue
        fi

        # Then check positive matches
        while IFS= read -r pattern; do
            [ -z "$pattern" ] && continue
            [[ "$pattern" == !* ]] && continue
            if matches_pattern "$file" "$pattern"; then
                echo "$tier"
                return
            fi
        done <<< "$paths"
    done

    # Unclassified files default to medium (safer than low)
    echo "medium"
}

# ─── Check escalation rules ───
check_escalations() {
    local file="$1"
    local basename
    basename=$(basename "$file")

    case "$file" in
        risk-policy.json)
            echo "ESCALATE: risk-policy.json modified — requires manual review"
            return 0
            ;;
        CLAUDE.md)
            echo "ESCALATE: CLAUDE.md modified — requires manual review"
            return 0
            ;;
        config/identity.py)
            echo "ESCALATE: config/identity.py modified — STOP: this is her identity"
            return 0
            ;;
    esac

    return 1
}

# ─── List all tier mappings ───
cmd_list_tiers() {
    check_deps
    echo -e "${BOLD}Risk Policy — Path Tiers${NC}"
    echo ""
    for tier in high medium low; do
        local desc
        desc=$(jq -r ".tiers.${tier}.description" "$POLICY_FILE")
        echo -e "  $(tier_label $tier): $desc"
        local merge
        merge=$(jq -r ".tiers.${tier}.merge_requires | join(\", \")" "$POLICY_FILE")
        echo -e "  ${DIM}merge requires: ${merge}${NC}"
        jq -r ".tiers.${tier}.paths[]" "$POLICY_FILE" | while IFS= read -r p; do
            echo -e "    ${DIM}${p}${NC}"
        done
        echo ""
    done

    echo -e "${BOLD}Task Clearances${NC}"
    jq -r '.task_clearances | to_entries[] | "  \(.key): \(.value)"' "$POLICY_FILE"
}

# ─── Classify specific files ───
cmd_classify() {
    check_deps
    shift  # remove --classify
    for file in "$@"; do
        local tier
        tier=$(classify_file "$file")
        echo -e "  $(tier_label $tier)  $file"
    done
}

# ─── Main: scope check for a task ───
cmd_check() {
    check_deps

    local task_id="$1"
    local branch="${2:-HEAD}"

    # Get task clearance
    local clearance
    clearance=$(jq -r ".task_clearances.\"${task_id}\" // \"unknown\"" "$POLICY_FILE")

    if [ "$clearance" = "unknown" ]; then
        echo -e "${YELLOW}Warning: No clearance defined for ${task_id} in risk-policy.json${NC}"
        echo -e "${YELLOW}Defaulting to 'low' clearance (strictest). Add the task to task_clearances.${NC}"
        clearance="low"
    fi

    local clearance_rank
    clearance_rank=$(tier_rank "$clearance")

    # Get changed files
    local changed_files
    if [ "$branch" = "HEAD" ]; then
        changed_files=$(git diff --name-only main...HEAD 2>/dev/null || git diff --name-only origin/main...HEAD 2>/dev/null || echo "")
    else
        changed_files=$(git diff --name-only main..."$branch" 2>/dev/null || git diff --name-only origin/main..."$branch" 2>/dev/null || echo "")
    fi

    if [ -z "$changed_files" ]; then
        echo -e "${DIM}No changed files detected.${NC}"
        exit 0
    fi

    local file_count
    file_count=$(echo "$changed_files" | wc -l | tr -d ' ')

    echo -e "${BOLD}Scope Check: ${task_id}${NC}"
    echo -e "  Clearance: $(tier_label $clearance)"
    echo -e "  Branch:    ${branch}"
    echo -e "  Files:     ${file_count} changed"
    echo ""

    local violations=0
    local escalations=0
    local highest_tier="low"

    while IFS= read -r file; do
        [ -z "$file" ] && continue

        # Check escalation rules first
        local esc_msg
        if esc_msg=$(check_escalations "$file"); then
            echo -e "  ${RED}⚠ ${esc_msg}${NC}"
            echo -e "    ${DIM}${file}${NC}"
            ((escalations++))
            continue
        fi

        # Classify the file
        local tier
        tier=$(classify_file "$file")
        local tier_r
        tier_r=$(tier_rank "$tier")

        # Track highest tier touched
        if [ "$tier_r" -gt "$(tier_rank "$highest_tier")" ]; then
            highest_tier="$tier"
        fi

        # Check against clearance
        if [ "$tier_r" -gt "$clearance_rank" ]; then
            echo -e "  ${RED}✗ VIOLATION${NC}  $(tier_label $tier)  ${file}"
            echo -e "    ${DIM}Task ${task_id} has '${clearance}' clearance but this file is '${tier}'${NC}"
            ((violations++))
        else
            echo -e "  ${GREEN}✓${NC} $(tier_label $tier)  ${DIM}${file}${NC}"
        fi
    done <<< "$changed_files"

    echo ""

    # Summary
    if [ "$escalations" -gt 0 ]; then
        echo -e "${RED}${BOLD}⚠ ${escalations} ESCALATION(S) — requires operator review before merge${NC}"
        echo ""
        exit 2
    fi

    if [ "$violations" -gt 0 ]; then
        echo -e "${RED}${BOLD}✗ ${violations} SCOPE VIOLATION(S) — ${task_id} touched files above its clearance${NC}"
        echo -e "${DIM}  Either fix the branch or update task_clearances in risk-policy.json${NC}"
        echo ""
        exit 1
    fi

    # Report merge requirements for highest tier touched
    local merge_reqs
    merge_reqs=$(jq -r ".tiers.${highest_tier}.merge_requires | join(\", \")" "$POLICY_FILE")
    echo -e "${GREEN}${BOLD}✓ All ${file_count} files within ${task_id}'s '${clearance}' clearance${NC}"
    echo -e "  ${DIM}Highest tier touched: ${highest_tier} → merge requires: ${merge_reqs}${NC}"
    echo ""
    exit 0
}

# ─── Usage ───
usage() {
    echo "Usage:"
    echo "  $0 TASK-XXX [branch]     Check branch scope against task clearance"
    echo "  $0 --list-tiers          Show all path→tier mappings"
    echo "  $0 --classify FILE...    Classify specific files"
    echo ""
    echo "Examples:"
    echo "  $0 TASK-058                    # check current branch"
    echo "  $0 TASK-056 feat/dynamic-actions  # check specific branch"
    echo "  $0 --classify pipeline/cortex.py window/src/app/page.tsx"
}

# ─── Entry point ───
case "${1:-}" in
    --list-tiers)   cmd_list_tiers ;;
    --classify)     cmd_classify "$@" ;;
    --help|-h)      usage ;;
    TASK-*)         cmd_check "$@" ;;
    *)              usage; exit 3 ;;
esac
