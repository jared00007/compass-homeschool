"""This Week's "Plan next week" tab: the school-days-this-week checkboxes
that let a holiday (or a field trip, or anything else that shrinks the
week) skip a day entirely rather than always generating for all four.

Built because "Plan next week" always targeted a fixed Monday-Thursday --
there was no way to say a given week only needed two or three days, short
of generating all four and deleting the one that didn't belong.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import streamlit as st
from streamlit.testing.v1 import AppTest

from compass import config, weekly
from compass.storage.db import Database

REPO_ROOT = Path(__file__).resolve().parent.parent
HOME_PATH = str(REPO_ROOT / "Home.py")
THIS_WEEK_PATH = str(REPO_ROOT / "pages" / "14_This_Week.py")

# A fixed Monday, not date.today() -- the page's own date_input is set
# explicitly below regardless, so this just needs to be *a* Monday.
TARGET_MONDAY = weekly.week_start(date(2026, 11, 23))


def _open_plan_tab(monkeypatch, db_path):
    st.cache_resource.clear()
    monkeypatch.setattr(config, "DEFAULT_DB_PATH", db_path)
    at = AppTest.from_file(HOME_PATH)
    at.session_state["parent_unlocked"] = True
    at.run(timeout=30)
    at.switch_page(THIS_WEEK_PATH)
    at.run(timeout=30)
    assert not at.exception, [e.message for e in at.exception]
    date_picker = [d for d in at.date_input if d.label.startswith("Week to plan")][0]
    date_picker.set_value(TARGET_MONDAY).run()
    assert not at.exception, [e.message for e in at.exception]
    return at, _plan_tab(at)


def _plan_tab(at):
    return [t for t in at.tabs if t.label == "Plan next week"][0]


def test_all_four_days_are_checked_by_default(monkeypatch, tmp_path):
    db_path = tmp_path / "week.db"
    db = Database(db_path)
    db.ensure_default_student()
    db.close()

    _, plan_tab = _open_plan_tab(monkeypatch, db_path)
    checkboxes = [c for c in plan_tab.checkbox if c.label in weekly.WEEKDAY_NAMES]
    assert len(checkboxes) == 4
    assert all(c.value is True for c in checkboxes)


def test_unchecking_the_only_missing_day_disables_that_subjects_button(monkeypatch, tmp_path):
    db_path = tmp_path / "week.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    dates = weekly.week_dates(TARGET_MONDAY)
    # Mon-Wed already planned for math; only Thursday is still missing.
    for d in dates[:3]:
        db.save_lesson(
            student_id=student["id"], agent="math", subject="math", topic="t", title="t",
            payload={"title": "t", "activities": []},
            metadata={"week_start": TARGET_MONDAY.isoformat(), "planned_for": d.isoformat()},
        )
    db.close()

    at, plan_tab = _open_plan_tab(monkeypatch, db_path)
    button = [b for b in plan_tab.button if b.key == "regen_week_math"][0]
    assert button.disabled is False  # Thursday still missing

    thursday = [c for c in plan_tab.checkbox if c.label == "Thursday"][0]
    thursday.set_value(False).run()
    plan_tab = _plan_tab(at)
    button = [b for b in plan_tab.button if b.key == "regen_week_math"][0]
    assert button.disabled is True  # nothing missing among the days still checked


def test_unchecking_a_day_does_not_affect_other_subjects(monkeypatch, tmp_path):
    """The picker is shared, but each subject's own missing-days set is
    still its own -- Science having nothing planned at all must still show
    as missing even once Thursday's unchecked for everyone."""
    db_path = tmp_path / "week.db"
    db = Database(db_path)
    db.ensure_default_student()
    db.close()

    at, plan_tab = _open_plan_tab(monkeypatch, db_path)
    thursday = [c for c in plan_tab.checkbox if c.label == "Thursday"][0]
    thursday.set_value(False).run()
    plan_tab = _plan_tab(at)
    science_button = [b for b in plan_tab.button if b.key == "regen_week_science"][0]
    assert science_button.disabled is False  # Mon-Wed still missing for Science


def test_unchecking_every_day_shows_a_message_and_disables_everything(monkeypatch, tmp_path):
    db_path = tmp_path / "week.db"
    db = Database(db_path)
    db.ensure_default_student()
    db.close()

    at, plan_tab = _open_plan_tab(monkeypatch, db_path)
    for name in weekly.WEEKDAY_NAMES:
        checkbox = [c for c in plan_tab.checkbox if c.label == name][0]
        checkbox.set_value(False).run()
        plan_tab = _plan_tab(at)

    text = " ".join(i.value for i in plan_tab.info)
    assert "check at least one" in text.lower()
    week_buttons = [b for b in plan_tab.button if b.key and b.key.startswith("regen_week_")]
    assert week_buttons
    assert all(b.disabled for b in week_buttons)


def test_the_first_checked_day_gets_the_topic_picker_even_if_its_not_monday(
    monkeypatch, tmp_path
):
    """Regression for the actual point of this feature: a Monday holiday
    must hand the topic picker to Tuesday instead, not silently drop it or
    leave it mislabeled "Monday's topic" on a Tuesday card."""
    db_path = tmp_path / "week.db"
    db = Database(db_path)
    db.ensure_default_student()
    db.close()

    at, plan_tab = _open_plan_tab(monkeypatch, db_path)
    monday = [c for c in plan_tab.checkbox if c.label == "Monday"][0]
    monday.set_value(False).run()
    plan_tab = _plan_tab(at)
    labels = [s.label for s in plan_tab.selectbox] + [t.label for t in plan_tab.text_input]
    assert any(label.startswith("Tuesday's topic") for label in labels)
    assert not any(label.startswith("Monday's topic") for label in labels)
