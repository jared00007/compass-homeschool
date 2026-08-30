"""Storage-layer behaviour that the rest of the app depends on."""

from __future__ import annotations

import sqlite3
import threading
import time
from datetime import date, timedelta

import pytest

from compass import config
from compass.storage.db import BIG_PROJECT_CATALOG, LIFE_SKILL_CATALOG, Database


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


def test_migrate_interests_is_idempotent_even_if_drop_column_is_unsupported(db, student):
    """On a SQLite build too old for DROP COLUMN, the ALTER silently no-ops
    (caught in _migrate_interests_string_to_list) and the `interests` column
    sticks around forever. migrate() runs on every app start, so without its
    own idempotency guard (blanking the column's *content*, not relying on
    the DROP to have removed it), the same leftover blob would get re-split
    and re-inserted into student_interests on every single restart.

    This sandbox's SQLite is new enough that the DROP always succeeds, so
    the failure is reproduced directly instead: put the column back exactly
    as the migration would have left it had the DROP silently failed
    (present, but already blanked out by that same run) and migrate again."""
    db.conn.execute("ALTER TABLE students ADD COLUMN interests TEXT NOT NULL DEFAULT ''")
    db.conn.execute(
        "UPDATE students SET interests = ? WHERE id = ?",
        ("Legos, Minecraft", student["id"]),
    )
    db.conn.commit()
    db._migrate_interests_string_to_list()

    db.conn.execute("ALTER TABLE students ADD COLUMN interests TEXT NOT NULL DEFAULT ''")
    db.conn.commit()
    db._migrate_interests_string_to_list()  # a second app start, DROP still "failing"

    interests = db.list_interests(student["id"])
    assert sorted(i["text"] for i in interests) == ["Legos", "Minecraft"]


def test_migrate_drops_old_journal_entries_unique_constraint(db, student):
    """journal_entries originally had UNIQUE (student_id, entry_date), which
    forced a second same-day check-in to silently overwrite the first.
    Existing rows saved under that constraint must survive being freed from
    it, and the freed table must actually accept a second same-day row after."""
    db.conn.execute("DROP TABLE journal_entries")
    db.conn.execute(
        "CREATE TABLE journal_entries (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "student_id INTEGER NOT NULL, entry_date TEXT NOT NULL, feeling TEXT NOT NULL, "
        "note TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT (datetime('now')), "
        "UNIQUE (student_id, entry_date))"
    )
    db.conn.execute(
        "INSERT INTO journal_entries (student_id, entry_date, feeling, note) VALUES (?, ?, ?, ?)",
        (student["id"], "2026-08-11", "Angry", "old row"),
    )
    db.conn.commit()
    db.migrate()
    entries = db.list_journal_entries(student["id"])
    assert len(entries) == 1
    assert entries[0]["note"] == "old row"
    db.save_journal_entry(student["id"], "2026-08-11", "Calm", "second check-in")
    assert len(db.list_journal_entries(student["id"])) == 2


def test_migrate_rebuilds_activities_to_allow_projects_tier(db, student):
    """activities.tier had a CHECK constraint that predates the Big Projects
    tier -- existing logged hours must survive the rebuild, foreign keys
    from activity_subject_credits must still resolve afterward, and a
    'projects'-tier activity must actually be insertable once it's done."""
    db.conn.execute("DROP TABLE activities")
    db.conn.execute(
        "CREATE TABLE activities (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "student_id INTEGER NOT NULL, lesson_id INTEGER, title TEXT NOT NULL, "
        "description TEXT NOT NULL DEFAULT '', "
        "tier TEXT NOT NULL CHECK (tier IN ('core', 'folded', 'choice', 'life_skills')), "
        "primary_subject TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'manual', "
        "minutes INTEGER NOT NULL CHECK (minutes > 0), occurred_on TEXT NOT NULL, "
        "location TEXT NOT NULL DEFAULT '', "
        "created_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    old_id = db.conn.execute(
        "INSERT INTO activities (student_id, title, tier, primary_subject, minutes, occurred_on) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (student["id"], "Old-style logged hours", "core", "math", 30, "2026-08-01"),
    ).lastrowid
    db.conn.execute(
        "INSERT INTO activity_subject_credits (activity_id, subject, minutes) VALUES (?, ?, ?)",
        (old_id, "math", 30),
    )
    db.conn.commit()

    db.migrate()

    activities = _list(db, "activities", student["id"])
    assert len(activities) == 1
    assert activities[0]["title"] == "Old-style logged hours"
    credits = db.conn.execute(
        "SELECT * FROM activity_subject_credits WHERE activity_id = ?", (old_id,)
    ).fetchall()
    assert len(credits) == 1  # the foreign key still resolves to the rebuilt row

    # the whole point: a 'projects'-tier row must now actually insert
    new_id = db.log_activity(
        student_id=student["id"],
        title="Stop-Motion Lego Film — Pick your story",
        tier=config.TIER_PROJECTS,
        primary_subject="writing",
        minutes=30,
        subject_credits={"writing": 30},
    )
    assert new_id > 0
    # foreign key enforcement is still live post-migration
    with pytest.raises(sqlite3.IntegrityError):
        db.conn.execute(
            "INSERT INTO activity_subject_credits (activity_id, subject, minutes) "
            "VALUES (?, ?, ?)",
            (999999, "math", 10),
        )
        db.conn.commit()


