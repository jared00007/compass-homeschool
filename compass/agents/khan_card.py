"""Khan cards -- a parent hand-enters a Khan Academy unit or exercise as a
lesson card for Landon, no AI lesson generation involved.

The family's math plan (and, when they want, other subjects) can run on Khan
Academy: Khan carries the teaching and the practice, and Compass is the wrapper
-- it schedules the work onto Landon's board, logs the hours for compliance, and
keeps a short auto-graded quiz on each card as the in-app retention check.

A Khan card IS an ordinary lesson row, saved under the subject's own agent key
(a math Khan card is a `math` lesson), so it surfaces on Home under that subject,
opens on the subject page, and flows through the exact same "approve & log hours"
review path as any other lesson -- no new completion plumbing. What's different
is only how it's built:

  * No `learn` / `worked_example` -- Khan does the teaching, so those stay empty
    and render as nothing.
  * ONE parent-graded activity: open the Khan skill (the link lives here), do it
    to mastery, then type your Khan score. Carrying an `answer` is what makes it
    gradeable, which is what unlocks the parent's approve-and-log-hours control.
  * A quiz pool generated from the unit/exercise name -- the one model call a
    Khan card makes, so Compass still has an auto-graded check the way every
    other lesson does. Regenerable, and droppable to zero if the parent enters
    their own questions instead.

Unlike a graph-walked math lesson it carries no `skill_id`, so it never advances
the math mastery graph on its own -- it logs real subject hours and a real quiz
score, but "mastered this node" stays something the prerequisite graph decides.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any, Callable
from uuid import uuid4

from compass import config, subjects
from compass.agents.llm import LessonGenerationError, _object, generate_lesson
from compass.agents.quiz import verify_quiz

# Every Khan card is saved under this one agent, whatever WA subject it credits,
# so they all share a single home (the Khan page) instead of being limited to the
# four subjects that happen to have their own page. The card's `subject` carries
# the real WA subject its hours credit.
AGENT_KEY = "khan"

# The WA subjects a Khan card can be assigned to, with friendly labels for the
# picker. Washington splits "English / ELA" into reading, writing, spelling and
# language, so there's no single "English" subject key -- the familiar label
# leads the reading option (reading is what the English agent credits and what
# the English grade folds together), with writing/spelling/language available for
# a parent who wants to credit those specifically. Each value is a real WA
# subject key the card's hours credit to.
KHAN_SUBJECTS: tuple[tuple[str, str], ...] = (
    ("math", "📐 Math"),
    ("reading", "📖 English / Language Arts"),
    ("writing", "✍️ Writing"),
    ("science", "🔬 Science"),
    ("history", "🏛️ History"),
    ("social_studies", "🌎 Social Studies"),
    ("art_and_music", "🎵 Art & Music"),
    ("health", "🏃 Health & Fitness"),
    ("spelling", "🔤 Spelling"),
    ("language", "🗣️ Grammar & Language"),
    ("occupational_education", "🛠️ Occupational Ed"),
)


def is_supported_subject(subject_key: str) -> bool:
    return subjects.is_valid(subject_key)


def khan_base_url(db: Any) -> str:
    """The one Khan Academy link every card points at -- set once by the family,
    so the parent never re-pastes a URL per card."""
    return (db.get_setting("khan_base_url") or "").strip() or config.DEFAULT_SETTINGS[
        "khan_base_url"
    ]


def default_minutes(subject_key: str) -> int:
    """The form opens at the subject's usual lesson length (Math 35, etc.),
    falling back to the family default -- same source the Plan-a-lesson form uses,
    so a Khan card doesn't feel like a different size of thing."""
    return config.SUBJECT_DEFAULT_MINUTES.get(
        subject_key, int(config.DEFAULT_SETTINGS["default_lesson_minutes"])
    )


# Just the quiz -- the only thing a Khan card asks a model for. Same item shape
# the app already grades everywhere, so nothing downstream needs to special-case
# it.
KHAN_QUIZ_SCHEMA = _object(
    {
        "quiz": {
            "type": "array",
            "description": (
                "A pool of {min}-{max} multiple-choice questions checking whether "
                "he learned this Khan Academy skill -- straightforward recall and "
                "application of the skill itself, the kind of thing he should be able "
                "to answer after practicing it on Khan. He's served five at a time, "
                "reshuffled on each retry, so the pool needs real breadth: cover the "
                "skill from several angles at a mix of difficulties, and don't reword "
                "one idea over and over."
            ).format(min=config.KHAN_QUIZ_POOL_MIN, max=config.KHAN_QUIZ_POOL_MAX),
            "items": _object(
                {
                    "question": {"type": "string"},
                    "choices": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Exactly four answer choices, one clearly correct and three "
                            "plausible distractors that aren't obviously wrong."
                        ),
                    },
                    "correct_index": {
                        "type": "integer",
                        "description": "0-based index into `choices` of the correct answer.",
                    },
                    "explanation": {
                        "type": "string",
                        "description": "One sentence on why that answer is correct, shown after he answers.",
                    },
                }
            ),
        }
    }
)

_QUIZ_SYSTEM = """\
You write a short auto-graded quiz for Compass, a family's homeschool app, for a \
{age}-year-old {grade}th grader named {name}. He has just practiced a specific \
skill on Khan Academy; your only job is to write a quiz that checks whether he \
learned THAT skill. You are not teaching anything and not writing a lesson -- \
only the quiz.

Anchor the quiz to a real grade-{grade} expectation for this exact skill \
(Common Core for math and language arts, NGSS for science, a state framework for \
social studies) -- the same depth and problem types a standards-aligned lesson \
on it would test, not watered down and not a grade ahead.

The skill: {skill}
Subject: {subject}{note}

Write a pool of {min}-{max} multiple-choice questions:
- Each has exactly four choices: one clearly correct, three plausible distractors.
- Spread across recall, application to a fresh case, and a few harder multi-step \
questions -- including ones that hinge on the mistake a student makes when they \
only half-learn this skill (that wrong answer becomes a distractor).
- Vary which position the correct answer sits in from question to question.
- `explanation` is one sentence on why the correct choice is right, shown after \
he answers.
- Keep every question answerable from knowing the skill itself -- nothing that \
needs a specific Khan video or outside trivia.
Write the questions at his reading level: short, plain, one idea each.
"""


