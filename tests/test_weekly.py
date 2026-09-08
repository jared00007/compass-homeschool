"""Weekly planning -- Friday reviews the week just finished and plans the
week ahead.

Two things worth pinning down here: the date math (which Monday does a given
day belong to, what "next week" means), and the orchestration split between
Science/English/History (four independent, fresh topics -- each day's own
state update is what makes the next call different) and Math (one skill for
the whole week, since the mastery gate means nothing changes between calls
made in the same sitting without a real graded assessment in between).
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from compass.storage.db import Database
from compass.weekly import (
    EPIC_ORDER,
    board_for_week,
    default_plan_target,
    due_lessons,
    epic_for,
    group_backlog_by_epic,
    is_backlogged,
    latest_per_day,
    today_subject_status,
    week_dates,
    week_start,
)

STUDENT = {"id": 1, "name": "Landon", "grade": "8"}


# --- date helpers ----------------------------------------------------------------


@pytest.mark.parametrize(
    "on,expected_monday",
    [
        (date(2026, 8, 10), date(2026, 8, 10)),  # a Monday
        (date(2026, 8, 14), date(2026, 8, 10)),  # a Friday, same week
        (date(2026, 8, 16), date(2026, 8, 10)),  # a Sunday, still that week
        (date(2026, 8, 17), date(2026, 8, 17)),  # the following Monday
    ],
)
def test_week_start_finds_the_monday(on, expected_monday):
    assert week_start(on) == expected_monday


def test_week_start_defaults_to_today():
    assert week_start() == week_start(date.today())


def test_week_dates_is_monday_through_thursday_only():
    dates = week_dates(date(2026, 8, 10))
    assert dates == [date(2026, 8, 10), date(2026, 8, 11), date(2026, 8, 12), date(2026, 8, 13)]


def test_week_dates_can_include_friday_as_a_fifth_option():
    """Friday stays out unless explicitly asked for -- the escape hatch for
    a week where a holiday on another weekday means Friday's needed as a
    substitute lesson day instead."""
    dates = week_dates(date(2026, 8, 10), include_friday=True)
    assert dates == [
        date(2026, 8, 10),
        date(2026, 8, 11),
        date(2026, 8, 12),
        date(2026, 8, 13),
        date(2026, 8, 14),
    ]


def test_default_plan_target_is_the_monday_after_next():
    """Planning always targets the week ahead, not the one about to end --
    Friday Aug 14 sits in the week starting Aug 10, so the plan target is
    Aug 17, not Aug 10 itself."""
    assert default_plan_target(date(2026, 8, 14)) == date(2026, 8, 17)


# --- latest_per_day: dedup for a regenerated day ------------------------------------


def _lesson(id, agent, planned_for):
    return {"id": id, "agent": agent, "metadata": {"planned_for": planned_for}}


def test_latest_per_day_keeps_the_newest_lesson_for_a_regenerated_day():
    lessons = [
        _lesson(1, "math", "2026-08-10"),
        _lesson(2, "math", "2026-08-10"),  # regenerated -- supersedes id 1
    ]
    result = latest_per_day(lessons)
    assert len(result) == 1
    assert result[0]["id"] == 2


def test_latest_per_day_keeps_different_agents_and_days_separate():
    lessons = [
        _lesson(1, "math", "2026-08-10"),
        _lesson(2, "science", "2026-08-10"),
        _lesson(3, "math", "2026-08-11"),
    ]
    result = latest_per_day(lessons)
    assert {(l["id"]) for l in result} == {1, 2, 3}


def test_latest_per_day_sorts_by_planned_for_then_id():
    lessons = [
        _lesson(5, "math", "2026-08-12"),
        _lesson(1, "science", "2026-08-10"),
        _lesson(3, "english", "2026-08-10"),
    ]
    result = latest_per_day(lessons)
    assert [l["id"] for l in result] == [1, 3, 5]


# --- due_lessons: "what's actually due now," not "whatever was generated most recently" ---


def test_due_lessons_picks_todays_over_a_later_generated_id():
    """The regression this exists to fix: batch-planning a whole week in one
    sitting means Friday's lesson has the highest id even though today is
    Tuesday -- id order must not win over the actual planned day."""
    lessons = [
        _lesson(5, "math", "2026-08-14"),  # Friday, generated last -> highest id
        _lesson(2, "math", "2026-08-11"),  # Tuesday -- today
    ]
    result = due_lessons(lessons, "2026-08-11")
    assert [l["id"] for l in result] == [2]


def test_due_lessons_excludes_anything_planned_for_a_later_day():
    lessons = [_lesson(1, "math", "2026-08-12")]  # Wednesday
    assert due_lessons(lessons, "2026-08-11") == []  # today is Tuesday


def test_due_lessons_includes_an_overdue_lesson_from_an_earlier_day():
    lessons = [_lesson(1, "math", "2026-08-10")]  # Monday, never done
    assert due_lessons(lessons, "2026-08-11") == lessons  # today is Tuesday


def test_due_lessons_sorts_oldest_overdue_first():
    lessons = [
        _lesson(1, "math", "2026-08-11"),  # today
        _lesson(2, "math", "2026-08-10"),  # overdue from yesterday
    ]
    result = due_lessons(lessons, "2026-08-11")
    assert [l["id"] for l in result] == [2, 1]


def test_due_lessons_puts_untagged_lessons_last():
    """A lesson generated the ordinary on-demand way (no day attached at
    all) is still due now -- it just yields to anything with a real day."""
    untagged = {"id": 9, "agent": "math", "metadata": {}}
    lessons = [untagged, _lesson(1, "math", "2026-08-11")]
    result = due_lessons(lessons, "2026-08-11")
    assert [l["id"] for l in result] == [1, 9]


def test_due_lessons_on_an_all_untagged_list_preserves_input_order():
    """No day tags anywhere (a family that's never used weekly batch
    planning) -- behaves like the old "most recent first" selection, since
    the caller already sorts lessons that way before calling this."""
    lessons = [
        {"id": 2, "agent": "math", "metadata": {}},
        {"id": 1, "agent": "math", "metadata": {}},
    ]
    result = due_lessons(lessons, "2026-08-11")
    assert [l["id"] for l in result] == [2, 1]


def test_due_lessons_excludes_a_lesson_from_a_fully_elapsed_week():
    """The Backlog feature's actual effect on due_lessons: merely overdue
    (same week) still surfaces, same as always, but once the whole week's
    gone by it's backlogged instead -- pulled out of the due list entirely,
    not just sorted to the bottom of it."""
    lessons = [_lesson(1, "math", "2026-08-10")]  # Monday, week of Aug 10
    assert due_lessons(lessons, "2026-08-18") == []  # the following Tuesday


# --- is_backlogged: a whole week's gone by without it being turned in -----------


def test_is_backlogged_false_for_a_lesson_still_within_its_own_week():
    lesson = _lesson(1, "math", "2026-08-10")  # Monday
    assert not is_backlogged(lesson, "2026-08-13")  # Thursday, same week


def test_is_backlogged_true_once_its_own_week_has_fully_ended():
    lesson = _lesson(1, "math", "2026-08-10")  # Monday, week of Aug 10
    assert is_backlogged(lesson, "2026-08-18")  # Tuesday, the following week


def test_is_backlogged_false_for_an_untagged_on_demand_lesson():
    """No planned_for at all -- no week concept, so it's never backlogged,
    matching due_lessons' own unbounded treatment of one."""
    untagged = {"id": 9, "agent": "math", "metadata": {}}
    assert not is_backlogged(untagged, "2026-08-18")


