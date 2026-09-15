"""Parent-added lesson resources: a parent attaches their own links/notes to a
lesson (a video they found, an article), and he sees them in that lesson.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from compass import auth, config
from compass.storage.db import Database

REPO_ROOT = Path(__file__).resolve().parent.parent
HOME_PATH = str(REPO_ROOT / "Home.py")
ENGLISH_PATH = str(REPO_ROOT / "pages" / "3_English.py")
MISSION_CONTROL_PATH = str(REPO_ROOT / "pages" / "14_Mission_Control.py")


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "res.db")
    yield database
    database.close()


@pytest.fixture()
def student(db):
    return db.ensure_default_student()


def _lesson(db, student_id):
    return db.save_lesson(
        student_id=student_id, agent="english", subject="english", topic="t",
        title="Essay", payload={"title": "Essay", "activities": []},
    )


# --- storage ----------------------------------------------------------------------


def test_a_resource_is_stored_on_the_lesson(db, student):
    lid = _lesson(db, student["id"])
    db.add_lesson_resource(lid, "Crash Course: Commas", "https://youtu.be/abc", "watch first")
    resources = db.get_lesson(lid)["metadata"]["parent_resources"]
    assert resources == [
        {"label": "Crash Course: Commas", "url": "https://youtu.be/abc",
         "note": "watch first", "minutes": config.RESOURCE_DEFAULT_MINUTES}
    ]


def test_a_note_only_resource_needs_no_link(db, student):
    lid = _lesson(db, student["id"])
    db.add_lesson_resource(lid, "Ask Grandpa about 1969", note="he was there")
    stored = db.get_lesson(lid)["metadata"]["parent_resources"][0]
    assert stored["label"] == "Ask Grandpa about 1969"
    assert stored["url"] == ""
    assert stored["note"] == "he was there"


def test_an_empty_resource_is_ignored(db, student):
    lid = _lesson(db, student["id"])
    db.add_lesson_resource(lid, "  ", "  ", "  ")
    assert "parent_resources" not in db.get_lesson(lid)["metadata"]


def test_a_resource_can_be_removed(db, student):
    lid = _lesson(db, student["id"])
    db.add_lesson_resource(lid, "One", "https://a.com")
    db.add_lesson_resource(lid, "Two", "https://b.com")
    db.remove_lesson_resource(lid, 0)
    remaining = db.get_lesson(lid)["metadata"]["parent_resources"]
    assert [r["label"] for r in remaining] == ["Two"]


def test_marking_a_resource_watched_logs_its_time(db, student):
    lid = _lesson(db, student["id"])
    db.add_lesson_resource(lid, "Crash Course", "https://youtu.be/abc", minutes=25)
    db.complete_lesson_resource(lid, 0, student["id"])

    resource = db.get_lesson(lid)["metadata"]["parent_resources"][0]
    assert resource.get("completed_on")
    acts = db.conn.execute(
        "SELECT minutes FROM activities WHERE student_id=? AND source='resource'",
        (student["id"],),
    ).fetchall()
    assert len(acts) == 1 and acts[0]["minutes"] == 25

    # A second tap doesn't double-log.
    db.complete_lesson_resource(lid, 0, student["id"])
    acts = db.conn.execute(
        "SELECT COUNT(*) c FROM activities WHERE source='resource'"
    ).fetchone()
    assert acts["c"] == 1


def test_un_watching_a_resource_takes_the_time_back(db, student):
    lid = _lesson(db, student["id"])
    db.add_lesson_resource(lid, "Doc", "https://x.com", minutes=30)
    db.complete_lesson_resource(lid, 0, student["id"])
    db.uncomplete_lesson_resource(lid, 0)

    resource = db.get_lesson(lid)["metadata"]["parent_resources"][0]
    assert not resource.get("completed_on")
    remaining = db.conn.execute(
        "SELECT COUNT(*) c FROM activities WHERE source='resource'"
    ).fetchone()["c"]
    assert remaining == 0


def test_removing_a_watched_resource_also_removes_its_time(db, student):
    lid = _lesson(db, student["id"])
    db.add_lesson_resource(lid, "Doc", "https://x.com", minutes=30)
    db.complete_lesson_resource(lid, 0, student["id"])
    db.remove_lesson_resource(lid, 0)
    remaining = db.conn.execute(
        "SELECT COUNT(*) c FROM activities WHERE source='resource'"
    ).fetchone()["c"]
    assert remaining == 0


# --- the UI, end to end -----------------------------------------------------------


def _open(monkeypatch, db_path, page_path, *, as_parent):
    st.cache_resource.clear()
    monkeypatch.setattr(config, "DEFAULT_DB_PATH", db_path)
    at = AppTest.from_file(HOME_PATH)
    if as_parent:
        at.session_state["parent_unlocked"] = True
    at.run(timeout=30)
    at.switch_page(page_path)
    at.run(timeout=30)
    assert not at.exception, [e.message for e in at.exception]
    return at


def _seed(tmp_path, *, resources=None):
    db_path = tmp_path / "a.db"
    database = Database(db_path)
    s = database.ensure_default_student()
    auth.set_pin(database, "1234")
    lid = database.save_lesson(
        student_id=s["id"], agent="english", subject="english", topic="t",
        title="Essay",
        payload={"title": "Essay", "overview": "o", "activities": [], "materials": []},
    )
    for r in resources or []:
        database.add_lesson_resource(lid, *r)
    database.close()
    return db_path, lid


def test_the_student_sees_a_parent_resource_in_the_lesson(monkeypatch, tmp_path):
    db_path, _ = _seed(
        tmp_path, resources=[("Crash Course: Commas", "https://youtu.be/abc", "")]
    )
    at = _open(monkeypatch, db_path, ENGLISH_PATH, as_parent=False)
    blob = "\n".join(m.value for m in at.markdown)
    assert "from your parent" in blob
    assert "Crash Course: Commas" in blob
    assert "https://youtu.be/abc" in blob


def test_the_student_can_mark_a_resource_watched_and_it_logs_time(monkeypatch, tmp_path):
    db_path, lid = _seed(
        tmp_path, resources=[("Crash Course: Commas", "https://youtu.be/abc", "")]
    )
    at = _open(monkeypatch, db_path, ENGLISH_PATH, as_parent=False)
    watch = [b for b in at.button if (b.key or "").startswith(f"reswatch_{lid}_")]
    assert watch, "his lesson should offer a Mark-watched button on the resource"
    watch[0].click().run()
    assert not at.exception, [e.message for e in at.exception]

    database = Database(db_path)
    n = database.conn.execute(
        "SELECT COUNT(*) c FROM activities WHERE source='resource'"
    ).fetchone()["c"]
    database.close()
    assert n == 1


def test_no_resources_block_for_the_student_when_there_are_none(monkeypatch, tmp_path):
    db_path, _ = _seed(tmp_path)
    at = _open(monkeypatch, db_path, ENGLISH_PATH, as_parent=False)
    blob = "\n".join(m.value for m in at.markdown)
    assert "Extra resources" not in blob  # stays invisible until something's added


def test_a_parent_adds_a_resource_from_the_review(monkeypatch, tmp_path):
    db_path, lid = _seed(tmp_path)
    database = Database(db_path)
    database.submit_lesson(lid)  # so it lands in the review queue, open to grade
    database.close()

    at = _open(monkeypatch, db_path, MISSION_CONTROL_PATH, as_parent=True)
    at.text_input(key=f"addres_label_{lid}").set_value("A helpful video").run()
    at.text_input(key=f"addres_url_{lid}").set_value("https://youtu.be/xyz").run()
    [b for b in at.button if (b.key or "") == f"addres_btn_{lid}"][0].click().run()
    assert not at.exception, [e.message for e in at.exception]

    database = Database(db_path)
    resources = database.get_lesson(lid)["metadata"]["parent_resources"]
    database.close()
    assert resources == [{"label": "A helpful video", "url": "https://youtu.be/xyz",
                          "note": "", "minutes": config.RESOURCE_DEFAULT_MINUTES}]