def generate_khan_quiz(
    student: dict[str, Any], subject_key: str, unit: str, *, note: str = ""
) -> list[dict[str, Any]]:
    """Generate and verify a quiz pool for one Khan skill. The single model call
    a Khan card makes; returns the cleaned list of questions (never raises on a
    few malformed items -- those are dropped, same as any lesson quiz)."""
    subject_label = subjects.label(subject_key)
    note_line = f"\nParent's note about this skill: {note.strip()}" if note.strip() else ""
    system = _QUIZ_SYSTEM.format(
        age=student.get("age") or 13,
        grade=student.get("grade") or "8",
        name=student.get("name") or "the student",
        skill=unit.strip(),
        subject=subject_label,
        note=note_line,
        min=config.KHAN_QUIZ_POOL_MIN,
        max=config.KHAN_QUIZ_POOL_MAX,
    )
    payload = generate_lesson(
        system=system,
        user_prompt=(
            "Write the quiz pool for this skill now. Return only the `quiz` field."
        ),
        schema=KHAN_QUIZ_SCHEMA,
        effort=config.DEFAULT_EFFORT,
    )
    verify_quiz(payload)
    # Carry the generation's token usage onto the first question so the built
    # card can surface it for cost tracking without inventing a place to hang it.
    usage = payload.get("_usage")
    quiz = payload.get("quiz") or []
    if quiz and usage:
        quiz[0].setdefault("_usage", usage)
    return quiz


_KHAN_REF_MARKER = "📚 **Khan reference**"


def khan_reference_line(
    course_name: str, unit: str, subject_key: str, unit_number: int | None = None
) -> str:
    """The one-line "what to open on Khan and where it credits" header that leads a
    Khan card -- Course · Subject · Unit N: name. Always starts with
    `_KHAN_REF_MARKER` so it can be found and rebuilt in place when a unit is
    renamed, renumbered, or re-credited."""
    bits = []
    if course_name.strip():
        bits.append(f"**{course_name.strip()}**")
    if subject_key:
        bits.append(f"🎯 {subjects.label(subject_key)}")
    if unit.strip():
        num = f"Unit {int(unit_number)}: " if unit_number else "Unit: "
        bits.append(f"📗 {num}{unit.strip()}")
    return f"{_KHAN_REF_MARKER} — " + " · ".join(bits)


def _overview_with_reference(overview: str, reference: str) -> str:
    """Put `reference` as the first paragraph of `overview`, replacing an existing
    reference line (so a rename/re-credit refreshes it in place) or prepending it."""
    parts = overview.split("\n\n", 1)
    if parts and parts[0].startswith(_KHAN_REF_MARKER):
        rest = parts[1] if len(parts) > 1 else ""
        return f"{reference}\n\n{rest}" if rest else reference
    return f"{reference}\n\n{overview}" if overview else reference


def build_khan_card_payload(
    subject_key: str,
    unit: str,
    url: str,
    minutes: int,
    *,
    quiz: list[dict[str, Any]] | None = None,
    note: str = "",
    course: str = "",
    course_name: str = "",
    unit_number: int | None = None,
    items: list[str] | None = None,
) -> dict[str, Any]:
    """The ordinary-lesson payload for a Khan card -- pure, no model call, so the
    shape is unit-testable on its own. Renders through render_lesson + render_quiz
    exactly like any other lesson. When the card came from a loaded course, pass
    `course` so the course name is stated on the card itself. `items` (the Khan
    lesson's videos/exercises) render as a checklist of what to do on Khan."""
    credit_subject = subject_key
    subject_label = subjects.label(credit_subject)
    unit = unit.strip()
    url = url.strip()
    course = course.strip()
    quiz = list(quiz or [])
    # Lift any usage the quiz carried up to a top-level `_usage`, where the cost
    # report already looks, and off the question the student sees.
    usage = quiz[0].pop("_usage", None) if quiz else None

    # The simplest possible card: the Khan link + the quiz, nothing to type. He
    # opens the link, does the skill on Khan, takes the quiz, and turns it in;
    # the quiz is what scores it. No graded activity, so the parent's review is
    # one tap (see review._render_khan_review).
    items = [str(i).strip() for i in (items or []) if str(i).strip()]
    reference = khan_reference_line(course_name, course, credit_subject, unit_number)
    overview = (
        f"{reference}\n\n"
        f"Do this one on Khan Academy:\n\n"
        f"▶️ **[Open in Khan Academy]({url})**\n\n"
        f"Work the skill all the way through over there, then come back and take "
        f"the quick quiz below to lock it in and turn it in."
    )
    if items:
        checklist = "\n".join(f"- {item}" for item in items)
        overview += f"\n\n**On Khan, work through:**\n{checklist}"
    if note.strip():
        overview += f"\n\n**From your parent:** {note.strip()}"

    payload: dict[str, Any] = {
        "title": f"Khan Academy: {unit}",
        "topic": unit,
        "overview": overview,
        "learning_objectives": [f"Work the Khan Academy skill: {unit}"],
        "learn": {
            "explanation": "",
            "video": {"found": False, "title": "", "url": "", "channel": "", "why": ""},
        },
        "worked_example": {"problem": "", "steps": ""},
        "activities": [],
        "materials": ["A device with Khan Academy open"],
        "subject_credits": [
            {
                "subject": credit_subject,
                "minutes": minutes,
                "justification": (
                    f"Completed the assigned Khan Academy skill '{unit}' for "
                    f"{subject_label}."
                ),
            }
        ],
        "quiz": quiz,
        "estimated_minutes": minutes,
        "fun_extra": {"title": "", "instructions": ""},
        "parent_notes": (
            f"Khan Academy card. He does '{unit}' on Khan (link in the lesson), "
            f"takes the quiz, and turns it in. The quiz scores it; approving is one "
            f"tap to log the hours and file it."
        ),
        "branches": [],
    }
    if usage:
        payload["_usage"] = usage
    return payload


