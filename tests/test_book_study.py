"""Book study -- the structured book report and the AI comprehension quiz.

The report is a fixed, teachable scaffold (no model call, free), assigned as an
ordinary lesson so it rides the writing + parent-review pipeline. The quiz IS a
model call, auto-graded like any lesson quiz. Covered here: what each one
persists, that the report costs nothing while the quiz is billed, and -- end to
end on Home -- that taking the quiz auto-completes without a parent step while
the report turns itself in for review.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from compass import auth, config, costs
from compass.agents import book_study
from compass.agents.quiz import QUESTIONS_PER_ATTEMPT
from compass.storage.db import Database
from tests.conftest import correct_pick

REPO_ROOT = Path(__file__).resolve().parent.parent
HOME_PATH = str(REPO_ROOT / "Home.py")
ENGLISH_PATH = str(REPO_ROOT / "pages" / "3_English.py")


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "book.db")
    yield database
    database.close()


@pytest.fixture()
def student(db):
    return db.ensure_default_student()


@pytest.fixture()
def book(db, student):
    db.add_book(student["id"], "The Hobbit", "J.R.R. Tolkien", total_pages=300)
    return db.current_book(student["id"])


def a_quiz_payload(n=14, **overrides):
    payload = {
        "overview": "How well did you follow the story?",
        "quiz": [
            {
                "question": f"Question {i}?",
                "choices": ["a", "b", "c", "d"],
                "correct_index": 0,
                "explanation": "Because a.",
            }
            for i in range(n)
        ],
        "_usage": {"input_tokens": 5, "output_tokens": 7, "model": "claude-opus-5"},
    }
    payload.update(overrides)
    return payload


# --- the report: a fixed scaffold, free ----------------------------------------


def test_build_book_report_persists_a_writing_assignment(db, student, book):
    lesson_id = book_study.build_book_report(db, student, book)
    report = db.get_lesson(lesson_id)

    assert report["agent"] == book_study.AGENT_KEY_REPORT
    assert report["status"] == "planned"
    assert report["metadata"]["book_id"] == book["id"]
    activities = report["payload"]["activities"]
    assert len(activities) == len(book_study.REPORT_SECTIONS)
    # Every section is a written response, so it rides the writing pipeline and
    # auto-submits for parent grading once he's filled them in.
    assert all(a["requires_written_response"] for a in activities)
    assert "The Hobbit" in report["title"]


def test_a_book_report_is_free_on_the_costs_page(db, student, book):
    book_study.build_book_report(db, student, book)
    start, end = db.school_year_bounds()
    report = costs.build_cost_report(db, student["id"], start, end)
    # Priced (not lumped in with legacy un-tracked lessons), and priced at $0 --
    # there was no API call.
    assert report.total_cost == 0.0
    assert report.unmeasured_lessons == 0
    assert any(a.agent == book_study.AGENT_KEY_REPORT and a.cost == 0.0 for a in report.by_agent)


# --- the quiz: an AI generation, auto-graded -----------------------------------


def test_generate_book_quiz_persists_and_is_costed(db, student, book):
    with patch("compass.agents.book_study.generate_lesson", return_value=a_quiz_payload()):
        lesson_id = book_study.generate_book_quiz(db, student, book)
    quiz = db.get_lesson(lesson_id)

    assert quiz["agent"] == book_study.AGENT_KEY_QUIZ
    assert quiz["subject"] == "reading"
    assert quiz["metadata"]["book_id"] == book["id"]
    assert len(quiz["payload"]["quiz"]) == 14

    start, end = db.school_year_bounds()
    usage = db.lesson_usage_between(student["id"], start, end)
    assert book_study.AGENT_KEY_QUIZ in {u["agent"] for u in usage}


def test_generate_book_quiz_drops_a_malformed_question(db, student, book):
    payload = a_quiz_payload(n=3)
    payload["quiz"].append(
        {"question": "broken", "choices": ["a", "b"], "correct_index": 9, "explanation": ""}
    )
    with patch("compass.agents.book_study.generate_lesson", return_value=payload):
        lesson_id = book_study.generate_book_quiz(db, student, book)
    kept = db.get_lesson(lesson_id)["payload"]["quiz"]
    assert len(kept) == 3
    assert all(q["question"] != "broken" for q in kept)


# --- end to end on Home --------------------------------------------------------


def _open(monkeypatch, db_path, page_path, *, as_parent):
    st.cache_resource.clear()
    monkeypatch.setattr(config, "DEFAULT_DB_PATH", db_path)
    at = AppTest.from_file(HOME_PATH)
    if as_parent:
        at.session_state["parent_unlocked"] = True
    at.run(timeout=30)
    if page_path != HOME_PATH:
        at.switch_page(page_path)
        at.run(timeout=30)
    assert not at.exception, [e.message for e in at.exception]
    return at


def test_home_shows_a_book_report_card(monkeypatch, tmp_path):
    db_path = tmp_path / "book.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    auth.set_pin(db, "1234")
    db.add_book(student["id"], "The Hobbit", "J.R.R. Tolkien")
    book_study.build_book_report(db, student, db.current_book(student["id"]))
    db.close()

    at = _open(monkeypatch, db_path, HOME_PATH, as_parent=False)
    body = " ".join(m.value for m in at.markdown).lower()
    assert "book report" in body


def test_home_book_quiz_auto_completes_without_a_parent_step(monkeypatch, tmp_path):
    db_path = tmp_path / "book.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    auth.set_pin(db, "1234")
    db.add_book(student["id"], "The Hobbit", "J.R.R. Tolkien")
    with patch("compass.agents.book_study.generate_lesson", return_value=a_quiz_payload()):
        lesson_id = book_study.generate_book_quiz(db, student, db.current_book(student["id"]))
    db.close()

    at = _open(monkeypatch, db_path, HOME_PATH, as_parent=False)
    pool = a_quiz_payload()["quiz"]
    for i in range(QUESTIONS_PER_ATTEMPT):
        at.radio(key=f"quiz_pick_{lesson_id}_{i}").set_value(correct_pick(pool, lesson_id, i))
    at.button(key=f"FormSubmitter:quiz_form_{lesson_id}-Submit quiz").click().run()
    assert not at.exception, [e.message for e in at.exception]

    db2 = Database(db_path)
    quiz = db2.get_lesson(lesson_id)
    db2.close()
    # Auto-graded and self-completed, never routed to the parent review queue.
    assert quiz["status"] == "completed"
    assert quiz["status"] != "submitted"


def test_english_books_tab_can_assign_a_report_and_generate_a_quiz(monkeypatch, tmp_path):
    db_path = tmp_path / "book.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    db.add_book(student["id"], "The Hobbit", "J.R.R. Tolkien")
    book = db.current_book(student["id"])
    db.close()

    monkeypatch.setattr("compass.agents.api_available", lambda: (True, "Ready."))
    at = _open(monkeypatch, db_path, ENGLISH_PATH, as_parent=True)

    at.button(key=f"bookreport_{book['id']}").click().run()
    with patch("compass.agents.book_study.generate_lesson", return_value=a_quiz_payload()):
        at.button(key=f"bookquiz_{book['id']}").click().run()
    assert not at.exception, [e.message for e in at.exception]

    db2 = Database(db_path)
    agents = {l["agent"] for l in db2.list_lessons(student["id"], limit=50)}
    db2.close()
    assert book_study.AGENT_KEY_REPORT in agents
    assert book_study.AGENT_KEY_QUIZ in agents
