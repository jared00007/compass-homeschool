"""The shared UI loop every Tier 1 agent page runs through.

`generate_and_log` replaced four near-identical hand-maintained copies of the
generate → review → log block. That consolidation is only worth it if the copy
that survived actually does the things the four were each responsible for, so
these tests pin the parts that would be silently skippable: the warnings from
credit/video normalization, the redacting renderer, and the per-agent session
key that keeps an expensive lesson alive across a rerun.
"""

from __future__ import annotations

import pytest

import compass.ui as ui
from compass.agents import get_agent
from compass.agents.framework import GeneratedLesson, TopicProposal
from compass.storage.db import Database


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    yield database
    database.close()


@pytest.fixture()
def student(db):
    return db.ensure_default_student()


class Recorder:
    """Stands in for `st`, capturing every string that would be rendered."""

    def __init__(self, written: list[str], state: dict):
        self._written = written
        self.session_state = state

    def __getattr__(self, name):
        def record(*args, **kwargs):
            for arg in args:
                if isinstance(arg, str):
                    self._written.append(arg)
            return self
        return record

    def __getitem__(self, _index):
        return self

    def __iter__(self):
        return iter([self, self])

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __bool__(self):
        """Widgets read falsy, so `if st.button(...)` doesn't fire.

        Without this the recorder's own return value is truthy and every test
        would take the Generate branch straight into a live API call.
        """
        return False


def a_lesson(**overrides):
    payload = {
        "title": "Two-Step Equations",
        "overview": "Undo the addition, then the multiplication.",
        "learning_objectives": ["Solve for x"],
        "activities": [
            {"title": "Practice", "kind": "practice", "minutes": 60,
             "instructions": "Solve problems 1-10."}
        ],
        "materials": ["Pencil"],
        "assessment": {"kind": "check", "description": "Ten items",
                       "mastery_criteria": "Answer key: 8 of 10"},
        "subject_credits": [{"subject": "math", "minutes": 60, "justification": "All of it."}],
        "estimated_minutes": 60,
        "parent_notes": "Watch for sign errors.",
        "branches": [],
        "video": {"found": False, "title": "", "url": "", "channel": "", "why": ""},
    }
    payload.update(overrides)
    return payload


def run(monkeypatch, db, student, *, generated=None, state=None, **kwargs):
    written: list[str] = []
    state = {} if state is None else state
    monkeypatch.setattr(ui, "st", Recorder(written, state))
    monkeypatch.setattr(ui, "is_parent", lambda: True)

    agent = get_agent("math")
    ctx = ui.context_for(db, student, minutes=60)
    proposal = TopicProposal(topic="t", rationale="r", strategy="s")
    if generated is not None:
        state[f"{agent.key}_lesson"] = generated

    params = dict(primary_subject="math", spinner="working…", api_ok=True)
    params.update(kwargs)
    ui.generate_and_log(db, student, agent, ctx, proposal, **params)
    return "\n".join(written), state


def test_normalization_warnings_always_reach_the_page(monkeypatch, db, student):
    """The whole point of one shared copy: a warning can't be dropped on one page."""
    generated = GeneratedLesson(
        lesson_id=1,
        proposal=TopicProposal(topic="t", rationale="r", strategy="s"),
        payload=a_lesson(),
        warnings=["Secondary subjects claimed 200 min inside a 60 min lesson."],
    )
    page, _ = run(monkeypatch, db, student, generated=generated)
    assert "Secondary subjects claimed 200 min" in page


def test_the_lesson_is_rendered_through_the_redacting_renderer(monkeypatch, db, student):
    generated = GeneratedLesson(
        lesson_id=1,
        proposal=TopicProposal(topic="t", rationale="r", strategy="s"),
        payload=a_lesson(),
        warnings=[],
    )
    page, _ = run(monkeypatch, db, student, generated=generated)
    assert "Two-Step Equations" in page
    assert "Solve problems 1-10." in page


def test_a_generated_lesson_offers_a_word_doc_download(monkeypatch, db, student):
    """generate_and_log only ever runs behind is_parent(), so it's safe for the
    downloadable doc to include the assessment and answer key too."""
    generated = GeneratedLesson(
        lesson_id=1,
        proposal=TopicProposal(topic="t", rationale="r", strategy="s"),
        payload=a_lesson(),
        warnings=[],
    )
    page, _ = run(monkeypatch, db, student, generated=generated)
    assert "Download as Word doc" in page


