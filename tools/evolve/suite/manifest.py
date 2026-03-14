"""Manifest reading and writing for eval suite splits."""

from __future__ import annotations

import json
import pathlib
from dataclasses import asdict, dataclass


@dataclass
class SuiteManifest:
    """Metadata for a single eval-suite split."""

    version: str
    created: str  # ISO date
    last_updated: str  # ISO date
    case_count: int
    category_distribution: dict[str, int]  # category -> count


def read_manifest(path: str) -> SuiteManifest | None:
    """Read a ``manifest.json`` file.

    Returns ``None`` if the file does not exist or cannot be parsed.
    """
    p = pathlib.Path(path)
    if not p.is_file():
        return None
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        return SuiteManifest(
            version=data.get("version", "unknown"),
            created=data.get("created", ""),
            last_updated=data.get("last_updated", ""),
            case_count=data.get("case_count", 0),
            category_distribution=data.get("category_distribution", {}),
        )
    except (json.JSONDecodeError, KeyError):
        return None


def write_manifest(path: str, manifest: SuiteManifest) -> None:
    """Write a :class:`SuiteManifest` as ``manifest.json``."""
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(asdict(manifest), f, indent=2)
        f.write("\n")
