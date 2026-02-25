#!/bin/bash
# list_agents.sh — Show all ALIVE agent containers and their status

echo "ALIVE Agents"
echo "============"
echo ""

FOUND=0
while IFS= read -r line; do
    [ -z "$line" ] && continue
    FOUND=1
    
    NAME=$(echo "$line" | awk '{print $1}')
    STATUS=$(echo "$line" | awk '{print $2}')
    AGENT_ID=${NAME#alive-agent-}
    
    PORT=$(docker port "$NAME" 8080 2>/dev/null | head -1 | cut -d: -f2 || echo "?")
    
    HEALTH="?"
    if [ "$STATUS" = "running" ] && [ "$PORT" != "?" ]; then
        if curl -s --max-time 2 "http://127.0.0.1:${PORT}/api/health" >/dev/null 2>&1; then
            HEALTH="✅ healthy"
        else
            HEALTH="⚠️  not responding"
        fi
    fi
    
    printf "  %-20s  port:%-6s  status:%-10s  %s\n" "$AGENT_ID" "$PORT" "$STATUS" "$HEALTH"
    
done < <(docker ps -a --filter "name=alive-agent-" --format "{{.Names}} {{.State}}")

if [ "$FOUND" -eq 0 ]; then
    echo "  No agents found."
fi

echo ""
