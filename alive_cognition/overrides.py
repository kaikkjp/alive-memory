"""Hard override rules for force-high and force-low salience.

Deterministic keyword/pattern checks.  No ML, no LLM calls.
First matching rule wins.  High overrides are checked before low.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from alive_cognition.types import EventSchema, SalienceBand

# ── Constants ────────────────────────────────────────────────────────────

_SAFETY_KEYWORDS: frozenset[str] = frozenset(
    {"emergency", "danger", "security breach", "attack", "vulnerability"}
)

_HEARTBEAT_PATTERNS: frozenset[str] = frozenset({"heartbeat", "ping", "health check", "keepalive"})

_REQUEST_PATTERN: re.Pattern[str] = re.compile(
    r"\bplease\b.*\b(do|make|show|tell|give|help|find|create|update|delete|run)\b",
    re.IGNORECASE,
)


# ── Result ───────────────────────────────────────────────────────────────


@dataclass
class OverrideResult:
    """Result of override check."""

    applied: bool = False
    force_band: SalienceBand | None = None
    reason: str = ""


# ── Public API ───────────────────────────────────────────────────────────


def check_overrides(event: EventSchema) -> OverrideResult:
    """Check hard override rules.  Returns OverrideResult.

    Force HIGH (PRIORITIZE):
      - direct user question (actor=="user" and content ends with "?"
        or matches request patterns)
      - safety risk keywords
      - host-provided salience override: metadata["salience"] > 0.7
      - explicit command: content starts with "/"
        or contains "please" + verb pattern

    Force LOW (DROP):
      - exact duplicate: metadata["_duplicate"] is True
      - heartbeat: event_type is SYSTEM and content matches heartbeat patterns
      - known spam: metadata["spam"] is True

    First matching rule wins.  High overrides checked before low.
    """
    result = _check_high(event)
    if result is not None:
        return result

    result = _check_low(event)
    if result is not None:
        return result

    return OverrideResult()


# ── Internals ────────────────────────────────────────────────────────────


def _check_high(event: EventSchema) -> OverrideResult | None:
    content = event.content.strip()
    content_lower = content.lower()

    # Direct user question
    if event.actor == "user" and content.endswith("?"):
        return OverrideResult(
            applied=True,
            force_band=SalienceBand.PRIORITIZE,
            reason="direct user question",
        )

    # Request pattern (please + verb)
    if event.actor == "user" and _REQUEST_PATTERN.search(content):
        return OverrideResult(
            applied=True,
            force_band=SalienceBand.PRIORITIZE,
            reason="user request pattern detected",
        )

    # Safety keywords
    for keyword in _SAFETY_KEYWORDS:
        if keyword in content_lower:
            return OverrideResult(
                applied=True,
                force_band=SalienceBand.PRIORITIZE,
                reason=f"safety keyword: {keyword}",
            )

    # Host-provided salience override
    meta_salience = event.metadata.get("salience")
    if meta_salience is not None and float(meta_salience) > 0.7:
        return OverrideResult(
            applied=True,
            force_band=SalienceBand.PRIORITIZE,
            reason="host salience override > 0.7",
        )

    # Explicit command (slash command)
    if content.startswith("/"):
        return OverrideResult(
            applied=True,
            force_band=SalienceBand.PRIORITIZE,
            reason="explicit slash command",
        )

    return None


def _check_low(event: EventSchema) -> OverrideResult | None:
    content_lower = event.content.strip().lower()

    # Exact duplicate flag
    if event.metadata.get("_duplicate") is True:
        return OverrideResult(
            applied=True,
            force_band=SalienceBand.DROP,
            reason="exact duplicate",
        )

    # Heartbeat / keepalive
    if event.event_type.value == "system":
        for pattern in _HEARTBEAT_PATTERNS:
            if pattern in content_lower:
                return OverrideResult(
                    applied=True,
                    force_band=SalienceBand.DROP,
                    reason=f"heartbeat pattern: {pattern}",
                )

    # Known spam
    if event.metadata.get("spam") is True:
        return OverrideResult(
            applied=True,
            force_band=SalienceBand.DROP,
            reason="flagged as spam",
        )

    return None
