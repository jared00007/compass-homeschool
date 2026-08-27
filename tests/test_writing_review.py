"""compass/agents/writing_review.py -- the automated read of one writing
response against the prompt it answered, and the one-call-per-activity gate
that keeps a student from iterating against the reviewer instead of thinking.

The model call itself is stubbed throughout: what's under test is the
plumbing around it (what gets sent, what gets stored, when the button is
offered), not the model's judgment.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from compass import auth, config
from compass.agents import writing_review
from compass.storage.db import Database

REPO_ROOT = Path(__file__).resolve().parent.parent
HOME_PATH = str(REPO_ROOT / "Home.py")
ENGLISH_PATH = str(REPO_ROOT / "pages" / "3_English.py")
ACTIVITY_LOG_PATH = str(REPO_ROOT / "pages" / "10_Activity_Log.py")

A_REVIEW = {
    "strengths": ["You quoted the Compact directly, which the prompt asked for."],
    "missing": ["The prompt asks you to name a group left out; you haven't yet."],
    "concerns": ["Energy isn't created by motion -- it's lost to friction as heat."],
    "next_moves": ["Go back and name one group who didn't sign."],
}


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    yield database
    database.close()


@pytest.fixture()
def student(db):
    return db.ensure_default_student()


def _payload():
    return {
        "title": "41 Signatures on a Boat",
        "activities": [
            {"title": "Write the source analysis", "kind": "writing", "minutes": 20,
             "instructions": "Write 150 words. Quote the Compact once.",
             "requires_written_response": True},
        ],
        "assessment": {"kind": "check", "description": "",
                       "mastery_criteria": "Names a group left out and defends a judgment."},
    }


def _lesson(db, student_id):
    return db.save_lesson(
        student_id=student_id, agent="history", subject="history", topic="t",
        title="41 Signatures on a Boat", payload=_payload(),
    )


# --- what gets sent to the model -------------------------------------------------


def test_the_prompt_carries_the_assignment_the_rubric_and_his_response():
    activity = _payload()["activities"][0]
    prompt = writing_review._user_prompt(
        "41 Signatures on a Boat", activity, "Names a group left out.", "What he wrote."
    )
    assert "Write 150 words. Quote the Compact once." in prompt
    assert "Names a group left out." in prompt
    assert "What he wrote." in prompt


def test_a_lesson_with_no_rubric_still_builds_a_prompt():
    """mastery_criteria is optional in practice -- an older lesson, or one
    where the model left it empty, must still be reviewable against its own
    instructions rather than crashing."""
    prompt = writing_review._user_prompt(
        "T", _payload()["activities"][0], "", "What he wrote."
    )
    assert "What he wrote." in prompt
    assert "MEETING THE BAR" not in prompt


# --- storage and the one-and-done gate -------------------------------------------


def test_a_review_is_stored_on_the_lesson(monkeypatch, db, student):
    lesson_id = _lesson(db, student["id"])
    monkeypatch.setattr(
        writing_review, "generate_lesson", lambda **kwargs: dict(A_REVIEW)
    )

    writing_review.review_writing(
        db, student, db.get_lesson(lesson_id), 0, "His response."
    )

    lesson = db.get_lesson(lesson_id)
    stored = lesson["metadata"]["writing_ai_review"]["0"]
    assert stored["missing"] == A_REVIEW["missing"]
    assert stored["concerns"] == A_REVIEW["concerns"]


def test_existing_review_reports_none_before_and_the_review_after(monkeypatch, db, student):
    lesson_id = _lesson(db, student["id"])
    assert writing_review.existing_review(db.get_lesson(lesson_id), 0) is None

    monkeypatch.setattr(
        writing_review, "generate_lesson", lambda **kwargs: dict(A_REVIEW)
    )
    writing_review.review_writing(db, student, db.get_lesson(lesson_id), 0, "Response.")

    assert writing_review.existing_review(db.get_lesson(lesson_id), 0) is not None
    # ...and only for the activity actually reviewed.
    assert writing_review.existing_review(db.get_lesson(lesson_id), 1) is None


def test_it_runs_on_the_cheap_review_model_not_the_lesson_model(monkeypatch, db, student):
    lesson_id = _lesson(db, student["id"])
    seen = {}

    def fake(**kwargs):
        seen.update(kwargs)
        return dict(A_REVIEW)

    monkeypatch.setattr(writing_review, "generate_lesson", fake)
    writing_review.review_writing(db, student, db.get_lesson(lesson_id), 0, "Response.")

    assert seen["model"] == config.REVIEW_MODEL
    assert seen["model"] != config.DEFAULT_MODEL


def test_the_cost_tracking_row_is_completed_so_it_never_looks_like_homework(
    monkeypatch, db, student
):
    """The bookkeeping row exists only so the Costs page counts this call.
    Every "what's still open" list in the app keys off status == planned, so
    it must not land there -- otherwise reviewing his own work would post a
    fake lesson to his home page."""
    lesson_id = _lesson(db, student["id"])
    monkeypatch.setattr(
        writing_review, "generate_lesson", lambda **kwargs: dict(A_REVIEW)
    )
    writing_review.review_writing(db, student, db.get_lesson(lesson_id), 0, "Response.")

    rows = [
        l for l in db.list_lessons(student["id"])
        if l["agent"] == writing_review.AGENT_KEY
    ]
    assert len(rows) == 1
    assert rows[0]["status"] == "completed"


# --- the button, end to end ------------------------------------------------------


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


def _seed_page_db(tmp_path, *, with_review=False, response="A first draft response."):
    db_path = tmp_path / "a.db"
    database = Database(db_path)
    student = database.ensure_default_student()
    auth.set_pin(database, "1234")
    lesson_id = database.save_lesson(
        student_id=student["id"], agent="english", subject="english", topic="t",
        title="41 Signatures on a Boat", payload=_payload(),
    )
    if response:
        database.save_writing_response(lesson_id, 0, response)
    if with_review:
        database.save_writing_ai_review(lesson_id, 0, dict(A_REVIEW))
    database.close()
    return db_path, lesson_id


def test_the_check_button_is_offered_before_any_review_exists(monkeypatch, tmp_path):
    db_path, lesson_id = _seed_page_db(tmp_path)
    at = _open(monkeypatch, db_path, ENGLISH_PATH, as_parent=False)
    assert any("Check my work" in (b.label or "") for b in at.button)


def test_the_check_button_is_gone_once_a_review_exists(monkeypatch, tmp_path):
    """One call per activity, ever -- the whole point of the gate."""
    db_path, lesson_id = _seed_page_db(tmp_path, with_review=True)
    at = _open(monkeypatch, db_path, ENGLISH_PATH, as_parent=False)
    assert not any("Check my work" in (b.label or "") for b in at.button)


def test_no_check_button_on_an_empty_response(monkeypatch, tmp_path):
    db_path, lesson_id = _seed_page_db(tmp_path, response="")
    at = _open(monkeypatch, db_path, ENGLISH_PATH, as_parent=False)
    assert not any("Check my work" in (b.label or "") for b in at.button)


def test_his_view_shows_strengths_and_next_moves_but_not_the_diagnostic(
    monkeypatch, tmp_path
):
    """He gets what's working plus at most two next moves. The list of
    everything missing, and any factual correction, is the parent's view --
    a wall of corrections is what makes him quit."""
    db_path, lesson_id = _seed_page_db(tmp_path, with_review=True)
    at = _open(monkeypatch, db_path, ENGLISH_PATH, as_parent=False)

    shown = " ".join(
        [s.value for s in at.success] + [i.value for i in at.info]
        + [w.value for w in at.warning] + [m.value for m in at.markdown]
    )
    assert A_REVIEW["strengths"][0] in shown
    assert A_REVIEW["next_moves"][0] in shown
    assert A_REVIEW["concerns"][0] not in shown
    assert A_REVIEW["missing"][0] not in shown


def test_his_next_moves_read_as_rework_not_as_a_neutral_note(monkeypatch, tmp_path):
    """A plain arrow in a blue info box reads as "here's a thought" -- these
    are the whole reason the read exists, so they carry the same 🔁 "needs
    more work" mark the assessment verdicts use, in amber."""
    db_path, lesson_id = _seed_page_db(tmp_path, with_review=True)
    at = _open(monkeypatch, db_path, ENGLISH_PATH, as_parent=False)

    # Streamlit lifts a leading emoji out of an alert's body into its own
    # `icon` field, so the mark is asserted there rather than in `.value`.
    moves = [w for w in at.warning if A_REVIEW["next_moves"][0] in w.value]
    assert moves, "next moves should render as a warning, not an info note"
    assert moves[0].icon == "🔁"
    assert "Go fix this" in moves[0].value


def test_the_parent_card_shows_the_full_diagnostic(monkeypatch, tmp_path):
    db_path, lesson_id = _seed_page_db(tmp_path, with_review=True)
    at = _open(monkeypatch, db_path, ACTIVITY_LOG_PATH, as_parent=True)

    shown = " ".join(
        [m.value for m in at.markdown] + [w.value for w in at.warning]
    )
    assert A_REVIEW["concerns"][0] in shown
    assert A_REVIEW["missing"][0] in shown


def test_reviewing_never_approves_or_submits_on_its_own(monkeypatch, tmp_path):
    """The hard guardrail: an automated read is advisory. It must not move
    the response out of draft -- only he can submit, only a parent approves."""
    db_path, lesson_id = _seed_page_db(tmp_path, with_review=True)
    database = Database(db_path)
    lesson = database.get_lesson(lesson_id)
    database.close()
    assert (lesson["metadata"].get("writing_review") or {}) == {}
