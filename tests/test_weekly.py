"""Weekly planning -- Friday reviews the week just finished and plans the
week ahead.

Two things worth pinning down here: the date math (which Monday does a given
day belong to, what "next week" means), and the orchestration split between
Science/English/History (four independent, fresh topics -- each day's own
state update is what makes the next call different) and Math (one skill for
the whole week, since the mastery gate means nothing changes between calls
made in the same sitting without a real graded assessment in between).
"""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest

from compass.agents.framework import GeneratedLesson, TopicProposal
from compass.agents.llm import LessonGenerationError
from compass.weekly import (
    MATH_STAGE_NOTES,
    default_plan_target,
    latest_per_day,
    plan_day,
    plan_math_week,
    plan_subject_week,
    week_dates,
    week_start,
)

STUDENT = {"id": 1, "name": "Landon", "grade": "8"}


# --- date helpers ----------------------------------------------------------------


@pytest.mark.parametrize(
    "on,expected_monday",
    [
        (date(2026, 8, 10), date(2026, 8, 10)),  # a Monday
        (date(2026, 8, 14), date(2026, 8, 10)),  # a Friday, same week
        (date(2026, 8, 16), date(2026, 8, 10)),  # a Sunday, still that week
        (date(2026, 8, 17), date(2026, 8, 17)),  # the following Monday
    ],
)
def test_week_start_finds_the_monday(on, expected_monday):
    assert week_start(on) == expected_monday


def test_week_start_defaults_to_today():
    assert week_start() == week_start(date.today())


def test_week_dates_is_monday_through_thursday_only():
    dates = week_dates(date(2026, 8, 10))
    assert dates == [date(2026, 8, 10), date(2026, 8, 11), date(2026, 8, 12), date(2026, 8, 13)]


def test_default_plan_target_is_the_monday_after_next():
    """Planning always targets the week ahead, not the one about to end --
    Friday Aug 14 sits in the week starting Aug 10, so the plan target is
    Aug 17, not Aug 10 itself."""
    assert default_plan_target(date(2026, 8, 14)) == date(2026, 8, 17)


# --- latest_per_day: dedup for a regenerated day ------------------------------------


def _lesson(id, agent, planned_for):
    return {"id": id, "agent": agent, "metadata": {"planned_for": planned_for}}


def test_latest_per_day_keeps_the_newest_lesson_for_a_regenerated_day():
    lessons = [
        _lesson(1, "math", "2026-08-10"),
        _lesson(2, "math", "2026-08-10"),  # regenerated -- supersedes id 1
    ]
    result = latest_per_day(lessons)
    assert len(result) == 1
    assert result[0]["id"] == 2


def test_latest_per_day_keeps_different_agents_and_days_separate():
    lessons = [
        _lesson(1, "math", "2026-08-10"),
        _lesson(2, "science", "2026-08-10"),
        _lesson(3, "math", "2026-08-11"),
    ]
    result = latest_per_day(lessons)
    assert {(l["id"]) for l in result} == {1, 2, 3}


def test_latest_per_day_sorts_by_planned_for_then_id():
    lessons = [
        _lesson(5, "math", "2026-08-12"),
        _lesson(1, "science", "2026-08-10"),
        _lesson(3, "english", "2026-08-10"),
    ]
    result = latest_per_day(lessons)
    assert [l["id"] for l in result] == [1, 3, 5]


# --- plan_day: the single-day primitive -------------------------------------------


class FakeAgent:
    key = "science"

    def __init__(self, propose_fn, generate_fn):
        self._propose_fn = propose_fn
        self._generate_fn = generate_fn

    def propose_topic(self, ctx):
        return self._propose_fn(ctx)

    def generate(self, ctx, proposal):
        return self._generate_fn(ctx, proposal)


def a_proposal(**overrides):
    proposal = TopicProposal(topic="Nurse logs", rationale="r", strategy="spiderweb", metadata={})
    for key, value in overrides.items():
        setattr(proposal, key, value)
    return proposal


