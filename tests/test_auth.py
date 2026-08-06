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
             "instructions": "Decide whether each relation is a function."}
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


def test_student_view_hides_compliance_credit_detail(monkeypatch):
    page = _rendered(monkeypatch, for_parent=False)
    assert "Whole lesson." not in page
