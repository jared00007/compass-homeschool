"""Every page loads without crashing, in both parent and student view.

A lightweight net for a whole class of bug the rest of the suite can't
see: something that only breaks when the actual Streamlit script executes
top to bottom -- an IndexError in page-level code, a KeyError from a
missing dict field, a StreamlitDuplicateElementKey from two tab bodies
that both run on every load (Streamlit runs every tab's body on every
rerun, hidden tabs included, not just the visible one).

This is exactly the shape of bug that shipped and was only caught by hand
during live Playwright verification: This Week's "Plan next week" tab
indexed target_dates[4] for Friday's date, but that list only ever holds
four dates (Monday-Thursday) -- an IndexError on every single load,
parent or student, regardless of which tab happened to be visible.
Reintroducing that exact line during development made this suite fail
with the same traceback a browser would have shown; this suite exists so
the next one like it fails a test run instead of surfacing live.

Deliberately not testing button clicks (Generate lesson, Plan this week,
etc.) -- those call the live Anthropic API, which this suite has no key
for and shouldn't be spending money on. Loading each page's default view
already exercises every tab's body (see above), which is where this kind
of bug actually lives.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from compass import auth, config
from compass.storage.db import Database

REPO_ROOT = Path(__file__).resolve().parent.parent
PAGES_DIR = REPO_ROOT / "pages"
HOME_PATH = str(REPO_ROOT / "Home.py")
# AppTest.from_file/switch_page resolve a relative path against the file
# that *calls* them (this test file's own directory), not the repo root --
# absolute paths sidestep that entirely.
PAGE_PATHS = [str(p) for p in sorted(PAGES_DIR.glob("*.py"))]


def _seed(db_path: Path, *, with_pin: bool) -> None:
    """A little data in every table a page might read -- an empty list
    rarely exercises the same code paths (a progress bar, a status badge,
    a "next up" computation) that a populated one does."""
    db = Database(db_path)
    student = db.ensure_default_student()
    sid = student["id"]
    db.add_interest(sid, "Legos")
    db.set_mastery(sid, "two-step-equations", "mastered", score=100.0)
    db.add_web_node(sid, "science", "Volcanoes")
    book_id = db.add_book(sid, "Hatchet", author="Gary Paulsen")
    db.add_vocabulary(sid, "resilient", "able to recover quickly", book_id)
    db.save_lesson(
        student_id=sid, agent="math", subject="math", topic="t", title="t",
        payload={"title": "t", "activities": []},
    )
    db.log_activity(
        student_id=sid, title="Math practice", tier="core", primary_subject="math",
        minutes=45, subject_credits={"math": 45},
    )
    db.add_travel_entry(sid, "WA", "2026-06-01", title="Olympic NP")
    db.save_journal_entry(sid, "2026-06-01", "happy", "good day")
    db.log_morning_routine(sid, "2026-06-01", "box_breathing")
    db.create_course(sid, "Pre-Algebra", "math", "2025-09-01", "2026-06-01")
    project_id = db.add_big_project(sid, "Stop-motion film", "a film")
    db.add_project_step(project_id, "Write the script")
    db.set_active_big_project(project_id)
    db.add_choice_topic(sid, "3D printing")
    db.add_life_skill(sid, "Do laundry")
    db.add_friday_plan_item(sid, "2026-08-28", "custom", "Guitar practice")
    if with_pin:
        auth.set_pin(db, "1234")
    db.close()


def _load(page_path: str, *, as_parent: bool) -> AppTest:
    at = AppTest.from_file(HOME_PATH)
    if as_parent:
        at.session_state["parent_unlocked"] = True
    at.run(timeout=30)
    if page_path != HOME_PATH:
        at.switch_page(page_path)
        at.run(timeout=30)
    return at


@pytest.mark.parametrize("page_path", [HOME_PATH] + PAGE_PATHS)
def test_page_loads_as_parent(monkeypatch, tmp_path, page_path):
    db_path = tmp_path / "smoke.db"
    _seed(db_path, with_pin=False)
    # Patching the env var alone isn't enough: config.DEFAULT_DB_PATH is a
    # module-level constant read from the environment once, the first time
    # compass.config is imported anywhere in the pytest process -- by the
    # time this test runs, that's long since happened. Patching the
    # attribute itself is what Database() actually consults on every call.
    monkeypatch.setattr(config, "DEFAULT_DB_PATH", db_path)

    at = _load(page_path, as_parent=True)

    assert not at.exception, [e.message for e in at.exception]


@pytest.mark.parametrize("page_path", [HOME_PATH] + PAGE_PATHS)
def test_page_loads_as_student(monkeypatch, tmp_path, page_path):
    db_path = tmp_path / "smoke.db"
    _seed(db_path, with_pin=True)  # a PIN is what makes is_parent() default False
    monkeypatch.setattr(config, "DEFAULT_DB_PATH", db_path)

    at = _load(page_path, as_parent=False)

    assert not at.exception, [e.message for e in at.exception]


def test_every_page_file_is_covered():
    """Guards against a new page file being added to pages/ without this
    suite noticing -- PAGE_PATHS is computed once at import time, so a
    page added after that would otherwise just never run here."""
    on_disk = {p.name for p in PAGES_DIR.glob("*.py")}
    covered = {Path(p).name for p in PAGE_PATHS}
    assert on_disk == covered


def test_home_actually_renders_the_skipped_planning_nudge(monkeypatch, tmp_path):
    """Not a crash check like the rest of this file -- weekly.planning_nudge
    itself is unit-tested in test_weekly.py against an injected `today`, but
    nothing there confirms Home.py actually calls it (with no `today`
    override, so it falls back to date.today()) and renders the result.
    Pins "today" to a fixed Sunday by patching weekly's own `date` rather
    than relying on whatever real day the test happens to run on."""
    from datetime import date as real_date

    from compass import weekly

    class _FixedToday(real_date):
        @classmethod
        def today(cls):
            return real_date(2026, 8, 23)  # a Sunday

    monkeypatch.setattr(weekly, "date", _FixedToday)

    db_path = tmp_path / "smoke.db"
    _seed(db_path, with_pin=False)
    monkeypatch.setattr(config, "DEFAULT_DB_PATH", db_path)

    at = _load(HOME_PATH, as_parent=True)

    assert not at.exception
    assert any("hasn't been planned yet" in i.value for i in at.info)


@pytest.mark.parametrize("as_parent", [True, False])
def test_home_no_longer_shows_the_days_until_school_countdown(monkeypatch, tmp_path, as_parent):
    """Removed on request -- "364 days until 1st day of school" read as
    pointless noise on Home, not useful information, in both views."""
    db_path = tmp_path / "smoke.db"
    _seed(db_path, with_pin=not as_parent)
    monkeypatch.setattr(config, "DEFAULT_DB_PATH", db_path)

    at = _load(HOME_PATH, as_parent=as_parent)

    assert not at.exception
    text = " ".join(c.value for c in at.caption)
    assert "until the first day of school" not in text
    assert "first day of school" not in text
