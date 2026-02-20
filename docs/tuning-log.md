# Tuning Log — The Shopkeeper

Why the numbers are what they are. Reference this before changing parameters.

---

## Drive Equilibria

Set in `pipeline/hypothalamus.py` → `DRIVE_EQUILIBRIA`.

These define who she is at rest — her personality when nothing is happening.

| Drive | Equilibrium | Reasoning |
|-------|-------------|-----------|
| social_hunger | 0.45 | Slightly below midpoint. She's a shopkeeper who enjoys visitors but doesn't crave them. Not an extrovert. |
| curiosity | 0.50 | Midpoint. She's naturally curious but not obsessively so. Settles to ~70% during idle periods when combined with time force (+0.03/hr). |
| expression_need | 0.35 | Below midpoint. She expresses when moved to, not compulsively. A quiet person who speaks with intention. |
| rest_need | 0.25 | Low. She's not perpetually tired. Rest need builds slowly from activity and drains naturally. |
| energy | 0.70 | Above midpoint. She has good baseline energy. Recovers naturally between active periods. |
| mood_valence | 0.05 | Near neutral-positive. She's not manic or depressive. Slight positive lean — contentment, not euphoria. |
| mood_arousal | 0.30 | Below midpoint. Calm by default. Alert when stimulated, but resting state is low-arousal. |

**Homeostatic pull rate:** 0.15/hr. This is the spring constant. Higher = snappier return to equilibrium, less dramatic swings. Lower = more emotional range but risk of pinning. 0.15 was chosen so that the pull generates ~+0.001/cycle at small displacements (near equilibrium) and ~+0.01/cycle at max displacement — gentle but persistent.

**Why equilibria matter:** These aren't just math. Changing `curiosity` from 0.50 to 0.70 makes her a fundamentally more curious person. Changing `expression_need` from 0.35 to 0.60 makes her chatty. Tune character, not just behavior.

---

## Drive Effect Magnitudes

Set in `pipeline/output.py` → `ACTION_DRIVE_EFFECTS` and inline adjustments.

### The curiosity drain problem (2026-02-16)

**Original values:**
- write_journal: curiosity -0.03 per action
- memory_updates present: curiosity -0.04
- Total possible per cycle: -0.07

**Homeostatic pull per cycle (3-5 min intervals):**
- At curiosity=0.0: pull = (0.50 - 0.0) × 0.15/hr × 0.05hr ≈ +0.004
- Drain/pull ratio: 0.07 / 0.004 = 17.5x — drain wins overwhelmingly

**Fixed values:**
- write_journal: curiosity -0.01
- memory_updates: curiosity -0.02
- Total possible per cycle: -0.03
- Drain/pull ratio at 0.0: 0.03 / 0.004 = 7.5x — still wins but not by as much
- At curiosity=0.30: pull ≈ +0.0015, drain net ≈ -0.028 — still drains but slowly
- Key: with drive-gating, write_journal fires less often, so the *average* drain per cycle drops significantly

**Lesson:** Drive effects per-action must be compared against homeostatic pull *per cycle at expected cycle frequency*. If action fires every cycle and drain > pull, the drive pins regardless of equilibrium.

### Expression need relief

- write_journal successful: expression_need -0.12
- write_journal skipped (empty detail): expression_need -0.06 (half relief — intention counts)
- express_thought: expression_need -0.08

**Problem found (2026-02-16):** At -0.12 per successful journal, expression_need zeroed out every cycle before it could build. Time-based growth (+0.04/hr ≈ +0.003/cycle) couldn't compete. Combined with drive-gating (requires > 0.2), she now journals → drops to ~0.1 → waits 15-20 cycles for it to rebuild → journals again. Natural rhythm.

---

## Habit System Parameters

### Drive gates

Set in `pipeline/basal_ganglia.py` → `HABIT_DRIVE_GATES`.

| Action | Gate | Threshold | Reasoning |
|--------|------|-----------|-----------|
| write_journal | expression_need | > 0.2 | She journals when she has something to express, not reflexively. 0.2 is low enough to fire regularly but prevents the every-cycle spam seen at 0.0. |
| express_thought | expression_need | > 0.2 | Same logic as journal. |
| post_x_draft | expression_need | > 0.2 | Same logic. Public expression needs even more buildup but using same threshold for now. |
| speak | social_hunger | > 0.3 | She talks when she wants connection. 0.3 is moderate — she's not antisocial but doesn't chatter. |
| rearrange | energy | > 0.3 | Physical action needs energy. |
| place_item | energy | > 0.3 | Same. |
| close_shop | shop_status | == 'open' | Binary gate. No drive threshold — closing an already-closed shop is just a bug. |