def test_migrate_upgrades_activities_already_allowing_projects_to_also_allow_wellness(db, student):
    """A database migrated mid-session (Big Projects added, Morning Routine
    not yet) has a CHECK constraint listing 'projects' but not 'wellness'.
    The guard must key off 'wellness' specifically, not bail out early just
    because 'projects' is already there, or a 'wellness'-tier row would
    never be insertable for a family sitting in that in-between state."""
    db.conn.execute("DROP TABLE activities")
    db.conn.execute(
        "CREATE TABLE activities (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "student_id INTEGER NOT NULL, lesson_id INTEGER, title TEXT NOT NULL, "
        "description TEXT NOT NULL DEFAULT '', "
        "tier TEXT NOT NULL CHECK (tier IN "
        "('core', 'folded', 'choice', 'life_skills', 'projects')), "
        "primary_subject TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'manual', "
        "minutes INTEGER NOT NULL CHECK (minutes > 0), occurred_on TEXT NOT NULL, "
        "location TEXT NOT NULL DEFAULT '', "
        "created_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    db.conn.commit()

    db.migrate()

    new_id = db.log_activity(
        student_id=student["id"],
        title="Morning routine — Box Breathing",
        tier=config.TIER_WELLNESS,
        primary_subject="health",
        minutes=3,
        subject_credits={"health": 3},
    )
    assert new_id > 0


def test_migrate_rebuilds_books_to_allow_upcoming_status(db, student):
    """books.status/term predate the two-books-per-year split -- an old-style
    row (no term column, status CHECK missing 'upcoming') must survive the
    rebuild, and vocabulary.source_book_id's foreign key must still resolve
    to it afterward."""
    db.conn.execute("DROP TABLE books")
    db.conn.execute(
        "CREATE TABLE books (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "student_id INTEGER NOT NULL, title TEXT NOT NULL, "
        "author TEXT NOT NULL DEFAULT '', reading_level TEXT NOT NULL DEFAULT '', "
        "total_pages INTEGER, current_page INTEGER NOT NULL DEFAULT 0, "
        "status TEXT NOT NULL DEFAULT 'reading' "
        "CHECK (status IN ('reading', 'finished', 'abandoned')), "
        "started_on TEXT, finished_on TEXT, notes TEXT NOT NULL DEFAULT '', "
        "created_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    old_id = db.conn.execute(
        "INSERT INTO books (student_id, title, status, started_on) "
        "VALUES (?, ?, ?, ?)",
        (student["id"], "Old-style book", "reading", "2026-08-01"),
    ).lastrowid
    db.conn.execute(
        "INSERT INTO vocabulary (student_id, word, source_book_id, next_review_on) "
        "VALUES (?, ?, ?, date('now'))",
        (student["id"], "resilient", old_id),
    )
    db.conn.commit()

    db.migrate()

    books = _list(db, "books", student["id"])
    assert len(books) == 1
    assert books[0]["title"] == "Old-style book"
    assert books[0]["term"] is None  # new column, backfilled to NULL
    # Regression: this rebuild used to run *before* the ai_summary column got
    # added, and rebuilds from its own hardcoded column list -- silently
    # dropping any column added ahead of it in migrate() on a database old
    # enough to actually need this rebuild.
    assert books[0]["ai_summary"] == ""

    word = db.list_vocabulary(student["id"])[0]
    assert word["source_book_id"] == old_id  # the foreign key still resolves

    # the whole point: an 'upcoming'-status row must now actually insert
    new_id = db.add_book(student["id"], "New book", term="second_half", status="upcoming")
    assert new_id > 0
    assert db.upcoming_book(student["id"])["id"] == new_id


def _list(db, table, student_id):
    return [dict(r) for r in db.conn.execute(f"SELECT * FROM {table} WHERE student_id = ?", (student_id,))]


def test_save_and_get_district_document_round_trips(db, student):
    db.save_district_document(student["id"], "declaration_packet", "packet.pdf", b"%PDF-fake-bytes")
    doc = db.get_district_document(student["id"], "declaration_packet")
    assert doc["filename"] == "packet.pdf"
    assert doc["content"] == b"%PDF-fake-bytes"
    assert doc["content_type"] == "application/pdf"


def test_get_district_document_is_none_when_nothing_uploaded(db, student):
    assert db.get_district_document(student["id"], "declaration_packet") is None


def test_uploading_again_replaces_rather_than_duplicates(db, student):
    db.save_district_document(student["id"], "declaration_packet", "old.pdf", b"old")
    db.save_district_document(student["id"], "declaration_packet", "new.pdf", b"new")
    doc = db.get_district_document(student["id"], "declaration_packet")
    assert doc["filename"] == "new.pdf"
    assert doc["content"] == b"new"
    rows = db.conn.execute(
        "SELECT COUNT(*) FROM district_documents WHERE student_id = ?", (student["id"],)
    ).fetchone()[0]
    assert rows == 1


def test_delete_district_document_removes_it(db, student):
    db.save_district_document(student["id"], "declaration_packet", "packet.pdf", b"x")
    db.delete_district_document(student["id"], "declaration_packet")
    assert db.get_district_document(student["id"], "declaration_packet") is None


def test_migrate_upgrades_a_blank_declaration_url_to_the_real_default(db, student):
    """declaration_url predates knowing the family's district -- an existing
    database has it seeded blank, and INSERT OR IGNORE alone won't touch an
    existing row, so migrate() needs its own upgrade path."""
    db.set_setting("declaration_url", "")
    db.migrate()
    assert db.get_setting("declaration_url") == config.DEFAULT_SETTINGS["declaration_url"]


def test_migrate_never_overwrites_a_parents_own_declaration_url(db, student):
    db.set_setting("declaration_url", "https://my-actual-district.example")
    db.migrate()
    assert db.get_setting("declaration_url") == "https://my-actual-district.example"


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


def test_school_year_midpoint_is_halfway_between_the_bounds(db):
    db.set_setting("school_year_start", "09-01")
    midpoint = db.school_year_midpoint(date(2026, 9, 1))
    start, end = db.school_year_bounds(date(2026, 9, 1))
    start_date, end_date = date.fromisoformat(start), date.fromisoformat(end)
    assert midpoint == start_date + (end_date - start_date) / 2

    # shifts automatically if the family adjusts their actual start date
    db.set_setting("school_year_start", "08-24")
    earlier_midpoint = db.school_year_midpoint(date(2026, 8, 24))
    assert earlier_midpoint < midpoint


def test_book_term_split_queues_a_second_half_book_without_making_it_current(db, student):
    first_id = db.add_book(student["id"], "Hatchet", term="first_half")
    second_id = db.add_book(
        student["id"], "The Giver", term="second_half", status="upcoming"
    )

    current = db.current_book(student["id"])
    assert current["id"] == first_id
    assert current["term"] == "first_half"

    upcoming = db.upcoming_book(student["id"])
    assert upcoming["id"] == second_id
    assert upcoming["term"] == "second_half"
    assert upcoming["started_on"] is None  # not started yet


def test_promote_upcoming_book_finishes_the_old_one_and_starts_the_new_one(db, student):
    first_id = db.add_book(student["id"], "Hatchet", term="first_half")
    second_id = db.add_book(
        student["id"], "The Giver", term="second_half", status="upcoming"
    )

    db.promote_upcoming_book(student["id"], second_id)

    books = {b["id"]: b for b in db.list_books(student["id"])}
    assert books[first_id]["status"] == "finished"
    assert books[first_id]["finished_on"] is not None
    assert books[second_id]["status"] == "reading"
    assert books[second_id]["started_on"] is not None
    assert db.current_book(student["id"])["id"] == second_id
    assert db.upcoming_book(student["id"]) is None


def test_book_with_no_term_behaves_exactly_as_before(db, student):
    book_id = db.add_book(student["id"], "Hatchet")
    book = db.list_books(student["id"])[0]
    assert book["id"] == book_id
    assert book["term"] is None
    assert book["status"] == "reading"
    assert db.current_book(student["id"])["id"] == book_id


def test_friday_plan_items_are_scoped_to_one_exact_date(db, student):
    db.add_friday_plan_item(student["id"], "2026-08-28", "big_project")
    db.add_friday_plan_item(student["id"], "2026-09-04", "travel_new")

    this_friday = db.list_friday_plan_items(student["id"], "2026-08-28")
    assert len(this_friday) == 1
    assert this_friday[0]["kind"] == "big_project"
    assert this_friday[0]["label"] == ""


def test_friday_plan_items_keep_insertion_order(db, student):
    first_id = db.add_friday_plan_item(student["id"], "2026-08-28", "travel_catchup", "5 trips")
    second_id = db.add_friday_plan_item(student["id"], "2026-08-28", "custom", "Guitar practice")

    items = db.list_friday_plan_items(student["id"], "2026-08-28")
    assert [i["id"] for i in items] == [first_id, second_id]


def test_delete_friday_plan_item_removes_only_that_one(db, student):
    keep_id = db.add_friday_plan_item(student["id"], "2026-08-28", "big_project")
    remove_id = db.add_friday_plan_item(student["id"], "2026-08-28", "custom", "Guitar")

    db.delete_friday_plan_item(remove_id)

    items = db.list_friday_plan_items(student["id"], "2026-08-28")
    assert [i["id"] for i in items] == [keep_id]


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


def test_reschedule_lesson_moves_planned_for_and_week_start(db, student):
    """The Backlog release valve: content and status stay put, only the
    two date fields that decide where a lesson lives move -- both of
    them, since a stale week_start would leave the moved lesson invisible
    to This Week's "already covered" check for its new week."""
    lesson_id = db.save_lesson(
        student["id"], "math", "math", "topic", "title", payload={"a": 1},
        metadata={"planned_for": "2026-01-05", "week_start": "2025-12-29"},
    )
    db.reschedule_lesson(lesson_id, "2026-02-16")  # a Monday
    lesson = db.get_lesson(lesson_id)
    assert lesson["metadata"]["planned_for"] == "2026-02-16"
    assert lesson["metadata"]["week_start"] == "2026-02-16"
    assert lesson["status"] == "planned"
    assert lesson["payload"] == {"a": 1}


def test_reschedule_lesson_snaps_week_start_to_the_targets_own_monday(db, student):
    """Moving into the middle of a week (not onto its Monday) still tags
    the lesson with that week's real Monday, not the target date itself --
    otherwise it wouldn't match up with anything else planned for that
    same week."""
    lesson_id = db.save_lesson(
        student["id"], "math", "math", "topic", "title", payload={"a": 1},
        metadata={"planned_for": "2026-01-05", "week_start": "2025-12-29"},
    )
    db.reschedule_lesson(lesson_id, "2026-02-19")  # a Thursday
    lesson = db.get_lesson(lesson_id)
    assert lesson["metadata"]["planned_for"] == "2026-02-19"
    assert lesson["metadata"]["week_start"] == "2026-02-16"  # that week's Monday


def test_reschedule_lesson_clears_held_back(db, student):
    """Moving a manually-backlogged lesson to a new day releases it the
    exact same way an automatically-backlogged one gets released --
    regardless of which path put it in the backlog to begin with."""
    lesson_id = db.save_lesson(
        student["id"], "math", "math", "topic", "title", payload={"a": 1},
        metadata={"planned_for": "2026-01-05", "week_start": "2025-12-29", "held_back": True},
    )
    db.reschedule_lesson(lesson_id, "2026-02-16")
    assert "held_back" not in db.get_lesson(lesson_id)["metadata"]


def test_reschedule_lesson_on_a_missing_id_is_a_no_op(db, student):
    db.reschedule_lesson(999999, "2026-02-16")  # doesn't raise


def test_send_to_backlog_sets_held_back(db, student):
    """A parent's own "not this week" call, any lesson, any day -- the
    manual counterpart to a whole week quietly running out on its own."""
    lesson_id = db.save_lesson(
        student["id"], "math", "math", "topic", "title", payload={"a": 1},
        metadata={"planned_for": "2026-08-31", "week_start": "2026-08-31"},
    )
    db.send_to_backlog(lesson_id)
    lesson = db.get_lesson(lesson_id)
    assert lesson["metadata"]["held_back"] is True
    # Untouched -- this is purely a visibility flag, not a reschedule.
    assert lesson["metadata"]["planned_for"] == "2026-08-31"
    assert lesson["status"] == "planned"


def test_send_to_backlog_on_a_missing_id_is_a_no_op(db, student):
    db.send_to_backlog(999999)  # doesn't raise


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


def test_add_travel_entry_accepts_favorite_moment_and_would_return(db, student):
    db.add_travel_entry(
        student["id"], "Wyoming", "2025-06-10", title="Yellowstone",
        favorite_moment="Watching Old Faithful erupt right on schedule.",
        would_return="Yes, in the fall next time.",
    )
    entry = db.list_travel_entries(student["id"])[0]
    assert entry["favorite_moment"] == "Watching Old Faithful erupt right on schedule."
    assert entry["would_return"] == "Yes, in the fall next time."


def test_add_travel_entry_defaults_favorite_moment_and_would_return_to_blank(db, student):
    db.add_travel_entry(student["id"], "Wyoming", "2025-06-10", title="Yellowstone")
    entry = db.list_travel_entries(student["id"])[0]
    assert entry["favorite_moment"] == ""
    assert entry["would_return"] == ""


def test_update_travel_entry_can_set_favorite_moment_and_would_return(db, student):
    entry_id = db.add_travel_entry(student["id"], "Wyoming", "2025-06-10", title="Yellowstone")
    db.update_travel_entry(
        entry_id, favorite_moment="The bison traffic jam.", would_return="Definitely."
    )
    entry = db.list_travel_entries(student["id"])[0]
    assert entry["favorite_moment"] == "The bison traffic jam."
    assert entry["would_return"] == "Definitely."


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


# --- the travel journal's review gate + assignment, mirroring life_skills ------


def test_add_travel_entry_defaults_to_completed(db, student):
    """Every existing caller (and every pre-existing row) has to keep
    reading as already-done -- the gate only ever engages for an entry the
    journal page deliberately marks otherwise."""
    entry_id = db.add_travel_entry(student["id"], "Wyoming", "2025-06-10", title="Yellowstone")
    entry = db.list_travel_entries(student["id"])[0]
    assert entry["id"] == entry_id
    assert entry["status"] == "completed"


def test_submit_travel_entry_sets_status(db, student):
    entry_id = db.add_travel_entry(
        student["id"], "Wyoming", "2025-06-10", title="Yellowstone", status="planned"
    )
    db.submit_travel_entry(entry_id)
    entry = db.list_travel_entries(student["id"])[0]
    assert entry["status"] == "submitted"


def test_send_travel_entry_back_stores_the_note(db, student):
    entry_id = db.add_travel_entry(
        student["id"], "Wyoming", "2025-06-10", title="Yellowstone", status="submitted"
    )
    db.send_travel_entry_back(entry_id, "more detail on what you actually did there")
    entry = db.list_travel_entries(student["id"])[0]
    assert entry["status"] == "needs_revision"
    assert entry["revision_note"] == "more detail on what you actually did there"


def test_approve_travel_entry_completes_it_and_logs_the_flat_credit(db, student):
    entry_id = db.add_travel_entry(
        student["id"], "Wyoming", "2025-06-10", title="Yellowstone",
        story="We watched Old Faithful erupt.", status="submitted",
    )
    db.approve_travel_entry(entry_id)
    entry = db.list_travel_entries(student["id"])[0]
    assert entry["status"] == "completed"

    activities = db.list_activities(student["id"])
    assert len(activities) == 1
    assert activities[0]["source"] == "travel_journal"
    assert activities[0]["minutes"] == (
        config.TRAVEL_JOURNAL_WRITING_MINUTES + config.TRAVEL_JOURNAL_SOCIAL_STUDIES_MINUTES
    )


def test_approve_travel_entry_can_store_optional_feedback(db, student):
    entry_id = db.add_travel_entry(
        student["id"], "Wyoming", "2025-06-10", title="Yellowstone",
        story="We watched Old Faithful erupt.", status="submitted",
    )
    db.approve_travel_entry(entry_id, "Great detail about the geyser!")
    entry = db.list_travel_entries(student["id"])[0]
    assert entry["status"] == "completed"
    assert entry["parent_feedback"] == "Great detail about the geyser!"


def test_approve_travel_entry_defaults_feedback_to_blank(db, student):
    entry_id = db.add_travel_entry(
        student["id"], "Wyoming", "2025-06-10", title="Yellowstone",
        story="We watched Old Faithful erupt.", status="submitted",
    )
    db.approve_travel_entry(entry_id)
    entry = db.list_travel_entries(student["id"])[0]
    assert entry["parent_feedback"] == ""


# --- Whether he's actually acknowledged feedback, not just that it exists -------


def test_approving_with_feedback_leaves_it_unread(db, student):
    entry_id = db.add_travel_entry(
        student["id"], "Wyoming", "2025-06-10", title="Yellowstone",
        story="We watched Old Faithful erupt.", status="submitted",
    )
    db.approve_travel_entry(entry_id, "Great detail about the geyser!")
    entry = db.list_travel_entries(student["id"])[0]
    assert entry["feedback_read_at"] is None
    assert [e["id"] for e in db.unread_travel_feedback(student["id"])] == [entry_id]


def test_marking_feedback_read_clears_it_from_unread(db, student):
    entry_id = db.add_travel_entry(
        student["id"], "Wyoming", "2025-06-10", title="Yellowstone",
        story="We watched Old Faithful erupt.", status="submitted",
    )
    db.approve_travel_entry(entry_id, "Great detail about the geyser!")
    db.mark_travel_feedback_read(entry_id, "I need to use commas in lists.")
    entry = db.list_travel_entries(student["id"])[0]
    assert entry["feedback_read_at"] is not None
    assert entry["feedback_reply"] == "I need to use commas in lists."
    assert db.unread_travel_feedback(student["id"]) == []


def test_unread_travel_feedback_excludes_entries_with_no_feedback(db, student):
    db.add_travel_entry(
        student["id"], "Wyoming", "2025-06-10", title="Yellowstone",
        story="We watched Old Faithful erupt.", status="completed",
    )
    assert db.unread_travel_feedback(student["id"]) == []


def test_set_travel_entry_feedback_marks_it_unread_again_when_changed(db, student):
    """The whole point of editing feedback after the fact -- fixing lost
    formatting or rewording it -- is that he sees the corrected version,
    not the stale one he may have already read."""
    entry_id = db.add_travel_entry(
        student["id"], "Wyoming", "2025-06-10", title="Yellowstone",
        story="We watched Old Faithful erupt.", status="submitted",
    )
    db.approve_travel_entry(entry_id, "flattened one line version")
    db.mark_travel_feedback_read(entry_id, "I need to use commas in lists.")
    assert db.unread_travel_feedback(student["id"]) == []

    db.set_travel_entry_feedback(entry_id, "Line one.\n\nLine two, fixed.")
    entry = db.list_travel_entries(student["id"])[0]
    assert entry["parent_feedback"] == "Line one.\n\nLine two, fixed."
    assert entry["feedback_read_at"] is None
    # His old reply was about the old text -- clearing along with read state.
    assert entry["feedback_reply"] == ""
    assert [e["id"] for e in db.unread_travel_feedback(student["id"])] == [entry_id]


def test_set_travel_entry_feedback_leaves_read_state_alone_when_unchanged(db, student):
    """Saving the rest of an edit (state, story) without touching feedback
    shouldn't re-flag something he already read."""
    entry_id = db.add_travel_entry(
        student["id"], "Wyoming", "2025-06-10", title="Yellowstone",
        story="We watched Old Faithful erupt.", status="submitted",
    )
    db.approve_travel_entry(entry_id, "Great detail!")
    db.mark_travel_feedback_read(entry_id, "I need to use commas in lists.")

    db.set_travel_entry_feedback(entry_id, "Great detail!")
    entry = db.list_travel_entries(student["id"])[0]
    assert entry["feedback_read_at"] is not None
    assert db.unread_travel_feedback(student["id"]) == []


def test_scheduling_a_travel_entry_makes_it_due_on_and_after_that_day(db, student):
    entry_id = db.add_travel_entry(
        student["id"], "Wyoming", "2025-06-10", title="Yellowstone", status="planned"
    )
    db.schedule_travel_entry(entry_id, "2026-08-24")
    assert db.due_travel_entries(student["id"], "2026-08-23") == []
    assert [e["id"] for e in db.due_travel_entries(student["id"], "2026-08-24")] == [entry_id]
    assert [e["id"] for e in db.due_travel_entries(student["id"], "2026-08-30")] == [entry_id]


def test_assign_open_travel_entries_creates_blank_stubs_due_that_day(db, student):
    """"Assign him to pick" -- unlike scheduling one specific trip, there's
    no destination decided yet, so each stub gets no state or title."""
    ids = db.assign_open_travel_entries(student["id"], 2, "2026-08-24")
    assert len(ids) == 2
    entries = {e["id"]: e for e in db.list_travel_entries(student["id"])}
    for entry_id in ids:
        entry = entries[entry_id]
        assert entry["state"] == ""
        assert entry["title"] == ""
        assert entry["status"] == "planned"
        assert entry["scheduled_for"] == "2026-08-24"
    due_ids = {e["id"] for e in db.due_travel_entries(student["id"], "2026-08-24")}
    assert due_ids == set(ids)


def test_due_travel_entries_includes_submitted_and_needs_revision_not_just_planned(db, student):
    """He shouldn't see a submitted trip as if it silently vanished --
    Home's marker distinguishes the states, but all three still count as
    "still needs attention from someone" until actually approved."""
    today = date.today().isoformat()
    submitted_id = db.add_travel_entry(
        student["id"], "Wyoming", today, title="Submitted trip", status="submitted"
    )
    db.schedule_travel_entry(submitted_id, today)
    revision_id = db.add_travel_entry(
        student["id"], "Montana", today, title="Needs revision", status="needs_revision"
    )
    db.schedule_travel_entry(revision_id, today)

    due_ids = {e["id"] for e in db.due_travel_entries(student["id"], today)}
    assert due_ids == {submitted_id, revision_id}


def test_approving_a_scheduled_travel_entry_clears_it_from_due(db, student):
    today = date.today().isoformat()
    entry_id = db.add_travel_entry(
        student["id"], "Wyoming", today, title="Yellowstone", status="submitted"
    )
    db.schedule_travel_entry(entry_id, today)
    assert len(db.due_travel_entries(student["id"], today)) == 1
    db.approve_travel_entry(entry_id)
    assert db.due_travel_entries(student["id"], today) == []


def test_upcoming_travel_entries_excludes_today_and_past_but_includes_the_future(db, student):
    today = "2026-08-24"
    yesterday_id = db.add_travel_entry(
        student["id"], "Wyoming", today, title="Yesterday", status="planned"
    )
    db.schedule_travel_entry(yesterday_id, "2026-08-23")
    today_id = db.add_travel_entry(
        student["id"], "Wyoming", today, title="Today", status="planned"
    )
    db.schedule_travel_entry(today_id, today)
    tomorrow_id = db.add_travel_entry(
        student["id"], "Wyoming", today, title="Tomorrow", status="planned"
    )
    db.schedule_travel_entry(tomorrow_id, "2026-08-25")

    upcoming = db.upcoming_travel_entries(student["id"], today)
    assert [e["id"] for e in upcoming] == [tomorrow_id]


def test_travel_entries_for_week_covers_monday_through_friday_only(db, student):
    monday_id = db.add_travel_entry(
        student["id"], "Wyoming", "2026-08-24", title="Monday trip", status="planned"
    )
    db.schedule_travel_entry(monday_id, "2026-08-24")
    friday_id = db.add_travel_entry(
        student["id"], "Wyoming", "2026-08-28", title="Friday trip", status="planned"
    )
    db.schedule_travel_entry(friday_id, "2026-08-28")
    next_monday_id = db.add_travel_entry(
        student["id"], "Wyoming", "2026-08-31", title="Next Monday trip", status="planned"
    )
    db.schedule_travel_entry(next_monday_id, "2026-08-31")
    unscheduled_id = db.add_travel_entry(
        student["id"], "Wyoming", "2026-08-24", title="Unscheduled", status="planned"
    )

    week = db.travel_entries_for_week(student["id"], "2026-08-24")
    assert {e["id"] for e in week} == {monday_id, friday_id}
    assert unscheduled_id not in {e["id"] for e in week}


def test_travel_entries_for_week_includes_completed_entries(db, student):
    """The Week grid shows the whole week's plan, done or not."""
    entry_id = db.add_travel_entry(
        student["id"], "Wyoming", "2026-08-24", title="Yellowstone", status="submitted"
    )
    db.schedule_travel_entry(entry_id, "2026-08-24")
    db.approve_travel_entry(entry_id)

    week = db.travel_entries_for_week(student["id"], "2026-08-24")
    assert [e["id"] for e in week] == [entry_id]
    assert week[0]["status"] == "completed"


def test_a_database_created_before_the_travel_review_gate_columns_gets_migrated(tmp_path):
    """A family's existing travel_entries table predates status/
    scheduled_for/revision_note -- old rows have to read as 'completed'
    (nothing to retroactively review) rather than break or silently need
    review out of nowhere."""
    path = tmp_path / "pre_gate.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE travel_entries ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, student_id INTEGER NOT NULL, "
        "state TEXT NOT NULL, park_key TEXT, title TEXT NOT NULL DEFAULT '', "
        "story TEXT NOT NULL DEFAULT '', favorite_moment TEXT NOT NULL DEFAULT '', "
        "would_return TEXT NOT NULL DEFAULT '', visited_on TEXT NOT NULL, "
        "created_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    conn.execute(
        "INSERT INTO travel_entries (student_id, state, title, visited_on) "
        "VALUES (1, 'Wyoming', 'Old entry', '2020-01-01')"
    )
    conn.commit()
    conn.close()

    migrated = Database(path)
    try:
        entry = migrated.conn.execute("SELECT * FROM travel_entries").fetchone()
        assert entry["status"] == "completed"
        assert entry["scheduled_for"] is None
        assert entry["revision_note"] == ""
        assert entry["parent_feedback"] == ""
        migrated.schedule_travel_entry(entry["id"], "2026-08-24")
    finally:
        migrated.close()


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


