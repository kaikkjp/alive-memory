# 069-C: Web Browse Executor

## Goal
Implement `WebBrowseExecutor` — when she decides to browse the web, this executor calls OpenRouter with a cheap model + web_search tool and returns real search results. Results become her immediate experience this cycle (journal entry, drive update). This is the first "real" action in the system.

## Context
Read these files first:
- `ARCHITECTURE.md` — system overview
- `tasks/TASK-069-real-body-actions.md` — full spec (Phase 2: Web Browse)
- `body/executor.py` — executor interface (from 069-A, must be merged first)
- `llm/client.py` — OpenRouter client (from TASK-059)
- `pipeline/output.py` — where action results get processed
- `pipeline/action_registry.py` — action capability definitions

## Dependencies
- **069-A must be merged** — you need the `BodyExecutor` base class and registry

## Files to Create

### `body/web.py`
```python
class WebBrowseExecutor(BodyExecutor):
    action_name = "browse_web"
    requires_energy = 0.15
    cooldown_seconds = 180
    requires_online = True
    
    async def execute(self, intention, context) -> ActionResult:
        query = intention.parameters["query"]
        reason = intention.parameters.get("reason", "general interest")
        
        # Call OpenRouter with cheap model + web_search tool
        response = await llm_client.call(
            model="google/gemini-2.0-flash",
            call_site="body.browse_web",
            messages=[{
                "role": "user",
                "content": f"Search the web for: {query}\n\nContext: {reason}\n\n"
                           f"Return a concise summary (max 500 words) with key facts and source URLs."
            }],
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            max_tokens=1000,
        )
        
        summary = extract_text(response)
        sources = extract_urls(response)
        
        return ActionResult(
            success=True,
            action_name="browse_web",
            data={"query": query, "summary": summary, "sources": sources}
        )
```

Key implementation details:
- Use `google/gemini-2.0-flash` (cheapest model with web search, ~$0.005/search)
- Parse response to extract text content and source URLs
- Handle errors gracefully (network failure, API error → ActionResult with success=False)
- Register executor in body/__init__.py or executor.py

### `migrations/069c_browse_history.sql`
```sql
CREATE TABLE IF NOT EXISTS browse_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    query TEXT NOT NULL,
    summary TEXT NOT NULL,
    sources TEXT,
    cycle_id INTEGER,
    cost_usd REAL,
    model TEXT
);
```

### `tests/test_web_browse.py`
- Mock OpenRouter response → executor returns structured BrowseResult
- Network error → ActionResult(success=False)
- Energy check: can_execute fails when energy too low
- Cooldown check: can_execute fails during cooldown
- Browse result saved to browse_history table
- Integration: register executor, resolve by name, execute

## Files to Modify

### `pipeline/action_registry.py`
Add entry:
```python
"browse_web": ActionCapability(
    name="browse_web",
    energy_cost=0.15,
    cooldown_seconds=180,
    prerequisites=[],
    category="external",
    enabled=True,
),
```

### `pipeline/output.py`
Add handler for browse_web ActionResult:
```python
if result.action_name == "browse_web" and result.success:
    # Log to browse_history
    await db.log_browse(result.data["query"], result.data["summary"], result.data["sources"], ...)
    # Write journal entry
    await db.write_journal(f"I looked up: {result.data['query']}\n\n{result.data['summary']}")
    # Update drives: curiosity satisfied
    drives.diversive_curiosity = max(0, drives.diversive_curiosity - 0.2)
    # Energy cost already deducted by basal_ganglia
```

### `llm/client.py`
Verify web_search tool support. The OpenRouter call needs to include:
```python
tools=[{"type": "web_search_20250305", "name": "web_search"}]
```
If the client doesn't support this tool type yet, add it. The response may contain tool_use blocks that need to be parsed to extract the final text.

### `db/analytics.py`
Add `service` column to cost logging if not present:
```python
# Log browse cost separately from cortex costs
await log_cost(model="google/gemini-2.0-flash", service="browse", ...)
```

## Files NOT to Touch
- `pipeline/cortex.py` (prompt update is 069-F)
- `pipeline/body.py` (already delegates via 069-A)
- `heartbeat_server.py`
- `body/channels.py`, `body/bus.py` (069-B scope)
- `sleep.py`
- `window/*`

## Done Signal
- `WebBrowseExecutor.execute()` makes real OpenRouter API call with web_search tool
- Returns structured result with summary + source URLs
- browse_history table populated
- Journal entry written from browse result
- Curiosity drive decreases after browse
- Cost logged with service="browse"
- All tests pass (unit with mocks + one integration test with real API if key available)
