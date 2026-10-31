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


def test_clear_spelling_grade_wipes_scores_but_keeps_progress(db, student):
    """Resetting the grade removes only the weekly-quiz score rows (what the letter
    is averaged from); the Leitner word progress stays. Reported: 'wipe landons
    grade for spelling but keep the hours ... he has an F'."""
    sid = student["id"]
    wid = db.add_spelling_word(sid, "rhythm", "keep the ____", "on")
    db.record_spelling_attempt(wid, correct=True, kind="daily")  # real word progress
    # Two low quiz scores (the "F").
    db.record_spelling_quiz(sid, 2, 10)   # 20%
    db.record_spelling_quiz(sid, 3, 10)   # 30% -> average 25 -> F
    assert spelling.grade_summary(db, sid)["letter"] == "F"
    progress_before = db.spelling_pool_counts(sid)

    removed = db.clear_spelling_grade(sid)
    assert removed == 2
    assert spelling.grade_summary(db, sid) is None          # grade is gone
    assert db.spelling_pool_counts(sid) == progress_before  # words untouched
    # the per-word Leitner progress (box climb from the right answer) survived too
    assert db.list_spelling_words(sid, include_retired=True)[0]["times_correct"] == 1


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
    spelling.complete_daily(db, student, [(a, True, "separate"), (b, False, "rhythem")], duration_seconds=95)
    assert spelling.daily_done_today(db) is True
    acts = [x for x in db.list_activities(sid) if x["source"] == "spelling"]
    assert len(acts) == 1 and acts[0]["primary_subject"] == "spelling"
    # Doing another word later the same day doesn't double-log the hours.
    c = db.add_spelling_word(sid, "island", "An ____.", "easier")
    spelling.complete_daily(db, student, [(c, True, "island")])
    assert len([x for x in db.list_activities(sid) if x["source"] == "spelling"]) == 1


def test_attempts_feed_the_parents_daily_flow(db, student):
    sid = student["id"]
    a = db.add_spelling_word(sid, "separate", "Keep them ____.", "on")
    b = db.add_spelling_word(sid, "rhythm", "A steady ____.", "on")
    spelling.complete_daily(db, student, [(a, True, "separate"), (b, False, "rhythem")], duration_seconds=95)
    flow = db.spelling_daily_flow(sid)
    assert len(flow) == 1
    assert flow[0]["answered"] == 2 and flow[0]["correct"] == 1 and flow[0]["kinds"] == "daily"
    # The per-word detail for that day, and the shaky-word list.
    words = {x["word"]: x["correct"] for x in db.spelling_attempts_on(sid, date.today().isoformat())}
    assert words == {"separate": 1, "rhythm": 0}
    shaky = db.shaky_spelling_words(sid)
    assert [w["word"] for w in shaky] == ["rhythm"]


def test_complete_quiz_records_score_logs_hours_and_sets_grade(db, student):
    sid = student["id"]
    a = db.add_spelling_word(sid, "necessary", "It is ____.", "on")
    b = db.add_spelling_word(sid, "conscience", "A clear ____.", "stretch")
    outcome = spelling.complete_quiz(db, student, [(a, True, "necessary"), (b, True, "conscience")], duration_seconds=240)
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


def test_the_parent_review_shows_the_daily_flow_in_records(monkeypatch, tmp_path):
    db_path = tmp_path / "review.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    spelling.save_settings(db, enabled=True)
    a = db.add_spelling_word(student["id"], "separate", "Keep them ____.", "on")
    b = db.add_spelling_word(student["id"], "rhythm", "A steady ____.", "on")
    spelling.complete_daily(db, student, [(a, True, "separate"), (b, False, "rhythem")], duration_seconds=95)
    db.close()

    st.cache_resource.clear()
    monkeypatch.setattr(config, "DEFAULT_DB_PATH", db_path)
    at = AppTest.from_file(HOME_PATH)
    at.session_state["parent_unlocked"] = True
    at.run(timeout=30)
    at.switch_page(MISSION_CONTROL_PATH)
    at.session_state["mc_view"] = "records"
    at.run(timeout=30)
    assert not at.exception, [e.message for e in at.exception]
    text = " ".join(m.value for m in at.markdown)
    assert "🔤 Spelling" in text
    assert "His daily flow" in text
    assert "rhythm" in text  # the shaky word he missed shows in "still working on"


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


# --- learn-first study step + letter-level feedback (Stage A) --------------------


def test_letter_diff_highlights_the_missed_letters():
    """A miss should teach: the correct word comes back with the specific letters
    he got wrong highlighted, not just 'wrong'. Reported: 'legit top notch for
    learning'."""
    from compass.ui import _spelling_letter_diff_html

    html = _spelling_letter_diff_html("rythm", "rhythm")
    # every letter of the correct word is present, and the missing 'h' is wrapped
    assert "rhythm".replace("h", "") in html.replace("<span", "").replace("</span>", "") \
        or "ythm" in html
    assert "<span" in html and ">h<" in html  # the h is the highlighted letter
    # a perfect answer highlights nothing
    assert "<span" not in _spelling_letter_diff_html("island", "island")
    # a blank answer highlights the whole word
    assert _spelling_letter_diff_html("", "island").count("<span") == 1


