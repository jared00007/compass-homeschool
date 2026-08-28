"""School-day streaks -- the one thing on his page that rewards showing up
rather than scoring well.

The weekend rule is the load-bearing part: counting Saturday and Sunday as
missed days would reset the streak every Monday morning, turning the one
encouraging mechanic into a weekly reminder that he failed.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from compass import auth, config
from compass.storage.db import Database
from compass.weekly import best_streak, current_streak

REPO_ROOT = Path(__file__).resolve().parent.parent
HOME_PATH = str(REPO_ROOT / "Home.py")

# Aug 2026: Thu 20, Fri 21, [Sat 22, Sun 23], Mon 24, Tue 25, Wed 26, Thu 27
WED = date(2026, 8, 26)


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    yield database
    database.close()


@pytest.fixture()
def student(db):
    return db.ensure_default_student()


# --- counting ------------------------------------------------------------------


def test_a_weekend_does_not_break_the_streak():
    days = {"2026-08-20", "2026-08-21", "2026-08-24", "2026-08-25"}
    assert current_streak(days, WED) == 4


def test_today_not_started_yet_does_not_break_the_streak():
    """The moment you most want it to say "you're on 4, keep going" is
    before he's done anything today."""
    days = {"2026-08-20", "2026-08-21", "2026-08-24", "2026-08-25"}
    assert current_streak(days, WED) == 4
    assert current_streak(days | {"2026-08-26"}, WED) == 5


def test_a_missed_school_day_breaks_it():
    days = {"2026-08-20", "2026-08-21", "2026-08-24", "2026-08-26"}  # skipped Tue 25
    assert current_streak(days, WED) == 1


def test_a_missed_yesterday_with_nothing_today_is_zero():
    assert current_streak({"2026-08-24"}, WED) == 0


def test_a_missed_friday_is_not_forgiven_just_because_today_is_the_weekend():
    """`today` being a non-school day is not the same thing as "today is
    still in progress" -- only an actual today gets that forgiveness. A
    Saturday `today` should read Friday the same way a Monday `today`
    would: as an already-elapsed school day, broken if it was missed."""
    saturday = date(2026, 8, 22)
    days = {"2026-08-20", "2026-08-21"}  # Thu, Fri both done
    assert current_streak(days, saturday) == 2

    missed_friday = {"2026-08-19", "2026-08-20"}  # Wed, Thu done, Fri skipped
    assert current_streak(missed_friday, saturday) == 0


def test_no_history_is_zero():
    assert current_streak(set(), WED) == 0
    assert best_streak(set(), WED) == 0


def test_best_streak_keeps_the_longest_run_not_the_current_one():
    # Thu/Fri/Mon is a 3-day run (the weekend is skipped, not counted),
    # then Tue is missed, then Wed starts a new run of 1.
    days = {"2026-08-20", "2026-08-21", "2026-08-24", "2026-08-26"}
    assert current_streak(days, WED) == 1
    assert best_streak(days, WED) == 3


def test_best_streak_survives_a_long_history_without_running_off_the_calendar():
    """Walking backwards from today to the start of history overflows
    `date` itself -- best_streak walks forward from his first recorded day
    instead."""
    assert best_streak({"1990-01-02"}, WED) == 1


# --- what counts as an active day ----------------------------------------------


def test_a_lesson_marked_done_counts(db, student):
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="math", subject="math", topic="t",
        title="t", payload={},
    )
    db.mark_student_done(lesson_id)
    assert db.active_days(student["id"]) == {date.today().isoformat()}


def test_a_life_skill_counts(db, student):
    skill_id = db.add_life_skill(student["id"], "Do laundry")
    db.set_life_skill_done(skill_id, True)
    assert db.active_days(student["id"]) == {date.today().isoformat()}


def test_a_vocab_review_alone_does_not_count(db, student):
    """One button press a day shouldn't be farmable into a streak."""
    db.mark_vocab_reviewed(student["id"], date.today().isoformat())
    assert db.active_days(student["id"]) == set()


def test_an_unfinished_lesson_does_not_count(db, student):
    db.save_lesson(
        student_id=student["id"], agent="math", subject="math", topic="t",
        title="t", payload={},
    )
    assert db.active_days(student["id"]) == set()


# --- on his page ----------------------------------------------------------------


def _open_home(monkeypatch, db_path):
    st.cache_resource.clear()
    monkeypatch.setattr(config, "DEFAULT_DB_PATH", db_path)
    at = AppTest.from_file(HOME_PATH)
    at.run(timeout=30)
    assert not at.exception, [e.message for e in at.exception]
    return at


def _seed_done_today(tmp_path):
    db_path = tmp_path / "streak.db"
    database = Database(db_path)
    s = database.ensure_default_student()
    auth.set_pin(database, "1234")
    lesson_id = database.save_lesson(
        student_id=s["id"], agent="math", subject="math", topic="t",
        title="Two-Step Equations", payload={"title": "t", "activities": []},
    )
    database.mark_student_done(lesson_id)
    database.close()
    return db_path


def test_his_home_page_shows_the_streak(monkeypatch, tmp_path):
    at = _open_home(monkeypatch, _seed_done_today(tmp_path))
    shown = " ".join(s.value for s in at.success)
    assert "day in a row" in shown or "days in a row" in shown


def test_a_student_with_no_history_is_not_shown_a_zero(monkeypatch, tmp_path):
    """A big "0 day streak" on day one is discouraging, not motivating."""
    db_path = tmp_path / "empty.db"
    database = Database(db_path)
    database.ensure_default_student()
    auth.set_pin(database, "1234")
    database.close()

    at = _open_home(monkeypatch, db_path)
    shown = " ".join(s.value for s in at.success)
    assert "in a row" not in shown
