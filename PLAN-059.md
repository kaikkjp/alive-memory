# PLAN-059: OpenRouter Multi-LLM Integration

## Phase 0: Documentation & Discovery Summary

### OpenRouter API (verified from docs)
- **Base URL:** `https://openrouter.ai/api/v1/chat/completions`
- **Auth:** `Authorization: Bearer <OPENROUTER_API_KEY>` header
- **Format:** OpenAI-compatible (system message in messages array, not separate param)
- **Model IDs:** `provider/model-name` format (e.g., `anthropic/claude-sonnet-4-5-20250929`)
- **Response cost:** `usage.cost` field returns exact USD cost per request
- **Cost breakdown:** `usage.cost_details.upstream_inference_prompt_cost` + `upstream_inference_completions_cost`
- **Error codes:** 400/401/402/403/408/429/502/503

### Current Codebase State (verified)
- **3 API call sites in `pipeline/cortex.py`:**
  - `cortex_call()` (line ~443) — main cycle, model=CORTEX_MODEL, max_tokens=1500
  - `cortex_call_maintenance()` (line ~514) — sleep journal, max_tokens=600
  - `cortex_call_reflect()` (line ~640) — reflection, model=REFLECT_MODEL, max_tokens=800
- **`sleep.py`** delegates to `cortex_call_reflect()` — no direct API calls
- **`pipeline/embed.py`** uses raw HTTP to OpenAI embeddings (aiohttp), separate from Anthropic SDK
- **All 3 cortex calls:** use `anthropic.AsyncAnthropic` singleton, `response.content[0].text` parsing, JSON extraction
- **No temperature set** in any call (uses API default)
- **Timeouts:** client=30s, asyncio.wait_for=60s
- **Cost tracking:** via `llm_logger.py` → `db.insert_llm_call_log()` (provider, model, purpose, tokens, cost_usd, cycle_id)
- **`httpx` already imported** in cortex.py (line 9)
- **TASK-055 DONE:** `self_parameters` table exists BUT uses `REAL` type — **cannot store string model names**
- **Next migration number:** 024

### Critical Constraint: self_parameters is REAL-only
The `self_parameters` table stores `value REAL NOT NULL`. The TASK-059 spec assumes it can store model name strings. **It cannot.**

**Decision:** Model config uses env vars + hardcoded defaults only (layers 2 and 3 from the spec). DB-backed model selection (layer 1) is deferred to a follow-up that adds a `string_parameters` table or extends the schema. This is the simplest path that delivers 90% of the value.

---

## Phase 1: Create `llm/` Module — Format Translation + Config

**What to implement:**
1. Create `llm/__init__.py` — exports `complete()` function
2. Create `llm/format.py` — bidirectional format translation:
   - `anthropic_to_openai(messages, system)` → prepends system as first message, converts content blocks
   - `openai_to_anthropic(response)` → converts `choices[0].message.content` → `{"content": [{"type": "text", "text": "..."}], "usage": {...}}`
3. Create `llm/config.py` — model resolution from env vars:
   - `OPENROUTER_API_KEY` (required)
   - `LLM_DEFAULT_MODEL` (default: `anthropic/claude-sonnet-4-5-20250929`)
   - `LLM_CORTEX_MODEL`, `LLM_SLEEP_MODEL`, `LLM_REFLECT_MODEL`, `LLM_EMBED_MODEL` (all optional, fall back to default)
   - `resolve_model(call_site)` function
   - `LLM_FALLBACK_ENABLED` (default: false), `ANTHROPIC_API_KEY` used only for fallback
4. Create `tests/test_llm_format.py`:
   - Test system prompt becomes first message
   - Test content block conversion (list → list, string → string passthrough)
   - Test response conversion (OpenAI shape → Anthropic shape)
   - Test usage field mapping (including `cost` from OpenRouter)
5. Create `tests/test_llm_config.py`:
   - Test env var resolution per call site
   - Test fallback to default model
   - Test missing OPENROUTER_API_KEY raises clear error

**Files created:** `llm/__init__.py`, `llm/format.py`, `llm/config.py`, `tests/test_llm_format.py`, `tests/test_llm_config.py`

**Documentation references:**
- OpenRouter request format: messages array with system role (OpenAI-compatible)
- OpenRouter response format: `choices[0].message.content`, `usage.cost`, `usage.prompt_tokens`, `usage.completion_tokens`
- Current Anthropic format in cortex.py: `system=` param (separate), `response.content[0].text`

**Anti-pattern guards:**
- Do NOT import or use the OpenAI Python SDK — use raw httpx (matches embed.py pattern, avoids new dependency)
- Do NOT try to store model strings in self_parameters REAL column
- Do NOT change prompt_assembler.py — translation is internal to llm/

**Verification:**
```bash
gtimeout 60 python3 -m pytest tests/test_llm_format.py tests/test_llm_config.py -v --tb=short 2>&1 || true
```

