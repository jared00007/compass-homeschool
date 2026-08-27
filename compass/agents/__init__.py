"""Tier 1 agents. Importing this package registers all four.

`life_skills` is exported alongside them but deliberately *not* registered: it has
no next-topic strategy because it never chooses a topic. The parent does.
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
from compass.agents import course_summary
from compass.agents import book_summary
from compass.agents import writing_review

from compass.agents.math_agent import AGENT as MATH_AGENT
from compass.agents.science_agent import AGENT as SCIENCE_AGENT
from compass.agents.english_agent import AGENT as ENGLISH_AGENT
from compass.agents.history_agent import AGENT as HISTORY_AGENT

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
    "course_summary",
    "book_summary",
    "writing_review",
    "register",
]
