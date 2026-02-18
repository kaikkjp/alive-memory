# TASK-059: OpenRouter Multi-LLM Integration

## Overview

Route all LLM calls through OpenRouter so different models can power different parts of her cognition. Test GPT-4o as her cortex, DeepSeek for sleep consolidation, Gemini for memory retrieval — or any combination. The cognitive architecture is model-agnostic; only the API routing changes.

**Why OpenRouter:** Single API key, unified billing, 200+ models, OpenAI-compatible format. No vendor lock-in.

---

## Current State

All LLM calls use the Anthropic Python SDK directly:

```python
# Current pattern (everywhere)
import anthropic
client = anthropic.Anthropic()
response = client.messages.create(
    model="claude-sonnet-4-5-20250929",
    messages=[...],
    system="...",
    max_tokens=...,
)
```

**Call sites to migrate:**

| Call Site | File | Purpose | Current Model |
|---|---|---|---|
| **Cortex** | `pipeline/cortex.py` | Main cycle LLM call — the big one | Claude Sonnet |
| **Sleep consolidation** | `sleep.py` | Reflection generation, memory consolidation | Claude Sonnet |
| **Sleep salience** | `sleep.py` | Day moment extraction | Claude Sonnet |
| **Cold search embeddings** | `pipeline/embed.py` | Vector embeddings for memory search | (may use a different endpoint) |
| **Content summarization** | `pipeline/sensorium.py` or `enrich.py` | Summarize ingested content | Claude Sonnet (if applicable) |

**Audit first:** `grep -rn "anthropic\." --include="*.py"` to find all SDK usage. There may be additional call sites.

---

## Architecture

### New Module: `llm/`

```
llm/
  __init__.py           — Exports: complete(), embed()
  client.py             — OpenRouter HTTP client
  config.py             — Model config per call site (from DB or env)
  format.py             — Anthropic message format → OpenRouter format translation
  cost.py               — Cost tracking per call (model, tokens, latency)
```

### `llm/client.py` — Core Client

```python
import httpx

OPENROUTER_BASE = "https://openrouter.ai/api/v1"

async def complete(
    messages: list[dict],
    system: str | None = None,
    call_site: str = "default",      # "cortex", "sleep", "sleep_salience", "embed"
    max_tokens: int = 4096,
    temperature: float = 0.7,
    response_format: dict | None = None,
) -> dict:
    """
    Single entry point for all LLM completions.
    
    1. Resolve model for this call_site (DB → env → default)
    2. Format messages (Anthropic → OpenAI format if needed)
    3. Call OpenRouter
    4. Log cost (model, tokens in/out, latency, call_site)
    5. Return parsed response in Anthropic-compatible shape
    """
```

### `llm/config.py` — Model Resolution

Model selection per call site. Three layers of config (highest priority first):

1. **DB** (`self_parameters` table from TASK-055) — `llm.cortex.model`, `llm.sleep.model`, etc.
2. **Environment variables** — `LLM_CORTEX_MODEL`, `LLM_SLEEP_MODEL`, etc.
3. **Defaults** — hardcoded fallbacks

```python
# Environment variable config
OPENROUTER_API_KEY=sk-or-v1-xxx              # Required

# Per call-site model (all optional, defaults to LLM_DEFAULT_MODEL)
LLM_DEFAULT_MODEL=anthropic/claude-sonnet-4-5-20250929
LLM_CORTEX_MODEL=anthropic/claude-sonnet-4-5-20250929
LLM_SLEEP_MODEL=openai/gpt-4o
LLM_SLEEP_SALIENCE_MODEL=openai/gpt-4o-mini
LLM_EMBED_MODEL=openai/text-embedding-3-small
LLM_CONTENT_MODEL=google/gemini-2.0-flash
```

After TASK-055, these map to `self_parameters`:

