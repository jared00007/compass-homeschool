"""XP and levels -- the connective tissue that turns everything he already
finishes into visible progress. Deliberately *computed live* from his own
completion signals rather than stored: there's no score column to drift out of
sync, re-approving or un-approving something just recomputes, and it never
waits on a parent to log hours (same reasoning the week progress gauge and the
Today checklist use his own `student_done_on` signal, not the activity log).

Pure motivation, not a compliance measure -- the point values and the level
curve are all tunable knobs in config.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from compass import config


@dataclass(frozen=True)
class XPState:
    total: int          # all XP earned, ever
    level: int          # 1-based
    title: str          # rank name for this level
    into_level: int     # XP earned toward the current level
    level_span: int     # XP a full level is worth (config.XP_PER_LEVEL)
    to_next: int        # XP still needed to reach the next level

    @property
    def fraction(self) -> float:
        """Progress through the current level, 0.0-1.0 -- ready for st.progress."""
        if self.level_span <= 0:
            return 0.0
        return self.into_level / self.level_span


def _rank_for_level(level: int) -> str:
    """The rank name for a level. The last name in the list holds for every
    level beyond it, so a long streak of progress never runs out of titles."""
    ranks = config.XP_RANKS
    if not ranks:
        return f"Level {level}"
    return ranks[min(level - 1, len(ranks) - 1)]


def total_xp(db: Any, student_id: int) -> int:
    """Sum XP across everything he's finished, from his own signals.

    Lessons count off `student_done_on` (his "I did it," not a parent's later
    approval), with a bonus for a quiz he passed. Life skills, coding modules,
    travel entries, and choice topics count once each once they're done, and
    every mastered math skill adds a little. All point values live in config.
    """
    total = 0

    for lesson in db.list_lessons(student_id, limit=500):
        metadata = lesson.get("metadata") or {}
        if metadata.get("student_done_on"):
            total += config.XP_PER_LESSON
        quiz_result = metadata.get("quiz_result") or {}
        if quiz_result.get("passed"):
            total += config.XP_QUIZ_PASS_BONUS

    total += config.XP_PER_LIFE_SKILL * sum(
        1 for s in db.list_life_skills(student_id) if s.get("completed_on")
    )
    total += config.XP_PER_CODING_MODULE * sum(
        1 for m in db.list_coding_modules(student_id) if m.get("completed_on")
    )
    total += config.XP_PER_TRAVEL_ENTRY * sum(
        1 for t in db.list_travel_entries(student_id) if t.get("status") == "completed"
    )
    total += config.XP_PER_CHOICE_TOPIC * sum(
        1 for c in db.list_choice_topics(student_id) if c.get("status") == "done"
    )
    total += config.XP_PER_MASTERED_SKILL * len(db.mastered_skills(student_id))

    return total


def state_for_total(total: int) -> XPState:
    """Turn a raw XP total into a level, rank, and progress -- split out so it's
    unit-testable without a database."""
    span = config.XP_PER_LEVEL
    level = total // span + 1
    into_level = total % span
    return XPState(
        total=total,
        level=level,
        title=_rank_for_level(level),
        into_level=into_level,
        level_span=span,
        to_next=span - into_level,
    )


def compute(db: Any, student_id: int) -> XPState:
    """His current XP standing -- total, level, rank, and progress to the next
    level -- computed fresh from the database."""
    return state_for_total(total_xp(db, student_id))
