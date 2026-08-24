#!/usr/bin/env python3
"""Wipe school-year data clean, keeping the student profile and long-term
projects, ahead of a new school year starting.

    python3 scripts/new_school_year_reset.py

Takes a safety snapshot (via compass.backup.snapshot, the same mechanism
"Back up now" on the Data page uses) before touching anything, then asks
for a typed confirmation.

Cleared: lessons, logged activities + their subject credits, saved books
and vocabulary, math mastery progress, the Science/History "topics
already explored" history, course/credit records, the Check-In feelings
journal, and the morning routine log. Life Skills keep their curated list
but have completed_on reset to not-done.

Left untouched: the student profile, Big Projects (long-term projects
carry across school years), the travel journal (a family record that
stacks year over year, not a single year's assignment -- explicitly not
a "this year's schoolwork" table the way books or lessons are), Tier 3
Choice topics, declarations of intent, and uploaded district documents --
none of those are a single year's assignments, and clearing them was
explicitly ruled out when this script was scoped.

Works from any working directory -- it locates the project root itself
rather than requiring `cd` first.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from compass.backup import snapshot  # noqa: E402
from compass.storage.db import Database  # noqa: E402

CLEAR_TABLES = [
    "activity_subject_credits",
    "activities",
    "lessons",
    "vocabulary",
    "books",
    "skill_mastery",
    "topic_web",
    "courses",
    "journal_entries",
    "morning_routine_log",
]

KEPT = (
    "student profile, Big Projects, the travel journal, Tier 3 Choice "
    "topics, declarations of intent, and uploaded district documents"
)


def main() -> None:
    db = Database()
    if not db.path.exists():
        print(f"No database found at {db.path}")
        return

    backup_path = snapshot(db.conn, db.path, reason="newyearreset")
    print(f"Safety snapshot saved to {backup_path}")

    print(
        "\nThis will permanently clear:\n"
        "  - assignments (lessons, logged activities, subject credits)\n"
        "  - saved books and vocabulary\n"
        "  - math mastery progress\n"
        "  - science/history topic history\n"
        "  - course/credit records\n"
        "  - the Check-In feelings journal\n"
        "  - the morning routine log\n"
        "  - Life Skills completion (the skill list itself stays, just un-checked)\n"
        f"\nKept untouched: {KEPT}.\n"
    )
    if input("Type YES to proceed: ").strip() != "YES":
        print("Cancelled -- nothing was changed.")
        db.close()
        return

    counts = {}
    with db.conn:
        for table in CLEAR_TABLES:
            counts[table] = db.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            db.conn.execute(f"DELETE FROM {table}")
        reset_skills = db.conn.execute(
            "SELECT COUNT(*) FROM life_skills WHERE completed_on IS NOT NULL"
        ).fetchone()[0]
        db.conn.execute("UPDATE life_skills SET completed_on = NULL")
    db.close()

    for table, count in counts.items():
        print(f"  cleared {count} row(s) from {table}")
    print(f"  reset completion on {reset_skills} life skill(s)")
    print(f"\nDone. Restore from {backup_path} if anything looks wrong.")


if __name__ == "__main__":
    main()
