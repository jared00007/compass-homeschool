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
MISSION_CONTROL_PATH = str(REPO_ROOT / "pages" / "14_Mission_Control.py")


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


def test_ready_once_the_writing_activity_is_approved():
    from compass.ui import _lesson_ready_to_submit

    lesson = {
        "payload": {"activities": [{"kind": "writing", "title": "Essay"}]},
        "metadata": {"writing_review": {"0": {"status": config.WRITING_APPROVED}}},
    }
    assert _lesson_ready_to_submit(lesson) == (True, "")


def test_not_ready_while_a_bounced_writing_activity_hasnt_been_resubmitted():
    """A parent's "send back for revision" leaves the activity at
    needs_revision, not draft -- the lesson-level gate has to check for
    that too, or "Turn it in for review" comes back enabled the instant a
    bounce lands, with nothing actually revised or resubmitted."""
    from compass.ui import _lesson_ready_to_submit

    lesson = {
        "payload": {"activities": [{"kind": "writing", "title": "Essay"}]},
        "metadata": {"writing_review": {"0": {"status": config.WRITING_NEEDS_REVISION}}},
    }
    ready, why = _lesson_ready_to_submit(lesson)
    assert ready is False
    assert "written response" in why.lower()


# --- auto-turn-in: finishing the last piece hands the lesson in ------------------


def test_auto_submit_fires_once_the_last_writing_response_is_in(db, student):
    """The bug a parent hit: he'd submit his English writing, believe he'd
    handed the lesson in, and it would sit at 'planned' forever because the
    separate lesson-level button never got clicked. Submitting the last
    piece now turns the whole lesson in on its own."""
    from compass.ui import _maybe_auto_submit_lesson

    lesson_id = _lesson(
        db, student["id"],
        activities=[{"kind": "writing", "title": "Essay"}],
    )
    # Nothing submitted yet -> not ready -> stays planned.
    assert _maybe_auto_submit_lesson(db, lesson_id) is False
    assert db.get_lesson(lesson_id)["status"] == "planned"

    # He submits his one writing response; that's the last piece.
    db.set_writing_review(lesson_id, 0, config.WRITING_SUBMITTED)
    assert _maybe_auto_submit_lesson(db, lesson_id) is True
    lesson = db.get_lesson(lesson_id)
    assert lesson["status"] == "submitted"
    assert lesson["metadata"]["student_done_on"]


def test_auto_submit_waits_for_every_piece(db, student):
    """A lesson with two writing activities and a quiz doesn't go in until
    all of them are done -- whichever he finishes last is what trips it."""
    from compass.ui import _maybe_auto_submit_lesson

    lesson_id = _lesson(
        db, student["id"],
        activities=[
            {"kind": "writing", "title": "One"},
            {"kind": "writing", "title": "Two"},
        ],
        quiz=[{"question": "?"}],
    )
    db.set_writing_review(lesson_id, 0, config.WRITING_SUBMITTED)
    assert _maybe_auto_submit_lesson(db, lesson_id) is False
    db.set_writing_review(lesson_id, 1, config.WRITING_SUBMITTED)
    # Writing's all in, but the quiz still isn't.
    assert _maybe_auto_submit_lesson(db, lesson_id) is False
    db.record_quiz_result(lesson_id, student["id"], 1, 1, True)
    assert _maybe_auto_submit_lesson(db, lesson_id) is True
    assert db.get_lesson(lesson_id)["status"] == "submitted"


def test_auto_submit_leaves_an_already_resolved_lesson_alone(db, student):
    """It only ever acts on his own in-progress work. A lesson already
    turned in, approved, or bounced back to him isn't re-submitted out from
    under whatever state a parent put it in."""
    from compass.ui import _maybe_auto_submit_lesson

    lesson_id = _lesson(db, student["id"], activities=[])  # ready by shape
    db.submit_lesson(lesson_id)
    db.set_lesson_status(lesson_id, "completed")
    assert _maybe_auto_submit_lesson(db, lesson_id) is False
    assert db.get_lesson(lesson_id)["status"] == "completed"


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


