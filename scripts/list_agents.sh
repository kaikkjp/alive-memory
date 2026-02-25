#!/usr/bin/env bash
# TASK-095 Phase 4: List all running agent containers.
#
# Usage: ./scripts/list_agents.sh [--all]
#
# Without --all: shows only running agents.
# With --all: shows all agents (including stopped).

set -euo pipefail

SHOW_ALL=false
if [[ "${1:-}" == "--all" ]]; then
    SHOW_ALL=true
fi

if [[ "$SHOW_ALL" == true ]]; then
    echo "All agent containers (running + stopped):"
    docker ps -a --filter "name=alive-agent-" \
        --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}\t{{.CreatedAt}}"
else
    echo "Running agent containers:"
    docker ps --filter "name=alive-agent-" \
        --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}\t{{.RunningFor}}"
fi
