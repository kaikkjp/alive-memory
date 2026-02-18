# TASK-065: Prompt Token Budget

## Problem

TASK-060 through TASK-063 all inject new content into the LLM prompt. Without a budget, each addition creeps the token count up until we hit truncation or degraded output quality. Currently there is no enforcement — sections grow unchecked.

## Solution

Enforce token caps on each section of the LLM prompt. A new `prompt/budget.py` module measures each section before the LLM call, truncates any that exceed their cap, and logs all trims.

## Design

1. **Define named prompt sections** — system, memory, drives, scene, self_context, conversation_history (extensible as 060-063 land)
2. **Per-section max token allocation** in external config (`prompt/budget_config.json`)
3. **Total budget** = model context window − reserved output tokens
4. **Before each LLM call**, `budget.py` measures each section, truncates/summarizes any that exceed their cap:
   - Conversation history: oldest-first truncation
   - Memory: least-relevant-first truncation
   - Other sections: configurable strategy
5. **Emit warning log** if any section hits its cap — visibility into what's getting cut

## Token counting

Must be fast. Options (decide during implementation):
- `tiktoken` for exact counts (Claude-compatible tokenizer)
- Character-estimate heuristic (~3.5 chars/token) as fallback

**Never use an LLM call for token counting.**

## Config format

```json
{
  "model_context_window": 200000,
  "reserved_output_tokens": 4096,
  "sections": {
    "system": { "max_tokens": 2000, "truncation": "none" },
    "memory": { "max_tokens": 3000, "truncation": "least_relevant_first" },
    "drives": { "max_tokens": 500, "truncation": "none" },
    "scene": { "max_tokens": 1000, "truncation": "oldest_first" },
    "self_context": { "max_tokens": 800, "truncation": "oldest_first" },
    "conversation_history": { "max_tokens": 8000, "truncation": "oldest_first" }
  }
}
```

Config must be tunable without code changes.

## Rules

- Token counting must be fast — no LLM calls
- Truncation strategy per section type (configurable)
- Never silently drop content — always log what was trimmed
- Budget config must be tunable without code changes
- Sections not yet implemented (e.g. self_context before 060 lands) are simply absent — budget system handles missing sections gracefully

## Scope

**Files you may touch:**
- `prompt/budget.py` (new — token counting + section enforcement)
- `pipeline/cortex.py` (post-059 — integrate budget checks before LLM call)
- `prompt/budget_config.json` or similar (new — per-section limits)

**Files you may NOT touch:**
- `pipeline/basal_ganglia.py`
- `simulate.py`

## Depends on

- TASK-064 merge (sleep phases cleaned up)
- TASK-059 merge (prompt structure finalized)

## Blocks

- TASK-060 (self-context injection — needs budget to respect)
- TASK-061 (organ awareness — adds another prompt section)

## Tests

- Unit: section over budget → truncated to limit
- Unit: total under budget → nothing touched
- Unit: missing section in config → graceful default
- Integration: full prompt assembly stays within model context window
- Log output shows trim events when triggered

## Definition of done

- Every prompt section has a token budget
- Total prompt size is bounded
- Truncation is per-section with configurable strategy
- All trims are logged
- Budget config is external and tunable without code changes
