"""Application-wide configuration and family policy defaults.

Anything here that is a *family policy* call (as opposed to a Washington state
requirement) is stored in the `settings` table so it can be changed from the UI.
The constants below are the defaults used on first run.
"""

from __future__ import annotations

import os
from pathlib import Path

# --- Storage -----------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = Path(os.environ.get("COMPASS_DB", PROJECT_ROOT / "compass.db"))

# --- Model -------------------------------------------------------------------

DEFAULT_MODEL = "claude-opus-5"
DEFAULT_EFFORT = "high"
DEFAULT_MAX_TOKENS = 16000

# Reviewing or summarizing something that already exists is a much smaller job
# than authoring a lesson from scratch, and doesn't need the frontier model to
# do it well: checking a response against a rubric that's already written, or
# introducing a book from its title, is close to the cheapest useful thing a
# model does. Named here, next to DEFAULT_MODEL, so every such feature reads
# one constant instead of picking its own -- and so moving them all back up is
# a one-line change if the quality ever disappoints.
REVIEW_MODEL = "claude-haiku-4-5"

# --- Washington state compliance floor ---------------------------------------
# RCW 28A.225.010 / 28A.200.010: instruction in 11 subjects, 1,000 hours/year.
# These are statutory, not preferences — they are not exposed as settings.

WA_ANNUAL_HOURS = 1000
WA_ANNUAL_DAYS = 180

# --- High school credit (grades 6-12 course documentation) -------------------
# Sumner-Bonney Lake's own figure for converting logged instructional time into
# a Carnegie-style credit toward the diploma. Not a WA statute -- a district
# packet requirement -- but not a family preference either, so it lives here
# rather than in `settings`.

CREDIT_HOURS_PER_UNIT = 150

# Not a district figure at all -- just the point at which the Courses page
# starts nudging "this subject has enough untagged hours sitting around to be
# worth turning into a course," so hours don't quietly pile up uncounted
# toward any credit. A UX tuning knob, free to adjust.
COURSE_NUDGE_HOURS = 20

# Flat credit a parent-approved travel journal entry earns automatically --
# no manual "Log hours" click needed for the ordinary case. Picked to read as
# a real but modest writing session plus its social-studies half (a trip
# genuinely does double as geography/civics/economics, WA's own definition of
# that subject), not an attempt to estimate actual time spent. The existing
# manual Log Hours flow on the journal page stays available afterward for
# anything that earned more than this.
TRAVEL_JOURNAL_WRITING_MINUTES = 30
TRAVEL_JOURNAL_SOCIAL_STUDIES_MINUTES = 15

# Below this many words, a story isn't "submitted for review" yet -- it's
# saved as a stub he can keep writing. Keeps a travel entry an actual
# written account of a real trip (who, what, where, a real memory) rather
# than a one-line "went to the store" cashing in the flat credit above.
TRAVEL_JOURNAL_MIN_STORY_WORDS = 60

# How many open-ended trips a parent can assign at once with "assign him to
# pick" -- he chooses the destinations himself, one stub per trip.
TRAVEL_JOURNAL_MAX_OPEN_PICKS = 5

# A click alone doesn't prove he read the feedback -- he has to reply with
# something specific from it first. Short (this isn't the story), but long
# enough to rule out a one-word dodge like "ok" or "k".
TRAVEL_JOURNAL_FEEDBACK_REPLY_MIN_WORDS = 4

