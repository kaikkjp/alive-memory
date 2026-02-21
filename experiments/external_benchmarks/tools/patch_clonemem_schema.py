#!/usr/bin/env python3
"""Patch CloneMemBench JSON schema drift for evaluator compatibility.

Maps `digital_trace_ids` to both:
- `media_ids` (qa_item-level expected by eval_oracle.py)
- `related_media_id` (evidence-level expected by auto metric script)
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def _patch_node(node: Any, drop_source: bool, stats: dict[str, int]) -> None:
    if isinstance(node, dict):
        if "digital_trace_ids" in node:
            mapped = _as_list(node["digital_trace_ids"])

            if "media_ids" not in node:
                node["media_ids"] = mapped
                stats["media_ids_added"] += 1
            if "related_media_id" not in node:
                node["related_media_id"] = mapped
                stats["related_media_id_added"] += 1

            if drop_source:
                node.pop("digital_trace_ids", None)
                stats["digital_trace_ids_removed"] += 1

            stats["digital_trace_nodes_seen"] += 1

        for value in node.values():
            _patch_node(value, drop_source=drop_source, stats=stats)
        return

    if isinstance(node, list):
        for item in node:
            _patch_node(item, drop_source=drop_source, stats=stats)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in-file", required=True, help="Input JSON path.")
    parser.add_argument("--out-file", required=True, help="Patched JSON output path.")
    parser.add_argument(
        "--drop-source",
        action="store_true",
        help="Remove `digital_trace_ids` after remapping.",
    )
    args = parser.parse_args()

    in_path = Path(args.in_file).resolve()
    out_path = Path(args.out_file).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with in_path.open("r", encoding="utf-8") as f:
        payload = json.load(f)

    stats = {
        "digital_trace_nodes_seen": 0,
        "media_ids_added": 0,
        "related_media_id_added": 0,
        "digital_trace_ids_removed": 0,
    }
    _patch_node(payload, drop_source=args.drop_source, stats=stats)

    with out_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(json.dumps({"out_file": str(out_path), "stats": stats}, indent=2))


if __name__ == "__main__":
    main()