def build_khan_checkpoint_payload(
    subject_key: str,
    label: str,
    url: str,
    minutes: int,
    *,
    kind: str,
    covers: list[str] | None = None,
    course: str = "",
    course_name: str = "",
    unit_number: int | None = None,
) -> dict[str, Any]:
    """The payload for a Khan CHECKPOINT card -- a quiz or unit test he takes on
    Khan. It carries no Compass quiz (it IS the quiz); he takes it on Khan, turns
    it in, and the parent records his real Khan score (which feeds the grade). The
    card lists which lessons it covers."""
    subject_label = subjects.label(subject_key)
    label = label.strip()
    url = url.strip()
    course = course.strip()
    covers = [str(c).strip() for c in (covers or []) if str(c).strip()]
    kind_label = "Unit test" if kind == "unit_test" else "Quiz"

    reference = khan_reference_line(course_name, course, subject_key, unit_number)
    covers_block = ""
    if covers:
        covers_block = "\n\n**It covers:**\n" + "\n".join(f"- {c}" for c in covers)
    overview = (
        f"{reference}\n\n"
        f"📝 **Checkpoint — Khan {kind_label}.**\n\n"
        f"▶️ **[Open in Khan Academy]({url})**\n\n"
        f"Take this {kind_label.lower()} over on Khan, then come back and turn it in. "
        f"Your parent records your real Khan score, which counts toward your grade."
        f"{covers_block}"
    )
    return {
        "title": f"Khan Academy: {label}",
        "topic": label,
        "overview": overview,
        "learning_objectives": [f"Take the Khan {kind_label}: {label}"],
        "learn": {
            "explanation": "",
            "video": {"found": False, "title": "", "url": "", "channel": "", "why": ""},
        },
        "worked_example": {"problem": "", "steps": ""},
        "activities": [],
        "materials": ["A device with Khan Academy open"],
        "subject_credits": [
            {
                "subject": subject_key,
                "minutes": minutes,
                "justification": (
                    f"Took the Khan Academy {kind_label.lower()} '{label}' for "
                    f"{subject_label}."
                ),
            }
        ],
        "quiz": [],
        "estimated_minutes": minutes,
        "fun_extra": {"title": "", "instructions": ""},
        "parent_notes": (
            f"Khan {kind_label} checkpoint. He takes it on Khan and turns it in; "
            f"record his real Khan score on the card (it feeds the grade)."
        ),
        "branches": [],
    }


def create_khan_card(
    db: Any,
    student: dict[str, Any],
    *,
    subject: str,
    unit: str,
    url: str | None = None,
    minutes: int,
    day_iso: str | None = None,
    note: str = "",
    quiz: list[dict[str, Any]] | None = None,
    generate_quiz: bool = True,
    no_xp: bool = False,
) -> int:
    """Create one Khan card, schedule it, and return its lesson id.

    `subject` is the WA subject the card's hours credit (any of `KHAN_SUBJECTS`).
    `url` defaults to the family's saved Khan link (`khan_base_url`), so the
    parent never re-pastes it per card. Generates the quiz from the unit name
    unless `quiz` is passed in (tests, or a parent who entered their own). Saved
    under the single `khan` agent so every Khan card shares one home (the Khan
    page). Scheduled to `day_iso` if given (via the normal reschedule path, which
    sets planned_for + week_start); left in the backlog otherwise.

    `no_xp=True` marks it a reminder/review card: it behaves like any other card
    (scheduled, worked, turned in, reviewed, hours logged) but earns no XP -- a
    way to put "circle back and review" time on his calendar without it padding
    the reward total.
    """
    if not is_supported_subject(subject):
        raise ValueError(f"'{subject}' isn't a valid subject for a Khan card.")
    if not unit.strip():
        raise ValueError("Give the unit or exercise a name.")
    url = (url or "").strip() or khan_base_url(db)

    if quiz is None and generate_quiz:
        quiz = generate_khan_quiz(student, subject, unit, note=note)

    payload = build_khan_card_payload(subject, unit, url, minutes, quiz=quiz, note=note)
    metadata: dict[str, Any] = {"source": "khan", "resource_url": url.strip()}
    if no_xp:
        metadata["no_xp"] = True
    if day_iso is None:
        # No day yet -> park it in the parent's Backlog to schedule from the
        # Board, the same way a generated series lands (held_back).
        metadata["held_back"] = True

    lesson_id = db.save_lesson(
        student_id=student["id"],
        agent=AGENT_KEY,
        subject=subject,
        topic=unit.strip(),
        title=f"Khan Academy: {unit.strip()}",
        payload=payload,
        strategy="parent_khan_card",
        rationale="Parent added a Khan Academy skill as a lesson card.",
        metadata=metadata,
    )
    if day_iso is not None:
        db.reschedule_lesson(lesson_id, day_iso)
    return lesson_id


# --- course shells: load a whole course, fill & assign it out over time --------


def create_course(
    db: Any,
    student: dict[str, Any],
    *,
    subject: str,
    course: str,
    lessons: list[Any],
    minutes: int,
    generate_quiz: bool = False,
    course_name: str = "",
    unit_number: int = 0,
    on_progress: Callable[[int, int, str | None], None] | None = None,
) -> dict[str, list[Any]]:
    """Load a whole Khan course from an ordered lesson list -- one card per
    lesson, numbered in order ("1. …", "2. …"), all tagged with a shared course
    id and parked in the Backlog to assign out day by day.

    `course` is the UNIT the cards belong to; `course_name` (optional) is the
    top-level Khan course the unit sits under (e.g. "8th grade math essentials"),
    stored so the Backlog can group and filter by course as well as unit.

    Each entry in ``lessons`` is one card, in order, and is either:
      * a plain name (``str``) or ``{"name", "items"}`` dict -> a LESSON card
        (``items`` is the Khan lesson's videos/exercises, shown as a checklist), or
      * a ``{"kind": "quiz"|"unit_test", "name", "covers"}`` dict -> a CHECKPOINT
        card (Khan's own quiz / unit test), the graded point where his real Khan
        score is recorded; it never gets a Compass quiz.

    Lesson quizzes are normally generated when a card is *assigned*
    (assign_course_card), so this defaults to no quiz -- pass generate_quiz=True to
    build them all up front. Returns {"created": [ids], "quiz_failed": [names]}."""
    if not is_supported_subject(subject):
        raise ValueError(f"'{subject}' isn't a valid subject for a Khan card.")
    course = course.strip()
    if not course:
        raise ValueError("Name the course.")
    normalized: list[dict[str, Any]] = []
    for entry in lessons:
        if isinstance(entry, dict) and entry.get("kind") in ("quiz", "unit_test"):
            name = str(entry.get("name") or "").strip()
            if name:
                covers = [str(c).strip() for c in (entry.get("covers") or []) if str(c).strip()]
                normalized.append({"kind": entry["kind"], "name": name, "covers": covers})
            continue
        if isinstance(entry, dict):
            name = str(entry.get("name") or "").strip()
            items = [str(i).strip() for i in (entry.get("items") or []) if str(i).strip()]
        else:
            name, items = str(entry).strip(), []
        if name:
            normalized.append({"kind": "lesson", "name": name, "items": items})
    if not any(e["kind"] == "lesson" for e in normalized):
        raise ValueError("Enter at least one lesson (one per line).")
    normalized = normalized[:120]  # a sane cap so a paste-gone-wrong can't create thousands
    url = khan_base_url(db)
    course_id = f"khancourse-{uuid4().hex[:8]}"
    total = len(normalized)
    result: dict[str, list[Any]] = {"created": [], "quiz_failed": []}
    for index, entry in enumerate(normalized, start=1):
        name = entry["name"]
        if on_progress is not None:
            on_progress(index - 1, total, name)
        metadata: dict[str, Any] = {
            "source": "khan", "resource_url": url,
            "khan_unit": course, "khan_course_id": course_id,
            "khan_part": index, "khan_course_total": total, "held_back": True,
        }
        if course_name.strip():
            metadata["khan_course_name"] = course_name.strip()
        if unit_number:
            metadata["khan_unit_number"] = int(unit_number)
        if entry["kind"] in ("quiz", "unit_test"):
            label = name
            prefix = f"{course}: "
            if label.startswith(prefix):
                label = label[len(prefix):]           # "Numbers and operations: Quiz 1" -> "Quiz 1"
            payload = build_khan_checkpoint_payload(
                subject, label, url, minutes, kind=entry["kind"],
                covers=entry["covers"], course=course, course_name=course_name.strip(),
                unit_number=unit_number or None,
            )
            title = f"{index}. 📝 {label}"
            payload["title"] = title
            metadata["khan_checkpoint"] = True
            metadata["khan_checkpoint_kind"] = entry["kind"]
            if entry["covers"]:
                metadata["khan_covers"] = entry["covers"]
            topic = label
        else:
            items = entry["items"]
            quiz = None
            if generate_quiz:
                try:
                    quiz = generate_khan_quiz(student, subject, name)
                except LessonGenerationError:
                    result["quiz_failed"].append(name)
            payload = build_khan_card_payload(
                subject, name, url, minutes, quiz=quiz, course=course,
                course_name=course_name.strip(), unit_number=unit_number or None, items=items,
            )
            title = f"{index}. {name}"
            payload["title"] = title
            if items:
                metadata["khan_items"] = items
            topic = name
        lesson_id = db.save_lesson(
            student_id=student["id"], agent=AGENT_KEY, subject=subject,
            topic=topic, title=title,
            payload=payload, strategy="parent_khan_course",
            rationale="Parent loaded a Khan course as an ordered lesson list.",
            metadata=metadata,
        )
        result["created"].append(lesson_id)
    if on_progress is not None:
        on_progress(total, total, None)
    return result


