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
    is_backlogged,
    latest_per_day,
    math_stage_note,
    plan_day,
    plan_missing_days,
    planning_nudge,
    today_subject_status,
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


def test_week_dates_can_include_friday_as_a_fifth_option():
    """Friday stays out unless explicitly asked for -- the escape hatch for
    a week where a holiday on another weekday means Friday's needed as a
    substitute lesson day instead."""
    dates = week_dates(date(2026, 8, 10), include_friday=True)
    assert dates == [
        date(2026, 8, 10),
        date(2026, 8, 11),
        date(2026, 8, 12),
        date(2026, 8, 13),
        date(2026, 8, 14),
    ]


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


def test_due_lessons_excludes_a_lesson_from_a_fully_elapsed_week():
    """The Backlog feature's actual effect on due_lessons: merely overdue
    (same week) still surfaces, same as always, but once the whole week's
    gone by it's backlogged instead -- pulled out of the due list entirely,
    not just sorted to the bottom of it."""
    lessons = [_lesson(1, "math", "2026-08-10")]  # Monday, week of Aug 10
    assert due_lessons(lessons, "2026-08-18") == []  # the following Tuesday


# --- is_backlogged: a whole week's gone by without it being turned in -----------


def test_is_backlogged_false_for_a_lesson_still_within_its_own_week():
    lesson = _lesson(1, "math", "2026-08-10")  # Monday
    assert not is_backlogged(lesson, "2026-08-13")  # Thursday, same week


def test_is_backlogged_true_once_its_own_week_has_fully_ended():
    lesson = _lesson(1, "math", "2026-08-10")  # Monday, week of Aug 10
    assert is_backlogged(lesson, "2026-08-18")  # Tuesday, the following week


def test_is_backlogged_false_for_an_untagged_on_demand_lesson():
    """No planned_for at all -- no week concept, so it's never backlogged,
    matching due_lessons' own unbounded treatment of one."""
    untagged = {"id": 9, "agent": "math", "metadata": {}}
    assert not is_backlogged(untagged, "2026-08-18")


def test_is_backlogged_true_when_held_back_even_within_this_week():
    """A parent's own "not this week" call, any day -- the manual
    counterpart to a whole week quietly running out on its own. Still
    true even when the lesson isn't due yet, let alone overdue."""
    lesson = {"id": 1, "agent": "math", "metadata": {"planned_for": "2026-08-14", "held_back": True}}
    assert is_backlogged(lesson, "2026-08-10")  # planned_for is still 4 days out


def test_is_backlogged_true_when_held_back_with_no_planned_for_at_all():
    """Even an on-demand lesson (no week concept) can be sent to backlog
    by hand -- it just never falls into it from time passing alone."""
    lesson = {"id": 1, "agent": "math", "metadata": {"held_back": True}}
    assert is_backlogged(lesson, "2026-08-18")


def test_due_lessons_excludes_a_held_back_lesson_due_today():
    """The actual point of the manual send-to-backlog feature: a parent
    can pull today's own due lesson out of Landon's view the instant they
    decide to, not just once its week eventually runs out."""
    lesson = _lesson(1, "math", "2026-08-11")
    lesson["metadata"]["held_back"] = True
    assert due_lessons([lesson], "2026-08-11") == []


# --- today_subject_status: one subject's row on Home's daily roster --------------


def _status_lesson(id, status, *, planned_for=None, done=None):
    metadata = {}
    if planned_for is not None:
        metadata["planned_for"] = planned_for
    if done is not None:
        metadata["student_done_on"] = done
    return {"id": id, "agent": "math", "status": status, "metadata": metadata}


def test_today_subject_status_prefers_a_pending_submission_over_anything_due():
    lessons = [
        _status_lesson(1, "submitted", planned_for="2026-08-11"),
        _status_lesson(2, "planned", planned_for="2026-08-11"),
    ]
    lesson, marker = today_subject_status(lessons, "2026-08-11")
    assert lesson["id"] == 1
    assert marker == "\U0001F4E4"


def test_today_subject_status_marks_a_sent_back_lesson_distinctly():
    lessons = [_status_lesson(1, "needs_revision", planned_for="2026-08-10")]
    lesson, marker = today_subject_status(lessons, "2026-08-11")
    assert lesson["id"] == 1
    assert marker == "↩️"


