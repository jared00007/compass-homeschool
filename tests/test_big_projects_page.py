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

from datetime import date, timedelta
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


def test_starter_catalog_banner_still_shows_with_only_the_travel_log_project(monkeypatch, tmp_path):
    """The automatic Travel Log project (see Database.ensure_travel_log_project,
    always present from a student's very first page view) must not itself
    count as "you already have a project" -- otherwise the "No projects
    yet" banner and its seed button would never show for anyone at all."""
    db_path = tmp_path / "projects.db"
    db = Database(db_path)
    db.ensure_default_student()
    db.close()

    at = _open_checklist_tab(monkeypatch, db_path)

    infos = [i.value for i in at.info]
    assert any("No projects yet" in i for i in infos)
    assert any(b.label == "Add this year's starter projects" for b in at.button)


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


def test_send_to_backlog_is_not_offered_on_an_active_step_only_date_assignment_is(
    monkeypatch, tmp_path
):
    """Reported directly against a live screenshot of this exact popover:
    "this action shouldnt be send to backlog, i should be able to push
    this to any date this week or next week. just assign to date." A
    project step is a sequential, up-next-driven plan, not a flexible
    weekly board -- parking an active step doesn't make sense mid-plan,
    and the "Send to backlog" button read as the only offered action when
    what a parent actually wants is just to move it to a different day.
    `show_backlog_toggle=False` on this call site drops the button
    entirely; assigning a day is still the one and only action, and it
    still works exactly as before (the date_input's own on-change already
    reschedules with no separate confirm step)."""
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

    keys = {b.key for b in at.button if b.key}
    assert not any(k.startswith(f"move_step_{step_id}_send_to_backlog") for k in keys)

    checkbox = [c for c in at.checkbox if c.key == f"move_step_{step_id}_assign_None"]
    assert checkbox, "the date checkbox must still be offered on an active step"
    checkbox[0].set_value(True).run()
    assert not at.exception, [e.message for e in at.exception]
    # Checking the box on its own already assigns today's date (the same
    # behavior every other move control has) -- the date_input's own key
    # folds in whatever's now current, so it moves too.

    date_widget = [
        d for d in at.date_input if d.key and d.key.startswith(f"move_step_{step_id}_date_")
    ][0]
    target_day = date.today() + timedelta(days=9)  # some day next week
    date_widget.set_value(target_day).run()
    assert not at.exception, [e.message for e in at.exception]

    db = Database(db_path)
    step = next(s for s in db.list_project_steps(project_id) if s["id"] == step_id)
    db.close()
    assert step["scheduled_for"] == target_day.isoformat()
    assert step["active"] == 1  # still active, still up next -- just moved


def test_move_to_to_do_promotes_a_backlogged_step(monkeypatch, tmp_path):
    db_path = tmp_path / "projects.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    project_id = db.add_big_project(student["id"], "Stop-Motion Film")
    step_id = db.add_project_step(project_id, "Write the script")  # defaults to Backlog
    db.close()

    at = _open_checklist_tab(monkeypatch, db_path)
    at = _expand_project(at, project_id)

    at.button(key=f"move_step_{step_id}_take_out_of_backlog").click().run()

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

    keys = {b.key for b in at.button if b.key}
    assert not any(
        k.startswith(f"move_step_{step_id}_send_to_backlog")
        or k.startswith(f"move_step_{step_id}_take_out_of_backlog")
        for k in keys
    )


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


def test_the_travel_log_project_exists_automatically_for_a_brand_new_student(monkeypatch, tmp_path):
    """Always present, not opt-in -- page_setup calls
    Database.ensure_travel_log_project on every load now, so a family never
    has to find and click a button to get it; it's just there from the
    very first page view, same as the Travel Journal itself always was."""
    db_path = tmp_path / "projects.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    db.close()

    _open_checklist_tab(monkeypatch, db_path)

    db = Database(db_path)
    projects = db.list_big_projects(student["id"])
    db.close()
    assert any(p["kind"] == "travel_log" for p in projects)


