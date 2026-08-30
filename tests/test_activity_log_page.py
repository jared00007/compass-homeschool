"""The Activity Log's "To review" tab: a weekly board (Monday-Thursday
columns matching how lessons actually get planned) plus an attention
section that pulls anything overdue or already-done-but-unlogged out of
its day column, regardless of which day or week it's for.

Uses real day offsets from `date.today()` rather than a fixed calendar
date -- the page itself calls `date.today()` directly (not through a
patchable module function like `weekly.date`), so pinning "today" would
mean monkeypatching the page's own script namespace, which AppTest
doesn't expose. Relative dates sidestep that entirely.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import streamlit as st
from streamlit.testing.v1 import AppTest

from compass import config, weekly
from compass.storage.db import Database

REPO_ROOT = Path(__file__).resolve().parent.parent
HOME_PATH = str(REPO_ROOT / "Home.py")
ACTIVITY_LOG_PATH = str(REPO_ROOT / "pages" / "10_Activity_Log.py")


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
    at.switch_page(ACTIVITY_LOG_PATH)
    at.run(timeout=30)
    assert not at.exception, [e.message for e in at.exception]
    return at, [t for t in at.tabs if t.label.startswith("To review")][0]


def _backlog_tab(at):
    return [t for t in at.tabs if t.label.startswith("🗄️ Backlog")][0]


def test_submitted_and_still_this_week_overdue_surface_regardless_of_day(monkeypatch, tmp_path):
    """A submitted lesson always needs a look, whatever weekday this test
    happens to run on. An overdue-but-still-this-week lesson does too --
    only once its *own* week fully ends does it become backlog instead
    (see the backlog-specific test below). Monday has no earlier day in
    its own week to construct that second case from, so it's only added
    when today isn't a Monday -- the submitted-lesson assertion alone
    still runs every day."""
    db_path = tmp_path / "review.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    sid = student["id"]
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    expected_attention = 1

    if week_start < today:
        db.save_lesson(
            student_id=sid, agent="math", subject="math", topic="t",
            title="Overdue this week",
            payload={"title": "Overdue this week", "activities": []},
            metadata={"planned_for": week_start.isoformat(), "week_start": week_start.isoformat()},
        )
        expected_attention = 2
    lid = db.save_lesson(
        student_id=sid, agent="science", subject="science", topic="t", title="Turned in",
        payload={"title": "Turned in", "activities": []},
        metadata={"planned_for": today.isoformat(), "week_start": week_start.isoformat()},
    )
    db.submit_lesson(lid)
    db.close()

    at, review_tab = _open_review_tab(monkeypatch, db_path)

    markdowns = [m.value for m in review_tab.markdown]
    assert any(
        "Needs your attention now" in m and f"({expected_attention})" in m for m in markdowns
    )
    labels = [e.label for e in review_tab.expander]
    assert any("waiting on you to review" in l and "Turned in" in l for l in labels)
    if week_start < today:
        assert any("overdue" in l and "Overdue this week" in l for l in labels)


def test_a_lesson_from_a_fully_elapsed_week_moves_to_backlog_not_attention(monkeypatch, tmp_path):
    """The actual point of the Backlog feature: once a lesson's whole week
    has come and gone without it being turned in, it's no longer "just
    overdue" -- it's pulled out of Landon's own view entirely (see
    weekly.is_backlogged/due_lessons) and held here until a parent
    explicitly moves it to a new day."""
    db_path = tmp_path / "review.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    sid = student["id"]
    today = date.today()
    week_start = today - timedelta(days=today.weekday())

    db.save_lesson(
        student_id=sid, agent="math", subject="math", topic="t", title="Backlogged lesson",
        payload={"title": "Backlogged lesson", "activities": []},
        metadata={
            "planned_for": (week_start - timedelta(days=7)).isoformat(),
            "week_start": (week_start - timedelta(days=7)).isoformat(),
        },
    )
    db.close()

    at, review_tab = _open_review_tab(monkeypatch, db_path)

    markdowns = [m.value for m in review_tab.markdown]
    assert not any("Needs your attention now" in m for m in markdowns)
    infos = [i.value for i in review_tab.info]
    assert any("1 lesson(s) in the Backlog" in i for i in infos)
    # The card itself (with its reschedule action) lives on the dedicated
    # Backlog tab now, not duplicated here too.
    labels = [e.label for e in review_tab.expander]
    assert not any("Backlogged lesson" in l for l in labels)
    labels = [e.label for e in _backlog_tab(at).expander]
    assert any("Backlogged lesson" in l for l in labels)


def test_sending_a_currently_due_lesson_to_backlog_pulls_it_off_the_board(monkeypatch, tmp_path):
    """The actual point of the manual send-to-backlog feature, reported
    directly: freedom to move a story into the backlog whenever a parent
    decides, not only once its whole week has quietly run out on its own.

    Planned for this week's own Monday rather than literally today -- a
    real day on the board no matter what weekday this test happens to run
    on (today itself can be a weekend, which the board doesn't have a
    column for at all)."""
    db_path = tmp_path / "review.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    sid = student["id"]
    week_start = weekly.week_start(date.today())

    lesson_id = db.save_lesson(
        student_id=sid, agent="math", subject="math", topic="t", title="Parked on purpose",
        payload={"title": "Parked on purpose", "activities": []},
        metadata={"planned_for": week_start.isoformat(), "week_start": week_start.isoformat()},
    )
    db.close()

    at, review_tab = _open_review_tab(monkeypatch, db_path)
    labels = [e.label for e in review_tab.expander]
    assert any("Parked on purpose" in l for l in labels)
    assert not any("backlogged" in l and "Parked on purpose" in l for l in labels)

    review_tab.checkbox(key=f"move_lesson_{lesson_id}_backlog_True").check().run()
    review_tab = [t for t in at.tabs if t.label.startswith("To review")][0]

    infos = [i.value for i in review_tab.info]
    assert any("1 lesson(s) in the Backlog" in i for i in infos)
    labels = [e.label for e in review_tab.expander]
    assert not any("Parked on purpose" in l for l in labels)
    labels = [e.label for e in _backlog_tab(at).expander]
    assert any("🗄️ backlogged" in l and "Parked on purpose" in l for l in labels)


def test_moving_a_manually_backlogged_lesson_releases_it(monkeypatch, tmp_path):
    db_path = tmp_path / "review.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    sid = student["id"]
    today = date.today()

    lesson_id = db.save_lesson(
        student_id=sid, agent="math", subject="math", topic="t", title="Parked then released",
        payload={"title": "Parked then released", "activities": []},
        metadata={
            "planned_for": today.isoformat(),
            "week_start": weekly.week_start(today).isoformat(),
            "held_back": True,
        },
    )
    db.close()

    at, review_tab = _open_review_tab(monkeypatch, db_path)
    infos = [i.value for i in review_tab.info]
    assert any("1 lesson(s) in the Backlog" in i for i in infos)

    # The reschedule action lives on the dedicated Backlog tab now, as the
    # shared move control's own date picker.
    backlog_tab = _backlog_tab(at)
    tomorrow = (today + timedelta(days=1)).isoformat()
    backlog_tab.date_input(key=f"move_lesson_{lesson_id}_date_{today.isoformat()}").set_value(
        date.fromisoformat(tomorrow)
    ).run()

    review_tab = [t for t in at.tabs if t.label.startswith("To review")][0]
    assert not any(
        "1 lesson(s) in the Backlog" in i.value for i in review_tab.info
    )
    labels = [e.label for e in _backlog_tab(at).expander]
    assert not any("Parked then released" in l for l in labels)


def test_a_held_back_lesson_not_yet_due_shows_backlogged_not_planned(monkeypatch, tmp_path):
    """Sent to backlog ahead of its own due date -- still shown as
    deliberately parked, not misread as merely "planned" or, worse,
    "overdue" (it isn't due yet at all)."""
    db_path = tmp_path / "review.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    sid = student["id"]
    future = date.today() + timedelta(days=3)

    db.save_lesson(
        student_id=sid, agent="math", subject="math", topic="t", title="Parked ahead of time",
        payload={"title": "Parked ahead of time", "activities": []},
        metadata={
            "planned_for": future.isoformat(),
            "week_start": weekly.week_start(future).isoformat(),
            "held_back": True,
        },
    )
    db.close()

    at, review_tab = _open_review_tab(monkeypatch, db_path)
    # The card itself (badge included) renders on the dedicated Backlog tab,
    # not duplicated inside "To review" too -- see the summary info there.
    labels = [e.label for e in _backlog_tab(at).expander]
    assert any("🗄️ backlogged" in l and "Parked ahead of time" in l for l in labels)
    assert not any("overdue" in l and "Parked ahead of time" in l for l in labels)


def test_board_columns_only_show_their_own_day(monkeypatch, tmp_path):
    db_path = tmp_path / "review.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    sid = student["id"]
    today = date.today()
    # Always next week's Monday/Tuesday -- guaranteed to be in the future no
    # matter what weekday "today" happens to be, so neither one can ever be
    # picked up as overdue regardless of when this test actually runs.
    next_week_start = weekly.week_start(today) + timedelta(days=7)
    day_a, day_b = weekly.week_dates(next_week_start)[:2]

    db.save_lesson(
        student_id=sid, agent="math", subject="math", topic="t", title="Monday's lesson",
        payload={"title": "Monday's lesson", "activities": []},
        metadata={"planned_for": day_a.isoformat(), "week_start": next_week_start.isoformat()},
    )
    db.save_lesson(
        student_id=sid, agent="english", subject="english", topic="t", title="Tuesday's lesson",
        payload={"title": "Tuesday's lesson", "activities": []},
        metadata={"planned_for": day_b.isoformat(), "week_start": next_week_start.isoformat()},
    )
    db.close()

    at, review_tab = _open_review_tab(monkeypatch, db_path)
    week_picker = [w for w in review_tab.date_input if w.label.startswith("Week to review")][0]
    week_picker.set_value(next_week_start).run()
    review_tab = [t for t in at.tabs if t.label.startswith("To review")][0]

    labels = [e.label for e in review_tab.expander]
    assert any("Monday's lesson" in l for l in labels)
    assert any("Tuesday's lesson" in l for l in labels)
    # Neither is overdue or done, so both stay in the board -- not the attention section.
    markdowns = [m.value for m in review_tab.markdown]
    assert not any("Needs your attention now" in m for m in markdowns)


def test_lesson_with_no_planned_for_lands_in_unscheduled(monkeypatch, tmp_path):
    db_path = tmp_path / "review.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    sid = student["id"]
    db.save_lesson(
        student_id=sid, agent="life_skills", subject="life_skills", topic="t",
        title="On-demand lesson", payload={"title": "On-demand lesson", "activities": []},
    )
    db.close()

    at, review_tab = _open_review_tab(monkeypatch, db_path)

    markdowns = [m.value for m in review_tab.markdown]
    assert any("Not tied to a specific day" in m and "(1)" in m for m in markdowns)
    labels = [e.label for e in review_tab.expander]
    assert any("On-demand lesson" in l for l in labels)


def test_switching_the_week_picker_changes_the_board(monkeypatch, tmp_path):
    db_path = tmp_path / "review.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    sid = student["id"]
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    next_monday = week_start + timedelta(days=7)

    db.save_lesson(
        student_id=sid, agent="math", subject="math", topic="t", title="Next week's lesson",
        payload={"title": "Next week's lesson", "activities": []},
        metadata={"planned_for": next_monday.isoformat(), "week_start": next_monday.isoformat()},
    )
    db.close()

    at, review_tab = _open_review_tab(monkeypatch, db_path)
    labels = [e.label for e in review_tab.expander]
    assert not any("Next week's lesson" in l for l in labels)

    week_picker = [w for w in review_tab.date_input if w.label.startswith("Week to review")][0]
    week_picker.set_value(next_monday).run()
    review_tab = [t for t in at.tabs if t.label.startswith("To review")][0]

    labels = [e.label for e in review_tab.expander]
    assert any("Next week's lesson" in l for l in labels)


def test_a_lesson_planned_for_another_week_is_not_silently_dropped(monkeypatch, tmp_path):
    """A real bug, found live: a lesson that's neither overdue/submitted
    (so not in 'attention') nor unscheduled (it does have a planned_for)
    but scheduled for a week other than the one on screen used to fall
    through every bucket and vanish -- rendered nowhere, with no way to
    even find it via the date picker above.

    It doesn't count toward the header total (a lesson simply scheduled
    for later isn't something to review yet -- a separate, later
    complaint: the count used to include it too), but it's still visible
    via the caption below, naming which week to switch to."""
    db_path = tmp_path / "review.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    sid = student["id"]
    today = date.today()
    # Two weeks out -- guaranteed not to be "this week" (the picker's
    # default) and not overdue no matter when this test runs.
    other_week_start = weekly.week_start(today) + timedelta(days=14)
    db.save_lesson(
        student_id=sid, agent="math", subject="math", topic="t", title="Later week's lesson",
        payload={"title": "Later week's lesson", "activities": []},
        metadata={"planned_for": other_week_start.isoformat(), "week_start": other_week_start.isoformat()},
    )
    db.close()

    at, review_tab = _open_review_tab(monkeypatch, db_path)
    # Nothing here actually needs your review -- it's just scheduled for
    # later -- so the header count is 0, not 1.
    assert review_tab.label == "To review (0)"
    labels = [e.label for e in review_tab.expander]
    assert not any("Later week's lesson" in l for l in labels)
    captions = [c.value for c in review_tab.caption]
    assert any(
        "1 more lesson" in c and "different week" in c and other_week_start.isoformat() in c
        for c in captions
    )
    # "Nothing waiting on you" is about actual review items, and there
    # genuinely are none -- a future lesson isn't one, so this still shows.
    assert any("Nothing waiting on you" in s.value for s in review_tab.success)


def test_a_friday_substitute_lesson_shows_on_the_board_not_other_week(monkeypatch, tmp_path):
    """This Week's school-days picker can opt Friday in as a lesson day
    (a stand-in for a holiday earlier that same week) -- a lesson planned
    there belongs in the board's own Friday column, not misreported as
    'scheduled for a different week' just because the board's day columns
    used to stop at Thursday."""
    db_path = tmp_path / "review.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    sid = student["id"]
    today = date.today()
    next_week_start = weekly.week_start(today) + timedelta(days=7)
    friday = weekly.week_dates(next_week_start, include_friday=True)[-1]

    db.save_lesson(
        student_id=sid, agent="math", subject="math", topic="t", title="Friday's lesson",
        payload={"title": "Friday's lesson", "activities": []},
        metadata={"planned_for": friday.isoformat(), "week_start": next_week_start.isoformat()},
    )
    db.close()

    at, review_tab = _open_review_tab(monkeypatch, db_path)
    week_picker = [w for w in review_tab.date_input if w.label.startswith("Week to review")][0]
    week_picker.set_value(next_week_start).run()
    review_tab = [t for t in at.tabs if t.label.startswith("To review")][0]

    labels = [e.label for e in review_tab.expander]
    assert any("Friday's lesson" in l for l in labels)
    captions = [c.value for c in review_tab.caption]
    assert not any("different week" in c for c in captions)


# --- Travel Journal entries share the same "To review" queue -------------------


def test_a_submitted_travel_entry_shows_up_in_to_review(monkeypatch, tmp_path):
    db_path = tmp_path / "review.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    db.add_travel_entry(
        student["id"], "Arizona", "2025-06-10", title="Grand Canyon",
        story="We hiked to the rim.", status="submitted",
    )
    db.close()

    at, review_tab = _open_review_tab(monkeypatch, db_path)
    assert review_tab.label == "To review (1)"
    markdowns = [m.value for m in review_tab.markdown]
    assert any("Travel Journal" in m and "(1)" in m for m in markdowns)
    labels = [e.label for e in review_tab.expander]
    assert any("waiting on you to review" in l and "Grand Canyon" in l for l in labels)


