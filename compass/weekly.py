"""Weekly planning -- Friday reviews the week just finished and plans the
week ahead, so Monday through Thursday he opens a lesson that's already
sitting there instead of someone remembering to generate one that morning.

Friday itself is deliberately not a new-content day: light review, plan next
week, and whatever time's left over goes to Big Projects or Life Skills,
ad hoc -- see `WEEKDAYS` below, which is Monday-Thursday only.

A planned lesson carries two extra keys in its own `metadata` (no schema
change -- the same place `student_done_on`, `quiz_result`, and `life_skill_id`
already live):

    week_start   ISO date of the Monday this lesson was planned for
    planned_for  ISO date of the specific day within that week

That's enough to answer "what's this week's plan" without a new table --
`Database.lessons_for_week` just filters on `metadata.week_start`.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any


# Friday is review/plan/filler, not a scheduled new-content day -- see the
# module docstring.
WEEKDAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday")


def week_start(on: date | None = None) -> date:
    """The Monday of the week containing `on`."""
    on = on or date.today()
    return on - timedelta(days=on.weekday())


def week_dates(start: date, *, include_friday: bool = False) -> list[date]:
    """The scheduled dates for the week beginning `start`: Monday-Thursday,
    plus Friday itself when `include_friday=True`.

    Friday stays out by default -- see the module docstring for why it's
    not a new-content day -- but callers that render the board pass
    `include_friday=True` so it shows as a fifth column, giving a week that
    lost a weekday to a holiday somewhere to still put five lesson days.

    `start` is assumed to already be a Monday -- callers get one from
    `week_start()` rather than an arbitrary date, so this doesn't re-derive it.
    """
    dates = [start + timedelta(days=i) for i in range(len(WEEKDAY_NAMES))]
    if include_friday:
        dates.append(start + timedelta(days=4))
    return dates



def default_plan_target(on: date | None = None) -> date:
    """The Monday of *next* week relative to `on` -- the sensible default for
    "which week should Friday's planning target," since planning is always
    for the week ahead, not the one about to end."""
    return week_start(on) + timedelta(days=7)


def latest_per_day(lessons: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Regenerating a day inserts a fresh lesson rather than replacing the
    old one -- same "newest wins, nothing gets deleted" approach already
    used for life-skill plans (`Database.latest_life_skill_plan`). Keyed on
    (agent, planned_for) so a superseded lesson just stops being shown here
    rather than needing to be deleted; it's still there for Activity Log's
    own "to review" cleanup if it was never logged.

    `lessons` must already be sorted oldest-first (planned_for, id), which
    is exactly what `Database.lessons_for_week` returns -- iterating in that
    order and overwriting a dict keyed by (agent, planned_for) naturally
    keeps the newest entry for each day. Shared by `pages/14_Mission_Control.py`
    (the parent's planner) and Home's Week tab (the student's read-only
    view of the same plan).
    """
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for lesson in lessons:
        key = (lesson["agent"], lesson["metadata"].get("planned_for", ""))
        latest[key] = lesson
    return sorted(
        latest.values(), key=lambda l: (l["metadata"].get("planned_for", ""), l["id"])
    )


def is_backlogged(lesson: dict[str, Any], today: str) -> bool:
    """Whether this lesson belongs in the backlog -- reported directly: a
    parent wants explicit control over when a missed assignment
    reappears, not to have it silently pile up as "overdue" forever on
    Landon's own view. A lesson in this state is pulled out of
    `due_lessons` below entirely; Activity Log's Backlog section is the
    only place it's still visible, until a parent explicitly moves it to
    a new day (`Database.reschedule_lesson`), at which point it's live
    again exactly like a freshly planned lesson.

    Three ways in, checked in this order:

    1. `metadata.held_back` -- a parent explicitly sent it there
       (`Database.send_to_backlog`), any lesson, any day, whether it's
       even due yet. This is the "move a story to the backlog myself,
       whenever I decide, not just once its whole week has quietly run
       out" freedom, reported directly.
    2. An unscheduled lesson from a generated series (`series_id` set,
       no `planned_for`): a series is raw material the parent schedules
       by day, so it lives in the backlog until they assign one. New
       series lessons also carry `held_back` (caught above); this catches
       ones generated before that flag existed, so they don't strand in
       the "planned" list.
    3. Its whole week already ended without it being turned in, with
       nobody touching it by hand at all -- the original, automatic path.

    Only the second check needs a `planned_for` at all -- an on-demand
    lesson (no week concept) can still be sent to backlog by hand, but
    never falls into it just from time passing, matching `due_lessons`'
    own unbounded treatment of an undated lesson otherwise. Status isn't
    checked here (same as `due_lessons` itself) -- every caller already
    narrows to still-open lessons before this runs.
    """
    metadata = lesson.get("metadata") or {}
    if metadata.get("held_back"):
        return True
    planned_for = metadata.get("planned_for") or ""
    if metadata.get("series_id") and not planned_for:
        return True
    if not planned_for:
        return False
    return week_start(date.fromisoformat(planned_for)) < week_start(date.fromisoformat(today))