def test_today_subject_status_shows_an_empty_box_for_something_due_but_untouched():
    lessons = [_status_lesson(1, "planned", planned_for="2026-08-11")]
    lesson, marker = today_subject_status(lessons, "2026-08-11")
    assert lesson["id"] == 1
    assert marker == "⬜"


def test_today_subject_status_shows_a_green_check_once_fully_approved_today():
    """Nothing due, nothing pending, but he finished and a parent approved
    this same subject's lesson earlier today -- the roster should still
    show it, checked, rather than reading as if nothing had happened."""
    lessons = [_status_lesson(1, "completed", done="2026-08-11")]
    lesson, marker = today_subject_status(lessons, "2026-08-11")
    assert lesson["id"] == 1
    assert marker == "✅"


def test_today_subject_status_ignores_a_lesson_completed_on_an_earlier_day():
    """An old approved lesson from a previous day isn't "today's" status --
    it's not relevant to what's on his plate right now."""
    lessons = [_status_lesson(1, "completed", done="2026-08-05")]
    lesson, marker = today_subject_status(lessons, "2026-08-11")
    assert lesson is None
    assert marker == ""


def test_today_subject_status_is_empty_when_nothing_is_set_up_for_this_subject():
    lesson, marker = today_subject_status([], "2026-08-11")
    assert lesson is None
    assert marker == ""


def test_today_subject_status_ignores_a_lesson_planned_for_a_later_day():
    lessons = [_status_lesson(1, "planned", planned_for="2026-08-14")]  # later this week
    lesson, marker = today_subject_status(lessons, "2026-08-11")
    assert lesson is None
    assert marker == ""


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


# --- plan_missing_days, non-math: independent, fresh topics -----------------------


def test_plan_missing_days_produces_one_result_per_missing_day():
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
    dates = week_dates(date(2026, 8, 10))
    results = plan_missing_days(None, STUDENT, agent, date(2026, 8, 10), dates, dates)
    assert [r.target_date for r in results] == dates
    assert [r.generated.payload["title"] for r in results] == [
        "Topic 1", "Topic 2", "Topic 3", "Topic 4",
    ]


def test_plan_missing_days_one_days_failure_does_not_block_the_others_when_not_math():
    calls = {"n": 0}

    def propose(ctx):
        calls["n"] += 1
        return a_proposal(topic=f"Topic {calls['n']}")

    def generate(ctx, proposal):
        if calls["n"] == 2:
            raise LessonGenerationError("rate limited")
        return GeneratedLesson(lesson_id=calls["n"], proposal=proposal, payload={}, warnings=[])

    agent = FakeAgent(propose_fn=propose, generate_fn=generate)
    dates = week_dates(date(2026, 8, 10))
    results = plan_missing_days(None, STUDENT, agent, date(2026, 8, 10), dates, dates)
    assert [r.error for r in results] == [None, "rate limited", None, None]


def test_plan_missing_days_seed_topics_target_a_specific_day_by_index():
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
    dates = week_dates(date(2026, 8, 10))
    plan_missing_days(
        None, STUDENT, agent, date(2026, 8, 10), dates, dates,
        seed_topics={0: "Rocks vs. Big Rigs (CrunchLabs)"},
    )
    assert seen_seeds == ["Rocks vs. Big Rigs (CrunchLabs)", "", "", ""]


def test_plan_missing_days_only_generates_the_missing_subset():
    """The whole reason `target_dates` and `missing_dates` are separate
    lists: a day already planned in an earlier session must be skipped
    entirely (no call at all), while a later day's index -- for seed
    targeting, and for math's stage note -- is still its position in the
    full week, not its position among the days actually being filled in."""
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
    dates = week_dates(date(2026, 8, 10))  # Mon-Thu
    missing = dates[1:]  # Tue-Thu only -- Monday already planned
    results = plan_missing_days(
        None, STUDENT, agent, date(2026, 8, 10), dates, missing,
        seed_topics={0: "should never be used -- day 0 isn't missing"},
    )
    assert [r.target_date for r in results] == missing
    assert seen_seeds == ["", "", ""]


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


# --- plan_missing_days, is_math=True: one skill, framed across the week -----------


