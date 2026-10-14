"""Landon's 'start a little business' project: the profile store and the flyer."""

from __future__ import annotations

from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from compass import business, config
from compass.storage.db import Database

REPO_ROOT = Path(__file__).resolve().parent.parent
HOME_PATH = str(REPO_ROOT / "Home.py")
BUSINESS_PATH = str(REPO_ROOT / "pages" / "19_My_Business.py")


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "biz.db")
    yield database
    database.close()


@pytest.fixture()
def student(db):
    return db.ensure_default_student()


# --- pure profile + flyer -------------------------------------------------------


def test_default_profile_is_empty_but_shaped():
    profile = business.default_profile()
    assert profile["name"] == ""
    assert profile["services"] == []


def test_is_ready_needs_a_name_and_a_service():
    assert not business.is_ready_for_flyer({"name": "", "services": []})
    assert not business.is_ready_for_flyer({"name": "X", "services": []})
    assert not business.is_ready_for_flyer({"name": "", "services": [{"label": "Rake"}]})
    assert business.is_ready_for_flyer({"name": "X", "services": [{"label": "Rake"}]})


def test_flyer_shows_the_business_name_services_and_contact():
    profile = {
        "name": "Leaf Crew", "slogan": "Done right.",
        "services": [{"emoji": "🍂", "label": "Rake leaves", "price": "$25"}],
        "contact": "(555) 111-2222",
    }
    html = business.flyer_inner_html(profile, "Landon")
    assert "Leaf Crew" in html
    assert "Rake leaves" in html and "$25" in html
    assert "(555) 111-2222" in html
    assert "Done right." in html
    assert "Run by Landon" in html


def test_a_half_filled_custom_service_is_dropped_from_the_flyer():
    profile = {"name": "X", "services": [
        {"emoji": "🍂", "label": "Rake", "price": "$20"},
        {"emoji": "", "label": "", "price": "$9"},  # no label -> dropped
    ]}
    html = business.flyer_inner_html(profile)
    assert "Rake" in html
    assert "$9" not in html


def test_flyer_escapes_user_input():
    html = business.flyer_inner_html(
        {"name": "<script>bad</script>", "services": [{"label": "Rake"}]}
    )
    assert "<script>bad" not in html
    assert "&lt;script&gt;" in html


def test_flyer_document_is_a_standalone_printable_page():
    doc = business.flyer_document(
        {"name": "X", "services": [{"label": "Rake", "price": "$20"}]}
    )
    assert doc.startswith("<!doctype html>")
    assert "</html>" in doc
    assert "Rake" in doc


# --- door-knock script ----------------------------------------------------------


def test_doorknock_script_is_built_from_his_details():
    profile = {
        "name": "Leaf Crew",
        "goal": "a new bike",
        "services": [
            {"label": "Rake leaves"}, {"label": "Bag the leaves"}, {"label": "Clear walkways"},
        ],
    }
    script = business.doorknock_script(profile, "Landon")
    assert "Landon" in script
    assert "Leaf Crew" in script
    assert "rake leaves" in script  # lower-cased into the offer line
    assert "a new bike" in script   # goal line only appears when set
    assert "flyer" in script.lower()


def test_doorknock_script_handles_a_bare_profile():
    # No name, no services, no goal -- still a usable, friendly script.
    script = business.doorknock_script({"name": "", "services": []})
    assert "yard work" in script.lower()
    assert "a new bike" not in script
    assert script.strip()


# --- receipt --------------------------------------------------------------------


def test_receipt_shows_the_job_details_and_amount():
    profile = {"name": "Leaf Crew", "contact": "(555) 111-2222"}
    job = {"id": 7, "job_date": "2026-10-13", "customer": "Mrs. Lee",
           "description": "Raked front yard", "earned": 25.0}
    html = business.receipt_inner_html(profile, job, "Landon")
    assert "Leaf Crew" in html
    assert "Mrs. Lee" in html
    assert "Raked front yard" in html
    assert "$25.00" in html
    assert "Receipt #7" in html
    assert "(555) 111-2222" in html


