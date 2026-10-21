"""The self-running Spelling track: settings, the word pool + Leitner spacing,
the grade, pool top-up (model call mocked), and the daily/quiz completion."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from compass import config, spelling
from compass.storage.db import Database

REPO_ROOT = Path(__file__).resolve().parent.parent
HOME_PATH = str(REPO_ROOT / "Home.py")


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "spelling.db")
    yield database
    database.close()


@pytest.fixture()
def student(db):
    return db.ensure_default_student()


# --- settings -------------------------------------------------------------------


def test_settings_default_off_with_sensible_values(db):
    cfg = spelling.settings(db)
    assert cfg["enabled"] is False
    assert cfg["daily_count"] == config.SPELLING_DAILY_WORDS
    assert cfg["quiz_count"] == config.SPELLING_QUIZ_WORDS
    assert cfg["quiz_day"] == config.SPELLING_QUIZ_WEEKDAY


def test_settings_round_trip(db):
    spelling.save_settings(db, enabled=True, daily_count=4, quiz_count=15, quiz_day=2)
    cfg = spelling.settings(db)
    assert cfg == {"enabled": True, "daily_count": 4, "quiz_count": 15, "quiz_day": 2, "level": ""}


def test_effective_level_uses_grade_then_override(db, student):
    assert "grade" in spelling.effective_level(db, student).lower()
    spelling.save_settings(db, level="4th grade")
    assert spelling.effective_level(db, student) == "4th grade"


def test_is_quiz_day_matches_the_setting(db):
    spelling.save_settings(db, quiz_day=0)  # Monday
    assert spelling.is_quiz_day(db, date(2026, 10, 19))      # a Monday
    assert not spelling.is_quiz_day(db, date(2026, 10, 20))  # a Tuesday


# --- the word pool + Leitner spacing --------------------------------------------


def test_new_words_are_due_today_and_pool_counts(db, student):
    sid = student["id"]
    db.add_spelling_word(sid, "separate", "Keep them ____.", "on")
    db.add_spelling_word(sid, "rhythm", "A steady ____.", "on")
    db.add_spelling_word(sid, "Separate")  # duplicate (case) -> ignored
    counts = db.spelling_pool_counts(sid)
    assert counts == {"total": 2, "active": 2, "due": 2}
    assert [w["word"] for w in db.spelling_due(sid, 5)] == ["separate", "rhythm"]


def test_a_right_answer_climbs_and_a_miss_drops_to_box_one(db, student):
    sid = student["id"]
    wid = db.add_spelling_word(sid, "necessary", "It is ____.", "on")
    db.record_spelling_attempt(wid, True)
    assert db.list_spelling_words(sid)[0]["box"] == 2
    # A later miss sends it back to box 1 so it returns soon.
    db.record_spelling_attempt(wid, False)
    row = db.list_spelling_words(sid)[0]
    assert row["box"] == 1 and row["times_missed"] == 1


def test_mastered_word_retires_out_of_rotation(db, student):
    sid = student["id"]
    wid = db.add_spelling_word(sid, "island", "An ____ in the sea.", "easier")
    for _ in range(5):  # climb to box 5 and retire
        db.record_spelling_attempt(wid, True)
    assert db.spelling_pool_counts(sid)["active"] == 0
    assert db.list_spelling_words(sid, include_retired=False) == []
    assert db.list_spelling_words(sid, include_retired=True)[0]["retired"] == 1


def test_quiz_pool_is_weighted_to_the_shaky_words(db, student):
    sid = student["id"]
    strong = db.add_spelling_word(sid, "cat", "A ____.", "easier")
    weak = db.add_spelling_word(sid, "conscience", "A clear ____.", "stretch")
    db.record_spelling_attempt(strong, True)   # strong climbs to box 2
    db.record_spelling_attempt(weak, False)    # weak stays at box 1, missed once
    # Lowest box first -> the weak word leads the quiz.
    assert db.spelling_quiz_pool(sid, 10)[0]["word"] == "conscience"


# --- the grade ------------------------------------------------------------------


def test_grade_summary_averages_quiz_scores(db, student):
    sid = student["id"]
    assert spelling.grade_summary(db, sid) is None  # none yet
    db.record_spelling_quiz(sid, 9, 10)   # 90
    db.record_spelling_quiz(sid, 8, 10)   # 80
    summary = spelling.grade_summary(db, sid)
    assert summary["average"] == 85 and summary["letter"] == "B"
    assert summary["quizzes"] == 2
    assert (summary["last_correct"], summary["last_total"]) == (8, 10)


# --- pool top-up (the one model call, mocked) -----------------------------------


_FAKE_WORDS = {"words": [
    {"word": "observation", "clue": "She wrote her ____.", "tier": "on"},
    {"word": "island", "clue": "An ____ in the sea.", "tier": "easier"},
    {"word": "bad word two", "clue": "x", "tier": "on"},  # multi-word -> dropped
    {"word": "conscience", "clue": "A clear ____.", "tier": "stretch"},
]}


def test_ensure_pool_generates_words_when_low(db, student):
    spelling.save_settings(db, enabled=True)
    with patch("compass.agents.llm.generate_lesson", return_value=_FAKE_WORDS), \
         patch("compass.agents.api_available", return_value=(True, "")):
        added = spelling.ensure_pool(db, student, minimum=3)
    words = {w["word"] for w in db.list_spelling_words(student["id"])}
    assert {"observation", "island", "conscience"} <= words
    assert "bad word two" not in words  # multi-word filtered out
    assert added >= 3


def test_ensure_pool_is_a_noop_when_disabled_or_no_api(db, student):
    # Disabled: never calls the model.
    with patch("compass.agents.api_available", return_value=(True, "")) as api:
        assert spelling.ensure_pool(db, student) == 0
        api.assert_not_called()
    # Enabled but no API key: no words, no crash.
    spelling.save_settings(db, enabled=True)
    with patch("compass.agents.api_available", return_value=(False, "no key")):
        assert spelling.ensure_pool(db, student) == 0
    assert db.spelling_pool_counts(student["id"])["active"] == 0


def test_ensure_pool_does_nothing_when_already_full(db, student):
    spelling.save_settings(db, enabled=True)
    for i in range(20):
        db.add_spelling_word(student["id"], f"word{i}", "A ____.", "on")
    with patch("compass.agents.llm.generate_lesson") as gen, \
         patch("compass.agents.api_available", return_value=(True, "")):
        assert spelling.ensure_pool(db, student) == 0
        gen.assert_not_called()


# --- completing the daily card and the weekly quiz ------------------------------


def test_complete_daily_records_and_logs_hours_once(db, student):
    sid = student["id"]
    a = db.add_spelling_word(sid, "separate", "Keep them ____.", "on")
    b = db.add_spelling_word(sid, "rhythm", "A steady ____.", "on")
    spelling.complete_daily(db, student, [(a, True), (b, False)])
    assert spelling.daily_done_today(db) is True
    acts = [x for x in db.list_activities(sid) if x["source"] == "spelling"]
    assert len(acts) == 1 and acts[0]["primary_subject"] == "spelling"
    # Doing another word later the same day doesn't double-log the hours.
    c = db.add_spelling_word(sid, "island", "An ____.", "easier")
    spelling.complete_daily(db, student, [(c, True)])
    assert len([x for x in db.list_activities(sid) if x["source"] == "spelling"]) == 1


def test_complete_quiz_records_score_logs_hours_and_sets_grade(db, student):
    sid = student["id"]
    a = db.add_spelling_word(sid, "necessary", "It is ____.", "on")
    b = db.add_spelling_word(sid, "conscience", "A clear ____.", "stretch")
    outcome = spelling.complete_quiz(db, student, [(a, True), (b, True)])
    assert outcome == {"correct": 2, "total": 2}
    assert db.spelling_quiz_taken_on(sid, date.today().isoformat())
    assert [x for x in db.list_activities(sid) if x["source"] == "spelling"]
    assert spelling.grade_summary(db, sid)["letter"] == "A+"


# --- the page -------------------------------------------------------------------


MISSION_CONTROL_PATH = str(REPO_ROOT / "pages" / "14_Mission_Control.py")


def test_setup_confirms_where_his_words_are_after_turning_it_on(monkeypatch, tmp_path):
    db_path = tmp_path / "setup.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    spelling.save_settings(db, enabled=True, quiz_day=0)  # Monday quiz
    db.add_spelling_word(student["id"], "separate", "Keep them ____.", "on")
    db.close()

    st.cache_resource.clear()
    monkeypatch.setattr(config, "DEFAULT_DB_PATH", db_path)
    # No API key in tests, so ensure_pool no-ops; the one seeded word is enough
    # for the "it's on his Home" confirmation to show.
    at = AppTest.from_file(HOME_PATH)
    at.session_state["parent_unlocked"] = True
    at.run(timeout=30)
    at.switch_page(MISSION_CONTROL_PATH)
    at.session_state["mc_view"] = "setup"
    at.run(timeout=30)
    assert not at.exception, [e.message for e in at.exception]
    text = " ".join([m.value for m in at.markdown] + [s.value for s in at.success]
                    + [c.value for c in at.caption])
    assert "on his Home" in text


def test_the_daily_card_shows_on_his_home_when_enabled(monkeypatch, tmp_path):
    from compass import auth

    db_path = tmp_path / "home.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    auth.set_pin(db, "1234")  # a PIN set -> the student view is the default (not parent)
    spelling.save_settings(db, enabled=True, quiz_day=0)  # Monday, so a weekday today is "daily"
    db.add_spelling_word(student["id"], "separate", "Keep the two piles ____.", "on")
    db.add_spelling_word(student["id"], "rhythm", "A steady ____ on the drum.", "on")
    db.close()

    st.cache_resource.clear()
    monkeypatch.setattr(config, "DEFAULT_DB_PATH", db_path)
    # Force a non-quiz day so the daily card (not the quiz) renders, and skip the
    # brand-new-DB first-day celebration that otherwise st.stop()s the page.
    with patch("compass.spelling.is_quiz_day", return_value=False), \
         patch("compass.ui.render_first_day_celebration", return_value=False):
        at = AppTest.from_file(HOME_PATH)
        at.run(timeout=30)
        assert not at.exception, [e.message for e in at.exception]
        markdowns = " ".join(m.value for m in at.markdown)
        assert "Daily spelling" in markdowns
        # The type-the-word inputs are present (one per due word).
        keys = [t.key for t in at.text_input]
        assert any((k or "").startswith("spd_in_") for k in keys)
