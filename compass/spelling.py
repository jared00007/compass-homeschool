"""The self-running Spelling track.

Spelling is one of Washington's eleven required subjects and the easiest to
leave uncovered. This track needs no word list from the parent: the model
generates grade-level words with a deliberate range (a few easier, most on
level, a few stretch), each with a one-sentence clue (the word blanked out). A
short **daily card** drills a handful with Leitner spacing -- miss a word and it
comes back soon, nail it and it retires -- and a **weekly quiz** (Friday by
default) scores a batch weighted toward the ones he's been missing, posts a
Spelling grade, and logs the time.

The parent turns it on and it runs. This module owns the settings, the word-pool
top-up (the one model call), the daily/quiz word selection, and the
completion/credit logic. The database (pool + Leitner + quiz history) lives in
storage.db; the surfaces live in compass.ui.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from compass import config

# --- settings (the parent's one-switch setup) -----------------------------------

_ENABLED = "spelling_enabled"
_DAILY_COUNT = "spelling_daily_count"
_QUIZ_DAY = "spelling_quiz_day"      # 0=Mon … 6=Sun
_QUIZ_COUNT = "spelling_quiz_count"
_LEVEL = "spelling_level"            # "" = auto (use the student's grade)

WEEKDAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def _int_setting(db: Any, key: str, default: int) -> int:
    try:
        value = int(db.get_setting(key))
    except (TypeError, ValueError):
        return default
    return value


def is_enabled(db: Any) -> bool:
    return db.get_setting(_ENABLED) == "1"


def settings(db: Any) -> dict[str, Any]:
    """The whole Spelling setup in one read -- what the parent panel shows and
    the daily/quiz surfaces run on."""
    quiz_day = _int_setting(db, _QUIZ_DAY, config.SPELLING_QUIZ_WEEKDAY)
    if quiz_day < 0 or quiz_day > 6:
        quiz_day = config.SPELLING_QUIZ_WEEKDAY
    return {
        "enabled": is_enabled(db),
        "daily_count": max(1, _int_setting(db, _DAILY_COUNT, config.SPELLING_DAILY_WORDS)),
        "quiz_count": max(1, _int_setting(db, _QUIZ_COUNT, config.SPELLING_QUIZ_WORDS)),
        "quiz_day": quiz_day,
        "level": (db.get_setting(_LEVEL) or "").strip(),
    }


def save_settings(
    db: Any, *, enabled: bool | None = None, daily_count: int | None = None,
    quiz_count: int | None = None, quiz_day: int | None = None, level: str | None = None,
) -> None:
    if enabled is not None:
        db.set_setting(_ENABLED, "1" if enabled else "0")
    if daily_count is not None:
        db.set_setting(_DAILY_COUNT, str(max(1, int(daily_count))))
    if quiz_count is not None:
        db.set_setting(_QUIZ_COUNT, str(max(1, int(quiz_count))))
    if quiz_day is not None:
        db.set_setting(_QUIZ_DAY, str(int(quiz_day) % 7))
    if level is not None:
        db.set_setting(_LEVEL, level.strip())


def effective_level(db: Any, student: dict[str, Any]) -> str:
    """The grade band the model writes for: the parent's override, else the
    student's own grade."""
    override = (db.get_setting(_LEVEL) or "").strip()
    if override:
        return override
    grade = student.get("grade")
    return f"grade {grade}" if grade else "middle school"


def is_quiz_day(db: Any, today: date | None = None) -> bool:
    today = today or date.today()
    return today.weekday() == settings(db)["quiz_day"]


# --- grade from quiz history ----------------------------------------------------

_LETTER_BANDS = (
    (97, "A+"), (93, "A"), (90, "A-"), (87, "B+"), (83, "B"), (80, "B-"),
    (77, "C+"), (73, "C"), (70, "C-"), (67, "D+"), (63, "D"), (60, "D-"),
)


def letter_grade(percent: float) -> str:
    for cutoff, letter in _LETTER_BANDS:
        if percent >= cutoff:
            return letter
    return "F"


