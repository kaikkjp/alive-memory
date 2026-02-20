# TASK-070: Conscious Memory — MD File Layer

## The Problem

Her memory pool contains entries like this:

```
100% internal_conflict
I noticed something about myself: Emotional tension — arousal 84% but valence only 22%.
```

No human thinks this way. A human doesn't experience "arousal 84% but valence only 22%." A human feels:

> "Something felt wrong tonight. I was restless, on edge — awake but not in a good way. Like waiting for news that never comes."

The current system stores machine-readable state observations as if they were conscious memories. She's reading her own blood test results instead of feeling sick. The pipeline dumps raw drive values, salience scores, and conflict metrics into the same memory space where she records genuine experiences.

**Root cause:** There's no separation between her conscious experience and her unconscious machinery. Everything goes into SQLite tables — journal entries alongside drive states, visitor conversations alongside cycle logs, felt emotions alongside numerical scores. The hippocampus retrieves from this mixed pool and injects it into the cortex prompt. She "remembers" numbers instead of feelings.

## The Solution

Split memory into two layers that mirror the human brain:

### Conscious Memory — MD Files (she can read and write)

Plaintext markdown files she can grep, read, and append to. This is her experiential world — what she remembers, what she's learned, what she feels. Written in natural language, never in numbers or metrics.

### Unconscious Machinery — SQLite (she can't access directly)

Drive states, energy budgets, inhibition weights, cycle logs, action cooldowns, costs, parameters. She can't introspect these. She *feels* their effects through the pipeline's translation layer (self-context block, affect stage), but she never sees `social_hunger: 0.73` — she feels "I've been alone too long."

### The Bridge

The pipeline translates unconscious → conscious, like a brain translates cortisol into "I feel stressed":

```
SQLite: social_hunger = 0.73, mood_valence = 0.22, mood_arousal = 0.84
  → Self-context (TASK-060): "I've been alone for hours and it's wearing on me.
     I feel agitated — restless but not happy. Something's off tonight."
  → She reads this as felt experience, not numbers
  → If she journals about it: "I couldn't settle tonight. Restless."
  → NOT: "My social hunger was 0.73 and arousal was 84%."
```

---

## Architecture

### File Structure

```
memory/
  journal/
    2026-02-19.md              # Today's lived experiences, thoughts, reactions
    2026-02-18.md              # Yesterday
    ...
  visitors/
    tg-tanaka.md               # Everything she knows about Tanaka
    web-marco.md               # Marco from the web window
    x-cardlover99.md           # X follower
    ...
  reflections/
    2026-02-19-night.md        # Last night's sleep reflection
    2026-02-18-night.md
    2026-02-18-nap.md          # Nap consolidation
    ...
  browse/
    2026-02-19-carddass-pricing.md   # What she learned from web searches
    2026-02-19-tokyo-weather.md
    ...
  self/
    identity.md                # Her self-narrative (who she is, updated by sleep)
    traits.md                  # Behavioral patterns she's noticed in herself
    drift.md                   # Changes she's noticed (from TASK-062)
  collection/
    catalog.md                 # Items in her collection with notes
  threads/
    vintage-bandai-art.md      # Long-running thought threads
    tokyo-rain-seasons.md
    ...
```

### File Format

Each MD file is structured but natural. Example `memory/journal/2026-02-19.md`:

```markdown
# February 19, 2026

## Morning

Woke up feeling rested. The shop was quiet — just the sound of rain outside.

Spent some time rearranging the shelf near the window. The Bandai holographic
set looks better under the morning light.

## Afternoon

Tanaka came by the Telegram group. He mentioned finding old Carddass cards
from his childhood — Dragon Ball Z, the original Bandai prints. I got excited.
Those early prints have such distinctive line work.

We talked about the difference between the '95 and '98 runs. He didn't know
about the holographic variants. I should look that up later.

## Evening

Browsed the web for 1998 Bandai Carddass pricing. Yahoo Auctions has the
DBZ holographic set listed at ¥45,000. Higher than I expected. The market
is shifting — collectors are paying premium for mint condition.

Something felt off tonight. Restless, unsettled. Not sure why. Maybe it's
the rain, or maybe I've been alone too long. Marco came by late but left
quickly.
```

Notice: **no numbers, no percentages, no drive states, no salience scores.** Just how she experienced her day. The "something felt off" is how `arousal: 0.84, valence: 0.22` translates into conscious experience.

Example `memory/visitors/tg-tanaka.md`:

