"""Choice Topics' active/backlog gate -- the same flow lessons, Big Project
steps, and Life Skills all already have. A topic can be parked out of
Landon's own view regardless of its approval status, and a parent moves it
back and forth freely.

Choice Topics used to be its own top-level page; it's now a "Student's
Choice" tab on pages/6_Life_Skills.py (see compass.ui.render_choice_topics_section)
-- these tests moved with it. The underlying choice_topics table and its
own status flow are untouched by that move.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st
from streamlit.testing.v1 import AppTest

from compass import auth, config
from compass.storage.db import Database

REPO_ROOT = Path(__file__).resolve().parent.parent
HOME_PATH = str(REPO_ROOT / "Home.py")
LIFE_SKILLS_PATH = str(REPO_ROOT / "pages" / "6_Life_Skills.py")


def _open(monkeypatch, db_path, *, as_parent=True):
    st.cache_resource.clear()
    monkeypatch.setattr(config, "DEFAULT_DB_PATH", db_path)
    at = AppTest.from_file(HOME_PATH)
    if as_parent:
        at.session_state["parent_unlocked"] = True
    at.run(timeout=30)
    at.switch_page(LIFE_SKILLS_PATH)
    at.run(timeout=30)
    assert not at.exception, [e.message for e in at.exception]
    return at


def test_a_backlogged_topic_is_hidden_from_the_student_view(monkeypatch, tmp_path):
    db_path = tmp_path / "topics.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    auth.set_pin(db, "1234")  # is_parent() defaults True with no PIN set at all
    db.add_choice_topic(student["id"], "Learn guitar chords", active=False)
    db.close()

    at = _open(monkeypatch, db_path, as_parent=False)

    markdowns = [m.value for m in at.markdown]
    assert not any("Learn guitar chords" in m for m in markdowns)


def test_an_active_topic_shows_in_the_students_list(monkeypatch, tmp_path):
    db_path = tmp_path / "topics.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    auth.set_pin(db, "1234")
    db.add_choice_topic(student["id"], "Learn guitar chords")  # active by default
    db.close()

    at = _open(monkeypatch, db_path, as_parent=False)

    markdowns = [m.value for m in at.markdown]
    assert any("Learn guitar chords" in m for m in markdowns)


def test_a_declined_topic_stays_visible_even_if_backlogged(monkeypatch, tmp_path):
    """Done/declined topics are exempt from the visibility filter -- a
    closed-out topic never disappears just because it's parked."""
    db_path = tmp_path / "topics.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    auth.set_pin(db, "1234")
    topic_id = db.add_choice_topic(student["id"], "Learn guitar chords")
    db.set_choice_status(topic_id, "declined")
    db.set_choice_topic_active(topic_id, False)
    db.close()

    at = _open(monkeypatch, db_path, as_parent=False)

    markdowns = [m.value for m in at.markdown]
    assert any("Learn guitar chords" in m for m in markdowns)


def test_backlog_button_moves_a_topic_out_of_the_students_view(monkeypatch, tmp_path):
    db_path = tmp_path / "topics.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    topic_id = db.add_choice_topic(student["id"], "Learn guitar chords")
    db.close()

    at = _open(monkeypatch, db_path)
    markdowns = [m.value for m in at.markdown]
    assert any("Learn guitar chords" in m and "backlogged" not in m for m in markdowns)

    at.button(key=f"backlog_topic_{topic_id}").click().run()

    markdowns = [m.value for m in at.markdown]
    assert any("Learn guitar chords" in m and "backlogged" in m for m in markdowns)


def test_unbacklog_button_restores_a_topic(monkeypatch, tmp_path):
    db_path = tmp_path / "topics.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    topic_id = db.add_choice_topic(student["id"], "Learn guitar chords", active=False)
    db.close()

    at = _open(monkeypatch, db_path)
    at.button(key=f"unbacklog_topic_{topic_id}").click().run()

    markdowns = [m.value for m in at.markdown]
    assert any("Learn guitar chords" in m and "backlogged" not in m for m in markdowns)


def test_backlog_toggle_is_not_offered_on_a_done_topic(monkeypatch, tmp_path):
    db_path = tmp_path / "topics.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    topic_id = db.add_choice_topic(student["id"], "Learn guitar chords")
    db.set_choice_status(topic_id, "approved")
    db.set_choice_status(topic_id, "active")
    db.set_choice_status(topic_id, "done")
    db.close()

    at = _open(monkeypatch, db_path)

    keys = {b.key for b in at.button}
    assert f"backlog_topic_{topic_id}" not in keys
    assert f"unbacklog_topic_{topic_id}" not in keys


def test_choice_topics_no_longer_has_its_own_page(monkeypatch, tmp_path):
    assert not (REPO_ROOT / "pages" / "5_Choice_Topics.py").exists()


def test_choice_topics_link_is_hidden_from_the_sidebar_for_a_parent_too(monkeypatch, tmp_path):
    db_path = tmp_path / "topics.db"
    db = Database(db_path)
    db.ensure_default_student()
    db.close()

    at = _open(monkeypatch, db_path, as_parent=True)

    markdowns = [m.value for m in at.markdown]
    assert any('Choice_Topics' in m and "display: none" in m for m in markdowns)