def test_is_backlogged_true_when_held_back_even_within_this_week():
    """A parent's own "not this week" call, any day -- the manual
    counterpart to a whole week quietly running out on its own. Still
    true even when the lesson isn't due yet, let alone overdue."""
    lesson = {"id": 1, "agent": "math", "metadata": {"planned_for": "2026-08-14", "held_back": True}}
    assert is_backlogged(lesson, "2026-08-10")  # planned_for is still 4 days out


def test_is_backlogged_true_when_held_back_with_no_planned_for_at_all():
    """Even an on-demand lesson (no week concept) can be sent to backlog
    by hand -- it just never falls into it from time passing alone."""
    lesson = {"id": 1, "agent": "math", "metadata": {"held_back": True}}
    assert is_backlogged(lesson, "2026-08-18")


def test_due_lessons_excludes_a_held_back_lesson_due_today():
    """The actual point of the manual send-to-backlog feature: a parent
    can pull today's own due lesson out of Landon's view the instant they
    decide to, not just once its week eventually runs out."""
    lesson = _lesson(1, "math", "2026-08-11")
    lesson["metadata"]["held_back"] = True
    assert due_lessons([lesson], "2026-08-11") == []


# --- today_subject_status: one subject's row on Home's daily roster --------------


def _status_lesson(id, status, *, planned_for=None, done=None):
    metadata = {}
    if planned_for is not None:
        metadata["planned_for"] = planned_for
    if done is not None:
        metadata["student_done_on"] = done
    return {"id": id, "agent": "math", "status": status, "metadata": metadata}


