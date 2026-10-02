"""Light enrichment tracks -- Art & Music and Movement / PE / Health.

The parts of a real school year that aren't the four academic cores. Each is a
quick, AI-generated activity he just *does* -- make something, move, try a skill
-- with no worked example, no checks, no quiz. One on-demand model call per
activity, costed like every other generator; credited to the WA subject it
covers (art_and_music or health) so it fills the compliance dashboard's thin
subjects and counts as a day's enrichment block.

Kept deliberately lighter than a Tier 1 lesson or a life-skills plan: the whole
point of enrichment is that it's a break from the grind, not more of it.
"""

from __future__ import annotations

from typing import Any

from compass import config, subjects
from compass.agents.llm import _object, generate_lesson

# The agent keys are the track keys in config.ENRICHMENT_TRACKS.
ACTIVITY_SCHEMA = _object(
    {
        "title": {"type": "string", "description": "Short, catchy name for the activity."},
        "overview": {
            "type": "string",
            "description": (
                "One or two sentences to the student: what this is and why it's worth "
                "doing (fun, or good for you). Written to a 13-year-old, upbeat."
            ),
        },
        "what_to_do": {
            "type": "string",
            "description": (
                "The activity itself, written straight to him in second person -- clear "
                "enough to just start. A single, doable thing he can finish in about the "
                "target time, on his own or with minimal setup. No grading, no right "
                "answer; the point is that he does it."
            ),
        },
        "materials": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Anything he needs, mostly stuff already around the house. Empty if none.",
        },
        "estimated_minutes": {"type": "integer"},
    }
)

_TRACK_PROMPTS = {
    "art_music": (
        "You design quick, hands-on ART & MAKING challenges for a homeschooled "
        "{age}-year-old named {name}. This is his creative time -- a break from "
        "academics. Give him ONE thing to MAKE, SKETCH, BUILD, or STORYBOARD: an "
        "invention to draw, a quick comic or storyboard, a paper/cardboard build, a "
        "design challenge, a re-imagining of an everyday object -- finishable in about "
        "{minutes} minutes with stuff around the house. ROUGH IS THE POINT: reward the "
        "idea and the attempt, never a polished, colored, or finely-finished result. No "
        "coloring-book busywork, no 'make it pretty.' Lean on his interests "
        "({interests}) where it fits. No grading, no right answer -- just a cool thing "
        "to make."
    ),
    "movement": (
        "You design quick MOVEMENT / PE / HEALTH activities for a homeschooled "
        "{age}-year-old named {name}. This is his get-up-and-move time -- a break from "
        "sitting, not a lecture. Give him ONE light, active thing to do -- a mini-workout, "
        "a sport skill to practice, a movement challenge, or a simple health habit to try "
        "-- finishable in about {minutes} minutes, safe to do on his own, needing little "
        "or no equipment. Lean on his interests ({interests}) where it fits. No grading, "
        "no quiz -- just get him moving."
    ),
}

SYSTEM_PROMPT = "{track_intro}\n\nReturn the activity as the structured fields only."


def art_card_seed_prompt(seed_skill: str = "") -> str:
    """The editable 'shell' prompt the parent tweaks when making an art card -- a
    starting direction, not the whole system prompt. Seeds off a Pixar in a Box (or
    any art) skill when one is passed, so an art card can ride on what he's doing."""
    if seed_skill.strip():
        return (
            f"A quick art challenge inspired by the Pixar in a Box idea "
            f"“{seed_skill.strip()}” — a sketch, storyboard, design, or build in that "
            f"spirit. Rough is the point: ideas over polish, no coloring or finishing."
        )
    return (
        "A quick MAKE / SKETCH / BUILD challenge — something to draw, invent, build, "
        "or storyboard in about 25 minutes with stuff around the house. Rough is the "
        "point: reward the idea and the attempt, not a polished or colored finish."
    )


def generate_activity(
    db: Any, student: dict[str, Any], track: str, instructions: str = ""
) -> int:
    """Draft one light enrichment activity for `track` ('art_music' or
    'movement'), persist it as a lesson under that agent key, and return its id.
    One on-demand model call, logged for cost tracking. `instructions` is the
    parent's optional steering prompt (e.g. the tweaked art-card shell). Raises
    ValueError on an unknown track."""
    spec = config.ENRICHMENT_TRACKS.get(track)
    if spec is None:
        raise ValueError(f"Unknown enrichment track: {track}")
    minutes = spec["minutes"]
    track_intro = _TRACK_PROMPTS[track].format(
        age=student.get("age") or 13,
        name=student.get("name") or "the student",
        minutes=minutes,
        interests=db.interests_text(student["id"]) or "a range of things",
    )
    if instructions.strip():
        track_intro += (
            f"\n\nUse this specific direction from the parent for THIS activity: "
            f"{instructions.strip()}"
        )
    payload = generate_lesson(
        system=SYSTEM_PROMPT.format(track_intro=track_intro),
        user_prompt="Design the activity now.",
        schema=ACTIVITY_SCHEMA,
        effort=config.DEFAULT_EFFORT,
    )
    subject = spec["subject"] if subjects.is_valid(spec["subject"]) else "health"
    title = payload.get("title") or spec["label"]
    return db.save_lesson(
        student_id=student["id"],
        agent=track,
        subject=subject,
        topic=spec["label"],
        title=f"{spec['emoji']} {title}",
        payload=payload,
        strategy="parent_requested",
        rationale=f"A light {spec['label']} enrichment activity.",
        metadata={"enrichment": True, "track": track, "credit_subject": subject},
    )
