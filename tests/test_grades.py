"""Grades: the retry weighting, the component weighting, and what he sees.

Landon asked to be graded, which makes the *shape* of the rules the thing
worth testing rather than the arithmetic alone. Three properties matter
more than any particular number here, and each has its own test below:

  * a retry can never lower a grade (so there is never a reason to avoid
    trying again),
  * a component with nothing in it is dropped, never counted as a zero (so
    "hasn't written anything yet" can't read as "failed the writing"),
  * a subject he hasn't started shows as ungraded, never as an F.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from compass import auth, config, gradebook, grades
from compass.storage.db import Database

REPO_ROOT = Path(__file__).resolve().parent.parent
HOME_PATH = str(REPO_ROOT / "Home.py")

DEDUCTION = 10
FLOOR = 70
LIMIT = config.GRADED_QUIZ_ATTEMPTS


def attempt(correct: int, total: int = 5) -> dict[str, int]:
    return {"correct": correct, "total": total}


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "grades.db")
    yield database
    database.close()


@pytest.fixture()
def student(db):
    return db.ensure_default_student()


# --- the retry weighting --------------------------------------------------------


def test_the_first_attempt_always_counts_in_full():
    assert grades.attempt_multiplier(1, DEDUCTION, FLOOR) == 1.0


def test_each_retry_is_worth_less_down_to_the_floor():
    assert grades.attempt_multiplier(2, DEDUCTION, FLOOR) == 0.9
    assert grades.attempt_multiplier(3, DEDUCTION, FLOOR) == 0.8
    assert grades.attempt_multiplier(4, DEDUCTION, FLOOR) == 0.7
    # The floor holds rather than sliding toward zero.
    assert grades.attempt_multiplier(9, DEDUCTION, FLOOR) == 0.7


def test_a_perfect_first_try_banks_a_hundred():
    percent, used = grades.quiz_score([attempt(5)], DEDUCTION, FLOOR, LIMIT)
    assert (round(percent), used) == (100, 1)


def test_a_rough_first_try_then_a_perfect_retry_banks_ninety():
    percent, _ = grades.quiz_score([attempt(3), attempt(5)], DEDUCTION, FLOOR, LIMIT)
    assert round(percent) == 90


def test_a_careless_retry_can_never_lower_the_grade():
    """The single most important property here. Best-weighted, not latest --
    otherwise a bad day after a good score is a punishment for practicing."""
    percent, _ = grades.quiz_score([attempt(5), attempt(1)], DEDUCTION, FLOOR, LIMIT)
    assert round(percent) == 100


def test_a_strong_first_try_still_beats_a_perfect_fourth():
    """Where the incentive lives: 85% thought-about beats 100% ground out."""
    first_try = grades.quiz_score([attempt(17, 20)], DEDUCTION, FLOOR, LIMIT)[0]
    fourth = grades.quiz_score(
        [attempt(0), attempt(0), attempt(0), attempt(5)], DEDUCTION, FLOOR, LIMIT
    )[0]
    assert round(first_try) == 85
    assert round(fourth) == 70
    assert first_try > fourth


def test_attempts_past_the_limit_are_ignored_entirely():
    attempts = [attempt(0)] * LIMIT + [attempt(5)]
    percent, used = grades.quiz_score(attempts, DEDUCTION, FLOOR, LIMIT)
    assert used == LIMIT
    assert percent == 0


def test_an_unfinished_quiz_is_not_a_zero():
    percent, used = grades.quiz_score([{"correct": 0, "total": 0}], DEDUCTION, FLOOR, LIMIT)
    assert percent is None and used == 0


# --- whether another attempt is worth taking -------------------------------------


def test_a_fresh_quiz_can_always_improve():
    assert grades.can_improve([], DEDUCTION, FLOOR, LIMIT) is True


def test_a_banked_hundred_cannot_be_improved():
    assert grades.can_improve([attempt(5)], DEDUCTION, FLOOR, LIMIT) is False


def test_a_banked_ninety_five_cannot_be_improved():
    """A second attempt tops out at 90, so 95 is already out of reach."""
    assert grades.can_improve([attempt(19, 20)], DEDUCTION, FLOOR, LIMIT) is False


def test_a_banked_eighty_can_still_be_improved():
    assert grades.can_improve([attempt(4)], DEDUCTION, FLOOR, LIMIT) is True


def test_the_attempt_limit_ends_it_regardless_of_score():
    assert grades.can_improve([attempt(1)] * LIMIT, DEDUCTION, FLOOR, LIMIT) is False


# --- combining components into a subject grade ------------------------------------


WEIGHTS = {"quizzes": 40, "writing": 40, "reading": 20}


def _grade(**kwargs) -> grades.SubjectGrade:
    base = dict(
        quiz_percents=[], writing_percents=[], reading_percents=[],
        mastery_percent=None, assessment_percents=[],
    )
    base.update(kwargs)
    return grades.subject_grade("english", WEIGHTS, **base)


def test_components_combine_by_their_weights():
    result = _grade(
        quiz_percents=[100.0], writing_percents=[50.0], reading_percents=[100.0]
    )
    assert round(result.percent) == 80  # .4*100 + .4*50 + .2*100


def test_a_missing_component_redistributes_rather_than_scoring_zero():
    """The bug that would matter most: a kid two weeks into the year with
    no writing yet must not be sitting at 60% for not having written."""
    result = _grade(quiz_percents=[100.0], reading_percents=[100.0])
    assert round(result.percent) == 100
    assert {c.key for c in result.components} == {"quizzes", "reading"}


def test_a_subject_with_nothing_recorded_is_ungraded_not_failing():
    result = _grade()
    assert result.graded is False
    assert result.percent is None
    assert result.letter is None


def test_the_components_are_carried_so_the_page_can_show_the_arithmetic():
    result = _grade(quiz_percents=[92.0], writing_percents=[78.0])
    detail = {c.key: (round(c.percent), c.weight) for c in result.components}
    assert detail == {"quizzes": (92, 40), "writing": (78, 40)}


def test_letters_land_on_the_standard_scale():
    assert config.letter_for(97) == "A+"
    assert config.letter_for(93) == "A"
    assert config.letter_for(89.9) == "B+"
    assert config.letter_for(59) == "F"


def test_malformed_weight_settings_are_skipped_not_fatal():
    """These come from an editable setting -- a typo shouldn't take down the
    page that shows the grade."""
    assert grades.parse_weights("quizzes:40,writing:oops,:20,bogus:10") == {"quizzes": 40}


# --- reading it back out of the database ------------------------------------------


def _lesson(db, student, agent="english", **metadata) -> int:
    return db.save_lesson(
        student_id=student["id"], agent=agent, subject=agent, topic="t",
        title="A lesson", payload={"title": "A lesson", "activities": []},
        metadata=metadata,
    )


def test_a_quiz_retry_is_deducted_in_the_order_it_was_taken(db, student):
    """`list_quiz_attempts` returns newest-first and the deduction is by
    position, so getting the order wrong would silently deduct the *first*
    attempt instead of the retry."""
    lesson_id = _lesson(db, student)
    db.record_quiz_result(lesson_id, student["id"], 3, 5, False)
    db.record_quiz_result(lesson_id, student["id"], 5, 5, True)

    result = gradebook.subject_grade(db, student["id"], "english")
    quizzes = [c for c in result.components if c.key == "quizzes"][0]
    assert round(quizzes.percent) == 90


def test_approved_writing_counts_full_and_a_bounce_counts_partial(db, student):
    _lesson(db, student, writing_review={
        "0": {"status": config.WRITING_APPROVED},
        "1": {"status": config.WRITING_NEEDS_REVISION},
    })
    result = gradebook.subject_grade(db, student["id"], "english")
    writing = [c for c in result.components if c.key == "writing"][0]
    assert round(writing.percent) == 85


def test_a_draft_he_has_not_submitted_is_not_yet_judged(db, student):
    """Not scored, not zeroed -- an unfinished draft is an absent grade."""
    _lesson(db, student, writing_review={"0": {"status": config.WRITING_DRAFT}})
    result = gradebook.subject_grade(db, student["id"], "english")
    assert [c for c in result.components if c.key == "writing"] == []


def test_extra_drafts_carry_no_penalty(db, student):
    """Deliberate: revision is the process working, and docking a second
    draft would teach exactly the submit-once habit this exists to fix."""
    lesson_id = _lesson(db, student)
    db.save_writing_response(lesson_id, 0, "first go")
    db.save_writing_response(lesson_id, 0, "much better second go")
    db.set_writing_review(lesson_id, 0, config.WRITING_APPROVED)

    result = gradebook.subject_grade(db, student["id"], "english")
    writing = [c for c in result.components if c.key == "writing"][0]
    assert writing.percent == 100


def test_the_parents_assessment_band_feeds_the_grade(db, student):
    lesson_id = _lesson(db, student)
    db.record_assessment(lesson_id, config.ASSESSMENT_GETTING_THERE, "")
    result = gradebook.subject_grade(db, student["id"], "english")
    assessment = [c for c in result.components if c.key == "assessment"][0]
    assert assessment.percent == config.ASSESSMENT_VERDICT_SCORES[
        config.ASSESSMENT_GETTING_THERE
    ]


def test_a_skipped_lesson_does_not_drag_the_grade(db, student):
    lesson_id = _lesson(db, student)
    db.record_assessment(lesson_id, config.ASSESSMENT_NOT_YET, "")
    db.set_lesson_status(lesson_id, "skipped")
    result = gradebook.subject_grade(db, student["id"], "english")
    assert result.graded is False


def test_math_mastery_is_measured_against_what_he_has_attempted(db, student):
    """Against attempted skills, not the whole graph -- otherwise he starts
    the year at 0% for skills the curriculum hasn't reached."""
    db.set_mastery(student["id"], "integer-operations", "mastered", score=100)
    db.set_mastery(student["id"], "fraction-operations", "in_progress", score=60)
    result = gradebook.subject_grade(db, student["id"], "math")
    mastery = [c for c in result.components if c.key == "mastery"][0]
    assert mastery.percent == 50


