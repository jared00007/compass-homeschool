"""Khan cards -- a parent hand-enters a Khan Academy unit/exercise as a lesson
card: it schedules onto Landon's board, credits the subject's hours, and keeps
one auto-graded quiz, without an AI-generated lesson body."""

from __future__ import annotations

from datetime import date

import pytest

import compass.ui as ui
from compass import weekly
from compass.agents import khan_card
from compass.storage.db import Database


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "khan.db")
    yield database
    database.close()


@pytest.fixture()
def student(db):
    return db.ensure_default_student()


_QUIZ = [
    {"question": "2^3 · 2^4 = ?", "choices": ["2^7", "2^12", "4^7", "2^1"],
     "correct_index": 0, "explanation": "Same base — add the exponents."},
]


# --- the pure payload builder --------------------------------------------------


def test_payload_is_a_gradeable_link_card_with_the_quiz():
    payload = khan_card.build_khan_card_payload(
        "math", "Multiplying & dividing powers",
        "https://www.khanacademy.org/x", 35, quiz=list(_QUIZ),
    )
    # The one step carries an answer key, which is what makes it gradeable (and
    # so unlocks the parent's approve-and-log-hours control).
    assert len(ui._gradeable_activities(payload)) == 1
    # The Khan link is in front of him, and the quiz rides along.
    assert "khanacademy.org/x" in payload["activities"][0]["instructions"]
    assert payload["quiz"] == _QUIZ
    # No AI lesson body -- Khan does the teaching.
    assert payload["learn"]["explanation"] == ""
    assert payload["worked_example"]["steps"] == ""


def test_english_card_credits_reading_not_english():
    """English's agent key isn't a real WA subject -- it teaches (and credits)
    reading, same as a generated English lesson."""
    payload = khan_card.build_khan_card_payload(
        "english", "Theme in a short story", "https://khan/x", 50, quiz=list(_QUIZ),
    )
    assert payload["subject_credits"][0]["subject"] == "reading"
    assert payload["subject_credits"][0]["minutes"] == 50


def test_generation_usage_is_lifted_off_the_question_to_the_top():
    """Token usage from the quiz generation belongs on the payload for the cost
    report, never on a question the student sees."""
    quiz = [dict(_QUIZ[0], _usage={"input_tokens": 5, "output_tokens": 9})]
    payload = khan_card.build_khan_card_payload("math", "Skill", "https://k/x", 30, quiz=quiz)
    assert payload["_usage"] == {"input_tokens": 5, "output_tokens": 9}
    assert "_usage" not in payload["quiz"][0]


# --- creating + scheduling -----------------------------------------------------


def test_create_schedules_the_card_and_credits_the_subject(db, student):
    today = date.today().isoformat()
    lesson_id = khan_card.create_khan_card(
        db, student, agent_key="math", unit="Exponent rules",
        url="https://khan/exp", minutes=35, day_iso=today, quiz=list(_QUIZ),
    )
    lesson = db.get_lesson(lesson_id)
    # Saved under the subject's own agent key so it lives with that subject.
    assert lesson["agent"] == "math"
    assert lesson["metadata"]["planned_for"] == today
    assert lesson["metadata"]["source"] == "khan"
    # It surfaces as a due math lesson the same day.
    math_lessons = db.list_lessons(student["id"], agent="math")
    assert any(l["id"] == lesson_id for l in weekly.due_lessons(math_lessons, today))


def test_no_day_parks_it_in_the_backlog(db, student):
    lesson_id = khan_card.create_khan_card(
        db, student, agent_key="science", unit="Cells",
        url="https://khan/cells", minutes=55, day_iso=None, quiz=list(_QUIZ),
    )
    lesson = db.get_lesson(lesson_id)
    assert lesson["metadata"].get("held_back") is True
    # Held-back lessons are pulled out of his due list.
    sci = db.list_lessons(student["id"], agent="science")
    assert not any(l["id"] == lesson_id for l in weekly.due_lessons(sci, date.today().isoformat()))


def test_create_rejects_bad_input(db, student):
    with pytest.raises(ValueError):
        khan_card.create_khan_card(db, student, agent_key="math", unit="",
                                   url="https://k/x", minutes=30, quiz=list(_QUIZ))
    with pytest.raises(ValueError):
        khan_card.create_khan_card(db, student, agent_key="math", unit="Skill",
                                   url="  ", minutes=30, quiz=list(_QUIZ))
    with pytest.raises(ValueError):
        khan_card.create_khan_card(db, student, agent_key="art", unit="Skill",
                                   url="https://k/x", minutes=30, quiz=list(_QUIZ))


# --- the quiz generation path (no real API) ------------------------------------


def test_generate_khan_quiz_verifies_and_keeps_usage(student, monkeypatch):
    """The one model call a card makes: it runs the same verify_quiz guard every
    lesson quiz gets, and carries the token usage back for cost tracking."""
    def fake_generate_lesson(*args, **kwargs):
        return {
            "quiz": [
                dict(_QUIZ[0]),
                {"question": "bad", "choices": ["only", "three", "here"],
                 "correct_index": 0, "explanation": "x"},  # malformed -> dropped
            ],
            "_usage": {"input_tokens": 11, "output_tokens": 22},
        }

    monkeypatch.setattr(khan_card, "generate_lesson", fake_generate_lesson)
    quiz = khan_card.generate_khan_quiz(student, "math", "Exponent rules")
    assert len(quiz) == 1  # the malformed question was dropped by verify_quiz
    assert quiz[0]["_usage"] == {"input_tokens": 11, "output_tokens": 22}


def test_created_card_renders_without_leaking_the_answer(db, student, monkeypatch):
    """The card renders through the ordinary lesson UI, shows the Khan link, and
    never puts its parent-facing answer key on Landon's screen."""
    lesson_id = khan_card.create_khan_card(
        db, student, agent_key="math", unit="Exponent rules",
        url="https://khan/exp", minutes=35, day_iso=date.today().isoformat(),
        quiz=list(_QUIZ),
    )
    lesson = db.get_lesson(lesson_id)

    written: list[str] = []

    class Rec:
        session_state: dict = {}
        def __getattr__(self, _n):
            def rec(*a, **k):
                for x in a:
                    if isinstance(x, str):
                        written.append(x)
                return self
            return rec
        def __getitem__(self, _i): return self
        def __iter__(self): return iter([self, self])
        def __enter__(self): return self
        def __exit__(self, *e): return False
        def __bool__(self): return False

    monkeypatch.setattr(ui, "st", Rec())
    monkeypatch.setattr(ui, "is_parent", lambda: False)
    ui.render_lesson(lesson["payload"], for_parent=False)
    page = "\n".join(written)
    assert "Open in Khan Academy" in page
    assert "khan/exp" in page
    assert "Approve once he's actually done" not in page  # the answer key stays hidden
