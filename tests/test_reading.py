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
from compass.reading import daily_reading_target
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


def test_home_reading_tile_has_no_goal_without_a_rate(monkeypatch, tmp_path):
    """Rate 0 keeps the old behaviour -- just the book and a progress bar, no
    target and no report controls."""
    db_path, _, _ = _seeded(tmp_path, current_page=150, pages_per_day=0)
    at = _open_home(monkeypatch, db_path)
    text = " ".join(m.value for m in at.markdown)
    assert "read up to page" not in text
    assert "Reading — Holes" in text


def test_home_reading_tile_greens_once_the_goal_is_reached(monkeypatch, tmp_path):
    db_path, student_id, book_id = _seeded(tmp_path, current_page=150, pages_per_day=25)
    database = Database(db_path)
    database.log_reading(student_id, book_id, 175, date.today().isoformat())  # hit the goal
    database.close()

    at = _open_home(monkeypatch, db_path)
    text = " ".join(m.value for m in at.markdown)
    assert "Reading — done for today ✅" in text


def test_home_reading_report_button_logs_and_advances(monkeypatch, tmp_path):
    db_path, student_id, book_id = _seeded(tmp_path, current_page=150, pages_per_day=25)
    at = _open_home(monkeypatch, db_path)
    [b for b in at.button if "I read up to page 175" in (b.label or "")][0].click().run()
    assert not at.exception, [e.message for e in at.exception]

    database = Database(db_path)
    book = next(b for b in database.list_books(student_id) if b["id"] == book_id)
    database.close()
    assert book["current_page"] == 175


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
