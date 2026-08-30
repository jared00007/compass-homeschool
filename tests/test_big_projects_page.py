"""The "Chunk this project into steps with AI" button on pages/7_Big_Projects.py.

Deliberately not testing the click itself here -- same reasoning
test_page_smoke.py states for every other AI-generation button in this
app: it calls the live Anthropic API, which this suite has no business
spending money on per test run. `tests/test_project_chunker.py` covers
the actual generation logic with the API call mocked out; this file only
covers the button's own visibility and disabled-state wiring, which
doesn't touch the network at all.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import streamlit as st
from streamlit.testing.v1 import AppTest

from compass import auth, config
from compass.storage.db import Database

REPO_ROOT = Path(__file__).resolve().parent.parent
HOME_PATH = str(REPO_ROOT / "Home.py")
BIG_PROJECTS_PATH = str(REPO_ROOT / "pages" / "7_Big_Projects.py")


def _open_checklist_tab(monkeypatch, db_path, *, as_parent=True):
    st.cache_resource.clear()
    monkeypatch.setattr(config, "DEFAULT_DB_PATH", db_path)
    at = AppTest.from_file(HOME_PATH)
    if as_parent:
        at.session_state["parent_unlocked"] = True
    at.run(timeout=30)
    at.switch_page(BIG_PROJECTS_PATH)
    at.run(timeout=30)
    assert not at.exception, [e.message for e in at.exception]
    return at


def _expand_project(at, project_id):
    """The card is collapsed on every fresh load -- the step list (and the
    Backlog section) only render once "Show" is clicked."""
    at.button(key=f"toggle_project_{project_id}").click().run()
    return at


def test_chunk_button_shows_only_for_a_stepless_project(monkeypatch, tmp_path):
    db_path = tmp_path / "projects.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    stepless_id = db.add_big_project(student["id"], "Backyard Weather Station", "Track real weather.")
    started_id = db.add_big_project(student["id"], "Stop-Motion Film", "A short film.")
    db.add_project_step(started_id, "Write the script")
    db.close()

    at = _open_checklist_tab(monkeypatch, db_path)

    keys = {b.key for b in at.button}
    assert f"chunk_project_{stepless_id}" in keys
    assert f"chunk_project_{started_id}" not in keys


def test_chunk_button_is_disabled_when_the_api_is_unavailable(monkeypatch, tmp_path):
    db_path = tmp_path / "projects.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    project_id = db.add_big_project(student["id"], "Backyard Weather Station", "Track real weather.")
    db.close()

    with patch("compass.agents.api_available", return_value=(False, "No API key configured.")):
        at = _open_checklist_tab(monkeypatch, db_path)

    button = at.button(key=f"chunk_project_{project_id}")
    assert button.disabled


# --- Backlog / To Do, same flow as a lesson's own Backlog -----------------------


def test_a_backlogged_step_is_hidden_from_the_student_view(monkeypatch, tmp_path):
    """The actual point: a step sitting in Backlog is parent-only, same as
    a backlogged lesson never showing up on Landon's own Home page."""
    db_path = tmp_path / "projects.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    auth.set_pin(db, "1234")  # is_parent() defaults True with no PIN set at all
    project_id = db.add_big_project(student["id"], "Stop-Motion Film")
    db.add_project_step(project_id, "Write the script")  # defaults to Backlog
    db.close()

    at = _open_checklist_tab(monkeypatch, db_path, as_parent=False)
    at = _expand_project(at, project_id)

    labels = [e.label for e in at.expander]
    assert not any("Write the script" in l for l in labels)


def test_an_active_step_shows_in_the_students_checklist(monkeypatch, tmp_path):
    db_path = tmp_path / "projects.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    auth.set_pin(db, "1234")
    project_id = db.add_big_project(student["id"], "Stop-Motion Film")
    db.add_project_step(project_id, "Write the script", active=True)
    db.close()

    at = _open_checklist_tab(monkeypatch, db_path, as_parent=False)
    at = _expand_project(at, project_id)

    labels = [e.label for e in at.expander]
    assert any("Write the script" in l for l in labels)


def test_backlog_section_never_renders_for_the_student(monkeypatch, tmp_path):
    db_path = tmp_path / "projects.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    auth.set_pin(db, "1234")
    project_id = db.add_big_project(student["id"], "Stop-Motion Film")
    db.add_project_step(project_id, "Write the script")  # defaults to Backlog
    db.close()

    at = _open_checklist_tab(monkeypatch, db_path, as_parent=False)
    at = _expand_project(at, project_id)

    markdowns = [m.value for m in at.markdown]
    assert not any("Backlog" in m for m in markdowns)


