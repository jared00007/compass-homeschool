"""The parent <-> student chat thread: a two-way message list with one-tap
read receipts, surfaced as an auto-opening card on his Home and in Mission
Control.
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
MISSION_CONTROL_PATH = str(REPO_ROOT / "pages" / "14_Mission_Control.py")


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "msg.db")
    yield database
    database.close()


@pytest.fixture()
def student(db):
    return db.ensure_default_student()


# --- storage ----------------------------------------------------------------------


def test_a_message_is_stored_and_listed_oldest_first(db, student):
    db.send_message(student["id"], "parent", "Don't forget your reading!")
    db.send_message(student["id"], "student", "ok!")
    thread = db.list_messages(student["id"])
    assert [(m["sender"], m["body"]) for m in thread] == [
        ("parent", "Don't forget your reading!"),
        ("student", "ok!"),
    ]


def test_a_blank_message_is_ignored(db, student):
    db.send_message(student["id"], "parent", "   ")
    assert db.list_messages(student["id"]) == []


def test_unread_counts_are_per_recipient(db, student):
    db.send_message(student["id"], "parent", "hi")   # unread for the student
    db.send_message(student["id"], "student", "yo")  # unread for the parent
    db.send_message(student["id"], "parent", "read this")  # unread for the student
    assert db.unread_message_count(student["id"], "student") == 2
    assert db.unread_message_count(student["id"], "parent") == 1


def test_marking_read_clears_only_the_recipients_unread(db, student):
    db.send_message(student["id"], "parent", "hi")
    db.send_message(student["id"], "student", "yo")
    db.mark_messages_read(student["id"], "student")  # student reads the parent's msg
    assert db.unread_message_count(student["id"], "student") == 0
    assert db.unread_message_count(student["id"], "parent") == 1  # his message still unread
    # And the parent's message now carries a read stamp (the receipt).
    parent_msg = db.list_messages(student["id"])[0]
    assert parent_msg["read_at"] is not None


# --- the UI, end to end -----------------------------------------------------------


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


def _seed(tmp_path):
    db_path = tmp_path / "a.db"
    database = Database(db_path)
    s = database.ensure_default_student()
    auth.set_pin(database, "1234")
    database.close()
    return db_path, s["id"]


def test_the_student_sees_a_parent_message_and_can_clear_it(monkeypatch, tmp_path):
    db_path, sid = _seed(tmp_path)
    database = Database(db_path)
    database.send_message(sid, "parent", "Reading first today please")
    database.close()

    at = _open(monkeypatch, db_path, HOME_PATH, as_parent=False)
    blob = "\n".join(m.value for m in at.markdown)
    assert "Reading first today please" in blob
    # The unread badge shows in the expander label.
    assert any("Messages — 1 new" in (e.label or "") for e in at.get("expander"))

    [b for b in at.button if (b.key or "") == "msg_gotit_student"][0].click().run()
    assert not at.exception, [e.message for e in at.exception]
    database = Database(db_path)
    assert database.unread_message_count(sid, "student") == 0
    database.close()


def test_the_student_can_reply(monkeypatch, tmp_path):
    db_path, sid = _seed(tmp_path)
    database = Database(db_path)
    database.send_message(sid, "parent", "How's it going?")
    database.close()

    at = _open(monkeypatch, db_path, HOME_PATH, as_parent=False)
    at.text_input(key="msg_input_student").set_value("going great!").run()
    [b for b in at.button if (b.key or "") == "FormSubmitter:msg_form_student-Send"][0].click().run()
    assert not at.exception, [e.message for e in at.exception]

    database = Database(db_path)
    thread = database.list_messages(sid)
    database.close()
    assert ("student", "going great!") in [(m["sender"], m["body"]) for m in thread]


def test_the_parent_sends_from_mission_control(monkeypatch, tmp_path):
    db_path, sid = _seed(tmp_path)
    at = _open(monkeypatch, db_path, MISSION_CONTROL_PATH, as_parent=True)
    at.text_input(key="msg_input_parent").set_value("Proud of you!").run()
    [b for b in at.button if (b.key or "") == "FormSubmitter:msg_form_parent-Send"][0].click().run()
    assert not at.exception, [e.message for e in at.exception]

    database = Database(db_path)
    thread = database.list_messages(sid)
    database.close()
    assert [(m["sender"], m["body"]) for m in thread] == [("parent", "Proud of you!")]
