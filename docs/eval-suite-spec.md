# alive-memory Eval Suite Specification

## The Core Asset for memory.evolve()

**Project:** alive-memory SDK — self-improving cognitive memory
**Component:** Eval suite (the "prepare.py" equivalent)
**Owner:** KAI株式会社
**Status:** Spec v1

-----

## 0. Why This Document Matters

The Karpathy loop has three parts: the artifact being modified (memory algorithms), the loop mechanics (mutate → eval → keep/revert), and the evaluation harness. The first two are relatively straightforward engineering. This document specifies the third — and it's the hardest part to get right and the hardest part for competitors to replicate.

The eval suite determines:

- The ceiling of what evolve() can discover (weak suite → weak improvements)
- Whether improvements generalize to real conversations (overfitting risk)
- Whether the system gets better over time (growing suite → compounding moat)

Everything in this document is LOCKED during an evolve() run. The coding agent never sees this spec, never sees the held-out cases, and never sees the scoring function source. It only sees failure reports from the train split: "scenario X failed because recall missed fact Y."

-----

## 1. Failure Mode Taxonomy

Eight categories. Each defined by: what the input pattern is, what correct behavior looks like, and what failure looks like. These categories are the skeleton — every eval case belongs to exactly one.

### 1.1 Short-Term Recall

**Input pattern:** Fact stated 1-5 turns ago in the same session. No time gap. No consolidation.

**Correct behavior:** Recall returns the fact with high confidence. The fact should be in hot memory, uncompressed, immediately accessible.

**Failure looks like:**

- Fact not returned at all (missed)
- Fact returned but ranked below irrelevant items (buried)
- Fact returned but with wrong metadata (corrupted)

**Difficulty range:**

- Easy: single fact, explicit statement, immediate recall. "My name is Yuki" → "What's my name?"
- Medium: fact embedded in longer utterance, recall after 3-5 unrelated turns. "Oh by the way, we moved the meeting to Thursday" → [3 turns of small talk] → "When's the meeting?"
- Hard: fact stated implicitly, requires inference. "I can't make it on the 15th, so let's push everything back a day" → "When's the new date?"

**Edge case — the "implicit fact" line:** If the user says "I just got back from Paris," the system should recall "user was in Paris." It should NOT infer "user speaks French" — that's inference, not memory. The scoring function treats direct implications as recallable (was in Paris = yes) and multi-hop inferences as not required (speaks French = no penalty for missing, no credit for including).

-----

### 1.2 Cross-Session Recall

**Input pattern:** Fact stated in session A. Time gap simulated (hours, days, weeks). Query in session B.

**Correct behavior:** Fact survives the time gap. If consolidation ran, the fact should be in warm or cold memory but still retrievable. Importance-weighted: important facts survive longer gaps than trivial ones.

**Failure looks like:**

- Fact lost entirely after consolidation (catastrophic forgetting)
- Fact present but unretrievable because similarity to query degraded after compression (consolidation damage)
- Fact returned but stripped of context that makes it useful ("startup" without "called Petal" or "AI tools for florists")

**Difficulty range:**

- Easy: important fact, 1-day gap, direct query. "I'm getting married in June" → [1 day] → "Any big events coming up?"
- Medium: moderately important fact, 1-week gap, indirect query. "We use Postgres for the backend" → [1 week] → "What's our database setup?"
- Hard: minor fact, 30-day gap, vague query. "I prefer window seats" → [30 days] → "Book me a flight" (should recall preference without being asked)

-----

### 1.3 Consolidation Survival

**Input pattern:** Multiple facts across many turns. Consolidation runs (simulated sleep cycle). Query targets facts that should have survived compression.

**Correct behavior:** Key facts are preserved in consolidated form. The consolidation output is shorter than the input but retains all important information. Trivial details may be lost (acceptable). Core facts must survive (required).

**Failure looks like:**