def test_plan_day_stamps_week_start_and_planned_for_on_success():
    agent = FakeAgent(
        propose_fn=lambda ctx: a_proposal(),
        generate_fn=lambda ctx, proposal: GeneratedLesson(
            lesson_id=1, proposal=proposal, payload={"title": "Nurse logs"}, warnings=[]
        ),
    )
    result = plan_day(None, STUDENT, agent, date(2026, 8, 10), date(2026, 8, 12))
    assert result.error is None
    assert result.generated.proposal.metadata["week_start"] == "2026-08-10"
    assert result.generated.proposal.metadata["planned_for"] == "2026-08-12"


def test_plan_day_reports_a_blocked_proposal_without_generating():
    called = []
    agent = FakeAgent(
        propose_fn=lambda ctx: a_proposal(blocked=True, blocked_reason="Every skill mastered."),
        generate_fn=lambda ctx, proposal: called.append(1) or pytest.fail("should not generate"),
    )
    result = plan_day(None, STUDENT, agent, date(2026, 8, 10), date(2026, 8, 10))
    assert result.error == "Every skill mastered."
    assert result.generated is None
    assert not called


def test_plan_day_catches_a_generation_error():
    agent = FakeAgent(
        propose_fn=lambda ctx: a_proposal(),
        generate_fn=lambda ctx, proposal: (_ for _ in ()).throw(
            LessonGenerationError("Rate limited by the Anthropic API.")
        ),
    )
    result = plan_day(None, STUDENT, agent, date(2026, 8, 10), date(2026, 8, 10))
    assert result.error == "Rate limited by the Anthropic API."
    assert result.generated is None


def test_plan_day_forwards_seed_topic_and_skill_id_and_parent_note():
    seen_inputs = {}

    def propose(ctx):
        seen_inputs.update(ctx.inputs)
        return a_proposal()

    agent = FakeAgent(
        propose_fn=propose,
        generate_fn=lambda ctx, proposal: GeneratedLesson(
            lesson_id=1, proposal=proposal, payload={}, warnings=[]
        ),
    )
    plan_day(
        None, STUDENT, agent, date(2026, 8, 10), date(2026, 8, 10),
        seed_topic="Rocks vs. Big Rigs (CrunchLabs)", skill_id="integer_operations",
        parent_note="Day 2 of 4.",
    )
    assert seen_inputs["seed_topic"] == "Rocks vs. Big Rigs (CrunchLabs)"
    assert seen_inputs["skill_id"] == "integer_operations"
    assert seen_inputs["parent_note"] == "Day 2 of 4."


# --- plan_subject_week: four independent, fresh topics ----------------------------


def test_plan_subject_week_produces_four_days():
    calls = {"n": 0}

    def propose(ctx):
        calls["n"] += 1
        return a_proposal(topic=f"Topic {calls['n']}")

    agent = FakeAgent(
        propose_fn=propose,
        generate_fn=lambda ctx, proposal: GeneratedLesson(
            lesson_id=calls["n"], proposal=proposal, payload={"title": proposal.topic}, warnings=[]
        ),
    )
    results = plan_subject_week(None, STUDENT, agent, date(2026, 8, 10))
    assert [r.target_date for r in results] == week_dates(date(2026, 8, 10))
    assert [r.generated.payload["title"] for r in results] == [
        "Topic 1", "Topic 2", "Topic 3", "Topic 4",
    ]


def test_plan_subject_week_one_days_failure_does_not_block_the_others():
    calls = {"n": 0}

    def propose(ctx):
        calls["n"] += 1
        return a_proposal(topic=f"Topic {calls['n']}")

    def generate(ctx, proposal):
        if calls["n"] == 2:
            raise LessonGenerationError("rate limited")
        return GeneratedLesson(lesson_id=calls["n"], proposal=proposal, payload={}, warnings=[])

    agent = FakeAgent(propose_fn=propose, generate_fn=generate)
    results = plan_subject_week(None, STUDENT, agent, date(2026, 8, 10))
    assert [r.error for r in results] == [None, "rate limited", None, None]


