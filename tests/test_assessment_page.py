"""End-to-end: the digital assessment card in Activity Log's review flow,
and the in-lesson writing response box on a subject page.

Replaces the old "parent reads assessment text, then walks to a different
page and re-types a mastery record" flow -- Math's mastery form and a
lighter three-way verdict for everything else now live right where hours
get logged (Activity Log's own review card), and a writing activity gets an
actual text box instead of being something he writes on paper and nobody
in the app ever sees.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st
from streamlit.testing.v1 import AppTest

from compass import auth, config
from compass.storage.db import Database

REPO_ROOT = Path(__file__).resolve().parent.parent
HOME_PATH = str(REPO_ROOT / "Home.py")
MATH_PATH = str(REPO_ROOT / "pages" / "1_Math.py")
ENGLISH_PATH = str(REPO_ROOT / "pages" / "3_English.py")
ACTIVITY_LOG_PATH = str(REPO_ROOT / "pages" / "10_Activity_Log.py")


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


# --- the inline mastery form (Math) --------------------------------------------------


def _math_lesson(db, student_id, *, quiz_result=None):
    payload = {
        "title": "Two-Step Equations", "activities": [],
        "assessment": {"kind": "check", "description": "Ten items",
                        "mastery_criteria": "8 of 10"},
    }
    metadata = {"skill_id": "two-step-equations"}
    if quiz_result:
        metadata["quiz_result"] = quiz_result
    return db.save_lesson(
        student_id=student_id, agent="math", subject="math", topic="t",
        title="Two-Step Equations", payload=payload, metadata=metadata,
    )


def test_math_lesson_gets_the_approve_not_yet_choice_in_activity_log(monkeypatch, tmp_path):
    db_path = tmp_path / "a.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    lesson_id = _math_lesson(db, student["id"])
    db.submit_lesson(lesson_id)  # the decision only opens up once he's turned it in
    db.close()

    at = _open(monkeypatch, db_path, ACTIVITY_LOG_PATH, as_parent=True)
    labels = [b.label for b in at.button]
    assert any("Approve" in (l or "") for l in labels)
    assert any("Not yet" in (l or "") for l in labels)
    assert not any((s.label or "") == "Status" for s in at.selectbox)


def test_approving_records_mastery_at_the_actual_quiz_score(monkeypatch, tmp_path):
    db_path = tmp_path / "a.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    lesson_id = _math_lesson(db, student["id"], quiz_result={
        "correct": 4, "total": 5, "passed": True, "graded_on": "2026-08-25",
    })
    db.submit_lesson(lesson_id)
    db.close()

    at = _open(monkeypatch, db_path, ACTIVITY_LOG_PATH, as_parent=True)
    approve = [b for b in at.button if "Approve" in (b.label or "")][0]
    approve.click().run()
    assert not at.exception, [e.message for e in at.exception]

    db2 = Database(db_path)
    mastery = db2.mastery_map(student["id"])
    lesson = db2.get_lesson(lesson_id)
    db2.close()
    assert mastery["two-step-equations"]["status"] == "mastered"
    assert mastery["two-step-equations"]["score"] == 80
    # Approving and logging hours are the same act now.
    assert lesson["status"] == "completed"


def test_not_yet_records_in_progress_not_mastered(monkeypatch, tmp_path):
    db_path = tmp_path / "a.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    lesson_id = _math_lesson(db, student["id"], quiz_result={
        "correct": 3, "total": 5, "passed": False, "graded_on": "2026-08-25",
    })
    db.submit_lesson(lesson_id)
    db.close()

    at = _open(monkeypatch, db_path, ACTIVITY_LOG_PATH, as_parent=True)
    keep_practicing = [b for b in at.button if "Not yet" in (b.label or "")][0]
    keep_practicing.click().run()
    assert not at.exception, [e.message for e in at.exception]

    db2 = Database(db_path)
    mastery = db2.mastery_map(student["id"])
    lesson = db2.get_lesson(lesson_id)
    db2.close()
    assert mastery["two-step-equations"]["status"] == "in_progress"
    # Sent back, not completed -- no hours logged until he redoes it.
    assert lesson["status"] == "needs_revision"


def test_an_already_approved_skill_shows_as_such(monkeypatch, tmp_path):
    db_path = tmp_path / "a.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    _math_lesson(db, student["id"])
    db.set_mastery(student["id"], "two-step-equations", "mastered", score=100.0)
    db.close()

    at = _open(monkeypatch, db_path, ACTIVITY_LOG_PATH, as_parent=True)
    text = " ".join(s.value for s in at.success)
    assert "Already approved" in text


# --- the three-way verdict (non-Math) --------------------------------------------------


def test_non_math_lesson_gets_the_three_way_verdict_form(monkeypatch, tmp_path):
    db_path = tmp_path / "a.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    payload = {
        "title": "Volcanoes", "activities": [],
        "assessment": {"kind": "check", "description": "Explain the three layers",
                        "mastery_criteria": "Names all three unprompted"},
    }
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="science", subject="science", topic="t",
        title="Volcanoes", payload=payload,
    )
    db.submit_lesson(lesson_id)
    db.close()

    at = _open(monkeypatch, db_path, ACTIVITY_LOG_PATH, as_parent=True)
    assert any(r.label == "How'd it go?" for r in at.radio)


def test_submitting_the_verdict_form_records_the_assessment(monkeypatch, tmp_path):
    db_path = tmp_path / "a.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    payload = {
        "title": "Volcanoes", "activities": [],
        "assessment": {"kind": "check", "description": "Explain the three layers",
                        "mastery_criteria": "Names all three unprompted"},
    }
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="science", subject="science", topic="t",
        title="Volcanoes", payload=payload,
    )
    db.submit_lesson(lesson_id)
    db.close()

    at = _open(monkeypatch, db_path, ACTIVITY_LOG_PATH, as_parent=True)
    radio = [r for r in at.radio if r.label == "How'd it go?"][0]
    # The raw option value, not its on-screen label -- the labels now carry
    # the percentage each band is worth toward the grade, and a test that
    # hardcodes the display string breaks every time that wording moves.
    radio.set_value(config.ASSESSMENT_NAILED_IT).run()
    submit = [b for b in at.button if "Approve" in (b.label or "")][0]
    submit.click().run()
    assert not at.exception, [e.message for e in at.exception]

    db2 = Database(db_path)
    lesson = db2.get_lesson(lesson_id)
    db2.close()
    assert lesson["metadata"]["assessment_result"]["verdict"] == "nailed_it"
    assert lesson["status"] == "completed"


def test_a_lesson_with_no_assessment_skill_or_writing_gets_no_card(monkeypatch, tmp_path):
    db_path = tmp_path / "a.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    payload = {"title": "Do laundry", "activities": []}
    db.save_lesson(
        student_id=student["id"], agent="life_skills", subject="occupational_education",
        topic="t", title="Do laundry", payload=payload,
    )
    db.close()

    at = _open(monkeypatch, db_path, ACTIVITY_LOG_PATH, as_parent=True)
    text = " ".join(m.value for m in at.markdown)
    assert "Assessment" not in text


# --- writing responses -----------------------------------------------------------------


def _writing_payload():
    return {
        "title": "Argue a Character's Choice",
        "overview": "",
        "activities": [
            {"title": "Essay", "kind": "writing", "minutes": 30,
             "instructions": "Argue for or against the choice.",
             "video": {"found": False, "title": "", "url": "", "channel": "", "why": ""}},
        ],
        "materials": [], "subject_credits": [], "branches": [],
    }


def _instruction_with_written_response_payload():
    """The reported case: a short-answer question buried inside an
    ordinary `instruction`-kind activity, same as an actual Science lesson
    ("Read this, then answer the two questions in your notebook...") --
    the box has to trigger off `requires_written_response`, not `kind`."""
    return {
        "title": "Where Does the Energy Go?",
        "overview": "",
        "activities": [
            {"title": "Read and answer", "kind": "instruction", "minutes": 15,
             "instructions": "Read this, then answer the two questions in your notebook.",
             "requires_written_response": True,
             "video": {"found": False, "title": "", "url": "", "channel": "", "why": ""}},
        ],
        "materials": [], "subject_credits": [], "branches": [],
    }


def _writing_payload_with_requirements(min_words=None, requires_quote=False):
    payload = _writing_payload()
    payload["activities"][0]["writing_requirements"] = {
        "min_words": min_words, "max_words": None, "min_sentences": None,
        "requires_quote": requires_quote,
    }
    return payload


def test_writing_activity_shows_a_response_box_in_student_view(monkeypatch, tmp_path):
    db_path = tmp_path / "a.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    auth.set_pin(db, "1234")
    db.save_lesson(
        student_id=student["id"], agent="english", subject="english", topic="t",
        title="Argue a Character's Choice", payload=_writing_payload(),
    )
    db.close()

    at = _open(monkeypatch, db_path, ENGLISH_PATH, as_parent=False)
    assert any(t.label == "Your response" for t in at.text_area)


def test_writing_activity_also_shows_a_response_box_on_home(monkeypatch, tmp_path):
    """Home's own checklist renders lessons through a separate call to
    render_lesson than the subject pages do (Home.py:297 vs.
    student_lesson_view in compass/ui.py) -- easy to fix one and forget the
    other, which is exactly what happened the first time around: Home
    never passed db/lesson_id/metadata through, so the box silently never
    appeared for the one place he actually opens lessons from day to day."""
    db_path = tmp_path / "a.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    auth.set_pin(db, "1234")
    db.save_lesson(
        student_id=student["id"], agent="english", subject="english", topic="t",
        title="Argue a Character's Choice", payload=_writing_payload(),
    )
    db.close()

    at = _open(monkeypatch, db_path, HOME_PATH, as_parent=False)
    assert any(t.label == "Your response" for t in at.text_area)


def test_an_instruction_activity_flagged_requires_written_response_gets_a_box(
    monkeypatch, tmp_path
):
    db_path = tmp_path / "a.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    auth.set_pin(db, "1234")
    db.save_lesson(
        student_id=student["id"], agent="science", subject="science", topic="t",
        title="Where Does the Energy Go?",
        payload=_instruction_with_written_response_payload(),
    )
    db.close()

    at = _open(monkeypatch, db_path, str(REPO_ROOT / "pages" / "2_Science.py"), as_parent=False)
    assert any(t.label == "Your response" for t in at.text_area)


def test_a_plain_instruction_activity_with_no_flag_gets_no_box(monkeypatch, tmp_path):
    db_path = tmp_path / "a.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    auth.set_pin(db, "1234")
    payload = _instruction_with_written_response_payload()
    payload["activities"][0]["requires_written_response"] = False
    db.save_lesson(
        student_id=student["id"], agent="science", subject="science", topic="t",
        title="Where Does the Energy Go?", payload=payload,
    )
    db.close()

    at = _open(monkeypatch, db_path, str(REPO_ROOT / "pages" / "2_Science.py"), as_parent=False)
    assert not any(t.label == "Your response" for t in at.text_area)


def test_a_flagged_instruction_activity_response_also_shows_in_parent_review(
    monkeypatch, tmp_path
):
    db_path = tmp_path / "a.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="science", subject="science", topic="t",
        title="Where Does the Energy Go?",
        payload=_instruction_with_written_response_payload(),
    )
    db.save_writing_response(lesson_id, 0, "PE is stored energy from being lifted up.")
    db.close()

    at = _open(monkeypatch, db_path, ACTIVITY_LOG_PATH, as_parent=True)
    text = " ".join(m.value for m in at.markdown)
    assert "PE is stored energy from being lifted up." in text


def test_saving_a_writing_response_persists_it(monkeypatch, tmp_path):
    db_path = tmp_path / "a.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    auth.set_pin(db, "1234")
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="english", subject="english", topic="t",
        title="Argue a Character's Choice", payload=_writing_payload(),
    )
    db.close()

    at = _open(monkeypatch, db_path, ENGLISH_PATH, as_parent=False)
    response_box = [t for t in at.text_area if t.label == "Your response"][0]
    response_box.set_value("I think the character was right because...").run()
    save_button = [b for b in at.button if b.label == "Save draft"][0]
    save_button.click().run()
    assert not at.exception, [e.message for e in at.exception]

    db2 = Database(db_path)
    lesson = db2.get_lesson(lesson_id)
    db2.close()
    assert (
        lesson["metadata"]["writing_responses"]["0"]
        == "I think the character was right because..."
    )


def test_a_saved_writing_response_appears_in_the_parent_review_card(monkeypatch, tmp_path):
    db_path = tmp_path / "a.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="english", subject="english", topic="t",
        title="Argue a Character's Choice", payload=_writing_payload(),
    )
    db.save_writing_response(lesson_id, 0, "I think the character was right because...")
    db.close()

    at = _open(monkeypatch, db_path, ACTIVITY_LOG_PATH, as_parent=True)
    text = " ".join(m.value for m in at.markdown)
    assert "I think the character was right because..." in text


def test_only_the_latest_draft_shows_when_theres_just_one_version(monkeypatch, tmp_path):
    db_path = tmp_path / "a.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="english", subject="english", topic="t",
        title="Argue a Character's Choice", payload=_writing_payload(),
    )
    db.save_writing_response(lesson_id, 0, "Only draft.")
    db.close()

    at = _open(monkeypatch, db_path, ACTIVITY_LOG_PATH, as_parent=True)
    assert not any("Earlier drafts" in (e.label or "") for e in at.expander)


def test_earlier_drafts_show_up_once_hes_revised_it(monkeypatch, tmp_path):
    db_path = tmp_path / "a.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="english", subject="english", topic="t",
        title="Argue a Character's Choice", payload=_writing_payload(),
    )
    db.save_writing_response(lesson_id, 0, "First draft.")
    db.save_writing_response(lesson_id, 0, "Second draft.")
    db.save_writing_response(lesson_id, 0, "Final version.")
    db.close()

    at = _open(monkeypatch, db_path, ACTIVITY_LOG_PATH, as_parent=True)
    drafts_expander = next(e for e in at.expander if "Earlier drafts" in (e.label or ""))
    assert "(2)" in drafts_expander.label
    body_text = " ".join(m.value for m in drafts_expander.markdown)
    assert "First draft." in body_text
    assert "Second draft." in body_text
    assert "Final version." not in body_text  # that's the current one, shown above

    # the current (latest) version is still shown outside the expander
    text = " ".join(m.value for m in at.markdown)
    assert "Final version." in text


def test_no_response_yet_says_so_in_the_parent_review_card(monkeypatch, tmp_path):
    db_path = tmp_path / "a.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    db.save_lesson(
        student_id=student["id"], agent="english", subject="english", topic="t",
        title="Argue a Character's Choice", payload=_writing_payload(),
    )
    db.close()

    at = _open(monkeypatch, db_path, ACTIVITY_LOG_PATH, as_parent=True)
    text = " ".join(c.value for c in at.caption)
    assert "hasn't written a response yet" in text


def test_logging_hours_does_not_launch_balloons(monkeypatch, tmp_path):
    """The balloons were the parent's own admin action (logging hours),
    not Landon's -- dropped on request. Landon getting a perfect quiz
    score still gets its own celebration; see test_quiz_duration.py."""
    import streamlit

    db_path = tmp_path / "a.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    lesson_id = _math_lesson(db, student["id"])
    db.submit_lesson(lesson_id)
    db.close()

    calls = []
    monkeypatch.setattr(streamlit, "balloons", lambda: calls.append(1))
    at = _open(monkeypatch, db_path, ACTIVITY_LOG_PATH, as_parent=True)
    log_button = [b for b in at.button if "Approve" in (b.label or "")][0]
    log_button.click().run()
    assert not at.exception, [e.message for e in at.exception]

    # The success message flashes and immediately reruns -- AppTest's final
    # state is past it, same as every other approve/decision flow here, so
    # this checks the actual record instead of a message that can't survive
    # the rerun that follows it.
    db2 = Database(db_path)
    assert db2.get_lesson(lesson_id)["status"] == "completed"
    db2.close()
    assert not calls


# --- writing review: the draft -> submit -> parent decision loop ----------------------


def test_submitting_below_the_word_count_is_blocked_with_a_reason(monkeypatch, tmp_path):
    """The whole point of the checks: a 50-word assignment can't be
    submitted as four words, and he's told exactly why rather than having
    a parent notice by eye days later."""
    db_path = tmp_path / "a.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    auth.set_pin(db, "1234")
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="english", subject="english", topic="t",
        title="Argue a Character's Choice",
        payload=_writing_payload_with_requirements(min_words=50),
    )
    db.close()

    at = _open(monkeypatch, db_path, ENGLISH_PATH, as_parent=False)
    at.text_area(key=f"writing_draft_{lesson_id}_0").set_value("way too short").run()
    at.button(key=f"submit_writing_{lesson_id}_0").click().run()
    assert not at.exception, [e.message for e in at.exception]

    errors = " ".join(e.value for e in at.error)
    assert "at least 50 words" in errors

    db2 = Database(db_path)
    lesson = db2.get_lesson(lesson_id)
    db2.close()
    assert (lesson["metadata"].get("writing_review") or {}) == {}


def test_submitting_without_a_required_quote_is_blocked(monkeypatch, tmp_path):
    db_path = tmp_path / "a.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    auth.set_pin(db, "1234")
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="english", subject="english", topic="t",
        title="Argue a Character's Choice",
        payload=_writing_payload_with_requirements(requires_quote=True),
    )
    db.close()

    at = _open(monkeypatch, db_path, ENGLISH_PATH, as_parent=False)
    at.text_area(key=f"writing_draft_{lesson_id}_0").set_value(
        "I have plenty of words here but no quotation marks anywhere at all."
    ).run()
    at.button(key=f"submit_writing_{lesson_id}_0").click().run()

    errors = " ".join(e.value for e in at.error)
    assert "quote" in errors.lower()


def test_a_passing_response_submits_and_locks_for_review(monkeypatch, tmp_path):
    db_path = tmp_path / "a.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    auth.set_pin(db, "1234")
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="english", subject="english", topic="t",
        title="Argue a Character's Choice",
        payload=_writing_payload_with_requirements(min_words=5),
    )
    db.close()

    at = _open(monkeypatch, db_path, ENGLISH_PATH, as_parent=False)
    at.text_area(key=f"writing_draft_{lesson_id}_0").set_value(
        "This response is comfortably over the required word count."
    ).run()
    at.button(key=f"submit_writing_{lesson_id}_0").click().run()
    assert not at.exception, [e.message for e in at.exception]

    db2 = Database(db_path)
    lesson = db2.get_lesson(lesson_id)
    db2.close()
    assert lesson["metadata"]["writing_review"]["0"]["status"] == "submitted"
    # He can no longer edit it -- the box is replaced by a waiting message.
    assert not any(t.label == "Your response" for t in at.text_area)


def test_saving_a_draft_never_runs_the_checks(monkeypatch, tmp_path):
    """Saving is for work-in-progress -- only submitting is gated, so he
    can stop mid-sentence and come back without being nagged."""
    db_path = tmp_path / "a.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    auth.set_pin(db, "1234")
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="english", subject="english", topic="t",
        title="Argue a Character's Choice",
        payload=_writing_payload_with_requirements(min_words=500),
    )
    db.close()

    at = _open(monkeypatch, db_path, ENGLISH_PATH, as_parent=False)
    at.text_area(key=f"writing_draft_{lesson_id}_0").set_value("barely started").run()
    at.button(key=f"save_writing_{lesson_id}_0").click().run()
    assert not at.exception, [e.message for e in at.exception]
    assert not at.error

    db2 = Database(db_path)
    lesson = db2.get_lesson(lesson_id)
    db2.close()
    assert lesson["metadata"]["writing_responses"]["0"] == "barely started"


def test_parent_sees_the_submitted_response_and_can_approve(monkeypatch, tmp_path):
    db_path = tmp_path / "a.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="english", subject="english", topic="t",
        title="Argue a Character's Choice", payload=_writing_payload(),
    )
    db.save_writing_response(lesson_id, 0, "His finished argument.")
    db.set_writing_review(lesson_id, 0, "submitted")
    db.set_lesson_status(lesson_id, "submitted")  # the whole lesson has to be turned in too
    db.close()

    at = _open(monkeypatch, db_path, ACTIVITY_LOG_PATH, as_parent=True)
    approve = [b for b in at.button if b.label == "✅ Approve"][0]
    approve.click().run()
    assert not at.exception, [e.message for e in at.exception]

    db2 = Database(db_path)
    lesson = db2.get_lesson(lesson_id)
    db2.close()
    assert lesson["metadata"]["writing_review"]["0"]["status"] == "approved"


def test_parent_can_send_it_back_with_feedback(monkeypatch, tmp_path):
    db_path = tmp_path / "a.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="english", subject="english", topic="t",
        title="Argue a Character's Choice", payload=_writing_payload(),
    )
    db.save_writing_response(lesson_id, 0, "Too thin an argument.")
    db.set_writing_review(lesson_id, 0, "submitted")
    db.set_lesson_status(lesson_id, "submitted")  # the whole lesson has to be turned in too
    db.close()

    at = _open(monkeypatch, db_path, ACTIVITY_LOG_PATH, as_parent=True)
    feedback_box = [
        t for t in at.text_area if "Feedback" in (t.label or "")
    ][0]
    feedback_box.set_value("Back this up with a quote from the text.").run()
    bounce = [b for b in at.button if "Send back" in (b.label or "")][0]
    bounce.click().run()
    assert not at.exception, [e.message for e in at.exception]

    db2 = Database(db_path)
    lesson = db2.get_lesson(lesson_id)
    db2.close()
    review = lesson["metadata"]["writing_review"]["0"]
    assert review["status"] == "needs_revision"
    assert review["feedback"] == "Back this up with a quote from the text."
    # Bouncing one piece sends the whole lesson back too.
    assert lesson["status"] == "needs_revision"


def test_a_bounced_response_shows_him_the_feedback_and_reopens_the_box(monkeypatch, tmp_path):
    db_path = tmp_path / "a.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    auth.set_pin(db, "1234")
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="english", subject="english", topic="t",
        title="Argue a Character's Choice", payload=_writing_payload(),
    )
    db.save_writing_response(lesson_id, 0, "Too thin an argument.")
    db.set_writing_review(lesson_id, 0, "needs_revision", "Add a quote from the text.")
    db.close()

    at = _open(monkeypatch, db_path, ENGLISH_PATH, as_parent=False)
    warnings = " ".join(w.value for w in at.warning)
    assert "Add a quote from the text." in warnings
    assert any(t.label == "Your response" for t in at.text_area)


def test_an_approved_response_is_read_only_for_him(monkeypatch, tmp_path):
    db_path = tmp_path / "a.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    auth.set_pin(db, "1234")
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="english", subject="english", topic="t",
        title="Argue a Character's Choice", payload=_writing_payload(),
    )
    db.save_writing_response(lesson_id, 0, "His finished argument.")
    db.set_writing_review(lesson_id, 0, "approved")
    db.close()

    at = _open(monkeypatch, db_path, ENGLISH_PATH, as_parent=False)
    assert not any(t.label == "Your response" for t in at.text_area)
    successes = " ".join(s.value for s in at.success)
    assert "approved" in successes.lower()