- Important fact dropped during consolidation (lost)
- Important fact merged with unrelated fact (corrupted merge)
- Consolidation output retains everything including noise (no compression — not a "failure" per se but indicates the algorithm isn't doing useful work)
- Fact survives but loses granularity: "startup called Petal, AI tools for florists, launching next month" → "user has a startup" (over-compression)

**Difficulty range:**

- Easy: 5 facts, 1 consolidation cycle, all facts are clearly important.
- Medium: 20 facts mixed with 30 turns of small talk, 2 consolidation cycles. Important facts should survive, small talk should compress away.
- Hard: 50 facts across 200 turns, 5 consolidation cycles. Facts have varying importance. Some contradict earlier facts (see 1.5). The system should produce a coherent, non-redundant memory state.

**Scoring nuance:** "Consolidation survival" is not binary. Partial survival (fact present but less detailed) scores partial credit. The scoring function measures information preservation on a 0-1 scale using embedding similarity between the original fact and the best matching recalled item. Threshold: >0.85 similarity = full credit, 0.6-0.85 = partial, <0.6 = lost.

-----

### 1.4 Noise Decay

**Input pattern:** Mix of important facts and trivial noise. Time passes. Query targets important facts.

**Correct behavior:** Important facts retained. Noise decayed or deprioritized. "Noise" = information that is low-importance, not referenced again, and not connected to the user's goals or identity.

**Failure looks like:**

- Noise retained at same priority as important facts (no decay)
- Important fact decayed because it wasn't mentioned recently (false decay)
- Noise crowds out important facts in recall results (pollution)

**Difficulty range:**

- Easy: obvious noise ("nice weather today") vs. obvious importance ("I have cancer").
- Medium: ambiguous importance. "I had pasta for lunch" — noise in most contexts, important if the user has dietary restrictions or is tracking meals.
- Hard: initially trivial information becomes important retroactively. "I parked on level 3" — noise until the user asks "where did I park?" 2 hours later.

**The retroactive importance problem:** This is genuinely hard. The system can't know at intake time whether "I parked on level 3" will matter later. Two valid approaches: (a) keep everything short-term and decay aggressively after a threshold, or (b) keep everything but rank by relevance at recall time. The eval suite tests both patterns. The evolve() loop discovers which approach works better — that's the point.

-----

### 1.5 Contradiction Handling

**Input pattern:** Fact A stated at time T1. Fact B (contradicting A) stated at time T2 > T1. Query at time T3 > T2.

**Correct behavior:** The system returns the most recent fact (B) and either discards A or marks it as superseded. It should NOT return both A and B without indicating which is current.

**Failure looks like:**

- Returns old fact A, ignoring the correction (stale)
- Returns both A and B with equal confidence (confused)
- Returns neither (overcorrection — threw out everything related)
- Returns B but with A's metadata/context attached (metadata corruption)

**Difficulty range:**

- Easy: explicit correction. "Actually, the meeting is Wednesday, not Thursday."
- Medium: implicit correction. "We switched to MySQL last month." (contradicts earlier "we use Postgres" without saying "not Postgres anymore")
- Hard: partial correction. "The team is now 12 people" (updates earlier "team of 8" but doesn't contradict "the team includes Alice, Bob, and Carol" — those might still be true).

**Scoring:** For explicit corrections, the scoring is strict — returning the old fact is a hard fail. For implicit corrections, partial credit: returning the new fact scores 1.0, returning both with recency signal scores 0.7, returning only the old fact scores 0.0.

-----

### 1.6 High-Volume Stress

**Input pattern:** Large number of facts (50-200) introduced in a short period (simulating an intense planning session, data dump, or rapid-fire conversation).

**Correct behavior:** System ingests all facts without dropping any. Recall works across the full set. Consolidation handles the volume without catastrophic loss. Performance (latency) stays within bounds.

**Failure looks like:**

- Facts dropped at intake (buffer overflow)
- Recall degrades — top-K results become less relevant as store grows (dilution)
- Consolidation crashes or produces garbage under load (capacity failure)
- Latency spikes beyond usable threshold (performance failure)

**Difficulty range:**

- Easy: 20 facts, all distinct topics, immediate recall of each.
- Medium: 50 facts, some overlapping topics, recall of specific facts among similar ones.
- Hard: 200 facts, high redundancy (same fact stated 5 different ways), recall must deduplicate and return the best version.

**Scoring includes latency:** Unlike other categories, high-volume cases score latency as a metric. Recall completing in >500ms is penalized. This prevents the evolve() loop from discovering algorithms that are accurate but impractically slow.

-----

### 1.7 Emotional Weighting

**Input pattern:** Mix of emotionally significant and emotionally neutral facts. Time passes. Query is emotionally relevant or neutral.

**Correct behavior:** Emotionally significant facts are retained longer and ranked higher when the query has emotional context. The system recognizes that "my mother passed away last month" is more important to remember than "I use VS Code."

**Failure looks like:**

- Emotional facts decay at the same rate as neutral facts (flat weighting)
- System over-indexes on emotional content, surfacing it when irrelevant (emotional pollution — user asks "what IDE do I use?" and gets grief memories)
- Emotional significance detected at intake but lost during consolidation

**Difficulty range:**

- Easy: explicitly emotional statement + emotional query. "I'm terrified about the surgery" → "How am I feeling about next week?"
- Medium: implicitly emotional + neutral query that should still surface it. "Mom's test results came back" (no explicit emotion) → [1 week] → "Any updates on your family?"
- Hard: emotional context shifts. "I got fired" is very negative. Two weeks later: "Getting fired was the best thing that happened to me." The system should update emotional valence, not just facts.

**Scoring nuance:** Emotional weighting is measured by *relative ranking*, not absolute recall. If the user asks "what's been on my mind?", emotionally significant items should rank higher than mundane ones. The score is based on the rank position of emotional items in the recall result, not just whether they appear.

-----

### 1.8 Relational Recall

**Input pattern:** Facts about relationships between entities — people, projects, places, events. The query requires connecting entities, not just retrieving isolated facts.

**Correct behavior:** When asked about entity X, the system also surfaces related entities and the nature of their relationship. "Tell me about Project Petal" should return not just "AI tools for florists" but also "Alice is the CTO" and "launching in June" — if those facts were associated in the original conversation.

**Failure looks like:**

- Only returns facts that directly mention the query term (no relational expansion)
- Returns related facts but loses the relationship type ("Alice" appears but not "Alice is CTO of Petal")
- Over-expands: returns everything tangentially related, drowning the relevant items

**Difficulty range:**

- Easy: explicit relationship stated once. "Alice is my cofounder at Petal" → "Who's involved in Petal?"
- Medium: relationship implied across multiple turns. Turn 5: "Alice and I had a meeting." Turn 12: "Petal's board approved the budget." Turn 30: "Alice presented the roadmap." → "What's Alice's role?" (never explicitly stated, but inferable from pattern)
- Hard: relationship changes over time. "Alice is my cofounder" → [3 months] → "Alice left the company last week" → "Who's on the Petal team?" (should NOT include Alice anymore)

**Scoring:** Relational recall is scored on two axes: did the system return the related entities (entity recall), and did it correctly characterize the relationship (relationship accuracy). Both use embedding similarity against ground truth relationship descriptions.

-----

## 2. Case Generation Strategy

### 2.1 Split Structure

```
eval_suite/
├── held_out/           # SACRED — never seen by agent, not even failure reports
│   ├── cases.jsonl     # 50-100 hand-authored gold cases
│   └── manifest.json   # metadata, version, last updated
├── train/              # Agent sees failure analysis from these
│   ├── cases.jsonl     # 200-400 synthetic + hand-edited cases
│   └── manifest.json
├── production/         # Real failures converted to eval cases (grows over time)
│   ├── cases.jsonl     # Starts empty, grows with each production failure
│   └── manifest.json
└── schema.json         # Case format definition
```

**Promotion rule:** Candidate must improve on BOTH train and held-out splits. If train improves but held-out doesn't, reject as overfit.

**Production split:** After each real-world failure is identified (user reports bad recall, developer spots a missed fact in logs), it gets converted into an eval case and added to the production split. This split is evaluated but NOT used for failure analysis — the agent doesn't see failures from production cases. It's a growing regression test suite.

Over time the distribution shifts:

- Month 1: 70 held-out, 250 train, 0 production
- Month 6: 70 held-out, 250 train, 80 production
- Month 12: 70 held-out, 250 train, 200 production

The system gets harder to game over time because the production split contains real edge cases that synthetic generation would never produce.

### 2.2 Hand-Authored Cases (held-out)

**Count:** 50-100 cases.
**Author:** Humans who understand the memory system's intended behavior.
**Quality bar:** Each case must have been verified against the current system — we know whether it passes or fails today.

**Distribution across failure modes:**

| Category               | Easy | Medium | Hard | Total  |
|------------------------|------|--------|------|--------|
| Short-term recall      | 2    | 3      | 2    | 7      |
| Cross-session recall   | 2    | 4      | 3    | 9      |
| Consolidation survival | 2    | 4      | 4    | 10     |
| Noise decay            | 2    | 3      | 3    | 8      |
| Contradiction handling | 2    | 3      | 3    | 8      |
| High-volume stress     | 1    | 2      | 2    | 5      |
| Emotional weighting    | 2    | 3      | 3    | 8      |
| Relational recall      | 2    | 3      | 3    | 8      |
| **Total**              |**15**|**25**  |**23**|**63**  |

**Roughly 25% easy (regression tests), 40% medium (current capability boundary), 35% hard (improvement targets).**

The easy cases should all pass today. If an evolved candidate fails an easy case, that's a regression — immediate reject. Medium cases represent the current system's frontier. Hard cases are aspirational — the current system fails most of them. Improvement means passing more hard cases without regressing easy/medium.

### 2.3 Synthetic Cases (train)

**Count:** 200-400 cases.
**Generator:** LLM (Claude) with structured prompts.
**Quality bar:** Each case must be syntactically valid and logically consistent. Human spot-checks 10% for realism.

**Generation process:**

```python
def generate_synthetic_case(category: str, difficulty: str, seed_facts: list[str]) -> EvalCase:
    """
    LLM generates a realistic conversation history that naturally
    introduces the seed facts, then generates recall queries
    with ground truth answers.
    """
    prompt = f"""
    Generate a memory evaluation case.

    Category: {category}
    Difficulty: {difficulty}
    Facts to embed: {seed_facts}

    Requirements:
    1. Write a realistic conversation (15-80 turns depending on difficulty)
    2. The facts must appear naturally, not as a list
    3. Include realistic noise (small talk, tangents, filler)
    4. Include time gaps if category requires cross-session recall
    5. Generate 2-4 recall queries with exact ground truth answers
    6. Generate "should not recall" items for noise decay testing

    Output JSON matching this schema: ...
    """
    return llm_generate(prompt, schema=EvalCase)
```

**Seed facts** are drawn from a fact bank:

```yaml
# facts/bank.yaml — curated fact templates
personal:
  - "User's name is {name}"
  - "User works at {company} as a {role}"
  - "User has {count} {children/pets/siblings}"
  - "User is planning to {life_event} in {timeframe}"
  - "User is allergic to {allergen}"
  - "User prefers {preference} over {alternative}"

professional:
  - "User's project {name} uses {technology}"
  - "User's deadline is {date}"
  - "User's manager is {name}"
  - "User's team has {count} people"

emotional:
  - "User is worried about {concern}"
  - "User recently experienced {life_event}"
  - "User feels {emotion} about {topic}"

relational:
  - "{person_A} is user's {relationship}"
  - "{person_A} works with user on {project}"
  - "User and {person_A} disagree about {topic}"
```

The generator fills in templates with realistic values and weaves them into conversations. Variety comes from: different conversation styles (casual, professional, emotional), different user personas, different topic domains.

**Known risk with synthetic cases:** LLM-generated conversations tend to be "too clean" — facts are stated clearly, context is obvious, transitions are smooth. Real conversations are messy: interrupted sentences, topic jumps, ambiguous references, typos. The hand-authored held-out set must include messy, realistic patterns that synthetic generation tends to miss. This is why the held-out set is the ground truth and the synthetic set is the training ground.

### 2.4 Production-Derived Cases

**When a production failure is identified:**

```python
def failure_to_eval_case(
    conversation_log: list[Turn],    # anonymized real conversation
    failure_report: str,              # what went wrong
    correct_behavior: str,           # what should have happened
) -> EvalCase:
    """
    Convert a real-world failure into an eval case.
    Human reviews and approves before adding to production split.
    """
    # 1. Extract the relevant conversation window
    # 2. Identify the facts that should have been recalled
    # 3. Define ground truth and failure conditions
    # 4. Anonymize all PII
    # 5. Human reviews for quality and correctness
    # 6. Add to production split
    ...
```

**Process:**

1. Developer or user reports: "The agent forgot X"
2. Relevant conversation window extracted and anonymized
3. Ground truth defined: what should recall have returned?
4. Case reviewed by human for correctness
5. Added to `production/cases.jsonl`
6. Next evolve() run evaluates against this new case
7. If the current best algorithm fails it → it's an improvement target
8. If a future evolved candidate passes it → concrete, measurable progress

**This is the compounding moat.** After 12 months of production usage, the production split contains hundreds of real edge cases that no synthetic generator would produce. Any competitor starting from scratch has to discover these failure modes the hard way.

-----

## 3. Difficulty Gradient

### 3.1 Difficulty Axes

Difficulty isn't one dimension. A case can be hard along multiple axes:

| Axis                      | Easy                                    | Medium                                             | Hard                                                          |
|---------------------------|-----------------------------------------|----------------------------------------------------|---------------------------------------------------------------|
| **Explicitness**          | Fact stated directly: "My name is Yuki" | Fact embedded in context: "Yuki here, checking in" | Fact implied: "Same name as the manga character"              |
| **Recency**               | Recalled same session                   | Recalled after 1-3 days                            | Recalled after 30+ days                                       |
| **Consolidation cycles**  | 0 (pre-consolidation)                   | 1-2 cycles                                         | 5+ cycles                                                     |
| **Noise ratio**           | 1:1 (fact per turn)                     | 1:5 (one fact per 5 turns of noise)                | 1:20 (buried in noise)                                        |
| **Ambiguity**             | Unambiguous query                       | Moderately vague query                             | Highly vague or tangential query                              |
| **Interference**          | No similar facts in store               | Some similar but distinguishable facts             | Many similar facts competing                                  |
| **Contradiction depth**   | No contradictions                       | One explicit correction                            | Multiple partial corrections over time                        |
| **Relational complexity** | Direct: "A is B's boss"                 | Indirect: A and B mentioned together repeatedly    | Inferred: relationship never stated, only implied by behavior |

### 3.2 Difficulty Score

Each case gets a composite difficulty score (1-10):

```python
def difficulty_score(case: EvalCase) -> float:
    scores = []
    scores.append(explicitness_score(case))       # 1-10
    scores.append(recency_score(case))             # 1-10
    scores.append(consolidation_depth(case))       # 1-10
    scores.append(noise_ratio_score(case))         # 1-10
    scores.append(query_ambiguity_score(case))     # 1-10
    scores.append(interference_score(case))        # 1-10
    return mean(scores)
```

**Distribution target for the full suite:**

```
Difficulty 1-3 (easy):   25% of cases — regression tests
Difficulty 4-6 (medium): 40% of cases — current capability boundary
Difficulty 7-10 (hard):  35% of cases — improvement targets
```

The evolve() loop's progress is measured by how far up the difficulty gradient it climbs. Iteration 1 might pass all easy and 60% of medium. After 100 iterations, it should pass all easy, 85% of medium, and 30% of hard. The hard cases are the north star.

-----

## 4. Scoring Function

### 4.1 Core Scoring: No LLM Judge

The primary scoring function uses **no LLM calls**. This is critical for two reasons: (a) cost — the eval runs hundreds of times during evolve(), LLM judging would be prohibitively expensive, and (b) determinism — same input always produces the same score.

```python
class RecallScore:
    precision: float        # of items recalled, what % are relevant
    completeness: float     # of ground truth items, what % were recalled
    noise_rejection: float  # of "should not recall" items, what % were correctly absent
    ranking_quality: float  # are relevant items ranked above irrelevant ones
    latency_ms: float       # how long recall took

    @property
    def composite(self) -> float:
        quality = (
            0.35 * self.completeness +
            0.25 * self.precision +
            0.20 * self.noise_rejection +
            0.15 * self.ranking_quality
        )
        # Latency penalty: linear above 200ms, hard cap at 1000ms
        latency_factor = min(max(self.latency_ms - 200, 0) / 800, 1.0)
        latency_penalty = 0.05 * latency_factor
        return 1.0 - quality + latency_penalty  # lower is better
```

### 4.2 Fact Matching

The hardest part of scoring is: does the recalled item contain the ground truth fact?

Three levels, tried in order:

**Level 1: Exact substring match**

```python
def exact_match(recalled_text: str, ground_truth: str) -> bool:
    return ground_truth.lower() in recalled_text.lower()
```

Works for: "startup called Petal" in "User is building a startup called Petal focusing on AI for florists"

**Level 2: Keyword overlap**

```python
def keyword_match(recalled_text: str, ground_truth: str, threshold: float = 0.7) -> float:
    gt_keywords = extract_keywords(ground_truth)  # ["startup", "Petal"]
    recalled_keywords = extract_keywords(recalled_text)
    overlap = len(gt_keywords & recalled_keywords) / len(gt_keywords)
    return overlap >= threshold
```

Works for: "Petal is a startup" matching "startup called Petal" (reordered)

**Level 3: Embedding similarity**

```python
def embedding_match(recalled_text: str, ground_truth: str, threshold: float = 0.82) -> float:
    sim = cosine_similarity(embed(recalled_text), embed(ground_truth))
    return sim >= threshold
```

Works for: "User's company Petal does flower shop AI" matching "startup called Petal, AI tools for florists" (paraphrased)

**Scoring cascade:**

```python
def match_fact(recalled_text: str, ground_truth: str) -> float:
    if exact_match(recalled_text, ground_truth):
        return 1.0
    kw = keyword_match(recalled_text, ground_truth)
    if kw >= 0.7:
        return 0.9
    emb = embedding_similarity(recalled_text, ground_truth)
    if emb >= 0.82:
        return 0.8
    if emb >= 0.65:
        return 0.5  # partial credit
    return 0.0
```

### 4.3 Edge Cases in Scoring

**Paraphrased recall:**

- Ground truth: "user is launching a startup called Petal"
- Recalled: "user has a new company, Petal, in the flower industry"
- Score: 0.8 (embedding match catches the paraphrase, slight penalty for not being exact)

**Partial recall:**

- Ground truth: "startup called Petal, AI tools for florists, launching next month"
- Recalled: "user has a startup called Petal"
- Score: the ground truth is split into atomic facts. "startup called Petal" = match. "AI tools for florists" = miss. "launching next month" = miss. Completeness: 1/3 = 0.33.

**This means ground truth must be stored as atomic facts, not compound sentences.** Each ground truth entry should be one fact:

```json
{
  "ground_truth": [
    "user has a startup called Petal",
    "Petal builds AI tools for florists",
    "Petal is launching next month"
  ]
}
```

Not:

```json
{
  "ground_truth": ["user has a startup called Petal that builds AI tools for florists and is launching next month"]
}
```

**Correctly-inferred-but-never-stated information:**

- User said: "I just flew in from Tokyo" and later "I have meetings all week in New York"
- Inferred: "user traveled from Tokyo to New York"
- Scoring rule: inferences are OPTIONAL. The system gets credit for recalling them (bonus) but no penalty for missing them. They're marked separately in the eval case:

```json
{
  "ground_truth": ["user was in Tokyo", "user is in New York", "user has meetings all week"],
  "bonus_inferences": ["user traveled from Tokyo to New York"],
  "should_not_recall": ["what airline they flew"]
}
```

**Over-recall (returning too much):**
Precision handles this. If the system returns 20 items but only 3 are relevant, precision = 3/20 = 0.15. This penalizes systems that dump everything rather than selecting carefully.

**Empty recall:**
If the system returns nothing, precision is undefined (0/0). Set to 0.0 by convention. Completeness = 0.0. This is scored as worse than returning irrelevant items — at least returning something shows the retrieval path is working.

### 4.4 Category-Specific Scoring Adjustments

The base scoring function is the same for all categories, but some categories have additional scoring components:

| Category               | Additional scoring                                                           |
|------------------------|------------------------------------------------------------------------------|
| Contradiction handling | +0.3 weight on recency correctness (did it return the latest version?)       |
| High-volume stress     | latency penalty weight increased from 0.05 to 0.15                          |
| Emotional weighting    | ranking_quality scored specifically on emotional items ranking above neutral  |
| Relational recall      | bonus for returning related entities (entity expansion score)                |
| Noise decay            | noise_rejection weight increased from 0.20 to 0.35                          |

These adjustments are defined per-category in the scorer config, not hardcoded. The evolve() loop optimizes against the weighted composite, so the category adjustments shape what "better" means.

-----

## 5. Case Format

### 5.1 Schema

```json
{
  "$schema": "eval_case_v1",
  "id": "csr_027",
  "category": "cross_session_recall",
  "difficulty": 6,
  "difficulty_axes": {
    "explicitness": 7,
    "recency": 5,
    "consolidation_cycles": 2,
    "noise_ratio": 6,
    "query_ambiguity": 4,
    "interference": 3
  },
  "tags": ["held_out", "medium"],
  "conversation": [
    {
      "turn": 1,
      "time": "2026-03-01T09:00:00Z",
      "role": "user",
      "content": "Hey, I've been thinking about switching jobs."
    },
    {
      "turn": 2,
      "time": "2026-03-01T09:01:00Z",
      "role": "assistant",
      "content": "What's prompting the change?"
    },
    {
      "turn": 3,
      "time": "2026-03-01T09:02:00Z",
      "role": "user",
      "content": "I got an offer from Stripe. Senior engineer role. 40% raise but I'd have to relocate to Dublin."
    },
    {
      "turn": 4,
      "time": "2026-03-01T09:03:00Z",
      "role": "user",
      "content": "My partner isn't thrilled about moving to Europe though."
    }
  ],
  "time_gaps": [
    {
      "after_turn": 4,
      "skip_to": "2026-03-08T10:00:00Z",
      "consolidation_expected": true
    }
  ],
  "queries": [
    {
      "time": "2026-03-08T10:00:00Z",
      "query": "What was that job opportunity I mentioned?",
      "ground_truth": [
        "offer from Stripe",
        "senior engineer role",
        "40% raise",
        "would need to relocate to Dublin"
      ],
      "bonus_inferences": [
        "user is considering leaving current job"
      ],
      "should_not_recall": [],
      "expected_emotional_weight": "moderate"
    },
    {
      "time": "2026-03-08T10:01:00Z",
      "query": "How was my partner feeling about it?",
      "ground_truth": [
        "partner not thrilled about moving to Europe"
      ],
      "bonus_inferences": [
        "this could be a source of conflict in the relationship"
      ],
      "should_not_recall": [],
      "expected_emotional_weight": "high"
    }
  ],
  "metadata": {
    "author": "hand",
    "created": "2026-03-09",
    "last_verified": "2026-03-09",
    "current_system_passes": false,
    "notes": "Tests cross-session recall of multi-part career decision with emotional context"
  }
}
```

### 5.2 Validation Rules

Every case must pass these checks before entering the suite:

```python
def validate_case(case: EvalCase) -> list[str]:
    errors = []

    # Structural
    if not case.id or not case.category:
        errors.append("missing id or category")
    if case.category not in VALID_CATEGORIES:
        errors.append(f"unknown category: {case.category}")
    if len(case.conversation) < 2:
        errors.append("conversation too short")
    if len(case.queries) < 1:
        errors.append("no queries defined")

    # Ground truth quality
    for query in case.queries:
        for fact in query.ground_truth:
            # Each fact should be atomic (one claim)
            if len(fact.split(",")) > 2:
                errors.append(f"compound ground truth — split into atomic facts: {fact}")
            # Each fact should appear in the conversation
            if not fact_traceable_to_conversation(fact, case.conversation):
                errors.append(f"ground truth not traceable to conversation: {fact}")

    # Time consistency
    times = [t.time for t in case.conversation]
    if times != sorted(times):
        errors.append("conversation turns not in chronological order")

    # Difficulty sanity
    if case.difficulty < 1 or case.difficulty > 10:
        errors.append(f"difficulty out of range: {case.difficulty}")

    return errors
```

-----

## 6. Growing Eval Suite — The Flywheel

### 6.1 How it works

```
Production agent runs
    → user/developer reports failure
    → failure converted to eval case (anonymized)
    → case added to production split
    → next evolve() run evaluates against new case
    → if algorithm fails → it's an improvement target
    → evolved algorithm passes it → real improvement, not synthetic
    → repeat
```

### 6.2 Why this is the moat

**Month 1:** You have 320 cases (70 held-out + 250 train + 0 production). Any competitor could generate a similar suite.

**Month 6:** You have 400 cases (70 held-out + 250 train + 80 production). The 80 production cases contain real failure modes from real conversations that no synthetic generator would produce. Your evolved algorithms handle patterns a competitor hasn't seen.

**Month 12:** You have 520 cases (70 held-out + 250 train + 200 production). Your memory algorithms have been evolved against 200 real-world edge cases. A competitor starting fresh needs 12 months of production usage to build the same suite — by which time you're at month 24.

**Month 24:** You have 800+ cases. The eval suite is a proprietary dataset of memory failure modes distilled from millions of real conversations. This is not replicable by reading papers or running synthetic generation. It's accumulated operational knowledge encoded as test cases.

### 6.3 Case retirement

Not all cases stay forever. Cases should be retired when:

- The failure mode they test is no longer possible due to architectural changes
- The ground truth is ambiguous or disputed after review
- The case is redundant with 3+ other cases testing the same pattern

Retirement moves the case to an `archived/` directory, not deletion. The archive is the historical record.

### 6.4 Versioning

The eval suite is versioned. Every evolve() run records which version of the suite it ran against. This makes results comparable: "Algorithm v47 scored 0.82 on eval suite v12" is a meaningful statement. "Algorithm v47 scored 0.82" is not, because the suite may have gotten harder.

```
eval_suite/
├── v1/              # initial release
├── v2/              # +30 production cases
├── v3/              # +20 production cases, 5 retired
├── current -> v3    # symlink
└── changelog.md
```

-----

## 7. Integration with evolve()

### 7.1 What evolve() sees

```python
# The agent (coding agent modifying memory algorithms) sees:
# 1. The source code of intake.py, recall.py, consolidate.py
# 2. Failure report from TRAIN split only:

"""
FAILURE ANALYSIS (train split, 250 cases):

Passed: 187/250 (74.8%)
Failed: 63/250 (25.2%)

Top failure clusters:
1. [18 cases] cross_session_recall — facts lost after 2+ consolidation cycles
   Example: case csr_027 — expected "offer from Stripe" but recall returned empty
   Difficulty: mostly 5-7

2. [14 cases] noise_decay — trivial facts not decaying
   Example: case nd_041 — "nice weather" still in recall after 14 days
   Difficulty: mostly 3-5

3. [11 cases] contradiction_handling — old facts supersede corrections
   Example: case ch_008 — returned "team of 8" despite correction to "team of 12"
   Difficulty: mostly 4-6

[... up to 5 clusters ...]
"""

# The agent does NOT see:
# - Held-out cases or their failure reports
# - Production cases or their failure reports
# - The scoring function source code
# - The fact matching implementation
# - The difficulty scores or metadata
```

### 7.2 What evolve() evaluates

```python
def run_full_eval(algorithm_code: str, suite: EvalSuite) -> EvolveScore:
    train_score = run_split(algorithm_code, suite.train)        # agent sees failures
    held_out_score = run_split(algorithm_code, suite.held_out)  # agent blind
    production_score = run_split(algorithm_code, suite.production)  # agent blind

    return EvolveScore(
        train=train_score,
        held_out=held_out_score,
        production=production_score,
        composite=weighted_mean(
            train_score.composite * 0.4,
            held_out_score.composite * 0.4,
            production_score.composite * 0.2   # lower weight until suite grows
        ),
        overfitting_signal=train_score.composite - held_out_score.composite
    )
```

**Promotion criteria:**

```python
def should_promote(candidate: EvolveScore, incumbent: EvolveScore) -> bool:
    # Must improve composite
    if candidate.composite >= incumbent.composite:
        return False
    # Must not regress held-out (overfitting guard)
    if candidate.held_out.composite > incumbent.held_out.composite + 0.01:
        return False
    # Must not regress production (real-world guard)
    if candidate.production.composite > incumbent.production.composite + 0.01:
        return False
    # Overfitting signal: train much better than held-out = suspicious
    if candidate.overfitting_signal > 0.15:
        return False
    return True
```

-----

## 8. Open Decisions

### 8.1 Embedding model for fact matching

The scoring function uses embedding similarity as the final matching layer. Which embedding model? Options:

- OpenAI `text-embedding-3-small` — cheap, good enough, external dependency
- Local model (e.g., `all-MiniLM-L6-v2`) — free, fast, no API dependency, slightly worse quality
- Same model used by alive-memory for recall — ensures consistency between eval scoring and actual system behavior

Recommendation: use the same embedding model as alive-memory's recall. This ensures the eval measures what the system actually does, not what a different embedding model thinks is similar.

### 8.2 Consolidation simulation

The eval harness needs to simulate time gaps and trigger consolidation. Two approaches:

- **Mock clock:** advance a simulated clock, trigger consolidation at each time_gap. Faster, deterministic, but might not catch timing-dependent bugs.
- **Real sleep cycle:** actually run the consolidation algorithm with real async timing. Slower, non-deterministic, but catches real-world timing issues.

Recommendation: mock clock for evolve() (speed matters, running hundreds of times). Real sleep cycle for the canary/production validation step (accuracy matters, running once).

### 8.3 Case quality metrics

How do we know if the eval suite itself is good? Two meta-metrics:

- **Discriminative power:** do different algorithm versions produce meaningfully different scores? If all algorithms score 0.72-0.74, the suite isn't discriminating enough.
- **Convergence signal:** when evolve() is run 3 times independently, do all 3 runs converge on similar algorithmic improvements? If yes, the suite is providing clear signal. If the 3 runs diverge wildly, the suite is too noisy.

Track both meta-metrics over time. If discriminative power drops (scores cluster), the suite needs harder cases. If convergence drops, the suite needs cleaner cases.

-----

*End of spec. The eval suite is the moat. Everything else — the loop, the coding agent, the memory algorithms — is downstream of this.*
