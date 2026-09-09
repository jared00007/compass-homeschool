"""The daily reading assignment: a parent sets a pages-per-day goal on a book,
and his Home reading tile turns that into a "read up to page N today" target he
can report against and green-check, the current page moving as he does.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from compass import auth, config
from compass.reading import (
    daily_reading_target,
    parse_reading_days,
    reading_active_on,
    serialize_reading_days,
)
from compass.storage.db import Database

REPO_ROOT = Path(__file__).resolve().parent.parent
HOME_PATH = str(REPO_ROOT / "Home.py")
MISSION_CONTROL_PATH = str(REPO_ROOT / "pages" / "14_Mission_Control.py")


# --- the pure target maths --------------------------------------------------------


def test_target_is_start_page_plus_rate():
    assert daily_reading_target(288, 150, 25) == 175


def test_target_is_capped_at_the_books_length():
    assert daily_reading_target(288, 280, 25) == 288


def test_no_target_without_a_rate_or_a_known_length():
    assert daily_reading_target(288, 150, 0) is None
    assert daily_reading_target(None, 150, 25) is None
    assert daily_reading_target(288, 150, None) is None


# --- which weekdays reading is assigned -------------------------------------------


def test_empty_reading_days_means_every_day():
    assert parse_reading_days("") is None
    assert reading_active_on("", 2) is True  # Wednesday
    assert reading_active_on(None, 6) is True  # Sunday


def test_specific_reading_days_gate_by_weekday():
    mon_wed_fri = "0,2,4"
    assert reading_active_on(mon_wed_fri, 0) is True   # Mon
    assert reading_active_on(mon_wed_fri, 2) is True   # Wed
    assert reading_active_on(mon_wed_fri, 1) is False  # Tue is off
    assert reading_active_on(mon_wed_fri, 3) is False  # Thu is off


def test_serialize_collapses_the_full_week_to_empty():
    assert serialize_reading_days(set(range(7))) == ""  # every day -> the simple default
    assert serialize_reading_days({0, 2, 4}) == "0,2,4"
    assert serialize_reading_days(None) == ""


# --- the reading log --------------------------------------------------------------


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "reading.db")
    yield database
    database.close()


@pytest.fixture()
def student(db):
    return db.ensure_default_student()


def _book(db, student_id, **plan):
    book_id = db.add_book(student_id, "Holes", total_pages=288)
    if plan:
        db.update_book(book_id, **plan)
    return book_id


def test_logging_reading_freezes_the_day_start_and_moves_the_current_page(db, student):
    book_id = _book(db, student["id"], current_page=150, pages_per_day=25)
    today = date.today().isoformat()

    db.log_reading(student["id"], book_id, 165, today)  # read partway to the goal
    row = db.reading_log_on(student["id"], book_id, today)
    assert row["start_page"] == 150  # anchored to where the day began
    assert row["end_page"] == 165
    book = next(b for b in db.list_books(student["id"]) if b["id"] == book_id)
    assert book["current_page"] == 165

    # A second save the same day keeps the start frozen -- the goal doesn't
    # walk forward as he reports more.
    db.log_reading(student["id"], book_id, 175, today)
    row = db.reading_log_on(student["id"], book_id, today)
    assert row["start_page"] == 150
    assert row["end_page"] == 175


def test_no_reading_log_row_until_he_reports(db, student):
    book_id = _book(db, student["id"], current_page=150, pages_per_day=25)
    assert db.reading_log_on(student["id"], book_id, date.today().isoformat()) is None


def test_reading_credits_reading_hours_once_per_day(db, student):
    """His daily reading counts toward the hour floor -- a block of Reading time
    the first time he logs pages that day, and only once no matter how many
    times he updates the page."""
    book_id = _book(db, student["id"], current_page=150, pages_per_day=25)
    today = date.today().isoformat()

    db.log_reading(student["id"], book_id, 165, today)
    acts = [a for a in db.list_activities(student["id"]) if a["credits"].get("reading")]
    assert len(acts) == 1
    assert acts[0]["credits"]["reading"] == config.READING_DEFAULT_MINUTES
    assert acts[0]["source"] == "reading"
    assert acts[0]["occurred_on"] == today

    db.log_reading(student["id"], book_id, 175, today)  # same day, updated page
    acts = [a for a in db.list_activities(student["id"]) if a["credits"].get("reading")]
    assert len(acts) == 1  # not double-credited


def test_reading_credits_a_fresh_block_each_day(db, student):
    from datetime import timedelta

    book_id = _book(db, student["id"], current_page=150, pages_per_day=25)
    day1 = date.today().isoformat()
    day2 = (date.today() - timedelta(days=1)).isoformat()
    db.log_reading(student["id"], book_id, 165, day1)
    db.log_reading(student["id"], book_id, 180, day2)
    acts = [a for a in db.list_activities(student["id"]) if a["credits"].get("reading")]
    assert len(acts) == 2  # one block per day he read


# --- the Home tile ----------------------------------------------------------------


def _open_home(monkeypatch, db_path):
    st.cache_resource.clear()
    monkeypatch.setattr(config, "DEFAULT_DB_PATH", db_path)
    at = AppTest.from_file(HOME_PATH)
    at.run(timeout=30)
    assert not at.exception, [e.message for e in at.exception]
    return at


def _seeded(tmp_path, **plan):
    db_path = tmp_path / "home.db"
    database = Database(db_path)
    s = database.ensure_default_student()
    auth.set_pin(database, "1234")
    book_id = database.add_book(s["id"], "Holes", total_pages=288)
    database.update_book(book_id, **plan)
    database.close()
    return db_path, s["id"], book_id


def test_home_reading_tile_shows_todays_page_goal(monkeypatch, tmp_path):
    db_path, _, _ = _seeded(tmp_path, current_page=150, pages_per_day=25)
    at = _open_home(monkeypatch, db_path)
    text = " ".join(m.value for m in at.markdown)
    assert "read up to page 175 today" in text


def test_home_reading_tile_is_gone_when_not_on_the_board(monkeypatch, tmp_path):
    """Rate 0 = the daily-reading card is off the board, so nothing about
    reading shows on his Due-today list at all."""
    db_path, _, _ = _seeded(tmp_path, current_page=150, pages_per_day=0)
    at = _open_home(monkeypatch, db_path)
    text = " ".join(m.value for m in at.markdown)
    assert "read up to page" not in text
    assert "Reading —" not in text


def test_home_reading_tile_greens_once_the_goal_is_reached(monkeypatch, tmp_path):
    db_path, student_id, book_id = _seeded(tmp_path, current_page=150, pages_per_day=25)
    database = Database(db_path)
    database.log_reading(student_id, book_id, 175, date.today().isoformat())  # hit the goal
    database.close()

    at = _open_home(monkeypatch, db_path)
    text = " ".join(m.value for m in at.markdown)
    assert "Reading — done for today ✅" in text


def test_home_reading_done_button_advances_to_the_goal(monkeypatch, tmp_path):
    db_path, student_id, book_id = _seeded(tmp_path, current_page=150, pages_per_day=25)
    at = _open_home(monkeypatch, db_path)
    [b for b in at.button if (b.label or "") == "✅ Done"][0].click().run()
    assert not at.exception, [e.message for e in at.exception]

    database = Database(db_path)
    book = next(b for b in database.list_books(student_id) if b["id"] == book_id)
    database.close()
    assert book["current_page"] == 175  # tapping Done logs reaching today's goal


def test_home_reading_partial_save_advances_to_the_reported_page(monkeypatch, tmp_path):
    """The "didn't finish" path: he logs the page he stopped on, and the book
    advances there (tomorrow's goal continues from it)."""
    db_path, student_id, book_id = _seeded(tmp_path, current_page=150, pages_per_day=25)
    at = _open_home(monkeypatch, db_path)
    at.number_input(key="reading_report_page").set_value(162).run()
    [b for b in at.button if (b.key or "") == "reading_save_page"][0].click().run()
    assert not at.exception, [e.message for e in at.exception]

    database = Database(db_path)
    book = next(b for b in database.list_books(student_id) if b["id"] == book_id)
    database.close()
    assert book["current_page"] == 162


def _open_mc_board(monkeypatch, db_path):
    st.cache_resource.clear()
    monkeypatch.setattr(config, "DEFAULT_DB_PATH", db_path)
    at = AppTest.from_file(HOME_PATH)
    at.session_state["parent_unlocked"] = True
    at.run(timeout=30)
    at.switch_page(MISSION_CONTROL_PATH)
    at.run(timeout=30)
    [b for b in at.button if (b.key or "") == "mc_viewbtn_board"][0].click().run()
    assert not at.exception, [e.message for e in at.exception]
    return at


def test_reading_board_card_shows_and_remove_takes_it_off(monkeypatch, tmp_path):
    db_path, student_id, book_id = _seeded(tmp_path, current_page=150, pages_per_day=20)
    at = _open_mc_board(monkeypatch, db_path)
    assert any("Daily reading · every day" in m.value for m in at.markdown)
    # The page count is an editable input, prefilled with the current rate.
    assert at.number_input(key=f"reading_board_rate_{book_id}").value == 20

    [b for b in at.button if (b.key or "") == "reading_board_remove"][0].click().run()
    assert not at.exception, [e.message for e in at.exception]
    database = Database(db_path)
    book = next(b for b in database.list_books(student_id) if b["id"] == book_id)
    database.close()
    assert book["pages_per_day"] == 0  # off the board


def test_reading_board_card_rate_is_editable_inline(monkeypatch, tmp_path):
    """The page count can be changed right on the card, any time."""
    db_path, student_id, book_id = _seeded(tmp_path, current_page=150, pages_per_day=20)
    at = _open_mc_board(monkeypatch, db_path)
    at.number_input(key=f"reading_board_rate_{book_id}").set_value(30).run()
    assert not at.exception, [e.message for e in at.exception]

    database = Database(db_path)
    book = next(b for b in database.list_books(student_id) if b["id"] == book_id)
    database.close()
    assert book["pages_per_day"] == 30


def test_reading_board_card_add_turns_it_on(monkeypatch, tmp_path):
    db_path, student_id, book_id = _seeded(tmp_path, current_page=150, pages_per_day=0)
    at = _open_mc_board(monkeypatch, db_path)
    # Off the board: the add control is shown (defaulting to 20/day).
    [b for b in at.button if (b.key or "") == "reading_board_add"][0].click().run()
    assert not at.exception, [e.message for e in at.exception]
    database = Database(db_path)
    book = next(b for b in database.list_books(student_id) if b["id"] == book_id)
    database.close()
    assert book["pages_per_day"] == 20


def test_reading_board_card_weekday_toggle_saves(monkeypatch, tmp_path):
    db_path, student_id, book_id = _seeded(tmp_path, current_page=150, pages_per_day=20)
    at = _open_mc_board(monkeypatch, db_path)
    # Starts every day (all ticked); untick Tuesday (weekday index 1).
    at.checkbox(key=f"reading_day_{book_id}_1").set_value(False).run()
    assert not at.exception, [e.message for e in at.exception]

    database = Database(db_path)
    book = next(b for b in database.list_books(student_id) if b["id"] == book_id)
    database.close()
    active = parse_reading_days(book["reading_days"])
    assert active is not None
    assert 1 not in active and 0 in active and 2 in active  # only Tuesday dropped


def test_home_reading_tile_hidden_on_an_off_day(monkeypatch, tmp_path):
    """With today turned off in the weekday pattern, no reading tile shows on
    his Due-today list."""
    today_wd = date.today().weekday()
    days = ",".join(str(d) for d in range(7) if d != today_wd)  # every day but today
    db_path, _, book_id = _seeded(tmp_path, current_page=150, pages_per_day=20)
    database = Database(db_path)
    database.update_book(book_id, reading_days=days)
    database.close()

    at = _open_home(monkeypatch, db_path)
    text = " ".join(m.value for m in at.markdown)
    assert "read up to page" not in text
    assert "Reading —" not in text


def test_home_reading_tile_shows_on_an_on_day(monkeypatch, tmp_path):
    today_wd = date.today().weekday()
    db_path, _, book_id = _seeded(tmp_path, current_page=150, pages_per_day=20)
    database = Database(db_path)
    database.update_book(book_id, reading_days=str(today_wd))  # only today
    database.close()

    at = _open_home(monkeypatch, db_path)
    text = " ".join(m.value for m in at.markdown)
    assert "read up to page 170 today" in text


def test_student_board_shows_the_reading_card_read_only(monkeypatch, tmp_path):
    db_path, _, _ = _seeded(tmp_path, current_page=150, pages_per_day=20)
    at = _open_home(monkeypatch, db_path)
    [b for b in at.button if "Board" in (b.label or "")][0].click().run()
    assert not at.exception, [e.message for e in at.exception]
    assert any("Read 20 pages · every day" in m.value for m in at.markdown)
    # No parent controls on his side.
    assert not any((b.key or "") == "reading_board_remove" for b in at.button)


def test_pages_per_day_is_settable_from_the_plan_panel(monkeypatch, tmp_path):
    """The reading goal is set where a parent already sets the current page --
    Mission Control -> Plan a lesson -> English -- not only on the buried Books
    tab (reported: "i dont see reading plan anywhere")."""
    db_path, student_id, book_id = _seeded(tmp_path, current_page=150, pages_per_day=0)
    st.cache_resource.clear()
    monkeypatch.setattr(config, "DEFAULT_DB_PATH", db_path)
    at = AppTest.from_file(HOME_PATH)
    at.session_state["parent_unlocked"] = True
    at.run(timeout=30)
    at.switch_page(MISSION_CONTROL_PATH)
    at.run(timeout=30)
    [b for b in at.button if (b.key or "") == "mc_viewbtn_plan"][0].click().run()
    [b for b in at.button if (b.key or "") == "plan_subjectbtn_english"][0].click().run()

    rate = [n for n in at.number_input if "Pages per day" in (n.label or "")][0]
    rate.set_value(25).run()
    assert not at.exception, [e.message for e in at.exception]

    database = Database(db_path)
    book = next(b for b in database.list_books(student_id) if b["id"] == book_id)
    database.close()
    assert book["pages_per_day"] == 25
