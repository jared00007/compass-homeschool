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
) -> PlannedDay:
    """Generate and persist one subject's lesson for one specific day,
    tagging it with which week's plan it belongs to and which day it's
    meant for. The one primitive every other function in this module (and
    a page regenerating a single day later) builds on.
    """
    inputs: dict[str, Any] = {}
    if seed_topic:
        inputs["seed_topic"] = seed_topic
    if skill_id:
        inputs["skill_id"] = skill_id
    if parent_note:
        inputs["parent_note"] = parent_note
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


def plan_subject_week(
    db: Any,
    student: dict[str, Any],
    agent: LessonAgent,
    week_start_date: date,
    *,
    seed_topics: dict[int, str] | None = None,
) -> list[PlannedDay]:
    """One fresh topic per day for Science, English, and History.

    Unlike math, each of these agents' own state updates the moment a
    lesson is generated -- a new branch gets added to science's web, an era
    gets marked touched -- so calling propose-then-generate four times in
    the same sitting genuinely produces four different days; no special
    handling needed. A day's failure doesn't block the rest, since none of
    these three depend on a prior day succeeding the way math's reinforcement
    sequence does.

    `seed_topics` points a specific day (0 = the week's first day) at an
    explicit topic instead of the agent's own automatic pick -- the hook for
    slotting in something specific, like a Class CrunchLabs unit for Science
    on a chosen day.
    """
    results: list[PlannedDay] = []
    for index, target_date in enumerate(week_dates(week_start_date)):
        seed = (seed_topics or {}).get(index, "")
        results.append(plan_day(db, student, agent, week_start_date, target_date, seed_topic=seed))
    return results


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


def plan_math_week(db: Any, student: dict[str, Any], week_start_date: date) -> list[PlannedDay]:
    """Math gets one skill for the whole week, not four different topics.

    The reason lives one level down, in `graph_walk` (compass/agents/
    strategies.py): the next skill only unlocks once the parent has
    actually graded this week's assessment against real performance.
    Nothing changes between four calls made in the same Friday sitting, so
    batch-generating math the way the other three agents do would just
    hand back the same skill four times over -- not a bug, the mastery gate
    working as designed, but not a useful week's plan either.

    Instead: Monday introduces the skill the strategy would naturally pick
    next, Tuesday-Wednesday escalate practice on that same skill, and
    Thursday leans toward the graded assessment. If Monday itself fails or
    the graph is fully mastered, the rest of the week is reported as
    skipped rather than attempted -- there's nothing to reinforce yet.
    """
    from compass.agents import get_agent

    agent = get_agent("math")
    dates = week_dates(week_start_date)
    results: list[PlannedDay] = []
    skill_id = ""
    stopped_reason = ""

    for index, target_date in enumerate(dates):
        if stopped_reason:
            results.append(
                PlannedDay(target_date, agent.key, None, f"Skipped — {stopped_reason}")
            )
            continue
        day = plan_day(
            db, student, agent, week_start_date, target_date,
            skill_id=skill_id, parent_note=MATH_STAGE_NOTES[index],
        )
        results.append(day)
        if day.error:
            stopped_reason = day.error
        elif index == 0 and day.generated:
            skill_id = day.generated.proposal.metadata.get("skill_id", "")
    return results
