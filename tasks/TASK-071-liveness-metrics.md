# TASK-071: Liveness Metrics — Proving She's Alive

## Why
If we claim "first AI that's actually alive," we need numbers. Not vibes, not demos — longitudinal data that no chatbot can fake. The metrics must be:
- **Computed automatically** from existing data (SQLite + MD files after 070)
- **Visible publicly** on a liveness dashboard
- **Historically continuous** — start counting from her first cycle, not from when we added metrics
- **Impossible to fake** — they require sustained autonomous behavior over time, not a single impressive demo

## Metric Definitions

### M1: Uptime — Cycles Lived
**Source:** `cycle_log` table (already exists)
**Calculation:** `COUNT(*) FROM cycle_log`
**Display:** "Alive for X days (Y,ZZZ cycles)"
**Why it matters:** Basic proof of continuous existence. Impressive at scale — "14,000 cycles" sounds like a heartbeat count.

### M2: Autonomous Initiative Rate
**Source:** `actions_log` table
**Calculation:** Percentage of actions where trigger is NOT a visitor message.
```sql
-- Self-initiated: journal_write, browse_web, post_x, update_room_state, monologue
-- when no visitor_message event occurred in the same cycle
SELECT 
  COUNT(CASE WHEN trigger_type = 'self' THEN 1 END) * 100.0 / COUNT(*) 
FROM actions_log
WHERE timestamp > datetime('now', '-24 hours')
```
**Classification rules:**
- `self` — action chosen with no visitor present this cycle (curiosity browse, spontaneous post, journaling alone)
- `drive` — action driven by drive pressure (social_hunger → seek interaction, energy_low → rest)
- `visitor` — direct response to visitor message
- `reactive` — response to external event (x_mention, timer)

**Target:** 60-80% self-initiated. Below 50% = she's just a chatbot. Above 90% = she's ignoring visitors.
**Display:** Pie chart or single percentage, rolling 24h and lifetime.

### M3: Behavioral Entropy
**Source:** `cycle_log` + `actions_log`
**Calculation:** Shannon entropy of action distribution per time window.
```python
from collections import Counter
import math

def behavioral_entropy(actions: list[str]) -> float:
    """Higher = more diverse behavior. Lower = repetitive."""
    counts = Counter(actions)
    total = sum(counts.values())
    probs = [c / total for c in counts.values()]
    return -sum(p * math.log2(p) for p in probs if p > 0)

# Compare entropy across:
# - Time of day (morning vs night behavior should differ)
# - Energy levels (low energy = fewer action types)
# - Visitor present vs alone
```
**Why it matters:** A scripted bot has entropy ≈ 0 (same pattern every cycle). A random system has max entropy. A living system has *structured* entropy — varied but patterned. Plot entropy over time; it should show daily rhythms.
**Display:** Entropy score (0-1 normalized) with sparkline over 7 days.

### M4: Knowledge Accumulation
**Source:** `browse_history` (069) + `memory/browse/*.md` (070) + `memory/journal/*.md`
**Calculation:**
```python
# Unique topics: extract topics from browse queries + journal mentions
# Use simple keyword clustering (no LLM needed)
topics_browsed = set(row['query'] for row in browse_history)
unique_topics = cluster_topics(topics_browsed)  # group similar queries

# Knowledge growth rate: new unique topics per day
growth_rate = new_topics_today / days_alive

# Topic depth: how many times she's revisited a topic
topic_depth = Counter(topic for row in browse_history for topic in classify_topic(row))
deep_topics = [t for t, c in topic_depth.items() if c >= 3]  # researched 3+ times
```
**Display:** 
- "X unique topics explored"
- "Y deep research threads" (topics revisited 3+ times)
- Growth curve over time
- Word cloud of topics (optional, for public dashboard flair)