def due_lessons(lessons: list[dict[str, Any]], today: str) -> list[dict[str, Any]]:
    """Filter to what's actually due now: today's, or overdue from an
    earlier day within the *same* week -- sorted oldest-overdue-first,
    then today's, then anything with no `planned_for` at all (ordinary
    on-demand generation, never batch-planned) last. A lesson planned for
    a day *later* than today is excluded outright, same as it doesn't
    belong in Home's own "Lessons ready for you" list either -- a caller
    that also wants a "later this week" count computes that separately
    from whatever this excluded, since that split needs the week's own
    end date, which isn't this function's business.

    Once a lesson's whole week has ended without being turned in, it's
    backlogged (see `is_backlogged` above) and drops out here too --
    indefinitely overdue is not the same as due, and a parent choosing to
    hold it back is not something this function should keep overriding by
    surfacing it anyway.

    Shared by Home (across every agent at once) and student_lesson_view
    (one agent's own subject page) so both pick the exact same lesson --
    the whole reason this exists is that they used to disagree: Home was
    already day-aware, but a subject page's own view just grabbed whichever
    lesson happened to be generated most recently, which is a different
    thing entirely once a whole week gets batch-planned in one sitting.
    """
    due = [
        lesson
        for lesson in lessons
        if not ((lesson.get("metadata") or {}).get("planned_for") or "") > today
        and not is_backlogged(lesson, today)
    ]

    def _order(lesson: dict[str, Any]) -> tuple[str, int]:
        metadata = lesson.get("metadata") or {}
        # A multi-day series carries no `planned_for` -- it walks in
        # `series_index` order instead, so day 1 shows before day 2 regardless
        # of which was generated (or listed) first. The sort is stable, so
        # non-series lessons (all index 0) keep the caller's input order.
        return (
            metadata.get("planned_for") or "9999-99-99",
            int(metadata.get("series_index") or 0),
        )

    due.sort(key=_order)
    return due


def _stuck_on_an_untracked_weekday(scheduled_for: str | None) -> bool:
    """Whether a scheduled date can *never* be found by any week's own
    `_for_week` query -- every one of those (life_skills_for_week and its
    four counterparts) filters `scheduled_for BETWEEN week_start AND
    week_start + 4 days`, i.e. Monday-Friday. A Saturday or Sunday date is
    permanently outside that range for every week, not just the current
    one, so a story stuck there needs a different way back onto the
    board's radar -- see `board_for_week`'s own "every other
    currently-parked story" pass below."""
    if not scheduled_for:
        return False
    return date.fromisoformat(scheduled_for).weekday() >= 5


