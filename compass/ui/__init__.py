"""Streamlit helpers shared across pages -- the package facade.

Kept out of `compass/` core modules on purpose — the agents, storage, and
compliance layers know nothing about Streamlit, so they stay testable and
reusable if the UI is ever replaced.

This used to be one ~6k-line module. It is now a package: the tightly-shared
core (mode/nav chrome, the generate loop, lesson rendering, the quiz, the
student lesson view, the daily/home widgets, small banners) lives here in
`__init__`, and larger self-contained sections are split into submodules,
each re-exported below so `from compass.ui import X` keeps working unchanged:

    comic.py            "Comic Panels" lesson layout + render_lesson
    board.py            the move control, day grid, and per-subject week view
    review.py           the digital assessment / grading-and-review card
    lifeskill_cards.py  the Life Skills page cards (life skills, coding, choice)
    vocab.py            the vocabulary-review quiz
    firstday.py         the once-a-year first-day-of-school celebration

The one thing to know when moving code in or out: a fair number of tests do
`monkeypatch.setattr(ui, "st", Recorder(...))` (and patch `ui.date` /
`ui.is_parent`) to render without a live Streamlit context. A submodule with
its own `import streamlit as st` would not see those patches, so the
submodules reach exactly those three names through `import compass.ui as _ui`
and call `_ui.st` / `_ui.date` / `_ui.is_parent`, resolved at call time.
Everything else a submodule shares is a plain import. Grep any file for
`^# ---` for its section landmarks.
"""

from __future__ import annotations

import html
import sqlite3
import time
from datetime import date
from typing import Any

import streamlit as st

from compass import (
    auth,
    config,
    daily,
    fun_facts,
    xp as xp_module,
    grades,
    gradebook,
    reading,
    subjects,
    theme as theming,
    weekly,
)
from compass.backup import auto_snapshot
from compass.agents import (
    GeneratedLesson,
    LessonAgent,
    LessonGenerationError,
    StudentContext,
)
from compass.agents.quiz import grade as grade_quiz, passed as quiz_passes, select_questions
from compass.compliance import declaration_status
from compass.morning_routines import MORNING_ROUTINES, routine_for_date
from compass.storage.db import Database


def md(text: str | None) -> str:
    """Escape literal dollar signs before handing text to st.write/st.markdown.

    Streamlit's markdown renderer treats a pair of `$` as LaTeX math
    delimiters -- completely invisible until a lesson happens to mention two
    dollar amounts in the same block of text (a math word problem about
    prices, a life-skill budget example, a quiz choice), at which point
    everything between them silently turns into a rendered equation instead
    of the price it actually was. `\\$` is always treated as a literal dollar
    sign by Streamlit's renderer, math context or not, so this is safe to
    apply unconditionally to any AI- or user-generated text before display —
    not needed for the app's own hardcoded labels, but cheap either way.
    """
    return (text or "").replace("$", "\\$")


@st.cache_resource
def get_db() -> Database:
    db = Database()
    # One snapshot per calendar day, taken on first open. Cheap on every
    # subsequent open, and it means the compliance record survives the laptop.
    try:
        auto_snapshot(db.conn, db.path)
    except (OSError, sqlite3.Error):
        # A backup problem must never stop the family using the app; the
        # Compliance page surfaces the real state of the backups.
        pass
    return db


def page_setup(title: str, icon: str = "🧭") -> tuple[Database, dict[str, Any]]:
    st.set_page_config(page_title=f"Compass — {title}", page_icon=icon, layout="wide")
    db = get_db()
    student = db.ensure_default_student()
    # Always present, not opt-in -- the Travel Journal runs all year long,
    # same as any other Big Project, so there's no button gating whether
    # its folder exists (see Database.ensure_travel_log_project). Cheap:
    # a single lookup by kind once it's already there.
    db.ensure_travel_log_project(student["id"])
    # Before anything renders, so the page never flashes unstyled.
    st.markdown(theming.css(), unsafe_allow_html=True)
    _sidebar(db, student)
    # Any page reached from a hub (not its own sidebar entry) gets its way back
    # automatically -- a page that isn't in the sidebar must never be a dead
    # end, and that's a property of the page's place in the app, not something
    # each page should have to remember to add by hand.
    _render_hub_back(title)
    return db, student


# Pages that live behind a hub rather than their own sidebar entry, mapped to
# the hub they belong to -- keyed by the `title` each passes to page_setup. Add
# a page here (or fold one behind a hub) and it gets a "← Back to <hub>" button
# for free; nothing renders for a top-level page that isn't listed.
_HUB_BACK: dict[str, tuple[str, str]] = {
    # The four core subjects live behind the Courses hub.
    "Math": ("Courses", "pages/17_Courses.py"),
    "Science": ("Courses", "pages/17_Courses.py"),
    "English": ("Courses", "pages/17_Courses.py"),
    "History": ("Courses", "pages/17_Courses.py"),
    # The parent-admin pages live behind Mission Control.
    "Course records": ("Mission Control", "pages/14_Mission_Control.py"),
    "Student Profile": ("Mission Control", "pages/14_Mission_Control.py"),
    "Compliance": ("Mission Control", "pages/14_Mission_Control.py"),
    "Model Costs": ("Mission Control", "pages/14_Mission_Control.py"),
}


def _render_hub_back(title: str) -> None:
    """The automatic "back" affordance for a hub-reached page (see `_HUB_BACK`).
    No-op for a top-level page. One shared key so a page never accidentally
    stacks two."""
    target = _HUB_BACK.get(title)
    if target is None:
        return
    hub_label, hub_path = target
    if st.button(f"← Back to {hub_label}", key="hub_back"):
        st.switch_page(hub_path)


# --- parent / student mode ---------------------------------------------------
#
# When a PIN is set, every new browser session starts in student mode. That's the
# right default: he opens the app far more often than you do, and the failure that
# matters is the answer key being visible when nobody meant it to be.


def is_parent() -> bool:
    """True when parent-only content should be shown."""
    db = get_db()
    if not auth.pin_is_set(db):
        return True  # No PIN configured — the app behaves as it always has.
    return bool(st.session_state.get("parent_unlocked", False))


# Two entry points, one app. The plain URL is Landon's -- it never offers any
# way to unlock the parent view, so he can't wander into it (nor even see that
# it's there). The parent's own bookmark carries `?view=parent`, and that is the
# only place the PIN unlock (and, before a PIN exists, the PIN setup) appears.
# This is UX separation on top of the real gate, not the gate itself: parent
# content is still PIN-checked by is_parent()/parent_only(), so the query string
# reveals the unlock box, it does not grant access. Reported directly: "the
# current one remains unchanged and will be the student only link, but it loses
# the option to login as parent. that parent link will be a new entry point ...
# for me only."
_PARENT_ENTRY_PARAM = "view"
_PARENT_ENTRY_VALUE = "parent"


def parent_entry_requested() -> bool:
    """Whether this browser tab was opened from the parent link (`?view=parent`).

    Session-sticky: once opened from the parent link, later reruns and even
    in-app page navigation (which drops the query string) keep it, so the
    unlock box doesn't vanish mid-PIN-entry the first time Streamlit reruns."""
    if st.session_state.get("_parent_entry"):
        return True
    if st.query_params.get(_PARENT_ENTRY_PARAM) == _PARENT_ENTRY_VALUE:
        st.session_state["_parent_entry"] = True
        return True
    return False


def _render_nav() -> None:
    """The sidebar navigation, grouped rather than one flat list of every page.
    Reported: "there should be a home screen ... Then there should be a Courses
    button below Home. That should contain Math, Science, English and History,
    the core. Below that ... Big Projects and then Life Skills ... and Check In
    and Quizzes." The four core subjects fold under a "Courses" group so the
    daily-work pages read as one thing, not four peers of everything else.

    Built with st.page_link rather than the default file-based nav (which can't
    group or reorder), so the default nav is hidden in `_sidebar` and this is
    the whole nav. Mission Control is the one parent-only entry -- shown only
    when the parent view is unlocked; the other parent-admin pages are reached
    from Mission Control's own hub buttons, not the sidebar."""
    st.page_link("Home.py", label="Home", icon="🏠")
    # One "Courses" entry, not four subject entries -- it lands on the Courses
    # hub page (pages/17_Courses.py), which is itself just four buttons into
    # Math / Science / English / History. Reported: "button should be Courses
    # and then in the Courses page, there should be 4 buttons each subject."
    st.page_link("pages/17_Courses.py", label="Courses", icon="📚")
    st.page_link("pages/7_Big_Projects.py", label="Big Projects", icon="🎬")
    st.page_link("pages/6_Life_Skills.py", label="Life Skills", icon="🛠️")
    st.page_link("pages/8_Check_In.py", label="Check In", icon="💬")
    st.page_link("pages/16_Quizzes.py", label="Quizzes", icon="📝")
    if is_parent():
        st.divider()
        st.page_link("pages/14_Mission_Control.py", label="Mission Control", icon="🚀")


# Hide Streamlit's own file-based sidebar nav entirely -- `_render_nav` replaces
# it with a grouped, reordered one. Kept separate from the per-link hiding below
# (still applied, harmlessly, as belt-and-suspenders) so the intent reads
# clearly: the default nav is gone, and what shows is exactly what _render_nav
# draws.
_HIDE_DEFAULT_NAV_CSS = """
<style>
div[data-testid="stSidebarNav"] { display: none !important; }
</style>
"""


def _sidebar(db: Database, student: dict[str, Any]) -> None:
    with st.sidebar:
        st.markdown(_HIDE_DEFAULT_NAV_CSS, unsafe_allow_html=True)
        st.markdown(f"### 🧭 Compass\n**{md(student['name'])}** · Grade {student['grade']}")
        _render_nav()
        st.divider()
        start, end = db.school_year_bounds()
        st.caption(f"School year {start} → {end}")
        st.divider()
        _mode_control(db, student)
    _hide_folded_in_nav()
    _hide_parent_only_nav()


# Pages that are entirely parent admin -- record-keeping, settings, spend --
# rather than something he does. Each already gates its own content behind
# parent_only(), so hiding the tab is UX cleanup on top of that, not the only
# thing standing between him and it: typing the URL directly still hits the
# same PIN gate the tab would have.
# Mission Control is the parent's hub and stays in the sidebar (hidden only
# from the student); the other parent-admin pages now fold into it as buttons
# (see _FOLDED_IN_PAGES) rather than each keeping its own sidebar entry.
_PARENT_ONLY_PAGES = (
    "Mission_Control",
)

# Folded into another page rather than removed -- Choice Topics and Coding
# Camp now live as tabs on Life Skills (same "his to pick"/"you decide" list,
# same active/backlog gate), and the Travel Journal always sits inside Big
# Projects as its own project (see Database.ensure_travel_log_project).
# Hidden from the top-level nav for both of you, not just for him -- the
# whole point was fewer sidebar entries, and a parent reaches all three
# through the page that now hosts them. Neither page file is deleted here
# for Travels (still real, still linked to from the Big Projects card);
# Choice Topics' and Coding's own pages are gone entirely -- see
# render_choice_topics_section/the Coding tab on pages/6_Life_Skills.py.
_FOLDED_IN_PAGES = (
    "Choice_Topics",
    "Landons_Travels",
    "Coding",
    # The parent-admin pages: still full pages, but reached by a button row on
    # Mission Control (see pages/14_Mission_Control.py) rather than their own
    # sidebar entries -- the sidebar is now just the student's own subjects.
    "Course_Records",
    "Student_Profile",
    "Compliance",
    "Model_Costs",
    # The four core subjects fold under the Courses hub page (pages/17_Courses.py,
    # its own nav entry) -- reached by that page's buttons, not the sidebar.
    "Math",
    "Science",
    "English",
    "History",
)


def _hide_folded_in_nav() -> None:
    selector = ", ".join(
        f'a[data-testid="stSidebarNavLink"][href$="/{slug}"]' for slug in _FOLDED_IN_PAGES
    )
    st.markdown(
        f"<style>{selector} {{ display: none !important; }}</style>",
        unsafe_allow_html=True,
    )


def _hide_parent_only_nav() -> None:
    if is_parent():
        return
    selector = ", ".join(
        f'a[data-testid="stSidebarNavLink"][href$="/{slug}"]' for slug in _PARENT_ONLY_PAGES
    )
    st.markdown(
        f"""<style>
        {selector} {{ display: none !important; }}
        </style>""",
        unsafe_allow_html=True,
    )


def _profile_control(db: Database, student: dict[str, Any]) -> None:
    """Point at the dedicated Student Profile page rather than editing here.

    Parent-only: the profile (including interests) feeds every agent's
    system prompt, so this is configuration, not a preference — the same
    reasoning that keeps Tier 1 strategy choices out of student hands. Used
    to be a cramped inline form (a single small textarea for interests);
    moved to its own page for room to list interests individually instead
    of hand-editing one run-on blob of text.
    """
    if not is_parent():
        return
    st.page_link("pages/12_Student_Profile.py", label="Edit his profile", icon="✏️")


def _mode_control(db: Database, student: dict[str, Any]) -> None:
    if not auth.pin_is_set(db):
        st.caption("**Parent view** — everything visible.")
        with st.expander("Set a parent PIN"):
            st.caption(
                "Hides answer keys, mastery criteria, and parent notes from the student "
                "view, and keeps lesson generation and the records behind a PIN."
            )
            pin = st.text_input("New PIN", type="password", key="pin_new")
            again = st.text_input("Confirm", type="password", key="pin_again")
            if st.button("Turn on student view"):
                if pin != again:
                    st.error("Those don't match.")
                else:
                    try:
                        auth.set_pin(db, pin)
                    except auth.PinError as exc:
                        st.error(str(exc))
                    else:
                        st.session_state["parent_unlocked"] = True
                        st.success("Student view is on. Write the PIN down somewhere.")
                        st.rerun()
        return

    if is_parent():
        # One grouping for every parent-only control instead of a loose stack
        # of buttons in the sidebar (reported: "all these parent only sidebar
        # buttons can be consolidated into ... grouping there"). Profile edit,
        # the view switch, and PIN management all live under one expander. The
        # PIN fields sit inline here rather than in their own nested expander --
        # Streamlit can't nest expanders, and this is tidier anyway.
        with st.expander("🔓 Parent settings", expanded=False):
            _profile_control(db, student)
            if st.button("Switch to student view", width="stretch"):
                st.session_state["parent_unlocked"] = False
                st.rerun()
            st.divider()
            st.caption("**Change or remove the PIN**")
            current = st.text_input("Current PIN", type="password", key="pin_cur")
            replacement = st.text_input("New PIN (blank to remove)", type="password", key="pin_rep")
            if st.button("Save", key="pin_save"):
                if not auth.verify(db, current):
                    st.error("That PIN is not right.")
                elif replacement.strip() == "":
                    auth.clear_pin(db)
                    st.success("PIN removed — everything is visible again.")
                    st.rerun()
                else:
                    try:
                        auth.set_pin(db, replacement)
                    except auth.PinError as exc:
                        st.error(str(exc))
                    else:
                        st.success("PIN changed.")
                        st.rerun()
        return

    st.caption("🎒 **Student view**")
    # The unlock only exists on the parent entry point (`?view=parent`). On
    # Landon's own link there is no way in and nothing to hint one exists.
    if not parent_entry_requested():
        return
    with st.expander("Parent unlock", expanded=True):
        pin = st.text_input("PIN", type="password", key="pin_unlock")
        if st.button("Unlock", width="stretch"):
            if auth.verify(db, pin):
                st.session_state["parent_unlocked"] = True
                st.rerun()
            else:
                st.error("Not right. Try again.")


def parent_only(message: str = "") -> bool:
    """Guard for a whole page. Returns True when the parent view is active."""
    if is_parent():
        return True
    st.info(
        message
        or "This part is for your parent. Use **Parent unlock** in the sidebar if that's you."
    )
    return False


def context_for(
    db: Database, student: dict[str, Any], **inputs: Any
) -> StudentContext:
    return StudentContext(
        db=db, student_id=student["id"], student=student, inputs=inputs
    )


# --- the generate → review → log loop ----------------------------------------


