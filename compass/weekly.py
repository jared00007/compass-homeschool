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

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from compass.agents.framework import GeneratedLesson, LessonAgent, StudentContext
from compass.agents.llm import LessonGenerationError

# Friday is review/plan/filler, not a scheduled new-content day -- see the
# module docstring.
WEEKDAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday")


def week_start(on: date | None = None) -> date:
    """The Monday of the week containing `on`."""
    on = on or date.today()
    return on - timedelta(days=on.weekday())


def week_dates(start: date) -> list[date]:
    """The four scheduled dates (Monday-Thursday) for the week beginning `start`.

    `start` is assumed to already be a Monday -- callers get one from
    `week_start()` rather than an arbitrary date, so this doesn't re-derive it.
    """
    return [start + timedelta(days=i) for i in range(len(WEEKDAY_NAMES))]


# --- school-day streaks --------------------------------------------------------
# A run of school days he actually did work on. Weekends are skipped rather
# than counted as misses, which matters more than it sounds: counting them
# would reset the streak to zero every Monday morning, turning the one
# mechanic meant to reward showing up into a weekly reminder that he failed.


def _school_days_back(today: date):
    """Weekdays, today first, walking backwards. Weekends never appear."""
    day = today
    while True:
        if day.weekday() < 5:
            yield day
        day -= timedelta(days=1)


def _is_deliberate_day_off(
    day: date, planned_days: set[str] | None, planned_weeks: set[str] | None
) -> bool:
    """Whether `day` looks like a real, deliberate day off -- a holiday
    unchecked in This Week's school-days picker -- rather than a day he
    just didn't get to.

    Both sets have to agree, and for a reason that isn't obvious: a day
    missing from `planned_days` alone is ambiguous. It's exactly what a
    genuine holiday looks like, but it's *also* exactly what every single
    day looks like for a family that never uses This Week's batch planner
    at all and generates every lesson on demand instead -- `planned_days`
    would just be permanently empty, and treating every gap as forgivable
    would silently make the whole streak meaningless (never breakable, no
    matter how long he actually goes without doing anything).

    `planned_weeks` is what breaks that tie: it only forgives a day if its
    *week* was actually run through the batch planner at all -- one of its
    days really did get planned_for -- and this particular day still isn't
    among them. A family that never touches This Week has an empty
    `planned_weeks` forever, so nothing here ever fires and every gap is
    judged exactly as it was before this existed.
    """
    if planned_days is None or planned_weeks is None:
        return False
    if day.isoformat() in planned_days:
        return False  # it *was* planned -- missing from active_days is a real miss
    return week_start(day).isoformat() in planned_weeks


def current_streak(
    active_days: set[str],
    today: date | None = None,
    planned_days: set[str] | None = None,
    planned_weeks: set[str] | None = None,
) -> int:
    """How many school days in a row, ending now, he did work on.

    Today not being done *yet* doesn't break the run -- the count just picks
    up from yesterday. Otherwise every streak would read zero each morning
    until he finished something, which is exactly backwards: the moment you
    most want it to say "you're on 6, keep it going" is before he's started.

    Checks `day == today` rather than `index == 0` for that forgiveness,
    because they're not the same thing on a weekend: `_school_days_back`
    skips Saturday/Sunday entirely, so when `today` itself is a weekend day
    the first day it yields is last Friday -- an already-elapsed school day,
    not "today, still in progress." `index == 0` used to forgive that Friday
    the same way it forgives an actual today, silently letting a missed
    Friday slide every single weekend that followed it.

    `planned_days`/`planned_weeks` (see the matching `Database` methods and
    `_is_deliberate_day_off`) are what tell a genuine holiday apart from a
    day he just didn't get to: a day that looks deliberately skipped is
    treated exactly like a weekend -- neither breaking the streak nor
    adding to it. Leaving either at `None` (the default) skips that check
    entirely, so every weekday is judged the plain way, for callers that
    don't track planning.
    """
    today = today or date.today()
    streak = 0
    for index, day in enumerate(_school_days_back(today)):
        if index > 400:  # pragma: no cover - defensive bound
            break
        day_iso = day.isoformat()
        if day_iso in active_days:
            streak += 1
        elif day == today:
            continue  # today is simply still in progress
        elif _is_deliberate_day_off(day, planned_days, planned_weeks):
            continue  # a real day off, not a miss
        else:
            break
    return streak


def best_streak(
    active_days: set[str],
    today: date | None = None,
    planned_days: set[str] | None = None,
    planned_weeks: set[str] | None = None,
) -> int:
    """His longest run ever, for the streak to be worth protecting.

    Computed from the same history rather than stored, so it can't drift out
    of step with the days it's counting.

    `planned_days`/`planned_weeks` carry the same deliberate-day-off check
    `current_streak` uses -- such a day leaves `run` untouched rather than
    resetting it to 0, so a genuine holiday in the middle of an otherwise
    unbroken run doesn't quietly cap his best-ever number below what it
    should be.
    """
    if not active_days:
        return 0
    today = today or date.today()
    # Forward from the first day he ever recorded, rather than backwards from
    # today -- `_school_days_back` is unbounded, and walking it to the start
    # of history runs off the end of `date` itself.
    day = date.fromisoformat(min(active_days))
    best = run = 0
    while day <= today:
        if day.weekday() < 5 and not _is_deliberate_day_off(day, planned_days, planned_weeks):
            run = run + 1 if day.isoformat() in active_days else 0
            best = max(best, run)
        day += timedelta(days=1)
    return best


