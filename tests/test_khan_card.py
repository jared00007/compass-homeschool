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


# --- courses: load an ordered lesson list, assign it out -----------------------


def test_create_course_makes_ordered_backlog_cards(db, student):
    lessons = ["Multiplying & dividing powers", "Negative exponents", "Powers of products"]
    result = khan_card.create_course(
        db, student, subject="math", course="Exponents & radicals",
        lessons=lessons, minutes=30,  # generate_quiz defaults off
    )
    ids = result["created"]
    assert len(ids) == 3
    first = db.get_lesson(ids[0])
    m = first["metadata"]
    assert first["agent"] == "khan" and first["subject"] == "math"
    assert m["held_back"] is True and m["khan_part"] == 1
    assert m["khan_course"] == "Exponents & radicals"
    # Numbered titles so the order reads at a glance.
    assert first["title"] == "1. Multiplying & dividing powers"
    assert db.get_lesson(ids[2])["title"] == "3. Powers of products"
    # One shared course id, and none is due (all in the backlog).
    assert len({db.get_lesson(i)["metadata"]["khan_course_id"] for i in ids}) == 1
    khan = db.list_lessons(student["id"], agent="khan")
    assert not weekly.due_lessons(khan, date.today().isoformat())


def test_assign_course_card_schedules_it_and_generates_the_quiz(db, student, monkeypatch):
    result = khan_card.create_course(
        db, student, subject="math", course="Exponents",
        lessons=["Multiply powers", "Divide powers"], minutes=30,
    )
    first = result["created"][0]
    monkeypatch.setattr(khan_card, "generate_khan_quiz", lambda *a, **k: list(_QUIZ))
    khan_card.assign_course_card(db, student, first, day_iso=date.today().isoformat())
    lesson = db.get_lesson(first)
    assert lesson["metadata"].get("held_back") is None            # scheduled now
    assert lesson["metadata"]["planned_for"] == date.today().isoformat()
    assert lesson["title"] == "1. Multiply powers"                # numbered title kept
    assert lesson["payload"]["quiz"] == _QUIZ                     # quiz generated on assign
    khan = db.list_lessons(student["id"], agent="khan")
    assert any(l["id"] == first for l in weekly.due_lessons(khan, date.today().isoformat()))


def test_course_summary_tracks_progress(db, student):
    result = khan_card.create_course(
        db, student, subject="math", course="Fractions",
        lessons=["Add", "Subtract", "Multiply", "Divide"], minutes=30,
    )
    ids = result["created"]
    khan_card.assign_course_card(db, student, ids[0], day_iso=date.today().isoformat(),
                                 quiz=list(_QUIZ))
    db.set_lesson_status(ids[0], "completed")

    summary = khan_card.course_summaries(db, student["id"])[0]
    assert summary["course"] == "Fractions" and summary["total"] == 4
    assert summary["done"] == 1 and summary["unassigned"] == 3
    assert summary["next_unassigned"]["metadata"]["khan_part"] == 2  # part 1 is assigned


def test_create_course_rejects_bad_input(db, student):
    with pytest.raises(ValueError):
        khan_card.create_course(db, student, subject="math", course="", lessons=["a"], minutes=30)
    with pytest.raises(ValueError):
        khan_card.create_course(db, student, subject="not_a_subject", course="X", lessons=["a"], minutes=30)
    with pytest.raises(ValueError):
        khan_card.create_course(db, student, subject="math", course="X", lessons=[], minutes=30)


def test_a_completed_khan_card_is_rewind_eligible(db, student):
    """The metadata payoff: finished Khan work feeds Rewind. A completed Khan card
    shows up in the pool a Rewind draws from (it didn't before)."""
    lid = khan_card.create_khan_card(
        db, student, subject="math", unit="Exponent rules",
        minutes=35, day_iso=date.today().isoformat(), quiz=list(_QUIZ),
    )
    db.set_lesson_status(lid, "completed")
    pool = db.completed_lessons_for_review(student["id"])
    khan = [l for l in pool if l["agent"] == "khan"]
    assert any(l["id"] == lid for l in khan)
    assert khan[0]["subject"] == "math"  # carries the real subject for the review


