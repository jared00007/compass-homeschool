"""The submit-and-review gate: he turns a whole lesson in, a parent
approves or sends it back, and nothing new shows for that subject until
it's resolved.

Built because logging hours and "he says he's done" used to be two
completely disconnected signals -- a lesson could sit self-reported-done
for days with nobody told anything needed reviewing. `db.submit_lesson`
is now the single event that both (streak-eligible) and (waiting on a
parent) come from, and `render_assessment_card`'s Approve action is the
single event that both grades the lesson and logs its hours.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from compass import auth, config
from compass.storage.db import Database

REPO_ROOT = Path(__file__).resolve().parent.parent
HOME_PATH = str(REPO_ROOT / "Home.py")
MATH_PATH = str(REPO_ROOT / "pages" / "1_Math.py")
ENGLISH_PATH = str(REPO_ROOT / "pages" / "3_English.py")
ACTIVITY_LOG_PATH = str(REPO_ROOT / "pages" / "10_Activity_Log.py")


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "gate.db")
    yield database
    database.close()


@pytest.fixture()
def student(db):
    return db.ensure_default_student()


def _open(monkeypatch, db_path, page_path, *, as_parent):
    # A PIN is what makes is_parent() default to False -- callers with
    # as_parent=False must call auth.set_pin(db, "1234") on their own `db`
    # before closing it, same convention every other page-test file uses.
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


# --- db.submit_lesson / db.send_lesson_back -------------------------------------


def _lesson(db, student_id, agent="english", **payload_overrides) -> int:
    payload = {"title": "t", "activities": []}
    payload.update(payload_overrides)
    return db.save_lesson(
        student_id=student_id, agent=agent, subject=agent, topic="t", title="t", payload=payload,
    )


def test_submit_lesson_stamps_done_and_sets_submitted(db, student):
    lesson_id = _lesson(db, student["id"])
    db.submit_lesson(lesson_id)
    lesson = db.get_lesson(lesson_id)
    assert lesson["status"] == "submitted"
    assert lesson["metadata"]["student_done_on"]


def test_send_lesson_back_sets_needs_revision(db, student):
    lesson_id = _lesson(db, student["id"])
    db.submit_lesson(lesson_id)
    db.send_lesson_back(lesson_id, "Redo the second part.")
    lesson = db.get_lesson(lesson_id)
    assert lesson["status"] == "needs_revision"
    assert lesson["metadata"]["lesson_feedback"] == "Redo the second part."
    assert lesson["metadata"]["lesson_feedback_history"] == ["Redo the second part."]


def test_a_second_lesson_level_bounce_keeps_the_first_note_too(db, student):
    lesson_id = _lesson(db, student["id"])
    db.submit_lesson(lesson_id)
    db.send_lesson_back(lesson_id, "Redo the second part.")
    db.submit_lesson(lesson_id)  # he turns it in again
    db.send_lesson_back(lesson_id, "Also fix the conclusion.")

    lesson = db.get_lesson(lesson_id)
    assert lesson["metadata"]["lesson_feedback"] == "Also fix the conclusion."
    assert lesson["metadata"]["lesson_feedback_history"] == [
        "Redo the second part.",
        "Also fix the conclusion.",
    ]


def test_send_lesson_back_with_no_feedback_leaves_it_unset(db, student):
    """The per-activity writing bounce calls this with no feedback text --
    that activity already carries its own, so there's nothing generic
    worth adding at the lesson level."""
    lesson_id = _lesson(db, student["id"])
    db.submit_lesson(lesson_id)
    db.send_lesson_back(lesson_id)
    lesson = db.get_lesson(lesson_id)
    assert lesson["status"] == "needs_revision"
    assert "lesson_feedback" not in lesson["metadata"]


def test_an_invalid_status_is_still_rejected(db, student):
    lesson_id = _lesson(db, student["id"])
    with pytest.raises(ValueError):
        db.set_lesson_status(lesson_id, "bogus")


# --- migration backfill -----------------------------------------------------------


def test_old_self_reported_done_but_unlogged_becomes_submitted(tmp_path):
    """The exact bug that motivated this feature: a lesson he'd marked done
    under the old rules, sitting unlogged, must land in the new review
    queue rather than silently reappearing as his current lesson."""
    import json
    import sqlite3

    db_path = tmp_path / "old.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        "CREATE TABLE students (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "name TEXT NOT NULL DEFAULT 'Student', grade TEXT NOT NULL DEFAULT '8');"
        "INSERT INTO students (id) VALUES (1);"
        "CREATE TABLE lessons ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,"
        "agent TEXT NOT NULL, subject TEXT NOT NULL, topic TEXT NOT NULL, title TEXT NOT NULL,"
        "strategy TEXT NOT NULL DEFAULT '', rationale TEXT NOT NULL DEFAULT '',"
        "payload TEXT NOT NULL, metadata TEXT NOT NULL DEFAULT '{}',"
        "status TEXT NOT NULL DEFAULT 'planned' CHECK (status IN ('planned','completed','skipped')),"
        "created_at TEXT NOT NULL DEFAULT (datetime('now'))"
        ");"
    )
    conn.execute(
        "INSERT INTO lessons (student_id, agent, subject, topic, title, payload, metadata, status) "
        "VALUES (1,'english','english','t','Old','{}', ?, 'planned')",
        (json.dumps({"student_done_on": "2026-08-20"}),),
    )
    conn.execute(
        "INSERT INTO lessons (student_id, agent, subject, topic, title, payload, metadata, status) "
        "VALUES (1,'math','math','t','Untouched','{}', '{}', 'planned')"
    )
    conn.commit()
    conn.close()

    db = Database(db_path)
    lessons = {l["title"]: l for l in db.list_lessons(1)}
    db.close()
    assert lessons["Old"]["status"] == "submitted"
    assert lessons["Untouched"]["status"] == "planned"


# --- readiness: what "Turn it in" actually requires ------------------------------


def test_ready_with_no_quiz_and_no_writing():
    from compass.ui import _lesson_ready_to_submit

    lesson = {"payload": {"activities": []}, "metadata": {}}
    assert _lesson_ready_to_submit(lesson) == (True, "")


def test_not_ready_until_the_quiz_is_taken():
    from compass.ui import _lesson_ready_to_submit

    lesson = {"payload": {"activities": [], "quiz": [{"question": "?"}]}, "metadata": {}}
    ready, why = _lesson_ready_to_submit(lesson)
    assert ready is False
    assert "quiz" in why.lower()


def test_ready_once_the_quiz_has_a_result():
    from compass.ui import _lesson_ready_to_submit

    lesson = {
        "payload": {"activities": [], "quiz": [{"question": "?"}]},
        "metadata": {"quiz_result": {"correct": 1, "total": 1}},
    }
    assert _lesson_ready_to_submit(lesson) == (True, "")


def test_not_ready_until_a_writing_activity_is_submitted():
    from compass.ui import _lesson_ready_to_submit

    lesson = {
        "payload": {"activities": [{"kind": "writing", "title": "Essay"}]},
        "metadata": {},
    }
    ready, why = _lesson_ready_to_submit(lesson)
    assert ready is False
    assert "written response" in why.lower()


def test_ready_once_the_writing_activity_is_submitted():
    from compass.ui import _lesson_ready_to_submit

    lesson = {
        "payload": {"activities": [{"kind": "writing", "title": "Essay"}]},
        "metadata": {"writing_review": {"0": {"status": config.WRITING_SUBMITTED}}},
    }
    assert _lesson_ready_to_submit(lesson) == (True, "")


# --- student_lesson_view: the gate itself, end to end ----------------------------


def _writing_lesson_payload():
    return {
        "title": "Essay",
        "overview": "",
        "activities": [
            {"title": "Essay", "kind": "writing", "minutes": 20,
             "instructions": "Write it.",
             "video": {"found": False, "title": "", "url": "", "channel": "", "why": ""}},
        ],
        "materials": [], "subject_credits": [], "branches": [],
    }


def test_a_submitted_lesson_blocks_a_batch_planned_future_lesson(monkeypatch, tmp_path):
    """Regression for the exact design goal: even if a parent has already
    batch-planned days ahead, nothing new shows for this subject until the
    one he's turned in is resolved."""
    db_path = tmp_path / "a.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    today_id = db.save_lesson(
        student_id=student["id"], agent="math", subject="math", topic="t",
        title="Today's lesson", payload={"title": "Today's lesson", "activities": []},
    )
    db.save_lesson(
        student_id=student["id"], agent="math", subject="math", topic="t",
        title="Tomorrow's lesson", payload={"title": "Tomorrow's lesson", "activities": []},
        metadata={"planned_for": "2099-01-01"},  # far enough out to never be "overdue"
    )
    db.submit_lesson(today_id)
    auth.set_pin(db, "1234")
    db.close()

    at = _open(monkeypatch, db_path, MATH_PATH, as_parent=False)
    text = "\n".join(m.value for m in at.markdown) + "\n".join(i.value for i in at.info)
    assert "Today's lesson" in text
    assert "Tomorrow's lesson" not in text
    assert "waiting on your parent" in text.lower()