# --- Coding Camp: same shape as Core Life Skills, its own catalog ---------------


def test_coding_modules_seed_only_once(db, student):
    first = db.seed_coding_modules(student["id"])
    second = db.seed_coding_modules(student["id"])
    assert first > 0
    assert second == 0


def test_coding_modules_are_seeded_with_real_idea_and_materials_text(db, student):
    db.seed_coding_modules(student["id"])
    modules = db.list_coding_modules(student["id"])
    assert len(modules) >= 15
    assert all(m["description"] for m in modules)
    assert all(m["materials"] for m in modules)
    assert all(m["credit_subject"] for m in modules)


def test_add_coding_module_defaults_to_occupational_education(db, student):
    module_id = db.add_coding_module(student["id"], "Build a text adventure")
    module = db.list_coding_modules(student["id"])[0]
    assert module["id"] == module_id
    assert module["credit_subject"] == "occupational_education"
    assert module["active"] == 1


def test_set_coding_module_active_toggles_visibility_without_touching_completion(db, student):
    module_id = db.add_coding_module(student["id"], "Build a text adventure")
    db.set_coding_module_done(module_id, True)
    db.set_coding_module_active(module_id, False)
    module = next(m for m in db.list_coding_modules(student["id"]) if m["id"] == module_id)
    assert module["active"] == 0
    assert module["completed_on"] is not None


