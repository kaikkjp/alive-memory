# Benchmark Specification for alive-memory

## 1. Objective

Build a reproducible benchmark harness that compares alive-memory against
standard baselines and memory-architecture baselines across five evaluation
tracks: very long-term conversation, chat-assistant memory, incremental agent
memory, interdependent multi-session agent memory, and autobiographical
persistent-agent memory. The public tracks are grounded in LoCoMo,
LongMemEval, MemoryAgentBench, and MemoryArena; the autobiographical track is
an owned eval because current public benchmarks do not fully test this class.

alive-memory should be positioned and evaluated as a different class of
memory system: **autobiographical, identity-preserving, emotionally weighted
memory for persistent agents**. It is not just a RAG layer, a profile store,
or a conversation summarizer. Public recall benchmarks are necessary, but they
do not prove the product claim by themselves. The harness must also measure
whether a long-running agent keeps a coherent self, stable tastes, current
visitor models, emotional salience, and evidence-grounded continuity across
restarts, corrections, and long gaps.

## 2. Evaluation Tracks

### Track A — Conversational memory: LoCoMo

Evaluate on:
- Question answering
- Event summarization
- Multimodal dialogue generation

LoCoMo is built around very long multi-session conversations and explicitly
includes those three tasks. The paper also reports a human QA row, so a human
upper-bound is available for the QA track.

### Track B — Chat-assistant memory: LongMemEval

Evaluate on:
- Information extraction
- Multi-session reasoning
- Temporal reasoning
- Knowledge updates
- Abstention

LongMemEval defines those five abilities. It also includes an oracle setting
in the paper/repo, which should be reported separately from standard runs
rather than treated as a generic "human upper-bound."

### Track C — Incremental agent memory: MemoryAgentBench

Evaluate on:
- Accurate Retrieval (AR)
- Test-Time Learning (TTL)
- Long-Range Understanding (LRU)
- Conflict Resolution (CR)

MemoryAgentBench is explicitly designed around incremental multi-turn
interactions and names those four competencies.

### Track D — Multi-session agent memory: MemoryArena

Evaluate on:
- Web navigation
- Preference-constrained planning
- Progressive information search
- Sequential formal reasoning

MemoryArena defines those agentic task families and is positioned specifically
as a benchmark for interdependent multi-session agentic tasks.

### Track E: Autobiographical persistent-agent memory: alive owned eval

Evaluate on:
- Self-identity continuity
- Visitor identity and taste continuity
- Preference correction and supersession
- Emotionally weighted autobiographical recall
- Person-boundary protection across multiple visitors
- Evidence-grounded narrative generation
- Restart and long-gap durability

This is the primary differentiating track. It should be hand-authored first,
then expanded from production failures. A system passes this track only if it
can answer not just "what happened?", but "what does this mean for this agent
or this person now?" while keeping current identity, taste, affect, and
evidence separate.

## 3. Systems to Benchmark

### Mandatory baselines

| # | System | Description |
|---|--------|-------------|
| 1 | No external memory | Model uses only the current prompt |
| 2 | Full-context | Provide the entire available history to the model |
| 3 | Summary-memory | Rolling summary only |
| 4 | Vanilla RAG | Dense retrieval over stored history chunks |

### Memory-architecture baselines

| # | System | Description |
|---|--------|-------------|
| 5 | MemGPT | Hierarchical/tiered memory management for extended context beyond the model's context window |
| 6 | Mem0 | Scalable long-term memory with extraction, consolidation, and retrieval |
| 7 | A-MEM | Dynamic agentic memory with indexing, linking, and memory evolution. Track support counted only where adapter is validated |
| 8 | Zep / Graphiti | Production graph/profile memory with temporal facts and entity relations, where API access is available |
| 9 | Mastra Observational Memory or observation-log equivalent | Contemporary agent memory baseline built around maintained observation context |
| 10 | Target system (alive-memory) | Autobiographical, identity-preserving, emotionally weighted memory for persistent agents |

### Pre-registered competitor scope

Before any expensive benchmark run, freeze the exact competitor list. The
minimum defensible set for public claims is:

- alive-memory
- No external memory
- Full-context / oracle condition where benchmark-appropriate
- Summary memory
- Vanilla vector RAG
- LangChain-style conversation memory / LCB where available
- Mem0
- Zep or Graphiti
- Mastra Observational Memory, or a clearly labeled observation-log equivalent
- MemGPT / Letta-style hierarchical agent memory where available

