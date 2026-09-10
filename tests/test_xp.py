"""XP totals and the level curve."""

from __future__ import annotations

from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from compass import auth, config, xp
from compass.storage.db import Database

REPO_ROOT = Path(__file__).resolve().parent.parent
HOME_PATH = str(REPO_ROOT / "Home.py")
MISSION_CONTROL_PATH = str(REPO_ROOT / "pages" / "14_Mission_Control.py")


def _open_mission_control(monkeypatch, db_path):
    st.cache_resource.clear()
    monkeypatch.setattr(config, "DEFAULT_DB_PATH", db_path)
    at = AppTest.from_file(HOME_PATH)
    at.session_state["parent_unlocked"] = True
    at.run(timeout=30)
    at.switch_page(MISSION_CONTROL_PATH)
    at.run(timeout=30)
    assert not at.exception, [e.message for e in at.exception]
    return at


def test_level_math_from_a_raw_total():
    span = config.XP_PER_LEVEL
    # Zero XP is level 1, freshly started.
    zero = xp.state_for_total(0)
    assert zero.level == 1
    assert zero.into_level == 0
    assert zero.to_next == span
    assert zero.fraction == 0.0

    # One full span crosses into level 2.
    two = xp.state_for_total(span)
    assert two.level == 2
    assert two.into_level == 0

    # Halfway through a level reads as 0.5 progress.
    half = xp.state_for_total(span + span // 2)
    assert half.level == 2
    assert half.fraction == pytest.approx(0.5)


def test_rank_title_holds_at_the_last_name_for_high_levels():
    # A level far beyond the rank list still gets the final title, never an
    # index error.
    huge = xp.state_for_total(config.XP_PER_LEVEL * 500)
    assert huge.title == config.XP_RANKS[-1]


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "xp.db")
    yield database
    database.close()


@pytest.fixture()
def student(db):
    return db.ensure_default_student()


def test_total_xp_sums_his_completion_signals(db, student):
    sid = student["id"]

    # A lesson he finished, with a passed quiz -> lesson XP + quiz bonus.
    db.save_lesson(
        student_id=sid, agent="math", subject="math", topic="t", title="Done Math",
        payload={"activities": []},
        metadata={"student_done_on": "2026-09-01", "quiz_result": {"passed": True}},
    )
    # A lesson generated but not finished -> no XP.
    db.save_lesson(
        student_id=sid, agent="science", subject="science", topic="t", title="Not Done",
        payload={"activities": []}, metadata={},
    )
    # A completed life skill.
    skill_id = db.add_life_skill(sid, "Do the laundry")
    db.set_life_skill_done(skill_id, True)

    expected = (
        config.XP_PER_LESSON
        + config.XP_QUIZ_PASS_BONUS
        + config.XP_PER_LIFE_SKILL
    )
    assert xp.total_xp(db, sid) == expected

    state = xp.compute(db, sid)
    assert state.total == expected
    assert state.level == expected // config.XP_PER_LEVEL + 1


def test_a_brand_new_student_is_level_one_with_zero_xp(db, student):
    state = xp.compute(db, student["id"])
    assert state.total == 0
    assert state.level == 1
    assert state.title == config.XP_RANKS[0]


def test_sent_back_lessons_dock_xp(db, student):
    sid = student["id"]
    # A finished lesson that was sent back twice: earns the lesson XP but loses
    # two penalties (one per bounce).
    db.save_lesson(
        student_id=sid, agent="english", subject="english", topic="t", title="Redo",
        payload={"activities": []},
        metadata={
            "student_done_on": "2026-09-01",
            "lesson_feedback_history": ["Fix intro", "Still needs work"],
        },
    )
    expected = config.XP_PER_LESSON - 2 * config.XP_SENT_BACK_PENALTY
    assert xp.total_xp(db, sid) == expected
    assert xp.sent_back_penalty(db, sid) == 2 * config.XP_SENT_BACK_PENALTY


def test_total_xp_never_goes_negative(db, student):
    sid = student["id"]
    # A lesson never finished (no lesson XP) but bounced twice -> would be
    # negative, floored to zero.
    db.save_lesson(
        student_id=sid, agent="english", subject="english", topic="t", title="Rough",
        payload={"activities": []},
        metadata={"lesson_feedback_history": ["a", "b", "c", "d", "e"]},
    )
    assert xp.total_xp(db, sid) == 0


def test_legacy_single_feedback_field_counts_as_one_bounce(db, student):
    sid = student["id"]
    db.save_lesson(
        student_id=sid, agent="english", subject="english", topic="t", title="Old",
        payload={"activities": []},
        metadata={"student_done_on": "2026-09-01", "lesson_feedback": "One old note"},
    )
    assert xp.total_xp(db, sid) == config.XP_PER_LESSON - config.XP_SENT_BACK_PENALTY


# --- the weekly reward loop ------------------------------------------------------

from datetime import date, timedelta


def _monday_of(iso: str) -> date:
    d = date.fromisoformat(iso)
    return d - timedelta(days=d.weekday())