def test_a_planned_unwritten_travel_stub_does_not_show_up_to_review(monkeypatch, tmp_path):
    """Nothing to review yet about a trip he hasn't written -- unlike an
    overdue lesson, an assigned-but-blank stub isn't itself the thing
    waiting on a parent."""
    db_path = tmp_path / "review.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    db.add_travel_entry(student["id"], "Arizona", "2025-06-10", title="Grand Canyon", status="planned")
    db.close()

    at, review_tab = _open_review_tab(monkeypatch, db_path)
    assert review_tab.label == "To review (0)"
    markdowns = [m.value for m in review_tab.markdown]
    assert not any("Travel Journal" in m for m in markdowns)


def test_approving_a_travel_entry_from_activity_log_completes_it_and_logs_credit(monkeypatch, tmp_path):
    db_path = tmp_path / "review.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    entry_id = db.add_travel_entry(
        student["id"], "Arizona", "2025-06-10", title="Grand Canyon",
        story="We hiked to the rim.", status="submitted",
    )
    db.close()

    at, review_tab = _open_review_tab(monkeypatch, db_path)
    approve = [b for b in review_tab.button if b.key == f"activitylog_approve_travel_{entry_id}"][0]
    approve.click().run()
    assert not at.exception, [e.message for e in at.exception]

    db = Database(db_path)
    entry = db.list_travel_entries(student["id"])[0]
    activities = db.list_activities(student["id"])
    db.close()
    assert entry["status"] == "completed"
    assert len(activities) == 1
    assert activities[0]["source"] == "travel_journal"


