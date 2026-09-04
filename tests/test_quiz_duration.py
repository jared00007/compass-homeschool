"""How long the quiz took: from opening its own collapsed container
(compass.ui.render_quiz's keyed expander, on_change="rerun") to submitting.

Not literally "time from his first click" -- the quiz form lives inside
one st.form, so individual picks never reach the server until Submit
either way -- but opening the expander is itself a deliberate action, and
AppTest can simulate that by writing straight into session_state (there's
no dedicated "toggle this expander" method on Streamlit's test Expander
element, unlike button/radio/etc., so this is the documented workaround:
set the widget's own key to True before the next .run()).
"""

from __future__ import annotations

import time
from pathlib import Path

import streamlit
import streamlit as st
from streamlit.testing.v1 import AppTest

from compass import auth, config
from compass.storage.db import Database
from compass.ui import format_duration
from tests.conftest import correct_pick, wrong_pick

REPO_ROOT = Path(__file__).resolve().parent.parent
HOME_PATH = str(REPO_ROOT / "Home.py")
MATH_PATH = str(REPO_ROOT / "pages" / "1_Math.py")
QUIZZES_PATH = str(REPO_ROOT / "pages" / "16_Quizzes.py")


def _quiz_payload():
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
            {"question": "What is 2 + 2?", "choices": ["3", "4", "5", "6"],
             "correct_index": 1, "explanation": ""},
        ],
    }


def _seed(tmp_path):
    db_path = tmp_path / "duration.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    auth.set_pin(db, "1234")
    # These tests exercise duration/retry mechanics, not the anti-rush gates, so
    # turn the min-time floor and the retry cooldown off here (their own tests
    # live in test_quiz_pacing.py).
    db.set_setting("quiz_min_seconds_per_question", "0")
    db.set_setting("quiz_retry_cooldown_seconds", "0")
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="math", subject="math", topic="t",
        title="Two-Step Equations", payload=_quiz_payload(),
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


def test_format_duration_under_a_minute():
    assert format_duration(45) == "45 sec"


def test_format_duration_exact_minutes():
    assert format_duration(120) == "2 min"


def test_format_duration_minutes_and_seconds():
    assert format_duration(90) == "1 min 30 sec"


def test_submitting_without_opening_the_expander_records_no_duration(monkeypatch, tmp_path):
    db_path, student_id, lesson_id = _seed(tmp_path)
    at = _open_math(monkeypatch, db_path)

    at.radio(key=f"quiz_pick_{lesson_id}_0").set_value(0)
    at.button(key=f"FormSubmitter:quiz_form_{lesson_id}-Submit quiz").click().run()

    db2 = Database(db_path)
    attempt = db2.list_quiz_attempts(student_id)[0]
    db2.close()
    assert attempt["duration_seconds"] is None

    text = " ".join(c.value for c in at.caption)
    assert "Took" not in text


def test_opening_the_expander_first_records_a_duration(monkeypatch, tmp_path):
    db_path, student_id, lesson_id = _seed(tmp_path)
    at = _open_math(monkeypatch, db_path)

    at.session_state[f"quiz_expander_{lesson_id}"] = True
    at.run(timeout=30)
    time.sleep(1.1)

    at.radio(key=f"quiz_pick_{lesson_id}_0").set_value(0)
    at.button(key=f"FormSubmitter:quiz_form_{lesson_id}-Submit quiz").click().run()
    assert not at.exception, [e.message for e in at.exception]

    db2 = Database(db_path)
    attempt = db2.list_quiz_attempts(student_id)[0]
    db2.close()
    assert attempt["duration_seconds"] is not None
    assert attempt["duration_seconds"] >= 1

    text = " ".join(c.value for c in at.caption)
    assert "⏱️ Took" in text


def test_retaking_the_quiz_times_the_second_attempt_independently(monkeypatch, tmp_path):
    """AppTest has no dedicated way to simulate a persisted expander toggle
    across multiple reruns the way a real click in a real browser would
    (Expander is the one Block type with no .set_value()-style element to
    drive) -- writing straight into session_state only holds for the very
    next .run(), so each open needs its own poke here. That's a test-harness
    gap, not evidence of the real app losing the open state; what's under
    test either way is the thing that matters: a retry resets the timer
    rather than inheriting the first attempt's already-elapsed start time.
    """
    db_path, student_id, lesson_id = _seed(tmp_path)
    at = _open_math(monkeypatch, db_path)
    expander_key = f"quiz_expander_{lesson_id}"

    at.session_state[expander_key] = True
    at.run(timeout=30)
    time.sleep(1.1)
    at.radio(key=f"quiz_pick_{lesson_id}_0").set_value(0)  # correctness is irrelevant here
    at.button(key=f"FormSubmitter:quiz_form_{lesson_id}-Submit quiz").click().run()

    at.button(key=f"quiz_retry_{lesson_id}").click().run()
    at.session_state[expander_key] = True
    at.run(timeout=30)
    # No sleep here -- the retry's own timer should start fresh, not
    # inherit the first attempt's (already-elapsed) start time.
    at.radio(key=f"quiz_pick_{lesson_id}_0").set_value(0)
    at.button(key=f"FormSubmitter:quiz_form_{lesson_id}-Submit quiz").click().run()

    db2 = Database(db_path)
    attempts = sorted(db2.list_quiz_attempts(student_id), key=lambda a: a["id"])
    db2.close()
    assert len(attempts) == 2
    first_duration = attempts[0]["duration_seconds"]
    second_duration = attempts[1]["duration_seconds"]
    assert first_duration is not None and first_duration >= 1
    # The retry reopened the (already-expanded) container instantly and was
    # submitted immediately -- its own duration should be much shorter than
    # the first attempt's, not inherited/accumulated from it.
    assert second_duration is not None
    assert second_duration < first_duration


def test_a_perfect_score_launches_balloons(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(streamlit, "balloons", lambda: calls.append(1))
    db_path, student_id, lesson_id = _seed(tmp_path)
    at = _open_math(monkeypatch, db_path)

    right = correct_pick(_quiz_payload()["quiz"], lesson_id, 0)
    at.radio(key=f"quiz_pick_{lesson_id}_0").set_value(right)
    at.button(key=f"FormSubmitter:quiz_form_{lesson_id}-Submit quiz").click().run()

    assert calls


def test_a_missed_question_does_not_launch_balloons(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(streamlit, "balloons", lambda: calls.append(1))
    db_path, student_id, lesson_id = _seed(tmp_path)
    at = _open_math(monkeypatch, db_path)

    at.radio(key=f"quiz_pick_{lesson_id}_0").set_value(
        wrong_pick(_quiz_payload()["quiz"], lesson_id, 0)
    )
    at.button(key=f"FormSubmitter:quiz_form_{lesson_id}-Submit quiz").click().run()

    assert not calls


def test_quizzes_page_shows_the_duration(monkeypatch, tmp_path):
    db_path, student_id, lesson_id = _seed(tmp_path)
    db = Database(db_path)
    db.record_quiz_result(
        lesson_id, student_id, correct=1, total=1, passed=True, duration_seconds=185
    )
    db.close()

    st.cache_resource.clear()
    monkeypatch.setattr(config, "DEFAULT_DB_PATH", db_path)
    at = AppTest.from_file(HOME_PATH)
    at.session_state["parent_unlocked"] = True
    at.run(timeout=30)
    at.switch_page(QUIZZES_PATH)
    at.run(timeout=30)
    assert not at.exception, [e.message for e in at.exception]

    labels = [e.label for e in at.expander]
    assert any("took 3 min 5 sec" in l for l in labels)
