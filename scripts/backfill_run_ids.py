#!/usr/bin/env python3
"""Backfill and normalize run_id values to MMDD-NN format.

Two operations:
1. Convert existing run_ids (e.g. uuid hashes) in pipeline_runs and jobs
   to MMDD-NN format based on the run's started_at date.
2. Assign run_id to jobs that have NULL run_id by matching discovered_at
   date to pipeline_runs.started_at.

Usage:
    python3 scripts/backfill_run_ids.py          # dry-run (preview)
    python3 scripts/backfill_run_ids.py --apply  # write to DB
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "seeker.db"


def _is_mmdd_nn(run_id: str) -> bool:
    """Check if run_id is already in MMDD-NN format."""
    parts = run_id.split("-")
    if len(parts) != 2:
        return False
    if len(parts[0]) != 4 or not parts[0].isdigit():
        return False
    if not parts[1].isdigit():
        return False
    return True


def normalize_run_ids(db: sqlite3.Connection, apply: bool = False) -> None:
    """Convert existing run_ids to MMDD-NN format."""
    runs = db.execute(
        "SELECT id, run_id, started_at FROM pipeline_runs ORDER BY started_at"
    ).fetchall()

    # Track per-date sequence for new format assignment
    date_seq: dict[str, int] = {}
    updates: list[tuple[str, str, int]] = []  # (old_run_id, new_run_id, run_pk)

    for run in runs:
        old_run_id = run["run_id"]
        if not old_run_id:
            continue
        if _is_mmdd_nn(old_run_id):
            # Already in correct format — track sequence
            date_part = old_run_id.split("-")[0]
            seq = int(old_run_id.split("-")[1])
            date_seq[date_part] = max(date_seq.get(date_part, 0), seq)
            continue

        started_at = run["started_at"]
        date_part = started_at[5:7] + started_at[8:10]  # MMDD from YYYY-MM-DDTHH:...
        date_seq[date_part] = date_seq.get(date_part, 0) + 1
        new_run_id = f"{date_part}-{date_seq[date_part]:02d}"
        updates.append((old_run_id, new_run_id, run["id"]))

    if not updates:
        print("All run_ids already in MMDD-NN format.")
        return

    print(f"Converting {len(updates)} run_ids to MMDD-NN format:")
    for old_id, new_id, _ in updates:
        print(f"  {old_id} → {new_id}")

    if apply:
        for old_id, new_id, run_pk in updates:
            db.execute("UPDATE pipeline_runs SET run_id = ? WHERE id = ?", (new_id, run_pk))
            db.execute("UPDATE jobs SET run_id = ? WHERE run_id = ?", (new_id, old_id))
        db.commit()
        print(f"  Updated {len(updates)} runs in pipeline_runs + corresponding jobs.")
    else:
        print("  [dry-run] Re-run with --apply to write.")


def backfill_nulls(db: sqlite3.Connection, apply: bool = False) -> None:
    """Assign run_id to jobs that have NULL run_id."""
    runs = db.execute(
        "SELECT run_id, started_at, cards_new FROM pipeline_runs ORDER BY started_at"
    ).fetchall()

    if not runs:
        print("No pipeline runs found.", file=sys.stderr)
        return

    total_matched = 0

    for run in runs:
        run_id = run["run_id"]
        started_at = run["started_at"]
        cards_new = run["cards_new"] or 0
        run_date = started_at[:10]

        unmatched = db.execute(
            "SELECT id FROM jobs WHERE run_id IS NULL AND DATE(discovered_at) = ? ORDER BY id",
            (run_date,),
        ).fetchall()

        match_count = len(unmatched)
        if match_count == 0:
            continue

        print(f"Run {run_id} (date={run_date}): {match_count} jobs with NULL run_id")

        if cards_new > 0 and match_count != cards_new:
            print(f"  WARNING: count mismatch (run says {cards_new}, found {match_count})")

        if apply:
            for row in unmatched:
                db.execute(
                    "UPDATE jobs SET run_id = ? WHERE id = ? AND run_id IS NULL",
                    (run_id, row["id"]),
                )
            db.commit()
            print(f"  Updated {match_count} jobs → run_id={run_id}")
        else:
            print(f"  [dry-run] Would update {match_count} jobs → run_id={run_id}")

        total_matched += match_count

    remaining = db.execute(
        "SELECT COUNT(*) as c FROM jobs WHERE run_id IS NULL"
    ).fetchone()["c"]

    print(f"\nTotal matched: {total_matched}")
    print(f"Remaining NULL: {remaining}")

    if not apply:
        print("\nDry-run complete. Re-run with --apply to write.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Normalize and backfill run_id values")
    parser.add_argument("--apply", action="store_true", help="Write changes to DB (default: dry-run)")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}", file=sys.stderr)
        sys.exit(1)

    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row

    print("=== Step 1: Normalize existing run_ids to MMDD-NN ===")
    normalize_run_ids(db, apply=args.apply)
    print()
    print("=== Step 2: Backfill NULL run_ids ===")
    backfill_nulls(db, apply=args.apply)

    db.close()