def generate_series_and_log(
    db: Database,
    student: dict[str, Any],
    agent: LessonAgent,
    ctx: StudentContext,
    proposal: Any,
    *,
    primary_subject: str,
    spinner: str,
    api_ok: bool,
) -> None:
    """Generate a whole topic as a multi-day series in one click.

    The parent picks the topic (the `proposal`); the generator decides how many
    days it needs and writes each as a full fixed-shape lesson. The days carry
    no calendar date -- they queue for him in order and he works through them one
    at a time -- so there's nothing here to schedule and no per-lesson hours form
    (hours log when each day is approved in review). Reported: for math "no
    reason to have days associated with it ... just pick a topic and chunk it out
    by however many days it takes."
    """
    state_key = f"{agent.key}_series"

    pending = [
        lesson
        for lesson in db.list_lessons(student["id"], agent=agent.key, limit=20)
        if lesson["status"] in ("planned", "submitted", "needs_revision")
    ]
    if pending:
        st.warning(
            f"⚠️ **{len(pending)}** {agent.name.replace(' Agent', '')} lesson(s) are already "
            "open for him. Generating a new series adds to that queue — clear or review the "
            "open ones from Mission Control → Review first if you don't want them stacking up."
        )

    # How many lessons: default lets the generator size the topic, but a parent
    # can force a count -- a book report or a one-off is a single lesson, while a
    # broad skill wants several (reported: "i should be able to choose how many
    # lessons to generate ... a book report style should be a single lesson").
    _DAYS_AUTO = "Let the generator decide"
    days_choice = st.selectbox(
        "How many lessons?",
        [_DAYS_AUTO, *range(1, 9)],
        format_func=lambda v: v if v == _DAYS_AUTO else (
            "1 lesson (single)" if v == 1 else f"{v} lessons"
        ),
        key=f"{agent.key}_series_days",
        help="Leave on auto for the generator to size it, or pick a number — "
        "1 for a book report or a one-off, more for a topic that needs building up.",
    )
    target_days = None if days_choice == _DAYS_AUTO else int(days_choice)
    # A skill-graph subject (math) genuinely needs building up; one lesson rarely
    # covers a skill well, so flag it rather than block it.
    if target_days == 1 and agent.key == "math":
        st.caption(
            "⚠️ Math skills usually need more than one lesson to teach and check — "
            "one is fine for a quick review, but consider letting it decide."
        )
    st.caption(
        "Generates the topic as day-sized lessons that land in the Board's Backlog "
        "for you to schedule."
    )
    if st.button(
        "✍️ Generate the full series",
        type="primary",
        disabled=not api_ok or proposal.blocked,
        key=f"{agent.key}_gen_series",
    ):
        with st.spinner(spinner):
            try:
                results = agent.generate_series(ctx, proposal, target_days=target_days)
            except LessonGenerationError as exc:
                st.error(str(exc))
                return
        st.session_state[state_key] = {
            "topic": proposal.topic,
            "days": [
                {
                    "title": r.payload.get("title") or "Lesson",
                    "focus": (r.proposal.metadata or {}).get("series_focus", "")
                    if hasattr(r.proposal, "metadata")
                    else "",
                    "warnings": r.warnings,
                }
                for r in results
            ],
        }
        st.rerun()

    summary = st.session_state.get(state_key)
    if not summary:
        return

    st.divider()
    days = summary["days"]
    st.success(
        f"✅ Generated **{len(days)}** {'day' if len(days) == 1 else 'days'} for "
        f"“{summary['topic']}.” They're waiting in the **Backlog** "
        "(Mission Control → 📋 Board) — assign each one to a day and he'll get it then, "
        "same as any other lesson."
    )
    for index, day in enumerate(days, start=1):
        st.markdown(f"**Day {index}.** {md(day['title'])}")
        if day.get("focus"):
            st.caption(md(day["focus"]))
        for warning in day.get("warnings") or []:
            st.caption(f"⚠️ {warning}")
    st.caption("Schedule them from the Board's Backlog, then grade each from Review as he turns it in.")
    if st.button("Clear this summary", key=f"{agent.key}_series_clear"):
        del st.session_state[state_key]
        st.rerun()


def difficulty_override_control(db: Database, key: str) -> str:
    """A per-generation difficulty override for one subject's Plan tab.

    Returns "" (meaning "use the family default") or a specific level key --
    feed it straight into context_for's `difficulty` input. Never sticky:
    each generation reads this fresh, so a one-off "Ease in" pick for a
    rough week can't quietly become the new normal without a parent
    actually choosing that on the Student Profile page.
    """
    default_level = db.get_setting("lesson_difficulty") or config.DIFFICULTY_STANDARD
    options = ["", *config.DIFFICULTY_LEVELS]
    return st.selectbox(
        "Difficulty for this lesson",
        options,
        format_func=lambda level: (
            f"Use family default ({config.difficulty_label(default_level)})"
            if level == ""
            else config.difficulty_label(level)
        ),
        key=key,
        help="Just this one lesson -- change the family default on the Student Profile page.",
    )


def render_subject_plan_panel(
    db: Database, student: dict[str, Any], agent_key: str, *, api_ok: bool
) -> None:
    """One subject's 'plan a lesson' panel: its own topic controls, then one
    click to generate the whole topic as a multi-day series.

    This is the single place a parent plans lessons -- broken out per subject in
    Mission Control's Plan view, after the old day-by-day week planner was
    removed (reported: "remove that 100% ... have the new plan a lesson to be in
    mission control and broken out for each subject"). Every widget key is
    prefixed with `agent_key` so all four panels can render on one page without
    colliding.
    """
    from compass.agents import get_agent

    agent = get_agent(agent_key)
    k = agent_key  # widget-key prefix
    difficulty = difficulty_override_control(db, key=f"{k}_difficulty")
    primary_subject = agent_key

    if agent_key == "math":
        from compass.curriculum import MATH_GRAPH, STRANDS, available_skills, missing_prerequisites

        mastered = db.mastered_skills(student["id"])
        ready_ids = {s.id for s in available_skills(mastered)}
        LET_AGENT = "Let the agent choose"
        all_skills = sorted(MATH_GRAPH.values(), key=lambda s: (s.strand, s.title))

        def _skill_label(skill) -> str:
            if skill.id in mastered:
                marker = "✅"
            elif skill.id in ready_ids:
                marker = "🔓"
            else:
                marker = "🔒"
            return f"{marker} {skill.title} — {STRANDS[skill.strand]}"

        columns = st.columns([2, 1])
        with columns[0]:
            choice = st.selectbox(
                "Skill",
                [LET_AGENT] + all_skills,
                format_func=lambda o: o if isinstance(o, str) else _skill_label(o),
                help="🔓 unlocked · ✅ mastered · 🔒 prerequisites not all met (you can still pick it).",
                key=f"{k}_skill",
            )
        with columns[1]:
            minutes = st.number_input(
                "Minutes / day", min_value=15, max_value=180, value=60, step=5, key=f"{k}_minutes"
            )
        parent_note = st.text_input(
            "Note for this lesson (optional)",
            placeholder="e.g. he struggled with negative signs last time",
            key=f"{k}_note",
        )
        skill_id = ""
        override_prereqs = False
        if choice != LET_AGENT:
            skill_id = choice.id
            locked_missing = missing_prerequisites(skill_id, mastered)
            if locked_missing and skill_id not in mastered:
                st.warning(
                    f"**{choice.title}** is out of sequence — these prerequisites aren't "
                    "mastered yet: "
                    + ", ".join(MATH_GRAPH[m].title for m in locked_missing)
                    + ". You can still teach it now; the lesson will scaffold what it leans on."
                )
                override_prereqs = st.checkbox(
                    "Generate it anyway (out of sequence)", key=f"{k}_override_prereqs"
                )
        ctx = context_for(
            db, student, minutes=minutes, parent_note=parent_note,
            skill_id=skill_id, override_prereqs=override_prereqs, difficulty=difficulty,
        )
    elif agent_key in ("science", "history"):
        location_label = (
            "Location-specific (optional)" if agent_key == "science"
            else "Location-specific (optional)"
        )
        placeholder = (
            "e.g. Olympic National Park, Hoh Rain Forest" if agent_key == "science"
            else "e.g. Whitman Mission, Walla Walla WA"
        )
        columns = st.columns([2, 1])
        with columns[0]:
            location = st.text_input(location_label, placeholder=placeholder, key=f"{k}_location")
        with columns[1]:
            minutes = st.number_input(
                "Minutes / day", min_value=15, max_value=240, value=75, step=15, key=f"{k}_minutes"
            )
        # Both emergent-path subjects get a first-class "change course" picker --
        # Science jumps to a new discipline, History to a new era. Reported:
        # "stuck in a period and not many options ... this should be an input I
        # can choose for all." Picking one starts a fresh path there.
        area_seed = ""
        picked_era = None
        if agent_key == "science":
            from compass.agents.science_agent import SCIENCE_AREAS

            area_choice = st.selectbox(
                "Jump to a new area of science (optional)",
                ["— continue the current path —", *[a[0] for a in SCIENCE_AREAS]],
                help="Switch the whole path -- e.g. move into life science or chemistry. "
                "It starts a fresh thread in that area, and later lessons branch off "
                "from there.",
                key=f"{k}_area",
            )
            area_seed = dict(SCIENCE_AREAS).get(area_choice, "")
        else:  # history
            from compass.agents.strategies import ERAS

            era_by_label = {label: key for key, label in ERAS}
            era_choice = st.selectbox(
                "Jump to a specific era (optional)",
                ["— least-covered era (let the timeline decide) —", *[lbl for _, lbl in ERAS]],
                help="Teach a period you choose instead of whatever the timeline says is "
                "furthest behind. Later lessons branch off from there.",
                key=f"{k}_era",
            )
            picked_era = era_by_label.get(era_choice)
        pool = db.unexplored_web_nodes(student["id"], agent_key, location or None)
        thread_label = "Which thread to pull" if agent_key == "science" else "Which thread to follow"
        thread_options = [(0, "Let the agent choose the next branch")] + [
            (n["id"], f"{'  ' * n.get('depth', 0)}{n['topic']}") for n in pool
        ]
        picked_id = st.selectbox(
            thread_label,
            [o[0] for o in thread_options],
            format_func=lambda i: dict(thread_options)[i],
            help="Open branches proposed by earlier lessons.",
            key=f"{k}_thread",
        )
        specific_seed = st.text_input(
            "Or a specific topic to start (optional)",
            placeholder=(
                "e.g. why nurse logs grow hemlocks and not spruce" if agent_key == "science"
                else "e.g. the 1855 Walla Walla Treaty Council"
            ),
            key=f"{k}_seed",
        )
        # Priority: a typed topic (most specific) wins, then a picked area/era,
        # then a chosen open thread -- so choosing a new path supersedes the
        # thread pick rather than fighting it.
        seed_topic = specific_seed.strip() or area_seed
        node_id = None if (seed_topic or picked_era) else (picked_id or None)
        parent_note = st.text_input("Note for this lesson (optional)", key=f"{k}_note")
        ctx = context_for(
            db, student, location=location, minutes=minutes, parent_note=parent_note,
            seed_topic=seed_topic, node_id=node_id, era=picked_era, difficulty=difficulty,
        )
    elif agent_key == "english":
        from compass.agents.strategies import ELA_FOCUS_ROTATION, STANDALONE_FOCUS_ROTATION

        book = db.current_book(student["id"])
        if not book:
            st.info(
                "No book is marked as currently being read, so this will be a standalone "
                "grammar/writing lesson instead — add one on the English page's **Books** tab "
                "for lessons tied to what he's actually reading."
            )
            focus_rotation = STANDALONE_FOCUS_ROTATION
        else:
            focus_rotation = ELA_FOCUS_ROTATION
        columns = st.columns([2, 1])
        with columns[0]:
            focus_labels = {key: text for key, text in focus_rotation}
            focus_choice = st.selectbox(
                "Focus",
                ["Let the agent rotate"] + list(focus_labels),
                format_func=lambda key: key if key == "Let the agent rotate" else focus_labels[key],
                key=f"{k}_focus",
            )
        with columns[1]:
            minutes = st.number_input(
                "Minutes / day", min_value=15, max_value=180, value=60, step=5, key=f"{k}_minutes"
            )
        if book:
            page_cols = st.columns(2)
            page = page_cols[0].number_input(
                "Current page", min_value=0, max_value=int(book["total_pages"] or 5000),
                value=int(book["current_page"] or 0),
                help="The agent will not reference anything past this page.",
                key=f"{k}_page",
            )
            if page != book["current_page"]:
                db.update_book(book["id"], current_page=int(page))
                book["current_page"] = int(page)
            rate = page_cols[1].number_input(
                "Pages per day (reading goal)", min_value=0, max_value=500,
                value=int(book.get("pages_per_day") or 0),
                help=(
                    "His daily reading target on Home ('read up to page N today'). "
                    "0 = no goal, just track the page. Also editable on the "
                    "English → Books tab."
                ),
                key=f"{k}_rate",
            )
            if rate != (book.get("pages_per_day") or 0):
                db.update_book(book["id"], pages_per_day=int(rate))
                book["pages_per_day"] = int(rate)
        seed_topic = st.text_input(
            "Or point this lesson at something specific (optional)",
            placeholder="e.g. the courtroom scene in chapter 12" if book else "e.g. writing a thank-you note",
            key=f"{k}_seed",
        )
        parent_note = st.text_input("Note for this lesson (optional)", key=f"{k}_note")
        ctx = context_for(
            db, student, minutes=minutes, parent_note=parent_note,
            focus="" if focus_choice == "Let the agent rotate" else focus_choice,
            seed_topic=seed_topic, difficulty=difficulty,
        )
        primary_subject = "reading" if book else "writing"
    else:
        st.error(f"Unknown subject: {agent_key}")
        return

    proposal = agent.propose_topic(ctx)
    render_proposal(agent, proposal)
    generate_series_and_log(
        db, student, agent, ctx, proposal,
        primary_subject=primary_subject,
        spinner="Planning the days and writing each lesson — this can take a few minutes.",
        api_ok=api_ok,
    )
    if agent_key == "english":
        st.caption(
            "Any `VOCAB:` lines in a day's materials are added to his spaced-repetition deck."
        )


# --- lesson rendering --------------------------------------------------------


def render_proposal(agent: LessonAgent, proposal) -> None:
    if proposal.blocked:
        st.warning(f"**{agent.name} can't plan a lesson yet.**\n\n{md(proposal.blocked_reason)}")
        return
    st.info(f"**Next up: {md(proposal.topic)}**\n\n{md(proposal.rationale)}")
    if proposal.context_lines:
        with st.expander("What the agent knows going in"):
            for line in proposal.context_lines:
                st.markdown(f"- {md(line)}")


def _needs_written_response(activity: dict[str, Any]) -> bool:
    """Whether this activity gets a typing box in place of a notebook page.

    Not the same question as `kind` -- `kind` describes what *sort* of
    activity this is (instruction/practice/reading/writing/...), while this
    is about whether it ends in something typeable at all, which the model
    is asked to flag directly via `requires_written_response` since a short
    answer just as often turns up buried inside an "instruction" or
    "practice" activity as inside one actually tagged `writing`. `kind ==
    "writing"` is kept as a second, always-true path for backward
    compatibility with lessons generated before that field existed.
    """
    return activity.get("kind") == "writing" or bool(
        activity.get("requires_written_response")
    )


def _has_answer_key(activity: dict[str, Any]) -> bool:
    """Whether this activity carries its own answer key -- the new fixed lesson
    shape, where each of the two comprehension activities is graded on its own.
    Old-shape activities have no `answer` and are graded by the lesson-wide
    `assessment` band instead, so this is what tells the two shapes apart."""
    return bool((activity.get("answer") or "").strip())


def _gradeable_activities(payload: dict[str, Any]) -> list[tuple[int, dict[str, Any]]]:
    """The activities a parent grades individually (new fixed shape): the ones
    carrying an answer key, in order, paired with their real indices so a
    recorded verdict lands on the right activity."""
    return [
        (index, activity)
        for index, activity in enumerate(payload.get("activities") or [])
        if _has_answer_key(activity)
    ]


def _activity_grades_recorded(metadata: dict[str, Any], payload: dict[str, Any]) -> int:
    """How many of a lesson's gradeable activities already have a verdict."""
    results = metadata.get("activity_results") or {}
    return sum(1 for index, _ in _gradeable_activities(payload) if str(index) in results)


def hand_in_activity_count(payload: dict[str, Any]) -> int:
    """How many activities in this lesson end in something he has to write and
    turn in -- i.e. how many separate pieces of work a parent should expect
    back to grade. Same predicate the student's own hand-in gate uses
    (`_needs_written_response`), so the count a parent is promised is exactly
    the number of typing boxes he has to fill."""
    return sum(
        1 for activity in (payload.get("activities") or [])
        if _needs_written_response(activity)
    )


