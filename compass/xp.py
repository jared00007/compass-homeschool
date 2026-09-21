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


def reward_pick_week(today: date | None = None) -> date:
    """The Monday of the week a NEW reward pick applies to.

    During the school week (Mon-Fri) that's this week -- he's working toward it
    now. On the weekend the Mon-Fri week is over and its reward is already
    settled (earned or not, delivered on the weekend), so a fresh pick is for the
    UPCOMING week, not the one that just finished. Keeping these separate is what
    stops a weekend pick from overwriting the reward he just earned: the picker
    writes here, never to `week_bounds(today)` once the week has closed.
    """
    today = today or date.today()
    monday = today - timedelta(days=today.weekday())
    if today.weekday() >= 5:  # Saturday or Sunday -> next week
        return monday + timedelta(days=7)
    return monday


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
    school_days: int = 5      # 5 normally; fewer on a holiday/short week
    # Landon's own reward pick for the week (he chooses Monday, a parent approves):
    #   "unset"    -- he hasn't picked yet; the parent default stands as fallback
    #   "pending"  -- he picked, waiting on a parent's approval
    #   "approved" -- a parent signed off; this is the locked reward
    #   "denied"   -- a parent bounced his custom pick (with a note); pick again
    reward_status: str = "unset"
    reward_source: str = ""    # "library" | "custom" | ""
    reward_note: str = ""      # a parent's note when a pick was denied

    @property
    def reward_pending(self) -> bool:
        return self.reward_status == "pending"

    @property
    def needs_reward_pick(self) -> bool:
        """He should be shown the picker -- nothing chosen yet, or his last pick
        was sent back."""
        return self.reward_status in ("unset", "denied")

    @property
    def is_short_week(self) -> bool:
        return self.school_days < 5

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


# --- Landon's own weekly reward pick (he chooses, a parent approves) --------------

_WEEK_CHOICES_SETTING = "xp_week_choices"


def _week_key(week_start: date | str) -> str:
    return week_start.isoformat() if isinstance(week_start, date) else str(week_start)


def _week_choices(db: Any) -> dict[str, Any]:
    raw = db.get_setting(_WEEK_CHOICES_SETTING)
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def week_reward_choice(db: Any, week_start: date | str) -> dict[str, Any] | None:
    """Landon's reward pick for one week (or None if he hasn't picked). A dict of
    {status, source, name, emoji, note} -- status is pending/approved/denied."""
    choice = _week_choices(db).get(_week_key(week_start))
    return choice if isinstance(choice, dict) else None


def set_week_reward_choice(
    db: Any, week_start: date | str, name: str, emoji: str, source: str = "library"
) -> None:
    """Record his pick for the week, pending a parent's approval. Overwrites any
    previous pick for that week (re-picking after a send-back, say).

    Refuses to touch a week whose reward has already been handed over
    (`weeks_given`) -- a delivered reward is settled history, and letting a later
    pick rewrite it is exactly the bug where a weekend pick erased an
    already-earned reward.
    """
    key = _week_key(week_start)
    if key in weeks_given(db):
        return
    choices = _week_choices(db)
    choices[key] = {
        "status": "pending",
        "source": source if source in ("library", "custom") else "library",
        "name": str(name or "").strip() or "Reward",
        "emoji": (str(emoji or "").strip()) or "🎁",
        "note": "",
    }
    db.set_setting(_WEEK_CHOICES_SETTING, json.dumps(choices))


def approve_week_reward(db: Any, week_start: date | str) -> None:
    """A parent signs off on his pick -- it becomes the locked reward."""
    choices = _week_choices(db)
    choice = choices.get(_week_key(week_start))
    if isinstance(choice, dict):
        choice["status"] = "approved"
        choice["note"] = ""
        db.set_setting(_WEEK_CHOICES_SETTING, json.dumps(choices))


def deny_week_reward(db: Any, week_start: date | str, note: str = "") -> None:
    """A parent bounces his pick back with an optional note -- no XP cost, he
    just picks again. Kept as a 'denied' record so the note can be shown."""
    choices = _week_choices(db)
    choice = choices.get(_week_key(week_start))
    if isinstance(choice, dict):
        choice["status"] = "denied"
        choice["note"] = str(note or "").strip()
        db.set_setting(_WEEK_CHOICES_SETTING, json.dumps(choices))


_REWARD_LIBRARY_SETTING = "xp_reward_library"


