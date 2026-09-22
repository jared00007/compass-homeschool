"""Khan cards -- a parent hand-enters Khan Academy units/exercises as lesson
cards (any subject, in bulk): they schedule onto Landon's board, credit the
subject's hours, and keep one auto-graded quiz, without an AI-generated lesson
body. Every card shares the single `khan` agent + Khan page."""

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


def test_payload_is_a_link_plus_quiz_card():
    """The simplest shape: the Khan link in the overview and the quiz -- no typed
    step, nothing to hand-grade. The quiz is what scores it."""
    payload = khan_card.build_khan_card_payload(
        "math", "Multiplying & dividing powers",
        "https://www.khanacademy.org/x", 35, quiz=list(_QUIZ),
    )
    assert payload["activities"] == []
    assert "Open in Khan Academy" in payload["overview"]
    assert "khanacademy.org/x" in payload["overview"]
    assert payload["quiz"] == _QUIZ
    assert payload["learn"]["explanation"] == ""
    # No answer key exists on the card at all now.
    assert "answer" not in payload


def test_khan_card_is_ready_to_submit_only_after_the_quiz():
    """Landon's whole gate: take the quiz, turn it in. No writing to submit."""
    payload = khan_card.build_khan_card_payload(
        "math", "Exponents", "https://k/x", 35, quiz=list(_QUIZ),
    )
    lesson = {"payload": payload, "metadata": {}}
    ready, _ = ui._lesson_ready_to_submit(lesson)
    assert not ready  # quiz not taken yet
    lesson["metadata"]["quiz_result"] = {"correct": 4, "total": 5}
    ready, _ = ui._lesson_ready_to_submit(lesson)
    assert ready


def test_any_wa_subject_credits_itself():
    """Khan cards aren't limited to the four core academics -- music (art_and_
    music), health, anything credits its own WA subject."""
    payload = khan_card.build_khan_card_payload(
        "art_and_music", "Reading rhythms", "https://khan/x", 30, quiz=list(_QUIZ),
    )
    assert payload["subject_credits"][0]["subject"] == "art_and_music"


def test_generation_usage_is_lifted_off_the_question_to_the_top():
    quiz = [dict(_QUIZ[0], _usage={"input_tokens": 5, "output_tokens": 9})]
    payload = khan_card.build_khan_card_payload("math", "Skill", "https://k/x", 30, quiz=quiz)
    assert payload["_usage"] == {"input_tokens": 5, "output_tokens": 9}
    assert "_usage" not in payload["quiz"][0]


# --- parsing a pasted list -----------------------------------------------------


def test_parse_units_trims_bullets_and_numbers_and_blanks():
    text = "  Unit one\n- Exponents\n2. Negative exponents\n\n• Powers of products\n   \n"
    assert khan_card.parse_units(text) == [
        "Unit one", "Exponents", "Negative exponents", "Powers of products",
    ]


# --- creating + scheduling -----------------------------------------------------


def test_create_saves_under_the_khan_agent_and_credits_the_subject(db, student):
    today = date.today().isoformat()
    lesson_id = khan_card.create_khan_card(
        db, student, subject="math", unit="Exponent rules",
        url="https://khan/exp", minutes=35, day_iso=today, quiz=list(_QUIZ),
    )
    lesson = db.get_lesson(lesson_id)
    assert lesson["agent"] == "khan"       # one home for every Khan card
    assert lesson["subject"] == "math"     # credits the real WA subject
    assert lesson["metadata"]["planned_for"] == today
    assert lesson["metadata"]["source"] == "khan"
    khan_lessons = db.list_lessons(student["id"], agent="khan")
    assert any(l["id"] == lesson_id for l in weekly.due_lessons(khan_lessons, today))


def test_no_day_parks_it_in_the_backlog(db, student):
    lesson_id = khan_card.create_khan_card(
        db, student, subject="science", unit="Cells",
        url="https://khan/cells", minutes=55, day_iso=None, quiz=list(_QUIZ),
    )
    lesson = db.get_lesson(lesson_id)
    assert lesson["metadata"].get("held_back") is True
    khan = db.list_lessons(student["id"], agent="khan")
    assert not any(l["id"] == lesson_id for l in weekly.due_lessons(khan, date.today().isoformat()))


def test_create_rejects_bad_input(db, student):
    with pytest.raises(ValueError):
        khan_card.create_khan_card(db, student, subject="math", unit="",
                                   url="https://k/x", minutes=30, quiz=list(_QUIZ))
    with pytest.raises(ValueError):
        khan_card.create_khan_card(db, student, subject="not_a_subject", unit="Skill",
                                   url="https://k/x", minutes=30, quiz=list(_QUIZ))


def test_url_defaults_to_the_saved_khan_link(db, student):
    lid = khan_card.create_khan_card(
        db, student, subject="math", unit="Exponents",
        minutes=35, day_iso=date.today().isoformat(), quiz=list(_QUIZ),
    )
    link = db.get_lesson(lid)["metadata"]["resource_url"]
    assert link == "https://www.khanacademy.org/profile/me/courses"
    assert link in db.get_lesson(lid)["payload"]["overview"]

    db.set_setting("khan_base_url", "https://www.khanacademy.org/math")
    lid2 = khan_card.create_khan_card(
        db, student, subject="math", unit="Fractions",
        minutes=35, day_iso=date.today().isoformat(), quiz=list(_QUIZ),
    )
    assert db.get_lesson(lid2)["metadata"]["resource_url"] == "https://www.khanacademy.org/math"


# --- bulk create ---------------------------------------------------------------


def test_bulk_create_makes_a_card_per_unit(db, student):
    units = ["Exponents", "Negative exponents", "Powers of products"]
    result = khan_card.create_khan_cards(
        db, student, subject="math", units=units, minutes=35,
        day_iso=date.today().isoformat(), generate_quiz=False,
    )
    assert len(result["created"]) == 3
    assert result["quiz_failed"] == []
    titles = {db.get_lesson(i)["payload"]["title"] for i in result["created"]}
    assert titles == {f"Khan Academy: {u}" for u in units}


def test_bulk_create_survives_a_quiz_failure(db, student, monkeypatch):
    """A single quiz-generation hiccup doesn't sink the batch -- that card is
    added without a quiz and named in quiz_failed."""
    from compass.agents.llm import LessonGenerationError

    def boom(*a, **k):
        raise LessonGenerationError("model blip")

    monkeypatch.setattr(khan_card, "generate_khan_quiz", boom)
    result = khan_card.create_khan_cards(
        db, student, subject="math", units=["A", "B"], minutes=35,
        day_iso=date.today().isoformat(), generate_quiz=True,
    )
    assert len(result["created"]) == 2          # both still created
    assert result["quiz_failed"] == ["A", "B"]  # neither got a quiz
    for lid in result["created"]:
        assert db.get_lesson(lid)["payload"]["quiz"] == []


# --- the quiz generation path (no real API) ------------------------------------


def test_generate_khan_quiz_verifies_and_keeps_usage(student, monkeypatch):
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
    assert len(quiz) == 1
    assert quiz[0]["_usage"] == {"input_tokens": 11, "output_tokens": 22}


def test_created_card_renders_with_the_khan_link(db, student, monkeypatch):
    lesson_id = khan_card.create_khan_card(
        db, student, subject="math", unit="Exponent rules",
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