def test_an_untouched_subject_reports_ungraded(db, student):
    for result in gradebook.all_subject_grades(db, student["id"]):
        assert result.graded is False


# --- on his page ------------------------------------------------------------------


def _seed(tmp_path):
    db_path = tmp_path / "home.db"
    database = Database(db_path)
    s = database.ensure_default_student()
    auth.set_pin(database, "1234")
    lesson_id = database.save_lesson(
        student_id=s["id"], agent="english", subject="english", topic="t",
        title="Paragraphs", payload={"title": "Paragraphs", "activities": []},
    )
    database.record_quiz_result(lesson_id, s["id"], 5, 5, True)
    database.close()
    return db_path


def _open_home(monkeypatch, db_path):
    st.cache_resource.clear()
    monkeypatch.setattr(config, "DEFAULT_DB_PATH", db_path)
    at = AppTest.from_file(HOME_PATH)
    at.run(timeout=30)
    assert not at.exception, [e.message for e in at.exception]
    return at


def test_his_home_page_has_a_grades_tab_with_a_letter(monkeypatch, tmp_path):
    at = _open_home(monkeypatch, _seed(tmp_path))
    grades_button = [b for b in at.button if "Grades" in (b.label or "")][0]
    grades_button.click().run()
    letters = [m.value for m in at.metric]
    assert "A+" in letters


