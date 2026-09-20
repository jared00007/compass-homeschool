"""The Rewind agent -- cumulative "flashback" reviews over already-completed
lessons.

Covers the boundary behaviour, not the model's prose: which completed lessons
become review material, that a generated review is persisted as its own `rewind`
lesson and costed, that a bad quiz question is dropped before it reaches him,
that its assessment time is split across the real subjects it covered, and --
end to end through the real Home page -- that taking the quiz auto-completes the
review without ever routing it to the parent review queue (parent grading is a
deliberate v2).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from compass import auth, config
from compass.agents import rewind
from compass.agents.quiz import QUESTIONS_PER_ATTEMPT
from compass.storage.db import Database
from tests.conftest import correct_pick

REPO_ROOT = Path(__file__).resolve().parent.parent
HOME_PATH = str(REPO_ROOT / "Home.py")
MISSION_CONTROL_PATH = str(REPO_ROOT / "pages" / "14_Mission_Control.py")


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "rewind.db")
    yield database
    database.close()


@pytest.fixture()
def student(db):
    return db.ensure_default_student()


def _seed_completed(db, student, agent, subject, title, objectives):
    lesson_id = db.save_lesson(
        student_id=student["id"], agent=agent, subject=subject, topic=title,
        title=title, payload={"learning_objectives": objectives, "quiz": []},
    )
    db.set_lesson_status(lesson_id, "completed")
    return lesson_id


def a_rewind_payload(n_questions=16, **overrides):
    payload = {
        "intro": "Let's look back at what you've learned!",
        "recap": [
            {"subject": "Math", "concept": "Slope", "refresher": "Rise over run."},
            {"subject": "Science", "concept": "Cells", "refresher": "The units of life."},
        ],
        "quiz": [
            {
                "question": f"Question {i}?",
                "choices": ["a", "b", "c", "d"],
                "correct_index": 0,
                "explanation": "Because a.",
            }
            for i in range(n_questions)
        ],
        "_usage": {"input_tokens": 5, "output_tokens": 7, "model": "claude-opus-5"},
    }
    payload.update(overrides)
    return payload


def _generate(db, student, selections, payload):
    with patch("compass.agents.rewind.generate_lesson", return_value=payload) as call:
        lesson_id = rewind.generate_rewind_review(db, student, selections)
    return lesson_id, call


# --- the selection menu --------------------------------------------------------


def test_completed_lessons_for_review_lists_only_finished_graded_lessons(db, student):
    done = _seed_completed(db, student, "math", "math", "Slope", ["Find slope"])
    # A planned (not completed) lesson, a non-graded agent, and a rewind review
    # itself must all stay out of the pickable material.
    db.save_lesson(student["id"], "science", "science", "Cells", "Cells",
                   payload={"learning_objectives": [], "quiz": []})  # planned
    life = db.save_lesson(student["id"], "life_skills", "health", "Laundry", "Laundry",
                          payload={"quiz": []})
    db.set_lesson_status(life, "completed")

    rows = db.completed_lessons_for_review(student["id"])
    assert [r["id"] for r in rows] == [done]
    assert rows[0]["learning_objectives"] == ["Find slope"]
    assert rows[0]["reviewed_on"]  # a date to show in the picker


# --- generation, persistence, cost ---------------------------------------------


def test_generate_rewind_review_persists_a_rewind_lesson(db, student):
    m = _seed_completed(db, student, "math", "math", "Slope", ["Find slope"])
    s = _seed_completed(db, student, "science", "science", "Cells", ["Name organelles"])
    selections = db.completed_lessons_for_review(student["id"])

    lesson_id, _ = _generate(db, student, selections, a_rewind_payload())
    review = db.get_lesson(lesson_id)

    assert review["agent"] == rewind.AGENT_KEY
    assert review["status"] == "planned"
    assert review["metadata"]["rewind"] is True
    assert sorted(review["metadata"]["source_lesson_ids"]) == sorted([m, s])
    assert review["metadata"]["subject_scope"] == ["Math", "Science"]
    assert len(review["payload"]["quiz"]) == 16


def test_generate_rewind_review_is_costed_like_every_other_generation(db, student):
    _seed_completed(db, student, "math", "math", "Slope", ["Find slope"])
    selections = db.completed_lessons_for_review(student["id"])
    _generate(db, student, selections, a_rewind_payload())

    start, end = db.school_year_bounds()
    usage = db.lesson_usage_between(student["id"], start, end)
    assert rewind.AGENT_KEY in {u["agent"] for u in usage}


def test_generate_rewind_review_drops_a_malformed_quiz_question(db, student):
    _seed_completed(db, student, "math", "math", "Slope", ["Find slope"])
    selections = db.completed_lessons_for_review(student["id"])
    payload = a_rewind_payload(n_questions=3)
    # A question whose correct_index points past its choices can never be
    # answered correctly -- verify_quiz must drop it before he sees it.
    payload["quiz"].append(
        {"question": "broken", "choices": ["a", "b"], "correct_index": 5, "explanation": ""}
    )
    lesson_id, _ = _generate(db, student, selections, payload)
    kept = db.get_lesson(lesson_id)["payload"]["quiz"]
    assert len(kept) == 3
    assert all(q["question"] != "broken" for q in kept)


def test_generate_rewind_review_rejects_an_empty_selection(db, student):
    with pytest.raises(ValueError):
        rewind.generate_rewind_review(db, student, [])


# --- assessment time, split across the real subjects ---------------------------


def test_rewind_quiz_time_is_split_across_the_subjects_it_covered(db, student):
    _seed_completed(db, student, "math", "math", "Slope", ["Find slope"])
    _seed_completed(db, student, "science", "science", "Cells", ["Name organelles"])
    _seed_completed(db, student, "english", "reading", "Metaphor", ["Spot a metaphor"])
    selections = db.completed_lessons_for_review(student["id"])
    lesson_id, _ = _generate(db, student, selections, a_rewind_payload())

    db.record_quiz_result(lesson_id, student["id"], correct=5, total=5, passed=True)

    quiz_acts = [a for a in db.list_activities(student["id"]) if a["source"] == "quiz"]
    assert len(quiz_acts) == 1
    assert quiz_acts[0]["minutes"] == config.REWIND_DEFAULT_MINUTES

    cur = db.conn.execute(
        "SELECT subject, SUM(minutes) m FROM activity_subject_credits GROUP BY subject"
    )
    credits = {r["subject"]: r["m"] for r in cur.fetchall()}
    # english folds to reading; the split sums to the whole block, never a
    # placeholder "review" subject.
    assert set(credits) == {"math", "science", "reading"}
    assert sum(credits.values()) == config.REWIND_DEFAULT_MINUTES
    assert "review" not in credits


def test_rewind_quiz_time_is_credited_once_even_on_a_retake(db, student):
    _seed_completed(db, student, "math", "math", "Slope", ["Find slope"])
    selections = db.completed_lessons_for_review(student["id"])
    lesson_id, _ = _generate(db, student, selections, a_rewind_payload())

    db.record_quiz_result(lesson_id, student["id"], correct=3, total=5, passed=False)
    db.record_quiz_result(lesson_id, student["id"], correct=5, total=5, passed=True)

    quiz_acts = [a for a in db.list_activities(student["id"]) if a["source"] == "quiz"]
    assert len(quiz_acts) == 1  # the retake doesn't stack a second block


# --- end to end on Landon's Home page ------------------------------------------


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


def test_home_shows_a_rewind_review_and_taking_it_completes_without_a_parent_step(
    monkeypatch, tmp_path
):
    db_path = tmp_path / "rewind.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    auth.set_pin(db, "1234")  # makes is_parent() default False -> student view
    _seed_completed(db, student, "math", "math", "Slope", ["Find slope"])
    selections = db.completed_lessons_for_review(student["id"])
    lesson_id, _ = _generate(db, student, selections, a_rewind_payload())
    db.close()

    at = _open(monkeypatch, db_path, HOME_PATH, as_parent=False)
    body = " ".join(m.value for m in at.markdown)
    assert "Rewind" in body

    pool = a_rewind_payload()["quiz"]
    for i in range(QUESTIONS_PER_ATTEMPT):
        at.radio(key=f"quiz_pick_{lesson_id}_{i}").set_value(correct_pick(pool, lesson_id, i))
    at.button(key=f"FormSubmitter:quiz_form_{lesson_id}-Submit quiz").click().run()
    assert not at.exception, [e.message for e in at.exception]

    db2 = Database(db_path)
    review = db2.get_lesson(lesson_id)
    attempts = db2.list_quiz_attempts(student["id"], lesson_id=lesson_id)
    db2.close()

    # Auto-graded and self-completed -- never handed to the parent review queue.
    assert review["status"] == "completed"
    assert review["status"] != "submitted"
    assert len(attempts) == 1
    assert attempts[0]["correct"] == QUESTIONS_PER_ATTEMPT


def test_mission_control_can_generate_a_rewind_review(monkeypatch, tmp_path):
    db_path = tmp_path / "rewind.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    _seed_completed(db, student, "math", "math", "Slope", ["Find slope"])
    db.close()

    # The generate button is gated on the Anthropic API being reachable, which a
    # test sandbox has no key for -- stand it up so the button is live.
    monkeypatch.setattr("compass.agents.api_available", lambda: (True, "Ready."))

    at = _open(monkeypatch, db_path, MISSION_CONTROL_PATH, as_parent=True)

    # Select all Math (authoritative), then generate (LLM mocked).
    at.checkbox(key="rewind_all_Math").set_value(True).run()
    with patch("compass.agents.rewind.generate_lesson", return_value=a_rewind_payload()):
        at.button(key="rewind_generate_btn").click().run()
    assert not at.exception, [e.message for e in at.exception]

    db2 = Database(db_path)
    reviews = db2.list_rewind_reviews(student["id"])
    db2.close()
    assert len(reviews) == 1
    assert reviews[0]["agent"] == rewind.AGENT_KEY
