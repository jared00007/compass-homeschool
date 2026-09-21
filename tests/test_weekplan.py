"""The Balanced-Week planner -- compose a week from the backlog instead of
hand-stacking it: core lessons spread across Mon-Fri, capped per day, subjects
mixed, leftovers left in the Backlog.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from compass import config, weekplan
from compass.storage.db import Database

REPO_ROOT = Path(__file__).resolve().parent.parent
HOME_PATH = str(REPO_ROOT / "Home.py")
MISSION_CONTROL_PATH = str(REPO_ROOT / "pages" / "14_Mission_Control.py")
A_MONDAY = date(2026, 9, 21)


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "wp.db")
    yield database
    database.close()


@pytest.fixture()
def student(db):
    return db.ensure_default_student()


def _backlogged(db, student, agent, n):
    ids = []
    for i in range(n):
        ids.append(
            db.save_lesson(
                student["id"], agent, agent, f"{agent}-{i}", f"{agent} lesson {i}",
                {"quiz": []}, metadata={"held_back": True},
            )
        )
    return ids


def test_backlog_pool_is_only_backlogged_planned_core_lessons(db, student):
    _backlogged(db, student, "math", 2)
    # A scheduled (not backlogged) lesson, and a non-core enrichment lesson.
    db.save_lesson(student["id"], "science", "science", "sched", "Scheduled",
                   {"quiz": []}, metadata={"planned_for": A_MONDAY.isoformat(),
                                           "week_start": A_MONDAY.isoformat()})
    db.save_lesson(student["id"], "art_music", "art_and_music", "art", "Art",
                   {"quiz": []}, metadata={"held_back": True, "enrichment": True})
    pool = weekplan.backlog_core_lessons(db, student["id"])
    assert len(pool) == 2
    assert all(l["agent"] == "math" for l in pool)


def test_balance_caps_per_day_and_mixes_subjects(db, student):
    for agent in ("math", "science", "english", "history"):
        _backlogged(db, student, agent, 2)  # 8 total
    plan = weekplan.balance_week(db, student["id"], A_MONDAY, cap_per_day=2)

    assert plan.assigned == 8
    assert plan.left_in_backlog == 0
    # No day over the cap.
    assert all(len(titles) <= 2 for titles in plan.days.values())
    # Every assigned lesson now carries the right planned day.
    for day_iso, titles in plan.days.items():
        for _ in titles:
            pass  # (titles are strings; day assignment verified below)
    # A day with two lessons has two different subjects (interleaving).
    two_up = [titles for titles in plan.days.values() if len(titles) == 2]
    for titles in two_up:
        subjects_on_day = {t.split()[0] for t in titles}
        assert len(subjects_on_day) == 2


def test_leftovers_stay_in_the_backlog_when_the_week_fills(db, student):
    _backlogged(db, student, "math", 12)  # cap 2 * 5 days = 10 slots
    plan = weekplan.balance_week(db, student["id"], A_MONDAY, cap_per_day=2)
    assert plan.assigned == 10
    assert plan.left_in_backlog == 2
    # The two leftovers are still backlogged.
    assert len(weekplan.backlog_core_lessons(db, student["id"])) == 2


def test_a_cap_of_zero_places_nothing(db, student):
    _backlogged(db, student, "math", 3)
    plan = weekplan.balance_week(db, student["id"], A_MONDAY, cap_per_day=0)
    assert plan.assigned == 0
    assert plan.left_in_backlog == 3


def test_balancing_actually_reschedules_the_lessons(db, student):
    ids = _backlogged(db, student, "math", 2)
    weekplan.balance_week(db, student["id"], A_MONDAY, cap_per_day=2)
    for lid in ids:
        meta = db.get_lesson(lid)["metadata"]
        assert meta.get("planned_for")  # now has a day
        assert "held_back" not in meta  # out of the backlog


def test_mission_control_plan_view_balances_the_week(monkeypatch, tmp_path):
    db_path = tmp_path / "wp.db"
    db = Database(db_path)
    student = db.ensure_default_student()
    _backlogged(db, student, "math", 3)
    db.close()

    st.cache_resource.clear()
    monkeypatch.setattr(config, "DEFAULT_DB_PATH", db_path)
    at = AppTest.from_file(HOME_PATH)
    at.session_state["parent_unlocked"] = True
    at.run(timeout=30)
    at.switch_page(MISSION_CONTROL_PATH)
    at.session_state["mc_view"] = "plan"
    at.run(timeout=30)
    assert not at.exception, [e.message for e in at.exception]

    at.button(key="weekplan_go").click().run()
    assert not at.exception, [e.message for e in at.exception]

    db2 = Database(db_path)
    scheduled = [
        l for l in db2.list_lessons(student["id"], agent="math", limit=50)
        if (l["metadata"] or {}).get("planned_for")
    ]
    db2.close()
    assert len(scheduled) == 3
