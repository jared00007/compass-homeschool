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


def test_series_lessons_have_no_planned_for_date(db, student):
    """The whole point of the change: no day is pinned to a calendar date --
    they just queue in order."""
    agent = get_agent("math")
    proposal = TopicProposal(topic="Pythagorean Theorem", rationale="r", strategy="graph_walk")
    with patch("compass.agents.series.plan_lesson_series", return_value=THREE_DAYS), patch(
        "compass.agents.framework.generate_lesson", side_effect=lambda **k: a_payload()
    ):
        results = agent.generate_series(ctx_for(db, student), proposal)
    for r in results:
        assert "planned_for" not in db.get_lesson(r.lesson_id)["metadata"]


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


def test_the_math_plan_button_generates_a_whole_series(monkeypatch, tmp_path):
    """The subject page's one click: pick a topic, hit Generate the full series,
    and the whole topic lands as ordered dateless lessons queued for him."""
    from pathlib import Path

    import streamlit as st
    from streamlit.testing.v1 import AppTest

    from compass import config as cfg

    db_path = tmp_path / "series_page.db"
    d = Database(db_path)
    s = d.ensure_default_student()
    d.close()

    st.cache_resource.clear()
    monkeypatch.setattr(cfg, "DEFAULT_DB_PATH", db_path)
    repo = Path(__file__).resolve().parent.parent

    at = AppTest.from_file(str(repo / "Home.py"))
    at.session_state["parent_unlocked"] = True
    at.run(timeout=60)
    at.switch_page(str(repo / "pages" / "1_Math.py"))
    at.run(timeout=60)

    plan = [{"title": "Day A", "focus": "focus a"}, {"title": "Day B", "focus": "focus b"}]
    with patch("compass.agents.series.plan_lesson_series", return_value=plan), patch(
        "compass.agents.framework.generate_lesson", side_effect=lambda **k: a_payload()
    ):
        button = [b for b in at.button if (b.key or "") == "math_gen_series"][0]
        button.click().run(timeout=60)
    assert not at.exception, [e.message for e in at.exception]

    d = Database(db_path)
    lessons = d.list_lessons(s["id"], agent="math", limit=10)
    d.close()
    assert len(lessons) == 2
    assert sorted(l["metadata"]["series_index"] for l in lessons) == [0, 1]
    assert not any("planned_for" in (l["metadata"] or {}) for l in lessons)


def test_due_lessons_walks_a_series_in_index_order(db, student):
    """Even if a later day has a lower id (or the list comes back in any order),
    the student sees day 1 first, then day 2 -- ordered by series_index."""
    from compass import weekly

    day2 = db.save_lesson(
        student_id=student["id"], agent="math", subject="math", topic="t",
        title="Day 2", payload={"title": "Day 2", "activities": []},
        metadata={"series_id": "s1", "series_index": 1, "series_total": 2},
    )
    day1 = db.save_lesson(
        student_id=student["id"], agent="math", subject="math", topic="t",
        title="Day 1", payload={"title": "Day 1", "activities": []},
        metadata={"series_id": "s1", "series_index": 0, "series_total": 2},
    )
    lessons = db.list_lessons(student["id"], agent="math", limit=10)
    due = weekly.due_lessons(lessons, "2026-09-05")
    assert [l["title"] for l in due] == ["Day 1", "Day 2"]
    assert due[0]["id"] == day1 and due[1]["id"] == day2
