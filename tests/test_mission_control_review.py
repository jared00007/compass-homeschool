"""Mission Control's Review tab (and its Backlog/Record neighbours): the
parent's read-and-decide queue. What he's turned in shows open and ready
to grade; overdue, sent-back, and still-planned work sit in their own
quieter sections below; and once a lesson's whole week has elapsed it drops
out to the Backlog entirely.

Uses real day offsets from `date.today()` rather than a fixed calendar
date -- the page itself calls `date.today()` directly (not through a
patchable module function), so pinning "today" would mean monkeypatching
the page's own script namespace, which AppTest doesn't expose. Relative
dates sidestep that entirely.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import streamlit as st
from streamlit.testing.v1 import AppTest

import compass.ui as ui
from compass import config, weekly
from compass.storage.db import Database

REPO_ROOT = Path(__file__).resolve().parent.parent
HOME_PATH = str(REPO_ROOT / "Home.py")
MISSION_CONTROL_PATH = str(REPO_ROOT / "pages" / "14_Mission_Control.py")


def _open_review_tab(monkeypatch, db_path):
    # get_db() is @st.cache_resource -- a global, process-wide cache keyed on
    # nothing but the function itself. Real deployments want exactly that (one
    # shared DB connection for every browser session); a test suite that opens
    # a fresh tmp_path DB per test does not, or the second test onward just
    # keeps talking to the first test's (now-closed) database.
    st.cache_resource.clear()
    monkeypatch.setattr(config, "DEFAULT_DB_PATH", db_path)
    at = AppTest.from_file(HOME_PATH)
    at.session_state["parent_unlocked"] = True
    at.run(timeout=30)
    at.switch_page(MISSION_CONTROL_PATH)
    at.run(timeout=30)
    assert not at.exception, [e.message for e in at.exception]
    return at, [t for t in at.tabs if t.label.startswith("✅ Review")][0]


def _review_tab(at):
    return [t for t in at.tabs if t.label.startswith("✅ Review")][0]


def _backlog_tab(at):
    return [t for t in at.tabs if t.label.startswith("🗄️ Backlog")][0]


def _md(tab):
    return [m.value for m in tab.markdown]


# --- the queue: turned in, overdue, sent back, still planned --------------------


def test_mission_control_has_a_courses_button(monkeypatch, tmp_path):
    """Courses folded off the sidebar into a button on Mission Control -- the
    first of the parent-admin pages to move into this hub."""
    db_path = tmp_path / "hub.db"
    db = Database(db_path)
    db.ensure_default_student()
    db.close()

    at, _ = _open_review_tab(monkeypatch, db_path)
    assert any((b.key or "") == "hub_courses" for b in at.button), "no Courses button on Mission Control"
    assert "Courses" in ui._FOLDED_IN_PAGES, "Courses must be hidden from the sidebar"


def test_a_submitted_lesson_surfaces_open_in_waiting_on_you(monkeypatch, tmp_path):
    """A turned-in lesson is the whole point of the queue: it shows in the
    "waiting on you" section as a collapsible card whose bar carries the
    badge and title. With just one thing waiting it starts expanded, so
    grading the sole item still takes no extra click."""
    db_path = tmp_path / "review.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    lid = db.save_lesson(
        student_id=student["id"], agent="science", subject="science", topic="t",
        title="Turned in", payload={"title": "Turned in", "activities": []},
    )
    db.submit_lesson(lid)
    db.close()

    at, review_tab = _open_review_tab(monkeypatch, db_path)
    assert review_tab.label == "✅ Review (1)"
    markdowns = _md(review_tab)
    assert any("Turned in — waiting on you" in m and "(1)" in m for m in markdowns)
    # The card is a collapsible expander; its bar carries the status + title,
    # and the sole waiting item opens automatically.
    waiting = [
        e for e in review_tab.expander
        if "turned in — waiting on you" in (e.label or "") and "Turned in" in (e.label or "")
    ]
    assert waiting, [e.label for e in review_tab.expander]


def test_the_waiting_bar_summarizes_hand_ins_and_quiz(monkeypatch, tmp_path):
    """The collapsed bar has to be worth scanning: it carries a quick read of
    what's inside -- how many hand-ins wait, and the quiz score -- so a parent
    can triage the queue without opening every card."""
    db_path = tmp_path / "review.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    payload = {
        "title": "Big one",
        "activities": [
            {"title": "Essay", "kind": "writing", "minutes": 30,
             "requires_written_response": True},
        ],
        "quiz": [{"question": "Q", "choices": ["a", "b"], "correct_index": 0}],
    }
    lid = db.save_lesson(
        student_id=student["id"], agent="english", subject="english", topic="t",
        title="Big one", payload=payload,
        metadata={"quiz_result": {"correct": 4, "total": 5, "passed": True}},
    )
    db.submit_lesson(lid)
    db.close()

    at, review_tab = _open_review_tab(monkeypatch, db_path)
    labels = " ".join(e.label or "" for e in review_tab.expander)
    assert "1 hand-in" in labels
    assert "quiz 4/5" in labels


def test_an_overdue_this_week_lesson_shows_in_the_overdue_section(monkeypatch, tmp_path):
    """Overdue but still within its own week: waiting on you, in its own
    section. Monday has no earlier day in its own week to build this case
    from, so the assertion only runs when today isn't a Monday."""
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    if week_start >= today:  # a Monday -- nothing earlier this week to be overdue
        return
    db_path = tmp_path / "review.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    db.save_lesson(
        student_id=student["id"], agent="math", subject="math", topic="t",
        title="Overdue this week", payload={"title": "Overdue this week", "activities": []},
        metadata={"planned_for": week_start.isoformat(), "week_start": week_start.isoformat()},
    )
    db.close()

    at, review_tab = _open_review_tab(monkeypatch, db_path)
    assert any("Overdue — not turned in yet" in m and "(1)" in m for m in _md(review_tab))
    labels = [e.label for e in review_tab.expander]
    assert any("overdue" in l and "Overdue this week" in l for l in labels)


