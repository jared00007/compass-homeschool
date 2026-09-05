"""Grades: the retry weighting, the component weighting, and what he sees.

Landon asked to be graded, which makes the *shape* of the rules the thing
worth testing rather than the arithmetic alone. Three properties matter
more than any particular number here, and each has its own test below:

  * a retry can never lower a grade (so there is never a reason to avoid
    trying again),
  * a component with nothing in it is dropped, never counted as a zero (so
    "hasn't handed anything in yet" can't read as "failed the hand-in"),
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


WEIGHTS = {"quizzes": 40, "assessment": 60}


def _grade(**kwargs) -> grades.SubjectGrade:
    base = dict(quiz_percents=[], mastery_percent=None, assessment_percents=[])
    base.update(kwargs)
    return grades.subject_grade("english", WEIGHTS, **base)


def test_components_combine_by_their_weights():
    result = _grade(quiz_percents=[100.0], assessment_percents=[50.0])
    assert round(result.percent) == 70  # .4*100 + .6*50


def test_a_missing_component_redistributes_rather_than_scoring_zero():
    """The bug that would matter most: a kid two weeks into the year with
    nothing handed in yet must not be sitting low for not having a hand-in --
    the quiz he does have carries the grade until there's more to weigh."""
    result = _grade(quiz_percents=[100.0])
    assert round(result.percent) == 100
    assert {c.key for c in result.components} == {"quizzes"}


def test_a_subject_with_nothing_recorded_is_ungraded_not_failing():
    result = _grade()
    assert result.graded is False
    assert result.percent is None
    assert result.letter is None


def test_the_components_are_carried_so_the_page_can_show_the_arithmetic():
    result = _grade(quiz_percents=[92.0], assessment_percents=[78.0])
    detail = {c.key: (round(c.percent), c.weight) for c in result.components}
    assert detail == {"quizzes": (92, 40), "assessment": (78, 60)}


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


def test_writing_review_is_coaching_not_its_own_grade_lane(db, student):
    """Writing folds into the hand-in now -- the write -> review -> revise loop
    still runs to coach him, but it no longer forms a separate grade component.
    Its quality is judged when the parent grades the hand-in (`assessment`)."""
    _lesson(db, student, writing_review={
        "0": {"status": config.WRITING_APPROVED},
        "1": {"status": config.WRITING_NEEDS_REVISION},
    })
    result = gradebook.subject_grade(db, student["id"], "english")
    assert [c for c in result.components if c.key == "writing"] == []


def test_reading_checks_fold_into_the_quiz_component(db, student):
    """Reading checks are auto-graded objective checks, same as the quiz, so
    they share one component the parent sees as "Quiz" -- not a separate lane."""
    lesson_id = _lesson(db, student, reading_checks={
        "0": {"correct": 4, "total": 4},
    })
    db.record_quiz_result(lesson_id, student["id"], 5, 5, True)
    result = gradebook.subject_grade(db, student["id"], "english")
    keys = {c.key for c in result.components}
    assert "reading" not in keys
    quiz = [c for c in result.components if c.key == "quizzes"][0]
    # 100 (quiz) and 100 (reading check) both land in the quiz component.
    assert round(quiz.percent) == 100


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


# --- the per-item drill-down: "why is his grade bad" ----------------------------


def test_graded_items_lists_each_scored_piece_worst_first(db, student):
    """Every individual thing that fed the average shows up as its own line,
    lowest score first, so the reason a grade is low is the top of the list."""
    good = _lesson(db, student, agent="english")
    db.record_quiz_result(good, student["id"], 5, 5, True)  # 100
    bad = _lesson(db, student, agent="english")
    db.record_quiz_result(bad, student["id"], 2, 5, False)  # 40

    items = gradebook.graded_items(db, student["id"], "english")
    percents = [round(i.percent) for i in items]
    assert percents == [40, 100]  # worst first
    assert all(i.component == "quizzes" for i in items)


