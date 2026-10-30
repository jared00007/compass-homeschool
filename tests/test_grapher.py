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