def test_schedule_unit_lays_lessons_across_school_days(db, student):
    from datetime import date, timedelta

    ids = khan_card.create_course(
        db, student, subject="math", course="Exponents",
        lessons=["A", "B", "C", "D", "E"], minutes=30)["created"]
    # Start on a Friday so the 2/day pace has to skip the weekend.
    friday = date(2026, 10, 2)  # a Friday
    assert friday.weekday() == 4
    result = khan_card.schedule_unit(db, student, _course_id(db, ids[0]),
                                     start_day=friday, per_day=2)
    assert result["scheduled"] == 5
    planned = {
        db.get_lesson(i)["metadata"]["khan_part"]: db.get_lesson(i)["metadata"]["planned_for"]
        for i in ids
    }
    monday = (friday + timedelta(days=3)).isoformat()
    tuesday = (friday + timedelta(days=4)).isoformat()
    # 2 on Fri, 2 on Mon (weekend skipped), 1 on Tue -- in lesson order.
    assert planned[1] == friday.isoformat() and planned[2] == friday.isoformat()
    assert planned[3] == monday and planned[4] == monday
    assert planned[5] == tuesday


def test_schedule_unit_skips_done_cards_and_errors_when_empty(db, student):
    from datetime import date

    ids = khan_card.create_course(
        db, student, subject="math", course="Exponents",
        lessons=["A", "B"], minutes=30)["created"]
    for i in ids:
        db.set_lesson_status(i, "completed")
    with pytest.raises(ValueError):
        khan_card.schedule_unit(db, student, _course_id(db, ids[0]),
                                start_day=date.today(), per_day=2)


def test_schedule_all_units_chains_every_unit_back_to_back(db, student):
    from datetime import date, timedelta

    # Two units loaded oldest-first: the earlier unit should take the early days.
    first = khan_card.create_course(
        db, student, subject="math", course="Exponents",
        lessons=["A", "B", "C"], minutes=30)["created"]
    second = khan_card.create_course(
        db, student, subject="math", course="Polynomials",
        lessons=["D", "E"], minutes=30)["created"]

    monday = date(2026, 10, 5)  # a Monday
    assert monday.weekday() == 0
    result = khan_card.schedule_all_units(db, student, start_day=monday, per_day=2)

    assert result["scheduled"] == 5
    assert result["units"] == 2
    day_of = lambda i: db.get_lesson(i)["metadata"]["planned_for"]
    tuesday = (monday + timedelta(days=1)).isoformat()
    wednesday = (monday + timedelta(days=2)).isoformat()
    # Unit 1 (oldest) flows first: A,B on Mon; C then unit-2's D on Tue; E on Wed.
    assert day_of(first[0]) == monday.isoformat()
    assert day_of(first[1]) == monday.isoformat()
    assert day_of(first[2]) == tuesday
    assert day_of(second[0]) == tuesday
    assert day_of(second[1]) == wednesday


def test_schedule_all_units_errors_when_nothing_is_left(db, student):
    from datetime import date

    ids = khan_card.create_course(
        db, student, subject="math", course="Exponents",
        lessons=["A", "B"], minutes=30)["created"]
    for i in ids:
        db.set_lesson_status(i, "completed")
    with pytest.raises(ValueError):
        khan_card.schedule_all_units(db, student, start_day=date.today(), per_day=2)


def test_clear_unfinished_cards_wipes_board_and_backlog_keeps_approved(db, student):
    from datetime import date

    # A backlog card (held_back), a board card (planned on a day), a skipped
    # leftover, and an approved one in the record.
    ids = khan_card.create_course(
        db, student, subject="math", course="Exponents",
        lessons=["A", "B", "C", "D"], minutes=30)["created"]
    khan_card.assign_course_card(db, student, ids[1], day_iso=date.today().isoformat(),
                                 generate_quiz=False)  # -> on the board (planned)
    db.set_lesson_status(ids[2], "skipped")
    db.set_lesson_status(ids[3], "completed")          # approved / official record

    clearable = khan_card.clearable_cards(db, student)
    assert ids[3] not in {c["id"] for c in clearable}  # the completed one is spared
    assert {ids[0], ids[1], ids[2]} <= {c["id"] for c in clearable}

    cleared = khan_card.clear_unfinished_cards(db, student)
    assert cleared == 3
    remaining = db.list_lessons(student["id"], agent="khan", limit=100)
    assert [c["id"] for c in remaining] == [ids[3]]     # only the approved card is left