def test_today_subject_status_prefers_a_pending_submission_over_anything_due():
    lessons = [
        _status_lesson(1, "submitted", planned_for="2026-08-11"),
        _status_lesson(2, "planned", planned_for="2026-08-11"),
    ]
    lesson, marker = today_subject_status(lessons, "2026-08-11")
    assert lesson["id"] == 1
    assert marker == "\U0001F4E4"


def test_today_subject_status_marks_a_sent_back_lesson_distinctly():
    lessons = [_status_lesson(1, "needs_revision", planned_for="2026-08-10")]
    lesson, marker = today_subject_status(lessons, "2026-08-11")
    assert lesson["id"] == 1
    assert marker == "↩️"


def test_today_subject_status_shows_an_empty_box_for_something_due_but_untouched():
    lessons = [_status_lesson(1, "planned", planned_for="2026-08-11")]
    lesson, marker = today_subject_status(lessons, "2026-08-11")
    assert lesson["id"] == 1
    assert marker == "⬜"


def test_today_subject_status_shows_a_green_check_once_fully_approved_today():
    """Nothing due, nothing pending, but he finished and a parent approved
    this same subject's lesson earlier today -- the roster should still
    show it, checked, rather than reading as if nothing had happened."""
    lessons = [_status_lesson(1, "completed", done="2026-08-11")]
    lesson, marker = today_subject_status(lessons, "2026-08-11")
    assert lesson["id"] == 1
    assert marker == "✅"


def test_today_subject_status_ignores_a_lesson_completed_on_an_earlier_day():
    """An old approved lesson from a previous day isn't "today's" status --
    it's not relevant to what's on his plate right now."""
    lessons = [_status_lesson(1, "completed", done="2026-08-05")]
    lesson, marker = today_subject_status(lessons, "2026-08-11")
    assert lesson is None
    assert marker == ""


def test_today_subject_status_points_to_an_unread_note_on_a_finished_lesson():
    """A finished lesson still carrying an approval note he hasn't read and
    replied to keeps the subject on the roster (📣) so he's sent to the lesson
    to read it -- even though it was approved on an earlier day."""
    lesson = {
        "id": 1, "agent": "math", "status": "completed",
        "metadata": {
            "student_done_on": "2026-08-05",  # earlier day: not "completed today"
            "writing_review": {"0": {
                "status": "approved",
                "approval_feedback": "Tighten the intro next time.",
                "approval_read_at": None,
            }},
        },
    }
    result, marker = today_subject_status([lesson], "2026-08-11")
    assert result["id"] == 1
    assert marker == "\U0001F4E3"  # 📣


def test_today_subject_status_drops_a_finished_lesson_once_its_note_is_read():
    lesson = {
        "id": 1, "agent": "math", "status": "completed",
        "metadata": {
            "student_done_on": "2026-08-05",
            "writing_review": {"0": {
                "status": "approved",
                "approval_feedback": "Tighten the intro.",
                "approval_read_at": "2026-08-06T09:00:00",
            }},
        },
    }
    result, marker = today_subject_status([lesson], "2026-08-11")
    assert result is None
    assert marker == ""