def hand_in_summary(payload: dict[str, Any]) -> str:
    """A one-line, parent-facing count of what to expect back from a lesson --
    reported directly: "clearly tell parent, this should include 1 hand in or 2
    hand in activities." Empty string when there's nothing to hand in, so a
    caller can skip the line entirely rather than print a zero."""
    count = hand_in_activity_count(payload)
    if count == 0:
        return ""
    return f"📝 {count} hand-in activit{'y' if count == 1 else 'ies'} to review"


# --- life skills: the AI-drafted teaching plan ---------------------------------


def render_life_skill_plan(plan: dict[str, Any]) -> None:
    """Render a life-skill teaching plan. Parent-facing throughout.

    Unlike a Tier 1 lesson there's no student view of this and no redaction to
    do: a life skill is something the parent runs standing next to him, so the
    plan is addressed to them. Guard the call site, not the fields.
    """
    st.subheader(md(plan.get("title", "Session plan")))
    if plan.get("overview"):
        st.write(md(plan["overview"]))

    columns = st.columns(2)
    with columns[0]:
        prep = (plan.get("prep") or "").strip()
        if prep and prep.lower().rstrip(".") != "nothing":
            st.markdown("**Before you start**")
            st.write(md(prep))
    with columns[1]:
        materials = plan.get("materials") or []
        if materials:
            st.markdown("**What you need**")
            for item in materials:
                st.markdown(f"- {md(item)}")

    steps = plan.get("steps") or []
    if steps:
        st.markdown("**How to run it**")
        for index, step in enumerate(steps, start=1):
            header = f"{index}. {md(step.get('title', 'Step'))} · {step.get('minutes', 0)} min"
            with st.expander(header, expanded=False):
                st.markdown("**He does**")
                st.write(md(step.get("what_he_does", "")))
                st.markdown("**You do**")
                st.write(md(step.get("what_you_do", "")))

    if plan.get("done_looks_like"):
        st.success(f"**Done looks like:** {md(plan['done_looks_like'])}")

    watch_for = plan.get("watch_for") or []
    if watch_for:
        with st.expander(f"Where this goes wrong ({len(watch_for)})"):
            for item in watch_for:
                st.markdown(f"- {md(item)}")

    follow_ups = plan.get("follow_ups") or []
    if follow_ups:
        with st.expander("Making it stick"):
            for item in follow_ups:
                st.markdown(f"- {md(item)}")

    credits = plan.get("subject_credits") or []
    if credits:
        st.markdown("**Subject credit (feeds the WA compliance dashboard)**")
        for credit in credits:
            st.markdown(
                f"- **{subjects.label(credit['subject'])}** — {credit['minutes']} min · "
                f"{credit.get('justification', '')}"
            )


# --- Coding Camp: the AI-drafted build guide -------------------------------------


def render_coding_plan(plan: dict[str, Any]) -> None:
    """Render a coding module's build guide.

    Unlike render_life_skill_plan, this one is meant for *him* -- he builds
    a module himself, at a computer, without a parent required to be there,
    so the whole guide (including each step's own code example) is written
    to and shown to him directly. There's no answer key here to redact:
    this is instructional content, the actual "how to do this" the parent
    asked for, not an assessment with a hidden answer -- see
    compass.agents.coding's own module docstring.
    """
    st.subheader(md(plan.get("title", "Build guide")))
    if plan.get("overview"):
        st.write(md(plan["overview"]))

    concepts = plan.get("concepts") or []
    if concepts:
        st.markdown("**What you'll need to know**")
        for concept in concepts:
            st.markdown(f"**{md(concept.get('name', ''))}** — {md(concept.get('explanation', ''))}")

    steps = plan.get("steps") or []
    if steps:
        st.markdown("**How to build it**")
        for index, step in enumerate(steps, start=1):
            header = f"{index}. {md(step.get('title', 'Step'))} · {step.get('minutes', 0)} min"
            with st.expander(header, expanded=False):
                st.write(md(step.get("instructions", "")))
                if step.get("example"):
                    st.code(step["example"])

    if plan.get("done_looks_like"):
        st.success(f"**Done looks like:** {md(plan['done_looks_like'])}")

    common_mistakes = plan.get("common_mistakes") or []
    if common_mistakes:
        with st.expander(f"Where this goes wrong ({len(common_mistakes)})"):
            for item in common_mistakes:
                st.markdown(f"- {md(item)}")

    stretch_goals = plan.get("stretch_goals") or []
    if stretch_goals:
        with st.expander("Want to keep going?"):
            for item in stretch_goals:
                st.markdown(f"- {md(item)}")

    parent_note = (plan.get("parent_note") or "").strip()
    if parent_note and parent_note.lower().rstrip(".") != "nothing" and is_parent():
        st.caption(f"👤 Parent note: {md(parent_note)}")

    credits = plan.get("subject_credits") or []
    if credits and is_parent():
        st.markdown("**Subject credit (feeds the WA compliance dashboard)**")
        for credit in credits:
            st.markdown(
                f"- **{subjects.label(credit['subject'])}** — {credit['minutes']} min · "
                f"{credit.get('justification', '')}"
            )


# --- logging hours against a lesson --------------------------------------------


def log_lesson_form(
    db: Database,
    student: dict[str, Any],
    generated: GeneratedLesson,
    source: str,
    primary_subject: str,
    location: str = "",
    key_prefix: str = "log",
    tier: str = config.TIER_CORE,
) -> None:
    """Let the parent confirm and log the hours this lesson actually took."""
    lesson = generated.payload
    st.markdown("### Log this as completed")
    st.caption(
        "Edit the minutes to what it actually took. Total minutes count toward the "
        "1,000-hour floor; the per-subject numbers are the multi-subject credit."
    )

    with st.form(f"{key_prefix}_form_{generated.lesson_id}"):
        columns = st.columns(3)
        with columns[0]:
            occurred_on = st.date_input("Date", value=date.today())
        with columns[1]:
            minutes = st.number_input(
                "Total minutes",
                min_value=5,
                max_value=600,
                value=int(lesson.get("estimated_minutes") or 60),
                step=5,
            )
        with columns[2]:
            where = st.text_input("Location", value=location)

        st.markdown("**Subject credit**")
        credits: dict[str, int] = {}
        for credit in lesson.get("subject_credits") or []:
            credits[credit["subject"]] = st.number_input(
                subjects.label(credit["subject"]),
                min_value=0,
                max_value=600,
                value=int(credit["minutes"]),
                step=5,
                key=f"{key_prefix}_credit_{generated.lesson_id}_{credit['subject']}",
            )

        submitted = st.form_submit_button("Log hours", type="primary")

    if submitted:
        db.log_activity(
            student_id=student["id"],
            title=lesson.get("title", "Lesson"),
            tier=tier,
            primary_subject=primary_subject,
            minutes=int(minutes),
            subject_credits={k: v for k, v in credits.items() if v > 0},
            occurred_on=occurred_on.isoformat(),
            description=lesson.get("overview", ""),
            source=source,
            location=where,
            lesson_id=generated.lesson_id,
        )
        st.success("Logged. The compliance dashboard is updated.")


# --- the in-lesson quiz ---------------------------------------------------------


def format_duration(seconds: int) -> str:
    minutes, secs = divmod(max(int(seconds), 0), 60)
    if minutes and secs:
        return f"{minutes} min {secs} sec"
    if minutes:
        return f"{minutes} min"
    return f"{secs} sec"


def _quiz_attempt_note(db: Database, student_id: int, lesson_id: int) -> tuple[str, bool]:
    """What the *next* attempt at this quiz is worth, and whether it counts.

    Returns `(sentence, graded)`. The retry stays available in every case --
    blocking practice to protect a number is backwards -- but he should never
    have to guess whether the run he's about to take changes anything.
    """
    deduction = db.get_int_setting("quiz_retry_deduction_percent")
    floor = db.get_int_setting("quiz_retry_floor_percent")
    limit = config.GRADED_QUIZ_ATTEMPTS
    attempts = list(reversed(db.list_quiz_attempts(student_id, lesson_id=lesson_id)))
    banked, used = grades.quiz_score(attempts, deduction, floor, limit)

    if not grades.can_improve(attempts, deduction, floor, limit):
        if used >= limit:
            return (
                f"That's all {limit} graded attempts — your grade for this quiz is "
                f"locked in at {banked:.0f}%. Practice as much as you want.",
                False,
            )
        return (
            f"You've already banked {banked:.0f}% here — another go is practice, "
            "it won't change your grade.",
            False,
        )

    if used == 0:
        return ("First try — it counts in full toward your grade.", True)
    worth = round(100 * grades.attempt_multiplier(used + 1, deduction, floor))
    return (
        f"Attempt {used + 1} of {limit} — worth up to {worth}% toward your grade. "
        "Your best attempt is the one that counts, so a rough run can't drag it down.",
        True,
    )


def render_quiz(
    db: Database,
    student: dict[str, Any],
    lesson_id: int,
    metadata: dict[str, Any],
    quiz: list[dict[str, Any]],
    agent: str | None = None,
) -> None:
    """The student's self-graded check on this lesson's content.

    The only thing standing between him and the answer key is that this
    function never writes a `correct_index` anywhere onto the page until after
    he submits. No CSS trick is needed for that part: Streamlit reruns this
    whole function on every interaction, so as long as the ungraded branch
    below never puts `correct_index` into a widget or a string, it never
    reaches the browser either — the answer simply isn't there to find, the
    same reasoning `render_lesson`'s redaction relies on.

    The `user-select: none` below is a separate, much weaker measure against
    copying the question text out to search for it — real friction, like the
    PIN, not a lock that can't be picked.

    Collapsed by default, in its own keyed expander with `on_change="rerun"`
    -- opening it is a deliberate action (unlike the lesson content sitting
    above it, which he's already looking at for other reasons), so the
    moment he expands it is a real start-of-quiz signal, stashed in session
    state and turned into `duration_seconds` at submission. Not literally
    "time from his first click," which the quiz form can't see -- the whole
    form lives inside one `st.form`, so nothing about individual picks
    reaches the server until Submit either way -- but close: he can't
    answer anything before opening it.
    """
    if not quiz:
        return

    state_key = f"quiz_result_{lesson_id}"
    result = st.session_state.get(state_key)
    start_key = f"quiz_started_at_{lesson_id}"
    expander_key = f"quiz_expander_{lesson_id}"

    # The five questions this sitting actually asks, drawn from the lesson's
    # pool and rotated by how many times he's already taken it. Pinned into
    # session state the first time rather than recomputed: this function
    # re-runs on every interaction, and the results view below has to grade
    # and review the same questions he answered, not a freshly dealt set.
    # Cleared by "Try again", which is what advances the rotation.
    asked_key = f"quiz_asked_{lesson_id}"
    if asked_key not in st.session_state:
        attempt = len(db.list_quiz_attempts(student["id"], lesson_id=lesson_id))
        st.session_state[asked_key] = select_questions(quiz, attempt, seed=lesson_id)
    quiz = st.session_state[asked_key]

    # Only the four Tier 1 subjects carry a grade, so only they get the
    # grade language -- a Life Skills quiz saying "worth 90% toward your
    # grade" would be inventing a grade that doesn't exist.
    graded_subject = agent in gradebook.GRADED_AGENTS

    st.divider()
    with st.expander("📝 Check your understanding", key=expander_key, on_change="rerun"):
        if st.session_state.get(expander_key) and start_key not in st.session_state:
            st.session_state[start_key] = time.time()

        with st.container(key=f"quiz_nocopy_{lesson_id}"):
            st.markdown(
                f"<style>.st-key-quiz_nocopy_{lesson_id} "
                "{ -webkit-user-select: none; user-select: none; }</style>",
                unsafe_allow_html=True,
            )

            if result is None:
                if graded_subject:
                    note, counts = _quiz_attempt_note(db, student["id"], lesson_id)
                    (st.info if counts else st.caption)(note)
                picks: list[int | None] = []
                with st.form(f"quiz_form_{lesson_id}"):
                    for index, item in enumerate(quiz):
                        st.markdown(f"**{index + 1}. {md(item['question'])}**")
                        pick = st.radio(
                            "choices",
                            options=list(range(len(item["choices"]))),
                            format_func=lambda i, choices=item["choices"]: md(choices[i]),
                            index=None,
                            label_visibility="collapsed",
                            key=f"quiz_pick_{lesson_id}_{index}",
                        )
                        picks.append(pick)
                    submitted = st.form_submit_button("Submit quiz", type="primary")

                if not submitted:
                    return
                if any(pick is None for pick in picks):
                    st.warning("Answer every question before submitting.")
                    return

                correct, total = grade_quiz(quiz, picks)
                threshold = db.get_int_setting("quiz_pass_percent")
                did_pass = quiz_passes(correct, total, threshold)
                started_at = st.session_state.pop(start_key, None)
                duration_seconds = int(time.time() - started_at) if started_at else None

                # Anti-rushing: a real read of five questions and their choices
                # takes more than a handful of seconds. Below the per-question
                # floor, refuse the submission, keep his answers, and put the
                # clock back so the wait counts down rather than restarting --
                # reported directly, "hes completing them in under 60 seconds."
                min_seconds = db.get_int_setting("quiz_min_seconds_per_question") * len(quiz)
                if duration_seconds is not None and min_seconds and duration_seconds < min_seconds:
                    st.session_state[start_key] = started_at
                    st.warning(
                        f"⏳ Slow down — that was only {duration_seconds}s. Read each "
                        f"question and every choice carefully, then submit "
                        f"(about {max(0, min_seconds - duration_seconds)}s to go)."
                    )
                    return

                st.session_state[state_key] = {
                    "picks": picks,
                    "correct": correct,
                    "duration_seconds": duration_seconds,
                    "graded_wall": time.time(),
                }
                detail = [
                    {
                        "question": item["question"],
                        "choices": item["choices"],
                        "correct_index": item["correct_index"],
                        "pick": pick,
                        "explanation": item.get("explanation", ""),
                    }
                    for item, pick in zip(quiz, picks)
                ]
                # Records the attempt AND reconciles Math mastery in one place
                # (db._reconcile_math_mastery): a perfect quiz masters the skill,
                # a below-pass quiz un-masters one he'd mastered. The UI no longer
                # touches mastery itself, so the two rules can't drift apart.
                db.record_quiz_result(
                    lesson_id, student["id"], correct, total, did_pass,
                    detail=detail, duration_seconds=duration_seconds,
                )

                # If the quiz was the one thing left, the lesson's now
                # complete from his side -- hand it straight to the parent
                # instead of leaving it parked on a "Turn it in" button he
                # already thinks he's past. Same rule the writing submit
                # uses; whichever piece he finishes last does this.
                if _maybe_auto_submit_lesson(db, lesson_id):
                    st.toast("Lesson turned in for review 📬")
                st.rerun()
                return

            picks = result["picks"]
            correct, total = result["correct"], len(quiz)
            threshold = db.get_int_setting("quiz_pass_percent")
            did_pass = quiz_passes(correct, total, threshold)
            pct = round(100 * correct / total)
            skill_id = metadata.get("skill_id")
            mastery_threshold = db.get_int_setting("math_mastery_percent") if skill_id else None
            fully_mastered = bool(skill_id) and quiz_passes(correct, total, mastery_threshold)

            if not did_pass:
                st.warning(
                    f"**{correct} / {total} correct ({pct}%)** — under the "
                    f"{threshold}% needed to pass. Ask your parent about another go."
                )
            elif skill_id and not fully_mastered:
                st.success(
                    f"**{correct} / {total} correct ({pct}%)** — nice work, that's a pass."
                )
                st.caption(
                    f"Mastery on this skill needs {mastery_threshold}% -- try again to lock "
                    "it in before moving on."
                )
            else:
                st.success(f"**{correct} / {total} correct ({pct}%)** — nice work.")
                if skill_id:
                    st.caption("Counted toward mastery of this skill.")

            duration_seconds = result.get("duration_seconds")
            if duration_seconds is not None:
                st.caption(f"⏱️ Took {format_duration(duration_seconds)}")

            if graded_subject:
                # The banked number, not just this sitting's raw score. On a
                # retry the two differ (this run is weighted, and the best
                # attempt is what counts), and quietly showing only the raw
                # percent after a deducted attempt would misstate the grade.
                deduction = db.get_int_setting("quiz_retry_deduction_percent")
                floor = db.get_int_setting("quiz_retry_floor_percent")
                attempts = list(
                    reversed(db.list_quiz_attempts(student["id"], lesson_id=lesson_id))
                )
                banked, used = grades.quiz_score(
                    attempts, deduction, floor, config.GRADED_QUIZ_ATTEMPTS
                )
                if banked is not None:
                    suffix = f" (best of {used} attempts)" if used > 1 else ""
                    st.caption(
                        f"📊 Toward your grade: **{banked:.0f}%**{suffix} — "
                        f"{config.letter_for(banked)}"
                    )

            for index, item in enumerate(quiz):
                pick = picks[index]
                right = pick == item["correct_index"]
                marker = "✅" if right else "❌"
                with st.expander(
                    f"{marker} {index + 1}. {md(item['question'])}", expanded=False
                ):
                    for choice_index, choice in enumerate(item["choices"]):
                        tag = ""
                        if choice_index == item["correct_index"]:
                            tag = " — correct answer"
                        elif choice_index == pick:
                            tag = " — your answer"
                        st.markdown(f"- {md(choice)}{tag}")
                    if item.get("explanation"):
                        st.caption(md(item["explanation"]))

            retry_label = "Try again"
            if graded_subject:
                note, counts = _quiz_attempt_note(db, student["id"], lesson_id)
                if not counts:
                    retry_label = "Practice again — won't change your grade"
                st.caption(note)

            # Anti-rushing, part two: after a miss, make him sit with what he
            # got wrong before firing off another guess -- the report that
            # prompted this had three retries in under 90s each, scores going
            # 3/5 -> 2/5 -> 2/5. "Try again" is locked for a short cooldown;
            # reviewing the missed questions above (each click reruns the page)
            # is exactly what counts it down, so the pause is spent looking, not
            # waiting. Passing attempts and practice retries are never gated.
            retry_disabled = False
            cooldown = db.get_int_setting("quiz_retry_cooldown_seconds")
            if not did_pass and cooldown:
                elapsed = time.time() - result.get("graded_wall", 0)
                remaining = int(cooldown - elapsed)
                if remaining > 0:
                    retry_disabled = True
                    st.caption(
                        f"⏳ Look back at what you missed above — **Try again** unlocks "
                        f"in about {remaining}s."
                    )
            if st.button(retry_label, key=f"quiz_retry_{lesson_id}", disabled=retry_disabled):
                del st.session_state[state_key]
                st.session_state.pop(start_key, None)
                # Dropping the pinned set is what advances the rotation --
                # the next render re-derives it from a now-higher attempt
                # count and deals different questions.
                st.session_state.pop(asked_key, None)
                st.rerun()