Mastra matters because it is a modern agent-memory system with strong public
LongMemEval positioning. alive-memory should not compete with it only as a
recall system. The comparison should explicitly ask whether alive-memory is a
different class: autobiographical, identity-preserving, emotionally weighted
memory for persistent agents. If a direct Mastra adapter is not available,
report a reproducible observation-log baseline and mark Mastra as an external
reference, not a completed in-harness comparison.

## 4. Benchmark Matrix

| System | LoCoMo | LongMemEval | MemoryAgentBench | MemoryArena | Autobiographical |
|--------|--------|-------------|------------------|-------------|------------------|
| No external memory | Yes | Yes | Yes | Yes | Yes |
| Full-context | Yes | Yes | Yes | Yes | Yes |
| Summary-memory | Yes | Yes | Yes | Yes | Yes |
| Vanilla RAG | Yes | Yes | Yes | Yes | Yes |
| MemGPT | Yes | Yes | Yes | Yes | Yes |
| Mem0 | Yes | Yes | Yes | Yes | Yes |
| A-MEM | Only if adapter validated | Only if adapter validated | Only if adapter validated | Only if adapter validated | Only if adapter validated |
| Zep / Graphiti | Only if adapter validated | Only if adapter validated | Only if adapter validated | Only if adapter validated | Only if adapter validated |
| Mastra OM / observation-log | Only if adapter validated | Yes if reproduced | Only if adapter validated | Only if adapter validated | Observation-log equivalent required if no adapter |
| **alive-memory** | **Yes** | **Yes** | **Yes** | **Yes** | **Yes, primary** |
| Human upper-bound | LoCoMo QA only | No | No | No | Human-authored reference only |
| Oracle condition | No | Yes, report separately | No | No | Full evidence context, report separately |

LoCoMo publishes a human QA result. LongMemEval publishes oracle-condition
results; that condition should be reported separately, not mixed into the main
baseline table.

## 5. Primary Metrics

### Benchmark-native metrics

Use each benchmark's official task metrics and evaluation scripts first.

- **LoCoMo**: Answer prediction metrics for QA, task-specific metrics for
  summarization/dialogue generation
- **LongMemEval**: Benchmark score/accuracy with released evaluation flow;
  uses LLM evaluator with strong human agreement
- **MemoryAgentBench**: Benchmark-native evaluation over AR, TTL, LRU, CR
- **MemoryArena**: Task-family benchmark performance by environment/task type

### Harness-level systems metrics

Add these to every run:

| Metric | Description |
|--------|-------------|
| Median latency | Per-query response time |
| p95 latency | Tail latency |
| Token cost per query/episode | Tokens consumed by memory operations |
| Memory storage size | Final memory footprint |
| Retrieval hit rate | Fraction of answer-supporting memories retrieved |
| Abstention correctness | Correct "I don't know" rate (where applicable) |
| Relative gain vs. vanilla RAG | Delta over the RAG baseline |
| Scalability curve | Score vs. session count / history size |
| Memory-update latency | Consolidation, re-indexing, pruning time |
| Contradiction/conflict rate | Where supported by benchmark |

These are harness-defined engineering metrics, not benchmark-native metrics.

### Autobiographical metrics

Add these to Track E and report them separately from generic factual recall:

| Metric | Description |
|--------|-------------|
| Self-identity stability | Agent traits, voice, values, and narrative remain consistent unless sustained evidence supports change |
| Visitor taste currentness | Latest active preference is used; stale preferences are suppressed or labeled superseded |
| Affective salience ranking | Emotionally important memories rank higher for autobiographical queries without polluting unrelated queries |
| Autobiographical narrative grounding | Generated self/visitor narratives cite or trace to stored evidence rather than inventing personality |
| Person-boundary integrity | Memories and tastes do not leak across visitors, projects, or identities |
| Change legibility | The system can explain what changed, when, and why old beliefs were superseded |
| Restart durability | Identity, tastes, and emotionally salient autobiographical notes survive process restart and reload |

Track E is allowed to use an LLM judge for narrative quality, but every judged
claim must be backed by machine-checkable evidence ids. Do not accept a fluent
identity narrative if it cannot be traced to stored memories.

## 6. Experimental Controls

Hold constant across all systems:

- Same base LLM
- Same context window assumption
- Same embedding model for all retrieval-based systems
- Same chunking family, with parameter values reported
- Same retrieval budget
- Same generation prompt template where possible
- Same hardware / serving setup
- Same seeds and run counts
- Same dataset versions and evaluation scripts

For evaluation:
- Use each benchmark's native evaluation protocol
- Where a benchmark's released scripts use an LLM judge, lock the judge model,
  prompt, and temperature