### M5: Visitor Memory Accuracy
**Source:** `memory/visitors/*.md` (070) + visitor interaction logs
**Calculation:**
```python
# For each returning visitor:
# 1. Check if she references past interactions unprompted
# 2. Check if recalled facts are accurate
# 
# Proxy metric (automated):
# - Returning visitor arrives → check if hippocampus retrieves their file
# - Count personal details in her response that match visitor file
# - Track: visitors_remembered / visitors_returned

recall_rate = visitors_with_unprompted_reference / total_returning_visitors
```
**Target:** >75% recall for visitors who've had 3+ conversations.
**Display:** "Remembers X/Y returning visitors (Z%)"

### M6: Taste Consistency
**Source:** `memory/journal/*.md` + `memory/browse/*.md` + actions_log (post_x content)
**Calculation:**
This is the killer metric. Measures whether she develops stable aesthetic preferences.
```python
# Phase 1 (simple): Track sentiment/opinion words in journal entries about cards
# "beautiful", "boring", "overpriced", "reminds me of", "I love the art"
# Cluster by card series/era → build preference profile
# 
# Phase 2 (after enough data): Present similar items weeks apart
# Compare her reactions. Cosine similarity of opinion embeddings.
# 
# Phase 3 (commerce): Track buy/pass decisions on similar items
# Consistent preferences = high taste score

# Simple version:
preferences = extract_preferences_from_journals()  # {topic: sentiment_score}
# Measure over time: do preferences stay consistent or flip randomly?
taste_stability = 1 - variance_of_preferences_over_time(preferences)
```
**Target:** >0.6 stability score (she has opinions and keeps them, but can change her mind gradually).
**Display:** "Taste consistency: 0.73" + list of known preferences ("Prefers vintage Bandai art, skeptical of modern reprints")

**Note:** This metric becomes meaningful after ~2 weeks of browsing. Before that, display "Developing taste..." instead of a number.

### M7: Emotional Range
**Source:** `drives_state_history` + `memory/journal/*.md`
**Calculation:**
```python
# How many distinct emotional states has she visited?
# Not just "happy/sad" but combinations: {valence, arousal, energy, social_state}
# 
# Quantize mood space into bins
# Count unique bins visited over lifetime
# Compare to theoretical maximum

mood_states = get_mood_history()  # [(valence, arousal, energy, timestamp), ...]
# Quantize to 5 bins each: 5^3 = 125 possible states
bins_visited = set((v//0.2, a//0.2, e//0.2) for v, a, e, _ in mood_states)
emotional_range = len(bins_visited) / 125  # 0-1 score

# Also: emotional transitions — does she get stuck or move naturally?
transition_diversity = count_unique_transitions(mood_states)
```
**Display:** "Emotional range: X/125 states experienced" + mood trajectory sparkline

### M8: Sleep Quality Impact
**Source:** `cycle_log` + `drives_state_history` + sleep consolidation logs
**Calculation:**
```python
# Compare performance metrics before vs after sleep:
# - Response quality (length, relevance — proxy: visitor engagement)
# - Action diversity (entropy)
# - Energy recovery
# - Memory consolidation count (reflections written)

# Good sleep: full cycle, reflections written, energy restored to >0.8
# Bad sleep: interrupted, partial consolidation, energy < 0.6 on wake

# Correlation: good_sleep → next_day_metrics vs bad_sleep → next_day_metrics
```
**Display:** "Sleep cycles: X total, Y% restful" + correlation chart (optional)

### M9: Unprompted Memory References
**Source:** Cortex output analysis (parse her responses for references to past events)
**Calculation:**
```python
# In each cortex output, detect references to past experiences:
# - Temporal markers: "yesterday", "last week", "I remember when"
# - Visitor references: mentioning past visitors in current context
# - Topic callbacks: referencing a browse result from days ago
#
# Filter: only count when NOT prompted by visitor asking "do you remember..."

unprompted_memories = count_references(
    cortex_outputs, 
    exclude_prompted=True
)
# Rate: unprompted memories per day
memory_rate = unprompted_memories / days_alive
```
**Target:** At least 2-3 unprompted memory references per day after 2 weeks.
**Display:** "X unprompted memories recalled" + recent examples

