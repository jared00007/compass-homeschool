"""Big Projects' 'choice' mode: a branching tree instead of one fixed
sequence -- finishing a step reveals whatever branches off of it as the
next set of paths to pick between (see big_projects.mode/project_steps.
parent_step_id and _step_chain/_step_choices/_render_choice_steps in
pages/7_Big_Projects.py).
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st
from streamlit.testing.v1 import AppTest

from compass import config
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
    at.button(key=f"toggle_project_{project_id}").click().run()
    return at


def test_add_project_form_offers_a_mode_choice(monkeypatch, tmp_path):
    db_path = tmp_path / "projects.db"
    Database(db_path).close()

    at = _open_checklist_tab(monkeypatch, db_path)
    manage_tab = at.tabs[2]
    labels = [r.label for r in manage_tab.radio]
    assert any("How should this one flow" in (label or "") for label in labels)


def test_creating_a_choice_mode_project_via_the_form_sets_its_mode(monkeypatch, tmp_path):
    db_path = tmp_path / "projects.db"
    Database(db_path).close()

    at = _open_checklist_tab(monkeypatch, db_path)
    manage_tab = at.tabs[2]
    title_input = [t for t in manage_tab.text_input if t.label == "Project title"][0]
    title_input.set_value("Branch Adventure")
    manage_tab.radio[0].set_value("choice")
    submit = [b for b in manage_tab.button if b.label == "Add project"][0]
    submit.click().run()

    db = Database(db_path)
    try:
        project = next(
            p for p in db.list_big_projects(db.ensure_default_student()["id"])
            if p["title"] == "Branch Adventure"
        )
        assert project["mode"] == "choice"
    finally:
        db.close()


def test_add_step_form_shows_branch_selector_only_for_choice_projects(monkeypatch, tmp_path):
    db_path = tmp_path / "projects.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    linear_id = db.add_big_project(student["id"], "Linear Project")
    choice_id = db.add_big_project(student["id"], "Branching Project", mode="choice")
    db.add_project_step(choice_id, "Path A", active=True)
    db.close()

    at = _open_checklist_tab(monkeypatch, db_path)
    manage_tab = at.tabs[2]
    project_select = manage_tab.selectbox(key="step_project")
    project_select.select_index(project_select.options.index("Linear Project")).run()
    manage_tab = at.tabs[2]
    parent_keys = {s.key for s in manage_tab.selectbox if s.key == "step_parent"}
    assert not parent_keys, "a linear project must not offer a branch-point selector"

    project_select = manage_tab.selectbox(key="step_project")
    project_select.select_index(project_select.options.index("Branching Project")).run()
    manage_tab = at.tabs[2]
    parent_select = manage_tab.selectbox(key="step_parent")
    assert "Start of the project" in parent_select.options


def test_choosing_a_branch_completes_it_and_reveals_its_children(monkeypatch, tmp_path):
    db_path = tmp_path / "projects.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    project_id = db.add_big_project(student["id"], "Branching Project", mode="choice")
    root_a = db.add_project_step(project_id, "Path A start", active=True)
    root_b = db.add_project_step(project_id, "Path B start", active=True)
    child_a1 = db.add_project_step(project_id, "A, leg two", parent_step_id=root_a, active=True)
    db.close()

    at = _open_checklist_tab(monkeypatch, db_path)
    at = _expand_project(at, project_id)

    labels = [e.label for e in at.expander]
    assert any("Path A start" in l for l in labels)
    assert any("Path B start" in l for l in labels)
    assert not any("A, leg two" in l for l in labels), "an unreached branch must not show yet"

    at.button(key=f"parent_done_step_{root_a}").click().run()

    captions = [c.value for c in at.caption]
    assert any("Path A start" in c and "✅" in c for c in captions)
    labels = [e.label for e in at.expander]
    assert not any("Path B start" in l for l in labels), "the branch not taken drops off the choice list"
    assert any("A, leg two" in l for l in labels), "finishing the root reveals its own child"
    _ = root_b


def test_a_true_leaf_reached_shows_the_end_of_path_message(monkeypatch, tmp_path):
    db_path = tmp_path / "projects.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    project_id = db.add_big_project(student["id"], "Branching Project", mode="choice")
    only_step = db.add_project_step(project_id, "The only step", active=True)
    db.close()

    at = _open_checklist_tab(monkeypatch, db_path)
    at = _expand_project(at, project_id)
    at.button(key=f"parent_done_step_{only_step}").click().run()

    successes = [s.value for s in at.success]
    assert any("End of this path" in s for s in successes)


def test_backlog_labels_a_branch_by_where_it_branches_from(monkeypatch, tmp_path):
    db_path = tmp_path / "projects.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    project_id = db.add_big_project(student["id"], "Branching Project", mode="choice")
    root_a = db.add_project_step(project_id, "Path A start", active=True)
    db.add_project_step(project_id, "A, leg two", parent_step_id=root_a, active=False)
    db.add_project_step(project_id, "Path C start", active=False)
    db.close()

    at = _open_checklist_tab(monkeypatch, db_path)
    at = _expand_project(at, project_id)

    labels = [e.label for e in at.expander]
    assert any('branches from "Path A start"' in l for l in labels)
    assert any("a starting option" in l and "Path C start" in l for l in labels)
