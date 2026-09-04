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


def test_rewards_unlock_by_cumulative_xp():
    first_threshold = config.XP_REWARDS[0][0]
    # Just under the first threshold: nothing unlocked, and it's the next target.
    below = xp.rewards_for_total(first_threshold - 1)
    assert not any(r.unlocked for r in below)
    assert xp.next_reward(first_threshold - 1).threshold == first_threshold

    # Exactly at the first threshold: it unlocks.
    at = xp.rewards_for_total(first_threshold)
    assert at[0].unlocked
    assert xp.next_reward(first_threshold).threshold == config.XP_REWARDS[1][0]

    # Past every threshold: all unlocked, no next reward.
    top = config.XP_REWARDS[-1][0] + 1
    assert all(r.unlocked for r in xp.rewards_for_total(top))
    assert xp.next_reward(top) is None


def test_a_reward_is_earned_unclaimed_until_the_parent_marks_it_given(db, student):
    """The state the parent needs to see: he's crossed the threshold but hasn't
    been handed the reward yet."""
    first = config.XP_REWARDS[0][0]
    # Earned by XP, but no 'given' recorded -> earned_unclaimed.
    rewards = xp.rewards_for_total(first, list(config.XP_REWARDS), xp.given_thresholds(db))
    assert rewards[0].earned_unclaimed
    assert not rewards[0].given

    # Parent marks it given -> no longer needs attention, flagged given.
    xp.set_reward_given(db, first, True)
    rewards = xp.rewards_for_total(first, list(config.XP_REWARDS), xp.given_thresholds(db))
    assert rewards[0].given
    assert not rewards[0].earned_unclaimed

    # Un-give restores it.
    xp.set_reward_given(db, first, False)
    assert first not in xp.given_thresholds(db)


def test_given_thresholds_survive_a_malformed_setting(db, student):
    db.set_setting("xp_rewards_given", "not json at all")
    assert xp.given_thresholds(db) == set()


def test_reward_ladder_defaults_to_config(db, student):
    # No stored setting -> the config defaults, as tuples ascending by threshold.
    ladder = xp.reward_ladder(db)
    assert ladder == list(config.XP_REWARDS)


def test_parent_can_edit_and_reset_the_reward_ladder(db, student):
    xp.set_reward_ladder(db, [
        {"threshold": 500, "name": "Concert tickets", "emoji": "🎫"},
        {"threshold": 100, "name": "Pizza night", "emoji": "🍕"},
        {"threshold": 0, "name": "  ", "emoji": "🎁"},  # blank name -> dropped
    ])
    ladder = xp.reward_ladder(db)
    # Sorted ascending, blank dropped.
    assert ladder == [(100, "Pizza night", "🍕"), (500, "Concert tickets", "🎫")]
    # And the student-facing helpers honor it.
    assert xp.next_reward(0, ladder).name == "Pizza night"
    assert [r.name for r in xp.rewards_for_total(200, ladder) if r.unlocked] == ["Pizza night"]

    # Clearing the setting falls back to config defaults.
    db.set_setting("xp_rewards", "")
    assert xp.reward_ladder(db) == list(config.XP_REWARDS)


def test_reward_ladder_tolerates_a_junk_setting(db, student):
    db.set_setting("xp_rewards", "not json at all")
    assert xp.reward_ladder(db) == list(config.XP_REWARDS)
    # A list with only junk rows also falls back rather than leaving no rewards.
    import json
    db.set_setting("xp_rewards", json.dumps([{"nope": 1}]))
    assert xp.reward_ladder(db) == list(config.XP_REWARDS)


def test_mission_control_shows_and_clears_an_earned_reward(monkeypatch, tmp_path):
    """The parent needs to know when he's earned one. A zero-threshold reward is
    'earned' at 0 XP, so Mission Control's review queue shows it with a 'Mark as
    given' button; clicking it records the reward as given."""
    db_path = tmp_path / "reward.db"
    database = Database(db_path)
    database.ensure_default_student()
    auth.set_pin(database, "1234")
    xp.set_reward_ladder(database, [{"threshold": 0, "name": "Movie night", "emoji": "🎬"}])
    database.close()

    at = _open_mission_control(monkeypatch, db_path)
    body = " ".join(m.value for m in at.markdown)
    assert "earned 1 reward" in body
    assert "Movie night" in body
    give = [b for b in at.button if (b.key or "") == "reward_given_0"][0]
    give.click().run()
    assert not at.exception, [e.message for e in at.exception]

    database = Database(db_path)
    assert 0 in xp.given_thresholds(database)
    database.close()