def test_week_bounds_are_monday_through_friday():
    # A Thursday.
    monday, friday = xp.week_bounds(date(2026, 9, 10))
    assert monday == date(2026, 9, 7)   # the Monday
    assert friday == date(2026, 9, 11)  # the Friday
    # A Sunday still belongs to the week that just ended.
    monday, friday = xp.week_bounds(date(2026, 9, 13))
    assert monday == date(2026, 9, 7)


def test_weekly_progress_counts_only_this_weeks_core_work(db, student):
    sid = student["id"]
    today = date(2026, 9, 10)  # Thursday
    this_mon = "2026-09-07"    # Monday of that week
    last_week = "2026-08-31"   # a Monday a week earlier

    # Two lessons finished this week, one with a passed quiz; one finished last
    # week (must NOT count this week).
    db.save_lesson(
        student_id=sid, agent="math", subject="math", topic="t", title="A",
        payload={"activities": []},
        metadata={"student_done_on": this_mon, "quiz_result": {"passed": True, "graded_on": this_mon}},
    )
    db.save_lesson(
        student_id=sid, agent="science", subject="science", topic="t", title="B",
        payload={"activities": []}, metadata={"student_done_on": "2026-09-08"},
    )
    db.save_lesson(
        student_id=sid, agent="history", subject="history", topic="t", title="Old",
        payload={"activities": []}, metadata={"student_done_on": last_week},
    )

    progress = xp.weekly_progress(db, sid, today)
    # Two lessons + one quiz this week; last week's lesson excluded.
    assert progress.core_xp == 2 * config.XP_PER_LESSON + config.XP_QUIZ_PASS_BONUS
    assert progress.total == progress.core_xp
    # Monday's panel holds the lesson + quiz; Tuesday's holds the second lesson.
    mon, tue = progress.days[0], progress.days[1]
    assert (mon.lessons, mon.quizzes) == (1, 1)
    assert mon.xp == config.XP_PER_LESSON + config.XP_QUIZ_PASS_BONUS
    assert tue.lessons == 1
    assert progress.goal == config.XP_WEEKLY_GOAL


def test_weekly_redo_docks_xp_on_the_day_it_happened(db, student):
    sid = student["id"]
    today = date(2026, 9, 10)
    db.save_lesson(
        student_id=sid, agent="english", subject="english", topic="t", title="Redo",
        payload={"activities": []},
        metadata={"student_done_on": "2026-09-07", "sent_back_on": ["2026-09-09"]},  # Wed
    )
    progress = xp.weekly_progress(db, sid, today)
    wed = progress.days[2]
    assert wed.redos == 1
    assert wed.xp == -config.XP_SENT_BACK_PENALTY
    # Net for the week: one lesson (Mon) minus one redo (Wed).
    assert progress.core_xp == config.XP_PER_LESSON - config.XP_SENT_BACK_PENALTY


def test_send_lesson_back_stamps_the_date_for_the_weekly_strip(db, student):
    sid = student["id"]
    lid = db.save_lesson(
        student_id=sid, agent="english", subject="english", topic="t", title="X",
        payload={"activities": []}, metadata={"student_done_on": "2026-09-07"},
    )
    db.send_lesson_back(lid, "fix it")
    lesson = db.get_lesson(lid)
    stamps = lesson["metadata"].get("sent_back_on")
    assert stamps and len(stamps) == 1  # dated, so the redo can land on its day


def test_extra_credit_counts_as_bonus_toward_the_goal(db, student):
    sid = student["id"]
    today = date(2026, 9, 10)  # Thursday
    # A life skill completed this week -> bonus XP toward the same goal. Its
    # completion date is stamped to a weekday inside the window so the test is
    # deterministic regardless of the real day it runs.
    skill_id = db.add_life_skill(sid, "Laundry")
    db.set_life_skill_done(skill_id, True)
    db.conn.execute(
        "UPDATE life_skills SET completed_on = ? WHERE id = ?", ("2026-09-08", skill_id)
    )
    db.conn.commit()

    progress = xp.weekly_progress(db, sid, today)
    assert progress.bonus_xp == config.XP_PER_LIFE_SKILL
    assert progress.total == config.XP_PER_LIFE_SKILL
    assert any("life skill" in b.label for b in progress.bonus_items)
    assert progress.week_start == date(2026, 9, 7)


def test_weekly_goal_and_reward_are_editable(db, student):
    # Defaults out of the box.
    assert xp.weekly_goal(db) == config.XP_WEEKLY_GOAL
    assert xp.weekly_reward(db) == (config.XP_WEEKLY_REWARD_NAME, config.XP_WEEKLY_REWARD_EMOJI)

    xp.set_weekly_goal(db, 250)
    xp.set_weekly_reward(db, "Pizza night", "🍕")
    assert xp.weekly_goal(db) == 250
    assert xp.weekly_reward(db) == ("Pizza night", "🍕")

    # A junk / non-positive goal falls back to the default rather than breaking.
    db.set_setting("xp_weekly_goal", "not a number")
    assert xp.weekly_goal(db) == config.XP_WEEKLY_GOAL
    # A blank name falls back to the config default reward name.
    xp.set_weekly_reward(db, "  ", "🎁")
    assert xp.weekly_reward(db)[0] == config.XP_WEEKLY_REWARD_NAME


