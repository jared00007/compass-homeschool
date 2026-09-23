"""Daily pacing -- the "enough for today" signal.

A full day is a couple of core lessons plus one enrichment block; once he clears
it Home tells him the rest of the day is his. Counts are derived live from the
same 'done today' signals the rest of the app records.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from compass import auth, config, pacing
from compass.storage.db import Database

REPO_ROOT = Path(__file__).resolve().parent.parent
HOME_PATH = str(REPO_ROOT / "Home.py")


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "pacing.db")
    yield database
    database.close()


@pytest.fixture()
def student(db):
    return db.ensure_default_student()


def _core_done(db, student, title, agent="math"):
    lid = db.save_lesson(student["id"], agent, agent, title, title, {"quiz": []})
    db.mark_student_done(lid)
    return lid


def test_a_fresh_day_is_not_a_full_day(db, student):
    plan = pacing.day_plan(db, student["id"], date.today())
    assert (plan.core_done, plan.enrichment_done) == (0, 0)
    assert plan.core_target == config.DAY_TARGET_CORE
    assert plan.enrichment_target == config.DAY_TARGET_ENRICHMENT
    assert plan.is_full_day is False


def test_two_core_plus_one_enrichment_is_a_full_day(db, student):
    today = date.today().isoformat()
    _core_done(db, student, "Slope", "math")
    _core_done(db, student, "Cells", "science")
    assert pacing.day_plan(db, student["id"], today).is_full_day is False  # no enrichment yet

    db.log_free_reading(student["id"], "Dog Man", 30)  # one enrichment block
    plan = pacing.day_plan(db, student["id"], today)
    assert (plan.core_done, plan.enrichment_done) == (2, 1)
    assert plan.is_full_day is True


def test_enrichment_counts_life_skills_and_trips(db, student):
    today = date.today().isoformat()
    db.conn.execute(
        "INSERT INTO life_skills (student_id, category, title, credit_subject, status, completed_on) "
        "VALUES (?,?,?,?,?,?)",
        (student["id"], "health", "Cook eggs", "health", "assigned", today),
    )
    db.conn.commit()
    assert db.enrichment_done_on(student["id"], today) == 1


def _khan_done(db, student, title, subject="math"):
    lid = db.save_lesson(student["id"], "khan", subject, title, title, {"quiz": []})
    db.mark_student_done(lid)
    return lid


def test_khan_core_cards_count_toward_the_core_target(db, student):
    today = date.today().isoformat()
    _khan_done(db, student, "Exponents", "math")
    _khan_done(db, student, "Cells", "science")
    _khan_done(db, student, "Main idea", "reading")   # reading folds into English -> core
    assert db.core_lessons_done_on(student["id"], today) == 3


def test_khan_noncore_cards_count_as_enrichment_not_core(db, student):
    today = date.today().isoformat()
    _khan_done(db, student, "Nutrition basics", "health")   # not a core academic subject
    assert db.core_lessons_done_on(student["id"], today) == 0
    assert db.enrichment_done_on(student["id"], today) == 1


def test_a_khan_card_can_complete_a_full_day(db, student):
    today = date.today().isoformat()
    _core_done(db, student, "Slope", "math")
    _khan_done(db, student, "Exponents", "math")   # the second core lesson, via Khan
    db.log_free_reading(student["id"], "Dog Man", 30)
    plan = pacing.day_plan(db, student["id"], today)
    assert (plan.core_done, plan.enrichment_done) == (2, 1)
    assert plan.is_full_day is True


def test_only_todays_work_counts(db, student):
    _core_done(db, student, "Slope", "math")
    # Yesterday there's nothing; today has one core lesson.
    yesterday = (date.today().fromordinal(date.today().toordinal() - 1)).isoformat()
    assert db.core_lessons_done_on(student["id"], yesterday) == 0
    assert db.core_lessons_done_on(student["id"], date.today().isoformat()) == 1


def test_parent_can_change_what_a_full_day_is(db, student):
    pacing.set_day_target(db, 1, 0)
    _core_done(db, student, "Slope", "math")
    plan = pacing.day_plan(db, student["id"], date.today())
    assert (plan.core_target, plan.enrichment_target) == (1, 0)
    assert plan.is_full_day is True


def test_home_roster_lists_every_khan_card_assigned_to_today(monkeypatch, tmp_path):
    """The lessons roster must show ALL of today's board cards, not collapse the
    Khan ones into a single row. Reported: the count said 6 but the list showed
    one Khan row. Three Khan cards on today -> three roster rows."""
    from compass.agents import khan_card

    db_path = tmp_path / "roster.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    auth.set_pin(db, "1234")  # student view
    db.set_setting("first_day_celebrated_start", db.school_year_bounds()[0])
    today = date.today().isoformat()
    for name in ("Exponents", "Radicals", "Polynomials"):
        khan_card.create_khan_card(
            db, student, subject="math", unit=name, minutes=30, day_iso=today, quiz=[])
    db.close()

    st.cache_resource.clear()
    monkeypatch.setattr(config, "DEFAULT_DB_PATH", db_path)
    at = AppTest.from_file(HOME_PATH)
    at.run(timeout=30)
    assert not at.exception, [e.message for e in at.exception]
    body = " ".join(m.value for m in at.markdown)
    assert "Lessons (3)" in body                       # roster size, not "Lessons (1)"
    khan_links = [pl.label for pl in at.get("page_link") if "Khan" in (pl.label or "")]
    assert len(khan_links) == 3, khan_links             # each card its own linked row
    for name in ("Exponents", "Radicals", "Polynomials"):
        assert any(name in (label or "") for label in khan_links)


def test_home_shows_full_day_message_once_he_clears_the_target(monkeypatch, tmp_path):
    db_path = tmp_path / "pacing.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    auth.set_pin(db, "1234")  # a PIN makes is_parent() default False -> student view
    # Dismiss the once-a-year first-day celebration so the normal Today view (and
    # its pacing card) renders instead of the cover page st.stop()ing it.
    db.set_setting("first_day_celebrated_start", db.school_year_bounds()[0])
    pacing.set_day_target(db, 1, 0)  # one lesson = a full day, for a deterministic test
    lid = db.save_lesson(student["id"], "math", "math", "Slope", "Slope", {"quiz": []})
    db.mark_student_done(lid)
    db.close()

    st.cache_resource.clear()
    monkeypatch.setattr(config, "DEFAULT_DB_PATH", db_path)
    at = AppTest.from_file(HOME_PATH)
    at.run(timeout=30)
    assert not at.exception, [e.message for e in at.exception]
    body = " ".join(m.value for m in at.markdown)
    assert "Full day" in body
