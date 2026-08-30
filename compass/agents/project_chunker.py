"""AI-drafted step-by-step plan for a Big Project -- turns a parent's title
and vision into an ordered list of small, doable steps, in the same shape
Big Projects' own hand-authored starter catalog already uses (a materials
list, a day-range pace, a subject credit -- see `BIG_PROJECT_CATALOG` in
compass/storage/db.py): agile-sprint style, one step at a time, each small
enough to actually finish in a sitting.

Offered only for a project that doesn't have any steps yet (see
pages/7_Big_Projects.py) -- there's no "regenerate" story here on purpose.
A project already has real progress the moment it has steps at all (a
parent's own edits, a step he's already checked off), and reconciling an
AI rewrite against that safely is a genuinely different, harder feature.
Keeping this one to "only ever fires on a blank project" means there's
nothing to silently overwrite, full stop.

A single on-demand model call, saved to the `lessons` table like every
other one, purely so the Costs page counts it -- same reasoning
course_summary.py gives for its own call. Excluded from Home's
student-facing lists the same way: this is a parent reviewing/drafting a
plan, not something to hand him directly.
"""

from __future__ import annotations

from typing import Any

from compass import config
from compass.agents.llm import _object, generate_lesson
from compass.subjects import SUBJECT_KEYS

AGENT_KEY = "project_chunker"

_STEP_SCHEMA = _object(
    {
        "title": {
            "type": "string",
            "description": "Short, concrete name for this step.",
        },
        "description": {
            "type": "string",
            "description": (
                "What actually happens in this step, written directly to the "
                "student in second person -- concrete and specific, the way a "
                "real how-to guide reads, not generic advice. A short numbered "
                "or bulleted list of what to actually do, then one line naming "
                "an observable bar for 'done' before moving to the next step."
            ),
        },
        "materials": {
            "type": "string",
            "description": "What's needed for this step, briefly. Empty string if genuinely nothing.",
        },
        "credit_subject": {"type": "string", "enum": list(SUBJECT_KEYS)},
        "min_days": {
            "type": "integer",
            "description": "Low end of a relaxed pace for this step, in days.",
        },
        "max_days": {
            "type": "integer",
            "description": "High end of that same pace, in days -- equal to min_days is fine.",
        },
    }
)

PLAN_SCHEMA = _object({"steps": {"type": "array", "items": _STEP_SCHEMA}})

_EXAMPLE_STEP = """\
Step example below, for voice and detail level only -- never reuse its content:

Title: "Pick your story"
Description: "Come up with a short story with a clear beginning, middle, and end. \
Keep it small on purpose -- 4 to 6 scenes is plenty for a first film.

- Think up 2 or 3 different ideas before picking one -- a one-line version of each \
is enough.
- Pick the one that actually excites you most, not the easiest one to think of.
- Say the whole story out loud to a parent, start to finish.

Before you move on: can you tell the whole story in under a minute without stopping \
to think? If not, sit with it another day first."
"""

SYSTEM_PROMPT = """\
You write step-by-step project plans for Compass, a family's homeschool app. A parent \
has a Big Project they want their grade {grade} student to work through independently \
over the course of a school year, in small ordered steps -- agile-sprint style, one \
step at a time, each small enough to actually finish in a single sitting.

## The project
- Title: {title}
- Vision: {vision}

## What "good" looks like
{example}

## What to write
Break this project into somewhere around 6-12 ordered steps -- whatever the project's \
actual scope calls for, not a fixed count. Each step needs a `title`, a `description` \
written directly to the student in the voice and detail level of the example above, \
`materials` (briefly, empty string if nothing), a `credit_subject` (whichever real \
subject this specific step actually earns credit toward -- steps commonly span \
several different subjects across one project), and a relaxed `min_days`/`max_days` \
pace -- this is filler for when there's time, never something to rush.

Order matters: assume step N assumes step N-1 is already done. Do not invent \
specifics about the finished product beyond what the vision above already says.
"""


def generate_project_steps(
    db: Any, student: dict[str, Any], project: dict[str, Any]
) -> list[dict[str, Any]]:
    """Draft an ordered list of steps for one Big Project from its title and
    vision alone, and log the call to the `lessons` table for cost tracking.

    Returns a list of dicts shaped exactly like `Database.add_project_step`'s
    own parameters (`title`, `description`, `materials`, `credit_subject`,
    `min_days`, `max_days`) -- the caller inserts each one with that method
    directly, same as a parent adding a step by hand.
    """
    system = SYSTEM_PROMPT.format(
        grade=student.get("grade") or "8",
        title=project["title"],
        vision=project.get("vision") or "Not written yet -- infer a reasonable one from the title.",
        example=_EXAMPLE_STEP,
    )
    payload = generate_lesson(
        system=system,
        user_prompt="Write the step-by-step plan now. Return the structured fields only.",
        schema=PLAN_SCHEMA,
        effort=config.DEFAULT_EFFORT,
    )
    steps = [
        {
            "title": step.get("title", ""),
            "description": step.get("description", ""),
            "materials": step.get("materials", ""),
            "credit_subject": step.get("credit_subject") or "occupational_education",
            "min_days": int(step.get("min_days") or 1),
            "max_days": int(step.get("max_days") or 1),
        }
        for step in (payload.get("steps") or [])
        if step.get("title")
    ]
    db.save_lesson(
        student_id=student["id"],
        agent=AGENT_KEY,
        subject="occupational_education",
        topic=project["title"],
        title=f"Project plan — {project['title']}",
        payload=payload,
        strategy="parent_requested",
        rationale="The parent asked for an AI-drafted step-by-step plan for this project.",
    )
    return steps
