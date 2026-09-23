"""The Khan mastery ladder -- Familiar -> Proficient -> Mastered, per Khan card.

Khan Academy scores each skill on its own ladder. Landon can push a skill up
that ladder by going back and practicing; he *marks* the level he reached, a
parent *confirms* it with one tap, and every confirmed tier earns XP. Taking a
whole unit to its mastery target earns a weekly bonus on top. The point is to
reward *revisiting* prior work -- climbing a skill is always upside, never a
penalty.

Everything here is **derived** from what's stored on each Khan card's metadata,
exactly like `compass.xp`: there's no separate score table to drift out of sync,
and re-confirming or adjusting a level just recomputes. The record on a card
lives at ``metadata["khan_mastery"]``::

    {
      "claimed": "proficient",     # highest level Landon says he reached
      "claimed_on": "2026-09-23",  # (dropped once a parent confirms it)
      "confirmed": "familiar",     # highest parent-confirmed level -- bears XP
      "history": [                 # one dated entry per confirmed tier, in order
        {"level": "familiar", "on": "2026-09-21"},
      ],
    }
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any

from compass import config

AGENT_KEY = "khan"
LEVELS: tuple[str, ...] = config.KHAN_MASTERY_LEVELS  # familiar < proficient < mastered
_PROFICIENT = "proficient"


# --- level helpers -----------------------------------------------------------

def is_valid_level(level: Any) -> bool:
    return level in LEVELS


def level_index(level: Any) -> int:
    """0-based rank of a level; -1 for None/invalid (read as 'no level yet'), so
    ``level_index(a) > level_index(b)`` orders levels with 'nothing' at the
    bottom."""
    try:
        return LEVELS.index(level)
    except (ValueError, TypeError):
        return -1


def level_label(level: Any) -> str:
    return config.KHAN_MASTERY_LABELS.get(level, "Not started")


def level_emoji(level: Any) -> str:
    return config.KHAN_MASTERY_EMOJI.get(level, "▫️")


def next_level(level: Any) -> str | None:
    """The tier above `level` (None past Mastered, `familiar` from nothing)."""
    idx = level_index(level)
    return LEVELS[idx + 1] if idx + 1 < len(LEVELS) else None


# --- reading one card --------------------------------------------------------

def _record(lesson: dict[str, Any]) -> dict[str, Any]:
    return dict((lesson.get("metadata") or {}).get("khan_mastery") or {})


def confirmed_level(lesson: dict[str, Any]) -> str | None:
    level = _record(lesson).get("confirmed")
    return level if is_valid_level(level) else None


def claimed_level(lesson: dict[str, Any]) -> str | None:
    level = _record(lesson).get("claimed")
    return level if is_valid_level(level) else None


def pending_claim(lesson: dict[str, Any]) -> str | None:
    """The level Landon has claimed that sits above what a parent has confirmed
    -- i.e. one waiting on a one-tap confirm. None when nothing is pending."""
    claimed = claimed_level(lesson)
    if claimed is None:
        return None
    return claimed if level_index(claimed) > level_index(confirmed_level(lesson)) else None


def card_xp(lesson: dict[str, Any]) -> int:
    """XP a card has earned from its confirmed mastery tiers."""
    return sum(
        config.KHAN_MASTERY_XP.get(entry.get("level"), 0)
        for entry in _record(lesson).get("history") or []
    )


def card_bumps(lesson: dict[str, Any]) -> list[tuple[str, int]]:
    """(date_iso, xp) for each confirmed tier on this card -- what the weekly
    strip needs to place a level-up on the day it was confirmed."""
    out: list[tuple[str, int]] = []
    for entry in _record(lesson).get("history") or []:
        xp = config.KHAN_MASTERY_XP.get(entry.get("level"), 0)
        on = str(entry.get("on") or "")[:10]
        if xp and on:
            out.append((on, xp))
    return out


def _proficient_plus_date(lesson: dict[str, Any]) -> str | None:
    """The date a card first reached Proficient-or-better (its `proficient`
    tier confirm), or None if it hasn't. Every card confirmed to proficient or
    mastered has this entry, because confirming climbs one tier at a time."""
    for entry in _record(lesson).get("history") or []:
        if entry.get("level") == _PROFICIENT:
            on = str(entry.get("on") or "")[:10]
            return on or None
    return None


def card_state(lesson: dict[str, Any]) -> dict[str, Any]:
    """Everything the marking UI needs for one card, in one read."""
    confirmed = confirmed_level(lesson)
    return {
        "confirmed": confirmed,
        "claimed": claimed_level(lesson),
        "pending": pending_claim(lesson),
        "next": next_level(confirmed),
        "xp": card_xp(lesson),
        "is_max": level_index(confirmed) >= len(LEVELS) - 1,
    }


# --- writing one card (claim / confirm) --------------------------------------

def _write(db: Any, lesson: dict[str, Any], record: dict[str, Any]) -> None:
    metadata = dict(lesson.get("metadata") or {})
    if record:
        metadata["khan_mastery"] = record
    else:
        metadata.pop("khan_mastery", None)
    db.update_lesson_content(lesson["id"], metadata=metadata)


def _require_khan_card(db: Any, lesson_id: int) -> dict[str, Any]:
    lesson = db.get_lesson(lesson_id)
    if lesson is None or lesson.get("agent") != AGENT_KEY:
        raise ValueError("That isn't a Khan card.")
    return lesson


def claim_mastery(db: Any, lesson_id: int, level: str, on: str | None = None) -> None:
    """Landon marks the level he reached on Khan. Records the claim (pending a
    parent's confirm) and awards no XP on its own. A claim at or below what's
    already confirmed is a no-op -- that tier is already his."""
    if not is_valid_level(level):
        raise ValueError(f"invalid Khan mastery level: {level!r}")
    lesson = _require_khan_card(db, lesson_id)
    record = _record(lesson)
    if level_index(level) <= level_index(record.get("confirmed")):
        return
    record["claimed"] = level
    record["claimed_on"] = on or date.today().isoformat()
    _write(db, lesson, record)


def confirm_mastery(
    db: Any, lesson_id: int, level: str | None = None, on: str | None = None
) -> int:
    """A parent confirms a card up to `level` (default: whatever Landon claimed).
    Appends a dated history entry for each new tier between the last confirmed
    level and the target, sets `confirmed`, clears the satisfied claim, and
    returns the XP those new tiers are worth. Monotonic -- it never lowers a
    confirmed level, so mastery XP only ever climbs."""
    lesson = _require_khan_card(db, lesson_id)
    record = _record(lesson)
    target = level if level is not None else record.get("claimed")
    target_idx = level_index(target)
    start = level_index(record.get("confirmed"))
    if target_idx <= start:
        return 0
    on = on or date.today().isoformat()
    history = list(record.get("history") or [])
    awarded = 0
    for i in range(start + 1, target_idx + 1):
        tier = LEVELS[i]
        history.append({"level": tier, "on": on})
        awarded += config.KHAN_MASTERY_XP.get(tier, 0)
    record["history"] = history
    record["confirmed"] = LEVELS[target_idx]
    if level_index(record.get("claimed")) <= target_idx:
        record.pop("claimed", None)
        record.pop("claimed_on", None)
    _write(db, lesson, record)
    return awarded


def reject_claim(db: Any, lesson_id: int) -> None:
    """A parent dismisses Landon's pending claim without confirming it -- clears
    the claim and leaves the confirmed level (and its XP) untouched."""
    lesson = _require_khan_card(db, lesson_id)
    record = _record(lesson)
    record.pop("claimed", None)
    record.pop("claimed_on", None)
    _write(db, lesson, record)


# --- aggregates across all his Khan cards ------------------------------------

def _khan_lessons(db: Any, student_id: int) -> list[dict[str, Any]]:
    return db.list_lessons(student_id, agent=AGENT_KEY, limit=500)


def total_mastery_xp(db: Any, student_id: int) -> int:
    """Lifetime XP from Khan mastery tiers across every Khan card."""
    return sum(card_xp(lesson) for lesson in _khan_lessons(db, student_id))


def mastery_bumps(db: Any, student_id: int) -> list[tuple[str, int]]:
    """Every confirmed tier as (date_iso, xp) -- for the weekly strip."""
    out: list[tuple[str, int]] = []
    for lesson in _khan_lessons(db, student_id):
        out.extend(card_bumps(lesson))
    return out


def pending_claims(db: Any, student_id: int) -> list[dict[str, Any]]:
    """The Khan cards with a mastery level Landon has claimed but no one has
    confirmed yet -- the parent's one-tap confirm queue. Newest card first."""
    out = []
    for lesson in _khan_lessons(db, student_id):
        claim = pending_claim(lesson)
        if claim:
            out.append({"lesson": lesson, "claim": claim, "confirmed": confirmed_level(lesson)})
    return out


def _unit_id(lesson: dict[str, Any]) -> Any:
    return (lesson.get("metadata") or {}).get("khan_course_id")


def _target_count(total: int) -> int:
    """How many of a unit's skills must reach Proficient+ to hit the target."""
    return max(1, math.ceil(total * config.KHAN_UNIT_MASTERY_TARGET))


def unit_summaries(db: Any, student_id: int) -> list[dict[str, Any]]:
    """Per-unit mastery standing -- counts by level, XP earned vs still on the
    table, and whether (and when) the unit crossed its mastery target. Newest
    unit first. Only Khan cards that belong to a loaded unit are included."""
    units: dict[Any, list[dict[str, Any]]] = {}
    for lesson in _khan_lessons(db, student_id):
        cid = _unit_id(lesson)
        if cid:
            units.setdefault(cid, []).append(lesson)

    per_tier = sum(config.KHAN_MASTERY_XP.values())  # XP for one fully-mastered skill
    out: list[dict[str, Any]] = []
    for cid, cards in units.items():
        meta0 = cards[0].get("metadata") or {}
        total = len(cards)
        by_level = {level: 0 for level in LEVELS}
        prof_plus_dates: list[str] = []
        xp_earned = 0
        for card in cards:
            level = confirmed_level(card)
            if level:
                by_level[level] += 1
            crossed = _proficient_plus_date(card)
            if crossed:
                prof_plus_dates.append(crossed)
            xp_earned += card_xp(card)
        prof_plus_dates.sort()
        target_count = _target_count(total)
        crossed_on = (
            prof_plus_dates[target_count - 1]
            if len(prof_plus_dates) >= target_count
            else None
        )
        out.append({
            "course_id": cid,
            "course": meta0.get("khan_course", "Unit"),
            "subject": cards[0].get("subject", ""),
            "total": total,
            "by_level": by_level,
            "proficient_plus": len(prof_plus_dates),
            "target_count": target_count,
            "target_met": crossed_on is not None,
            "crossed_on": crossed_on,
            "xp_earned": xp_earned,
            "xp_available": max(0, total * per_tier - xp_earned),
            "bonus": config.KHAN_UNIT_MASTERY_BONUS,
            "_created": max((c.get("created_at") or "") for c in cards),
            "_planned": [(c.get("metadata") or {}).get("planned_for") for c in cards],
        })
    out.sort(key=lambda u: u["_created"], reverse=True)
    return out


def unit_bonuses(db: Any, student_id: int) -> list[tuple[str, int]]:
    """(date_iso, bonus_xp) for every unit that has reached its mastery target,
    dated the day it crossed the line -- feeds both the lifetime total and the
    weekly bar. Any unit he masters earns the bonus, once."""
    return [
        (u["crossed_on"], config.KHAN_UNIT_MASTERY_BONUS)
        for u in unit_summaries(db, student_id)
        if u["target_met"] and u["crossed_on"]
    ]


def active_unit(
    db: Any, student_id: int, today: date | None = None
) -> dict[str, Any] | None:
    """The unit to feature on Landon's Home this week: the one with the most
    cards planned for the current Mon-Fri week, else the newest unit that isn't
    fully at its target, else the newest unit. None when no units are loaded."""
    summaries = unit_summaries(db, student_id)
    if not summaries:
        return None
    today = today or date.today()
    monday = today - timedelta(days=today.weekday())
    friday = monday + timedelta(days=4)

    def planned_this_week(unit: dict[str, Any]) -> int:
        count = 0
        for planned in unit["_planned"]:
            iso = str(planned or "")[:10]
            if iso and monday.isoformat() <= iso <= friday.isoformat():
                count += 1
        return count

    with_week = [(planned_this_week(u), u) for u in summaries]
    best = max(with_week, key=lambda pair: pair[0])
    if best[0] > 0:
        return best[1]  # a unit is actively scheduled this week
    unfinished = [u for u in summaries if not u["target_met"]]
    return (unfinished or summaries)[0]  # summaries already sorted newest-first
