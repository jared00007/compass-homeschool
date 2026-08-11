"""Storage-layer behaviour that the rest of the app depends on."""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta

import pytest

from compass import config
from compass.storage.db import LIFE_SKILL_CATALOG, Database


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


def test_migrate_carries_old_park_visits_into_travel_entries(db, student):
    """park_visits (park-only, no story) predates the state-first travel
    journal -- a family already running the old tracker has real rows in it
    that must survive the switch to travel_entries, not vanish."""
    db.conn.execute(
        "CREATE TABLE park_visits (id INTEGER PRIMARY KEY, student_id INTEGER, "
        "park_key TEXT, visited_on TEXT, created_at TEXT DEFAULT (datetime('now')))"
    )
    db.conn.execute(
        "INSERT INTO park_visits (student_id, park_key, visited_on) VALUES (?, ?, ?)",
        (student["id"], "glacier", "2025-06-10"),
    )
    db.conn.commit()
    db.migrate()
    entries = db.list_travel_entries(student["id"])
    assert len(entries) == 1
    assert entries[0]["state"] == "Montana"
    assert entries[0]["park_key"] == "glacier"
    tables = {
        row[0] for row in db.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert "park_visits" not in tables


def test_migrate_carries_old_interests_string_into_the_list(db, student):
    """students.interests used to be one free-text blob -- a family with
    existing text there must not lose it when the column is retired."""
    db.conn.execute("ALTER TABLE students ADD COLUMN interests TEXT NOT NULL DEFAULT ''")
    db.conn.execute(
        "UPDATE students SET interests = ? WHERE id = ?",
        ("Legos, Minecraft, filmmaking", student["id"]),
    )
    db.conn.commit()
    db.migrate()
    interests = db.list_interests(student["id"])
    assert [i["text"] for i in interests] == ["Legos", "Minecraft", "filmmaking"]
    columns = {row["name"] for row in db.conn.execute("PRAGMA table_info(students)")}
    assert "interests" not in columns


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


def test_delete_lesson_removes_a_planned_lesson(db, student):
    """The escape hatch for an accidental double-generate: a planned lesson
    nobody wants shouldn't have to live forever."""
    lesson_id = db.save_lesson(
        student["id"], "english", "reading", "topic", "title", payload={"a": 1}
    )
    db.delete_lesson(lesson_id)
    assert db.get_lesson(lesson_id) is None


def test_deleting_a_logged_lessons_activity_keeps_its_hours(db, student):
    """A lesson can be deleted even after it's been logged -- the activity
    (and its hours/credit) survives; it just loses the back-link, per
    `activities.lesson_id`'s `ON DELETE SET NULL`."""
    lesson_id = db.save_lesson(
        student["id"], "math", "math", "topic", "title", payload={"a": 1}
    )
    db.log_activity(
        student_id=student["id"],
        title="title",
        tier=config.TIER_CORE,
        primary_subject="math",
        minutes=45,
        subject_credits={"math": 45},
        lesson_id=lesson_id,
    )
    db.delete_lesson(lesson_id)
    activity = db.list_activities(student["id"])[0]
    assert activity["minutes"] == 45
    assert activity["lesson_id"] is None


def test_a_state_can_have_more_than_one_travel_entry(db, student):
    """One row per trip, not per state -- a return trip gets its own entry."""
    db.add_travel_entry(student["id"], "Wyoming", "2023-07-04", title="First time at Yellowstone")
    db.add_travel_entry(student["id"], "Wyoming", "2025-06-10", title="Back again")
    entries = db.list_travel_entries(student["id"])
    assert len(entries) == 2
    assert {e["visited_on"] for e in entries} == {"2023-07-04", "2025-06-10"}


def test_travel_entry_park_key_is_optional(db, student):
    """The entry's required scope is the state -- a trip with no park visit
    still gets a real entry, just with no park_key attached."""
    db.add_travel_entry(student["id"], "Montana", "2024-08-01", title="Just passing through")
    entry = db.list_travel_entries(student["id"])[0]
    assert entry["state"] == "Montana"
    assert entry["park_key"] is None


def test_travel_entries_are_most_recent_first(db, student):
    db.add_travel_entry(student["id"], "Utah", "2022-01-01", park_key="zion")
    db.add_travel_entry(student["id"], "California", "2024-01-01", park_key="yosemite")
    entries = db.list_travel_entries(student["id"])
    assert [e["park_key"] for e in entries] == ["yosemite", "zion"]


def test_delete_travel_entry_removes_only_that_entry(db, student):
    keep_id = db.add_travel_entry(student["id"], "Utah", "2022-01-01", park_key="zion")
    remove_id = db.add_travel_entry(student["id"], "Utah", "2024-01-01", park_key="zion")
    db.delete_travel_entry(remove_id)
    remaining = db.list_travel_entries(student["id"])
    assert len(remaining) == 1
    assert remaining[0]["id"] == keep_id


def test_update_travel_entry_changes_only_the_given_fields(db, student):
    """A parent fixing a typo'd state shouldn't have to retype the story too."""
    entry_id = db.add_travel_entry(
        student["id"], "Texas", "2024-06-15", title="Red Rock Everywhere", story="Hiked all day.", park_key="zion"
    )
    db.update_travel_entry(entry_id, state="Utah")
    entry = db.list_travel_entries(student["id"])[0]
    assert entry["state"] == "Utah"
    assert entry["title"] == "Red Rock Everywhere"
    assert entry["story"] == "Hiked all day."
    assert entry["park_key"] == "zion"


def test_update_travel_entry_can_clear_the_park_link(db, student):
    entry_id = db.add_travel_entry(student["id"], "Montana", "2024-06-15", park_key="glacier")
    db.update_travel_entry(entry_id, park_key=None)
    entry = db.list_travel_entries(student["id"])[0]
    assert entry["park_key"] is None


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
    """Every catalog skill ships with a written mission and a "you'll need"
    list, not blank fields -- the card has nothing to show otherwise."""
    db.seed_life_skills(student["id"])
    skills = db.list_life_skills(student["id"])
    assert len(skills) >= 150
    assert all(s["description"] for s in skills)
    assert all(s["materials"] for s in skills)


def test_the_original_fifteen_seed_active_and_the_rest_locked(db, student):
    """A brand-new checklist shouldn't dump a year's worth of content on the
    student at once, but shouldn't start empty either -- the original
    fifteen unlock immediately, the rest wait for a parent to release them."""
    db.seed_life_skills(student["id"])
    skills = db.list_life_skills(student["id"])
    assert sum(1 for s in skills if s["active"]) == 15
    assert sum(1 for s in skills if not s["active"]) == len(skills) - 15


def test_set_life_skill_active_toggles_visibility_without_touching_completion(db, student):
    skill_id = db.add_life_skill(student["id"], "Sew a button", "Sewing")
    db.set_life_skill_done(skill_id, True)
    db.set_life_skill_active(skill_id, False)
    skill = next(s for s in db.list_life_skills(student["id"]) if s["id"] == skill_id)
    assert skill["active"] == 0
    assert skill["completed_on"] is not None


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


def test_growing_up_category_exists_locked_by_default_and_credits_health():
    """A parent picks the pace here more deliberately than anywhere else in
    the catalog -- nothing in this category should land pre-unlocked."""
    growing_up = [entry for entry in LIFE_SKILL_CATALOG if entry[0] == "Growing Up"]
    assert len(growing_up) >= 5
    for category, title, credit_subject, description, materials, active in growing_up:
        assert active is False, title
        assert credit_subject == "health", title
        assert description and materials


def test_a_checklist_seeded_before_the_catalog_grew_gets_topped_up(db, student):
    """A family that already ran `seed_life_skills` before the master catalog
    grew past the original fifteen would otherwise never see the later
    additions, active or not -- `seed_life_skills` only fires once."""
    db.seed_life_skills(student["id"])
    # Simulate a pre-expansion checklist: drop everything not in the original 15
    # (the catalog's first 15 entries, active by default).
    original_titles = tuple(title for _, title, *_, active in LIFE_SKILL_CATALOG if active)
    placeholders = ",".join("?" for _ in original_titles)
    db.conn.execute(
        f"DELETE FROM life_skills WHERE student_id = ? AND title NOT IN ({placeholders})",
        (student["id"], *original_titles),
    )
    db.conn.commit()
    assert len(db.list_life_skills(student["id"])) == 15

    db._backfill_life_skill_catalog()

    skills = db.list_life_skills(student["id"])
    assert len(skills) == len(LIFE_SKILL_CATALOG)
    new_arrival = next(s for s in skills if s["title"] == "Lock down your privacy settings")
    assert new_arrival["active"] == 0
    # The 15 that were already there keep whatever state they had -- the
    # backfill only ever inserts what's missing, never touches existing rows.
    original = next(s for s in skills if s["title"] == "Do laundry start to finish")
    assert original["active"] == 1


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
    db.update_student(student["id"], name="Sam", grade="8", age=13)
    reloaded = db.get_student(student["id"])
    assert reloaded["name"] == "Sam"
    assert reloaded["age"] == 13

    db.update_student(student["id"], grade="9")
    reloaded = db.get_student(student["id"])
    assert reloaded["grade"] == "9"
    assert reloaded["name"] == "Sam", "an unrelated field must not be reset"


def test_add_list_and_delete_interests(db, student):
    """Each interest is its own row -- add a few, remove one, the rest survive."""
    first_id = db.add_interest(student["id"], "Legos")
    db.add_interest(student["id"], "Minecraft")
    interests = db.list_interests(student["id"])
    assert [i["text"] for i in interests] == ["Legos", "Minecraft"]
    assert db.interests_text(student["id"]) == "Legos, Minecraft"

    db.delete_interest(first_id)
    remaining = db.list_interests(student["id"])
    assert [i["text"] for i in remaining] == ["Minecraft"]


def test_interests_text_is_empty_for_a_student_with_none(db, student):
    assert db.interests_text(student["id"]) == ""


def test_checking_in_twice_the_same_day_updates_not_duplicates(db, student):
    db.save_journal_entry(student["id"], "2026-08-11", "Frustrated", "Math was hard.")
    db.save_journal_entry(student["id"], "2026-08-11", "Calm", "Feeling better now.")
    entries = db.list_journal_entries(student["id"])
    assert len(entries) == 1
    assert entries[0]["feeling"] == "Calm"
    assert entries[0]["note"] == "Feeling better now."


def test_journal_entries_are_most_recent_first(db, student):
    db.save_journal_entry(student["id"], "2026-08-09", "Good", "")
    db.save_journal_entry(student["id"], "2026-08-11", "Tired", "")
    db.save_journal_entry(student["id"], "2026-08-10", "Sad", "")
    entries = db.list_journal_entries(student["id"])
    assert [e["entry_date"] for e in entries] == ["2026-08-11", "2026-08-10", "2026-08-09"]


def test_journal_entry_for_date_finds_it_or_returns_none(db, student):
    db.save_journal_entry(student["id"], "2026-08-11", "Angry", "")
    assert db.journal_entry_for_date(student["id"], "2026-08-11")["feeling"] == "Angry"
    assert db.journal_entry_for_date(student["id"], "2026-08-01") is None


def test_delete_journal_entry_removes_only_that_entry(db, student):
    remove_id = db.save_journal_entry(student["id"], "2026-08-10", "Good", "")
    db.save_journal_entry(student["id"], "2026-08-11", "Calm", "")
    db.delete_journal_entry(remove_id)
    remaining = db.list_journal_entries(student["id"])
    assert len(remaining) == 1
    assert remaining[0]["entry_date"] == "2026-08-11"


def test_update_student_ignores_unknown_fields(db, student):
    """The sidebar form only ever sends the three real columns, but the method
    itself should refuse to become a general-purpose SQL injection point."""
    db.update_student(student["id"], name="Sam", is_admin=True, agent="root")
    reloaded = db.get_student(student["id"])
    assert reloaded["name"] == "Sam"
    assert "is_admin" not in reloaded and "agent" not in reloaded


def test_update_student_with_no_recognised_fields_is_a_no_op(db, student):
    before = db.get_student(student["id"])
    db.update_student(student["id"])
    assert db.get_student(student["id"]) == before