# --- bulk import: a whole course (many units) from one pasted outline ----------

_COURSE_LINE_RE = re.compile(r"^\s*course\s*[:\-]\s*(.+)$", re.I)
# "Unit 3: Polynomials", "Unit: Exponents", "## Unit 2 — Radicals" ... group 1 is the
# real Khan unit number (kept, not discarded, so "Unit 2: …" stays Unit 2 even when
# an earlier unit is finished); group 2 is the name.
_UNIT_LINE_RE = re.compile(r"^\s*#{0,6}\s*unit\b[ \t]*(\d*)[ \t]*[:\-.—]?[ \t]*(.*)$", re.I)
# "Lesson: Repeating decimals" -- Khan's grouping *inside* a unit. Each becomes
# one card; the video/exercise lines under it become that card's checklist.
_LESSON_LINE_RE = re.compile(r"^\s*#{0,6}\s*lesson\b[ \t]*\d*[ \t]*[:\-.]?[ \t]*(.*)$", re.I)
# A markdown header that isn't a "Unit" line -> also a unit boundary.
_MD_HEADER_RE = re.compile(r"^\s*#{1,6}[ \t]+(.+)$")
# A leading bullet or numbering on a lesson line, stripped before storing.
_BULLET_RE = re.compile(r"^\s*(?:[-*•·–—]|\d+[.)])[ \t]+")
# Khan's own cumulative checks -- a "... Quiz · N questions" row or a unit test /
# course challenge. These become CHECKPOINT cards (the graded points where his
# real Khan score is recorded), placed after the lessons they cover. Matches
# anywhere in the line (they're prefixed with the unit name).
_KHAN_TEST_LINE_RE = re.compile(r"\bquiz\b[^\n]*·|\bunit\s+test\b|\bcourse\s+challenge\b", re.I)
# Strip a checkpoint line's trailing "- Quiz · N questions" / "- Unit Test · …"
# down to its label ("Numbers and operations: Quiz 1").
_CHECKPOINT_SUFFIX_RE = re.compile(
    r"\s*[-–—]\s*(?:quiz|unit\s+test|course\s+challenge)\b.*$", re.I
)
# Khan course-page chrome to drop -- whole-line matches only, so a real lesson
# that merely contains one of these words (e.g. "Review of exponents") survives.
_NOISE_LINE_RE = re.compile(
    r"^(?:"
    r"quiz(?:[ \t]*\d+)?|"
    r"unit[ \t]*\d*[ \t]*test|"
    r"course challenge|"
    r"practice|learn|review|test|start|continue|up next|see all|skill summary|"
    r"get[ \t]+\d+[ \t]+of[ \t]+\d+.*|"
    r"\d+\s*%.*|"
    r"(?:not started|attempted|familiar|proficient|mastered)\b.*|"
    r"level[ \t]+\d+.*|"
    r"mastery.*"
    r")$",
    re.I,
)


# A trailing "[subject]" tag on a Unit line names where that unit's hours credit,
# e.g. "Unit: Simulation [math]" -- so one paste can spread a cross-disciplinary
# course (Pixar in a Box) across subjects while staying one course.
_UNIT_SUBJECT_RE = re.compile(r"^(.*?)\s*\[([^\]]+)\]\s*$")


def resolve_subject_key(text: str) -> str | None:
    """Turn a free-form subject tag ("math", "Art & Music", "ELA") into a valid
    subject key, or None when it matches nothing. Matches a key directly, a
    KHAN_SUBJECTS label (ignoring emoji/punctuation), or a few common aliases."""
    if not text:
        return None
    raw = text.strip().lower()
    norm = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())
    nt = norm(raw)
    for key, label in KHAN_SUBJECTS:
        if raw == key or nt == norm(key) or nt == norm(label):
            return key
    aliases = {
        "ela": "reading", "english": "reading", "languagearts": "reading",
        "la": "reading", "art": "art_and_music", "artmusic": "art_and_music",
        "music": "art_and_music", "pe": "health", "fitness": "health",
        "pehealth": "health", "cte": "occupational_education",
        "occ": "occupational_education", "occed": "occupational_education",
        "cs": "occupational_education", "socialstudies": "social_studies",
        "grammar": "language",
    }
    return aliases.get(nt)