def a_math_agent(propose_fn, generate_fn):
    agent = FakeAgent(propose_fn=propose_fn, generate_fn=generate_fn)
    agent.key = "math"
    return agent


def test_plan_missing_days_math_reuses_the_same_skill_across_all_four_days():
    seen_skill_ids = []

    def propose(ctx):
        seen_skill_ids.append(ctx.inputs.get("skill_id", ""))
        return a_proposal(metadata={"skill_id": "integer_operations"})

    agent = a_math_agent(
        propose_fn=propose,
        generate_fn=lambda ctx, proposal: GeneratedLesson(
            lesson_id=1, proposal=proposal, payload={}, warnings=[]
        ),
    )
    dates = week_dates(date(2026, 8, 10))
    results = plan_missing_days(None, STUDENT, agent, date(2026, 8, 10), dates, dates, is_math=True)

    assert len(results) == 4
    assert all(r.error is None for r in results)
    # Day 1 asks for nothing specific; days 2-4 are pinned to day 1's pick.
    assert seen_skill_ids == ["", "integer_operations", "integer_operations", "integer_operations"]


def test_plan_missing_days_math_escalates_the_parent_note_each_day():
    seen_notes = []

    def propose(ctx):
        seen_notes.append(ctx.inputs.get("parent_note", ""))
        return a_proposal(metadata={"skill_id": "integer_operations"})

    agent = a_math_agent(
        propose_fn=propose,
        generate_fn=lambda ctx, proposal: GeneratedLesson(
            lesson_id=1, proposal=proposal, payload={}, warnings=[]
        ),
    )
    dates = week_dates(date(2026, 8, 10))
    plan_missing_days(None, STUDENT, agent, date(2026, 8, 10), dates, dates, is_math=True)

    assert tuple(seen_notes) == MATH_STAGE_NOTES
    assert seen_notes[0] == ""
    assert "day 2 of 4" in seen_notes[1].lower()
    assert "not a re-introduction" in seen_notes[1].lower()
    assert "assessment" in seen_notes[3].lower()  # day 4 leans toward grading


def test_plan_missing_days_math_stops_reinforcing_when_the_first_day_is_blocked():
    agent = a_math_agent(
        propose_fn=lambda ctx: a_proposal(blocked=True, blocked_reason="Every skill mastered."),
        generate_fn=lambda ctx, proposal: pytest.fail("should not generate"),
    )
    dates = week_dates(date(2026, 8, 10))
    results = plan_missing_days(None, STUDENT, agent, date(2026, 8, 10), dates, dates, is_math=True)

    assert results[0].error == "Every skill mastered."
    assert all("Skipped" in r.error for r in results[1:])


def test_plan_missing_days_math_stops_reinforcing_when_a_later_day_fails():
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
    dates = week_dates(date(2026, 8, 10))
    results = plan_missing_days(None, STUDENT, agent, date(2026, 8, 10), dates, dates, is_math=True)

    assert results[0].error is None
    assert results[1].error == "rate limited"
    assert results[2].error == "Skipped — rate limited"
    assert results[3].error == "Skipped — rate limited"


def test_plan_missing_days_math_stops_across_a_missing_subset_too():
    """The same stop-on-failure rule, exercised through the actual "fill in
    missing days" path This_Week.py uses: Tuesday (already planned earlier)
    isn't in `missing_dates` at all, Wednesday fails, so Thursday -- also
    missing -- must come back skipped rather than reinforcing a skill that
    was never confirmed."""
    calls = {"n": 0}

    def propose(ctx):
        calls["n"] += 1
        return a_proposal(metadata={"skill_id": "integer_operations"})

    def generate(ctx, proposal):
        raise LessonGenerationError("rate limited")

    agent = a_math_agent(propose_fn=propose, generate_fn=generate)
    dates = week_dates(date(2026, 8, 10))  # Mon-Thu
    missing = dates[2:]  # Wed-Thu only
    results = plan_missing_days(
        None, STUDENT, agent, date(2026, 8, 10), dates, missing,
        is_math=True, skill_id="integer_operations",
    )

    assert results[0].target_date == dates[2]
    assert results[0].error == "rate limited"
    assert results[1].target_date == dates[3]
    assert results[1].error == "Skipped — rate limited"


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
