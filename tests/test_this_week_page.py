"""This Week's "Plan next week" tab: the school-days-this-week checkboxes
that let a holiday (or a field trip, or anything else that shrinks the
week) skip a day entirely rather than always generating for all four.

Built because "Plan next week" always targeted a fixed Monday-Thursday --
there was no way to say a given week only needed two or three days, short
of generating all four and deleting the one that didn't belong.
"""

from __future__ import annotations

from datetime import date, timedelta
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
    backlog_key = f"move_weekplan_lesson_{lesson_id}_send_to_backlog"
    button = [b for b in plan_tab.button if b.key == backlog_key]
    assert button, "the move control's Send to backlog button must be offered on a planned lesson"
    button[0].click().run()

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


# --- the Board tab: every subject's stories, one week, one place ----------------


def _open_board_tab(monkeypatch, db_path):
    st.cache_resource.clear()
    monkeypatch.setattr(config, "DEFAULT_DB_PATH", db_path)
    at = AppTest.from_file(HOME_PATH)
    at.session_state["parent_unlocked"] = True
    at.run(timeout=30)
    at.switch_page(THIS_WEEK_PATH)
    at.run(timeout=30)
    assert not at.exception, [e.message for e in at.exception]
    date_picker = [d for d in at.date_input if d.label == "Week to view"][0]
    date_picker.set_value(TARGET_MONDAY).run()
    assert not at.exception, [e.message for e in at.exception]
    return at, _board_tab(at)


def _board_tab(at):
    return [t for t in at.tabs if t.label == "📋 Board"][0]


def test_board_is_the_first_tab(monkeypatch, tmp_path):
    db_path = tmp_path / "week.db"
    Database(db_path).close()
    at, _ = _open_board_tab(monkeypatch, db_path)
    assert at.tabs[0].label == "📋 Board"


def test_a_planned_lesson_shows_on_the_board_with_a_move_control(monkeypatch, tmp_path):
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

    _, board_tab = _open_board_tab(monkeypatch, db_path)
    labels = [e.label for e in board_tab.expander]
    assert any("Locking In the Coordinate Plane" in label for label in labels)
    backlog_key = f"move_board_lesson_{lesson_id}_send_to_backlog"
    assert any(b.key == backlog_key for b in board_tab.button)
    # "Deeper review" link: a lesson's real full-content view lives in
    # Activity Log's own review queue, not the Math/Science/English/History
    # pages -- those are planning tools with nothing to show for a lesson
    # that's already been generated.
    captions = " ".join(c.value for c in board_tab.caption)
    assert 'Under the "To review" tab.' in captions


def test_moving_a_story_to_a_different_week_shows_a_notice_not_just_a_vanish(
    monkeypatch, tmp_path
):
    """A parent moving a backlogged lesson onto a date that lands in a
    *different* week (reported directly: "i moved two math lessons from
    backlog to their own dates... and they have disappeared") must never
    just vanish from the board with no explanation -- board_for_week only
    ever returns the one week it's asked for, so the card leaving the
    currently-viewed week is correct, but it needs to say so. This can't
    be `st.toast` -- confirmed against this app's actual Streamlit version
    that a toast fired in the same run as the move control's own
    `st.rerun()` never reaches the browser at all -- so the notice has to
    survive via session_state and render as a real `st.info` instead.
    """
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
            "held_back": True,
        },
    )
    db.close()

    at, board_tab = _open_board_tab(monkeypatch, db_path)
    date_key = f"move_board_lesson_{lesson_id}_date_{TARGET_MONDAY.isoformat()}"
    date_widget = [d for d in board_tab.date_input if d.key == date_key][0]
    next_week_date = TARGET_MONDAY + timedelta(days=8)  # a Tuesday, the week after
    date_widget.set_value(next_week_date).run()
    assert not at.exception, [e.message for e in at.exception]

    board_tab = _board_tab(at)
    infos = [i.value for i in board_tab.info]
    assert any(
        next_week_date.isoformat() in text and "next week's board" in text for text in infos
    ), infos
    # And the notice is one-shot -- it must not still be there after another run.
    at.run(timeout=30)
    board_tab = _board_tab(at)
    assert not board_tab.info