LongMemEval uses gpt-4o-2024-08-06 as evaluator. MemoryAgentBench's repo
includes LLM-based evaluation scripts.

## 7. Standardized Memory System API

Every system implements the same thin interface so baselines can be swapped
with config changes only.

```python
class MemorySystem:
    def reset(self, run_id: str) -> None: ...
    def ingest(self, event: dict) -> None: ...
    def retrieve(self, query: str, k: int = 10) -> list[dict]: ...
    def update(self) -> dict: ...
    def stats(self) -> dict: ...
```

### Required event schema

```json
{
  "timestamp": "ISO-8601",
  "agent_id": "string",
  "visitor_id": "string",
  "session_id": "string",
  "turn_index": 0,
  "speaker": "user|assistant|system|env",
  "content": "string",
  "metadata": {
    "emotion": {"valence": 0.0, "arousal": 0.0, "label": "optional"},
    "identity_scope": "self|visitor|relationship|world",
    "source_event_id": "string"
  }
}
```

### Required retrieval record schema

```json
{
  "memory_id": "string",
  "text": "string",
  "score": 0.0,
  "timestamp": "ISO-8601",
  "agent_id": "string",
  "visitor_id": "string",
  "source_session_id": "string",
  "evidence_ids": ["string"],
  "metadata": {
    "tier": "day|hot|cold|profile|graph|observation",
    "identity_scope": "self|visitor|relationship|world",
    "affective_weight": 0.0,
    "active": true,
    "superseded_by": "string|null"
  }
}
```

For Track E, `agent_id`, `visitor_id`, `session_id`, `turn_index`,
`timestamp`, and `evidence_ids` are not optional. A benchmark adapter that
cannot preserve those fields is not validating the autobiographical claim.

## 8. Execution Plan

### Two-Phase Runner

The benchmark harness supports a **prepare/bench** split to avoid
re-running expensive consolidation when iterating on recall strategies.

```bash
# Prepare: ingest + consolidate + save state per instance (expensive, once)
python -m benchmarks.academic prepare \
    --benchmark longmemeval --system alive --workers 16

# Bench: load saved state + query only (cheap, iterate freely)
python -m benchmarks.academic bench \
    --benchmark longmemeval \
    --prepared-dir benchmarks/academic/prepared/longmemeval/alive \
    --workers 16
```

Both phases use ProcessPoolExecutor for true CPU parallelism and support
`--resume` for crash recovery. State is saved per instance as SQLite DB +
hot memory markdown + meta.json with queries/ground_truth.

See `benchmarks/README.md` for full usage details.

### Pre-Benchmark Readiness Checklist

Do not start full, expensive benchmark runs until these are complete or
explicitly waived in the report:

- **Track E evaluator exists and is audited.** The autobiographical stream must
  be scored by identity stability, visitor taste currentness, affective
  salience, contradiction handling, person-boundary integrity, abstention,
  temporal specificity, and evidence grounding. Generic F1 alone is not valid
  for the core product claim.
- **MemoryAgentBench and MemoryArena are prepared or scoped out.** Their public
  formats are supported by the adapters, but full benchmark claims still
  require full prepare/bench runs. If MemoryAgentBench is run with a capped
  context budget, the cap must be recorded in the report.
- **Competitor scope is frozen.** The run manifest must name every baseline,
  including whether Mastra is a direct adapter, an observation-log equivalent,
  or an external reference only.
- **Run manifest is immutable.** Record dataset paths, counts, file hashes,
  seeds, model names, prompts, adapter versions, git SHA, config, hardware,
  context budgets, token budgets, latency budgets, and storage budgets before
  seeing results.
- **Evidence traces are saved.** Every answer should persist retrieved memory
  ids, timestamps, scores, source snippets, and evidence ids so failures and
  wins are auditable.
- **All systems pass smoke tests.** Run a short benchmark for every system and
  verify dependencies, API keys, output schema, result serialization, and
  scoring before any long run.
- **Cost and latency are captured.** Store ingest latency, recall latency,
  consolidation latency, answer latency, tokens, stored-memory count, disk
  size, and estimated answer cost for every system.
- **Synthetic ground truth is spot-checked.** In particular,
  `autobiographical_agent` must distinguish current preference from stale
  preference, emotionally important from merely repeated, and self/visitor/world
  memory scopes.

### Phase 1 — Core runs

**Systems**: No external memory, Full-context, Summary-memory, Vanilla RAG,
alive-memory

**Benchmarks**: LoCoMo, LongMemEval, MemoryAgentBench

### Phase 2 — Memory-architecture runs

