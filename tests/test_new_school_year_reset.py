"""`scripts/new_school_year_reset.py` -- clears a school year's data ahead of
the next one starting, keeping the student profile and long-term projects.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from compass.backup import backup_dir
from compass.storage.db import Database

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "new_school_year_reset.py"


def run_script(db_path: Path, cwd: Path, confirm: str = "YES") -> str:
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=cwd,
        input=confirm,
        env={"COMPASS_DB": str(db_path), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _seed_everything(db: Database, student_id: int) -> None:
    db.add_interest(student_id, "Legos")
    db.save_lesson(
        student_id=student_id, agent="math", subject="math",
        topic="t", title="t", payload={},
    )
    db.log_activity(
        student_id=student_id, title="logged hours", tier="core",
        primary_subject="math", minutes=45, subject_credits={"math": 45},
    )
    db.set_mastery(student_id, "two-step-equations", "mastered", score=100.0)
    db.add_web_node(student_id, "science", "Volcanoes")
    book_id = db.add_book(student_id, "Hatchet", author="Gary Paulsen")
    db.add_vocabulary(student_id, "resilient", "able to recover quickly", book_id)
    db.add_travel_entry(student_id, "WA", "2026-06-01", title="Olympic NP")
    db.save_journal_entry(student_id, "2026-06-01", "happy", "good day")
    db.log_morning_routine(student_id, "2026-06-01", "stretch")
    course_id = db.create_course(
        student_id, "Pre-Algebra", "math", "2025-09-01", "2026-06-01"
    )
    project_id = db.add_big_project(student_id, "Stop-motion film", "A short film")
    db.add_project_step(project_id, "Write the script", credit_subject="writing")
    db.add_choice_topic(student_id, "3D printing")
    skill_id = db.add_life_skill(student_id, "Do laundry")
    db.set_life_skill_done(skill_id, True)
    db.mark_declaration_filed(student_id, "2026-09-01")
    db.save_district_document(student_id, "declaration", "packet.pdf", b"data")
    return course_id, project_id, skill_id


def test_clears_school_year_data_keeps_profile_and_projects(tmp_path):
    db_path = tmp_path / "test.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    course_id, project_id, skill_id = _seed_everything(db, student["id"])
    db.close()

    output = run_script(db_path, cwd=tmp_path)
    assert "Cancelled" not in output

    db = Database(db_path)
    student = db.ensure_default_student()
    sid = student["id"]

    # kept
    assert db.interests_text(sid) == "Legos"
    # Reopening the db tops up the starter catalog for any student who
    # already has at least one project (see _backfill_big_project_catalog),
    # so check the seeded project survives rather than the total count.
    project_titles = {p["title"] for p in db.list_big_projects(sid)}
    assert "Stop-motion film" in project_titles
    assert len(db.list_project_steps(project_id)) == 1
    assert len(db.list_choice_topics(sid)) == 1
    assert db.declaration_status(sid, "2026-09-01")["filed_on"] is not None
    assert db.get_district_document(sid, "declaration") is not None

    # cleared
    assert db.list_lessons(sid) == []
    assert db.list_activities(sid) == []
    assert db.mastered_skills(sid) == set()
    assert db.explored_topics(sid, "science") == []
    assert db.web_nodes(sid, "science") == []
    assert db.list_books(sid) == []
    assert db.list_vocabulary(sid) == []
    assert db.list_travel_entries(sid) == []
    assert db.list_journal_entries(sid) == []
    assert db.morning_routine_for_date(sid, "2026-06-01") is None
    assert db.list_courses(sid) == []

    # life skill list kept, but completion reset -- reopening the db also
    # tops up the full life skill catalog (see _backfill_life_skill_catalog),
    # so check the seeded skill by id rather than the total count.
    seeded_skill = next(s for s in db.list_life_skills(sid) if s["id"] == skill_id)
    assert seeded_skill["title"] == "Do laundry"
    assert seeded_skill["completed_on"] is None
    assert all(s["completed_on"] is None for s in db.list_life_skills(sid))
    db.close()


def test_declining_confirmation_changes_nothing(tmp_path):
    db_path = tmp_path / "test.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    db.save_lesson(
        student_id=student["id"], agent="math", subject="math",
        topic="t", title="t", payload={},
    )
    db.close()

    output = run_script(db_path, cwd=tmp_path, confirm="no")
    assert "Cancelled" in output

    db = Database(db_path)
    student = db.ensure_default_student()
    assert len(db.list_lessons(student["id"])) == 1
    db.close()


def test_takes_a_safety_snapshot_before_clearing(tmp_path):
    db_path = tmp_path / "test.db"
    Database(db_path).close()

    run_script(db_path, cwd=tmp_path)

    snapshots = list(backup_dir(db_path).glob("*newyearreset*.db"))
    assert len(snapshots) == 1


def test_works_from_a_directory_other_than_the_project_root(tmp_path):
    db_path = tmp_path / "test.db"
    Database(db_path).close()

    unrelated_cwd = tmp_path / "somewhere_else"
    unrelated_cwd.mkdir()
    output = run_script(db_path, cwd=unrelated_cwd)
    assert "Done." in output
