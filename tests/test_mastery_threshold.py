"""Passing a Math quiz and fully mastering the skill are two different
bars now, not one: quiz_pass_percent (default 80) is real, encouraging
feedback on its own, while math_mastery_percent (default 100) is the
stricter bar that actually auto-records mastery and unlocks the next
skill. A score in between should still feel like a pass, just with a
nudge to go again for full mastery -- it should NOT record mastery.

Drives the real quiz form end-to-end (five questions, so 80% is an exact,
reachable score) rather than asserting on compass.agents.quiz.grade
directly, since what's under test here is compass.ui.render_quiz's own
wiring between a score and the mastery record -- the grading math itself
is already covered in test_quiz.py.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st
from streamlit.testing.v1 import AppTest

from compass import auth, config
from compass.storage.db import Database

REPO_ROOT = Path(__file__).resolve().parent.parent
HOME_PATH = str(REPO_ROOT / "Home.py")
MATH_PATH = str(REPO_ROOT / "pages" / "1_Math.py")

SKILL_ID = "two-step-equations"


def _five_question_payload():
    return {
        "title": "Two-Step Equations",
        "overview": "",
        "activities": [],
        "materials": [],
        "assessment": {"kind": "check", "description": "", "mastery_criteria": ""},
        "subject_credits": [],
        "estimated_minutes": 30,
        "parent_notes": "",
        "branches": [],
        "quiz": [
            {"question": f"Question {i}?", "choices": ["a", "b", "c", "d"],
             "correct_index": 0, "explanation": ""}
            for i in range(5)
        ],
    }


def _open(monkeypatch, db_path, *, as_parent):
    st.cache_resource.clear()
    monkeypatch.setattr(config, "DEFAULT_DB_PATH", db_path)
    at = AppTest.from_file(HOME_PATH)
    if as_parent:
        at.session_state["parent_unlocked"] = True
    at.run(timeout=30)
    at.switch_page(MATH_PATH)
    at.run(timeout=30)
    assert not at.exception, [e.message for e in at.exception]
    return at


def _submit_quiz(at, lesson_id, *, correct_count):
    """Answer the 5-question quiz, getting exactly `correct_count` right
    (choice 0 is always correct; anything else is wrong)."""
    for index in range(5):
        pick = 0 if index < correct_count else 1
        at.radio(key=f"quiz_pick_{lesson_id}_{index}").set_value(pick)
    at.button(key=f"FormSubmitter:quiz_form_{lesson_id}-Submit quiz").click().run()
    assert not at.exception, [e.message for e in at.exception]
    return at


def _seed(tmp_path):
    db_path = tmp_path / "mastery.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    auth.set_pin(db, "1234")
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="math", subject="math", topic="t",
        title="Two-Step Equations", payload=_five_question_payload(),
        metadata={"skill_id": SKILL_ID},
    )
    db.close()
    return db_path, student["id"], lesson_id


def test_a_score_below_the_pass_bar_does_not_record_mastery(monkeypatch, tmp_path):
    db_path, student_id, lesson_id = _seed(tmp_path)
    at = _open(monkeypatch, db_path, as_parent=False)
    _submit_quiz(at, lesson_id, correct_count=3)  # 60% -- below the 80% pass bar

    db2 = Database(db_path)
    mastery = db2.mastery_map(student_id)
    db2.close()
    assert SKILL_ID not in mastery


def test_a_passing_but_imperfect_score_does_not_record_mastery(monkeypatch, tmp_path):
    db_path, student_id, lesson_id = _seed(tmp_path)
    at = _open(monkeypatch, db_path, as_parent=False)
    _submit_quiz(at, lesson_id, correct_count=4)  # 80% -- passes, but not fully mastered

    db2 = Database(db_path)
    mastery = db2.mastery_map(student_id)
    db2.close()
    assert SKILL_ID not in mastery


def test_a_passing_but_imperfect_score_still_shows_encouraging_feedback(monkeypatch, tmp_path):
    db_path, student_id, lesson_id = _seed(tmp_path)
    at = _open(monkeypatch, db_path, as_parent=False)
    _submit_quiz(at, lesson_id, correct_count=4)

    text = " ".join(s.value for s in at.success) + " ".join(c.value for c in at.caption)
    assert "nice work, that's a pass" in text
    assert "Mastery on this skill needs 100%" in text
    assert "try again" in text.lower()


def test_a_perfect_score_records_mastery(monkeypatch, tmp_path):
    db_path, student_id, lesson_id = _seed(tmp_path)
    at = _open(monkeypatch, db_path, as_parent=False)
    _submit_quiz(at, lesson_id, correct_count=5)  # 100%

    db2 = Database(db_path)
    mastery = db2.mastery_map(student_id)
    db2.close()
    assert mastery[SKILL_ID]["status"] == "mastered"


def test_a_perfect_score_shows_the_mastery_counted_caption(monkeypatch, tmp_path):
    db_path, student_id, lesson_id = _seed(tmp_path)
    at = _open(monkeypatch, db_path, as_parent=False)
    _submit_quiz(at, lesson_id, correct_count=5)

    text = " ".join(c.value for c in at.caption)
    assert "Counted toward mastery of this skill." in text


def test_a_non_math_lesson_is_unaffected_by_the_mastery_bar(monkeypatch, tmp_path):
    """No skill_id at all (Science/English/History) -- passing still just
    shows the ordinary "nice work" message, no mastery nudge, since there's
    no mastery gate there to hook into either way."""
    db_path = tmp_path / "mastery.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    auth.set_pin(db, "1234")
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="science", subject="science", topic="t",
        title="Volcanoes", payload=_five_question_payload(),
    )
    db.close()

    st.cache_resource.clear()
    monkeypatch.setattr(config, "DEFAULT_DB_PATH", db_path)
    at = AppTest.from_file(HOME_PATH)
    at.run(timeout=30)
    at.switch_page(str(REPO_ROOT / "pages" / "2_Science.py"))
    at.run(timeout=30)
    _submit_quiz(at, lesson_id, correct_count=4)  # 80%

    text = " ".join(s.value for s in at.success) + " ".join(c.value for c in at.caption)
    assert "nice work." in text
    assert "Mastery on this skill" not in text
    assert "Counted toward mastery" not in text