# --- the student's own lesson view: current + reopenable past lessons ----------


def _done_lessons(db: Database, student_id: int, agent_key: str) -> list[dict[str, Any]]:
    lessons = db.list_lessons(student_id, agent=agent_key, limit=10)
    return [l for l in lessons if l["status"] == "completed"]


def _lesson_ready_to_submit(lesson: dict[str, Any]) -> tuple[bool, str]:
    """Whether "Turn it in" will actually do anything yet -- the quiz (if
    this lesson has one) taken at least once, and every writing activity
    at least submitted. Doesn't require anything be *approved* -- that's
    the parent's call once it's turned in, not a bar he clears himself.

    A writing activity still sitting at `needs_revision` -- a parent
    bounced it and he hasn't clicked "Submit for review" again yet, with
    or without actually editing it -- is just as not-ready as one still at
    the untouched `draft` default. Checking for "not draft" instead of "is
    submitted or approved" used to let this slip through: the lesson-level
    gate would read the whole lesson as ready the instant it came back
    from a bounce, even though the one thing that was flagged was
    untouched, letting him hand the whole lesson straight back to
    "Needs your attention now" with nothing actually revised.
    """
    metadata = lesson.get("metadata") or {}
    payload = lesson["payload"]
    if (payload.get("quiz") or []) and not metadata.get("quiz_result"):
        return False, "Take the quiz below before you turn this in."
    review_map = metadata.get("writing_review") or {}
    for index, activity in enumerate(payload.get("activities") or []):
        if not _needs_written_response(activity):
            continue
        status = review_map.get(str(index), {}).get("status", config.WRITING_DRAFT)
        if status not in (config.WRITING_SUBMITTED, config.WRITING_APPROVED):
            return False, "Submit every written response below before you turn this in."
    return True, ""


def _maybe_auto_submit_lesson(db: Database, lesson_id: int) -> bool:
    """Turn the whole lesson in the instant its last piece is done, without
    making him hunt for a separate button.

    His mental model is "I finished my writing / my quiz, so I'm done" --
    but submitting a writing response (set_writing_review) and taking the
    quiz (record_quiz_result) each only move their own piece, never the
    lesson. The lesson-level "Turn it in for review" button was the only
    thing that moved status -> submitted, and it lives out of sight below
    the fold on the subject page and not at all in the board's full-lesson
    dialog. The result a parent actually hit: he'd submit his English
    writing, believe he'd handed it in, and it would sit at 'planned'
    forever, never reaching the review queue.

    So whichever piece he finishes last quietly turns the lesson in for
    him, but only once the same gate the manual button uses
    (_lesson_ready_to_submit) reads the whole lesson as genuinely ready --
    quiz taken if there is one, every written response submitted. Fires
    only from 'planned'/'needs_revision'; anything already submitted or
    resolved is left alone. The manual button stays for the one shape this
    can't cover on its own -- a lesson with neither a quiz nor any writing,
    which is ready the moment it's opened and so has no "last piece" to key
    off of.
    """
    lesson = db.get_lesson(lesson_id)
    if lesson is None or lesson["status"] not in ("planned", "needs_revision"):
        return False
    ready, _ = _lesson_ready_to_submit(lesson)
    if not ready:
        return False
    db.submit_lesson(lesson_id)
    return True


def render_lesson_resources(
    db: Database,
    lesson_id: int,
    metadata: dict[str, Any] | None,
    *,
    parent: bool,
) -> None:
    """Parent-added resources on a lesson -- your own links (a video, an
    article) or notes, on top of what the agent generated. Shows the list to
    everyone; on the parent side it also carries the add/remove controls. On his
    side it's read-only, and it renders nothing at all when there's nothing to
    show, so it stays invisible until you actually attach something."""
    resources = (metadata or {}).get("parent_resources") or []
    if not resources and not parent:
        return
    with st.container(border=True):
        st.markdown("**📎 Extra resources from your parent**")
        if not resources and parent:
            st.caption("Add a helpful video, article, or note for this lesson below.")
        for index, resource in enumerate(resources):
            label = resource.get("label") or resource.get("url") or "Resource"
            url = (resource.get("url") or "").strip()
            note = resource.get("note") or ""
            row = st.columns([9, 1]) if parent else [st.container()]
            if url:
                href = url if url.startswith(("http://", "https://")) else f"https://{url}"
                line = f"🔗 [{md(label)}]({href})"
            else:
                line = f"📝 **{md(label)}**"
            if note:
                line += f" — {md(note)}"
            row[0].markdown(line)
            if parent and row[1].button(
                "✕", key=f"rmres_{lesson_id}_{index}", help="Remove this resource"
            ):
                db.remove_lesson_resource(lesson_id, index)
                st.rerun()

        if parent:
            with st.expander("➕ Add a link or resource"):
                label = st.text_input("Title", key=f"addres_label_{lesson_id}")
                url = st.text_input(
                    "Link (optional)", key=f"addres_url_{lesson_id}",
                    placeholder="https://…",
                )
                note = st.text_input("Note (optional)", key=f"addres_note_{lesson_id}")
                if st.button("Add", key=f"addres_btn_{lesson_id}", type="primary"):
                    if label.strip() or url.strip() or note.strip():
                        db.add_lesson_resource(lesson_id, label, url, note)
                        st.rerun()
                    else:
                        st.caption("Add a title, a link, or a note first.")


def render_message_thread(db: Database, student: dict[str, Any], *, sender: str) -> None:
    """The parent <-> student chat, one thread per student. `sender` is who's
    looking ('parent' or 'student'); the same widget serves both sides. It's an
    expander that auto-opens with a count when there's something unread -- the
    in-app 'notification' -- shows the thread with read receipts on your own
    messages, a one-tap 'Got it' to clear what's new, and a box to reply."""
    viewer_is_parent = sender == "parent"
    student_name = student.get("name") or "your student"
    unread = db.unread_message_count(student["id"], sender)
    messages = db.list_messages(student["id"])

    title = f"💬 Messages — {unread} new" if unread else "💬 Messages"
    with st.expander(title, expanded=bool(unread)):
        if not messages:
            st.caption(
                "No messages yet — send the first one below."
                if viewer_is_parent
                else "No messages yet."
            )
        for message in messages:
            mine = message["sender"] == sender
            if mine:
                who = "You"
            else:
                who = student_name if viewer_is_parent else "Your parent"
            stamp = message["created_at"]
            when = stamp[5:16] if len(stamp) >= 16 else stamp  # MM-DD HH:MM
            is_new = (not mine) and not message.get("read_at")
            line = f"{'🔵 ' if is_new else ''}**{who}** · {when} — {md(message['body'])}"
            if mine and message.get("read_at"):
                line += "  ·  ✓ read"
            st.markdown(line)
            # A tagged lesson/activity, if this message references one: shown
            # under it with a jump link to that subject's page.
            if message.get("lesson_id"):
                ref = _message_reference(db, message)
                if ref:
                    ref_label, ref_page = ref
                    if ref_page:
                        st.page_link(ref_page, label=f"📎 Re: {ref_label}", icon="↗️")
                    else:
                        st.caption(f"📎 Re: {ref_label}")

        if unread:
            if st.button("👍 Got it", key=f"msg_gotit_{sender}"):
                db.mark_messages_read(student["id"], sender)
                st.rerun()

        # Optional: tag the message to a specific lesson (and an activity in it).
        # Outside the send form so picking a lesson can refresh the activity list.
        recent_lessons = [
            l for l in db.list_lessons(student["id"], limit=25)
            if (l.get("agent") or "") in _MESSAGE_TAG_PAGES
        ]
        tagged_lesson = st.selectbox(
            "📎 Tag a lesson (optional)",
            [None] + recent_lessons,
            format_func=lambda l: "— none —" if l is None else _message_lesson_label(l),
            key=f"msg_lesson_{sender}",
        )
        tagged_activity_index = None
        if tagged_lesson is not None:
            activities = (tagged_lesson.get("payload") or {}).get("activities") or []
            if activities:
                choice = st.selectbox(
                    "…and an activity? (optional)",
                    [None] + list(range(len(activities))),
                    format_func=lambda i: "Whole lesson"
                    if i is None
                    else f"Activity {i + 1}: {md(activities[i].get('title', 'Activity'))}",
                    key=f"msg_activity_{sender}",
                )
                tagged_activity_index = choice

        recipient = student_name if viewer_is_parent else "your parent"
        with st.form(f"msg_form_{sender}", clear_on_submit=True):
            body = st.text_input(
                f"Message {recipient}", key=f"msg_input_{sender}",
                placeholder="Type a message…",
            )
            sent = st.form_submit_button("Send", type="primary")
        if sent and body.strip():
            db.send_message(
                student["id"], sender, body,
                lesson_id=tagged_lesson["id"] if tagged_lesson else None,
                activity_index=tagged_activity_index,
            )
            # Reset the tag pickers so the next message starts clean.
            for tag_key in (f"msg_lesson_{sender}", f"msg_activity_{sender}"):
                st.session_state.pop(tag_key, None)
            st.rerun()


_MESSAGE_TAG_PAGES = {
    "math": "pages/1_Math.py",
    "science": "pages/2_Science.py",
    "english": "pages/3_English.py",
    "history": "pages/4_History.py",
}


def _message_lesson_label(lesson: dict[str, Any]) -> str:
    """A short 'Subject — Title' label for the message lesson picker."""
    title = (lesson.get("payload") or {}).get("title") or lesson.get("title") or "a lesson"
    subject = subjects.label(lesson.get("subject") or lesson.get("agent") or "")
    return f"{subject} — {md(title)}"


def _message_reference(
    db: Database, message: dict[str, Any]
) -> tuple[str, str | None] | None:
    """The (label, subject-page) a tagged message points at, or None if the
    lesson it referenced has since been deleted. The label reads 'Subject —
    Title[ · Activity N: ...]'; the page is the subject page to jump to, or None
    for a subject with no dedicated page."""
    lesson = db.get_lesson(message["lesson_id"])
    if not lesson:
        return None
    label = _message_lesson_label(lesson)
    index = message.get("activity_index")
    if index is not None:
        activities = (lesson.get("payload") or {}).get("activities") or []
        if 0 <= index < len(activities):
            act_title = activities[index].get("title") or "Activity"
            label += f" · Activity {index + 1}: {md(act_title)}"
        else:
            label += f" · Activity {index + 1}"
    return label, _MESSAGE_TAG_PAGES.get(lesson.get("agent") or "")


def _render_pending_writing_notes(
    db: Database,
    student: dict[str, Any],
    lessons: list[dict[str, Any]],
    agent_key: str,
) -> None:
    """Notes his parent left on approved writing, kept in the lesson on the
    subject page until he reads and replies to each. An approved lesson is
    'completed' and normally leaves this page; while it still carries an
    unacknowledged note it surfaces here instead -- the note shown under the
    numbered activity it belongs to, with the same typed-reply gate the rest of
    the app uses. Once he replies, the note clears and the lesson drops off like
    any finished one. Replaces the old Home 'Notes on your writing' card so
    feedback lives with the lesson, not on his main board."""
    for lesson in lessons:
        if lesson["status"] != "completed":
            continue
        reviews = (lesson.get("metadata") or {}).get("writing_review") or {}
        activities = lesson["payload"].get("activities") or []
        unread = [
            (int(index_str), review)
            for index_str, review in reviews.items()
            if review.get("approval_feedback") and not review.get("approval_read_at")
        ]
        if not unread:
            continue
        lesson_title = lesson["payload"].get("title", lesson["title"])
        with st.container(border=True):
            st.markdown(f"📣 **A note from your parent on {md(lesson_title)}**")
            for index, review in sorted(unread):
                title = (
                    activities[index].get("title", "Activity")
                    if index < len(activities)
                    else "Activity"
                )
                st.success(f"✅ Activity #{index + 1} — {md(title)} — approved.")
                render_writing_feedback_reply_form(
                    db, lesson["id"], index, review["approval_feedback"],
                    key_prefix=f"subject_{agent_key}",
                )