def test_a_fully_elapsed_week_lesson_drops_to_backlog_not_the_queue(monkeypatch, tmp_path):
    """Once a lesson's whole week has come and gone without being turned in,
    it's no longer just overdue -- it's pulled out of his own view entirely
    and held in the Backlog until a parent moves it to a new day. The Review
    tab only notes the count; the card itself lives on the Backlog tab."""
    db_path = tmp_path / "review.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    db.save_lesson(
        student_id=student["id"], agent="math", subject="math", topic="t",
        title="Backlogged lesson", payload={"title": "Backlogged lesson", "activities": []},
        metadata={
            "planned_for": (week_start - timedelta(days=7)).isoformat(),
            "week_start": (week_start - timedelta(days=7)).isoformat(),
        },
    )
    db.close()

    at, review_tab = _open_review_tab(monkeypatch, db_path)
    assert not any("Overdue — not turned in yet" in m for m in _md(review_tab))
    assert any("1 lesson(s) parked in the Backlog" in i.value for i in review_tab.info)
    assert not any("Backlogged lesson" in (e.label or "") for e in review_tab.expander)
    assert any("Backlogged lesson" in (e.label or "") for e in _backlog_tab(at).expander)


def test_a_planned_ahead_lesson_shows_in_the_planned_section(monkeypatch, tmp_path):
    """Scheduled and still ahead of him -- kept reachable (to preview, log,
    or move) in the quieter 'Planned' section, not spread across a day
    board."""
    db_path = tmp_path / "review.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    future = date.today() + timedelta(days=2)
    db.save_lesson(
        student_id=student["id"], agent="math", subject="math", topic="t",
        title="Coming up", payload={"title": "Coming up", "activities": []},
        metadata={"planned_for": future.isoformat(), "week_start": weekly.week_start(future).isoformat()},
    )
    db.close()

    at, review_tab = _open_review_tab(monkeypatch, db_path)
    assert any("Planned — not turned in yet" in m and "(1)" in m for m in _md(review_tab))
    assert any("Coming up" in (e.label or "") for e in review_tab.expander)


