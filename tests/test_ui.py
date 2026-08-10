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
    db.record_quiz_result(lesson_id, correct=9, total=10, passed=True)
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


# --- render_vocab_review: his own flashcard review, word before definition ---


def render_vocab(monkeypatch, db, student, *, state=None, button_pressed=None):
    written: list[str] = []
    state = {} if state is None else state
    recorder = Recorder(written, state)
    if button_pressed is not None:
        recorder.button = button_stub(written, button_pressed)
    monkeypatch.setattr(ui, "st", recorder)
    ui.render_vocab_review(db, student)
    return "\n".join(written), state


def test_nothing_due_shows_a_clean_success_message(monkeypatch, db, student):
    page, _ = render_vocab(monkeypatch, db, student)
    assert "Nothing due for review today." in page


def test_a_due_word_shows_before_reveal_without_its_definition(monkeypatch, db, student):
    """The whole point: he must not be able to read the definition next to the
    word he's supposed to be recalling, before he's chosen to check himself."""
    db.add_vocabulary(student["id"], "ephemeral", "lasting a very short time")
    db.conn.execute("UPDATE vocabulary SET next_review_on = date('now')")
    db.conn.commit()
    page, _ = render_vocab(monkeypatch, db, student)
    assert "ephemeral" in page
    assert "lasting a very short time" not in page
    assert "Show definition" in page


def test_revealing_shows_the_definition_and_grading_buttons(monkeypatch, db, student):
    db.add_vocabulary(student["id"], "ephemeral", "lasting a very short time")
    db.conn.execute("UPDATE vocabulary SET next_review_on = date('now')")
    db.conn.commit()
    vocab_id = db.list_vocabulary(student["id"])[0]["id"]
    page, _ = render_vocab(monkeypatch, db, student, state={f"vocab_reveal_{vocab_id}": True})
    assert "lasting a very short time" in page
    assert "I knew it" in page
    assert "I missed it" in page


def test_marking_knew_it_records_correct_and_clears_the_reveal(monkeypatch, db, student):
    db.add_vocabulary(student["id"], "ephemeral", "lasting a very short time")
    db.conn.execute("UPDATE vocabulary SET next_review_on = date('now')")
    db.conn.commit()
    vocab_id = db.list_vocabulary(student["id"])[0]["id"]
    reveal_key = f"vocab_reveal_{vocab_id}"

    _, state = render_vocab(
        monkeypatch, db, student,
        state={reveal_key: True},
        button_pressed=f"vocab_ok_{vocab_id}",
    )

    entry = db.list_vocabulary(student["id"])[0]
    assert entry["box"] == 2  # advanced from box 1
    assert entry["times_correct"] == 1
    assert reveal_key not in state


def test_marking_missed_it_resets_the_box_and_clears_the_reveal(monkeypatch, db, student):
    db.add_vocabulary(student["id"], "ephemeral", "lasting a very short time")
    db.conn.execute("UPDATE vocabulary SET next_review_on = date('now'), box = 4")
    db.conn.commit()
    vocab_id = db.list_vocabulary(student["id"])[0]["id"]
    reveal_key = f"vocab_reveal_{vocab_id}"

    _, state = render_vocab(
        monkeypatch, db, student,
        state={reveal_key: True},
        button_pressed=f"vocab_miss_{vocab_id}",
    )

    entry = db.list_vocabulary(student["id"])[0]
    assert entry["box"] == 1  # dropped back down
    assert entry["times_missed"] == 1
    assert reveal_key not in state


def test_only_one_card_shows_even_with_several_words_due(monkeypatch, db, student):
    """A deck to work through one at a time, not a wall of identical boxes."""
    db.add_vocabulary(student["id"], "ephemeral", "lasting a very short time")
    db.add_vocabulary(student["id"], "ubiquitous", "present everywhere")
    db.conn.execute("UPDATE vocabulary SET next_review_on = date('now')")
    db.conn.commit()
    due = db.vocabulary_due(student["id"])
    first, second = due[0], due[1]

    page, _ = render_vocab(monkeypatch, db, student)
    assert first["word"] in page
    assert second["word"] not in page


def test_a_correct_answer_builds_the_streak(monkeypatch, db, student):
    db.add_vocabulary(student["id"], "ephemeral", "lasting a very short time")
    db.conn.execute("UPDATE vocabulary SET next_review_on = date('now')")
    db.conn.commit()
    vocab_id = db.list_vocabulary(student["id"])[0]["id"]
    reveal_key = f"vocab_reveal_{vocab_id}"

    _, state = render_vocab(
        monkeypatch, db, student,
        state={reveal_key: True, "vocab_streak": 2},
        button_pressed=f"vocab_ok_{vocab_id}",
    )
    assert state["vocab_streak"] == 3
    assert state["vocab_best_streak"] == 3
    assert state["vocab_reviewed_count"] == 1