def test_a_sent_back_lesson_reopens_with_feedback(monkeypatch, tmp_path):
    db_path = tmp_path / "a.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="english", subject="english", topic="t",
        title="Essay", payload=_writing_lesson_payload(),
    )
    db.submit_lesson(lesson_id)
    db.send_lesson_back(lesson_id, "Add more detail to your second paragraph.")
    auth.set_pin(db, "1234")
    db.close()

    at = _open(monkeypatch, db_path, ENGLISH_PATH, as_parent=False)
    text = "\n".join(w.value for w in at.warning)
    assert "Add more detail to your second paragraph." in text
    assert "Essay" in "\n".join(m.value for m in at.markdown)


def test_turn_it_in_is_disabled_until_ready(monkeypatch, tmp_path):
    db_path = tmp_path / "a.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    db.save_lesson(
        student_id=student["id"], agent="english", subject="english", topic="t",
        title="Essay", payload=_writing_lesson_payload(),
    )
    auth.set_pin(db, "1234")
    db.close()

    at = _open(monkeypatch, db_path, ENGLISH_PATH, as_parent=False)
    submit_button = [b for b in at.button if "Turn it in for review" in (b.label or "")][0]
    assert submit_button.proto.disabled is True
    caption_text = "\n".join(c.value for c in at.caption)
    assert "written response" in caption_text.lower()


