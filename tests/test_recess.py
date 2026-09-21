"""Recess -- the quick, no-stakes break menu on Landon's Home."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from compass import auth, config, pacing, recess
from compass.storage.db import Database

REPO_ROOT = Path(__file__).resolve().parent.parent
HOME_PATH = str(REPO_ROOT / "Home.py")


def test_recess_is_deterministic_by_day_and_rotates():
    day = date(2026, 9, 21)
    # Same day -> same break, every time (holds all day).
    assert recess.recess_of_the_day(day) == recess.recess_of_the_day(day)
    # Consecutive days walk through the menu, so it changes day to day.
    seen = {recess.recess_of_the_day(day + timedelta(days=i)) for i in range(len(recess.RECESS_BREAKS))}
    assert len(seen) == len(recess.RECESS_BREAKS)  # a full rotation with no repeats


def test_every_break_is_well_formed():
    for emoji, kind, prompt in recess.RECESS_BREAKS:
        assert emoji and kind and prompt


def _open_home_student(monkeypatch, db_path):
    st.cache_resource.clear()
    monkeypatch.setattr(config, "DEFAULT_DB_PATH", db_path)
    at = AppTest.from_file(HOME_PATH)
    at.run(timeout=30)
    assert not at.exception, [e.message for e in at.exception]
    return at


def test_home_shows_a_recess_break(monkeypatch, tmp_path):
    db_path = tmp_path / "recess.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    auth.set_pin(db, "1234")
    db.set_setting("first_day_celebrated_start", db.school_year_bounds()[0])
    db.close()

    at = _open_home_student(monkeypatch, db_path)
    body = " ".join(m.value for m in at.markdown)
    assert "break" in body.lower()


def test_recess_reads_as_earned_once_the_day_is_full(monkeypatch, tmp_path):
    db_path = tmp_path / "recess.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    auth.set_pin(db, "1234")
    db.set_setting("first_day_celebrated_start", db.school_year_bounds()[0])
    pacing.set_day_target(db, 1, 0)  # one lesson = a full day
    lid = db.save_lesson(student["id"], "math", "math", "Slope", "Slope", {"quiz": []})
    db.mark_student_done(lid)
    db.close()

    at = _open_home_student(monkeypatch, db_path)
    body = " ".join(m.value for m in at.markdown)
    assert "earned it" in body.lower()
