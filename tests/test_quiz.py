"""Verifying and grading the in-app multiple-choice quiz.

Two things this module has to get right in isolation, before any Streamlit
form is involved: a malformed question from the model (wrong choice count, an
out-of-range `correct_index`) must be dropped rather than silently break
grading, and the grading/pass-threshold math has to be exactly right, since a
false "passed" auto-records mastery on the Math skill graph.
"""

from __future__ import annotations

import pytest

from compass.agents.quiz import CHOICE_COUNT, grade, passed, verify_quiz
from compass.storage.db import Database


def a_question(**overrides):
    question = {
        "question": "What is 2 + 2?",
        "choices": ["3", "4", "5", "6"],
        "correct_index": 1,
        "explanation": "2 + 2 = 4.",
    }
    question.update(overrides)
    return question


def verify(quiz):
    payload = {"quiz": quiz}
    warnings = verify_quiz(payload)
    return warnings, payload["quiz"]


# --- verify_quiz: well-formed questions survive --------------------------------


def test_a_well_formed_question_is_kept():
    warnings, quiz = verify([a_question()])
    assert not warnings
    assert quiz == [a_question()]


def test_choice_and_question_text_is_stripped():
    warnings, quiz = verify(
        [a_question(question="  What is 2 + 2?  ", choices=["3", " 4 ", "5", "6"])]
    )
    assert quiz[0]["question"] == "What is 2 + 2?"
    assert quiz[0]["choices"][1] == "4"


# --- verify_quiz: malformed questions are dropped, not half-kept ---------------


def test_wrong_choice_count_is_dropped():
    warnings, quiz = verify([a_question(choices=["3", "4", "5"])])
    assert quiz == []
    assert any("malformed" in w for w in warnings)


def test_out_of_range_correct_index_is_dropped():
    warnings, quiz = verify([a_question(correct_index=CHOICE_COUNT)])
    assert quiz == []
    assert any("malformed" in w for w in warnings)


def test_negative_correct_index_is_dropped():
    warnings, quiz = verify([a_question(correct_index=-1)])
    assert quiz == []


def test_a_bool_correct_index_is_dropped():
    """`bool` is a subclass of `int` in Python -- `True`/`False` must not sneak
    through as 1/0 just because `isinstance(x, int)` alone would accept them."""
    warnings, quiz = verify([a_question(correct_index=True)])
    assert quiz == []


def test_an_empty_choice_is_dropped():
    warnings, quiz = verify([a_question(choices=["3", "", "5", "6"])])
    assert quiz == []


def test_a_blank_question_is_dropped():
    warnings, quiz = verify([a_question(question="   ")])
    assert quiz == []


def test_one_bad_question_does_not_take_down_the_rest():
    good = a_question()
    bad = a_question(question="Broken", correct_index=99)
    warnings, quiz = verify([good, bad])
    assert len(quiz) == 1
    assert quiz[0]["question"] == "What is 2 + 2?"
    assert any("Broken" in w for w in warnings)


def test_a_missing_quiz_key_becomes_an_empty_list():
    payload = {}
    warnings = verify_quiz(payload)
    assert payload["quiz"] == []
    assert warnings == []


def test_a_non_list_quiz_becomes_an_empty_list():
    payload = {"quiz": "not a list"}
    verify_quiz(payload)
    assert payload["quiz"] == []


# --- grading --------------------------------------------------------------------


def test_grade_counts_correct_picks():
    quiz = [a_question(correct_index=1), a_question(correct_index=0)]
    correct, total = grade(quiz, [1, 0])
    assert (correct, total) == (2, 2)


def test_grade_counts_wrong_picks_as_wrong():
    quiz = [a_question(correct_index=1), a_question(correct_index=0)]
    correct, total = grade(quiz, [1, 1])
    assert (correct, total) == (1, 2)


def test_grade_treats_an_unanswered_question_as_wrong_not_a_crash():
    quiz = [a_question(correct_index=1)]
    correct, total = grade(quiz, [None])
    assert (correct, total) == (0, 1)


# --- pass threshold ---------------------------------------------------------------


def test_passing_exactly_at_the_threshold_counts():
    assert passed(4, 5, 80)


def test_just_under_the_threshold_does_not_count():
    assert not passed(3, 5, 80)


def test_an_empty_quiz_never_passes():
    assert not passed(0, 0, 80)


# --- persisting a graded result ---------------------------------------------------


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    yield database
    database.close()