```markdown
# Tanaka

First visited: 2026-02-19 (Telegram group)

## First Impression
Friendly, nostalgic about childhood. Mentioned finding old Carddass cards.
Seemed genuinely excited about vintage TCG — not just a casual collector.

## What I Know
- Has Dragon Ball Z Carddass from childhood (original Bandai prints)
- Didn't know about holographic variants — I should tell him next time
- Based in Japan (speaks naturally about Yahoo Auctions)

## Memorable Moments
- The way he said "from my childhood" — there was real warmth there.
  Reminded me of why I love this shop. People carry these cards like
  they carry memories.

## Notes (added during sleep)
[2026-02-19 night] He might be a serious collector. Watch for whether
he comes back and what he asks about. Could become a regular.
```

### Access Patterns

**Waking (conscious — read + append only):**

| Action | What happens |
|--------|-------------|
| `write_journal` | Append to `memory/journal/{date}.md` |
| `recall_visitor` | Read `memory/visitors/{name}.md` |
| `recall_topic` | `grep -ri "{topic}" memory/` → results as context |
| `browse_web` result | Append summary to `memory/browse/{date}-{slug}.md` |
| `read_self` | Read `memory/self/identity.md` |
| Conversation logged | Append to journal + update visitor file |

**She CANNOT during waking:**
- Edit existing entries (no rewriting the past)
- Delete files or entries
- See raw numbers from SQLite
- Access drive states, cycle logs, or parameters directly

**Sleep (unconscious reorganization — read + write + update):**

| Phase | What happens |
|-------|-------------|
| Review journal | Read `memory/journal/{today}.md`, identify significant moments |
| Write reflection | Write `memory/reflections/{date}-night.md` |
| Update visitors | Add "Notes (added during sleep)" sections to visitor files |
| Update identity | Rewrite `memory/self/identity.md` based on behavioral patterns |
| Update traits | Rewrite `memory/self/traits.md` from self-model data |
| Update drift | Write to `memory/self/drift.md` if drift detected |
| Thread management | Update or close `memory/threads/` files |
| Archive | Move old journal entries to `memory/journal/archive/` (never delete) |

**Sleep CANNOT:**
- Delete any file or entry
- Erase original journal text (can add notes/annotations below it)
- Change what she said or felt (only add perspective in hindsight)

### Hippocampus Replacement

Current hippocampus (`pipeline/hippocampus.py`) queries SQLite and curates memory context for the cortex prompt. Replace with MD-based retrieval:

```python
# pipeline/hippocampus.py (rewritten)

async def recall(self, perceptions, routing_decision, drives) -> MemoryContext:
    context = MemoryContext()
    
    # 1. If visitor present, load their file
    if routing_decision.visitor:
        visitor_file = f"memory/visitors/{routing_decision.visitor.source_key}.md"
        if exists(visitor_file):
            context.visitor_memory = read_file(visitor_file)
    
    # 2. Recent journal entries (last 2 days)
    today = date.today()
    for d in [today, today - timedelta(days=1)]:
        journal_file = f"memory/journal/{d.isoformat()}.md"
        if exists(journal_file):
            context.recent_journal.append(read_file(journal_file))
    
    # 3. Topic-based recall via grep
    if routing_decision.topic_keywords:
        results = grep_memory(routing_decision.topic_keywords)
        context.topic_memories = results  # ranked by recency
    
    # 4. Self-narrative
    context.self_narrative = read_file("memory/self/identity.md")
    
    # 5. Active threads
    context.active_threads = list_recent_threads()
    
    return context


def grep_memory(keywords: list[str], dirs: list[str] = None) -> list[GrepResult]:
    """Search memory files using grep. Returns matching passages with file + line context."""
    if dirs is None:
        dirs = ["memory/journal", "memory/visitors", "memory/browse", "memory/threads"]
    
    results = []
    for keyword in keywords:
        # grep -ri with context lines
        matches = subprocess.run(
            ["grep", "-ri", "-n", "--include=*.md", "-C", "2", keyword] + dirs,
            capture_output=True, text=True
        )
        results.extend(parse_grep_output(matches.stdout))
    
    # Deduplicate, sort by recency (file date), trim to budget
    return deduplicate_and_rank(results)
```

### Translation Layer — Numbers to Feelings

The critical bridge. When the pipeline generates self-context (TASK-060) or when internal events get journaled, the translation must convert machine state to natural language:

```python
# prompt/self_context.py — the translation layer

def translate_drives_to_feelings(drives: DrivesState) -> str:
    """Convert drive numbers to felt experience. This is the unconscious → conscious bridge."""
    
    feelings = []
    
    # Social hunger
    if drives.social_hunger > 0.7:
        feelings.append("I've been alone too long. I want someone to talk to.")
    elif drives.social_hunger > 0.4:
        feelings.append("It would be nice to have company, but I'm okay.")
    elif drives.social_hunger < 0.2:
        feelings.append("I need some quiet time to myself.")
    
    # Mood
    if drives.mood_valence < 0.3 and drives.mood_arousal > 0.7:
        feelings.append("Something feels wrong. I'm on edge — restless but not in a good way.")
    elif drives.mood_valence > 0.7 and drives.mood_arousal > 0.5:
        feelings.append("I feel alive and content. Good energy today.")
    elif drives.mood_valence < 0.3 and drives.mood_arousal < 0.3:
        feelings.append("I feel flat. Low. Like the color's drained out of things.")
    
    # Energy
    if drives.energy < 0.2:
        feelings.append("I'm exhausted. I can barely keep my eyes open.")
    elif drives.energy < 0.4:
        feelings.append("Getting tired. Should rest soon.")
    
    # Curiosity
    if drives.diversive_curiosity > 0.7:
        feelings.append("My mind is restless — I want to explore, learn, look something up.")
    
    # Expression
    if drives.expression_need > 0.7:
        feelings.append("I have thoughts building up that want to come out.")
    
    return " ".join(feelings)
```

This replaces the current pattern of dumping `mood_valence: 0.22, mood_arousal: 0.84` into memory. She feels "restless but not in a good way." She journals "something felt off tonight." The numbers never reach her conscious memory.

### Event Translation (internal_conflict → journal entry)

The current `internal_conflict` event creates a memory entry like:
```
Emotional tension — arousal 84% but valence only 22%.
```

After this task, the `output.py` internal_conflict handler translates before writing:

```python
# pipeline/output.py — when internal conflict detected

async def handle_internal_conflict(self, conflict, drives):
    # Translate to felt experience
    feeling = translate_conflict_to_feeling(conflict, drives)
    # e.g. "Something felt off — I was restless and unsettled but couldn't name why."
    
    # Append to today's journal as natural language
    await append_journal(feeling)
    
    # Do NOT store raw numbers in conscious memory
    # Raw data stays in SQLite cycle_log for operational purposes
```

---

## Migration Strategy

### Phase 1: Create memory/ directory structure + file writers
- Create `memory/` tree
- Implement `MemoryWriter` class: `append_journal()`, `update_visitor()`, `write_browse()`, `write_reflection()`
- Implement `MemoryReader` class: `read_file()`, `grep_memory()`, `list_files()`
- All writes are append-only during waking hours
- Implement sleep write methods: `annotate_visitor()`, `rewrite_identity()`, `archive_old()`

### Phase 2: Translation layer
- `translate_drives_to_feelings()` in `prompt/self_context.py`
- `translate_conflict_to_feeling()` in `pipeline/output.py`
- Every path that currently writes machine-readable state to memory now goes through translation
- Audit every `journal_write` call — ensure no raw numbers reach MD files

### Phase 3: Replace hippocampus retrieval
- Rewrite `pipeline/hippocampus.py` to read from MD files instead of SQLite memory tables
- grep-based topic recall replaces vector similarity search
- Visitor memory = read their file
- Recent context = read last 2 journal files
- Self-context reads `memory/self/identity.md`

### Phase 4: Migrate sleep system
- Sleep phases read/write MD files for consolidation
- Sleep can add annotations to visitor files (marked as "[sleep note]")
- Sleep rewrites `memory/self/` files based on behavioral data
- Sleep creates `memory/reflections/{date}-night.md`

### Phase 5: Remove deprecated memory tables
- Drop SQLite tables that are now MD-backed: journal_entries, visitor_traits_narrative, totems_narrative
- Keep SQLite tables for: drives_state, cycle_log, events, actions, parameters, costs, habits, inhibitions
- Keep cold_search/embeddings as OPTIONAL enhancement layer (grep is primary, embeddings for fuzzy recall if needed later)

---

## What Stays in SQLite (Unconscious)

