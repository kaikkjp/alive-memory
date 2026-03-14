"""Validation logic for eval cases and suites."""

from __future__ import annotations

from tools.evolve.stopwords import STOPWORDS
from tools.evolve.types import ConversationTurn, EvalCase, FailureCategory

from .loader import EvalSuite

VALID_CATEGORIES: set[str] = {c.value for c in FailureCategory}


def validate_case(case: EvalCase) -> list[str]:
    """Validate a single eval case.

    Returns a list of human-readable error strings.  An empty list means the
    case is valid.

    Checks performed:

    * ``id`` and ``category`` are present and non-empty.
    * ``category`` is one of the known :class:`FailureCategory` values.
    * ``conversation`` has at least 2 turns.
    * At least 1 query is defined.
    * Each ``ground_truth`` fact is atomic (heuristic: ``<= 2`` commas).
    * Each ``ground_truth`` fact is traceable to the conversation text.
    * Conversation turns are in chronological order (``time`` values sorted).
    * ``difficulty`` is between 1 and 10 inclusive.
    * ``time_gaps`` reference valid turn numbers (``after_turn <= max turn``).
    """
    errors: list[str] = []

    # id / category presence
    if not case.id:
        errors.append("Missing 'id'.")
    if not case.category:
        errors.append("Missing 'category'.")
    elif case.category not in VALID_CATEGORIES:
        errors.append(
            f"Unknown category '{case.category}'. "
            f"Valid: {sorted(VALID_CATEGORIES)}."
        )

    # conversation length
    if len(case.conversation) < 2:
        errors.append(
            f"Conversation has {len(case.conversation)} turn(s); need >= 2."
        )

    # queries
    if not case.queries:
        errors.append("No queries defined.")

    # ground_truth atomicity and traceability
    for qi, q in enumerate(case.queries):
        for fi, fact in enumerate(q.ground_truth):
            if fact.count(",") > 2:
                errors.append(
                    f"Query {qi} ground_truth[{fi}] has >2 commas — "
                    "may not be atomic."
                )
            if case.conversation and not fact_traceable_to_conversation(
                fact, case.conversation
            ):
                errors.append(
                    f"Query {qi} ground_truth[{fi}] '{fact}' not traceable "
                    "to conversation."
                )

    # chronological order
    times = [t.time for t in case.conversation]
    if times != sorted(times):
        errors.append("Conversation turns are not in chronological order.")

    # difficulty range
    if not (1 <= case.difficulty <= 10):
        errors.append(
            f"Difficulty {case.difficulty} outside valid range [1, 10]."
        )

    # time_gaps reference valid turns
    max_turn = max((t.turn for t in case.conversation), default=0)
    for gi, gap in enumerate(case.time_gaps):
        if gap.after_turn > max_turn:
            errors.append(
                f"time_gaps[{gi}].after_turn ({gap.after_turn}) exceeds "
                f"max turn ({max_turn})."
            )

    return errors


def validate_suite(suite: EvalSuite) -> dict[str, list[str]]:
    """Validate every case in every split.

    Returns a dict mapping ``case_id`` to its list of errors.  Only cases with
    at least one error are included; an empty dict means the suite is valid.
    """
    issues: dict[str, list[str]] = {}
    for split_cases in (suite.train, suite.held_out, suite.production):
        for case in split_cases:
            errs = validate_case(case)
            if errs:
                issues[case.id] = errs
    return issues


def fact_traceable_to_conversation(
    fact: str,
    conversation: list[ConversationTurn],
) -> bool:
    """Check that key tokens from *fact* appear somewhere in the conversation.

    Extracts meaningful tokens from the fact (lowercased, stopwords and short
    words removed) and checks whether at least 50 % of those tokens appear in
    the concatenated conversation text.
    """
    tokens = _extract_tokens(fact)
    if not tokens:
        # Nothing meaningful to check — treat as traceable.
        return True

    corpus = " ".join(t.content.lower() for t in conversation)
    found = sum(1 for tok in tokens if tok in corpus)
    return found / len(tokens) >= 0.5


def _extract_tokens(text: str) -> list[str]:
    """Extract meaningful lower-case tokens from *text*."""
    raw = text.lower().split()
    # Strip basic punctuation from each token.
    cleaned = [t.strip(".,;:!?\"'()[]{}") for t in raw]
    return [
        t
        for t in cleaned
        if t and len(t) > 2 and t not in STOPWORDS
    ]