def test_a_missed_answer_resets_the_streak_but_keeps_the_best(monkeypatch, db, student):
    db.add_vocabulary(student["id"], "ephemeral", "lasting a very short time")
    db.conn.execute("UPDATE vocabulary SET next_review_on = date('now')")
    db.conn.commit()
    vocab_id = db.list_vocabulary(student["id"])[0]["id"]
    reveal_key = f"vocab_reveal_{vocab_id}"

    _, state = render_vocab(
        monkeypatch, db, student,
        state={reveal_key: True, "vocab_streak": 4, "vocab_best_streak": 4},
        button_pressed=f"vocab_miss_{vocab_id}",
    )
    assert state["vocab_streak"] == 0
    assert state["vocab_best_streak"] == 4  # a miss doesn't erase what he'd already earned
    assert state["vocab_reviewed_count"] == 1


def test_finishing_the_due_list_celebrates_instead_of_the_plain_empty_state(
    monkeypatch, db, student
):
    page, _ = render_vocab(
        monkeypatch, db, student,
        state={"vocab_reviewed_count": 3, "vocab_best_streak": 2},
    )
    assert "All caught up" in page
    assert "Nothing due for review today." not in page


# --- render_vocab_match: Trading Cards, the game-style alternative --------


def render_match(monkeypatch, db, student, *, state=None, button_pressed=None):
    written: list[str] = []
    state = {} if state is None else state
    recorder = Recorder(written, state)
    if button_pressed is not None:
        recorder.button = button_stub(written, button_pressed)
    monkeypatch.setattr(ui, "st", recorder)
    ui.render_vocab_match(db, student)
    return "\n".join(written), state


def vocab_by_id(db, student_id, vocab_id):
    return next(w for w in db.list_vocabulary(student_id) if w["id"] == vocab_id)


def test_match_no_due_words_shows_success(monkeypatch, db, student):
    page, _ = render_match(monkeypatch, db, student)
    assert "Nothing due for review today." in page


def test_match_shows_words_and_definitions_upfront(monkeypatch, db, student):
    """Unlike flashcards, seeing every definition at once is the point -- and
    unlike Memory Match, nothing here ever has to vanish to make the game
    work, since there's no board position to remember."""
    db.add_vocabulary(student["id"], "ephemeral", "lasting a very short time")
    db.conn.execute("UPDATE vocabulary SET next_review_on = date('now')")
    db.conn.commit()
    page, _ = render_match(monkeypatch, db, student)
    assert "ephemeral" in page
    assert "lasting a very short time" in page


def test_a_fresh_call_initializes_a_round_from_due_words(monkeypatch, db, student):
    db.add_vocabulary(student["id"], "ephemeral", "lasting a very short time")
    db.add_vocabulary(student["id"], "ubiquitous", "present everywhere")
    db.conn.execute("UPDATE vocabulary SET next_review_on = date('now')")
    db.conn.commit()
    ids = {w["id"] for w in db.list_vocabulary(student["id"])}

    _, state = render_match(monkeypatch, db, student)
    match_state = state["vocab_match"]
    assert set(match_state["round_ids"]) == ids
    assert set(match_state["word_order"]) == ids
    assert set(match_state["def_order"]) == ids
    assert "start_time" in match_state  # the round timer's clock


def test_clicking_a_word_selects_it(monkeypatch, db, student):
    db.add_vocabulary(student["id"], "ephemeral", "lasting a very short time")
    db.conn.execute("UPDATE vocabulary SET next_review_on = date('now')")
    db.conn.commit()
    vocab_id = db.list_vocabulary(student["id"])[0]["id"]

    _, state = render_match(monkeypatch, db, student, button_pressed=f"match_word_{vocab_id}")
    assert state["vocab_match"]["selected"] == vocab_id


