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


def test_overdue_and_needs_logging_surface_regardless_of_day(monkeypatch, tmp_path):
    db_path = tmp_path / "review.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    sid = student["id"]
    today = date.today()
    week_start = today - timedelta(days=today.weekday())

    db.save_lesson(
        student_id=sid, agent="math", subject="math", topic="t", title="Overdue lesson",
        payload={"title": "Overdue lesson", "activities": []},
        metadata={
            "planned_for": (week_start - timedelta(days=7)).isoformat(),
            "week_start": (week_start - timedelta(days=14)).isoformat(),
        },
    )
    lid = db.save_lesson(
        student_id=sid, agent="science", subject="science", topic="t", title="Turned in",
        payload={"title": "Turned in", "activities": []},
        metadata={"planned_for": today.isoformat(), "week_start": week_start.isoformat()},
    )
    db.submit_lesson(lid)
    db.close()

    at, review_tab = _open_review_tab(monkeypatch, db_path)

    markdowns = [m.value for m in review_tab.markdown]
    assert any("Needs your attention now" in m and "(2)" in m for m in markdowns)
    labels = [e.label for e in review_tab.expander]
    assert any("overdue" in l and "Overdue lesson" in l for l in labels)
    assert any("waiting on you to review" in l and "Turned in" in l for l in labels)


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

    checkbox = [c for c in review_tab.checkbox if c.label.startswith("Also show")][0]
    checkbox.set_value(True).run()
    review_tab = [t for t in at.tabs if t.label.startswith("To review")][0]

    assert any("Finished lesson" in e.label for e in review_tab.expander)