def test_receipt_escapes_user_input_and_survives_a_missing_amount():
    job = {"job_date": "2026-10-13", "customer": "<b>hax</b>", "earned": None}
    html = business.receipt_inner_html({"name": "X"}, job)
    assert "<b>hax</b>" not in html
    assert "&lt;b&gt;hax" in html
    assert "$0.00" in html  # None earned falls back to zero, never crashes


def test_receipt_document_is_a_standalone_printable_page():
    doc = business.receipt_document(
        {"name": "X"}, {"job_date": "2026-10-13", "description": "Rake", "earned": 20.0}
    )
    assert doc.startswith("<!doctype html>")
    assert "</html>" in doc
    assert "$20.00" in doc


# --- "help me write it" request shape -------------------------------------------


def test_copy_schema_requires_slogan_and_about():
    assert business.COPY_SCHEMA["required"] == ["slogan", "about"]
    assert business.COPY_SCHEMA["additionalProperties"] is False


def test_copy_system_prompt_carries_his_details():
    prompt = business.copy_system_prompt(
        name="Leaf Crew", age=13, interests="Minecraft",
        services=["Rake leaves", "Clear walkways"],
    )
    assert "Leaf Crew" in prompt
    assert "Rake leaves" in prompt and "Clear walkways" in prompt
    assert "Minecraft" in prompt
    assert "13-year-old" in prompt


# --- privacy-aware contact on the flyer -----------------------------------------


def test_flyer_contact_phone_is_the_default():
    html = business.flyer_inner_html(
        {"name": "X", "services": [{"label": "Rake"}], "contact": "555-0100"}
    )
    assert "📞 Call or text to book: 555-0100" in html
    assert "phone Call" not in html  # the method key must not leak where the emoji goes


def test_flyer_contact_email_changes_the_booking_line():
    html = business.flyer_inner_html({
        "name": "X", "services": [{"label": "Rake"}],
        "contact": "book@example.com", "contact_method": "email",
    })
    assert "✉️ Email to book: book@example.com" in html
    assert "Call or text" not in html
    assert "email Email" not in html


def test_flyer_contact_knock_shows_no_number_even_if_one_is_stored():
    # The safest option for a young teen: the flyer carries no number at all.
    html = business.flyer_inner_html({
        "name": "X", "services": [{"label": "Rake"}],
        "contact": "555-SHOULD-NOT-SHOW", "contact_method": "knock",
    })
    assert "555-SHOULD-NOT-SHOW" not in html
    assert "🚪" in html and "come back around" in html
    assert "knock I'll" not in html  # the method key must not leak into the line


# --- the neighborhood map (houses) ----------------------------------------------


def test_neighborhood_map_is_empty_until_a_house_is_added():
    html = business.neighborhood_map_html([])
    assert "map" in html.lower()
    assert "🏠" not in html  # no pins yet


def test_neighborhood_map_groups_houses_and_colors_by_status():
    houses = [
        {"nickname": "Blue house", "street": "Maple St", "status": "customer"},
        {"nickname": "Corner lot", "street": "Maple St", "status": "avoid"},
        {"nickname": "Big porch", "street": "Oak Ave", "status": "maybe"},
    ]
    html = business.neighborhood_map_html(houses, "Landon")
    assert "Landon's neighborhood map" in html
    assert "Maple St" in html and "Oak Ave" in html
    assert "Blue house" in html and "Corner lot" in html and "Big porch" in html
    assert "🟢" in html and "🔴" in html and "🟡" in html  # legend + pins


def test_neighborhood_map_escapes_user_input():
    html = business.neighborhood_map_html([{"nickname": "<script>x</script>", "status": "maybe"}])
    assert "<script>x" not in html
    assert "&lt;script&gt;" in html


def test_house_status_defaults_to_maybe_for_unknown():
    assert business.house_status("customer")[1] == "🟢"
    assert business.house_status("nonsense")[0] == "maybe"


