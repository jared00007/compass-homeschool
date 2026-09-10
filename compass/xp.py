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
from dataclasses import dataclass, field
from datetime import date, timedelta
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


def _sent_back_count(metadata: dict[str, Any]) -> int:
    """How many times one lesson has been sent back for a redo -- every bounce,
    counted. The authoritative source is `sent_back_on`, which gets one entry
    per send-back whether or not a note was typed; older data (saved before that
    timeline existed) falls back to the feedback trail, then the single legacy
    field. Kept in step with the weekly strip, which counts the same stamps."""
    stamps = metadata.get("sent_back_on")
    if stamps:
        return len(stamps)
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
    and travel entries count once each once they're done, and every mastered
    math skill adds a little. All point values live in config.
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


# ---------------------------------------------------------------------------
# The weekly reward loop -- "a good week earns a reward by Friday."
#
# Everything above is his all-time standing (the small Level/rank line on the
# card). Everything below is the week-by-week game: XP resets every Monday, and
# what he finishes Mon-Fri climbs toward one reward. His *core* school work
# (lessons, passed quizzes, mastered skills) fills the bar; life skills, coding,
# and trips are extra credit that top him off if Friday comes up short. Same
# design as the lifetime total -- computed live from his own completion signals,
# nothing stored to drift, re-approving just recomputes.
# ---------------------------------------------------------------------------

WEEKDAY_LABELS = ("MON", "TUE", "WED", "THU", "FRI")

# How near the goal counts as "so close" -- the threshold under which the
# Friday extra-credit nudge appears. Deliberately a bit under two lessons'
# worth: close enough that one more thing genuinely gets him there.
WEEKLY_CLOSE_MARGIN = 60


def week_bounds(today: date) -> tuple[date, date]:
    """The Monday-Friday school week `today` falls in. Monday is the reset;
    Friday is the finish line. The weekend is deliberately out of the window --
    it's reward time, not school time -- so anything he finishes Sat/Sun doesn't
    count toward the week (and next Monday starts him fresh)."""
    monday = today - timedelta(days=today.weekday())
    return monday, monday + timedelta(days=4)


def _parse_iso(value: Any) -> date | None:
    """A stored ISO date string -> a `date`, or None for anything unparseable
    (missing, a datetime, junk). Only the leading YYYY-MM-DD is read, so a
    full timestamp still lands on the right day."""
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None


@dataclass(frozen=True)
class DayRecord:
    """One day of the strip -- what he finished and what it was worth."""

    day: date
    label: str            # MON..FRI
    short_date: str       # "9/8"
    lessons: int
    quizzes: int
    skills: int
    redos: int            # lessons sent back this day -- the one thing that docks
    is_today: bool
    is_future: bool

    @property
    def xp(self) -> int:
        """This day's net core XP. Can go negative on a rough day (a redo with
        nothing finished) -- shown honestly per day; the week total is floored."""
        return (
            self.lessons * config.XP_PER_LESSON
            + self.quizzes * config.XP_QUIZ_PASS_BONUS
            + self.skills * config.XP_PER_MASTERED_SKILL
            - self.redos * config.XP_SENT_BACK_PENALTY
        )

    @property
    def has_activity(self) -> bool:
        return bool(self.lessons or self.quizzes or self.skills or self.redos)


@dataclass(frozen=True)
class BonusItem:
    """One line of extra credit -- earned this week, or an option still open."""

    emoji: str
    label: str
    xp: int


