"""Math Agent — prerequisite-graph based.

Built second in the plan and deliberately: it is the furthest thing from the
spiderweb prototype, so if the shared framework can carry both, it generalizes.
"""

from __future__ import annotations

from compass.agents.framework import AgentSpec, LessonAgent, StudentContext, TopicProposal
from compass.agents.prompts import build_standard_prompt
from compass.agents.strategies import graph_walk

GUIDANCE = """\
Math is the one subject here with a strict prerequisite chain. You cannot teach \
fractions before division, and Compass will not let you: the next skill is chosen \
by walking a hand-authored 8th-grade dependency graph, and it only unlocks once \
every prerequisite is demonstrably mastered. Your job is to teach the single node \
you are handed, well.

What that means in practice:
- Assume real fluency in the listed prerequisites. Build on them; do not reteach them.
- Do not preview or drift into the skills this one unlocks. That is next month's lesson.
- Include worked examples with the reasoning shown, then practice that escalates \
from procedural to applied. Word problems should use things he actually encounters \
on the road — trip distances, fuel, elevation, park fees, campsite geometry.
- The assessment is load-bearing. The parent scores it and that score is what \
unlocks the next node, so `mastery_criteria` has to be specific enough to grade \
without judgment calls (e.g. "8 of 10 correct, including at least 2 of the 3 \
applied problems"), and it must actually test THIS skill rather than arithmetic \
fluency in general.
- Name the common misconceptions for this specific skill in `parent_notes`.
"""


def _prompt(ctx: StudentContext, proposal: TopicProposal) -> str:
    return build_standard_prompt(ctx, proposal, "math")


SPEC = AgentSpec(
    key="math",
    name="Math Agent",
    primary_subject="math",
    agent_guidance=GUIDANCE,
    next_topic=graph_walk,
    build_user_prompt=_prompt,
    # On, but only for the shared video search -- math never needs the general
    # web to teach a fixed skill, so the budget stays tight.
    use_web_search=True,
    max_web_searches=2,
)

AGENT = LessonAgent(SPEC)
