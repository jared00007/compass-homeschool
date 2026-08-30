"""Build guides for coding modules the parent has already chosen.

Same reasoning compass.agents.life_skills gives for its own track: *what*
he builds next is the parent's call, not a model's, so nothing here picks a
module. What earns a call is the blank page after that decision -- turning
"build a choose-your-own-adventure text game" into an actual walkthrough
(the concepts he needs, a step-by-step build guide with real code guidance
at each step, and the ways it commonly goes wrong) rather than leaving him
with just the one-line task the catalog gives. That gap was reported
directly: "we need to include the learning resources and content for him
to learn it. There's just do this but [not] know how to do this."

Landon builds this himself at a computer, unlike a life skill a parent runs
alongside him -- so unlike life_skills' own plan (written to the parent),
this one is written directly to him, the same second-person convention
Tier 1 lesson activities already use.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from compass import config, subjects
from compass.agents.credits import normalize_credits
from compass.agents.llm import _object, generate_lesson

AGENT_KEY = "coding"

# Narrower than a Tier 1 agent's list, matching what CODING_MODULE_CATALOG
# itself ever credits -- occupational education for the build itself, math
# for a module that's really about working with real numbers/data, art &
# music for one that's really about visual design.
SECONDARY_CREDIT_SUBJECTS: tuple[str, ...] = (
    "occupational_education",
    "math",
    "art_and_music",
)

DEFAULT_PRIMARY = "occupational_education"


def allowed_credits(module: dict[str, Any]) -> tuple[str, ...]:
    """Subjects a build guide for this module may credit, the parent's
    choice first -- same reasoning life_skills.allowed_credits gives."""
    primary = module.get("credit_subject")
    if not subjects.is_valid(primary):
        primary = DEFAULT_PRIMARY
    return (primary,) + tuple(s for s in SECONDARY_CREDIT_SUBJECTS if s != primary)


def plan_schema(allowed: tuple[str, ...]) -> dict[str, Any]:
    """The build-guide shape, with the credit enum narrowed to this
    module's subjects."""
    return _object(
        {
            "title": {"type": "string", "description": "Short, concrete name for this build."},
            "overview": {
                "type": "string",
                "description": "Two or three sentences: what you'll build, and the core idea it teaches.",
            },
            "concepts": {
                "type": "array",
                "items": _object(
                    {
                        "name": {"type": "string"},
                        "explanation": {
                            "type": "string",
                            "description": (
                                "What this idea actually is, in plain language, before "
                                "the steps below put it to use."
                            ),
                        },
                    }
                ),
                "description": (
                    "The handful of programming ideas this build actually needs, "
                    "explained before he needs them -- the how-to-do-this content "
                    "itself, not just a task list."
                ),
            },
            "steps": {
                "type": "array",
                "items": _object(
                    {
                        "title": {"type": "string"},
                        "minutes": {"type": "integer"},
                        "instructions": {
                            "type": "string",
                            "description": (
                                "Written to him, second person -- what to build in this "
                                "step and why it works, not just what to type."
                            ),
                        },
                        "example": {
                            "type": "string",
                            "description": (
                                "A short, real code snippet demonstrating the technique "
                                "for this step -- not the whole solution, just enough to "
                                "unblock him."
                            ),
                        },
                    }
                ),
            },
            "common_mistakes": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Where this actually goes wrong for a first-timer, and what the "
                    "error or symptom actually looks like."
                ),
            },
            "done_looks_like": {
                "type": "string",
                "description": "The observable finish line -- what running it should actually do.",
            },
            "stretch_goals": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Real ways to extend this once it works, for if he wants to keep going.",
            },
            "parent_note": {
                "type": "string",
                "description": (
                    "Anything worth a parent knowing -- rarely needed, since this is "
                    "self-directed. Say 'Nothing' if there is genuinely nothing."
                ),
            },
            "subject_credits": {
                "type": "array",
                "items": _object(
                    {
                        "subject": {"type": "string", "enum": list(allowed)},
                        "minutes": {"type": "integer"},
                        "justification": {
                            "type": "string",
                            "description": "The specific step that earns this credit.",
                        },
                    }
                ),
            },
            "estimated_minutes": {"type": "integer"},
        }
    )


