"""Lightning lessons -- one short, single-topic lesson from a parent's topic +
editable instructions. The model call is mocked; what's pinned is the wiring:
a real fixed-shape lesson lands in the Backlog, tagged lightning, steered by the
parent's instructions."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from compass.agents import lightning
from compass.storage.db import Database


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "lightning.db")
    yield database
    database.close()


@pytest.fixture()
def student(db):
    return db.ensure_default_student()


def _payload(**overrides):
    payload = {
        "title": "A quick lesson",
        "activities": [{"minutes": 10}, {"minutes": 5}],
        "estimated_minutes": 15,
        "subject_credits": [{"subject": "math", "minutes": 15, "justification": ""}],
    }
    payload.update(overrides)
    return payload


def test_generates_one_short_lesson_into_the_backlog(db, student):
    with patch("compass.agents.framework.generate_lesson", side_effect=lambda **k: _payload()):
        result = lightning.generate_lightning_lesson(
            db, student, "math", topic="Negative exponents", minutes=15,
        )
    lesson = db.get_lesson(result.lesson_id)
    assert lesson["agent"] == "math"
    assert lesson["metadata"].get("lightning") is True
    # Lands in the Backlog (held_back), no day assigned -- schedule it from the Board.
    assert lesson["metadata"].get("held_back") is True
    assert not lesson["metadata"].get("planned_for")


def test_a_single_lesson_skips_the_multi_day_planner(db, student):
    # If the planner were called it would need its own mock; target_days=1 must
    # avoid it, so mocking only the day-writer is enough.
    with patch("compass.agents.framework.generate_lesson", side_effect=lambda **k: _payload()):
        result = lightning.generate_lightning_lesson(db, student, "science", topic="Cells")
    assert db.get_lesson(result.lesson_id)["metadata"].get("series_total") == 1


def test_the_parents_instructions_reach_the_writer(db, student):
    seen = {}
    with patch(
        "compass.agents.framework.generate_lesson",
        side_effect=lambda **k: seen.update(k) or _payload(),
    ):
        lightning.generate_lightning_lesson(
            db, student, "english", topic="Commas in a series",
            instructions="Use sports examples he'll like.",
        )
    prompt = seen.get("user_prompt", "")
    assert "Commas in a series" in prompt
    assert "sports examples" in prompt          # the editable instructions steer it
    assert "LIGHTNING SHORT" in prompt          # and the fixed brevity directive


def test_rejects_a_bad_subject_or_empty_topic(db, student):
    with pytest.raises(ValueError):
        lightning.generate_lightning_lesson(db, student, "art_music", topic="Color")
    with pytest.raises(ValueError):
        lightning.generate_lightning_lesson(db, student, "math", topic="   ")


def test_agent_for_subject_maps_khan_subjects_to_writers():
    assert lightning.agent_for_subject("math") == "math"
    assert lightning.agent_for_subject("reading") == "english"
    assert lightning.agent_for_subject("social_studies") == "history"
    assert lightning.agent_for_subject("health") is None          # no writer -> no spin-off


def test_spinoff_seed_prompt_names_the_skill():
    seed = lightning.spinoff_seed_prompt("Negative exponents")
    assert "Negative exponents" in seed and "companion" in seed.lower()


def test_a_spin_off_lesson_links_back_to_its_khan_skill(db, student):
    link = {"khan_lesson_id": 42, "skill": "Negative exponents", "unit": "Exponents", "course_id": "kc1"}
    with patch("compass.agents.framework.generate_lesson", side_effect=lambda **k: _payload()):
        result = lightning.generate_lightning_lesson(
            db, student, "math", topic="Negative exponents",
            instructions="Companion to his Khan practice.", link=link,
        )
    meta = db.get_lesson(result.lesson_id)["metadata"]
    assert meta.get("lightning") is True
    assert meta.get("spun_off_from") == link          # the layer is trackable