def parse_course_outline(text: str) -> dict[str, Any]:
    """Parse a pasted Khan course/unit outline into ``{course, units}`` where each
    unit is ``{"unit": name, "entries": [...]}`` and every entry is one card, in
    order. Two kinds of entry:

      * a **lesson** -- ``{"kind": "lesson", "name": str, "items": [str]}`` -- one
        per Khan ``Lesson:``; the video/exercise lines under it become ``items``
        (its checklist). A unit with no ``Lesson:`` markers falls back to the flat
        style: every content line is its own name-only lesson.
      * a **checkpoint** -- ``{"kind": "quiz"|"unit_test", "name": str,
        "covers": [lesson names]}`` -- from Khan's own quizzes and unit test.
        ``covers`` is computed by position: a quiz covers the lessons since the
        previous checkpoint; the unit test covers the whole unit. Checkpoints are
        the graded points where his real Khan score is recorded.

    An optional "Course: ..." line names the course; unit boundaries are "Unit ..."
    lines or markdown ``#`` headers. Other Khan page chrome (Practice, Learn,
    mastery %, ...) is dropped. Empty units are dropped."""
    course = ""
    units: list[dict[str, Any]] = []
    current_unit: dict[str, Any] | None = None
    current_lesson: dict[str, Any] | None = None
    lesson_is_explicit = False  # was the current lesson opened by a "Lesson:" line?

    def _start_unit(name: str, number: str = "") -> None:
        nonlocal current_unit, current_lesson, lesson_is_explicit
        name = name.strip()
        subject = ""
        tag_match = _UNIT_SUBJECT_RE.match(name)
        if tag_match is not None:
            resolved = resolve_subject_key(tag_match.group(2))
            if resolved is not None:
                name = tag_match.group(1).strip()
                subject = resolved
        current_unit = {
            "unit": name or f"Unit {len(units) + 1}", "entries": [], "subject": subject,
            # The real Khan unit number from the paste ("Unit 2: …" -> 2), kept so a
            # finished earlier unit never renumbers the rest. None -> numbered by
            # load order at creation.
            "number": int(number) if str(number).strip().isdigit() else None,
        }
        current_lesson = None
        lesson_is_explicit = False
        units.append(current_unit)

    def _start_lesson(name: str, *, explicit: bool) -> None:
        nonlocal current_lesson, lesson_is_explicit
        if current_unit is None:
            _start_unit(course or "Unit 1")
        current_lesson = {"kind": "lesson", "name": name.strip(), "items": []}
        lesson_is_explicit = explicit
        current_unit["entries"].append(current_lesson)

    def _add_checkpoint(line: str) -> None:
        nonlocal current_lesson, lesson_is_explicit
        if current_unit is None:
            _start_unit(course or "Unit 1")
        low = line.lower()
        kind = "unit_test" if ("unit test" in low or "course challenge" in low) else "quiz"
        label = _CHECKPOINT_SUFFIX_RE.sub("", line).strip() or (
            "Unit test" if kind == "unit_test" else "Quiz"
        )
        current_unit["entries"].append({"kind": kind, "name": label, "covers": []})
        current_lesson = None  # a quiz ends the run of lessons before it
        lesson_is_explicit = False

    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        course_match = _COURSE_LINE_RE.match(line)
        if course_match and not units and not course:
            course = course_match.group(1).strip()
            continue
        stripped = _BULLET_RE.sub("", line).strip()
        if not stripped:
            continue
        if _KHAN_TEST_LINE_RE.search(stripped):
            _add_checkpoint(stripped)
            continue
        if _NOISE_LINE_RE.match(stripped):
            continue  # other Khan page chrome
        unit_match = _UNIT_LINE_RE.match(line)
        if unit_match is not None:
            _start_unit(unit_match.group(2), unit_match.group(1))
            continue
        lesson_match = _LESSON_LINE_RE.match(line)
        if lesson_match is not None:
            name = lesson_match.group(1).strip()
            if name:
                _start_lesson(name, explicit=True)
            continue
        header_match = _MD_HEADER_RE.match(line)
        if header_match is not None:
            _start_unit(header_match.group(1))
            continue
        # A normal content line. Under an explicit "Lesson:" it's a checklist item;
        # otherwise (flat paste) it's its own name-only lesson.
        if current_lesson is not None and lesson_is_explicit:
            current_lesson["items"].append(stripped)
        else:
            _start_lesson(stripped, explicit=False)

    clean_units: list[dict[str, Any]] = []
    for unit in units:
        entries = [
            e for e in unit["entries"]
            if e["kind"] != "lesson" or e["name"] or e["items"]
        ]
        lesson_names = [e["name"] for e in entries if e["kind"] == "lesson"]
        if not lesson_names:
            continue  # a unit with no real lessons (just stray chrome) is dropped
        # Fill each checkpoint's coverage by position.
        since: list[str] = []
        for entry in entries:
            if entry["kind"] == "lesson":
                since.append(entry["name"])
            elif entry["kind"] == "unit_test":
                entry["covers"] = list(lesson_names)
                since = []
            else:  # quiz
                entry["covers"] = list(since)
                since = []
        clean_units.append({
            "unit": unit["unit"], "entries": entries,
            "subject": unit.get("subject", ""), "number": unit.get("number"),
        })
    return {"course": course, "units": clean_units}


def create_course_from_outline(
    db: Any,
    student: dict[str, Any],
    *,
    subject: str,
    text: str,
    minutes: int,
    generate_quiz: bool = False,
    on_progress: Callable[[int, int, str | None], None] | None = None,
) -> dict[str, Any]:
    """Load a whole Khan course from one pasted outline: parse it into units and
    create each unit's ordered cards (via `create_course`). Every unit is its own
    grouping, exactly like loading them one at a time -- this just does the whole
    course in one paste. Returns a summary: the course name, the units created,
    and the total card count."""
    parsed = parse_course_outline(text)
    if not parsed["units"]:
        raise ValueError("Couldn't find any units or lessons in that paste.")
    created: list[dict[str, Any]] = []
    total_units = len(parsed["units"])
    for index, unit in enumerate(parsed["units"]):
        if on_progress is not None:
            on_progress(index, total_units, unit["unit"])
        # A per-unit "[subject]" tag wins; otherwise the whole paste shares the
        # form's default subject. This is what lets one cross-disciplinary course
        # credit different units to different subjects in a single load.
        unit_subject = unit.get("subject") or subject
        if not is_supported_subject(unit_subject):
            unit_subject = subject
        # Keep the real Khan unit number from the paste when it had one; only fall
        # back to load order for an untagged "Unit:" line.
        unit_number = unit.get("number") or (index + 1)
        result = create_course(
            db, student, subject=unit_subject, course=unit["unit"],
            lessons=unit["entries"], minutes=minutes, generate_quiz=generate_quiz,
            course_name=parsed["course"], unit_number=unit_number,
        )
        created.append(
            {"unit": unit["unit"], "subject": unit_subject, "ids": result["created"]}
        )
    if on_progress is not None:
        on_progress(total_units, total_units, None)
    return {
        "course": parsed["course"],
        "units": created,
        "unit_count": len(created),
        "card_count": sum(len(c["ids"]) for c in created),
    }