def reward_library(db: Any) -> list[tuple[str, str]]:
    """The reward presets a parent can pick from -- the config seed plus any
    they've saved, de-duplicated by name (a saved edit wins over the seed of the
    same name). Each is (name, emoji). Tolerant of a malformed stored value."""
    library: list[tuple[str, str]] = []
    seen: set[str] = set()
    raw = db.get_setting(_REWARD_LIBRARY_SETTING)
    if raw:
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            parsed = None
        if isinstance(parsed, list):
            for row in parsed:
                try:
                    name = str(row["name"]).strip()
                    emoji = (str(row.get("emoji") or "").strip()) or "🎁"
                except (KeyError, TypeError, ValueError):
                    continue
                if name and name.lower() not in seen:
                    library.append((name, emoji))
                    seen.add(name.lower())
    for name, emoji in config.XP_REWARD_LIBRARY:
        if name.lower() not in seen:
            library.append((name, emoji))
            seen.add(name.lower())
    return library


def add_reward_to_library(db: Any, name: str, emoji: str) -> None:
    """Save a new reward preset (or update the emoji of an existing one by name)
    so it's reusable from the picker. A blank name is ignored."""
    name = str(name or "").strip()
    if not name:
        return
    emoji = (str(emoji or "").strip()) or "🎁"
    saved = [
        {"name": n, "emoji": e}
        for n, e in reward_library(db)
        if n.lower() != name.lower()
    ]
    saved.insert(0, {"name": name, "emoji": emoji})
    db.set_setting(_REWARD_LIBRARY_SETTING, json.dumps(saved))


def remove_reward_from_library(db: Any, name: str) -> None:
    """Drop a reward preset by name. Only affects the parent's saved list; the
    config seed always remains available."""
    name = str(name or "").strip().lower()
    saved = [
        {"name": n, "emoji": e}
        for n, e in reward_library(db)
        if n.lower() != name
    ]
    db.set_setting(_REWARD_LIBRARY_SETTING, json.dumps(saved))


_WEEK_DAYS_SETTING = "xp_week_days"


def week_school_days(db: Any, week_start: date | str) -> int:
    """How many school days a given week counts as -- 5 by default, fewer when a
    parent has flagged it a short/holiday week. Keyed by the week's Monday
    (ISO), stored as a JSON dict under `xp_week_days`, so a short week only
    affects that week and next Monday starts fresh at 5."""
    key = week_start.isoformat() if isinstance(week_start, date) else str(week_start)
    raw = db.get_setting(_WEEK_DAYS_SETTING)
    if raw:
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            parsed = None
        if isinstance(parsed, dict):
            try:
                days = int(parsed.get(key))
            except (TypeError, ValueError):
                days = 5
            if 1 <= days <= 5:
                return days
    return 5


def set_week_school_days(db: Any, week_start: date | str, days: int) -> None:
    """Flag a week as short (a holiday week) by setting its school-day count.
    Clamped to 1-5; setting 5 clears the override for that week."""
    key = week_start.isoformat() if isinstance(week_start, date) else str(week_start)
    try:
        days = max(1, min(5, int(days)))
    except (TypeError, ValueError):
        days = 5
    raw = db.get_setting(_WEEK_DAYS_SETTING)
    try:
        current = json.loads(raw) if raw else {}
        if not isinstance(current, dict):
            current = {}
    except (ValueError, TypeError):
        current = {}
    if days == 5:
        current.pop(key, None)
    else:
        current[key] = days
    db.set_setting(_WEEK_DAYS_SETTING, json.dumps(current))


def scaled_goal(base_goal: int, school_days: int) -> int:
    """A full-week goal scaled down for a short week -- weighted to the number of
    school days out of five, floored at 10 so it stays a real target. A 400 goal
    on a 4-day holiday week becomes 320."""
    return max(10, round(base_goal * school_days / 5))


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

    # The reward: Landon's own pick once a parent approves it, his pending pick
    # while it waits, or the parent default as the fallback until he picks.
    default_name, default_emoji = weekly_reward(db)
    choice = week_reward_choice(db, monday)
    reward_status, reward_source, reward_note = "unset", "", ""
    reward_name, reward_emoji = default_name, default_emoji
    if choice and choice.get("status") == "approved":
        reward_name, reward_emoji = choice["name"], choice["emoji"]
        reward_status, reward_source = "approved", choice.get("source", "")
    elif choice and choice.get("status") == "pending":
        reward_name, reward_emoji = choice["name"], choice["emoji"]
        reward_status, reward_source = "pending", choice.get("source", "")
    elif choice and choice.get("status") == "denied":
        reward_status, reward_note = "denied", choice.get("note", "")

    school_days = week_school_days(db, monday)
    return WeeklyProgress(
        week_start=monday,
        goal=scaled_goal(weekly_goal(db), school_days),
        reward_name=reward_name,
        reward_emoji=reward_emoji,
        days=days,
        bonus_items=bonus_items,
        given=monday.isoformat() in weeks_given(db),
        school_days=school_days,
        reward_status=reward_status,
        reward_source=reward_source,
        reward_note=reward_note,
    )
