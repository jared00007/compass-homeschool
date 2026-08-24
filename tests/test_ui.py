"""The shared UI loop every Tier 1 agent page runs through.

`generate_and_log` replaced four near-identical hand-maintained copies of the
generate → review → log block. That consolidation is only worth it if the copy
that survived actually does the things the four were each responsible for, so
these tests pin the parts that would be silently skippable: the warnings from
credit/video normalization, the redacting renderer, and the per-agent session
key that keeps an expensive lesson alive across a rerun.
"""

from __future__ import annotations

from datetime import date

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


def button_stub(written: list[str], button_pressed: str):
    """A `st.button` override that both fires on the requested key and still
    records the button's label -- a plain `lambda ...: key == button_pressed`
    fires correctly but silently drops the label from `written`, which only
    matters for a test that (like several below) asserts on page text from
    the very same render as the click."""

    def stub(*args, key=None, **kwargs):
        for arg in args:
            if isinstance(arg, str):
                written.append(arg)
        return key == button_pressed

    return stub


def a_lesson(**overrides):
    payload = {
        "title": "Two-Step Equations",
        "overview": "Undo the addition, then the multiplication.",
        "learning_objectives": ["Solve for x"],
        "activities": [
            {"title": "Practice", "kind": "practice", "minutes": 60,
             "instructions": "Solve problems 1-10.",
             "example": "Worked model: solve 5x + 3 = 18 step by step.",
             "video": {"found": False, "title": "", "url": "", "channel": "", "why": ""}}
        ],
        "materials": ["Pencil"],
        "assessment": {"kind": "check", "description": "Ten items",
                       "mastery_criteria": "Answer key: 8 of 10"},
        "subject_credits": [{"subject": "math", "minutes": 60, "justification": "All of it."}],
        "estimated_minutes": 60,
        "parent_notes": "Watch for sign errors.",
        "branches": [],
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


def test_md_escapes_dollar_signs_so_streamlit_never_renders_them_as_latex():
    """Streamlit's markdown renderer treats a `$...$` pair as inline LaTeX --
    without escaping, a word problem mentioning two prices in the same block
    of text silently turns everything between them into a rendered equation.
    Reported live: "Snack bars: 6 bars for $4.20, or 10 bars for $6.50" had
    "4.20, or 10 bars for" render as a formula instead of plain text."""
    assert ui.md("6 bars for $4.20, or 10 bars for $6.50") == (
        "6 bars for \\$4.20, or 10 bars for \\$6.50"
    )
    assert ui.md(None) == ""
    assert ui.md("") == ""
    assert ui.md("no dollar signs here") == "no dollar signs here"


def test_activity_instructions_with_dollar_amounts_render_escaped(monkeypatch, db, student):
    lesson = a_lesson()
    lesson["activities"][0]["instructions"] = (
        "Snack bars: 6 bars for $4.20, or 10 bars for $6.50. Which is cheaper?"
    )
    generated = GeneratedLesson(
        lesson_id=1,
        proposal=TopicProposal(topic="t", rationale="r", strategy="s"),
        payload=lesson,
        warnings=[],
    )
    page, _ = run(monkeypatch, db, student, generated=generated)
    assert "6 bars for \\$4.20, or 10 bars for \\$6.50" in page


def test_the_worked_example_is_shown_before_the_instructions(monkeypatch, db, student):
    generated = GeneratedLesson(
        lesson_id=1,
        proposal=TopicProposal(topic="t", rationale="r", strategy="s"),
        payload=a_lesson(),
        warnings=[],
    )
    page, _ = run(monkeypatch, db, student, generated=generated)
    assert "Worked model: solve 5x + 3 = 18 step by step." in page
    assert page.index("Worked model:") < page.index("Solve problems 1-10.")


def test_materials_render_before_activities(monkeypatch, db, student):
    """He should see what he needs before being told what to do with it."""
    generated = GeneratedLesson(
        lesson_id=1,
        proposal=TopicProposal(topic="t", rationale="r", strategy="s"),
        payload=a_lesson(),
        warnings=[],
    )
    page, _ = run(monkeypatch, db, student, generated=generated)
    assert page.index("**Materials**") < page.index("**Activities**")


def test_an_activitys_video_renders_before_its_example_and_instructions(monkeypatch, db, student):
    """One video per activity, not one per lesson -- it's that activity's own
    entry point, so it shows before the worked example and instructions for
    that same activity."""
    lesson = a_lesson()
    lesson["activities"][0]["video"] = {
        "found": True, "title": "Two-Step Equations Explained",
        "url": "https://youtube.com/watch?v=abc", "channel": "Khan Academy",
        "why": "Shows the same undo-in-order idea worked out loud.",
    }
    generated = GeneratedLesson(
        lesson_id=1,
        proposal=TopicProposal(topic="t", rationale="r", strategy="s"),
        payload=lesson,
        warnings=[],
    )
    page, _ = run(monkeypatch, db, student, generated=generated)
    assert "Two-Step Equations Explained" in page
    assert page.index("**Activities**") < page.index("Two-Step Equations Explained")
    assert page.index("Two-Step Equations Explained") < page.index("Worked model:")
    assert page.index("Worked model:") < page.index("Solve problems 1-10.")


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


def test_no_pending_lesson_shows_no_warning(monkeypatch, db, student):
    page, _ = run(monkeypatch, db, student)
    assert "already generated and unlogged" not in page


def test_a_pending_planned_lesson_warns_before_generating_another(monkeypatch, db, student):
    """The actual bug this guards against: session state is empty (a fresh
    session, e.g. after an app restart) but the database already has an
    unlogged lesson for this agent -- the page must say so instead of
    looking untouched and inviting a duplicate."""
    db.save_lesson(
        student["id"], "math", "math", "topic", "Two-Step Equations", payload={"a": 1}
    )
    page, _ = run(monkeypatch, db, student)
    assert "already generated and unlogged" in page
    assert "Two-Step Equations" in page


def test_no_warning_for_the_lesson_already_held_in_session(monkeypatch, db, student):
    """The one exception: a pending lesson that IS the one already on screen
    isn't a forgotten duplicate, so it shouldn't warn about itself."""
    lesson_id = db.save_lesson(
        student["id"], "math", "math", "topic", "Two-Step Equations", payload={"a": 1}
    )
    generated = GeneratedLesson(
        lesson_id=lesson_id,
        proposal=TopicProposal(topic="t", rationale="r", strategy="s"),
        payload=a_lesson(),
        warnings=[],
    )
    page, _ = run(monkeypatch, db, student, generated=generated)
    assert "already generated and unlogged" not in page


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


def test_current_lesson_matches_the_day_not_whichever_id_is_highest(monkeypatch, db, student):
    """Regression: batch-planning a whole week in one sitting means Friday's
    lesson (generated last) has the highest id, even though today is
    Tuesday -- this must show Tuesday's, the same lesson Home's own
    "Lessons ready for you" list would show, not whichever was generated
    most recently."""
    _fix_today(monkeypatch, date(2026, 8, 11))  # a Tuesday
    tuesday_id = db.save_lesson(
        student["id"], "math", "math", "topic", "Tuesday's Lesson", payload=a_lesson(title="Tuesday's Lesson"),
        metadata={"week_start": "2026-08-10", "planned_for": "2026-08-11"},
    )
    friday_id = db.save_lesson(
        student["id"], "math", "math", "topic", "Friday's Lesson", payload=a_lesson(title="Friday's Lesson"),
        metadata={"week_start": "2026-08-10", "planned_for": "2026-08-14"},
    )
    assert friday_id > tuesday_id  # generated later in the same batch

    page = render_student_view(monkeypatch, db, student)
    assert "Tuesday's Lesson" in page
    assert "Friday's Lesson" not in page


def test_current_lesson_falls_back_to_the_oldest_overdue_day(monkeypatch, db, student):
    _fix_today(monkeypatch, date(2026, 8, 12))  # a Wednesday
    db.save_lesson(
        student["id"], "math", "math", "topic", "Monday's Lesson", payload=a_lesson(title="Monday's Lesson"),
        metadata={"week_start": "2026-08-10", "planned_for": "2026-08-10"},
    )
    db.save_lesson(
        student["id"], "math", "math", "topic", "Tuesday's Lesson", payload=a_lesson(title="Tuesday's Lesson"),
        metadata={"week_start": "2026-08-10", "planned_for": "2026-08-11"},
    )
    page = render_student_view(monkeypatch, db, student)
    assert "Monday's Lesson" in page  # oldest overdue, not Tuesday's


def test_current_lesson_never_shows_one_planned_for_a_later_day(monkeypatch, db, student):
    _fix_today(monkeypatch, date(2026, 8, 11))  # a Tuesday
    db.save_lesson(
        student["id"], "math", "math", "topic", "Friday's Lesson", payload=a_lesson(title="Friday's Lesson"),
        metadata={"week_start": "2026-08-10", "planned_for": "2026-08-14"},
    )
    page = render_student_view(monkeypatch, db, student)
    assert "Friday's Lesson" not in page
    assert "No math lesson has been set up yet" in page


def test_current_lesson_shows_a_today_badge_when_planned_for_today(monkeypatch, db, student):
    _fix_today(monkeypatch, date(2026, 8, 11))  # a Tuesday
    db.save_lesson(
        student["id"], "math", "math", "topic", "Tuesday's Lesson", payload=a_lesson(),
        metadata={"week_start": "2026-08-10", "planned_for": "2026-08-11"},
    )
    page = render_student_view(monkeypatch, db, student)
    assert "Tuesday — today's lesson" in page
    assert "Was due" not in page


def test_current_lesson_shows_a_was_due_badge_when_overdue(monkeypatch, db, student):
    _fix_today(monkeypatch, date(2026, 8, 12))  # a Wednesday
    db.save_lesson(
        student["id"], "math", "math", "topic", "Monday's Lesson", payload=a_lesson(),
        metadata={"week_start": "2026-08-10", "planned_for": "2026-08-10"},
    )
    page = render_student_view(monkeypatch, db, student)
    assert "Was due Monday" in page
    assert "today's lesson" not in page


def test_current_lesson_shows_no_day_badge_for_an_ordinary_on_demand_lesson(monkeypatch, db, student):
    """No planned_for at all -- generated the ordinary way, not through
    weekly batch-planning -- so there's no day to badge it with."""
    db.save_lesson(student["id"], "math", "math", "topic", "Two-Step Equations", payload=a_lesson())
    page = render_student_view(monkeypatch, db, student)
    assert "today's lesson" not in page
    assert "Was due" not in page


# --- render_past_lessons: always last, a separate call so page-specific ---
# --- content (English's Words to Review) can come between it and the      ---
# --- current lesson above ---------------------------------------------------


def render_past(monkeypatch, db, student, *, agent_key="math", selectbox_return=None):
    written: list[str] = []
    recorder = Recorder(written, {})
    recorder.selectbox = lambda *args, **kwargs: selectbox_return
    monkeypatch.setattr(ui, "st", recorder)
    ui.render_past_lessons(db, student, agent_key)
    return "\n".join(written)


def test_nothing_done_renders_nothing(monkeypatch, db, student):
    """No "Past lessons" heading at all when there's nothing to show --
    not an empty section sitting on the page."""
    page = render_past(monkeypatch, db, student)
    assert page == ""


def test_a_finished_lesson_can_be_reopened_from_past_lessons(monkeypatch, db, student):
    lesson_id = db.save_lesson(
        student["id"], "math", "math", "topic", "Two-Step Equations", payload=a_lesson()
    )
    db.mark_student_done(lesson_id)
    lesson = db.get_lesson(lesson_id)
    label = f"{lesson['created_at'][:10]} — {lesson['title']}"

    page = render_past(monkeypatch, db, student, selectbox_return=label)
    assert "Past lessons" in page
    assert "Solve problems 1-10." in page  # reopened, read-only


# --- render_today_checklist: his own accomplishment list, not a compliance one ---


def render_today(monkeypatch, db, student):
    written: list[str] = []
    monkeypatch.setattr(ui, "st", Recorder(written, {}))
    shown = ui.render_today_checklist(db, student)
    return "\n".join(written), shown


def test_nothing_done_yet_shows_nothing(monkeypatch, db, student):
    page, shown = render_today(monkeypatch, db, student)
    assert shown is False
    assert page == ""


def test_a_lesson_marked_done_today_appears(monkeypatch, db, student):
    lesson_id = db.save_lesson(
        student["id"], "math", "math", "topic", "Two-Step Equations", payload=a_lesson()
    )
    db.mark_student_done(lesson_id)
    page, shown = render_today(monkeypatch, db, student)
    assert shown is True
    assert "Two-Step Equations" in page
    assert "Today" in page


def test_a_quiz_score_from_today_is_included(monkeypatch, db, student):
    lesson_id = db.save_lesson(
        student["id"], "math", "math", "topic", "Two-Step Equations", payload=a_lesson()
    )
    db.mark_student_done(lesson_id)
    db.record_quiz_result(lesson_id, student["id"], correct=9, total=10, passed=True)
    page, _ = render_today(monkeypatch, db, student)
    assert "9/10" in page


def test_an_old_quiz_score_is_not_shown_as_todays(monkeypatch, db, student):
    """record_quiz_result stamps graded_on with today's date, so simulate a
    stale one by writing the metadata directly rather than faking the clock."""
    lesson_id = db.save_lesson(
        student["id"], "math", "math", "topic", "Two-Step Equations", payload=a_lesson()
    )
    db.mark_student_done(lesson_id)
    db.conn.execute(
        "UPDATE lessons SET metadata = json_set(metadata, '$.quiz_result', json(?)) WHERE id = ?",
        ('{"correct": 3, "total": 10, "passed": false, "graded_on": "2020-01-01"}', lesson_id),
    )
    db.conn.commit()
    page, _ = render_today(monkeypatch, db, student)
    assert "3/10" not in page


def test_a_life_skill_completed_today_appears(monkeypatch, db, student):
    skill_id = db.add_life_skill(student["id"], "Change a tire", category="Vehicle")
    db.set_life_skill_done(skill_id, True)
    page, shown = render_today(monkeypatch, db, student)
    assert shown is True
    assert "Change a tire" in page


def test_a_life_skill_completed_earlier_is_not_todays(monkeypatch, db, student):
    skill_id = db.add_life_skill(student["id"], "Change a tire", category="Vehicle")
    db.set_life_skill_done(skill_id, True)
    db.conn.execute(
        "UPDATE life_skills SET completed_on = ? WHERE id = ?", ("2020-01-01", skill_id)
    )
    db.conn.commit()
    page, shown = render_today(monkeypatch, db, student)
    assert shown is False
    assert "Change a tire" not in page


def test_a_lesson_marked_done_on_a_prior_day_is_not_todays(monkeypatch, db, student):
    lesson_id = db.save_lesson(
        student["id"], "math", "math", "topic", "Two-Step Equations", payload=a_lesson()
    )
    db.mark_student_done(lesson_id)
    db.conn.execute(
        "UPDATE lessons SET metadata = json_set(metadata, '$.student_done_on', '2020-01-01') "
        "WHERE id = ?",
        (lesson_id,),
    )
    db.conn.commit()
    page, shown = render_today(monkeypatch, db, student)
    assert shown is False
    assert "Two-Step Equations" not in page


# --- render_vocab_memory: the one review mode, a face-down matching grid ---


def render_memory(monkeypatch, db, student, *, state=None, button_pressed=None):
    written: list[str] = []
    state = {} if state is None else state
    recorder = Recorder(written, state)
    if button_pressed is not None:
        recorder.button = button_stub(written, button_pressed)
    monkeypatch.setattr(ui, "st", recorder)
    ui.render_vocab_memory(db, student)
    return "\n".join(written), state


def vocab_by_id(db, student_id, vocab_id):
    return next(w for w in db.list_vocabulary(student_id) if w["id"] == vocab_id)


def test_memory_no_due_words_shows_success(monkeypatch, db, student):
    page, _ = render_memory(monkeypatch, db, student)
    assert "Nothing due for review today." in page


def test_cards_start_face_down(monkeypatch, db, student):
    """Neither the word nor its definition should be readable before he's
    flipped that specific card -- same redaction reasoning the old flashcard
    mode relied on, just applied to twice as many cards."""
    db.add_vocabulary(student["id"], "ephemeral", "lasting a very short time")
    db.conn.execute("UPDATE vocabulary SET next_review_on = date('now')")
    db.conn.commit()
    page, _ = render_memory(monkeypatch, db, student)
    assert "ephemeral" not in page
    assert "lasting a very short time" not in page
    assert ui.VOCAB_MEMORY_CARD_BACK in page


def test_a_fresh_call_initializes_a_round_from_due_words(monkeypatch, db, student):
    db.add_vocabulary(student["id"], "ephemeral", "lasting a very short time")
    db.add_vocabulary(student["id"], "ubiquitous", "present everywhere")
    db.conn.execute("UPDATE vocabulary SET next_review_on = date('now')")
    db.conn.commit()
    ids = {w["id"] for w in db.list_vocabulary(student["id"])}

    _, state = render_memory(monkeypatch, db, student)
    memory_state = state["vocab_memory"]
    assert set(memory_state["round_ids"]) == ids
    # Two cards per word -- one word-side, one definition-side.
    assert len(memory_state["card_order"]) == 2 * len(ids)
    assert set(memory_state["card_vocab"].values()) == ids
    assert "start_time" in memory_state  # the round timer's clock


def test_flipping_one_card_reveals_it_without_resolving(monkeypatch, db, student):
    db.add_vocabulary(student["id"], "ephemeral", "lasting a very short time")
    db.conn.execute("UPDATE vocabulary SET next_review_on = date('now')")
    db.conn.commit()
    vocab_id = db.list_vocabulary(student["id"])[0]["id"]

    _, state = render_memory(
        monkeypatch, db, student, button_pressed=f"vocab_card_{vocab_id}_word"
    )
    assert state["vocab_memory"]["flipped"] == [f"{vocab_id}_word"]
    assert vocab_id not in state["vocab_memory"]["resolved"]

    # The click itself renders the card's *pre-click* face (a real browser
    # button doesn't retroactively relabel itself mid-click either) -- the
    # flip becomes visible on the next repaint, same as everywhere else in
    # this app that mutates state then reruns.
    page, _ = render_memory(monkeypatch, db, student, state=state)
    assert "ephemeral" in page


def test_flipping_the_matching_definition_resolves_the_pair(monkeypatch, db, student):
    db.add_vocabulary(student["id"], "ephemeral", "lasting a very short time")
    db.conn.execute("UPDATE vocabulary SET next_review_on = date('now')")
    db.conn.commit()
    vocab_id = db.list_vocabulary(student["id"])[0]["id"]

    _, state = render_memory(
        monkeypatch, db, student, button_pressed=f"vocab_card_{vocab_id}_word"
    )
    page, state = render_memory(
        monkeypatch, db, student, state=state, button_pressed=f"vocab_card_{vocab_id}_def"
    )

    assert vocab_id in state["vocab_memory"]["resolved"]
    assert state["vocab_memory"]["flipped"] == []
    assert not state["vocab_memory"]["mismatch"]
    entry = vocab_by_id(db, student["id"], vocab_id)
    assert entry["box"] == 2
    assert entry["times_correct"] == 1


def test_a_resolved_pair_stays_visible_in_place(monkeypatch, db, student):
    """The whole point of the rebuild: a matched pair must not vanish -- it
    stays on the board, face-up, so there's still something to see it by.

    A second, still-due word is seeded alongside the one being resolved --
    with only one word due total, resolving it empties `due` outright and
    the board gives way to the "all caught up" screen on the very next
    repaint (true of Trading Cards before it too); that edge case says
    nothing about whether a resolved pair survives *within* an still-active
    round, which is what this test is actually pinning down.
    """
    db.add_vocabulary(student["id"], "ephemeral", "lasting a very short time")
    db.add_vocabulary(student["id"], "ubiquitous", "present everywhere")
    db.conn.execute("UPDATE vocabulary SET next_review_on = date('now')")
    db.conn.commit()
    vocab_id = next(
        w["id"] for w in db.list_vocabulary(student["id"]) if w["word"] == "ephemeral"
    )

    _, state = render_memory(
        monkeypatch, db, student, button_pressed=f"vocab_card_{vocab_id}_word"
    )
    _, state = render_memory(
        monkeypatch, db, student, state=state, button_pressed=f"vocab_card_{vocab_id}_def"
    )
    page, _ = render_memory(monkeypatch, db, student, state=state)
    assert "ephemeral" in page
    assert "lasting a very short time" in page


def test_flipping_a_non_matching_card_sets_mismatch_and_keeps_both_visible(
    monkeypatch, db, student
):
    db.add_vocabulary(student["id"], "ephemeral", "lasting a very short time")
    db.add_vocabulary(student["id"], "ubiquitous", "present everywhere")
    db.conn.execute("UPDATE vocabulary SET next_review_on = date('now')")
    db.conn.commit()
    words = {w["word"]: w["id"] for w in db.list_vocabulary(student["id"])}
    eph_id, ubi_id = words["ephemeral"], words["ubiquitous"]

    _, state = render_memory(
        monkeypatch, db, student, button_pressed=f"vocab_card_{eph_id}_word"
    )
    _, state = render_memory(
        monkeypatch, db, student, state=state, button_pressed=f"vocab_card_{ubi_id}_def"
    )

    assert state["vocab_memory"]["mismatch"] is True
    assert eph_id in state["vocab_memory"]["missed"]
    assert ubi_id in state["vocab_memory"]["missed"]
    assert eph_id not in state["vocab_memory"]["resolved"]

    # Both stay revealed until he taps flip-back, not hidden immediately --
    # on the next repaint (not the click's own render, same pre-click-label
    # timing as everywhere else here), not just in session state.
    page, _ = render_memory(monkeypatch, db, student, state=state)
    assert "ephemeral" in page
    assert "present everywhere" in page
    assert "flip back" in page.lower()


def test_flip_back_clears_the_mismatch(monkeypatch, db, student):
    db.add_vocabulary(student["id"], "ephemeral", "lasting a very short time")
    db.add_vocabulary(student["id"], "ubiquitous", "present everywhere")
    db.conn.execute("UPDATE vocabulary SET next_review_on = date('now')")
    db.conn.commit()
    words = {w["word"]: w["id"] for w in db.list_vocabulary(student["id"])}
    eph_id, ubi_id = words["ephemeral"], words["ubiquitous"]

    _, state = render_memory(
        monkeypatch, db, student, button_pressed=f"vocab_card_{eph_id}_word"
    )
    _, state = render_memory(
        monkeypatch, db, student, state=state, button_pressed=f"vocab_card_{ubi_id}_def"
    )
    _, state = render_memory(
        monkeypatch, db, student, state=state, button_pressed="vocab_flip_back"
    )
    assert state["vocab_memory"]["mismatch"] is False
    assert state["vocab_memory"]["flipped"] == []

    page, _ = render_memory(monkeypatch, db, student, state=state)
    assert "ephemeral" not in page
    assert "present everywhere" not in page


def test_a_pair_that_mismatched_first_still_counts_as_missed_once_matched(
    monkeypatch, db, student
):
    """The scoring rule, carried over from Trading Cards: only a first-try
    match counts as "knew it." A pair that needed a mismatch first still
    records a miss once it's eventually matched."""
    db.add_vocabulary(student["id"], "ephemeral", "lasting a very short time")
    db.add_vocabulary(student["id"], "ubiquitous", "present everywhere")
    db.conn.execute("UPDATE vocabulary SET next_review_on = date('now')")
    db.conn.commit()
    words = {w["word"]: w["id"] for w in db.list_vocabulary(student["id"])}
    eph_id, ubi_id = words["ephemeral"], words["ubiquitous"]

    _, state = render_memory(
        monkeypatch, db, student, button_pressed=f"vocab_card_{eph_id}_word"
    )
    _, state = render_memory(
        monkeypatch, db, student, state=state, button_pressed=f"vocab_card_{ubi_id}_def"
    )
    _, state = render_memory(
        monkeypatch, db, student, state=state, button_pressed="vocab_flip_back"
    )
    _, state = render_memory(
        monkeypatch, db, student, state=state, button_pressed=f"vocab_card_{eph_id}_word"
    )
    _, state = render_memory(
        monkeypatch, db, student, state=state, button_pressed=f"vocab_card_{eph_id}_def"
    )

    entry = vocab_by_id(db, student["id"], eph_id)
    assert entry["box"] == 1
    assert entry["times_missed"] == 1
    assert entry["times_correct"] == 0


def test_a_mismatch_resets_the_streak_immediately(monkeypatch, db, student):
    """The streak breaks the moment the mismatch happens, not once the pair
    eventually resolves -- the number on screen shouldn't lag."""
    db.add_vocabulary(student["id"], "ephemeral", "lasting a very short time")
    db.add_vocabulary(student["id"], "ubiquitous", "present everywhere")
    db.conn.execute("UPDATE vocabulary SET next_review_on = date('now')")
    db.conn.commit()
    words = {w["word"]: w["id"] for w in db.list_vocabulary(student["id"])}
    eph_id, ubi_id = words["ephemeral"], words["ubiquitous"]

    _, state = render_memory(
        monkeypatch, db, student,
        state={"vocab_streak": 4, "vocab_best_streak": 4},
        button_pressed=f"vocab_card_{eph_id}_word",
    )
    _, state = render_memory(
        monkeypatch, db, student, state=state, button_pressed=f"vocab_card_{ubi_id}_def"
    )
    assert state["vocab_streak"] == 0
    assert state["vocab_best_streak"] == 4  # not erased by the mismatch


def test_a_clean_match_builds_the_streak(monkeypatch, db, student):
    db.add_vocabulary(student["id"], "ephemeral", "lasting a very short time")
    db.conn.execute("UPDATE vocabulary SET next_review_on = date('now')")
    db.conn.commit()
    vocab_id = db.list_vocabulary(student["id"])[0]["id"]

    _, state = render_memory(
        monkeypatch, db, student,
        state={"vocab_streak": 2, "vocab_best_streak": 2},
        button_pressed=f"vocab_card_{vocab_id}_word",
    )
    _, state = render_memory(
        monkeypatch, db, student, state=state, button_pressed=f"vocab_card_{vocab_id}_def"
    )

    assert state["vocab_streak"] == 3
    assert state["vocab_best_streak"] == 3
    assert state["vocab_reviewed_count"] == 1


def test_no_due_words_but_a_session_already_happened_celebrates(monkeypatch, db, student):
    page, _ = render_memory(
        monkeypatch, db, student,
        state={"vocab_reviewed_count": 3, "vocab_best_streak": 2},
    )
    assert "All caught up" in page
    assert "Nothing due for review today." not in page


def test_finishing_a_round_shows_its_own_celebration_toast(monkeypatch, db, student):
    db.add_vocabulary(student["id"], "ephemeral", "lasting a very short time")
    db.conn.execute("UPDATE vocabulary SET next_review_on = date('now')")
    db.conn.commit()
    vocab_id = db.list_vocabulary(student["id"])[0]["id"]

    _, state = render_memory(
        monkeypatch, db, student, button_pressed=f"vocab_card_{vocab_id}_word"
    )
    page, _ = render_memory(
        monkeypatch, db, student, state=state, button_pressed=f"vocab_card_{vocab_id}_def"
    )
    assert "Round complete" in page


def test_finishing_a_round_persists_a_best_time(monkeypatch, db, student):
    db.add_vocabulary(student["id"], "ephemeral", "lasting a very short time")
    db.conn.execute("UPDATE vocabulary SET next_review_on = date('now')")
    db.conn.commit()
    vocab_id = db.list_vocabulary(student["id"])[0]["id"]
    assert db.get_setting("vocab_best_round_seconds") is None

    _, state = render_memory(
        monkeypatch, db, student, button_pressed=f"vocab_card_{vocab_id}_word"
    )
    render_memory(
        monkeypatch, db, student, state=state, button_pressed=f"vocab_card_{vocab_id}_def"
    )

    assert db.get_setting("vocab_best_round_seconds") is not None


def test_the_hud_shows_streak_reviewed_left_and_a_timer(monkeypatch, db, student):
    """`st.progress`'s round-progress text is a keyword arg (`text=`), which
    the Recorder stub doesn't capture, only positional string args; the four
    metrics are the part of the HUD worth pinning here."""
    db.add_vocabulary(student["id"], "ephemeral", "lasting a very short time")
    db.conn.execute("UPDATE vocabulary SET next_review_on = date('now')")
    db.conn.commit()
    page, _ = render_memory(monkeypatch, db, student)
    assert "Streak" in page
    assert "Reviewed" in page
    assert "Left today" in page
    assert "This round" in page


def test_matching_one_pair_does_not_reset_the_rest_of_the_round(monkeypatch, db, student):
    """Regression: a matched pair drops out of `due` immediately (its
    next_review_on moves into the future), which used to be indistinguishable
    from "reviewed elsewhere" staleness and silently restarted the whole
    round on the very next render -- the progress bar and pairs-found count
    could never accumulate past one."""
    db.add_vocabulary(student["id"], "ephemeral", "lasting a very short time")
    db.add_vocabulary(student["id"], "ubiquitous", "present everywhere")
    db.add_vocabulary(student["id"], "meticulous", "very careful and precise")
    db.conn.execute("UPDATE vocabulary SET next_review_on = date('now')")
    db.conn.commit()
    words = {w["word"]: w["id"] for w in db.list_vocabulary(student["id"])}
    met_id = words["meticulous"]

    _, state = render_memory(
        monkeypatch, db, student, button_pressed=f"vocab_card_{met_id}_word"
    )
    original_round_ids = set(state["vocab_memory"]["round_ids"])
    _, state = render_memory(
        monkeypatch, db, student, state=state, button_pressed=f"vocab_card_{met_id}_def"
    )

    assert set(state["vocab_memory"]["round_ids"]) == original_round_ids
    assert state["vocab_memory"]["resolved"] == {met_id}

    # A follow-up render with no click -- the resulting repaint -- must still
    # show the accumulated round, not a freshly reinitialized one.
    _, state = render_memory(monkeypatch, db, student, state=state)
    assert set(state["vocab_memory"]["round_ids"]) == original_round_ids


# --- render_life_skill_cards: always-visible cards, a checkbox is the only action ---


def checkbox_stub(written: list[str], key_pressed: str):
    """A `st.checkbox` override that flips just the targeted checkbox and
    otherwise echoes back whatever `value` it was given -- mirrors
    `button_stub`'s reasoning, but for a value-carrying widget rather than
    a fire-once one."""

    def stub(*args, value=False, key=None, **kwargs):
        for arg in args:
            if isinstance(arg, str):
                written.append(arg)
        return (not value) if key == key_pressed else value

    return stub


def render_cards(monkeypatch, db, skills, *, can_edit=True, button_pressed=None, checkbox_pressed=None):
    written: list[str] = []
    recorder = Recorder(written, {})
    if button_pressed is not None:
        recorder.button = button_stub(written, button_pressed)
    # Always stubbed, even with nothing pressed: the Recorder's own generic
    # fallback returns itself (falsy, but not a real bool) rather than
    # echoing back `value`, which made every unstubbed checkbox compare
    # unequal to an already-True `earned` and silently fire
    # `set_life_skill_done(id, <Recorder object>)` on every render.
    recorder.checkbox = checkbox_stub(written, checkbox_pressed)
    monkeypatch.setattr(ui, "st", recorder)
    ui.render_life_skill_cards(db, skills, can_edit)
    return "\n".join(written)


def test_no_skills_renders_nothing(monkeypatch, db):
    assert render_cards(monkeypatch, db, []) == ""


def test_inactive_skills_are_hidden_but_earned_ones_stay_even_if_relocked(monkeypatch, db, student):
    db.seed_life_skills(student["id"])
    skills = db.list_life_skills(student["id"])
    locked = next(s for s in skills if s["title"] == "Lock down your privacy settings")
    assert locked["active"] == 0

    page = render_cards(monkeypatch, db, db.list_life_skills(student["id"]))
    assert "Lock down your privacy" not in page

    db.set_life_skill_done(locked["id"], True)
    db.set_life_skill_active(locked["id"], False)  # earned, then re-locked
    page = render_cards(monkeypatch, db, db.list_life_skills(student["id"]))
    assert "Lock down your privacy" in page


def test_cards_show_the_tally_and_every_category(monkeypatch, db, student):
    db.seed_life_skills(student["id"])
    skills = db.list_life_skills(student["id"])
    earned = next(s for s in skills if s["title"] == "Do laundry start to finish")
    db.set_life_skill_done(earned["id"], True)

    page = render_cards(monkeypatch, db, db.list_life_skills(student["id"]))
    assert "1 / 15 earned" in page  # only the 15 active-by-default catalog entries are visible
    assert "Money" in page
    assert "Cooking" in page
    assert "Vehicle" in page
    assert "Communication" in page
    assert "Home" in page
    # All three items per category render, not just the first two -- pins the
    # switch from `zip(columns, items)` (silently drops past 2 under the test
    # harness's fixed-length column iterator) to index-based access.
    assert "Basic first aid and when to call for help" in page


def test_the_story_and_materials_show_without_any_click(monkeypatch, db, student):
    """The whole point of the rebuild: nothing is click-to-reveal anymore."""
    db.seed_life_skills(student["id"])
    skills = db.list_life_skills(student["id"])
    page = render_cards(monkeypatch, db, skills)
    assert "Figure out what money" in page  # apostrophe HTML-escapes past this point
    assert "pencil and paper" in page


def test_checking_the_box_marks_the_skill_done(monkeypatch, db, student):
    db.seed_life_skills(student["id"])
    skills = db.list_life_skills(student["id"])
    budget = next(s for s in skills if s["title"] == "Build and follow a monthly budget")

    render_cards(monkeypatch, db, skills, checkbox_pressed=f"ls_done_{budget['id']}")
    updated = next(s for s in db.list_life_skills(student["id"]) if s["id"] == budget["id"])
    assert updated["completed_on"] is not None


def test_unchecking_an_earned_skill_marks_it_not_done(monkeypatch, db, student):
    db.seed_life_skills(student["id"])
    skills = db.list_life_skills(student["id"])
    budget = next(s for s in skills if s["title"] == "Build and follow a monthly budget")
    db.set_life_skill_done(budget["id"], True)

    render_cards(
        monkeypatch, db, db.list_life_skills(student["id"]),
        checkbox_pressed=f"ls_done_{budget['id']}",
    )
    updated = next(s for s in db.list_life_skills(student["id"]) if s["id"] == budget["id"])
    assert updated["completed_on"] is None


def test_materials_only_show_when_present(monkeypatch, db, student):
    skill_id = db.add_life_skill(student["id"], "Sew a button", "Sewing", "Thread it and knot it.")
    page = render_cards(monkeypatch, db, db.list_life_skills(student["id"]))
    assert "You'll need" not in page

    db.delete_life_skill(skill_id)
    db.add_life_skill(
        student["id"], "Sew a button", "Sewing", "Thread it and knot it.",
        materials="needle, thread, a button",
    )
    page = render_cards(monkeypatch, db, db.list_life_skills(student["id"]))
    assert "You'll need" in page
    assert "needle, thread, a button" in page


def test_a_custom_category_falls_back_to_the_default_icon(monkeypatch, db, student):
    db.add_life_skill(student["id"], "Learn to sew a button", "Sewing")
    page = render_cards(monkeypatch, db, db.list_life_skills(student["id"]))
    assert "Sewing" in page
    assert ui.LIFE_SKILL_DEFAULT_ICON in page


def test_a_skill_title_and_description_are_escaped(monkeypatch, db, student):
    """The card renders via `unsafe_allow_html=True`, so a title or
    description containing markup must come out escaped -- unlike the
    checkbox's own label, which is inherently plain text regardless of
    escaping (Streamlit widget labels don't execute HTML)."""
    db.add_life_skill(student["id"], "<script>alert(1)</script>", "General", "<b>bold</b> mission")
    page = render_cards(monkeypatch, db, db.list_life_skills(student["id"]))
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert "&lt;b&gt;bold&lt;/b&gt; mission" in page


def test_students_do_not_see_the_remove_control(monkeypatch, db, student):
    db.seed_life_skills(student["id"])
    page = render_cards(monkeypatch, db, db.list_life_skills(student["id"]), can_edit=False)
    assert "🗑️ Remove" not in page


def test_parents_see_the_remove_control(monkeypatch, db, student):
    db.seed_life_skills(student["id"])
    page = render_cards(monkeypatch, db, db.list_life_skills(student["id"]), can_edit=True)
    assert "🗑️ Remove" in page


def test_removing_a_skill_deletes_it(monkeypatch, db, student):
    db.seed_life_skills(student["id"])
    skills = db.list_life_skills(student["id"])
    budget = next(s for s in skills if s["title"] == "Build and follow a monthly budget")

    render_cards(monkeypatch, db, skills, can_edit=True, button_pressed=f"ls_remove_{budget['id']}")
    remaining_titles = {s["title"] for s in db.list_life_skills(student["id"])}
    assert "Build and follow a monthly budget" not in remaining_titles


def test_a_student_cannot_remove_a_skill_even_if_the_button_key_matched(monkeypatch, db, student):
    """`can_edit=False` must mean the remove button is never even called, not
    just hidden -- this pins that the button call itself is skipped."""
    db.seed_life_skills(student["id"])
    skills = db.list_life_skills(student["id"])
    budget = next(s for s in skills if s["title"] == "Build and follow a monthly budget")

    render_cards(monkeypatch, db, skills, can_edit=False, button_pressed=f"ls_remove_{budget['id']}")
    remaining_titles = {s["title"] for s in db.list_life_skills(student["id"])}
    assert "Build and follow a monthly budget" in remaining_titles


# --- render_life_skill_catalog_manager: the pace control, parent-only ---


def render_catalog_manager(monkeypatch, db, skills, *, checkbox_pressed=None):
    written: list[str] = []
    recorder = Recorder(written, {})
    recorder.checkbox = checkbox_stub(written, checkbox_pressed)  # see render_cards for why always
    monkeypatch.setattr(ui, "st", recorder)
    ui.render_life_skill_catalog_manager(db, skills)
    return "\n".join(written)


def test_catalog_manager_shows_the_unlock_tally_and_locked_entries(monkeypatch, db, student):
    db.seed_life_skills(student["id"])
    skills = db.list_life_skills(student["id"])
    page = render_catalog_manager(monkeypatch, db, skills)
    assert f"15 / {len(skills)} unlocked" in page
    assert "Digital Life" in page
    assert "Health & Safety" in page
    assert "Work & Career" in page
    assert "Lock down your privacy settings" in page


def test_catalog_manager_rows_show_the_full_mission_materials_and_subject(monkeypatch, db, student):
    """Deeper than a bare title + checkbox -- a parent should be able to
    decide whether to unlock something without leaving this page."""
    db.seed_life_skills(student["id"])
    page = render_catalog_manager(monkeypatch, db, db.list_life_skills(student["id"]))
    assert "Figure out what money's coming in" in page
    assert "pencil and paper" in page
    assert "Credits toward Occupational Education" in page


def test_unlocking_a_skill_flips_it_active(monkeypatch, db, student):
    db.seed_life_skills(student["id"])
    skills = db.list_life_skills(student["id"])
    locked = next(s for s in skills if s["title"] == "Lock down your privacy settings")
    assert locked["active"] == 0

    render_catalog_manager(monkeypatch, db, skills, checkbox_pressed=f"ls_active_{locked['id']}")
    updated = next(s for s in db.list_life_skills(student["id"]) if s["id"] == locked["id"])
    assert updated["active"] == 1


def test_relocking_an_active_skill_flips_it_back(monkeypatch, db, student):
    db.seed_life_skills(student["id"])
    skills = db.list_life_skills(student["id"])
    budget = next(s for s in skills if s["title"] == "Build and follow a monthly budget")
    assert budget["active"] == 1

    render_catalog_manager(monkeypatch, db, skills, checkbox_pressed=f"ls_active_{budget['id']}")
    updated = next(s for s in db.list_life_skills(student["id"]) if s["id"] == budget["id"])
    assert updated["active"] == 0


# --- render_morning_routine: start-of-day stretch/breathing/mindfulness pick ---


def radio_stub(*args, index=0, **kwargs):
    """Mirrors a real `st.radio`'s default behaviour: whatever `index` picks
    out of the options list, unless a test overrides the whole widget."""
    options = args[1] if len(args) > 1 else kwargs.get("options")
    return options[index]


def render_morning(monkeypatch, db, student, *, button_pressed=None, radio_pick=None):
    written: list[str] = []
    recorder = Recorder(written, {})
    recorder.radio = (lambda *a, **kw: radio_pick) if radio_pick is not None else radio_stub
    if button_pressed is not None:
        recorder.button = button_stub(written, button_pressed)
    monkeypatch.setattr(ui, "st", recorder)
    shown = ui.render_morning_routine(db, student)
    return "\n".join(written), shown


def test_not_done_yet_shows_todays_routine_and_returns_false(monkeypatch, db, student):
    page, shown = render_morning(monkeypatch, db, student)
    assert shown is False
    assert "Morning Routine" in page
    assert "feeling good" in page


def test_marking_done_logs_health_credit_and_records_the_pick(monkeypatch, db, student):
    page, shown = render_morning(monkeypatch, db, student, button_pressed="morning_routine_done")
    assert "Mark this morning done" in page

    today = date.today().isoformat()
    logged = db.morning_routine_for_date(student["id"], today)
    assert logged is not None

    activities = db.list_activities(student["id"])
    assert len(activities) == 1
    assert activities[0]["primary_subject"] == "health"
    assert activities[0]["tier"] == "wellness"
    assert activities[0]["credits"] == {"health": activities[0]["minutes"]}


def test_already_done_today_shows_success_and_offers_a_switch(monkeypatch, db, student):
    today = date.today().isoformat()
    db.log_morning_routine(student["id"], today, "box_breathing")
    page, shown = render_morning(monkeypatch, db, student)
    assert shown is True
    assert "Done for today" in page
    assert "Box Breathing" in page
    assert "Switch to this one" in page


def test_switching_routines_the_same_day_does_not_double_credit(monkeypatch, db, student):
    """The first completion earns the Health minutes; picking a different
    routine later the same day updates the record but must not log a
    second, redundant chunk of credited time."""
    today = date.today().isoformat()
    db.log_morning_routine(student["id"], today, "box_breathing")
    db.log_activity(
        student_id=student["id"],
        title="Morning routine — Box Breathing",
        tier="wellness",
        primary_subject="health",
        minutes=3,
        subject_credits={"health": 3},
        occurred_on=today,
    )

    render_morning(
        monkeypatch, db, student, button_pressed="morning_routine_done", radio_pick="sun_salutation"
    )

    logged = db.morning_routine_for_date(student["id"], today)
    assert logged["routine_key"] == "sun_salutation"
    assert len(db.list_activities(student["id"])) == 1


def test_big_project_status_text_nudges_when_none_is_active(db, student):
    assert "pick one" in ui.big_project_status_text(db, student["id"]).lower()


def test_big_project_status_text_shows_the_next_step(db, student):
    project_id = db.add_big_project(student["id"], "Stop-motion film")
    db.add_project_step(project_id, "Write the script")
    db.set_active_big_project(project_id)
    text = ui.big_project_status_text(db, student["id"])
    assert "Stop-motion film" in text
    assert "Write the script" in text


def test_big_project_status_text_celebrates_when_all_steps_are_done(db, student):
    project_id = db.add_big_project(student["id"], "Stop-motion film")
    step_id = db.add_project_step(project_id, "Write the script")
    db.set_active_big_project(project_id)
    db.set_project_step_done(step_id, True)
    assert "all done" in ui.big_project_status_text(db, student["id"]).lower()


def test_render_friday_plan_falls_back_to_the_fixed_pairing_when_nothing_is_set(
    monkeypatch, db, student
):
    written: list[str] = []
    monkeypatch.setattr(ui, "st", Recorder(written, {}))
    ui.render_friday_plan(db, student, "2026-08-28")
    page = "\n".join(written)
    assert "pick one to work on this year" in page
    assert "Travel Journal" in page


def test_render_friday_plan_shows_whatever_the_parent_set_instead(monkeypatch, db, student):
    db.add_friday_plan_item(
        student["id"], "2026-08-28", "travel_catchup", "Catch up on 5 older trips"
    )
    db.add_friday_plan_item(
        student["id"], "2026-08-28", "custom", "Practice guitar for 30 minutes"
    )

    written: list[str] = []
    monkeypatch.setattr(ui, "st", Recorder(written, {}))
    ui.render_friday_plan(db, student, "2026-08-28")
    page = "\n".join(written)
    assert "Catch up on 5 older trips" in page
    assert "Practice guitar for 30 minutes" in page
    assert "pick one to work on this year" not in page  # fallback must not also show


def test_render_friday_plan_only_shows_items_for_that_exact_date(monkeypatch, db, student):
    db.add_friday_plan_item(student["id"], "2026-08-28", "custom", "This Friday's thing")
    db.add_friday_plan_item(student["id"], "2026-09-04", "custom", "Next Friday's thing")

    written: list[str] = []
    monkeypatch.setattr(ui, "st", Recorder(written, {}))
    ui.render_friday_plan(db, student, "2026-08-28")
    page = "\n".join(written)
    assert "This Friday's thing" in page
    assert "Next Friday's thing" not in page


# --- render_first_day_celebration: one-time "Issue #1" cover on the first day ---


def _fix_today(monkeypatch, fixed):
    """Pins both ui.date and db.date, since the guard reads date.today() in
    ui.py and school_year_bounds() reads its own date.today() in db.py --
    patching only one leaves the other on the real clock."""
    from datetime import date as real_date

    import compass.storage.db as db_module

    class _FixedToday(real_date):
        @classmethod
        def today(cls):
            return fixed

    monkeypatch.setattr(ui, "date", _FixedToday)
    monkeypatch.setattr(db_module, "date", _FixedToday)


def render_first_day(monkeypatch, db, student, *, button_pressed=None, state=None):
    written: list[str] = []
    state = {} if state is None else state
    recorder = Recorder(written, state)
    if button_pressed is not None:
        recorder.button = button_stub(written, button_pressed)
    monkeypatch.setattr(ui, "st", recorder)
    shown = ui.render_first_day_celebration(db, student)
    return "\n".join(written), shown, state


def test_hidden_before_the_school_year_actually_starts(monkeypatch, db, student):
    db.set_setting("school_year_start", "09-01")
    _fix_today(monkeypatch, date(2026, 8, 20))
    _, shown, _ = render_first_day(monkeypatch, db, student)
    assert shown is False


def test_shown_on_the_literal_first_day(monkeypatch, db, student):
    db.set_setting("school_year_start", "09-01")
    _fix_today(monkeypatch, date(2026, 9, 1))
    page, shown, _ = render_first_day(monkeypatch, db, student)
    assert shown is True
    assert "THE FIRST DAY!" in page


def test_still_shown_a_few_days_late(monkeypatch, db, student):
    db.set_setting("school_year_start", "09-01")
    _fix_today(monkeypatch, date(2026, 9, 8))
    _, shown, _ = render_first_day(monkeypatch, db, student)
    assert shown is True


def test_no_longer_shown_once_the_window_has_passed(monkeypatch, db, student):
    """The bug this guards against: school_year_bounds() always returns a
    start <= today, so without a window check this would show up any time
    at all during the year, not just near the actual first day."""
    db.set_setting("school_year_start", "09-01")
    _fix_today(monkeypatch, date(2026, 12, 1))
    _, shown, _ = render_first_day(monkeypatch, db, student)
    assert shown is False


def test_not_shown_again_once_already_celebrated_for_this_years_start(monkeypatch, db, student):
    db.set_setting("school_year_start", "09-01")
    _fix_today(monkeypatch, date(2026, 9, 2))
    db.set_setting("first_day_celebrated_start", "2026-09-01")
    _, shown, _ = render_first_day(monkeypatch, db, student)
    assert shown is False


def test_blurbs_mention_the_current_and_upcoming_book(monkeypatch, db, student):
    db.set_setting("school_year_start", "09-01")
    _fix_today(monkeypatch, date(2026, 9, 1))
    db.add_book(student["id"], "Holes", status="reading")
    db.add_book(student["id"], "Ready Player One", status="upcoming")
    page, shown, _ = render_first_day(monkeypatch, db, student)
    assert shown is True
    assert "Holes" in page
    assert "Ready Player One" in page


def test_blurbs_mention_the_active_big_project_next_step(monkeypatch, db, student):
    db.set_setting("school_year_start", "09-01")
    _fix_today(monkeypatch, date(2026, 9, 1))
    project_id = db.add_big_project(student["id"], "Stop-motion film")
    db.add_project_step(project_id, "Write the script")
    db.set_active_big_project(project_id)
    page, shown, _ = render_first_day(monkeypatch, db, student)
    assert shown is True
    assert "Stop-motion film" in page
    assert "Write the script" in page


def test_still_shows_travel_log_and_next_issue_with_no_book_or_project(monkeypatch, db, student):
    db.set_setting("school_year_start", "09-01")
    _fix_today(monkeypatch, date(2026, 9, 1))
    page, shown, _ = render_first_day(monkeypatch, db, student)
    assert shown is True
    assert "Travel" in page


def test_clicking_lets_go_marks_this_years_start_celebrated(monkeypatch, db, student):
    db.set_setting("school_year_start", "09-01")
    _fix_today(monkeypatch, date(2026, 9, 1))
    render_first_day(monkeypatch, db, student, button_pressed="first_day_go")
    assert db.get_setting("first_day_celebrated_start", "") == "2026-09-01"


def test_see_whats_inside_flips_to_a_table_of_contents(monkeypatch, db, student):
    db.set_setting("school_year_start", "09-01")
    _fix_today(monkeypatch, date(2026, 9, 1))
    db.add_book(student["id"], "Holes", status="reading")
    project_id = db.add_big_project(student["id"], "Stop-Motion Film", vision="A short stop-motion film he writes, builds, and shoots himself.")
    db.add_project_step(project_id, "Write the script")
    db.set_active_big_project(project_id)
    db.add_choice_topic(student["id"], "Learn guitar chords", description="Enough chords to play a few songs.")
    db.add_life_skill(student["id"], "Change a tire", description="How to safely swap a flat for the spare.")
    db.add_travel_entry(student["id"], "WA", "2026-07-01", title="Olympic NP", story="Hiked to Hurricane Ridge.")

    _, _, state = render_first_day(monkeypatch, db, student, button_pressed="first_day_peek")
    assert state["first_day_view"] == "contents"

    page, shown, _ = render_first_day(monkeypatch, db, student, state=state)
    assert shown is True
    assert "Inside This Issue" in page
    assert "Holes" in page
    assert "Stop-Motion Film" in page
    assert "A short stop-motion film he writes, builds, and shoots himself." in page
    assert "Next up: Write the script" in page
    assert "Learn guitar chords" in page
    assert "Enough chords to play a few songs." in page
    assert "Change a tire" in page
    assert "How to safely swap a flat for the spare." in page
    assert "Olympic NP" in page
    assert "Hiked to Hurricane Ridge." in page


def test_table_of_contents_shows_every_big_project_not_just_the_active_one(monkeypatch, db, student):
    db.set_setting("school_year_start", "09-01")
    _fix_today(monkeypatch, date(2026, 9, 1))
    active_id = db.add_big_project(student["id"], "Stop-Motion Film")
    db.set_active_big_project(active_id)
    db.add_big_project(student["id"], "Birdhouse Build")

    state = {"first_day_view": "contents"}
    page, shown, _ = render_first_day(monkeypatch, db, student, state=state)
    assert shown is True
    assert "Stop-Motion Film" in page
    assert "Birdhouse Build" in page


def test_table_of_contents_hides_shelved_big_projects(monkeypatch, db, student):
    """Shelved means "not an interest" -- showing it in a celebratory
    preview of the year would contradict that."""
    db.set_setting("school_year_start", "09-01")
    _fix_today(monkeypatch, date(2026, 9, 1))
    db.add_big_project(student["id"], "Wanted Project")
    shelved_id = db.add_big_project(student["id"], "Shelved Project")
    db.set_big_project_shelved(shelved_id, True)

    state = {"first_day_view": "contents"}
    page, shown, _ = render_first_day(monkeypatch, db, student, state=state)
    assert shown is True
    assert "Wanted Project" in page
    assert "Shelved Project" not in page


def test_table_of_contents_shows_every_book_not_just_the_one_marked_reading(monkeypatch, db, student):
    """Regression: whether a book is marked 'reading' vs 'upcoming' is the
    parent's own bookkeeping (when to switch), and shouldn't gate whether he
    can see what's on his list at all -- both should show."""
    db.set_setting("school_year_start", "09-01")
    _fix_today(monkeypatch, date(2026, 9, 1))
    db.add_book(student["id"], "Holes", status="reading")
    upcoming_id = db.add_book(student["id"], "Ready Player One", status="upcoming")
    db.update_book(upcoming_id, ai_summary="A teenager races through a virtual utopia for a hidden prize.")

    state = {"first_day_view": "contents"}
    page, shown, _ = render_first_day(monkeypatch, db, student, state=state)
    assert shown is True
    assert "Holes" in page
    assert "Ready Player One" in page
    assert "A teenager races through a virtual utopia for a hidden prize." in page


def test_table_of_contents_shows_every_book_regardless_of_status(monkeypatch, db, student):
    """No status filter at all -- 'in progress or not' doesn't gate this
    list. current_book()/upcoming_book() answer a different question (which
    one the English agent reads from right now); this is "what's on his
    list for the year," full stop."""
    db.set_setting("school_year_start", "09-01")
    _fix_today(monkeypatch, date(2026, 9, 1))
    db.add_book(student["id"], "Holes", status="finished")
    db.add_book(student["id"], "Ready Player One", status="abandoned")
    db.add_book(student["id"], "Ender's Game", status="reading")

    state = {"first_day_view": "contents"}
    page, shown, _ = render_first_day(monkeypatch, db, student, state=state)
    assert shown is True
    assert "Holes" in page
    assert "Ready Player One" in page
    assert "Ender's Game" in page


def test_table_of_contents_opens_with_a_note_from_the_parents(monkeypatch, db, student):
    """Nothing about this section reads from the database -- it's a fixed
    message about the year itself (first year of homeschooling, what's
    expected), so it should show even with nothing else set up at all."""
    db.set_setting("school_year_start", "09-01")
    _fix_today(monkeypatch, date(2026, 9, 1))
    state = {"first_day_view": "contents"}
    page, shown, _ = render_first_day(monkeypatch, db, student, state=state)
    assert shown is True
    assert "FROM YOUR PARENTS" in page
    assert "first year of homeschooling" in page
    assert "we believe in you" in page
    assert "take your time" in page
    assert "read what's given to you" in page
    assert "give it your all" in page
    assert "explanations, examples, and videos" in page
    assert page.index("FROM YOUR PARENTS") < page.index("THIS YEAR'S BOOKS")


def test_table_of_contents_handles_nothing_set_up_yet(monkeypatch, db, student):
    db.set_setting("school_year_start", "09-01")
    _fix_today(monkeypatch, date(2026, 9, 1))
    state = {"first_day_view": "contents"}
    page, shown, _ = render_first_day(monkeypatch, db, student, state=state)
    assert shown is True
    assert "wide open" in page
    assert "No stamps yet" in page


def test_table_of_contents_explains_check_in_and_morning_routine(monkeypatch, db, student):
    """These two carry no per-student data -- they exist purely so he knows
    what those daily habits are and what's expected, since Home introduces
    them by name without ever spelling that out."""
    db.set_setting("school_year_start", "09-01")
    _fix_today(monkeypatch, date(2026, 9, 1))
    state = {"first_day_view": "contents"}
    page, shown, _ = render_first_day(monkeypatch, db, student, state=state)
    assert shown is True
    assert "CHECK-IN" in page
    assert "Your parents can read it" in page
    assert "MORNING ROUTINE" in page
    assert "start the day feeling good" in page


def test_table_of_contents_explains_the_app_itself(monkeypatch, db, student):
    """Every other feature in this preview got its own explainer -- the core
    daily subjects and the app's own shape hadn't, until these three."""
    db.set_setting("school_year_start", "09-01")
    _fix_today(monkeypatch, date(2026, 9, 1))
    state = {"first_day_view": "contents"}
    page, shown, _ = render_first_day(monkeypatch, db, student, state=state)
    assert shown is True
    assert "WHERE EVERYTHING LIVES" in page
    assert "Home** is where your day actually starts" in page
    assert "HOW YOUR LESSONS WORK" in page
    assert "built just for you" in page
    assert "HOW THE WEEK COMES TOGETHER" in page
    assert "show up on **Home**" in page


def test_choice_topics_life_skills_and_travel_are_labeled_as_examples(monkeypatch, db, student):
    """These sections show either a starter catalog or just whatever's been
    logged so far -- not a fixed or complete assignment list -- so the label
    is there to keep him from mistaking one for the other."""
    db.set_setting("school_year_start", "09-01")
    _fix_today(monkeypatch, date(2026, 9, 1))
    db.add_choice_topic(student["id"], "Learn guitar chords")
    db.add_life_skill(student["id"], "Change a tire")
    db.add_travel_entry(student["id"], "WA", "2026-07-01", title="Olympic NP")

    state = {"first_day_view": "contents"}
    page, shown, _ = render_first_day(monkeypatch, db, student, state=state)
    assert shown is True
    assert "THINGS HE WANTS TO LEARN (EXAMPLES)" in page
    assert "A few examples — see Choice Topics" in page
    assert "LIFE SKILLS UNLOCKED (EXAMPLES)" in page
    assert "A few examples from the catalog — see Life Skills" in page
    assert "LANDON'S TRAVELS SO FAR (EXAMPLES)" in page
    assert "A few examples so far — see Landon's Travels" in page


def test_books_show_their_half_of_the_year_instead_of_reading_progress_status(monkeypatch, db, student):
    """Both books are equally locked in for the year regardless of which one
    is actually marked 'reading' right now -- that's just the parent's own
    bookkeeping for the agent, not a statement about which book is real."""
    db.set_setting("school_year_start", "09-01")
    _fix_today(monkeypatch, date(2026, 9, 1))
    db.add_book(student["id"], "Holes", term="first_half", status="reading")
    db.add_book(student["id"], "Ready Player One", term="second_half", status="upcoming")

    state = {"first_day_view": "contents"}
    page, shown, _ = render_first_day(monkeypatch, db, student, state=state)
    assert shown is True
    assert "Holes" in page
    assert "first half of the year" in page
    assert "Ready Player One" in page
    assert "second half of the year" in page
    assert "currently reading" not in page
    assert "queued for later" not in page


def test_back_to_the_cover_returns_to_the_cover_view(monkeypatch, db, student):
    db.set_setting("school_year_start", "09-01")
    _fix_today(monkeypatch, date(2026, 9, 1))
    state = {"first_day_view": "contents"}
    render_first_day(monkeypatch, db, student, button_pressed="first_day_back", state=state)
    assert state["first_day_view"] == "cover"


def test_lets_go_from_the_contents_view_also_dismisses_it(monkeypatch, db, student):
    db.set_setting("school_year_start", "09-01")
    _fix_today(monkeypatch, date(2026, 9, 1))
    state = {"first_day_view": "contents"}
    render_first_day(monkeypatch, db, student, button_pressed="first_day_go_from_toc", state=state)
    assert db.get_setting("first_day_celebrated_start", "") == "2026-09-01"