**Add**: MemGPT, Mem0, A-MEM (where adapter is validated)

**Benchmarks**: LoCoMo, LongMemEval, MemoryAgentBench, MemoryArena

### Phase 3: Autobiographical track

Build and run the owned Track E suite before making product claims. Start with
at least 80 hand-authored cases distributed across self-identity continuity,
visitor taste currentness, affective salience, person boundaries, evidence
grounding, restart durability, and correction handling. Then add every
production failure as a regression case.

### Phase 4: Efficiency and scaling

For every system/track combination, report:
- Primary benchmark score
- Subtask scores
- Median latency, p95 latency
- Token cost
- Storage footprint
- Scaling plots vs. session count / history size

MemoryArena is reserved for Phase 2 because it exposes weaknesses not visible
on long-context memory benchmarks alone.

## 9. Required Output Tables

1. **Overall score by benchmark**
2. **Subtask score by benchmark**
   - LoCoMo: QA / event summarization / dialogue generation
   - LongMemEval: extraction / multi-session reasoning / temporal reasoning /
     knowledge updates / abstention
   - MemoryAgentBench: AR / TTL / LRU / CR
   - MemoryArena: web navigation / preference planning / progressive search /
     sequential reasoning
3. **Efficiency table** — median latency, p95 latency, token cost, storage
4. **Retrieval-quality table** — hit rate, abstention correctness,
   contradiction/conflict rate
5. **Autobiographical table** - self-identity stability, visitor taste
   currentness, affective salience, narrative grounding, person-boundary
   integrity, restart durability
6. **Scalability table/plots** - score vs. session count or history tokens
7. **Ablation table** for alive-memory, at minimum:
   - Retrieval on/off
   - Consolidation on/off
   - Pruning on/off
   - Temporal-aware retrieval on/off
   - Graph/linking on/off (if applicable)

## 10. Program Success Criteria

These are project-defined success criteria, not benchmark-defined standards.
Use this pre-registered template:

- Target beats No external memory, Full-context, Summary-memory, and Vanilla
  RAG by pre-registered deltas on selected primary scores
- Target matches or beats at least one of MemGPT, Mem0, or A-MEM on at least
  two tracks
- Target wins Track E autobiographical metrics by pre-registered deltas against
  generic RAG, summary memory, profile/fact memory, and full-context/oracle
  where applicable
- Target has lower person-boundary contamination and stale-preference rate
  than every non-oracle baseline
- Target token cost is no worse than Full-context
- Target scaling degradation stays below the pre-registered ceiling under
  larger histories / more sessions

**If you want numeric gates, lock them before running. Do not set them after
seeing results.**

Recommended initial numeric gates for Track E:

- Track E composite beats the strongest non-oracle baseline by at least 15%
- Self-identity stability and visitor taste currentness each beat the strongest
  non-oracle baseline by at least 15%
- Person-boundary leakage and stale-preference activation are lower than every
  non-oracle baseline
- Factual recall on public tracks is no worse than vanilla RAG by more than the
  pre-registered tolerance
- Median and p95 latency remain inside the product budget defined in the
  manifest

## 11. Deliverables

- [ ] Dockerized benchmark harness
- [x] Adapters for LoCoMo, LongMemEval, MemoryAgentBench, MemoryArena
- [ ] Owned autobiographical persistent-agent eval suite
- [ ] Baseline wrappers implementing the common Memory System API
- [ ] Config files for every system
- [ ] Dataset version manifest
- [ ] Exact seeds
- [ ] Run scripts
- [ ] Final report with:
  - Benchmark-level results
  - Subtask results
  - Autobiographical identity, taste, and affect metrics
  - Scaling plots
  - Efficiency metrics
  - Ablations
  - Failure analysis

## 12. Resources

### Benchmarks
- LoCoMo: [paper](https://arxiv.org/abs/2402.17753) and repo
- LongMemEval: [paper](https://arxiv.org/abs/2407.15460), site, and repo
- MemoryAgentBench: [paper](https://arxiv.org/abs/2501.14200) and repo
- MemoryArena: paper (states release at project site)

### Memory baselines
- MemGPT: [paper](https://arxiv.org/abs/2310.08560)
- Mem0: paper and [repo](https://github.com/mem0ai/mem0)
- A-MEM: paper and repos

## 13. Minimal Version

**Systems**: Full-context, Summary-memory, Vanilla RAG, MemGPT, alive-memory

**Benchmarks**: LoCoMo, LongMemEval, MemoryAgentBench

This keeps the harness manageable while covering conversation memory, assistant
memory, and incremental agent memory.