# --- multi-subject job credit ---------------------------------------------------


def test_job_can_credit_math_and_writing_as_separate_blocks(db, student):
    sid = student["id"]
    db.add_business_job(sid, job_date="2026-10-13", customer="Mrs. Lee", earned=25.0,
                        minutes=60, count_math=True, count_writing=True)
    cur = db.conn.execute(
        "SELECT subject, SUM(minutes) m FROM activity_subject_credits GROUP BY subject"
    )
    credits = {r["subject"]: r["m"] for r in cur.fetchall()}
    assert credits["occupational_education"] == 60
    assert credits["math"] == config.BUSINESS_BOOKKEEPING_MINUTES
    assert credits["writing"] == config.BUSINESS_WRITING_MINUTES
    # The business_jobs.minutes column (used for totals) is still just the labor.
    assert db.business_totals(sid)["minutes"] == 60


def test_deleting_a_job_removes_its_math_and_writing_credit_too(db, student):
    sid = student["id"]
    job_id = db.add_business_job(sid, job_date="2026-10-13", earned=20.0, minutes=45,
                                 count_math=True, count_writing=True)
    assert len([a for a in db.list_activities(sid) if a["source"] == "business"]) == 3
    db.delete_business_job(job_id)
    assert [a for a in db.list_activities(sid) if a["source"] == "business"] == []


def test_math_and_writing_credit_are_off_by_default(db, student):
    sid = student["id"]
    db.add_business_job(sid, job_date="2026-10-13", earned=20.0, minutes=45)
    subjects = {a["primary_subject"] for a in db.list_activities(sid) if a["source"] == "business"}
    assert subjects == {"occupational_education"}


def test_business_subject_minutes_breakdown(db, student):
    sid = student["id"]
    db.add_business_job(sid, job_date="2026-10-13", earned=25.0, minutes=60, count_math=True)
    db.add_business_job(sid, job_date="2026-10-14", earned=30.0, minutes=90, count_math=True)
    breakdown = db.business_subject_minutes(sid)
    assert breakdown["occupational_education"] == 150
    assert breakdown["math"] == 2 * config.BUSINESS_BOOKKEEPING_MINUTES


def test_business_monthly_totals_group_by_month(db, student):
    sid = student["id"]
    db.add_business_job(sid, job_date="2026-10-05", earned=25.0, expense=5.0, minutes=60)
    db.add_business_job(sid, job_date="2026-10-20", earned=35.0, expense=0.0, minutes=90)
    db.add_business_job(sid, job_date="2026-11-02", earned=40.0, expense=0.0, minutes=60)
    months = db.business_monthly_totals(sid)
    assert [m["month"] for m in months] == ["2026-11", "2026-10"]  # newest first
    october = months[1]
    assert october["jobs"] == 2
    assert october["earned"] == 60.0 and october["profit"] == 55.0
    assert october["minutes"] == 150


# --- houses: storage ------------------------------------------------------------


def test_houses_round_trip_and_update_and_delete(db, student):
    sid = student["id"]
    h1 = db.add_business_house(sid, "Blue house", street="Maple St", status="customer")
    db.add_business_house(sid, "Grumpy corner", street="Maple St", status="avoid",
                          notes="yelled at me lol")
    houses = db.list_business_houses(sid)
    assert len(houses) == 2
    assert db.business_house_streets(sid) == ["Maple St"]
    # An unknown status is normalized to 'maybe'.
    weird = db.add_business_house(sid, "Mystery", status="banana")
    assert next(h for h in db.list_business_houses(sid) if h["id"] == weird)["status"] == "maybe"
    # Update and delete.
    db.update_business_house(h1, status="maybe", notes="moved")
    updated = next(h for h in db.list_business_houses(sid) if h["id"] == h1)
    assert updated["status"] == "maybe" and updated["notes"] == "moved"
    db.delete_business_house(h1)
    assert all(h["id"] != h1 for h in db.list_business_houses(sid))