def test_schedule_coding_module_unlocks_it(db, student):
    module_id = db.add_coding_module(student["id"], "Build a text adventure")
    db.set_coding_module_active(module_id, False)
    db.schedule_coding_module(module_id, date.today().isoformat())
    module = next(m for m in db.list_coding_modules(student["id"]) if m["id"] == module_id)
    assert module["active"] == 1
    assert module["scheduled_for"] == date.today().isoformat()


def test_due_coding_modules_excludes_completed_and_locked(db, student):
    today = date.today().isoformat()
    due_id = db.add_coding_module(student["id"], "Due today")
    db.schedule_coding_module(due_id, today)

    done_id = db.add_coding_module(student["id"], "Already done")
    db.schedule_coding_module(done_id, today)
    db.set_coding_module_done(done_id, True)

    locked_id = db.add_coding_module(student["id"], "Re-locked")
    db.schedule_coding_module(locked_id, today)
    db.set_coding_module_active(locked_id, False)

    due = db.due_coding_modules(student["id"], today)
    assert [m["id"] for m in due] == [due_id]


def test_upcoming_coding_modules_only_includes_the_future(db, student):
    today = date.today().isoformat()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    today_id = db.add_coding_module(student["id"], "Due today")
    db.schedule_coding_module(today_id, today)
    future_id = db.add_coding_module(student["id"], "Due tomorrow")
    db.schedule_coding_module(future_id, tomorrow)

    upcoming = db.upcoming_coding_modules(student["id"], today)
    assert [m["id"] for m in upcoming] == [future_id]


def test_delete_coding_module_removes_it(db, student):
    module_id = db.add_coding_module(student["id"], "Build a text adventure")
    db.delete_coding_module(module_id)
    assert db.list_coding_modules(student["id"]) == []


def test_backfill_coding_module_catalog_tops_up_missing_entries_as_locked(db, student):
    """Same reasoning as the Life Skills catalog top-up: a family that
    seeded before the catalog grew still gets the newer modules, but always
    locked -- a parent who already curated their active set didn't ask for
    anything new to suddenly appear."""
    from compass.storage.db import CODING_MODULE_CATALOG

    first_title = CODING_MODULE_CATALOG[0][1]
    db.add_coding_module(student["id"], first_title)

    db._backfill_coding_module_catalog()

    modules = db.list_coding_modules(student["id"])
    assert len(modules) == len(CODING_MODULE_CATALOG)
    new_ones = [m for m in modules if m["title"] != first_title]
    assert new_ones
    assert all(m["active"] == 0 for m in new_ones)


def test_a_database_created_before_coding_modules_existed_gets_the_table(tmp_path):
    """`coding_modules` shipped after some real databases already existed --
    `CREATE TABLE IF NOT EXISTS` in schema.sql covers this on its own (no
    ALTER needed, it's a brand-new table), but a family's existing
    `activities.tier` CHECK constraint predates 'coding' and needs the
    table-rebuild migration to actually accept it."""
    path = tmp_path / "pre_coding.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE students (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, "
        "grade TEXT NOT NULL DEFAULT '', age INTEGER)"
    )
    conn.execute("INSERT INTO students (id, name) VALUES (1, 'Old Student')")
    conn.execute(
        "CREATE TABLE activities ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, student_id INTEGER NOT NULL, "
        "lesson_id INTEGER, title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', "
        "tier TEXT NOT NULL CHECK (tier IN "
        "('core', 'folded', 'choice', 'life_skills', 'projects', 'wellness')), "
        "primary_subject TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'manual', "
        "minutes INTEGER NOT NULL CHECK (minutes > 0), occurred_on TEXT NOT NULL, "
        "location TEXT NOT NULL DEFAULT '', "
        "created_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    conn.execute(
        "INSERT INTO activities (student_id, title, tier, primary_subject, minutes, occurred_on) "
        "VALUES (1, 'Old activity', 'core', 'math', 30, '2025-01-01')"
    )
    conn.commit()
    conn.close()

    migrated = Database(path)
    try:
        old_activity = migrated.conn.execute(
            "SELECT * FROM activities WHERE title = 'Old activity'"
        ).fetchone()
        assert old_activity["tier"] == "core"  # untouched by the rebuild
        migrated.log_activity(
            student_id=1, title="New coding activity", tier="coding",
            primary_subject="occupational_education", minutes=30,
            subject_credits={"occupational_education": 30}, occurred_on="2025-01-02",
            source="coding",
        )
        module_id = migrated.add_coding_module(1, "Build a text adventure")
        assert migrated.list_coding_modules(1)[0]["id"] == module_id
    finally:
        migrated.close()


# --- Choice Topics: the same active/backlog gate life_skills already has --------


def test_add_choice_topic_defaults_to_active(db, student):
    """Unlike lessons/project_steps, this feature never hid anything before
    the `active` column existed -- a freshly proposed topic stays exactly
    as visible as it always was."""
    topic_id = db.add_choice_topic(student["id"], "Learn guitar chords")
    topic = db.list_choice_topics(student["id"])[0]
    assert topic["id"] == topic_id
    assert topic["active"] == 1


def test_add_choice_topic_can_start_backlogged(db, student):
    db.add_choice_topic(student["id"], "Learn guitar chords", active=False)
    assert db.list_choice_topics(student["id"])[0]["active"] == 0


def test_set_choice_topic_active_toggles_without_touching_status(db, student):
    topic_id = db.add_choice_topic(student["id"], "Learn guitar chords")
    db.set_choice_status(topic_id, "approved")
    db.set_choice_topic_active(topic_id, False)
    topic = db.list_choice_topics(student["id"])[0]
    assert topic["active"] == 0
    assert topic["status"] == "approved"
    db.set_choice_topic_active(topic_id, True)
    topic = db.list_choice_topics(student["id"])[0]
    assert topic["active"] == 1
    assert topic["status"] == "approved"


def test_a_database_created_before_the_choice_topic_active_column_gets_migrated(tmp_path):
    """`active` shipped after some real databases already existed, with
    choice topics a student could already see. The migration backfills it
    to 1 for every pre-existing row -- an already-visible topic must not
    suddenly vanish into the Backlog the moment this column gets added."""
    path = tmp_path / "pre_active.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE choice_topics ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, student_id INTEGER NOT NULL, "
        "title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', "
        "category TEXT NOT NULL DEFAULT '', "
        "credit_subject TEXT NOT NULL DEFAULT 'occupational_education', "
        "status TEXT NOT NULL DEFAULT 'proposed', "
        "proposed_on TEXT NOT NULL DEFAULT (date('now')), "
        "decided_on TEXT, parent_note TEXT NOT NULL DEFAULT '')"
    )
    conn.execute("INSERT INTO choice_topics (student_id, title) VALUES (1, 'Old topic')")
    conn.commit()
    conn.close()

    migrated = Database(path)
    try:
        topic = migrated.conn.execute("SELECT * FROM choice_topics").fetchone()
        assert topic["active"] == 1
    finally:
        migrated.close()