def test_the_grades_tab_shows_no_overall_gpa(monkeypatch, tmp_path):
    """Deliberate: one number for everything reads as a verdict on him
    rather than on the work."""
    at = _open_home(monkeypatch, _seed(tmp_path))
    grades_button = [b for b in at.button if "Grades" in (b.label or "")][0]
    grades_button.click().run()
    labels = " ".join(m.label for m in at.metric)
    assert "GPA" not in labels
    assert "Overall" not in labels


# --- telling him what an attempt is worth, before he takes it ---------------------

MATH_PATH = str(REPO_ROOT / "pages" / "1_Math.py")

QUIZ_POOL = [
    {"question": "What is 2 + 2?", "choices": ["3", "4", "5", "6"],
     "correct_index": 1, "explanation": "2 + 2 = 4."},
    {"question": "What is 3 + 3?", "choices": ["5", "6", "7", "8"],
     "correct_index": 1, "explanation": "3 + 3 = 6."},
]


def _seed_quiz(tmp_path, attempts: list[tuple[int, int]] = ()) -> tuple[Path, int]:
    db_path = tmp_path / "attempt.db"
    database = Database(db_path)
    s = database.ensure_default_student()
    auth.set_pin(database, "1234")
    lesson_id = database.save_lesson(
        student_id=s["id"], agent="math", subject="math", topic="t",
        title="Two-Step Equations",
        payload={"title": "t", "activities": [], "quiz": QUIZ_POOL},
    )
    for correct, total in attempts:
        database.record_quiz_result(lesson_id, s["id"], correct, total, False)
    database.close()
    return db_path, lesson_id


