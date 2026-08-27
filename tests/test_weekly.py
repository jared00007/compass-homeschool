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

from datetime import date, timedelta
from unittest.mock import patch

import pytest

from compass.agents.framework import GeneratedLesson, TopicProposal
from compass.agents.llm import LessonGenerationError
from compass.storage.db import Database
from compass.weekly import (
    MATH_STAGE_NOTES,
    default_plan_target,
    due_lessons,
    latest_per_day,
    math_stage_note,
    plan_day,
    plan_math_week,
    plan_subject_week,
    planning_nudge,
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


# --- due_lessons: "what's actually due now," not "whatever was generated most recently" ---


def test_due_lessons_picks_todays_over_a_later_generated_id():
    """The regression this exists to fix: batch-planning a whole week in one
    sitting means Friday's lesson has the highest id even though today is
    Tuesday -- id order must not win over the actual planned day."""
    lessons = [
        _lesson(5, "math", "2026-08-14"),  # Friday, generated last -> highest id
        _lesson(2, "math", "2026-08-11"),  # Tuesday -- today
    ]
    result = due_lessons(lessons, "2026-08-11")
    assert [l["id"] for l in result] == [2]


def test_due_lessons_excludes_anything_planned_for_a_later_day():
    lessons = [_lesson(1, "math", "2026-08-12")]  # Wednesday
    assert due_lessons(lessons, "2026-08-11") == []  # today is Tuesday


def test_due_lessons_includes_an_overdue_lesson_from_an_earlier_day():
    lessons = [_lesson(1, "math", "2026-08-10")]  # Monday, never done
    assert due_lessons(lessons, "2026-08-11") == lessons  # today is Tuesday


def test_due_lessons_sorts_oldest_overdue_first():
    lessons = [
        _lesson(1, "math", "2026-08-11"),  # today
        _lesson(2, "math", "2026-08-10"),  # overdue from yesterday
    ]
    result = due_lessons(lessons, "2026-08-11")
    assert [l["id"] for l in result] == [2, 1]


def test_due_lessons_puts_untagged_lessons_last():
    """A lesson generated the ordinary on-demand way (no day attached at
    all) is still due now -- it just yields to anything with a real day."""
    untagged = {"id": 9, "agent": "math", "metadata": {}}
    lessons = [untagged, _lesson(1, "math", "2026-08-11")]
    result = due_lessons(lessons, "2026-08-11")
    assert [l["id"] for l in result] == [1, 9]


def test_due_lessons_on_an_all_untagged_list_preserves_input_order():
    """No day tags anywhere (a family that's never used weekly batch
    planning) -- behaves like the old "most recent first" selection, since
    the caller already sorts lessons that way before calling this."""
    lessons = [
        {"id": 2, "agent": "math", "metadata": {}},
        {"id": 1, "agent": "math", "metadata": {}},
    ]
    result = due_lessons(lessons, "2026-08-11")
    assert [l["id"] for l in result] == [2, 1]


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


def test_plan_day_forwards_node_id():
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
    plan_day(None, STUDENT, agent, date(2026, 8, 10), date(2026, 8, 10), node_id="42")
    assert seen_inputs["node_id"] == "42"
    assert "seed_topic" not in seen_inputs


def test_plan_day_omits_node_id_when_not_given():
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
    plan_day(None, STUDENT, agent, date(2026, 8, 10), date(2026, 8, 10))
    assert "node_id" not in seen_inputs


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


# --- math_stage_note: the same escalating note, for a holiday-shortened week -------


def test_math_stage_note_matches_the_fixed_four_day_version():
    """Same wording as MATH_STAGE_NOTES for the ordinary case -- this only
    needs to differ once the week is shorter than four days."""
    for index in range(4):
        assert math_stage_note(index, 4) == MATH_STAGE_NOTES[index]


def test_math_stage_note_day_one_is_always_blank():
    assert math_stage_note(0, 1) == ""
    assert math_stage_note(0, 3) == ""


def test_math_stage_note_counts_against_the_actual_total():
    note = math_stage_note(1, 3)
    assert "day 2 of 3" in note
    assert "day 2 of 4" not in note


def test_math_stage_note_last_day_is_weighted_toward_the_assessment():
    note = math_stage_note(2, 3)
    assert "day 3 of 3" in note
    assert "assessment" in note.lower()


def test_math_stage_note_on_a_single_day_week_has_no_middle_tier():
    """Day one and the last day are the same day on a one-day week --
    the "no note yet" branch wins, since there's nothing to escalate
    from within a single day."""
    assert math_stage_note(0, 1) == ""


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


# --- planning_nudge ---------------------------------------------------------------


@pytest.fixture()
def nudge_db(tmp_path):
    database = Database(tmp_path / "test.db")
    yield database
    database.close()


@pytest.fixture()
def nudge_student(nudge_db):
    return nudge_db.ensure_default_student()


def _plan_a_lesson(db, student_id, week_start_date):
    db.save_lesson(
        student_id=student_id, agent="math", subject="math", topic="t", title="t",
        payload={},
        metadata={"week_start": week_start_date.isoformat(), "planned_for": week_start_date.isoformat()},
    )


def test_warns_when_a_weekday_arrives_to_an_unplanned_week(nudge_db, nudge_student):
    monday = date(2026, 8, 10)  # a Monday
    severity, message = planning_nudge(nudge_db, nudge_student["id"], today=monday)
    assert severity == "warning"
    assert "hasn't been planned" in message


@pytest.mark.parametrize("weekday_offset", [0, 1, 2, 3])  # Mon, Tue, Wed, Thu
def test_no_nudge_on_any_weekday_once_this_week_is_planned(nudge_db, nudge_student, weekday_offset):
    monday = date(2026, 8, 10)
    _plan_a_lesson(nudge_db, nudge_student["id"], monday)
    assert planning_nudge(nudge_db, nudge_student["id"], today=monday + timedelta(days=weekday_offset)) is None


@pytest.mark.parametrize("weekday_offset", [4, 5, 6])  # Fri, Sat, Sun
def test_gently_nudges_on_a_weekend_when_next_week_is_unplanned(nudge_db, nudge_student, weekday_offset):
    monday = date(2026, 8, 10)
    on = monday + timedelta(days=weekday_offset)
    severity, message = planning_nudge(nudge_db, nudge_student["id"], today=on)
    assert severity == "info"
    assert "Next week hasn't been planned" in message


def test_no_nudge_once_next_week_is_planned_ahead_of_time(nudge_db, nudge_student):
    friday = date(2026, 8, 14)
    _plan_a_lesson(nudge_db, nudge_student["id"], default_plan_target(friday))
    assert planning_nudge(nudge_db, nudge_student["id"], today=friday) is None


def test_weekend_nudge_ignores_whether_the_week_just_finished_was_ever_planned(
    nudge_db, nudge_student
):
    """By Friday, Monday-Thursday is already history -- the nudge shifts to
    being about next week specifically, not a lingering complaint about a
    week that's effectively over."""
    friday = date(2026, 8, 14)
    _plan_a_lesson(nudge_db, nudge_student["id"], default_plan_target(friday))
    # the week that just ended (starting Aug 10) was deliberately never planned
    assert planning_nudge(nudge_db, nudge_student["id"], today=friday) is None
