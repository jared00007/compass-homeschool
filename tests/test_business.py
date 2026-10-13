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
