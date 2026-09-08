"""Science Agent — spiderweb branching from a topic or a location.

This is the shape the original roadschooling prototype had: pick a thread, pull
it, and let each lesson propose the next set of branches. Compass stores the web
so the thread survives between sessions instead of restarting every time.
"""

from __future__ import annotations

from typing import Any

from compass.agents.framework import AgentSpec, LessonAgent, StudentContext, TopicProposal
from compass.agents.prompts import build_standard_prompt
from compass.agents.strategies import record_spiderweb_result, spiderweb

GUIDANCE = """\
Science here is a spiderweb, not a syllabus. Each lesson pulls one thread and \
proposes the next branches, so the year's path is emergent and driven by where \
the family actually is.

What that means in practice:
- Location first. If the family is at a national park, a coastline, a lava field, \
a river, a farm — the lesson is about THAT, specifically. Use web search to get \
the real species, the real geology, the real conditions. "Some birds live here" \
is a failure; "the Clark's nutcracker caches whitebark pine seeds here, which is \
why the pines regenerate along ridgelines" is the job.
- Every lesson gets one genuine field or hands-on component. Observation, \
measurement, collection, a built thing. Not a worksheet with an outdoor theme.
- Teach the mechanism, not the label. An 8th grader should leave knowing why \
something happens, not just what it's called.
- Fold honestly. A field journal entry is real writing. Sketching a specimen with \
attention to structure is real art. Reading an interpretive sign is not reading \
instruction. Credit what you actually built into the activities.
- End with 2-4 `branches`: real, distinct next lessons this one opens up. Vary \
their direction — one that goes deeper, one that goes sideways into another \
discipline, one that follows the location. These become the pool the next lesson \
is drawn from, so a vague branch costs you later.
"""


# Broad 8th-grade science strands a parent can jump the spiderweb into, to
# deliberately change course -- reported: "what if I want to choose a whole new
# area of science like life sciences or bio ... just a different path." Each is
# phrased as a fresh-thread seed, so picking one starts that discipline instead
# of continuing whatever web the recent lessons built. (label, seed_topic).
SCIENCE_AREAS: tuple[tuple[str, str], ...] = (
    ("Life science & biology",
     "Start a fresh 8th-grade life-science thread: living things, cells, and how "
     "organisms are built and work. Pick a strong first lesson that opens up biology."),
    ("Human body & health",
     "Start a fresh 8th-grade thread on the human body: pick one major body system "
     "and how it works, opening up anatomy and health."),
    ("Chemistry & matter",
     "Start a fresh 8th-grade chemistry thread on matter: atoms, elements, and how "
     "substances react and change."),
    ("Physics, forces & energy",
     "Start a fresh 8th-grade physics thread: forces, motion, and energy -- pick a "
     "strong hands-on first lesson."),
    ("Earth science & geology",
     "Start a fresh 8th-grade earth-science thread: rocks, plate tectonics, and the "
     "systems that shape the planet."),
    ("Weather & climate",
     "Start a fresh 8th-grade thread on weather and climate: the atmosphere, what "
     "drives weather, and how climate works."),
    ("Space & astronomy",
     "Start a fresh 8th-grade astronomy thread: the solar system, stars, and how we "
     "know what's out there."),
    ("Ecology & environment",
     "Start a fresh 8th-grade ecology thread: ecosystems, energy flow, biomes, and "
     "how living things depend on each other."),
)


def _prompt(ctx: StudentContext, proposal: TopicProposal) -> str:
    return build_standard_prompt(ctx, proposal, "science")


def _post_process(ctx: StudentContext, proposal: TopicProposal, payload: dict[str, Any]) -> None:
    record_spiderweb_result(ctx, proposal, payload, agent_key="science")


SPEC = AgentSpec(
    key="science",
    name="Science Agent",
    primary_subject="science",
    agent_guidance=GUIDANCE,
    next_topic=spiderweb,
    build_user_prompt=_prompt,
    use_web_search=True,
    # Location grounding needs several searches, and video is now per activity
    # rather than one-per-lesson (several more, not just one) -- both share
    # this same budget.
    max_web_searches=9,
    post_process=_post_process,
)

AGENT = LessonAgent(SPEC)