def test_send_to_backlog_moves_a_step_out_of_to_do(monkeypatch, tmp_path):
    db_path = tmp_path / "projects.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    project_id = db.add_big_project(student["id"], "Stop-Motion Film")
    step_id = db.add_project_step(project_id, "Write the script", active=True)
    db.close()

    at = _open_checklist_tab(monkeypatch, db_path)
    at = _expand_project(at, project_id)
    labels = [e.label for e in at.expander]
    assert any("Write the script" in l and "up next" in l for l in labels)

    at.button(key=f"backlog_step_{step_id}").click().run()

    markdowns = [m.value for m in at.markdown]
    assert any("Backlog" in m for m in markdowns)
    labels = [e.label for e in at.expander]
    assert not any("up next" in l for l in labels)
    assert any("Write the script" in l for l in labels)  # still visible, in Backlog now


def test_move_to_to_do_promotes_a_backlogged_step(monkeypatch, tmp_path):
    db_path = tmp_path / "projects.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    project_id = db.add_big_project(student["id"], "Stop-Motion Film")
    step_id = db.add_project_step(project_id, "Write the script")  # defaults to Backlog
    db.close()

    at = _open_checklist_tab(monkeypatch, db_path)
    at = _expand_project(at, project_id)

    at.button(key=f"todo_step_{step_id}").click().run()

    labels = [e.label for e in at.expander]
    assert any("Write the script" in l and "up next" in l for l in labels)
    markdowns = [m.value for m in at.markdown]
    assert not any("Backlog" in m for m in markdowns)


def test_send_to_backlog_is_not_offered_on_an_already_done_step(monkeypatch, tmp_path):
    db_path = tmp_path / "projects.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    project_id = db.add_big_project(student["id"], "Stop-Motion Film")
    step_id = db.add_project_step(project_id, "Write the script", active=True)
    db.set_project_step_done(step_id, True)
    db.close()

    at = _open_checklist_tab(monkeypatch, db_path)
    at = _expand_project(at, project_id)

    keys = {b.key for b in at.button}
    assert f"backlog_step_{step_id}" not in keys


def test_travel_log_card_shows_a_trip_summary_and_link_instead_of_steps(monkeypatch, tmp_path):
    db_path = tmp_path / "projects.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    project_id = db.ensure_travel_log_project(student["id"])
    db.add_travel_entry(student["id"], "Colorado", "2026-06-01", "Rocky Mountain hike")
    db.add_travel_entry(
        student["id"], "Utah", "2026-07-01", "", status="submitted"
    )
    db.close()

    at = _open_checklist_tab(monkeypatch, db_path)
    at = _expand_project(at, project_id)

    captions = [c.value for c in at.caption]
    assert any("1 trip" in c and "written up" in c for c in captions)
    assert any("1 still open" in c for c in captions)
    links = [pl.label for pl in at.get("page_link")]
    assert any("Landon's Travels" in label for label in links)
    # None of the step-list machinery applies to this project.
    assert not any(e.label.startswith(("1.", "2.")) for e in at.expander)


def test_travel_log_project_is_never_offered_for_the_year_pick(monkeypatch, tmp_path):
    """big_project_status_text assumes an active project has steps with a
    next one due -- never true for a travel log, so it must not be
    selectable as "the one" worked on this year."""
    db_path = tmp_path / "projects.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    project_id = db.ensure_travel_log_project(student["id"])
    db.close()

    at = _open_checklist_tab(monkeypatch, db_path)
    at = _expand_project(at, project_id)

    keys = {b.key for b in at.button}
    assert f"activate_project_{project_id}" not in keys


def test_travel_log_is_excluded_from_the_add_a_step_project_picker(monkeypatch, tmp_path):
    db_path = tmp_path / "projects.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    db.ensure_travel_log_project(student["id"])
    ordinary_id = db.add_big_project(student["id"], "Stop-Motion Film")
    db.close()

    at = _open_checklist_tab(monkeypatch, db_path)

    picker = at.selectbox(key="step_project")
    assert "Travel Log" not in picker.options
    assert "Stop-Motion Film" in picker.options
    assert ordinary_id  # sanity: an ordinary project really was added


def test_fold_in_travel_journal_button_creates_the_project(monkeypatch, tmp_path):
    db_path = tmp_path / "projects.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    db.close()

    at = _open_checklist_tab(monkeypatch, db_path)
    at.button(key="fold_in_travel_log").click().run()

    db = Database(db_path)
    projects = db.list_big_projects(student["id"])
    db.close()
    assert any(p["kind"] == "travel_log" for p in projects)


def test_fold_in_travel_journal_button_is_hidden_once_already_folded_in(monkeypatch, tmp_path):
    db_path = tmp_path / "projects.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    db.ensure_travel_log_project(student["id"])
    db.close()

    at = _open_checklist_tab(monkeypatch, db_path)

    markdowns = [m.value for m in at.markdown]
    assert not any("Fold in the Travel Journal" in m for m in markdowns)
