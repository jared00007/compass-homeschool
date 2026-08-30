"""Parent PIN, and the redaction it gates.

The threat model is a curious 13-year-old with the app open in front of him, not
an attacker. What matters is that the answer key is genuinely absent from the
student view rather than merely hidden behind a collapsed section.
"""

from __future__ import annotations

import pytest

from compass import auth
from compass.storage.db import Database


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    yield database
    database.close()


def test_pin_is_not_stored_in_plaintext(db):
    auth.set_pin(db, "8th-grade-2026")
    stored = db.get_setting(auth.PIN_SETTING)
    assert "8th-grade-2026" not in stored
    assert stored.startswith("pbkdf2_sha256$")


def test_correct_pin_verifies(db):
    auth.set_pin(db, "1234")
    assert auth.verify(db, "1234")


def test_wrong_pin_is_rejected(db):
    auth.set_pin(db, "1234")
    assert not auth.verify(db, "1235")
    assert not auth.verify(db, "")
    assert not auth.verify(db, "12345")


def test_same_pin_hashes_differently_each_time(db):
    """Salted, so two families with the same PIN don't share a hash."""
    first = auth.hash_pin("1234")
    second = auth.hash_pin("1234")
    assert first != second
    assert auth.check_pin(first, "1234")
    assert auth.check_pin(second, "1234")


def test_short_pins_are_refused(db):
    with pytest.raises(auth.PinError):
        auth.set_pin(db, "12")
    assert not auth.pin_is_set(db)


def test_pin_can_be_changed_and_removed(db):
    auth.set_pin(db, "1234")
    assert auth.pin_is_set(db)

    auth.set_pin(db, "5678")
    assert not auth.verify(db, "1234")
    assert auth.verify(db, "5678")

    auth.clear_pin(db)
    assert not auth.pin_is_set(db)
    assert not auth.verify(db, "5678")


def test_corrupt_hash_fails_closed(db):
    """A mangled setting must reject, never accept."""
    for junk in ("", "garbage", "pbkdf2_sha256$notanint$aa$bb", "a$b$c"):
        assert not auth.check_pin(junk, "1234")


def test_unset_pin_never_verifies(db):
    assert not auth.pin_is_set(db)
    assert not auth.verify(db, "")
    assert not auth.verify(db, "anything")


# --- the redaction itself ----------------------------------------------------


def _lesson():
    return {
        "title": "Defining Functions",
        "overview": "Every input gets exactly one output.",
        "learning_objectives": ["Apply the vertical line test"],
        "activities": [
            {"title": "Sort the relations", "kind": "practice", "minutes": 14,
             "instructions": "Decide whether each relation is a function.",
             "example": "A model example: relation {(1,2),(1,3)} is not a function.",
             "video": {
                 "found": True,
                 "title": "Functions Explained With Real Examples",
                 "url": "https://www.youtube.com/watch?v=abc123",
                 "channel": "Some Teaching Channel",
                 "why": "Shows several worked examples back to back.",
             }}
        ],
        "materials": ["Graph paper"],
        "assessment": {
            "kind": "10-item mastery check",
            "description": "Ten items, mixed representations.",
            "mastery_criteria": "Answer key: 1 F, 2 NF, 3 F, 4 NF, 5 NF.",
        },
        "subject_credits": [{"subject": "math", "minutes": 60, "justification": "Whole lesson."}],
        "parent_notes": "Watch for him reversing the definition.",
        "estimated_minutes": 60,
        "branches": [],
    }


def _rendered(monkeypatch, for_parent):
    """Capture every string the renderer would put on the page."""
    import compass.ui as ui

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

        # st.columns(n) is indexed and iterated; each column is a context manager.
        def __getitem__(self, _index):
            return Recorder()

        def __iter__(self):
            return iter([Recorder(), Recorder(), Recorder()])

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    recorder = Recorder()
    monkeypatch.setattr(ui, "st", recorder)
    monkeypatch.setattr(ui, "is_parent", lambda: for_parent)
    ui.render_lesson(_lesson(), for_parent=for_parent)
    return "\n".join(written)


def test_student_view_never_emits_the_answer_key(monkeypatch):
    page = _rendered(monkeypatch, for_parent=False)
    assert "Answer key" not in page
    assert "1 F, 2 NF" not in page
    assert "Watch for him reversing" not in page, "parent notes must not render either"
    # The work itself still reaches him.
    assert "Sort the relations" in page
    assert "Decide whether each relation is a function." in page
    assert "Graph paper" in page


def test_parent_view_shows_everything(monkeypatch):
    page = _rendered(monkeypatch, for_parent=True)
    assert "Answer key" in page
    assert "Watch for him reversing" in page
    assert "Sort the relations" in page
    assert "Functions Explained With Real Examples" in page
    assert "https://www.youtube.com/watch?v=abc123" in page
    assert "Compass doesn't control what YouTube recommends" in page


def test_student_view_shows_no_assessment_section_at_all(monkeypatch):
    """The check itself now happens digitally in Activity Log's own review
    card -- there's nothing left for him to do with this text, so student
    view shows nothing rather than a "your parent has it" stub that no
    longer matches how it's actually checked."""
    page = _rendered(monkeypatch, for_parent=False)
    assert "Assessment" not in page


def test_parent_view_still_shows_the_assessment_description(monkeypatch):
    page = _rendered(monkeypatch, for_parent=True)
    assert "Assessment" in page
    assert "Ten items, mixed representations." in page