def assign_course_card(
    db: Any,
    student: dict[str, Any],
    lesson_id: int,
    *,
    day_iso: str,
    generate_quiz: bool = True,
    quiz: list[dict[str, Any]] | None = None,
) -> int:
    """Assign one Khan course card to a day: generate its quiz if it doesn't have
    one yet (and generate_quiz is on), then schedule it (which clears held_back).
    Keeps the numbered title and course tags. Returns the lesson id."""
    lesson = db.get_lesson(lesson_id)
    if lesson is None or (lesson.get("metadata") or {}).get("source") != "khan":
        raise ValueError("That isn't a Khan card.")
    # A checkpoint IS the Khan quiz -- it never gets a Compass auto-quiz, even if
    # quiz generation is on for the batch it's scheduled with.
    is_checkpoint = bool((lesson.get("metadata") or {}).get("khan_checkpoint"))
    payload = lesson["payload"]
    if not payload.get("quiz") and not is_checkpoint:
        if quiz is None and generate_quiz:
            quiz = generate_khan_quiz(student, lesson["subject"], lesson["topic"])
        if quiz:
            payload["quiz"] = quiz
            db.update_lesson_content(lesson_id, payload=payload)
    db.reschedule_lesson(lesson_id, day_iso)  # schedules + clears held_back
    return lesson_id


def _unit_stats(cards: list[dict[str, Any]], today_iso: str) -> dict[str, Any]:
    """Roll one unit's cards up into the tracker's per-unit numbers: progress,
    where the cards sit (scheduled / backlog / overdue), the average approved Khan
    score, and what needs the parent (help flags, scores to approve)."""
    cards = sorted(cards, key=lambda c: (c.get("metadata") or {}).get("khan_part") or 0)
    total = len(cards)
    done = scheduled = backlog = overdue = needs_help = pending_scores = 0
    scores: list[float] = []
    next_card: dict[str, Any] | None = None
    for card in cards:
        meta = card.get("metadata") or {}
        status = card["status"]
        if status == "completed":
            done += 1
        elif status == "skipped":
            pass
        elif meta.get("held_back"):
            backlog += 1
            if next_card is None:
                next_card = {"id": card["id"], "title": card.get("title") or card.get("topic")}
        else:
            scheduled += 1
            planned = str(meta.get("planned_for") or "")[:10]
            if planned and planned < today_iso and status in ("planned", "needs_revision"):
                overdue += 1
        result = meta.get("khan_result") or {}
        if result.get("percent") is not None:
            scores.append(float(result["percent"]))
        if (meta.get("khan_reflection") or {}).get("went") == "need_help" and status in (
            "submitted", "needs_revision"
        ):
            needs_help += 1
        if (meta.get("khan_score_claim") or {}).get("percent") is not None:
            pending_scores += 1
    if done >= total and total:
        status_label = "done"
    elif done == 0 and scheduled == 0 and overdue == 0:
        status_label = "not_started"
    else:
        status_label = "in_progress"
    return {
        "total": total, "done": done, "scheduled": scheduled, "backlog": backlog,
        "overdue": overdue, "needs_help": needs_help, "pending_scores": pending_scores,
        "avg_score": round(sum(scores) / len(scores), 1) if scores else None,
        "scored": len(scores), "next_card": next_card, "status": status_label,
    }


def course_tracker(db: Any, student: dict[str, Any], today: date | None = None) -> list[dict[str, Any]]:
    """A read-only roll-up of every loaded Khan course for the Course Tracker:
    course -> units, each with progress, the average approved Khan score, and what
    needs the parent (help flags, scores to approve) plus the next card to schedule.
    Courses and their units come back in load order (earliest card first). Only
    cards that belong to a loaded unit (with a ``khan_course_id``) are included."""
    today_iso = (today or date.today()).isoformat()
    all_cards = db.list_lessons(student["id"], agent=AGENT_KEY, limit=2000)

    # course name -> {unit course_id -> [cards]}, remembering load order by min id.
    courses: dict[str, dict[str, list[dict[str, Any]]]] = {}
    course_first: dict[str, int] = {}
    unit_first: dict[tuple[str, str], int] = {}
    unit_name: dict[tuple[str, str], str] = {}
    unit_number: dict[tuple[str, str], int] = {}
    for card in all_cards:
        meta = card.get("metadata") or {}
        cid = meta.get("khan_course_id")
        if not cid:
            continue
        # Group by the top-level course name when it's stored; otherwise fall back
        # to the card's subject (every card has one) so courses loaded before the
        # course-name field still group as Math / English / Science, filterable.
        course = (
            meta.get("khan_course_name")
            or (subjects.label(card.get("subject")) if card.get("subject") else None)
            or "Other Khan cards"
        )
        courses.setdefault(course, {}).setdefault(cid, []).append(card)
        i = card["id"]
        course_first[course] = min(course_first.get(course, i), i)
        unit_first[(course, cid)] = min(unit_first.get((course, cid), i), i)
        unit_name.setdefault((course, cid), meta.get("khan_unit") or meta.get("khan_course") or "Unit")
        if meta.get("khan_unit_number"):
            unit_number[(course, cid)] = int(meta["khan_unit_number"])

    out: list[dict[str, Any]] = []
    for course in sorted(courses, key=lambda c: (course_first[c], c)):
        units_out: list[dict[str, Any]] = []
        c_total = c_done = c_help = c_pending = 0
        c_scores: list[float] = []
        # Every unit gets a number so the tracker can always label it "Unit N" --
        # the stored khan_unit_number when there is one, otherwise its 1-based
        # position in load order (courses loaded before that field was captured
        # still read Unit 1, Unit 2, … instead of an unnumbered list).
        for position, cid in enumerate(
            sorted(courses[course], key=lambda u: unit_first[(course, u)])
        ):
            stats = _unit_stats(courses[course][cid], today_iso)
            stats["course_id"] = cid
            stats["unit"] = unit_name[(course, cid)]
            stats["unit_number"] = unit_number.get((course, cid)) or (position + 1)
            stats["subject"] = courses[course][cid][0].get("subject", "")
            units_out.append(stats)
            c_total += stats["total"]; c_done += stats["done"]
            c_help += stats["needs_help"]; c_pending += stats["pending_scores"]
            if stats["avg_score"] is not None:
                c_scores += [stats["avg_score"]] * stats["scored"]
        out.append({
            "course": course, "units": units_out,
            "total": c_total, "done": c_done,
            "needs_help": c_help, "pending_scores": c_pending,
            "avg_score": round(sum(c_scores) / len(c_scores), 1) if c_scores else None,
        })
    return out


