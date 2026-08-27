"""The "did you actually read it?" check on off-screen reading.

Every English lesson opens with "read chapters 9-10" and nothing ever
confirmed it happened -- plausibly upstream of a lot of thin writing,
since you can't write 200 words about a chapter you skimmed.

Deliberately ungated: it reports, it never blocks. A question the model
got wrong about an obscure book would otherwise strand him on reading he
genuinely did.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from compass import auth, config
from compass.agents.quiz import verify_reading_checks
from compass.storage.db import Database

REPO_ROOT = Path(__file__).resolve().parent.parent
HOME_PATH = str(REPO_ROOT / "Home.py")
ENGLISH_PATH = str(REPO_ROOT / "pages" / "3_English.py")
ACTIVITY_LOG_PATH = str(REPO_ROOT / "pages" / "10_Activity_Log.py")


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    yield database
    database.close()


@pytest.fixture()
def student(db):
    return db.ensure_default_student()


def _questions():
    return [
        {"question": "What did Brian use to make the fish spear?",
         "choices": ["A sapling", "His hatchet handle", "A bone", "Rope"],
         "correct_index": 0},
        {"question": "Where did he build the fish pen?",
         "choices": ["The shallows", "A cave", "The ridge", "Under the plane"],
         "correct_index": 0},
    ]


def _payload(with_check=True):
    return {
        "title": "Brian's Turning Point",
        "overview": "",
        "activities": [
            {"title": "Read Ch. 9-10", "kind": "reading", "minutes": 15,
             "instructions": "Read through the fish-spear scene.",
             "reading_check": _questions() if with_check else [],
             "video": {"found": False, "title": "", "url": "", "channel": "", "why": ""}},
        ],
        "materials": [], "subject_credits": [], "branches": [],
    }


# --- validation ------------------------------------------------------------------


def test_a_malformed_question_is_dropped_before_it_reaches_him():
    """Graded against a book the model is recalling rather than content it
    just wrote, so a half-formed question here is if anything likelier."""
    payload = _payload()
    payload["activities"][0]["reading_check"] = [
        {"question": "Fine?", "choices": ["a", "b", "c", "d"], "correct_index": 0},
        {"question": "Only three choices?", "choices": ["a", "b", "c"], "correct_index": 0},
        {"question": "Unselectable answer?", "choices": ["a", "b", "c", "d"],
         "correct_index": 9},
    ]
    warnings = verify_reading_checks(payload)
    kept = payload["activities"][0]["reading_check"]
    assert [q["question"] for q in kept] == ["Fine?"]
    assert len(warnings) == 2


def test_a_missing_reading_check_normalizes_to_empty():
    payload = _payload(with_check=False)
    del payload["activities"][0]["reading_check"]
    verify_reading_checks(payload)
    assert payload["activities"][0]["reading_check"] == []


# --- storage ---------------------------------------------------------------------


def test_a_score_is_stored_per_activity(db, student):
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="english", subject="english", topic="t",
        title="t", payload=_payload(),
    )
    db.save_reading_check(lesson_id, 0, correct=2, total=2)

    stored = db.get_lesson(lesson_id)["metadata"]["reading_checks"]["0"]
    assert (stored["correct"], stored["total"]) == (2, 2)
    assert stored["checked_on"]


def test_storing_a_score_preserves_other_metadata(db, student):
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="math", subject="math", topic="t", title="t",
        payload={}, metadata={"skill_id": "two-step-equations"},
    )
    db.save_reading_check(lesson_id, 0, correct=1, total=2)
    assert db.get_lesson(lesson_id)["metadata"]["skill_id"] == "two-step-equations"


# --- his page ---------------------------------------------------------------------


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


def _seed(tmp_path, *, with_check=True, score=None):
    db_path = tmp_path / "reading.db"
    database = Database(db_path)
    s = database.ensure_default_student()
    auth.set_pin(database, "1234")
    lesson_id = database.save_lesson(
        student_id=s["id"], agent="english", subject="english", topic="t",
        title="Brian's Turning Point", payload=_payload(with_check=with_check),
    )
    if score is not None:
        database.save_reading_check(lesson_id, 0, *score)
    database.close()
    return db_path, lesson_id


def test_the_check_is_shown_on_a_reading_activity(monkeypatch, tmp_path):
    db_path, lesson_id = _seed(tmp_path)
    at = _open(monkeypatch, db_path, ENGLISH_PATH, as_parent=False)
    text = " ".join(m.value for m in at.markdown)
    assert "did you read it" in text.lower()
    assert "What did Brian use to make the fish spear?" in text


def test_no_check_is_shown_when_the_lesson_has_none(monkeypatch, tmp_path):
    db_path, lesson_id = _seed(tmp_path, with_check=False)
    at = _open(monkeypatch, db_path, ENGLISH_PATH, as_parent=False)
    text = " ".join(m.value for m in at.markdown)
    assert "did you read it" not in text.lower()


def test_answering_correctly_records_it_and_says_so(monkeypatch, tmp_path):
    db_path, lesson_id = _seed(tmp_path)
    at = _open(monkeypatch, db_path, ENGLISH_PATH, as_parent=False)

    at.radio(key=f"reading_pick_{lesson_id}_0_0").set_value(0)
    at.radio(key=f"reading_pick_{lesson_id}_0_1").set_value(0)
    at.button(key=f"FormSubmitter:reading_check_{lesson_id}_0-Check").click().run()
    assert not at.exception, [e.message for e in at.exception]

    db2 = Database(db_path)
    stored = db2.get_lesson(lesson_id)["metadata"]["reading_checks"]["0"]
    db2.close()
    assert (stored["correct"], stored["total"]) == (2, 2)
    assert any("you read it" in s.value for s in at.success)


def test_a_wrong_answer_nudges_him_back_to_the_text(monkeypatch, tmp_path):
    db_path, lesson_id = _seed(tmp_path)
    at = _open(monkeypatch, db_path, ENGLISH_PATH, as_parent=False)

    at.radio(key=f"reading_pick_{lesson_id}_0_0").set_value(1)  # wrong
    at.radio(key=f"reading_pick_{lesson_id}_0_1").set_value(0)  # right
    at.button(key=f"FormSubmitter:reading_check_{lesson_id}_0-Check").click().run()

    db2 = Database(db_path)
    stored = db2.get_lesson(lesson_id)["metadata"]["reading_checks"]["0"]
    db2.close()
    assert (stored["correct"], stored["total"]) == (1, 2)
    assert any("going back over" in w.value for w in at.warning)


def test_it_never_blocks_the_rest_of_the_lesson(monkeypatch, tmp_path):
    """Ungated on purpose -- a bad question about an obscure book must not
    strand him on reading he actually did."""
    db_path, lesson_id = _seed(tmp_path)
    at = _open(monkeypatch, db_path, ENGLISH_PATH, as_parent=False)
    assert any("I'm done for today" in (b.label or "") for b in at.button)


# --- the parent's view -------------------------------------------------------------


def test_the_parent_sees_a_passed_check(monkeypatch, tmp_path):
    db_path, lesson_id = _seed(tmp_path, score=(2, 2))
    at = _open(monkeypatch, db_path, ACTIVITY_LOG_PATH, as_parent=True)
    text = " ".join(c.value for c in at.caption)
    assert "Reading check" in text and "2/2" in text


def test_the_parent_is_warned_about_a_failed_check(monkeypatch, tmp_path):
    db_path, lesson_id = _seed(tmp_path, score=(0, 2))
    at = _open(monkeypatch, db_path, ACTIVITY_LOG_PATH, as_parent=True)
    warnings = " ".join(w.value for w in at.warning)
    assert "Reading check" in warnings
    assert "actually did the reading" in warnings