def test_a_life_skill_shows_on_the_board_with_a_move_control(monkeypatch, tmp_path):
    db_path = tmp_path / "week.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    db.seed_life_skills(student["id"])
    skill = db.list_life_skills(student["id"])[0]
    db.schedule_life_skill(skill["id"], TARGET_MONDAY.isoformat())
    db.close()

    _, board_tab = _open_board_tab(monkeypatch, db_path)
    labels = [e.label for e in board_tab.expander]
    assert any(skill["title"] in label for label in labels)
    backlog_key = f"move_board_ls_{skill['id']}_send_to_backlog"
    assert any(b.key == backlog_key for b in board_tab.button)
    captions = " ".join(c.value for c in board_tab.caption)
    assert 'Under the "Checklist" tab.' in captions


def test_a_backlogged_story_shows_in_its_epics_backlog_panel_section(monkeypatch, tmp_path):
    db_path = tmp_path / "week.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    db.seed_life_skills(student["id"])
    skill = db.list_life_skills(student["id"])[0]
    db.schedule_life_skill(skill["id"], TARGET_MONDAY.isoformat())
    db.set_life_skill_active(skill["id"], False)
    db.close()

    _, board_tab = _open_board_tab(monkeypatch, db_path)
    markdowns = " ".join(m.value for m in board_tab.markdown)
    assert "📋 Product Backlog" in markdowns
    life_skills_expanders = [
        e for e in board_tab.expander if e.label.startswith("🛠️ Life Skills")
    ]
    assert life_skills_expanders, "the Life Skills epic section must be offered"
    card_labels = [e.label for e in life_skills_expanders[0].expander]
    assert any(skill["title"] in label for label in card_labels)


def test_moving_a_life_skill_from_the_board_reschedules_it(monkeypatch, tmp_path):
    db_path = tmp_path / "week.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    db.seed_life_skills(student["id"])
    skill = db.list_life_skills(student["id"])[0]
    db.schedule_life_skill(skill["id"], TARGET_MONDAY.isoformat())
    db.close()

    _, board_tab = _open_board_tab(monkeypatch, db_path)
    send_key = f"move_board_ls_{skill['id']}_send_to_backlog"
    board_tab.button(key=send_key).click().run()

    db = Database(db_path)
    reloaded = next(s for s in db.list_life_skills(student["id"]) if s["id"] == skill["id"])
    db.close()
    assert reloaded["active"] == 0


def test_reactivating_a_lesson_from_the_board_does_not_clobber_its_picked_day(
    monkeypatch, tmp_path
):
    """The actual bug behind "i moved two math lessons from backlog to
    their own dates, 9/2 and 9/3, and they have disappeared": reactivating
    a backlogged lesson used to call reschedule_lesson(lid, date.today())
    -- clobbering whatever day a parent had already picked for it back to
    today. Exercised end to end here: pick a real day, send it back to
    the backlog, then take it back out via the "Take out of Backlog"
    button -- the day picked in step one must survive all of it.
    """
    db_path = tmp_path / "week.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="history", subject="history", topic="t",
        title="1776: The Year the Colonies Broke Up With a King",
        payload={"title": "1776: The Year the Colonies Broke Up With a King", "activities": []},
        metadata={
            "planned_for": TARGET_MONDAY.isoformat(),
            "week_start": TARGET_MONDAY.isoformat(),
            "held_back": True,
        },
    )
    db.close()

    picked_day = TARGET_MONDAY + timedelta(days=1)  # a Tuesday, same week

    at, board_tab = _open_board_tab(monkeypatch, db_path)
    date_key = f"move_board_lesson_{lesson_id}_date_{TARGET_MONDAY.isoformat()}"
    date_widget = [d for d in board_tab.date_input if d.key == date_key][0]
    date_widget.set_value(picked_day).run()
    assert not at.exception, [e.message for e in at.exception]

    # Send it back to the backlog, then take it out again with the
    # dedicated button -- the exact two-step sequence the old bidirectional
    # checkbox's un-check path used to get wrong.
    board_tab = _board_tab(at)
    board_tab.button(key=f"move_board_lesson_{lesson_id}_send_to_backlog").click().run()
    assert not at.exception, [e.message for e in at.exception]

    board_tab = _board_tab(at)
    board_tab.button(key=f"move_board_lesson_{lesson_id}_take_out_of_backlog").click().run()
    assert not at.exception, [e.message for e in at.exception]

    db = Database(db_path)
    reloaded = db.get_lesson(lesson_id)
    db.close()
    assert reloaded["metadata"]["planned_for"] == picked_day.isoformat()
    assert "held_back" not in reloaded["metadata"]