def test_turning_it_in_blocks_further_edits(monkeypatch, tmp_path):
    db_path = tmp_path / "a.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="english", subject="english", topic="t",
        title="Essay", payload=_writing_lesson_payload(),
    )
    db.save_writing_response(lesson_id, 0, "A response comfortably past any word minimum.")
    db.set_writing_review(lesson_id, 0, config.WRITING_SUBMITTED)
    auth.set_pin(db, "1234")
    db.close()

    at = _open(monkeypatch, db_path, ENGLISH_PATH, as_parent=False)
    submit_button = [b for b in at.button if "Turn it in for review" in (b.label or "")][0]
    assert submit_button.proto.disabled is False
    submit_button.click().run()
    assert not at.exception, [e.message for e in at.exception]

    db2 = Database(db_path)
    lesson = db2.get_lesson(lesson_id)
    db2.close()
    assert lesson["status"] == "submitted"

    at2 = _open(monkeypatch, db_path, ENGLISH_PATH, as_parent=False)
    text = "\n".join(i.value for i in at2.info)
    assert "waiting on your parent" in text.lower()
    assert not any("Turn it in for review" in (b.label or "") for b in at2.button)


# --- render_assessment_card: approve folds in logging the hours ------------------


def test_approving_a_non_math_lesson_logs_hours_in_the_same_click(monkeypatch, tmp_path):
    db_path = tmp_path / "a.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="science", subject="science", topic="t",
        title="Volcanoes",
        payload={
            "title": "Volcanoes", "activities": [],
            "assessment": {"kind": "check", "description": "d", "mastery_criteria": "m"},
            "estimated_minutes": 45, "subject_credits": [],
        },
    )
    db.submit_lesson(lesson_id)
    db.close()

    at = _open(monkeypatch, db_path, ACTIVITY_LOG_PATH, as_parent=True)
    radio = [r for r in at.radio if r.label == "How'd it go?"][0]
    radio.set_value(config.ASSESSMENT_SOLID).run()
    minutes = [n for n in at.number_input if n.label == "Total minutes"][0]
    minutes.set_value(45).run()
    approve = [b for b in at.button if "Approve" in (b.label or "")][0]
    approve.click().run()
    assert not at.exception, [e.message for e in at.exception]

    db2 = Database(db_path)
    lesson = db2.get_lesson(lesson_id)
    activities = db2.list_activities(student["id"])
    db2.close()
    assert lesson["status"] == "completed"
    assert lesson["metadata"]["assessment_result"]["verdict"] == "solid"
    assert len(activities) == 1
    assert activities[0]["minutes"] == 45


