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
from compass.agents.quiz import verify_quiz, verify_reading_checks
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
        return self.db.interests_text(self.student_id)

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

    @property
    def difficulty(self) -> str:
        """The per-generation override if one was chosen, else the family
        default -- never sticky, so a one-off "Ease in" pick doesn't quietly
        become the new normal without anyone choosing that."""
        return (
            self.inputs.get("difficulty")
            or self.db.get_setting("lesson_difficulty")
            or config.DIFFICULTY_STANDARD
        )

    @property
    def effort(self) -> str:
        """Family-wide by default (Student Profile's Model effort setting),
        same resolution order as difficulty above."""
        return (
            self.inputs.get("effort")
            or self.db.get_setting("effort_level")
            or config.DEFAULT_EFFORT
        )


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

## How a lesson is shaped: Learn → Worked example → Two checks → Quiz
Every lesson has the same four parts, in this order — never more, never fewer. \
The shape is FIXED so every day feels the same, not a different pile of \
activities each time. One idea: taught once, modeled once, checked twice, \
quizzed. Do not invent extra sections or split one idea across a crowded list \
of activities.

1. **Learn** (`learn`) — the teaching section. Explain today's ONE idea in plain \
language {student_name} reads on his own: what it is, why it matters, and a \
short worked example inside the prose if it helps. He is not graded here — teach \
it well enough that the two checks below are fair.

2. **Worked example** (`worked_example`) — ONE problem of exactly the type the \
two checks will ask, solved for him start to finish. Break it into small, \
numbered steps in plain language, and use a relatable hook or comparison where \
one fits his age. This is the "let's do one together" that comes right before he \
tries his own — he is NOT graded on it. Use DIFFERENT specifics than the \
activities (different numbers, a different sentence): it models the move, it is \
never the answer to his own problem.

3. **Two checks** (`activities`) — EXACTLY TWO short comprehension checks on what \
Learn just taught. Both are graded: he does each, and the parent grades it \
against that activity's own `answer`. Keep each small and focused — a single \
clear task, not a multi-part project. This is "did he get it?", not "prove \
mastery of everything."
- **Math and procedural subjects: keep them simple and objective** — a few \
problems or a short computation — with an exact worked `answer`.
- **Every other subject requires some writing** — a few sentences or a short \
paragraph in his own words. Writing only improves by writing, so make him put \
the idea into words.
- `answer` is the full worked solution (math) or what a correct/complete \
response must contain (writing), so a parent grades without solving it \
themselves. **{student_name} NEVER sees `answer`.**

4. **Quiz** (`quiz`) — a quick, auto-marked quiz he takes himself (see below).

That is the whole lesson and the whole grade: the two graded checks plus the \
quiz. If a topic is too big to teach once and check twice, it is two lessons, \
not one crowded one.

## A supplementary video for the Learn section, wherever a real one exists
`learn.video` is ONE video for the lesson's core idea — not one per activity.

**Only look for a video from one of these channels, because they're the ones \
this family has vetted for his age and this subject: {video_channels}.** Search \
including the channel name and this lesson's specific skill — "Khan Academy \
two-step equations," not just "two-step equations video" — so results actually \
point at their uploads instead of whatever ranks highest.

- **Only report `found: true` if a search this turn actually returned a specific \
video from one of those channels, and you are copying its title and URL exactly \
as the search gave them.** Never write a URL from memory, never guess at one \
that "should" exist, and never adjust or shorten a URL you found. If the best \
result is from a channel not on that list, report `found: false` — the channel \
matters as much as the content, and a wrong-source video doesn't belong even if \
it looks fine. A missing video costs nothing; a wrong one costs trust.
- `why` is one sentence and specific: what he'll actually see in the video that \
the explanation and worked example don't already show him. Not "this is a good \
video about X."
- The lesson must stand on its own without it. Nothing in `activities` or `quiz` \
may depend on him having watched it.

