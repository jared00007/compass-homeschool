"""Washington's Declaration of Intent (RCW 28A.200.010) -- a once-a-year filing
deadline, tracked separately from the hours/subjects compliance report.

The one behavior worth pinning carefully: an unfiled deadline that has passed
must NOT quietly roll forward to next year's date the way the school-year-start
countdown does. That would turn a missed filing into a calm year-long countdown
instead of a warning -- the exact silent-downgrade failure mode this project
has consistently refused to ship elsewhere (credits, video, quiz).
"""

from __future__ import annotations

from datetime import date

import pytest

from compass import config
from compass.compliance.declaration import status
from compass.school_calendar import date_in_year, days_until, next_annual_date
from compass.storage.db import Database


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    yield database
    database.close()


@pytest.fixture()
def student(db):
    return db.ensure_default_student()


# --- compass/school_calendar.py ------------------------------------------------


def test_date_in_year_builds_the_expected_date():
    assert date_in_year("09-15", 2026) == date(2026, 9, 15)


def test_date_in_year_falls_back_on_garbage_rather_than_raising():
    assert date_in_year("not-a-date", 2026) == date(2026, 9, 1)
    assert date_in_year("", 2026) == date(2026, 9, 1)


def test_date_in_year_falls_back_on_feb_29_in_a_non_leap_year():
    assert date_in_year("02-29", 2026) == date(2026, 9, 1)


def test_next_annual_date_stays_this_year_if_not_passed_yet():
    on = date(2026, 8, 1)
    assert next_annual_date("09-01", on) == date(2026, 9, 1)


def test_next_annual_date_rolls_forward_once_passed():
    on = date(2026, 9, 15)
    assert next_annual_date("09-01", on) == date(2027, 9, 1)


def test_next_annual_date_treats_today_as_not_yet_passed():
    on = date(2026, 9, 1)
    assert next_annual_date("09-01", on) == date(2026, 9, 1)


def test_days_until():
    assert days_until(date(2026, 9, 15), on=date(2026, 9, 1)) == 14
    assert days_until(date(2026, 9, 1), on=date(2026, 9, 15)) == -14


# --- compass/compliance/declaration.py -----------------------------------------


def test_before_the_deadline_shows_a_forward_countdown(db, student):
    db.set_setting("declaration_due", "09-15")
    ds = status(db, student["id"], on=date(2026, 9, 1))
    assert ds.due_on == date(2026, 9, 15)
    assert ds.days_remaining == 14
    assert not ds.filed
    assert not ds.overdue


def test_an_unfiled_deadline_that_has_passed_stays_overdue_not_rolled_forward(db, student):
    """The core guard this module exists for."""
    db.set_setting("declaration_due", "09-15")
    ds = status(db, student["id"], on=date(2026, 10, 1))
    assert ds.due_on == date(2026, 9, 15), "must not silently become next year's date"
    assert ds.overdue
    assert ds.days_remaining < 0
    assert not ds.filed


def test_filing_this_years_deadline_reports_filed(db, student):
    db.set_setting("declaration_due", "09-15")
    db.mark_declaration_filed(student["id"], date(2026, 9, 15).isoformat(), filed_on="2026-09-10")
    ds = status(db, student["id"], on=date(2026, 9, 20))
    assert ds.filed
    assert ds.filed_on == "2026-09-10"
    assert not ds.overdue


def test_a_filed_deadline_that_has_passed_advances_to_next_years(db, student):
    """Once handled, the status moves on -- it doesn't keep reporting a stale
    win for the rest of the year."""
    db.set_setting("declaration_due", "09-15")
    db.mark_declaration_filed(student["id"], date(2026, 9, 15).isoformat())
    ds = status(db, student["id"], on=date(2027, 1, 1))
    assert ds.due_on == date(2027, 9, 15)
    assert not ds.filed
    assert not ds.overdue


def test_the_family_supplied_url_passes_through(db, student):
    db.set_setting("declaration_url", "https://example-district.k12.wa.us/homeschool")
    ds = status(db, student["id"])
    assert ds.url == "https://example-district.k12.wa.us/homeschool"


def test_default_url_is_the_familys_own_district_not_an_invented_one(db, student):
    """Filled in from this family's own district packet (see
    config.DEFAULT_SETTINGS), not guessed for an unknown district -- Compass
    still has no business inventing one for a family it doesn't know."""
    ds = status(db, student["id"])
    assert ds.url == config.DEFAULT_SETTINGS["declaration_url"]


def test_clearing_the_url_is_respected_not_silently_reset(db, student):
    db.set_setting("declaration_url", "")
    ds = status(db, student["id"])
    assert ds.url == ""


def test_a_malformed_due_date_setting_degrades_to_september_1st(db, student):
    db.set_setting("declaration_due", "garbage")
    ds = status(db, student["id"], on=date(2026, 1, 1))
    assert ds.due_on == date(2026, 9, 1)


# --- compass/storage/db.py ------------------------------------------------------


def test_declaration_status_is_none_before_any_filing(db, student):
    assert db.declaration_status(student["id"], "2026-09-15") is None


def test_mark_declaration_filed_defaults_filed_on_to_today(db, student):
    db.mark_declaration_filed(student["id"], "2026-09-15")
    row = db.declaration_status(student["id"], "2026-09-15")
    assert row["filed_on"] == date.today().isoformat()


def test_marking_filed_twice_updates_rather_than_duplicating(db, student):
    db.mark_declaration_filed(student["id"], "2026-09-15", filed_on="2026-09-01")
    db.mark_declaration_filed(student["id"], "2026-09-15", filed_on="2026-09-10")
    row = db.declaration_status(student["id"], "2026-09-15")
    assert row["filed_on"] == "2026-09-10"


def test_clear_declaration_filed_undoes_a_mistaken_click(db, student):
    db.mark_declaration_filed(student["id"], "2026-09-15")
    db.clear_declaration_filed(student["id"], "2026-09-15")
    row = db.declaration_status(student["id"], "2026-09-15")
    assert row["filed_on"] is None


def test_different_school_years_are_tracked_independently(db, student):
    db.mark_declaration_filed(student["id"], "2025-09-15")
    assert db.declaration_status(student["id"], "2026-09-15") is None
    assert db.declaration_status(student["id"], "2025-09-15")["filed_on"] is not None