def _next_school_day(day: date) -> date:
    """`day` itself if it's a weekday, else the next Monday-Friday."""
    while day.weekday() >= 5:  # 5 = Saturday, 6 = Sunday
        day += timedelta(days=1)
    return day


def project_finish(start_day: date, count: int, per_day: int) -> dict[str, Any]:
    """Where `count` cards would land if scheduled `per_day` per school day from
    `start_day` -- the read-only twin of `schedule_unit`'s day walk, so the tracker
    can show a finish date before anything is committed. Returns
    {"days": k, "last_day": date|None}; count <= 0 gives 0 days and no last day."""
    per_day = max(1, int(per_day))
    count = int(count)
    if count <= 0:
        return {"days": 0, "last_day": None}
    day = _next_school_day(start_day)
    placed = 0
    days_used = 1
    for _ in range(count):
        if placed >= per_day:
            day = _next_school_day(day + timedelta(days=1))
            placed = 0
            days_used += 1
        placed += 1
    return {"days": days_used, "last_day": day}


def last_booked_day(db: Any, student: dict[str, Any]) -> date | None:
    """The latest school day any Khan card is already scheduled for -- the max
    ``planned_for`` across cards that are on the board (planned / needs_revision /
    submitted), ignoring backlog and finished cards. None when nothing is booked."""
    latest: date | None = None
    for card in db.list_lessons(student["id"], agent=AGENT_KEY, limit=2000):
        if card["status"] not in ("planned", "needs_revision", "submitted"):
            continue
        meta = card.get("metadata") or {}
        if meta.get("held_back"):
            continue
        planned = str(meta.get("planned_for") or "")[:10]
        if planned:
            try:
                d = date.fromisoformat(planned)
            except ValueError:
                continue
            if latest is None or d > latest:
                latest = d
    return latest


def next_open_schedule_day(
    db: Any, student: dict[str, Any], today: date | None = None
) -> date:
    """The next school day to schedule into so new units chain *after* whatever is
    already booked, instead of piling onto days that are already full. The school
    day after the last booked Khan day, or today when nothing is booked yet."""
    today = today or date.today()
    last = last_booked_day(db, student)
    base = (last + timedelta(days=1)) if last else today
    return _next_school_day(base)


def rename_unit(
    db: Any,
    student: dict[str, Any],
    course_id: str,
    *,
    name: str | None = None,
    number: int | None = None,
) -> int:
    """Edit a loaded unit's record: set its ``khan_unit`` name and/or its
    ``khan_unit_number`` across EVERY card that shares ``course_id`` (approved cards
    included, so the record stays consistent). Pass ``number`` as a falsy value to
    clear a stored number and fall back to the automatic load-order index. Returns
    how many cards were updated. Name it by topic only -- the tracker/backlog add
    the "Unit N:" prefix themselves, so storing "Unit 1 Critical thinking" is what
    produces a doubled "Unit 1: Unit 1 Critical thinking"."""
    updated = 0
    for card in db.list_lessons(student["id"], agent=AGENT_KEY, limit=2000):
        meta = card.get("metadata") or {}
        if meta.get("khan_course_id") != course_id:
            continue
        new_meta = dict(meta)
        if name is not None:
            new_meta["khan_unit"] = name
        if number is not None:
            if number:
                new_meta["khan_unit_number"] = int(number)
            else:
                new_meta.pop("khan_unit_number", None)
        # Rebuild the card's "Course · Subject · Unit N: name" reference line from
        # the updated metadata whenever the name or number changed.
        payload = None
        if name is not None or number is not None:
            payload = dict(card.get("payload") or {})
            if payload.get("overview"):
                ref = khan_reference_line(
                    new_meta.get("khan_course_name", ""),
                    new_meta.get("khan_unit") or "",
                    card.get("subject", ""),
                    new_meta.get("khan_unit_number"),
                )
                payload["overview"] = _overview_with_reference(payload["overview"], ref)
        db.update_lesson_content(card["id"], metadata=new_meta, payload=payload)
        updated += 1
    return updated


def recredit_unit(db: Any, student: dict[str, Any], course_id: str, subject: str) -> int:
    """Change which subject a loaded unit's hours credit toward -- updates every
    card in the unit (all sharing ``course_id``): its ``subject`` column (what the
    gradebook and tracker group by) and its payload ``subject_credits`` (what the
    hours actually post to when the card is approved). Minutes are kept. Returns how
    many cards were updated. Raises ValueError for an unknown subject."""
    if not is_supported_subject(subject):
        raise ValueError(f"'{subject}' isn't a valid subject for a Khan card.")
    label = subjects.label(subject)
    updated = 0
    for card in db.list_lessons(student["id"], agent=AGENT_KEY, limit=2000):
        meta = card.get("metadata") or {}
        if meta.get("khan_course_id") != course_id:
            continue
        payload = dict(card.get("payload") or {})
        existing = payload.get("subject_credits") or []
        minutes = (
            existing[0].get("minutes")
            if existing else payload.get("estimated_minutes")
        ) or 0
        unit = card.get("topic") or card.get("title") or "this skill"
        payload["subject_credits"] = [{
            "subject": subject,
            "minutes": minutes,
            "justification": (
                f"Completed the assigned Khan Academy skill '{unit}' for {label}."
            ),
        }]
        # Keep the card's "Course · Subject · Unit" reference line current.
        if payload.get("overview"):
            ref = khan_reference_line(
                meta.get("khan_course_name", ""), meta.get("khan_unit") or unit, subject,
                meta.get("khan_unit_number"),
            )
            payload["overview"] = _overview_with_reference(payload["overview"], ref)
        db.update_lesson_content(card["id"], subject=subject, payload=payload)
        updated += 1
    return updated


