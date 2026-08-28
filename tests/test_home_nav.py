"""Home's own nav: four big buttons (Today / This Week / Upcoming Week /
Grades) standing in for what used to be small `st.tabs()`, chosen because a
plain button row is the only way to put shared header content (greeting,
streak, fun fact) *between* the nav row and whichever view's body is showing
-- see Home.py's own comment on why `st.tabs()` can't do that.
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
    assert _nav_button(at, "This Week").proto.type == "secondary"
    assert _nav_button(at, "Upcoming Week").proto.type == "secondary"
    assert _nav_button(at, "Grades").proto.type == "secondary"
    text = " ".join(m.value for m in at.markdown)
    assert "Lessons (" in text


def test_clicking_a_second_view_after_a_first_does_not_leave_the_first_looking_pressed(
    monkeypatch, tmp_path
):
    """Regression: the four buttons render in one left-to-right pass, so a
    button rendered *before* the one just clicked used to still compute its
    own primary/secondary look from the stale session_state value -- one
    click behind. Clicking This Week, then Grades, used to leave This Week
    looking pressed instead of Grades."""
    at = _open_home(monkeypatch, _seed(tmp_path))

    _nav_button(at, "This Week").click().run()
    assert _nav_button(at, "This Week").proto.type == "primary"
    assert _nav_button(at, "Today").proto.type == "secondary"

    _nav_button(at, "Grades").click().run()
    assert _nav_button(at, "Grades").proto.type == "primary"
    assert _nav_button(at, "This Week").proto.type == "secondary"
    assert _nav_button(at, "Today").proto.type == "secondary"
    text = " ".join(c.value for c in at.caption)
    assert "Nothing here is based on how long you worked" in text


def test_upcoming_week_button_shows_the_upcoming_week_view(monkeypatch, tmp_path):
    at = _open_home(monkeypatch, _seed(tmp_path))
    _nav_button(at, "Upcoming Week").click().run()
    assert _nav_button(at, "Upcoming Week").proto.type == "primary"
    text = " ".join(c.value for c in at.caption)
    assert "next week's plan" in text


def test_switching_views_and_back_to_today_still_shows_the_roster(monkeypatch, tmp_path):
    at = _open_home(monkeypatch, _seed(tmp_path))
    _nav_button(at, "Grades").click().run()
    _nav_button(at, "Today").click().run()
    assert _nav_button(at, "Today").proto.type == "primary"
    text = " ".join(m.value for m in at.markdown)
    assert "Lessons (" in text
