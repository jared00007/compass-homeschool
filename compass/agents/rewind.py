"""The Rewind agent -- a cumulative "flashback" review over lessons Landon has
already finished.

A parent picks any set of completed Tier 1 lessons (math, science, English,
history) and this draws them back together into one short refresher plus a mixed
auto-graded quiz that crosses all of them -- "do you still know this?" rather
than "here's something new." Same on-demand shape as `course_summary` and
`life_skills`: one parent-triggered model call, never automatic, regenerable any
time, and logged to the `lessons` table under its own agent key so the Costs
page counts it.

The review is stored AS a lesson (agent `rewind`), so Landon takes its quiz
through the same quiz engine every other lesson uses -- but it carries no
`skill_id` and isn't a graded agent, so it never touches Math mastery or the
gradebook. It's a low-stakes recall check. (Parent-approved grading of written
recall is a deliberate v2; v1 is auto-graded multiple choice only.)
"""

from __future__ import annotations

from typing import Any

from compass import config, subjects
from compass.agents.llm import _object, generate_lesson
from compass.agents.quiz import verify_quiz

AGENT_KEY = "rewind"

# Which real WA subject a completed lesson's assessment time credits when it's
# reviewed. The four graded agents; English folds to reading (its agent key
# isn't itself a subject key), the rest map to themselves.
_AGENT_CREDIT_SUBJECT = {
    "math": "math",
    "science": "science",
    "english": "reading",
    "history": "history",
}

