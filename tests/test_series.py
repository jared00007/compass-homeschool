"""Chunking a topic into a multi-day lesson series.

The planning call and each day's generation are the model's job and are mocked
here; what this pins is the deterministic wiring around them -- that a topic
becomes N ordered fixed-shape lessons, each carrying series metadata and no
`planned_for`, each day pointed at its own focus without re-teaching earlier
days, and that the student walks them in order.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from compass.agents import get_agent
from compass.agents.framework import StudentContext, TopicProposal
from compass.storage.db import Database


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    yield database
    database.close()


@pytest.fixture()
def student(db):
    return db.ensure_default_student()


def ctx_for(db, student, **inputs) -> StudentContext:
    return StudentContext(db=db, student_id=student["id"], student=student, inputs=inputs)


def a_payload(**overrides):
    payload = {
        "title": "A day",
        "activities": [{"minutes": 30}, {"minutes": 15}],
        "estimated_minutes": 45,
        "subject_credits": [{"subject": "math", "minutes": 45, "justification": ""}],
    }
    payload.update(overrides)
    return payload


THREE_DAYS = [
    {"title": "Naming the sides", "focus": "Legs vs hypotenuse."},
    {"title": "Finding the hypotenuse", "focus": "a²+b²=c² for c."},
    {"title": "Finding a leg", "focus": "Rearranging for a missing leg."},
]


# --- the engine: a topic becomes N ordered lessons ----------------------------


def test_generate_series_creates_one_lesson_per_planned_day(db, student):
    agent = get_agent("math")
    proposal = TopicProposal(topic="Pythagorean Theorem", rationale="r", strategy="graph_walk")
    with patch("compass.agents.series.plan_lesson_series", return_value=THREE_DAYS), patch(
        "compass.agents.framework.generate_lesson", side_effect=lambda **k: a_payload()
    ):
        results = agent.generate_series(ctx_for(db, student), proposal)
    assert len(results) == 3
    lessons = db.list_lessons(student["id"], agent="math", limit=10)
    assert len(lessons) == 3


def test_series_lessons_carry_shared_id_and_ordered_index(db, student):
    agent = get_agent("math")
    proposal = TopicProposal(topic="Pythagorean Theorem", rationale="r", strategy="graph_walk")
    with patch("compass.agents.series.plan_lesson_series", return_value=THREE_DAYS), patch(
        "compass.agents.framework.generate_lesson", side_effect=lambda **k: a_payload()
    ):
        results = agent.generate_series(ctx_for(db, student), proposal)
    metas = [db.get_lesson(r.lesson_id)["metadata"] for r in results]
    assert len({m["series_id"] for m in metas}) == 1  # all one series
    assert [m["series_index"] for m in metas] == [0, 1, 2]
    assert all(m["series_total"] == 3 for m in metas)
    assert all(m["series_title"] == "Pythagorean Theorem" for m in metas)


def test_series_lessons_land_in_the_backlog_with_no_day_assigned(db, student):
    """A generated series flows into the parent's Backlog as raw material to
    schedule by day: each lesson is held_back (so it's backlogged and stays out
    of the student's queue) and carries no planned_for until the parent assigns
    one."""
    from compass import weekly

    agent = get_agent("math")
    proposal = TopicProposal(topic="Pythagorean Theorem", rationale="r", strategy="graph_walk")
    with patch("compass.agents.series.plan_lesson_series", return_value=THREE_DAYS), patch(
        "compass.agents.framework.generate_lesson", side_effect=lambda **k: a_payload()
    ):
        results = agent.generate_series(ctx_for(db, student), proposal)
    today = "2026-09-06"
    for r in results:
        lesson = db.get_lesson(r.lesson_id)
        assert "planned_for" not in lesson["metadata"]
        assert lesson["metadata"]["held_back"] is True
        assert weekly.is_backlogged(lesson, today)
    # Backlogged, so the student sees none of them until a day is assigned.
    assert weekly.due_lessons(
        [db.get_lesson(r.lesson_id) for r in results], today
    ) == []


def test_each_day_is_pointed_at_its_own_focus_without_reteaching(db, student):
    """Every day's user prompt names that day's focus and lists the earlier
    days as already covered, so the model teaches one chunk at a time."""
    agent = get_agent("math")
    proposal = TopicProposal(topic="Pythagorean Theorem", rationale="r", strategy="graph_walk")
    seen_prompts: list[str] = []
    with patch("compass.agents.series.plan_lesson_series", return_value=THREE_DAYS), patch(
        "compass.agents.framework.generate_lesson",
        side_effect=lambda **k: seen_prompts.append(k["user_prompt"]) or a_payload(),
    ):
        agent.generate_series(ctx_for(db, student), proposal)
    # Day 2's prompt names its own focus and flags day 1 as already covered.
    assert "a²+b²=c² for c." in seen_prompts[1]
    assert "do NOT reteach" in seen_prompts[1]
    assert "Naming the sides" in seen_prompts[1]
    # Day 1 has nothing earlier to avoid re-teaching.
    assert "do NOT reteach" not in seen_prompts[0]


def test_an_empty_plan_still_produces_one_real_lesson(db, student):
    """A blank/unusable planning response must not silently generate nothing --
    it falls back to a single-day series on the whole topic."""
    agent = get_agent("math")
    proposal = TopicProposal(topic="Pythagorean Theorem", rationale="r", strategy="graph_walk")
    with patch("compass.agents.series.plan_lesson_series", return_value=[]), patch(
        "compass.agents.framework.generate_lesson", side_effect=lambda **k: a_payload()
    ):
        results = agent.generate_series(ctx_for(db, student), proposal)
    assert len(results) == 1
    assert db.get_lesson(results[0].lesson_id)["metadata"]["series_total"] == 1


def test_a_single_day_series_leaves_the_proposal_untouched(db, student):
    agent = get_agent("math")
    proposal = TopicProposal(
        topic="Small topic", rationale="r", strategy="graph_walk",
        context_lines=["some context"],
    )
    one_day = [{"title": "Small topic", "focus": "the whole thing"}]
    seen: list[str] = []
    with patch("compass.agents.series.plan_lesson_series", return_value=one_day), patch(
        "compass.agents.framework.generate_lesson",
        side_effect=lambda **k: seen.append(k["user_prompt"]) or a_payload(),
    ):
        agent.generate_series(ctx_for(db, student), proposal)
    # A one-day series doesn't add the "day 1 of N" scaffolding.
    assert "day 1 of" not in seen[0]


def test_a_forced_blocked_proposal_raises_rather_than_generating(db, student):
    from compass.agents.llm import LessonGenerationError

    agent = get_agent("math")
    blocked = TopicProposal(
        topic="", rationale="", strategy="graph_walk", blocked=True,
        blocked_reason="locked",
    )
    with pytest.raises(LessonGenerationError):
        agent.generate_series(ctx_for(db, student), blocked)


# --- the planner: parsing the model's day breakdown ---------------------------


def test_plan_lesson_series_parses_and_cleans_the_days():
    from compass.agents import series

    raw = {"days": [
        {"title": "One", "focus": "first focus"},
        {"title": "", "focus": "second focus"},   # blank title -> falls back to focus
        {"title": "Three", "focus": "   "},         # blank focus -> dropped
    ]}
    with patch("compass.agents.series.generate_lesson", return_value=raw):
        days = series.plan_lesson_series(
            topic="t", subject_label="Math", grade="8", minutes_per_day=45
        )
    assert days == [
        {"title": "One", "focus": "first focus"},
        {"title": "second focus", "focus": "second focus"},
    ]


def test_plan_lesson_series_caps_the_day_count():
    from compass.agents import series

    raw = {"days": [{"title": f"D{i}", "focus": f"f{i}"} for i in range(20)]}
    with patch("compass.agents.series.generate_lesson", return_value=raw):
        days = series.plan_lesson_series(
            topic="t", subject_label="Math", grade="8", minutes_per_day=45
        )
    assert len(days) == series.MAX_SERIES_DAYS


# --- ordering: the student walks a series in order ----------------------------



def test_an_unscheduled_series_lesson_is_backlogged_not_due(db, student):
    """A series lives in the parent's Backlog until a day is assigned, so an
    unscheduled series lesson is backlogged and never shows in the student's due
    list -- and this holds even for one generated before the `held_back` flag
    existed (series_id + no planned_for is enough), so old series don't strand
    in the 'planned' list."""
    from compass import weekly

    lid = db.save_lesson(
        student_id=student["id"], agent="math", subject="math", topic="t",
        title="Day 1", payload={"title": "Day 1", "activities": []},
        metadata={"series_id": "s1", "series_index": 0, "series_total": 2},  # no held_back
    )
    lesson = db.get_lesson(lid)
    today = "2026-09-06"
    assert weekly.is_backlogged(lesson, today)
    assert weekly.due_lessons([lesson], today) == []

    # Assigning a day clears the backlog and makes it live.
    db.reschedule_lesson(lid, today)
    live = db.get_lesson(lid)
    assert not weekly.is_backlogged(live, today)
    assert [l["id"] for l in weekly.due_lessons([live], today)] == [lid]
