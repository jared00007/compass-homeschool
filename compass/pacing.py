"""Daily pacing -- the "enough for today" signal.

A real school day isn't an endless stack of lessons: a couple of core academic
lessons plus one enrichment block (art, PE, a documentary, a project step, free
reading, a life skill) is a full, honest day for a 13-year-old. This module
computes where he is against that target so Home can tell him when he's done and
the rest of the day is his -- the direct antidote to grinding lesson after
lesson.

Everything here is derived live from the same "done today" signals the rest of
the app already records (student_done_on, completed_on, visited_on, the activity
log), the same way the weekly XP is derived -- no new stored state to drift.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from compass import config

_CORE_TARGET_SETTING = "day_target_core"
_ENRICHMENT_TARGET_SETTING = "day_target_enrichment"


def day_target_core(db: Any) -> int:
    """Core academic lessons that count as a full day (parent override, else the
    config default). Floored at 0 so a parent can set an enrichment-only day."""
    raw = db.get_setting(_CORE_TARGET_SETTING)
    try:
        return max(0, int(raw)) if raw not in (None, "") else config.DAY_TARGET_CORE
    except (ValueError, TypeError):
        return config.DAY_TARGET_CORE


def day_target_enrichment(db: Any) -> int:
    """Enrichment blocks that count as a full day (parent override, else the
    config default)."""
    raw = db.get_setting(_ENRICHMENT_TARGET_SETTING)
    try:
        return max(0, int(raw)) if raw not in (None, "") else config.DAY_TARGET_ENRICHMENT
    except (ValueError, TypeError):
        return config.DAY_TARGET_ENRICHMENT


def set_day_target(db: Any, core: int, enrichment: int) -> None:
    """Parent sets what a full day is -- how many core lessons and how many
    enrichment blocks."""
    db.set_setting(_CORE_TARGET_SETTING, str(max(0, int(core))))
    db.set_setting(_ENRICHMENT_TARGET_SETTING, str(max(0, int(enrichment))))


@dataclass(frozen=True)
class DayPlan:
    """Where he stands against today's target."""

    core_done: int
    enrichment_done: int
    core_target: int
    enrichment_target: int

    @property
    def core_left(self) -> int:
        return max(0, self.core_target - self.core_done)

    @property
    def enrichment_left(self) -> int:
        return max(0, self.enrichment_target - self.enrichment_done)

    @property
    def is_full_day(self) -> bool:
        """Both halves of the target met -- a full, balanced day."""
        return self.core_left == 0 and self.enrichment_left == 0

    @property
    def any_done(self) -> bool:
        return self.core_done > 0 or self.enrichment_done > 0

    @property
    def total_done(self) -> int:
        return self.core_done + self.enrichment_done

    @property
    def total_target(self) -> int:
        return self.core_target + self.enrichment_target


def day_plan(db: Any, student_id: int, today: date | str | None = None) -> DayPlan:
    """His standing for `today` against the daily target -- computed live from
    what he's actually finished, so it moves the moment he completes something."""
    if today is None:
        today = date.today()
    day = today.isoformat() if isinstance(today, date) else str(today)[:10]
    return DayPlan(
        core_done=db.core_lessons_done_on(student_id, day),
        enrichment_done=db.enrichment_done_on(student_id, day),
        core_target=day_target_core(db),
        enrichment_target=day_target_enrichment(db),
    )
