"""The Balanced-Week planner -- compose a week instead of hand-stacking it.

Generating a topic drops day-sized core lessons into the Backlog. Rather than
the parent dragging each one onto a day (and easily ending up with four lessons
piled on Monday), this spreads the backlog across Mon-Fri, capped at a few core
lessons per day and interleaved by subject so no day is all one thing. Enrichment
already surfaces on its own and the daily-pacing target asks for one a day, so
the planner's job is just the core-lesson distribution -- lighter, varied days.

It only moves already-generated lessons (reschedule_lesson -- same call the Board
uses), so nothing is regenerated or re-paid-for. Leftovers stay in the Backlog.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from compass import subjects, weekly

# The four core academic agents whose lessons the planner distributes.
CORE_AGENTS = ("math", "science", "english", "history")


def _interleave_by_subject(lessons: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Round-robin the lessons by agent so consecutive picks tend to be different
    subjects -- math, science, english, history, math, ... -- which is what makes
    a composed day varied instead of two of the same subject back to back."""
    by_agent: dict[str, list[dict[str, Any]]] = {}
    for lesson in lessons:
        by_agent.setdefault(lesson.get("agent", ""), []).append(lesson)
    # Stable subject order; each subject's own lessons keep their order.
    order = [a for a in CORE_AGENTS if a in by_agent] + [
        a for a in by_agent if a not in CORE_AGENTS
    ]
    queues = [list(by_agent[a]) for a in order]
    interleaved: list[dict[str, Any]] = []
    while any(queues):
        for q in queues:
            if q:
                interleaved.append(q.pop(0))
    return interleaved


@dataclass
class WeekPlan:
    """The result of composing a week: what landed on each weekday, and how many
    lessons were left in the Backlog because the week filled up."""

    week_start: date
    days: dict[str, list[str]] = field(default_factory=dict)  # ISO day -> lesson titles
    assigned: int = 0
    left_in_backlog: int = 0


def backlog_core_lessons(db: Any, student_id: int, today: str | None = None) -> list[dict[str, Any]]:
    """The pool the planner distributes: still-planned core lessons sitting in the
    Backlog (a parent held them back, or their week already elapsed)."""
    today = today or date.today().isoformat()
    pool = []
    for agent in CORE_AGENTS:
        for lesson in db.list_lessons(student_id, agent=agent, limit=500):
            if lesson["status"] == "planned" and weekly.is_backlogged(lesson, today):
                pool.append(lesson)
    return pool


def balance_week(
    db: Any,
    student_id: int,
    week_start: date,
    cap_per_day: int,
    today: str | None = None,
) -> WeekPlan:
    """Spread the backlog of core lessons across Mon-Fri of `week_start`, at most
    `cap_per_day` per day, interleaved by subject. Assigns each with
    reschedule_lesson (the Board's own move); leftovers stay in the Backlog."""
    days = [week_start + timedelta(days=i) for i in range(5)]  # Mon-Fri
    plan = WeekPlan(week_start=week_start, days={d.isoformat(): [] for d in days})
    cap = max(0, int(cap_per_day))
    if cap == 0:
        plan.left_in_backlog = len(backlog_core_lessons(db, student_id, today))
        return plan

    pool = _interleave_by_subject(backlog_core_lessons(db, student_id, today))
    slots: list[list[dict[str, Any]]] = [[] for _ in days]
    di = 0
    for lesson in pool:
        placed = False
        for _ in range(len(days)):
            if len(slots[di]) < cap:
                slots[di].append(lesson)
                di = (di + 1) % len(days)
                placed = True
                break
            di = (di + 1) % len(days)
        if not placed:
            break  # every day is at the cap

    for day_index, day_lessons in enumerate(slots):
        day_iso = days[day_index].isoformat()
        for lesson in day_lessons:
            db.reschedule_lesson(lesson["id"], day_iso)
            title = lesson.get("title") or subjects.label(lesson.get("agent", "")) + " lesson"
            plan.days[day_iso].append(title)
            plan.assigned += 1

    plan.left_in_backlog = max(0, len(pool) - plan.assigned)
    return plan