def default_plan_target(on: date | None = None) -> date:
    """The Monday of *next* week relative to `on` -- the sensible default for
    "which week should Friday's planning target," since planning is always
    for the week ahead, not the one about to end."""
    return week_start(on) + timedelta(days=7)


def planning_nudge(db: Any, student_id: int, today: date | None = None) -> tuple[str, str] | None:
    """Whether a parent's dashboard should flag that planning got skipped,
    and what to say -- factored out of Home.py so the date logic is
    testable without going through a full page render (see school_calendar's
    own injectable `on` param for the same reasoning).

    Monday through Thursday only ever has a lesson waiting because someone
    ran This Week's "Plan next week" ahead of time; nothing else says so if
    that never happened. Two tiers, worst case first: a warning if the
    *current* week has no lessons planned at all (an actual problem, any
    day of it -- today's lesson may simply not exist), or an info note if
    it's Fri/Sat/Sun and *next* week isn't set up yet (not yet a problem --
    Friday just hasn't happened, or hasn't finished happening). Returns
    `None` the rest of the time: everything due is already planned, or it's
    still too early in the week to expect it.

    Returns `(severity, message)` where `severity` is a literal Streamlit
    method name ("warning" or "info") a caller can `getattr(st, severity)`
    on directly.
    """
    today = today or date.today()
    this_week_planned = bool(
        latest_per_day(db.lessons_for_week(student_id, week_start(today).isoformat()))
    )
    if today.weekday() <= 3 and not this_week_planned:
        return (
            "warning",
            "⚠️ This week hasn't been planned yet — Monday through Thursday's "
            "lessons don't exist. Head to **This Week → Plan next week** (it can "
            "target any week, not just the upcoming one).",
        )

    if today.weekday() >= 4:
        next_week_planned = bool(
            latest_per_day(
                db.lessons_for_week(student_id, default_plan_target(today).isoformat())
            )
        )
        if not next_week_planned:
            return (
                "info",
                "📅 Next week hasn't been planned yet — usually a Friday thing. "
                "Head to **This Week → Plan next week** when you get a chance.",
            )

    return None


# --- batch generation ----------------------------------------------------------


@dataclass
class PlannedDay:
    """The result of planning one subject's lesson for one day -- always
    produced, even on failure, so a page can render a consistent 4-row table
    regardless of what happened underneath."""

    target_date: date
    subject: str
    generated: GeneratedLesson | None
    error: str | None = None


def plan_day(
    db: Any,
    student: dict[str, Any],
    agent: LessonAgent,
    week_start_date: date,
    target_date: date,
    *,
    seed_topic: str = "",
    skill_id: str = "",
    parent_note: str = "",
    node_id: str = "",
) -> PlannedDay:
    """Generate and persist one subject's lesson for one specific day,
    tagging it with which week's plan it belongs to and which day it's
    meant for. The one primitive every other function in this module (and
    a page regenerating a single day later) builds on.

    `node_id` points Science/History at a specific open branch already
    sitting in their topic web (see spiderweb/timeline's own
    `ctx.inputs.get("node_id")`) -- the same mechanism their single-lesson
    pages use, now reachable from the batch planner too. `seed_topic` wins
    over it if both are given, same priority those strategies already
    apply.
    """
    inputs: dict[str, Any] = {}
    if seed_topic:
        inputs["seed_topic"] = seed_topic
    if skill_id:
        inputs["skill_id"] = skill_id
    if parent_note:
        inputs["parent_note"] = parent_note
    if node_id:
        inputs["node_id"] = node_id
    ctx = StudentContext(db=db, student_id=student["id"], student=student, inputs=inputs)

    try:
        proposal = agent.propose_topic(ctx)
        if proposal.blocked:
            return PlannedDay(target_date, agent.key, None, proposal.blocked_reason or "Blocked.")
        proposal.metadata["week_start"] = week_start_date.isoformat()
        proposal.metadata["planned_for"] = target_date.isoformat()
        generated = agent.generate(ctx, proposal)
        return PlannedDay(target_date, agent.key, generated, None)
    except LessonGenerationError as exc:
        return PlannedDay(target_date, agent.key, None, str(exc))



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
    keeps the newest entry for each day. Shared by `pages/14_This_Week.py`
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