def test_today_subject_status_is_empty_when_nothing_is_set_up_for_this_subject():
    lesson, marker = today_subject_status([], "2026-08-11")
    assert lesson is None
    assert marker == ""


def test_today_subject_status_ignores_a_lesson_planned_for_a_later_day():
    lessons = [_status_lesson(1, "planned", planned_for="2026-08-14")]  # later this week
    lesson, marker = today_subject_status(lessons, "2026-08-11")
    assert lesson is None
    assert marker == ""


# --- board_for_week ----------------------------------------------------------------


@pytest.fixture()
def board_db(tmp_path):
    database = Database(tmp_path / "board.db")
    yield database
    database.close()


@pytest.fixture()
def board_student(board_db):
    student = board_db.ensure_default_student()
    board_db.seed_life_skills(student["id"])
    board_db.seed_coding_modules(student["id"])
    return student


def test_board_buckets_every_story_type_by_its_own_day(board_db, board_student):
    """One of each story type, each on a different weekday -- confirms
    every branch of the aggregator reads its own item correctly, not just
    lessons (the one type every other weekly.py function already covers)."""
    monday = week_start()
    sid = board_student["id"]

    board_db.save_lesson(
        student_id=sid, agent="math", subject="math", topic="t", title="Math Lesson",
        payload={"activities": []},
        metadata={"planned_for": monday.isoformat(), "week_start": monday.isoformat()},
    )
    skills = board_db.list_life_skills(sid)
    board_db.schedule_life_skill(skills[0]["id"], monday.isoformat())

    modules = board_db.list_coding_modules(sid)
    board_db.schedule_coding_module(modules[0]["id"], (monday + timedelta(days=1)).isoformat())

    topic_id = board_db.add_choice_topic(sid, "Learn guitar chords")
    board_db.schedule_choice_topic(topic_id, (monday + timedelta(days=2)).isoformat())

    project_id = board_db.add_big_project(sid, "Stop-Motion Film")
    step_id = board_db.add_project_step(project_id, "Write the script", active=True)
    board_db.schedule_project_step(step_id, (monday + timedelta(days=3)).isoformat())

    entry_id = board_db.add_travel_entry(
        sid, "Wyoming", monday.isoformat(), title="Yellowstone", status="planned"
    )
    board_db.schedule_travel_entry(entry_id, (monday + timedelta(days=4)).isoformat())

    board = board_for_week(board_db, board_student, monday)

    assert [k for k, _ in board[monday.isoformat()]] == ["lesson", "life_skill"]
    assert [k for k, _ in board[(monday + timedelta(days=1)).isoformat()]] == ["coding_module"]
    assert [k for k, _ in board[(monday + timedelta(days=2)).isoformat()]] == ["choice_topic"]
    assert [k for k, _ in board[(monday + timedelta(days=3)).isoformat()]] == ["project_step"]
    assert [k for k, _ in board[(monday + timedelta(days=4)).isoformat()]] == ["travel_entry"]
    assert board["backlog"] == []


def test_board_puts_a_backlogged_lesson_in_backlog_not_its_stale_day(board_db, board_student):
    monday = week_start()
    sid = board_student["id"]
    lesson_id = board_db.save_lesson(
        student_id=sid, agent="science", subject="science", topic="t", title="Backyard Ecosystem",
        payload={"activities": []},
        metadata={"planned_for": monday.isoformat(), "week_start": monday.isoformat()},
    )
    board_db.send_to_backlog(lesson_id)

    board = board_for_week(board_db, board_student, monday)
    assert board[monday.isoformat()] == []
    assert [item["title"] for _, item in board["backlog"]] == ["Backyard Ecosystem"]


