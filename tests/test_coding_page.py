"""Coding Camp -- same shape as Core Life Skills throughout (its own
active/backlog gate, its own master-list pace control), just its own page
and its own catalog. These tests mirror test_life_skills.py's own
checklist-visibility coverage rather than duplicating the AI-planner tests
that file has -- Coding Camp has no agent in v1.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st
from streamlit.testing.v1 import AppTest

from compass import auth, config
from compass.storage.db import Database

REPO_ROOT = Path(__file__).resolve().parent.parent
HOME_PATH = str(REPO_ROOT / "Home.py")
CODING_PATH = str(REPO_ROOT / "pages" / "17_Coding.py")


def _open(monkeypatch, db_path, *, as_parent=True):
    st.cache_resource.clear()
    monkeypatch.setattr(config, "DEFAULT_DB_PATH", db_path)
    at = AppTest.from_file(HOME_PATH)
    if as_parent:
        at.session_state["parent_unlocked"] = True
    at.run(timeout=30)
    at.switch_page(CODING_PATH)
    at.run(timeout=30)
    assert not at.exception, [e.message for e in at.exception]
    return at


def test_seed_button_shows_when_the_checklist_is_empty(monkeypatch, tmp_path):
    db_path = tmp_path / "coding.db"
    db = Database(db_path)
    db.ensure_default_student()
    db.close()

    at = _open(monkeypatch, db_path)

    assert any("No checklist yet" in i.value for i in at.info)
    assert any(b.label == "Seed the starter catalog" for b in at.button)


def test_seed_button_populates_the_master_catalog(monkeypatch, tmp_path):
    db_path = tmp_path / "coding.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    db.close()

    at = _open(monkeypatch, db_path)
    seed_button = [b for b in at.button if b.label == "Seed the starter catalog"][0]
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


def test_marking_a_module_done_updates_the_record(monkeypatch, tmp_path):
    db_path = tmp_path / "coding.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    module_id = db.add_coding_module(student["id"], "Zzz Custom Test Module")
    db.close()

    at = _open(monkeypatch, db_path)
    at.checkbox(key=f"coding_done_{module_id}").set_value(True).run()

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
    master_tab = [t for t in at.tabs if t.label == "Master list"][0]
    active_checkbox = [
        c for c in master_tab.checkbox if c.key.startswith(f"coding_active_{module_id}_")
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
    manage_tab = [t for t in at.tabs if t.label == "Add a module"][0]
    title_input = [i for i in manage_tab.text_input if i.label == "Module"][0]
    title_input.set_value("Automate my alarm")
    manage_tab.button[0].click().run()

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
    log_tab = [t for t in at.tabs if t.label == "Log time"][0]
    # The catalog auto-tops-up the moment a family has *any* module (see
    # _backfill_coding_module_catalog), so the selectbox has more than just
    # this test's own entry -- pick it explicitly rather than trust the
    # default option.
    module_select = [s for s in log_tab.selectbox if s.label == "Module"][0]
    module_select.set_value("General — Zzz Custom Test Module")
    mark_done = [c for c in log_tab.checkbox if c.label == "Mark this module done"][0]
    mark_done.set_value(True)
    log_button = [b for b in log_tab.button if b.label == "Log hours"][0]
    log_button.click().run()

    db = Database(db_path)
    module = next(m for m in db.list_coding_modules(student["id"]) if m["id"] == module_id)
    activities = db.conn.execute(
        "SELECT * FROM activities WHERE student_id = ? AND tier = 'coding'", (student["id"],)
    ).fetchall()
    db.close()
    assert module["completed_on"] is not None
    assert len(activities) == 1
