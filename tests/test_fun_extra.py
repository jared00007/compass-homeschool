"""The optional, ungraded 'just for fun' activity (`fun_extra`).

Generated only when the parent opts in at plan time; rendered as a light,
skippable card that never blocks turning the lesson in.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st
from streamlit.testing.v1 import AppTest

from compass import auth, config
from compass.agents.framework import StudentContext
from compass.agents.prompts import build_standard_prompt
from compass.storage.db import Database

REPO_ROOT = Path(__file__).resolve().parent.parent
HOME_PATH = str(REPO_ROOT / "Home.py")
MATH_PATH = str(REPO_ROOT / "pages" / "1_Math.py")


class _Proposal:
    topic = "Slope of a line"
    rationale = "next in the graph"
    context_lines: list = []
    guidance = ""


def _ctx(**inputs):
    inputs.setdefault("minutes", 40)
    return StudentContext(db=None, student_id=1, student={"name": "Landon"}, inputs=inputs)


def test_prompt_requests_fun_extra_only_when_the_parent_opts_in():
    on = build_standard_prompt(_ctx(include_fun_extra=True), _Proposal(), "Math")
    off = build_standard_prompt(_ctx(), _Proposal(), "Math")
    assert "fun extra" in on.lower()
    assert "leave `fun_extra` empty" in off.lower()


def _lesson_payload(with_fun: bool):
    payload = {
        "title": "Slope",
        "overview": "Find slope from two points.",
        "learning_objectives": ["Find slope"],
        "learn": {"explanation": "Rise over run.", "video": {"found": False}},
        "worked_example": {"problem": "p", "steps": "s"},
        "activities": [],
        "materials": [],
        "assessment": {"kind": "check", "description": "", "mastery_criteria": ""},
        "subject_credits": [],
        "estimated_minutes": 40,
        "parent_notes": "",
        "branches": [],
        "quiz": [],
    }
    payload["fun_extra"] = (
        {"title": "Slope scavenger hunt", "instructions": "Find three ramps and rank them steepest to flattest."}
        if with_fun
        else {"title": "", "instructions": ""}
    )
    return payload


def _open_math_as_student(monkeypatch, db_path):
    st.cache_resource.clear()
    monkeypatch.setattr(config, "DEFAULT_DB_PATH", db_path)
    at = AppTest.from_file(HOME_PATH)
    at.run(timeout=30)
    at.switch_page(MATH_PATH)
    at.run(timeout=30)
    assert not at.exception, [e.message for e in at.exception]
    return at


def test_a_fun_extra_shows_on_his_lesson_when_present(monkeypatch, tmp_path):
    db_path = tmp_path / "fun.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    auth.set_pin(db, "1234")
    db.save_lesson(
        student_id=student["id"], agent="math", subject="math", topic="t",
        title="Slope", payload=_lesson_payload(with_fun=True),
    )
    db.close()

    at = _open_math_as_student(monkeypatch, db_path)
    body = " ".join(m.value for m in at.markdown)
    assert "Just for fun" in body
    assert "scavenger hunt" in body.lower()


def test_no_fun_card_when_the_lesson_has_none(monkeypatch, tmp_path):
    db_path = tmp_path / "nofun.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    auth.set_pin(db, "1234")
    db.save_lesson(
        student_id=student["id"], agent="math", subject="math", topic="t",
        title="Slope", payload=_lesson_payload(with_fun=False),
    )
    db.close()

    at = _open_math_as_student(monkeypatch, db_path)
    body = " ".join(m.value for m in at.markdown)
    assert "Just for fun" not in body


def test_fun_extra_never_blocks_turning_the_lesson_in():
    # The submit gate cares about the quiz and written responses, never the
    # optional fun card -- a lesson with only a fun_extra is still ready.
    from compass.ui import _lesson_ready_to_submit

    lesson = {"payload": _lesson_payload(with_fun=True), "metadata": {}}
    ready, _ = _lesson_ready_to_submit(lesson)
    assert ready is True
