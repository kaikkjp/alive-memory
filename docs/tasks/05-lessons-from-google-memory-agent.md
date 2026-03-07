# Task 05: Lessons from Google's Always-On Memory Agent

## Source
Comparison review of [GoogleCloudPlatform/generative-ai/gemini/agents/always-on-memory-agent](https://github.com/GoogleCloudPlatform/generative-ai/tree/main/gemini/agents/always-on-memory-agent)

## Tasks

### 1. Multimodal Intake (High Priority)
**What Google does:** Ingests 27 file types (images, audio, video, PDFs) via Gemini's native multimodal capabilities. Files dropped in `./inbox/` are auto-processed.

**What alive-sdk lacks:** Thalamus only handles text events.

**Implementation idea:**
- Add a `MultimodalPerceiver` that routes non-text inputs through an LLM vision/audio call
- Output is a text `Perception` that feeds into the existing thalamus pipeline
- Support: images, PDFs, audio transcripts, video frame descriptions
- LLM extracts: description, entities, sentiment, suggested salience
- Thalamus treats the LLM output as a regular perception — no changes to downstream

**Files to touch:** `alive_memory/intake/thalamus.py`, new `alive_memory/intake/multimodal.py`

---

### 2. Debug Dashboard (Medium Priority)
**What Google does:** Streamlit dashboard showing memories, with upload/query/clear. Decoupled from agent via HTTP API.

**What alive-sdk lacks:** Server exists (`alive_memory/server/`) but no visualization.

**Implementation idea:**
- Streamlit app consuming the existing FastAPI server
- Pages: mood/drives gauges, memory timeline, identity traits over time, recent reflections, dream log
- Read-only by default, optional intake/consolidate triggers
- Useful for development, demos, and debugging sleep cycles

**Files to touch:** New `alive_memory/dashboard/` directory, `app.py`

---

### 3. Agent Framework Adapters (Medium Priority)
**What Google does:** Built on ADK with multi-agent orchestration (orchestrator routes to ingest/consolidate/query sub-agents).

**What alive-sdk lacks:** Only has a LangChain adapter. No ADK, LangGraph, or tool-use adapters.

**Implementation idea:**
- Expose `intake()`, `recall()`, `consolidate()` as tool definitions
- ADK adapter: tools for Google ADK agents
- LangGraph adapter: nodes for LangGraph workflows
- Generic tool-use adapter: JSON schema tool definitions any framework can consume

**Files to touch:** `alive_memory/adapters/adk.py`, `alive_memory/adapters/langgraph.py`

---

### 4. Quickstart Mode (Medium Priority)
**What Google does:** 5 pip deps, one file, `python agent.py` runs everything. Zero config.

**What alive-sdk has:** Rich config system but higher setup friction.

**Implementation idea:**
- `AliveMemory.quickstart(name="my-agent")` class method
- Defaults: local embeddings, no LLM (raw journal), SQLite in `~/.alive/{name}/`, auto sleep every 30min
- Single-function API: `memory.remember(text)` / `memory.ask(query)`
- Hides sleep cycle, meta-controller, identity system — they still run but with safe defaults
- Upgrade path: pass a config to unlock full features

**Files to touch:** `alive_memory/__init__.py`, new convenience methods

---

### 5. File Watcher Adapter (Low Priority)
**What Google does:** `watchdog` monitors `./inbox/`, auto-ingests new files.

**What alive-sdk lacks:** Intake requires programmatic `intake()` calls.

**Implementation idea:**
- Optional `FileWatcher` class using `watchdog`
- Monitors a directory, calls `intake()` on new files
- Pairs with multimodal intake (task 1) for non-text files
- Config: watch path, polling interval, file type filters

**Files to touch:** New `alive_memory/intake/file_watcher.py`, optional dep in `pyproject.toml`

---

## Anti-Patterns to Avoid (from Google's Implementation)

These are things Google got wrong that alive-sdk should NOT adopt:

1. **No auth on HTTP API** — alive-sdk server should always require auth tokens
2. **Sync SQLite in async code** — alive-sdk already uses aiosqlite, keep it
3. **LIMIT N on recall** — never silently cap memory access; degrade gracefully
4. **No tests** — maintain test coverage, add tests for every new feature
5. **Hardcoded LLM provider** — keep the Protocol-based abstraction
6. **unsafe_allow_html** — never render user content as raw HTML
