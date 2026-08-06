"""Teaching plans for life skills the parent has already chosen.

This is deliberately not one of the Tier 1 agents, and the difference is the
whole point. Math, Science, English and History each answer a question the parent
genuinely cannot answer off the top of their head — what is he not ready for yet,
which era has he covered least, which vocabulary is due today. Those need state,
so they need an agent.

"Should he learn budgeting or how to change a tire next?" is not that question.
The parent knows their own family, the design brief says don't build this track
agentic by default, and a model picking from a checklist would be a dropdown in a
costume. So nothing here decides *what* comes next.

What is worth a model call is the blank page after you've decided. Turning "change
a tire" into a plan you could actually run on a Saturday — the order, the timing,
what to say, what going wrong looks like, and an honest read on which of the
eleven required subjects it covers — is real work, and it is the part a parent
would otherwise skip and improvise.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from compass import config, subjects
from compass.agents.credits import normalize_credits
from compass.agents.llm import _object, generate_lesson

AGENT_KEY = "life_skills"

# What the planner may add *on its own initiative*, narrower than any Tier 1
# agent's list. Health and occupational education are the two subjects this track
# exists to cover. Math (a real budget, a real measurement), reading (a lease, a
# manual — not a recipe), writing (an email that actually gets sent), language (a
# phone call he has to make himself) and social studies (how taxes, banks and
# contracts work) are the ones that genuinely occur while doing something
# practical.
#
# Science is absent: cooking chemistry is a Science lesson, and letting this
# planner claim it too would quietly double-count hours the Science agent earns.
SECONDARY_CREDIT_SUBJECTS: tuple[str, ...] = (
    "occupational_education",
    "health",
    "math",
    "reading",
    "writing",
    "language",
    "social_studies",
)

DEFAULT_PRIMARY = "occupational_education"


def allowed_credits(skill: dict[str, Any]) -> tuple[str, ...]:
    """Subjects a plan for this skill may credit, the parent's choice first.

    The primary is whatever the parent set on the skill, even if it's outside the
    secondary list — they chose it deliberately, and quietly rebilling their
    "write a polite email" skill as occupational education would be exactly the
    kind of silent wrong answer this track is supposed to avoid. The narrow list
    only bounds what the *model* may add unprompted.
    """
    primary = skill.get("credit_subject")
    if not subjects.is_valid(primary):
        primary = DEFAULT_PRIMARY
    return (primary,) + tuple(s for s in SECONDARY_CREDIT_SUBJECTS if s != primary)


def plan_schema(allowed: tuple[str, ...]) -> dict[str, Any]:
    """The plan shape, with the credit enum narrowed to this skill's subjects."""
    return _object(
        {
            "title": {"type": "string", "description": "Short, concrete name for this session."},
            "overview": {
                "type": "string",
                "description": "Two or three sentences to the parent: what you'll do and why it works.",
            },
            "prep": {
                "type": "string",
                "description": (
                    "What the parent has to arrange before starting — buy something, pick a "
                    "location, set aside cash. Say 'Nothing' if there is genuinely nothing."
                ),
            },
            "materials": {"type": "array", "items": {"type": "string"}},
            "steps": {
                "type": "array",
                "items": _object(
                    {
                        "title": {"type": "string"},
                        "minutes": {"type": "integer"},
                        "what_he_does": {
                            "type": "string",
                            "description": "Written to the student in second person. The hands-on part.",
                        },
                        "what_you_do": {
                            "type": "string",
                            "description": (
                                "Written to the parent: what to demonstrate, hand over, or stay "
                                "quiet through."
                            ),
                        },
                    }
                ),
            },
            "watch_for": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Where this usually goes wrong, including anything genuinely unsafe.",
            },
            "done_looks_like": {
                "type": "string",
                "description": (
                    "The completion bar, observable by a parent standing there — not a feeling "
                    "about whether he got it."
                ),
            },
            "follow_ups": {
                "type": "array",
                "items": {"type": "string"},
                "description": "How to make it stick: the real occasion to hand this to him next.",
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
You write teaching plans for core life skills inside Compass, the family's \
homeschool app.

## What you are and are not doing
The parent has already decided which skill to teach. That decision is theirs and \
it is final — they know their kid, their week, and their vehicle. **Do not \
propose a different skill, a prerequisite skill, or a "you should really do X \
first."** Your entire job is turning the skill they named into a session they \
could run this Saturday.

## The student
- Name: {student_name}
- Grade: {grade}{age_line}
- Interests he has told us about: {interests}

## What makes a good plan here
- This is a real task done in the real world, alongside the parent. It is not a \
worksheet, a quiz, or a reading assignment. **If your plan could be completed at \
a desk, you have written the wrong plan.**
- He is 13 and capable. The parent demonstrates once, then hands it over and lets \
him do it badly the first time. Say where they should stay quiet.
- Be specific to the actual task: real tools, real amounts, real numbers. "Discuss \
budgeting" is not a step. "Give him the $60 grocery list and the calculator, and \
don't correct him until checkout" is.
- Say plainly where it can genuinely hurt someone — a jack, a hot pan, a knife — \
and where it merely gets messy. Do not pad every step with a safety warning; that \
teaches him to ignore all of them.
- The family roadschools, so favour plans that work in or around wherever they \
are parked, and don't assume a garage or a full kitchen.

## Washington state compliance
Washington requires instruction across eleven subjects and 1,000 hours a year. \
This track is where the family's Health and Occupational Education coverage \
genuinely comes from, and the `subject_credits` you return go straight into their \
compliance record — not a guess, and something they may have to defend.

- Always credit the primary subject: {primary_subject}.
- You may additionally credit any of: {allowed_secondary}.

**The test for a secondary credit:** point to a numbered step whose *purpose* is \
that subject and which produces something you could hand to an evaluator. \
Comparing unit prices across four brands and writing down the winner earns math. \
Reading a rental agreement and marking the clauses that cost money earns reading. \
A recipe does not earn reading. Talking about money does not earn math.

**How many minutes to claim.** The primary subject gets the full session length, \
because the whole session is that subject. A secondary subject gets the minutes \
of the *step* that earns it — not the whole session. Steps live inside the \
session, so **the secondary minutes added together must not exceed the session's \
total length.** If that forces you to choose, choose: two well-earned credits beat \
five thin ones. An over-credited hour is a compliance problem, not a win.

## Format
- `what_he_does` is written to the student in second person. `what_you_do`, \
`overview`, `prep`, and `watch_for` are written to the parent.
- Target roughly {minutes} minutes total. Match `estimated_minutes` to the sum of \
your step minutes.
"""


@dataclass
class LifeSkillPlan:
    # `lesson_id` rather than `plan_id`: it is a row in the `lessons` table, and
    # naming it honestly lets it share the parent's logging form.
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
    student: dict[str, Any], allowed: tuple[str, ...], minutes: int
) -> str:
    primary, *allowed_secondary = allowed
    age = student.get("age")
    return SYSTEM_PROMPT.format(
        student_name=student.get("name") or "the student",
        grade=student.get("grade") or "8",
        age_line=f"\n- Age: {age}" if age else "",
        interests=student.get("interests") or "none recorded yet",
        primary_subject=subjects.label(primary),
        allowed_secondary=", ".join(subjects.label(s) for s in allowed_secondary),
        minutes=minutes,
    )


def build_user_prompt(skill: dict[str, Any], minutes: int, parent_note: str, location: str) -> str:
    lines = [
        f"Teach this life skill: **{skill['title']}**",
        f"Category: {skill.get('category') or 'General'}",
    ]
    if skill.get("description"):
        lines.append(f"What the parent says 'done' looks like: {skill['description']}")
    if location:
        lines.append(f"Where the family is right now: {location}")
    if parent_note:
        lines.append(f"The parent adds: {parent_note}")
    lines.append(
        f"\nWrite a plan for roughly {minutes} minutes. Return the structured plan only."
    )
    return "\n".join(lines)


def generate_plan(
    db,
    student: dict[str, Any],
    skill: dict[str, Any],
    *,
    minutes: int,
    parent_note: str = "",
    location: str = "",
    use_web_search: bool = False,
) -> LifeSkillPlan:
    """Write and persist a teaching plan for one parent-chosen life skill.

    Stored in the `lessons` table under the `life_skills` agent so that the cost
    page counts these against the year's spend like anything else that calls the
    model. A plan the parent can't see the price of is a plan they'll be
    surprised by in April.
    """
    allowed = allowed_credits(skill)
    primary = allowed[0]

    payload = generate_lesson(
        system=build_system_prompt(student, allowed, minutes),
        user_prompt=build_user_prompt(skill, minutes, parent_note, location),
        use_web_search=use_web_search,
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
    for key in ("materials", "watch_for", "follow_ups"):
        payload.setdefault(key, [])
    # This plan's schema has no `video` field to check it against, and it has
    # no value once verification would have happened -- drop it rather than
    # persist an unused sidecar key.
    payload.pop("_search_result_urls", None)

    lesson_id = db.save_lesson(
        student_id=student["id"],
        agent=AGENT_KEY,
        subject=primary,
        topic=skill["title"],
        title=payload.get("title") or skill["title"],
        payload=payload,
        strategy="parent_chosen",
        rationale="The parent picked this skill; the model only planned how to teach it.",
        metadata={"life_skill_id": skill["id"], "category": skill.get("category") or ""},
    )
    return LifeSkillPlan(lesson_id=lesson_id, payload=payload, warnings=warnings)