def test_sending_a_planned_lesson_to_backlog_from_the_queue(monkeypatch, tmp_path):
    """The manual send-to-backlog move: park a lesson whenever a parent
    decides, not only once its week has run out. Offered on the still-open
    (planned/overdue) cards via the shared move control."""
    db_path = tmp_path / "review.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    future = date.today() + timedelta(days=2)
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="math", subject="math", topic="t",
        title="Parked on purpose", payload={"title": "Parked on purpose", "activities": []},
        metadata={"planned_for": future.isoformat(), "week_start": weekly.week_start(future).isoformat()},
    )
    db.close()

    at, review_tab = _open_review_tab(monkeypatch, db_path)
    assert any("Parked on purpose" in (e.label or "") for e in review_tab.expander)

    review_tab.button(key=f"move_lesson_{lesson_id}_send_to_backlog").click().run()
    review_tab = _review_tab(at)

    assert any("1 lesson(s) parked in the Backlog" in i.value for i in review_tab.info)
    assert not any("Parked on purpose" in (e.label or "") for e in review_tab.expander)
    assert any(
        "🗄️ backlogged" in (e.label or "") and "Parked on purpose" in (e.label or "")
        for e in _backlog_tab(at).expander
    )


def test_moving_a_backlogged_lesson_releases_it_from_the_backlog_tab(monkeypatch, tmp_path):
    db_path = tmp_path / "review.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    today = date.today()
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="math", subject="math", topic="t",
        title="Parked then released", payload={"title": "Parked then released", "activities": []},
        metadata={
            "planned_for": today.isoformat(),
            "week_start": weekly.week_start(today).isoformat(),
            "held_back": True,
        },
    )
    db.close()

    at, review_tab = _open_review_tab(monkeypatch, db_path)
    assert any("1 lesson(s) parked in the Backlog" in i.value for i in review_tab.info)

    backlog_tab = _backlog_tab(at)
    tomorrow = today + timedelta(days=1)
    backlog_tab.date_input(key=f"move_lesson_{lesson_id}_date_{today.isoformat()}").set_value(
        tomorrow
    ).run()

    review_tab = _review_tab(at)
    assert not any("parked in the Backlog" in i.value for i in review_tab.info)
    assert not any("Parked then released" in (e.label or "") for e in _backlog_tab(at).expander)


def test_a_sent_back_lesson_can_still_be_rescheduled(monkeypatch, tmp_path):
    """A lesson sent back isn't closed out -- he's meant to redo it, and a
    parent might push that redo to a later day. Only 'submitted' (already
    turned in) loses the move control."""
    db_path = tmp_path / "review.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    week_start = weekly.week_start(date.today())
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="math", subject="math", topic="t",
        title="Sent back for a redo", payload={"title": "Sent back for a redo", "activities": []},
        metadata={"planned_for": week_start.isoformat(), "week_start": week_start.isoformat()},
    )
    db.set_lesson_status(lesson_id, "needs_revision")
    db.close()

    at, review_tab = _open_review_tab(monkeypatch, db_path)
    backlog_key = f"move_lesson_{lesson_id}_send_to_backlog"
    button = [b for b in review_tab.button if b.key == backlog_key]
    assert button, "the move control must still be offered on a needs_revision lesson"
    button[0].click().run()

    db = Database(db_path)
    lesson = db.get_lesson(lesson_id)
    db.close()
    assert lesson["metadata"].get("held_back") is True


def test_a_submitted_lesson_gets_no_move_control(monkeypatch, tmp_path):
    """A submitted lesson is already turned in and waiting on a decision --
    rescheduling it out from under that doesn't make sense, so it keeps just
    Skip/Remove."""
    db_path = tmp_path / "review.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="math", subject="math", topic="t",
        title="Turned in already", payload={"title": "Turned in already", "activities": []},
    )
    db.set_lesson_status(lesson_id, "submitted")
    db.close()

    at, review_tab = _open_review_tab(monkeypatch, db_path)
    move_widgets = [
        w.key for w in (list(review_tab.button) + list(review_tab.checkbox) + list(review_tab.date_input))
        if w.key and w.key.startswith(f"move_lesson_{lesson_id}_")
    ]
    assert not move_widgets, "a submitted lesson should not offer the move control"


