"""Anti-rushing on the quiz: a minimum time before a submission is accepted,
and a short cooldown on "Try again" after a miss. Reported directly -- he was
finishing five-question quizzes in under a minute, with retries getting *worse*
(3/5 -> 2/5 -> 2/5) in under 90 seconds each. The gates are family-policy
settings (`quiz_min_seconds_per_question`, `quiz_retry_cooldown_seconds`), on by
default; every other quiz test turns them off, so this file is where they're
exercised on.

Opening the quiz's own expander is what starts its clock (see
test_quiz_duration.py for why that's the documented AppTest workaround), so
these tests set the expander key and then backdate the stored start time to
stand in for real elapsed seconds without actually sleeping.
"""

from __future__ import annotations

import time
from pathlib import Path

import streamlit as st
from streamlit.testing.v1 import AppTest

from compass import auth, config
from compass.storage.db import Database
from tests.conftest import correct_pick, wrong_pick

REPO_ROOT = Path(__file__).resolve().parent.parent
HOME_PATH = str(REPO_ROOT / "Home.py")
MATH_PATH = str(REPO_ROOT / "pages" / "1_Math.py")


def _payload():
    return {
        "title": "Two-Step Equations",
        "activities": [],
        "quiz": [
            {"question": "What is 2 + 2?", "choices": ["3", "4", "5", "6"],
             "correct_index": 1, "explanation": "Two and two make four."},
        ],
    }


def _seed(tmp_path):
    db_path = tmp_path / "pacing.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    auth.set_pin(db, "1234")
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="math", subject="math", topic="t",
        title="Two-Step Equations", payload=_payload(),
    )
    db.close()
    return db_path, student["id"], lesson_id


def _open_math(monkeypatch, db_path):
    st.cache_resource.clear()
    monkeypatch.setattr(config, "DEFAULT_DB_PATH", db_path)
    at = AppTest.from_file(HOME_PATH)
    at.run(timeout=30)
    at.switch_page(MATH_PATH)
    at.run(timeout=30)
    assert not at.exception, [e.message for e in at.exception]
    return at


def _submit(at, lesson_id):
    at.button(key=f"FormSubmitter:quiz_form_{lesson_id}-Submit quiz").click().run()
    assert not at.exception, [e.message for e in at.exception]


def test_a_too_fast_submit_is_refused_and_records_nothing(monkeypatch, tmp_path):
    db_path, student_id, lesson_id = _seed(tmp_path)
    at = _open_math(monkeypatch, db_path)
    at.session_state[f"quiz_expander_{lesson_id}"] = True
    at.run(timeout=30)  # opening the expander starts the clock (now)
    at.radio(key=f"quiz_pick_{lesson_id}_0").set_value(1)
    _submit(at, lesson_id)  # ~0 seconds elapsed, under the 48s/question floor

    db2 = Database(db_path)
    attempts = db2.list_quiz_attempts(student_id)
    db2.close()
    assert attempts == []  # nothing graded
    assert any("Slow down" in w.value for w in at.warning)


def test_submitting_after_the_time_floor_grades_normally(monkeypatch, tmp_path):
    db_path, student_id, lesson_id = _seed(tmp_path)
    at = _open_math(monkeypatch, db_path)
    at.session_state[f"quiz_expander_{lesson_id}"] = True
    at.run(timeout=30)
    # Stand in for having spent well over the per-question floor (48s).
    at.session_state[f"quiz_started_at_{lesson_id}"] = time.time() - 300
    at.radio(key=f"quiz_pick_{lesson_id}_0").set_value(
        correct_pick(_payload()["quiz"], lesson_id, 0)
    )
    _submit(at, lesson_id)

    db2 = Database(db_path)
    attempts = db2.list_quiz_attempts(student_id)
    db2.close()
    assert len(attempts) == 1
    assert attempts[0]["correct"] == 1


def test_try_again_is_locked_during_the_cooldown_then_unlocks(monkeypatch, tmp_path):
    db_path, student_id, lesson_id = _seed(tmp_path)
    at = _open_math(monkeypatch, db_path)
    at.session_state[f"quiz_expander_{lesson_id}"] = True
    at.run(timeout=30)
    at.session_state[f"quiz_started_at_{lesson_id}"] = time.time() - 300
    at.radio(key=f"quiz_pick_{lesson_id}_0").set_value(
        wrong_pick(_payload()["quiz"], lesson_id, 0)  # a miss -> a fail
    )
    _submit(at, lesson_id)

    # Freshly failed: Try again is disabled and a "look back" note is shown.
    retry = at.button(key=f"quiz_retry_{lesson_id}")
    assert retry.disabled is True
    assert any("unlocks in about" in c.value for c in at.caption)

    # Once the cooldown has elapsed (reviewing the misses is what counts it
    # down live), the button unlocks.
    at.session_state[f"quiz_result_{lesson_id}"]["graded_wall"] = time.time() - 120
    at.run(timeout=30)
    assert at.button(key=f"quiz_retry_{lesson_id}").disabled is False
