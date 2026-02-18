#!/usr/bin/env python3
"""Purge duplicate 'something felt off' day memories from the database.

Keeps the 2 most recent internal_conflict entries that contain the generic
fallback text. Deletes all older duplicates. Safe to run multiple times.

Usage:
    python scripts/purge_duplicate_memories.py [--db PATH] [--dry-run]

Defaults to data/shopkeeper.db if --db is not specified.
"""

import argparse
import os
import sqlite3
import sys


DEFAULT_DB = os.path.join(
    os.environ.get('SHOPKEEPER_DATA_DIR',
                   os.path.join(os.path.dirname(__file__), '..', 'data')),
    'shopkeeper.db',
)

POISON_TEXT = 'something felt off'
KEEP_COUNT = 2


def purge(db_path: str, dry_run: bool = False) -> int:
    """Delete duplicate internal_conflict memories. Returns count deleted."""
    if not os.path.exists(db_path):
        print(f"[PurgeMemory] DB not found: {db_path}")
        return 0

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Find all internal_conflict memories with the generic fallback text
    cursor = conn.execute(
        """SELECT id, ts, salience, summary
           FROM day_memory
           WHERE moment_type = 'internal_conflict'
             AND summary LIKE ?
           ORDER BY ts DESC""",
        (f'%{POISON_TEXT}%',),
    )
    rows = cursor.fetchall()

    total = len(rows)
    if total <= KEEP_COUNT:
        print(f"[PurgeMemory] Found {total} matching entries — nothing to purge "
              f"(keeping {KEEP_COUNT}).")
        conn.close()
        return 0

    to_delete = rows[KEEP_COUNT:]  # Skip the KEEP_COUNT most recent
    delete_ids = [r['id'] for r in to_delete]

    print(f"[PurgeMemory] Found {total} 'something felt off' memories.")
    print(f"[PurgeMemory] Keeping {KEEP_COUNT} most recent, deleting {len(delete_ids)}.")

    if dry_run:
        print("[PurgeMemory] DRY RUN — no changes made.")
        for r in to_delete:
            print(f"  Would delete: id={r['id'][:8]}… ts={r['ts']} "
                  f"salience={r['salience']}")
    else:
        placeholders = ','.join('?' for _ in delete_ids)
        conn.execute(
            f"DELETE FROM day_memory WHERE id IN ({placeholders})",
            delete_ids,
        )
        conn.commit()
        print(f"[PurgeMemory] Deleted {len(delete_ids)} duplicate memories.")

    conn.close()
    return len(delete_ids)


def main():
    parser = argparse.ArgumentParser(
        description='Purge duplicate internal_conflict day memories.')
    parser.add_argument('--db', default=DEFAULT_DB,
                        help=f'Path to SQLite DB (default: {DEFAULT_DB})')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be deleted without changing DB')
    args = parser.parse_args()

    db_path = os.path.abspath(args.db)
    print(f"[PurgeMemory] Target DB: {db_path}")

    deleted = purge(db_path, dry_run=args.dry_run)
    sys.exit(0 if deleted >= 0 else 1)


if __name__ == '__main__':
    main()