def test_a_held_back_lesson_not_yet_due_shows_backlogged(monkeypatch, tmp_path):
    """Sent to backlog ahead of its own due date -- shown as deliberately
    parked, not misread as 'overdue' (it isn't due yet). The card lives on
    the Backlog tab."""
    db_path = tmp_path / "review.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    future = date.today() + timedelta(days=3)
    db.save_lesson(
        student_id=student["id"], agent="math", subject="math", topic="t",
        title="Parked ahead of time", payload={"title": "Parked ahead of time", "activities": []},
        metadata={
            "planned_for": future.isoformat(),
            "week_start": weekly.week_start(future).isoformat(),
            "held_back": True,
        },
    )
    db.close()

    at, _ = _open_review_tab(monkeypatch, db_path)
    labels = [e.label for e in _backlog_tab(at).expander]
    assert any("🗄️ backlogged" in l and "Parked ahead of time" in l for l in labels)
    assert not any("overdue" in l and "Parked ahead of time" in l for l in labels)


# --- Travel Journal entries share the same Review queue ------------------------


def test_a_submitted_travel_entry_shows_up_waiting_on_you(monkeypatch, tmp_path):
    db_path = tmp_path / "review.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    db.add_travel_entry(
        student["id"], "Arizona", "2025-06-10", title="Grand Canyon",
        story="We hiked to the rim.", status="submitted",
    )
    db.close()

    at, review_tab = _open_review_tab(monkeypatch, db_path)
    assert review_tab.label == "✅ Review (1)"
    # The travel card is a collapsible expander now, same as the lesson cards;
    # its bar carries the status and the trip title.
    assert any(
        "turned in — waiting on you" in (e.label or "") and "Grand Canyon" in (e.label or "")
        for e in review_tab.expander
    ), [e.label for e in review_tab.expander]


def test_a_planned_unwritten_travel_stub_does_not_show_up(monkeypatch, tmp_path):
    """Nothing to review yet about a trip he hasn't written -- unlike an
    overdue lesson, an assigned-but-blank stub isn't itself waiting on a
    parent."""
    db_path = tmp_path / "review.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    db.add_travel_entry(student["id"], "Arizona", "2025-06-10", title="Grand Canyon", status="planned")
    db.close()

    at, review_tab = _open_review_tab(monkeypatch, db_path)
    assert review_tab.label == "✅ Review (0)"
    assert not any("Grand Canyon" in m for m in _md(review_tab))


def test_approving_a_travel_entry_completes_it_and_logs_credit(monkeypatch, tmp_path):
    db_path = tmp_path / "review.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    entry_id = db.add_travel_entry(
        student["id"], "Arizona", "2025-06-10", title="Grand Canyon",
        story="We hiked to the rim.", status="submitted",
    )
    db.close()

    at, review_tab = _open_review_tab(monkeypatch, db_path)
    approve = [b for b in review_tab.button if b.key == f"mc_approve_travel_{entry_id}"][0]
    approve.click().run()
    assert not at.exception, [e.message for e in at.exception]

    db = Database(db_path)
    entry = db.list_travel_entries(student["id"])[0]
    activities = db.list_activities(student["id"])
    db.close()
    assert entry["status"] == "completed"
    assert len(activities) == 1
    assert activities[0]["source"] == "travel_journal"


def test_approving_a_travel_entry_with_feedback_stores_it(monkeypatch, tmp_path):
    db_path = tmp_path / "review.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    entry_id = db.add_travel_entry(
        student["id"], "Arizona", "2025-06-10", title="Grand Canyon",
        story="We hiked to the rim.", status="submitted",
    )
    db.close()

    at, review_tab = _open_review_tab(monkeypatch, db_path)
    feedback_input = [
        w for w in review_tab.text_area if w.label == "Feedback (optional, shown to him)"
    ][0]
    feedback_input.set_value("Loved reading this one.")
    approve = [b for b in review_tab.button if b.key == f"mc_approve_travel_{entry_id}"][0]
    approve.click().run()
    assert not at.exception, [e.message for e in at.exception]

    db = Database(db_path)
    entry = db.list_travel_entries(student["id"])[0]
    db.close()
    assert entry["status"] == "completed"
    assert entry["parent_feedback"] == "Loved reading this one."


