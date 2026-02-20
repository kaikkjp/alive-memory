#!/usr/bin/env python3
"""Merge duplicate threads in the shopkeeper database.

For each title with multiple threads, keeps the one with the highest touch_count
(oldest as tiebreak), merges content from the rest, then deletes duplicates.

Usage:
    python scripts/merge_duplicate_threads.py [DB_PATH]

Default DB_PATH: data/shopkeeper_live.db
Use --dry-run to preview without modifying.
"""

import argparse
import json
import sqlite3
import sys
from datetime import datetime


def find_duplicates(conn: sqlite3.Connection) -> dict[str, list[dict]]:
    """Find titles with more than one non-archived thread."""
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT id, title, status, priority, content, touch_count,
                  created_at, last_touched, tags, resolution
           FROM threads
           WHERE status != 'archived'
           ORDER BY title, touch_count DESC, created_at ASC"""
    ).fetchall()

    by_title: dict[str, list[dict]] = {}
    for r in rows:
        t = r['title']
        by_title.setdefault(t, []).append(dict(r))

    return {t: threads for t, threads in by_title.items() if len(threads) > 1}


def merge_group(conn: sqlite3.Connection, title: str,
                threads: list[dict], dry_run: bool):
    """Merge a group of duplicate threads into the best survivor."""
    # Survivor: highest touch_count, then earliest created_at
    survivor = threads[0]  # already sorted by touch_count DESC, created_at ASC
    dupes = threads[1:]

    print(f"\n  Title: \"{title}\"")
    print(f"  Survivor: {survivor['id'][:8]}... "
          f"(touches={survivor['touch_count']}, "
          f"created={survivor['created_at'][:19]})")

    # Collect content from duplicates
    extra_content = []
    extra_tags = set()
    latest_touched = survivor['last_touched']
    total_touches = survivor['touch_count']

    for d in dupes:
        print(f"  Merging:  {d['id'][:8]}... "
              f"(touches={d['touch_count']}, "
              f"created={d['created_at'][:19]})")
        if d['content'] and d['content'].strip():
            # Only add if substantively different from survivor content
            if d['content'].strip() != (survivor['content'] or '').strip():
                extra_content.append(d['content'].strip())
        total_touches += d['touch_count']
        if d['last_touched'] and d['last_touched'] > latest_touched:
            latest_touched = d['last_touched']
        if d['tags']:
            try:
                extra_tags.update(json.loads(d['tags']))
            except (json.JSONDecodeError, TypeError):
                pass

    # Merge survivor tags
    survivor_tags = set()
    if survivor['tags']:
        try:
            survivor_tags = set(json.loads(survivor['tags']))
        except (json.JSONDecodeError, TypeError):
            pass
    merged_tags = sorted(survivor_tags | extra_tags)

    # Build merged content
    merged_content = (survivor['content'] or '').strip()
    if extra_content:
        merged_content += '\n\n--- merged from duplicates ---\n'
        merged_content += '\n\n'.join(extra_content)

    dupe_ids = [d['id'] for d in dupes]

    if dry_run:
        print(f"  [DRY RUN] Would merge {len(dupes)} dupes into survivor")
        print(f"  [DRY RUN] Total touches: {total_touches}, "
              f"Extra content chunks: {len(extra_content)}")
        return

    # Update survivor
    conn.execute(
        """UPDATE threads
           SET content = ?,
               touch_count = ?,
               last_touched = ?,
               tags = ?,
               touch_reason = 'dedup_cleanup'
           WHERE id = ?""",
        (merged_content, total_touches, latest_touched,
         json.dumps(merged_tags), survivor['id'])
    )

    # Delete duplicates
    placeholders = ','.join('?' * len(dupe_ids))
    conn.execute(
        f"DELETE FROM threads WHERE id IN ({placeholders})",
        dupe_ids
    )
    conn.commit()
    print(f"  Deleted {len(dupe_ids)} duplicates, merged into {survivor['id'][:8]}")


def main():
    parser = argparse.ArgumentParser(description='Merge duplicate threads')
    parser.add_argument('db_path', nargs='?',
                        default='data/shopkeeper_live.db',
                        help='Path to SQLite database')
    parser.add_argument('--dry-run', action='store_true',
                        help='Preview changes without modifying')
    args = parser.parse_args()

    conn = sqlite3.connect(args.db_path)
    conn.row_factory = sqlite3.Row

    duplicates = find_duplicates(conn)

    if not duplicates:
        print("No duplicate threads found.")
        conn.close()
        return

    print(f"Found {len(duplicates)} titles with duplicates:")
    total_dupes = sum(len(v) - 1 for v in duplicates.values())
    print(f"  {total_dupes} duplicate threads to merge\n")

    for title, threads in duplicates.items():
        merge_group(conn, title, threads, args.dry_run)

    # Summary
    remaining = conn.execute("SELECT COUNT(*) FROM threads").fetchone()[0]
    open_count = conn.execute(
        "SELECT COUNT(*) FROM threads WHERE status IN ('open', 'active')"
    ).fetchone()[0]
    print(f"\nDone. Threads remaining: {remaining} ({open_count} open)")

    conn.close()


if __name__ == '__main__':
    main()
