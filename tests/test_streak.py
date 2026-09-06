"""School-day streaks -- the one thing on his page that rewards showing up
rather than scoring well.

The weekend rule is the load-bearing part: counting Saturday and Sunday as
missed days would reset the streak every Monday morning, turning the one
encouraging mechanic into a weekly reminder that he failed.
"""

from __future__ import annotations

from datetime import date

import pytest

from compass.storage.db import Database
from compass.weekly import best_streak, current_streak

# Aug 2026: Thu 20, Fri 21, [Sat 22, Sun 23], Mon 24, Tue 25, Wed 26, Thu 27
WED = date(2026, 8, 26)


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    yield database
    database.close()


@pytest.fixture()
def student(db):
    return db.ensure_default_student()


# --- counting ------------------------------------------------------------------


def test_a_weekend_does_not_break_the_streak():
    days = {"2026-08-20", "2026-08-21", "2026-08-24", "2026-08-25"}
    assert current_streak(days, WED) == 4


def test_today_not_started_yet_does_not_break_the_streak():
    """The moment you most want it to say "you're on 4, keep going" is
    before he's done anything today."""
    days = {"2026-08-20", "2026-08-21", "2026-08-24", "2026-08-25"}
    assert current_streak(days, WED) == 4
    assert current_streak(days | {"2026-08-26"}, WED) == 5


def test_a_missed_school_day_breaks_it():
    days = {"2026-08-20", "2026-08-21", "2026-08-24", "2026-08-26"}  # skipped Tue 25
    assert current_streak(days, WED) == 1


def test_a_missed_yesterday_with_nothing_today_is_zero():
    assert current_streak({"2026-08-24"}, WED) == 0


def test_a_missed_friday_is_not_forgiven_just_because_today_is_the_weekend():
    """`today` being a non-school day is not the same thing as "today is
    still in progress" -- only an actual today gets that forgiveness. A
    Saturday `today` should read Friday the same way a Monday `today`
    would: as an already-elapsed school day, broken if it was missed."""
    saturday = date(2026, 8, 22)
    days = {"2026-08-20", "2026-08-21"}  # Thu, Fri both done
    assert current_streak(days, saturday) == 2

    missed_friday = {"2026-08-19", "2026-08-20"}  # Wed, Thu done, Fri skipped
    assert current_streak(missed_friday, saturday) == 0


def test_no_history_is_zero():
    assert current_streak(set(), WED) == 0
    assert best_streak(set(), WED) == 0


def test_best_streak_keeps_the_longest_run_not_the_current_one():
    # Thu/Fri/Mon is a 3-day run (the weekend is skipped, not counted),
    # then Tue is missed, then Wed starts a new run of 1.
    days = {"2026-08-20", "2026-08-21", "2026-08-24", "2026-08-26"}
    assert current_streak(days, WED) == 1
    assert best_streak(days, WED) == 3


def test_best_streak_survives_a_long_history_without_running_off_the_calendar():
    """Walking backwards from today to the start of history overflows
    `date` itself -- best_streak walks forward from his first recorded day
    instead."""
    assert best_streak({"1990-01-02"}, WED) == 1


# --- planned_days/planned_weeks: telling a deliberate day off from a real miss --
#
# Monday the 24th is the anchor for all of these: it's the Monday of the
# week containing WED, so week_start(any day that week) == "2026-08-24".


def test_a_day_nothing_was_ever_planned_for_does_not_break_the_streak():
    """Monday 24th was a holiday -- unchecked in This Week's school-days
    picker -- but the rest of that week *was* batch-planned (planned_weeks
    has that Monday), so its absence from planned_days reads as deliberate.
    Must count the same way a weekend does: skipped, not a miss."""
    active = {"2026-08-20", "2026-08-21", "2026-08-25", "2026-08-26"}  # Mon 24 missing
    planned_days = set(active)  # Monday was never planned; Tue/Wed were
    planned_weeks = {"2026-08-24"}  # this week did get a batch-planning pass
    assert current_streak(active, WED, planned_days=planned_days, planned_weeks=planned_weeks) == 4

    # Without planning info at all, the same data reads as a broken streak --
    # this is exactly the gap being closed here.
    assert current_streak(active, WED) == 2


def test_a_planned_day_left_undone_still_breaks_the_streak():
    """Contrast with the above: Monday 24th *was* planned this time, he
    just didn't do it. That's a real miss, not a day off, and must still
    break the streak even with planning info given."""
    active = {"2026-08-20", "2026-08-21", "2026-08-25", "2026-08-26"}  # Mon 24 missing
    planned_days = active | {"2026-08-24"}  # Monday had work waiting
    planned_weeks = {"2026-08-24"}
    assert current_streak(active, WED, planned_days=planned_days, planned_weeks=planned_weeks) == 2