def test_sending_a_travel_entry_back_sets_needs_revision(monkeypatch, tmp_path):
    db_path = tmp_path / "review.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    entry_id = db.add_travel_entry(
        student["id"], "Arizona", "2025-06-10", title="Grand Canyon",
        story="We went there.", status="submitted",
    )
    db.close()

    at, review_tab = _open_review_tab(monkeypatch, db_path)
    bounce = [b for b in review_tab.button if b.key == f"mc_bounce_travel_{entry_id}"][0]
    bounce.click().run()
    review_tab = _review_tab(at)

    note_input = [w for w in review_tab.text_input if w.label == "What should he fix or add?"][0]
    note_input.set_value("Add more detail.")
    send = [b for b in review_tab.button if b.label == "Send back"][0]
    send.click().run()
    assert not at.exception, [e.message for e in at.exception]

    db = Database(db_path)
    entry = db.list_travel_entries(student["id"])[0]
    db.close()
    assert entry["status"] == "needs_revision"
    assert "more detail" in entry["revision_note"]


# --- the Record tab: completed/skipped history behind a checkbox ---------------


def test_history_stays_hidden_until_the_checkbox_is_checked(monkeypatch, tmp_path):
    db_path = tmp_path / "review.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    lid = db.save_lesson(
        student_id=student["id"], agent="math", subject="math", topic="t",
        title="Finished lesson", payload={"title": "Finished lesson", "activities": []},
    )
    db.set_lesson_status(lid, "completed")
    db.close()

    at, review_tab = _open_review_tab(monkeypatch, db_path)
    assert not any("Finished lesson" in (e.label or "") for e in review_tab.expander)
    assert any("Nothing turned in to grade" in s.value for s in review_tab.success)

    checkbox = [c for c in at.checkbox if c.label.startswith("Also show")][0]
    checkbox.set_value(True).run()

    assert any("Finished lesson" in (e.label or "") for e in at.expander)


# --- the consolidated Backlog tab: every item type parked, one place -----------
#
# Reported directly: a parent needs a clean view into what's backlogged (or
# just left over in an in-progress project) across every item type, not only
# lessons -- "Landon did the first two legs of Lego film, backlog would
# clearly show what's left."


def test_backlog_tab_shows_nothing_parked_when_everything_is_clear(monkeypatch, tmp_path):
    db_path = tmp_path / "backlog.db"
    db = Database(db_path)
    db.ensure_default_student()
    db.close()

    at, _ = _open_review_tab(monkeypatch, db_path)

    successes = [s.value for s in _backlog_tab(at).success]
    assert any("Nothing parked anywhere" in s for s in successes)


def test_backlog_tab_groups_a_projects_remaining_steps_by_title(monkeypatch, tmp_path):
    """Both a step still in Backlog and a step already in To Do but not
    finished yet count as "what's left" -- together, since a parent
    describing an in-progress project means both."""
    db_path = tmp_path / "backlog.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    project_id = db.add_big_project(student["id"], "Lego Stop-Motion Film")
    done_id = db.add_project_step(project_id, "Write the script", active=True)
    db.set_project_step_done(done_id, True)
    todo_id = db.add_project_step(project_id, "Storyboard it", active=True)
    backlog_id = db.add_project_step(project_id, "Film the last scene")  # defaults to Backlog
    db.close()

    at, _ = _open_review_tab(monkeypatch, db_path)
    backlog_tab = _backlog_tab(at)

    # Not an exact total -- adding any custom project also triggers
    # _backfill_big_project_catalog's own top-up (pre-existing, unrelated
    # behavior: a family with *any* project gets the starter catalog too),
    # so other projects' steps count here as well.
    markdowns = [m.value for m in backlog_tab.markdown]
    assert any("Big Projects" in m for m in markdowns)
    # Each project is now its own collapsible expander (title + count),
    # rather than a bold caption; its remaining steps render as bordered
    # cards inside, each step's title/status a markdown line.
    assert any("Lego Stop-Motion Film" in (e.label or "") for e in backlog_tab.expander)
    assert any("Storyboard it" in m and "To Do" in m for m in markdowns)
    assert any("Film the last scene" in m and "Backlog" in m for m in markdowns)
    # The finished step isn't "left" -- it doesn't show up here at all.
    assert not any("Write the script" in m for m in markdowns)

    # Un-backlogging is now the shared move control's own button, not a
    # bespoke "➡️ To Do" one -- same "Take out of Backlog" every story type uses.
    backlog_tab.button(
        key=f"move_backlog_step_{backlog_id}_take_out_of_backlog"
    ).click().run()

    db = Database(db_path)
    step = next(s for s in db.list_project_steps(project_id) if s["id"] == backlog_id)
    db.close()
    assert step["active"] == 1
    assert todo_id  # sanity: the other step really was created


