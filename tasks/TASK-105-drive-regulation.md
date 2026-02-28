# TASK-105: Drive-Based Regulation — Replace Hard Caps + Social Sensitivity Trait

**Status:** READY
**Priority:** P2
**Branch:** `feature/drive-regulation`
**Depends on:** P1-6 energy feeling fix (must be live so budget-as-tiredness works)

---

## Problem

Two overlapping rate-limiting systems fight each other:

1. **Hard caps** — journal 3/day, content reads capped, thread creation capped. Added early before drives existed. Blunt instrument.
2. **Drive system** — expression_need drops after journaling, curiosity gates content consumption. Designed to be the rate limiter.

Both are active. Drives say "journal" but cap says "you hit 3 today." Counter keeps incrementing past the cap (known bug). Drives don't get relief signal because the action was blocked. New agents with no content/threads/actions are starved — journaling is their only outlet and it's capped at 3.

Additionally, social hunger uses a flat drain per message regardless of agent personality or conversation pacing. No session concept, no personality variation.

This task removes caps, lets drives be the sole behavioral regulator, and adds personality-driven social dynamics.

---

## Part A: Remove Per-Action Caps

### Delete

- Journal daily cap (3/day) — wherever this is enforced (likely `body.py` or `action_registry.py`)
- Journal cap counter — the counter that increments past the cap
- Content read cap — if one exists
- Thread creation cap — if one exists
- Any `_today` counters for these actions

### Keep

- **X posting governor** — this is brand safety, not rate limiting. Rate limit (8hr cooldown) + daily cap (2/day) + topic whitelist + forbidden patterns + similarity check. All stay.
- **Real-dollar budget** — the ultimate cap. She can't act if she can't pay.

### Why this is safe

Without caps, what prevents action spam?

1. **Drives decay on action.** Journal drops expression_need by ~0.12-0.20. After 3-4 journals, expression_need is near 0. No drive pressure → basal ganglia doesn't select the action.
2. **Budget constrains total activity.** At $0.01/cycle and $5/day budget, she gets ~500 cycles max. Journaling every cycle would drain budget in hours. The budget IS the cap.
3. **Basal ganglia competition.** Journal competes with think, browse, engage, express. It only wins when expression_need is the dominant drive. With multiple outlets, it rarely dominates for long.

### New agent behavior (desired)

Day 1: High expression_need (nothing else to do) → journals 8-10 times → expression_need satisfied → idle/think cycles dominate. Budget spent on journaling + thinking = ~$1.50.

Day 3: Content feeds configured → read_content competes with journal → journals drop to 4-5/day naturally.

Day 7: Threads active, visitors arriving → journal drops to 2-3/day. Self-correcting without magic numbers.

---

## Part B: Social Sensitivity Trait

### Identity YAML addition

```yaml
# In agent identity YAML (demo/config/default_identity.yaml, etc.)
personality:
  social_sensitivity: 0.5  # 0.0 = deep introvert, 1.0 = strong extrovert
```

Default: `0.5` (neutral). The Shopkeeper might be `0.35` (slightly introverted — she likes people but needs space). A greeter agent might be `0.8`.

### How it affects social_hunger

**Time drift (loneliness rate):**
```python
# Current: flat +0.05/hr
# New: personality-scaled
drift_per_hour = 0.05 * social_sensitivity
# Introvert (0.2): +0.01/hr — gets lonely very slowly
# Neutral (0.5):   +0.025/hr
# Extrovert (0.8): +0.04/hr — gets lonely fast
```

**Relief per message (with diminishing returns):**
```python
# Current: flat -0.08 or -0.15 per message
# New: personality-scaled with session decay
base_relief = 0.15 * (1.0 + (1.0 - social_sensitivity))
# Introvert (0.2): base_relief = 0.27 — each message fills her up fast
# Neutral (0.5):   base_relief = 0.225
# Extrovert (0.8): base_relief = 0.18 — needs more messages to feel full

# Diminishing returns within session
relief = base_relief / (1 + messages_this_session * 0.3)
# Message 1: full relief
# Message 3: ~53% relief
# Message 5: ~40% relief
# Message 10: ~25% relief
```