def student_lesson_view(
    db: Database,
    student: dict[str, Any],
    agent_key: str,
    subject_label: str,
    *,
    comic_layout: bool = True,
) -> None:
    """What the student sees on a subject page: his work, and nothing else.

    A lesson already turned in (`status` in `submitted`/`needs_revision`)
    takes priority over anything else and blocks a new one from taking its
    place -- 'submitted' is waiting on a parent, 'needs_revision' is
    waiting on him again, and either way nothing new shows for this
    subject until it's resolved, even if a parent has already
    batch-planned days ahead. "Turn it in" (db.submit_lesson) is what
    moves a lesson into that state; render_assessment_card, on the
    parent's side, is what moves it back out (approved -> completed, sent
    back -> needs_revision).

    Deliberately doesn't render "Past lessons" itself -- a page with its own
    content after the current lesson (English's Words to Review, for one)
    needs that section last, not sandwiched in the middle of the page.
    Call render_past_lessons() once, at the very end, after everything else
    on the page -- every subject page should, even ones with nothing of
    their own following it today, so a page added later doesn't have to
    remember this rule.

    Picks the same lesson Home's own "Lessons ready for you" list would
    (weekly.due_lessons -- today's, or the oldest overdue one) rather than
    whichever lesson happens to have the highest id. Those disagree:
    generating a multi-day series in one sitting means the last day
    generated has the most recent `created_at`, which is a different thing
    entirely from "the one due today." A day badge
    above the lesson (only shown when it carries a `planned_for` tag at
    all -- an ordinary on-demand generation has no day attached) makes
    that same fact visible here, not just inferred from being on the page.
    """
    lessons = db.list_lessons(student["id"], agent=agent_key, limit=10)
    icon = SUBJECT_ICONS.get(agent_key, "📘")

    # A note his parent left when approving a piece of writing lives here, in
    # the lesson, under the numbered activity it's about -- not on his Home
    # board. An approved lesson counts as done and would normally drop off this
    # page, but one carrying a note he hasn't read and replied to stays put at
    # the top until he does, then closes out like any finished lesson.
    _render_pending_writing_notes(db, student, lessons, agent_key)

    pending = next(
        (l for l in lessons if l["status"] in ("submitted", "needs_revision")), None
    )
    if pending is not None:
        pending_metadata = pending.get("metadata") or {}
        history = _feedback_history(
            pending_metadata, history_key="lesson_feedback_history", single_key="lesson_feedback"
        )
        if pending["status"] == "submitted":
            st.info("📤 Submitted — waiting on your parent to check this.")
        else:
            # Sent back to him. This is the single most important thing on the
            # page -- it's waiting on *him* -- and the whole reason he's here is
            # to read why and fix it, so it gets a loud red callout at the very
            # top of the lesson, framed as a note from his parent rather than a
            # quiet amber aside ("it doesnt appear to clearly tell him why i
            # sent it back"). The most recent note (history is oldest-first) is
            # the one that matters, so it's shown big; any earlier notes sit
            # under it for context.
            # Which specific pieces were flagged (a lesson can have several
            # written answers and only one or two sent back). Named right here
            # so he doesn't have to open every card to find the one that needs
            # work; each is also badged "↩️ Needs another look" on its own card
            # further down.
            flagged = _writing_rework_summary(
                pending["payload"].get("activities") or [], pending_metadata
            )
            if history:
                st.error(
                    f"↩️ **Your parent sent this back.** Here's what to fix:\n\n"
                    f"> {md(history[-1])}"
                )
                if len(history) > 1:
                    with st.expander("Earlier notes on this lesson"):
                        for note in history[:-1]:
                            st.markdown(f"- {md(note)}")
            elif flagged:
                st.error(
                    "↩️ **Your parent sent this back** — some of your written "
                    "answers need another look. They're listed right below, and "
                    "each one is marked ↩️ further down where you fix it."
                )
            else:
                st.error(
                    "↩️ **Your parent sent this back.** Check your work below "
                    "and turn it in again."
                )
            if flagged:
                lines = []
                for item in flagged:
                    head = f"↩️ **Activity #{item['number']} — {md(item['title'])}**"
                    lines.append(f"{head}: {md(item['note'])}" if item["note"] else head)
                count = len(flagged)
                st.warning(
                    f"**{count} "
                    f"{'activity needs' if count == 1 else 'activities need'} "
                    "another look — scroll down to each one to fix it:**\n\n"
                    + "\n\n".join(lines)
                )
        render_lesson(
            pending["payload"],
            for_parent=False,
            db=db,
            lesson_id=pending["id"],
            metadata=pending.get("metadata") or {},
            comic_layout=comic_layout,
            comic_frame_title=f"{icon} {subject_label} — Current Lesson",
            student=student,
            printable=True,
        )
        render_quiz(
            db,
            student,
            pending["id"],
            pending.get("metadata") or {},
            pending["payload"].get("quiz") or [],
            agent=agent_key,
        )
        render_lesson_resources(db, pending["id"], pending_metadata, parent=False)
        if pending["status"] == "needs_revision":
            ready, why_not = _lesson_ready_to_submit(pending)
            if st.button(
                "📬 Turn it in for review",
                key=f"submit_lesson_{pending['id']}",
                type="primary",
                disabled=not ready,
            ):
                db.submit_lesson(pending["id"])
                st.rerun()
            if not ready:
                st.caption(why_not)
        return

    todo = [
        l for l in lessons
        if l["status"] not in ("skipped", "submitted", "needs_revision", "completed")
        and not (l.get("metadata") or {}).get("student_done_on")
    ]
    due_now = weekly.due_lessons(todo, date.today().isoformat())
    done = _done_lessons(db, student["id"], agent_key)
    current = due_now[0] if due_now else None

    if current is None:
        if done:
            st.success("Nothing left to do for now — nice work. Look back below if you want.")
        else:
            st.info(
                f"No {subject_label} lesson has been set up yet. Ask your parent to plan one."
            )
    else:
        current_metadata = current.get("metadata") or {}
        planned_for = current_metadata.get("planned_for")
        if planned_for:
            weekday = date.fromisoformat(planned_for).strftime("%A")
            if planned_for < date.today().isoformat():
                st.caption(f"⚠️ Was due {weekday}")
            else:
                st.caption(f"📅 {weekday} — today's lesson")
        # Part of a multi-day series: show where he is in it, so a topic
        # chunked across days reads as one journey, not a pile of separate
        # lessons. The next part opens on its own as he finishes this one.
        series_total = int(current_metadata.get("series_total") or 0)
        if series_total > 1:
            part = int(current_metadata.get("series_index") or 0) + 1
            series_title = current_metadata.get("series_title") or "this topic"
            st.caption(f"📚 Part {part} of {series_total} — *{md(series_title)}*")
        render_lesson(
            current["payload"],
            for_parent=False,
            db=db,
            lesson_id=current["id"],
            metadata=current.get("metadata") or {},
            comic_layout=comic_layout,
            comic_frame_title=f"{icon} {subject_label} — Current Lesson",
            student=student,
            printable=True,
        )
        render_quiz(
            db,
            student,
            current["id"],
            current.get("metadata") or {},
            current["payload"].get("quiz") or [],
            agent=agent_key,
        )
        render_lesson_resources(db, current["id"], current_metadata, parent=False)
        ready, why_not = _lesson_ready_to_submit(current)
        if st.button(
            "📬 Turn it in for review",
            key=f"submit_lesson_{current['id']}",
            type="primary",
            disabled=not ready,
        ):
            db.submit_lesson(current["id"])
            st.rerun()
        if not ready:
            st.caption(why_not)


def render_past_lessons(
    db: Database, student: dict[str, Any], agent_key: str, subject_label: str | None = None
) -> None:
    """The reopenable archive of lessons a parent has fully approved --
    always the last thing on a subject page. See student_lesson_view's
    docstring for why this is a separate call rather than folded into it.

    `subject_label` should be the same one passed to student_lesson_view --
    optional (falling back to a title-cased `agent_key`) only because a few
    call sites predate this parameter, not because re-deriving it here is
    preferred; a subject with a multi-word or oddly-cased key would title-case
    wrong here while student_lesson_view showed it correctly, a silent
    mismatch between two views of the same subject.
    """
    done = _done_lessons(db, student["id"], agent_key)
    if not done:
        return
    subject_label = subject_label or agent_key.title()
    st.divider()
    st.subheader("Past lessons")
    # The date he actually finished it, not when it was generated -- those
    # can be days apart (a lesson sitting there over a weekend, or a whole
    # week batch-planned in one sitting on Friday), and `created_at` would
    # silently show every lesson from one planning session under the same
    # date. Falls back to `created_at` only for data old enough to predate
    # `student_done_on` existing at all.
    labels = [
        f"{(l.get('metadata') or {}).get('student_done_on') or l['created_at'][:10]} "
        f"— {l['title']}"
        for l in done
    ]
    choice = st.selectbox(
        "Look back at a finished lesson",
        labels,
        index=None,
        placeholder="Pick one to reopen",
        key=f"past_lesson_pick_{agent_key}",
    )
    if choice is not None:
        selected = done[labels.index(choice)]
        icon = SUBJECT_ICONS.get(agent_key, "📘")
        render_lesson(
            selected["payload"],
            for_parent=False,
            db=db,
            lesson_id=selected["id"],
            metadata=selected.get("metadata") or {},
            comic_layout=True,
            comic_frame_title=f"{icon} {subject_label} — Past Lesson",
            student=student,
        )
        render_quiz(
            db,
            student,
            selected["id"],
            selected.get("metadata") or {},
            selected["payload"].get("quiz") or [],
            agent=agent_key,
        )


# --- subject icons, the daily checklist, morning routine -----------------------

SUBJECT_ICONS = {
    "math": "📐", "science": "🔬", "english": "📖", "history": "🏛️",
    "life_skills": "🛠️", "coding": "💻",
}

# One icon per unified-board `kind` (see weekly.board_for_week) -- lessons
# use SUBJECT_ICONS keyed on their own agent instead, since a lesson's icon
# depends on which subject generated it.
BOARD_KIND_ICONS = {
    "life_skill": "🛠️",
    "coding_module": "💻",
    "choice_topic": "⭐",
    "project_step": "🎬",
    "travel_entry": "🧭",
}

# One color + display name per board-card identity -- for a lesson that's its
# agent (a Math lesson vs a Science lesson); for every other kind it's the kind
# itself. Rendered as a small colored bar across the top of each board card
# (see render_board_card) so "what is this" reads at a glance from color and
# word together, without opening the card. Days are already unmistakable from
# the big colored column headers, so a card's own color is free to mean
# subject/kind instead of repeating the day. Hues chosen to be distinct from
# each other and legible under white text.
BOARD_TAG_COLORS = {
    "math": "#3f6bd8",
    "science": "#2f9e5f",
    "english": "#e0871a",
    "history": "#c0553b",
    "life_skill": "#0f9b9b",
    "coding_module": "#7c5cd6",
    "choice_topic": "#b9932b",
    "project_step": "#c0398f",
    "travel_entry": "#2c9cc9",
}
BOARD_TAG_LABELS = {
    "math": "Math", "science": "Science", "english": "English", "history": "History",
    "life_skill": "Life Skill", "coding_module": "Coding", "choice_topic": "Choice",
    "project_step": "Big Project", "travel_entry": "Travel",
}
_BOARD_TAG_FALLBACK_COLOR = "#8a7a5c"


def board_card_tag(kind: str, item: dict[str, Any]) -> tuple[str, str, str]:
    """(color, icon, label) for a board card's colored kind bar. A lesson's
    identity is its agent (Math/Science/English/History); every other kind is
    identified by the kind itself."""
    if kind == "lesson":
        agent = item.get("agent", "")
        return (
            BOARD_TAG_COLORS.get(agent, _BOARD_TAG_FALLBACK_COLOR),
            SUBJECT_ICONS.get(agent, "📘"),
            BOARD_TAG_LABELS.get(agent, (agent.replace("_", " ").title() or "Lesson")),
        )
    return (
        BOARD_TAG_COLORS.get(kind, _BOARD_TAG_FALLBACK_COLOR),
        BOARD_KIND_ICONS.get(kind, "📘"),
        BOARD_TAG_LABELS.get(kind, kind.replace("_", " ").title()),
    )


def _board_identity(kind: str, item: dict[str, Any]) -> str:
    """The row a card belongs to on the aligned week grid: a lesson's agent,
    or the kind itself for everything else -- the same key board_card_tag
    colors by, so a subject/kind reads as one straight row across the week."""
    return item.get("agent", "") if kind == "lesson" else kind


# Fixed top-to-bottom order for the week grid's rows, so a subject sits in the
# same row every week regardless of which days it happens to have cards on.
# The four core subjects first (they're the daily spine), then the elective
# kinds; any identity not listed falls in after these, in first-seen order.
_BOARD_ROW_ORDER = [
    "math", "science", "english", "history",
    "life_skill", "coding_module", "choice_topic", "project_step", "travel_entry",
]

# One icon per epic in weekly.EPIC_ORDER -- the Board tab's Product Backlog
# panel groups by this, not by story kind.
EPIC_ICONS = {
    "Math": "📐", "Science": "🔬", "English": "📖", "History": "🏛️",
    "Life Skills": "🛠️", "Big Projects": "🎬",
}

def _render_grade_override_form(db: Database, grade: Any) -> None:
    """Parent-only: set (or clear) a subject's grade by hand, right where the
    grade is shown. Reported directly: "where can i find/edit a grading record
    as parent?" -- the grade is normally computed from what he turned in, but a
    parent needs the last word (a project the app never saw, a bad-day quiz to
    forgive). Stored as the `grade_override_<subject>` setting via
    gradebook.set_override; clearing hands the number back to the computed
    grade."""
    subject = grade.subject
    default = float(grade.percent) if grade.percent is not None else 85.0
    with st.form(f"grade_override_{subject}"):
        st.caption("Set this grade by hand")
        new_percent = st.number_input(
            "Grade %",
            min_value=0.0,
            max_value=100.0,
            value=round(default, 1),
            step=1.0,
            key=f"grade_override_input_{subject}",
        )
        note = st.text_input(
            "Note (optional — shows with the grade)",
            value=grade.override_note if grade.overridden else "",
            key=f"grade_override_note_input_{subject}",
        )
        save_col, clear_col = st.columns(2)
        if save_col.form_submit_button("Save grade", type="primary"):
            gradebook.set_override(db, subject, new_percent, note)
            st.rerun()
        if clear_col.form_submit_button(
            "Clear (use computed)", disabled=not grade.overridden
        ):
            gradebook.set_override(db, subject, None)
            st.rerun()


def _grade_dot(percent: float) -> str:
    """A traffic-light dot for one graded item's score, so a parent scanning
    the drill-down sees the shape of the list before reading a single number:
    green passing comfortably, amber shaky, red failing."""
    if percent >= 80:
        return "🟢"
    if percent >= 70:
        return "🟡"
    return "🔴"


def _render_grade_item_editor(
    db: Database, student: dict[str, Any], subject: str, item: Any
) -> None:
    """The ✏️ on one editable graded item -- a parent re-grading a single
    hand-in or math skill by hand, right from the report card. Reported: "i
    should have control on edit activity grading when needed." A hand-in re-picks
    its verdict (record_assessment); a math skill flips mastered / not-yet
    (set_mastery). Quizzes never reach here -- they're auto-graded off his
    answers, so `item.editable` is false for them. Tucked in a popover so the
    list stays a clean at-a-glance read until you actually want to change one."""
    with st.popover("✏️", use_container_width=True, help="Re-grade this by hand"):
        if item.component == "assessment" and item.lesson_id is not None:
            st.caption(f"Re-grade **{md(item.title)}**")
            verdicts = list(config.ASSESSMENT_VERDICTS)
            current = item.verdict if item.verdict in verdicts else verdicts[0]
            # A per-activity grade and a legacy whole-lesson hand-in can both be
            # open at once, so the widget keys mix in the activity index to stay
            # unique per item.
            slug = (
                f"{item.lesson_id}_{item.activity_index}"
                if item.activity_index is not None
                else str(item.lesson_id)
            )
            new_verdict = st.selectbox(
                "Grade",
                verdicts,
                index=verdicts.index(current),
                format_func=lambda v: config.ASSESSMENT_VERDICT_LABELS[v],
                key=f"grade_item_verdict_{subject}_{slug}",
            )
            if st.button(
                "Save grade",
                key=f"grade_item_save_{subject}_{slug}",
                type="primary",
            ):
                if item.activity_index is not None:
                    db.record_activity_grade(item.lesson_id, item.activity_index, new_verdict)
                else:
                    db.record_assessment(item.lesson_id, new_verdict)
                st.success("Updated.")
                st.rerun()
        elif item.component == "mastery" and item.skill_id is not None:
            st.caption(f"Set mastery for **{md(item.title)}**")
            mastered_col, not_yet_col = st.columns(2)
            if mastered_col.button(
                "🎯 Mastered", key=f"grade_item_master_{subject}_{item.skill_id}"
            ):
                db.set_mastery(student["id"], item.skill_id, "mastered", score=100)
                st.rerun()
            if not_yet_col.button(
                "↩️ Not yet", key=f"grade_item_notyet_{subject}_{item.skill_id}"
            ):
                db.set_mastery(student["id"], item.skill_id, "in_progress")
                st.rerun()