def test_sending_back_does_not_log_any_hours(monkeypatch, tmp_path):
    db_path = tmp_path / "a.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="science", subject="science", topic="t",
        title="Volcanoes",
        payload={
            "title": "Volcanoes", "activities": [],
            "assessment": {"kind": "check", "description": "d", "mastery_criteria": "m"},
        },
    )
    db.submit_lesson(lesson_id)
    db.close()

    at = _open(monkeypatch, db_path, ACTIVITY_LOG_PATH, as_parent=True)
    bounce = [b for b in at.button if "Send back" in (b.label or "")][0]
    bounce.click().run()
    assert not at.exception, [e.message for e in at.exception]

    db2 = Database(db_path)
    lesson = db2.get_lesson(lesson_id)
    activities = db2.list_activities(student["id"])
    db2.close()
    assert lesson["status"] == "needs_revision"
    assert activities == []


def test_the_lesson_wide_decision_waits_for_writing_to_be_approved_first(monkeypatch, tmp_path):
    """A lesson with both a pending writing activity and an assessment
    verdict shouldn't offer two different "send it back" buttons for the
    same lesson at once -- grade the writing piece first."""
    db_path = tmp_path / "a.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    payload = _writing_lesson_payload()
    payload["assessment"] = {"kind": "check", "description": "d", "mastery_criteria": "m"}
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="english", subject="english", topic="t",
        title="Essay", payload=payload,
    )
    db.save_writing_response(lesson_id, 0, "His response.")
    db.set_writing_review(lesson_id, 0, config.WRITING_SUBMITTED)
    db.submit_lesson(lesson_id)
    db.close()

    at = _open(monkeypatch, db_path, ACTIVITY_LOG_PATH, as_parent=True)
    assert not any(r.label == "How'd it go?" for r in at.radio)
    text = "\n".join(c.value for c in at.caption)
    assert "approve his response above" in text.lower()


# --- Activity Log's queue ----------------------------------------------------------


def test_a_submitted_lesson_counts_as_needing_attention(monkeypatch, tmp_path):
    db_path = tmp_path / "a.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="math", subject="math", topic="t",
        title="Fractions", payload={"title": "Fractions", "activities": []},
    )
    db.submit_lesson(lesson_id)
    db.close()

    at = _open(monkeypatch, db_path, ACTIVITY_LOG_PATH, as_parent=True)
    review_tab = [t for t in at.tabs if t.label.startswith("To review")][0]
    markdowns = [m.value for m in review_tab.markdown]
    assert any("Needs your attention now" in m and "(1)" in m for m in markdowns)


def test_a_sent_back_lesson_gets_its_own_quiet_section(monkeypatch, tmp_path):
    db_path = tmp_path / "a.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="math", subject="math", topic="t",
        title="Fractions", payload={"title": "Fractions", "activities": []},
    )
    db.submit_lesson(lesson_id)
    db.send_lesson_back(lesson_id, "Try again.")
    db.close()

    at = _open(monkeypatch, db_path, ACTIVITY_LOG_PATH, as_parent=True)
    review_tab = [t for t in at.tabs if t.label.startswith("To review")][0]
    markdowns = [m.value for m in review_tab.markdown]
    assert any("Sent back" in m and "waiting on him" in m for m in markdowns)
    assert not any("Needs your attention now" in m and "(1)" in m for m in markdowns)


def test_a_graded_subject_lesson_never_shows_the_plain_log_hours_form(monkeypatch, tmp_path):
    """Hours for Math/Science/English/History now only ever get logged
    through the combined Approve action -- the old standalone form would
    let a parent log hours for a lesson he hasn't even turned in yet."""
    db_path = tmp_path / "a.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    db.save_lesson(
        student_id=student["id"], agent="math", subject="math", topic="t",
        title="Fractions", payload={"title": "Fractions", "activities": []},
    )
    db.close()

    at = _open(monkeypatch, db_path, ACTIVITY_LOG_PATH, as_parent=True)
    assert not any(b.label == "Log hours" for b in at.button)


def test_a_life_skill_lesson_still_gets_the_plain_log_hours_form(monkeypatch, tmp_path):
    """Life Skills never goes through the submit/review gate at all --
    this must keep working exactly as it always has."""
    db_path = tmp_path / "a.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    db.save_lesson(
        student_id=student["id"], agent="life_skills", subject="occupational_education",
        topic="t", title="Do laundry", payload={"title": "Do laundry", "activities": []},
    )
    db.close()

    at = _open(monkeypatch, db_path, ACTIVITY_LOG_PATH, as_parent=True)
    assert any(b.label == "Log hours" for b in at.button)