def test_plan_subject_week_seed_topics_target_a_specific_day_by_index():
    seen_seeds = []

    def propose(ctx):
        seen_seeds.append(ctx.inputs.get("seed_topic", ""))
        return a_proposal()

    agent = FakeAgent(
        propose_fn=propose,
        generate_fn=lambda ctx, proposal: GeneratedLesson(
            lesson_id=1, proposal=proposal, payload={}, warnings=[]
        ),
    )
    plan_subject_week(
        None, STUDENT, agent, date(2026, 8, 10),
        seed_topics={0: "Rocks vs. Big Rigs (CrunchLabs)"},
    )
    assert seen_seeds == ["Rocks vs. Big Rigs (CrunchLabs)", "", "", ""]


# --- plan_math_week: one skill, framed across the week -----------------------------


def a_math_agent(propose_fn, generate_fn):
    agent = FakeAgent(propose_fn=propose_fn, generate_fn=generate_fn)
    agent.key = "math"
    return agent


def test_plan_math_week_reuses_the_same_skill_across_all_four_days():
    seen_skill_ids = []

    def propose(ctx):
        seen_skill_ids.append(ctx.inputs.get("skill_id", ""))
        return a_proposal(metadata={"skill_id": "integer_operations"})

    with patch(
        "compass.agents.get_agent",
        return_value=a_math_agent(
            propose_fn=propose,
            generate_fn=lambda ctx, proposal: GeneratedLesson(
                lesson_id=1, proposal=proposal, payload={}, warnings=[]
            ),
        ),
    ):
        results = plan_math_week(None, STUDENT, date(2026, 8, 10))

    assert len(results) == 4
    assert all(r.error is None for r in results)
    # Day 1 asks for nothing specific; days 2-4 are pinned to day 1's pick.
    assert seen_skill_ids == ["", "integer_operations", "integer_operations", "integer_operations"]


def test_plan_math_week_escalates_the_parent_note_each_day():
    seen_notes = []

    def propose(ctx):
        seen_notes.append(ctx.inputs.get("parent_note", ""))
        return a_proposal(metadata={"skill_id": "integer_operations"})

    with patch(
        "compass.agents.get_agent",
        return_value=a_math_agent(
            propose_fn=propose,
            generate_fn=lambda ctx, proposal: GeneratedLesson(
                lesson_id=1, proposal=proposal, payload={}, warnings=[]
            ),
        ),
    ):
        plan_math_week(None, STUDENT, date(2026, 8, 10))

    assert tuple(seen_notes) == MATH_STAGE_NOTES
    assert seen_notes[0] == ""
    assert "day 2 of 4" in seen_notes[1].lower()
    assert "not a re-introduction" in seen_notes[1].lower()
    assert "assessment" in seen_notes[3].lower()  # day 4 leans toward grading


def test_plan_math_week_stops_reinforcing_when_the_first_day_is_blocked():
    agent = a_math_agent(
        propose_fn=lambda ctx: a_proposal(blocked=True, blocked_reason="Every skill mastered."),
        generate_fn=lambda ctx, proposal: pytest.fail("should not generate"),
    )
    with patch("compass.agents.get_agent", return_value=agent):
        results = plan_math_week(None, STUDENT, date(2026, 8, 10))

    assert results[0].error == "Every skill mastered."
    assert all("Skipped" in r.error for r in results[1:])


def test_plan_math_week_stops_reinforcing_when_a_later_day_fails():
    """Day 1 succeeds, day 2 fails -- days 3 and 4 must not blindly continue
    reinforcing a skill using state that never got confirmed."""
    calls = {"n": 0}

    def propose(ctx):
        calls["n"] += 1
        return a_proposal(metadata={"skill_id": "integer_operations"})

    def generate(ctx, proposal):
        if calls["n"] == 2:
            raise LessonGenerationError("rate limited")
        return GeneratedLesson(lesson_id=calls["n"], proposal=proposal, payload={}, warnings=[])

    agent = a_math_agent(propose_fn=propose, generate_fn=generate)
    with patch("compass.agents.get_agent", return_value=agent):
        results = plan_math_week(None, STUDENT, date(2026, 8, 10))

    assert results[0].error is None
    assert results[1].error == "rate limited"
    assert results[2].error == "Skipped — rate limited"
    assert results[3].error == "Skipped — rate limited"