@dataclass(frozen=True)
class WeeklyProgress:
    """His standing for the current week -- everything the card needs to draw
    the strip, the goal meter, the bonus line, and the reward state."""

    week_start: date
    goal: int
    reward_name: str
    reward_emoji: str
    days: list[DayRecord]
    bonus_items: list[BonusItem] = field(default_factory=list)
    given: bool = False

    @property
    def core_xp(self) -> int:
        """Bar-filling XP from school work, floored at zero."""
        return max(0, sum(d.xp for d in self.days))

    @property
    def bonus_xp(self) -> int:
        return sum(b.xp for b in self.bonus_items)

    @property
    def total(self) -> int:
        return max(0, sum(d.xp for d in self.days) + self.bonus_xp)

    @property
    def reached(self) -> bool:
        return self.total >= self.goal

    @property
    def remaining(self) -> int:
        return max(0, self.goal - self.total)

    @property
    def fraction(self) -> float:
        if self.goal <= 0:
            return 1.0
        return min(1.0, self.total / self.goal)

    @property
    def earned_unclaimed(self) -> bool:
        """Hit the goal but the parent hasn't handed the reward over yet -- the
        one state that needs a parent's attention."""
        return self.reached and not self.given

    @property
    def close(self) -> bool:
        """Short of the goal, but near enough that a bit of extra credit gets
        him there -- when the Friday nudge is worth showing."""
        return not self.reached and self.remaining <= WEEKLY_CLOSE_MARGIN


_WEEKLY_GOAL_SETTING = "xp_weekly_goal"
_WEEKLY_REWARD_NAME_SETTING = "xp_weekly_reward_name"
_WEEKLY_REWARD_EMOJI_SETTING = "xp_weekly_reward_emoji"
_WEEKS_GIVEN_SETTING = "xp_weeks_given"


def weekly_goal(db: Any) -> int:
    """The XP goal for a week -- a parent's saved number, else the config
    default. A junk or non-positive stored value falls back to the default
    rather than leaving him a goal he can't read or can't miss."""
    raw = db.get_setting(_WEEKLY_GOAL_SETTING)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return config.XP_WEEKLY_GOAL
    return value if value > 0 else config.XP_WEEKLY_GOAL


def set_weekly_goal(db: Any, goal: int) -> None:
    """Save the weekly XP goal. Clamped to at least 10 so it stays a real
    target."""
    try:
        value = max(10, int(goal))
    except (TypeError, ValueError):
        value = config.XP_WEEKLY_GOAL
    db.set_setting(_WEEKLY_GOAL_SETTING, str(value))


def weekly_reward(db: Any) -> tuple[str, str]:
    """The (name, emoji) of the reward he's climbing toward this week -- a
    parent's saved pair, else the config default. A blank saved name falls back
    to the default so the card never shows a nameless reward."""
    name = (db.get_setting(_WEEKLY_REWARD_NAME_SETTING) or "").strip()
    emoji = (db.get_setting(_WEEKLY_REWARD_EMOJI_SETTING) or "").strip()
    return (
        name or config.XP_WEEKLY_REWARD_NAME,
        emoji or config.XP_WEEKLY_REWARD_EMOJI,
    )


def set_weekly_reward(db: Any, name: str, emoji: str) -> None:
    """Save the weekly reward's name and emoji. A blank name clears back to the
    config default; a blank emoji defaults to a gift box."""
    db.set_setting(_WEEKLY_REWARD_NAME_SETTING, str(name or "").strip())
    db.set_setting(_WEEKLY_REWARD_EMOJI_SETTING, (str(emoji or "").strip()) or "🎁")


def weeks_given(db: Any) -> set[str]:
    """The week-start dates (ISO Mondays) whose reward the parent has marked
    handed over. Stored as a JSON list under `xp_weeks_given`; a malformed value
    reads as 'nothing given' rather than raising."""
    raw = db.get_setting(_WEEKS_GIVEN_SETTING)
    if not raw:
        return set()
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return set()
    if not isinstance(parsed, list):
        return set()
    return {str(v) for v in parsed}


def set_week_reward_given(db: Any, week_start: date | str, given: bool = True) -> None:
    """Mark (or un-mark) one week's reward as handed over, keyed by its Monday."""
    key = week_start.isoformat() if isinstance(week_start, date) else str(week_start)
    current = weeks_given(db)
    if given:
        current.add(key)
    else:
        current.discard(key)
    db.set_setting(_WEEKS_GIVEN_SETTING, json.dumps(sorted(current)))


