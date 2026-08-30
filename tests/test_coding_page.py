"""Coding Camp -- same shape as Core Life Skills throughout (its own
active/backlog gate, its own master-list pace control), folded into the
Life Skills page as a flat section (see pages/6_Life_Skills.py's "Coding"
tab) rather than kept as its own top-level page. These tests mirror
test_life_skills.py's own checklist-visibility coverage rather than
duplicating the AI-planner tests that file has (see test_coding_plan.py
for those). "Write a build guide" itself is never clicked here, same
reasoning test_big_projects_page.py's own AI-chunk button test gives: it
calls the live Anthropic API, which this suite has no business spending
money on per test run -- this only covers the button's own visibility and
wiring.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st
from streamlit.testing.v1 import AppTest

from compass import auth, config
from compass.storage.db import Database

REPO_ROOT = Path(__file__).resolve().parent.parent
HOME_PATH = str(REPO_ROOT / "Home.py")
LIFE_SKILLS_PATH = str(REPO_ROOT / "pages" / "6_Life_Skills.py")


def _open(monkeypatch, db_path, *, as_parent=True):
    st.cache_resource.clear()
    monkeypatch.setattr(config, "DEFAULT_DB_PATH", db_path)
    at = AppTest.from_file(HOME_PATH)
    if as_parent:
        at.session_state["parent_unlocked"] = True
    at.run(timeout=30)
    at.switch_page(LIFE_SKILLS_PATH)
    at.run(timeout=30)
    assert not at.exception, [e.message for e in at.exception]
    return at


def _coding_tab(at):
    return [t for t in at.tabs if t.label == "Coding"][0]


def test_coding_is_no_longer_its_own_sidebar_page(monkeypatch, tmp_path):
    db_path = tmp_path / "coding.db"
    Database(db_path).close()

    at = _open(monkeypatch, db_path)
    assert any(t.label == "Coding" for t in at.tabs)


def test_seed_button_shows_when_the_checklist_is_empty(monkeypatch, tmp_path):
    db_path = tmp_path / "coding.db"
    db = Database(db_path)
    db.ensure_default_student()
    db.close()

    at = _open(monkeypatch, db_path)
    coding_tab = _coding_tab(at)

    assert any("No checklist yet" in i.value for i in coding_tab.info)
    assert any(b.label == "Seed the starter catalog" for b in coding_tab.button)


def test_seed_button_populates_the_master_catalog(monkeypatch, tmp_path):
    db_path = tmp_path / "coding.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    db.close()

    at = _open(monkeypatch, db_path)
    coding_tab = _coding_tab(at)
    seed_button = [b for b in coding_tab.button if b.label == "Seed the starter catalog"][0]
    seed_button.click().run()

    db = Database(db_path)
    modules = db.list_coding_modules(student["id"])
    db.close()
    assert len(modules) >= 15


def test_a_locked_module_is_hidden_from_the_student_view(monkeypatch, tmp_path):
    db_path = tmp_path / "coding.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    auth.set_pin(db, "1234")  # is_parent() defaults True with no PIN set at all
    db.add_coding_module(student["id"], "Zzz Custom Test Module")
    module_id = db.list_coding_modules(student["id"])[0]["id"]
    db.set_coding_module_active(module_id, False)
    db.close()

    # Student view has no tab strip at all (checklist_tab/choice_tab/
    # coding_tab are plain stacked containers there) -- query the whole
    # page rather than a labeled tab, same as every other student-view
    # check on this page already does.
    at = _open(monkeypatch, db_path, as_parent=False)

    markdowns = [m.value for m in at.markdown]
    assert not any("Zzz Custom Test Module" in m for m in markdowns)


def test_an_unlocked_module_shows_in_the_students_checklist(monkeypatch, tmp_path):
    db_path = tmp_path / "coding.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    auth.set_pin(db, "1234")
    db.add_coding_module(student["id"], "Zzz Custom Test Module")
    db.close()

    at = _open(monkeypatch, db_path, as_parent=False)

    markdowns = [m.value for m in at.markdown]
    assert any("Zzz Custom Test Module" in m for m in markdowns)


def test_the_move_control_never_shows_in_the_students_checklist(monkeypatch, tmp_path):
    """Regression: render_coding_module_cards used to render the shared
    story-move control (backlog/schedule popover) unconditionally, the same
    bug render_life_skill_cards had -- both slipped through because every
    *other* surface that control got wired into (Big Projects, Choice
    Topics, lesson review cards) already gated it on is_parent(), so the
    omission here wasn't caught by copy-paste review. This is parent-only:
    he never gets to backlog or reschedule his own checklist."""
    db_path = tmp_path / "coding.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    auth.set_pin(db, "1234")
    db.add_coding_module(student["id"], "Zzz Custom Test Module")
    db.close()

    at = _open(monkeypatch, db_path, as_parent=False)

    move_keys = [c.key for c in at.checkbox if c.key and c.key.startswith("move_coding_")]
    assert move_keys == []


def test_marking_a_module_done_updates_the_record(monkeypatch, tmp_path):
    db_path = tmp_path / "coding.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    module_id = db.add_coding_module(student["id"], "Zzz Custom Test Module")
    db.close()

    at = _open(monkeypatch, db_path)
    coding_tab = _coding_tab(at)
    [c for c in coding_tab.checkbox if c.key == f"coding_done_{module_id}"][0].set_value(True).run()

    db = Database(db_path)
    module = next(m for m in db.list_coding_modules(student["id"]) if m["id"] == module_id)
    db.close()
    assert module["completed_on"] is not None


def test_master_list_can_unlock_a_locked_module(monkeypatch, tmp_path):
    db_path = tmp_path / "coding.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    module_id = db.add_coding_module(student["id"], "Zzz Custom Test Module")
    db.set_coding_module_active(module_id, False)
    db.close()

    at = _open(monkeypatch, db_path)
    coding_tab = _coding_tab(at)
    active_checkbox = [
        c for c in coding_tab.checkbox if c.key.startswith(f"coding_active_{module_id}_")
    ][0]
    active_checkbox.set_value(True).run()

    db = Database(db_path)
    module = next(m for m in db.list_coding_modules(student["id"]) if m["id"] == module_id)
    db.close()
    assert module["active"] == 1


def test_add_a_module_form_creates_it(monkeypatch, tmp_path):
    db_path = tmp_path / "coding.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    db.close()

    at = _open(monkeypatch, db_path)
    coding_tab = _coding_tab(at)
    title_input = [i for i in coding_tab.text_input if i.key == "coding_add_title"][0]
    title_input.set_value("Automate my alarm")
    submit = [b for b in coding_tab.button if b.label == "Add module"][0]
    submit.click().run()

    db = Database(db_path)
    titles = {m["title"] for m in db.list_coding_modules(student["id"])}
    db.close()
    assert "Automate my alarm" in titles


def test_log_time_records_an_activity_and_can_mark_done(monkeypatch, tmp_path):
    db_path = tmp_path / "coding.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    module_id = db.add_coding_module(student["id"], "Zzz Custom Test Module")
    db.close()

    at = _open(monkeypatch, db_path)
    coding_tab = _coding_tab(at)
    # The catalog auto-tops-up the moment a family has *any* module (see
    # _backfill_coding_module_catalog), so the selectbox has more than just
    # this test's own entry -- pick it explicitly rather than trust the
    # default option.
    module_select = [s for s in coding_tab.selectbox if s.label == "Module"][0]
    module_select.set_value("General — Zzz Custom Test Module")
    mark_done = [c for c in coding_tab.checkbox if c.key == "coding_log_done"][0]
    mark_done.set_value(True)
    log_button = [b for b in coding_tab.button if b.label == "Log hours"][0]
    log_button.click().run()

    db = Database(db_path)
    module = next(m for m in db.list_coding_modules(student["id"]) if m["id"] == module_id)
    activities = db.conn.execute(
        "SELECT * FROM activities WHERE student_id = ? AND tier = 'coding'", (student["id"],)
    ).fetchall()
    db.close()
    assert module["completed_on"] is not None
    assert len(activities) == 1


def test_plan_a_build_guide_section_shows_up_for_parents(monkeypatch, tmp_path):
    db_path = tmp_path / "coding.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    db.add_coding_module(student["id"], "Zzz Custom Test Module")
    db.close()

    at = _open(monkeypatch, db_path)
    coding_tab = _coding_tab(at)

    assert any("Plan a build guide" in m.value for m in coding_tab.markdown)
    assert any(b.label == "Write a build guide" for b in coding_tab.button)
    assert any(s.label == "Which module" for s in coding_tab.selectbox)


def test_plan_a_build_guide_section_is_hidden_from_the_student(monkeypatch, tmp_path):
    db_path = tmp_path / "coding.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    auth.set_pin(db, "1234")
    db.add_coding_module(student["id"], "Zzz Custom Test Module")
    db.close()

    at = _open(monkeypatch, db_path, as_parent=False)

    assert not any("Plan a build guide" in m.value for m in at.markdown)
    assert not any(b.label == "Write a build guide" for b in at.button)