def test_house_visit_counts_match_logged_jobs(db, student):
    sid = student["id"]
    db.add_business_house(sid, "Mrs. Lee", status="customer")
    db.add_business_house(sid, "Never hired", status="maybe")
    db.add_business_job(sid, job_date="2026-10-13", customer="Mrs. Lee", earned=25.0, minutes=60)
    db.add_business_job(sid, job_date="2026-10-20", customer="Mrs. Lee", earned=25.0, minutes=60)
    counts = db.business_house_visit_counts(sid)
    assert counts["mrs. lee"] == 2
    assert counts["never hired"] == 0


def test_the_page_adds_a_house_to_the_map(monkeypatch, tmp_path):
    db_path = tmp_path / "biz.db"
    Database(db_path).close()
    at = _open(monkeypatch, db_path)
    [t for t in at.text_input if t.key == "bizhouse_nick"][0].set_value("Blue house on Maple")
    [b for b in at.button if "Add to my map" in (b.label or "")][0].click().run()
    assert not at.exception, [e.message for e in at.exception]
    db = Database(db_path)
    student = db.ensure_default_student()
    houses = db.list_business_houses(student["id"])
    db.close()
    assert len(houses) == 1 and houses[0]["nickname"] == "Blue house on Maple"


# --- storage --------------------------------------------------------------------


def test_profile_round_trips_through_the_db(db, student):
    assert db.get_business_profile(student["id"])["name"] == ""  # empty default
    db.save_business_profile(student["id"], {
        "name": "Leaf Crew",
        "services": [{"emoji": "🍂", "label": "Rake leaves", "price": "$20"}],
        "contact": "(555) 123-4567",
    })
    got = db.get_business_profile(student["id"])
    assert got["name"] == "Leaf Crew"
    assert got["services"][0]["label"] == "Rake leaves"
    assert got["contact"] == "(555) 123-4567"
    # Re-saving replaces, never stacks a second row.
    db.save_business_profile(student["id"], {"name": "Yard Help", "services": []})
    assert db.get_business_profile(student["id"])["name"] == "Yard Help"


# --- the page -------------------------------------------------------------------


def _open(monkeypatch, db_path):
    st.cache_resource.clear()
    monkeypatch.setattr(config, "DEFAULT_DB_PATH", db_path)
    at = AppTest.from_file(HOME_PATH)
    at.run(timeout=30)
    at.switch_page(BUSINESS_PATH)
    at.run(timeout=30)
    assert not at.exception, [e.message for e in at.exception]
    return at


def test_the_page_saves_a_business_and_renders_its_flyer(monkeypatch, tmp_path):
    db_path = tmp_path / "biz.db"
    Database(db_path).close()

    at = _open(monkeypatch, db_path)
    [t for t in at.text_input if t.label == "Business name"][0].set_value("Landon's Leaf Crew")
    at.checkbox(key="biz_svc_rake").check()
    [t for t in at.text_input if t.key == "biz_price_rake"][0].set_value("$25")
    [b for b in at.button if "Save my business" in (b.label or "")][0].click().run()
    assert not at.exception, [e.message for e in at.exception]

    db = Database(db_path)
    student = db.ensure_default_student()
    profile = db.get_business_profile(student["id"])
    db.close()
    assert profile["name"] == "Landon's Leaf Crew"
    assert any(s["label"] == "Rake leaves" and s["price"] == "$25" for s in profile["services"])
    # The flyer renders on the page (the apostrophe is HTML-escaped in the flyer).
    assert any("Leaf Crew" in (m.value or "") for m in at.markdown)
    assert any("Rake leaves" in (m.value or "") for m in at.markdown)


# --- the money / job log --------------------------------------------------------


