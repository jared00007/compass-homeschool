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


# Built-in starter prompts the art-card generator offers alongside a parent's own
# saved ones -- loadable, tweakable, and savable under a new name, but not
# deletable (they're code, not the parent's library). The first is a polished,
# schema-aware version of a disciplined "line work + pop of color" brief.
_ART_EXAMPLE_LINEWORK = """\
Design a disciplined 60-minute technical line-art session for an 8th grader. This \
is a focused drawing class, NOT a loose doodle break -- objective tone, no \
"keep it rough" framing.

PICK ONE theme for today suited to his interests (e.g. a Minecraft isometric \
build, a one-point-perspective video-game corridor, a mech or lightsaber hero \
pose). State the chosen theme up front.

STRICT CONSTRAINTS:
1. POP OF COLOR RULE: Focus on raw line work, but allow minimal, high-impact color \
(a glowing lightsaber, neon game wires, a single energy blast, glowing eyes). No \
heavy backgrounds, no full-page coloring.
2. MINUTE-BY-MINUTE ARCHITECTURE: Break the 60 minutes into strict, sequential \
increments totaling exactly 60. Open with a 5-minute technical warm-up drill.
3. SEQUENTIAL GATES: Don't present the steps as one block. Break them into \
numbered, locked gates; end each gate with a bold "STOP -- finish this before the \
next gate" line.
4. MANDATORY DELIVERABLE: Close with a handwritten, numbered exercise or \
structural-labeling task that proves completion and organization.
5. NO FLUFF: Direct, objective, non-patronizing. No intro or outro filler.

REQUIRED RESOURCES -- integrate these exact links where they fit:
- Minecraft / 3D geometric shapes -> DailySTEM printable isometric dot paper: \
https://dailystem.com/2018/12/14/isometric-drawing-aka-non-digital-minecraft/
- Room depth, action panels, corridors -> Instructables one-point-perspective \
guide: https://www.instructables.com/How-To-Draw-A-Room-Using-One-Point-Perspective/
- Standard drawing mechanics / technical line work -> The Arty Teacher: \
https://theartyteacher.com/websites-every-art-teacher-should-know/

FIELD MAPPING (so it fits the card cleanly, no duplication):
- title: the lesson title + theme.
- overview: ONE direct line on what today's session is.
- materials: the tools needed, INCLUDING the resource links above.
- what_to_do: the full body as markdown -- the 60-minute schedule, the sequential \
gates (using the linked guides), and the mandatory handwritten deliverable, under \
clear headings.
- estimated_minutes: 60.
"""

ART_PROMPT_EXAMPLES: dict[str, str] = {
    "Line work + pop of color (60 min)": _ART_EXAMPLE_LINEWORK,
}


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
    db: Any, student: dict[str, Any], track: str, instructions: str = "",
    instructions_mode: str = "append",
) -> int:
    """Draft one light enrichment activity for `track` ('art_music' or
    'movement'), persist it as a lesson under that agent key, and return its id.
    One on-demand model call, logged for cost tracking. `instructions` is the
    parent's optional steering prompt (e.g. a saved art-card brief).

    `instructions_mode` decides how that prompt is used:
    - "append" (default): the prompt is a tweak layered on top of the track's
      own framing -- a light nudge ("base it on perspective drawing").
    - "replace": the prompt IS the brief -- it governs the whole design and
      overrides the default framing (so a disciplined, technical prompt isn't
      fighting the track's built-in "keep it rough" voice). Only the student
      context (name, age, interests) and the subject are kept around it.

    Raises ValueError on an unknown track."""
    spec = config.ENRICHMENT_TRACKS.get(track)
    if spec is None:
        raise ValueError(f"Unknown enrichment track: {track}")
    minutes = spec["minutes"]
    name = student.get("name") or "the student"
    age = student.get("age") or 13
    interests = db.interests_text(student["id"]) or "a range of things"
    instr = instructions.strip()
    if instr and instructions_mode == "replace":
        subject_word = "ART & MAKING" if track == "art_music" else spec["label"].upper()
        track_intro = (
            f"You design a {subject_word} activity for a homeschooled {age}-year-old "
            f"named {name} (interests: {interests}). Follow the parent's full design "
            f"brief below exactly -- it governs the style, structure, timing, and "
            f"constraints for this activity, and overrides any default framing.\n\n"
            f"PARENT'S BRIEF:\n{instr}"
        )
    else:
        track_intro = _TRACK_PROMPTS[track].format(
            age=age, name=name, minutes=minutes, interests=interests,
        )
        if instr:
            track_intro += (
                f"\n\nUse this specific direction from the parent for THIS activity: "
                f"{instr}"
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
