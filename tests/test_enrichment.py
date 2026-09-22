"""Light enrichment tracks -- Art & Music and Movement / PE / Health.

A quick, AI-generated activity he just does; when he taps 'I did it,' it logs
time to the WA subject it covers and counts as a day's enrichment block.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

import compass.ui as ui
from compass import auth, config, pacing
from compass.agents import enrichment
from compass.storage.db import Database


class _Rec:
    """A minimal `st` stand-in that records the strings it would render."""

    session_state: dict = {}

    def __init__(self, written):
        self._written = written

    def __getattr__(self, _name):
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
        return False

REPO_ROOT = Path(__file__).resolve().parent.parent
HOME_PATH = str(REPO_ROOT / "Home.py")
MISSION_CONTROL_PATH = str(REPO_ROOT / "pages" / "14_Mission_Control.py")


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "enrich.db")
    yield database
    database.close()


@pytest.fixture()
def student(db):
    return db.ensure_default_student()


def an_activity_payload(**overrides):
    payload = {
        "title": "3-panel comic",
        "overview": "Draw a quick comic strip.",
        "what_to_do": "Fold a page into three, draw a joke across the panels.",
        "materials": ["paper", "pencil"],
        "estimated_minutes": 30,
        "_usage": {"input_tokens": 2, "output_tokens": 3, "model": "claude-opus-5"},
    }
    payload.update(overrides)
    return payload


def _generate(db, student, track, payload=None):
    with patch("compass.agents.enrichment.generate_lesson", return_value=payload or an_activity_payload()):
        return enrichment.generate_activity(db, student, track)


def test_generate_activity_persists_and_is_costed(db, student):
    for track in ("art_music", "movement"):
        lesson_id = _generate(db, student, track)
        activity = db.get_lesson(lesson_id)
        assert activity["agent"] == track
        assert activity["subject"] == config.ENRICHMENT_TRACKS[track]["subject"]
        assert activity["metadata"]["enrichment"] is True

    start, end = db.school_year_bounds()
    costed = {u["agent"] for u in db.lesson_usage_between(student["id"], start, end)}
    assert {"art_music", "movement"} <= costed


def test_unknown_track_raises(db, student):
    with pytest.raises(ValueError):
        enrichment.generate_activity(db, student, "underwater_basket_weaving")


def test_completing_credits_the_subject_and_counts_as_enrichment(db, student):
    today = date.today().isoformat()
    art = _generate(db, student, "art_music")
    assert db.enrichment_done_on(student["id"], today) == 0  # not done yet

    db.complete_enrichment_activity(art, student["id"])
    assert db.get_lesson(art)["status"] == "completed"
    assert db.enrichment_done_on(student["id"], today) == 1

    acts = [a for a in db.list_activities(student["id"]) if a["source"] == "art_music"]
    assert len(acts) == 1 and acts[0]["minutes"] == 30
    cur = db.conn.execute(
        "SELECT subject, SUM(minutes) m FROM activity_subject_credits GROUP BY subject"
    )
    assert dict((r["subject"], r["m"]) for r in cur.fetchall()) == {"art_and_music": 30}

    # Re-completing never stacks a second block of hours.
    db.complete_enrichment_activity(art, student["id"])
    acts = [a for a in db.list_activities(student["id"]) if a["source"] == "art_music"]
    assert len(acts) == 1


def test_an_enrichment_block_helps_make_a_full_day(db, student):
    today = date.today().isoformat()
    pacing.set_day_target(db, 0, 1)  # a full day here is just one enrichment block
    assert pacing.day_plan(db, student["id"], today).is_full_day is False
    art = _generate(db, student, "art_music")
    db.complete_enrichment_activity(art, student["id"])
    assert pacing.day_plan(db, student["id"], today).is_full_day is True


def test_future_scheduled_enrichment_waits_and_does_not_pile_on_today(db, student, monkeypatch):
    """Reported: art/music + movement generated and scheduled for other days all
    sat on his Today page. Home now day-filters them like the lesson roster -- a
    future one waits for its day, a today one still shows."""
    today = date.today()
    today_iso = today.isoformat()
    tomorrow_iso = (today + timedelta(days=1)).isoformat()

    a_today = _generate(db, student, "art_music", an_activity_payload(title="Today art"))
    a_future = _generate(db, student, "movement", an_activity_payload(title="Future move"))
    db.reschedule_lesson(a_today, today_iso)
    db.reschedule_lesson(a_future, tomorrow_iso)

    written: list[str] = []
    monkeypatch.setattr(ui, "st", _Rec(written))
    ui.render_enrichment_activities(db, student, today_iso)
    page = "\n".join(written)

    assert "Today art" in page
    assert "Future move" not in page


def _open(monkeypatch, db_path, page_path, *, as_parent):
    st.cache_resource.clear()
    monkeypatch.setattr(config, "DEFAULT_DB_PATH", db_path)
    at = AppTest.from_file(HOME_PATH)
    if as_parent:
        at.session_state["parent_unlocked"] = True
    at.run(timeout=30)
    if page_path != HOME_PATH:
        at.switch_page(page_path)
        at.run(timeout=30)
    assert not at.exception, [e.message for e in at.exception]
    return at


def test_home_shows_and_completes_an_enrichment_activity(monkeypatch, tmp_path):
    db_path = tmp_path / "enrich.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    auth.set_pin(db, "1234")
    db.set_setting("first_day_celebrated_start", db.school_year_bounds()[0])
    lesson_id = _generate(db, student, "movement")
    db.close()

    at = _open(monkeypatch, db_path, HOME_PATH, as_parent=False)
    body = " ".join(m.value for m in at.markdown)
    assert "comic" in body.lower() or "Movement" in body

    at.button(key=f"enrich_done_{lesson_id}").click().run()
    assert not at.exception, [e.message for e in at.exception]

    db2 = Database(db_path)
    assert db2.get_lesson(lesson_id)["status"] == "completed"
    assert db2.enrichment_done_on(student["id"], date.today().isoformat()) == 1
    db2.close()


def test_mission_control_generates_an_enrichment_activity(monkeypatch, tmp_path):
    db_path = tmp_path / "enrich.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    db.close()

    monkeypatch.setattr("compass.agents.api_available", lambda: (True, "Ready."))
    at = _open(monkeypatch, db_path, MISSION_CONTROL_PATH, as_parent=True)
    with patch("compass.agents.enrichment.generate_lesson", return_value=an_activity_payload()):
        at.button(key="gen_enrich_art_music").click().run()
    assert not at.exception, [e.message for e in at.exception]

    db2 = Database(db_path)
    assert len(db2.list_enrichment_activities(student["id"], "art_music")) == 1
    db2.close()
