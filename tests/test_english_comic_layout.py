"""The "Comic Panels" redesign of the English student page (`comic_layout=True`
on render_lesson/student_lesson_view), the one Comic Panels direction chosen
after showing three mockups. Activities become an ink-bordered panel grid with
issue tags and kind pills instead of a stack of collapsed expanders; Math,
Science, and History are untouched (`comic_layout` defaults to False there).
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st
from streamlit.testing.v1 import AppTest

from compass import auth, config
from compass.storage.db import Database

REPO_ROOT = Path(__file__).resolve().parent.parent
HOME_PATH = str(REPO_ROOT / "Home.py")
ENGLISH_PATH = str(REPO_ROOT / "pages" / "3_English.py")
MATH_PATH = str(REPO_ROOT / "pages" / "1_Math.py")


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


def _hatchet_payload():
    return {
        "title": "Brian's Turning Point",
        "overview": "Where survival stops being enough.",
        "learning_objectives": ["Find the exact paragraph where Brian's mindset shifts"],
        "materials": ["Hatchet, chapters 9-10"],
        "activities": [
            {"title": "Read Ch. 9-10", "kind": "reading", "minutes": 15,
             "instructions": "Read through the fish-spear scene.",
             "video": {"found": False, "title": "", "url": "", "channel": "", "why": ""}},
            {"title": "Find the Turn", "kind": "instruction", "minutes": 10,
             "instructions": "Find the paragraph where he starts planning ahead.",
             "example": "In ch. 4, panic sounds like short, jumpy sentences.",
             "video": {"found": False, "title": "", "url": "", "channel": "", "why": ""}},
            {"title": "Write It Down", "kind": "writing", "minutes": 10,
             "instructions": "What changed, exactly?",
             "video": {"found": False, "title": "", "url": "", "channel": "", "why": ""}},
        ],
        "subject_credits": [], "branches": [],
    }


def _math_payload():
    return {
        "title": "Two-Step Equations",
        "overview": "",
        "activities": [
            {"title": "Practice", "kind": "practice", "minutes": 30,
             "instructions": "Solve problems 1-10.",
             "video": {"found": False, "title": "", "url": "", "channel": "", "why": ""}},
        ],
        "materials": [], "subject_credits": [], "branches": [],
    }


def test_english_activities_render_as_comic_panels(monkeypatch, tmp_path):
    db_path = tmp_path / "a.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    auth.set_pin(db, "1234")
    db.save_lesson(
        student_id=student["id"], agent="english", subject="english", topic="t",
        title="Brian's Turning Point", payload=_hatchet_payload(),
    )
    db.close()

    at = _open(monkeypatch, db_path, ENGLISH_PATH, as_parent=False)
    text = " ".join(m.value for m in at.markdown)
    assert "No. 1" in text and "No. 2" in text and "No. 3" in text
    assert "comic-pill--reading" in text
    assert "comic-pill--instruction" in text
    assert "comic-pill--writing" in text
    # The expander-based layout is gone for this page -- activities are
    # always visible, not tucked behind a click.
    assert not any("Read Ch. 9-10" in (e.label or "") for e in at.expander)


def test_english_writing_box_still_works_inside_a_comic_panel(monkeypatch, tmp_path):
    db_path = tmp_path / "a.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    auth.set_pin(db, "1234")
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="english", subject="english", topic="t",
        title="Brian's Turning Point", payload=_hatchet_payload(),
    )
    db.close()

    at = _open(monkeypatch, db_path, ENGLISH_PATH, as_parent=False)
    response_box = [t for t in at.text_area if t.label == "Your response"][0]
    response_box.set_value("He starts planning instead of just reacting.").run()
    save_button = [b for b in at.button if b.label == "Save response"][0]
    save_button.click().run()
    assert not at.exception, [e.message for e in at.exception]

    db2 = Database(db_path)
    lesson = db2.get_lesson(lesson_id)
    db2.close()
    assert (
        lesson["metadata"]["writing_responses"]["2"]
        == "He starts planning instead of just reacting."
    )


def test_english_progress_dots_track_the_one_real_signal(monkeypatch, tmp_path):
    """One dot per activity that actually needs a typed response -- there's no
    honest "done" signal for reading/instruction activities, so those don't
    get a dot at all rather than a fabricated one."""
    db_path = tmp_path / "a.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    auth.set_pin(db, "1234")
    db.save_lesson(
        student_id=student["id"], agent="english", subject="english", topic="t",
        title="Brian's Turning Point", payload=_hatchet_payload(),
    )
    db.close()

    at = _open(monkeypatch, db_path, ENGLISH_PATH, as_parent=False)
    text = " ".join(m.value for m in at.markdown)
    assert "comic-progress-dots" in text
    assert text.count('<span class="') >= 1


def test_math_keeps_the_plain_expander_layout(monkeypatch, tmp_path):
    db_path = tmp_path / "a.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    auth.set_pin(db, "1234")
    db.save_lesson(
        student_id=student["id"], agent="math", subject="math", topic="t",
        title="Two-Step Equations", payload=_math_payload(),
    )
    db.close()

    at = _open(monkeypatch, db_path, MATH_PATH, as_parent=False)
    assert any("Practice" in (e.label or "") for e in at.expander)
    text = " ".join(m.value for m in at.markdown)
    assert "comic-issue-tag" not in text
