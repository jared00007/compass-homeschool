"""The Slope & Intercept Explorer -- a client-side manipulative, so the testable
surface is the generated document (it carries all its own logic) and that the
page renders it without blowing up. The canvas math itself is exercised in a
real browser during development, not here."""

from __future__ import annotations

from pathlib import Path

import streamlit as st
from streamlit.testing.v1 import AppTest

from compass import config
from compass.storage.db import Database
from compass.ui import slope_intercept_explorer_html

REPO_ROOT = Path(__file__).resolve().parent.parent
HOME_PATH = str(REPO_ROOT / "Home.py")
EXPLORER_PATH = str(REPO_ROOT / "pages" / "10_Graph_Explorer.py")


def test_explorer_is_a_complete_self_contained_document():
    html = slope_intercept_explorer_html()
    assert html.lstrip().startswith("<!doctype html>")
    assert "<script>" in html and "</html>" in html.rstrip()[-10:]
    # It runs in the components iframe, which doesn't inherit the page theme, so
    # it must carry its own colors rather than rely on the app's CSS.
    assert "--paper:#FFFBF0" in html and "--line:#2F63E0" in html


def test_explorer_has_the_core_teaching_pieces():
    html = slope_intercept_explorer_html()
    # the two drivers
    assert 'id="m"' in html and 'id="b"' in html
    assert "How steep is it?" in html and "Where does it start?" in html
    # the three linked representations: line (canvas), equation, table
    assert "<canvas" in html and 'id="eq"' in html and "<table" in html
    # the big ideas it has to make land
    assert "unit rate" in html
    assert "Proportional" in html and "(0, 0)" in html  # the origin fingerprint
    assert "y-intercept" in html
    # the missions walk the ladder, ending in reading a graph backwards
    for mission_bit in ("slope = 3", "y-intercept = 5", "negative slope", "mystery line"):
        assert mission_bit in html, mission_bit


def test_explorer_page_renders(tmp_path, monkeypatch):
    st.cache_resource.clear()
    monkeypatch.setattr(config, "DEFAULT_DB_PATH", str(tmp_path / "g.db"))
    Database(tmp_path / "g.db").ensure_default_student()

    at = AppTest.from_file(HOME_PATH)
    at.session_state["parent_unlocked"] = True
    at.run(timeout=30)
    at.switch_page(EXPLORER_PATH)
    at.run(timeout=30)
    assert not at.exception, [e.message for e in at.exception]
    assert any("Slope & Intercept Explorer" in (t.value or "") for t in at.title)


def test_explorer_page_works_for_the_student_too(tmp_path, monkeypatch):
    """It's a practice tool Landon opens himself -- it must render in student
    view (a PIN forces student mode), not just the parent's."""
    from compass import auth

    st.cache_resource.clear()
    monkeypatch.setattr(config, "DEFAULT_DB_PATH", str(tmp_path / "g.db"))
    db = Database(tmp_path / "g.db")
    db.ensure_default_student()
    auth.set_pin(db, "1234")
    db.close()

    at = AppTest.from_file(HOME_PATH)
    at.run(timeout=30)
    at.switch_page(EXPLORER_PATH)
    at.run(timeout=30)
    assert not at.exception, [e.message for e in at.exception]


# --- the "find the gap" diagnostic --------------------------------------------

from compass.ui import DIAGNOSTIC, GRAPHING_LADDER  # noqa: E402
from compass.ui.grapher import _diagnostic_readout  # noqa: E402


def test_diagnostic_all_correct_reads_as_put_it_together():
    result = _diagnostic_readout([q["correct"] for q in DIAGNOSTIC])
    assert result["all_right"] and not result["shaky"]


def test_diagnostic_flags_the_shaky_rungs_in_teaching_order():
    # miss question 4 (slope) and question 2 (unit rate); the readout should name
    # both, lowest rung first.
    picks = [q["correct"] for q in DIAGNOSTIC]
    picks[1] = (DIAGNOSTIC[1]["correct"] + 1) % 4   # unit_rate wrong
    picks[3] = (DIAGNOSTIC[3]["correct"] + 1) % 4   # slope wrong
    result = _diagnostic_readout(picks)
    assert result["shaky"] == ["unit_rate", "slope"]   # teaching order
    assert "intercept" in result["got"] and "plotting" in result["got"]
    assert not result["all_right"]


# --- the scaffolded 6-lesson ladder -------------------------------------------


def test_graphing_ladder_is_six_rungs_ending_in_reading_backwards():
    assert len(GRAPHING_LADDER) == 6
    assert "Plot points" in GRAPHING_LADDER[0]["title"]
    assert "write the equation" in GRAPHING_LADDER[-1]["title"].lower() \
        or "write the equation" in GRAPHING_LADDER[-1]["focus"].lower()
    # every rung carries a real teaching focus
    assert all(d["focus"].strip() for d in GRAPHING_LADDER)