def test_matching_the_right_definition_on_the_first_try_records_correct(
    monkeypatch, db, student
):
    db.add_vocabulary(student["id"], "ephemeral", "lasting a very short time")
    db.add_vocabulary(student["id"], "ubiquitous", "present everywhere")
    db.conn.execute("UPDATE vocabulary SET next_review_on = date('now')")
    db.conn.commit()
    eph_id = next(
        w["id"] for w in db.list_vocabulary(student["id"]) if w["word"] == "ephemeral"
    )

    _, state = render_match(monkeypatch, db, student, button_pressed=f"match_word_{eph_id}")
    _, state = render_match(
        monkeypatch, db, student, state=state, button_pressed=f"match_def_{eph_id}"
    )

    assert eph_id in state["vocab_match"]["resolved"]
    assert state["vocab_match"]["selected"] is None
    entry = vocab_by_id(db, student["id"], eph_id)
    assert entry["box"] == 2
    assert entry["times_correct"] == 1


def test_a_wrong_guess_then_the_right_one_still_counts_as_missed(monkeypatch, db, student):
    """The scoring rule: only a first-try match counts as "knew it." A word
    that needed a wrong guess before landing right still records a miss --
    same as if he'd needed to see the flashcard's definition to get there."""
    db.add_vocabulary(student["id"], "ephemeral", "lasting a very short time")
    db.add_vocabulary(student["id"], "ubiquitous", "present everywhere")
    db.conn.execute("UPDATE vocabulary SET next_review_on = date('now')")
    db.conn.commit()
    words = {w["word"]: w["id"] for w in db.list_vocabulary(student["id"])}
    eph_id, ubi_id = words["ephemeral"], words["ubiquitous"]

    _, state = render_match(monkeypatch, db, student, button_pressed=f"match_word_{eph_id}")
    _, state = render_match(
        monkeypatch, db, student, state=state, button_pressed=f"match_def_{ubi_id}"
    )
    assert eph_id in state["vocab_match"]["missed"]
    assert eph_id not in state["vocab_match"]["resolved"]
    assert state["vocab_match"]["selected"] is None

    _, state = render_match(
        monkeypatch, db, student, state=state, button_pressed=f"match_word_{eph_id}"
    )
    _, state = render_match(
        monkeypatch, db, student, state=state, button_pressed=f"match_def_{eph_id}"
    )

    entry = vocab_by_id(db, student["id"], eph_id)
    assert entry["box"] == 1
    assert entry["times_missed"] == 1
    assert entry["times_correct"] == 0


def test_match_no_due_words_but_a_session_already_happened_celebrates(monkeypatch, db, student):
    """Same completion screen render_vocab_review uses -- the two modes share
    the session counters, so this fires regardless of which mode got him there."""
    page, _ = render_match(
        monkeypatch, db, student,
        state={"vocab_reviewed_count": 3, "vocab_best_streak": 2},
    )
    assert "All caught up" in page
    assert "Nothing due for review today." not in page


def test_a_clean_match_builds_the_shared_streak(monkeypatch, db, student):
    db.add_vocabulary(student["id"], "ephemeral", "lasting a very short time")
    db.conn.execute("UPDATE vocabulary SET next_review_on = date('now')")
    db.conn.commit()
    vocab_id = db.list_vocabulary(student["id"])[0]["id"]

    _, state = render_match(
        monkeypatch, db, student,
        state={"vocab_streak": 2, "vocab_best_streak": 2},
        button_pressed=f"match_word_{vocab_id}",
    )
    _, state = render_match(
        monkeypatch, db, student, state=state, button_pressed=f"match_def_{vocab_id}"
    )

    assert state["vocab_streak"] == 3
    assert state["vocab_best_streak"] == 3
    assert state["vocab_reviewed_count"] == 1


def test_a_wrong_guess_resets_the_shared_streak_immediately(monkeypatch, db, student):
    """The streak breaks the moment the wrong guess happens, not only once the
    word eventually gets matched -- the number on screen shouldn't lag."""
    db.add_vocabulary(student["id"], "ephemeral", "lasting a very short time")
    db.add_vocabulary(student["id"], "ubiquitous", "present everywhere")
    db.conn.execute("UPDATE vocabulary SET next_review_on = date('now')")
    db.conn.commit()
    words = {w["word"]: w["id"] for w in db.list_vocabulary(student["id"])}
    eph_id, ubi_id = words["ephemeral"], words["ubiquitous"]

    _, state = render_match(
        monkeypatch, db, student,
        state={"vocab_streak": 4, "vocab_best_streak": 4},
        button_pressed=f"match_word_{eph_id}",
    )
    _, state = render_match(
        monkeypatch, db, student, state=state, button_pressed=f"match_def_{ubi_id}"
    )
    assert state["vocab_streak"] == 0
    assert state["vocab_best_streak"] == 4  # not erased by the miss