def test_record_quiz_result_is_readable_back_from_lesson_metadata(db):
    student = db.ensure_default_student()
    lesson_id = db.save_lesson(
        student_id=student["id"],
        agent="math",
        subject="math",
        topic="t",
        title="t",
        payload={},
        metadata={"skill_id": "two-step-equations"},
    )
    db.record_quiz_result(lesson_id, student["id"], correct=4, total=5, passed=True)

    lesson = db.get_lesson(lesson_id)
    assert lesson["metadata"]["quiz_result"] == {
        "correct": 4,
        "total": 5,
        "passed": True,
        "graded_on": lesson["metadata"]["quiz_result"]["graded_on"],
    }
    # the strategy metadata that was already there must survive the merge
    assert lesson["metadata"]["skill_id"] == "two-step-equations"


# --- quiz attempt history ---------------------------------------------------------


def _lesson(db, student_id):
    return db.save_lesson(
        student_id=student_id, agent="math", subject="math", topic="t",
        title="Two-Step Equations", payload={},
    )


def test_each_recorded_attempt_gets_its_own_row(db):
    student = db.ensure_default_student()
    lesson_id = _lesson(db, student["id"])

    db.record_quiz_result(lesson_id, student["id"], correct=3, total=5, passed=False)
    db.record_quiz_result(lesson_id, student["id"], correct=5, total=5, passed=True)

    attempts = db.list_quiz_attempts(student["id"])
    assert len(attempts) == 2
    assert {a["correct"] for a in attempts} == {3, 5}


def test_list_quiz_attempts_is_newest_first(db):
    student = db.ensure_default_student()
    lesson_id = _lesson(db, student["id"])

    db.record_quiz_result(lesson_id, student["id"], correct=1, total=5, passed=False)
    db.record_quiz_result(lesson_id, student["id"], correct=4, total=5, passed=True)

    attempts = db.list_quiz_attempts(student["id"])
    assert [a["correct"] for a in attempts] == [4, 1]


def test_list_quiz_attempts_can_be_narrowed_to_one_lesson(db):
    student = db.ensure_default_student()
    lesson_a = _lesson(db, student["id"])
    lesson_b = _lesson(db, student["id"])
    db.record_quiz_result(lesson_a, student["id"], correct=1, total=5, passed=False)
    db.record_quiz_result(lesson_b, student["id"], correct=5, total=5, passed=True)

    attempts = db.list_quiz_attempts(student["id"], lesson_id=lesson_a)
    assert len(attempts) == 1
    assert attempts[0]["lesson_id"] == lesson_a


def test_quiz_attempt_carries_which_lesson_it_was_for(db):
    student = db.ensure_default_student()
    lesson_id = _lesson(db, student["id"])
    db.record_quiz_result(lesson_id, student["id"], correct=3, total=5, passed=False)

    attempt = db.list_quiz_attempts(student["id"])[0]
    assert attempt["lesson_title"] == "Two-Step Equations"
    assert attempt["subject"] == "math"


def test_per_question_detail_round_trips(db):
    student = db.ensure_default_student()
    lesson_id = _lesson(db, student["id"])
    detail = [
        {
            "question": "What is 2 + 2?",
            "choices": ["3", "4", "5", "6"],
            "correct_index": 1,
            "pick": 0,
            "explanation": "2 + 2 = 4.",
        }
    ]
    db.record_quiz_result(lesson_id, student["id"], correct=0, total=1, passed=False, detail=detail)

    attempt = db.list_quiz_attempts(student["id"])[0]
    assert attempt["detail"] == detail


def test_an_attempt_recorded_without_detail_defaults_to_an_empty_list(db):
    student = db.ensure_default_student()
    lesson_id = _lesson(db, student["id"])
    db.record_quiz_result(lesson_id, student["id"], correct=1, total=1, passed=True)

    attempt = db.list_quiz_attempts(student["id"])[0]
    assert attempt["detail"] == []


def test_passed_comes_back_as_a_real_bool(db):
    student = db.ensure_default_student()
    lesson_id = _lesson(db, student["id"])
    db.record_quiz_result(lesson_id, student["id"], correct=5, total=5, passed=True)

    attempt = db.list_quiz_attempts(student["id"])[0]
    assert attempt["passed"] is True


def test_duration_seconds_round_trips(db):
    student = db.ensure_default_student()
    lesson_id = _lesson(db, student["id"])
    db.record_quiz_result(
        lesson_id, student["id"], correct=5, total=5, passed=True, duration_seconds=252
    )

    attempt = db.list_quiz_attempts(student["id"])[0]
    assert attempt["duration_seconds"] == 252


def test_duration_seconds_defaults_to_none_when_not_given(db):
    student = db.ensure_default_student()
    lesson_id = _lesson(db, student["id"])
    db.record_quiz_result(lesson_id, student["id"], correct=5, total=5, passed=True)

    attempt = db.list_quiz_attempts(student["id"])[0]
    assert attempt["duration_seconds"] is None
