#!/usr/bin/env python3
"""
Partial production cleanup — reset malfunctioning systems, preserve identity.

DELETES:
  - journal_entries     (polluted with monologue copies)
  - day_memory          (salience scores from broken formula)
  - habits              (90% strength from spam loops)
  - cycle_log           (operational data, not personality)

RESETS:
  - drives_state → equilibria values (fresh pull system)

KEEPS:
  - collection_items    (genuinely hers)
  - content_pool        (fresh items ready)
  - conversation_log    (real visitor moments)
  - visitors            (real people she met)
  - visitor_traits      (learned observations)
  - totems              (weighted associations)
  - inhibitions         (learned suppression rules)
  - events              (append-only log — the ground truth)
  - daily_summaries     (compressed history)

Usage:
  # Dry run (default) — shows what would happen
  python scripts/prod_partial_clean.py data/shopkeeper.db

  # Actually do it
  python scripts/prod_partial_clean.py data/shopkeeper.db --execute
"""

import sqlite3
import sys
import os
from datetime import datetime, timezone


# ─── Drive equilibria (from pipeline/hypothalamus.py) ───
DRIVE_EQUILIBRIA = {
    'social_hunger':   0.45,
    'curiosity':       0.50,
    'expression_need': 0.35,
    'rest_need':       0.25,
    'energy':          0.70,
    'mood_valence':    0.05,
    'mood_arousal':    0.30,
}


def run(db_path: str, execute: bool = False):
    if not os.path.exists(db_path):
        print(f"ERROR: database not found at {db_path}")
        sys.exit(1)

    mode = "EXECUTE" if execute else "DRY RUN"
    print(f"\n{'='*60}")
    print(f"  Partial DB Clean — {mode}")
    print(f"  Database: {db_path}")
    print(f"  Time: {datetime.now(timezone.utc).isoformat()}")
    print(f"{'='*60}\n")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # ─── Inventory before ───
    tables_to_wipe = ['journal_entries', 'day_memory', 'habits', 'cycle_log']
    tables_to_keep = [
        'collection_items', 'content_pool', 'conversation_log',
        'visitors', 'visitor_traits', 'totems', 'inhibitions',
        'events', 'daily_summaries',
    ]

    print("TABLES TO WIPE:")
    for t in tables_to_wipe:
        try:
            cur.execute(f"SELECT COUNT(*) FROM {t}")
            count = cur.fetchone()[0]
            print(f"  {t}: {count} rows → DELETE ALL")
        except sqlite3.OperationalError:
            print(f"  {t}: (table does not exist, skipping)")

    print("\nTABLES TO KEEP (untouched):")
    for t in tables_to_keep:
        try:
            cur.execute(f"SELECT COUNT(*) FROM {t}")
            count = cur.fetchone()[0]
            print(f"  {t}: {count} rows")
        except sqlite3.OperationalError:
            print(f"  {t}: (table does not exist)")

    # ─── Current drive state ───
    print("\nDRIVE STATE RESET:")
    try:
        cur.execute("SELECT * FROM drives_state WHERE id = 1")
        row = cur.fetchone()
        if row:
            for key in DRIVE_EQUILIBRIA:
                old = row[key]
                new = DRIVE_EQUILIBRIA[key]
                arrow = " ←" if abs(old - new) > 0.01 else ""
                print(f"  {key}: {old:.3f} → {new:.3f}{arrow}")
        else:
            print("  (no drives_state row found — will insert)")
    except sqlite3.OperationalError:
        print("  (drives_state table does not exist)")

    if not execute:
        print(f"\n{'─'*60}")
        print("  DRY RUN complete. No changes made.")
        print("  Re-run with --execute to apply.")
        print(f"{'─'*60}\n")
        conn.close()
        return

    # ─── Execute ───
    print(f"\n{'─'*60}")
    print("  EXECUTING CLEANUP...")
    print(f"{'─'*60}\n")

    # Back up first
    backup_path = db_path + f".backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    print(f"  Backing up to: {backup_path}")
    backup_conn = sqlite3.connect(backup_path)
    conn.backup(backup_conn)
    backup_conn.close()
    print("  Backup complete.\n")

    # Wipe tables
    for t in tables_to_wipe:
        try:
            cur.execute(f"DELETE FROM {t}")
            print(f"  Wiped {t}: {cur.rowcount} rows deleted")
        except sqlite3.OperationalError:
            print(f"  Skipped {t}: table does not exist")

    # Reset drives to equilibria
    now = datetime.now(timezone.utc).isoformat()
    try:
        cur.execute("SELECT COUNT(*) FROM drives_state WHERE id = 1")
        if cur.fetchone()[0] > 0:
            cur.execute("""
                UPDATE drives_state SET
                    social_hunger = ?,
                    curiosity = ?,
                    expression_need = ?,
                    rest_need = ?,
                    energy = ?,
                    mood_valence = ?,
                    mood_arousal = ?,
                    updated_at = ?
                WHERE id = 1
            """, (
                DRIVE_EQUILIBRIA['social_hunger'],
                DRIVE_EQUILIBRIA['curiosity'],
                DRIVE_EQUILIBRIA['expression_need'],
                DRIVE_EQUILIBRIA['rest_need'],
                DRIVE_EQUILIBRIA['energy'],
                DRIVE_EQUILIBRIA['mood_valence'],
                DRIVE_EQUILIBRIA['mood_arousal'],
                now,
            ))
            print("  Reset drives_state to equilibria")
        else:
            print("  No drives_state row to reset")
    except sqlite3.OperationalError as e:
        print(f"  Could not reset drives_state: {e}")

    conn.commit()
    conn.close()

    print(f"\n{'='*60}")
    print("  CLEANUP COMPLETE")
    print(f"  Backup at: {backup_path}")
    print(f"{'='*60}\n")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python scripts/prod_partial_clean.py <db_path> [--execute]")
        sys.exit(1)

    db_path = sys.argv[1]
    execute = '--execute' in sys.argv
    run(db_path, execute)