def bonus_options() -> list[BonusItem]:
    """The standing ways to earn extra credit -- shown in the Friday nudge so
    the point values there stay in step with what these actually award."""
    return [
        BonusItem("🛠️", "Life skill", config.XP_PER_LIFE_SKILL),
        BonusItem("💻", "Coding module", config.XP_PER_CODING_MODULE),
        BonusItem("🧭", "Trip write-up", config.XP_PER_TRAVEL_ENTRY),
    ]


def weekly_progress(
    db: Any, student_id: int, today: date | None = None
) -> WeeklyProgress:
    """His standing for the Monday-Friday week that `today` falls in, built live
    from the same completion signals the lifetime total uses -- so the weekly
    strip and the all-time bar can never disagree about what he finished."""
    today = today or date.today()
    monday, friday = week_bounds(today)

    def in_week(d: date | None) -> bool:
        return d is not None and monday <= d <= friday

    # Per-day core tallies, keyed by weekday index 0-4 (Mon-Fri).
    lessons = [0] * 5
    quizzes = [0] * 5
    skills = [0] * 5
    redos = [0] * 5

    for lesson in db.list_lessons(student_id, limit=500):
        metadata = lesson.get("metadata") or {}
        done = _parse_iso(metadata.get("student_done_on"))
        if in_week(done):
            lessons[done.weekday()] += 1
        quiz = metadata.get("quiz_result") or {}
        if quiz.get("passed"):
            # Prefer the quiz's own graded date; fall back to the lesson's
            # completion date for older results saved before graded_on existed.
            when = _parse_iso(quiz.get("graded_on")) or done
            if in_week(when):
                quizzes[when.weekday()] += 1
        for stamp in metadata.get("sent_back_on") or []:
            when = _parse_iso(stamp)
            if in_week(when):
                redos[when.weekday()] += 1

    for stamp in db.mastered_skill_dates(student_id):
        when = _parse_iso(stamp)
        if in_week(when):
            skills[when.weekday()] += 1

    days: list[DayRecord] = []
    for i in range(5):
        d = monday + timedelta(days=i)
        days.append(
            DayRecord(
                day=d,
                label=WEEKDAY_LABELS[i],
                short_date=f"{d.month}/{d.day}",
                lessons=lessons[i],
                quizzes=quizzes[i],
                skills=skills[i],
                redos=redos[i],
                is_today=(d == today),
                is_future=(d > today),
            )
        )

    # Extra credit finished this week -- life skills, coding, trips.
    life_done = sum(
        1
        for s in db.list_life_skills(student_id)
        if in_week(_parse_iso(s.get("completed_on")))
    )
    coding_done = sum(
        1
        for m in db.list_coding_modules(student_id)
        if in_week(_parse_iso(m.get("completed_on")))
    )
    trips_done = sum(
        1
        for t in db.list_travel_entries(student_id)
        if t.get("status") == "completed" and in_week(_parse_iso(t.get("visited_on")))
    )

    bonus_items: list[BonusItem] = []
    if life_done:
        bonus_items.append(
            BonusItem("🛠️", f"{life_done} life skill{'s' if life_done != 1 else ''}",
                      life_done * config.XP_PER_LIFE_SKILL)
        )
    if coding_done:
        bonus_items.append(
            BonusItem("💻", f"{coding_done} coding module{'s' if coding_done != 1 else ''}",
                      coding_done * config.XP_PER_CODING_MODULE)
        )
    if trips_done:
        bonus_items.append(
            BonusItem("🧭", f"{trips_done} trip write-up{'s' if trips_done != 1 else ''}",
                      trips_done * config.XP_PER_TRAVEL_ENTRY)
        )

    name, emoji = weekly_reward(db)
    return WeeklyProgress(
        week_start=monday,
        goal=weekly_goal(db),
        reward_name=name,
        reward_emoji=emoji,
        days=days,
        bonus_items=bonus_items,
        given=monday.isoformat() in weeks_given(db),
    )