---

## Phase 2: Create `llm/client.py` + Cost Tracking

**What to implement:**
1. Create `llm/client.py`:
   - `async def complete(messages, system, call_site, max_tokens, temperature, timeout)` → main entry point
   - Uses `httpx.AsyncClient` for HTTP calls to `https://openrouter.ai/api/v1/chat/completions`
   - Internally calls `format.anthropic_to_openai()` before sending, `format.openai_to_anthropic()` on response
   - Returns Anthropic-compatible dict: `{"content": [{"type": "text", "text": "..."}], "usage": {...}}`
   - Retry on 429 (rate limit) with exponential backoff (1 retry, 2s delay)
   - Timeout via `httpx.Timeout` (connect=10s, read=60s)
   - Headers: `Authorization: Bearer {key}`, `Content-Type: application/json`, `HTTP-Referer: https://github.com/TriMinhPham/shopkeeper`, `X-Title: The Shopkeeper`
2. Create `llm/cost.py`:
   - `async def log_cost(call_site, model, input_tokens, output_tokens, latency_ms, cost_usd, cycle_id)`
   - Writes to existing `llm_call_log` table via `db.insert_llm_call_log()` (reuse existing schema)
   - Add `call_site` and `latency_ms` columns via migration
   - Use OpenRouter's `usage.cost` when available (exact cost), fall back to `llm_logger.estimate_cost()`
3. Create migration `migrations/024_llm_call_log_extend.sql`:
   - `ALTER TABLE llm_call_log ADD COLUMN call_site TEXT;`
   - `ALTER TABLE llm_call_log ADD COLUMN latency_ms INTEGER;`
4. Update `llm/__init__.py` to export `complete`
5. Create `tests/test_llm_cost.py`:
   - Test log_cost writes to DB
   - Test cost_usd from OpenRouter response is used when present

**Files created:** `llm/client.py`, `llm/cost.py`, `migrations/024_llm_call_log_extend.sql`, `tests/test_llm_cost.py`
**Files modified:** `llm/__init__.py`

**Documentation references:**
- OpenRouter chat completions endpoint: `POST https://openrouter.ai/api/v1/chat/completions`
- Response `usage.cost` field for exact USD cost
- Existing `llm_logger.py` pattern for cost estimation fallback
- Existing `db.insert_llm_call_log()` signature in `db/analytics.py` (lines 96-113)

**Anti-pattern guards:**
- Do NOT use the `openai` or `anthropic` SDKs in the new client — raw httpx only
- Do NOT change the existing `llm_call_log` schema destructively — only ADD columns
- Do NOT change `llm_logger.py` — `llm/cost.py` is the new path; old logger kept for backward compat

**Verification:**
```bash
gtimeout 60 python3 -m pytest tests/test_llm_cost.py -v --tb=short 2>&1 || true
```

---

## Phase 3: Migrate Cortex (the big one)

**What to implement:**
1. Modify `pipeline/cortex.py`:
   - Replace `import anthropic` with `from llm import complete as llm_complete`
   - Remove `_client` singleton and `_get_client()` function
   - Keep `httpx` import (used for timeout exception catching)
   - In `cortex_call()` (line ~443): replace `client.messages.create(...)` with `await llm_complete(messages=..., system=..., call_site="cortex", max_tokens=1500)`
   - In `cortex_call_maintenance()` (line ~514): replace with `await llm_complete(messages=..., system=..., call_site="cortex_maintenance", max_tokens=max_tokens)`
   - In `cortex_call_reflect()` (line ~640): replace with `await llm_complete(messages=..., system=..., call_site="reflect", max_tokens=max_tokens)`
   - Update response parsing: `response.content[0].text` → `response["content"][0]["text"]` (dict access instead of attribute access)
   - Keep circuit breaker, daily cap, timeout logic unchanged
   - Keep `llm_logger.log_llm_call()` calls — they still work, AND `llm/cost.py` adds extra tracking
   - Update error handling: catch `httpx.TimeoutException`, `httpx.ConnectError`, generic `Exception` instead of `anthropic.APIError`

2. Keep `CORTEX_MODEL` and `REFLECT_MODEL` constants for now — `llm/config.py` resolves the actual model, but these serve as documentation

**Files modified:** `pipeline/cortex.py`

**Documentation references:**
- Current cortex_call pattern: lines 443-451 (API call), 481-489 (response parse)
- Current cortex_call_maintenance: lines 514-522 (API call), 559-569 (response parse)
- Current cortex_call_reflect: lines 640-648 (API call), 666-675 (response parse)
- `llm/client.py` complete() returns `{"content": [{"type": "text", "text": "..."}], "usage": {...}}`

