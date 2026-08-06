"""The shared agent framework.

Every Tier 1 agent is the same three things:

    system prompt template  +  tool config  +  a "next topic" strategy

Only the third one is genuinely different between subjects, which is why it is a
pluggable function rather than a subclass hook. Math walks a prerequisite graph;
Science and History branch a spiderweb; English follows whatever he is currently
reading. The framework owns everything else: prompt assembly, the API call,
validating the model's multi-subject credit claims against what that agent is
allowed to claim, persistence, and post-generation bookkeeping.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from compass import config, subjects
from compass.agents.credits import normalize_credits
from compass.agents.llm import LessonGenerationError, generate_lesson
from compass.agents.video import channels_for_prompt, verify_video
from compass.storage.db import Database


# --- context passed to strategies and prompt builders ------------------------


@dataclass
class StudentContext:
    """Everything an agent knows before it decides what to teach."""

    db: Database
    student_id: int
    student: dict[str, Any]
    inputs: dict[str, Any] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.student.get("name") or "the student"

    @property
    def grade(self) -> str:
        return str(self.student.get("grade") or "8")

    @property
    def age(self) -> int | None:
        return self.student.get("age")

    @property
    def interests(self) -> str:
        return self.student.get("interests") or ""

    @property
    def location(self) -> str:
        return (self.inputs.get("location") or "").strip()

    @property
    def minutes(self) -> int:
        raw = self.inputs.get("minutes")
        if raw:
            return int(raw)
        return self.db.get_int_setting("default_lesson_minutes")

    @property
    def parent_note(self) -> str:
        return (self.inputs.get("parent_note") or "").strip()


@dataclass
class TopicProposal:
    """A strategy's answer to 'what should he do next, and why?'"""

    topic: str
    rationale: str
    strategy: str
    guidance: str = ""
    context_lines: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    blocked: bool = False
    blocked_reason: str = ""


class NextTopicStrategy(Protocol):
    def __call__(self, ctx: StudentContext) -> TopicProposal: ...


@dataclass
class GeneratedLesson:
    lesson_id: int
    proposal: TopicProposal
    payload: dict[str, Any]
    warnings: list[str] = field(default_factory=list)

    @property
    def credits(self) -> dict[str, int]:
        return {c["subject"]: int(c["minutes"]) for c in self.payload.get("subject_credits", [])}

    @property
    def total_minutes(self) -> int:
        return int(self.payload.get("estimated_minutes") or 0)


# --- the shared system prompt ------------------------------------------------