def test_ladder_builds_six_backlog_lessons(tmp_path):
    """The builder hands the fixed ladder to the Math agent's own series path, so
    six graded Math lessons land in the Backlog (held_back), in order."""
    from unittest.mock import patch

    from compass.agents import get_agent
    from compass.ui import context_for
    from compass.ui.grapher import _ladder_proposal

    db = Database(tmp_path / "ladder.db")
    student = db.ensure_default_student()

    def fake_lesson(**kw):
        return {
            "title": "Graphing day", "topic": "graphing", "overview": "x",
            "activities": [{"title": "a", "minutes": 20}, {"title": "b", "minutes": 20}],
            "quiz": [], "subject_credits": [{"subject": "math", "minutes": 40}],
        }

    with patch("compass.agents.framework.generate_lesson", side_effect=fake_lesson):
        agent = get_agent("math")
        ctx = context_for(db, student, minutes=45)
        results = agent.generate_series(ctx, _ladder_proposal(), plan=GRAPHING_LADDER)

    assert len(results) == 6
    lessons = db.list_lessons(student["id"], agent="math", limit=50)
    assert len(lessons) == 6
    assert all((l.get("metadata") or {}).get("held_back") for l in lessons)  # backlog
    assert sorted((l["metadata"]).get("series_index") for l in lessons) == [0, 1, 2, 3, 4, 5]
    db.close()


def test_parent_sees_the_ladder_builder_student_does_not(tmp_path, monkeypatch):
    from compass import auth

    monkeypatch.setattr(config, "DEFAULT_DB_PATH", str(tmp_path / "g.db"))

    def open_explorer(parent):
        st.cache_resource.clear()
        at = AppTest.from_file(HOME_PATH)
        if parent:
            at.session_state["parent_unlocked"] = True
        at.run(timeout=30)
        at.switch_page(EXPLORER_PATH)
        at.run(timeout=30)
        assert not at.exception, [e.message for e in at.exception]
        return "\n".join(m.value for m in at.markdown)

    db = Database(tmp_path / "g.db")
    db.ensure_default_student()
    auth.set_pin(db, "1234")  # a PIN forces student mode by default
    db.close()

    parent_md = open_explorer(parent=True)
    assert "graphing ladder" in parent_md and "Find the gap" in parent_md

    student_md = open_explorer(parent=False)
    assert "Find the gap" in student_md          # diagnostic is for him too
    assert "graphing ladder" not in student_md   # building/assigning work is not


# --- the redesigned Mystery Line Challenge + missions-as-cards -----------------


def test_mystery_challenge_is_a_hinted_two_step():
    html = slope_intercept_explorer_html()
    assert "Mystery Line Challenge" in html
    # the two explicit steps, with their own feedback slots
    assert 'id="step1"' in html and 'id="step2"' in html
    assert 'id="fb_start"' in html and 'id="fb_steep"' in html
    # a graduated hint (nudge -> method -> reveal) wired to a button
    assert 'id="hintbtn"' in html and "function showHint" in html
    assert "The answer:" in html  # the third hint reveals the equation
    # directional feedback, not just "keep trying"
    assert "make it STEEPER" in html and "slide" in html


def test_missions_card_builder_makes_a_trackable_board_card(tmp_path, monkeypatch):
    st.cache_resource.clear()
    monkeypatch.setattr(config, "DEFAULT_DB_PATH", str(tmp_path / "m.db"))
    Database(tmp_path / "m.db").ensure_default_student()

    at = AppTest.from_file(HOME_PATH)
    at.session_state["parent_unlocked"] = True
    at.run(timeout=30)
    at.switch_page(EXPLORER_PATH)
    at.run(timeout=30)
    add = [b for b in at.button if "graphing-missions card" in (b.label or "")]
    assert add, [b.label for b in at.button]
    add[0].click().run(timeout=30)
    assert not at.exception, [e.message for e in at.exception]

    db = Database(tmp_path / "m.db")
    student = db.ensure_default_student()
    cards = [l for l in db.list_lessons(student["id"], agent="khan", limit=20)
             if (l.get("metadata") or {}).get("general_card")]
    db.close()
    assert len(cards) == 1
    assert "Graphing missions" in cards[0]["title"]
    assert cards[0]["metadata"].get("xp_override") == 15   # logs a little XP when done


def test_missions_card_is_hidden_from_the_student(tmp_path, monkeypatch):
    from compass import auth

    st.cache_resource.clear()
    monkeypatch.setattr(config, "DEFAULT_DB_PATH", str(tmp_path / "m.db"))
    db = Database(tmp_path / "m.db")
    db.ensure_default_student()
    auth.set_pin(db, "1234")
    db.close()

    at = AppTest.from_file(HOME_PATH)
    at.run(timeout=30)
    at.switch_page(EXPLORER_PATH)
    at.run(timeout=30)
    assert not any("graphing-missions card" in (b.label or "") for b in at.button)