def delete_unit(db: Any, student: dict[str, Any], course_id: str) -> int:
    """Delete every card in a loaded unit (all cards sharing ``course_id``) -- the
    one-click 'remove this whole unit' a parent needs when a load split or
    duplicated a unit. Hours already logged survive the delete
    (``activities.lesson_id`` is ``ON DELETE SET NULL``), and the remaining units
    renumber themselves by load order. Returns how many cards were deleted."""
    cards = [
        card
        for card in db.list_lessons(student["id"], agent=AGENT_KEY, limit=2000)
        if (card.get("metadata") or {}).get("khan_course_id") == course_id
    ]
    for card in cards:
        db.delete_lesson(card["id"])
    return len(cards)


def schedule_unit(
    db: Any,
    student: dict[str, Any],
    course_id: str,
    *,
    start_day: date,
    per_day: int,
    generate_quiz: bool = False,
) -> dict[str, Any]:
    """Lay a unit's remaining lessons onto the calendar, `per_day` per school day
    (Mon-Fri), in lesson order, starting on `start_day`. One action instead of
    assigning each card by hand. Skips weekends and cards already done/skipped.
    Returns {"scheduled": n, "last_day": date, "days": k}."""
    per_day = max(1, int(per_day))
    cards = [
        card
        for card in db.list_lessons(student["id"], agent="khan", limit=500)
        if (card.get("metadata") or {}).get("khan_course_id") == course_id
        and card["status"] not in ("completed", "skipped")
    ]
    cards.sort(key=lambda c: (c.get("metadata") or {}).get("khan_part") or 0)
    if not cards:
        raise ValueError("This unit has no lessons left to schedule.")

    day = _next_school_day(start_day)
    placed_today = 0
    days_used = 1
    for card in cards:
        if placed_today >= per_day:
            day = _next_school_day(day + timedelta(days=1))
            placed_today = 0
            days_used += 1
        assign_course_card(db, student, card["id"], day_iso=day.isoformat(), generate_quiz=generate_quiz)
        placed_today += 1
    return {"scheduled": len(cards), "last_day": day, "days": days_used}


def schedule_all_units(
    db: Any,
    student: dict[str, Any],
    *,
    start_day: date,
    per_day: int,
    generate_quiz: bool = False,
) -> dict[str, Any]:
    """Lay EVERY loaded unit's remaining lessons onto the calendar back-to-back,
    `per_day` per school day, in unit-then-lesson order (oldest unit first) --
    the 'book the whole load' action. One continuous day cursor flows across
    units, so day 1 fills before day 2. Returns
    {"scheduled": n, "units": u, "last_day": date, "days": k}."""
    per_day = max(1, int(per_day))
    summaries = course_summaries(db, student["id"])  # newest unit first
    ordered_cards: list[dict[str, Any]] = []
    for unit in reversed(summaries):  # oldest unit first, so it takes the early days
        cards = [c for c in unit["cards"] if c["status"] not in ("completed", "skipped")]
        cards.sort(key=lambda c: (c.get("metadata") or {}).get("khan_part") or 0)
        ordered_cards.extend(cards)
    if not ordered_cards:
        raise ValueError("No Khan lessons left to schedule.")

    day = _next_school_day(start_day)
    placed_today = 0
    days_used = 1
    for card in ordered_cards:
        if placed_today >= per_day:
            day = _next_school_day(day + timedelta(days=1))
            placed_today = 0
            days_used += 1
        assign_course_card(db, student, card["id"], day_iso=day.isoformat(), generate_quiz=generate_quiz)
        placed_today += 1
    return {
        "scheduled": len(ordered_cards),
        "units": len(summaries),
        "last_day": day,
        "days": days_used,
    }


def clearable_cards(db: Any, student: dict[str, Any]) -> list[dict[str, Any]]:
    """Khan cards that AREN'T in the official record -- everything except approved
    (``completed``) ones: board cards (planned / submitted / needs_revision),
    backlog cards (held_back), and any leftover skipped ones. The exact set a
    'clean slate before reloading courses' should remove."""
    return [
        card
        for card in db.list_lessons(student["id"], agent=AGENT_KEY, limit=2000)
        if card["status"] != "completed"
    ]


def clear_unfinished_cards(db: Any, student: dict[str, Any]) -> int:
    """Delete every Khan card that isn't approved/completed -- a clean slate to
    reload courses. Completed cards (the official record) are left untouched, and
    any hours already logged survive (``activities.lesson_id`` is ``ON DELETE SET
    NULL``, so the hours keep their credit, they just lose the back-link to a
    now-deleted card). Returns how many cards were deleted."""
    cards = clearable_cards(db, student)
    for card in cards:
        db.delete_lesson(card["id"])
    return len(cards)


def clear_all_cards(db: Any, student: dict[str, Any]) -> int:
    """Delete EVERY Khan card, approved ones included -- the full reset before
    loading a first real course, so even "Your Khan units" comes back empty. Any
    hours already logged survive the delete (``activities.lesson_id`` is ``ON
    DELETE SET NULL``), so the school-year hours record is kept even though the
    cards themselves are gone. Returns how many cards were deleted."""
    cards = db.list_lessons(student["id"], agent=AGENT_KEY, limit=2000)
    for card in cards:
        db.delete_lesson(card["id"])
    return len(cards)


def course_summaries(db: Any, student_id: int) -> list[dict[str, Any]]:
    """A student's Khan courses, grouped by course id with progress -- the data
    behind the Backlog course manager. Newest course first. Each carries the
    course name/subject/total, its cards in order, how many are done, and the
    still-unassigned ones (parked in the Backlog), lowest part first."""
    cards = db.list_lessons(student_id, agent=AGENT_KEY, limit=1000)
    by_course: dict[str, list[dict[str, Any]]] = {}
    for card in cards:
        cid = (card.get("metadata") or {}).get("khan_course_id")
        if cid:
            by_course.setdefault(cid, []).append(card)

    summaries: list[dict[str, Any]] = []
    for cid, group in by_course.items():
        group.sort(key=lambda c: (c.get("metadata") or {}).get("khan_part") or 0)
        meta0 = group[0].get("metadata") or {}
        done = [c for c in group if c["status"] == "completed"]
        unassigned = [c for c in group if (c.get("metadata") or {}).get("held_back")]
        summaries.append({
            "course_id": cid,
            "course": meta0.get("khan_unit") or meta0.get("khan_course") or "Course",
            "subject": group[0]["subject"],
            "total": meta0.get("khan_course_total") or len(group),
            "cards": group,
            "done": len(done),
            "unassigned": len(unassigned),
            "next_unassigned": unassigned[0] if unassigned else None,
        })
    summaries.sort(key=lambda s: max(c["id"] for c in s["cards"]), reverse=True)
    return summaries
