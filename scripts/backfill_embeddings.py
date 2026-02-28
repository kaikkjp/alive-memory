#!/usr/bin/env python3
"""Backfill cold memory embeddings for existing conversation and cycle logs.

Run once after Phase 2 deployment to embed historical data:

    COLD_SEARCH_ENABLED=true OPENAI_API_KEY=sk-... python3 scripts/backfill_embeddings.py

Processes entries in batches of 50, sleeping 1s between batches to
respect OpenAI rate limits. Safe to interrupt and resume — already-embedded
entries are skipped via NOT EXISTS + dedupe guard.
"""

import asyncio
import os
import sys

# Add engine/ to path (TASK-101: engine/ contains all platform Python code)
_repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_repo_root, 'engine'))

# Force cold search enabled for backfill
os.environ['COLD_SEARCH_ENABLED'] = 'true'

import db  # noqa: E402
from pipeline.embed_cold import embed_new_cold_entries  # noqa: E402


async def main():
    """Run embedding backfill in batches until complete."""
    print("[Backfill] Initializing database...")
    await db.init_db()

    total_convos = 0
    total_monos = 0
    total_errors = 0
    batch_num = 0

    print("[Backfill] Starting embedding backfill...")
    print("  Press Ctrl+C to safely interrupt (progress is saved).\n")

    while True:
        batch_num += 1
        print(f"[Backfill] Batch {batch_num}...")

        stats = await embed_new_cold_entries()

        convos = stats['conversations_embedded']
        monos = stats['monologues_embedded']
        errors = stats['errors']

        total_convos += convos
        total_monos += monos
        total_errors += errors

        print(f"  Embedded: {convos} conversations, {monos} monologues, {errors} errors")
        print(f"  Running total: {total_convos} convos, {total_monos} monos, {total_errors} errors")

        # If nothing was embedded AND no errors, we're truly done.
        # If errors > 0 but nothing embedded, there are rows that failed —
        # don't claim "complete" as they may succeed on retry.
        if convos == 0 and monos == 0:
            if errors == 0:
                print("\n[Backfill] Complete — no more entries to embed.")
            else:
                print(f"\n[Backfill] Stopped — {errors} errors in last batch, "
                      f"0 successful. Check API key / network and re-run.")
            break

        # Rate limit pause between batches
        print("  Sleeping 1s for rate limits...")
        await asyncio.sleep(1)

    # Final stats
    total_embeddings = await db.get_cold_embedding_count()
    print(f"\n[Backfill] Final summary:")
    print(f"  Conversations embedded: {total_convos}")
    print(f"  Monologues embedded:    {total_monos}")
    print(f"  Errors:                 {total_errors}")
    print(f"  Total embeddings in DB: {total_embeddings}")

    await db.close_db()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[Backfill] Interrupted — progress has been saved.")
        print("  Run again to continue from where you left off.")
