"""The travel journal's review gate: writing an entry submits it, a parent
approves it (logging its flat credit automatically) or sends it back, and
a parent can assign a trip to a specific day ahead of time -- the same
scheduling pattern Life Skills already has, plus the same review-gate
vocabulary lessons already use.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import streamlit as st
from streamlit.testing.v1 import AppTest

from compass import auth, config
from compass.storage.db import Database

REPO_ROOT = Path(__file__).resolve().parent.parent
HOME_PATH = str(REPO_ROOT / "Home.py")
TRAVELS_PATH = str(REPO_ROOT / "pages" / "9_Landons_Travels.py")


def _open_home(monkeypatch, db_path):
    st.cache_resource.clear()
    monkeypatch.setattr(config, "DEFAULT_DB_PATH", db_path)
    at = AppTest.from_file(HOME_PATH)
    at.run(timeout=30)
    assert not at.exception, [e.message for e in at.exception]
    return at


def _open_travels(monkeypatch, db_path, *, as_parent=False):
    st.cache_resource.clear()
    monkeypatch.setattr(config, "DEFAULT_DB_PATH", db_path)
    at = AppTest.from_file(HOME_PATH)
    if as_parent:
        at.session_state["parent_unlocked"] = True
    at.run(timeout=30)
    at.switch_page(TRAVELS_PATH)
    at.run(timeout=30)
    assert not at.exception, [e.message for e in at.exception]
    return at


def _journal_tab(at):
    return [t for t in at.tabs if t.label == "Travel journal"][0]


# --- Home: due card, upcoming hint, Week grid -----------------------------------


def test_a_trip_assigned_for_today_shows_up_on_home(monkeypatch, tmp_path):
    db_path = tmp_path / "home.db"
    database = Database(db_path)
    s = database.ensure_default_student()
    auth.set_pin(database, "1234")
    today = date.today().isoformat()
    entry_id = database.add_travel_entry(
        s["id"], "Wyoming", today, title="Yellowstone", status="planned"
    )
    database.schedule_travel_entry(entry_id, today)
    database.close()

    at = _open_home(monkeypatch, db_path)
    text = " ".join(m.value for m in at.markdown)
    assert "Travel Journal (1)" in text
    labels = [pl.label for pl in at.get("page_link")]
    assert any("Yellowstone" in label for label in labels)


def test_a_trip_assigned_for_later_shows_an_upcoming_hint_on_home(monkeypatch, tmp_path):
    db_path = tmp_path / "home.db"
    database = Database(db_path)
    s = database.ensure_default_student()
    auth.set_pin(database, "1234")
    entry_id = database.add_travel_entry(
        s["id"], "Wyoming", date.today().isoformat(), title="Yellowstone", status="planned"
    )
    later = (date.today() + timedelta(days=7)).isoformat()
    database.schedule_travel_entry(entry_id, later)
    database.close()

    at = _open_home(monkeypatch, db_path)
    text = " ".join(c.value for c in at.caption)
    assert "more trip(s) assigned for a later week" in text
    labels = [pl.label for pl in at.get("page_link")]
    assert not any("Yellowstone" in label for label in labels)


def test_home_shows_no_travel_journal_card_when_nothing_is_assigned(monkeypatch, tmp_path):
    db_path = tmp_path / "home.db"
    database = Database(db_path)
    s = database.ensure_default_student()
    auth.set_pin(database, "1234")
    database.add_travel_entry(s["id"], "Wyoming", "2025-06-10", title="Old trip")  # unscheduled
    database.close()

    at = _open_home(monkeypatch, db_path)
    text = " ".join(m.value for m in at.markdown)
    assert "Travel Journal" not in text


def test_a_trip_assigned_this_week_shows_on_the_week_grid(monkeypatch, tmp_path):
    db_path = tmp_path / "home.db"
    database = Database(db_path)
    s = database.ensure_default_student()
    auth.set_pin(database, "1234")
    entry_id = database.add_travel_entry(
        s["id"], "Wyoming", date.today().isoformat(), title="Yellowstone", status="planned"
    )
    database.schedule_travel_entry(entry_id, date.today().isoformat())
    database.close()

    at = _open_home(monkeypatch, db_path)
    week_button = [b for b in at.button if "This Week" in (b.label or "")][0]
    week_button.click().run()
    assert not at.exception, [e.message for e in at.exception]
    text = " ".join(m.value for m in at.markdown)
    assert "Yellowstone" in text


# --- Adding an entry: story decides submitted vs. planned -----------------------


def test_the_journal_page_loads_for_both_views(monkeypatch, tmp_path):
    db_path = tmp_path / "home.db"
    database = Database(db_path)
    database.ensure_default_student()
    auth.set_pin(database, "1234")
    database.close()

    _open_travels(monkeypatch, db_path, as_parent=False)
    _open_travels(monkeypatch, db_path, as_parent=True)


def test_writing_a_real_entry_submits_it_not_completes_it(monkeypatch, tmp_path):
    """The core behavior change this feature makes: a real entry with a
    story now waits on a parent instead of existing as done the instant
    it's saved."""
    db_path = tmp_path / "home.db"
    database = Database(db_path)
    s = database.ensure_default_student()
    auth.set_pin(database, "1234")
    database.close()

    at = _open_travels(monkeypatch, db_path, as_parent=False)
    tab = _journal_tab(at)
    title_input = [w for w in tab.text_input if w.label == "Title"][0]
    title_input.set_value("Yellowstone trip")
    story_input = [w for w in tab.text_area if w.label == "The story"][0]
    story_input.set_value(" ".join(["We", "watched", "Old", "Faithful", "erupt", "together"] * 12))
    submit = [b for b in tab.button if b.label in ("Save this entry", "Assign this trip")][0]
    submit.click().run()
    assert not at.exception, [e.message for e in at.exception]

    database = Database(db_path)
    entry = database.list_travel_entries(s["id"])[0]
    database.close()
    assert entry["status"] == "submitted"
    assert entry["title"] == "Yellowstone trip"