def grade_summary(db: Any, student_id: int) -> dict[str, Any] | None:
    """His Spelling standing from quiz history -- a KIND average, a letter, and the
    most recent quiz. None until he's taken one.

    'Kind' = once there are at least three quizzes, his single LOWEST score is
    dropped before averaging, and only his recent dozen count. So one rough early
    week (the 'bar too high on the first rollout' F) doesn't follow him all year --
    the grade tracks where he is NOW."""
    results = db.list_spelling_quiz_results(student_id, limit=12)
    scored = [r for r in results if r["total"]]
    if not scored:
        return None
    pcts = [100 * r["correct"] / r["total"] for r in scored]  # recent first
    kept = sorted(pcts)
    dropped = len(kept) >= 3
    if dropped:
        kept = kept[1:]  # drop the single lowest
    pct = sum(kept) / len(kept)
    latest = scored[0]
    return {
        "average": round(pct),
        "letter": letter_grade(pct),
        "quizzes": len(scored),
        "counted": len(kept),
        "dropped_lowest": dropped,
        "last_correct": latest["correct"],
        "last_total": latest["total"],
        "last_on": latest["taken_on"],
    }


# --- motivation: streak, mastery belts, progress --------------------------------

# Belts by how many words he's truly mastered (reached box 5). A long, reachable
# ladder so there's always a next rank in sight.
SPELLING_BELTS: list[tuple[int, str]] = [
    (0, "⚪ White"), (5, "🟡 Yellow"), (15, "🟠 Orange"), (30, "🟢 Green"),
    (50, "🔵 Blue"), (75, "🟣 Purple"), (100, "🟤 Brown"), (150, "⚫ Black"),
]


def belt_for(mastered: int) -> tuple[str, int | None, int]:
    """His current belt for `mastered` words: (belt_name, next_threshold_or_None,
    words_to_next). At the top belt, next is None and words_to_next is 0."""
    name = SPELLING_BELTS[0][1]
    nxt: int | None = None
    for i, (threshold, label_) in enumerate(SPELLING_BELTS):
        if mastered >= threshold:
            name = label_
            nxt = SPELLING_BELTS[i + 1][0] if i + 1 < len(SPELLING_BELTS) else None
        else:
            break
    to_next = (nxt - mastered) if nxt is not None else 0
    return name, nxt, to_next


def daily_streak(dates: list[str], today: str | None = None) -> int:
    """Consecutive days of spelling practice ending today (or yesterday, so an
    unfinished today doesn't break the chain). `dates` = distinct practice days,
    most recent first (ISO)."""
    from datetime import timedelta

    have = set(dates)
    if not have:
        return 0
    cur = date.fromisoformat(today) if today else date.today()
    if cur.isoformat() not in have:
        cur = cur - timedelta(days=1)  # today not done yet? count from yesterday
        if cur.isoformat() not in have:
            return 0
    streak = 0
    while cur.isoformat() in have:
        streak += 1
        cur = cur - timedelta(days=1)
    return streak


def spelling_progress(db: Any, student: dict[str, Any]) -> dict[str, Any]:
    """A compact 'how's he doing' snapshot for the student's own view: mastered
    count, his belt and what's next, the active-pool size, and his practice
    streak. All cheap reads."""
    sid = student["id"]
    counts = db.spelling_pool_counts(sid)
    mastered = db.spelling_mastered_count(sid)
    belt, nxt, to_next = belt_for(mastered)
    next_belt = next((lbl for thr, lbl in SPELLING_BELTS if thr == nxt), None)
    streak = daily_streak(db.spelling_practice_dates(sid))
    return {
        "mastered": mastered,
        "active": counts["active"],
        "total_seen": counts["total"],
        "belt": belt,
        "next_at": nxt,
        "next_belt": next_belt,
        "to_next": to_next,
        "streak": streak,
    }


# --- the one model call: top up the word pool -----------------------------------