def test_student_view_also_sees_the_suggested_video(monkeypatch):
    """Unlike the answer key, a verified video is meant for him too -- it's
    checked against a real search result and restricted to YouTube before it
    ever reaches the renderer, so there's nothing left to redact."""
    page = _rendered(monkeypatch, for_parent=False)
    assert "Functions Explained With Real Examples" in page
    assert "https://www.youtube.com/watch?v=abc123" in page
    # The parent-only "here's why this is safe" framing stays parent-side, though.
    assert "Compass doesn't control what YouTube recommends" not in page


def test_no_video_section_when_none_was_found(monkeypatch):
    lesson = _lesson()
    lesson["activities"][0]["video"] = {
        "found": False, "title": "", "url": "", "channel": "", "why": "",
    }

    import compass.ui as ui

    written: list[str] = []

    class Recorder:
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
            return iter([Recorder(), Recorder()])

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(ui, "st", Recorder())
    monkeypatch.setattr(ui, "is_parent", lambda: True)
    ui.render_lesson(lesson, for_parent=True)
    page = "\n".join(written)
    assert "Functions Explained With Real Examples" not in page
    assert "https://www.youtube.com/watch?v=abc123" not in page


def test_student_view_hides_compliance_credit_detail(monkeypatch):
    page = _rendered(monkeypatch, for_parent=False)
    assert "Whole lesson." not in page


def test_profile_editor_is_parent_only(monkeypatch, tmp_path):
    """His name, age, and interests feed every agent's prompt — configuration,
    not a preference — so he must not be able to open, let alone submit, this
    form himself."""
    import compass.ui as ui

    written: list[str] = []

    class Recorder:
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
            return iter([Recorder(), Recorder()])

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    from compass.storage.db import Database

    db = Database(tmp_path / "test.db")
    student = db.ensure_default_student()

    monkeypatch.setattr(ui, "st", Recorder())
    monkeypatch.setattr(ui, "is_parent", lambda: False)
    ui._profile_control(db, student)
    db.close()

    assert not written, "the student-view branch must render nothing at all"


def test_student_view_never_hides_streamlits_own_view_more_toggle(monkeypatch):
    """Regression: this used to force-hide Streamlit's native "View N more"
    sidebar collapse toggle for the student unconditionally, on the theory
    that hiding the parent-only pages above would always leave the rest
    fitting without it. That stopped being true the moment the page count
    grew past Streamlit's own collapse threshold (adding Coding Camp pushed
    it over) -- Quizzes and Coding both silently became unreachable for him,
    since the toggle that would have revealed them was itself hidden. The
    toggle must never be targeted by this CSS at all, regardless of how many
    pages exist."""
    import compass.ui as ui

    written: list[str] = []

    class Recorder:
        def __getattr__(self, _name):
            def record(*args, **kwargs):
                for arg in args:
                    if isinstance(arg, str):
                        written.append(arg)
                return Recorder()
            return record

    monkeypatch.setattr(ui, "st", Recorder())
    monkeypatch.setattr(ui, "is_parent", lambda: False)
    ui._hide_parent_only_nav()

    css = "\n".join(written)
    assert "stSidebarNavViewButton" not in css


def test_student_view_hides_the_parent_only_nav_tabs(monkeypatch):
    """Activity Log, Compliance, Student Profile, Courses, This Week, and Model
    Costs are all parent admin -- record-keeping, settings, spend -- rather than
    something he does. Each already gates its own content behind parent_only(),
    but the tab itself has to disappear too, not just the content behind it."""
    import compass.ui as ui

    written: list[str] = []

    class Recorder:
        def __getattr__(self, _name):
            def record(*args, **kwargs):
                for arg in args:
                    if isinstance(arg, str):
                        written.append(arg)
                return Recorder()
            return record

    monkeypatch.setattr(ui, "st", Recorder())
    monkeypatch.setattr(ui, "is_parent", lambda: False)
    ui._hide_parent_only_nav()

    css = "\n".join(written)
    for slug in ui._PARENT_ONLY_PAGES:
        assert f'href$="/{slug}"' in css
    # And the subjects/tiers he does use must never be targeted.
    for kept in ("Home", "Math", "Life_Skills", "Big_Projects", "Check_In"):
        assert f'href$="/{kept}"' not in css


def test_parent_view_leaves_the_nav_untouched(monkeypatch):
    import compass.ui as ui

    written: list[str] = []

    class Recorder:
        def __getattr__(self, _name):
            def record(*args, **kwargs):
                for arg in args:
                    if isinstance(arg, str):
                        written.append(arg)
                return Recorder()
            return record

    monkeypatch.setattr(ui, "st", Recorder())
    monkeypatch.setattr(ui, "is_parent", lambda: True)
    ui._hide_parent_only_nav()

    assert not written, "parent view must never hide nav tabs"


def test_folded_in_pages_are_hidden_from_the_nav_for_both_of_you(monkeypatch):
    """Choice Topics (now a Life Skills tab) and Landon's Travels (now
    always inside Big Projects, see Database.ensure_travel_log_project)
    are hidden from the sidebar for a parent too -- unlike _PARENT_ONLY_PAGES,
    which only hides from him, this one isn't gated by is_parent() at all."""
    import compass.ui as ui

    written: list[str] = []

    class Recorder:
        def __getattr__(self, _name):
            def record(*args, **kwargs):
                for arg in args:
                    if isinstance(arg, str):
                        written.append(arg)
                return Recorder()
            return record

    monkeypatch.setattr(ui, "st", Recorder())
    ui._hide_folded_in_nav()

    css = "\n".join(written)
    for slug in ui._FOLDED_IN_PAGES:
        assert f'href$="/{slug}"' in css
    for kept in ("Home", "Math", "Life_Skills", "Big_Projects", "Check_In"):
        assert f'href$="/{kept}"' not in css
