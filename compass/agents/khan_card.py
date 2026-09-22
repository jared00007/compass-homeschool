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

from typing import Any

from compass import config, subjects
from compass.agents.llm import _object, generate_lesson
from compass.agents.quiz import verify_quiz

# The four core subject pages a Khan card can land on, keyed by the agent key
# Home maps to each subject page -> the real WA subject key its hours credit.
# Mirrors each agent's own `primary_subject` (English teaches, and credits,
# reading), so a card's credit matches how that subject is counted everywhere
# else. Only these four have a subject page + graded gradebook to slot into.
AGENT_CREDIT_SUBJECT = {
    "math": "math",
    "science": "science",
    "english": "reading",
    "history": "history",
}


def is_supported_subject(agent_key: str) -> bool:
    return agent_key in AGENT_CREDIT_SUBJECT


def default_minutes(agent_key: str) -> int:
    """The form opens at the subject's usual lesson length (Math 35, etc.),
    falling back to the family default -- same source the Plan-a-lesson form uses,
    so a Khan card doesn't feel like a different size of thing."""
    return config.SUBJECT_DEFAULT_MINUTES.get(
        agent_key, int(config.DEFAULT_SETTINGS["default_lesson_minutes"])
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
    student: dict[str, Any], agent_key: str, unit: str, *, note: str = ""
) -> list[dict[str, Any]]:
    """Generate and verify a quiz pool for one Khan skill. The single model call
    a Khan card makes; returns the cleaned list of questions (never raises on a
    few malformed items -- those are dropped, same as any lesson quiz)."""
    subject_label = subjects.label(AGENT_CREDIT_SUBJECT.get(agent_key, agent_key))
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
    agent_key: str,
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
    credit_subject = AGENT_CREDIT_SUBJECT.get(agent_key, agent_key)
    subject_label = subjects.label(credit_subject)
    unit = unit.strip()
    url = url.strip()
    quiz = list(quiz or [])
    # Lift any usage the quiz carried up to a top-level `_usage`, where the cost
    # report already looks, and off the question the student sees.
    usage = quiz[0].pop("_usage", None) if quiz else None

    activity = {
        "title": "Do the Khan skill, then log your score",
        "minutes": minutes,
        "phase": "practice",
        "instructions": (
            f"Head to Khan Academy and work this all the way through:\n\n"
            f"▶️ **[Open in Khan Academy]({url})**\n\n"
            f"When you've finished it there, come back and tell me how it went — "
            f"your mastery level or score, plus one thing that clicked or tripped "
            f"you up. Then take the quiz below."
        ),
        "requires_written_response": True,
        "writing_requirements": {
            "min_words": None,
            "max_words": None,
            "min_sentences": None,
            "requires_quote": False,
        },
        "answer": (
            f"He should report a real Khan Academy result for '{unit}' — a mastery "
            "level, a percent, or 'leveled up' — plus a quick reflection. Approve "
            "once he's actually done the skill on Khan and logged a plausible "
            "result; send it back if the box is empty or he clearly skipped it."
        ),
        "video": {"found": False, "title": "", "url": "", "channel": "", "why": ""},
        "example": "",
        "self_check": "",
        "reading_check": [],
        "checklist": [],
    }

    payload: dict[str, Any] = {
        "title": f"Khan Academy: {unit}",
        "topic": unit,
        "overview": (
            f"This one's on Khan Academy — do the skill there, tell me how it went, "
            f"then take a quick quiz to lock it in."
        ),
        "learning_objectives": [f"Work the Khan Academy skill: {unit}"],
        "learn": {
            "explanation": "",
            "video": {"found": False, "title": "", "url": "", "channel": "", "why": ""},
        },
        "worked_example": {"problem": "", "steps": ""},
        "activities": [activity],
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
            f"Manual Khan Academy card. He does '{unit}' on Khan (link in the "
            f"activity), reports his score, and takes the quiz. Approve & log hours "
            f"once he's done."
        ),
        "branches": [],
    }
    if note.strip():
        payload["overview"] += f"\n\nFrom your parent: {note.strip()}"
    if usage:
        payload["_usage"] = usage
    return payload


def create_khan_card(
    db: Any,
    student: dict[str, Any],
    *,
    agent_key: str,
    unit: str,
    url: str,
    minutes: int,
    day_iso: str | None = None,
    note: str = "",
    quiz: list[dict[str, Any]] | None = None,
    generate_quiz: bool = True,
) -> int:
    """Create one Khan card, schedule it, and return its lesson id.

    Generates the quiz from the unit name unless `quiz` is passed in (tests, or a
    parent who entered their own). Saved under the subject's own agent key so it
    lives alongside that subject's lessons everywhere. Scheduled to `day_iso` if
    given (via the normal reschedule path, which sets planned_for + week_start);
    left in the backlog otherwise, for the parent to place from the Board.
    """
    if not is_supported_subject(agent_key):
        raise ValueError(f"Khan cards aren't supported for '{agent_key}'.")
    if not unit.strip():
        raise ValueError("Give the unit or exercise a name.")
    if not url.strip():
        raise ValueError("Paste the Khan Academy link for this skill.")

    if quiz is None and generate_quiz:
        quiz = generate_khan_quiz(student, agent_key, unit, note=note)

    payload = build_khan_card_payload(
        agent_key, unit, url, minutes, quiz=quiz, note=note
    )
    metadata: dict[str, Any] = {"source": "khan", "resource_url": url.strip()}
    if day_iso is None:
        # No day yet -> park it in the parent's Backlog to schedule from the
        # Board, the same way a generated series lands (held_back).
        metadata["held_back"] = True

    lesson_id = db.save_lesson(
        student_id=student["id"],
        agent=agent_key,
        subject=AGENT_CREDIT_SUBJECT.get(agent_key, agent_key),
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
