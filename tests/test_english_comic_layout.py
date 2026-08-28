"""The "Comic Panels" redesign, the one direction chosen after showing three
mockups on the English page. Activities become an ink-bordered panel grid --
each one framed, with an issue tag and a kind pill -- instead of a stack of
collapsed expanders. Rolled out as the default for every subject's
student-facing lesson (`comic_layout` on `render_lesson`/
`student_lesson_view` now defaults to True), not just English, so Math,
Science, and History get the same activity tagging.
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
    save_button = [b for b in at.button if b.label == "Save draft"][0]
    save_button.click().run()
    assert not at.exception, [e.message for e in at.exception]

    db2 = Database(db_path)
    lesson = db2.get_lesson(lesson_id)
    db2.close()
    assert (
        lesson["metadata"]["writing_responses"]["2"]
        == "He starts planning instead of just reacting."
    )


def test_english_progress_dots_cover_every_activity_not_just_writing_ones(
    monkeypatch, tmp_path
):
    """One dot per activity, in order -- everything up to the next unmet
    typed-response requirement reads as passed, since there's no honest
    per-activity "done" signal for a reading/instruction activity on its
    own. The Hatchet lesson has 3 activities and one requires a response
    (index 2, unanswered), so that's 2 "done" dots then 1 "current"."""
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
    assert text.count('<span class="done"></span>') == 2
    assert text.count('<span class="current"></span>') == 1


def test_english_lesson_gets_a_framed_eyebrow_header(monkeypatch, tmp_path):
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
    assert "comic-frame-title" in text
    assert "English — Current Lesson" in text


def test_math_now_also_gets_the_comic_panel_treatment(monkeypatch, tmp_path):
    """Rolled out beyond English on request -- the kind pill/issue tag
    should show up for every subject's activities, not just English's."""
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
    text = " ".join(m.value for m in at.markdown)
    assert "comic-issue-tag" in text
    assert "No. 1" in text
    assert "comic-pill--neutral" in text  # "practice" has no dedicated color
    assert "math — Current Lesson" in text
    assert not any("Practice" in (e.label or "") for e in at.expander)


def test_reopening_a_past_lesson_also_gets_the_comic_panel_treatment(monkeypatch, tmp_path):
    """Regression: render_past_lessons calls render_lesson directly and had
    been left off the comic_layout rollout -- reopening a finished lesson
    (exactly what happens once "Nothing left to do for now" shows, and he
    picks an old one from the dropdown) silently fell back to the old plain
    expander layout even though the current lesson above it was redesigned."""
    db_path = tmp_path / "a.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    auth.set_pin(db, "1234")
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="english", subject="english", topic="t",
        title="Brian's Turning Point", payload=_hatchet_payload(),
    )
    db.mark_student_done(lesson_id)
    db.set_lesson_status(lesson_id, "completed")  # fully resolved, not just self-reported
    db.close()

    at = _open(monkeypatch, db_path, ENGLISH_PATH, as_parent=False)
    picker = [s for s in at.selectbox if s.label == "Look back at a finished lesson"][0]
    picker.select_index(0).run()
    assert not at.exception, [e.message for e in at.exception]

    text = " ".join(m.value for m in at.markdown)
    assert "comic-issue-tag" in text
    assert "No. 1" in text
    assert "Past Lesson" in text


def test_homes_lesson_roster_links_out_instead_of_embedding_the_lesson(
    monkeypatch, tmp_path
):
    """Home used to render each lesson's full content inline through its own
    separate call to render_lesson -- a second call site that had already
    caused one regression (the comic-panel treatment, then the writing-
    response box, each forgotten here once before). It now just links out
    to the subject page, the only place a lesson actually renders for him,
    so there's no second call site left to fall out of sync with
    student_lesson_view."""
    db_path = tmp_path / "a.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    auth.set_pin(db, "1234")
    db.save_lesson(
        student_id=student["id"], agent="english", subject="english", topic="t",
        title="Brian's Turning Point", payload=_hatchet_payload(),
    )
    db.close()

    at = _open(monkeypatch, db_path, HOME_PATH, as_parent=False)
    text = " ".join(m.value for m in at.markdown)
    assert "comic-issue-tag" not in text

    links = [l for l in at.get("page_link") if "Brian's Turning Point" in l.label]
    assert len(links) == 1
    assert links[0].page == "English"