SYSTEM_PROMPT = """\
You write build guides for coding modules inside Compass, the family's \
homeschool app.

## What you are and are not doing
The parent has already decided which module he's building next. That decision \
is theirs and it is final -- **do not propose a different module, a prerequisite \
module, or a different tech stack than what the module's own materials imply.** \
Your entire job is turning the one-line module description into an actual build \
guide he can follow himself.

## The student
- Name: {student_name}
- Grade: {grade}{age_line}
- Interests he has told us about: {interests}

## What makes a good build guide here
- He builds this himself, at a computer, without a parent walking him through it \
in person -- write directly to him, second person, the same way a Tier 1 \
lesson's activities already do.
- Teach the concept before he needs it, not after. `concepts` comes first for a \
reason: if a step uses a loop, "loops" needs to already be explained above it. \
This is the actual point of the whole guide -- knowing *how* to do this, not \
just being told to do it.
- Each step's `example` is a short, real snippet demonstrating the technique -- \
never the whole solution. The point is unblocking him, not building it for him.
- Be specific to the actual language or tool the module's own materials imply \
(Python, Scratch, plain HTML/CSS/JS, whatever fits) -- don't default to Python if \
the module clearly wants something else.
- List the mistakes a first-timer actually makes here, with what the error or \
symptom actually looks like -- not generic "debug carefully" advice.

## Washington state compliance
Washington requires instruction across eleven subjects and 1,000 hours a year, \
and the `subject_credits` you return go straight into their compliance record -- \
not a guess, and something they may have to defend.

- Always credit the primary subject: {primary_subject}.
- You may additionally credit any of: {allowed_secondary}.
- **The test for a secondary credit:** point to a numbered step whose *purpose* \
is that subject. A step that happens to involve numbers doesn't automatically \
earn math -- computing something and using the real result to drive the program \
does.
- Minutes for a secondary subject come from that step's own minutes, not the \
whole session; added together they must not exceed the total.

## Format
Target roughly {minutes} minutes total. Match `estimated_minutes` to the sum of \
your step minutes.
"""


@dataclass
class CodingPlan:
    # `lesson_id` rather than `plan_id`: it is a row in the `lessons` table,
    # and naming it honestly lets it share the parent's logging form.
    lesson_id: int
    payload: dict[str, Any]
    warnings: list[str] = field(default_factory=list)

    @property
    def credits(self) -> dict[str, int]:
        return {c["subject"]: int(c["minutes"]) for c in self.payload.get("subject_credits", [])}

    @property
    def total_minutes(self) -> int:
        return int(self.payload.get("estimated_minutes") or 0)


def build_system_prompt(
    db: Any, student: dict[str, Any], allowed: tuple[str, ...], minutes: int
) -> str:
    primary, *allowed_secondary = allowed
    age = student.get("age")
    return SYSTEM_PROMPT.format(
        student_name=student.get("name") or "the student",
        grade=student.get("grade") or "8",
        age_line=f"\n- Age: {age}" if age else "",
        interests=db.interests_text(student["id"]) or "none recorded yet",
        primary_subject=subjects.label(primary),
        allowed_secondary=", ".join(subjects.label(s) for s in allowed_secondary),
        minutes=minutes,
    )


def build_user_prompt(module: dict[str, Any], minutes: int) -> str:
    lines = [
        f"Build this coding module: **{module['title']}**",
        f"Category: {module.get('category') or 'General'}",
    ]
    if module.get("description"):
        lines.append(f"What 'done' looks like: {module['description']}")
    if module.get("materials"):
        lines.append(f"Materials/tools: {module['materials']}")
    lines.append(
        f"\nWrite a build guide for roughly {minutes} minutes. Return the structured plan only."
    )
    return "\n".join(lines)


def generate_plan(
    db,
    student: dict[str, Any],
    module: dict[str, Any],
    *,
    minutes: int = 60,
) -> CodingPlan:
    """Write and persist a build guide for one parent-chosen coding module.

    Stored in the `lessons` table under the `coding` agent so that the cost
    page counts these against the year's spend like anything else that
    calls the model.
    """
    allowed = allowed_credits(module)
    primary = allowed[0]

    payload = generate_lesson(
        system=build_system_prompt(db, student, allowed, minutes),
        user_prompt=build_user_prompt(module, minutes),
        use_web_search=False,
        schema=plan_schema(allowed),
        effort=config.DEFAULT_EFFORT,
    )
    warnings = normalize_credits(
        payload,
        primary=primary,
        allowed=allowed,
        fallback_minutes=minutes,
        segments_key="steps",
    )
    for key in ("concepts", "common_mistakes", "stretch_goals"):
        payload.setdefault(key, [])
    # No `video` field in this schema to check it against, and no value in
    # persisting an unused sidecar key.
    payload.pop("_search_result_urls", None)

    lesson_id = db.save_lesson(
        student_id=student["id"],
        agent=AGENT_KEY,
        subject=primary,
        topic=module["title"],
        title=payload.get("title") or module["title"],
        payload=payload,
        strategy="parent_chosen",
        rationale="The parent picked this module; the model only wrote the build guide.",
        metadata={"coding_module_id": module["id"], "category": module.get("category") or ""},
    )
    return CodingPlan(lesson_id=lesson_id, payload=payload, warnings=warnings)
