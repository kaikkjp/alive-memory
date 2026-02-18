# TASK-065: Prompt token budget strategy

## Problem

Cortex prompt is gaining new sections:
- Self-context block (TASK-060)
- Cognitive state block (TASK-061)
- Fitness function block (TASK-063)

Each competes for context window space with memories, perceptions, and identity. Without a budget system, prompt size grows unbounded and critical sections get crowded out.

## Solution

Add a token budget system in `prompt_assembler.py`. Each section gets a max allocation. Priority order determines what gets trimmed first when total exceeds budget. Perceptions and identity are never trimmed.

## Priority order (highest to lowest)

1. **Identity** — never trimmed
2. **Perceptions** — never trimmed (current sensory input)
3. **Memories** — trimmed last (recall context)
4. **Self-context notes** — trimmed before memories
5. **Cognitive state** — trimmed before self-context
6. **Fitness function** — trimmed first

## Budget allocation (configurable)

| Section | Max tokens | Trimmable |
|---------|-----------|-----------|
| Identity | 800 | No |
| Perceptions | 1500 | No |
| Memories | 3000 | Yes (last) |
| Self-context | 500 | Yes |
| Cognitive state | 200 | Yes |
| Fitness function | 300 | Yes |
| **Total budget** | **6300** | — |

Allocations stored in config (not self_parameters — operator-controlled, not character-controlled).

## Trimming strategy

When total assembled prompt exceeds budget:
1. Trim lowest-priority sections first
2. Within a section, trim oldest/least-relevant items first
3. Log what was trimmed and why
4. Never trim below minimum thresholds (e.g., cognitive state always gets at least the "All organs active" line)

## Scope

**Files you may touch:**
- `pipeline/prompt_assembler.py` (add budget allocation and priority trimming)
- `config/` (add `prompt_budget.py` or extend existing config)

**Files you may NOT touch:**
- `pipeline/cortex.py`
- `pipeline/basal_ganglia.py`

## Tests

- Unit: prompt stays under total budget with all sections populated
- Unit: low-priority sections trimmed before high-priority
- Unit: identity and perceptions never trimmed even under pressure
- Unit: trimming is deterministic and logged

## Definition of done

- Every prompt section has a token budget
- Total prompt size is bounded
- Priority trimming is deterministic and logged