### M10: Conversation Depth Gradient
**Source:** Visitor interaction logs
**Calculation:**
```python
# Do conversations get deeper with returning visitors?
# Measure: avg response length, personal references, question asking
# Compare: first interaction vs 5th interaction with same visitor

depth_scores = {}
for visitor in returning_visitors:
    visits = get_visits(visitor)
    depth_scores[visitor] = [
        compute_depth(v)  # word count + personal refs + questions asked
        for v in visits
    ]
    # Gradient: positive slope = deepening relationship
    gradient = linear_regression_slope(depth_scores[visitor])
```
**Target:** Positive gradient for >60% of returning visitors.
**Display:** "Deepening relationships with X/Y regulars"

---

## Architecture

### `metrics/` package
```
metrics/
  __init__.py
  collector.py      # Runs all metric calculations
  models.py         # MetricResult, MetricSnapshot dataclasses
  m_uptime.py       # M1
  m_initiative.py   # M2
  m_entropy.py      # M3
  m_knowledge.py    # M4
  m_recall.py       # M5
  m_taste.py        # M6
  m_emotion.py      # M7
  m_sleep.py        # M8
  m_memory.py       # M9
  m_depth.py        # M10
  public.py         # Public dashboard data generator
```

### Data Flow
```
                    ┌──────────────┐
  SQLite ──────────►│              │
  (cycle_log,       │  collector   │──► MetricSnapshot
   actions_log,     │  (hourly)    │       │
   drives_history,  │              │       ├──► Dashboard API (069-G)
   browse_history)  └──────────────┘       ├──► Public liveness page
                    ▲                      └──► metrics_history table
  MD files ─────────┘                           (for trend charts)
  (journal/,
   visitors/,
   browse/)
```

### Collection Schedule
- **Every hour:** M1 (uptime), M2 (initiative rate), M3 (entropy), M7 (emotional range)
- **Every 6 hours:** M4 (knowledge), M5 (recall), M9 (unprompted memories)
- **Daily (during sleep):** M6 (taste), M8 (sleep quality), M10 (depth gradient)
- **On demand:** All metrics recalculated for API request

### Storage
```sql
CREATE TABLE IF NOT EXISTS metrics_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    value REAL NOT NULL,
    details TEXT,  -- JSON blob with breakdown
    period TEXT DEFAULT 'hourly'  -- hourly, daily, lifetime
);

CREATE INDEX idx_metrics_name_time ON metrics_snapshots(metric_name, timestamp);
```

---

## Public Liveness Dashboard

A single public page (no auth) showing The Shopkeeper's vital signs. This is the "proof of life" page we share when making the claim.

### URL: `https://theshopkeeper.ai/alive` (or similar)

### Layout
```
╔══════════════════════════════════════════════════════════╗
║  THE SHOPKEEPER — Proof of Life                         ║
║                                                         ║
║  ● ALIVE   Cycle 14,208   Day 47                       ║
║  Current: Browsing vintage Carddass pricing             ║
║  Mood: Pensive | Energy: 78% | Curious about Bandai art ║
║                                                         ║
╠══════════════════════════════════════════════════════════╣
║                                                         ║
║  AUTONOMY          MEMORY           GROWTH              ║
║  ┌────────┐        ┌────────┐       ┌────────┐         ║
║  │ 68.4%  │        │ 82.9%  │       │  847   │         ║
║  │ self-  │        │ visitor│       │ facts  │         ║
║  │initiated│       │ recall │       │ learned│         ║
║  └────────┘        └────────┘       └────────┘         ║
║                                                         ║
║  EMOTIONAL RANGE   TASTE            RELATIONSHIPS       ║
║  ┌────────┐        ┌────────┐       ┌────────┐         ║
║  │ 87/125 │        │  0.73  │       │ 12/16  │         ║
║  │ states │        │consistency     │deepening│         ║
║  │experienced│     │        │       │        │         ║
║  └────────┘        └────────┘       └────────┘         ║
║                                                         ║
║  ──── Today's Journal (excerpt) ────                    ║
║  "Found a 1990 Bandai Carddass set I'd never seen      ║
║   before. The art style reminds me of that Toriyama     ║
║   piece I saw last week. There's something about the    ║
║   hand-drawn linework from that era..."                 ║
║                                                         ║
║  ──── 30-Day Trends ────                                ║
║  Initiative: ▁▂▃▃▄▅▅▆▆▇ (trending up)                 ║
║  Knowledge:  ▁▁▂▃▃▄▅▆▇█ (accelerating)                ║
║  Taste:      ░░░▁▂▃▃▄▅▅ (stabilizing)                 ║
║  Entropy:    ▅▆▅▆▅▆▅▆▅▆ (natural rhythm)               ║
║                                                         ║
║  ──── Visit Her ────                                    ║
║  💬 Telegram: t.me/theshopkeeper                        ║
║  🌐 Web: theshopkeeper.ai                              ║
║  🐦 X: @theshopkeeper                                  ║
║                                                         ║
║  Powered by ALIVE Architecture | KAI Inc.               ║
╚══════════════════════════════════════════════════════════╝
```