# --- XP + levels (student-facing fun, not a compliance measure) --------------
# Points earned for the things he actually finishes, summed live from his own
# completion signals (see compass.xp) -- no stored score to drift out of sync,
# and no waiting on a parent to log hours. All tunable knobs, pure motivation.
XP_PER_LESSON = 20
XP_QUIZ_PASS_BONUS = 10
XP_PER_LIFE_SKILL = 15
XP_PER_CODING_MODULE = 15
XP_PER_TRAVEL_ENTRY = 30
XP_PER_CHOICE_TOPIC = 15
XP_PER_MASTERED_SKILL = 10
# The one thing that *costs* XP: every time a lesson is sent back for a redo.
# Deliberately modest (a bit over a lesson's own worth split in half, well under
# a full lesson) and floored so the total never drops below zero -- a real "read
# the whole assignment the first time" consequence, not a punishment that erases
# a good week. Counted per bounce, so a lesson sent back twice costs twice.
XP_SENT_BACK_PENALTY = 10
# Flat XP span per level -- level = total // XP_PER_LEVEL + 1.
XP_PER_LEVEL = 100
# Real-world rewards he unlocks at cumulative-XP milestones -- the "reward
# system of movie night, ice cream sundae party" idea, made concrete. The app
# only surfaces what he's earned and what's next; the parent decides when to
# actually deliver it. (threshold_xp, name, emoji), ascending by threshold.
XP_REWARDS: tuple[tuple[int, str, str], ...] = (
    (150, "Pick a family movie night", "🎬"),
    (300, "Ice cream sundae run", "🍨"),
    (500, "Friend sleepover", "🛌"),
    (750, "Ice cream sundae party", "🎉"),
    (1000, "A day trip you choose", "🗺️"),
)
# Rank names by level (level 1 = index 0). The last one holds for every level
# beyond the list, so it never runs out -- on the compass/explorer theme.
XP_RANKS = (
    "Rookie Navigator",
    "Scout",
    "Trail Finder",
    "Pathfinder",
    "Trailblazer",
    "Explorer",
    "Voyager",
    "Cartographer",
    "Captain",
    "Commander",
    "Admiral",
    "Legend of the Map",
)

# Rough per-block time estimates for the weekly board's "how heavy is this day"
# gauge (see ui.board_item_minutes). A lesson carries its own real estimate
# (its activities' minutes) and a travel entry uses the two constants above; the
# rest have no stored duration, so these are deliberately round, tunable
# defaults -- enough to let a parent eyeball whether a day is packed or light,
# never a claim of exact time spent. Shown with a "≈" so they read as estimates.
BOARD_BLOCK_MINUTES: dict[str, int] = {
    "life_skill": 30,
    "coding_module": 45,
    "choice_topic": 30,
    "project_step": 45,
}

# --- Family policy defaults (editable in Settings) ---------------------------

