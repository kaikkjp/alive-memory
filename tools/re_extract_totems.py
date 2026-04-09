"""Re-extract totems from cold_memory raw turns using improved prompt.

Reads raw conversation turns from prepared instance DBs, runs a better
fact extraction prompt, and replaces the totems table. No re-ingest needed.

Usage:
    python tools/re_extract_totems.py \
        --prepared-dir benchmarks/academic/prepared/longmemeval/alive_v3/longmemeval/alive \
        --instances 0-19 \
        --output-dir benchmarks/academic/prepared/longmemeval/alive_v4
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sqlite3
import sys
import time
from pathlib import Path

_REPO_ROOT = str(Path(__file__).resolve().parents[1])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

EXTRACT_PROMPT = """\
Extract every concrete fact from this conversation turn. Return a JSON object:

{{"totems": [
  {{"entity": "<subject>", "context": "<specific fact with exact values>", "weight": <0.0-1.0>, "category": "<cat>"}}
]}}

Rules:
- Entity = the subject (person, thing, place, event)
- Context = the SPECIFIC fact. Include exact numbers, dates, amounts, names, locations.
  BAD:  "blood pressure — Managing blood pressure is important"
  GOOD: "blood pressure — User's reading is 140/90, monitoring since February"
  BAD:  "Fitbit Inspire HR — A fitness tracker"
  GOOD: "Fitbit Inspire HR — Purchased on February 15th for step tracking"
- Category: one of "personal", "preference", "relationship", "location", "event", "temporal", "general"
- For temporal facts (dates, durations, sequences), use category "temporal"
- Weight: 0.8-1.0 for specific personal facts, 0.3-0.5 for general knowledge
- Skip generic advice/information the assistant gives unless the user confirms it applies to them
- Only extract facts clearly stated, do not infer

Conversation turn:
{content}

Session: {session_id}

Return ONLY valid JSON, no markdown fencing. If no facts, return {{"totems": []}}"""


async def extract_from_instance(
    instance_dir: Path,
    output_dir: Path,
    api_key: str,
    model: str = "gpt-4o-mini",
    base_url: str = "https://api.openai.com/v1",
) -> dict:
    """Re-extract totems for a single instance."""
    import openai

    client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url)

    # Copy instance to output
    out_instance = output_dir / instance_dir.name
    if out_instance.exists():
        shutil.rmtree(out_instance)
    shutil.copytree(str(instance_dir), str(out_instance))

    db_path = str(out_instance / "bench.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Read all raw turns from cold_memory
    rows = conn.execute(
        "SELECT content, session_id FROM cold_memory ORDER BY id"
    ).fetchall()

    print(f"  {instance_dir.name}: {len(rows)} turns to process")

    # Clear existing totems
    conn.execute("DELETE FROM totems")
    conn.commit()

    new_totems = 0
    errors = 0

    for i, row in enumerate(rows):
        content = row["content"]
        session_id = row["session_id"] or ""

        # Skip very short turns
        if len(content) < 20:
            continue

        prompt = EXTRACT_PROMPT.format(content=content, session_id=session_id)

        try:
            resp = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You extract concrete facts from conversations. Return only valid JSON."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=800,
                temperature=0,
            )
            text = resp.choices[0].message.content.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                if text.endswith("```"):
                    text = text[:-3]
                text = text.strip()

            data = json.loads(text)
            totems = data.get("totems", [])

            for totem in totems:
                entity = totem.get("entity", "").strip()
                if not entity:
                    continue
                conn.execute(
                    """INSERT INTO totems (entity, weight, context, category, source_session_id,
                       first_seen, last_referenced, first_seen_at, last_seen_at)
                       VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'), datetime('now'), datetime('now'))""",
                    (
                        entity,
                        float(totem.get("weight", 0.5)),
                        totem.get("context", ""),
                        totem.get("category", "general"),
                        session_id,
                    ),
                )
                new_totems += 1

        except json.JSONDecodeError:
            errors += 1
        except Exception as e:
            errors += 1
            if "rate" in str(e).lower():
                await asyncio.sleep(5)

        if (i + 1) % 50 == 0:
            conn.commit()
            print(f"    {i+1}/{len(rows)} turns, {new_totems} totems so far")

    conn.commit()

    # Update meta.json
    meta_path = out_instance / "meta.json"
    meta = json.loads(meta_path.read_text())
    meta["totem_re_extraction"] = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "model": model,
        "new_totem_count": new_totems,
        "errors": errors,
    }
    meta_path.write_text(json.dumps(meta, indent=2))

    # Checkpoint DB
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    for suffix in ("-wal", "-shm"):
        p = db_path + suffix
        if os.path.exists(p):
            os.remove(p)

    print(f"  {instance_dir.name}: done — {new_totems} totems (was {len(rows)} turns, {errors} errors)")
    return {"instance": instance_dir.name, "totems": new_totems, "errors": errors}


def parse_instance_range(s: str) -> list[int]:
    """Parse '0-19' or '0,5,10' into list of ints."""
    result = []
    for part in s.split(","):
        if "-" in part:
            a, b = part.split("-", 1)
            result.extend(range(int(a), int(b) + 1))
        else:
            result.append(int(part))
    return result


async def main():
    parser = argparse.ArgumentParser(description="Re-extract totems from prepared instances")
    parser.add_argument("--prepared-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--instances", default="0-19", help="Instance range e.g. '0-19' or '0,5,10'")
    parser.add_argument("--model", default="gpt-4o-mini")
    parser.add_argument("--base-url", default="https://api.openai.com/v1")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("OPENAI_API_KEY not set")
        sys.exit(1)

    prepared = Path(args.prepared_dir)
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)

    instance_ids = parse_instance_range(args.instances)
    instance_dirs = []
    for iid in instance_ids:
        d = prepared / f"instance_{iid:03d}"
        if d.exists():
            instance_dirs.append(d)
        else:
            print(f"Warning: {d} not found, skipping")

    print(f"Re-extracting totems for {len(instance_dirs)} instances")
    print(f"Model: {args.model}, Output: {output}\n")

    sem = asyncio.Semaphore(args.workers)

    async def bounded(d):
        async with sem:
            return await extract_from_instance(d, output, api_key, args.model, args.base_url)

    start = time.perf_counter()
    results = await asyncio.gather(*[bounded(d) for d in instance_dirs])
    elapsed = time.perf_counter() - start

    total_totems = sum(r["totems"] for r in results)
    total_errors = sum(r["errors"] for r in results)
    print(f"\nDone in {elapsed:.1f}s — {total_totems} totems across {len(results)} instances ({total_errors} errors)")


if __name__ == "__main__":
    asyncio.run(main())