def due_lessons(lessons: list[dict[str, Any]], today: str) -> list[dict[str, Any]]:
    """Filter to what's actually due now: today's, or overdue from an
    earlier day -- sorted oldest-overdue-first, then today's, then anything
    with no `planned_for` at all (ordinary on-demand generation, never
    batch-planned) last. A lesson planned for a day *later* than today is
    excluded outright, same as it doesn't belong in Home's own "Lessons
    ready for you" list either -- a caller that also wants a "later this
    week" count computes that separately from whatever this excluded, since
    that split needs the week's own end date, which isn't this function's
    business.

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
    ]
    due.sort(key=lambda lesson: (lesson.get("metadata") or {}).get("planned_for") or "9999-99-99")
    return due


MATH_STAGE_NOTES: tuple[str, ...] = (
    "",  # Day 1: no note. A fresh introduction, taught the normal way.
    "This is day 2 of 4 on this same skill this week -- additional "
    "practice, not a re-introduction. Escalate the difficulty slightly "
    "from the first day.",
    "This is day 3 of 4 on this same skill this week -- more practice, "
    "escalating further toward the assessment.",
    "This is day 4 of 4 on this same skill this week -- weight this "
    "lesson toward the graded assessment that determines whether the "
    "next skill unlocks next week.",
)


def math_stage_note(index: int, total: int) -> str:
    """The same escalating note as MATH_STAGE_NOTES, generalized to
    however many school days a week actually has -- a holiday can shrink
    it to two or three, and "day 2 of 4" is simply wrong once the week
    itself is only 2 or 3 days long.

    The ordinary four-day case reuses MATH_STAGE_NOTES verbatim (its two
    middle days read differently from each other -- "escalate slightly"
    vs. "more practice, escalating further" -- which a generic formula
    below collapses into one repeated sentence). Only a week actually
    shortened by something like a holiday falls through to the generic
    three-tier version: no note on day one, escalating practice through
    the middle, weighted toward the assessment on the last day (which can
    be the same day as the first, on a single-day week).
    """
    if total == 4:
        return MATH_STAGE_NOTES[index]
    if index == 0:
        return ""
    if index == total - 1:
        return (
            f"This is day {index + 1} of {total} on this same skill this week -- "
            "weight this lesson toward the graded assessment that determines "
            "whether the next skill unlocks next week."
        )
    return (
        f"This is day {index + 1} of {total} on this same skill this week -- "
        "additional practice, not a re-introduction, escalating toward the "
        "assessment."
    )


def plan_missing_days(
    db: Any,
    student: dict[str, Any],
    agent: LessonAgent,
    week_start_date: date,
    target_dates: list[date],
    missing_dates: list[date],
    *,
    is_math: bool = False,
    skill_id: str = "",
    seed_topics: dict[int, str] | None = None,
    node_ids: dict[int, str] | None = None,
) -> list[PlannedDay]:
    """Generate whichever of `target_dates` are still missing a lesson
    (`missing_dates`, always a subset) for one subject/agent.

    `target_dates` is the full checked-days list for the week (see the
    school-days picker on pages/14_This_Week.py) -- `math_stage_note` and
    `seed_topics`/`node_ids` both need a day's position in the *whole*
    week, not just its position among the days still missing a lesson, so
    both lists are taken separately rather than one being inferred from
    the other.

    Math (`is_math=True`) reuses one skill for the whole week rather than
    a fresh topic each day. The reason lives one level down, in
    `graph_walk` (compass/agents/strategies.py): the next skill only
    unlocks once the parent has actually graded this week's assessment
    against real performance, so calling propose-then-generate several
    times in the same sitting would just hand back the same skill every
    time -- not a bug, the mastery gate working as designed, but not a
    useful week's plan either. Instead, the first missing day introduces
    the skill (or continues `skill_id`, when an earlier day this week
    already picked one and only later days are being filled in);
    `math_stage_note` escalates the framing on each day after that toward
    the graded assessment. Once any day fails -- a real error, or the
    graph turning out to already be fully mastered -- every day after it
    in this call is reported as skipped rather than attempted: continuing
    to reinforce a skill that never got confirmed would frame the rest of
    the week around whatever the agent's own automatic pick happened to
    be at that moment, not the skill that actually failed.

    Non-math subjects have no such dependency -- each of their own
    agents' state updates the moment a lesson is generated (a new branch
    added to Science's web, an era marked touched in History) -- so one
    day's failure never blocks the rest.

    `seed_topics`/`node_ids` point a specific day (keyed by its index in
    `target_dates`) at an explicit topic or an already-open branch instead
    of the agent's own automatic pick -- the hook for slotting in
    something specific, like a Class CrunchLabs unit for Science on a
    chosen day.
    """
    results: list[PlannedDay] = []
    stopped_reason = ""
    for target_date in missing_dates:
        index = target_dates.index(target_date)
        if is_math and stopped_reason:
            results.append(
                PlannedDay(target_date, agent.key, None, f"Skipped — {stopped_reason}")
            )
            continue
        day = plan_day(
            db, student, agent, week_start_date, target_date,
            seed_topic=(seed_topics or {}).get(index, ""),
            skill_id=skill_id,
            parent_note=math_stage_note(index, len(target_dates)) if is_math else "",
            node_id=(node_ids or {}).get(index, ""),
        )
        results.append(day)
        if is_math:
            if day.error:
                stopped_reason = day.error
            elif index == 0 and day.generated:
                skill_id = day.generated.proposal.metadata.get("skill_id", "")
    return results
