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
