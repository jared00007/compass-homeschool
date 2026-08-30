"""The "Chunk this project into steps with AI" button on pages/7_Big_Projects.py.

Deliberately not testing the click itself here -- same reasoning
test_page_smoke.py states for every other AI-generation button in this
app: it calls the live Anthropic API, which this suite has no business
spending money on per test run. `tests/test_project_chunker.py` covers
the actual generation logic with the API call mocked out; this file only
covers the button's own visibility and disabled-state wiring, which
doesn't touch the network at all.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import streamlit as st
from streamlit.testing.v1 import AppTest

from compass import config
from compass.storage.db import Database

REPO_ROOT = Path(__file__).resolve().parent.parent
HOME_PATH = str(REPO_ROOT / "Home.py")
BIG_PROJECTS_PATH = str(REPO_ROOT / "pages" / "7_Big_Projects.py")


def _open_checklist_tab(monkeypatch, db_path):
    st.cache_resource.clear()
    monkeypatch.setattr(config, "DEFAULT_DB_PATH", db_path)
    at = AppTest.from_file(HOME_PATH)
    at.session_state["parent_unlocked"] = True
    at.run(timeout=30)
    at.switch_page(BIG_PROJECTS_PATH)
    at.run(timeout=30)
    assert not at.exception, [e.message for e in at.exception]
    return at


def test_chunk_button_shows_only_for_a_stepless_project(monkeypatch, tmp_path):
    db_path = tmp_path / "projects.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    stepless_id = db.add_big_project(student["id"], "Backyard Weather Station", "Track real weather.")
    started_id = db.add_big_project(student["id"], "Stop-Motion Film", "A short film.")
    db.add_project_step(started_id, "Write the script")
    db.close()

    at = _open_checklist_tab(monkeypatch, db_path)

    keys = {b.key for b in at.button}
    assert f"chunk_project_{stepless_id}" in keys
    assert f"chunk_project_{started_id}" not in keys


def test_chunk_button_is_disabled_when_the_api_is_unavailable(monkeypatch, tmp_path):
    db_path = tmp_path / "projects.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    project_id = db.add_big_project(student["id"], "Backyard Weather Station", "Track real weather.")
    db.close()

    with patch("compass.agents.api_available", return_value=(False, "No API key configured.")):
        at = _open_checklist_tab(monkeypatch, db_path)

    button = at.button(key=f"chunk_project_{project_id}")
    assert button.disabled
