"""Backups protect the family's legal record. Tested accordingly."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from compass import backup, config
from compass.storage.db import Database


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "compass.db")
    yield database
    database.close()


@pytest.fixture()
def student(db):
    return db.ensure_default_student()


def log(db, student, title="Session", minutes=60, on="2026-03-02"):
    return db.log_activity(
        student_id=student["id"],
        title=title,
        tier=config.TIER_CORE,
        primary_subject="math",
        minutes=minutes,
        subject_credits={"math": minutes},
        occurred_on=on,
    )


def test_snapshot_captures_current_data(db, student):
    log(db, student, title="Algebra")
    path = backup.snapshot(db.conn, db.path, reason="manual")

    assert path.exists()
    restored = Database(path)
    assert [a["title"] for a in restored.list_activities(student["id"])] == ["Algebra"]
    restored.close()


def test_snapshot_of_a_live_connection_is_consistent(db, student):
    """The backup API must see committed data without closing the connection."""
    for i in range(50):
        log(db, student, title=f"Session {i}")
    path = backup.snapshot(db.conn, db.path)

    copy = Database(path)
    assert len(copy.list_activities(student["id"])) == 50
    copy.close()
    # Original still usable afterwards.
    log(db, student, title="After backup")
    assert len(db.list_activities(student["id"])) == 51


def test_auto_snapshot_runs_once_per_day(db, student):
    log(db, student)
    first = backup.auto_snapshot(db.conn, db.path, today=date(2026, 3, 2))
    second = backup.auto_snapshot(db.conn, db.path, today=date(2026, 3, 2))
    third = backup.auto_snapshot(db.conn, db.path, today=date(2026, 3, 3))

    assert first is not None
    assert second is None, "opening the app twice in a day must not re-snapshot"
    assert third is not None


def test_snapshots_are_listed_newest_first(db, student):
    log(db, student)
    for day in (1, 2, 3):
        backup.auto_snapshot(db.conn, db.path, today=date(2026, 3, day))
    snapshots = backup.list_snapshots(db.path)

    assert len(snapshots) == 3
    assert snapshots[0].taken_at > snapshots[-1].taken_at


def test_unrelated_files_in_the_backup_folder_are_ignored(db, student):
    log(db, student)
    backup.snapshot(db.conn, db.path)
    (backup.backup_dir(db.path) / "notes.txt").write_text("hello")
    (backup.backup_dir(db.path) / "compass-garbage.db").write_bytes(b"x")

    assert len(backup.list_snapshots(db.path)) == 1


def _fake_snapshot(db, when: datetime, reason: str = "auto"):
    """Write a real snapshot then rename it to a chosen timestamp."""
    path = backup.snapshot(db.conn, db.path, reason=reason)
    target = path.parent / f"compass-{when:%Y-%m-%d-%H%M%S}-{reason}.db"
    path.rename(target)
    return target


def test_prune_keeps_recent_dailies(db, student):
    log(db, student)
    today = date(2026, 6, 30)
    for offset in range(0, 20):
        _fake_snapshot(db, datetime(2026, 6, 30) - timedelta(days=offset))

    backup.prune(db.path, today=today)
    assert len(backup.list_snapshots(db.path)) == 20, "nothing inside the window drops"


def test_prune_thins_old_snapshots_to_one_per_month(db, student):
    log(db, student)
    today = date(2026, 6, 30)
    # Five snapshots in each of two months, all well outside the daily window.
    for day in (2, 5, 9, 14, 20):
        _fake_snapshot(db, datetime(2026, 1, day, 9, 0, 0))
        _fake_snapshot(db, datetime(2026, 2, day, 9, 0, 0))
    # Plus one recent, which must survive untouched.
    _fake_snapshot(db, datetime(2026, 6, 29, 9, 0, 0))

    removed = backup.prune(db.path, today=today)
    kept = backup.list_snapshots(db.path)

    assert len(removed) == 8
    assert len(kept) == 3
    months = sorted((s.taken_at.year, s.taken_at.month) for s in kept)
    assert months == [(2026, 1), (2026, 2), (2026, 6)]
    # The earliest snapshot of each archived month is the one kept.
    january = next(s for s in kept if s.taken_at.month == 1)
    assert january.taken_at.day == 2


def test_restore_replaces_current_data(db, student):
    log(db, student, title="Before snapshot")
    snap = backup.snapshot(db.conn, db.path, reason="manual")

    log(db, student, title="After snapshot")
    assert len(db.list_activities(student["id"])) == 2

    backup.restore(db.conn, db.path, snap)

    titles = [a["title"] for a in db.list_activities(student["id"])]
    assert titles == ["Before snapshot"], "the later activity must be gone"


def test_restore_saves_the_current_state_first(db, student):
    log(db, student, title="Original")
    snap = backup.snapshot(db.conn, db.path, reason="manual")
    log(db, student, title="Work I would hate to lose")

    safety = backup.restore(db.conn, db.path, snap)

    assert safety.exists()
    recovered = Database(safety)
    titles = {a["title"] for a in recovered.list_activities(student["id"])}
    assert "Work I would hate to lose" in titles, "a mistaken restore must be undoable"
    recovered.close()


def test_restore_keeps_the_live_connection_usable(db, student):
    log(db, student, title="Before")
    snap = backup.snapshot(db.conn, db.path, reason="manual")
    backup.restore(db.conn, db.path, snap)

    # Same connection object, still works for reads and writes.
    log(db, student, title="After restore")
    assert len(db.list_activities(student["id"])) == 2


def test_restoring_a_missing_snapshot_raises_and_changes_nothing(db, student):
    log(db, student, title="Untouched")
    with pytest.raises(FileNotFoundError):
        backup.restore(db.conn, db.path, db.path.parent / "backups" / "nope.db")
    assert [a["title"] for a in db.list_activities(student["id"])] == ["Untouched"]


def test_snapshot_round_trips_every_table(db, student):
    """A backup that silently drops a table is worse than no backup."""
    log(db, student, title="Activity")
    db.set_mastery(student["id"], "integer-operations", "mastered", score=95.0)
    book_id = db.add_book(student["id"], "The Hobbit", "Tolkien")
    db.add_vocabulary(student["id"], "burgle", "to steal", source_book_id=book_id)
    db.add_choice_topic(student["id"], "Minecraft modding")
    db.seed_life_skills(student["id"])
    db.add_web_node(student["id"], "science", "nurse logs")
    db.save_lesson(student["id"], "math", "math", "t", "Lesson", payload={"a": 1})
    db.set_setting("tier3_cap_percent", "35")

    snap = backup.snapshot(db.conn, db.path, reason="manual")
    copy = Database(snap)

    assert len(copy.list_activities(student["id"])) == 1
    assert copy.mastered_skills(student["id"]) == {"integer-operations"}
    assert len(copy.list_books(student["id"])) == 1
    assert len(copy.list_vocabulary(student["id"])) == 1
    assert len(copy.list_choice_topics(student["id"])) == 1
    assert len(copy.list_life_skills(student["id"])) > 0
    assert len(copy.web_nodes(student["id"], "science")) == 1
    assert len(copy.list_lessons(student["id"])) == 1
    assert copy.get_setting("tier3_cap_percent") == "35"
    copy.close()
