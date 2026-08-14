"""AI-drafted course description, goals, and outline.

Mirrors `test_life_skills.py`'s approach: the interesting behaviour is the
boundary (never reaches the student's Home page, always gets costed) and
which of the two prompt branches (nothing taught yet vs. real coverage) gets
built, not the model's actual prose.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from compass.agents import course_summary
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
def course(db, student):
    course_id = db.create_course(
        student["id"], "Washington State History", "history", "2025-09-01", "2026-08-31",
        grade_level="8",
    )
    return db.get_course(course_id)


def a_summary_payload(**overrides):
    payload = {
        "description": "A survey of Washington state history from indigenous peoples through statehood.",
        "goals": "Understand the tribal, territorial, and statehood eras of Washington.",
        "outline": "Unit 1: Indigenous peoples. Unit 2: Territorial era. Unit 3: Statehood.",
        "_usage": {"input_tokens": 10, "output_tokens": 20},
    }
    payload.update(overrides)
    return payload


def generate(db, student, course, taught, payload):
    with patch("compass.agents.course_summary.generate_lesson", return_value=payload) as call:
        summary = course_summary.generate_course_summary(db, student, course, taught)
    return summary, call


# --- the draft itself ----------------------------------------------------------


def test_generate_course_summary_returns_the_three_fields(db, student, course):
    summary, _ = generate(db, student, course, [], a_summary_payload())
    assert summary["description"].startswith("A survey of Washington")
    assert summary["goals"].startswith("Understand the tribal")
    assert summary["outline"].startswith("Unit 1")


def test_missing_fields_default_to_empty_strings(db, student, course):
    summary, _ = generate(db, student, course, [], {"_usage": {}})
    assert summary == {"description": "", "goals": "", "outline": ""}


# --- persistence / cost tracking ------------------------------------------------


def test_a_summary_is_stored_and_costed(db, student, course):
    generate(db, student, course, [], a_summary_payload())
    start, end = db.school_year_bounds()
    usage = db.lesson_usage_between(student["id"], start, end)
    assert [u["agent"] for u in usage] == [course_summary.AGENT_KEY], "drafts must show on the bill"


def test_summaries_do_not_reach_the_students_home_page(db, student, course):
    """Course documentation is parent paperwork -- the same boundary
    life_skills plans get, and for the same reason: nothing here is a lesson
    he should ever see listed as 'ready for you'."""
    generate(db, student, course, [], a_summary_payload())
    lessons = db.list_lessons(student["id"], limit=25)
    visible = [l for l in lessons if l["agent"] != course_summary.AGENT_KEY]
    assert lessons and not visible


# --- prompt branches -------------------------------------------------------------


def test_no_coverage_prompt_when_nothing_taught_yet(db, student, course):
    _, call = generate(db, student, course, [], a_summary_payload())
    system = call.call_args.kwargs["system"]
    assert "Nothing has been taught under this course yet" in system
    assert "1-credit History course" in system


def test_coverage_prompt_lists_what_was_taught(db, student, course):
    taught = [
        {"title": "Indigenous Peoples of the Puget Sound", "objectives": ["Identify three tribes"]},
        {"title": "Washington Territorial Government", "objectives": []},
    ]
    _, call = generate(db, student, course, taught, a_summary_payload())
    system = call.call_args.kwargs["system"]
    assert "What's actually been taught so far" in system
    assert "Indigenous Peoples of the Puget Sound -- Identify three tribes" in system
    assert "Washington Territorial Government -- no objectives recorded" in system
    assert "Nothing has been taught" not in system


def test_credit_value_scales_the_target_hours_in_the_prompt(db, student):
    db_id = db.create_course(
        student["id"], "Half-Credit Elective", "art_and_music", "2025-09-01", "2026-01-31",
        grade_level="9", credit_value=0.5,
    )
    half_course = db.get_course(db_id)
    _, call = generate(db, student, half_course, [], a_summary_payload())
    system = call.call_args.kwargs["system"]
    assert "0.5-credit art_and_music" in system or "75" in system


def test_prompt_names_the_course_title_subject_and_grade(db, student, course):
    _, call = generate(db, student, course, [], a_summary_payload())
    system = call.call_args.kwargs["system"]
    assert "Washington State History" in system
    assert "History" in system
    assert "Grade level: 8" in system