def test_scheduling_a_life_skill_makes_it_due_on_and_after_that_day(db, student):
    skill_id = db.add_life_skill(student["id"], "Change a tire", "Vehicle")
    db.schedule_life_skill(skill_id, "2026-08-24")
    assert db.due_life_skills(student["id"], "2026-08-23") == []
    assert [s["id"] for s in db.due_life_skills(student["id"], "2026-08-24")] == [skill_id]
    assert [s["id"] for s in db.due_life_skills(student["id"], "2026-08-30")] == [skill_id]


def test_scheduling_a_locked_skill_unlocks_it(db, student):
    """Otherwise a skill could show as due on Home while linking to a
    checklist page that hides it for being locked -- see
    schedule_life_skill's docstring."""
    skill_id = db.add_life_skill(student["id"], "Read a map", "Navigation")
    db.set_life_skill_active(skill_id, False)
    db.schedule_life_skill(skill_id, date.today().isoformat())
    skill = next(s for s in db.list_life_skills(student["id"]) if s["id"] == skill_id)
    assert skill["active"] == 1


def test_relocking_an_assigned_skill_removes_it_from_due(db, student):
    skill_id = db.add_life_skill(student["id"], "Sew a button", "Sewing")
    today = date.today().isoformat()
    db.schedule_life_skill(skill_id, today)
    db.set_life_skill_active(skill_id, False)
    assert db.due_life_skills(student["id"], today) == []


def test_clearing_a_schedule_does_not_relock_the_skill(db, student):
    skill_id = db.add_life_skill(student["id"], "Read a map", "Navigation")
    db.set_life_skill_active(skill_id, False)
    db.schedule_life_skill(skill_id, date.today().isoformat())
    db.schedule_life_skill(skill_id, None)
    skill = next(s for s in db.list_life_skills(student["id"]) if s["id"] == skill_id)
    assert skill["active"] == 1


def test_upcoming_life_skills_excludes_todays_and_pasts_but_includes_the_future(db, student):
    yesterday = db.add_life_skill(student["id"], "Change a tire", "Vehicle")
    db.schedule_life_skill(yesterday, "2026-08-23")
    today_skill = db.add_life_skill(student["id"], "Sew a button", "Sewing")
    db.schedule_life_skill(today_skill, "2026-08-24")
    tomorrow = db.add_life_skill(student["id"], "Read a map", "Navigation")
    db.schedule_life_skill(tomorrow, "2026-08-25")

    upcoming = db.upcoming_life_skills(student["id"], "2026-08-24")
    assert [s["id"] for s in upcoming] == [tomorrow]


def test_upcoming_life_skills_excludes_completed_and_relocked_ones(db, student):
    tomorrow = "2026-08-25"
    done = db.add_life_skill(student["id"], "Bake bread", "Cooking")
    db.schedule_life_skill(done, tomorrow)
    db.set_life_skill_done(done, True)

    relocked = db.add_life_skill(student["id"], "Read a map", "Navigation")
    db.schedule_life_skill(relocked, tomorrow)
    db.set_life_skill_active(relocked, False)

    assert db.upcoming_life_skills(student["id"], "2026-08-24") == []


def test_life_skills_for_week_covers_monday_through_friday_only(db, student):
    monday = db.add_life_skill(student["id"], "Change a tire", "Vehicle")
    db.schedule_life_skill(monday, "2026-08-24")
    friday = db.add_life_skill(student["id"], "Sew a button", "Sewing")
    db.schedule_life_skill(friday, "2026-08-28")
    next_monday = db.add_life_skill(student["id"], "Read a map", "Navigation")
    db.schedule_life_skill(next_monday, "2026-08-31")
    unscheduled = db.add_life_skill(student["id"], "Bake bread", "Cooking")

    week = db.life_skills_for_week(student["id"], "2026-08-24")
    assert {s["id"] for s in week} == {monday, friday}
    assert unscheduled not in {s["id"] for s in week}


def test_life_skills_for_week_includes_completed_skills(db, student):
    """The Week grid shows the whole week's plan, done or not -- a finished
    skill should still show, marked done, not just drop off the grid."""
    skill_id = db.add_life_skill(student["id"], "Change a tire", "Vehicle")
    db.schedule_life_skill(skill_id, "2026-08-24")
    db.set_life_skill_done(skill_id, True)

    week = db.life_skills_for_week(student["id"], "2026-08-24")
    assert [s["id"] for s in week] == [skill_id]
    assert week[0]["completed_on"] is not None


def test_an_unscheduled_life_skill_never_shows_up_as_due(db, student):
    """The default (no `scheduled_for`) has to keep behaving exactly like it
    always did -- a family that never assigns a day shouldn't see anything
    new show up anywhere."""
    db.add_life_skill(student["id"], "Bake bread", "Cooking")
    assert db.due_life_skills(student["id"], date.today().isoformat()) == []


def test_completing_a_scheduled_life_skill_clears_it_from_due(db, student):
    skill_id = db.add_life_skill(student["id"], "Balance a checkbook", "Budgeting")
    today = date.today().isoformat()
    db.schedule_life_skill(skill_id, today)
    assert len(db.due_life_skills(student["id"], today)) == 1
    db.set_life_skill_done(skill_id, True)
    assert db.due_life_skills(student["id"], today) == []


def test_clearing_a_skills_schedule_removes_it_from_due(db, student):
    skill_id = db.add_life_skill(student["id"], "Write a resume", "Work")
    today = date.today().isoformat()
    db.schedule_life_skill(skill_id, today)
    db.schedule_life_skill(skill_id, None)
    assert db.due_life_skills(student["id"], today) == []


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
        assert skill["scheduled_for"] is None
        migrated.set_life_skill_done(skill["id"], True)
        migrated.schedule_life_skill(skill["id"], "2026-08-24")
    finally:
        migrated.close()


