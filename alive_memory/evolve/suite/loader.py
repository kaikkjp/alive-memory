"""Load eval suites from directory structure."""

from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass, field
from typing import Any

from alive_memory.evolve.suite.manifest import read_manifest
from alive_memory.evolve.types import (
    ConversationTurn,
    EvalCase,
    EvalQuery,
    TimeGap,
)

_SEED_DIR = pathlib.Path(__file__).parent / "seed"


@dataclass
class EvalSuite:
    """An eval suite with train / held-out / production splits."""

    train: list[EvalCase] = field(default_factory=list)
    held_out: list[EvalCase] = field(default_factory=list)
    production: list[EvalCase] = field(default_factory=list)
    version: str = "unknown"


def load_suite(path: str) -> EvalSuite:
    """Load an eval suite from a directory.

    Expected layout::

        path/
          train/cases.jsonl + manifest.json
          held_out/cases.jsonl + manifest.json
          production/cases.jsonl + manifest.json

    Each line in ``cases.jsonl`` is a JSON-serialised :class:`EvalCase`.
    If ``production/`` does not exist or its ``cases.jsonl`` is empty the
    production split is simply left empty.

    The ``version`` field is read from the first manifest found.
    """
    root = pathlib.Path(path)
    if not root.is_dir():
        raise FileNotFoundError(f"Suite directory not found: {root}")

    train = _load_split(root / "train")
    held_out = _load_split(root / "held_out")
    production = _load_split(root / "production")

    # Resolve version from the first manifest that has one.
    version = "unknown"
    for split_name in ("train", "held_out", "production"):
        manifest = read_manifest(str(root / split_name / "manifest.json"))
        if manifest is not None:
            version = manifest.version
            break

    return EvalSuite(
        train=train,
        held_out=held_out,
        production=production,
        version=version,
    )


def _load_split(split_dir: pathlib.Path) -> list[EvalCase]:
    """Load cases from a split directory's ``cases.jsonl`` file."""
    cases_path = split_dir / "cases.jsonl"
    if not cases_path.is_file():
        return []

    cases: list[EvalCase] = []
    with open(cases_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            cases.append(_parse_case(data))
    return cases


def _parse_case(data: dict[str, Any]) -> EvalCase:
    """Parse a JSON dict into an :class:`EvalCase`.

    Handles nested :class:`ConversationTurn`, :class:`TimeGap`, and
    :class:`EvalQuery` objects.
    """
    conversation = [
        ConversationTurn(
            turn=t["turn"],
            time=t["time"],
            role=t["role"],
            content=t["content"],
        )
        for t in data.get("conversation", [])
    ]

    time_gaps = [
        TimeGap(
            after_turn=g["after_turn"],
            skip_to=g["skip_to"],
            consolidation_expected=g.get("consolidation_expected", True),
        )
        for g in data.get("time_gaps", [])
    ]

    queries = [
        EvalQuery(
            time=q["time"],
            query=q["query"],
            ground_truth=q.get("ground_truth", []),
            bonus_inferences=q.get("bonus_inferences", []),
            should_not_recall=q.get("should_not_recall", []),
            expected_emotional_weight=q.get("expected_emotional_weight"),
        )
        for q in data.get("queries", [])
    ]

    return EvalCase(
        id=data["id"],
        category=data["category"],
        difficulty=data["difficulty"],
        difficulty_axes=data.get("difficulty_axes", {}),
        tags=data.get("tags", []),
        conversation=conversation,
        time_gaps=time_gaps,
        queries=queries,
        metadata=data.get("metadata", {}),
    )


def load_seed_suite() -> EvalSuite:
    """Load the built-in seed suite shipped with the package."""
    return load_suite(str(_SEED_DIR))