# What the parent's selection turns into: a short recap grouped by subject, then
# a cumulative quiz. Shaped like an ordinary lesson (overview + a Learn-style
# refresher + quiz) so it renders through the exact same lesson UI every other
# lesson uses -- it IS a lesson, just a review one.
REWIND_SCHEMA = _object(
    {
        "overview": {
            "type": "string",
            "description": (
                "One or two warm sentences to the student setting up this review -- "
                "that it pulls together things he's already learned across subjects and "
                "this is a chance to show he still remembers them. Written to a "
                "13-year-old, encouraging, not a parent-facing summary."
            ),
        },
        "refresher": {
            "type": "string",
            "description": (
                "A quick refresher he reads before the quiz -- a short markdown recap "
                "grouped by subject. Use a bold subject heading, then one bullet per key "
                "concept (bold the concept name, then a sentence or two jogging his "
                "memory of how it works). Consolidate overlapping ideas across lessons; "
                "this is a memory jog, not a re-teach. Plain, at his reading level."
            ),
        },
        "quiz": {
            "type": "array",
            "description": (
                "A pool of {min}-{max} multiple-choice questions that MIX the selected "
                "subjects and concepts -- a cumulative check that he's retained what he "
                "learned, not a re-run of any single lesson's own quiz. He's asked five "
                "at a time, rotated on each retry, so give it real breadth: spread across "
                "every concept in the recap, at a mix of difficulties, each question "
                "answerable from a genuinely different piece of knowledge."
            ).format(min=config.REWIND_QUIZ_POOL_MIN, max=config.REWIND_QUIZ_POOL_MAX),
            "items": _object(
                {
                    "question": {"type": "string"},
                    "choices": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Exactly four answer choices, one clearly correct and three "
                            "plausible distractors."
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
        },
    }
)

SYSTEM_PROMPT = """\
You build cumulative review "flashbacks" for Compass, a family's homeschool app, \
for a {age}-year-old {grade}th grader named {name}. He has already learned the \
material below in earlier lessons; your job is to pull it back together so he can \
show he still remembers it -- NOT to teach anything new.

Write everything directly to him, at his reading level: plain, specific, and \
encouraging, the way a good tutor warms up a review session. Never mention that a \
model wrote this, and never invent concepts that aren't in the material he's \
actually covered.

Produce three things:
- `overview`: one or two encouraging sentences setting up the review.
- `refresher`: a short markdown recap grouped by subject (a bold subject \
heading, then one bullet per key concept -- bold the concept, then a sentence \
jogging his memory). Consolidate overlapping ideas; a memory jog, not a re-teach.
- `quiz`: a pool of {min}-{max} multiple-choice questions that MIX the subjects \
and concepts together -- a genuine cumulative check. Cover every concept in the \
refresher across a range of difficulty. Each question must be answerable from the \
material below; exactly four choices, one correct.

Two rules that keep it fair:
- **Every quiz question is answerable from a concept named in the refresher \
above it.** Don't quiz a detail you didn't jog. If a question needs a fact, the \
refresher reminds him of it first -- the refresher and the quiz are one piece.
- **Only review what he actually learned** (the material below). Never invent a \
concept, a number, or a definition that isn't in it.

## What {name} has already learned (the material to review)
{material}
"""


def _material_section(selections: list[dict[str, Any]]) -> str:
    """Render the chosen completed lessons into the prompt, grouped by subject
    with each lesson's title, topic, and objectives -- the concept inventory the
    review draws from."""
    by_subject: dict[str, list[dict[str, Any]]] = {}
    for item in selections:
        label = subjects.label(item.get("subject") or item.get("agent") or "")
        by_subject.setdefault(label, []).append(item)

    blocks: list[str] = []
    for label in sorted(by_subject):
        lines = [f"### {label}"]
        for item in by_subject[label]:
            title = item.get("title") or item.get("topic") or "a lesson"
            topic = item.get("topic") or ""
            header = f"- {title}"
            if topic and topic != title:
                header += f" (topic: {topic})"
            lines.append(header)
            for obj in item.get("learning_objectives") or []:
                lines.append(f"    - {obj}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def generate_rewind_review(
    db: Any, student: dict[str, Any], selections: list[dict[str, Any]]
) -> int:
    """Draft one Rewind review over `selections` (completed lessons, each a dict
    from `db.completed_lessons_for_review`), persist it as a `rewind` lesson, and
    return its lesson id. Logged to the `lessons` table for cost tracking, the
    same as every other on-demand agent.

    Raises `ValueError` if nothing was selected -- there's nothing to review.
    """
    if not selections:
        raise ValueError("Pick at least one completed lesson to review.")

    system = SYSTEM_PROMPT.format(
        age=student.get("age") or 13,
        grade=student.get("grade") or "8",
        name=student.get("name") or "the student",
        min=config.REWIND_QUIZ_POOL_MIN,
        max=config.REWIND_QUIZ_POOL_MAX,
        material=_material_section(selections),
    )
    payload = generate_lesson(
        system=system,
        user_prompt=(
            "Build the review now. Return the overview, the refresher, and the "
            "cumulative quiz pool as structured fields only."
        ),
        schema=REWIND_SCHEMA,
        effort=config.DEFAULT_EFFORT,
    )
    # Same guard every lesson quiz gets: drop any malformed/unanswerable question
    # before it can reach him and silently break grading.
    verify_quiz(payload)

    subject_labels = sorted(
        {subjects.label(s.get("subject") or s.get("agent") or "") for s in selections}
    )
    scope = ", ".join(subject_labels) if subject_labels else "several subjects"

    # Shape the model's output into the ordinary lesson payload so it renders
    # through render_lesson + render_quiz exactly like every other lesson: the
    # refresher becomes the "Learn" section, the quiz stays the quiz. Keep _usage
    # for cost tracking.
    payload["title"] = f"Rewind review — {scope}"
    payload["overview"] = payload.get("overview") or ""
    payload["learn"] = {"explanation": payload.pop("refresher", ""), "video": {"found": False}}
    payload["learning_objectives"] = ["Show you still remember what you've learned across subjects"]
    payload["activities"] = []
    # Real WA subject keys the review's assessment time should credit -- a
    # cumulative review spans several, so its sit-time is split across the ones it
    # actually covered rather than pinned to a made-up "review" subject. English
    # folds to reading, the others map to themselves; only valid keys survive.
    def _credit_subject(selection: dict[str, Any]) -> str | None:
        # A core agent maps by its key (English -> reading); a Khan card isn't in
        # that map, so it credits its own real WA subject (math, reading, ...).
        mapped = _AGENT_CREDIT_SUBJECT.get(selection.get("agent") or "")
        if mapped:
            return mapped
        subject = selection.get("subject") or ""
        return subject if subjects.is_valid(subject) else None

    credit_subjects = sorted(
        {c for s in selections if (c := _credit_subject(s))}
    )
    lesson_id = db.save_lesson(
        student_id=student["id"],
        agent=AGENT_KEY,
        subject="review",
        topic="Rewind review",
        title=f"🔁 Rewind — {scope}",
        payload=payload,
        strategy="parent_requested",
        rationale=(
            "The parent pulled together already-completed lessons into a cumulative "
            "recall review."
        ),
        metadata={
            "rewind": True,
            "subject_scope": subject_labels,
            "credit_subjects": credit_subjects,
            "source_lesson_ids": [s["id"] for s in selections if s.get("id") is not None],
        },
    )
    return lesson_id