def test_graded_items_includes_hand_ins_and_reading_checks(db, student):
    lesson_id = _lesson(db, student, agent="english", reading_checks={
        "0": {"correct": 3, "total": 4},  # 75
    })
    db.record_quiz_result(lesson_id, student["id"], 5, 5, True)  # 100
    db.record_assessment(lesson_id, config.ASSESSMENT_GETTING_THERE, "")

    items = gradebook.graded_items(db, student["id"], "english")
    components = {i.component for i in items}
    assert components == {"quizzes", "assessment"}
    # The hand-in verdict rides in the detail so a parent sees which band it was.
    assessment = [i for i in items if i.component == "assessment"][0]
    assert config.ASSESSMENT_GETTING_THERE in assessment.detail


def test_graded_items_lists_math_skills_individually(db, student):
    db.set_mastery(student["id"], "integer-operations", "mastered", score=100)
    db.set_mastery(student["id"], "fraction-operations", "in_progress", score=60)

    items = gradebook.graded_items(db, student["id"], "math")
    mastery = [i for i in items if i.component == "mastery"]
    assert len(mastery) == 2
    # The not-yet-mastered skill sorts to the top (0%), the mastered one to 100%.
    assert mastery[0].percent == 0.0
    assert mastery[-1].percent == 100.0


def test_graded_items_skips_a_skipped_lesson(db, student):
    lesson_id = _lesson(db, student, agent="english")
    db.record_assessment(lesson_id, config.ASSESSMENT_NOT_YET, "")
    db.set_lesson_status(lesson_id, "skipped")
    assert gradebook.graded_items(db, student["id"], "english") == []


def test_only_hand_ins_and_math_skills_are_editable(db, student):
    """A parent can re-grade the items they judged themselves -- a hand-in
    verdict or a math skill -- but not an auto-marked quiz, which changes only
    when he retakes it."""
    lesson_id = _lesson(db, student, agent="english")
    db.record_quiz_result(lesson_id, student["id"], 3, 5, False)
    db.record_assessment(lesson_id, config.ASSESSMENT_GETTING_THERE, "")

    items = gradebook.graded_items(db, student["id"], "english")
    quiz = [i for i in items if i.component == "quizzes"][0]
    hand_in = [i for i in items if i.component == "assessment"][0]

    assert not quiz.editable
    assert quiz.lesson_id is None  # nothing to hand-edit
    assert hand_in.editable
    assert hand_in.lesson_id == lesson_id
    assert hand_in.verdict == config.ASSESSMENT_GETTING_THERE


def test_a_math_skill_item_is_editable_by_its_skill_id(db, student):
    db.set_mastery(student["id"], "integer-operations", "in_progress", score=60)
    items = gradebook.graded_items(db, student["id"], "math")
    skill = [i for i in items if i.component == "mastery"][0]
    assert skill.editable
    assert skill.skill_id == "integer-operations"
    assert skill.percent == 0.0  # not yet mastered


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


def test_a_parent_override_replaces_the_computed_grade(db):
    """A parent's hand-set grade wins over whatever the components computed,
    and carries its note; the computed breakdown stays on the grade so both
    can be shown. Reported: "where can i find/edit a grading record as parent?"
    """
    student = db.ensure_default_student()
    # Give math a real computed grade first, from a quiz attempt.
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="math", subject="math", topic="t",
        title="Q", payload={"title": "Q", "activities": []},
        metadata={"skill_id": "add_within_20"},
    )
    db.record_quiz_result(
        lesson_id=lesson_id, student_id=student["id"], correct=3, total=5, passed=False
    )
    computed = gradebook.subject_grade(db, student["id"], "math")
    assert computed.graded and not computed.overridden

    gradebook.set_override(db, "math", 95, "Nailed the project I gave him")
    overridden = gradebook.subject_grade(db, student["id"], "math")
    assert overridden.overridden
    assert overridden.percent == 95
    assert overridden.override_note == "Nailed the project I gave him"
    # The computed components are still there for the breakdown.
    assert overridden.components

    gradebook.set_override(db, "math", None)
    assert not gradebook.subject_grade(db, student["id"], "math").overridden


def test_override_can_grade_a_subject_with_no_computed_grade(db):
    """A subject with no auto-signals is ungraded -- but a parent can still put
    a grade on it by hand (a subject taught entirely off-app)."""
    student = db.ensure_default_student()
    assert not gradebook.subject_grade(db, student["id"], "history").graded
    gradebook.set_override(db, "history", 88)
    graded = gradebook.subject_grade(db, student["id"], "history")
    assert graded.graded and graded.overridden and graded.percent == 88