BASE_SYSTEM_PROMPT = """\
You plan lessons for a homeschooled student inside Compass, the family's \
homeschool app. You are the {agent_name}.

## The student
- Name: {student_name}
- Grade: {grade}{age_line}
- Interests he has told us about: {interests}

## Your subject
Primary subject: {primary_subject}.
{agent_guidance}

## Washington state compliance
Washington requires instruction across eleven subjects and 1,000 instructional \
hours per year. Compass logs hours from your lessons directly into the family's \
compliance dashboard, so the `subject_credits` you return are the actual \
compliance record — not a guess.

The eleven subjects are: {all_subjects}.

Rules for `subject_credits`:
- Always credit the primary subject, {primary_subject}.
- You may additionally credit any of: {allowed_secondary}.

**The test for a secondary credit:** point to a numbered activity, or a clearly \
delineated part of one, whose *purpose* is that subject and which produces \
something you could hand to an evaluator. A 250-word argument with cited \
evidence earns writing. A field journal entry earns writing. A structural \
drawing earns art.

Describing the primary instruction in another subject's vocabulary does not \
earn a credit. If the student restates a definition precisely, that is you \
teaching {primary_subject} well — it is not language instruction. If a worked \
example happens to use a computer, a recipe, or a car, that is context — it is \
not occupational education. If you cannot name the activity number and say what \
artifact it produces, do not claim the credit.

**How many minutes to claim.** The primary subject gets the full lesson length, \
because the whole lesson is that subject. A secondary subject gets the minutes of \
the *segment* that earns it — the 18 minutes he spends reading the source, the 15 \
he spends writing about it. Not the whole lesson.

Segments live inside the lesson, so **the secondary minutes added together must \
not exceed the lesson's total length.** A 60-minute lesson has at most 60 minutes \
of secondary segments to distribute, however many subjects you name. If that \
forces you to choose, choose: two well-earned credits beat five thin ones.

- Never claim a subject that isn't in the allowed list, and never inflate. The \
parent has to defend these hours to a district. An over-credited hour is a \
compliance problem, not a win — and a lesson that honestly credits one subject \
is worth more than one that pads four.
- Minutes per subject may exceed the lesson's total minutes when one activity \
really does teach several subjects at once. That is the intent.

## A supplementary video, if a real one exists
Use `web_search` to look for one video that would help him actually see or hear \
today's specific topic — a worked example in real time, real footage, a real \
demonstration. This is optional and secondary to the lesson itself.

**Only look for a video from one of these channels, because they're the ones \
this family has vetted for his age and this subject: {video_channels}.** Search \
by including the channel name in your query — "Khan Academy two-step equations," \
not just "two-step equations video" — so results actually point at their \
uploads instead of whatever ranks highest.

- **Only report `found: true` if a search this turn actually returned a specific \
video from one of those channels, and you are copying its title and URL exactly \
as the search gave them.** Never write a URL from memory, never guess at one \
that "should" exist, and never adjust or shorten a URL you found. If the best \
result you find is from a channel not on that list, report `found: false` — the \
channel matters as much as the content here, and a wrong-source video doesn't \
belong even if it looks fine. A missing video costs nothing.
- One search is usually enough. This is not the lesson's research budget — do \
not spend it here if the topic also needs grounding in real places, species, or \
sources.
- `why` is one sentence and specific: what he'll actually see in the video that \
the lesson doesn't already show him. Not "this is a good video about X."
- The lesson must stand on its own without it. Nothing in `activities` or \
`assessment` may depend on him having watched it.

## The family's approach
- The design goal is that {student_name} does not feel like he is doing eleven \
separate subjects. Fold naturally; do not bolt on a token art question.
- He has real freedom of choice elsewhere in the week. This lesson is the \
structured part, so make it worth the structure: concrete, doable, and not \
busywork.
- The family roadschools. Lessons that use where they physically are beat \
generic curriculum, when the location genuinely fits.
- Write activity instructions to the student in second person. Write \
`parent_notes` and `overview` to the parent.
- **The student reads `activities` and `materials` directly, on his own screen. \
He never sees `assessment`, `parent_notes`, or `subject_credits`.** So put every \
answer, worked solution, scoring rule, and answer key in `assessment` — never in \
an activity's instructions, and never in `materials`. Questions go in the \
activity; answers go in the assessment. Getting this wrong hands him the answer \
key to the test he is about to sit.
- Target roughly {minutes} minutes total. Match `estimated_minutes` to the sum \
of your activity minutes.
"""


@dataclass
class AgentSpec:
    key: str
    name: str
    primary_subject: str
    agent_guidance: str
    next_topic: NextTopicStrategy
    build_user_prompt: Callable[[StudentContext, TopicProposal], str]
    use_web_search: bool = False
    # Science and History search several times to ground location facts; an
    # agent whose only reason to search is finding one video needs far fewer.
    max_web_searches: int = 6
    post_process: Callable[[StudentContext, TopicProposal, dict[str, Any]], None] | None = None
    default_effort: str = config.DEFAULT_EFFORT


