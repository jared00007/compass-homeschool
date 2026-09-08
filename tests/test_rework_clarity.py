"""Which written piece needs work, made obvious on his side.

A lesson can carry several written answers and come back with only one or two
actually sent back for a redo. From the red "sent this back" banner alone he
couldn't tell which -- the fix here names the flagged pieces in the banner and
badges each one on its own activity card ("its hard for him to know which
actual activity has feedback/rework required. make that better UI please").
"""

from __future__ import annotations

from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from compass import auth, config
from compass.storage.db import Database
from compass.ui.comic import _comic_review_flag_html, _writing_rework_summary

REPO_ROOT = Path(__file__).resolve().parent.parent
HOME_PATH = str(REPO_ROOT / "Home.py")
ENGLISH_PATH = str(REPO_ROOT / "pages" / "3_English.py")


def _payload():
    """Three written activities so a flag on one has to stand out from two
    that are fine."""
    return {
        "title": "Three Short Answers",
        "activities": [
            {"title": "Analyze the Compact", "kind": "writing", "minutes": 15,
             "instructions": "Quote it once.", "requires_written_response": True},
            {"title": "Name a group left out", "kind": "writing", "minutes": 15,
             "instructions": "Name one group.", "requires_written_response": True},
            {"title": "Defend a judgment", "kind": "writing", "minutes": 15,
             "instructions": "Take a side.", "requires_written_response": True},
        ],
        "assessment": {"kind": "check", "description": "", "mastery_criteria": ""},
    }


# --- the helpers, in isolation ---------------------------------------------------


def test_summary_names_only_the_flagged_pieces_with_their_latest_note():
    metadata = {
        "writing_review": {
            "1": {"status": config.WRITING_NEEDS_REVISION,
                  "feedback_history": ["First pass.", "Still need one group."]},
        }
    }
    flagged = _writing_rework_summary(_payload()["activities"], metadata)
    assert [f["number"] for f in flagged] == [2]
    assert flagged[0]["title"] == "Name a group left out"
    # Newest note wins -- history is oldest-first.
    assert flagged[0]["note"] == "Still need one group."


def test_summary_is_empty_when_nothing_is_sent_back():
    metadata = {
        "writing_review": {
            "0": {"status": config.WRITING_APPROVED},
            "1": {"status": config.WRITING_SUBMITTED},
        }
    }
    assert _writing_rework_summary(_payload()["activities"], metadata) == []


def test_flag_badge_shows_for_a_redo_but_never_on_the_parent_side():
    metadata = {"writing_review": {"0": {"status": config.WRITING_NEEDS_REVISION}}}
    assert "Needs another look" in _comic_review_flag_html(0, metadata, parent=False)
    assert _comic_review_flag_html(0, metadata, parent=True) == ""


def test_flag_badge_marks_an_unread_approval_note_but_not_a_read_one():
    unread = {"writing_review": {"0": {
        "status": config.WRITING_APPROVED, "approval_feedback": "Nice work.",
        "approval_read_at": None}}}
    read = {"writing_review": {"0": {
        "status": config.WRITING_APPROVED, "approval_feedback": "Nice work.",
        "approval_read_at": "2026-01-01"}}}
    assert "A note to read" in _comic_review_flag_html(0, unread, parent=False)
    assert _comic_review_flag_html(0, read, parent=False) == ""


# --- end to end, on his English page ---------------------------------------------


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    yield database
    database.close()


def _seed_sent_back(tmp_path):
    """A lesson with three written answers, one of them (No. 2) sent back for a
    redo the same way a per-activity bounce does: flag the piece, then the whole
    lesson goes to needs_revision with no lesson-level note."""
    db_path = tmp_path / "a.db"
    database = Database(db_path)
    student = database.ensure_default_student()
    auth.set_pin(database, "1234")
    lesson_id = database.save_lesson(
        student_id=student["id"], agent="english", subject="english", topic="t",
        title="Three Short Answers", payload=_payload(),
    )
    for index in range(3):
        database.save_writing_response(lesson_id, index, f"Draft {index}.")
    database.set_writing_review(
        lesson_id, 1, config.WRITING_NEEDS_REVISION, "Name one group left out."
    )
    database.send_lesson_back(lesson_id)
    database.close()
    return db_path


def _open_student(monkeypatch, db_path):
    st.cache_resource.clear()
    monkeypatch.setattr(config, "DEFAULT_DB_PATH", db_path)
    at = AppTest.from_file(HOME_PATH)
    at.run(timeout=30)
    at.switch_page(ENGLISH_PATH)
    at.run(timeout=30)
    assert not at.exception, [e.message for e in at.exception]
    return at


def test_the_banner_names_the_specific_piece_that_needs_work(monkeypatch, tmp_path):
    at = _open_student(monkeypatch, _seed_sent_back(tmp_path))
    banner = " ".join(w.value for w in at.warning)
    assert "These pieces need another look" in banner
    assert "Name a group left out" in banner
    assert "Name one group left out." in banner
    # The two pieces that were fine are not dragged into the list.
    assert "Analyze the Compact" not in banner
    assert "Defend a judgment" not in banner


def test_the_flagged_activity_card_carries_the_badge(monkeypatch, tmp_path):
    at = _open_student(monkeypatch, _seed_sent_back(tmp_path))
    shown = " ".join(m.value for m in at.markdown)
    assert "Needs another look" in shown
