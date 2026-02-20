# CHANGELOG — The Shopkeeper

All notable behavioral and system changes. Dates in JST.

---

## 2026-02-16

### Drive system rebalancing
- **Homeostatic pull mechanism** (TASK-024): Added spring-like restoring force to all 7 drives. Each drive has a character-defined equilibrium; displacement creates proportional pull back. Fixes drives permanently pinning at 0% or 100%.
- **Action-inferred drive relief** (TASK-024): Successful actions now satisfy relevant drives. Speaking reduces curiosity, journaling reduces curiosity, quiet cycles provide rest recovery. Previously only social_hunger, energy, and mood_valence were affected post-action.
- **Curiosity drain reduction**: `write_journal` curiosity cost reduced from -0.03 to -0.01. Memory_updates curiosity hit reduced from -0.04 to -0.02. Previous values overwhelmed homeostatic pull by 30-70x.

### Habit system fixes
- **Generative vs reflexive actions** (TASK-032): Actions tagged as `generative` (write_journal, speak, post_x_draft) no longer auto-fire via habits. Instead, strong habits boost impulse (+0.3) so cortex is more likely to choose the action. Reflexive actions (rearrange, end_engagement, express_thought) still auto-fire. Fixes blank journal entries from habit-skipping cortex.
- **Drive-gating for habits**: Habits only fire when the relevant drive supports the action. write_journal requires expression_need > 0.2. speak requires social_hunger > 0.3. close_shop requires shop actually open. Fixes write_journal firing every cycle and close_shop spam (11x/day on an already-closed shop).
- **3-cycle cooldown**: Same action can't habit-fire twice within 3 cycles. Safety net against spam loops.

### Journal quality
- **Empty detail filter**: write_journal skipped at body level if cortex provides no distinct detail.text. No more falling back to monologue copy. The internal_monologue already captures the thought — journal is for deliberate, distinct reflection only.
- **Salience boost removed**: Removed +0.08 salience boost for write_journal in day_memory. Journal entries compete on content quality, not action type.
- **Partial drive relief for skipped journals**: If she intends to journal but has nothing distinct to say, expression_need relief is halved (-0.06 instead of -0.12). The intention partially satisfies the drive.

### Memory system
- **Resonance variance** (TASK-025): Replaced boolean-dominated salience scoring with continuous factors: drive delta (0–0.25), content richness (0–0.12), action diversity (0–0.10), mode bonus (0–0.05). Cortex resonance flag reduced from +0.4 to +0.2. Fixes all memories showing identical 55% resonance.

### Feed pipeline
- **Content pipeline activated** (TASK-033): 8 RSS feeds configured (5 core + 3 serendipity). readings.txt seeded with 14 curated URLs. Feed ingester wired into heartbeat loop on 1-hour cycle.

### Dashboard
- **Heartbeat indicator** (TASK-022): Shows Active/Late/Inactive based on actual cycle timestamps, not static flag.
- **Thread titles** (TASK-023): Fixed query hitting wrong table (cycle_log instead of threads). Now shows real thread titles, types, tags, activity.
- **Body panel** (TASK-015): Action capabilities grid, energy budget bar, actions today.
- **Behavioral panel** (TASK-015): Top habits, active inhibitions, suppression feed, cortex savings counter.
- **Content Pool panel** (TASK-026): Unseen items, type breakdown, recent additions.
- **Feed panel** (TASK-027): Pipeline status, queue depth, ingestion rate, error tracking.
- **Consumption History panel** (TASK-028): What she consumed and what it produced, with outcome tags.
- **Scene compositor** (TASK-021a): 6-layer visual rendering with sprite states.
- **Pipeline-driven scene** (TASK-021b): Sprite and time-of-day resolved server-side from live drive/engagement state.

### Infrastructure
- **Migrations**: Ran on VPS. Created missing tables (threads, content_pool, etc.) that were never created because DB predated migration system.
- **Memory Pool query**: Changed from today-only filter to 7-day rolling window.

---

## 2026-02-14 — 2026-02-15

### Initial build completion
- Tasks 001–014, 016–020 completed. Full ALIVE pipeline: sensorium, thalamus, cortex, basal ganglia, body, output, sleep. Multi-intention processing, inhibition learning, habit formation, multi-visitor engagement, engagement choice. VPS deployed.
