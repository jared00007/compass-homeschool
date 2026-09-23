"""`scripts/khan_cards.py` -- inspect, re-subject, or delete Khan cards."""

from __future__ import annotations

import subprocess
import sys
from datetime import date
from pathlib import Path

from compass.agents import khan_card
from compass.storage.db import Database

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "khan_cards.py"
_QUIZ = [{"question": "q", "choices": ["a", "b", "c", "d"], "correct_index": 1, "explanation": "e"}]


def run(db_path: Path, *args: str) -> str:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=db_path.parent,
        env={"COMPASS_DB": str(db_path), "PATH": "/usr/bin:/bin"},
        capture_output=True, text=True, check=True,
    )
    return result.stdout


def _seed(db_path: Path):
    db = Database(db_path)
    student = db.ensure_default_student()
    # A completed, scheduled card that logged hours under 'reading' (mis-tagged).
    lid = khan_card.create_khan_card(
        db, student, subject="reading", unit="Exponents", minutes=30,
        day_iso=date.today().isoformat(), quiz=list(_QUIZ),
    )
    db.set_lesson_status(lid, "completed")
    db.log_activity(
        student_id=student["id"], title="Khan Academy: Exponents", tier="core",
        primary_subject="reading", minutes=30, subject_credits={"reading": 30},
        source="khan", lesson_id=lid,
    )
    # A backlog card (no day).
    khan_card.create_khan_card(
        db, student, subject="reading", unit="Fractions", minutes=30,
        day_iso=None, quiz=list(_QUIZ),
    )
    db.close()
    return student["id"]


def test_list_shows_the_khan_cards(tmp_path):
    db_path = tmp_path / "t.db"
    _seed(db_path)
    out = run(db_path, "--list")
    assert "2 Khan card(s)" in out
    assert "Exponents" in out and "Fractions" in out


def test_set_subject_fixes_the_lesson_and_the_logged_hours(tmp_path):
    db_path = tmp_path / "t.db"
    student_id = _seed(db_path)
    out = run(db_path, "--set-subject", "math")
    assert "Re-tagged 2 Khan card(s) to Math" in out

    db = Database(db_path)
    subjects_now = {r["subject"] for r in db.conn.execute(
        "SELECT subject FROM lessons WHERE agent='khan'").fetchall()}
    assert subjects_now == {"math"}                       # lesson rows fixed
    # The logged hours moved to math too, so compliance follows.
    credit = db.conn.execute("SELECT subject, minutes FROM activity_subject_credits").fetchone()
    assert credit["subject"] == "math" and credit["minutes"] == 30
    db.close()


def test_set_subject_can_target_only_one_source_subject(tmp_path):
    db_path = tmp_path / "t.db"
    _seed(db_path)
    # Nothing is tagged 'science', so a --from science pass changes nothing.
    out = run(db_path, "--set-subject", "math", "--from", "science")
    assert "No matching Khan cards." in out


def test_delete_scheduled_then_all_keeps_logged_hours(tmp_path):
    db_path = tmp_path / "t.db"
    student_id = _seed(db_path)
    out = run(db_path, "--delete", "--scheduled")
    assert "Deleted 1 scheduled Khan card(s)" in out

    db = Database(db_path)
    remaining = db.conn.execute("SELECT COUNT(*) FROM lessons WHERE agent='khan'").fetchone()[0]
    assert remaining == 1  # the backlog card survives
    db.close()

    out = run(db_path, "--delete")
    assert "Deleted 1 Khan card(s)" in out
    db = Database(db_path)
    assert db.conn.execute("SELECT COUNT(*) FROM lessons WHERE agent='khan'").fetchone()[0] == 0
    # Hours logged before the delete are still on the record.
    assert sum(a["minutes"] for a in db.list_activities(student_id)) == 30
    db.close()
