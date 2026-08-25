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
    _math_lesson(db, student["id"])
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
    _math_lesson(db, student["id"], quiz_result={
        "correct": 4, "total": 5, "passed": True, "graded_on": "2026-08-25",
    })
    db.close()

    at = _open(monkeypatch, db_path, ACTIVITY_LOG_PATH, as_parent=True)
    approve = [b for b in at.button if "Approve" in (b.label or "")][0]
    approve.click().run()
    assert not at.exception, [e.message for e in at.exception]

    db2 = Database(db_path)
    mastery = db2.mastery_map(student["id"])
    db2.close()
    assert mastery["two-step-equations"]["status"] == "mastered"
    assert mastery["two-step-equations"]["score"] == 80


def test_not_yet_records_in_progress_not_mastered(monkeypatch, tmp_path):
    db_path = tmp_path / "a.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    _math_lesson(db, student["id"], quiz_result={
        "correct": 3, "total": 5, "passed": False, "graded_on": "2026-08-25",
    })
    db.close()

    at = _open(monkeypatch, db_path, ACTIVITY_LOG_PATH, as_parent=True)
    keep_practicing = [b for b in at.button if "Not yet" in (b.label or "")][0]
    keep_practicing.click().run()
    assert not at.exception, [e.message for e in at.exception]

    db2 = Database(db_path)
    mastery = db2.mastery_map(student["id"])
    db2.close()
    assert mastery["two-step-equations"]["status"] == "in_progress"


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
    db.save_lesson(
        student_id=student["id"], agent="science", subject="science", topic="t",
        title="Volcanoes", payload=payload,
    )
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
    db.close()

    at = _open(monkeypatch, db_path, ACTIVITY_LOG_PATH, as_parent=True)
    radio = [r for r in at.radio if r.label == "How'd it go?"][0]
    radio.set_value("🎯 Nailed it").run()
    submit = [b for b in at.button if "Save assessment" in (b.label or "")][0]
    submit.click().run()
    assert not at.exception, [e.message for e in at.exception]

    db2 = Database(db_path)
    lesson = db2.get_lesson(lesson_id)
    db2.close()
    assert lesson["metadata"]["assessment_result"]["verdict"] == "nailed_it"


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
    save_button = [b for b in at.button if b.label == "Save response"][0]
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