SPELLING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "words": {
            "type": "array",
            "description": "The spelling words for this batch.",
            "items": {
                "type": "object",
                "properties": {
                    "word": {
                        "type": "string",
                        "description": "A single spelling word, lowercase, correctly spelled.",
                    },
                    "clue": {
                        "type": "string",
                        "description": (
                            "One short, natural sentence that uses the word, with the "
                            "word itself replaced by a blank '____'. Gives him the "
                            "meaning in context without showing the spelling."
                        ),
                    },
                    "tier": {
                        "type": "string",
                        "enum": ["easier", "on", "stretch"],
                        "description": (
                            "'easier' = a touch below grade (confidence), 'on' = right "
                            "at grade, 'stretch' = a bit above."
                        ),
                    },
                    "definition": {
                        "type": "string",
                        "description": (
                            "A short, kid-friendly meaning of the word (one plain "
                            "sentence, no jargon). This is shown in the 'study the word' "
                            "step, so it CAN name the word."
                        ),
                    },
                    "syllables": {
                        "type": "string",
                        "description": (
                            "The word broken into syllables with hyphens, e.g. "
                            "'rhy-thm', 'def-i-nite-ly'. Helps him spell it chunk by chunk."
                        ),
                    },
                    "word_parts": {
                        "type": "string",
                        "description": (
                            "A brief note on the word's structure that aids spelling: a "
                            "root/prefix/suffix or a related word family, e.g. "
                            "'sign + -ature; keep the silent g from sign' or "
                            "'un- + necessary (one n, two s, two c? no: 2 c, 2 s)'. "
                            "Keep it one short line; '' if nothing useful."
                        ),
                    },
                    "memory_trick": {
                        "type": "string",
                        "description": (
                            "A short, sticky memory trick / mnemonic for the tricky part "
                            "of the spelling, e.g. 'necessary: one Collar, two Sleeves' or "
                            "'there's A RAT in sepARATe'. '' if none fits."
                        ),
                    },
                },
                "required": ["word", "clue", "tier", "definition", "syllables",
                             "word_parts", "memory_trick"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["words"],
    "additionalProperties": False,
}


def _generation_prompt(level: str, n: int, exclude: set[str]) -> tuple[str, str]:
    avoid = ", ".join(sorted(exclude)[:120])
    system = (
        f"You build a spelling word list for a homeschooled student at {level} level. "
        f"Choose words that are genuinely useful and commonly misspelled -- not obscure "
        f"trivia. Keep a deliberate RANGE: about one in five a touch EASIER than grade "
        f"(confidence), most right ON grade, and one or two a STRETCH above. For each "
        f"word write one short, natural sentence that uses it, with the word replaced by "
        f"a blank '____' so the sentence gives meaning without revealing the spelling. "
        f"Words must be single words, lowercase, and correctly spelled.\n\n"
        f"ALSO, for each word, fill the study fields that help a kid actually LEARN to "
        f"spell it: a plain kid-friendly definition; the word split into syllables with "
        f"hyphens; a one-line note on its word-parts or the tricky letters; and a short, "
        f"sticky memory trick for the hard part. These are shown only in a 'study the "
        f"word' step, so they may reveal the word itself. If a field doesn't apply, use "
        f"an empty string."
    )
    user = f"Give me {n} spelling words now."
    if avoid:
        user += f" Do NOT repeat any of these words he already has: {avoid}."
    return system, user


def generate_words(
    db: Any, student: dict[str, Any], n: int, exclude: set[str] | None = None
) -> list[dict[str, str]]:
    """One model call -> a batch of {word, clue, tier}. Raises LessonGenerationError
    on an API problem (callers that top up a pool swallow it)."""
    from compass.agents.llm import generate_lesson

    system, user = _generation_prompt(
        effective_level(db, student), n, {w.lower() for w in (exclude or set())}
    )
    payload = generate_lesson(
        system=system, user_prompt=user, schema=SPELLING_SCHEMA,
        effort=config.DEFAULT_EFFORT,
    )
    out: list[dict[str, str]] = []
    for item in payload.get("words") or []:
        word = str(item.get("word") or "").strip()
        if not word or " " in word:
            continue
        tier = item.get("tier")
        out.append({
            "word": word.lower(),
            "clue": str(item.get("clue") or "").strip(),
            "tier": tier if tier in ("easier", "on", "stretch") else "on",
            "definition": str(item.get("definition") or "").strip(),
            "syllables": str(item.get("syllables") or "").strip(),
            "word_parts": str(item.get("word_parts") or "").strip(),
            "memory_trick": str(item.get("memory_trick") or "").strip(),
        })
    return out


def ensure_pool(db: Any, student: dict[str, Any], *, minimum: int | None = None) -> int:
    """Keep at least `minimum` active words in rotation, generating more at his
    level when the pool runs low. A no-op (returns 0) when spelling is off or the
    API isn't available, so the app never blocks on it. Returns how many were
    added."""
    if not is_enabled(db):
        return 0
    minimum = minimum or config.SPELLING_MIN_POOL
    counts = db.spelling_pool_counts(student["id"])
    if counts["active"] >= minimum:
        return 0
    from compass.agents import api_available
    ok, _msg = api_available()
    if not ok:
        return 0
    existing = {w["word"].lower() for w in db.list_spelling_words(student["id"], include_retired=True)}
    want = max(minimum - counts["active"], config.SPELLING_DAILY_WORDS * 2)
    try:
        batch = generate_words(db, student, want, exclude=existing)
    except Exception:
        return 0  # a flaky generation never breaks his day; we try again next load
    added = 0
    for item in batch:
        if item["word"] in existing:
            continue
        if db.add_spelling_word(
            student["id"], item["word"], item["clue"], item["tier"],
            definition=item.get("definition", ""),
            syllables=item.get("syllables", ""),
            word_parts=item.get("word_parts", ""),
            memory_trick=item.get("memory_trick", ""),
        ):
            added += 1
            existing.add(item["word"])
    return added


# --- daily card + weekly quiz: selection and completion -------------------------

def daily_words(db: Any, student: dict[str, Any]) -> list[dict[str, Any]]:
    return db.spelling_due(student["id"], limit=settings(db)["daily_count"])


def quiz_words(db: Any, student: dict[str, Any]) -> list[dict[str, Any]]:
    return db.spelling_quiz_pool(student["id"], limit=settings(db)["quiz_count"])


def _daily_done_key(on: str) -> str:
    return f"spelling_daily_done_{on}"


def daily_done_today(db: Any, today: str | None = None) -> bool:
    return bool(db.get_setting(_daily_done_key(today or date.today().isoformat())))


def complete_daily(
    db: Any, student: dict[str, Any],
    answers: list[tuple[int, bool, str]], duration_seconds: int | None = None,
) -> dict[str, Any]:
    """Record each word's result (Leitner) -- with exactly what he typed and how
    long the card took -- then log the day's few minutes to Spelling, once per day
    so re-opening never double-counts. `answers` is (word_id, correct, typed).
    Returns {mastered: how many words he just pushed to mastery} so the card can
    celebrate it."""
    mastered_before = db.spelling_mastered_count(student["id"])
    for word_id, correct, typed in answers:
        db.record_spelling_attempt(
            word_id, bool(correct), kind="daily",
            typed=typed, duration_seconds=duration_seconds,
        )
    mastered_now = max(0, db.spelling_mastered_count(student["id"]) - mastered_before)
    key = _daily_done_key(date.today().isoformat())
    if answers and not db.get_setting(key):
        db.log_activity(
            student_id=student["id"],
            title="Daily spelling",
            tier=config.TIER_CORE,
            primary_subject="spelling",
            minutes=config.SPELLING_DAILY_MINUTES,
            subject_credits={"spelling": config.SPELLING_DAILY_MINUTES},
            occurred_on=date.today().isoformat(),
            description="Daily spelling practice.",
            source="spelling",
        )
        db.set_setting(key, "1")
    return {"mastered": mastered_now}


def complete_quiz(
    db: Any, student: dict[str, Any],
    answers: list[tuple[int, bool, str]], duration_seconds: int | None = None,
) -> dict[str, Any]:
    """Record the quiz: each word's Leitner result and submission (typed + time),
    the score row (for the grade), and the assessment time -- once per day.
    `answers` is (word_id, correct, typed). Returns {correct, total}."""
    for word_id, correct, typed in answers:
        db.record_spelling_attempt(
            word_id, bool(correct), kind="quiz",
            typed=typed, duration_seconds=duration_seconds,
        )
    correct = sum(1 for _wid, ok, _t in answers if ok)
    total = len(answers)
    db.record_spelling_quiz(student["id"], correct, total, duration_seconds=duration_seconds)
    db.log_activity(
        student_id=student["id"],
        title="Spelling quiz",
        tier=config.TIER_CORE,
        primary_subject="spelling",
        minutes=config.SPELLING_QUIZ_MINUTES,
        subject_credits={"spelling": config.SPELLING_QUIZ_MINUTES},
        occurred_on=date.today().isoformat(),
        description=f"Weekly spelling quiz — {correct}/{total}.",
        source="spelling",
    )
    return {"correct": correct, "total": total}


# --- practice game modes (daily card only) --------------------------------------
#
# The daily card used to be the same "hear it, type it" every day. These give it
# variety AND scaffold by how shaky the word is: a brand-new / just-missed word
# (low Leitner box) gets an easier, supported mode (pick the right spelling, or
# fill the blanks); as it climbs boxes the support falls away until it's full
# dictation from memory. The weekly quiz is always dictation -- it's the test.
# All pure functions, seeded by the word + day so a word's mode is stable within
# a day (reruns don't reshuffle) but varies day to day.

import random as _random

PRACTICE_MODES = ("choose", "missing", "unscramble", "dictation")

_MODE_LABELS = {
    "choose": "✅ Pick the correct spelling",
    "missing": "🧩 Fill in the missing letters",
    "unscramble": "🔀 Unscramble the letters",
    "dictation": "🔊 Hear it, then spell it",
}


def _seed(*parts: Any) -> _random.Random:
    return _random.Random("|".join(str(p) for p in parts))


def practice_mode_for(word: dict[str, Any], day: str) -> str:
    """Pick the practice mode for one word today, scaffolded by its Leitner box:
    box 1 (new/just-missed) -> recognition or fill-the-blanks; box 2-3 -> a mix up
    to dictation; box 4+ -> straight dictation."""
    box = int(word.get("box") or 1)
    if box <= 1:
        pool = ["choose", "missing"]
    elif box <= 3:
        pool = ["missing", "unscramble", "dictation"]
    else:
        pool = ["dictation"]
    return _seed(word.get("id"), day).choice(pool)


def mode_label(mode: str) -> str:
    return _MODE_LABELS.get(mode, _MODE_LABELS["dictation"])


def scramble_word(word: str, day: str = "") -> str:
    """The word's letters shuffled into a jumble (never back to the word itself)."""
    word = (word or "").strip()
    if len(word) < 2:
        return word
    rng = _seed(word, day)
    letters = list(word)
    for _ in range(16):
        rng.shuffle(letters)
        candidate = "".join(letters)
        if candidate != word:
            return candidate
    return "".join(reversed(word))


def mask_word(word: str, day: str = "") -> str:
    """The word with ~40% of its *interior* letters blanked to underscores,
    spaced out so the blanks are obvious (r h y t h m -> r _ y _ h m)."""
    word = (word or "").strip()
    if len(word) <= 2:
        return " ".join(word)
    rng = _seed(word, day)
    interior = list(range(1, len(word) - 1))
    rng.shuffle(interior)
    blanks = max(1, round(len(word) * 0.4))
    chars = list(word)
    for i in interior[:blanks]:
        chars[i] = "_"
    return " ".join(chars)


def _perturb(word: str, rng: _random.Random) -> str:
    chars = list(word)
    ops = ["swap", "double", "vowel"]
    if len(chars) >= 4:
        ops.append("drop")
    op = rng.choice(ops)
    if op == "swap" and len(chars) >= 2:
        i = rng.randrange(len(chars) - 1)
        chars[i], chars[i + 1] = chars[i + 1], chars[i]
    elif op == "drop" and len(chars) >= 4:
        chars.pop(rng.randrange(1, len(chars) - 1))
    elif op == "double":
        i = rng.randrange(len(chars))
        chars.insert(i, chars[i])
    elif op == "vowel":
        vowels = "aeiou"
        idxs = [i for i, c in enumerate(chars) if c in vowels]
        if idxs:
            i = rng.choice(idxs)
            chars[i] = rng.choice([v for v in vowels if v != chars[i]])
    return "".join(chars)


def misspellings(word: str, n: int = 3, day: str = "") -> list[str]:
    """`n` plausible WRONG spellings of the word (letter swaps, a dropped or
    doubled letter, a vowel swap) -- the distractors for the 'pick the correct
    spelling' mode. Never includes the real word."""
    word = (word or "").strip()
    rng = _seed(word, day, "miss")
    out: list[str] = []
    seen = {word}
    tries = 0
    while len(out) < n and tries < 80:
        tries += 1
        cand = _perturb(word, rng)
        if cand and cand not in seen:
            seen.add(cand)
            out.append(cand)
    return out


def choice_options(word: str, n_distractors: int = 3, day: str = "") -> list[str]:
    """The shuffled option list for 'pick the correct spelling': the real word plus
    up to `n_distractors` plausible misspellings."""
    opts = [word] + misspellings(word, n_distractors, day)
    _seed(word, day, "opts").shuffle(opts)
    return opts
