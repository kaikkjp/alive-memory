# TASK-068: Behavioral Health Diagnostic

> **Purpose:** Reusable diagnostic an agent runs on demand to catch system-level behavioral bugs before they compound. Run this after any soak test, before any deploy, or whenever something "feels off."
>
> **Agent instruction:** Pull the live production DB first (Step 0), then run all checks below. Report findings as PASS / WARN / FAIL with evidence.

---

## 0. Pull Production Database

**Always run against the live DB from the VPS, not the local copy.** Local DBs go stale fast.

```bash
scp shopkeeper:/var/www/shopkeeper/data/shopkeeper.db data/shopkeeper_live.db
```

- SSH alias `shopkeeper` is configured in `~/.ssh/config` (root@89.167.23.147)
- DB on VPS lives at `/var/www/shopkeeper/data/shopkeeper.db`
- Save locally as `data/shopkeeper_live.db` to avoid overwriting dev DBs
- All queries below should target this file

**Table name reference** (actual names differ from some specs):
- `day_memory` (not `day_memories`)
- `cycle_log` (not `cycle_logs`)
- `action_log` — status column: `'executed'|'suppressed'|'incapable'|'inhibited'`
- `internal_monologue` (not `inner_monologue`)
- `action` column (not `action_name`)
- `drives_state` — single row, drive columns not rows

---

## 1. Memory Pool Health

```sql
-- Duplicate check: same moment_type + similar summary within 1 hour
SELECT moment_type, summary, COUNT(*) as dupes,
       MIN(created_at) as first, MAX(created_at) as last
FROM day_memories
GROUP BY moment_type, summary
HAVING COUNT(*) > 3
ORDER BY dupes DESC LIMIT 20;

-- Salience distribution: should be spread, not clustered
SELECT moment_type, ROUND(salience, 1) as sal_bucket, COUNT(*)
FROM day_memories
GROUP BY moment_type, sal_bucket
ORDER BY sal_bucket DESC;

-- Recall monopoly check: what would hippocampus.recall() return right now?
SELECT moment_type, summary, salience
FROM day_memories
ORDER BY salience DESC LIMIT 20;
-- FAIL if >50% are the same moment_type
```

---

## 2. Action Loop Detection

```sql
-- Same action firing repeatedly
SELECT action_name, COUNT(*) as fires,
       MIN(created_at) as first, MAX(created_at) as last
FROM cycle_logs
WHERE created_at > datetime('now', '-24 hours')
GROUP BY action_name
ORDER BY fires DESC LIMIT 10;
-- WARN if any single action is >40% of total cycles

-- Suppression rate
SELECT COUNT(*) FILTER (WHERE suppressed = 1) as suppressed,
       COUNT(*) as total,
       ROUND(100.0 * COUNT(*) FILTER (WHERE suppressed = 1) / COUNT(*), 1) as pct
FROM action_log
WHERE created_at > datetime('now', '-24 hours');
-- WARN if suppression rate > 30%
```

---

## 3. Drive Stagnation

```sql
-- Drives stuck at extreme values
SELECT drive_name, value, updated_at
FROM drives_state
WHERE value > 0.85 OR value < 0.10;
-- WARN if any drive has been >0.85 or <0.10 for more than 6 hours

-- Mood stuck
SELECT AVG(arousal) as avg_arousal, AVG(valence) as avg_valence, COUNT(*)
FROM cycle_logs
WHERE created_at > datetime('now', '-6 hours');
-- WARN if avg_arousal > 0.7 AND avg_valence < 0.3 (sustained tension)
```

---

## 4. LLM Output Quality

```sql
-- Identical or near-identical outputs
SELECT inner_monologue, COUNT(*) as repeats
FROM cycle_logs
WHERE created_at > datetime('now', '-24 hours')
GROUP BY inner_monologue
HAVING COUNT(*) > 2
ORDER BY repeats DESC LIMIT 5;
-- FAIL if any monologue repeats >3 times

-- Empty/null output fields
SELECT COUNT(*) FILTER (WHERE inner_monologue IS NULL OR inner_monologue = '') as empty_mono,
       COUNT(*) FILTER (WHERE body_state IS NULL) as empty_body,
       COUNT(*) as total
FROM cycle_logs
WHERE created_at > datetime('now', '-24 hours');
-- WARN if empty rate > 10%
```

---

## 5. Sleep Cycle Health

```sql
-- Sleep actually happening
SELECT event_type, created_at
FROM cycle_logs
WHERE event_type IN ('sleep_start', 'sleep_end', 'nap_start', 'nap_end')
ORDER BY created_at DESC LIMIT 10;
-- FAIL if no sleep in last 24 hours

-- Deferred sleeps stacking
SELECT COUNT(*) as deferred_count
FROM cycle_logs
WHERE event_type = 'sleep_deferred'
  AND created_at > datetime('now', '-24 hours');
-- WARN if > 5 deferrals in 24h
```

---

## 6. Context Completeness

```
# Run one cortex cycle in dry-run and check:
# - self_context block present and populated (060)
# - self_model loaded (061)
# - drift detection running (062)
# - budget enforcement active (065)
# - all prompt sections within token budget
# Print: section name, token count, budget cap, % used
```

---

## 7. Frontend/Visitor Health

```
# Check via HTTP:
GET /assets/sprites/char-1-cropped.png  → 200? (not transparent 1x1)
GET /assets/shop_interior.png           → 200?

# WebSocket: connect, wait for scene_update → sprite_state populated?

# Dashboard: GET /dashboard → 200? All panels render?
```

---

## Output Format

```
BEHAVIORAL HEALTH CHECK — [timestamp]
========================================
Memory Pool:       FAIL — 47 duplicate "something felt off" entries monopolizing recall
Action Loops:      PASS
Drive Stagnation:  WARN — social_hunger at 0.76 for 9 hours
LLM Output:        PASS
Sleep Cycles:      PASS
Context:           PASS — all sections within budget
Frontend:          PASS — sprites loading, dashboard renders
========================================
ACTION NEEDED: Memory pool poisoned. Run purge script.
```