def test_daily_card_has_a_study_step_but_the_quiz_does_not(monkeypatch, tmp_path):
    """The daily practice card carries a 'study this word' step (Look-Cover-Write-
    Check); the weekly quiz stays a clean test with no study aid."""
    from compass import auth

    def render(quiz_day_offset, *, expect_quiz):
        db_path = tmp_path / f"study_{quiz_day_offset}.db"
        db = Database(db_path)
        student = db.ensure_default_student()
        auth.set_pin(db, "1234")
        import datetime
        today_wd = datetime.date.today().weekday()
        spelling.save_settings(db, enabled=True,
                               quiz_day=(today_wd if expect_quiz else (today_wd + 1) % 7))
        db.add_spelling_word(student["id"], "rhythm", "a steady ____", "on",
                             definition="a repeated beat", syllables="rhy-thm")
        db.close()
        st.cache_resource.clear()
        monkeypatch.setattr(config, "DEFAULT_DB_PATH", db_path)
        with patch("compass.ui.render_first_day_celebration", return_value=False):
            at = AppTest.from_file(HOME_PATH)
            at.run(timeout=30)
        assert not at.exception, [e.message for e in at.exception]
        return " ".join(
            (getattr(e, "label", "") or "") for e in list(at.expander)
        )

    daily_expanders = render(1, expect_quiz=False)
    assert "Study this word" in daily_expanders   # the learn-first step is on the daily card

    quiz_expanders = render(0, expect_quiz=True)
    assert "Study this word" not in quiz_expanders  # ...but never on the graded quiz


def test_daily_card_offers_a_second_try_and_counts_a_self_fix(monkeypatch, tmp_path):
    """A cold miss on the daily card isn't an instant fail: he gets a fix-up round
    with the correct spelling shown, and fixing it counts. Reported: 'gentle
    two-try scaffold instead of instant fail'."""
    from compass import auth

    db_path = tmp_path / "twotry.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    auth.set_pin(db, "1234")
    import datetime
    today_wd = datetime.date.today().weekday()
    spelling.save_settings(db, enabled=True, quiz_day=(today_wd + 1) % 7, daily_count=2)
    db.add_spelling_word(student["id"], "rhythm", "a steady ____", "on")
    db.add_spelling_word(student["id"], "island", "an ____ in the sea", "on")
    words = {w["word"]: w["id"] for w in db.list_spelling_words(student["id"])}
    db.close()

    st.cache_resource.clear()
    monkeypatch.setattr(config, "DEFAULT_DB_PATH", db_path)
    with patch("compass.ui.render_first_day_celebration", return_value=False):
        at = AppTest.from_file(HOME_PATH)
        at.run(timeout=30)
        # One right, one wrong on the first check.
        at.text_input(key=f"spd_in_{words['rhythm']}").set_value("rhythm")
        at.text_input(key=f"spd_in_{words['island']}").set_value("iland")  # missing s
        at.button(key="spd_submit").click().run(timeout=30)
        assert not at.exception, [e.message for e in at.exception]

        # It did NOT finalize -- the fix-up round is showing, not the done state.
        from compass import spelling as sp
        assert not sp.daily_done_today(Database(db_path))
        fix_inputs = [t.key for t in at.text_input if (t.key or "").startswith("spd_fix_in_")]
        assert fix_inputs == [f"spd_fix_in_{words['island']}"]  # only the missed word

        # Fix it on the second look -> it counts.
        at.text_input(key=f"spd_fix_in_{words['island']}").set_value("island")
        at.button(key="spd_fix_submit").click().run(timeout=30)
        assert not at.exception, [e.message for e in at.exception]

    db = Database(db_path)
    assert sp.daily_done_today(db)                      # now it's finalized
    # the self-fixed word counts as correct (climbed a box, no miss recorded)
    by_word = {w["word"]: w for w in db.list_spelling_words(student["id"], include_retired=True)}
    assert by_word["island"]["times_correct"] == 1 and by_word["island"]["times_missed"] == 0
    assert by_word["rhythm"]["times_correct"] == 1     # the first-try word too
    db.close()


# --- difficulty / level control -------------------------------------------------


def test_reset_spelling_pool_retires_active_but_keeps_history(db, student):
    """Lowering the level and rebuilding retires his current words (so the new
    level takes effect today) without deleting them -- his attempt history and
    grade are built from the rows, which must survive."""
    for w in ("alpha", "bravo", "charlie"):
        db.add_spelling_word(student["id"], w, "a ____ clue", "on")
    assert db.spelling_pool_counts(student["id"])["active"] == 3

    retired = db.reset_spelling_pool(student["id"])
    assert retired == 3
    counts = db.spelling_pool_counts(student["id"])
    assert counts["active"] == 0          # none in rotation now
    assert counts["total"] == 3           # ...but the rows (history) are kept