def test_a_bounced_writing_activity_with_no_feedback_still_gets_a_warning(
    monkeypatch, tmp_path
):
    """A parent can send a writing activity back with the feedback box left
    blank -- send_lesson_back's own test (below) checks that's allowed at
    the lesson level. Either way, the activity itself must still visibly
    read as "sent back" to him, not silently fall through to a plain,
    unmarked draft box indistinguishable from one he simply hasn't started."""
    db_path = tmp_path / "a.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="english", subject="english", topic="t",
        title="Essay", payload=_writing_lesson_payload(),
    )
    db.submit_lesson(lesson_id)
    db.set_writing_review(lesson_id, 0, config.WRITING_NEEDS_REVISION, "")
    db.send_lesson_back(lesson_id)
    auth.set_pin(db, "1234")
    db.close()

    at = _open(monkeypatch, db_path, ENGLISH_PATH, as_parent=False)
    text = "\n".join(w.value for w in at.warning)
    assert "asked for another look" in text
    # And the draft box he's meant to revise is still right there.
    assert any(t.label == "Your response" for t in at.text_area)


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


def test_submitting_the_last_writing_response_turns_the_lesson_in(monkeypatch, tmp_path):
    """End to end through the real English page: he types his response and
    clicks the writing activity's own "Submit for review" -- the action he
    thinks of as finishing -- and the whole lesson lands in the parent's
    queue without him touching the separate lesson-level button."""
    db_path = tmp_path / "a.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="english", subject="english", topic="t",
        title="Essay", payload=_writing_lesson_payload(),
    )
    auth.set_pin(db, "1234")
    db.close()

    at = _open(monkeypatch, db_path, ENGLISH_PATH, as_parent=False)
    box = [t for t in at.text_area if t.label == "Your response"][0]
    box.set_value("A response that runs comfortably past any word minimum on the page.").run()
    submit = [b for b in at.button if b.label == "Submit for review"][0]
    submit.click().run()
    assert not at.exception, [e.message for e in at.exception]

    db2 = Database(db_path)
    lesson = db2.get_lesson(lesson_id)
    db2.close()
    assert lesson["status"] == "submitted"
    assert lesson["metadata"]["student_done_on"]


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


def test_the_review_card_shows_the_quiz_he_took(monkeypatch, tmp_path):
    """A parent reviewing a turned-in lesson can read the quiz the same way
    they read his writing: each question, the answer he picked, and the
    right one -- not just a one-line score."""
    db_path = tmp_path / "a.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="science", subject="science", topic="t",
        title="Volcanoes",
        payload={
            "title": "Volcanoes", "activities": [],
            "quiz": [
                {"question": "What is lava called underground?",
                 "choices": ["Magma", "Basalt"], "correct_index": 0},
                {"question": "Which plate boundary builds volcanoes?",
                 "choices": ["Transform", "Convergent"], "correct_index": 1},
            ],
        },
    )
    db.record_quiz_result(
        lesson_id, student["id"], 1, 2, False,
        detail=[
            {"question": "What is lava called underground?",
             "choices": ["Magma", "Basalt"], "correct_index": 0, "pick": 0,
             "explanation": "Underground it's magma; above ground, lava."},
            {"question": "Which plate boundary builds volcanoes?",
             "choices": ["Transform", "Convergent"], "correct_index": 1, "pick": 0,
             "explanation": "Convergent boundaries force one plate under another."},
        ],
    )
    db.submit_lesson(lesson_id)
    db.close()

    at = _open(monkeypatch, db_path, MISSION_CONTROL_PATH, as_parent=True)
    # Each question is a per-question expander, marked ✅/❌ so a parent can
    # scan which he missed; the question text lives in that label.
    labels = "\n".join(e.label for e in at.get("expander"))
    assert "What is lava called underground?" in labels
    assert "Which plate boundary builds volcanoes?" in labels
    blob = "\n".join(m.value for m in at.markdown)
    # His pick and the right answer are both labelled, so a parent can see
    # exactly what he chose on the one he missed.
    assert "his answer" in blob.lower()
    assert "correct answer" in blob.lower()
    # And the headline score is right there too.
    assert "1/2" in blob