def test_a_parent_assigning_a_trip_with_a_blank_story_creates_a_stub(monkeypatch, tmp_path):
    db_path = tmp_path / "home.db"
    database = Database(db_path)
    database.ensure_default_student()
    auth.set_pin(database, "1234")
    database.close()

    at = _open_travels(monkeypatch, db_path, as_parent=True)
    tab = _journal_tab(at)
    title_input = [w for w in tab.text_input if w.label == "Title"][0]
    title_input.set_value("Grand Canyon trip")
    assign = [c for c in tab.checkbox if c.label.startswith("Assign this trip")][0]
    assign.set_value(True).run()
    tab = _journal_tab(at)

    submit = [b for b in tab.button if b.label in ("Save this entry", "Assign this trip")][0]
    submit.click().run()
    assert not at.exception, [e.message for e in at.exception]

    database = Database(db_path)
    s = database.ensure_default_student()
    entry = database.list_travel_entries(s["id"])[0]
    database.close()
    assert entry["status"] == "planned"
    assert entry["scheduled_for"] == date.today().isoformat()


# --- writing up an assigned stub, and the parent review actions -----------------


def test_writing_up_an_assigned_stub_submits_it_for_review(monkeypatch, tmp_path):
    """Open to anyone, not just a parent -- this is what he does himself."""
    db_path = tmp_path / "home.db"
    database = Database(db_path)
    s = database.ensure_default_student()
    auth.set_pin(database, "1234")
    entry_id = database.add_travel_entry(
        s["id"], "Arizona", "2025-06-10", title="Grand Canyon", status="planned"
    )
    database.close()

    at = _open_travels(monkeypatch, db_path, as_parent=False)
    tab = _journal_tab(at)
    compose_button = [b for b in tab.button if b.key == f"compose_entry_{entry_id}"][0]
    compose_button.click().run()
    tab = _journal_tab(at)

    # Two "The story" fields exist on the page while composing -- the
    # always-present "Add a travel entry" form's own blank one (first in
    # document order) and this compose form's pre-filled one (last) --
    # `[-1]` picks the one actually being edited here.
    story_input = [w for w in tab.text_area if w.label == "The story"][-1]
    story_input.set_value(
        " ".join(["We", "hiked", "to", "the", "rim", "and", "watched", "the", "sunset"] * 7)
    )
    submit = [b for b in tab.button if b.label == "Submit for review"][0]
    submit.click().run()
    assert not at.exception, [e.message for e in at.exception]

    database = Database(db_path)
    entry = database.list_travel_entries(s["id"])[0]
    database.close()
    assert entry["status"] == "submitted"
    assert "sunset" in entry["story"]