def render_report_card(db: Database, student: dict[str, Any], *, for_parent: bool) -> None:
    """Subject grades, with the arithmetic showing.

    Deliberately per-subject with no overall GPA: one number for everything
    reads as a verdict on him rather than on the work, which is the failure
    mode most likely to make a kid who already freezes stop trying. Four
    separate numbers are four separate, fixable things.

    A subject with nothing recorded shows as ungraded, never as an F -- an
    absent grade and a failed one are completely different facts.
    """
    subject_grades = gradebook.all_subject_grades(db, student["id"])
    if not any(grade.graded for grade in subject_grades):
        if not for_parent:
            st.caption(
                "No grades yet — they'll show up here once there are quizzes and "
                "assignments to average."
            )
            return
        st.caption(
            "No grades computed yet — they'll fill in from quizzes and assignments. "
            "You can also set any subject's grade by hand below."
        )

    columns = st.columns(len(subject_grades))
    for column, grade in zip(columns, subject_grades):
        label = gradebook.AGENT_LABELS.get(grade.subject, grade.subject.title())
        icon = SUBJECT_ICONS.get(grade.subject, "📘")
        with column:
            if grade.overridden:
                st.caption("✏️ adjusted by parent")
            # The percent rides on the label rather than st.metric's `delta`.
            # A delta always draws a direction arrow, and "↑ 40%" under an F
            # reads as a gain of 40 points rather than a score of 40 (and "↑
            # not graded yet" is nonsense in any direction); delta_color="off"
            # greys the arrow but doesn't remove it. A caption underneath
            # works, but lands outside the card's border and reads as
            # detached from the letter it belongs to.
            if grade.graded:
                st.metric(f"{icon} {label} — {grade.percent:.0f}%", grade.letter)
            else:
                # "ungraded", not "not graded yet": four metrics share a row,
                # and the longer phrase wraps the label onto a second line
                # only on the ungraded card, leaving the row visibly ragged.
                st.metric(f"{icon} {label} — ungraded", "—")

    # For the parent, every subject gets a row -- even an ungraded one, so a
    # grade can be set by hand where the auto-signals haven't produced one yet.
    # For the student, only the subjects that actually have a grade show their
    # breakdown.
    shown = subject_grades if for_parent else [g for g in subject_grades if g.graded]
    for grade in shown:
        label = gradebook.AGENT_LABELS.get(grade.subject, grade.subject.title())
        heading = (
            f"What makes up the {label} grade"
            if for_parent
            else f"What makes up your {label} grade"
        )
        with st.expander(heading):
            if grade.overridden:
                note = f" — {md(grade.override_note)}" if grade.override_note else ""
                st.info(
                    f"✏️ This grade is set by hand to **{grade.percent:.0f}% "
                    f"({grade.letter})**{note}. The breakdown below is what the "
                    "computed grade would be."
                )
            # One plain sentence up top so the breakdown reads without a decoder
            # ring: the grade comes from two things -- the quiz and the hand-in --
            # plus math mastery. Everything else in a lesson is practice.
            if for_parent:
                st.caption(
                    "Two things make the grade: the **quizzes** he takes "
                    "(auto-marked) and the **hand-in** — the finished piece he "
                    "hands you to grade. Everything else in a lesson is practice, "
                    "not a separate score."
                )
            else:
                st.caption(
                    "Two things make your grade: the **quizzes** you take "
                    "(marked for you) and the **hand-in** — the finished piece you "
                    "turn in. Everything else in a lesson is practice, not a "
                    "separate score."
                )
            for component in grade.components:
                blurb = grades.COMPONENT_BLURBS.get(component.key, "")
                blurb_line = (
                    f"  <span style='color:var(--c-dim); font-size:12px;'>"
                    f"{html.escape(blurb)}</span>  \n"
                    if blurb
                    else ""
                )
                st.markdown(
                    f"- **{component.label}** — {component.percent:.0f}% "
                    f"·  {component.weight}% of the grade  \n"
                    f"{blurb_line}"
                    f"  <span style='color:var(--c-dim); font-size:12px;'>"
                    f"{html.escape(component.detail)}</span>",
                    unsafe_allow_html=True,
                )
            if not grade.components:
                st.caption("No graded work yet to average from.")

            # The averages above hide which individual pieces pulled the grade
            # down. Reported: "his math grade is bad and i dont know why -- how
            # can the parent see into each graded item in a list with grade?"
            # So every scored item that fed those averages is listed here,
            # worst first, tagged with which component it belongs to.
            items = gradebook.graded_items(db, student["id"], grade.subject)
            if items:
                st.markdown(
                    "**Every graded item** — worst first, so what's pulling it "
                    "down is right at the top:"
                    if for_parent
                    else "**Every graded item** — worst first:"
                )
                if for_parent:
                    st.caption(
                        "Each hand-in and math skill has an ✏️ to re-grade it by "
                        "hand. Quizzes are auto-marked off his answers — the way "
                        "to change one is to have him retake it."
                    )
                for item in items:
                    letter = config.letter_for(item.percent)
                    text_col, edit_col = (
                        st.columns([6, 1]) if for_parent else (st.container(), None)
                    )
                    with text_col:
                        st.markdown(
                            f"{_grade_dot(item.percent)} **{item.percent:.0f}%** "
                            f"({letter}) — {md(item.title)}  \n"
                            f"  <span style='color:var(--c-dim); font-size:12px;'>"
                            f"{html.escape(item.component_label)} · "
                            f"{html.escape(item.detail)}</span>",
                            unsafe_allow_html=True,
                        )
                    if edit_col is not None and item.editable:
                        with edit_col:
                            _render_grade_item_editor(db, student, grade.subject, item)

            if for_parent:
                st.caption(
                    "Weights are settings — `grade_weights_"
                    f"{grade.subject}` on the Student Profile page."
                )
                _render_grade_override_form(db, grade)


def render_travel_feedback_reply_form(
    db: Database, entry: dict[str, Any], *, key_prefix: str
) -> None:
    """The gate for marking Travel Journal feedback read -- a parent asked
    directly how a bare "I read this" button proves anything, since he
    could click it without reading a word. Requires a short reply in his
    own words about something specific from the feedback first: not proof
    he understood it, but proof he was actually looking at it, and it
    gives a parent something real to read and judge for themselves rather
    than a bare timestamp. Shared between Home's "Feedback to read" card
    and the entry's own card on the journal page -- both need identical
    validation, so `key_prefix` just keeps their widget keys apart."""
    with st.form(f"{key_prefix}_feedback_reply_{entry['id']}"):
        reply = st.text_input(
            "What's one thing from this feedback? (in your own words)",
            key=f"{key_prefix}_feedback_reply_input_{entry['id']}",
            placeholder="e.g. Use commas when I list things",
        )
        if st.form_submit_button("✅ I read this"):
            word_count = len(reply.split())
            if word_count < config.TRAVEL_JOURNAL_FEEDBACK_REPLY_MIN_WORDS:
                st.warning(
                    f"Say a little more -- needs at least "
                    f"{config.TRAVEL_JOURNAL_FEEDBACK_REPLY_MIN_WORDS} words about "
                    f"something specific ({word_count} so far)."
                )
            else:
                db.mark_travel_feedback_read(entry["id"], reply.strip())
                st.rerun()


def render_writing_feedback_reply_form(
    db: Database,
    lesson_id: int,
    activity_index: int,
    note: str,
    *,
    key_prefix: str,
) -> None:
    """The acknowledgement gate on a parent's note about an *approved* piece of
    writing -- the same reply-in-your-own-words the Travel Journal asks for,
    replacing the old one-tap "I read this" (reported: "require him to do more
    than just i read it lol"). Shared by his subject-page lesson view and Home's
    "Notes on your writing" card, so `key_prefix` keeps their widgets apart. His
    reply is stored next to the read stamp for a parent to see."""
    with st.form(f"{key_prefix}_writing_reply_{lesson_id}_{activity_index}"):
        st.caption(f"💬 Your parent's note: {md(note)}")
        reply = st.text_input(
            "What's one thing you'll take from this? (in your own words)",
            key=f"{key_prefix}_writing_reply_input_{lesson_id}_{activity_index}",
            placeholder="e.g. Next time I'll back up my point with an example",
        )
        if st.form_submit_button("✅ I read this"):
            word_count = len(reply.split())
            if word_count < config.WRITING_FEEDBACK_REPLY_MIN_WORDS:
                st.warning(
                    f"Say a little more — needs at least "
                    f"{config.WRITING_FEEDBACK_REPLY_MIN_WORDS} words about something "
                    f"specific ({word_count} so far)."
                )
            else:
                db.mark_writing_feedback_read(lesson_id, activity_index, reply.strip())
                st.rerun()


def render_progress_panel(db: Database, student: dict[str, Any], *, columns: int = 4) -> None:
    """His progress numbers -- the "📈 Progress" heading and KPI tiles. Lives at
    the bottom of the Level card on Home (moved out of the Due-today card so Due
    today stands on its own)."""
    st.markdown("**📈 Progress**")
    _render_learner_kpis(db, student, columns=columns)


def _render_learner_kpis(db: Database, student: dict[str, Any], *, columns: int = 4) -> None:
    """The compact KPI tiles -- finished lessons, passed quizzes, and the
    subject he's put the most work into. Custom HTML grid rather than st.metric
    so the tiles stay short instead of stacking tall. `columns` controls the
    grid width: 4 for a single strip, 2 for a 2x2 block when the tiles sit in a
    half-width column (the two-panel Today card)."""
    stats = xp_module.learner_stats(db, student["id"])

    tiles = [
        ("📚", stats.lessons_done, "lessons done"),
        ("🎯", stats.quizzes_passed, "quizzes passed"),
        ("🛠️", stats.skills_done, "life skills"),
        ("🧭", stats.trips_written, "trips written"),
    ]
    cells = "".join(
        f'<div style="text-align:center; padding:8px 4px; background:var(--c-panel); '
        f'border:1px solid rgba(36,28,18,.08); border-radius:8px;">'
        f'<div style="font-size:19px; font-weight:800; line-height:1.1;">{icon} {value}</div>'
        f'<div style="font-size:11px; color:var(--c-dim);">{label}</div>'
        f"</div>"
        for icon, value, label in tiles
    )
    st.markdown(
        f'<div style="display:grid; grid-template-columns:repeat({columns},1fr); '
        f'gap:6px; margin-top:8px;">{cells}</div>',
        unsafe_allow_html=True,
    )
    if stats.heaviest_subject:
        st.caption(
            f"💪 Most work so far: **{md(stats.heaviest_subject.title())}** "
            f"({stats.heaviest_subject_count} lesson"
            f"{'s' if stats.heaviest_subject_count != 1 else ''})"
        )


def render_daily_due(db: Database, student: dict[str, Any], today: str) -> None:
    """The day's small recurring work -- his start-of-day routine and check-in,
    words to review, where his book is, and any life skills due -- rendered to
    POP at the top of the Home Today card so it's the first thing he sees and
    does daily. Each item is a bright, colored tile: gold when there's something
    waiting (a big count he can't miss), calm green when he's caught up, blue for
    his reading progress bar. Morning Routine and Check-In sit at the top as
    tight tiles that link out to their own pages rather than unrolling the full
    widget here."""
    routine_done = db.morning_routine_for_date(student["id"], today) is not None
    checked_in = db.journal_entry_for_date(student["id"], today) is not None
    due_words = db.vocabulary_due(student["id"], limit=25)
    book = db.current_book(student["id"])
    due_skills = db.due_life_skills(student["id"], today)
    later_skills = len(db.upcoming_life_skills(student["id"], today))
    topics = [
        t
        for t in db.list_choice_topics(student["id"])
        if t["status"] in ("active", "approved")
    ]
    due_coding = db.due_coding_modules(student["id"], today)

    def _tile(
        icon: str,
        label_html: str,
        *,
        tone: str,
        big: Any = "",
        link: tuple[str, str] | None = None,
    ) -> None:
        # tone: "todo" (gold, something waiting) | "done" (green, caught up) |
        # "info" (blue, neutral progress). `link` is an optional (label, href)
        # rendered as an anchor on the SAME row, pushed to the right edge -- so a
        # tile's follow-up action ("check in again") sits beside its status
        # instead of on a separate line below it. The href is relative to the
        # app root so it survives a base-path deployment, same slug Streamlit's
        # own multipage links use (e.g. "Check_In" for pages/8_Check_In.py).
        accent, bg = {
            "todo": ("var(--c-primary)", "rgba(242,183,5,.16)"),
            "done": ("var(--c-good)", "rgba(47,155,104,.12)"),
            "info": ("var(--c-alt)", "rgba(47,99,224,.09)"),
        }[tone]
        big_html = (
            f'<span style="font-size:27px; font-weight:900; color:{accent}; '
            f'line-height:1; margin:0 3px;">{big}</span>'
            if big != ""
            else ""
        )
        link_html = ""
        if link is not None:
            link_label, link_href = link
            link_html = (
                f'<a href="{html.escape(link_href)}" target="_self" '
                f'style="margin-left:auto; padding-left:10px; white-space:nowrap; '
                f'font-weight:700; font-size:13px; color:{accent}; '
                f'text-decoration:none;">{html.escape(link_label)}</a>'
            )
        st.markdown(
            f'<div style="display:flex; align-items:center; gap:4px; background:{bg}; '
            f'border-left:5px solid {accent}; border-radius:8px; padding:10px 13px; '
            f'margin-bottom:6px;">'
            f'<span style="font-size:17px;">{icon}</span>{big_html}'
            f'<span style="font-weight:800; font-size:14px;">{label_html}</span>'
            f'{link_html}</div>',
            unsafe_allow_html=True,
        )

    st.markdown(
        '<div style="font-size:16px; font-weight:900; margin:2px 0 9px;">📌 Due today</div>',
        unsafe_allow_html=True,
    )

    # Start-of-day pair -- Morning Routine and Check-In, kept tight: a status
    # tile plus a single link out to the actual page, not the full widget
    # inline. They lead the list because they're what he does first each day.
    if routine_done:
        _tile("🧘", "Morning Routine — done for today ✅", tone="done")
    else:
        _tile("🧘", "Morning Routine — start your day", tone="todo")
        st.page_link("pages/5_Morning_Routine.py", label="Do it now", icon="➡️")

    if checked_in:
        # The follow-up "check in again" sits on the same row as the done
        # status, right-aligned inside the tile, rather than on a line below.
        _tile(
            "💬", "Check-In — done for today ✅", tone="done",
            link=("↩️ Check in again", "Check_In"),
        )
    else:
        _tile("💬", "Check-In — say how you're doing", tone="todo")
        st.page_link("pages/8_Check_In.py", label="Open Check-In", icon="➡️")

    # Lessons -- a compact "N of M submitted" count of today's core-subject
    # lessons (Math, Science, English, History -- max 4), so he can see his
    # progress through the day's real work at a glance. M is however many are
    # actually relevant today (the same per-subject roster the Lessons cards
    # below use), so it shifts day to day; a lesson counts as done the moment
    # he's turned it in (📤) or it's approved (✅ / 📣 a note to read). The full
    # per-subject cards with links live further down the page.
    lesson_markers = []
    for lesson_agent in ("math", "science", "english", "history"):
        agent_lessons = db.list_lessons(student["id"], agent=lesson_agent, limit=10)
        lesson_row, marker = weekly.today_subject_status(agent_lessons, today)
        if lesson_row is not None:
            lesson_markers.append(marker)
    total_lessons = len(lesson_markers)
    if total_lessons:
        submitted_lessons = sum(1 for m in lesson_markers if m in ("📤", "✅", "📣"))
        if submitted_lessons >= total_lessons:
            _tile(
                "📚", f"Lessons — {submitted_lessons} of {total_lessons} in ✅",
                tone="done",
            )
        else:
            _tile(
                "📚",
                f"Lessons — {submitted_lessons} of {total_lessons} submitted",
                tone="todo",
            )

    # Words -- a green check once he's done for the day, whether he cleared every
    # due word or hit "I'm done with words for today" in the game (his own
    # signal), so the tile reflects "I finished," not just "nothing left due."
    words_done_today = db.vocab_reviewed_on(student["id"], today)
    if words_done_today:
        _tile("🔤", "Words — done for today ✅", tone="done")
    elif due_words:
        _tile("🔤", "words to review", tone="todo", big=len(due_words))
        st.page_link("pages/3_English.py", label="Review now", icon="➡️")
    else:
        _tile("🔤", "Words — all caught up ✅", tone="done")

    # Reading -- driven entirely by the standing "daily reading" board card.
    # When the current book has a pages-per-day goal (it's on the board), today's
    # target shows here with a one-tap Done; take it off the board and this tile
    # disappears completely, same as any other unassigned story.
    rate = int((book or {}).get("pages_per_day") or 0)
    reading_today = book and rate > 0 and reading.reading_active_on(
        book.get("reading_days") or "", date.fromisoformat(today).weekday()
    )
    if reading_today:
        total = book.get("total_pages")
        current = book.get("current_page") or 0
        log_today = db.reading_log_on(student["id"], book["id"], today)
        start_page = log_today["start_page"] if log_today else current
        target = reading.daily_reading_target(total, start_page, rate)
        goal_page = target if target is not None else start_page + rate
        of_total = f" of {total}" if total else ""
        if current >= goal_page:
            _tile(
                "📖", f"Reading — done for today ✅ (page {current}{of_total})",
                tone="done",
            )
        else:
            # One line: the target on the left, a "Done" on the right -- like
            # Check-In's inline action. The "didn't finish" path (log a partial
            # page) sits collapsed underneath, there when he needs it.
            tile_col, done_col = st.columns([4, 1])
            with tile_col:
                _tile(
                    "📖",
                    f"Reading — {md(book['title'])}: read up to page {goal_page} today",
                    tone="info",
                )
            with done_col:
                if st.button("✅ Done", key="reading_hit_goal", width="stretch"):
                    db.log_reading(student["id"], book["id"], goal_page, today)
                    st.rerun()
            with st.expander("Didn't finish? Log the page you stopped on"):
                reported = st.number_input(
                    "Page reached", min_value=0,
                    max_value=int(total) if total else 100000,
                    value=int(current), key="reading_report_page",
                )
                if st.button("Save", key="reading_save_page"):
                    db.log_reading(student["id"], book["id"], int(reported), today)
                    st.rerun()

    # Life Skills -- big gold count only for what he still has to do; ones he's
    # marked done (submitted, waiting on a parent's approval) count as his part
    # finished, so once all that's left is waiting on you the tile goes green
    # rather than nagging him about work he's already handed in.
    todo_skills = [
        s for s in due_skills
        if (s.get("status") or "") != config.LIFE_SKILL_SUBMITTED
    ]
    awaiting_skills = [
        s for s in due_skills
        if (s.get("status") or "") == config.LIFE_SKILL_SUBMITTED
    ]
    if todo_skills:
        _tile("🛠️", f"Life Skills ({len(todo_skills)}) due", tone="todo", big=len(todo_skills))
        for skill in todo_skills:
            st.page_link("pages/6_Life_Skills.py", label=md(skill["title"]), icon="➡️")
        if awaiting_skills:
            st.caption(f"✅ {len(awaiting_skills)} handed in, waiting on your parent")
    elif awaiting_skills:
        # He's done his part -- standard "done for today" like the other tiles;
        # the parent-approval it's waiting on rides underneath as a note.
        _tile("🛠️", "Life Skills — done for today ✅", tone="done")
        st.caption("Handed in — waiting on your parent to check it off.")
    else:
        _tile("🛠️", "Life Skills (0) — nothing due ✅", tone="done")

    # Travel journal -- scheduled entries he needs to write. Unlike Life Skills
    # it only appears when a trip is actually assigned for today (travel is
    # occasional, so an everyday "nothing due" row would just be clutter). Same
    # submitted-vs-todo split: a trip he's written and turned in reads as his
    # part done, waiting on a parent.
    due_trips = db.due_travel_entries(student["id"], today)
    todo_trips = [t for t in due_trips if (t.get("status") or "planned") != "submitted"]
    awaiting_trips = [t for t in due_trips if (t.get("status") or "") == "submitted"]
    if todo_trips:
        _tile("🧳", f"Travel journal ({len(todo_trips)}) to write", tone="todo", big=len(todo_trips))
        for trip in todo_trips:
            st.page_link(
                "pages/9_Landons_Travels.py",
                label=md(trip.get("title") or trip.get("state") or "Trip"),
                icon="➡️",
            )
        if awaiting_trips:
            st.caption(f"✅ {len(awaiting_trips)} handed in, waiting on your parent")
    elif awaiting_trips:
        _tile("🧳", "Travel journal — done for today ✅", tone="done")
        st.caption("Handed in — waiting on your parent to check it off.")

    # Big Projects -- a project step assigned for today gets its own tile, the
    # same shape as Life Skills and Travel (only when one's actually due, since
    # a step isn't an everyday thing). Same submitted-vs-todo split.
    due_steps = db.due_project_steps(student["id"], today)
    todo_steps = [s for s in due_steps if (s.get("status") or "planned") != "submitted"]
    awaiting_steps = [s for s in due_steps if (s.get("status") or "") == "submitted"]
    if todo_steps:
        _tile("🏗️", f"Big Projects ({len(todo_steps)}) due", tone="todo")
        for step in todo_steps:
            project_title = step.get("project_title") or "Big Project"
            st.page_link(
                "pages/7_Big_Projects.py",
                label=f"{md(step['title'])} — {md(project_title)}",
                icon="➡️",
            )
        if awaiting_steps:
            st.caption(f"✅ {len(awaiting_steps)} handed in, waiting on your parent")
    elif awaiting_steps:
        _tile("🏗️", "Big Projects — done for today ✅", tone="done")
        st.caption("Handed in — waiting on your parent to check it off.")

    # +later, plus the Student's Choice / Coding counts that each have their own
    # scheduled-for-a-day items, as one compact caption at the bottom.
    later_trips = len(db.upcoming_travel_entries(student["id"], today))
    extra: list[str] = []
    if later_skills:
        extra.append(f"+{later_skills} skill(s) later")
    if later_trips:
        extra.append(f"🧳 +{later_trips} trip(s) later")
    if topics:
        extra.append(f"⭐ {len(topics)} Choice")
    if due_coding:
        extra.append(f"💻 {len(due_coding)} coding due")
    if extra:
        st.caption(" · ".join(extra))


