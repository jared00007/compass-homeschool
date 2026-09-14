"""Instructional hours are captured for work that used to credit nothing.

Big Project steps and coding modules now log a default block of time on
completion (and are backfilled for work finished earlier), and a quick-log panel
turns real-life learning into a one-tap activity. All of it flows into the same
`activities` table the compliance total sums.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from compass import auth, config
from compass.storage.db import Database

REPO_ROOT = Path(__file__).resolve().parent.parent
HOME_PATH = str(REPO_ROOT / "Home.py")
MISSION_CONTROL_PATH = str(REPO_ROOT / "pages" / "14_Mission_Control.py")


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "hours.db")
    yield database
    database.close()


@pytest.fixture()
def student(db):
    return db.ensure_default_student()


def _activities(db, student_id, source):
    return db.conn.execute(
        "SELECT tier, minutes, title FROM activities WHERE student_id = ? AND source = ?",
        (student_id, source),
    ).fetchall()


# --- Big Project steps -----------------------------------------------------------


def test_approving_a_project_step_logs_hours(db, student):
    project_id = db.add_big_project(student["id"], "Stop-motion film")
    step_id = db.add_project_step(project_id, "Build the set", credit_subject="art_and_music")
    db.approve_project_step(step_id)

    rows = _activities(db, student["id"], "big_projects")
    assert len(rows) == 1
    assert rows[0]["tier"] == config.TIER_PROJECTS
    assert rows[0]["minutes"] == config.PROJECT_STEP_DEFAULT_MINUTES
    # And it credits the step's own subject.
    credits = db.conn.execute(
        "SELECT subject, minutes FROM activity_subject_credits "
        "WHERE activity_id = (SELECT id FROM activities WHERE student_id=? AND source='big_projects')",
        (student["id"],),
    ).fetchall()
    assert {c["subject"] for c in credits} == {"art_and_music"}


def test_a_project_step_is_not_double_counted(db, student):
    project_id = db.add_big_project(student["id"], "Garden")
    step_id = db.add_project_step(project_id, "Plant the beds")
    db.approve_project_step(step_id)
    db.approve_project_step(step_id)  # re-approve -> still one activity
    assert len(_activities(db, student["id"], "big_projects")) == 1


# --- Coding modules --------------------------------------------------------------


def test_completing_a_coding_module_logs_hours(db, student):
    module_id = db.add_coding_module(student["id"], "Loops and conditionals")
    db.set_coding_module_done(module_id, True)

    rows = _activities(db, student["id"], "coding")
    assert len(rows) == 1
    assert rows[0]["tier"] == config.TIER_CODING
    assert rows[0]["minutes"] == config.CODING_DEFAULT_MINUTES


def test_uncompleting_and_recompleting_a_module_does_not_double_count(db, student):
    module_id = db.add_coding_module(student["id"], "Functions")
    db.set_coding_module_done(module_id, True)
    db.set_coding_module_done(module_id, False)  # un-check
    db.set_coding_module_done(module_id, True)   # re-check
    assert len(_activities(db, student["id"], "coding")) == 1


# --- Retroactive backfill --------------------------------------------------------


def test_backfill_credits_work_finished_before_logging_existed(db, student):
    # Simulate old data: a completed step + module with NO activity logged.
    project_id = db.add_big_project(student["id"], "Old project")
    step_id = db.add_project_step(project_id, "An old step")
    db.conn.execute(
        "UPDATE project_steps SET status='completed', completed_on='2026-09-01' WHERE id=?",
        (step_id,),
    )
    module_id = db.add_coding_module(student["id"], "An old module")
    db.conn.execute(
        "UPDATE coding_modules SET completed_on='2026-09-01' WHERE id=?", (module_id,)
    )
    db.conn.commit()
    assert _activities(db, student["id"], "big_projects") == []
    assert _activities(db, student["id"], "coding") == []

    db._backfill_project_step_credits()
    db._backfill_coding_credits()
    assert len(_activities(db, student["id"], "big_projects")) == 1
    assert len(_activities(db, student["id"], "coding")) == 1

    # Idempotent -- a second pass doesn't add a thing.
    db._backfill_project_step_credits()
    db._backfill_coding_credits()
    assert len(_activities(db, student["id"], "big_projects")) == 1
    assert len(_activities(db, student["id"], "coding")) == 1


# --- Quick-log panel, end to end -------------------------------------------------


def test_quick_log_button_logs_an_activity(monkeypatch, tmp_path):
    db_path = tmp_path / "q.db"
    database = Database(db_path)
    database.ensure_default_student()
    auth.set_pin(database, "1234")
    database.close()

    st.cache_resource.clear()
    monkeypatch.setattr(config, "DEFAULT_DB_PATH", db_path)
    at = AppTest.from_file(HOME_PATH)
    at.session_state["parent_unlocked"] = True
    at.run(timeout=30)
    at.switch_page(MISSION_CONTROL_PATH)
    at.run(timeout=30)
    # Switch to the Record view where the quick-log lives.
    [b for b in at.button if (b.key or "") == "mc_viewbtn_record"][0].click().run()
    assert not at.exception, [e.message for e in at.exception]

    [b for b in at.button if (b.key or "") == "quicklog_0"][0].click().run()
    assert not at.exception, [e.message for e in at.exception]

    database = Database(db_path)
    logged = database.conn.execute(
        "SELECT COUNT(*) c FROM activities WHERE source='quick_log'"
    ).fetchone()["c"]
    database.close()
    assert logged == 1