class LessonAgent:
    """Turns an AgentSpec plus a student's state into a persisted lesson."""

    def __init__(self, spec: AgentSpec):
        self.spec = spec

    # -- identity -------------------------------------------------------------

    @property
    def key(self) -> str:
        return self.spec.key

    @property
    def name(self) -> str:
        return self.spec.name

    @property
    def allowed_subjects(self) -> tuple[str, ...]:
        return subjects.allowed_credit_subjects(self.spec.key, self.spec.primary_subject)

    # -- step 1: decide what to teach ----------------------------------------

    def propose_topic(self, ctx: StudentContext) -> TopicProposal:
        return self.spec.next_topic(ctx)

    # -- step 2: write the lesson --------------------------------------------

    def build_system_prompt(self, ctx: StudentContext) -> str:
        age_line = f"\n- Age: {ctx.age}" if ctx.age else ""
        allowed_secondary = [s for s in self.allowed_subjects if s != self.spec.primary_subject]
        return BASE_SYSTEM_PROMPT.format(
            agent_name=self.spec.name,
            student_name=ctx.name,
            grade=ctx.grade,
            age_line=age_line,
            interests=ctx.interests or "none recorded yet",
            primary_subject=subjects.label(self.spec.primary_subject),
            agent_guidance=self.spec.agent_guidance.strip(),
            all_subjects=", ".join(subjects.label(k) for k in subjects.SUBJECT_KEYS),
            allowed_secondary=", ".join(subjects.label(s) for s in allowed_secondary) or "none",
            minutes=ctx.minutes,
            video_channels=channels_for_prompt(self.spec.key),
        )

    def generate(
        self, ctx: StudentContext, proposal: TopicProposal | None = None
    ) -> GeneratedLesson:
        proposal = proposal or self.propose_topic(ctx)
        if proposal.blocked:
            raise LessonGenerationError(proposal.blocked_reason or "This agent is blocked.")

        payload = generate_lesson(
            system=self.build_system_prompt(ctx),
            user_prompt=self.spec.build_user_prompt(ctx, proposal),
            use_web_search=self.spec.use_web_search,
            max_web_searches=self.spec.max_web_searches,
            effort=self.spec.default_effort,
        )
        warnings = self._normalize(payload, proposal, ctx)

        lesson_id = ctx.db.save_lesson(
            student_id=ctx.student_id,
            agent=self.spec.key,
            subject=self.spec.primary_subject,
            topic=payload.get("topic") or proposal.topic,
            title=payload.get("title") or proposal.topic,
            payload=payload,
            strategy=proposal.strategy,
            rationale=proposal.rationale,
            metadata=proposal.metadata,
        )

        if self.spec.post_process:
            self.spec.post_process(ctx, proposal, payload)

        return GeneratedLesson(
            lesson_id=lesson_id, proposal=proposal, payload=payload, warnings=warnings
        )

    # -- step 3: keep the model honest ---------------------------------------

    def _normalize(
        self, payload: dict[str, Any], proposal: TopicProposal, ctx: StudentContext
    ) -> list[str]:
        """Clamp the model's credit claims to what this agent may actually claim.

        The compliance dashboard reads these numbers directly, so this is the
        one place where being strict matters more than being agreeable.
        """
        warnings = normalize_credits(
            payload,
            primary=self.spec.primary_subject,
            allowed=self.allowed_subjects,
            fallback_minutes=ctx.minutes,
        )
        warnings += verify_video(payload, self.spec.key)
        payload.setdefault("branches", [])
        payload.setdefault("materials", [])
        payload.setdefault("learning_objectives", [])
        payload.setdefault("video", {"found": False, "title": "", "url": "", "channel": "", "why": ""})
        return warnings


# --- registry ----------------------------------------------------------------

_REGISTRY: dict[str, LessonAgent] = {}


def register(agent: LessonAgent) -> LessonAgent:
    _REGISTRY[agent.key] = agent
    return agent


def get_agent(key: str) -> LessonAgent:
    if key not in _REGISTRY:
        # Importing the package registers every agent as a side effect.
        import compass.agents  # noqa: F401
    if key not in _REGISTRY:
        raise KeyError(f"No agent registered under '{key}'")
    return _REGISTRY[key]


def all_agents() -> dict[str, LessonAgent]:
    import compass.agents  # noqa: F401

    return dict(_REGISTRY)