**Session tracking:**
```python
# A "session" is a burst of conversation with gaps < 10 minutes
# Tracked per-visitor in hypothalamus state (not persisted to DB)

class SessionTracker:
    def __init__(self):
        self.sessions: dict[str, Session] = {}  # visitor_id -> Session
    
    def on_message(self, visitor_id: str) -> int:
        """Returns messages_this_session count."""
        now = time.time()
        session = self.sessions.get(visitor_id)
        
        if session is None or (now - session.last_message_at) > 600:  # 10 min timeout
            # New session
            self.sessions[visitor_id] = Session(count=1, last_message_at=now)
            return 1
        
        session.count += 1
        session.last_message_at = now
        return session.count
```

Module-level instance in hypothalamus. Not persisted — resets on restart, which is fine. Sessions are transient by nature.

### drives_to_feeling() updates

```python
# Social hunger thresholds adjusted by personality
if social_sensitivity < 0.3:  # introvert
    if d.social_hunger > 0.8:
        lines.append("It's been quiet for a while. You wouldn't mind some company.")
    elif d.social_hunger < 0.15:
        lines.append("You need space. Too many voices today.")
elif social_sensitivity > 0.7:  # extrovert
    if d.social_hunger > 0.5:
        lines.append("You're restless. You want someone to talk to.")
    elif d.social_hunger < 0.2:
        lines.append("You've had a good run of conversation. Feeling warm.")
else:  # neutral
    # existing thresholds
```

Introvert threshold for loneliness is higher (needs to be very lonely before feeling it). Threshold for "enough" is lower (fills up fast). Extrovert is the inverse.

---

## Part C: Verify Drive Relief Signals

With caps removed, drive relief must work correctly or actions spam. Verify these are wired:

| Action | Drive affected | Relief amount | Verified? |
|--------|---------------|---------------|-----------|
| write_journal (with distinct text) | expression_need | -0.12 to -0.20 | Check |
| write_journal (skipped, no text) | expression_need | -0.06 (half relief) | Check — this is the P1 fix from body.py |
| read_content | curiosity (diversive) | -0.10 to -0.15 | Check |
| visitor speech received | social_hunger | -(session-decayed relief) | New |
| post_x | expression_need | -0.25 to -0.30 | Check |
| create/update thread | expression_need | -0.10 | Check |

If any of these are not wired, wire them before removing caps. Removing caps without working drive relief = guaranteed spam.

---

## Files to modify

**hypothalamus.py (or drives.py):**
- Read `social_sensitivity` from agent identity config
- Scale social_hunger drift and relief
- Add SessionTracker for diminishing returns
- Pass messages_this_session into relief calculation

**body.py / action_registry.py:**
- Remove journal daily cap check
- Remove cap counter increment
- Remove content/thread caps if they exist

**drives_to_feeling():**
- Personality-aware social hunger thresholds

**Identity YAML schema:**
- Add `personality.social_sensitivity` field with default 0.5

**config/agent_identity.py (or identity loader):**
- Parse social_sensitivity from YAML, expose to hypothalamus

---

## Verification

1. **Cap removal:** Run agent 24h with no caps. Count journals — should be 6-12 on day 1 (high expression), tapering to 3-5 by day 3 as other actions compete. If journal count stays >15/day, drive relief is broken.

2. **Social sensitivity:** Deploy two test agents — one at 0.2 (introvert), one at 0.8 (extrovert). Send 10 messages to each. Introvert should show "enough" feeling after 3-4 messages, extrovert after 8-9. Check drives_state in DB after test.

3. **Session decay:** Send 5 messages in quick succession, wait 15 minutes, send 5 more. First batch: diminishing relief. Second batch: full relief resets (new session). Check social_hunger values in cycle_log.

4. **Budget as ultimate cap:** Set daily budget to $1. Agent should naturally slow down and rest before journaling 20 times — budget runs out first.

---

## Risk

Medium. Removing caps is safe IF drive relief is working. The verification step "check relief is wired" is critical — do it before removing caps, not after. If relief is broken in any action path, that action will fire every cycle until budget runs out.

Social sensitivity is low risk — it's a new parameter with a neutral default. Existing agents behave identically at 0.5.
