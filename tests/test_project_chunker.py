"""AI-drafted step-by-step plan for a Big Project.

Mirrors test_course_summary.py's approach: the interesting behaviour is the
boundary (never reaches the student's Home page, always gets costed) and
what the prompt says, not the model's actual prose. `generate_project_steps`
itself doesn't insert anything -- it hands back plain dicts shaped like
`Database.add_project_step`'s own parameters, and the page inserts them --
so these tests stop at that returned list.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from compass.agents import project_chunker
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
def project(db, student):
    project_id = db.add_big_project(
        student["id"], "Backyard Weather Station",
        vision="Build and run a real weather station, then track and share the data.",
    )
    return {"id": project_id, "title": "Backyard Weather Station",
            "vision": "Build and run a real weather station, then track and share the data."}


def a_step(**overrides):
    step = {
        "title": "Pick your instruments",
        "description": "Decide what you'll measure and with what.",
        "materials": "thermometer, notebook",
        "credit_subject": "science",
        "min_days": 1,
        "max_days": 2,
    }
    step.update(overrides)
    return step


def a_plan_payload(steps=None, **overrides):
    payload = {"steps": steps if steps is not None else [a_step()], "_usage": {"input_tokens": 10, "output_tokens": 20}}
    payload.update(overrides)
    return payload


def generate(db, student, project, payload):
    with patch("compass.agents.project_chunker.generate_lesson", return_value=payload) as call:
        steps = project_chunker.generate_project_steps(db, student, project)
    return steps, call


# --- the draft itself ------------------------------------------------------------


def test_generate_project_steps_returns_the_step_fields(db, student, project):
    steps, _ = generate(db, student, project, a_plan_payload())
    assert steps == [
        {
            "title": "Pick your instruments",
            "description": "Decide what you'll measure and with what.",
            "materials": "thermometer, notebook",
            "credit_subject": "science",
            "min_days": 1,
            "max_days": 2,
        }
    ]


def test_preserves_step_order(db, student, project):
    steps, _ = generate(
        db, student, project,
        a_plan_payload(steps=[a_step(title="First"), a_step(title="Second"), a_step(title="Third")]),
    )
    assert [s["title"] for s in steps] == ["First", "Second", "Third"]


def test_a_step_with_no_title_is_dropped(db, student, project):
    """A malformed entry shouldn't become a blank, meaningless step row."""
    steps, _ = generate(
        db, student, project,
        a_plan_payload(steps=[a_step(title="Real step"), a_step(title="")]),
    )
    assert [s["title"] for s in steps] == ["Real step"]


def test_missing_optional_fields_default_sensibly(db, student, project):
    minimal = {"title": "Bare step"}
    steps, _ = generate(db, student, project, a_plan_payload(steps=[minimal]))
    assert steps == [
        {
            "title": "Bare step",
            "description": "",
            "materials": "",
            "credit_subject": "occupational_education",
            "min_days": 1,
            "max_days": 1,
        }
    ]


def test_no_steps_at_all_returns_an_empty_list(db, student, project):
    steps, _ = generate(db, student, project, a_plan_payload(steps=[]))
    assert steps == []


# --- persistence / cost tracking --------------------------------------------------


def test_the_draft_call_is_stored_and_costed(db, student, project):
    generate(db, student, project, a_plan_payload())
    start, end = db.school_year_bounds()
    usage = db.lesson_usage_between(student["id"], start, end)
    assert [u["agent"] for u in usage] == [project_chunker.AGENT_KEY]


def test_the_draft_call_never_reaches_the_students_home_page(db, student, project):
    """Parent paperwork -- the same boundary course_summary's own call gets,
    for the same reason: nothing here is a lesson he should ever see listed
    as 'ready for you'. Home's roster only ever queries by the four core
    agent keys, so this agent key alone already keeps it off -- this test
    just pins that down."""
    generate(db, student, project, a_plan_payload())
    lessons = db.list_lessons(student["id"], limit=25)
    visible = [l for l in lessons if l["agent"] != project_chunker.AGENT_KEY]
    assert lessons and not visible


# --- prompt content ----------------------------------------------------------------


def test_prompt_names_the_project_title_and_vision(db, student, project):
    _, call = generate(db, student, project, a_plan_payload())
    system = call.call_args.kwargs["system"]
    assert "Backyard Weather Station" in system
    assert "Build and run a real weather station" in system


def test_prompt_falls_back_when_vision_is_blank(db, student, project):
    blank_vision = {**project, "vision": ""}
    _, call = generate(db, student, blank_vision, a_plan_payload())
    system = call.call_args.kwargs["system"]
    assert "infer a reasonable one from the title" in system


def test_prompt_names_the_students_grade(db, student, project):
    _, call = generate(db, student, project, a_plan_payload())
    system = call.call_args.kwargs["system"]
    assert f"grade {student['grade']}" in system