def test_board_puts_a_backlogged_life_skill_in_backlog_regardless_of_its_original_week(
    board_db, board_student
):
    """The interesting case: a skill parked from a completely different
    (past) week must still surface in the global Backlog bucket -- the
    `_for_week` queries alone would never find it, since its stale
    scheduled_for date falls outside the target week's own range."""
    monday = week_start()
    sid = board_student["id"]
    skills = board_db.list_life_skills(sid)
    skill_id = skills[0]["id"]
    board_db.schedule_life_skill(skill_id, (monday - timedelta(days=21)).isoformat())
    board_db.set_life_skill_active(skill_id, False)

    board = board_for_week(board_db, board_student, monday)
    assert [item["id"] for kind, item in board["backlog"] if kind == "life_skill"] == [skill_id]


def test_board_never_floods_backlog_with_the_untouched_catalog(board_db, board_student):
    """The actual bug this guards: life_skills/coding_modules are
    pre-seeded from a large starter catalog, the vast majority sitting
    inactive from the moment it's seeded simply because it was never
    unlocked -- not because a parent ever parked it. None of that should
    ever show up as board clutter."""
    board = board_for_week(board_db, board_student, week_start())
    assert board["backlog"] == []


def test_board_never_lets_a_weekend_date_fall_off_the_board_entirely(
    board_db, board_student
):
    """The actual bug this guards: the board's five day-columns are
    Monday-Friday only, so a story whose own date lands on a Saturday or
    Sunday used to match neither a day column nor "backlogged" (its
    active flag says it's not parked) -- falling through both branches of
    _place_scheduled and vanishing from the board outright, not even
    visible in the Backlog panel. Reported directly, and confirmed
    against a real lesson stuck exactly this way after a move-control bug
    reset its date to a Sunday: "i moved two math lessons from backlog to
    their own dates... and they have disappeared." Every story kind goes
    through the same _place_scheduled helper, so this is checked across
    more than just lessons -- the fix has to hold board-wide, not just
    for the one kind that happened to surface it.
    """
    monday = week_start()
    saturday = monday + timedelta(days=5)
    sunday = monday + timedelta(days=6)
    sid = board_student["id"]

    lesson_id = board_db.save_lesson(
        student_id=sid, agent="math", subject="math", topic="t", title="Stuck Lesson",
        payload={"activities": []},
        metadata={"planned_for": sunday.isoformat(), "week_start": monday.isoformat()},
    )
    skills = board_db.list_life_skills(sid)
    skill_id = skills[0]["id"]
    board_db.schedule_life_skill(skill_id, saturday.isoformat())

    board = board_for_week(board_db, board_student, monday)

    backlog_ids = {(kind, item["id"]) for kind, item in board["backlog"]}
    assert ("lesson", lesson_id) in backlog_ids
    assert ("life_skill", skill_id) in backlog_ids
    # And not double-placed anywhere else on the board.
    all_placed = [pair for day, items in board.items() for pair in items if day != "backlog"]
    assert ("lesson", lesson_id) not in {(k, i["id"]) for k, i in all_placed}
    assert ("life_skill", skill_id) not in {(k, i["id"]) for k, i in all_placed}


def test_board_excludes_a_completed_story_from_backlog(board_db, board_student):
    monday = week_start()
    sid = board_student["id"]
    skills = board_db.list_life_skills(sid)
    skill_id = skills[0]["id"]
    board_db.schedule_life_skill(skill_id, (monday - timedelta(days=21)).isoformat())
    board_db.set_life_skill_done(skill_id, True)
    board_db.set_life_skill_active(skill_id, False)

    board = board_for_week(board_db, board_student, monday)
    assert board["backlog"] == []


def test_board_surfaces_an_on_the_fly_lesson_on_today(board_db, board_student):
    """Reported directly: "there is not assigned work today for landon on the
    board but his home screen shows different?" An on-demand lesson (generated
    from a subject page, so no planned_for/week_start) is due today on Home but
    used to land on no day column at all. It must appear on today's column so
    the board and Home agree."""

    monday = week_start()
    # Anchor "today" to a weekday in-range so the assertion holds every day of
    # the week -- the board only has Mon-Fri columns, so on a weekend the real
    # date.today() isn't a column key and this would spuriously KeyError.
    today_iso = monday.isoformat()
    sid = board_student["id"]
    lesson_id = board_db.save_lesson(
        student_id=sid, agent="math", subject="math", topic="t",
        title="Order of Operations", payload={"activities": []},
        metadata={},  # on the fly: no planned_for, no week_start
    )

    board = board_for_week(board_db, board_student, monday, today=monday)
    assert ("lesson", lesson_id) in {(k, i["id"]) for k, i in board[today_iso]}
    # and not duplicated into the backlog
    assert ("lesson", lesson_id) not in {(k, i["id"]) for k, i in board["backlog"]}


