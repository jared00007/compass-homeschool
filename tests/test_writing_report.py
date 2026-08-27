"""`scripts/writing_report.py` -- the read-only diagnostic tool that pulls
every writing response Landon has ever saved (with the actual prompt and
every draft) into one place, for a parent to review the real pattern
instead of judging off a general impression or one lesson at a time.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from compass.storage.db import Database

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "writing_report.py"


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


def test_reports_prompt_and_every_draft_in_chronological_order(tmp_path):
    db_path = tmp_path / "test.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="english", subject="english", topic="t",
        title="Brian's Turning Point",
        payload={
            "title": "Brian's Turning Point",
            "activities": [
                {"title": "Write It Down", "kind": "writing", "minutes": 10,
                 "instructions": "What changed, exactly?"},
            ],
        },
    )
    db.save_writing_response(lesson_id, 0, "idk")
    db.save_writing_response(lesson_id, 0, "he changed his mind")
    db.close()

    output = run_script(db_path, cwd=tmp_path)
    assert "Brian's Turning Point" in output
    assert "What changed, exactly?" in output
    assert output.index("idk") < output.index("he changed his mind")
    assert "Draft 1" in output
    assert "Final" in output


def test_says_so_when_nothing_has_been_saved_yet(tmp_path):
    db_path = tmp_path / "test.db"
    Database(db_path).close()
    output = run_script(db_path, cwd=tmp_path)
    assert "No writing responses saved yet." in output


def test_works_from_a_directory_other_than_the_project_root(tmp_path):
    db_path = tmp_path / "test.db"
    Database(db_path).close()
    unrelated_cwd = tmp_path / "somewhere_else"
    unrelated_cwd.mkdir()
    output = run_script(db_path, cwd=unrelated_cwd)
    assert "No writing responses saved yet." in output