DEFAULT_SETTINGS: dict[str, str] = {
    # Annual instructional-hour target. Defaults to the WA floor; a family may
    # choose to aim higher.
    "annual_hour_target": str(WA_ANNUAL_HOURS),
    # Target instructional days.
    "annual_day_target": str(WA_ANNUAL_DAYS),
    # Share of the annual target that may come from Tier 3 (student choice)
    # before the dashboard shows a soft warning. WA does not mandate a split —
    # this is a family policy call, so it is a warning, never a block.
    "tier3_cap_percent": "20",
    # Typical instructional day length in minutes, used to size lesson requests.
    "default_lesson_minutes": "60",
    # Score needed on the in-app quiz to count as a pass -- real, encouraging
    # feedback ("nice work") on its own, distinct from mastery below.
    "quiz_pass_percent": "80",
    # Score needed on a Math quiz specifically for the skill to auto-record as
    # mastered -- deliberately a separate, stricter bar than quiz_pass_percent
    # above: an 80% still passes and feels good, but Math treats "mastered"
    # (which unlocks the next skill) as a higher bar than "passed," and nudges
    # a retry in between rather than silently calling 80% good enough to move
    # on. Math-only: Science/English/History have no mastery gate to hook
    # into (see GUIDE.md), so this setting has no effect there.
    "math_mastery_percent": "100",
    # Anti-rushing: the fewest seconds he must spend before the quiz will accept
    # a submission, counted per question (so 5 questions x 15s = a 75-second
    # floor). Blitzing a five-question quiz in 40 seconds isn't reading it --
    # reported directly ("hes completing them in under 60 seconds"). Below the
    # floor, Submit is refused with a "slow down" nudge and his answers are kept,
    # so he waits rather than starts over. Set to 0 to turn the gate off.
    "quiz_min_seconds_per_question": "15",
    # Anti-rushing, part two: after a failed attempt he must wait this many
    # seconds before "Try again" unlocks -- a forced pause to actually look at
    # what he missed (shown right there) instead of rapid-firing the same guess.
    # The screenshot that prompted this had three retries in under 90s each,
    # scores going 3/5 -> 2/5 -> 2/5. Set to 0 to turn the cooldown off.
    "quiz_retry_cooldown_seconds": "30",
    # --- grading ---------------------------------------------------------
    # How much each quiz retry is worth, relative to a first attempt: the
    # 2nd counts for 90%, the 3rd 80%, and so on, down to the floor. The
    # grade takes the BEST weighted attempt, so a careless retry can never
    # lower it -- there must never be a reason to avoid trying again.
    "quiz_retry_deduction_percent": "10",
    # The least a retry can ever be worth. Without a floor, a tenth attempt
    # is worth nothing and practice starts to feel punished.
    "quiz_retry_floor_percent": "70",
    # Per-subject grade weights, as "component:weight" pairs. Deliberately
    # settings rather than constants: what a subject's grade should be made
    # of is a teaching judgment, and it differs by subject -- Math leans on
    # its mastery graph, English on what he actually wrote. Components:
    # quizzes, writing, reading (reading checks), mastery, assessment.
    "grade_weights_math": "quizzes:45,mastery:35,assessment:20",
    "grade_weights_english": "writing:40,quizzes:25,reading:15,assessment:20",
    "grade_weights_science": "quizzes:40,writing:25,reading:15,assessment:20",
    "grade_weights_history": "quizzes:40,writing:25,reading:15,assessment:20",
    # School year start (MM-DD). Used to bucket activities into a school year.
    "school_year_start": "09-01",
    # Washington's annual Declaration of Intent filing deadline (MM-DD). Default
    # is RCW 28A.200.010's September 15th; a family starting home-based
    # instruction after the school year begins instead has two weeks from that
    # start date, so this is editable rather than a hardcoded constant.
    "declaration_due": "09-15",
    # The family's own school district's site, and where its Declaration of
    # Intent actually gets sent -- filled in from the family's own district
    # packet once they've told Compass which district that is, not guessed.
    # Sumner-Bonney Lake files by mail/fax, not an online portal, hence a
    # separate mailing-address setting rather than assuming a "filing page."
    "declaration_url": "https://www.sumnersd.org",
    "declaration_mail_to": (
        "Sumner-Bonney Lake School District\n"
        "1202 Wood Avenue\n"
        "Sumner, WA 98390\n"
        "Phone: (253) 891-6000 · Fax: (253) 891-6101"
    ),
    # How hard Tier 1 lessons should be, family-wide. A per-generation choice
    # on each subject's Plan tab can override this for one lesson without
    # changing the family default -- see DIFFICULTY_LEVELS below.
    "lesson_difficulty": "standard",
}

# --- Tiers -------------------------------------------------------------------

TIER_CORE = "core"  # Tier 1 — agent-planned, WA-mandated core subjects
TIER_FOLDED = "folded"  # Tier 2 — secondary credit earned inside a Tier 1 activity
TIER_CHOICE = "choice"  # Tier 3 — student-selected interest topics
TIER_LIFE_SKILLS = "life_skills"  # Parent-defined checklist track
TIER_PROJECTS = "projects"  # Parent-defined multi-step project track (e.g. the Lego film)
TIER_WELLNESS = "wellness"  # Morning routine -- stretch/breathing/mindfulness credit
TIER_CODING = "coding"  # Parent-defined checklist track, same shape as Life Skills

TIERS = (
    TIER_CORE, TIER_FOLDED, TIER_CHOICE, TIER_LIFE_SKILLS, TIER_PROJECTS,
    TIER_WELLNESS, TIER_CODING,
)

TIER_LABELS = {
    TIER_CORE: "Tier 1 — Core",
    TIER_FOLDED: "Tier 2 — Folded in",
    TIER_CHOICE: "Tier 3 — {name}'s choice",
    TIER_LIFE_SKILLS: "Core life skills",
    TIER_PROJECTS: "Big Projects",
    TIER_WELLNESS: "Morning Wellness",
    TIER_CODING: "Coding Camp",
}


