"""End-to-end: taking the in-app quiz actually persists an attempt with
per-question detail, and pages/16_Quizzes.py surfaces it.

Drives the real quiz form (radio picks, form submit) through Streamlit's
AppTest rather than calling compass.agents.quiz.grade directly -- that part
is already covered in test_quiz.py in isolation. What's new and worth
covering end-to-end is the wiring in compass.ui.render_quiz that turns a
submitted form into the `detail` list compass.storage.db.record_quiz_result
now persists, and that the Quizzes page reads it back correctly.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st
from streamlit.testing.v1 import AppTest

from compass import auth, config
from compass.storage.db import Database
from tests.conftest import correct_pick, wrong_pick

REPO_ROOT = Path(__file__).resolve().parent.parent
HOME_PATH = str(REPO_ROOT / "Home.py")
MATH_PATH = str(REPO_ROOT / "pages" / "1_Math.py")
QUIZZES_PATH = str(REPO_ROOT / "pages" / "16_Quizzes.py")


def _quiz_payload(**overrides):
    payload = {
        "title": "Two-Step Equations",
        "overview": "Undo the addition, then the multiplication.",
        "learning_objectives": ["Solve for x"],
        "activities": [],
        "materials": [],
        "assessment": {"kind": "check", "description": "", "mastery_criteria": ""},
        "subject_credits": [],
        "estimated_minutes": 30,
        "parent_notes": "",
        "branches": [],
        "quiz": [
            {
                "question": "What is 2 + 2?",
                "choices": ["3", "4", "5", "6"],
                "correct_index": 1,
                "explanation": "2 + 2 = 4.",
            },
            {
                "question": "What is 3 + 3?",
                "choices": ["5", "6", "7", "8"],
                "correct_index": 1,
                "explanation": "3 + 3 = 6.",
            },
        ],
    }
    payload.update(overrides)
    return payload


def _open(monkeypatch, db_path, page_path, *, as_parent):
    # get_db() is @st.cache_resource -- see tests/test_activity_log_page.py's
    # own note on why this must be cleared before pointing a fresh AppTest at
    # a different tmp_path database.
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


def test_submitting_the_quiz_persists_an_attempt_with_per_question_detail(
    monkeypatch, tmp_path
):
    db_path = tmp_path / "quiz.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    auth.set_pin(db, "1234")  # a PIN is what makes is_parent() default False
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="math", subject="math", topic="t",
        title="Two-Step Equations", payload=_quiz_payload(),
    )
    db.close()

    at = _open(monkeypatch, db_path, MATH_PATH, as_parent=False)
    pool = _quiz_payload()["quiz"]
    right_0 = correct_pick(pool, lesson_id, 0)
    at.radio(key=f"quiz_pick_{lesson_id}_0").set_value(right_0)
    at.radio(key=f"quiz_pick_{lesson_id}_1").set_value(wrong_pick(pool, lesson_id, 1))
    at.button(key=f"FormSubmitter:quiz_form_{lesson_id}-Submit quiz").click().run()
    assert not at.exception, [e.message for e in at.exception]

    db2 = Database(db_path)
    attempts = db2.list_quiz_attempts(student["id"])
    db2.close()

    assert len(attempts) == 1
    attempt = attempts[0]
    assert (attempt["correct"], attempt["total"]) == (1, 2)
    assert attempt["passed"] is False
    assert attempt["detail"][0]["pick"] == attempt["detail"][0]["correct_index"]
    assert attempt["detail"][1]["pick"] != attempt["detail"][1]["correct_index"]


def test_retaking_the_quiz_adds_a_second_attempt_not_a_replacement(monkeypatch, tmp_path):
    db_path = tmp_path / "quiz.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    auth.set_pin(db, "1234")
    db.set_setting("quiz_retry_cooldown_seconds", "0")  # retry-mechanics test, not the cooldown
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="math", subject="math", topic="t",
        title="Two-Step Equations", payload=_quiz_payload(),
    )
    db.close()

    at = _open(monkeypatch, db_path, MATH_PATH, as_parent=False)
    pool = _quiz_payload()["quiz"]
    at.radio(key=f"quiz_pick_{lesson_id}_0").set_value(wrong_pick(pool, lesson_id, 0))
    at.radio(key=f"quiz_pick_{lesson_id}_1").set_value(wrong_pick(pool, lesson_id, 1))
    at.button(key=f"FormSubmitter:quiz_form_{lesson_id}-Submit quiz").click().run()

    at.button(key=f"quiz_retry_{lesson_id}").click().run()
    # Attempt 1, not 0 -- the retry rotates to a different deal.
    at.radio(key=f"quiz_pick_{lesson_id}_0").set_value(
        correct_pick(pool, lesson_id, 0, attempt=1)
    )
    at.radio(key=f"quiz_pick_{lesson_id}_1").set_value(
        correct_pick(pool, lesson_id, 1, attempt=1)
    )
    at.button(key=f"FormSubmitter:quiz_form_{lesson_id}-Submit quiz").click().run()
    assert not at.exception, [e.message for e in at.exception]

    db2 = Database(db_path)
    attempts = db2.list_quiz_attempts(student["id"])
    db2.close()

    assert [a["correct"] for a in sorted(attempts, key=lambda a: a["id"])] == [0, 2]


def test_quizzes_page_shows_attempt_count_and_score_trend(monkeypatch, tmp_path):
    db_path = tmp_path / "quiz.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="math", subject="math", topic="t",
        title="Two-Step Equations", payload=_quiz_payload(),
    )
    db.record_quiz_result(lesson_id, student["id"], correct=1, total=2, passed=False)
    db.record_quiz_result(lesson_id, student["id"], correct=2, total=2, passed=True)
    db.close()

    at = _open(monkeypatch, db_path, QUIZZES_PATH, as_parent=True)

    text = " ".join(m.value for m in at.markdown) + " ".join(c.value for c in at.caption)
    assert "2 attempts" in text
    assert "1/2 → 2/2" in text


def test_quizzes_page_marks_wrong_answers_in_the_expanded_attempt(monkeypatch, tmp_path):
    db_path = tmp_path / "quiz.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="math", subject="math", topic="t",
        title="Two-Step Equations", payload=_quiz_payload(),
    )
    db.record_quiz_result(
        lesson_id, student["id"], correct=1, total=2, passed=False,
        detail=[
            {"question": "What is 2 + 2?", "choices": ["3", "4", "5", "6"],
             "correct_index": 1, "pick": 1, "explanation": "2 + 2 = 4."},
            {"question": "What is 3 + 3?", "choices": ["5", "6", "7", "8"],
             "correct_index": 1, "pick": 0, "explanation": "3 + 3 = 6."},
        ],
    )
    db.close()

    at = _open(monkeypatch, db_path, QUIZZES_PATH, as_parent=True)

    expander_labels = [e.label for e in at.expander]
    assert any("did not pass" in l for l in expander_labels)
    attempt_expander = next(e for e in at.expander if "did not pass" in e.label)
    body_text = " ".join(m.value for m in attempt_expander.markdown)
    assert "✅" in body_text and "What is 2 + 2?" in body_text
    assert "❌" in body_text and "What is 3 + 3?" in body_text
    caption_text = " ".join(c.value for c in attempt_expander.caption)
    assert "correct answer" not in body_text or "his answer" in body_text


def test_quizzes_page_filters_by_subject(monkeypatch, tmp_path):
    db_path = tmp_path / "quiz.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    math_lesson = db.save_lesson(
        student_id=student["id"], agent="math", subject="math", topic="t",
        title="Math Quiz Lesson", payload=_quiz_payload(),
    )
    science_lesson = db.save_lesson(
        student_id=student["id"], agent="science", subject="science", topic="t",
        title="Science Quiz Lesson", payload=_quiz_payload(title="Science Quiz Lesson"),
    )
    db.record_quiz_result(math_lesson, student["id"], correct=2, total=2, passed=True)
    db.record_quiz_result(science_lesson, student["id"], correct=2, total=2, passed=True)
    db.close()

    at = _open(monkeypatch, db_path, QUIZZES_PATH, as_parent=True)
    text = " ".join(m.value for m in at.markdown)
    assert "Math Quiz Lesson" in text and "Science Quiz Lesson" in text

    multiselect = [m for m in at.multiselect if m.label == "Filter by subject"][0]
    multiselect.set_value(["math"]).run()

    text = " ".join(m.value for m in at.markdown)
    assert "Math Quiz Lesson" in text
    assert "Science Quiz Lesson" not in text


def test_quizzes_page_shows_empty_state_with_no_attempts(monkeypatch, tmp_path):
    db_path = tmp_path / "quiz.db"
    Database(db_path).close()

    at = _open(monkeypatch, db_path, QUIZZES_PATH, as_parent=True)
    assert any("No quizzes taken yet" in i.value for i in at.info)


def _twenty_question_payload():
    return {
        "title": "Two-Step Equations", "overview": "", "activities": [], "materials": [],
        "assessment": {"kind": "check", "description": "", "mastery_criteria": ""},
        "subject_credits": [], "estimated_minutes": 30, "parent_notes": "", "branches": [],
        "quiz": [
            {"question": f"Question number {i}?",
             "choices": [f"a{i}", f"b{i}", f"c{i}", f"d{i}"],
             "correct_index": i % 4, "explanation": ""}
            for i in range(20)
        ],
    }


def _questions_on_screen(at):
    return {m.value for m in at.markdown if "Question number" in m.value}


def test_retaking_deals_a_different_set_of_questions(monkeypatch, tmp_path):
    """End to end: he answers five, retries, and gets five he hasn't seen --
    the reason the lesson carries a pool of 20 rather than just five."""
    db_path = tmp_path / "rotate.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    auth.set_pin(db, "1234")
    db.set_setting("quiz_retry_cooldown_seconds", "0")  # rotation test, not the cooldown
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="math", subject="math", topic="t",
        title="Two-Step Equations", payload=_twenty_question_payload(),
    )
    db.close()

    at = _open(monkeypatch, db_path, MATH_PATH, as_parent=False)
    first_round = _questions_on_screen(at)
    assert len(first_round) == 5

    for index in range(5):
        at.radio(key=f"quiz_pick_{lesson_id}_{index}").set_value(0)
    at.button(key=f"FormSubmitter:quiz_form_{lesson_id}-Submit quiz").click().run()
    at.button(key=f"quiz_retry_{lesson_id}").click().run()
    assert not at.exception, [e.message for e in at.exception]

    second_round = _questions_on_screen(at)
    assert len(second_round) == 5
    assert not (first_round & second_round), "a retry re-showed a question"


def test_the_asked_set_survives_answering_without_reshuffling(monkeypatch, tmp_path):
    """render_quiz re-runs on every widget interaction. If the deal weren't
    pinned, picking an answer would silently swap the questions underneath
    him mid-quiz."""
    db_path = tmp_path / "stable.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    auth.set_pin(db, "1234")
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="math", subject="math", topic="t",
        title="Two-Step Equations", payload=_twenty_question_payload(),
    )
    db.close()

    at = _open(monkeypatch, db_path, MATH_PATH, as_parent=False)
    before = _questions_on_screen(at)
    at.radio(key=f"quiz_pick_{lesson_id}_0").set_value(0).run()
    at.radio(key=f"quiz_pick_{lesson_id}_1").set_value(1).run()
    assert _questions_on_screen(at) == before