def board_for_week(
    db: Any, student: dict[str, Any], week_start_date: date, today: date | None = None
) -> dict[str, list[tuple[str, dict[str, Any]]]]:
    """Every story assigned to one Monday-anchored week, or currently
    backlogged regardless of which week it was originally for -- the raw
    material for the unified weekly board (pages/14_Mission_Control.py's own
    "Board" tab, the one place a parent can see and rearrange every
    subject's stories at once instead of hunting through each subject's
    own page).

    Six buckets in the returned dict: one per weekday Monday-Friday (keyed
    by that day's own ISO date), plus `"backlog"` -- a single pool shared
    across every story type, matching how each subject's own Backlog
    section already treats things (parking something doesn't care which
    week it came from, and pulling it back in works the same regardless of
    where it started).

    Each bucket holds `(kind, item)` pairs, `kind` one of "lesson",
    "life_skill", "coding_module", "choice_topic", "project_step", or
    "travel_entry" -- callers dispatch on that to pick the right title,
    icon, and move-control wiring (see `render_board_card` in
    `compass.ui`).

    A story backlogged *within* the target week's own date range shows
    only in "backlog", never also under its stale day -- otherwise it'd
    render twice, once under a day that no longer means anything now that
    it's parked. That's what `_place_scheduled`'s branch does. The second
    half of this function is a separate pass over every *other* currently
    backlogged story regardless of which week (or no week at all) it was
    assigned to -- `_for_week` only returns rows whose date already falls
    in this specific range, so a story backlogged from some other week
    would otherwise never surface here at all. `backlogged_ids` guards
    against double-adding a story counted by both passes.
    """
    today = today or date.today()
    today_iso = today.isoformat()
    week_start_iso = week_start_date.isoformat()
    student_id = student["id"]

    days = [(week_start_date + timedelta(days=i)).isoformat() for i in range(5)]
    board: dict[str, list[tuple[str, dict[str, Any]]]] = {d: [] for d in days}
    board["backlog"] = []
    backlogged_ids: dict[str, set[int]] = {}

    def _place_scheduled(
        day_iso: str, backlogged: bool, kind: str, item: dict[str, Any]
    ) -> None:
        # A story's own date can land on a day this board simply doesn't
        # track -- a weekend, most commonly, since the five day-columns
        # are Monday-Friday only -- without being "backlogged" by any of
        # the checks above. That used to fall through both branches here
        # and vanish outright: not on any day column, not in the Backlog
        # panel either, invisible on the one page meant to show every
        # story at once. Reported directly, and confirmed against a real
        # lesson stuck exactly this way: "i moved two math lessons from
        # backlog to their own dates... and they have disappeared."
        # Backlog is the fallback now -- a story with nowhere else to go
        # is still a story a parent can find and re-place, never one that
        # just silently isn't anywhere.
        if backlogged or day_iso not in board:
            board["backlog"].append((kind, item))
            backlogged_ids.setdefault(kind, set()).add(item["id"])
        else:
            board[day_iso].append((kind, item))

    for lesson in latest_per_day(db.lessons_for_week(student_id, week_start_iso)):
        planned_for = lesson["metadata"].get("planned_for", "")
        _place_scheduled(planned_for, is_backlogged(lesson, today_iso), "lesson", lesson)

    for skill in db.life_skills_for_week(student_id, week_start_iso):
        _place_scheduled(skill["scheduled_for"], not skill["active"], "life_skill", skill)

    for module in db.coding_modules_for_week(student_id, week_start_iso):
        _place_scheduled(module["scheduled_for"], not module["active"], "coding_module", module)

    for topic in db.choice_topics_for_week(student_id, week_start_iso):
        _place_scheduled(topic["scheduled_for"], not topic["active"], "choice_topic", topic)

    for step in db.project_steps_for_week(student_id, week_start_iso):
        _place_scheduled(step["scheduled_for"], not step["active"], "project_step", step)

    for trip in db.travel_entries_for_week(student_id, week_start_iso):
        _place_scheduled(trip["scheduled_for"], not trip["active"], "travel_entry", trip)

    # --- Every other currently-parked story, any week (or no week at all)
    # it originally belonged to. Only closed-out stories are excluded --
    # same "nothing left for a move to do" reasoning every subject's own
    # Backlog section already applies.
    #
    # `_stuck_on_an_untracked_weekday` catches a second, harder-to-see way
    # a story can go permanently invisible: life_skills_for_week and its
    # four counterparts below all query `scheduled_for BETWEEN week_start
    # AND week_start + 4 days` (Monday-Friday) -- a story scheduled for a
    # Saturday or Sunday never falls in *any* week's version of that range,
    # so it never reaches `_place_scheduled` at all, for any week, ever.
    # Since it's also still `active` (a parent never sent it to backlog on
    # purpose), the "every other currently-parked story" checks below used
    # to miss it too -- those only ever looked for `not active`. A story
    # stuck this way needs to surface here regardless of its active flag,
    # or nothing on the whole Board would ever show it again.
    # On-the-fly lessons -- generated on demand from a subject page rather than
    # batch-planned -- carry no planned_for/week_start, so they never land on
    # any day column above and (unless a parent parked them) aren't backlogged
    # either. Home's own daily roster still shows them as due today
    # (due_lessons treats an undated open lesson as due now), which made the
    # board read empty on a day Landon actually had work -- reported directly:
    # "there is not assigned work today for landon on the board but his home
    # screen shows different?" Surface the still-open ones on today's column so
    # the board and Home agree, newest-per-subject to match Home's
    # one-row-per-subject roster, and only when today is one of the five day
    # columns (a past/future week's board shows that week's plan, not today's
    # ad-hoc work).
    seen_undated_agents: set[str] = set()
    for lesson in db.list_lessons(student_id, limit=200):
        if lesson["id"] in backlogged_ids.get("lesson", set()):
            continue
        metadata = lesson.get("metadata") or {}
        if lesson["status"] == "planned" and is_backlogged(lesson, today_iso):
            board["backlog"].append(("lesson", lesson))
            continue
        if (
            today_iso in board
            and lesson["status"] == "planned"
            and not metadata.get("planned_for")
            and not metadata.get("student_done_on")
            and lesson["agent"] not in seen_undated_agents
        ):
            seen_undated_agents.add(lesson["agent"])
            board[today_iso].append(("lesson", lesson))

    # `scheduled_for is not None` is doing real work here, not just
    # matching the other passes' shape: life_skills/coding_modules are
    # pre-seeded from a ~150-entry starter catalog, the vast majority of
    # it sitting `active=0` from the moment it's seeded simply because it
    # was never unlocked -- not because a parent ever parked it. Without
    # this, the board's Backlog column would drown in the entire untouched
    # catalog rather than showing only what a parent actually engaged with
    # (unlocked and assigned a day) and then chose to pull back. An
    # inactive-and-never-scheduled entry is still findable on the Master
    # List, same as always -- it just isn't board clutter.
    for skill in db.list_life_skills(student_id):
        if (
            not skill["completed_on"]
            and skill["scheduled_for"]
            and skill["id"] not in backlogged_ids.get("life_skill", set())
            and (not skill["active"] or _stuck_on_an_untracked_weekday(skill["scheduled_for"]))
        ):
            board["backlog"].append(("life_skill", skill))

    for module in db.list_coding_modules(student_id):
        if (
            not module["completed_on"]
            and module["scheduled_for"]
            and module["id"] not in backlogged_ids.get("coding_module", set())
            and (not module["active"] or _stuck_on_an_untracked_weekday(module["scheduled_for"]))
        ):
            board["backlog"].append(("coding_module", module))

    for topic in db.list_choice_topics(student_id):
        if (
            topic["status"] not in ("done", "declined")
            and topic["id"] not in backlogged_ids.get("choice_topic", set())
            and (not topic["active"] or _stuck_on_an_untracked_weekday(topic["scheduled_for"]))
        ):
            board["backlog"].append(("choice_topic", topic))

    for project in db.list_big_projects(student_id):
        if project["shelved"] or project["kind"] == "travel_log":
            continue
        for step in db.list_project_steps(project["id"]):
            if (
                not step["completed_on"]
                and step["id"] not in backlogged_ids.get("project_step", set())
                and (not step["active"] or _stuck_on_an_untracked_weekday(step["scheduled_for"]))
            ):
                board["backlog"].append(("project_step", step))

    for trip in db.list_travel_entries(student_id):
        if (
            trip["status"] != "completed"
            and trip["id"] not in backlogged_ids.get("travel_entry", set())
            and (not trip["active"] or _stuck_on_an_untracked_weekday(trip["scheduled_for"]))
        ):
            board["backlog"].append(("travel_entry", trip))

    return board


