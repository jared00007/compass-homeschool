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

import json
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


@dataclass(frozen=True)
class Reward:
    """One real-world reward: whether his XP has reached it (`unlocked`), and
    whether the parent has actually handed it over yet (`given`)."""

    threshold: int
    name: str
    emoji: str
    unlocked: bool
    given: bool = False

    @property
    def earned_unclaimed(self) -> bool:
        """He's hit the threshold but the parent hasn't marked it given -- the
        one state that needs the parent's attention."""
        return self.unlocked and not self.given


def _sent_back_count(metadata: dict[str, Any]) -> int:
    """How many times one lesson has been sent back for a redo -- the length of
    its feedback trail, falling back to the single legacy field for data saved
    before the history list existed (same fallback rule ui._feedback_history
    uses; inlined here to keep xp free of a UI import)."""
    history = metadata.get("lesson_feedback_history")
    if history:
        return len(history)
    return 1 if metadata.get("lesson_feedback") else 0


def sent_back_penalty(db: Any, student_id: int) -> int:
    """Total XP docked so far for sent-back lessons -- for showing the cost,
    since `total_xp` only exposes the netted-and-floored figure."""
    bounces = sum(
        _sent_back_count(lesson.get("metadata") or {})
        for lesson in db.list_lessons(student_id, limit=500)
    )
    return config.XP_SENT_BACK_PENALTY * bounces


_REWARD_LADDER_SETTING = "xp_rewards"


def reward_ladder(db: Any) -> list[tuple[int, str, str]]:
    """The reward milestones in force -- a parent's own edited list if they've
    saved one (`xp_rewards` setting, JSON), otherwise the config defaults.
    Tolerant of a malformed stored value: a bad row is dropped and, if nothing
    survives, it falls back to the defaults rather than leaving him with no
    rewards to climb toward (same defensiveness `grades.parse_weights` applies
    to its own editable setting). Always returned ascending by threshold."""
    raw = db.get_setting(_REWARD_LADDER_SETTING)
    if raw:
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            parsed = None
        if isinstance(parsed, list):
            ladder: list[tuple[int, str, str]] = []
            for row in parsed:
                try:
                    threshold = int(row["threshold"])
                    name = str(row["name"]).strip()
                    emoji = (str(row.get("emoji") or "").strip()) or "🎁"
                except (KeyError, TypeError, ValueError):
                    continue
                if name:
                    ladder.append((threshold, name, emoji))
            if ladder:
                return sorted(ladder, key=lambda r: r[0])
    return list(config.XP_REWARDS)


def set_reward_ladder(db: Any, rows: list[dict[str, Any]]) -> None:
    """Save a parent's edited reward list. Drops rows with no name, clamps a
    missing/junk threshold to 0, defaults a blank emoji, and stores the result
    sorted ascending. Saving an empty list clears back to the config defaults."""
    cleaned: list[dict[str, Any]] = []
    for row in rows:
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        try:
            threshold = max(0, int(row.get("threshold") or 0))
        except (TypeError, ValueError):
            threshold = 0
        emoji = (str(row.get("emoji") or "").strip()) or "🎁"
        cleaned.append({"threshold": threshold, "name": name, "emoji": emoji})
    cleaned.sort(key=lambda r: r["threshold"])
    db.set_setting(_REWARD_LADDER_SETTING, json.dumps(cleaned))


_REWARD_GIVEN_SETTING = "xp_rewards_given"


def given_thresholds(db: Any) -> set[int]:
    """The reward thresholds the parent has already marked as handed over.
    Stored as a JSON list of ints under `xp_rewards_given`; a malformed value
    reads as 'nothing given' rather than raising."""
    raw = db.get_setting(_REWARD_GIVEN_SETTING)
    if not raw:
        return set()
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return set()
    if not isinstance(parsed, list):
        return set()
    out: set[int] = set()
    for value in parsed:
        try:
            out.add(int(value))
        except (TypeError, ValueError):
            continue
    return out


