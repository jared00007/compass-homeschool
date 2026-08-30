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


def test_friday_is_offered_but_unchecked_by_default(monkeypatch, tmp_path):
    """Reported directly: a holiday landing on a weekday shouldn't mean the
    week only gets three lesson days -- Friday's available as a fifth
    option, but stays unchecked unless a parent opts it in, since it's
    normally the review/light day instead."""
    db_path = tmp_path / "week.db"
    db = Database(db_path)
    db.ensure_default_student()
    db.close()

    _, plan_tab = _open_plan_tab(monkeypatch, db_path)
    friday = [c for c in plan_tab.checkbox if c.label == "Friday"]
    assert len(friday) == 1
    assert friday[0].value is False


def test_checking_friday_covers_for_a_holiday_earlier_in_the_week(monkeypatch, tmp_path):
    """The actual point of the feature: Tuesday-Thursday already planned,
    Monday's a holiday (so nothing's ever seeded for it) -- unchecking
    Monday alone leaves nothing missing, but checking Friday too gives the
    week its fourth lesson day back."""
    db_path = tmp_path / "week.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    dates = weekly.week_dates(TARGET_MONDAY)
    for d in dates[1:]:
        db.save_lesson(
            student_id=student["id"], agent="math", subject="math", topic="t", title="t",
            payload={"title": "t", "activities": []},
            metadata={"week_start": TARGET_MONDAY.isoformat(), "planned_for": d.isoformat()},
        )
    db.close()

    at, plan_tab = _open_plan_tab(monkeypatch, db_path)
    monday = [c for c in plan_tab.checkbox if c.label == "Monday"][0]
    monday.set_value(False).run()
    plan_tab = _plan_tab(at)
    button = [b for b in plan_tab.button if b.key == "regen_week_math"][0]
    assert button.disabled is True  # Tue-Thu already cover the three checked days

    friday = [c for c in plan_tab.checkbox if c.label == "Friday"][0]
    friday.set_value(True).run()
    plan_tab = _plan_tab(at)
    button = [b for b in plan_tab.button if b.key == "regen_week_math"][0]
    assert button.disabled is False  # Friday's checked now and still missing a lesson


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


def test_the_move_control_can_send_a_planned_lesson_to_backlog(monkeypatch, tmp_path):
    """The actual point of the sprint-board request: a lesson already sitting
    on a specific day in "Plan next week" needs the same freedom to move to
    Backlog (or another day) that Activity Log's own Backlog tab already
    gives -- not just after the fact once its week has run out, but right
    here while planning it."""
    db_path = tmp_path / "week.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="math", subject="math", topic="t",
        title="Locking In the Coordinate Plane",
        payload={"title": "Locking In the Coordinate Plane", "activities": []},
        metadata={
            "planned_for": TARGET_MONDAY.isoformat(),
            "week_start": TARGET_MONDAY.isoformat(),
        },
    )
    db.close()

    at, plan_tab = _open_plan_tab(monkeypatch, db_path)
    backlog_key = f"move_weekplan_lesson_{lesson_id}_backlog_True"
    checkbox = [c for c in plan_tab.checkbox if c.key == backlog_key]
    assert checkbox, "the move control's backlog toggle must be offered on a planned lesson"
    checkbox[0].set_value(True).run()

    db = Database(db_path)
    lesson = db.get_lesson(lesson_id)
    db.close()
    assert lesson["metadata"].get("held_back") is True


def test_the_move_control_offers_moving_to_a_different_day(monkeypatch, tmp_path):
    db_path = tmp_path / "week.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="science", subject="science", topic="t",
        title="Backyard Ecosystem",
        payload={"title": "Backyard Ecosystem", "activities": []},
        metadata={
            "planned_for": TARGET_MONDAY.isoformat(),
            "week_start": TARGET_MONDAY.isoformat(),
        },
    )
    db.close()

    _, plan_tab = _open_plan_tab(monkeypatch, db_path)
    date_key = f"move_weekplan_lesson_{lesson_id}_date_{TARGET_MONDAY.isoformat()}"
    date_widget = [d for d in plan_tab.date_input if d.key == date_key]
    assert date_widget, "the move control's date picker must be offered on a planned lesson"