def test_a_parent_approving_a_submitted_entry_completes_it_and_logs_credit(monkeypatch, tmp_path):
    db_path = tmp_path / "home.db"
    database = Database(db_path)
    s = database.ensure_default_student()
    auth.set_pin(database, "1234")
    entry_id = database.add_travel_entry(
        s["id"], "Arizona", "2025-06-10", title="Grand Canyon",
        story="We hiked to the rim.", status="submitted",
    )
    database.close()

    at = _open_travels(monkeypatch, db_path, as_parent=True)
    tab = _journal_tab(at)
    approve = [b for b in tab.button if b.key == f"approve_entry_{entry_id}"][0]
    approve.click().run()
    assert not at.exception, [e.message for e in at.exception]

    database = Database(db_path)
    entry = database.list_travel_entries(s["id"])[0]
    activities = database.list_activities(s["id"])
    database.close()
    assert entry["status"] == "completed"
    assert len(activities) == 1
    assert activities[0]["source"] == "travel_journal"


# --- Assigning him to pick his own trips (open picks) --------------------------


def test_assigning_open_picks_creates_the_requested_number_of_blank_stubs(monkeypatch, tmp_path):
    db_path = tmp_path / "home.db"
    database = Database(db_path)
    database.ensure_default_student()
    auth.set_pin(database, "1234")
    database.close()

    at = _open_travels(monkeypatch, db_path, as_parent=True)
    tab = _journal_tab(at)
    assign_button = [b for b in tab.button if b.key == "assign_open_travel_picks"][0]
    assign_button.click().run()
    assert not at.exception, [e.message for e in at.exception]

    database = Database(db_path)
    s = database.ensure_default_student()
    entries = database.list_travel_entries(s["id"])
    database.close()
    # Default count on the assign form is 2.
    assert len(entries) == 2
    assert all(e["state"] == "" and e["title"] == "" and e["status"] == "planned" for e in entries)


def test_composing_an_open_pick_lets_him_choose_the_trip_and_submits_it(monkeypatch, tmp_path):
    db_path = tmp_path / "home.db"
    database = Database(db_path)
    s = database.ensure_default_student()
    auth.set_pin(database, "1234")
    database.assign_open_travel_entries(s["id"], 1, date.today().isoformat())
    database.close()

    at = _open_travels(monkeypatch, db_path, as_parent=False)
    tab = _journal_tab(at)
    compose_button = [b for b in tab.button if b.label == "✍️ Write it up"][0]
    compose_button.click().run()
    tab = _journal_tab(at)

    state_select = [w for w in tab.selectbox if w.label == "State"][-1]
    state_select.set_value("Wyoming")
    title_input = [w for w in tab.text_input if w.label == "Title"][-1]
    title_input.set_value("Yellowstone Adventure")
    story_input = [w for w in tab.text_area if w.label == "The story"][-1]
    long_story = " ".join(["We", "explored", "the", "park", "together"] * 15)
    story_input.set_value(long_story)
    submit = [b for b in tab.button if b.label == "Submit for review"][0]
    submit.click().run()
    assert not at.exception, [e.message for e in at.exception]

    database = Database(db_path)
    entry = database.list_travel_entries(s["id"])[0]
    database.close()
    assert entry["status"] == "submitted"
    assert entry["state"] == "Wyoming"
    assert entry["title"] == "Yellowstone Adventure"


