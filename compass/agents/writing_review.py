"""A read of one writing response against the prompt it was answering.

The mechanical checks in `compass/writing_checks.py` are pure pattern
matching -- they count words and look for quotation marks, and would
happily pass a padded 200 words that answers nothing. This is the part
that needs judgment: did he actually address what was asked, and is what
he wrote true?

Deliberately advisory. It never approves, never blocks a submission, and
never edits his work -- the parent remains the only one who can accept an
assignment. Two guardrails, both real:

- **One call per activity, ever.** Stored on the lesson the first time and
  never regenerated. Without this a student who doesn't want to write can
  iterate against the reviewer instead of thinking, which is the opposite
  of the point.
- **Written to be read by a 13-year-old who avoids writing.** Names what
  works before what doesn't, and hands back at most two concrete next
  moves rather than an exhaustive list of everything wrong. The parent's
  own view of the same stored result carries the fuller diagnostic.

Runs on `config.REVIEW_MODEL` (Haiku), not the frontier model the lesson
agents use -- see that constant for why.
"""

from __future__ import annotations

from typing import Any

from compass import config
from compass.agents.llm import _object, generate_lesson

AGENT_KEY = "writing_review"

REVIEW_SCHEMA = _object(
    {
        "strengths": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "One or two specific things this response genuinely does well, quoting "
                "or naming the actual part you mean. Never generic praise ('good job'), "
                "and never invented -- if the response is thin, say something small but "
                "true rather than something encouraging but false. May be empty only if "
                "there is honestly nothing."
            ),
        },
        "missing": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Each part the prompt explicitly required that the response has not "
                "addressed yet, one per entry, naming the requirement. Empty if every "
                "required part is covered."
            ),
        },
        "concerns": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Statements that are factually wrong, or reasoning that does not hold "
                "up -- a science claim that inverts what actually happens, a conclusion "
                "the evidence given does not support. State the correction plainly. "
                "Empty if nothing is wrong. Do not list style or spelling here."
            ),
        },
        "next_moves": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "At most TWO concrete next steps, written directly to the student in "
                "second person ('Go back to your third sentence and...'). Pick the two "
                "that would most improve the response; leave the rest out even if more "
                "could be said. Never write the sentence for him -- say what to do, not "
                "what to type. Empty only if the response fully meets the assignment."
            ),
        },
    }
)

SYSTEM_PROMPT = """\
You are reviewing one piece of writing by a 13-year-old homeschool student in \
8th grade, against the assignment he was given.

Important context about this student: he tends to write a fast first draft and \
call it done, and he gets discouraged and avoids writing when it feels like \
nothing he does is right. Your job is to get him to go back in and revise -- \
not to grade him, and not to make him feel bad. A review he shuts down over is \
worse than no review.

So:
- Lead with what actually works, and be specific about it. Name the sentence or \
the move you mean. Generic praise reads as fake and he will ignore the rest.
- Then name what the assignment asked for that he has not done yet. Be concrete \
and neutral -- "the prompt asks you to name a group who was left out, and you \
haven't yet" -- never scolding.
- Flag anything factually wrong or reasoning that doesn't hold up, and say what \
is actually true. This matters more than style: a confident wrong statement \
should not survive review.
- Hand back at most TWO next moves. If there are five things wrong, pick the two \
that matter most. A wall of corrections is the thing that makes him quit.
- Never rewrite his sentences for him and never supply the content he was asked \
to produce. Say what to do; let him do it.
- Ignore spelling and capitalization entirely. Those are not what this is for.

Judge only against what the assignment actually asked for. Do not invent \
requirements it did not state.
"""


def _user_prompt(
    lesson_title: str, activity: dict[str, Any], rubric: str, response: str
) -> str:
    parts = [
        f"Lesson: {lesson_title}",
        f"Activity: {activity.get('title', 'Writing')}",
        "",
        "THE ASSIGNMENT HE WAS GIVEN:",
        activity.get("instructions", ""),
    ]
    # The lesson's own `assessment.mastery_criteria` is the rubric a parent
    # would have marked this against -- already written per lesson, and never
    # shown to the student. Passing it here is what lets the review judge
    # "did this meet the bar" rather than guessing at one.
    if rubric:
        parts += ["", "WHAT COUNTS AS MEETING THE BAR (he has not seen this):", rubric]
    parts += ["", "WHAT HE WROTE:", response]
    return "\n".join(parts)


def review_writing(
    db: Any,
    student: dict[str, Any],
    lesson: dict[str, Any],
    activity_index: int,
    response: str,
) -> dict[str, Any]:
    """Review one writing response and store the result on the lesson.

    Returns the stored review. Callers are responsible for not calling this
    twice for the same activity -- see `existing_review`, which the UI uses
    to hide the button once one exists.
    """
    payload_lesson = lesson["payload"]
    activities = payload_lesson.get("activities") or []
    activity = activities[activity_index] if activity_index < len(activities) else {}
    rubric = (payload_lesson.get("assessment") or {}).get("mastery_criteria", "")

    payload = generate_lesson(
        system=SYSTEM_PROMPT,
        user_prompt=_user_prompt(
            payload_lesson.get("title", ""), activity, rubric, response
        ),
        schema=REVIEW_SCHEMA,
        model=config.REVIEW_MODEL,
        effort=config.EFFORT_MEDIUM,
    )

    review = {
        "strengths": payload.get("strengths") or [],
        "missing": payload.get("missing") or [],
        "concerns": payload.get("concerns") or [],
        "next_moves": payload.get("next_moves") or [],
    }
    db.save_writing_ai_review(lesson["id"], activity_index, review)

    # A row of its own purely so the Costs page counts this against its own
    # agent key, same as book_summary/course_summary. Marked completed
    # immediately: it is bookkeeping, not something anyone has to action, and
    # every "what's still open" list in the app keys off status == planned.
    bookkeeping_id = db.save_lesson(
        student_id=student["id"],
        agent=AGENT_KEY,
        subject=lesson["subject"],
        topic=payload_lesson.get("title", ""),
        title=f"Writing review — {activity.get('title', 'Writing')}",
        payload=payload,
        strategy="student_requested",
        rationale="Automated read of a writing response against its own prompt.",
    )
    db.set_lesson_status(bookkeeping_id, "completed")
    return review


def existing_review(lesson: dict[str, Any], activity_index: int) -> dict[str, Any] | None:
    """The stored review for this activity, if one has already been run.

    The one-and-done gate: the UI shows the button only when this is None.
    """
    reviews = (lesson.get("metadata") or {}).get("writing_ai_review") or {}
    return reviews.get(str(activity_index))