### Cooldown

3 cycles per action. Safety net, not primary gate. Prevents rapid re-firing even if drive state bounces above threshold. At ~3-5 min cycle intervals, this is a 9-15 minute minimum gap between same-action habit fires.

### Strength thresholds

- Auto-fire threshold: 0.60 (set in TASK-011b)
- Formation threshold: 0.10 (second occurrence in similar context)
- Strength curve: fast 0→0.4, medium 0.4→0.6, slow 0.6→0.8

**close_shop at 90% strength (2026-02-16):** Reached 90% because it fired 18 times in a row with no gate. After adding the open/closed gate, it still exists at 90% but only fires when shop is actually open. Strength will naturally decay if she stops closing the shop at night (which she should, since it's already closed).

---

## Journal Behavior

### Empty detail filter (2026-02-16)

**Problem:** write_journal fell back to monologue when cortex provided no detail.text. Result: duplicate storage (same thought in cycle_log AND journal_entries AND text_fragments), memory pool pollution (90% of entries were "I wrote in my journal"), salience distortion (+0.08 boost for all journal cycles).

**Fix:** Body-level filter. If detail.text is empty/whitespace, skip the journal write. Monologue already captures the thought. Journal reserved for when cortex has something distinct.

**Salience boost removed:** write_journal was getting +0.08 in day_memory scoring. This meant routine journal-with-monologue-copy ranked higher than genuine insights. Removed entirely — content quality determines salience.

---

## Memory / Resonance

### Salience scoring (TASK-025, 2026-02-16)

**Before:** Almost entirely boolean. Cortex resonance (+0.4) + write_journal (+0.15) = 0.55 for most entries. No variance.

**After:** Continuous factors:
- Cortex resonance flag: +0.2 (down from +0.4 — fires too often to be a strong signal)
- Drive delta: 0–0.25 (linear scale based on how much drives changed)
- Content richness: 0–0.12 (word count of monologue/dialogue)
- Action diversity: 0–0.10 (0.05 per distinct action type)
- Mode bonus: 0–0.05 (engage/express/consume get small base)
- Self-expression: +0.08 (down from +0.15)

**Result:** Resonance now ranges from ~0.30 to ~0.80 depending on cycle richness.

---

## Feed / Content

### RSS sources (2026-02-16)

5 core + 3 serendipity. Core matches her existing Collection taste (Ma, Camus, Tokyo alleys, Satie):
- spoon-tamago.com (Tokyo design/craft)
- aeon.co (philosophy essays)
- themarginalian.org (literature/wisdom)
- publicdomainreview.org (historical curiosities)
- tokyoartbeat.com (exhibitions)

Adjacent sources for serendipity:
- ambientblog.net (music/soundscapes)
- messynessychic.com (exploration/nostalgia)
- lensculture.com (photography)

**Ingestion rate:** 1hr cycle, cap at 50 unseen. At 8 sources, expect 5-15 new items/day depending on feed frequency.

---

## Open Questions

- **Mood valence capping at 100%:** Quiet cycles give +0.02/cycle. Homeostatic pull toward 0.05 should counter this, but mood valence was still pinned at 100% in the Feb 16 snapshot. May need to reduce quiet cycle mood boost or verify pull is applying to mood_valence.
- **Rest need stuck at 100%:** Time-based buildup (+0.03/hr) vs homeostatic pull toward 0.25. With drive-gating and journal cooldown reducing cycle frequency, rest_need should start dropping. Monitor during soak test.
- **Curiosity at 0% post-fix:** With reduced drains and drive-gating, curiosity should climb toward equilibrium. If still pinned after 24h of soak test, the pull rate (0.15/hr) may need increasing or the remaining drains are still too strong.
- **Habit strength decay:** close_shop and write_journal habits are at 90% and 82%. If behavior changes reduce firing frequency, do habits decay? If not, add time-based decay for unfired habits.