def tier_label(tier: str, student_name: str) -> str:
    """TIER_LABELS, with Tier 3's `{name}` placeholder filled in. The only
    label that's ever student-specific -- pulled from the student's own
    profile field (same one the sidebar already reads), not a hardcoded
    name, so it can't go stale if that profile is ever edited."""
    return TIER_LABELS.get(tier, tier).format(name=student_name)


# --- Assessment verdicts -------------------------------------------------------
# The parent's digital check on a lesson's `assessment` block, for subjects with
# no mastery graph to hook into (Science/English/History -- Math's equivalent is
# recording mastery directly, since it already has one). See
# Database.record_assessment and compass.ui.render_assessment_card.

ASSESSMENT_NAILED_IT = "nailed_it"
ASSESSMENT_SOLID = "solid"
ASSESSMENT_GETTING_THERE = "getting_there"
ASSESSMENT_NEEDS_MORE_WORK = "needs_more_work"
ASSESSMENT_NOT_YET = "not_yet"

# Five bands rather than the original three: three is too coarse to grade
# with -- everything real lands on "getting there," which then has to mean
# both "nearly had it" and "barely engaged." The three original keys are
# still valid values, so nothing already recorded breaks.
ASSESSMENT_VERDICTS = (
    ASSESSMENT_NAILED_IT,
    ASSESSMENT_SOLID,
    ASSESSMENT_GETTING_THERE,
    ASSESSMENT_NEEDS_MORE_WORK,
    ASSESSMENT_NOT_YET,
)

# What each band is worth when it feeds a subject grade. Shown on the label
# itself, so a parent always knows exactly what they're assigning rather
# than discovering the mapping later.
ASSESSMENT_VERDICT_SCORES = {
    ASSESSMENT_NAILED_IT: 100,
    ASSESSMENT_SOLID: 90,
    ASSESSMENT_GETTING_THERE: 80,
    ASSESSMENT_NEEDS_MORE_WORK: 70,
    ASSESSMENT_NOT_YET: 55,
}

ASSESSMENT_VERDICT_LABELS = {
    ASSESSMENT_NAILED_IT: "🎯 Nailed it (100%)",
    ASSESSMENT_SOLID: "✅ Solid (90%)",
    ASSESSMENT_GETTING_THERE: "🌱 Getting there (80%)",
    ASSESSMENT_NEEDS_MORE_WORK: "🔁 Needs more work (70%)",
    ASSESSMENT_NOT_YET: "⚠️ Not yet (55%)",
}


# --- Grades --------------------------------------------------------------------
# Washington does not require grades for a homeschooled student -- this exists
# because Landon asked to be graded, and because `courses.final_grade` (already
# in the schema, for grades 6-12 credit documentation) will want a real number
# when a transcript starts mattering.

# Letter bands, highest first. Standard US scale.
GRADE_BANDS: tuple[tuple[float, str], ...] = (
    (97, "A+"), (93, "A"), (90, "A-"),
    (87, "B+"), (83, "B"), (80, "B-"),
    (77, "C+"), (73, "C"), (70, "C-"),
    (67, "D+"), (63, "D"), (60, "D-"),
    (0, "F"),
)

# The most graded attempts a quiz can have. Four is where the 20-question
# pool runs out at 5 a sitting (see compass/agents/quiz.py), so a fifth
# attempt would be measuring memory of the quiz rather than knowledge of the
# lesson. The deduction floor below lands on the same number independently.
# Retries past this still work -- they're just labelled as practice and left
# out of the grade, because blocking practice to protect a number is
# backwards.
GRADED_QUIZ_ATTEMPTS = 4


def letter_for(percent: float) -> str:
    """The letter for a 0-100 score."""
    for floor, letter in GRADE_BANDS:
        if percent >= floor:
            return letter
    return "F"