def test_clear_unfinished_cards_keeps_logged_hours(db, student):
    from datetime import date

    lid = khan_card.create_khan_card(
        db, student, subject="math", unit="Exponent rules",
        minutes=35, day_iso=date.today().isoformat(), quiz=[],
    )
    db.log_activity(
        student_id=student["id"], title="Khan work", tier="core",
        primary_subject="math", minutes=35, subject_credits={"math": 35},
        lesson_id=lid,
    )
    # Logging hours completes the card (so it'd normally be KEPT). Force it back to
    # a board state to exercise the delete-safety path: a cleared card whose hours
    # must still survive (activities.lesson_id is ON DELETE SET NULL).
    db.set_lesson_status(lid, "planned")
    khan_card.clear_unfinished_cards(db, student)
    assert db.get_lesson(lid) is None
    acts = db.list_activities(student["id"])
    assert any(a["minutes"] == 35 and a["primary_subject"] == "math" for a in acts)


def test_assigning_a_checkpoint_never_generates_a_compass_quiz(db, student, monkeypatch):
    """A checkpoint IS the Khan quiz, so scheduling it -- even with quiz
    generation on -- must not attach a Compass auto-quiz (and must not call the
    generator)."""
    from datetime import date

    khan_card.create_course_from_outline(
        db, student, subject="math", minutes=30, text=(
            "Unit: U\n"
            "Lesson: A\n"
            "Numbers and operations: Quiz 1 - Quiz · 5 questions\n"
        ),
    )
    check = [
        c for c in db.list_lessons(student["id"], agent="khan")
        if (c.get("metadata") or {}).get("khan_checkpoint")
    ][0]

    def _boom(*a, **k):
        raise AssertionError("a checkpoint must never call the quiz generator")
    monkeypatch.setattr(khan_card, "generate_khan_quiz", _boom)

    khan_card.assign_course_card(
        db, student, check["id"], day_iso=date.today().isoformat(), generate_quiz=True,
    )
    assert db.get_lesson(check["id"])["payload"]["quiz"] == []   # still no Compass quiz


def test_clear_all_cards_wipes_approved_too_but_keeps_hours(db, student):
    from datetime import date

    ids = khan_card.create_course(
        db, student, subject="math", course="Exponents",
        lessons=["A", "B"], minutes=30)["created"]
    khan_card.assign_course_card(db, student, ids[0], day_iso=date.today().isoformat(),
                                 generate_quiz=False)
    db.log_activity(
        student_id=student["id"], title="Khan work", tier="core",
        primary_subject="math", minutes=40, subject_credits={"math": 40},
        lesson_id=ids[0],
    )
    db.set_lesson_status(ids[0], "completed")   # approved / in the record

    cleared = khan_card.clear_all_cards(db, student)
    assert cleared == 2                           # BOTH the approved and the other go
    assert db.list_lessons(student["id"], agent="khan", limit=100) == []
    assert khan_card.course_summaries(db, student["id"]) == []   # "Your Khan units" empties
    # The logged hours survive the delete (school-year record kept).
    acts = db.list_activities(student["id"])
    assert any(a["minutes"] == 40 and a["primary_subject"] == "math" for a in acts)


def _course_id(db, lesson_id):
    return db.get_lesson(lesson_id)["metadata"]["khan_course_id"]


def test_parse_course_outline_splits_units_and_lessons():
    text = (
        "Course: Algebra 1\n"
        "Unit: Exponents & radicals\n"
        "Multiplying & dividing powers\n"
        "- Negative exponents\n"
        "Unit 2: Polynomials\n"
        "1. Adding polynomials\n"
        "Multiplying binomials\n"
    )
    parsed = khan_card.parse_course_outline(text)
    assert parsed["course"] == "Algebra 1"
    assert [u["unit"] for u in parsed["units"]] == ["Exponents & radicals", "Polynomials"]
    # No "Lesson:" markers -> flat style: each line is its own name-only card.
    def _lessons(u):
        return [e for e in u["entries"] if e["kind"] == "lesson"]
    assert [l["name"] for l in _lessons(parsed["units"][0])] == [
        "Multiplying & dividing powers", "Negative exponents"]
    assert [l["name"] for l in _lessons(parsed["units"][1])] == [
        "Adding polynomials", "Multiplying binomials"]
    assert all(l["items"] == [] for u in parsed["units"] for l in _lessons(u))