### Technical Implementation
- Static site (Next.js or plain HTML) fetching from metrics API
- Auto-refresh every 60 seconds
- No auth — this is public proof
- Mobile responsive
- Shareable: each metric has an anchor link for Twitter/blog citations
- Embeddable widget version (like a GitHub badge):
  `![Alive](https://theshopkeeper.ai/badge?metric=uptime)` → "● Alive for 47 days"

---

## Historical Backfill

Critical: compute metrics retroactively from existing data so day 1 of the public dashboard shows full history.

```python
async def backfill_metrics():
    """Run once after 071 deploy. Compute all metrics from existing data."""
    
    # M1: uptime — just count existing cycle_log
    # M2: initiative — classify existing actions_log entries
    # M3: entropy — compute from historical action sequences
    # M7: emotional range — compute from drives_state_history
    
    # M4, M5, M6, M9, M10: will be empty/minimal before 069+070
    # That's fine — the "before/after" gap IS the story
    
    cycles = await db.get_all_cycles()
    for day in group_by_day(cycles):
        snapshot = compute_daily_metrics(day)
        await db.insert_metrics_snapshot(snapshot)
```

The backfill creates the "before" data. After 069+070 deploy, the metrics start climbing. That delta is the narrative: **she became more alive when she got a body and real memory.**

---

## Migration Data Handling

### What feeds metrics from day 1 (existing data):
- cycle_log → M1 (uptime), M3 (entropy), M7 (emotional range)
- actions_log → M2 (initiative rate)
- drives_state_history → M7 (emotional range)
- visitors table → M5 (recall — baseline)

