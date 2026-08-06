"""The life-skills planner.

The point of this module is what it *doesn't* do — it never picks a skill — so
most of these tests are about the boundary rather than the output. The rest check
that a plan gets the same credit policing a Tier 1 lesson does, since the hours
land in the same compliance record either way.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from compass.agents import life_skills
from compass.storage.db import Database


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    yield database
    database.close()


@pytest.fixture()
def student(db):
    return db.ensure_default_student()


@pytest.fixture()
def skill(db, student):
    skill_id = db.add_life_skill(
        student["id"],
        "Change a tire",
        category="Vehicle",
        description="Swaps the spare on unaided, torques the nuts in a star pattern.",
        credit_subject="occupational_education",
    )
    return next(s for s in db.list_life_skills(student["id"]) if s["id"] == skill_id)


def a_plan(**overrides):
    payload = {
        "title": "Changing a tire on the trailer",
        "overview": "Do it in the driveway before you have to do it on a shoulder.",
        "prep": "Park on level ground. Find the jack.",
        "materials": ["The spare", "Jack", "Lug wrench"],
        "steps": [
            {
                "title": "Break the nuts loose",
                "minutes": 20,
                "what_he_does": "Loosen each nut a quarter turn before jacking.",
                "what_you_do": "Demonstrate one, then hand it over and stay quiet.",
            },
            {
                "title": "Jack and swap",
                "minutes": 40,
                "what_he_does": "Raise the vehicle and swap the wheel.",
                "what_you_do": "Watch the jack point. Say nothing else.",
            },
        ],
        "watch_for": ["A jack on soft ground will sink."],
        "done_looks_like": "Spare on, nuts torqued in a star pattern, tools stowed.",
        "follow_ups": ["Next flat is his."],
        "subject_credits": [
            {"subject": "occupational_education", "minutes": 60, "justification": "The swap."}
        ],
        "estimated_minutes": 60,
        "_usage": {"input_tokens": 10, "output_tokens": 20},
    }
    payload.update(overrides)
    return payload


def generate(db, student, skill, payload, **kwargs):
    with patch("compass.agents.life_skills.generate_lesson", return_value=payload) as call:
        plan = life_skills.generate_plan(db, student, skill, minutes=60, **kwargs)
    return plan, call


# --- the boundary ------------------------------------------------------------


def test_the_planner_is_not_a_registered_agent():
    """It has no next-topic strategy because it never chooses a topic."""
    from compass.agents import all_agents

    assert life_skills.AGENT_KEY not in all_agents()


def test_the_prompt_forbids_proposing_a_different_skill(db, student, skill):
    _, call = generate(db, student, skill, a_plan())
    system = call.call_args.kwargs["system"]
    assert "Do not \\\npropose a different skill" in system or "propose a different skill" in system
    user = call.call_args.kwargs["user_prompt"]
    assert "Change a tire" in user
    assert "star pattern" in user, "the parent's own bar for 'done' has to reach the model"


def test_science_is_not_claimable(db, student, skill):
    """Cooking chemistry is a Science lesson; letting both claim it double-counts."""
    assert "science" not in life_skills.SECONDARY_CREDIT_SUBJECTS
    payload = a_plan(
        subject_credits=[
            {"subject": "occupational_education", "minutes": 60, "justification": "swap"},
            {"subject": "science", "minutes": 30, "justification": "leverage"},
        ]
    )
    plan, _ = generate(db, student, skill, payload)
    assert plan.credits == {"occupational_education": 60}
    assert any("outside this agent's scope" in w for w in plan.warnings)


def test_web_search_is_off_unless_asked_for(db, student, skill):
    _, call = generate(db, student, skill, a_plan())
    assert call.call_args.kwargs["use_web_search"] is False

    _, call = generate(db, student, skill, a_plan(), use_web_search=True)
    assert call.call_args.kwargs["use_web_search"] is True


# --- credits -----------------------------------------------------------------


def test_secondary_credits_cannot_exceed_the_session(db, student, skill):
    payload = a_plan(
        subject_credits=[
            {"subject": "occupational_education", "minutes": 60, "justification": "swap"},
            {"subject": "math", "minutes": 40, "justification": "torque figures"},
            {"subject": "health", "minutes": 40, "justification": "safety"},
        ]
    )
    plan, _ = generate(db, student, skill, payload)
    secondary = sum(m for s, m in plan.credits.items() if s != "occupational_education")
    assert secondary <= plan.total_minutes
    assert any("scaled down to fit" in w for w in plan.warnings)


def test_the_parents_chosen_subject_is_always_credited(db, student, skill):
    payload = a_plan(
        subject_credits=[{"subject": "math", "minutes": 30, "justification": "torque"}]
    )
    plan, _ = generate(db, student, skill, payload)
    assert plan.credits["occupational_education"] == 60


def test_total_time_is_reconciled_against_the_steps(db, student, skill):
    plan, _ = generate(db, student, skill, a_plan(estimated_minutes=200))
    assert plan.total_minutes == 60, "60 minutes of steps is 60 minutes, whatever it claimed"


def test_the_parents_subject_wins_even_outside_the_narrow_list(db, student, skill):
    """The starter checklist bills "write a polite email" as Language, and it's right.

    Silently rebilling it as occupational education because Language isn't on the
    planner's own shortlist would be the exact silent wrong answer this track is
    meant to avoid. The shortlist bounds what the model *adds*, not what the
    parent chose.
    """
    db.conn.execute(
        "UPDATE life_skills SET credit_subject = 'art_and_music' WHERE id = ?", (skill["id"],)
    )
    db.conn.commit()
    reloaded = next(s for s in db.list_life_skills(student["id"]) if s["id"] == skill["id"])

    assert life_skills.allowed_credits(reloaded)[0] == "art_and_music"
    plan, call = generate(db, student, reloaded, a_plan())
    assert plan.credits["art_and_music"] == 60, "the parent's subject is credited in full"
    enum = call.call_args.kwargs["schema"]["properties"]["subject_credits"]["items"][
        "properties"
    ]["subject"]["enum"]
    assert enum[0] == "art_and_music", "the schema has to offer it, or the model can't return it"


def test_a_nonsense_credit_subject_falls_back(db, student, skill):
    db.conn.execute(
        "UPDATE life_skills SET credit_subject = 'underwater_basketry' WHERE id = ?",
        (skill["id"],),
    )
    db.conn.commit()
    reloaded = next(s for s in db.list_life_skills(student["id"]) if s["id"] == skill["id"])
    assert life_skills.allowed_credits(reloaded)[0] == life_skills.DEFAULT_PRIMARY


# --- persistence -------------------------------------------------------------


def test_a_plan_is_stored_against_its_skill_and_costed(db, student, skill):
    plan, _ = generate(db, student, skill, a_plan())

    found = db.latest_life_skill_plan(student["id"], skill["id"])
    assert found["id"] == plan.lesson_id
    assert found["metadata"]["life_skill_id"] == skill["id"]

    start, end = db.school_year_bounds()
    usage = db.lesson_usage_between(student["id"], start, end)
    assert [u["agent"] for u in usage] == [life_skills.AGENT_KEY], "plans must show on the bill"


def test_the_newest_plan_wins(db, student, skill):
    generate(db, student, skill, a_plan(title="first attempt"))
    plan, _ = generate(db, student, skill, a_plan(title="second attempt"))
    found = db.latest_life_skill_plan(student["id"], skill["id"])
    assert found["id"] == plan.lesson_id
    assert found["payload"]["title"] == "second attempt"


def test_renaming_a_skill_does_not_orphan_its_plan(db, student, skill):
    generate(db, student, skill, a_plan())
    db.conn.execute(
        "UPDATE life_skills SET title = 'Change a tire (trailer)' WHERE id = ?", (skill["id"],)
    )
    db.conn.commit()
    assert db.latest_life_skill_plan(student["id"], skill["id"]) is not None


def test_plans_do_not_reach_the_students_home_page(db, student, skill):
    """The plan is written to the parent — 'stay quiet and let him fail' is not his."""
    generate(db, student, skill, a_plan())
    lessons = db.list_lessons(student["id"], limit=25)
    visible = [l for l in lessons if l["agent"] != life_skills.AGENT_KEY]
    assert lessons and not visible