def test_the_review_card_shows_the_lesson_body_he_read(monkeypatch, tmp_path):
    """Reviewing his work, a parent can open the actual lesson -- its
    activities and instructions -- the same content he read, not just the
    overview and his answers. The answer-key material a student never sees
    (here, lesson-level parent_notes) stays hidden inside that view too, so
    it really is his screen."""
    db_path = tmp_path / "a.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="science", subject="science", topic="t",
        title="Volcanoes",
        payload={
            "title": "Volcanoes", "overview": "o",
            "activities": [
                {"title": "Read about magma", "kind": "reading", "minutes": 10,
                 "instructions": "UNIQUEINSTRUCTIONXYZ — read chapter four closely.",
                 "video": {"found": False, "title": "", "url": "", "channel": "", "why": ""}},
            ],
            "parent_notes": "PARENTONLYNOTE watch for the magma/lava mixup.",
        },
    )
    db.submit_lesson(lesson_id)
    db.close()

    at = _open(monkeypatch, db_path, MISSION_CONTROL_PATH, as_parent=True)
    blob = "\n".join(m.value for m in at.markdown)
    # The lesson body renders inline in the review now, not behind an
    # expander -- the activity he read is right there.
    assert "UNIQUEINSTRUCTIONXYZ" in blob
    # Rendered as his screen -- the parent-only note is not in that view.
    assert "PARENTONLYNOTE" not in blob


def test_the_review_is_inline_content_response_and_controls_together(monkeypatch, tmp_path):
    """The whole point of the inline review: the activity he read, his
    response to it, and the approve/send-back control all sit together, and
    his response shows exactly once (not once in a lesson preview and again
    in a separate grading panel)."""
    db_path = tmp_path / "a.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="english", subject="english", topic="t",
        title="Essay",
        payload={
            "title": "Essay", "overview": "o",
            "activities": [
                {"title": "Essay", "kind": "writing", "minutes": 20,
                 "instructions": "INLINEINSTRUCTION write your paragraph.",
                 "video": {"found": False, "title": "", "url": "", "channel": "", "why": ""}},
            ],
        },
    )
    db.save_writing_response(lesson_id, 0, "HISUNIQUERESPONSE about the topic.")
    db.set_writing_review(lesson_id, 0, config.WRITING_SUBMITTED)
    db.submit_lesson(lesson_id)
    db.close()

    at = _open(monkeypatch, db_path, MISSION_CONTROL_PATH, as_parent=True)
    blob = "\n".join(m.value for m in at.markdown)
    # Activity content and his response are both on the page...
    assert "INLINEINSTRUCTION" in blob
    assert "HISUNIQUERESPONSE" in blob
    # ...his response exactly once (no duplicate preview + grading copy)...
    assert blob.count("HISUNIQUERESPONSE") == 1
    # ...and the per-activity approve control is right there to act on.
    assert any(b.label == "✅ Approve" for b in at.button)


# --- render_lesson_review: approve folds in logging the hours --------------------


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

    at = _open(monkeypatch, db_path, MISSION_CONTROL_PATH, as_parent=True)
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

    at = _open(monkeypatch, db_path, MISSION_CONTROL_PATH, as_parent=True)
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

    at = _open(monkeypatch, db_path, MISSION_CONTROL_PATH, as_parent=True)
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

    at = _open(monkeypatch, db_path, MISSION_CONTROL_PATH, as_parent=True)
    review_tab = [t for t in at.tabs if t.label.startswith("✅ Review")][0]
    markdowns = [m.value for m in review_tab.markdown]
    assert any("Turned in — waiting on you" in m and "(1)" in m for m in markdowns)


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

    at = _open(monkeypatch, db_path, MISSION_CONTROL_PATH, as_parent=True)
    review_tab = [t for t in at.tabs if t.label.startswith("✅ Review")][0]
    markdowns = [m.value for m in review_tab.markdown]
    assert any("Sent back" in m and "waiting on him" in m for m in markdowns)
    # A sent-back lesson is waiting on him, not counted as waiting on you.
    assert any("Turned in — waiting on you (0)" in m for m in markdowns)


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

    at = _open(monkeypatch, db_path, MISSION_CONTROL_PATH, as_parent=True)
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

    at = _open(monkeypatch, db_path, MISSION_CONTROL_PATH, as_parent=True)
    assert any(b.label == "Log hours" for b in at.button)
