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


# --- writing response version history ------------------------------------------------


def test_every_save_is_kept_as_its_own_version(db, student):
    lesson_id = _lesson(db, student["id"])
    db.save_writing_response(lesson_id, 0, "Draft one.")
    db.save_writing_response(lesson_id, 0, "Draft two.")
    db.save_writing_response(lesson_id, 0, "Final version.")

    versions = db.list_writing_response_versions(lesson_id, 0)
    assert [v["text"] for v in versions] == ["Draft one.", "Draft two.", "Final version."]


def test_versions_are_scoped_to_their_own_activity(db, student):
    lesson_id = _lesson(db, student["id"])
    db.save_writing_response(lesson_id, 0, "First activity's draft.")
    db.save_writing_response(lesson_id, 1, "Second activity's draft.")

    assert [v["text"] for v in db.list_writing_response_versions(lesson_id, 0)] == [
        "First activity's draft."
    ]
    assert [v["text"] for v in db.list_writing_response_versions(lesson_id, 1)] == [
        "Second activity's draft."
    ]


def test_versions_are_scoped_to_their_own_lesson(db, student):
    lesson_a = _lesson(db, student["id"])
    lesson_b = _lesson(db, student["id"])
    db.save_writing_response(lesson_a, 0, "Lesson A's draft.")
    db.save_writing_response(lesson_b, 0, "Lesson B's draft.")

    assert [v["text"] for v in db.list_writing_response_versions(lesson_a, 0)] == [
        "Lesson A's draft."
    ]


def test_a_single_save_produces_exactly_one_version(db, student):
    lesson_id = _lesson(db, student["id"])
    db.save_writing_response(lesson_id, 0, "Only draft.")

    assert len(db.list_writing_response_versions(lesson_id, 0)) == 1


def test_no_saves_yet_means_no_versions(db, student):
    lesson_id = _lesson(db, student["id"])
    assert db.list_writing_response_versions(lesson_id, 0) == []


def test_saving_a_response_preserves_other_metadata_already_there(db, student):
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="math", subject="math", topic="t", title="t",
        payload={}, metadata={"skill_id": "two-step-equations"},
    )
    db.save_writing_response(lesson_id, 0, "text")

    lesson = db.get_lesson(lesson_id)
    assert lesson["metadata"]["skill_id"] == "two-step-equations"


# --- writing review: draft -> submitted -> parent decision ---------------------------


def test_a_response_defaults_to_draft_status(db, student):
    lesson_id = _lesson(db, student["id"])
    lesson = db.get_lesson(lesson_id)
    assert (lesson["metadata"].get("writing_review") or {}) == {}


def test_setting_a_review_status_is_readable_back(db, student):
    lesson_id = _lesson(db, student["id"])
    db.set_writing_review(lesson_id, 0, "submitted")

    lesson = db.get_lesson(lesson_id)
    assert lesson["metadata"]["writing_review"]["0"] == {
        "status": "submitted", "feedback": "", "feedback_history": [],
    }


def test_sending_back_for_revision_carries_the_feedback(db, student):
    lesson_id = _lesson(db, student["id"])
    db.set_writing_review(lesson_id, 0, "needs_revision", "Add a quote from the text.")

    lesson = db.get_lesson(lesson_id)
    review = lesson["metadata"]["writing_review"]["0"]
    assert review["status"] == "needs_revision"
    assert review["feedback"] == "Add a quote from the text."
    assert review["feedback_history"] == ["Add a quote from the text."]


def test_a_second_bounce_keeps_the_first_notes_feedback_too(db, student):
    """The actual bug report: a second bounce used to silently overwrite
    the first note, so a student who'd fixed the first thing but not the
    second lost the very feedback explaining the first."""
    lesson_id = _lesson(db, student["id"])
    db.set_writing_review(lesson_id, 0, "needs_revision", "Add a quote from the text.")
    db.set_writing_review(lesson_id, 0, "submitted")  # he resubmits
    db.set_writing_review(lesson_id, 0, "needs_revision", "Now the intro needs work too.")

    lesson = db.get_lesson(lesson_id)
    review = lesson["metadata"]["writing_review"]["0"]
    assert review["feedback"] == "Now the intro needs work too."  # the latest, on its own
    assert review["feedback_history"] == [
        "Add a quote from the text.",
        "Now the intro needs work too.",
    ]


