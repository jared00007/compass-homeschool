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
    db.record_quiz_result(lesson_id, correct=4, total=5, passed=True)

    lesson = db.get_lesson(lesson_id)
    assert lesson["metadata"]["quiz_result"] == {
        "correct": 4,
        "total": 5,
        "passed": True,
        "graded_on": lesson["metadata"]["quiz_result"]["graded_on"],
    }
    # the strategy metadata that was already there must survive the merge
    assert lesson["metadata"]["skill_id"] == "two-step-equations"