def test_parse_course_outline_groups_lessons_with_their_items():
    """Khan's real Unit -> Lesson -> items shape: each 'Lesson:' is one card and
    the videos/exercises under it become that card's checklist. Quizzes and the
    unit test are dropped."""
    text = (
        "Unit: Numbers and operations\n"
        "Lesson: Repeating decimals\n"
        "Converting a fraction to a repeating decimal - Video · 4 minutes\n"
        "Writing fractions as repeating decimals - Exercise · 4 questions\n"
        "Lesson: Square roots & cube roots\n"
        "Intro to square roots - Video · 5 minutes\n"
        "Square roots - Exercise · 4 questions\n"
        "Numbers and operations: Quiz 1 - Quiz · 6 questions\n"
        "Numbers and operations: Unit test\n"
    )
    parsed = khan_card.parse_course_outline(text)
    entries = parsed["units"][0]["entries"]
    lessons = [e for e in entries if e["kind"] == "lesson"]
    assert [l["name"] for l in lessons] == ["Repeating decimals", "Square roots & cube roots"]
    assert len(lessons[0]["items"]) == 2 and len(lessons[1]["items"]) == 2
    assert "Intro to square roots - Video · 5 minutes" in lessons[1]["items"]
    # The quiz and the unit test became CHECKPOINTS (not lessons/items), each
    # covering the lessons before it.
    checks = [e for e in entries if e["kind"] != "lesson"]
    assert [c["kind"] for c in checks] == ["quiz", "unit_test"]
    assert checks[0]["covers"] == ["Repeating decimals", "Square roots & cube roots"]
    assert checks[1]["covers"] == ["Repeating decimals", "Square roots & cube roots"]


def test_a_lesson_cards_checklist_shows_on_the_card(db, student):
    khan_card.create_course_from_outline(
        db, student, subject="math", minutes=30, text=(
            "Unit: Numbers and operations\n"
            "Lesson: Square roots & cube roots\n"
            "Intro to square roots - Video · 5 minutes\n"
            "Square roots - Exercise · 4 questions\n"
        ),
    )
    card = db.list_lessons(student["id"], agent="khan")[0]
    assert card["metadata"]["khan_items"] == [
        "Intro to square roots - Video · 5 minutes",
        "Square roots - Exercise · 4 questions",
    ]
    assert "On Khan, work through:" in card["payload"]["overview"]
    assert "Intro to square roots" in card["payload"]["overview"]


def test_create_course_from_outline_makes_checkpoint_cards(db, student):
    khan_card.create_course_from_outline(
        db, student, subject="math", minutes=30, text=(
            "Unit: Numbers and operations\n"
            "Lesson: Repeating decimals\n"
            "Writing fractions - Exercise · 4 questions\n"
            "Lesson: Square roots & cube roots\n"
            "Square roots - Exercise · 4 questions\n"
            "Numbers and operations: Quiz 1 - Quiz · 6 questions\n"
            "Numbers and operations: Unit test\n"
        ),
    )
    cards = sorted(
        db.list_lessons(student["id"], agent="khan"),
        key=lambda c: c["metadata"]["khan_part"],
    )
    kinds = [(c["metadata"].get("khan_checkpoint_kind") or "lesson") for c in cards]
    assert kinds == ["lesson", "lesson", "quiz", "unit_test"]

    quiz_card = cards[2]
    assert quiz_card["metadata"]["khan_checkpoint"] is True
    assert quiz_card["metadata"]["khan_covers"] == [
        "Repeating decimals", "Square roots & cube roots"]
    assert "📝" in quiz_card["title"] and "Quiz 1" in quiz_card["title"]  # unit prefix stripped
    assert "Checkpoint" in quiz_card["payload"]["overview"]
    assert "It covers" in quiz_card["payload"]["overview"]
    assert quiz_card["payload"]["quiz"] == []          # a checkpoint carries no Compass quiz


def test_parse_course_outline_skips_khan_page_chrome():
    text = (
        "Unit: Exponents\n"
        "Multiplying powers\n"
        "Quiz 1\n"
        "Practice\n"
        "80% mastery\n"
        "Negative exponents\n"
        "Unit test\n"
    )
    parsed = khan_card.parse_course_outline(text)
    assert len(parsed["units"]) == 1
    entries = parsed["units"][0]["entries"]
    lessons = [e["name"] for e in entries if e["kind"] == "lesson"]
    # Page chrome (Practice, mastery %) dropped; the two real lessons kept, and
    # "Quiz 1" / "Unit test" became checkpoints, not lessons.
    assert lessons == ["Multiplying powers", "Negative exponents"]
    # A bare "Quiz 1" (no "· N questions") is just chrome and is dropped; the
    # "Unit test" row becomes a checkpoint.
    kinds = [e["kind"] for e in entries if e["kind"] != "lesson"]
    assert kinds == ["unit_test"]