def _open_math(monkeypatch, db_path):
    st.cache_resource.clear()
    monkeypatch.setattr(config, "DEFAULT_DB_PATH", db_path)
    at = AppTest.from_file(HOME_PATH)
    at.run(timeout=30)
    at.switch_page(MATH_PATH)
    at.run(timeout=30)
    assert not at.exception, [e.message for e in at.exception]
    return at


def _text(at) -> str:
    return " ".join(
        [c.value for c in at.caption]
        + [i.value for i in at.info]
        + [b.label or "" for b in at.button]
    )


def test_a_first_attempt_is_told_it_counts_in_full(monkeypatch, tmp_path):
    db_path, _ = _seed_quiz(tmp_path)
    assert "counts in full" in _text(_open_math(monkeypatch, db_path))


def test_a_retry_is_told_what_it_is_worth(monkeypatch, tmp_path):
    db_path, _ = _seed_quiz(tmp_path, [(1, 2)])
    text = _text(_open_math(monkeypatch, db_path))
    assert "Attempt 2 of 4" in text and "90%" in text


def test_a_run_that_cannot_change_the_grade_says_so(monkeypatch, tmp_path):
    """He is never blocked from another go -- he's just told plainly that
    this one is practice, which is the honest version of a retry cap."""
    db_path, _ = _seed_quiz(tmp_path, [(2, 2)])
    text = _text(_open_math(monkeypatch, db_path))
    assert "practice" in text.lower()
    assert "won't change your grade" in text


def test_the_fifth_attempt_is_out_of_the_grade(monkeypatch, tmp_path):
    db_path, _ = _seed_quiz(tmp_path, [(0, 2)] * config.GRADED_QUIZ_ATTEMPTS)
    text = _text(_open_math(monkeypatch, db_path))
    assert f"all {config.GRADED_QUIZ_ATTEMPTS} graded attempts" in text


def test_an_ungraded_subject_gets_no_grade_talk(monkeypatch, tmp_path):
    """Life Skills doesn't carry a grade, so its quiz must not invent one."""
    db_path = tmp_path / "lifeskill.db"
    database = Database(db_path)
    s = database.ensure_default_student()
    auth.set_pin(database, "1234")
    database.save_lesson(
        student_id=s["id"], agent="life_skills", subject="life_skills", topic="t",
        title="Laundry", payload={"title": "t", "activities": [], "quiz": QUIZ_POOL},
    )
    database.close()

    st.cache_resource.clear()
    monkeypatch.setattr(config, "DEFAULT_DB_PATH", db_path)
    at = AppTest.from_file(HOME_PATH)
    at.run(timeout=30)
    assert "toward your grade" not in _text(at).lower()
