"""Digital assessment storage: a lesson's saved writing response(s), and the
parent's recorded check on the lesson (mastery for Math via `set_mastery`
directly; a lighter three-way verdict for everything else via
`record_assessment`). See compass.ui.render_assessment_card for how these
come together in the actual review flow.
"""

from __future__ import annotations

import pytest

from compass.storage.db import Database


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    yield database
    database.close()


@pytest.fixture()
def student(db):
    return db.ensure_default_student()


def _lesson(db, student_id, **overrides):
    payload = {"title": "Argue a Character's Choice", "activities": []}
    payload.update(overrides)
    return db.save_lesson(
        student_id=student_id, agent="english", subject="english", topic="t",
        title=payload["title"], payload=payload,
    )


# --- writing responses --------------------------------------------------------------


def test_a_saved_writing_response_is_readable_back(db, student):
    lesson_id = _lesson(db, student["id"])
    db.save_writing_response(lesson_id, 0, "My response to the prompt.")

    lesson = db.get_lesson(lesson_id)
    assert lesson["metadata"]["writing_responses"]["0"] == "My response to the prompt."


def test_saving_a_response_does_not_clobber_a_different_activitys_response(db, student):
    lesson_id = _lesson(db, student["id"])
    db.save_writing_response(lesson_id, 0, "First activity's response.")
    db.save_writing_response(lesson_id, 1, "Second activity's response.")

    lesson = db.get_lesson(lesson_id)
    responses = lesson["metadata"]["writing_responses"]
    assert responses["0"] == "First activity's response."
    assert responses["1"] == "Second activity's response."


def test_saving_again_overwrites_the_same_activitys_response(db, student):
    lesson_id = _lesson(db, student["id"])
    db.save_writing_response(lesson_id, 0, "Draft one.")
    db.save_writing_response(lesson_id, 0, "Final version.")

    lesson = db.get_lesson(lesson_id)
    assert lesson["metadata"]["writing_responses"]["0"] == "Final version."


def test_saving_a_response_preserves_other_metadata_already_there(db, student):
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="math", subject="math", topic="t", title="t",
        payload={}, metadata={"skill_id": "two-step-equations"},
    )
    db.save_writing_response(lesson_id, 0, "text")

    lesson = db.get_lesson(lesson_id)
    assert lesson["metadata"]["skill_id"] == "two-step-equations"


# --- assessment verdicts -------------------------------------------------------------


def test_a_recorded_assessment_is_readable_back(db, student):
    lesson_id = _lesson(db, student["id"])
    db.record_assessment(lesson_id, "nailed_it", notes="Great work today.")

    lesson = db.get_lesson(lesson_id)
    result = lesson["metadata"]["assessment_result"]
    assert result["verdict"] == "nailed_it"
    assert result["notes"] == "Great work today."
    assert result["assessed_on"]


def test_recording_again_replaces_the_previous_verdict(db, student):
    lesson_id = _lesson(db, student["id"])
    db.record_assessment(lesson_id, "needs_more_work")
    db.record_assessment(lesson_id, "nailed_it")

    lesson = db.get_lesson(lesson_id)
    assert lesson["metadata"]["assessment_result"]["verdict"] == "nailed_it"


def test_an_invalid_verdict_is_rejected(db, student):
    lesson_id = _lesson(db, student["id"])
    with pytest.raises(ValueError):
        db.record_assessment(lesson_id, "great")


def test_recording_an_assessment_preserves_other_metadata_already_there(db, student):
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="science", subject="science", topic="t", title="t",
        payload={}, metadata={"web_node_id": 7},
    )
    db.record_assessment(lesson_id, "getting_there")

    lesson = db.get_lesson(lesson_id)
    assert lesson["metadata"]["web_node_id"] == 7