# --- Writing review status -----------------------------------------------------
# The draft -> submitted -> parent-decision loop a writing response moves
# through, tracked separately from the assessment verdict above -- this is
# about one specific typed answer meeting the assignment, not the lesson as
# a whole. See Database.set_writing_review and compass.ui's writing-box and
# assessment-card handling.

WRITING_DRAFT = "draft"
WRITING_SUBMITTED = "submitted"
WRITING_NEEDS_REVISION = "needs_revision"
WRITING_APPROVED = "approved"

WRITING_REVIEW_STATUSES = (
    WRITING_DRAFT, WRITING_SUBMITTED, WRITING_NEEDS_REVISION, WRITING_APPROVED,
)


# --- Lesson difficulty --------------------------------------------------------
# Family-wide by default (the `lesson_difficulty` setting above), with a
# per-generation override each subject's Plan tab offers on top of it -- see
# StudentContext.difficulty in agents/framework.py for how the two combine.
# Applies to the four Tier 1 agents only; Life Skills plans a hands-on task,
# not a reading/writing complexity level, so it isn't a fit for this dial.

DIFFICULTY_EASE_IN = "ease_in"
DIFFICULTY_STANDARD = "standard"
DIFFICULTY_PUSH = "push"

DIFFICULTY_LEVELS = (DIFFICULTY_EASE_IN, DIFFICULTY_STANDARD, DIFFICULTY_PUSH)

DIFFICULTY_LABELS = {
    DIFFICULTY_EASE_IN: "Ease in",
    DIFFICULTY_STANDARD: "Standard",
    DIFFICULTY_PUSH: "Push him",
}

# What each level actually tells the model, dropped into the shared system
# prompt every Tier 1 agent uses (agents/framework.py's BASE_SYSTEM_PROMPT).
# Deliberately one shared block, not per-subject text -- this is about tone,
# scaffolding, and vocabulary, which generalize across subjects, while each
# agent's own guidance still supplies the subject-specific instructions.
# Never touches `assessment`/mastery criteria: BASE_SYSTEM_PROMPT pins that
# bar as fixed regardless of difficulty, so "Ease in" can't quietly mean a
# lower bar for being marked mastered than "Push him" would require.
DIFFICULTY_GUIDANCE = {
    DIFFICULTY_EASE_IN: (
        "Keep this one approachable. Favor the version of an idea he can get on "
        "the first read, a worked example before he's asked to try one cold, and "
        "vocabulary he already knows over new technical terms unless the lesson "
        "is specifically teaching that term. It's fine if this doesn't stretch "
        "him -- steady footing matters more than pace today."
    ),
    DIFFICULTY_STANDARD: (
        "Teach at grade level, with enough scaffolding that a capable "
        "13-year-old can do this himself. New vocabulary or techniques get a "
        "worked example before he's asked to apply one independently."
    ),
    DIFFICULTY_PUSH: (
        "He's 13 and capable -- don't write down to him. Teach at or above "
        "grade level, expect him to sit with a harder idea before you hand him "
        "the answer, and don't over-scaffold: one clear example is enough, then "
        "let him work independently."
    ),
}


def difficulty_label(level: str) -> str:
    return DIFFICULTY_LABELS.get(level, level)


# --- Model effort ---------------------------------------------------------------
# Family-wide, changeable from Student Profile -- see StudentContext.effort in
# agents/framework.py. How much the model reasons before writing a lesson is
# the single biggest lever on generation cost; offering only "high" (the
# default) and "medium" here is deliberate -- "low" trades away enough
# quality that it isn't a real option for a family that's said no to that
# tradeoff, and "xhigh"/"max" only cost more than the default, never less.

EFFORT_MEDIUM = "medium"
EFFORT_HIGH = "high"

EFFORT_LEVELS = (EFFORT_MEDIUM, EFFORT_HIGH)

EFFORT_LABELS = {
    EFFORT_MEDIUM: "Medium — lower cost, some quality tradeoff",
    EFFORT_HIGH: "High — best quality (default)",
}


def effort_label(level: str) -> str:
    return EFFORT_LABELS.get(level, level)