def test_a_database_created_before_the_step_active_column_gets_migrated(tmp_path):
    """`active` shipped after some real databases already existed, with
    project steps a parent could already see. The migration backfills it
    to 1 for every pre-existing row -- an already-visible step must not
    suddenly vanish into the Backlog the moment this column gets added."""
    path = tmp_path / "pre_active.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE big_projects ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, student_id INTEGER NOT NULL, "
        "title TEXT NOT NULL, vision TEXT NOT NULL DEFAULT '', "
        "sort_order INTEGER NOT NULL DEFAULT 0, "
        "created_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    conn.execute("INSERT INTO big_projects (id, student_id, title) VALUES (1, 1, 'Old project')")
    conn.execute(
        "CREATE TABLE project_steps ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL, "
        "sort_order INTEGER NOT NULL DEFAULT 0, title TEXT NOT NULL, "
        "description TEXT NOT NULL DEFAULT '', materials TEXT NOT NULL DEFAULT '', "
        "credit_subject TEXT NOT NULL DEFAULT 'occupational_education', "
        "min_days INTEGER NOT NULL DEFAULT 1, max_days INTEGER NOT NULL DEFAULT 1, "
        "completed_on TEXT, created_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    conn.execute("INSERT INTO project_steps (project_id, title) VALUES (1, 'Old step')")
    conn.commit()
    conn.close()

    migrated = Database(path)
    try:
        step = migrated.conn.execute("SELECT * FROM project_steps").fetchone()
        assert step["active"] == 1
    finally:
        migrated.close()


def test_a_database_created_before_the_project_kind_column_gets_migrated(tmp_path):
    """`kind` shipped after some real databases already had big_projects rows
    -- every pre-existing project must migrate in as an ordinary 'steps'
    project, not the new 'travel_log' kind, or its step list would suddenly
    stop rendering."""
    path = tmp_path / "pre_kind.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE big_projects ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, student_id INTEGER NOT NULL, "
        "title TEXT NOT NULL, vision TEXT NOT NULL DEFAULT '', "
        "sort_order INTEGER NOT NULL DEFAULT 0, "
        "created_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    conn.execute("INSERT INTO big_projects (student_id, title) VALUES (1, 'Old project')")
    conn.commit()
    conn.close()

    migrated = Database(path)
    try:
        project = migrated.conn.execute("SELECT * FROM big_projects").fetchone()
        assert project["kind"] == "steps"
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


def test_checking_in_twice_the_same_day_keeps_both(db, student):
    db.save_journal_entry(student["id"], "2026-08-11", "Frustrated", "Math was hard.")
    db.save_journal_entry(student["id"], "2026-08-11", "Calm", "Feeling better now.")
    entries = db.list_journal_entries(student["id"])
    assert len(entries) == 2
    assert entries[0]["feeling"] == "Calm"
    assert entries[0]["note"] == "Feeling better now."
    assert entries[1]["feeling"] == "Frustrated"


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


def test_journal_entry_for_date_returns_the_most_recent_of_several(db, student):
    db.save_journal_entry(student["id"], "2026-08-11", "Angry", "")
    db.save_journal_entry(student["id"], "2026-08-11", "Calm", "")
    assert db.journal_entry_for_date(student["id"], "2026-08-11")["feeling"] == "Calm"


def test_delete_journal_entry_removes_only_that_entry(db, student):
    remove_id = db.save_journal_entry(student["id"], "2026-08-10", "Good", "")
    db.save_journal_entry(student["id"], "2026-08-11", "Calm", "")
    db.delete_journal_entry(remove_id)
    remaining = db.list_journal_entries(student["id"])
    assert len(remaining) == 1
    assert remaining[0]["entry_date"] == "2026-08-11"


def test_seed_big_projects_adds_the_catalog_once(db, student):
    added = db.seed_big_projects(student["id"])
    assert added == 3
    projects = db.list_big_projects(student["id"])
    titles = {p["title"] for p in projects}
    assert titles == {"Stop-Motion Lego Film", "Mini Podcast Series", "Toy Photography"}
    for project in projects:
        steps = db.list_project_steps(project["id"])
        assert len(steps) >= 10
        assert all(s["credit_subject"] for s in steps)
        assert all(s["description"] for s in steps)
    # Seeding again is a no-op -- a family that already has projects (or
    # deleted the starter ones on purpose) never gets them pushed back on them.
    assert db.seed_big_projects(student["id"]) == 0
    assert len(db.list_big_projects(student["id"])) == 3


def test_seed_big_projects_still_seeds_when_only_the_travel_log_project_exists(db, student):
    """The Travel Log project (see ensure_travel_log_project) is always
    present from a student's very first page view now -- it must never
    itself count as "already has projects," or the starter-catalog button
    would silently do nothing for every family from day one."""
    db.ensure_travel_log_project(student["id"])

    added = db.seed_big_projects(student["id"])

    assert added == 3
    kinds = {p["kind"] for p in db.list_big_projects(student["id"])}
    assert kinds == {"steps", "travel_log"}


def test_backfill_big_project_catalog_ignores_the_travel_log_project(db, student):
    """Same reasoning as the seeding test above -- the automatic Travel Log
    row must not itself satisfy "this family already has something, top up
    what's missing," or every family would get the entire starter catalog
    injected unasked the moment that column exists."""
    db.ensure_travel_log_project(student["id"])

    db._backfill_big_project_catalog()

    projects = db.list_big_projects(student["id"])
    assert len(projects) == 1
    assert projects[0]["kind"] == "travel_log"


def test_backfill_big_project_catalog_tops_up_new_catalog_projects(db, student):
    """A family that seeded before the catalog grew (just the Lego film,
    say) must pick up the newer catalog projects on next launch without
    disturbing the one they already have -- same reasoning as the Life
    Skills catalog top-up."""
    lego_title, lego_vision, lego_steps = next(
        p for p in BIG_PROJECT_CATALOG if p[0] == "Stop-Motion Lego Film"
    )
    db._insert_big_project(student["id"], 0, lego_title, lego_vision, lego_steps)
    db.conn.commit()
    project = db.list_big_projects(student["id"])[0]
    step = db.list_project_steps(project["id"])[0]
    db.set_project_step_done(step["id"], True)

    db._backfill_big_project_catalog()

    projects = db.list_big_projects(student["id"])
    titles = {p["title"] for p in projects}
    assert titles == {"Stop-Motion Lego Film", "Mini Podcast Series", "Toy Photography"}
    # the pre-existing project and its progress are untouched
    lego = next(p for p in projects if p["title"] == "Stop-Motion Lego Film")
    assert lego["id"] == project["id"]
    assert db.list_project_steps(lego["id"])[0]["completed_on"] is not None


def test_backfill_big_project_step_content_syncs_revised_catalog_text(db, student):
    """A project seeded before a step's text was revised (more detail added)
    must pick up the new copy on the next launch, without losing whether
    that step was already checked off."""
    db.seed_big_projects(student["id"])
    project = db.list_big_projects(student["id"])[0]
    step = db.list_project_steps(project["id"])[0]
    db.set_project_step_done(step["id"], True)
    db.conn.execute(
        "UPDATE project_steps SET description = 'old short text' WHERE id = ?",
        (step["id"],),
    )
    db.conn.commit()

    db._backfill_big_project_step_content()

    refreshed = db.list_project_steps(project["id"])[0]
    assert refreshed["description"] != "old short text"
    assert "Before you move on" in refreshed["description"]
    assert refreshed["completed_on"] is not None  # still checked off


def test_seeded_steps_carry_a_pace_not_a_deadline(db, student):
    """Every seeded step should have a sane day-range pace (min <= max,
    both positive) -- this is guidance for how long a step should take,
    deliberately not a due date anywhere in the schema."""
    db.seed_big_projects(student["id"])
    for project in db.list_big_projects(student["id"]):
        for step in db.list_project_steps(project["id"]):
            assert step["min_days"] >= 1
            assert step["max_days"] >= step["min_days"]


def test_backfill_big_project_step_content_syncs_revised_pace(db, student):
    db.seed_big_projects(student["id"])
    project = db.list_big_projects(student["id"])[0]
    step = db.list_project_steps(project["id"])[0]
    db.conn.execute(
        "UPDATE project_steps SET min_days = 99, max_days = 99 WHERE id = ?",
        (step["id"],),
    )
    db.conn.commit()

    db._backfill_big_project_step_content()

    refreshed = db.list_project_steps(project["id"])[0]
    assert refreshed["min_days"] != 99
    assert refreshed["max_days"] != 99


def test_add_project_step_appends_in_order(db, student):
    project_id = db.add_big_project(student["id"], "Test Project", "A vision.")
    db.add_project_step(project_id, "Step one", credit_subject="writing")
    db.add_project_step(project_id, "Step two", credit_subject="art_and_music")
    steps = db.list_project_steps(project_id)
    assert [s["title"] for s in steps] == ["Step one", "Step two"]
    assert [s["sort_order"] for s in steps] == [0, 1]


def test_add_project_step_defaults_pace_to_one_day(db, student):
    project_id = db.add_big_project(student["id"], "Test Project", "A vision.")
    step_id = db.add_project_step(project_id, "Step one")
    step = db.list_project_steps(project_id)[0]
    assert step["min_days"] == 1
    assert step["max_days"] == 1


def test_add_project_step_accepts_a_custom_pace(db, student):
    project_id = db.add_big_project(student["id"], "Test Project", "A vision.")
    db.add_project_step(project_id, "Step one", min_days=3, max_days=5)
    step = db.list_project_steps(project_id)[0]
    assert step["min_days"] == 3
    assert step["max_days"] == 5


def test_add_project_step_never_lets_max_fall_below_min(db, student):
    project_id = db.add_big_project(student["id"], "Test Project", "A vision.")
    db.add_project_step(project_id, "Step one", min_days=5, max_days=2)
    step = db.list_project_steps(project_id)[0]
    assert step["min_days"] == 5
    assert step["max_days"] == 5


def test_set_project_step_done_toggles_completed_on(db, student):
    project_id = db.add_big_project(student["id"], "Test Project")
    step_id = db.add_project_step(project_id, "Step one")
    assert db.list_project_steps(project_id)[0]["completed_on"] is None
    db.set_project_step_done(step_id, True)
    assert db.list_project_steps(project_id)[0]["completed_on"] is not None
    db.set_project_step_done(step_id, False)
    assert db.list_project_steps(project_id)[0]["completed_on"] is None


def test_add_project_step_defaults_to_backlog(db, student):
    """A freshly added step -- by hand, or from the AI chunker -- starts
    parked, not immediately committed to the plan. A parent pulls it into
    To Do explicitly."""
    project_id = db.add_big_project(student["id"], "Test Project")
    db.add_project_step(project_id, "Step one")
    assert db.list_project_steps(project_id)[0]["active"] == 0


def test_add_project_step_can_start_in_to_do(db, student):
    project_id = db.add_big_project(student["id"], "Test Project")
    db.add_project_step(project_id, "Step one", active=True)
    assert db.list_project_steps(project_id)[0]["active"] == 1


def test_set_project_step_active_moves_between_backlog_and_to_do(db, student):
    project_id = db.add_big_project(student["id"], "Test Project")
    step_id = db.add_project_step(project_id, "Step one")
    assert db.list_project_steps(project_id)[0]["active"] == 0
    db.set_project_step_active(step_id, True)
    assert db.list_project_steps(project_id)[0]["active"] == 1
    db.set_project_step_active(step_id, False)
    assert db.list_project_steps(project_id)[0]["active"] == 0


def test_set_project_step_active_never_touches_completed_on(db, student):
    """Same reasoning set_life_skill_active gives for its own skill: an
    already-done step's completion record is untouched by this flag."""
    project_id = db.add_big_project(student["id"], "Test Project")
    step_id = db.add_project_step(project_id, "Step one", active=True)
    db.set_project_step_done(step_id, True)
    db.set_project_step_active(step_id, False)
    assert db.list_project_steps(project_id)[0]["completed_on"] is not None


def test_delete_big_project_cascades_to_its_steps(db, student):
    project_id = db.add_big_project(student["id"], "Test Project")
    db.add_project_step(project_id, "Step one")
    db.delete_big_project(project_id)
    assert db.list_project_steps(project_id) == []
    assert db.list_big_projects(student["id"]) == []


def test_set_big_project_shelved_toggles_and_is_reversible(db, student):
    project_id = db.add_big_project(student["id"], "Test Project")
    db.set_big_project_shelved(project_id, True)
    assert db.list_big_projects(student["id"])[0]["shelved"] == 1
    db.set_big_project_shelved(project_id, False)
    assert db.list_big_projects(student["id"])[0]["shelved"] == 0


def test_shelving_a_project_does_not_delete_it(db, student):
    """The whole point: unlike delete_big_project, the row (and its steps)
    survive -- shelving is reversible, delete never was."""
    project_id = db.add_big_project(student["id"], "Test Project")
    db.add_project_step(project_id, "Step one")
    db.set_big_project_shelved(project_id, True)
    assert len(db.list_big_projects(student["id"])) == 1
    assert len(db.list_project_steps(project_id)) == 1


def test_shelved_catalog_projects_do_not_come_back_after_a_restart(db, student):
    """Regression: _backfill_big_project_catalog used to be the only thing
    standing between a deleted catalog project and it reappearing on the
    next migrate(). Shelving instead of deleting fixes this for good --
    the row survives, so the catalog top-up's "is this title already here"
    check correctly finds it and leaves it alone."""
    db.seed_big_projects(student["id"])
    projects = db.list_big_projects(student["id"])
    target = projects[0]
    db.set_big_project_shelved(target["id"], True)

    db._backfill_big_project_catalog()  # what migrate() runs on every restart

    refreshed = db.list_big_projects(student["id"])
    assert len(refreshed) == len(projects), "no duplicate or resurrected row"
    matching = next(p for p in refreshed if p["title"] == target["title"])
    assert matching["shelved"] == 1


def test_shelving_the_active_project_clears_the_active_pick(db, student):
    project_id = db.add_big_project(student["id"], "Test Project")
    db.set_active_big_project(project_id)
    assert db.active_big_project(student["id"]) is not None

    db.set_big_project_shelved(project_id, True)

    assert db.active_big_project(student["id"]) is None


def test_shelving_an_inactive_project_leaves_the_active_pick_alone(db, student):
    active_id = db.add_big_project(student["id"], "Active One")
    other_id = db.add_big_project(student["id"], "Other One")
    db.set_active_big_project(active_id)

    db.set_big_project_shelved(other_id, True)

    active = db.active_big_project(student["id"])
    assert active is not None
    assert active["id"] == active_id


def test_add_big_project_defaults_to_steps_kind(db, student):
    project_id = db.add_big_project(student["id"], "Test Project")
    project = db.list_big_projects(student["id"])[0]
    assert project["id"] == project_id
    assert project["kind"] == "steps"


def test_ensure_travel_log_project_creates_one_project(db, student):
    project_id = db.ensure_travel_log_project(student["id"])
    projects = db.list_big_projects(student["id"])
    assert len(projects) == 1
    assert projects[0]["id"] == project_id
    assert projects[0]["kind"] == "travel_log"


def test_ensure_travel_log_project_is_idempotent(db, student):
    """A parent could click "Fold in the Travel Journal" more than once, or
    rename the project afterward -- neither should spawn a second one, since
    the lookup is by kind rather than by title."""
    first_id = db.ensure_travel_log_project(student["id"])
    db.conn.execute(
        "UPDATE big_projects SET title = ? WHERE id = ?", ("Renamed", first_id)
    )
    db.conn.commit()

    second_id = db.ensure_travel_log_project(student["id"])

    assert second_id == first_id
    assert len(db.list_big_projects(student["id"])) == 1


def test_no_active_big_project_until_one_is_chosen(db, student):
    db.add_big_project(student["id"], "Test Project")
    assert db.active_big_project(student["id"]) is None


def test_active_big_project_returns_the_chosen_one(db, student):
    first_id = db.add_big_project(student["id"], "First")
    db.add_big_project(student["id"], "Second")
    db.set_active_big_project(first_id)
    active = db.active_big_project(student["id"])
    assert active is not None
    assert active["id"] == first_id
    assert active["title"] == "First"


def test_active_big_project_can_be_changed(db, student):
    first_id = db.add_big_project(student["id"], "First")
    second_id = db.add_big_project(student["id"], "Second")
    db.set_active_big_project(first_id)
    db.set_active_big_project(second_id)
    assert db.active_big_project(student["id"])["id"] == second_id


def test_active_big_project_can_be_cleared(db, student):
    project_id = db.add_big_project(student["id"], "Test Project")
    db.set_active_big_project(project_id)
    db.set_active_big_project(None)
    assert db.active_big_project(student["id"]) is None


def test_active_big_project_self_heals_after_deletion(db, student):
    """Deleting the chosen project shouldn't leave a dangling reference --
    the lookup just comes back empty, same as never having picked one."""
    project_id = db.add_big_project(student["id"], "Test Project")
    db.set_active_big_project(project_id)
    db.delete_big_project(project_id)
    assert db.active_big_project(student["id"]) is None


def test_delete_project_step_removes_only_that_step(db, student):
    project_id = db.add_big_project(student["id"], "Test Project")
    keep_id = db.add_project_step(project_id, "Keep me")
    remove_id = db.add_project_step(project_id, "Remove me")
    db.delete_project_step(remove_id)
    remaining = db.list_project_steps(project_id)
    assert len(remaining) == 1
    assert remaining[0]["id"] == keep_id


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


def test_morning_routine_for_date_is_none_before_logging(db, student):
    assert db.morning_routine_for_date(student["id"], "2026-08-12") is None


def test_log_morning_routine_round_trips(db, student):
    db.log_morning_routine(student["id"], "2026-08-12", "box_breathing")
    logged = db.morning_routine_for_date(student["id"], "2026-08-12")
    assert logged["routine_key"] == "box_breathing"


def test_logging_a_second_routine_same_day_replaces_the_first(db, student):
    """Unlike Check-In, a morning routine is one event per day -- picking a
    different one later the same day updates the record rather than
    stacking a second row."""
    db.log_morning_routine(student["id"], "2026-08-12", "box_breathing")
    db.log_morning_routine(student["id"], "2026-08-12", "sun_salutation")
    logged = db.morning_routine_for_date(student["id"], "2026-08-12")
    assert logged["routine_key"] == "sun_salutation"
    rows = db.conn.execute(
        "SELECT COUNT(*) FROM morning_routine_log WHERE student_id = ?", (student["id"],)
    ).fetchone()[0]
    assert rows == 1


def test_morning_routine_log_is_per_student(db, student):
    other_id = db.create_student("Sibling", "5")
    db.log_morning_routine(student["id"], "2026-08-12", "box_breathing")
    assert db.morning_routine_for_date(other_id, "2026-08-12") is None


# --- courses (grades 6-12 credit documentation) -------------------------------


def test_migrate_adds_course_id_to_a_pre_existing_activities_table(db, student):
    """A database that predates Courses has an `activities` table without
    the column -- `CREATE TABLE IF NOT EXISTS` is a no-op against it, so the
    column and its index have to come from `_ensure_column` instead, and
    existing logged hours must survive untouched."""
    db.conn.execute("DROP TABLE activities")
    db.conn.execute(
        "CREATE TABLE activities (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "student_id INTEGER NOT NULL, lesson_id INTEGER, title TEXT NOT NULL, "
        "description TEXT NOT NULL DEFAULT '', "
        "tier TEXT NOT NULL CHECK (tier IN "
        "('core', 'folded', 'choice', 'life_skills', 'projects', 'wellness')), "
        "primary_subject TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'manual', "
        "minutes INTEGER NOT NULL CHECK (minutes > 0), occurred_on TEXT NOT NULL, "
        "location TEXT NOT NULL DEFAULT '', "
        "created_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    old_id = db.conn.execute(
        "INSERT INTO activities (student_id, title, tier, primary_subject, minutes, occurred_on) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (student["id"], "Old-style logged hours", "core", "math", 30, "2026-08-01"),
    ).lastrowid
    db.conn.commit()

    db.migrate()

    columns = {row["name"] for row in db.conn.execute("PRAGMA table_info(activities)")}
    assert "course_id" in columns
    row = db.conn.execute("SELECT title, course_id FROM activities WHERE id = ?", (old_id,)).fetchone()
    assert row["title"] == "Old-style logged hours"
    assert row["course_id"] is None


def test_create_and_get_course_round_trips(db, student):
    course_id = db.create_course(
        student["id"], "Washington State History", "history", "2025-09-01", "2026-08-31",
        grade_level="8", description="desc", goals="goals", outline="outline",
    )
    course = db.get_course(course_id)
    assert course["title"] == "Washington State History"
    assert course["credit_subject"] == "history"
    assert course["credit_value"] == 1.0
    assert course["pass_fail"] is None
    assert course["final_grade"] == ""


def test_get_course_is_none_for_an_unknown_id(db, student):
    assert db.get_course(999999) is None


def test_list_courses_is_most_recent_start_date_first(db, student):
    db.create_course(student["id"], "Older", "math", "2024-09-01", "2025-06-01")
    db.create_course(student["id"], "Newer", "history", "2025-09-01", "2026-06-01")
    titles = [c["title"] for c in db.list_courses(student["id"])]
    assert titles == ["Newer", "Older"]


def test_update_course_ignores_unknown_fields(db, student):
    course_id = db.create_course(student["id"], "Algebra 1", "math", "2025-09-01", "2026-06-01")
    db.update_course(course_id, final_grade="B+", not_a_real_field="x")
    course = db.get_course(course_id)
    assert course["final_grade"] == "B+"
    assert "not_a_real_field" not in course


def test_update_course_with_no_recognised_fields_is_a_no_op(db, student):
    course_id = db.create_course(student["id"], "Algebra 1", "math", "2025-09-01", "2026-06-01")
    before = db.get_course(course_id)
    db.update_course(course_id)
    assert db.get_course(course_id) == before


def test_pass_fail_rejects_anything_other_than_pass_or_fail(db, student):
    course_id = db.create_course(student["id"], "Algebra 1", "math", "2025-09-01", "2026-06-01")
    with pytest.raises(sqlite3.IntegrityError):
        db.update_course(course_id, pass_fail="incomplete")


def test_delete_course_untags_its_activities_but_keeps_them(db, student):
    course_id = db.create_course(student["id"], "Algebra 1", "math", "2025-09-01", "2026-06-01")
    activity_id = db.log_activity(
        student_id=student["id"], title="Solving for x", tier="core", primary_subject="math",
        minutes=45, subject_credits={"math": 45}, occurred_on="2025-10-01",
    )
    db.set_activity_course(activity_id, course_id)
    db.delete_course(course_id)
    assert db.get_course(course_id) is None
    remaining = db.conn.execute(
        "SELECT course_id FROM activities WHERE id = ?", (activity_id,)
    ).fetchone()
    assert remaining["course_id"] is None
    activities = db.list_activities(student["id"])
    assert len(activities) == 1  # the logged hours themselves are untouched


def test_candidate_activities_matches_by_subject_and_date_range(db, student):
    course_id = db.create_course(student["id"], "Algebra 1", "math", "2025-09-01", "2026-06-01")
    in_range = db.log_activity(
        student_id=student["id"], title="In range", tier="core", primary_subject="math",
        minutes=30, subject_credits={"math": 30}, occurred_on="2025-10-01",
    )
    db.log_activity(
        student_id=student["id"], title="Wrong subject", tier="core", primary_subject="science",
        minutes=30, subject_credits={"science": 30}, occurred_on="2025-10-01",
    )
    db.log_activity(
        student_id=student["id"], title="Out of range", tier="core", primary_subject="math",
        minutes=30, subject_credits={"math": 30}, occurred_on="2024-01-01",
    )
    candidates = db.candidate_activities_for_course(
        student["id"], "math", "2025-09-01", "2026-06-01", course_id
    )
    assert [a["id"] for a in candidates] == [in_range]


def test_candidate_activities_excludes_ones_claimed_by_another_course(db, student):
    course_a = db.create_course(student["id"], "Algebra 1", "math", "2025-09-01", "2026-06-01")
    course_b = db.create_course(student["id"], "Geometry", "math", "2025-09-01", "2026-06-01")
    activity_id = db.log_activity(
        student_id=student["id"], title="Claimed by A", tier="core", primary_subject="math",
        minutes=30, subject_credits={"math": 30}, occurred_on="2025-10-01",
    )
    db.set_activity_course(activity_id, course_a)
    candidates_for_b = db.candidate_activities_for_course(
        student["id"], "math", "2025-09-01", "2026-06-01", course_b
    )
    assert candidates_for_b == []
    candidates_for_a = db.candidate_activities_for_course(
        student["id"], "math", "2025-09-01", "2026-06-01", course_a
    )
    assert [a["id"] for a in candidates_for_a] == [activity_id]


def test_set_activity_course_can_untag(db, student):
    course_id = db.create_course(student["id"], "Algebra 1", "math", "2025-09-01", "2026-06-01")
    activity_id = db.log_activity(
        student_id=student["id"], title="Solving for x", tier="core", primary_subject="math",
        minutes=45, subject_credits={"math": 45}, occurred_on="2025-10-01",
    )
    db.set_activity_course(activity_id, course_id)
    db.set_activity_course(activity_id, None)
    activity = db.conn.execute("SELECT course_id FROM activities WHERE id = ?", (activity_id,)).fetchone()
    assert activity["course_id"] is None


def test_course_minutes_sums_only_tagged_activities(db, student):
    course_id = db.create_course(student["id"], "Algebra 1", "math", "2025-09-01", "2026-06-01")
    tagged = db.log_activity(
        student_id=student["id"], title="Tagged", tier="core", primary_subject="math",
        minutes=45, subject_credits={"math": 45}, occurred_on="2025-10-01",
    )
    db.log_activity(
        student_id=student["id"], title="Untagged", tier="core", primary_subject="math",
        minutes=100, subject_credits={"math": 100}, occurred_on="2025-10-02",
    )
    db.set_activity_course(tagged, course_id)
    assert db.course_minutes(course_id) == 45


def test_course_minutes_is_zero_for_a_course_with_nothing_tagged(db, student):
    course_id = db.create_course(student["id"], "Algebra 1", "math", "2025-09-01", "2026-06-01")
    assert db.course_minutes(course_id) == 0


def test_course_activities_carries_the_full_lesson_when_there_is_one(db, student):
    course_id = db.create_course(student["id"], "Algebra 1", "math", "2025-09-01", "2026-06-01")
    lesson_id = db.save_lesson(
        student["id"], "math", "math", "topic", "Two-Step Equations",
        payload={"title": "Two-Step Equations", "assessment": {"kind": "check"}},
    )
    activity_id = db.log_activity(
        student_id=student["id"], title="Two-Step Equations", tier="core", primary_subject="math",
        minutes=45, subject_credits={"math": 45}, occurred_on="2025-10-01", lesson_id=lesson_id,
    )
    db.set_activity_course(activity_id, course_id)
    activities = db.course_activities(course_id)
    assert len(activities) == 1
    assert activities[0]["lesson"]["payload"]["title"] == "Two-Step Equations"


def test_course_activities_has_none_lesson_for_a_manual_entry(db, student):
    course_id = db.create_course(student["id"], "Algebra 1", "math", "2025-09-01", "2026-06-01")
    activity_id = db.log_activity(
        student_id=student["id"], title="Worksheet practice", tier="core", primary_subject="math",
        minutes=30, subject_credits={"math": 30}, occurred_on="2025-10-01",
    )
    db.set_activity_course(activity_id, course_id)
    activities = db.course_activities(course_id)
    assert activities[0]["lesson"] is None


# --- untagged_subject_minutes: the raw material for the Courses page nudge ----


def test_untagged_subject_minutes_excludes_tagged_activities(db, student):
    course_id = db.create_course(student["id"], "Algebra 1", "math", "2025-09-01", "2026-06-01")
    tagged = db.log_activity(
        student_id=student["id"], title="Tagged", tier="core", primary_subject="math",
        minutes=100, subject_credits={"math": 100}, occurred_on="2025-10-01",
    )
    db.set_activity_course(tagged, course_id)
    db.log_activity(
        student_id=student["id"], title="Untagged", tier="core", primary_subject="math",
        minutes=60, subject_credits={"math": 60}, occurred_on="2025-10-02",
    )
    totals = db.untagged_subject_minutes(student["id"], "2025-09-01", "2026-06-01")
    assert totals == {"math": 60}


def test_untagged_subject_minutes_groups_by_subject(db, student):
    db.log_activity(
        student_id=student["id"], title="Math one", tier="core", primary_subject="math",
        minutes=30, subject_credits={"math": 30}, occurred_on="2025-10-01",
    )
    db.log_activity(
        student_id=student["id"], title="Math two", tier="core", primary_subject="math",
        minutes=45, subject_credits={"math": 45}, occurred_on="2025-10-02",
    )
    db.log_activity(
        student_id=student["id"], title="Science", tier="core", primary_subject="science",
        minutes=50, subject_credits={"science": 50}, occurred_on="2025-10-01",
    )
    totals = db.untagged_subject_minutes(student["id"], "2025-09-01", "2026-06-01")
    assert totals == {"math": 75, "science": 50}


def test_untagged_subject_minutes_respects_the_date_range(db, student):
    db.log_activity(
        student_id=student["id"], title="In range", tier="core", primary_subject="math",
        minutes=30, subject_credits={"math": 30}, occurred_on="2025-10-01",
    )
    db.log_activity(
        student_id=student["id"], title="Out of range", tier="core", primary_subject="math",
        minutes=90, subject_credits={"math": 90}, occurred_on="2024-01-01",
    )
    totals = db.untagged_subject_minutes(student["id"], "2025-09-01", "2026-06-01")
    assert totals == {"math": 30}


def test_untagged_subject_minutes_is_empty_with_nothing_logged(db, student):
    assert db.untagged_subject_minutes(student["id"], "2025-09-01", "2026-06-01") == {}


# --- lessons_for_week ----------------------------------------------------------


def test_lessons_for_week_filters_by_metadata_not_created_at(db, student):
    """A lesson planned on Friday for the following Tuesday still belongs to
    *that* week's plan regardless of when it was generated."""
    db.save_lesson(
        student["id"], "math", "math", "topic", "In this week",
        payload={"title": "t"}, metadata={"week_start": "2026-08-17", "planned_for": "2026-08-18"},
    )
    db.save_lesson(
        student["id"], "english", "english", "topic", "A different week",
        payload={"title": "t"}, metadata={"week_start": "2026-08-24", "planned_for": "2026-08-24"},
    )
    week = db.lessons_for_week(student["id"], "2026-08-17")
    assert [l["title"] for l in week] == ["In this week"]


def test_lessons_for_week_orders_by_planned_for(db, student):
    db.save_lesson(
        student["id"], "history", "history", "topic", "Thursday",
        payload={"title": "t"}, metadata={"week_start": "2026-08-17", "planned_for": "2026-08-20"},
    )
    db.save_lesson(
        student["id"], "science", "science", "topic", "Monday",
        payload={"title": "t"}, metadata={"week_start": "2026-08-17", "planned_for": "2026-08-17"},
    )
    week = db.lessons_for_week(student["id"], "2026-08-17")
    assert [l["title"] for l in week] == ["Monday", "Thursday"]


def test_lessons_for_week_is_empty_when_nothing_planned(db, student):
    assert db.lessons_for_week(student["id"], "2026-08-17") == []


def test_lessons_for_week_ignores_lessons_with_no_week_metadata(db, student):
    """A lesson generated the ordinary on-demand way (no week tags at all)
    must not accidentally show up in a week's plan."""
    db.save_lesson(
        student["id"], "math", "math", "topic", "On-demand lesson", payload={"title": "t"},
    )
    assert db.lessons_for_week(student["id"], "2026-08-17") == []


# --- concurrent metadata writes --------------------------------------------------


def test_concurrent_writes_to_different_activities_do_not_lose_either_one(
    db, student, monkeypatch
):
    """`ui.get_db()` caches one Database (one Connection) per server process
    with `st.cache_resource` -- every browser session shares it, so a parent
    and student acting at the same moment run on two different threads
    against the exact same object. save_writing_response reads the whole
    lesson row, mutates the metadata dict in Python, and writes it all back;
    without something serializing that read-modify-write, two saves for two
    different activities landing close enough together can have the second
    one overwrite the first's write with a stale copy it read before the
    first one committed.

    Forces that interleaving deterministically (rather than hoping it shows
    up under raw thread-timing luck) by making get_lesson slow: thread A
    starts first and is asleep *inside* the lock, mid-read; thread B's own
    call blocks on the same lock until A finishes, rather than reading the
    pre-A state and clobbering A's write on the way out."""
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="english", subject="english", topic="t",
        title="Essay", payload={"activities": []},
    )

    real_get_lesson = Database.get_lesson

    def slow_get_lesson(self, *args, **kwargs):
        result = real_get_lesson(self, *args, **kwargs)
        time.sleep(0.05)
        return result

    monkeypatch.setattr(Database, "get_lesson", slow_get_lesson)

    first = threading.Thread(target=db.save_writing_response, args=(lesson_id, 0, "first"))
    second = threading.Thread(target=db.save_writing_response, args=(lesson_id, 1, "second"))
    first.start()
    time.sleep(0.01)  # first is now asleep inside slow_get_lesson, holding the lock
    second.start()
    first.join()
    second.join()

    lesson = real_get_lesson(db, lesson_id)
    assert lesson["metadata"]["writing_responses"] == {"0": "first", "1": "second"}