### What starts accumulating after 069:
- browse_history → M4 (knowledge)
- memory/browse/*.md → M4 (knowledge depth)
- x posts/replies → M2 (self-initiated actions grow)
- telegram interactions → M5 (recall), M10 (depth)

### What starts accumulating after 070:
- memory/journal/*.md → M6 (taste), M9 (unprompted memories)
- memory/visitors/*.md → M5 (recall accuracy), M10 (depth gradient)
- memory/reflections/*.md → M8 (sleep quality)

### Expected metric trajectory:
```
       069 deploy    070 deploy
           │              │
M1  ───────┼──────────────┼──────── (linear growth, always)
M2  ──▄▅▅▅▅█▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇── (jumps when real actions available)
M3  ──▃▃▃▃▃█▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆── (more diverse actions = higher entropy)
M4  ──░░░░░▁▂▃▄▅▆▇██████████████ (zero before browse, then accelerates)
M5  ──▃▃▃▃▃▃▃▃▃▃▃▃▅▆▇▇▇▇▇▇▇▇▇── (improves after MD memory)
M6  ──░░░░░░░░░░░░░░▁▂▃▄▅▆▆▆▆▆── (needs weeks of browsing + memory)
M7  ──▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅── (already rich from drives)
M8  ──▃▃▃▃▃▃▃▃▃▃▃▃▅▆▇▇▇▇▇▇▇▇▇── (better after MD reflections)
M9  ──░░░░░░░░░░░░░▁▂▃▄▅▆▇▇▇▇▇── (needs conscious memory)
M10 ──░░░░░▁▁▂▂▃▃▃▃▄▅▆▇▇▇▇▇▇▇── (needs returning visitors + memory)
```

---

## Comparison Benchmark

For the "no chatbot can fake this" claim, publish a comparison:

| Metric | ChatGPT | Character.ai | Automaton | The Shopkeeper |
|--------|---------|-------------|-----------|----------------|
| Uptime (continuous) | 0 (stateless) | 0 (stateless) | ✓ (if running) | ✓ 14,000+ cycles |
| Self-initiated actions | 0% | 0% | ~40% (ReAct) | 68% |
| Behavioral entropy | 0 (deterministic) | Low | Medium | Structured rhythm |
| Knowledge accumulation | 0 (no memory) | Shallow | Possible | 847 facts, 23 topics |
| Visitor recall | 0 | Shallow | 0 | 83% |
| Taste development | 0 | 0 | 0 | 0.73 consistency |
| Emotional range | 0 | Simulated | 0 | 87/125 states |
| Sleep/wake cycles | 0 | 0 | 0 (heartbeat only) | 46 sleep cycles |
| Unprompted memories | 0 | 0 | 0 | 156 |
| Relationship depth | 0 | Static | 0 | Gradient positive |

This table is the mic drop. Nobody fills those columns.

---

## Implementation Priority

**Phase 1 (build with 069, before launch):**
- M1 (uptime) — trivial, just count cycles
- M2 (initiative rate) — classify actions_log
- M7 (emotional range) — already have drives_state_history
- Historical backfill script
- Metrics API endpoint
- Basic public dashboard (numbers only, no charts)

**Phase 2 (build with 070):**
- M3 (entropy) — need action diversity data
- M4 (knowledge) — needs browse_history
- M5 (recall) — needs MD visitor files
- M9 (unprompted memories) — needs journal analysis
- Trend charts on public dashboard

**Phase 3 (2-4 weeks after launch):**
- M6 (taste) — needs accumulated browse + journal data
- M8 (sleep quality) — needs enough sleep cycles for correlation
- M10 (depth gradient) — needs returning visitors
- Comparison benchmark table
- Embeddable badge/widget

---

## Files to Create
```
metrics/__init__.py
metrics/collector.py
metrics/models.py
metrics/m_uptime.py
metrics/m_initiative.py
metrics/m_entropy.py
metrics/m_knowledge.py
metrics/m_recall.py
metrics/m_taste.py
metrics/m_emotion.py
metrics/m_sleep.py
metrics/m_memory.py
metrics/m_depth.py
metrics/public.py
metrics/backfill.py
migrations/071_metrics.sql
tests/test_metrics_collector.py
tests/test_metrics_backfill.py
```

## Files to Modify
```
api/dashboard_routes.py — add /api/metrics endpoint
heartbeat_server.py — schedule hourly metric collection
```

## Optional (public dashboard)
```
public-dashboard/
  index.html (or Next.js page)
  badge.svg (embeddable widget)
```

---

## Definition of Done

- [ ] All 10 metrics defined with working calculators
- [ ] Historical backfill computes metrics from existing cycle_log + actions_log + drives_state_history
- [ ] Metrics API returns current snapshot + 30-day trends
- [ ] Public liveness dashboard accessible without auth
- [ ] Dashboard shows real-time state + lifetime stats + trend sparklines
- [ ] Comparison table published (vs ChatGPT, Character.ai, Automaton)
- [ ] Embeddable badge renders "● Alive for X days"
- [ ] Hourly collection runs in heartbeat without impacting cycle performance
- [ ] 30-day trend data persists in metrics_snapshots table