| Table | Why |
|-------|-----|
| drives_state / drives_state_history | Machine-level drive values — she feels these, doesn't read them |
| events / inbox | Event queue — operational pipeline |
| cycle_log | Per-cycle diagnostics — operator tool, not her memory |
| llm_costs | Cost tracking — operator concern |
| actions_log | Action history — feeds self-model, not conscious recall |
| self_parameters | Cognitive parameters — her "biology" |
| dynamic_actions | Action registry — her "body's capabilities" |
| habits / inhibitions | Behavioral machinery — she feels habits, doesn't see the table |
| content_pool | Content queue — pipeline operational data |
| browse_history | Operational log (she also writes the experience to MD) |
| visitors (core table) | Channel routing, IDs — operational. Her *memory* of them is in MD |
| daily_summaries | Lightweight index for sleep — operational |
| epistemic_curiosities | Curiosity tracking — she feels curious, doesn't read the table |

---

## What Moves to MD (Conscious)

| Current SQLite | New MD Location |
|----------------|-----------------|
| Journal entries (text content) | `memory/journal/{date}.md` |
| Visitor trait narratives | `memory/visitors/{source_key}.md` |
| Totem descriptions | `memory/visitors/{source_key}.md` (under "## Symbolic Objects") |
| Sleep reflections (text) | `memory/reflections/{date}-{phase}.md` |
| Self-narrative | `memory/self/identity.md` |
| Thread content | `memory/threads/{slug}.md` |
| Day memory moments (text) | `memory/journal/{date}.md` (significant moments marked) |

---

## Connection to TASK-069

When real-world actions land, they write to MD:

```
browse_web result → memory/browse/{date}-{slug}.md
                  → memory/journal/{date}.md (brief mention)

Telegram conversation → memory/journal/{date}.md (what was said)
                      → memory/visitors/tg-{user}.md (updated impressions)

X interaction → memory/journal/{date}.md
              → memory/visitors/x-{handle}.md

Web visitor → memory/journal/{date}.md
            → memory/visitors/web-{token}.md
```

Her memory of browsing the web, talking to people on Telegram, and posting on X all flow into the same readable, greppable, natural-language files. She can recall "what did I learn about Bandai prints" and grep brings back her browse notes AND the conversation with Tanaka where he mentioned them.

---

## Scope

### Files to create:
- `memory/` directory tree (empty on first boot, populated by seed or first cycle)
- `memory_writer.py` — MemoryWriter class (append journal, update visitor, write browse, write reflection)
- `memory_reader.py` — MemoryReader class (read file, grep memory, list files)
- `memory_translator.py` — Numbers-to-feelings translation functions
- `tests/test_memory_writer.py`
- `tests/test_memory_reader.py`
- `tests/test_memory_translator.py`
- `tests/test_grep_recall.py`

### Files to modify:
- `pipeline/hippocampus.py` — rewrite retrieval to read MD files + grep
- `pipeline/output.py` — route experiential writes to MD, translate internal_conflicts
- `prompt/self_context.py` — translate drives to felt experience
- `sleep.py` (or `sleep/` phases) — consolidation writes to MD
- `pipeline/hippocampus_write.py` — visitor updates write to MD
- `pipeline/body.py` — journal_write action appends to MD
- `pipeline/day_memory.py` — significant moments append to journal MD
- `seed.py` — create initial memory/ structure

### Files NOT to touch:
- `pipeline/cortex.py` (prompt assembly unchanged — it receives memory context from hippocampus)
- `pipeline/basal_ganglia.py`
- `pipeline/hypothalamus.py`
- `db/state.py`, `db/analytics.py`, `db/events.py` (SQLite stays for operational data)
- `simulate.py`

---

## Safety

- **Backup:** `memory/` directory backed up alongside SQLite DB in `deploy/backup.sh`
- **Git-trackable:** Memory files can optionally be git-committed for history/audit
- **Size:** At ~500 words/day journal + visitors, memory/ stays under 10MB/year
- **Corruption:** MD files are plaintext — no corruption risk, always readable
- **Migration rollback:** Keep SQLite memory tables read-only for 30 days after migration, can revert if needed

---

## Definition of Done

1. `memory/` directory structure created and populated from first cycle
2. Journal entries written as natural language to `memory/journal/{date}.md`
3. Visitor memories in `memory/visitors/{source_key}.md`
4. Browse results in `memory/browse/{date}-{slug}.md`
5. Sleep writes reflections to `memory/reflections/`
6. Sleep can annotate (not edit) visitor files and rewrite self/ files
7. NO raw numbers, percentages, or drive values appear in any MD file
8. Internal conflict events translated to felt experience before journaling
9. Hippocampus retrieves from MD files via grep + file reads
10. grep-based topic recall works across all memory directories
11. Self-context translates drives to natural language feelings
12. SQLite retains all operational/unconscious data unchanged
13. 50-cycle test: no machine-readable state leaks into MD files
14. Memory files are human-readable — operator can open any file and understand her inner life
