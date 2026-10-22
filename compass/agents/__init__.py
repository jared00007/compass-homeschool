"""Tier 1 agents. Importing this package registers all four.

`life_skills` and `coding` are exported alongside them but deliberately *not*
registered: neither has a next-topic strategy, because neither ever chooses a
topic. The parent does.
"""

from compass.agents.framework import (
    AgentSpec,
    GeneratedLesson,
    LessonAgent,
    StudentContext,
    TopicProposal,
    all_agents,
    get_agent,
    register,
)
from compass.agents.llm import LessonGenerationError, api_available
from compass.agents import life_skills
from compass.agents import coding
from compass.agents import course_summary
from compass.agents import book_summary
from compass.agents import writing_review
from compass.agents import project_chunker

from compass.agents.math_agent import AGENT as MATH_AGENT
from compass.agents.science_agent import AGENT as SCIENCE_AGENT
from compass.agents.english_agent import AGENT as ENGLISH_AGENT
from compass.agents.history_agent import AGENT as HISTORY_AGENT

# Agents whose "lessons" are parent paperwork or a cost-tracking record of one
# model call -- a drafted course write-up, a book documentation draft, a review
# of his writing, a project broken into steps -- never a card Landon is assigned
# to do. They're logged to the `lessons` table so the model call shows on the
# bill, but they must never surface as student work: not on his Home roster, and
# not on the planning board. Home already allowlists the student-facing agents,
# so it never sees these; the board pulls *every* lesson to assemble the week, so
# it filters this set out explicitly (see `weekly.board_for_week`). Reported
# directly: a "Course documentation -- Math" card no one recognized sitting on
# the board ("i have no idea what this course summary... card is... i believe its
# bunk").
PARENT_PAPERWORK_AGENTS = frozenset(
    {
        course_summary.AGENT_KEY,
        book_summary.AGENT_KEY,
        writing_review.AGENT_KEY,
        project_chunker.AGENT_KEY,
    }
)

for _agent in (MATH_AGENT, SCIENCE_AGENT, ENGLISH_AGENT, HISTORY_AGENT):
    register(_agent)

__all__ = [
    "AgentSpec",
    "GeneratedLesson",
    "LessonAgent",
    "LessonGenerationError",
    "StudentContext",
    "TopicProposal",
    "MATH_AGENT",
    "SCIENCE_AGENT",
    "ENGLISH_AGENT",
    "HISTORY_AGENT",
    "all_agents",
    "api_available",
    "get_agent",
    "life_skills",
    "coding",
    "course_summary",
    "book_summary",
    "writing_review",
    "project_chunker",
    "PARENT_PAPERWORK_AGENTS",
    "register",
]
