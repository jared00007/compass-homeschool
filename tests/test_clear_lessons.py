"""`scripts/clear_lessons.py` -- the maintenance script for forcing every
subject to generate a fresh lesson (e.g. after an update changes what a
lesson contains), without touching anything else in the database.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from compass.storage.db import Database

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "clear_lessons.py"


def run_script(db_path: Path, cwd: Path) -> str:
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=cwd,
        env={"COMPASS_DB": str(db_path), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def test_clears_lessons_but_leaves_hours_mastery_and_profile_alone(tmp_path):
    db_path = tmp_path / "test.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    db.save_lesson(
        student_id=student["id"], agent="math", subject="math",
        topic="t", title="t", payload={},
    )
    db.save_lesson(
        student_id=student["id"], agent="science", subject="science",
        topic="t2", title="t2", payload={},
    )
    db.set_mastery(student["id"], "two-step-equations", "mastered", score=100.0)
    db.log_activity(
        student_id=student["id"], title="logged hours", tier="core",
        primary_subject="math", minutes=45, subject_credits={"math": 45},
    )
    db.close()

    output = run_script(db_path, cwd=tmp_path)
    assert "Cleared 2 lesson(s)" in output

    db = Database(db_path)
    student = db.ensure_default_student()
    assert db.list_lessons(student["id"]) == []
    assert db.mastered_skills(student["id"]) == {"two-step-equations"}
    assert sum(a["minutes"] for a in db.list_activities(student["id"])) == 45
    db.close()


def test_works_from_a_directory_other_than_the_project_root(tmp_path):
    """The whole reason this is a script and not a paste-in one-liner: it
    must not require `cd`-ing into the project first."""
    db_path = tmp_path / "test.db"
    Database(db_path).close()  # just needs to exist

    unrelated_cwd = tmp_path / "somewhere_else"
    unrelated_cwd.mkdir()
    output = run_script(db_path, cwd=unrelated_cwd)
    assert "Cleared 0 lesson(s)" in output


def test_reports_zero_on_an_already_empty_lessons_table(tmp_path):
    db_path = tmp_path / "test.db"
    Database(db_path).close()
    output = run_script(db_path, cwd=tmp_path)
    assert "Cleared 0 lesson(s)" in output
