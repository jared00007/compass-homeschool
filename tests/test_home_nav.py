"""Home's own nav: three big buttons (Today / Board / Grades) standing in for
what used to be small `st.tabs()`, chosen because a plain button row is the
only way to put shared header content (greeting, streak, fun fact) *between*
the nav row and whichever view's body is showing -- see Home.py's own comment
on why `st.tabs()` can't do that. The old This Week + Upcoming Week views are
now one Board with its own This-week / Next-week toggle, matching the parent.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st
from streamlit.testing.v1 import AppTest

from compass import auth, config
from compass.storage.db import Database

REPO_ROOT = Path(__file__).resolve().parent.parent
HOME_PATH = str(REPO_ROOT / "Home.py")


def _open_home(monkeypatch, db_path):
    st.cache_resource.clear()
    monkeypatch.setattr(config, "DEFAULT_DB_PATH", db_path)
    at = AppTest.from_file(HOME_PATH)
    at.run(timeout=30)
    assert not at.exception, [e.message for e in at.exception]
    return at


def _seed(tmp_path):
    db_path = tmp_path / "nav.db"
    db = Database(db_path)
    db.ensure_default_student()
    auth.set_pin(db, "1234")
    db.close()
    return db_path


def _nav_button(at, label_substring):
    return [b for b in at.button if label_substring in (b.label or "")][0]


def test_today_is_the_default_view(monkeypatch, tmp_path):
    at = _open_home(monkeypatch, _seed(tmp_path))
    assert _nav_button(at, "Today").proto.type == "primary"
    assert _nav_button(at, "Board").proto.type == "secondary"
    assert _nav_button(at, "Grades").proto.type == "secondary"
    text = " ".join(m.value for m in at.markdown)
    assert "Lessons (" in text


def test_clicking_a_second_view_after_a_first_does_not_leave_the_first_looking_pressed(
    monkeypatch, tmp_path
):
    """Regression: the buttons render in one left-to-right pass, so a button
    rendered *before* the one just clicked used to still compute its own
    primary/secondary look from the stale session_state value -- one click
    behind. Clicking Board, then Grades, used to leave Board looking pressed
    instead of Grades."""
    at = _open_home(monkeypatch, _seed(tmp_path))

    _nav_button(at, "Board").click().run()
    assert _nav_button(at, "Board").proto.type == "primary"
    assert _nav_button(at, "Today").proto.type == "secondary"

    _nav_button(at, "Grades").click().run()
    assert _nav_button(at, "Grades").proto.type == "primary"
    assert _nav_button(at, "Board").proto.type == "secondary"
    assert _nav_button(at, "Today").proto.type == "secondary"
    text = " ".join(c.value for c in at.caption)
    assert "Nothing here is based on how long you worked" in text


def test_board_pages_forward_several_weeks(monkeypatch, tmp_path):
    """The old This Week + Upcoming Week nav buttons are now one Board view
    with a forward week-pager (◀ Earlier / This week / Later ▶) -- so he can
    look not just at next week but several weeks out, matching the fact that
    a parent can plan that far ahead now."""
    at = _open_home(monkeypatch, _seed(tmp_path))
    _nav_button(at, "Board").click().run()
    assert _nav_button(at, "Board").proto.type == "primary"

    # Defaults to this week; "Earlier" is disabled at the near edge.
    prev_button = [b for b in at.button if b.key == "student_board_prev"][0]
    assert prev_button.disabled is True

    later = [b for b in at.button if b.key == "student_board_next"][0]
    later.click().run()
    text = " ".join(c.value for c in at.caption)
    assert "next week" in text

    later = [b for b in at.button if b.key == "student_board_next"][0]
    later.click().run()
    text = " ".join(c.value for c in at.caption)
    assert "2 weeks out" in text

    # And "This week" jumps straight back to the near edge.
    this_button = [b for b in at.button if b.key == "student_board_this"][0]
    this_button.click().run()
    prev_button = [b for b in at.button if b.key == "student_board_prev"][0]
    assert prev_button.disabled is True


def test_the_student_board_is_read_only_no_move_controls(monkeypatch, tmp_path):
    """render_board_days(interactive=False): a student's own Board must never
    offer the parent-only reschedule/backlog move control -- planning is a
    parent's to do, he just sees what's set."""
    db_path = tmp_path / "nav.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    auth.set_pin(db, "1234")
    from compass import weekly

    monday = weekly.week_start()
    db.save_lesson(
        student_id=student["id"], agent="math", subject="math", topic="t",
        title="On the Board This Week",
        payload={"title": "On the Board This Week", "activities": []},
        metadata={"planned_for": monday.isoformat(), "week_start": monday.isoformat()},
    )
    db.close()

    at = _open_home(monkeypatch, db_path)
    _nav_button(at, "Board").click().run()
    assert not at.exception, [e.message for e in at.exception]
    move_keys = [
        b.key for b in at.button
        if b.key and (b.key.startswith("move_board_") or b.key.startswith("board_view_lesson_"))
    ]
    # No move control at all; the View-full-lesson dialog stays available.
    assert not any(k.startswith("move_board_") for k in move_keys)


def test_switching_views_and_back_to_today_still_shows_the_roster(monkeypatch, tmp_path):
    at = _open_home(monkeypatch, _seed(tmp_path))
    _nav_button(at, "Grades").click().run()
    _nav_button(at, "Today").click().run()
    assert _nav_button(at, "Today").proto.type == "primary"
    text = " ".join(m.value for m in at.markdown)
    assert "Lessons (" in text