## The quiz he takes himself
Write `quiz`: a pool of **at least 20** multiple-choice questions checking \
whether he actually learned today's content — straightforward recall and \
application of exactly what this lesson taught, nothing outside it. He is served \
five at a time from this pool, reshuffled on each retry, so the pool needs real \
breadth: cover every part of the lesson at a mix of difficulties, and don't \
reword one idea twenty times. He takes it himself, right on the screen, graded \
automatically the moment he submits.

- Each question needs exactly four choices: one clearly correct, three \
plausible distractors that aren't obviously wrong.
- **Spread the pool across three kinds of question, not one.** Roughly: a \
third that check he *recalls* the facts/definitions, a third that make him \
*apply* the idea to a new case, and a third that are harder — multi-step, or \
that hinge on the exact misconception you named in `parent_notes` (the wrong \
answer he'd pick if he half-learned it becomes a distractor). A pool that is \
twenty recall questions isn't measuring whether he can actually use this.
- Vary which position the correct answer sits in from question to question — \
do not default to always putting it first or last.
- `explanation` is one sentence, shown to him after he answers, on why the \
correct choice is correct.
- Base every question on this lesson's own material. If he could pass by \
guessing or from outside knowledge, the question isn't doing its job.

## How hard to make this
{difficulty_guidance}

This changes how you teach it, never what he's on the hook for: the two checks \
stay at grade level regardless of this setting. A parent dialing this down for a \
rough week must not mean he's later marked as having learned less than the \
standard actually requires.

**Anchor the rigor to a real grade-{grade} standard, not a vibe.** "8th grade" \
has a concrete meaning — pitch the content and the two checks to the depth a \
documented standard for this exact topic expects (Common Core for math and \
language arts, Next Generation Science Standards for science, a state \
social-studies framework for history/social studies). Teach to that depth: the \
same concepts, the same kind of reasoning and problem types a standards-aligned \
8th-grade lesson on this topic would demand. Don't water a topic down to \
definitions when its standard expects him to apply and analyze, and don't drift \
above grade level into content that belongs to a later year.

## Writing for a 13-year-old
{student_name} reads `title`, `overview`, `learning_objectives`, `learn`, \
`worked_example`, `activities`, `materials`, the video's `why`, and every `quiz` \
question directly, on his own screen, exactly as you write them. Write all of \
those for a 13-year-old — not for a parent, not for a curriculum committee:

- Short sentences, one idea each. If a sentence needs a comma to hold two \
ideas, that's two sentences instead.
- Plain, everyday words over precise-sounding ones — "figure out," "add up," \
"push back on," not "determine," "aggregate," "critique." If a technical term \
is the actual point of the lesson (a vocabulary word, a math term), use it, but \
show what it means in plain language right there rather than defining it once \
formally and moving on.
- Second person, casual and direct — like a sharp older sibling explaining it, \
not a textbook. Contractions are normal. A little personality is good.
- Lean on what he's told us he's into ({interests}) for examples and numbers \
where it genuinely fits — not shoehorned into every activity.
- Simple structure does more work here than vocabulary does: short paragraphs, \
one instruction per line in a list of steps, no throat-clearing before getting \
to the point.

Each activity's `answer`, `parent_notes`, and every `subject_credits[].justification` \
are the opposite of all that — those are for the parent, so write them like the \
adult reading them actually is one.

## The family's approach
- The design goal is that {student_name} does not feel like he is doing eleven \
separate subjects. Fold naturally; do not bolt on a token art question.
- He has real freedom of choice elsewhere in the week. This lesson is the \
structured part, so make it worth the structure: concrete, doable, and not \
busywork.
- The family roadschools. Lessons that use where they physically are beat \
generic curriculum, when the location genuinely fits.
- **The student reads `learn`, `worked_example`, `activities`, and `materials` \
directly, on his own screen. He never sees any activity's `answer`, \
`parent_notes`, or `subject_credits`.** So put every worked solution, scoring \
rule, and answer key in that activity's own `answer` — never in its \
`instructions`, the Learn text, the worked example, or `materials`. The question \
goes in `instructions`; the answer goes in `answer`. Getting this wrong hands him \
the answer key to the check he is about to sit. And keep `worked_example` on \
DIFFERENT specifics than either activity, so it models the move without being an \
activity's answer.
- **He does take `quiz` directly, but Compass reveals each `correct_index` only \
after he submits.** Don't work a quiz question's answer into the Learn text, the \
worked example, or an activity's instructions either.
- **Whenever an activity's `instructions` ask him to put an answer into words — \
write a sentence, answer a question, explain why, argue a position — set that \
activity's `requires_written_response` to true.** That's what puts an actual \
typing box in front of him, in place of a notebook page. Leave it false only for \
work genuinely done on paper instead: solving a math problem by hand, drawing a \
diagram, a hands-on task. For every non-math subject, the two checks should \
almost always be written.
- **Whenever `requires_written_response` is true, fill in that activity's \
`writing_requirements` with real numbers pulled from `instructions` itself** — \
min_words/max_words (leave one null if you only gave a floor or a ceiling), \
min_sentences (when you asked for a sentence count instead), and requires_quote \
(true only if you explicitly told him to quote something in quotation marks). \
Compass checks these before he can submit, so they must match what `instructions` \
asked for — never stricter, never looser. Leave every field null/false when \
`requires_written_response` is false, or you didn't ask for a specific count.
- Target roughly {minutes} minutes total — the two checks plus reading time for \
Learn and the worked example. Match `estimated_minutes` to that whole total.
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
            difficulty_guidance=config.DIFFICULTY_GUIDANCE.get(
                ctx.difficulty, config.DIFFICULTY_GUIDANCE[config.DIFFICULTY_STANDARD]
            ),
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
            effort=ctx.effort,
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

    # -- step 2b: write a whole topic as a multi-day series ------------------

    def _day_proposal(
        self,
        base: TopicProposal,
        day: dict[str, str],
        index: int,
        total: int,
        prior_titles: list[str],
    ) -> TopicProposal:
        """A per-day view of the base proposal: same topic and context, but
        pointed at just this day's focus and told what the earlier days already
        covered, so the model teaches one chunk without re-teaching or racing
        ahead. A one-day series is just the base topic, untouched."""
        if total <= 1:
            return base
        context = list(base.context_lines or [])
        context.append(f"This is day {index + 1} of {total} in a multi-day series on: {base.topic}.")
        if prior_titles:
            context.append(
                "Earlier days already covered these — do NOT reteach them: "
                + "; ".join(prior_titles) + "."
            )
        context.append(f"TODAY's focus — teach and check only this: {day['focus']}")
        guidance = (base.guidance + "\n" if base.guidance else "") + (
            "This lesson is one day of a series. Teach ONLY today's focus above; don't "
            "re-teach earlier days or jump ahead to later ones. Keep the fixed lesson "
            "shape: Learn, one worked example, exactly two graded activities, a short quiz."
        )
        from dataclasses import replace

        return replace(
            base,
            topic=f"{base.topic} — Day {index + 1}: {day['title']}",
            context_lines=context,
            guidance=guidance,
        )

    def generate_series(
        self,
        ctx: StudentContext,
        proposal: TopicProposal | None = None,
        *,
        plan: list[dict[str, str]] | None = None,
    ) -> list[GeneratedLesson]:
        """Write a whole topic as an ordered series of fixed-shape lessons.

        The generator decides how many days the topic needs (see
        `series.plan_lesson_series`) and every day is written by this agent's
        normal path, so each is a complete Learn -> worked example -> two graded
        activities -> quiz lesson. The days carry no `planned_for` date: they
        queue for him in `series_index` order and he works through them one at a
        time, which is what drops the day-by-day scheduling the parent didn't
        want. `plan` can be passed in to skip the planning call (tests, or a
        parent who edited the day breakdown first)."""
        from uuid import uuid4

        from compass.agents.series import plan_lesson_series
        from compass import subjects

        proposal = proposal or self.propose_topic(ctx)
        if proposal.blocked:
            raise LessonGenerationError(proposal.blocked_reason or "This agent is blocked.")

        if plan is None:
            plan = plan_lesson_series(
                topic=proposal.topic,
                subject_label=subjects.label(self.spec.primary_subject),
                grade=ctx.grade,
                minutes_per_day=ctx.minutes,
                context="\n".join(proposal.context_lines or []),
            )
        # A blank or unusable plan still produces one real lesson rather than
        # nothing -- a single-day series on the whole topic.
        if not plan:
            plan = [{"title": proposal.topic, "focus": proposal.topic}]

        series_id = f"{self.spec.key}-{uuid4().hex[:8]}"
        total = len(plan)
        results: list[GeneratedLesson] = []
        prior_titles: list[str] = []
        for index, day in enumerate(plan):
            day_proposal = self._day_proposal(proposal, day, index, total, prior_titles)
            payload = generate_lesson(
                system=self.build_system_prompt(ctx),
                user_prompt=self.spec.build_user_prompt(ctx, day_proposal),
                use_web_search=self.spec.use_web_search,
                max_web_searches=self.spec.max_web_searches,
                effort=ctx.effort,
            )
            warnings = self._normalize(payload, day_proposal, ctx)
            metadata = dict(proposal.metadata or {})
            metadata.update(
                {
                    "series_id": series_id,
                    "series_index": index,
                    "series_total": total,
                    "series_title": proposal.topic,
                    "series_focus": day["focus"],
                }
            )
            lesson_id = ctx.db.save_lesson(
                student_id=ctx.student_id,
                agent=self.spec.key,
                subject=self.spec.primary_subject,
                topic=payload.get("topic") or day["title"] or proposal.topic,
                title=payload.get("title") or day["title"] or proposal.topic,
                payload=payload,
                strategy=proposal.strategy,
                rationale=proposal.rationale,
                metadata=metadata,
            )
            if self.spec.post_process:
                self.spec.post_process(ctx, day_proposal, payload)
            results.append(
                GeneratedLesson(
                    lesson_id=lesson_id, proposal=day_proposal, payload=payload, warnings=warnings
                )
            )
            prior_titles.append(day["title"] or day["focus"])
        return results

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
        warnings += verify_quiz(payload)
        warnings += verify_reading_checks(payload)
        payload.setdefault("branches", [])
        payload.setdefault("materials", [])
        payload.setdefault("learning_objectives", [])
        payload.setdefault("quiz", [])
        # The fixed-shape sections. `learn` and `worked_example` are the teaching
        # half a new lesson leads with; defaulted so a lesson generated before
        # the switch (or a partial payload) still renders without a KeyError.
        payload.setdefault(
            "learn",
            {"explanation": "", "video": {"found": False, "title": "", "url": "",
                                          "channel": "", "why": ""}},
        )
        payload.setdefault("worked_example", {"problem": "", "steps": ""})
        # Defensive, per activity, same as the other setdefaults above --
        # `video` is required by the schema, but every other optional-in-
        # practice field gets this same belt-and-suspenders treatment.
        for activity in payload.get("activities") or []:
            # `phase` (learn/practice) replaced the old 8-value `kind`. A lesson
            # generated before the switch still carries `kind`; map it so the
            # grouped Learn/Practice view keeps working on old lessons -- only a
            # bare "instruction" is teaching, everything else was him doing work.
            if not activity.get("phase"):
                legacy = activity.get("kind")
                activity["phase"] = "learn" if legacy == "instruction" else "practice"
            activity.setdefault(
                "video", {"found": False, "title": "", "url": "", "channel": "", "why": ""}
            )
            activity.setdefault("requires_written_response", False)
            # The per-activity answer key the parent grades against (new shape).
            activity.setdefault("answer", "")
            # Legacy fields kept defaulted so old lessons still render/grade.
            activity.setdefault("self_check", "")
            activity.setdefault("checklist", [])
            activity.setdefault("reading_check", [])
            activity.setdefault(
                "writing_requirements",
                {"min_words": None, "max_words": None, "min_sentences": None,
                 "requires_quote": False},
            )
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