def set_reward_given(db: Any, threshold: int, given: bool = True) -> None:
    """Mark (or un-mark) one reward threshold as handed over by the parent."""
    current = given_thresholds(db)
    if given:
        current.add(int(threshold))
    else:
        current.discard(int(threshold))
    db.set_setting(_REWARD_GIVEN_SETTING, json.dumps(sorted(current)))


def rewards_for_total(
    total: int,
    ladder: list[tuple[int, str, str]] | None = None,
    given: set[int] | None = None,
) -> list[Reward]:
    """Every reward, each flagged `unlocked` if `total` has reached its
    threshold and `given` if the parent has marked it handed over.
    `ladder` defaults to the config rewards when not given (keeps this pure and
    db-free for tests); callers with a db pass `reward_ladder(db)` so a parent's
    edits are honored, plus `given_thresholds(db)` so the handed-over flag is
    accurate."""
    ladder = ladder if ladder is not None else list(config.XP_REWARDS)
    given = given or set()
    return [
        Reward(
            threshold=threshold,
            name=name,
            emoji=emoji,
            unlocked=total >= threshold,
            given=threshold in given,
        )
        for threshold, name, emoji in ladder
    ]


def next_reward(total: int, ladder: list[tuple[int, str, str]] | None = None) -> Reward | None:
    """The lowest-threshold reward he hasn't reached yet, or None once every
    reward is unlocked."""
    for reward in rewards_for_total(total, ladder):
        if not reward.unlocked:
            return reward
    return None


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
        # ...and the one thing that costs XP: each time this lesson was sent
        # back for a redo. Counted off the feedback history (one entry per
        # bounce), so a lesson bounced twice costs twice.
        total -= config.XP_SENT_BACK_PENALTY * _sent_back_count(metadata)

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

    # Floored at the very end: send-back penalties can eat into everything he's
    # earned, but the total never goes negative -- a zero bar reads as "start
    # climbing," a negative one reads as broken.
    return max(0, total)


@dataclass(frozen=True)
class LearnerStats:
    """A quick tally of everything he's actually finished -- the header KPIs
    next to his Level card. Counts, not scores: 'how much have I done,' which
    is the one thing the Level bar (an abstract number) doesn't say plainly."""

    lessons_done: int
    quizzes_passed: int
    skills_done: int
    trips_written: int
    heaviest_subject: str | None       # the subject he's put the most lessons into
    heaviest_subject_count: int


def learner_stats(db: Any, student_id: int) -> LearnerStats:
    """Tally his finished work for the Home KPI strip. Built from the same
    `student_done_on` completion signal the XP total uses, so the numbers here
    never disagree with the bar right next to them. 'Heaviest subject' is the
    one with the most completed lessons -- his by-volume workhorse."""
    lessons_done = 0
    quizzes_passed = 0
    subject_counts: dict[str, int] = {}
    for lesson in db.list_lessons(student_id, limit=500):
        metadata = lesson.get("metadata") or {}
        if metadata.get("student_done_on"):
            lessons_done += 1
            subject = (lesson.get("subject") or lesson.get("agent") or "").strip()
            if subject:
                subject_counts[subject] = subject_counts.get(subject, 0) + 1
        if (metadata.get("quiz_result") or {}).get("passed"):
            quizzes_passed += 1

    skills_done = sum(
        1 for s in db.list_life_skills(student_id) if s.get("completed_on")
    )
    trips_written = sum(
        1 for t in db.list_travel_entries(student_id) if t.get("status") == "completed"
    )

    heaviest_subject: str | None = None
    heaviest_subject_count = 0
    if subject_counts:
        heaviest_subject, heaviest_subject_count = max(
            subject_counts.items(), key=lambda kv: kv[1]
        )

    return LearnerStats(
        lessons_done=lessons_done,
        quizzes_passed=quizzes_passed,
        skills_done=skills_done,
        trips_written=trips_written,
        heaviest_subject=heaviest_subject,
        heaviest_subject_count=heaviest_subject_count,
    )


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