def test_next_week_button_jumps_the_board_to_next_weeks_monday(monkeypatch, tmp_path):
    """The actual point of the button: right after a Friday planning
    session generates next week's lessons, this is the one click that
    shows them on the board, ready to move around -- not hand-picking
    next week's date via the date_input every time."""
    db_path = tmp_path / "week.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    # Relative to *real* today, not TARGET_MONDAY -- the button itself
    # computes weekly.default_plan_target() off the real current date.
    next_monday = weekly.default_plan_target()
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="math", subject="math", topic="t",
        title="Next Week's Lesson",
        payload={"title": "Next Week's Lesson", "activities": []},
        metadata={"planned_for": next_monday.isoformat(), "week_start": next_monday.isoformat()},
    )
    db.close()

    at, board_tab = _open_board_tab(monkeypatch, db_path)
    # _open_board_tab already parks the picker on TARGET_MONDAY -- confirm
    # next week's lesson isn't visible yet before the jump.
    assert not any("Next Week's Lesson" in e.label for e in board_tab.expander)

    next_week_button = [b for b in board_tab.button if b.label == "Next week"][0]
    next_week_button.click().run()

    board_tab = _board_tab(at)
    assert any("Next Week's Lesson" in e.label for e in board_tab.expander)
    date_widget = [d for d in board_tab.date_input if d.key == "board_week_picker"][0]
    assert weekly.week_start(date_widget.value) == weekly.default_plan_target()
    assert lesson_id  # sanity: the lesson really was created


def test_this_week_button_returns_from_next_week(monkeypatch, tmp_path):
    db_path = tmp_path / "week.db"
    db = Database(db_path)
    db.ensure_default_student()
    db.close()

    at, board_tab = _open_board_tab(monkeypatch, db_path)
    next_week_button = [b for b in board_tab.button if b.label == "Next week"][0]
    next_week_button.click().run()

    board_tab = _board_tab(at)
    this_week_button = [b for b in board_tab.button if b.label == "This week"][0]
    this_week_button.click().run()

    board_tab = _board_tab(at)
    date_widget = [d for d in board_tab.date_input if d.key == "board_week_picker"][0]
    assert weekly.week_start(date_widget.value) == weekly.week_start(date.today())


# --- Product Backlog panel: every parked story, any week it came from ----------


def test_the_backlog_panel_includes_a_story_parked_from_a_totally_different_week(
    monkeypatch, tmp_path
):
    """The actual ask this panel exists to satisfy: 'backlog should include
    all stories I put into the backlog' -- not just ones parked from the
    week currently being viewed."""
    db_path = tmp_path / "week.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="history", subject="history", topic="t",
        title="Origins of the Cold War",
        payload={"title": "Origins of the Cold War", "activities": []},
        metadata={
            "planned_for": (TARGET_MONDAY - timedelta(days=90)).isoformat(),
            "week_start": (TARGET_MONDAY - timedelta(days=90)).isoformat(),
        },
    )
    db.send_to_backlog(lesson_id)
    db.close()

    _, board_tab = _open_board_tab(monkeypatch, db_path)
    history_expanders = [e for e in board_tab.expander if e.label.startswith("🏛️ History")]
    assert history_expanders, "a story parked months ago must still surface in its epic's panel section"
    card_labels = [e.label for e in history_expanders[0].expander]
    assert any("Origins of the Cold War" in label for label in card_labels)


def test_the_board_columns_are_monday_through_friday_only_no_sixth_backlog_column(
    monkeypatch, tmp_path
):
    """Backlog moved into its own panel -- the day side of the board no
    longer carries a sixth column for it."""
    db_path = tmp_path / "week.db"
    Database(db_path).close()

    _, board_tab = _open_board_tab(monkeypatch, db_path)
    # Day headers are now colored HTML pills (see _WEEKDAY_COLORS), not
    # plain "**Mon**"-style markdown -- check for the day abbreviation
    # inside whichever markdown block renders it instead.
    day_markdowns = " ".join(m.value for m in board_tab.markdown)
    for day in ("Mon", "Tue", "Wed", "Thu", "Fri"):
        assert f">{day}</span>" in day_markdowns
    # The old day-column-style "**🗄️ Backlog**" header is gone -- it's now
    # the panel's own "📋 Product Backlog" heading instead.
    assert not any(m.value == "**🗄️ Backlog**" for m in board_tab.markdown)
    assert any(m.value == "**📋 Product Backlog**" for m in board_tab.markdown)
