#!/usr/bin/env python3
"""Clear every generated lesson, leaving everything else untouched.

    python3 scripts/clear_lessons.py

Deletes all rows from `lessons` only. Logged hours (the compliance record),
the parent PIN, the student profile, and math mastery are unaffected --
`activities.lesson_id` is `ON DELETE SET NULL`, not cascading, so nothing
about hours already logged is touched. Use this to force every subject to
generate a genuinely fresh lesson on the next click, e.g. after an update
that changes what a lesson contains.

Works from any working directory -- it locates the project root itself
rather than requiring `cd` first.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from compass.storage.db import Database  # noqa: E402


def main() -> None:
    db = Database()
    count = db.conn.execute("SELECT COUNT(*) FROM lessons").fetchone()[0]
    db.conn.execute("DELETE FROM lessons")
    db.conn.commit()
    db.close()
    print(f"Cleared {count} lesson(s). Hours, PIN, profile, and mastery are untouched.")


if __name__ == "__main__":
    main()
