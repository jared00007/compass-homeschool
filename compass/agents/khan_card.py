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


_BULLET = re.compile(r"^\s*(?:[-*•·▪◦–—]|\d{1,3}[.)])\s+")


def parse_units(text: str) -> list[str]:
    """Split a pasted block into clean unit names -- one per line, blanks dropped,
    and a leading bullet or number ('- ', '1. ', '• ') trimmed so a list copied
    off a Khan course page comes in as tidy titles."""
    units: list[str] = []
    for line in (text or "").splitlines():
        cleaned = _BULLET.sub("", line).strip()
        if cleaned:
            units.append(cleaned)
    return units


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


def build_khan_card_payload(
    subject_key: str,
    unit: str,
    url: str,
    minutes: int,
    *,
    quiz: list[dict[str, Any]] | None = None,
    note: str = "",
) -> dict[str, Any]:
    """The ordinary-lesson payload for a Khan card -- pure, no model call, so the
    shape is unit-testable on its own. Renders through render_lesson + render_quiz
    exactly like any other lesson."""
    credit_subject = subject_key
    subject_label = subjects.label(credit_subject)
    unit = unit.strip()
    url = url.strip()
    quiz = list(quiz or [])
    # Lift any usage the quiz carried up to a top-level `_usage`, where the cost
    # report already looks, and off the question the student sees.
    usage = quiz[0].pop("_usage", None) if quiz else None

    # The simplest possible card: the Khan link + the quiz, nothing to type. He
    # opens the link, does the skill on Khan, takes the quiz, and turns it in;
    # the quiz is what scores it. No graded activity, so the parent's review is
    # one tap (see review._render_khan_review).
    overview = (
        f"Do this one on Khan Academy:\n\n"
        f"▶️ **[Open in Khan Academy]({url})**\n\n"
        f"Work the skill all the way through over there, then come back and take "
        f"the quick quiz below to lock it in and turn it in."
    )
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
) -> int:
    """Create one Khan card, schedule it, and return its lesson id.

    `subject` is the WA subject the card's hours credit (any of `KHAN_SUBJECTS`).
    `url` defaults to the family's saved Khan link (`khan_base_url`), so the
    parent never re-pastes it per card. Generates the quiz from the unit name
    unless `quiz` is passed in (tests, or a parent who entered their own). Saved
    under the single `khan` agent so every Khan card shares one home (the Khan
    page). Scheduled to `day_iso` if given (via the normal reschedule path, which
    sets planned_for + week_start); left in the backlog otherwise.
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


def create_khan_cards(
    db: Any,
    student: dict[str, Any],
    *,
    subject: str,
    units: list[str],
    minutes: int,
    day_iso: str | None = None,
    note: str = "",
    generate_quiz: bool = True,
    on_progress: Callable[[int, int, str | None], None] | None = None,
) -> dict[str, list[Any]]:
    """Create a card for each unit in a pasted list -- the bulk path.

    Resilient: if a card's quiz generation fails (an API hiccup on one of many),
    the card is still created *without* a quiz rather than aborting the whole
    batch, and its name is collected in `quiz_failed` so the parent can retry it.
    `on_progress(done, total, current_unit)` is called before each card so the UI
    can show a progress bar. Returns {"created": [ids], "quiz_failed": [names]}.
    """
    result: dict[str, list[Any]] = {"created": [], "quiz_failed": []}
    total = len(units)
    for index, unit in enumerate(units):
        if on_progress is not None:
            on_progress(index, total, unit)
        try:
            lesson_id = create_khan_card(
                db, student, subject=subject, unit=unit, minutes=minutes,
                day_iso=day_iso, note=note, generate_quiz=generate_quiz,
            )
        except LessonGenerationError:
            # The quiz call failed for this one -- add the card anyway, no quiz,
            # so a single API hiccup doesn't sink the whole import.
            lesson_id = create_khan_card(
                db, student, subject=subject, unit=unit, minutes=minutes,
                day_iso=day_iso, note=note, generate_quiz=False,
            )
            result["quiz_failed"].append(unit)
        result["created"].append(lesson_id)
    if on_progress is not None:
        on_progress(total, total, None)
    return result


# --- course shells: load a whole course, fill & assign it out over time --------


def create_course(
    db: Any,
    student: dict[str, Any],
    *,
    subject: str,
    course: str,
    lessons: list[str],
    minutes: int,
    generate_quiz: bool = False,
    on_progress: Callable[[int, int, str | None], None] | None = None,
) -> dict[str, list[Any]]:
    """Load a whole Khan course from an ordered lesson list -- one card per
    lesson, numbered in order ("1. …", "2. …"), all tagged with a shared course
    id and parked in the Backlog to assign out day by day.

    Quizzes are normally generated when a card is *assigned* (assign_course_card),
    so this defaults to no quiz -- pass generate_quiz=True to build them all up
    front. Returns {"created": [ids], "quiz_failed": [names]}."""
    if not is_supported_subject(subject):
        raise ValueError(f"'{subject}' isn't a valid subject for a Khan card.")
    course = course.strip()
    if not course:
        raise ValueError("Name the course.")
    lessons = [lesson.strip() for lesson in lessons if lesson.strip()]
    if not lessons:
        raise ValueError("Enter at least one lesson (one per line).")
    lessons = lessons[:100]  # a sane cap so a paste-gone-wrong can't create thousands
    url = khan_base_url(db)
    course_id = f"khancourse-{uuid4().hex[:8]}"
    total = len(lessons)
    result: dict[str, list[Any]] = {"created": [], "quiz_failed": []}
    for index, lesson in enumerate(lessons, start=1):
        if on_progress is not None:
            on_progress(index - 1, total, lesson)
        quiz = None
        if generate_quiz:
            try:
                quiz = generate_khan_quiz(student, subject, lesson)
            except LessonGenerationError:
                result["quiz_failed"].append(lesson)
        payload = build_khan_card_payload(subject, lesson, url, minutes, quiz=quiz)
        payload["title"] = f"{index}. {lesson}"  # numbered so the order reads at a glance
        lesson_id = db.save_lesson(
            student_id=student["id"], agent=AGENT_KEY, subject=subject,
            topic=lesson, title=f"{index}. {lesson}",
            payload=payload, strategy="parent_khan_course",
            rationale="Parent loaded a Khan course as an ordered lesson list.",
            metadata={
                "source": "khan", "resource_url": url,
                "khan_course": course, "khan_course_id": course_id,
                "khan_part": index, "khan_course_total": total, "held_back": True,
            },
        )
        result["created"].append(lesson_id)
    if on_progress is not None:
        on_progress(total, total, None)
    return result


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
    payload = lesson["payload"]
    if not payload.get("quiz"):
        if quiz is None and generate_quiz:
            quiz = generate_khan_quiz(student, lesson["subject"], lesson["topic"])
        if quiz:
            payload["quiz"] = quiz
            db.update_lesson_content(lesson_id, payload=payload)
    db.reschedule_lesson(lesson_id, day_iso)  # schedules + clears held_back
    return lesson_id


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
            "course": meta0.get("khan_course", "Course"),
            "subject": group[0]["subject"],
            "total": meta0.get("khan_course_total") or len(group),
            "cards": group,
            "done": len(done),
            "unassigned": len(unassigned),
            "next_unassigned": unassigned[0] if unassigned else None,
        })
    summaries.sort(key=lambda s: max(c["id"] for c in s["cards"]), reverse=True)
    return summaries
