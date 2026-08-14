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
    # Score needed on the in-app quiz to count as a pass. A pass on a Math lesson
    # auto-records mastery; other subjects just show the score.
    "quiz_pass_percent": "80",
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

TIERS = (TIER_CORE, TIER_FOLDED, TIER_CHOICE, TIER_LIFE_SKILLS, TIER_PROJECTS, TIER_WELLNESS)

TIER_LABELS = {
    TIER_CORE: "Tier 1 — Core",
    TIER_FOLDED: "Tier 2 — Folded in",
    TIER_CHOICE: "Tier 3 — {name}'s choice",
    TIER_LIFE_SKILLS: "Core life skills",
    TIER_PROJECTS: "Big Projects",
    TIER_WELLNESS: "Morning Wellness",
}


def tier_label(tier: str, student_name: str) -> str:
    """TIER_LABELS, with Tier 3's `{name}` placeholder filled in. The only
    label that's ever student-specific -- pulled from the student's own
    profile field (same one the sidebar already reads), not a hardcoded
    name, so it can't go stale if that profile is ever edited."""
    return TIER_LABELS.get(tier, tier).format(name=student_name)


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