def test_finishing_a_round_shows_its_own_celebration_toast(monkeypatch, db, student):
    db.add_vocabulary(student["id"], "ephemeral", "lasting a very short time")
    db.conn.execute("UPDATE vocabulary SET next_review_on = date('now')")
    db.conn.commit()
    vocab_id = db.list_vocabulary(student["id"])[0]["id"]

    _, state = render_match(monkeypatch, db, student, button_pressed=f"match_word_{vocab_id}")
    page, _ = render_match(
        monkeypatch, db, student, state=state, button_pressed=f"match_def_{vocab_id}"
    )
    assert "Round complete" in page


def test_finishing_a_round_persists_a_best_time(monkeypatch, db, student):
    db.add_vocabulary(student["id"], "ephemeral", "lasting a very short time")
    db.conn.execute("UPDATE vocabulary SET next_review_on = date('now')")
    db.conn.commit()
    vocab_id = db.list_vocabulary(student["id"])[0]["id"]
    assert db.get_setting("vocab_best_round_seconds") is None

    _, state = render_match(monkeypatch, db, student, button_pressed=f"match_word_{vocab_id}")
    render_match(monkeypatch, db, student, state=state, button_pressed=f"match_def_{vocab_id}")

    assert db.get_setting("vocab_best_round_seconds") is not None


def test_the_hud_shows_streak_reviewed_left_and_a_timer(monkeypatch, db, student):
    """`st.progress`'s round-progress text is a keyword arg (`text=`), which
    the Recorder stub -- like real st.progress calls elsewhere in this app --
    doesn't capture, only positional string args; the four metrics are the
    part of the HUD worth pinning here."""
    db.add_vocabulary(student["id"], "ephemeral", "lasting a very short time")
    db.conn.execute("UPDATE vocabulary SET next_review_on = date('now')")
    db.conn.commit()
    page, _ = render_match(monkeypatch, db, student)
    assert "Streak" in page
    assert "Reviewed" in page
    assert "Left today" in page
    assert "This round" in page


def test_matching_one_word_does_not_reset_the_rest_of_the_round(monkeypatch, db, student):
    """Regression: a matched word drops out of `due` immediately (its
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

    _, state = render_match(
        monkeypatch, db, student, button_pressed=f"match_word_{words['meticulous']}"
    )
    original_round_ids = set(state["vocab_match"]["round_ids"])
    _, state = render_match(
        monkeypatch, db, student, state=state, button_pressed=f"match_def_{words['meticulous']}"
    )

    assert set(state["vocab_match"]["round_ids"]) == original_round_ids
    assert state["vocab_match"]["resolved"] == {words["meticulous"]}

    # A follow-up render with no click -- the resulting repaint -- must still
    # show the accumulated round, not a freshly reinitialized one.
    _, state = render_match(monkeypatch, db, student, state=state)
    assert set(state["vocab_match"]["round_ids"]) == original_round_ids


# --- render_life_skill_badges: a trophy shelf, read-only over the real checklist ---


def render_badges(monkeypatch, skills):
    written: list[str] = []
    monkeypatch.setattr(ui, "st", Recorder(written, {}))
    ui.render_life_skill_badges(skills)
    return "\n".join(written)


def test_no_skills_renders_nothing(monkeypatch):
    assert render_badges(monkeypatch, []) == ""


def test_earned_and_locked_skills_are_labeled(monkeypatch, db, student):
    db.seed_life_skills(student["id"])
    skills = db.list_life_skills(student["id"])
    earned = next(s for s in skills if s["title"] == "Do laundry start to finish")
    db.set_life_skill_done(earned["id"], True)

    page = render_badges(monkeypatch, db.list_life_skills(student["id"]))
    assert "1 / 15" in page
    assert "Do laundry start to finish" in page
    assert "Home" in page
    assert "Money" in page


def test_a_custom_category_falls_back_to_the_default_icon(monkeypatch, db, student):
    db.add_life_skill(student["id"], "Learn to sew a button", "Sewing")
    page = render_badges(monkeypatch, db.list_life_skills(student["id"]))
    assert "Sewing" in page
    assert ui.LIFE_SKILL_DEFAULT_ICON in page


def test_a_skill_title_with_html_is_escaped(monkeypatch, db, student):
    db.add_life_skill(student["id"], "<script>alert(1)</script>", "General")
    page = render_badges(monkeypatch, db.list_life_skills(student["id"]))
    assert "<script>" not in page
    assert "&lt;script&gt;" in page