def test_a_week_never_touched_by_batch_planning_forgives_nothing():
    """The critical safety case: a family that never uses This Week's batch
    planner has an empty planned_days *and* empty planned_weeks forever --
    every lesson is on-demand, with no planned_for/week_start tag at all.
    A missing Monday must still break the streak exactly as it always did;
    planned_days being empty must never be read as "everything is a day
    off," or the whole streak mechanic would go silent permanently the
    moment a family didn't opt into batch planning."""
    active = {"2026-08-20", "2026-08-21", "2026-08-25", "2026-08-26"}  # Mon 24 missing
    assert current_streak(active, WED, planned_days=set(), planned_weeks=set()) == 2


def test_best_streak_is_not_capped_by_a_day_that_was_never_planned():
    # Thu/Fri/[Mon: never planned]/Tue/Wed would be a broken 2+2 without
    # planning info; with it, the untouched Monday doesn't reset the run,
    # so the whole stretch counts as one run of 4.
    active = {"2026-08-20", "2026-08-21", "2026-08-25", "2026-08-26"}
    planned_days = set(active)
    planned_weeks = {"2026-08-24"}
    assert (
        best_streak(active, WED, planned_days=planned_days, planned_weeks=planned_weeks) == 4
    )
    assert best_streak(active, WED) == 2


def test_best_streak_still_resets_on_a_planned_day_left_undone():
    active = {"2026-08-20", "2026-08-21", "2026-08-25", "2026-08-26"}
    planned_days = active | {"2026-08-24"}
    planned_weeks = {"2026-08-24"}
    assert (
        best_streak(active, WED, planned_days=planned_days, planned_weeks=planned_weeks) == 2
    )


def test_planned_days_across_every_subject(db, student):
    db.save_lesson(
        student_id=student["id"], agent="math", subject="math", topic="t",
        title="t", payload={}, metadata={"planned_for": "2026-08-24"},
    )
    db.save_lesson(
        student_id=student["id"], agent="english", subject="english", topic="t",
        title="t", payload={}, metadata={"planned_for": "2026-08-25"},
    )
    # An on-demand lesson, generated the ordinary way with no day attached --
    # must not show up as a "planned" date.
    db.save_lesson(
        student_id=student["id"], agent="science", subject="science", topic="t",
        title="t", payload={},
    )
    assert db.planned_days(student["id"]) == {"2026-08-24", "2026-08-25"}


def test_planned_weeks_across_every_subject(db, student):
    db.save_lesson(
        student_id=student["id"], agent="math", subject="math", topic="t",
        title="t", payload={}, metadata={"week_start": "2026-08-24", "planned_for": "2026-08-24"},
    )
    db.save_lesson(
        student_id=student["id"], agent="english", subject="english", topic="t",
        title="t", payload={}, metadata={"week_start": "2026-08-17", "planned_for": "2026-08-18"},
    )
    # An on-demand lesson -- no week_start tag -- must not show up.
    db.save_lesson(
        student_id=student["id"], agent="science", subject="science", topic="t",
        title="t", payload={},
    )
    assert db.planned_weeks(student["id"]) == {"2026-08-24", "2026-08-17"}


# --- what counts as an active day ----------------------------------------------


def test_a_lesson_marked_done_counts(db, student):
    lesson_id = db.save_lesson(
        student_id=student["id"], agent="math", subject="math", topic="t",
        title="t", payload={},
    )
    db.mark_student_done(lesson_id)
    assert db.active_days(student["id"]) == {date.today().isoformat()}


def test_a_life_skill_counts(db, student):
    skill_id = db.add_life_skill(student["id"], "Do laundry")
    db.set_life_skill_done(skill_id, True)
    assert db.active_days(student["id"]) == {date.today().isoformat()}


def test_a_vocab_review_alone_does_not_count(db, student):
    """One button press a day shouldn't be farmable into a streak."""
    db.mark_vocab_reviewed(student["id"], date.today().isoformat())
    assert db.active_days(student["id"]) == set()


def test_an_unfinished_lesson_does_not_count(db, student):
    db.save_lesson(
        student_id=student["id"], agent="math", subject="math", topic="t",
        title="t", payload={},
    )
    assert db.active_days(student["id"]) == set()