def test_backlog_tab_excludes_a_project_with_nothing_left(monkeypatch, tmp_path):
    db_path = tmp_path / "backlog.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    project_id = db.add_big_project(student["id"], "Finished Project")
    step_id = db.add_project_step(project_id, "Only step", active=True)
    db.set_project_step_done(step_id, True)
    db.close()

    at, _ = _open_review_tab(monkeypatch, db_path)
    markdowns = [m.value for m in _backlog_tab(at).markdown]
    assert not any("Finished Project" in m for m in markdowns)


def test_backlog_tab_excludes_the_travel_log_project(monkeypatch, tmp_path):
    """The Travel Log folder never has project_steps rows at all (see
    Database.ensure_travel_log_project) -- it must never show up in this
    section, since it has nothing a step-level "what's left" applies to."""
    db_path = tmp_path / "backlog.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    db.ensure_travel_log_project(student["id"])
    db.close()

    at, _ = _open_review_tab(monkeypatch, db_path)
    markdowns = [m.value for m in _backlog_tab(at).markdown]
    assert not any("Travel Log" in m for m in markdowns)


def test_backlog_tab_has_no_life_skills_section(monkeypatch, tmp_path):
    """Life Skills' own "backlog" is its 161-entry master catalog, most of
    it locked by design (a pace-control menu, not situational parking) --
    listing all of it here with individual un-backlog buttons would bury
    the small, situational sections this tab is actually for. Its own
    Master List tab already is the right place for that."""
    db_path = tmp_path / "backlog.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    skill_id = db.add_life_skill(student["id"], "Change a tire", "Vehicle")
    db.set_life_skill_active(skill_id, False)
    db.close()

    at, _ = _open_review_tab(monkeypatch, db_path)
    backlog_tab = _backlog_tab(at)
    markdowns = [m.value for m in backlog_tab.markdown]
    assert not any("Life Skills" in m for m in markdowns)
    assert not any(f"backlog_tab_unls_{skill_id}" == b.key for b in backlog_tab.button)


def test_backlog_tab_lists_a_backlogged_choice_topic_with_an_unbacklog_button(monkeypatch, tmp_path):
    db_path = tmp_path / "backlog.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    topic_id = db.add_choice_topic(student["id"], "Learn guitar chords", active=False)
    db.close()

    at, _ = _open_review_tab(monkeypatch, db_path)
    backlog_tab = _backlog_tab(at)
    markdowns = [m.value for m in backlog_tab.markdown]
    assert any("Choice Topics" in m and "(1)" in m for m in markdowns)

    backlog_tab.button(key=f"backlog_tab_untopic_{topic_id}").click().run()

    db = Database(db_path)
    topic = next(t for t in db.list_choice_topics(student["id"]) if t["id"] == topic_id)
    db.close()
    assert topic["active"] == 1


def test_backlog_tab_excludes_a_done_or_declined_choice_topic(monkeypatch, tmp_path):
    db_path = tmp_path / "backlog.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    topic_id = db.add_choice_topic(student["id"], "Learn guitar chords")
    db.set_choice_status(topic_id, "declined")
    db.set_choice_topic_active(topic_id, False)
    db.close()

    at, _ = _open_review_tab(monkeypatch, db_path)
    markdowns = [m.value for m in _backlog_tab(at).markdown]
    assert not any("Choice Topics" in m for m in markdowns)