# The order every epic-grouped view (the Board tab's Product Backlog panel)
# lists epics in -- core subjects first in their usual order, then the two
# catch-all epics last, matching how the parent described the grouping.
EPIC_ORDER = ("Math", "Science", "English", "History", "Life Skills", "Big Projects")

_LESSON_AGENT_EPIC = {
    "math": "Math", "science": "Science", "english": "English", "history": "History",
    # Both fold into the Life Skills epic, same as the page they already
    # share (pages/6_Life_Skills.py's Coding tab) -- a generated lesson
    # from either agent is still a Life Skills story, not a seventh epic.
    "life_skills": "Life Skills", "coding": "Life Skills",
}
_KIND_EPIC = {
    "life_skill": "Life Skills", "coding_module": "Life Skills", "choice_topic": "Life Skills",
    # Travel Journal auto-folds into Big Projects (Database.ensure_travel_log_project),
    # so its entries belong to that epic here too, not a standalone one.
    "project_step": "Big Projects", "travel_entry": "Big Projects",
}


def epic_for(kind: str, item: dict[str, Any]) -> str:
    """Which epic (see EPIC_ORDER) a board story belongs to. Lessons key
    off their own agent -- every other kind has one fixed epic regardless
    of its own fields."""
    if kind == "lesson":
        return _LESSON_AGENT_EPIC.get(item["agent"], item["agent"].title())
    return _KIND_EPIC.get(kind, kind.replace("_", " ").title())