def test_reward_is_earned_unclaimed_until_the_parent_marks_the_week_given(db, student):
    sid = student["id"]
    today = date(2026, 9, 10)
    monday = _monday_of("2026-09-10")
    xp.set_weekly_goal(db, 20)
    # One lesson (+20) hits the goal exactly.
    db.save_lesson(
        student_id=sid, agent="math", subject="math", topic="t", title="A",
        payload={"activities": []}, metadata={"student_done_on": "2026-09-07"},
    )
    progress = xp.weekly_progress(db, sid, today)
    assert progress.reached
    assert progress.earned_unclaimed
    assert not progress.given

    # Parent hands it over for that week.
    xp.set_week_reward_given(db, monday, True)
    progress = xp.weekly_progress(db, sid, today)
    assert progress.given
    assert not progress.earned_unclaimed

    # Un-give restores it.
    xp.set_week_reward_given(db, monday, False)
    assert monday.isoformat() not in xp.weeks_given(db)


def test_weeks_given_survive_a_malformed_setting(db, student):
    db.set_setting("xp_weeks_given", "not json at all")
    assert xp.weeks_given(db) == set()


def test_close_flag_triggers_within_the_margin(db, student):
    sid = student["id"]
    today = date(2026, 9, 10)
    xp.set_weekly_goal(db, 100)
    # 60 XP of work: 3 lessons -> 40 short, which is within the close margin.
    for day in ("2026-09-07", "2026-09-08", "2026-09-09"):
        db.save_lesson(
            student_id=sid, agent="math", subject="math", topic="t", title=day,
            payload={"activities": []}, metadata={"student_done_on": day},
        )
    progress = xp.weekly_progress(db, sid, today)
    assert not progress.reached
    assert progress.close  # 40 <= WEEKLY_CLOSE_MARGIN
    assert progress.remaining == 40


def test_mission_control_shows_and_clears_the_weekly_reward(monkeypatch, tmp_path):
    """The parent needs to know when he's earned the week's reward. A goal of 0
    is 'reached' immediately, so Mission Control's review queue shows it with a
    'Mark as given' button; clicking it records the week as given."""
    db_path = tmp_path / "reward.db"
    database = Database(db_path)
    sid = database.ensure_default_student()["id"]
    auth.set_pin(database, "1234")
    # A tiny goal so any state reads as reached; give him one lesson finished on
    # the current week's Monday, so it's in-window whatever day the test runs.
    database.set_setting("xp_weekly_goal", "10")
    this_monday = date.today() - timedelta(days=date.today().weekday())
    database.save_lesson(
        student_id=sid, agent="math", subject="math", topic="t", title="A",
        payload={"activities": []},
        metadata={"student_done_on": this_monday.isoformat()},
    )
    database.close()

    at = _open_mission_control(monkeypatch, db_path)
    body = " ".join(m.value for m in at.markdown)
    assert "time to deliver" in body
    give = [b for b in at.button if (b.key or "") == "reward_given_week"][0]
    give.click().run()
    assert not at.exception, [e.message for e in at.exception]

    database = Database(db_path)
    assert xp.weeks_given(database)  # the week is recorded as given
    database.close()


# --- learner_stats: the Home KPI strip -------------------------------------------


def test_learner_stats_tally_of_finished_work(db, student):
    sid = student["id"]
    # Two finished math lessons (one with a passed quiz), one finished english.
    db.save_lesson(
        student_id=sid, agent="math", subject="math", topic="t", title="Math A",
        payload={"activities": []},
        metadata={"student_done_on": "2026-09-01", "quiz_result": {"passed": True}},
    )
    db.save_lesson(
        student_id=sid, agent="math", subject="math", topic="t", title="Math B",
        payload={"activities": []}, metadata={"student_done_on": "2026-09-02"},
    )
    db.save_lesson(
        student_id=sid, agent="english", subject="english", topic="t", title="Eng A",
        payload={"activities": []}, metadata={"student_done_on": "2026-09-03"},
    )
    # A generated-but-unfinished lesson counts for nothing.
    db.save_lesson(
        student_id=sid, agent="science", subject="science", topic="t", title="Sci",
        payload={"activities": []}, metadata={},
    )
    skill_id = db.add_life_skill(sid, "Laundry")
    db.set_life_skill_done(skill_id, True)

    stats = xp.learner_stats(db, sid)
    assert stats.lessons_done == 3
    assert stats.quizzes_passed == 1
    assert stats.skills_done == 1
    # Math is his by-volume workhorse.
    assert stats.heaviest_subject == "math"
    assert stats.heaviest_subject_count == 2


def test_learner_stats_are_all_zero_for_a_fresh_student(db, student):
    stats = xp.learner_stats(db, student["id"])
    assert stats.lessons_done == 0
    assert stats.quizzes_passed == 0
    assert stats.heaviest_subject is None
    assert stats.heaviest_subject_count == 0