def test_the_review_surfaces_the_assessment_answer_sheet(monkeypatch, tmp_path):
    """The parent's grading guide (the assessment he never sees) shows in the
    review, below his work -- reported: "wheres that answer sheet for me?\""""
    db_path = tmp_path / "review.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    lid = db.save_lesson(
        student_id=student["id"], agent="math", subject="math", topic="t",
        title="Coordinate Plane",
        payload={
            "title": "Coordinate Plane",
            "activities": [],
            "assessment": {
                "kind": "worksheet",
                "description": "PART A — plot (4, 6) and (-3, -7).",
                "answer_key": "A: (4, 6) is Quadrant I. (-3, -7) is Quadrant III.",
                "mastery_criteria": "All points plotted in the correct quadrant.",
            },
        },
    )
    db.submit_lesson(lid)
    db.close()

    at, review_tab = _open_review_tab(monkeypatch, db_path)
    markdowns = " ".join(_md(review_tab))
    assert "For grading" in markdowns
    assert "PART A — plot (4, 6)" in markdowns
    assert "Answer key" in markdowns
    assert "Quadrant III" in markdowns
    assert "Counts as mastered when" in markdowns
    assert "correct quadrant" in markdowns


def test_approving_a_below_bar_math_quiz_does_not_record_mastery(monkeypatch, tmp_path):
    """A parent Approve on a Math skill whose latest quiz is under the mastery
    bar logs the hours and accepts the work, but must NOT silently record the
    skill as mastered -- that's how a stale "mastered at 80%" used to appear.
    Reported directly: "math should no longer be mastered if he bombs a quiz.\""""
    db_path = tmp_path / "review.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    lid = db.save_lesson(
        student_id=student["id"], agent="math", subject="math", topic="t",
        title="Coordinate Plane",
        payload={"title": "Coordinate Plane", "activities": []},
        metadata={"skill_id": "coord-plane"},
    )
    # 80% quiz -- passes, but under the default 100% mastery bar. Reconcile
    # leaves it unmastered (it was never mastered).
    db.record_quiz_result(lid, student["id"], correct=4, total=5, passed=True)
    db.submit_lesson(lid)
    db.close()

    at, review_tab = _open_review_tab(monkeypatch, db_path)
    approve_key = f"FormSubmitter:review_{lid}_assess_{lid}-✅ Approve & log hours"
    [b for b in at.button if b.key == approve_key][0].click().run()
    assert not at.exception, [e.message for e in at.exception]

    db2 = Database(db_path)
    row = db2.mastery_map(student["id"]).get("coord-plane", {})
    db2.close()
    assert row.get("status") == "in_progress"  # accepted, but not mastered


def test_the_override_checkbox_lets_a_parent_master_below_the_bar(monkeypatch, tmp_path):
    """The escape hatch: a parent confident despite a low quiz can tick the
    override and Approve records mastery deliberately."""
    db_path = tmp_path / "review.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    lid = db.save_lesson(
        student_id=student["id"], agent="math", subject="math", topic="t",
        title="Coordinate Plane",
        payload={"title": "Coordinate Plane", "activities": []},
        metadata={"skill_id": "coord-plane"},
    )
    db.record_quiz_result(lid, student["id"], correct=4, total=5, passed=True)
    db.submit_lesson(lid)
    db.close()

    at, review_tab = _open_review_tab(monkeypatch, db_path)
    at.checkbox(key=f"review_{lid}_master_override_{lid}").set_value(True).run()
    approve_key = f"FormSubmitter:review_{lid}_assess_{lid}-✅ Approve & log hours"
    [b for b in at.button if b.key == approve_key][0].click().run()
    assert not at.exception, [e.message for e in at.exception]

    db2 = Database(db_path)
    row = db2.mastery_map(student["id"]).get("coord-plane", {})
    db2.close()
    assert row.get("status") == "mastered"


def test_submitted_project_steps_show_as_needs_review(monkeypatch, tmp_path):
    """A submitted Big Project step surfaces in the review tab's "waiting on
    you" section with a link out to Big Projects, so "needs review" isn't
    buried on another tab."""
    db_path = tmp_path / "review.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    pid = db.add_big_project(student_id=student["id"], title="Toy Photography", vision="v")
    step = db.add_project_step(pid, "Pick your toy and your theme", active=True)
    db.submit_project_step(step, "Red car, noir theme.")
    db.close()

    at, review_tab = _open_review_tab(monkeypatch, db_path)
    assert review_tab.label == "✅ Review (1)"
    markdowns = " ".join(_md(review_tab))
    assert "project step(s) turned in" in markdowns
    assert "Pick your toy and your theme" in markdowns
