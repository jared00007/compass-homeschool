"""AI-drafted book introduction -- shown to him on the Books tab and (once
drafted) in the first-day "table of contents" preview.

Mirrors `test_course_summary.py`'s approach: pin the boundary (cached on the
row, costed, never reaches Home as a lesson) rather than the model's prose.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from compass.agents import book_summary
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
def book(db, student):
    book_id = db.add_book(student["id"], "Holes", author="Louis Sachar", status="reading")
    return _book_row(db, student["id"], book_id)


def _book_row(db, student_id, book_id):
    return next(b for b in db.list_books(student_id) if b["id"] == book_id)


def a_summary_payload(**overrides):
    payload = {
        "summary": "Stanley Digs holes at a brutal desert camp and slowly uncovers a decades-old mystery.",
        "_usage": {"input_tokens": 10, "output_tokens": 20},
    }
    payload.update(overrides)
    return payload


def generate(db, student, book, payload):
    with patch("compass.agents.book_summary.generate_lesson", return_value=payload) as call:
        summary = book_summary.generate_book_summary(db, student, book)
    return summary, call


def test_generate_book_summary_returns_the_drafted_text(db, student, book):
    summary, _ = generate(db, student, book, a_summary_payload())
    assert summary.startswith("Stanley Digs holes")


def test_missing_summary_field_defaults_to_empty_string(db, student, book):
    summary, _ = generate(db, student, book, {"_usage": {}})
    assert summary == ""


def test_a_blank_summary_is_not_cached_or_costed(db, student, book):
    generate(db, student, book, {"_usage": {}})
    refreshed = _book_row(db, student["id"], book["id"])
    assert refreshed["ai_summary"] == ""
    assert db.list_lessons(student["id"], limit=25) == []


def test_the_summary_is_cached_on_the_book_row(db, student, book):
    generate(db, student, book, a_summary_payload())
    refreshed = _book_row(db, student["id"], book["id"])
    assert refreshed["ai_summary"].startswith("Stanley Digs holes")


def test_a_summary_is_costed(db, student, book):
    generate(db, student, book, a_summary_payload())
    start, end = db.school_year_bounds()
    usage = db.lesson_usage_between(student["id"], start, end)
    assert [u["agent"] for u in usage] == [book_summary.AGENT_KEY], "drafts must show on the bill"


def test_summaries_do_not_reach_the_students_home_page(db, student, book):
    generate(db, student, book, a_summary_payload())
    lessons = db.list_lessons(student["id"], limit=25)
    visible = [l for l in lessons if l["agent"] != book_summary.AGENT_KEY]
    assert lessons and not visible


def test_prompt_names_the_title_and_author(db, student, book):
    _, call = generate(db, student, book, a_summary_payload())
    prompt = call.call_args.kwargs["user_prompt"]
    assert "Holes" in prompt
    assert "Louis Sachar" in prompt


def test_prompt_handles_a_book_with_no_author_on_file(db, student):
    book_id = db.add_book(student["id"], "Untitled Draft", status="reading")
    book = _book_row(db, student["id"], book_id)
    _, call = generate(db, student, book, a_summary_payload())
    prompt = call.call_args.kwargs["user_prompt"]
    assert "unknown" in prompt