def test_a_resubmit_with_no_new_feedback_does_not_touch_the_history(db, student):
    lesson_id = _lesson(db, student["id"])
    db.set_writing_review(lesson_id, 0, "needs_revision", "Add a quote from the text.")
    db.set_writing_review(lesson_id, 0, "submitted")  # no feedback on a plain status change

    review = db.get_lesson(lesson_id)["metadata"]["writing_review"]["0"]
    assert review["feedback_history"] == ["Add a quote from the text."]


def test_review_status_is_tracked_independently_per_activity(db, student):
    lesson_id = _lesson(db, student["id"])
    db.set_writing_review(lesson_id, 0, "approved")
    db.set_writing_review(lesson_id, 1, "needs_revision", "Too short.")

    lesson = db.get_lesson(lesson_id)
    assert lesson["metadata"]["writing_review"]["0"]["status"] == "approved"
    assert lesson["metadata"]["writing_review"]["1"]["status"] == "needs_revision"


def test_an_invalid_status_is_rejected(db, student):
    lesson_id = _lesson(db, student["id"])
    with pytest.raises(ValueError):
        db.set_writing_review(lesson_id, 0, "not_a_real_status")


def test_setting_review_status_preserves_other_metadata_already_there(db, student):
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="math", subject="math", topic="t", title="t",
        payload={}, metadata={"skill_id": "two-step-equations"},
    )
    db.set_writing_review(lesson_id, 0, "submitted")

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


# --- per-activity grades (the new fixed lesson shape) --------------------------


def test_a_recorded_activity_grade_is_readable_back(db, student):
    lesson_id = _lesson(db, student["id"])
    db.record_activity_grade(lesson_id, 0, "solid", notes="Clear reasoning.")

    result = db.get_lesson(lesson_id)["metadata"]["activity_results"]["0"]
    assert result["verdict"] == "solid"
    assert result["notes"] == "Clear reasoning."
    assert result["assessed_on"]


def test_two_activities_are_graded_independently(db, student):
    lesson_id = _lesson(db, student["id"])
    db.record_activity_grade(lesson_id, 0, "nailed_it")
    db.record_activity_grade(lesson_id, 1, "not_yet")

    results = db.get_lesson(lesson_id)["metadata"]["activity_results"]
    assert results["0"]["verdict"] == "nailed_it"
    assert results["1"]["verdict"] == "not_yet"


def test_re_grading_one_activity_leaves_the_other_untouched(db, student):
    lesson_id = _lesson(db, student["id"])
    db.record_activity_grade(lesson_id, 0, "getting_there")
    db.record_activity_grade(lesson_id, 1, "solid")
    db.record_activity_grade(lesson_id, 0, "nailed_it")  # re-grade only activity 0

    results = db.get_lesson(lesson_id)["metadata"]["activity_results"]
    assert results["0"]["verdict"] == "nailed_it"
    assert results["1"]["verdict"] == "solid"


def test_an_invalid_activity_verdict_is_rejected(db, student):
    lesson_id = _lesson(db, student["id"])
    with pytest.raises(ValueError):
        db.record_activity_grade(lesson_id, 0, "great")


def test_recording_an_activity_grade_preserves_other_metadata_already_there(db, student):
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="science", subject="science", topic="t", title="t",
        payload={}, metadata={"web_node_id": 7},
    )
    db.record_activity_grade(lesson_id, 0, "getting_there")

    assert db.get_lesson(lesson_id)["metadata"]["web_node_id"] == 7
