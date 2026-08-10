"""Storage-layer behaviour that the rest of the app depends on."""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta

import pytest

from compass import config
from compass.storage.db import Database


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    yield database
    database.close()


@pytest.fixture()
def student(db):
    return db.ensure_default_student()


def test_migrate_is_idempotent(tmp_path):
    path = tmp_path / "twice.db"
    first = Database(path)
    first.create_student("Sam", "8")
    first.close()
    second = Database(path)
    assert len(second.list_students()) == 1
    second.close()


def test_settings_fall_back_to_defaults(db):
    assert db.get_int_setting("annual_hour_target") == config.WA_ANNUAL_HOURS
    db.set_setting("annual_hour_target", "1100")
    assert db.get_int_setting("annual_hour_target") == 1100


def test_school_year_bounds_wrap_correctly(db):
    db.set_setting("school_year_start", "09-01")
    start, end = db.school_year_bounds(date(2026, 3, 15))
    assert start == "2025-09-01"
    assert end == "2026-08-31"

    start, end = db.school_year_bounds(date(2026, 9, 1))
    assert start == "2026-09-01"
    assert end == "2027-08-31"


def test_logging_an_activity_defaults_credit_to_the_primary_subject(db, student):
    activity_id = db.log_activity(
        student_id=student["id"],
        title="Math",
        tier=config.TIER_CORE,
        primary_subject="math",
        minutes=45,
        subject_credits={},
    )
    assert activity_id
    activity = db.list_activities(student["id"])[0]
    assert activity["credits"] == {"math": 45}


def test_logging_a_lesson_marks_it_completed(db, student):
    lesson_id = db.save_lesson(
        student["id"], "math", "math", "topic", "title", payload={"a": 1}
    )
    assert db.get_lesson(lesson_id)["status"] == "planned"
    db.log_activity(
        student_id=student["id"],
        title="title",
        tier=config.TIER_CORE,
        primary_subject="math",
        minutes=45,
        subject_credits={"math": 45},
        lesson_id=lesson_id,
    )
    assert db.get_lesson(lesson_id)["status"] == "completed"


def test_mark_student_done_stamps_metadata_without_touching_status(db, student):
    lesson_id = db.save_lesson(
        student["id"], "math", "math", "topic", "title", payload={"a": 1}
    )
    db.mark_student_done(lesson_id)
    lesson = db.get_lesson(lesson_id)
    assert lesson["metadata"]["student_done_on"] == date.today().isoformat()
    assert lesson["status"] == "planned"  # the parent's hour-logging status, untouched


def test_mark_student_done_preserves_other_metadata(db, student):
    """It must not clobber skill_id or other strategy metadata already stored
    there -- json_set only touches the one key it's given."""
    lesson_id = db.save_lesson(
        student["id"], "math", "math", "topic", "title",
        payload={"a": 1}, metadata={"skill_id": "two_step_equations"},
    )
    db.mark_student_done(lesson_id)
    lesson = db.get_lesson(lesson_id)
    assert lesson["metadata"]["skill_id"] == "two_step_equations"
    assert lesson["metadata"]["student_done_on"] == date.today().isoformat()


def test_zero_minute_activity_is_rejected(db, student):
    with pytest.raises(ValueError):
        db.log_activity(
            student_id=student["id"],
            title="Nothing",
            tier=config.TIER_CORE,
            primary_subject="math",
            minutes=0,
            subject_credits={"math": 0},
        )


def test_deleting_an_activity_removes_its_credits(db, student):
    activity_id = db.log_activity(
        student_id=student["id"],
        title="Science",
        tier=config.TIER_CORE,
        primary_subject="science",
        minutes=60,
        subject_credits={"science": 60, "writing": 20},
    )
    db.delete_activity(activity_id)
    remaining = db.conn.execute(
        "SELECT COUNT(*) AS n FROM activity_subject_credits"
    ).fetchone()["n"]
    assert remaining == 0


def test_leitner_promotes_on_correct_and_resets_on_miss(db, student):
    db.add_vocabulary(student["id"], "prudent", "careful")
    entry = db.list_vocabulary(student["id"])[0]
    assert entry["box"] == 1

    db.record_vocabulary_review(entry["id"], correct=True)
    entry = db.list_vocabulary(student["id"])[0]
    assert entry["box"] == 2
    assert entry["next_review_on"] == (date.today() + timedelta(days=3)).isoformat()

    db.record_vocabulary_review(entry["id"], correct=False)
    entry = db.list_vocabulary(student["id"])[0]
    assert entry["box"] == 1
    assert entry["times_missed"] == 1


def test_leitner_box_is_capped_at_five(db, student):
    db.add_vocabulary(student["id"], "prudent", "careful")
    entry_id = db.list_vocabulary(student["id"])[0]["id"]
    for _ in range(10):
        db.record_vocabulary_review(entry_id, correct=True)
    assert db.list_vocabulary(student["id"])[0]["box"] == 5