def test_rebuild_regenerates_at_the_new_level(db, student):
    """After dialing the level down, a rebuild generates fresh words AT that
    level -- the generation prompt carries the new grade band."""
    spelling.save_settings(db, enabled=True, level="grade 6")
    for w in ("oldone", "oldtwo"):
        db.add_spelling_word(student["id"], w, "an ____ clue", "stretch")

    db.reset_spelling_pool(student["id"])
    with patch("compass.agents.llm.generate_lesson", return_value=_FAKE_WORDS) as gen, \
         patch("compass.agents.api_available", return_value=(True, "")):
        made = spelling.ensure_pool(db, student, minimum=3)
    assert made >= 3
    # the prompt was built for grade 6, not his grade 8
    system = gen.call_args.kwargs["system"]
    assert "grade 6" in system
    active = {w["word"] for w in db.list_spelling_words(student["id"])}  # active only
    assert "observation" in active and "oldone" not in active


def test_difficulty_control_lowers_his_level(tmp_path, monkeypatch):
    """The parent view's new Difficulty selector writes the level override, so
    'Easier' actually drops the grade Compass writes his words at. Reported: "bring
    down the level ... allow for the type of dynamic change ... for parent."""
    st.cache_resource.clear()
    monkeypatch.setattr(config, "DEFAULT_DB_PATH", str(tmp_path / "s.db"))
    db = Database(tmp_path / "s.db")
    student = db.ensure_default_student()
    spelling.save_settings(db, enabled=True)
    db.close()

    at = AppTest.from_file(HOME_PATH)
    at.session_state["parent_unlocked"] = True
    at.run(timeout=30)
    at.switch_page(str(REPO_ROOT / "pages" / "14_Mission_Control.py"))
    at.session_state["mc_view"] = "setup"
    at.run(timeout=30)

    diff = [sb for sb in at.selectbox if (sb.label or "") == "Difficulty"]
    assert diff, "the Difficulty selector should render when spelling is on"
    easier = next(o for o in diff[0].options if "Easier — two grades down" in o)
    diff[0].set_value(easier).run(timeout=30)
    assert not at.exception, [e.message for e in at.exception]

    db = Database(tmp_path / "s.db")
    assert spelling.effective_level(db, db.ensure_default_student()) == "grade 6"
    db.close()


# --- seeing his submission + how long it took -----------------------------------


def test_daily_submission_stores_exactly_what_he_typed_and_the_time(db, student):
    """A parent needs to see his real submission and pacing, not just a tally:
    each word keeps the exact text he typed, and the whole card keeps its
    wall-clock time. Reported: "can i see his submission? and ... track how long
    it took him."""
    sid = student["id"]
    a = db.add_spelling_word(sid, "separate", "Keep them ____.", "on")
    b = db.add_spelling_word(sid, "rhythm", "A steady ____.", "on")
    spelling.complete_daily(
        db, student, [(a, True, "separate"), (b, False, "rhythem")], duration_seconds=95
    )
    rows = {x["word"]: x for x in db.spelling_attempts_on(sid, date.today().isoformat())}
    assert rows["rhythm"]["typed"] == "rhythem"       # his exact (wrong) spelling
    assert rows["separate"]["typed"] == "separate"
    assert rows["rhythm"]["duration_seconds"] == 95
    assert db.spelling_daily_flow(sid)[0]["seconds"] == 95


def test_quiz_submission_stores_its_duration(db, student):
    sid = student["id"]
    a = db.add_spelling_word(sid, "necessary", "It is ____.", "on")
    spelling.complete_quiz(db, student, [(a, True, "necessary")], duration_seconds=240)
    res = db.list_spelling_quiz_results(sid)
    assert res and res[0]["duration_seconds"] == 240


def test_review_shows_his_typed_submission_and_time(monkeypatch, tmp_path):
    db_path = tmp_path / "sub.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    spelling.save_settings(db, enabled=True)
    a = db.add_spelling_word(student["id"], "separate", "Keep them ____.", "on")
    b = db.add_spelling_word(student["id"], "rhythm", "A steady ____.", "on")
    spelling.complete_daily(
        db, student, [(a, True, "separate"), (b, False, "rhythem")], duration_seconds=95
    )
    db.close()

    st.cache_resource.clear()
    monkeypatch.setattr(config, "DEFAULT_DB_PATH", db_path)
    at = AppTest.from_file(HOME_PATH)
    at.session_state["parent_unlocked"] = True
    at.run(timeout=30)
    at.switch_page(MISSION_CONTROL_PATH)
    at.session_state["mc_view"] = "records"
    at.run(timeout=30)
    assert not at.exception, [e.message for e in at.exception]
    text = " ".join(
        [m.value for m in at.markdown]
        + [c.value for c in at.caption]
        + [e.label for e in at.expander]
    )
    assert "exactly what he typed" in text          # the submission expander
    assert "rhythem" in text                        # his actual wrong spelling
    assert "1 min 35 s" in text                     # 95s rendered as a duration