def test_create_course_from_outline_loads_every_unit(db, student):
    text = (
        "Course: Algebra 1\n"
        "Unit: Exponents\n"
        "Multiply powers\n"
        "Divide powers\n"
        "Unit: Radicals\n"
        "Square roots\n"
    )
    result = khan_card.create_course_from_outline(
        db, student, subject="math", text=text, minutes=30)
    assert result["course"] == "Algebra 1"
    assert result["unit_count"] == 2 and result["card_count"] == 3
    khan = db.list_lessons(student["id"], agent="khan")
    units = {(l.get("metadata") or {}).get("khan_course") for l in khan}
    assert units == {"Exponents", "Radicals"}


def test_create_course_from_outline_rejects_an_empty_paste(db, student):
    with pytest.raises(ValueError):
        khan_card.create_course_from_outline(
            db, student, subject="math", text="Quiz\nPractice\nUnit test\n", minutes=30)


def test_render_khan_courses_shows_a_loaded_course_and_progress(db, student, monkeypatch):
    """The Backlog course manager renders a loaded course with its progress, and
    doesn't blow up doing it."""
    khan_card.create_course(
        db, student, subject="math", course="Algebra basics",
        lessons=["Exponents", "Radicals", "Polynomials", "Factoring"], minutes=30,
    )
    written: list[str] = []

    class Rec:
        session_state: dict = {}
        def __getattr__(self, _n):
            def rec(*a, **k):
                for x in list(a) + list(k.values()):
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
    ui.render_khan_courses(db, student)
    page = "\n".join(written)
    assert "Algebra basics" in page
    assert "0 of 4 done" in page
    assert "1. Exponents" in page  # the ordered lesson list


def test_khan_board_tag_colors_by_subject_and_marks_khan():
    """A Khan card's board tag is colored by its subject and labeled 'Khan · X',
    with the 🅰️ marker -- two color signals (subject bar + fixed Khan stripe)."""
    color, icon, label = ui.board_card_tag("lesson", {"agent": "khan", "subject": "math"})
    assert color == ui.SUBJECT_TAG_COLORS["math"]
    assert icon == "🅰️" and label == "Khan · Math"
    # A different subject gets a different color.
    art_color, _, art_label = ui.board_card_tag(
        "lesson", {"agent": "khan", "subject": "art_and_music"}
    )
    assert art_color == ui.SUBJECT_TAG_COLORS["art_and_music"] and art_color != color
    assert art_label.startswith("Khan ·")
    # A card loaded from a unit names the unit on the bar, so you can tell which
    # unit a numbered card belongs to at a glance; color still encodes subject.
    unit_color, _, unit_label = ui.board_card_tag(
        "lesson",
        {"agent": "khan", "subject": "math",
         "metadata": {"khan_course": "Exponents & radicals"}},
    )
    assert unit_color == ui.SUBJECT_TAG_COLORS["math"]  # still subject-colored
    assert unit_label == "Khan · Exponents & radicals"
    # A normal (non-Khan) lesson tag is unchanged.
    _, _, math_label = ui.board_card_tag("lesson", {"agent": "math", "subject": "math"})
    assert math_label == "Math"


def test_khan_card_states_its_unit_on_the_card():
    """When a card comes from a loaded unit, the unit name is stated in the
    lesson body so it's visible when the card is opened, not just on the bar."""
    payload = khan_card.build_khan_card_payload(
        "math", "Multiplying powers", "https://khan", 30, course="Exponents & radicals",
    )
    assert "**Unit:** Exponents & radicals" in payload["overview"]
    # A standalone card (no unit) has no unit line.
    plain = khan_card.build_khan_card_payload("math", "Multiplying powers", "https://khan", 30)
    assert "Unit:" not in plain["overview"]


def test_create_course_puts_the_unit_name_on_every_card(db, student):
    """Loading a unit tags each card with the unit name in its body."""
    khan_card.create_course(
        db, student, subject="math", course="Exponents & radicals",
        lessons=["Multiply powers", "Divide powers"], minutes=30,
    )
    for card in db.list_lessons(student["id"], agent="khan"):
        assert "**Unit:** Exponents & radicals" in card["payload"]["overview"]
