#!/usr/bin/env python3
"""Every writing response Landon has ever saved, in one place, oldest first.

    python3 scripts/writing_report.py

For each one: the date, subject, lesson title, the actual prompt he was
answering, and every draft he saved for it (not just the final one) --
useful for looking at the real pattern across weeks rather than judging
off a general impression or one lesson at a time.

Read-only. Works from any working directory -- it locates the project
root itself rather than requiring `cd` first.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from compass.storage.db import Database  # noqa: E402


def main() -> None:
    db = Database()
    student = db.ensure_default_student()

    pairs = db.conn.execute(
        "SELECT DISTINCT lesson_id, activity_index FROM writing_response_versions "
        "WHERE student_id = ? ORDER BY (SELECT MIN(saved_at) FROM writing_response_versions "
        "v2 WHERE v2.lesson_id = writing_response_versions.lesson_id "
        "AND v2.activity_index = writing_response_versions.activity_index)",
        (student["id"],),
    ).fetchall()

    if not pairs:
        print("No writing responses saved yet.")
        db.close()
        return

    print(f"Writing responses for {student['name']} -- {len(pairs)} activity/lesson pair(s)\n")
    print("=" * 78)

    for lesson_id, activity_index in pairs:
        lesson = db.get_lesson(lesson_id)
        if not lesson:
            continue
        activities = lesson["payload"].get("activities") or []
        activity = activities[activity_index] if activity_index < len(activities) else {}
        versions = db.list_writing_response_versions(lesson_id, activity_index)

        print(f"\n{lesson['created_at'][:10]}  ·  {lesson['agent'].title()}  ·  {lesson['title']}")
        if activity.get("title"):
            print(f"Activity: {activity['title']} ({activity.get('kind', '?')})")
        if activity.get("instructions"):
            print(f"Prompt: {activity['instructions']}")
        print("-" * 78)

        for index, version in enumerate(versions, start=1):
            label = "Final" if index == len(versions) else f"Draft {index}"
            text = version["text"].strip() or "(empty)"
            print(f"  [{label}, saved {version['saved_at']}]")
            print(f"  {text}")
            if index < len(versions):
                print()

        print("=" * 78)

    db.close()


if __name__ == "__main__":
    main()