def test_a_too_short_open_pick_story_does_not_submit(monkeypatch, tmp_path):
    """The whole point of this feature -- picking a real trip and writing
    about it -- so a one-liner doesn't sneak through as submitted."""
    db_path = tmp_path / "home.db"
    database = Database(db_path)
    s = database.ensure_default_student()
    auth.set_pin(database, "1234")
    database.assign_open_travel_entries(s["id"], 1, date.today().isoformat())
    database.close()

    at = _open_travels(monkeypatch, db_path, as_parent=False)
    tab = _journal_tab(at)
    compose_button = [b for b in tab.button if b.label == "✍️ Write it up"][0]
    compose_button.click().run()
    tab = _journal_tab(at)

    state_select = [w for w in tab.selectbox if w.label == "State"][-1]
    state_select.set_value("Wyoming")
    title_input = [w for w in tab.text_input if w.label == "Title"][-1]
    title_input.set_value("Corner store run")
    story_input = [w for w in tab.text_area if w.label == "The story"][-1]
    story_input.set_value("We went there.")
    submit = [b for b in tab.button if b.label == "Submit for review"][0]
    submit.click().run()
    assert not at.exception, [e.message for e in at.exception]

    database = Database(db_path)
    entry = database.list_travel_entries(s["id"])[0]
    database.close()
    assert entry["status"] == "planned"
    assert entry["story"] == "We went there."
    assert any("needs at least" in w.value for w in at.warning)


def test_a_too_short_story_on_the_add_form_saves_as_a_stub_not_submitted(monkeypatch, tmp_path):
    db_path = tmp_path / "home.db"
    database = Database(db_path)
    database.ensure_default_student()
    auth.set_pin(database, "1234")
    database.close()

    at = _open_travels(monkeypatch, db_path, as_parent=False)
    tab = _journal_tab(at)
    title_input = [w for w in tab.text_input if w.label == "Title"][0]
    title_input.set_value("Quick trip")
    story_input = [w for w in tab.text_area if w.label == "The story"][0]
    story_input.set_value("It was fun.")
    submit = [b for b in tab.button if b.label in ("Save this entry", "Assign this trip")][0]
    submit.click().run()
    assert not at.exception, [e.message for e in at.exception]

    database = Database(db_path)
    s = database.ensure_default_student()
    entry = database.list_travel_entries(s["id"])[0]
    database.close()
    assert entry["status"] == "planned"
    assert entry["story"] == "It was fun."
    assert any("needs at least" in w.value for w in at.warning)


def test_a_parent_sending_a_submitted_entry_back_with_a_note(monkeypatch, tmp_path):
    db_path = tmp_path / "home.db"
    database = Database(db_path)
    s = database.ensure_default_student()
    auth.set_pin(database, "1234")
    entry_id = database.add_travel_entry(
        s["id"], "Arizona", "2025-06-10", title="Grand Canyon",
        story="We went there.", status="submitted",
    )
    database.close()

    at = _open_travels(monkeypatch, db_path, as_parent=True)
    tab = _journal_tab(at)
    bounce = [b for b in tab.button if b.key == f"reviewbounce_entry_{entry_id}"][0]
    bounce.click().run()
    tab = _journal_tab(at)

    note_input = [w for w in tab.text_input if w.label == "What should he fix or add?"][0]
    note_input.set_value("Add more detail about what you actually did there.")
    send = [b for b in tab.button if b.label == "Send back"][0]
    send.click().run()
    assert not at.exception, [e.message for e in at.exception]

    database = Database(db_path)
    entry = database.list_travel_entries(s["id"])[0]
    database.close()
    assert entry["status"] == "needs_revision"
    assert "more detail" in entry["revision_note"]
