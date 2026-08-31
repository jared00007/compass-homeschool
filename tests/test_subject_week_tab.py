"""Each core subject page's own "This week" tab (Math, Science, English,
History): reported directly -- "shouldnt i still be able to go to each core
curriculum tab like math, english, science, histroy etc and also get the
level of detail and view into lessons. kinda like the board view of this
week and next." Reuses weekly.board_for_week/render_board_card verbatim,
filtered to that subject's own lessons, so it stays in lockstep with the
Board tab's own behavior and bugfixes.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st
from streamlit.testing.v1 import AppTest

from compass import config, weekly
from compass.storage.db import Database

REPO_ROOT = Path(__file__).resolve().parent.parent
HOME_PATH = str(REPO_ROOT / "Home.py")
MATH_PATH = str(REPO_ROOT / "pages" / "1_Math.py")
SCIENCE_PATH = str(REPO_ROOT / "pages" / "2_Science.py")


def _open_week_tab(monkeypatch, db_path, page_path):
    st.cache_resource.clear()
    monkeypatch.setattr(config, "DEFAULT_DB_PATH", db_path)
    at = AppTest.from_file(HOME_PATH)
    at.session_state["parent_unlocked"] = True
    at.run(timeout=30)
    at.switch_page(page_path)
    at.run(timeout=30)
    assert not at.exception, [e.message for e in at.exception]
    return at, _week_tab(at)


def _week_tab(at):
    return [t for t in at.tabs if t.label == "This week"][0]


def test_this_week_is_the_first_tab_on_math(monkeypatch, tmp_path):
    db_path = tmp_path / "week.db"
    Database(db_path).close()
    at, _ = _open_week_tab(monkeypatch, db_path, MATH_PATH)
    assert at.tabs[0].label == "This week"


def test_a_planned_math_lesson_shows_with_its_move_control(monkeypatch, tmp_path):
    db_path = tmp_path / "week.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    monday = weekly.week_start(weekly.default_plan_target())
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="math", subject="math", topic="t",
        title="Locking In the Coordinate Plane",
        payload={"title": "Locking In the Coordinate Plane", "activities": []},
        metadata={"planned_for": monday.isoformat(), "week_start": monday.isoformat()},
    )
    db.close()

    at, week_tab = _open_week_tab(monkeypatch, db_path, MATH_PATH)
    jump_button = [b for b in week_tab.button if b.label == "Next week"]
    assert jump_button
    jump_button[0].click().run()

    week_tab = _week_tab(at)
    labels = [e.label for e in week_tab.expander]
    assert any("Locking In the Coordinate Plane" in label for label in labels)
    assert any(b.key == f"move_board_lesson_{lesson_id}_send_to_backlog" for b in week_tab.button)


def test_a_math_lesson_does_not_leak_into_the_science_page(monkeypatch, tmp_path):
    db_path = tmp_path / "week.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    monday = weekly.week_start(weekly.default_plan_target())
    db.save_lesson(
        student_id=student["id"], agent="math", subject="math", topic="t",
        title="Locking In the Coordinate Plane",
        payload={"title": "Locking In the Coordinate Plane", "activities": []},
        metadata={"planned_for": monday.isoformat(), "week_start": monday.isoformat()},
    )
    db.close()

    at, week_tab = _open_week_tab(monkeypatch, db_path, SCIENCE_PATH)
    jump_button = [b for b in week_tab.button if b.label == "Next week"][0]
    jump_button.click().run()

    week_tab = _week_tab(at)
    labels = [e.label for e in week_tab.expander]
    assert not any("Locking In the Coordinate Plane" in label for label in labels)


def test_this_and_next_week_buttons_are_independent_of_the_board_tabs_own_picker(
    monkeypatch, tmp_path
):
    """Session state is shared across the whole browser session -- the
    subject page's own "Next week" jump must not clobber (or be clobbered
    by) This Week page's own board_week_picker, since both live in the same
    st.session_state."""
    db_path = tmp_path / "week.db"
    Database(db_path).close()

    at, week_tab = _open_week_tab(monkeypatch, db_path, MATH_PATH)
    next_week_button = [b for b in week_tab.button if b.label == "Next week"][0]
    next_week_button.click().run()

    week_tab = _week_tab(at)
    date_widget = [d for d in week_tab.date_input if d.key == "subject_week_math_picker"][0]
    assert weekly.week_start(date_widget.value) == weekly.default_plan_target()
    assert "board_week_picker" not in at.session_state


def test_view_full_lesson_works_from_within_the_subject_page(monkeypatch, tmp_path):
    db_path = tmp_path / "week.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    monday = weekly.week_start(date_today := weekly.default_plan_target())
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="math", subject="math", topic="t",
        title="Locking In the Coordinate Plane",
        payload={
            "title": "Locking In the Coordinate Plane",
            "overview": "A lesson genuinely worth reading in full.",
            "activities": [],
        },
        metadata={"planned_for": monday.isoformat(), "week_start": monday.isoformat()},
    )
    db.close()

    at, week_tab = _open_week_tab(monkeypatch, db_path, MATH_PATH)
    jump_button = [b for b in week_tab.button if b.label == "Next week"][0]
    jump_button.click().run()

    week_tab = _week_tab(at)
    view_key = f"board_view_lesson_{lesson_id}"
    assert any(b.key == view_key for b in week_tab.button)
    at.button(key=view_key).click().run()
    assert not at.exception, [e.message for e in at.exception]
    assert any(
        "A lesson genuinely worth reading in full." in m.value for m in at.markdown
    )
