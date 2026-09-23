#!/usr/bin/env python3
"""Inspect, re-subject, or delete Khan cards -- a one-off maintenance helper.

Khan cards are lessons saved under the `khan` agent. Run this from anywhere
(it finds the project root itself); it acts on the same database the app uses.

    # See what you've got (id · subject · status · day · title):
    python3 scripts/khan_cards.py --list

    # Fix the record: re-tag EVERY Khan card to math (subject column, the
    # payload's subject credits, and any hours already logged):
    python3 scripts/khan_cards.py --set-subject math

    # ...or only the ones currently mis-tagged as, say, reading:
    python3 scripts/khan_cards.py --set-subject math --from reading

    # Delete Khan cards. Default: all of them. --scheduled: only the ones
    # assigned to a day (i.e. sitting on the board's day columns):
    python3 scripts/khan_cards.py --delete
    python3 scripts/khan_cards.py --delete --scheduled

Deleting a card leaves any hours it already logged intact (activities.lesson_id
is ON DELETE SET NULL). Re-subjecting fixes the lesson AND the logged hours, so
the compliance record and the gradebook both reflect the corrected subject.
Valid subjects are the eleven WA keys: math, reading, writing, spelling,
language, science, social_studies, history, health, occupational_education,
art_and_music.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from compass import subjects  # noqa: E402
from compass.storage.db import Database  # noqa: E402


def _khan_rows(db: Database) -> list:
    return db.conn.execute(
        "SELECT id, subject, status, title, "
        "json_extract(metadata, '$.planned_for') AS planned_for "
        "FROM lessons WHERE agent = 'khan' ORDER BY id"
    ).fetchall()


def do_list(db: Database) -> None:
    rows = _khan_rows(db)
    if not rows:
        print("No Khan cards.")
        return
    print(f"{len(rows)} Khan card(s):")
    for r in rows:
        day = r["planned_for"] or "backlog"
        print(f"  #{r['id']:>4}  {r['subject']:<22}  {r['status']:<13}  {day:<12}  {r['title']}")


def do_set_subject(db: Database, new_subject: str, from_subject: str | None) -> None:
    if not subjects.is_valid(new_subject):
        raise SystemExit(f"'{new_subject}' isn't a valid WA subject key.")
    label = subjects.label(new_subject)
    where = "agent = 'khan'"
    params: list = []
    if from_subject:
        where += " AND subject = ?"
        params.append(from_subject)
    rows = db.conn.execute(
        f"SELECT id, topic, payload FROM lessons WHERE {where}", params
    ).fetchall()
    if not rows:
        print("No matching Khan cards.")
        return
    for r in rows:
        lesson_id = r["id"]
        payload = json.loads(r["payload"])
        credits = payload.get("subject_credits") or []
        for credit in credits:
            credit["subject"] = new_subject
            credit["justification"] = (
                f"Completed the assigned Khan Academy skill '{r['topic']}' for {label}."
            )
        db.conn.execute(
            "UPDATE lessons SET subject = ?, payload = ? WHERE id = ?",
            (new_subject, json.dumps(payload), lesson_id),
        )
        # Fix hours already logged from this card, so compliance + grades follow.
        db.conn.execute(
            "UPDATE activities SET primary_subject = ? WHERE lesson_id = ? AND source = 'khan'",
            (new_subject, lesson_id),
        )
        db.conn.execute(
            "UPDATE activity_subject_credits SET subject = ? "
            "WHERE activity_id IN (SELECT id FROM activities WHERE lesson_id = ? AND source = 'khan')",
            (new_subject, lesson_id),
        )
    db.conn.commit()
    scope = f" (from '{from_subject}')" if from_subject else ""
    print(f"Re-tagged {len(rows)} Khan card(s){scope} to {label} ({new_subject}).")


def do_delete(db: Database, scheduled_only: bool) -> None:
    where = "agent = 'khan'"
    if scheduled_only:
        where += " AND json_extract(metadata, '$.planned_for') IS NOT NULL"
    ids = [r["id"] for r in db.conn.execute(f"SELECT id FROM lessons WHERE {where}").fetchall()]
    for lesson_id in ids:
        db.delete_lesson(lesson_id)
    which = "scheduled " if scheduled_only else ""
    print(f"Deleted {len(ids)} {which}Khan card(s). Any hours they logged are kept.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect, re-subject, or delete Khan cards.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--list", action="store_true", help="List every Khan card.")
    group.add_argument("--set-subject", metavar="SUBJECT", help="Re-tag Khan cards to this WA subject.")
    group.add_argument("--delete", action="store_true", help="Delete Khan cards.")
    parser.add_argument("--from", dest="from_subject", metavar="SUBJECT",
                        help="With --set-subject: only re-tag cards currently in this subject.")
    parser.add_argument("--scheduled", action="store_true",
                        help="With --delete: only cards assigned to a day (on the board).")
    args = parser.parse_args()

    db = Database()
    try:
        if args.list:
            do_list(db)
        elif args.set_subject:
            do_set_subject(db, args.set_subject, args.from_subject)
        elif args.delete:
            do_delete(db, args.scheduled)
    finally:
        db.close()


if __name__ == "__main__":
    main()
