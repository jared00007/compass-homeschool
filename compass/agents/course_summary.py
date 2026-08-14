"""AI-drafted course description, goals/objectives, and outline -- the three
free-text fields Sumner-Bonney Lake's grades 6-12 packet asks a parent to
write for every course. A parent can still type these by hand; this is an
optional draft to start from and can always be edited or regenerated.

Two moments this gets used, both a single on-demand model call rather than
anything automatic: once, optionally, when a course is first created
(subject and grade alone, before anything's tagged) and again, any time
later, as a "regenerate from what's actually been taught" refresh once real
lessons are tagged to the course. Never triggered by lesson generation
itself -- a course often doesn't exist yet when the first lesson of the year
is written, and firing a model call on every single lesson would be wasteful
for something that only needs to change a handful of times a year, and would
risk silently overwriting a parent's own edits.

Saved to the `lessons` table like every other model call, under its own
agent key, purely so the Costs page counts it -- a parent who can't see the
price of a call is a parent who gets surprised by it in April, the same
reasoning `life_skills.py` states for its own plans. It is deliberately
excluded from Home's student-facing "Ready for you" list the same way a
life-skills plan is: this is parent paperwork, not something to hand him.
"""

from __future__ import annotations

from typing import Any

from compass import config, subjects
from compass.agents.llm import _object, generate_lesson

AGENT_KEY = "course_summary"

SUMMARY_SCHEMA = _object(
    {
        "description": {
            "type": "string",
            "description": (
                "2-4 sentences a school district reviewer would read first: what this "
                "course covers and why it counts as this subject."
            ),
        },
        "goals": {
            "type": "string",
            "description": (
                "The course's goals and objectives, as flowing sentences -- not a "
                "bulleted list, since this is printed as one plain paragraph."
            ),
        },
        "outline": {
            "type": "string",
            "description": (
                "The scope and sequence -- the units or themes the course moves "
                "through, in order, as flowing sentences, not a bulleted list."
            ),
        },
    }
)

SYSTEM_PROMPT = """\
You write course documentation for Compass, a family's homeschool app. This \
specific document is formal: it is submitted to a public school district \
(Sumner-Bonney Lake) as part of the paperwork that lets a homeschool course \
count for credit toward a diploma. Write the way a real syllabus reads -- \
plain, concrete, and confident, not promotional and not childish.

## The course
- Title: {title}
- Subject: {subject}
- Grade level: {grade}
- Credit value: {credit_value:g} credit ({target_hours:g} instructional hours)

{coverage_section}
## What to write
- `description`: what a district reviewer reads first. Say what the course is and \
why it satisfies the {subject} requirement, in plain terms.
- `goals`: the goals and objectives a student should be able to demonstrate by the \
end of the course.
- `outline`: the scope and sequence -- units or themes, in a sensible order.

All three are single paragraphs of flowing prose, not bulleted lists -- they are \
printed as plain paragraphs in the final document.
"""

NO_COVERAGE_SECTION = (
    "Nothing has been taught under this course yet -- write a plan for a full "
    "{credit_value:g}-credit {subject} course at this grade level, the way you would "
    "design one before the year starts.\n"
)

COVERAGE_SECTION_HEADER = (
    "## What's actually been taught so far\n"
    "Base `description`, `goals`, and `outline` on this real coverage -- extend it "
    "to a sensible full course rather than only restating what's listed, but do "
    "not invent specific lessons that contradict it.\n"
)


def _coverage_section(course: dict[str, Any], taught: list[dict[str, Any]]) -> str:
    if not taught:
        return NO_COVERAGE_SECTION.format(
            credit_value=course.get("credit_value") or 1.0,
            subject=subjects.label(course["credit_subject"]),
        )
    lines = [COVERAGE_SECTION_HEADER]
    for item in taught:
        objectives = "; ".join(item.get("objectives") or []) or "no objectives recorded"
        lines.append(f"- {item['title']} -- {objectives}")
    return "\n".join(lines) + "\n\n"


def generate_course_summary(
    db: Any, student: dict[str, Any], course: dict[str, Any], taught: list[dict[str, Any]]
) -> dict[str, str]:
    """Draft `{description, goals, outline}` for one course, and log the call
    to the `lessons` table for cost tracking.

    `taught` is a list of `{"title": ..., "objectives": [...]}` for whatever's
    already tagged to the course -- pass `[]` for a brand-new course with
    nothing tagged yet, which still produces a reasonable initial draft from
    subject and grade level alone.
    """
    target_hours = config.CREDIT_HOURS_PER_UNIT * (course.get("credit_value") or 1.0)
    system = SYSTEM_PROMPT.format(
        title=course["title"],
        subject=subjects.label(course["credit_subject"]),
        grade=course.get("grade_level") or "8",
        credit_value=course.get("credit_value") or 1.0,
        target_hours=target_hours,
        coverage_section=_coverage_section(course, taught),
    )
    payload = generate_lesson(
        system=system,
        user_prompt="Write the course documentation now. Return the structured fields only.",
        schema=SUMMARY_SCHEMA,
        effort=config.DEFAULT_EFFORT,
    )
    summary = {
        "description": payload.get("description", ""),
        "goals": payload.get("goals", ""),
        "outline": payload.get("outline", ""),
    }
    db.save_lesson(
        student_id=student["id"],
        agent=AGENT_KEY,
        subject=course["credit_subject"],
        topic=course["title"],
        title=f"Course documentation — {course['title']}",
        payload=payload,
        strategy="parent_requested",
        rationale="The parent asked for a drafted course description, goals, and outline.",
    )
    return summary