**Anti-pattern guards:**
- Do NOT change `prompt_assembler.py` — prompt format stays Anthropic-style, translation is in `llm/format.py`
- Do NOT change the response JSON parsing logic (json.loads, regex strip) — only change how the raw text is extracted
- Do NOT remove the circuit breaker or daily cap — those are heartbeat-level safety
- Do NOT change function signatures of cortex_call, cortex_call_maintenance, cortex_call_reflect — callers must not know about the routing change

**Verification:**
```bash
# Unit tests for cortex
gtimeout 60 python3 -m pytest tests/test_cortex.py -v --tb=short 2>&1 || true

# Full suite to catch regressions
gtimeout 120 python3 -m pytest tests/ --tb=short -q 2>&1 || true
```

---

## Phase 4: Migrate Embeddings + Cleanup

**What to implement:**
1. **Optionally migrate `pipeline/embed.py`:**
   - embed.py already uses raw HTTP (aiohttp) to OpenAI embeddings
   - OpenRouter supports embeddings at the same endpoint pattern
   - If embedding via OpenRouter is desired: add `async def embed(text, call_site)` to `llm/client.py`
   - If keeping separate OpenAI embeddings: leave embed.py unchanged (it works fine)
   - **Recommendation:** Leave embed.py as-is for now — embeddings are a different concern, and OpenRouter embedding pricing may differ. Flag for follow-up.

2. **Update `requirements.txt`:**
   - Add `httpx>=0.27.0,<1.0.0` (explicit dependency, currently transitive via anthropic)
   - Keep `anthropic` for now if fallback is desired; mark with comment `# fallback only — remove after migration proven`

3. **Update `llm_logger.py` `COST_PER_1K` dict:**
   - Add entries for OpenRouter model IDs (prefixed with provider/): `anthropic/claude-sonnet-4-5-20250929`, `openai/gpt-4o`, etc.
   - OR: when OpenRouter response includes `usage.cost`, skip local cost estimation entirely (prefer this)

4. **Add `.env` template entries:**
   - Document `OPENROUTER_API_KEY` in README or .env.example

**Files modified:** `requirements.txt`, `llm_logger.py` (optional), `pipeline/embed.py` (optional)

**Anti-pattern guards:**
- Do NOT remove `anthropic` from requirements.txt yet — keep as fallback until migration is proven
- Do NOT change embed.py unless explicitly asked — it's a separate API with different pricing

**Verification:**
```bash
# Full test suite
gtimeout 120 python3 -m pytest tests/ --tb=short -q 2>&1 || true

# Verify no direct anthropic SDK usage in cortex path
grep -n "anthropic\." pipeline/cortex.py  # should show nothing except maybe comments
grep -n "from llm import" pipeline/cortex.py  # should show the new import
```

---

## Phase 5: Integration Test + Regression

**What to implement:**
1. Run 10 cycles with `OPENROUTER_API_KEY` set and `LLM_CORTEX_MODEL=anthropic/claude-sonnet-4-5-20250929`
2. Verify:
   - Cycle completes without error
   - Response format is correct (JSON parsed, CortexOutput created)
   - Cost logged to `llm_call_log` with provider=`openrouter`, model=`anthropic/claude-sonnet-4-5-20250929`
   - `call_site` and `latency_ms` columns populated
3. Test model switching:
   - Set `LLM_CORTEX_MODEL=openai/gpt-4o` and run 3 cycles
   - Verify different model name in cost log
4. Run full test suite one final time

**Verification:**
```bash
# 10-cycle smoke test
python3 simulate.py --cycles 10

# Check cost log
sqlite3 data/shopkeeper.db "SELECT provider, model, purpose, call_site, latency_ms, cost_usd FROM llm_call_log ORDER BY created_at DESC LIMIT 20;"

# Full suite
gtimeout 120 python3 -m pytest tests/ --tb=short -q 2>&1 || true
```

---

## Summary: File Change Map

### New files (9):
- `llm/__init__.py`
- `llm/client.py`
- `llm/config.py`
- `llm/format.py`
- `llm/cost.py`
- `tests/test_llm_format.py`
- `tests/test_llm_config.py`
- `tests/test_llm_cost.py`
- `migrations/024_llm_call_log_extend.sql`

### Modified files (2-3):
- `pipeline/cortex.py` (main migration)
- `requirements.txt` (add httpx explicit dep)
- `llm_logger.py` (optional: add OpenRouter model pricing)

### NOT touched:
- `pipeline/prompt_assembler.py`
- `pipeline/validator.py`
- `pipeline/basal_ganglia.py`
- `heartbeat.py`
- `window/*`
- `db.py`
- `sleep.py` (delegates to cortex, no changes needed)

### Deferred to follow-up:
- DB-backed model config (needs string parameter support in self_parameters)
- embed.py migration to OpenRouter
- Dashboard LLM panel
- Fallback provider implementation (optional, low priority)