def test_word_doc_download_defers_docx_generation(monkeypatch, db, student):
    """`data` must be a callable, not already-built bytes -- otherwise a page

    listing many lessons (Activity Log's "Generated lessons" tab) would rebuild
    every lesson's .docx on every rerun, not just the one being downloaded.
    Requires streamlit>=1.52.0, which is why requirements.txt's floor was
    bumped -- an older streamlit would reject or mishandle a callable here.
    """
    calls: list[dict] = []
    written: list[str] = []
    state: dict = {}
    recorder = Recorder(written, state)
    recorder.download_button = lambda *args, **kwargs: calls.append(kwargs)
    monkeypatch.setattr(ui, "st", recorder)
    monkeypatch.setattr(ui, "is_parent", lambda: True)

    agent = get_agent("math")
    ctx = ui.context_for(db, student, minutes=60)
    proposal = TopicProposal(topic="t", rationale="r", strategy="s")
    state[f"{agent.key}_lesson"] = GeneratedLesson(
        lesson_id=1, proposal=proposal, payload=a_lesson(), warnings=[]
    )

    ui.generate_and_log(
        db, student, agent, ctx, proposal,
        primary_subject="math", spinner="x", api_ok=True,
    )

    assert len(calls) == 1
    assert callable(calls[0]["data"])
    assert calls[0]["data"]().startswith(b"PK")  # a real docx when actually invoked


def test_the_optional_trailing_note_is_shown_when_given(monkeypatch, db, student):
    """English is the only caller that passes one; it must not leak to the others."""
    generated = GeneratedLesson(
        lesson_id=1,
        proposal=TopicProposal(topic="t", rationale="r", strategy="s"),
        payload=a_lesson(),
        warnings=[],
    )
    with_note, _ = run(
        monkeypatch, db, student, generated=generated, after_render="VOCAB lines were saved."
    )
    assert "VOCAB lines were saved." in with_note

    without, _ = run(monkeypatch, db, student, generated=generated)
    assert "VOCAB lines were saved." not in without


def test_nothing_renders_before_a_lesson_exists(monkeypatch, db, student):
    """An un-generated page shows the button and stops -- no empty divider or form."""
    page, _ = run(monkeypatch, db, student)
    assert "Log this as completed" not in page
    assert "Two-Step Equations" not in page


def test_the_session_key_is_per_agent(monkeypatch, db, student):
    """Four agents share this function; one shared key would have them overwrite
    each other's lessons on every page switch."""
    keys = set()
    for name in ("math", "science", "english", "history"):
        keys.add(f"{get_agent(name).key}_lesson")
    assert len(keys) == 4
    # and it matches the keys the pages used before consolidation
    assert keys == {"math_lesson", "science_lesson", "english_lesson", "history_lesson"}


# --- student_lesson_view: his own "I'm done" signal, separate from `status` ---


def render_student_view(monkeypatch, db, student, *, agent_key="math", selectbox_return=None):
    written: list[str] = []
    recorder = Recorder(written, {})
    recorder.selectbox = lambda *args, **kwargs: selectbox_return
    monkeypatch.setattr(ui, "st", recorder)
    ui.student_lesson_view(db, student, agent_key, agent_key)
    return "\n".join(written)


def test_student_view_with_no_lessons_shows_setup_prompt(monkeypatch, db, student):
    page = render_student_view(monkeypatch, db, student)
    assert "No math lesson has been set up yet" in page


def test_student_view_shows_current_lesson_and_a_done_button(monkeypatch, db, student):
    db.save_lesson(student["id"], "math", "math", "topic", "Two-Step Equations", payload=a_lesson())
    page = render_student_view(monkeypatch, db, student)
    assert "Two-Step Equations" in page
    assert "Solve problems 1-10." in page
    assert "I'm done for today" in page


def test_marking_done_moves_a_lesson_out_of_current(monkeypatch, db, student):
    """This is the whole feature: his own signal, not the parent's `status`,
    controls what he sees as current -- and it's separate from hour logging."""
    lesson_id = db.save_lesson(
        student["id"], "math", "math", "topic", "Two-Step Equations", payload=a_lesson()
    )
    db.mark_student_done(lesson_id)
    assert db.get_lesson(lesson_id)["status"] == "planned"  # unaffected by his click

    page = render_student_view(monkeypatch, db, student)
    assert "Nothing left to do" in page
    assert "I'm done for today" not in page
    assert "Two-Step Equations" not in page  # not dumped into the page unprompted


def test_skipped_lessons_never_show_as_his_current_lesson(monkeypatch, db, student):
    lesson_id = db.save_lesson(
        student["id"], "math", "math", "topic", "Two-Step Equations", payload=a_lesson()
    )
    db.set_lesson_status(lesson_id, "skipped")
    page = render_student_view(monkeypatch, db, student)
    assert "Two-Step Equations" not in page
    assert "No math lesson has been set up yet" in page


def test_a_finished_lesson_can_be_reopened_from_past_lessons(monkeypatch, db, student):
    lesson_id = db.save_lesson(
        student["id"], "math", "math", "topic", "Two-Step Equations", payload=a_lesson()
    )
    db.mark_student_done(lesson_id)
    lesson = db.get_lesson(lesson_id)
    label = f"{lesson['created_at'][:10]} — {lesson['title']}"

    page = render_student_view(monkeypatch, db, student, selectbox_return=label)
    assert "Solve problems 1-10." in page  # reopened, read-only