def test_approving_with_feedback_from_activity_log_stores_it(monkeypatch, tmp_path):
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
    approve = [b for b in review_tab.button if b.key == f"activitylog_approve_travel_{entry_id}"][0]
    approve.click().run()
    assert not at.exception, [e.message for e in at.exception]

    db = Database(db_path)
    entry = db.list_travel_entries(student["id"])[0]
    db.close()
    assert entry["status"] == "completed"
    assert entry["parent_feedback"] == "Loved reading this one."


def test_sending_a_travel_entry_back_from_activity_log_sets_needs_revision(monkeypatch, tmp_path):
    db_path = tmp_path / "review.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    entry_id = db.add_travel_entry(
        student["id"], "Arizona", "2025-06-10", title="Grand Canyon",
        story="We went there.", status="submitted",
    )
    db.close()

    at, review_tab = _open_review_tab(monkeypatch, db_path)
    bounce = [b for b in review_tab.button if b.key == f"activitylog_bounce_travel_{entry_id}"][0]
    bounce.click().run()
    review_tab = [t for t in at.tabs if t.label.startswith("To review")][0]

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


def test_history_stays_hidden_until_the_checkbox_is_checked(monkeypatch, tmp_path):
    db_path = tmp_path / "review.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    sid = student["id"]
    lid = db.save_lesson(
        student_id=sid, agent="math", subject="math", topic="t", title="Finished lesson",
        payload={"title": "Finished lesson", "activities": []},
    )
    db.set_lesson_status(lid, "completed")
    db.close()

    at, review_tab = _open_review_tab(monkeypatch, db_path)
    assert not any("Finished lesson" in e.label for e in review_tab.expander)
    assert any("Nothing waiting on you" in s.value for s in review_tab.success)

    # Rendered below all the tabs, not scoped to any one of them -- see
    # show_history in pages/10_Activity_Log.py.
    checkbox = [c for c in at.checkbox if c.label.startswith("Also show")][0]
    checkbox.set_value(True).run()

    assert any("Finished lesson" in e.label for e in at.expander)


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
    assert any("Lego Stop-Motion Film" in m for m in markdowns)
    captions = [c.value for c in backlog_tab.caption]
    assert any("Storyboard it" in c and "To Do" in c for c in captions)
    assert any("Film the last scene" in c and "Backlog" in c for c in captions)
    # The finished step isn't "left" -- it doesn't show up here at all.
    assert not any("Write the script" in c for c in captions)

    backlog_tab.button(key=f"backlog_tab_step_todo_{backlog_id}").click().run()

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
