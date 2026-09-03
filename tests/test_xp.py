"""XP totals and the level curve."""

from __future__ import annotations

import pytest

from compass import config, xp
from compass.storage.db import Database


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