def render_today_checklist(db: Database, student: dict[str, Any]) -> bool:
    """His own "what I did today" list -- a fun accomplishment checklist, not
    a compliance record. Built entirely from his own signals (student_done_on,
    a quiz result graded today, a life skill either of you checked off today,
    the vocab review's own "I'm done for today" button) so it never depends
    on the parent having logged anything yet -- that gap was the exact thing
    that made "current lesson" confusing before.

    Returns whether anything was actually shown, so a caller can fall back to
    something else when the day hasn't started yet.
    """
    today = date.today().isoformat()

    done_today = [
        lesson
        for lesson in db.list_lessons(student["id"], limit=25)
        if (lesson.get("metadata") or {}).get("student_done_on") == today
    ]
    skills_today = [
        skill
        for skill in db.list_life_skills(student["id"])
        if skill["completed_on"] == today
    ]
    vocab_done_today = db.vocab_reviewed_on(student["id"], today)

    if not done_today and not skills_today and not vocab_done_today:
        return False

    total = len(done_today) + len(skills_today) + (1 if vocab_done_today else 0)
    st.subheader(f"✅ Today ({total})")
    st.caption("Nice work — here's what you've knocked out today.")

    for lesson in done_today:
        icon = SUBJECT_ICONS.get(lesson["agent"], "📘")
        quiz_result = (lesson.get("metadata") or {}).get("quiz_result") or {}
        extra = ""
        if quiz_result.get("graded_on") == today and quiz_result.get("total"):
            pct = round(100 * quiz_result["correct"] / quiz_result["total"])
            trophy = " 🎯" if quiz_result.get("passed") else ""
            extra = f" — quiz {quiz_result['correct']}/{quiz_result['total']} ({pct}%){trophy}"
        st.markdown(f"- {icon} **{md(lesson['title'])}**{extra}")

    for skill in skills_today:
        st.markdown(f"- 🛠️ **{md(skill['title'])}**")

    if vocab_done_today:
        st.markdown("- 🔤 **Vocabulary reviewed**")

    return True


def render_morning_routine(db: Database, student: dict[str, Any]) -> bool:
    """A short, parent-curated menu of stretches/breathing/mindfulness
    routines (compass.morning_routines) -- not agent-generated, this is
    personal to the family, same reasoning as the Life Skills catalog.
    Logs real Health-subject credit on first completion each day (WA's
    Health subject explicitly covers physical and mental wellbeing).

    Returns whether he's already done one today, so the caller can fold this
    into the rest of the day's checklist.
    """
    today = date.today().isoformat()
    logged = db.morning_routine_for_date(student["id"], today)
    catalog = {r[0]: r for r in MORNING_ROUTINES}
    default_key = logged["routine_key"] if logged else routine_for_date(today)[0]
    default_routine = catalog.get(default_key, MORNING_ROUTINES[0])

    render_card_heading("🧘 Morning Routine")
    if logged:
        done_routine = catalog.get(logged["routine_key"])
        title = done_routine[1] if done_routine else logged["routine_key"]
        st.success(f"✅ Done for today — {md(title)}. Nice start.")
        label = "Do a different one instead"
    else:
        st.caption("A few minutes to start the day feeling good, before anything else.")
        label = (
            f"{default_routine[2]} {default_routine[1]} ({default_routine[3]} min) "
            "— tap to see the steps"
        )

    with st.expander(label, expanded=False):
        options = list(catalog.keys())
        picked_key = st.radio(
            "Pick one",
            options,
            index=options.index(default_key),
            format_func=lambda k: f"{catalog[k][2]} {catalog[k][1]} ({catalog[k][3]} min)",
            label_visibility="collapsed",
            key="morning_routine_pick",
        )
        routine = catalog[picked_key]
        st.caption(md(routine[4]))
        for step in routine[5]:
            st.markdown(f"- {md(step)}")
        button_label = "Switch to this one" if logged else "Mark this morning done ✅"
        if st.button(button_label, type="primary", key="morning_routine_done"):
            db.log_morning_routine(student["id"], today, picked_key)
            if not logged:
                db.log_activity(
                    student_id=student["id"],
                    title=f"Morning routine — {routine[1]}",
                    tier=config.TIER_WELLNESS,
                    primary_subject="health",
                    minutes=routine[3],
                    subject_credits={"health": routine[3]},
                    occurred_on=today,
                    description=routine[4],
                    source="morning_routine",
                )
            st.rerun()

    return logged is not None


# --- API availability (used by the generate -> review -> log loop above) -------


def api_status_banner() -> bool:
    from compass.agents import api_available

    ok, message = api_available()
    if not ok:
        st.error(
            f"**Lesson generation is unavailable.** {message}\n\n"
            "Everything else in Compass — the compliance dashboard, the activity log, "
            "choice topics, and life skills — works without it."
        )
    return ok


# --- small standalone banners ---------------------------------------------------


def render_card_heading(text: str) -> None:
    """A card-section heading that reads as a normal title, not a shout --
    Home stacks several of these on screen at once (Lessons, Morning
    Routine, Check-In, ...), and the fixed theme's global rule for every
    literal `#`-heading (`.stApp h1-h4`, see theme.py) is bold, uppercase,
    and letter-spaced -- right for a page's one real heading, wrong
    repeated across half a dozen small cards on the same busy dashboard.
    A plain styled div sidesteps that rule entirely, since it was never a
    real `<h*>` element for the theme's selectors to catch.
    """
    st.markdown(
        f'<div style="font-size:16px; font-weight:700; color:var(--c-text); '
        f'margin-bottom:6px;">{text}</div>',
        unsafe_allow_html=True,
    )


def render_brain_break() -> None:
    """Student view only -- a little daily bonus round: a riddle he can guess
    before revealing, the word of the day, and a quick history flashback. Pure
    flavor, rotates daily (see compass.daily), no lesson attached. Kept in one
    bordered card so it reads as a fun aside, not another assignment."""
    question, answer = daily.riddle_of_the_day()
    word, part_of_speech, definition = daily.word_of_the_day()
    with st.container(border=True, key="landon_card_brainbreak"):
        render_card_heading("🧠 Brain Break")
        st.markdown(f"**🎲 Fun fact:** {md(fun_facts.fact_of_the_day())}")
        st.markdown(f"**🧩 Riddle:** {md(question)}")
        with st.expander("Reveal the answer"):
            st.markdown(f"**{md(answer)}**")
        st.markdown(
            f"**🔤 Word of the day:** {md(word)} "
            f"*({md(part_of_speech)})* — {md(definition)}"
        )
        st.caption("Bonus points if you use it in a sentence today.")
        st.markdown(f"**📜 History flashback:** {md(daily.history_flashback())}")


def render_travel_passport(db: Database, student: dict[str, Any]) -> None:
    """A collectible "passport" of the states and national parks he's stamped
    through the Travel Journal -- a stamp earned per trip he's written up and a
    parent has approved. The travel data already tracks his visited states and
    parks (compass.national_parks); this just surfaces it as a filling-in
    collection, on the "make it fun" wish. Shown only once he has any travel
    entries at all, so it never sits empty as clutter."""
    from compass import national_parks

    entries = db.list_travel_entries(student["id"])
    if not entries:
        return
    completed = [e for e in entries if e.get("status") == "completed"]
    visited_states = sorted({e["state"] for e in completed if e.get("state")})
    parks: list[tuple[str, str]] = []
    seen_parks: set[str] = set()
    for entry in completed:
        key = entry.get("park_key")
        if key and key not in seen_parks:
            park = national_parks.park_by_key(key)
            if park:
                seen_parks.add(key)
                parks.append((key, park.name))
    total_states = len(national_parks.STATES)
    waiting = len(entries) - len(completed)

    with st.container(border=True, key="landon_card_passport"):
        render_card_heading("🗺️ Travel Passport")
        st.markdown(
            f"**{len(visited_states)} of {total_states} states explored** · "
            f"**{len(parks)} park{'s' if len(parks) != 1 else ''} stamped**"
        )
        if visited_states:
            st.caption("📍 " + " · ".join(md(state) for state in visited_states))
        if parks:
            st.markdown(
                "  ".join(f"{national_parks.icon_for(key)} {md(name)}" for key, name in parks)
            )
        if waiting:
            st.caption(
                f"✍️ {waiting} trip(s) waiting to be written up — finish one to earn its stamp."
            )
        elif not completed:
            st.caption("Your passport's ready — your first stamp is one trip away.")


# The Mon-Fri day colors for the weekly XP strip -- the same five the Home
# week grid and the first-day cover use (theme.PRINTED_COMIC_WEEKDAY_COLORS), so
# a day reads the same color everywhere. Gold (Tuesday) takes ink text; the rest
# take white, for legible ribbons.
_XP_WEEKDAY_TEXT = ("#fff", "#241C12", "#fff", "#fff", "#fff")
_XP_INK = "#241C12"


def _xp_day_frame_html(day: "xp_module.DayRecord", color: str, text: str) -> str:
    """One comic panel in the weekly strip -- a colored day ribbon over the
    day's haul and its +XP stamp. Future days and an untouched today read as a
    blank panel 'waiting to be drawn.'"""
    ribbon = (
        f'<div style="font-family:var(--c-head);font-weight:800;font-size:14px;'
        f'letter-spacing:.04em;color:{text};background:{color};padding:3px 8px;'
        f'display:flex;justify-content:space-between;align-items:center;'
        f'border-bottom:2.5px solid {_XP_INK};">'
        f'<span>{day.label}</span>'
        f'<span style="font-size:10px;opacity:.9;">'
        f'{"TODAY" if day.is_today else html.escape(day.short_date)}</span></div>'
    )

    if day.is_future or (day.is_today and not day.has_activity):
        inner = (
            '<div style="flex:1;display:flex;flex-direction:column;align-items:center;'
            'justify-content:center;text-align:center;gap:4px;padding:8px;">'
            + (
                '<span style="font-size:26px;">✏️</span>'
                '<b style="font-size:11px;line-height:1.1;">Your turn —<br>draw this one</b>'
                if day.is_today
                else '<span style="font-size:12px;color:var(--c-dim);font-weight:700;">— up next —</span>'
            )
            + "</div>"
        )
        border = f"2.5px dashed {_XP_INK}"
        bg = ("repeating-linear-gradient(135deg,var(--c-panel) 0 8px,"
              "rgba(36,28,18,.06) 8px 16px)")
    else:
        chips = []
        if day.lessons:
            chips.append(_xp_chip(f"✅ {day.lessons} lesson{'s' if day.lessons != 1 else ''}", "#fdeeb8"))
        if day.quizzes:
            chips.append(_xp_chip(f"🧠 {day.quizzes} quiz{'zes' if day.quizzes != 1 else ''}", "#d8e4fb"))
        if day.skills:
            chips.append(_xp_chip(f"📐 {day.skills} skill{'s' if day.skills != 1 else ''}", "#d5eddd"))
        if day.redos:
            chips.append(_xp_chip(
                f"↩️ redo −{day.redos * config.XP_SENT_BACK_PENALTY}",
                "#f7dcd9", fg="var(--c-bad)", border="var(--c-bad)"))
        if not chips:
            chips.append('<span style="font-size:12px;color:var(--c-dim);font-weight:700;">nothing yet</span>')
        # The +XP stamp: red when a rough day went negative, dim at zero.
        value = day.xp
        if value < 0:
            stamp_txt, stamp_bg = f"−{abs(value)}", "var(--c-bad)"
        else:
            stamp_txt, stamp_bg = f"+{value}", ("var(--c-primary)" if value else "rgba(36,28,18,.12)")
        stamp = (
            f'<div style="margin-top:auto;text-align:right;"><span style="font-family:var(--c-head);'
            f'font-weight:800;color:{_XP_INK};background:{stamp_bg};border:2px solid {_XP_INK};'
            f'padding:0 7px;border-radius:4px;box-shadow:2px 2px 0 {_XP_INK};display:inline-block;">'
            f'{stamp_txt}</span></div>'
        )
        inner = (
            '<div style="flex:1;display:flex;flex-direction:column;gap:5px;padding:8px;">'
            '<div style="display:flex;flex-direction:column;gap:4px;align-items:flex-start;">'
            + "".join(chips)
            + "</div>"
            + stamp
            + "</div>"
        )
        border = f"2.5px solid {_XP_INK}"
        bg = "var(--c-panel)"

    return (
        f'<div style="flex:0 0 122px;border:{border};border-radius:4px;background:{bg};'
        f'box-shadow:3px 3px 0 {_XP_INK};overflow:hidden;display:flex;flex-direction:column;'
        f'min-height:146px;scroll-snap-align:start;">{ribbon}{inner}</div>'
    )