def test_jobs_track_money_and_totals(db, student):
    sid = student["id"]
    assert db.business_totals(sid)["jobs"] == 0
    db.add_business_job(sid, job_date="2026-10-13", customer="Mrs. Lee",
                        description="Raked front yard", earned=25.0, expense=3.5, minutes=60)
    db.add_business_job(sid, job_date="2026-10-14", customer="Mr. Ortiz",
                        earned=40.0, expense=0.0, minutes=90)
    jobs = db.list_business_jobs(sid)
    assert len(jobs) == 2
    assert jobs[0]["job_date"] == "2026-10-14"  # newest first
    totals = db.business_totals(sid)
    assert totals == {"jobs": 2, "earned": 65.0, "expense": 3.5, "profit": 61.5, "minutes": 150}


def test_a_job_logs_occupational_education_hours_and_delete_removes_them(db, student):
    sid = student["id"]
    job_id = db.add_business_job(sid, job_date="2026-10-13", customer="Mrs. Lee",
                                 earned=25.0, minutes=60)
    acts = [a for a in db.list_activities(sid) if a["source"] == "business"]
    assert len(acts) == 1 and acts[0]["minutes"] == 60
    cur = db.conn.execute(
        "SELECT subject, SUM(minutes) m FROM activity_subject_credits GROUP BY subject"
    )
    credits = {r["subject"]: r["m"] for r in cur.fetchall()}
    assert credits.get("occupational_education") == 60
    # Deleting the job removes its logged hours too.
    db.delete_business_job(job_id)
    assert [a for a in db.list_activities(sid) if a["source"] == "business"] == []


# --- the My Business Big Project ------------------------------------------------


def test_ensure_business_project_creates_a_steps_project_once(db, student):
    sid = student["id"]
    project_id = db.ensure_business_project(sid)
    projects = [p for p in db.list_big_projects(sid) if p["kind"] == "business"]
    assert len(projects) == 1
    assert projects[0]["id"] == project_id
    assert projects[0]["title"] == "My Yard Business"

    steps = db.list_project_steps(project_id)
    assert len(steps) >= 4
    # First step is live (To Do); the rest start in Backlog.
    assert steps[0]["active"] == 1
    assert all(s["active"] == 0 for s in steps[1:])
    # The work counts as real school time -- Occupational Education.
    assert all(s["credit_subject"] == "occupational_education" for s in steps)

    # Idempotent: a second call returns the same project and adds no steps.
    again = db.ensure_business_project(sid)
    assert again == project_id
    assert len(db.list_project_steps(project_id)) == len(steps)


def test_the_page_mirrors_the_business_onto_the_big_projects_board(monkeypatch, tmp_path):
    db_path = tmp_path / "biz.db"
    Database(db_path).close()
    at = _open(monkeypatch, db_path)
    [t for t in at.text_input if t.label == "Business name"][0].set_value("Landon's Leaf Crew")
    at.checkbox(key="biz_svc_rake").check()
    [b for b in at.button if "Save my business" in (b.label or "")][0].click().run()
    assert not at.exception, [e.message for e in at.exception]

    db = Database(db_path)
    student = db.ensure_default_student()
    projects = [p for p in db.list_big_projects(student["id"]) if p["kind"] == "business"]
    db.close()
    assert len(projects) == 1  # saving a business seeds the project on the board


def test_a_zero_minute_job_tracks_money_without_logging_hours(db, student):
    sid = student["id"]
    db.add_business_job(sid, job_date="2026-10-13", earned=10.0, minutes=0)
    assert db.business_totals(sid)["earned"] == 10.0
    assert [a for a in db.list_activities(sid) if a["source"] == "business"] == []


def test_the_page_logs_a_job_and_updates_totals(monkeypatch, tmp_path):
    db_path = tmp_path / "biz.db"
    Database(db_path).close()
    at = _open(monkeypatch, db_path)
    at.number_input(key="bizjob_charged").set_value(30.0)
    [b for b in at.button if "Add this job" in (b.label or "")][0].click().run(timeout=30)
    assert not at.exception, [e.message for e in at.exception]
    db = Database(db_path)
    student = db.ensure_default_student()
    totals = db.business_totals(student["id"])
    db.close()
    assert totals["jobs"] == 1 and totals["earned"] == 30.0
    assert totals["minutes"] == 60  # default minutes logged as Occupational Ed