def test_reorder_steps_up_button_swaps_with_the_previous_step(monkeypatch, tmp_path):
    """The move control only ever handles a day or Backlog, never step
    *order* -- this is the only UI for changing which step comes next in
    a linear project's fixed sequence (see db.move_project_step)."""
    db_path = tmp_path / "projects.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    project_id = db.add_big_project(student["id"], "Stop-Motion Film")
    step_a = db.add_project_step(project_id, "Step A")
    step_b = db.add_project_step(project_id, "Step B")
    db.add_project_step(project_id, "Step C")
    db.close()

    at = _open_checklist_tab(monkeypatch, db_path)
    manage_tab = at.tabs[2]
    project_select = manage_tab.selectbox(key="reorder_project")
    project_select.select_index(project_select.options.index("Stop-Motion Film")).run()

    manage_tab = at.tabs[2]
    up_button = [b for b in manage_tab.button if b.key == f"step_up_{step_b}"][0]
    assert not up_button.disabled
    up_button.click().run()

    db = Database(db_path)
    steps = [s["title"] for s in db.list_project_steps(project_id)]
    db.close()
    assert steps == ["Step B", "Step A", "Step C"]


def test_reorder_steps_boundary_buttons_are_disabled(monkeypatch, tmp_path):
    db_path = tmp_path / "projects.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    project_id = db.add_big_project(student["id"], "Stop-Motion Film")
    step_a = db.add_project_step(project_id, "Step A")
    step_b = db.add_project_step(project_id, "Step B")
    db.close()

    at = _open_checklist_tab(monkeypatch, db_path)
    manage_tab = at.tabs[2]
    project_select = manage_tab.selectbox(key="reorder_project")
    project_select.select_index(project_select.options.index("Stop-Motion Film")).run()

    manage_tab = at.tabs[2]
    first_up = [b for b in manage_tab.button if b.key == f"step_up_{step_a}"][0]
    last_down = [b for b in manage_tab.button if b.key == f"step_down_{step_b}"][0]
    assert first_up.disabled
    assert last_down.disabled


def _steps_project(db, student_id, *, active=True):
    pid = db.add_big_project(student_id=student_id, title="Toy Photography", vision="v")
    step = db.add_project_step(pid, "Pick your toy and your theme", active=active)
    db.schedule_project_step(step, date.today().isoformat())
    return pid, step


def test_student_submits_a_step_for_review(monkeypatch, tmp_path):
    """The student side of the gate: a due step offers "Submit for review",
    which turns it in (status submitted) rather than silently marking it done."""
    db_path = tmp_path / "projects.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    auth.set_pin(db, "1234")
    project_id, step = _steps_project(db, student["id"])
    db.close()

    at = _open_checklist_tab(monkeypatch, db_path, as_parent=False)
    at = _expand_project(at, project_id)
    at.button(key=f"submit_step_{step}").click().run()
    assert not at.exception, [e.message for e in at.exception]

    db2 = Database(db_path)
    row = db2.list_project_steps(project_id)[0]
    db2.close()
    assert row["status"] == "submitted"


def test_parent_approves_a_submitted_step(monkeypatch, tmp_path):
    """The parent side: a submitted step offers Approve, which completes it."""
    db_path = tmp_path / "projects.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    auth.set_pin(db, "1234")
    project_id, step = _steps_project(db, student["id"])
    db.submit_project_step(step, "Chose the red car.")
    db.close()

    at = _open_checklist_tab(monkeypatch, db_path, as_parent=True)
    at = _expand_project(at, project_id)
    at.button(key=f"approve_step_{step}").click().run()
    assert not at.exception, [e.message for e in at.exception]

    db2 = Database(db_path)
    row = db2.list_project_steps(project_id)[0]
    db2.close()
    assert row["status"] == "completed"
    assert row["completed_on"] is not None
