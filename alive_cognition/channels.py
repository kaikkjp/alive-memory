"""Four deterministic channel scorers for multi-channel salience.

Each scorer is a pure function: (event, context) -> (score, reasons).
No LLM calls, no embeddings, no side effects.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from alive_cognition.types import EventSchema
from alive_memory.types import DriveState, EventType, MoodState

# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------


@dataclass
class ChannelContext:
    """Ambient state passed to every channel scorer."""

    active_goals: list[str] = field(default_factory=list)
    identity_keywords: list[str] = field(default_factory=list)
    current_drives: DriveState | None = None
    current_mood: MoodState | None = None


# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

_STOP_WORDS: frozenset[str] = frozenset(
    [
        "i",
        "me",
        "my",
        "myself",
        "we",
        "our",
        "ours",
        "ourselves",
        "you",
        "your",
        "yours",
        "yourself",
        "yourselves",
        "he",
        "him",
        "his",
        "himself",
        "she",
        "her",
        "hers",
        "herself",
        "it",
        "its",
        "itself",
        "they",
        "them",
        "their",
        "theirs",
        "themselves",
        "what",
        "which",
        "who",
        "whom",
        "this",
        "that",
        "these",
        "those",
        "am",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "having",
        "do",
        "does",
        "did",
        "doing",
        "a",
        "an",
        "the",
        "and",
        "but",
        "if",
        "or",
        "because",
        "as",
        "until",
        "while",
        "of",
        "at",
        "by",
        "for",
        "with",
        "about",
        "against",
        "between",
        "through",
        "during",
        "before",
        "after",
        "above",
        "below",
        "to",
        "from",
        "up",
        "down",
        "in",
        "out",
        "on",
        "off",
        "over",
        "under",
        "again",
        "further",
        "then",
        "once",
        "here",
        "there",
        "when",
        "where",
        "why",
        "how",
        "all",
        "both",
        "each",
        "few",
        "more",
        "most",
        "other",
        "some",
        "such",
        "no",
        "nor",
        "not",
        "only",
        "own",
        "same",
        "so",
        "than",
        "too",
        "very",
        "s",
        "t",
        "can",
        "will",
        "just",
        "don",
        "should",
        "now",
        "d",
        "ll",
        "m",
        "o",
        "re",
        "ve",
        "y",
        "ain",
        "aren",
        "couldn",
        "didn",
        "doesn",
        "hadn",
        "hasn",
        "haven",
        "isn",
        "ma",
        "mightn",
        "mustn",
        "needn",
        "shan",
        "shouldn",
        "wasn",
        "weren",
        "won",
        "wouldn",
        "could",
        "would",
        "shall",
        "may",
        "might",
        "must",
        "also",
        "still",
        "already",
        "yet",
        "even",
        "really",
        "actually",
        "just",
        "like",
        "well",
        "yeah",
        "yes",
        "ok",
        "okay",
        "sure",
        "right",
        "got",
        "get",
        "let",
        "know",
        "think",
        "going",
        "go",
        "see",
        "look",
        "want",
        "need",
        "come",
        "take",
        "make",
        "say",
        "said",
    ]
)

_NUMBER_RE: re.Pattern[str] = re.compile(r"\b\d[\d,./:%-]*\b")

_TIME_EXPR_RE: re.Pattern[str] = re.compile(
    r"(?:in\s+\d+\s+(?:minute|hour|second|day)s?)"
    r"|(?:by\s+\d+:\d+)"
    r"|(?:before\s+\d+)",
    re.IGNORECASE,
)

# --- Keyword sets (frozenset for O(1) lookup) ---

_REQUEST_PATTERNS: frozenset[str] = frozenset({"please", "can you", "tell me", "show me", "help"})

_PREFERENCE_PATTERNS: tuple[str, ...] = (
    "i like",
    "i prefer",
    "i always",
    "i never",
    "my favorite",
)

_POSITIVE_AFFECT: frozenset[str] = frozenset(
    {
        "happy",
        "love",
        "great",
        "amazing",
        "thank",
        "thanks",
        "awesome",
        "excellent",
        "wonderful",
        "appreciate",
    }
)

_NEGATIVE_AFFECT: frozenset[str] = frozenset(
    {
        "angry",
        "frustrated",
        "hate",
        "terrible",
        "awful",
        "disappointed",
        "upset",
        "worried",
        "scared",
        "hurt",
        "sorry",
        "fail",
        "failed",
        "error",
        "broken",
        "crash",
    }
)

_INTENSITY_MARKERS: frozenset[str] = frozenset(
    {
        "very",
        "extremely",
        "absolutely",
        "incredibly",
        "never",
        "always",
        "worst",
        "best",
    }
)

_RISK_KEYWORDS: frozenset[str] = frozenset(
    {
        "danger",
        "emergency",
        "urgent",
        "critical",
        "security",
        "password",
        "delete",
        "destroy",
        "kill",
        "attack",
    }
)

_MONEY_KEYWORDS: frozenset[str] = frozenset(
    {
        "money",
        "cost",
        "price",
        "pay",
        "payment",
        "bill",
        "budget",
        "expensive",
        "free",
        "discount",
        "$",
    }
)

_TIME_PRESSURE: frozenset[str] = frozenset(
    {
        "now",
        "asap",
        "immediately",
        "urgent",
        "hurry",
        "deadline",
        "today",
        "tonight",
        "right away",
    }
)

_ERROR_INDICATORS: frozenset[str] = frozenset(
    {
        "error",
        "exception",
        "failed",
        "timeout",
        "crash",
        "down",
        "broken",
        "502",
        "503",
        "500",
        "404",
    }
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _tokenize(content: str) -> list[str]:
    """Split content into lowercase words stripped of punctuation."""
    return [w.lower().strip(".,!?;:'\"()[]{}") for w in content.split() if w]


def _words_set(content: str) -> set[str]:
    """Unique lowercase words from content."""
    return set(_tokenize(content))


def _content_contains_any(content_lower: str, patterns: frozenset[str]) -> list[str]:
    """Return which patterns appear in content (substring match)."""
    return [p for p in patterns if p in content_lower]


# ---------------------------------------------------------------------------
# Channel 1: Relevance
# ---------------------------------------------------------------------------


def score_relevance(event: EventSchema, context: ChannelContext) -> tuple[float, list[str]]:
    """Does this matter to active goals, identity, drives, or is it actionable?"""
    score = 0.0
    reasons: list[str] = []
    content_lower = event.content.lower()

    # User interaction is inherently relevant
    if event.actor == "user":
        score += 0.3
        reasons.append("user interaction (+0.30)")
    # Conversation events carry more relevance than system/sensor events
    if event.event_type == EventType.CONVERSATION:
        score += 0.15
        reasons.append("conversation event (+0.15)")

    # Goal keyword matching
    if context.active_goals:
        goal_matches = 0
        matched_goals: list[str] = []
        for goal in context.active_goals:
            goal_words = goal.lower().split()
            if any(gw in content_lower for gw in goal_words):
                goal_matches += 1
                matched_goals.append(goal)
        if goal_matches > 0:
            boost = min(0.6, goal_matches * 0.2)
            score += boost
            reasons.append(f"goal match: {', '.join(matched_goals)} (+{boost:.2f})")

    # Identity keyword matching
    if context.identity_keywords and any(
        kw.lower() in content_lower for kw in context.identity_keywords
    ):
        score += 0.15
        reasons.append("identity keyword match (+0.15)")

    # Drive alignment: high-deficit drives matching content
    if context.current_drives:
        drive_map = {
            "curiosity": context.current_drives.curiosity,
            "social": context.current_drives.social,
            "expression": context.current_drives.expression,
            "rest": context.current_drives.rest,
        }
        for drive_name, level in drive_map.items():
            if level > 0.7 and drive_name in content_lower:
                score += 0.15
                reasons.append(f"high-deficit drive '{drive_name}' ({level:.2f}) (+0.15)")

    # Actionability: question or request
    if event.content.rstrip().endswith("?"):
        score += 0.25
        reasons.append("explicit question (+0.25)")
    elif any(p in content_lower for p in _REQUEST_PATTERNS):
        score += 0.25
        reasons.append("request/command pattern (+0.25)")

    return _clamp(score), reasons


# ---------------------------------------------------------------------------
# Channel 2: Surprise
# ---------------------------------------------------------------------------


def score_surprise(event: EventSchema, context: ChannelContext) -> tuple[float, list[str]]:
    """How novel is this, and would storing it improve future decisions?"""
    content = event.content
    reasons: list[str] = []

    words = content.split()
    word_count = len(words)

    # Short content baseline
    if word_count < 3:
        return 0.05, ["short content baseline (0.05)"]

    # --- Information density: content word ratio ---
    tokens = _tokenize(content)
    content_words = [w for w in tokens if w not in _STOP_WORDS]
    content_ratio = len(content_words) / max(1, len(tokens))
    density_contrib = content_ratio * 0.3
    reasons.append(f"info density {content_ratio:.2f} (*0.3={density_contrib:.2f})")

    # --- Average content word length ---
    avg_len = 0.0
    if content_words:
        avg_len = sum(len(w) for w in content_words) / len(content_words)
    length_signal = min(1.0, max(0.0, (avg_len - 3) / 5))
    length_contrib = length_signal * 0.2
    reasons.append(
        f"avg word len {avg_len:.1f} -> signal {length_signal:.2f} (*0.2={length_contrib:.2f})"
    )

    # --- Numbers/dates ---
    number_count = len(_NUMBER_RE.findall(content))
    number_signal = min(1.0, number_count * 0.2)
    number_contrib = number_signal * 0.1
    if number_count > 0:
        reasons.append(
            f"{number_count} numbers -> signal {number_signal:.2f} (*0.1={number_contrib:.2f})"
        )

    # --- Unique word ratio ---
    unique_ratio = len(set(t.lower() for t in tokens)) / max(1, len(tokens))
    unique_contrib = unique_ratio * 0.2
    reasons.append(f"unique ratio {unique_ratio:.2f} (*0.2={unique_contrib:.2f})")

    # --- Named entity proxy: capitalized words not at sentence start ---
    sentences = content.split(".")
    cap_count = 0
    for sentence in sentences:
        sentence_words = sentence.strip().split()
        # Skip the first word of each sentence
        for w in sentence_words[1:]:
            if w and w[0].isupper() and w.lower() not in _STOP_WORDS:
                cap_count += 1
    entity_signal = min(1.0, cap_count * 0.15)
    entity_contrib = entity_signal * 0.1
    if cap_count > 0:
        reasons.append(
            f"{cap_count} entity-like caps -> signal {entity_signal:.2f} (*0.1={entity_contrib:.2f})"
        )

    score = density_contrib + length_contrib + number_contrib + unique_contrib + entity_contrib

    # --- Preference revelation bonus ---
    content_lower = content.lower()
    if any(p in content_lower for p in _PREFERENCE_PATTERNS):
        score += 0.15
        reasons.append("preference revelation (+0.15)")

    return _clamp(score), reasons


# ---------------------------------------------------------------------------
# Channel 3: Impact
# ---------------------------------------------------------------------------


def score_impact(event: EventSchema, context: ChannelContext) -> tuple[float, list[str]]:
    """How emotionally, socially, economically, or safety-relevant?"""
    score = 0.0
    reasons: list[str] = []
    content_lower = event.content.lower()
    words = _words_set(event.content)

    has_intensity = bool(words & _INTENSITY_MARKERS)

    # Positive affect
    pos_hits = words & _POSITIVE_AFFECT
    if pos_hits:
        score += 0.15
        reasons.append(f"positive affect ({', '.join(sorted(pos_hits))}) (+0.15)")

    # Negative affect (weighted higher)
    neg_hits = words & _NEGATIVE_AFFECT
    if neg_hits:
        score += 0.2
        reasons.append(f"negative affect ({', '.join(sorted(neg_hits))}) (+0.20)")

    # Risk/safety
    risk_hits = words & _RISK_KEYWORDS
    if risk_hits:
        score += 0.4
        reasons.append(f"risk/safety ({', '.join(sorted(risk_hits))}) (+0.40)")

    # Money/value
    money_hits = words & _MONEY_KEYWORDS
    if "$" in content_lower:
        money_hits = money_hits | {"$"}
    if money_hits:
        score += 0.15
        reasons.append(f"money/value ({', '.join(sorted(money_hits))}) (+0.15)")

    # Intensity multiplier (applied after additive signals)
    if has_intensity and score > 0:
        old_score = score
        score *= 1.3
        matched_markers = sorted(words & _INTENSITY_MARKERS)
        reasons.append(
            f"intensity markers ({', '.join(matched_markers)}) "
            f"(*1.3: {old_score:.2f} -> {score:.2f})"
        )

    return _clamp(score), reasons


# ---------------------------------------------------------------------------
# Channel 4: Urgency
# ---------------------------------------------------------------------------


def score_urgency(event: EventSchema, context: ChannelContext) -> tuple[float, list[str]]:
    """Does delayed response reduce value?"""
    score = 0.0
    reasons: list[str] = []
    content_lower = event.content.lower()
    words = _words_set(event.content)

    # Event type baseline
    if event.event_type == EventType.SYSTEM:
        # Systems can wait -- no baseline boost
        reasons.append("system event (baseline 0.0)")
    elif event.event_type == EventType.CONVERSATION:
        score += 0.15
        reasons.append("conversation event (baseline +0.15)")

    # Time pressure keywords (handle multi-word "right away" separately)
    time_hits = words & (_TIME_PRESSURE - {"right away"})
    if "right away" in content_lower:
        time_hits = time_hits | {"right away"}
    if time_hits:
        score += 0.3
        reasons.append(f"time pressure ({', '.join(sorted(time_hits))}) (+0.30)")

    # Time expressions (regex)
    time_matches = _TIME_EXPR_RE.findall(event.content)
    if time_matches:
        score += 0.2
        reasons.append(f"time expression ({time_matches[0]!r}) (+0.20)")

    # Error/failure indicators
    error_hits = words & _ERROR_INDICATORS
    if error_hits:
        score += 0.2
        reasons.append(f"error indicators ({', '.join(sorted(error_hits))}) (+0.20)")

    # User question -- implicit time pressure (user is waiting)
    if event.actor == "user" and "?" in event.content:
        score += 0.15
        reasons.append("user question -- waiting for response (+0.15)")

    return _clamp(score), reasons