def _xp_chip(label: str, bg: str, *, fg: str = _XP_INK, border: str | None = None) -> str:
    border = border or _XP_INK
    return (
        f'<span style="display:inline-flex;align-items:center;gap:4px;font-size:11px;'
        f'font-weight:800;border:2px solid {border};border-radius:20px;padding:0 7px;'
        f'background:{bg};color:{fg};white-space:nowrap;">{html.escape(label)}</span>'
    )


def _weekly_xp_html(state: "xp_module.XPState", progress: "xp_module.WeeklyProgress") -> str:
    """The card's visual centerpiece: the rank line, the goal meter, and the
    Mon-Fri comic strip ending in the reward payoff panel."""
    pct = round(progress.fraction * 100, 1)
    reward = html.escape(progress.reward_name)
    colors = theming.PRINTED_COMIC_WEEKDAY_COLORS

    header = (
        '<div style="display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:9px;">'
        '<span style="font-family:var(--c-head);font-weight:800;font-size:21px;'
        'letter-spacing:.03em;text-transform:uppercase;">🗓️ This Week</span>'
        f'<span style="font-size:11px;font-weight:800;text-transform:uppercase;letter-spacing:.03em;'
        f'color:#fff;background:var(--c-border);padding:3px 9px;border-radius:20px;'
        f'border:2px solid {_XP_INK};white-space:nowrap;">🧭 {html.escape(state.title)} · Lvl {state.level}</span>'
        "</div>"
    )

    meter = (
        '<div style="display:flex;align-items:baseline;justify-content:space-between;margin-bottom:5px;">'
        f'<span style="font-family:var(--c-head);font-weight:800;font-size:25px;line-height:.9;">'
        f'{progress.total}<span style="font-size:14px;color:var(--c-dim);"> / {progress.goal} XP</span></span>'
        f'<span style="font-size:12px;font-weight:800;color:var(--c-dim);">{progress.reward_emoji} Fri</span></div>'
        f'<div style="height:19px;border:2.5px solid {_XP_INK};border-radius:20px;background:var(--c-panel);'
        f'box-shadow:2px 2px 0 {_XP_INK};overflow:hidden;">'
        f'<div style="height:100%;width:{pct}%;background:repeating-linear-gradient(45deg,'
        f'var(--c-primary) 0 9px,#d99f00 9px 18px);'
        + (f'border-right:2.5px solid {_XP_INK};' if 0 < pct < 100 else "")
        + '"></div></div>'
    )

    if progress.reached:
        cap = f'<div style="font-size:12.5px;font-weight:800;margin-top:7px;color:var(--c-good);">🎉 {reward} — unlocked!</div>'
    else:
        cap = (
            f'<div style="font-size:12.5px;font-weight:700;margin-top:7px;">'
            f'<span style="color:var(--c-bad);font-weight:800;">{progress.remaining} XP</span> '
            f'to {reward} — {"one more push!" if progress.close else "keep at it."}</div>'
        )

    frames = "".join(
        _xp_day_frame_html(day, colors[i], _XP_WEEKDAY_TEXT[i])
        for i, day in enumerate(progress.days)
    )
    # The reward payoff panel closes the strip.
    lock = ("✅ earned" if progress.reached else f"🔒 at {progress.goal}")
    payoff = (
        f'<div style="flex:0 0 112px;border:2.5px solid {_XP_INK};border-radius:4px;'
        f'background:var(--c-primary);box-shadow:3px 3px 0 {_XP_INK};overflow:hidden;'
        f'display:flex;flex-direction:column;min-height:146px;scroll-snap-align:start;">'
        f'<div style="font-family:var(--c-head);font-weight:800;font-size:13px;color:{_XP_INK};'
        f'background:#d99f00;padding:3px 8px;border-bottom:2.5px solid {_XP_INK};">GOAL</div>'
        f'<div style="flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;'
        f'text-align:center;gap:5px;padding:8px;color:{_XP_INK};">'
        f'<span style="font-size:30px;line-height:1;">{progress.reward_emoji}</span>'
        f'<b style="font-size:11.5px;line-height:1.1;">{reward}</b>'
        f'<span style="font-size:10px;font-weight:800;text-transform:uppercase;">{lock}</span></div></div>'
    )

    strip = (
        '<div style="display:flex;gap:10px;overflow-x:auto;padding:4px 2px 10px;'
        'scroll-snap-type:x mandatory;">'
        + frames + payoff + "</div>"
        '<div style="font-size:10px;font-weight:800;color:var(--c-dim);text-transform:uppercase;'
        'letter-spacing:.05em;text-align:right;margin-top:-4px;">swipe →</div>'
    )

    return f'<div style="color:var(--c-text);">{header}{meter}{cap}{strip}</div>'


def render_xp_level(db: Database, student: dict[str, Any]) -> None:
    """His weekly XP card -- everything he finishes Mon-Fri turned into a comic
    strip climbing toward one reward by Friday. Core school work (lessons,
    quizzes, mastered skills) fills the bar; life skills, coding, and trips are
    the extra credit that tops him off if Friday's close. Computed live (see
    compass.xp) so it moves the moment he finishes something, and resets every
    Monday. Student view only; pure motivation, not a grade."""
    state = xp_module.compute(db, student["id"])
    progress = xp_module.weekly_progress(db, student["id"], date.today())

    st.markdown(_weekly_xp_html(state, progress), unsafe_allow_html=True)

    # Extra credit already banked this week -- the reserve that counts toward the
    # same goal, shown as its own line so the bar stays about school work.
    if progress.bonus_items:
        line = " · ".join(f"{b.emoji} {md(b.label)} +{b.xp}" for b in progress.bonus_items)
        st.caption(f"⚡ Bonus this week: {line}")

    # The reward state. Earned reads as a win to act on; close reads as a nudge
    # to grab one piece of extra credit; otherwise nothing extra is shown.
    if progress.reached and not progress.given:
        st.success(
            f"🎉 {progress.reward_emoji} **{md(progress.reward_name)}** unlocked — "
            "great week! Go ask a parent to make it happen."
        )
    elif progress.reached and progress.given:
        st.caption(f"✅ {progress.reward_emoji} {md(progress.reward_name)} — claimed. Nice week.")
    elif progress.close:
        opts = " · ".join(f"{b.emoji} {md(b.label)} +{b.xp}" for b in xp_module.bonus_options())
        st.info(
            f"⚡ **{progress.remaining} XP from {md(progress.reward_name)}** — you crushed the "
            f"school week. Finish one more to lock it in: {opts}."
        )

    # How the weekly score works, spelled out for him -- built from the same
    # config knobs the scoring uses, so the numbers here can't drift from what he
    # actually earns and loses.
    with st.expander("ℹ️ How the week works"):
        st.markdown(
            f"Everything you finish **Monday–Friday** fills the bar toward "
            f"**{progress.goal} XP**. Hit it and {progress.reward_emoji} "
            f"**{md(progress.reward_name)}** is yours for the weekend. It resets every Monday.\n\n"
            "**Fills the bar (your school work):**\n"
            f"- ✅ Finish a lesson: **+{config.XP_PER_LESSON}**\n"
            f"- 🧠 Pass a quiz: **+{config.XP_QUIZ_PASS_BONUS}**\n"
            f"- 📐 Master a math skill: **+{config.XP_PER_MASTERED_SKILL}**\n\n"
            "**Extra credit (tops you off if Friday's close):**\n"
            f"- 🛠️ Life skill or 💻 coding module: **+{config.XP_PER_LIFE_SKILL}** each\n"
            f"- 🧭 Write up a trip: **+{config.XP_PER_TRAVEL_ENTRY}**\n\n"
            "**The one thing that costs XP:**\n"
            f"- ↩️ A lesson **sent back** for a redo: **−{config.XP_SENT_BACK_PENALTY}** (each time). "
            "Read the whole assignment and do every part the first time, and you never lose any."
        )


def render_earned_rewards(db: Database, student: dict[str, Any]) -> None:
    """Parent-only: this week's reward alert. Reported: "i need to know as the
    parent when he hits one." His weekly XP crossing the goal is computed live,
    but nothing tells the parent -- so this surfaces the reward when he's
    **earned it but not yet been handed it**, with a button to mark it given.
    Reads as a notification when he's earned it, and a quiet one-line status the
    rest of the time."""
    progress = xp_module.weekly_progress(db, student["id"], date.today())
    name = student.get("name") or "He"

    if progress.earned_unclaimed:
        with st.container(border=True, key="parent_earned_rewards"):
            st.markdown(
                f"### {progress.reward_emoji} {md(name)} earned this week's reward — time to deliver"
            )
            st.caption(
                f"He hit {progress.total} / {progress.goal} XP this week. Hand it over in "
                "real life, then mark it given so it clears from here and shows as claimed "
                "on his screen."
            )
            cols = st.columns([4, 2])
            cols[0].markdown(
                f"{progress.reward_emoji} **{md(progress.reward_name)}**  \n"
                f"<span style='color:var(--c-dim); font-size:12px;'>"
                f"earned at {progress.goal} XP · week of {progress.week_start.strftime('%b %-d')}</span>",
                unsafe_allow_html=True,
            )
            if cols[1].button("✅ Mark as given", key="reward_given_week", width="stretch"):
                xp_module.set_week_reward_given(db, progress.week_start, True)
                st.rerun()
    elif progress.reached and progress.given:
        st.caption(
            f"✅ This week's reward given: {progress.reward_emoji} {md(progress.reward_name)}."
        )
        with st.expander("Undo 'given'"):
            if st.button(
                f"↩️ Un-give {progress.reward_emoji} {md(progress.reward_name)}",
                key="reward_ungive_week",
            ):
                xp_module.set_week_reward_given(db, progress.week_start, False)
                st.rerun()
    else:
        st.caption(
            f"🎯 This week: **{progress.total} / {progress.goal} XP** toward "
            f"{progress.reward_emoji} {md(progress.reward_name)} — "
            f"{progress.remaining} to go."
        )


def render_xp_reward_editor(db: Database) -> None:
    """Parent-only: set the weekly goal and the reward he's climbing toward --
    reported: "parent also needs ability to edit, adjust ... xp rewards." The
    student XP card reads these same settings, so a change here is what he sees
    next load. The point values themselves (per lesson, per quiz, ...) stay in
    config; this is the two knobs a parent actually turns."""
    goal = xp_module.weekly_goal(db)
    reward_name, reward_emoji = xp_module.weekly_reward(db)
    st.caption(
        "One reward a week. Set how much XP counts as a good week, and name what "
        "he earns for hitting it by Friday. Roughly a lesson is "
        f"+{config.XP_PER_LESSON} and a passed quiz +{config.XP_QUIZ_PASS_BONUS}, so "
        f"{goal} is about {max(1, goal // config.XP_PER_LESSON)} lessons' worth of work."
    )
    new_goal = st.number_input(
        "Weekly XP goal", min_value=10, max_value=5000, value=int(goal), step=10,
        key="xp_weekly_goal_input",
    )
    emoji_col, name_col = st.columns([1, 4])
    new_emoji = emoji_col.text_input("Emoji", value=reward_emoji, key="xp_weekly_reward_emoji_input")
    new_name = name_col.text_input("Reward", value=reward_name, key="xp_weekly_reward_name_input")

    save_col, reset_col = st.columns(2)
    if save_col.button("Save weekly reward", type="primary", key="save_xp_weekly"):
        xp_module.set_weekly_goal(db, int(new_goal))
        xp_module.set_weekly_reward(db, new_name, new_emoji)
        st.success("Weekly reward saved.")
        st.rerun()
    if reset_col.button("Reset to default", key="reset_xp_weekly"):
        for setting in ("xp_weekly_goal", "xp_weekly_reward_name", "xp_weekly_reward_emoji"):
            db.set_setting(setting, "")
        st.rerun()


def render_declaration_banner(db: Database, student: dict[str, Any]) -> None:
    """Parent-only: filing paperwork with the district, not a lesson matter.

    Washington's Declaration of Intent (RCW 28A.200.010) has nothing to do
    with hours or subject coverage, which is why it's tracked here rather than
    folded into the compliance report -- a family perfectly on pace for 1,000
    hours can still be about to miss this deadline.
    """
    ds = declaration_status(db, student["id"])
    when = f"{ds.due_on.strftime('%B')} {ds.due_on.day}, {ds.due_on.year}"

    if ds.filed:
        st.success(f"✅ Declaration of Intent filed on {ds.filed_on} for the {when} deadline.")
        return

    if ds.overdue:
        st.error(
            f"📌 **Declaration of Intent was due {when}** — file with your school "
            "district as soon as possible (WA RCW 28A.200.010)."
        )
    else:
        message = (
            f"📌 **Declaration of Intent due in {ds.days_remaining} days** — file with "
            f"your school district by {when} (WA RCW 28A.200.010)."
        )
        (st.warning if ds.days_remaining <= 14 else st.info)(message)

    columns = st.columns([3, 1])
    with columns[0]:
        if ds.url:
            st.caption(f"[Your district's filing page]({ds.url})")
        else:
            st.caption("Add your district's filing link in Compliance → Year settings.")
    with columns[1]:
        if st.button("Mark as filed", key="mark_declaration_filed"):
            db.mark_declaration_filed(student["id"], ds.due_on.isoformat())
            st.rerun()

from compass.ui.comic import (  # noqa: E402,F401
    _COMIC_PANEL_CSS,
    _COMIC_KIND_PILL_VARIANT,
    _COMIC_KIND_ICONS,
    _PHASE_LABELS,
    _PHASE_ICONS,
    _PHASE_PILL_VARIANT,
    activity_phase,
    _comic_phase_pill_html,
    _comic_review_flag_html,
    _writing_rework_summary,
    _comic_progress_dots_html,
    _render_reading_check,
    _feedback_history,
    _stored_ai_review,
    _render_ai_review_for_student,
    _render_activity_body,
    _render_activity_comic_panel,
    _render_learn_section,
    render_lesson,
)

from compass.ui.board import (  # noqa: E402,F401
    render_story_move_control,
    _render_board_deep_link,
    _render_board_detail,
    _render_board_estimate_editor,
    _project_step_pace,
    _TRAVEL_BOARD_PROMPTS,
    board_item_minutes,
    format_board_minutes,
    _BOARD_MOVE_NOTICE_KEY,
    _board_schedule,
    render_board_move_notice,
    render_reading_board_card,
    _SERIES_DAY_PREFIX_RE,
    series_day_title,
    render_board_card,
    _WEEK_BOARD_SCROLL_CSS,
    render_board_days,
    _BOARD_BACKLOG_SCROLL_CSS,
    render_board_backlog,
    _SUBJECT_WEEK_SCROLL_CSS,
    render_subject_week_tab,
)

from compass.ui.review import (  # noqa: E402,F401
    _hours_inputs,
    _log_hours_for_lesson,
    _render_quiz_review,
    _render_writing_review_controls,
    _render_activity_grade_picker,
    _render_final_grade_decision,
    render_lesson_review,
)

from compass.ui.lifeskill_cards import (  # noqa: E402,F401
    LIFE_SKILL_CATEGORY_ICONS,
    LIFE_SKILL_DEFAULT_ICON,
    LIFE_SKILL_CARDS_PER_ROW,
    _LIFE_SKILL_CARD_CSS,
    render_student_life_skills,
    render_life_skill_catalog_manager,
    render_life_skill_review_card,
    render_coding_module_cards,
    render_coding_module_catalog_manager,
    _CHOICE_STATUS_FLOW,
    render_choice_topics_section,
)

from compass.ui.vocab import (  # noqa: E402,F401
    VOCAB_STREAK_HYPE,
    VOCAB_STREAK_ON_FIRE,
    VOCAB_QUIZ_CHOICES,
    VOCAB_QUIZ_MIN_DEFINED_WORDS,
    _render_vocab_done_button,
    render_vocab_quiz,
    render_vocab_activity_for_parent,
)

from compass.ui.firstday import (  # noqa: E402,F401
    _FIRST_DAY_INK,
    _FIRST_DAY_PAPER,
    _FIRST_DAY_CARD_PAPER,
    _FIRST_DAY_COLORS,
    _FIRST_DAY_WINDOW_DAYS,
    _FIRST_DAY_CARD_CSS,
    render_first_day_celebration,
    _render_first_day_contents,
)
