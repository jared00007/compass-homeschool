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
    # The family's own school district's filing page or contact. Left blank by
    # default -- Compass has no business guessing which of Washington's ~300
    # districts a family reports to, or what that district's process looks
    # like this year.
    "declaration_url": "",
}

# --- Tiers -------------------------------------------------------------------

TIER_CORE = "core"  # Tier 1 — agent-planned, WA-mandated core subjects
TIER_FOLDED = "folded"  # Tier 2 — secondary credit earned inside a Tier 1 activity
TIER_CHOICE = "choice"  # Tier 3 — student-selected interest topics
TIER_LIFE_SKILLS = "life_skills"  # Parent-defined checklist track

TIERS = (TIER_CORE, TIER_FOLDED, TIER_CHOICE, TIER_LIFE_SKILLS)

TIER_LABELS = {
    TIER_CORE: "Tier 1 — Core",
    TIER_FOLDED: "Tier 2 — Folded in",
    TIER_CHOICE: "Tier 3 — His choice",
    TIER_LIFE_SKILLS: "Core life skills",
}