def test_board_keeps_only_the_newest_on_the_fly_lesson_per_subject(board_db, board_student):
    """Matching Home's one-row-per-subject roster: two undated math lessons
    don't stack two math cards on today -- only the newest surfaces."""

    monday = week_start()
    # Anchor "today" to a weekday in-range (see the sibling test) so this holds
    # on weekends too, when the real date.today() is not a board column.
    today_iso = monday.isoformat()
    sid = board_student["id"]
    older = board_db.save_lesson(
        student_id=sid, agent="math", subject="math", topic="t",
        title="Older Math", payload={"activities": []}, metadata={},
    )
    newer = board_db.save_lesson(
        student_id=sid, agent="math", subject="math", topic="t",
        title="Newer Math", payload={"activities": []}, metadata={},
    )
    board = board_for_week(board_db, board_student, monday, today=monday)
    today_lesson_ids = {i["id"] for k, i in board[today_iso] if k == "lesson"}
    assert newer in today_lesson_ids
    assert older not in today_lesson_ids


def test_board_leaves_an_on_the_fly_lesson_off_a_week_that_isnt_todays(board_db, board_student):
    """An undated 'do it now' lesson is today's work, not a future week's plan
    -- viewing next week's board must not carry it along, since today isn't one
    of that week's day columns."""
    monday = week_start()
    next_monday = monday + timedelta(days=7)
    sid = board_student["id"]
    board_db.save_lesson(
        student_id=sid, agent="math", subject="math", topic="t",
        title="Order of Operations", payload={"activities": []}, metadata={},
    )
    board = board_for_week(board_db, board_student, next_monday)
    placed = [pair for day, items in board.items() for pair in items if day != "backlog"]
    assert placed == []


# --- epic_for / group_backlog_by_epic -----------------------------------------------


@pytest.mark.parametrize(
    "kind,item,expected",
    [
        ("lesson", {"agent": "math"}, "Math"),
        ("lesson", {"agent": "science"}, "Science"),
        ("lesson", {"agent": "english"}, "English"),
        ("lesson", {"agent": "history"}, "History"),
        ("lesson", {"agent": "life_skills"}, "Life Skills"),
        ("lesson", {"agent": "coding"}, "Life Skills"),
        ("life_skill", {}, "Life Skills"),
        ("coding_module", {}, "Life Skills"),
        ("choice_topic", {}, "Life Skills"),
        ("project_step", {}, "Big Projects"),
        ("travel_entry", {}, "Big Projects"),
    ],
)
def test_epic_for_every_board_kind(kind, item, expected):
    assert epic_for(kind, item) == expected


def test_group_backlog_by_epic_covers_every_epic_even_when_empty():
    grouped = group_backlog_by_epic([])
    assert set(grouped) == set(EPIC_ORDER)
    assert all(items == [] for items in grouped.values())


def test_group_backlog_by_epic_groups_life_skills_and_coding_together():
    """Both fold into the same Life Skills epic, same as the page they
    already share (pages/6_Life_Skills.py's Coding tab)."""
    backlog = [
        ("life_skill", {"id": 1, "title": "Grocery shop on a set budget"}),
        ("coding_module", {"id": 2, "title": "Build a random decision-maker"}),
        ("project_step", {"id": 3, "title": "Storyboard the opening scene"}),
    ]
    grouped = group_backlog_by_epic(backlog)
    assert [item["id"] for _, item in grouped["Life Skills"]] == [1, 2]
    assert [item["id"] for _, item in grouped["Big Projects"]] == [3]
    assert grouped["Math"] == []