def test_vocab_review_gets_its_own_framed_eyebrow_header(monkeypatch, tmp_path):
    db_path = tmp_path / "a.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    auth.set_pin(db, "1234")
    db.add_vocabulary(student["id"], "resilient", "able to recover quickly")
    db.conn.execute("UPDATE vocabulary SET next_review_on = date('now')")
    db.conn.commit()
    db.close()

    at = _open(monkeypatch, db_path, ENGLISH_PATH, as_parent=False)
    text = " ".join(m.value for m in at.markdown)
    assert "Words to Review" in text
    assert "comic-frame-title" in text


# --- single column, and marking a card done collapses it -------------------------


def test_marking_a_card_done_collapses_it(monkeypatch, tmp_path):
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
    assert "Read through the fish-spear scene." in " ".join(m.value for m in at.markdown)
    done_button = [b for b in at.button if b.label == "✅ Mark this one done"][0]
    done_button.click().run()
    assert not at.exception, [e.message for e in at.exception]

    text = " ".join(m.value for m in at.markdown)
    assert "Read through the fish-spear scene." not in text  # tucked away
    assert any(b.label == "↩️ Done — tap to reopen" for b in at.button)

    db2 = Database(db_path)
    lesson = db2.get_lesson(lesson_id)
    db2.close()
    assert lesson["metadata"]["collapsed_activities"] == [0]


def test_reopening_a_collapsed_card_restores_it(monkeypatch, tmp_path):
    db_path = tmp_path / "a.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    auth.set_pin(db, "1234")
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="english", subject="english", topic="t",
        title="Brian's Turning Point", payload=_hatchet_payload(),
    )
    db.set_activity_collapsed(lesson_id, 0, True)
    db.close()

    at = _open(monkeypatch, db_path, ENGLISH_PATH, as_parent=False)
    reopen_button = [b for b in at.button if b.label == "↩️ Done — tap to reopen"][0]
    reopen_button.click().run()
    assert not at.exception, [e.message for e in at.exception]

    text = " ".join(m.value for m in at.markdown)
    assert "Read through the fish-spear scene." in text

    db2 = Database(db_path)
    assert db2.get_lesson(lesson_id)["metadata"]["collapsed_activities"] == []
    db2.close()


def test_collapsing_is_scoped_to_its_own_card(monkeypatch, tmp_path):
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
    done_buttons = [b for b in at.button if b.label == "✅ Mark this one done"]
    assert len(done_buttons) == 3  # all three activities, including the writing one, get a toggle
    done_buttons[0].click().run()
    assert not at.exception, [e.message for e in at.exception]

    text = " ".join(m.value for m in at.markdown)
    assert "Read through the fish-spear scene." not in text
    assert "Find the paragraph where he starts planning ahead." in text  # activity 1, untouched


def test_a_parent_previewing_the_lesson_sees_every_card_regardless_of_collapse(
    monkeypatch, tmp_path
):
    """A parent opening a lesson needs the whole thing -- collapsing is a
    student-side reading convenience only, enforced in
    _render_activity_comic_panel by gating on `parent` alone. Exercised
    directly against render_lesson (the Recorder pattern from
    test_auth.py), since no page today hands a parent the comic layout for
    an already-collapsed lesson to click through -- the parent-facing
    review card (render_assessment_card) is a separate summary that
    doesn't call render_lesson at all."""
    import compass.ui as ui

    db_path = tmp_path / "a.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="english", subject="english", topic="t",
        title="Brian's Turning Point", payload=_hatchet_payload(),
    )
    db.set_activity_collapsed(lesson_id, 0, True)
    lesson = db.get_lesson(lesson_id)

    written: list[str] = []

    class Recorder:
        """Stands in for `st`, recording every string that would be rendered."""

        def __getattr__(self, _name):
            def record(*args, **kwargs):
                for arg in args:
                    if isinstance(arg, str):
                        written.append(arg)
                return Recorder()
            return record

        def __getitem__(self, _index):
            return Recorder()

        def __iter__(self):
            return iter([Recorder(), Recorder(), Recorder()])

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(ui, "st", Recorder())
    monkeypatch.setattr(ui, "is_parent", lambda: True)
    ui.render_lesson(
        lesson["payload"],
        for_parent=True,
        db=db,
        lesson_id=lesson_id,
        metadata=lesson["metadata"],
        comic_layout=True,
        student=student,
    )
    db.close()

    page = "\n".join(written)
    assert "Read through the fish-spear scene." in page
    assert "↩️ Done — tap to reopen" not in page