| Parameter Key | Category | Default | Bounds |
|---|---|---|---|
| `llm.default.model` | llm | `anthropic/claude-sonnet-4-5-20250929` | string |
| `llm.cortex.model` | llm | (uses default) | string |
| `llm.sleep.model` | llm | (uses default) | string |
| `llm.sleep_salience.model` | llm | (uses default) | string |
| `llm.embed.model` | llm | `openai/text-embedding-3-small` | string |
| `llm.content.model` | llm | (uses default) | string |
| `llm.cortex.temperature` | llm | 0.7 | 0.0–2.0 |
| `llm.cortex.max_tokens` | llm | 4096 | 256–16384 |
| `llm.sleep.temperature` | llm | 0.6 | 0.0–2.0 |

### `llm/format.py` — Message Format Translation

OpenRouter uses OpenAI format. The Shopkeeper's prompts are in Anthropic format. Translate:

```python
def anthropic_to_openai(messages: list, system: str | None) -> list:
    """
    Anthropic format:
      system="You are..."
      messages=[{"role": "user", "content": "..."}]
    
    OpenAI/OpenRouter format:
      messages=[
        {"role": "system", "content": "You are..."},
        {"role": "user", "content": "..."}
      ]
    """
    result = []
    if system:
        result.append({"role": "system", "content": system})
    for msg in messages:
        # Handle Anthropic's content blocks (text, image, etc.)
        if isinstance(msg["content"], list):
            # Convert content blocks to OpenAI format
            result.append({
                "role": msg["role"],
                "content": convert_content_blocks(msg["content"])
            })
        else:
            result.append(msg)
    return result

def openai_to_anthropic(response: dict) -> dict:
    """
    Convert OpenRouter response back to Anthropic-compatible shape
    so existing parsing code (cortex, sleep) doesn't break.
    
    OpenRouter returns:
      {"choices": [{"message": {"content": "..."}}], "usage": {...}}
    
    Convert to:
      {"content": [{"type": "text", "text": "..."}], "usage": {...}}
    """
```

**Critical:** `prompt_assembler.py` output doesn't change. The translation happens inside `llm/client.py`. All existing code that parses cortex output continues to work unchanged.

### `llm/cost.py` — Cost Tracking

Extend the existing `llm_costs` table to include model name:

```sql
-- Existing table (check current schema, extend if needed)
ALTER TABLE llm_costs ADD COLUMN model TEXT;
ALTER TABLE llm_costs ADD COLUMN call_site TEXT;
ALTER TABLE llm_costs ADD COLUMN latency_ms INTEGER;
```

Log every call:

```python
async def log_cost(
    call_site: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    latency_ms: int,
    cost_usd: float | None = None,   # OpenRouter returns this in headers
):
```

OpenRouter returns cost info in response headers (`x-ratelimit-*`) and in the response body (`usage`). Some models also return `cost` in the response. Capture whatever's available.

---

## Migration Steps

### Phase 1: Create `llm/` module

Build `client.py`, `config.py`, `format.py`, `cost.py` as a standalone module. Write tests against OpenRouter directly (with a real API key in CI env).

### Phase 2: Migrate Cortex (the big one)

Replace the Anthropic SDK call in `pipeline/cortex.py`:

```python
# Before
import anthropic
client = anthropic.Anthropic()
response = client.messages.create(
    model="claude-sonnet-4-5-20250929",
    messages=messages,
    system=system_prompt,
    max_tokens=4096,
    temperature=0.7,
)
text = response.content[0].text

# After
from llm import complete
response = await complete(
    messages=messages,
    system=system_prompt,
    call_site="cortex",
    max_tokens=4096,
    temperature=0.7,
)
text = response["content"][0]["text"]  # Same shape, format.py handles translation
```

**Test:** Run 10 cycles with the same model (Claude Sonnet via OpenRouter). Output should be behaviorally identical to direct Anthropic SDK. Compare cycle logs.

### Phase 3: Migrate Sleep

Replace SDK calls in `sleep.py` (consolidation + salience). These are less critical — sleep runs once per sleep cycle, not per waking cycle.

### Phase 4: Migrate remaining call sites

Embed, content summarization, any others found in audit.

### Phase 5: Remove Anthropic SDK dependency

Once all calls route through `llm/`, remove `anthropic` from `requirements.txt`. The only dependency is `httpx` (already used) or `requests`.

---

## Fallback Strategy

If OpenRouter is down or returns errors:

```python
# Config
LLM_FALLBACK_ENABLED=true
LLM_FALLBACK_PROVIDER=anthropic     # Direct Anthropic as fallback
ANTHROPIC_API_KEY=sk-ant-xxx         # Only needed if fallback enabled

# Logic in client.py
async def complete(...):
    try:
        return await _call_openrouter(...)
    except (httpx.ConnectError, httpx.TimeoutException, OpenRouterError) as e:
        if config.fallback_enabled:
            log.warning(f"OpenRouter failed ({e}), falling back to {config.fallback_provider}")
            return await _call_fallback(...)
        raise
```

Fallback is optional. If `LLM_FALLBACK_ENABLED` is false (default), OpenRouter errors propagate normally and the cycle fails gracefully (existing error handling in heartbeat.py).

---

## Dashboard Integration

Add to the existing Costs panel or create a new LLM panel:

- **Model usage breakdown:** Which model is used for each call site
- **Cost per model:** Daily cost split by model
- **Latency comparison:** Average latency per model per call site
- **Current config:** Show which model is assigned to each call site, with ability to change (operator only)

This is low priority — can be a follow-up task. The cost logging in the DB is the important part.

---

## Testing

### Unit Tests

```python
# test_format.py
- anthropic_to_openai: system prompt becomes first message
- anthropic_to_openai: content blocks convert correctly
- anthropic_to_openai: handles string content (passthrough)
- openai_to_anthropic: choices[0].message.content → content[0].text
- openai_to_anthropic: usage fields map correctly

# test_config.py
- DB param overrides env var
- env var overrides default
- missing call_site falls back to default model
- invalid model string logs warning, uses default

# test_cost.py
- log_cost writes to DB with all fields
- cost_usd extracted from OpenRouter response when available
```

### Integration Tests

```python
# test_client.py (requires OPENROUTER_API_KEY in env)
- complete() returns valid response for Claude Sonnet
- complete() returns valid response for GPT-4o
- complete() returns valid response for DeepSeek
- complete() handles rate limit (429) with retry
- complete() handles timeout gracefully
- complete() logs cost after each call

# test_pipeline.py
- Run 10 cycles via simulate.py with OpenRouter routing
- Compare output shape to direct Anthropic output
- Verify cost logging includes model name
```

### Regression

- Run 50 cycles with `LLM_CORTEX_MODEL=anthropic/claude-sonnet-4-5-20250929` via OpenRouter
- Compare behavioral output (journal entries, drive changes, action distribution) to baseline
- Should be statistically identical (same model, just different routing)

---

## Scope

### Files to create
- `llm/__init__.py`
- `llm/client.py`
- `llm/config.py`
- `llm/format.py`
- `llm/cost.py`
- `tests/test_llm_format.py`
- `tests/test_llm_config.py`
- `tests/test_llm_cost.py`
- `migrations/0XX_llm_model_tracking.py` (extend llm_costs table)

### Files to modify
- `pipeline/cortex.py` (replace Anthropic SDK call)
- `sleep.py` (replace Anthropic SDK calls)
- `pipeline/embed.py` (replace embedding call if applicable)
- Any other files found in `grep -rn "anthropic\." --include="*.py"` audit
- `requirements.txt` (add httpx if not present, eventually remove anthropic)
- `db/parameters.py` (add llm.* parameter seeds if TASK-055 is merged)

### Files NOT to touch
- `pipeline/prompt_assembler.py` (prompt format stays the same)
- `pipeline/validator.py`
- `pipeline/basal_ganglia.py`
- `heartbeat.py` (unless needed for config loading)
- `window/*` (frontend unchanged)

---

## Definition of Done

1. All LLM calls route through `llm/client.py` → OpenRouter
2. Model configurable per call site (cortex, sleep, embed, etc.)
3. Config reads from DB (self_parameters) → env → defaults
4. Cost logging includes model name, call site, and latency
5. Anthropic SDK no longer called directly anywhere
6. Existing output parsing (cortex, sleep) unchanged — format translation is transparent
7. 50-cycle regression test passes with identical behavioral output
8. Fallback to direct Anthropic works (if enabled)
9. Can hot-swap models by changing a DB parameter — no restart needed