def test_adding_a_known_word_again_does_not_reset_progress(db, student):
    db.add_vocabulary(student["id"], "prudent", "careful")
    entry_id = db.list_vocabulary(student["id"])[0]["id"]
    db.record_vocabulary_review(entry_id, correct=True)
    db.add_vocabulary(student["id"], "prudent", "careful and sensible")

    entries = db.list_vocabulary(student["id"])
    assert len(entries) == 1
    assert entries[0]["box"] == 2, "re-adding a word must not wipe its review history"
    assert entries[0]["definition"] == "careful and sensible"


def test_life_skills_seed_only_once(db, student):
    first = db.seed_life_skills(student["id"])
    second = db.seed_life_skills(student["id"])
    assert first > 0
    assert second == 0


def test_life_skills_are_seeded_with_real_mission_and_materials_text(db, student):
    """Every starter skill ships with a written mission and a "you'll need"
    list, not blank fields -- the card has nothing to show otherwise."""
    db.seed_life_skills(student["id"])
    skills = db.list_life_skills(student["id"])
    assert len(skills) == 15
    assert all(s["description"] for s in skills)
    assert all(s["materials"] for s in skills)


def test_a_database_created_before_the_materials_column_gets_migrated(tmp_path):
    """`materials` shipped after some real databases already existed. Since
    `CREATE TABLE IF NOT EXISTS` only ever fires on a table's first creation,
    an existing life_skills table needs the column added out-of-band -- this
    pins that `migrate()` does it instead of silently leaving old databases
    without the column the card's "you'll need" line reads from."""
    path = tmp_path / "pre_materials.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE life_skills ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, student_id INTEGER NOT NULL, "
        "category TEXT NOT NULL DEFAULT 'General', title TEXT NOT NULL, "
        "description TEXT NOT NULL DEFAULT '', "
        "credit_subject TEXT NOT NULL DEFAULT 'occupational_education', "
        "completed_on TEXT, notes TEXT NOT NULL DEFAULT '', "
        "sort_order INTEGER NOT NULL DEFAULT 0, "
        "created_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    conn.execute("INSERT INTO life_skills (student_id, title) VALUES (1, 'Old skill')")
    conn.commit()
    conn.close()

    migrated = Database(path)
    try:
        skill = migrated.conn.execute("SELECT * FROM life_skills").fetchone()
        assert skill["materials"] == ""
        migrated.set_life_skill_done(skill["id"], True)
    finally:
        migrated.close()


def test_a_checklist_seeded_before_mission_text_existed_gets_backfilled(db, student):
    """A checklist seeded in an earlier build (blank description/materials,
    since `seed_life_skills` only ever inserts once per student) must pick up
    the real mission text on the next launch rather than showing "No mission
    notes yet" forever -- reported after exactly that happened live."""
    db.conn.execute(
        "INSERT INTO life_skills (student_id, category, title, credit_subject) "
        "VALUES (?, 'Money', 'Build and follow a monthly budget', 'occupational_education')",
        (student["id"],),
    )
    db.conn.commit()

    db._backfill_life_skill_content()

    skill = db.list_life_skills(student["id"])[0]
    assert skill["description"].startswith("Figure out what money")
    assert "pencil and paper" in skill["materials"]


def test_backfill_never_overwrites_a_parents_own_edit(db, student):
    skill_id = db.add_life_skill(
        student["id"], "Build and follow a monthly budget", "Money",
        description="Our family's own version of this.",
    )
    db._backfill_life_skill_content()
    skill = next(s for s in db.list_life_skills(student["id"]) if s["id"] == skill_id)
    assert skill["description"] == "Our family's own version of this."


def test_unexplored_web_nodes_prefer_the_current_location(db, student):
    db.add_web_node(student["id"], "science", "desert varnish", location="Moab", depth=2)
    db.add_web_node(student["id"], "science", "salmon runs", location="Hoh River", depth=3)
    nodes = db.unexplored_web_nodes(student["id"], "science", location="Hoh River")
    assert nodes[0]["topic"] == "salmon runs", "location match beats shallower depth"


def test_update_student_changes_only_the_named_fields(db, student):
    db.update_student(student["id"], name="Sam", grade="8", age=13, interests="guitar")
    reloaded = db.get_student(student["id"])
    assert reloaded["name"] == "Sam"
    assert reloaded["interests"] == "guitar"

    db.update_student(student["id"], grade="9")
    reloaded = db.get_student(student["id"])
    assert reloaded["grade"] == "9"
    assert reloaded["name"] == "Sam", "an unrelated field must not be reset"


def test_update_student_ignores_unknown_fields(db, student):
    """The sidebar form only ever sends the four real columns, but the method
    itself should refuse to become a general-purpose SQL injection point."""
    db.update_student(student["id"], name="Sam", is_admin=True, agent="root")
    reloaded = db.get_student(student["id"])
    assert reloaded["name"] == "Sam"
    assert "is_admin" not in reloaded and "agent" not in reloaded


def test_update_student_with_no_recognised_fields_is_a_no_op(db, student):
    before = db.get_student(student["id"])
    db.update_student(student["id"])
    assert db.get_student(student["id"]) == before