def group_backlog_by_epic(
    backlog: list[tuple[str, dict[str, Any]]],
) -> dict[str, list[tuple[str, dict[str, Any]]]]:
    """Reshapes `board_for_week`'s own flat `"backlog"` list into
    epic-grouped order for the Board tab's Product Backlog panel -- no new
    query, since that list is already every currently-parked story
    regardless of which week it came from (see `board_for_week`'s own
    docstring on its two-pass Backlog sweep). Every epic in EPIC_ORDER
    gets an entry, empty list included, so a caller can iterate the fixed
    order and skip whichever come back empty without a KeyError."""
    grouped: dict[str, list[tuple[str, dict[str, Any]]]] = {epic: [] for epic in EPIC_ORDER}
    for kind, item in backlog:
        grouped.setdefault(epic_for(kind, item), []).append((kind, item))
    return grouped


def today_subject_status(
    lessons: list[dict[str, Any]], today: str
) -> tuple[dict[str, Any] | None, str]:
    """One subject's row for Home's daily roster: whichever lesson is
    actually relevant right now for this agent, and a marker reflecting
    its real review-gate state -- not just whether he's touched it.

    Same priority order student_lesson_view uses on the subject's own
    page (a pending review always wins over anything new due), so Home's
    roster and the subject page never disagree about which lesson is
    "the" one right now:

        submitted        -> waiting on a parent               "\U0001F4E4"
        needs_revision   -> sent back, waiting on him again    "↩️"
        due now, planned -> nothing turned in yet              "⬜"
        completed today  -> a parent fully approved it today   "✅"
        anything else    -> nothing relevant to show right now (None, "")

    Unlike the subject page, a fully resolved lesson doesn't just vanish
    here: reflecting the actual goal (see a green check once a parent's
    signed off) means the roster keeps showing the subject once there's
    nothing else due, rather than reading as if nothing had ever been
    assigned.
    """
    pending = next((l for l in lessons if l["status"] in ("submitted", "needs_revision")), None)
    if pending is not None:
        marker = "\U0001F4E4" if pending["status"] == "submitted" else "↩️"
        return pending, marker

    todo = [
        l
        for l in lessons
        if l["status"] not in ("skipped", "submitted", "needs_revision", "completed")
        and not (l.get("metadata") or {}).get("student_done_on")
    ]
    due_now = due_lessons(todo, today)
    if due_now:
        return due_now[0], "⬜"

    completed_today = [
        l
        for l in lessons
        if l["status"] == "completed" and (l.get("metadata") or {}).get("student_done_on") == today
    ]
    if completed_today:
        return completed_today[0], "✅"

    # A finished lesson that still carries a note he hasn't read and replied to
    # keeps the subject on the roster as a pointer -- the note itself lives in
    # the lesson on the subject page, this just makes sure he's sent there
    # rather than the subject going quiet with an unread note left behind.
    note_pending = next(
        (l for l in lessons if l["status"] == "completed" and _has_unread_approval_note(l)),
        None,
    )
    if note_pending is not None:
        return note_pending, "\U0001F4E3"  # 📣

    return None, ""


def _has_unread_approval_note(lesson: dict[str, Any]) -> bool:
    """Whether any writing piece in this lesson was approved with a note he
    hasn't yet read and replied to -- the signal that keeps an otherwise-done
    lesson visible until he's actually seen his parent's note."""
    reviews = (lesson.get("metadata") or {}).get("writing_review") or {}
    return any(
        rv.get("approval_feedback") and not rv.get("approval_read_at")
        for rv in reviews.values()
    )
