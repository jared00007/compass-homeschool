"""Streamlit helpers shared across pages.

Kept out of `compass/` core modules on purpose — the agents, storage, and
compliance layers know nothing about Streamlit, so they stay testable and
reusable if the UI is ever replaced.

One large file rather than a package on purpose, for now: a fair number of
tests replace this module's own `st` name with a recording stand-in
(`monkeypatch.setattr(ui, "st", Recorder(...))` in tests/test_ui.py and
tests/test_auth.py) to exercise render functions without a real Streamlit
script context. Splitting this into submodules would give each one its own
separate `st` binding, silently breaking every one of those patches (they'd
patch the wrong module's name) unless the tests were rewritten in lockstep
-- a real, worthwhile refactor, but a deliberately separate one from a
general cleanup pass. In the meantime, the `# --- section ---` banners below
are searchable landmarks; grep this file for `^# ---` to jump straight
between them. In the order they appear:

    md()                          escape `$` before any user/AI text render
    parent / student mode          get_db, page_setup, sidebar chrome, auth
    generate -> review -> log loop generate_and_log and its small helpers
    lesson rendering                render_proposal, _needs_written_response
    "Comic Panels" lesson layout    the activity-card grid every subject uses
    life skills: teaching plan      render_life_skill_plan (parent-facing)
    logging hours                   log_lesson_form
    the in-lesson quiz              format_duration, render_quiz
    digital assessment card         render_assessment_card (Activity Log)
    student's own lesson view       student_lesson_view, render_past_lessons
    subject icons / Friday / daily  SUBJECT_ICONS, checklist, morning routine
    life skill cards                the catalog grid + its manager
    coding camp                     render_coding_module_cards + its catalog manager
    choice topics (Tier 3)          render_choice_topics_section, folded into Life Skills
    vocabulary review               the multiple-choice quiz, auto-graded
    API availability                api_status_banner
    first-day-of-school celebration a once-a-year full-page takeover
    small standalone banners        render_fun_fact, render_declaration_banner
"""

from __future__ import annotations

import html
import random
import sqlite3
import time
from datetime import date
from functools import partial
from typing import Any, Callable

import streamlit as st

from compass import (
    auth,
    config,
    daily,
    fun_facts,
    xp as xp_module,
    grades,
    gradebook,
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
from compass.agents import checklist_suggest, writing_review
from compass.agents.quiz import grade, passed as quiz_passes, select_questions
from compass.compliance import declaration_status
from compass.export import (
    DocxExtractionError,
    extract_docx_text,
    lesson_to_docx,
    lesson_to_pdf,
    suggested_filename,
    suggested_pdf_filename,
)
from compass.morning_routines import MORNING_ROUTINES, routine_for_date
from compass.storage.db import Database
from compass.writing_checks import check_writing, writing_hints


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
        _profile_control(db, student)
        st.divider()
        _mode_control(db)
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


def _mode_control(db: Database) -> None:
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
        st.caption("🔓 **Parent view**")
        if st.button("Switch to student view", width="stretch"):
            st.session_state["parent_unlocked"] = False
            st.rerun()
        with st.expander("Change or remove the PIN"):
            current = st.text_input("Current PIN", type="password", key="pin_cur")
            replacement = st.text_input("New PIN (blank to remove)", type="password", key="pin_rep")
            if st.button("Save"):
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


def generate_and_log(
    db: Database,
    student: dict[str, Any],
    agent: LessonAgent,
    ctx: StudentContext,
    proposal,
    *,
    primary_subject: str,
    spinner: str,
    api_ok: bool,
    location: str = "",
    after_render: str = "",
) -> None:
    """The whole Tier 1 loop: generate, surface warnings, render, offer to log.

    All four agent pages ran a near-identical copy of this. Keeping one copy
    matters beyond tidiness: the redaction in `render_lesson` and the warnings
    from credit/video normalization are the two things that must never be
    skipped on any page, and four hand-maintained copies is four chances to
    forget one.

    The generated lesson is held in session state under the agent's own key, so
    a rerun (logging hours, changing a widget) doesn't lose an expensive lesson.

    Session state is what makes a just-generated lesson stick around across
    reruns on *this* page -- but it's memory, not the record, so it's empty
    again after an app restart or a fresh browser session even though the
    lesson itself is still sitting in the database, unlogged. That gap is
    exactly what let two near-identical English lessons get generated one
    session apart with nothing on the page to say the first was still
    waiting: the button looked untouched. Checking the database itself for
    an existing planned lesson -- not just session state -- catches that.
    """
    state_key = f"{agent.key}_lesson"
    current = st.session_state.get(state_key)

    pending = [
        lesson
        for lesson in db.list_lessons(student["id"], agent=agent.key, limit=10)
        if lesson["status"] in ("planned", "submitted", "needs_revision")
        and (not current or lesson["id"] != current.lesson_id)
    ]
    if pending:
        st.warning(
            f"⚠️ **{pending[0]['title']}** is already generated and still open for this "
            "subject. Generating another leaves both waiting on his Home page -- review "
            "or remove the old one from Mission Control → Review."
        )

    if st.button("Generate lesson", type="primary", disabled=not api_ok or proposal.blocked):
        with st.spinner(spinner):
            try:
                st.session_state[state_key] = agent.generate(ctx, proposal)
            except LessonGenerationError as exc:
                st.error(str(exc))

    generated = st.session_state.get(state_key)
    if not generated:
        return

    # An on-demand lesson is "do this now" work -- stamp it for today so it's
    # real today-scheduled work on both Home and the board, rather than a
    # dateless lesson that shows on Home's roster but nowhere on the schedule
    # (reported: "today should only display lessons he is expected to review
    # TODAY... he has nothing scheduled in the boardview for today?"). A no-op
    # once it already has a day, so it never fights a real schedule.
    db.schedule_lesson_today_if_unscheduled(generated.lesson_id)

    st.divider()
    for warning in generated.warnings:
        st.caption(f"⚠️ {warning}")
    render_lesson(generated.payload)
    download_columns = st.columns(2)
    download_columns[0].download_button(
        "🖨️ Print to PDF",
        data=partial(lesson_to_pdf, generated.payload),
        file_name=suggested_pdf_filename(generated.payload),
        mime="application/pdf",
        key=f"{agent.key}_pdf_download",
    )
    download_columns[1].download_button(
        "📄 Word doc",
        data=partial(lesson_to_docx, generated.payload),
        file_name=suggested_filename(generated.payload),
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        key=f"{agent.key}_docx_download",
    )
    if after_render:
        st.caption(after_render)
    st.divider()
    log_lesson_form(
        db,
        student,
        generated,
        source=agent.key,
        primary_subject=primary_subject,
        location=location,
        key_prefix=agent.key,
    )


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


# --- "Comic Panels" lesson layout ---------------------------------------------
# Sampled three redesigns for the English page (stacked expanders felt "stale
# and full") and this is the one picked: activities become an ink-bordered
# panel grid instead of an accordion, each with an issue tag and a kind pill,
# always open rather than collapsed. Reuses theme.py's own CSS custom
# properties throughout (no new palette) -- opt-in via `comic_layout` on
# render_lesson so Math/Science/History keep the plain expander layout they
# already had.
_COMIC_PANEL_CSS = """
<style>
div[class*="st-key-comic_panel_"] {
  background: var(--c-panel);
  background-image: var(--c-panel-texture);
  background-repeat: no-repeat;
  border: 2px solid var(--c-text);
  border-radius: var(--c-radius);
  box-shadow: 4px 4px 0 rgba(36,28,18,.22);
  padding: .9rem 1.1rem .8rem;
  position: relative;
  margin-bottom: 1rem;
}
.comic-issue-tag {
  position: absolute;
  top: -12px;
  left: 14px;
  background: var(--c-primary);
  border: 2px solid var(--c-text);
  border-radius: 999px;
  font-family: var(--c-head);
  font-weight: 800;
  font-size: .68rem;
  padding: .15rem .55rem;
  color: var(--c-text);
  white-space: nowrap;
}
.comic-kind-icon { font-size: 1.2rem; margin-right: .35rem; }
.comic-pill {
  display: inline-flex; align-items: center; gap: .3rem;
  font-family: var(--c-head); font-weight: 700; font-size: .66rem;
  text-transform: uppercase; letter-spacing: .03em;
  padding: .2rem .55rem; border-radius: 999px;
}
.comic-pill--reading { background: var(--c-pill-reading-bg); color: var(--c-alt); }
.comic-pill--writing { background: var(--c-pill-writing-bg); color: var(--c-warn); }
.comic-pill--discussion { background: var(--c-pill-discussion-bg); color: var(--c-good); }
.comic-pill--instruction { background: var(--c-pill-instruction-bg); color: var(--c-pill-instruction-fg); }
.comic-pill--neutral { background: var(--c-panel); color: var(--c-dim); border: 1px solid var(--c-border); }
.comic-progress-dots { display: flex; gap: .4rem; margin: .1rem 0 1.1rem; }
.comic-progress-dots span {
  width: 26px; height: 8px; border-radius: 999px; background: var(--c-border);
  opacity: .25; display: inline-block;
}
.comic-progress-dots span.done { background: var(--c-good); opacity: 1; }
.comic-progress-dots span.current { background: var(--c-primary); opacity: 1; }
div[class*="st-key-comic_frame_"] {
  background: var(--c-panel);
  border: 1px solid var(--c-border);
  border-radius: var(--c-radius);
  box-shadow: 5px 5px 0 rgba(36,28,18,.14);
  padding: 1.5rem 1.6rem 1.3rem;
  margin-bottom: 1.3rem;
}
.comic-frame-title {
  font-family: var(--c-head);
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: .02em;
  font-size: .78rem;
  color: var(--c-dim);
  margin-bottom: 1rem;
  display: flex;
  align-items: center;
  gap: .4rem;
}
</style>
"""

_COMIC_KIND_PILL_VARIANT = {
    "reading": "reading",
    "writing": "writing",
    "discussion": "discussion",
    "instruction": "instruction",
}
_COMIC_KIND_ICONS = {
    "reading": "📚",
    "writing": "✍️",
    "discussion": "💬",
    "instruction": "🧭",
    "practice": "🛠️",
    "field": "🧳",
    "project": "🧩",
    "assessment": "📝",
}

# Activities now carry a phase (learn/practice) instead of the old 8-value kind.
_PHASE_LABELS = {"learn": "Learn", "practice": "Practice"}
_PHASE_ICONS = {"learn": "📖", "practice": "🛠️"}
_PHASE_PILL_VARIANT = {"learn": "instruction", "practice": "writing"}


def activity_phase(activity: dict[str, Any]) -> str:
    """learn or practice. New lessons carry `phase` directly; a lesson written
    before the switch is read off its old `kind` -- only a bare "instruction"
    was teaching, everything else was work he did."""
    phase = activity.get("phase")
    if phase in _PHASE_LABELS:
        return phase
    return "learn" if activity.get("kind") == "instruction" else "practice"


def _comic_phase_pill_html(activity: dict[str, Any]) -> str:
    phase = activity_phase(activity)
    variant = _PHASE_PILL_VARIANT.get(phase, "neutral")
    icon = _PHASE_ICONS.get(phase, "📌")
    label = html.escape(_PHASE_LABELS.get(phase, "activity"))
    return (
        f'<span class="comic-kind-icon">{icon}</span>'
        f'<span class="comic-pill comic-pill--{variant}">{label}</span>'
    )


def _comic_progress_dots_html(
    activities: list[dict[str, Any]], metadata: dict[str, Any] | None
) -> str:
    """One dot per activity, in order. There's no real per-activity "done"
    signal for a reading/instruction/discussion activity -- he doesn't check
    those off individually -- so this reads activities in sequence and
    treats everything up to the next *unmet* typed-response requirement as
    passed, the requirement itself as "current", and anything after as still
    ahead. A lesson with no typed-response activity at all falls back to the
    one real lesson-level signal instead of inventing per-activity state:
    every dot lit once he's marked the whole lesson done, none lit before
    that.
    """
    if not activities:
        return ""
    metadata = metadata or {}
    required = [i for i, a in enumerate(activities) if _needs_written_response(a)]
    if required:
        saved = metadata.get("writing_responses") or {}
        done = {i for i in required if (saved.get(str(i)) or "").strip()}
        next_up = next((i for i in required if i not in done), None)
        cutoff = next_up if next_up is not None else len(activities)
        classes = [
            "done" if i < cutoff else ("current" if i == cutoff else "")
            for i in range(len(activities))
        ]
    else:
        lit = bool(metadata.get("student_done_on"))
        classes = ["done" if lit else "" for _ in activities]
    dots = "".join(f'<span class="{c}"></span>' for c in classes)
    return '<div class="comic-progress-dots">' + dots + "</div>"


def _render_reading_check(
    activity: dict[str, Any],
    index: int,
    *,
    db: Database,
    lesson_id: int,
    metadata: dict[str, Any] | None,
) -> None:
    """"Did you actually read it?" -- two or three specifics from the text,
    graded on the spot.

    Every English lesson opens with "read chapters 9-10" and, before this,
    nothing ever checked that it happened -- which is plausibly upstream of
    a lot of thin writing, since you can't write 200 words about a chapter
    you skimmed. Deliberately ungated: it reports, it doesn't block. A
    question the model got wrong about an obscure book would otherwise
    strand him on reading he actually did.
    """
    questions = activity.get("reading_check") or []
    if not questions:
        return

    stored = ((metadata or {}).get("reading_checks") or {}).get(str(index))
    if stored:
        correct, total = stored.get("correct", 0), stored.get("total", 0)
        if total and correct == total:
            st.success(f"📖 Reading check: {correct}/{total} — you read it.")
        else:
            st.warning(
                f"📖 Reading check: {correct}/{total}. Worth going back over that "
                "part before you keep going."
            )
        return

    with st.form(f"reading_check_{lesson_id}_{index}"):
        st.markdown("**📖 Quick check — did you read it?**")
        picks: list[int | None] = []
        for question_index, item in enumerate(questions):
            st.markdown(f"{question_index + 1}. {md(item['question'])}")
            picks.append(
                st.radio(
                    "choices",
                    options=list(range(len(item["choices"]))),
                    format_func=lambda i, choices=item["choices"]: md(choices[i]),
                    index=None,
                    label_visibility="collapsed",
                    key=f"reading_pick_{lesson_id}_{index}_{question_index}",
                )
            )
        submitted = st.form_submit_button("Check")

    if submitted:
        if any(pick is None for pick in picks):
            st.warning("Answer all of them first.")
            return
        correct = sum(
            1 for item, pick in zip(questions, picks) if pick == item["correct_index"]
        )
        db.save_reading_check(lesson_id, index, correct, len(questions))
        st.rerun()


def _feedback_history(source: dict[str, Any], *, history_key: str, single_key: str) -> list[str]:
    """Every note given so far on one piece of feedback, oldest first --
    falls back to a single legacy field for data saved before `history_key`
    existed. Shared by every place that reads a feedback trail (per-activity
    writing review, student and parent side, and the whole-lesson banner)
    so a future change to the fallback rule can't be applied to two of the
    three copies and forgotten on the third -- exactly what happened once
    already, when a second bounce silently overwrote the first note."""
    return source.get(history_key) or (
        [source[single_key]] if source.get(single_key) else []
    )


def _stored_ai_review(metadata: dict[str, Any] | None, index: int) -> dict[str, Any] | None:
    """The automated read of this activity's response, if one has been run.

    Read straight off the metadata already in hand rather than through
    `writing_review.existing_review`, which takes a whole lesson row --
    the render path only ever has the metadata dict.
    """
    return ((metadata or {}).get("writing_ai_review") or {}).get(str(index))


def _render_ai_review_for_student(review: dict[str, Any]) -> None:
    """His side of the stored review: what's working, then at most two next
    moves. The parent's own view of the same result (in
    `render_assessment_card`) carries the fuller diagnostic -- the missing
    requirements and any factual corrections -- deliberately not repeated
    here, where a wall of everything wrong is the thing most likely to make
    him give up rather than revise."""
    st.divider()
    st.markdown("**🔍 A read on what you wrote**")
    for strength in review.get("strengths") or []:
        st.success(f"👍 {md(strength)}")
    # Amber and marked "go fix", not a neutral blue note -- these are the
    # whole reason the read exists, and a plain arrow in an info box reads
    # as "here's a thought" rather than "this needs another pass." 🔁 is the
    # same "needs more work" mark the assessment verdicts already use
    # (config.ASSESSMENT_VERDICT_LABELS), so it means one thing app-wide.
    for move in review.get("next_moves") or []:
        st.warning(f"🔁 **Go fix this:** {md(move)}")
    if not (review.get("next_moves") or review.get("strengths")):
        st.caption("Nothing flagged — give it another read yourself, then submit.")
    st.caption("This is a suggestion, not a grade. Your parent still reads it too.")


def _render_activity_body(
    activity: dict[str, Any],
    index: int,
    *,
    parent: bool,
    db: Database | None,
    lesson_id: int | None,
    metadata: dict[str, Any] | None,
    student: dict[str, Any] | None = None,
    review_owns_response: bool = False,
) -> None:
    """The inside of one activity: video, worked example, instructions, and
    (when it applies) the typed-response box. Shared by both the plain
    expander layout and the comic-panel layout so the two never drift apart.

    `review_owns_response` is set only by the parent's inline grading view
    (render_lesson_review): there, his written response and the approve/send
    -back controls are rendered together right below the activity by
    `_render_writing_review_controls`, so this function renders the activity
    *content* and stops short of showing the response a second time."""
    video = activity.get("video") or {}
    if video.get("found") and video.get("url"):
        st.markdown(f"▶️ **[{md(video.get('title', 'Watch'))}]({video['url']})**")
        caption_parts = []
        if video.get("channel"):
            caption_parts.append(video["channel"])
        if video.get("why"):
            caption_parts.append(video["why"])
        if caption_parts:
            st.caption(" — ".join(caption_parts))
        if parent:
            st.caption(
                "Checked against a real search result and restricted to "
                "YouTube, but Compass doesn't control what YouTube "
                "recommends once the video ends."
            )

    example = activity.get("example")
    if example:
        st.markdown(
            f'<div style="background:var(--c-panel); border-left:3px solid '
            f'var(--c-alt); border-radius:var(--c-radius); padding:10px 14px; '
            f'margin-bottom:10px; font-size:13.5px;">'
            f'<b>📖 Here\'s how:</b><br>{html.escape(example).replace(chr(10), "<br>")}'
            f"</div>",
            unsafe_allow_html=True,
        )
    st.write(md(activity.get("instructions", "")))

    if not parent and db is not None and lesson_id is not None:
        _render_reading_check(
            activity, index, db=db, lesson_id=lesson_id, metadata=metadata
        )

    # Practice feedback: for an objective activity, the worked answers to its own
    # problems, tucked behind a toggle so he tries first and then sees where he
    # went wrong. This is the "practice is reviewed" half of Learn -> Practice ->
    # Prove for anything the parent doesn't hand-grade.
    self_check = activity.get("self_check")
    if self_check:
        with st.expander("✅ Check your work", expanded=False):
            st.caption("Give it a real try first — then open this to see how you did.")
            st.markdown(md(self_check))

    if _needs_written_response(activity) and not review_owns_response:
        saved = ((metadata or {}).get("writing_responses") or {}).get(str(index), "")
        if not parent and db is not None and lesson_id is not None:
            review = ((metadata or {}).get("writing_review") or {}).get(str(index), {})
            status = review.get("status", config.WRITING_DRAFT)

            if status == config.WRITING_APPROVED:
                st.success("✅ Your parent approved this one.")
                approval_note = review.get("approval_feedback")
                if approval_note and not review.get("approval_read_at"):
                    # Approved, so it counts -- but they left you something to
                    # read. Same deal as travel-journal feedback: you have to
                    # tick that you saw it, so a note isn't lost just because
                    # the piece already passed.
                    st.info(f"💬 A note from your parent: {md(approval_note)}")
                    if st.button(
                        "👍 Got it — I read this",
                        key=f"ack_writing_{lesson_id}_{index}",
                    ):
                        db.mark_writing_feedback_read(lesson_id, index)
                        st.rerun()
                elif approval_note:
                    st.caption(f"💬 Note from your parent: {md(approval_note)}")
                st.write(md(saved))
                return

            if status == config.WRITING_NEEDS_REVISION:
                history = _feedback_history(
                    review, history_key="feedback_history", single_key="feedback"
                )
                if len(history) == 1:
                    st.warning(f"Your parent asked for another look: {md(history[0])}")
                elif history:
                    st.warning(
                        "Your parent asked for another look — everything they've flagged "
                        "so far:\n\n" + "\n".join(f"- {md(note)}" for note in history)
                    )
                else:
                    st.warning("Your parent asked for another look — revise it below.")

            if status == config.WRITING_SUBMITTED:
                st.info("⏳ Submitted — waiting on your parent to look at it.")
                st.write(md(saved))
                if st.button(
                    "✏️ Actually, let me revise it",
                    key=f"reopen_writing_{lesson_id}_{index}",
                ):
                    db.set_writing_review(lesson_id, index, config.WRITING_DRAFT)
                    st.rerun()
                return

            draft_key = f"writing_draft_{lesson_id}_{index}"
            # Some kids would rather write in Word than in the box below --
            # the upload just refills that box with the doc's text rather
            # than opening a separate review path, so every check further
            # down (word count, AI review, parent review) keeps working
            # exactly the same whichever way the words got there. Has to run
            # -- and, on a change, rerun -- *before* the text_area below is
            # instantiated: Streamlit refuses a session_state write to a
            # widget's own key once that widget has already appeared this
            # run. Uploading again overwrites whatever's in the box, same as
            # re-typing over it would; comparing against the box's current
            # value (rather than unconditionally rerunning) is what stops
            # this from fighting a response he's since edited by hand -- the
            # file stays "uploaded" across reruns even after its text has
            # already been pulled in.
            uploaded_doc = st.file_uploader(
                "...or upload a Word doc instead",
                type=["docx"],
                key=f"writing_upload_{lesson_id}_{index}",
            )
            if uploaded_doc is not None:
                try:
                    extracted = extract_docx_text(uploaded_doc)
                except DocxExtractionError as exc:
                    st.error(str(exc))
                else:
                    if extracted != st.session_state.get(draft_key, saved):
                        st.session_state[draft_key] = extracted
                        st.rerun()
            # The parts he has to cover, one checkbox each -- the fix for
            # skimming a multi-part prompt and answering only the first half.
            # He has to tick every one before "Submit for review" unlocks, so
            # each requirement is something he had to see and acknowledge, not
            # something buried in a paragraph he read past. Ticks persist
            # (checklist_checked in metadata) so a reload doesn't re-lock it.
            checklist_items = activity.get("checklist") or []
            checklist_ready = True
            if checklist_items:
                stored_checks = (
                    ((metadata or {}).get("checklist_checked") or {}).get(str(index)) or []
                )
                for item_index in range(len(checklist_items)):
                    state_key = f"checkitem_{lesson_id}_{index}_{item_index}"
                    if state_key not in st.session_state:
                        st.session_state[state_key] = (
                            stored_checks[item_index]
                            if item_index < len(stored_checks)
                            else False
                        )

                def _persist_checklist(lid=lesson_id, idx=index, count=len(checklist_items)):
                    db.set_activity_checklist(
                        lid,
                        idx,
                        [
                            bool(st.session_state.get(f"checkitem_{lid}_{idx}_{i}"))
                            for i in range(count)
                        ],
                    )

                st.markdown("**✅ Before you turn it in, check off each part:**")
                checked = [
                    st.checkbox(
                        md(item),
                        key=f"checkitem_{lesson_id}_{index}_{item_index}",
                        on_change=_persist_checklist,
                    )
                    for item_index, item in enumerate(checklist_items)
                ]
                checklist_ready = all(checked)

            response = st.text_area(
                "Your response",
                value=st.session_state.get(draft_key, saved),
                height=160,
                key=draft_key,
            )

            # Coach-only self-help, never a block. The mechanical basics he
            # keeps skipping (capitals, run-ons, end punctuation) caught
            # instantly so he can fix them himself, and -- for anything
            # paragraph-shaped -- a structure to lean on when a blank box is
            # the thing that stalls him. Deeper feedback is "Check my work"
            # and the parent's review.
            for hint_index, hint in enumerate(writing_hints(response)):
                if hint_index == 0:
                    st.caption("✍️ Quick check before you turn it in:")
                st.caption(f"• {hint}")
            _writing_reqs = activity.get("writing_requirements") or {}
            wants_paragraph = (
                activity.get("kind") == "writing"
                or (_writing_reqs.get("min_words") or 0) >= 40
                or (_writing_reqs.get("min_sentences") or 0) >= 3
            )
            if wants_paragraph:
                with st.expander("🧱 Not sure how to structure it?"):
                    st.markdown(
                        "- **Start** with your main point in one clear sentence.\n"
                        "- **Then** give two reasons or examples that back it up.\n"
                        "- **End** by restating your point in a new way."
                    )

            ai_review = _stored_ai_review(metadata, index)
            save_col, check_col, submit_col = st.columns(3)
            if save_col.button("Save draft", key=f"save_writing_{lesson_id}_{index}"):
                db.save_writing_response(lesson_id, index, response)
                st.success("Saved.")
                st.rerun()
            # One call per activity, ever -- the button is gone once a review
            # exists, so a student who'd rather not write can't iterate
            # against the reviewer in place of thinking. Deliberately not
            # offered while there's nothing written to review.
            if ai_review is None and response.strip():
                if check_col.button(
                    "🔍 Check my work", key=f"aicheck_writing_{lesson_id}_{index}"
                ):
                    db.save_writing_response(lesson_id, index, response)
                    with st.spinner("Reading what you wrote…"):
                        try:
                            writing_review.review_writing(
                                db, student, db.get_lesson(lesson_id), index, response
                            )
                        except LessonGenerationError as exc:
                            st.error(str(exc))
                        else:
                            st.rerun()
            submit_clicked = submit_col.button(
                "Submit for review",
                key=f"submit_writing_{lesson_id}_{index}",
                type="primary",
                disabled=not checklist_ready,
            )
            if not checklist_ready:
                st.caption(
                    "Tick every part above once you've actually done it — that's how "
                    "you turn this in."
                )
            if submit_clicked:
                requirements = activity.get("writing_requirements")
                # A math answer is a number or an expression, not prose --
                # "42" is a complete answer, not a zero-sentence failure. The
                # generator sometimes tags a numeric-answer step as a written
                # response and even sets min_sentences on it, which then
                # rejected the answer until he typed a stray period to make it
                # count as a "sentence." Prose word/sentence/quote rules never
                # apply to a math response; only the not-blank check does.
                lesson_row = db.get_lesson(lesson_id)
                if lesson_row and lesson_row.get("agent") == "math":
                    requirements = None
                problems = check_writing(response, requirements)
                if problems:
                    for problem in problems:
                        st.error(problem)
                else:
                    db.save_writing_response(lesson_id, index, response)
                    db.set_writing_review(lesson_id, index, config.WRITING_SUBMITTED)
                    if _maybe_auto_submit_lesson(db, lesson_id):
                        st.success(
                            "Submitted — that was the last thing, so your whole "
                            "lesson just went to your parent to review. 📬"
                        )
                    else:
                        st.success("Submitted!")
                    st.rerun()

            if ai_review is not None:
                _render_ai_review_for_student(ai_review)
        elif saved:
            st.markdown("**His response**")
            st.write(md(saved))


def _render_activity_comic_panel(
    activity: dict[str, Any],
    index: int,
    *,
    parent: bool,
    db: Database | None,
    lesson_id: int | None,
    metadata: dict[str, Any] | None,
    key_prefix: str,
    student: dict[str, Any] | None = None,
) -> None:
    """One activity's card, full width. Collapsing is his own reading
    convenience -- a card he's tucked away as done shrinks to just the
    title bar with a reopen button, nothing more. Parent view always
    shows every card in full regardless of what's collapsed: a parent
    opening a lesson to review or approve it needs to see everything, not
    whatever the student happened to tuck away for himself while working
    through it.
    """
    collapsed = (
        not parent
        and db is not None
        and lesson_id is not None
        and index in ((metadata or {}).get("collapsed_activities") or [])
    )

    with st.container(key=f"comic_panel_activity_{key_prefix}_{index}"):
        st.markdown(f'<div class="comic-issue-tag">No. {index + 1}</div>', unsafe_allow_html=True)
        st.markdown(
            f"##### {md(activity.get('title', 'Activity'))}  \n"
            f"{_comic_phase_pill_html(activity)}",
            unsafe_allow_html=True,
        )
        if collapsed:
            if st.button("↩️ Done — tap to reopen", key=f"reopen_activity_{key_prefix}_{index}"):
                db.set_activity_collapsed(lesson_id, index, False)
                st.rerun()
            return

        st.caption(f"{activity.get('minutes', 0)} min")
        _render_activity_body(
            activity, index, parent=parent, db=db, lesson_id=lesson_id,
            metadata=metadata, student=student,
        )
        if not parent and db is not None and lesson_id is not None:
            if st.button("✅ Mark this one done", key=f"collapse_activity_{key_prefix}_{index}"):
                db.set_activity_collapsed(lesson_id, index, True)
                st.rerun()


def _render_learn_section(lesson: dict[str, Any], *, parent: bool) -> None:
    """The teaching half of the fixed lesson shape -- the Learn explanation (with
    its one video) and the walked-through Worked example -- rendered before the
    two graded activities. Silent on an old-shape lesson that has neither, so it
    layers in without disturbing how existing lessons render."""
    learn = lesson.get("learn") or {}
    explanation = (learn.get("explanation") or "").strip()
    worked = lesson.get("worked_example") or {}
    problem = (worked.get("problem") or "").strip()
    steps = (worked.get("steps") or "").strip()

    if explanation:
        st.markdown("### 📗 Learn")
        st.write(md(explanation))
        video = learn.get("video") or {}
        if video.get("found") and video.get("url"):
            st.markdown(f"▶️ **[{md(video.get('title', 'Watch'))}]({video['url']})**")
            bits = [b for b in (video.get("channel"), video.get("why")) if b]
            if bits:
                st.caption(" — ".join(bits))
            if parent:
                st.caption(
                    "Checked against a real search result and restricted to YouTube, "
                    "but Compass doesn't control what YouTube recommends after it ends."
                )

    if problem or steps:
        st.markdown("### 🧭 Let's do one together")
        st.caption("Worked all the way through, so you can see how — you're not graded on this one.")
        if problem:
            st.markdown(f"**{md(problem)}**")
        if steps:
            st.markdown(
                f'<div style="background:var(--c-panel); border-left:3px solid '
                f'var(--c-alt); border-radius:var(--c-radius); padding:10px 14px; '
                f'margin:6px 0 12px; font-size:14px;">'
                f'{html.escape(steps).replace(chr(10), "<br>")}</div>',
                unsafe_allow_html=True,
            )

    if explanation or problem or steps:
        # The graded work starts here -- a clear line between "taught" and "your
        # turn," since the two activities below are what actually get a grade.
        st.markdown("### ✏️ Now you try")


def render_lesson(
    lesson: dict[str, Any],
    for_parent: bool | None = None,
    *,
    db: Database | None = None,
    lesson_id: int | None = None,
    metadata: dict[str, Any] | None = None,
    comic_layout: bool = False,
    comic_frame_title: str = "📘 Current Lesson",
    student: dict[str, Any] | None = None,
) -> None:
    """Render a lesson. In student view the answer key never reaches the page.

    The redaction happens here rather than in a CSS class or an expander, because
    anything sent to the browser can be read out of it. What a student must not
    see is simply not written.

    `db`/`lesson_id`/`metadata` are optional and only matter for a writing
    activity: given all three, in student view, that activity gets an actual
    text box instead of just instructions to write on paper -- his response
    saves straight to this lesson (`Database.save_writing_response`), which
    is what `render_assessment_card` later shows a parent when it's time to
    check the lesson. Omitted (the generation-preview call in
    `generate_and_log`, where nothing's been written yet and the viewer is
    the parent anyway), the writing activity just renders like any other.
    """
    parent = is_parent() if for_parent is None else for_parent
    objectives = lesson.get("learning_objectives") or []
    materials = lesson.get("materials") or []
    activities = lesson.get("activities") or []

    if comic_layout:
        st.markdown(_COMIC_PANEL_CSS, unsafe_allow_html=True)
        key_prefix = str(lesson_id) if lesson_id is not None else str(id(lesson))
        with st.container(key=f"comic_frame_lesson_{key_prefix}"):
            st.markdown(
                f'<div class="comic-frame-title">{html.escape(comic_frame_title)}</div>',
                unsafe_allow_html=True,
            )
            dots = _comic_progress_dots_html(activities, metadata)
            if dots:
                st.markdown(dots, unsafe_allow_html=True)

            st.markdown(f"## {md(lesson.get('title', 'Lesson'))}")
            if lesson.get("overview"):
                st.write(md(lesson["overview"]))

            if objectives or materials:
                columns = st.columns(2)
                with columns[0]:
                    if objectives:
                        st.markdown("**Learning objectives**")
                        for objective in objectives:
                            st.markdown(f"- {md(objective)}")
                with columns[1]:
                    # Materials before activities on purpose -- knowing what
                    # you need is part of being set up to start, not a
                    # footnote to read after being told what to do.
                    if materials:
                        st.markdown("**Materials**")
                        for item in materials:
                            st.markdown(f"- {md(item)}")

            # The teaching half (Learn + Worked example) comes before the two
            # graded activities in the fixed lesson shape.
            _render_learn_section(lesson, parent=parent)

            # Single column, full width -- pairing two activities per row
            # (the original comic-grid mockup) left mismatched-height cards
            # squeezed side by side whenever one activity had more to show
            # than its neighbor (a video, a worked example). One card per
            # row lets each one take exactly the room it needs.
            for index, activity in enumerate(activities):
                _render_activity_comic_panel(
                    activity,
                    index,
                    parent=parent,
                    db=db,
                    lesson_id=lesson_id,
                    metadata=metadata,
                    key_prefix=key_prefix,
                    student=student,
                )
    else:
        st.subheader(md(lesson.get("title", "Lesson")))
        if lesson.get("overview"):
            st.write(md(lesson["overview"]))

        if objectives:
            st.markdown("**Learning objectives**")
            for objective in objectives:
                st.markdown(f"- {md(objective)}")
        if materials:
            st.markdown("**Materials**")
            for item in materials:
                st.markdown(f"- {md(item)}")

        _render_learn_section(lesson, parent=parent)

        if activities:
            st.markdown("**Activities**")
            for index, activity in enumerate(activities, start=1):
                header = (
                    f"{index}. {md(activity.get('title', 'Activity'))} · "
                    f"{_PHASE_LABELS.get(activity_phase(activity), '')} · {activity.get('minutes', 0)} min"
                )
                with st.expander(header, expanded=False):
                    _render_activity_body(
                        activity,
                        index - 1,
                        parent=parent,
                        db=db,
                        lesson_id=lesson_id,
                        metadata=metadata,
                        student=student,
                    )

    # Parent-only: the actual check now happens digitally, in Activity Log's
    # own review card (render_assessment_card), not here -- nothing for him
    # to do with this text, so student view shows nothing at all rather than
    # a "your parent has it" stub that no longer matches how it's checked.
    assessment = lesson.get("assessment") or {}
    # The rubric is the ONE part of the hand-in that's safe for him to see -- it
    # describes qualities of a strong response, not the answers. Shown to him as
    # his bar before he starts; the parent also gets it in the grading panel.
    if assessment.get("rubric") and not parent:
        with st.container(border=True, key=f"landon_card_rubric_{lesson_id or 'x'}"):
            st.markdown("**🎯 What a strong hand-in looks like**")
            st.markdown(md(assessment["rubric"]))
    if assessment and parent:
        st.markdown("**Hand-in** (the work he turns in for you to grade)")
        st.caption(
            "One of the two things his grade comes from -- the finished piece "
            "he hands you, graded with the 5-band verdict in the review tab. "
            "The other is the on-screen quiz below, which he takes and grades "
            "himself. Everything above is practice that gets him ready for these."
        )
        st.markdown(f"*{md(assessment.get('kind', ''))}* — {md(assessment.get('description', ''))}")
        if assessment.get("rubric"):
            st.markdown(f"**How it's graded (he sees this too):**\n\n{md(assessment['rubric'])}")
        if assessment.get("mastery_criteria"):
            st.markdown(f"**Counts as mastered when:** {md(assessment['mastery_criteria'])}")

    if parent:
        if lesson.get("parent_notes"):
            with st.expander("Notes for the parent"):
                st.write(md(lesson["parent_notes"]))

        credits = lesson.get("subject_credits") or []
        if credits:
            st.markdown("**Subject credit (feeds the WA compliance dashboard)**")
            for credit in credits:
                st.markdown(
                    f"- **{subjects.label(credit['subject'])}** — {credit['minutes']} min · "
                    f"{md(credit.get('justification', ''))}"
                )

        branches = lesson.get("branches") or []
        if branches:
            with st.expander(f"Branches this opens up ({len(branches)})"):
                for branch in branches:
                    st.markdown(f"- **{md(branch.get('topic'))}** — {md(branch.get('rationale', ''))}")

        quiz = lesson.get("quiz") or []
        if quiz:
            with st.expander(f"Quiz answer key ({len(quiz)} questions)"):
                for index, item in enumerate(quiz, start=1):
                    st.markdown(f"**{index}. {md(item['question'])}**")
                    for choice_index, choice in enumerate(item["choices"]):
                        marker = "✅" if choice_index == item["correct_index"] else "—"
                        st.markdown(f"{marker} {md(choice)}")
                    if item.get("explanation"):
                        st.caption(md(item["explanation"]))


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

                correct, total = grade(quiz, picks)
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

                # A literal perfect score, not the (configurable, sometimes
                # lower) pass/mastery threshold -- and fired here, at the
                # moment of grading, rather than in the results branch below,
                # which redraws on every rerun a persisted result is showing
                # (an unrelated widget elsewhere on the page, the quiz
                # expander toggling) and would otherwise launch balloons
                # over and over for the same score.
                if correct == total:
                    st.balloons()
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


# --- the digital assessment card (Activity Log's review flow) ------------------


def _hours_inputs(payload: dict[str, Any], key_prefix: str) -> tuple[int, str, dict[str, int]]:
    """The minutes/location/subject-credit inputs shared by every place that
    finishes a lesson -- the same fields `log_lesson_form` collects for a
    Life Skills lesson, reused here so approving a graded-subject lesson
    can log its hours in the same click rather than a second form.

    Must be called inside an open `st.form`.
    """
    columns = st.columns(2)
    with columns[0]:
        minutes = st.number_input(
            "Total minutes",
            min_value=5,
            max_value=600,
            value=int(payload.get("estimated_minutes") or 60),
            step=5,
            key=f"{key_prefix}_minutes",
        )
    with columns[1]:
        where = st.text_input("Location", key=f"{key_prefix}_location")
    credits: dict[str, int] = {}
    subject_credits = payload.get("subject_credits") or []
    if subject_credits:
        st.caption("Subject credit")
        credit_columns = st.columns(len(subject_credits))
        for column, credit in zip(credit_columns, subject_credits):
            with column:
                credits[credit["subject"]] = st.number_input(
                    subjects.label(credit["subject"]),
                    min_value=0,
                    max_value=600,
                    value=int(credit["minutes"]),
                    step=5,
                    key=f"{key_prefix}_credit_{credit['subject']}",
                )
    return int(minutes), where, credits


def _log_hours_for_lesson(
    db: Database,
    student: dict[str, Any],
    lesson: dict[str, Any],
    *,
    minutes: int,
    location: str,
    credits: dict[str, int],
) -> None:
    """The actual db.log_activity call behind every "Approve & log hours"
    button below -- log_activity already sets status='completed' when
    given a lesson_id, so approving and archiving are the same act."""
    payload = lesson["payload"]
    db.log_activity(
        student_id=student["id"],
        title=lesson.get("title", "Lesson"),
        tier=config.TIER_CORE,
        primary_subject=lesson["subject"],
        minutes=minutes,
        subject_credits={k: v for k, v in credits.items() if v > 0},
        occurred_on=date.today().isoformat(),
        description=payload.get("overview", ""),
        source=lesson["agent"],
        location=location,
        lesson_id=lesson["id"],
    )


def _render_quiz_review(db: Database, student: dict[str, Any], lesson: dict[str, Any]) -> bool:
    """The quiz he took, laid out for the parent the same way his own
    graded view showed it -- each question, which answer he picked, which
    was right, and the explanation. The review card used to surface the
    quiz as a single score line and nothing more, so a parent could see
    *that* he scored 4/5 but never *which* one he missed or what he chose;
    the writing sitting right beside it was fully readable, and the quiz
    should be too.

    Reads the latest graded attempt (list_quiz_attempts is newest-first)
    and its stored per-question `detail`. Returns True when it rendered
    something, so the caller can count "there's a quiz to look at" among
    the reasons this card has anything to show. Renders nothing -- and
    returns False -- for a lesson with no quiz, or a quiz he hasn't taken
    yet.
    """
    attempts = db.list_quiz_attempts(student["id"], lesson_id=lesson["id"])
    if not attempts:
        return False
    latest = attempts[0]
    detail = latest.get("detail") or []
    if not detail:
        return False

    correct, total = latest["correct"], latest["total"]
    pct = round(100 * correct / total) if total else 0
    verdict = "🎯 passed" if latest.get("passed") else "below the pass threshold"
    suffix = f" · latest of {len(attempts)} attempts" if len(attempts) > 1 else ""
    st.markdown(f"**📝 Quiz — {correct}/{total} ({pct}%)** — {verdict}{suffix}")

    for index, item in enumerate(detail):
        pick = item.get("pick")
        right = pick == item.get("correct_index")
        marker = "✅" if right else "❌"
        # The ones he missed open on their own -- those are what a parent is
        # scanning for; the ones he got right stay a click away rather than
        # padding out the card.
        with st.expander(f"{marker} {index + 1}. {md(item['question'])}", expanded=not right):
            for choice_index, choice in enumerate(item.get("choices") or []):
                tag = ""
                if choice_index == item.get("correct_index"):
                    tag = " — correct answer"
                elif choice_index == pick:
                    tag = " — his answer"
                st.markdown(f"- {md(choice)}{tag}")
            if pick is None:
                st.caption("He left this one blank.")
            if item.get("explanation"):
                st.caption(md(item["explanation"]))
    return True


def _render_writing_review_controls(
    db: Database,
    student: dict[str, Any],
    lesson: dict[str, Any],
    index: int,
    activity: dict[str, Any],
    *,
    key_prefix: str,
    metadata: dict[str, Any],
    review_map: dict[str, Any],
) -> None:
    """One writing activity's evidence and its approve/send-back call, meant
    to sit directly under that activity in the parent's inline review: his
    response, earlier drafts, the automated read, and -- once he's turned the
    whole lesson in -- the buttons to approve it or bounce it back to him."""
    responses = metadata.get("writing_responses") or {}
    text = responses.get(str(index), "")
    review = review_map.get(str(index), {})
    status = review.get("status", config.WRITING_DRAFT)

    # His actual submission, made to stand out from the assignment text
    # above it -- a bold label and its own boxed panel, not a subtle italic
    # line that reads as more instructions. This is the thing a parent
    # opened the card to see.
    st.markdown("**✍️ What he turned in:**")
    if text:
        with st.container(border=True):
            st.write(md(text))
    else:
        st.caption("He hasn't written a response yet.")

    # The parts he was asked to cover, and which he checked off -- so you can
    # confirm a ticked box was actually done, not just clicked past. He can't
    # turn a writing activity in until every box is ticked, so all showing ✅
    # is his self-report, the ❌ (if any, on an already-submitted lesson from
    # before this existed) a genuine gap.
    checklist_items = activity.get("checklist") or []
    if checklist_items:
        stored_checks = (metadata.get("checklist_checked") or {}).get(str(index)) or []
        st.caption("Parts he had to cover:")
        for item_index, item in enumerate(checklist_items):
            ticked = item_index < len(stored_checks) and stored_checks[item_index]
            st.markdown(f"{'✅' if ticked else '⬜'} {md(item)}")

    versions = db.list_writing_response_versions(lesson["id"], index)
    if len(versions) > 1:
        with st.expander(f"Earlier drafts ({len(versions) - 1})"):
            for version in versions[:-1]:
                st.caption(version["saved_at"])
                st.write(md(version["text"]))
                st.divider()

    ai_review = _stored_ai_review(metadata, index)
    if ai_review is not None:
        # The same stored result he already saw before submitting -- his
        # view showed strengths and next moves; yours adds what the
        # assignment asked for that's still missing, and anything
        # factually wrong. No second model call: this is read back, not
        # regenerated.
        with st.expander("🔍 What the automated read noticed"):
            # Three tiers, loudest first. This card is read to decide
            # whether to send the assignment back, so the two reasons to
            # do that shouldn't sit quieter than the praise -- which is
            # what a plain bullet under a ⚠️ alert was doing. `missing`
            # carries the same 🔁 his own view uses for the same items,
            # so the mark means one thing on both sides of the app.
            for concern in ai_review.get("concerns") or []:
                st.error(f"⚠️ **Check this** — {md(concern)}")
            for item in ai_review.get("missing") or []:
                st.warning(f"🔁 **Needs rework** — {md(item)}")
            for strength in ai_review.get("strengths") or []:
                st.markdown(f"- ✅ **Working:** {md(strength)}")
            if not any(ai_review.get(k) for k in ("concerns", "missing", "strengths")):
                st.caption("Nothing flagged.")
            st.caption(
                "Advisory only, and it can be wrong -- it never approves "
                "anything on its own."
            )

    if status == config.WRITING_APPROVED:
        approval_note = review.get("approval_feedback")
        if approval_note:
            st.success(f"✅ Approved with a note for him: {md(approval_note)}")
            if review.get("approval_read_at"):
                st.caption(f"👀 He read it — {review['approval_read_at']}")
            else:
                st.caption("⏳ Waiting on him to read it and tick that he saw it.")
        else:
            st.success("✅ Approved.")
    elif status == config.WRITING_NEEDS_REVISION:
        history = _feedback_history(
            review, history_key="feedback_history", single_key="feedback"
        )
        if len(history) <= 1:
            st.warning(
                "↩️ Sent back for revision" + (f": {md(history[0])}" if history else ".")
            )
        else:
            st.warning("↩️ Sent back for revision — every note you've given so far:")
            for note in history:
                st.markdown(f"- {md(note)}")
    elif status == config.WRITING_SUBMITTED and lesson["status"] == "submitted":
        # If this is a *re*-review -- you sent it back once, he reworked it and
        # turned it in again -- the notes you gave last time are the whole
        # point of comparison, so surface them right above the buttons rather
        # than making you remember what you'd asked for. Empty on a first pass.
        prior_notes = _feedback_history(
            review, history_key="feedback_history", single_key="feedback"
        )
        if prior_notes:
            st.warning(
                "↩️ You sent this back "
                + (
                    "before — what you asked for:"
                    if len(prior_notes) == 1
                    else "before — every note so far:"
                )
            )
            for note in prior_notes:
                st.markdown(f"- {md(note)}")
            st.caption("His reworked response is what's shown above.")
        st.info("⏳ He's submitted this — awaiting your review.")
        review_key = f"{key_prefix}_writing_review_{lesson['id']}_{index}"
        with st.form(review_key):
            feedback = st.text_area(
                "Feedback for him",
                key=f"{review_key}_feedback",
                help=(
                    "Send back → he has to revise before it counts. "
                    "Approve → it counts as done, but he still has to read this "
                    "note and tick that he saw it."
                ),
            )
            approve_col, bounce_col = st.columns(2)
            approve = approve_col.form_submit_button("✅ Approve", type="primary")
            bounce = bounce_col.form_submit_button("↩️ Send back for revision")
        if approve:
            db.set_writing_review(
                lesson["id"], index, config.WRITING_APPROVED, approval_note=feedback
            )
            st.rerun()
        elif bounce:
            db.set_writing_review(lesson["id"], index, config.WRITING_NEEDS_REVISION, feedback)
            # Bouncing any one piece sends the whole lesson back to him --
            # he needs to see it and act, not just this activity. No
            # lesson-level feedback text: this activity already carries
            # its own, right where he'll read it.
            db.send_lesson_back(lesson["id"])
            st.rerun()
    elif status == config.WRITING_SUBMITTED:
        # Submitted at the activity level but the lesson as a whole
        # hasn't been turned in yet -- possible on data from before this
        # gate existed. Nothing to act on until he turns in the rest.
        st.caption("⏳ Submitted — waiting on him to turn in the whole lesson.")
    else:
        st.caption("Still drafting — he hasn't submitted this one yet.")

    # Add or edit the self-check parts on a lesson he hasn't turned in yet --
    # the way to bring the checklist gate to lessons generated before it
    # existed, without regenerating the day. "Suggest" reads the parts out of
    # the assignment's own instructions; you confirm or edit before saving,
    # so nothing goes live on his screen that you didn't approve.
    if lesson["status"] in ("planned", "needs_revision"):
        existing_items = activity.get("checklist") or []
        summary = f" ({len(existing_items)})" if existing_items else " — none yet"
        with st.expander(f"🧩 Self-check parts he must tick{summary}"):
            edit_key = f"{key_prefix}_checklist_edit_{index}"
            if edit_key not in st.session_state:
                st.session_state[edit_key] = "\n".join(existing_items)
            st.text_area(
                "One part per line — he'll have to tick each before he can turn this in.",
                key=edit_key,
                height=110,
            )
            save_col, suggest_col = st.columns(2)
            if save_col.button("Save parts", key=f"{key_prefix}_checklist_save_{index}"):
                items = [
                    line.strip()
                    for line in st.session_state[edit_key].splitlines()
                    if line.strip()
                ]
                db.set_activity_checklist_items(lesson["id"], index, items)
                st.success("Saved.")
                st.rerun()
            if suggest_col.button(
                "✨ Suggest from the instructions",
                key=f"{key_prefix}_checklist_suggest_{index}",
            ):
                with st.spinner("Reading the assignment…"):
                    try:
                        suggested = checklist_suggest.suggest_checklist(
                            activity.get("instructions", "")
                        )
                    except LessonGenerationError as exc:
                        st.error(f"Couldn't suggest right now: {exc}")
                        suggested = None
                if suggested:
                    st.session_state[edit_key] = "\n".join(suggested)
                    st.rerun()
                elif suggested is not None:
                    st.caption(
                        "This assignment reads as a single ask — no separate parts to "
                        "check off. Add your own above if you want to."
                    )


def _render_final_grade_decision(
    db: Database,
    student: dict[str, Any],
    lesson: dict[str, Any],
    *,
    key_prefix: str,
    metadata: dict[str, Any],
    assessment: dict[str, Any],
    skill_id: Any,
    writing_all_approved: bool,
) -> None:
    """The one lesson-wide call, at the very bottom of the review: mastery
    for a Math skill (a `skill_id`), the five-band verdict for every other
    graded subject. Only opens up once he's turned the lesson in AND every
    writing piece in it is individually approved -- never two "send it back"
    buttons live for the same lesson at once. Approving folds in logging the
    hours in the same click; sending back reopens it to him."""
    if skill_id:
        current = db.mastery_map(student["id"]).get(skill_id, {})
        quiz_result = metadata.get("quiz_result") or {}
        latest_score = (
            round(100 * quiz_result["correct"] / quiz_result["total"])
            if quiz_result.get("total")
            else current.get("score")
        )
        mastery_bar = db.get_int_setting("math_mastery_percent")
        # "Mastered" now has to be earned by the quiz, not just approved: the
        # skill only records as mastered when his latest quiz clears the mastery
        # bar, or when you deliberately override. This is what stops a stale
        # "mastered at 80%" from being minted by an Approve click on a lesson he
        # didn't actually ace -- reported directly.
        earned_mastery = latest_score is not None and latest_score >= mastery_bar
        if current.get("status") == "mastered":
            st.success(f"✅ Already approved — mastered at {current.get('score') or '?'}%.")
        elif current.get("status") == "in_progress" and str(
            current.get("notes", "")
        ).startswith("Dropped from mastered"):
            # A skill that was mastered but a later quiz knocked back down, so
            # the parent isn't misled by a stale "mastered" while he's clearly
            # struggling now. The note carries the score that dropped it.
            st.warning(f"⚠️ {md(current['notes'])} It's back to *in progress* — worth another look.")
        st.caption(
            f"Mastery needs a quiz at {mastery_bar}%+ — his latest was "
            f"{latest_score if latest_score is not None else '—'}%. Approving logs the "
            "hours and accepts his work; it records the skill as **mastered** only when "
            "the quiz clears that bar (or you tick the override below). A weak quiz on a "
            "skill he'd mastered drops it back on its own."
        )
        if lesson["status"] == "submitted" and writing_all_approved:
            with st.form(f"{key_prefix}_assess_{lesson['id']}"):
                notes = st.text_area("Notes (optional)", value=current.get("notes", ""))
                feedback = st.text_area(
                    "Feedback (shown to him if you send it back for more practice)"
                )
                override_master = False
                if not earned_mastery:
                    override_master = st.checkbox(
                        f"Mark this skill mastered anyway (his latest quiz was "
                        f"{latest_score if latest_score is not None else '—'}%, under the "
                        f"{mastery_bar}% bar)",
                        key=f"{key_prefix}_master_override_{lesson['id']}",
                    )
                minutes, where, credits = _hours_inputs(
                    lesson["payload"], f"{key_prefix}_hrs_{lesson['id']}"
                )
                approve_col, practice_col = st.columns(2)
                approve = approve_col.form_submit_button("✅ Approve & log hours", type="primary")
                keep_practicing = practice_col.form_submit_button(
                    "🔁 Not yet — send back for more practice"
                )
            if approve:
                mastered = earned_mastery or override_master
                db.set_mastery(
                    student["id"], skill_id,
                    "mastered" if mastered else "in_progress",
                    score=latest_score, notes=notes,
                )
                _log_hours_for_lesson(
                    db, student, lesson, minutes=minutes, location=where, credits=credits
                )
                st.success(
                    "Approved and logged — the next skill is unlocked."
                    if mastered
                    else "Approved and logged. The skill stays *in progress* until a "
                    "stronger quiz — the next skill won't unlock yet."
                )
                st.rerun()
            elif keep_practicing:
                db.set_mastery(
                    student["id"], skill_id, "in_progress", score=latest_score, notes=notes
                )
                db.send_lesson_back(lesson["id"], feedback)
                st.success("Sent back — he'll see this again to keep practicing.")
                st.rerun()
        elif lesson["status"] == "submitted":
            st.caption("Approve his response above before deciding on this skill.")
        elif lesson["status"] == "needs_revision":
            st.caption(
                "↩️ Sent back — waiting on him to keep practicing and turn it in again."
            )
        elif lesson["status"] == "planned":
            st.caption("Still working — nothing to review yet.")
    elif assessment:
        result = metadata.get("assessment_result") or {}
        current_verdict = result.get("verdict")
        if lesson["status"] == "submitted" and writing_all_approved:
            with st.form(f"{key_prefix}_assess_{lesson['id']}"):
                # Vertical, not horizontal: five bands with their percentages
                # spelled out don't fit on one row without truncating exactly
                # the part that says what you're assigning. And no
                # pre-selected default -- index=0 would sit on "Nailed it,"
                # so a parent who hit Save without reading would hand out a
                # 100%.
                verdict = st.radio(
                    "How'd it go?",
                    config.ASSESSMENT_VERDICTS,
                    index=config.ASSESSMENT_VERDICTS.index(current_verdict)
                    if current_verdict in config.ASSESSMENT_VERDICTS
                    else None,
                    format_func=lambda v: config.ASSESSMENT_VERDICT_LABELS[v],
                )
                st.caption(
                    "This band is part of his grade for the subject — the "
                    "percentage on each one is what it's worth."
                )
                notes = st.text_area("Notes (optional)", value=result.get("notes", ""))
                feedback = st.text_area("Feedback (shown to him if you send it back)")
                minutes, where, credits = _hours_inputs(
                    lesson["payload"], f"{key_prefix}_hrs_{lesson['id']}"
                )
                approve_col, bounce_col = st.columns(2)
                approve = approve_col.form_submit_button("✅ Approve & log hours", type="primary")
                bounce = bounce_col.form_submit_button("↩️ Send back for revision")
            if approve:
                if verdict is None:
                    st.warning("Pick a band first.")
                else:
                    db.record_assessment(lesson["id"], verdict, notes)
                    _log_hours_for_lesson(
                        db, student, lesson, minutes=minutes, location=where, credits=credits
                    )
                    st.success("Approved and logged.")
                    st.rerun()
            elif bounce:
                db.send_lesson_back(lesson["id"], feedback)
                st.success("Sent back for revision.")
                st.rerun()
        elif lesson["status"] == "submitted":
            st.caption("Approve his response above before grading the whole lesson.")
        elif lesson["status"] == "needs_revision":
            st.caption("↩️ Sent back — waiting on him to revise and turn it in again.")
        elif lesson["status"] == "planned":
            st.caption("Still working — nothing to review yet.")
        if result:
            st.caption(
                f"Last recorded: {config.ASSESSMENT_VERDICT_LABELS.get(result.get('verdict'), '')} "
                f"on {result.get('assessed_on', '')}"
            )


def render_lesson_review(
    db: Database, student: dict[str, Any], lesson: dict[str, Any], key_prefix: str
) -> None:
    """Grade in place. The whole lesson as he saw it, and under each activity
    the very submission it produced -- his written response with its own
    approve/send-back buttons, the reading check -- and after the activities
    the quiz with his answers against the key. A parent reads top to bottom
    and never scrolls back up to a separate panel of controls to act on what
    they just read.

    Replaces the old split of a read-only lesson preview plus a detached
    assessment card. The lesson-wide decision (mastery, or the five-band
    verdict, folding in the hours) still lands exactly once, at the very end.

    The content is the parent view -- his responses shown, but the answer
    key and parent notes still held back exactly as they are on his own
    screen -- so it stays faithful to the lesson he actually worked from.
    """
    payload = lesson["payload"]
    metadata = lesson.get("metadata") or {}
    assessment = payload.get("assessment") or {}
    skill_id = metadata.get("skill_id")
    activities = payload.get("activities") or []
    review_map = metadata.get("writing_review") or {}
    reading_checks = metadata.get("reading_checks") or {}

    # If you've sent this lesson back before and he's turned it in again, the
    # notes you gave are the frame for this whole re-read -- put them at the
    # very top so you're grading against what you asked for, not from memory.
    lesson_notes = _feedback_history(
        metadata, history_key="lesson_feedback_history", single_key="lesson_feedback"
    )
    if lesson_notes:
        with st.container(border=True):
            if len(lesson_notes) == 1:
                st.markdown("↩️ **You sent this back — what you asked him for:**")
            else:
                st.markdown("↩️ **You've sent this back before — every note so far:**")
            for note in lesson_notes:
                st.markdown(f"- {md(note)}")

    if payload.get("overview"):
        st.write(md(payload["overview"]))
    objectives = payload.get("learning_objectives") or []
    materials = payload.get("materials") or []
    if objectives or materials:
        columns = st.columns(2)
        with columns[0]:
            if objectives:
                st.markdown("**Learning objectives**")
                for objective in objectives:
                    st.markdown(f"- {md(objective)}")
        with columns[1]:
            if materials:
                st.markdown("**Materials**")
                for item in materials:
                    st.markdown(f"- {md(item)}")

    # The teaching half he worked from -- shown here too so a parent grades with
    # the same Learn and worked example in front of them that he had.
    _render_learn_section(lesson, parent=True)

    for index, activity in enumerate(activities):
        with st.container(border=True):
            st.markdown(
                f"**{index + 1}. {md(activity.get('title', 'Activity'))}**  \n"
                f"{_comic_phase_pill_html(activity)} · "
                f"{activity.get('minutes', 0)} min",
                unsafe_allow_html=True,
            )
            # The activity exactly as he saw it (parent side: answer key and
            # parent notes still held back), then his own work and the
            # grading controls right underneath -- never up in a separate
            # block he has to scroll away to.
            _render_activity_body(
                activity,
                index,
                parent=True,
                db=db,
                lesson_id=lesson["id"],
                metadata=metadata,
                student=student,
                review_owns_response=True,
            )
            stored = reading_checks.get(str(index))
            if stored:
                correct, total = stored.get("correct", 0), stored.get("total", 0)
                label = f"📖 Reading check: {correct}/{total}"
                if total and correct == total:
                    st.caption(f"{label} ✅")
                else:
                    st.warning(f"{label} — worth asking whether he actually did the reading.")
            if _needs_written_response(activity):
                _render_writing_review_controls(
                    db, student, lesson, index, activity,
                    key_prefix=key_prefix, metadata=metadata, review_map=review_map,
                )

    if payload.get("quiz"):
        with st.container(border=True):
            if not _render_quiz_review(db, student, lesson):
                st.caption("📝 Quiz — he hasn't taken it yet.")

    # The parent's answer sheet / grading guide, sitting right below all his
    # work where the grading actually happens -- not a tiny caption up top he
    # has to scroll past. Reported: "wheres that answer sheet for me? that
    # should be right below his response for all activities." This is whatever
    # the lesson already carries in `assessment` (the paper he hands over, plus
    # what counts as mastered); the student never sees `assessment`, so this is
    # the one place these worked details surface.
    if (
        assessment.get("description")
        or assessment.get("answer_key")
        or assessment.get("mastery_criteria")
        or assessment.get("rubric")
    ):
        with st.container(border=True):
            st.markdown("**🔑 For grading — the hand-in & how to score it**")
            if assessment.get("kind"):
                st.caption(f"*{md(assessment['kind'])}*")
            if assessment.get("description"):
                st.markdown(md(assessment["description"]))
            # The leveled rubric -- what strong/getting-there/not-yet looks like.
            # Safe to have shown him too (it's his bar), so it reads next to the
            # verdict picker as the consistent words to grade against.
            if assessment.get("rubric"):
                st.markdown(
                    f'<div style="background:var(--c-panel); border-left:3px solid '
                    f'var(--c-warn); border-radius:var(--c-radius); padding:10px 14px; '
                    f'margin:8px 0;"><b>🎯 Grading rubric</b><br>'
                    f'{html.escape(assessment["rubric"]).replace(chr(10), "<br>")}'
                    f"</div>",
                    unsafe_allow_html=True,
                )
            # The worked answer key -- newly generated lessons carry it (older
            # ones won't, so it's shown only when present). Set apart in its own
            # tinted block so it reads as "the answers," not more prompt.
            if assessment.get("answer_key"):
                st.markdown(
                    f'<div style="background:var(--c-panel); border-left:3px solid '
                    f'var(--c-good); border-radius:var(--c-radius); padding:10px 14px; '
                    f'margin:8px 0;"><b>✅ Answer key</b><br>'
                    f'{html.escape(assessment["answer_key"]).replace(chr(10), "<br>")}'
                    f"</div>",
                    unsafe_allow_html=True,
                )
            if assessment.get("mastery_criteria"):
                st.markdown(
                    f"**Counts as mastered when:** {md(assessment['mastery_criteria'])}"
                )

    # The lesson-wide decision waits for every writing piece to be approved
    # first, so grading the whole lesson never collides with a per-activity
    # approve/bounce still pending above.
    writing_activities = [
        (index, activity)
        for index, activity in enumerate(activities)
        if _needs_written_response(activity)
    ]
    writing_all_approved = all(
        (review_map.get(str(index)) or {}).get("status") == config.WRITING_APPROVED
        for index, _ in writing_activities
    )
    _render_final_grade_decision(
        db,
        student,
        lesson,
        key_prefix=key_prefix,
        metadata=metadata,
        assessment=assessment,
        skill_id=skill_id,
        writing_all_approved=writing_all_approved,
    )


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
    whichever lesson happens to have the highest id. Those used to
    disagree: batch-planning a whole week in one sitting means the last
    day generated (often Friday) has the most recent `created_at`, which
    is a different thing entirely from "the one due today." A day badge
    above the lesson (only shown when it carries a `planned_for` tag at
    all -- an ordinary on-demand generation has no day attached) makes
    that same fact visible here, not just inferred from being on the page.
    """
    lessons = db.list_lessons(student["id"], agent=agent_key, limit=10)
    icon = SUBJECT_ICONS.get(agent_key, "📘")

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
            if history:
                st.error(
                    f"↩️ **Your parent sent this back.** Here's what to fix:\n\n"
                    f"> {md(history[-1])}"
                )
                if len(history) > 1:
                    with st.expander("Earlier notes on this lesson"):
                        for note in history[:-1]:
                            st.markdown(f"- {md(note)}")
            else:
                st.error(
                    "↩️ **Your parent sent this back.** Check your work below "
                    "and turn it in again."
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
        )
        render_quiz(
            db,
            student,
            pending["id"],
            pending.get("metadata") or {},
            pending["payload"].get("quiz") or [],
            agent=agent_key,
        )
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
        planned_for = (current.get("metadata") or {}).get("planned_for")
        if planned_for:
            weekday = date.fromisoformat(planned_for).strftime("%A")
            if planned_for < date.today().isoformat():
                st.caption(f"⚠️ Was due {weekday}")
            else:
                st.caption(f"📅 {weekday} — today's lesson")
        render_lesson(
            current["payload"],
            for_parent=False,
            db=db,
            lesson_id=current["id"],
            metadata=current.get("metadata") or {},
            comic_layout=comic_layout,
            comic_frame_title=f"{icon} {subject_label} — Current Lesson",
            student=student,
        )
        render_quiz(
            db,
            student,
            current["id"],
            current.get("metadata") or {},
            current["payload"].get("quiz") or [],
            agent=agent_key,
        )
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


# --- subject icons, Friday's plan, the daily checklist, morning routine --------

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

# Friday is deliberately never a new-content day (see compass/weekly.py), so
# its cell on the Week grid has always shown a fixed Big Project + Travel
# Journal pairing. friday_plan_items lets a parent replace that, one Friday
# at a time, with any mix of these standardized options -- or a free-text
# 'custom' one -- rather than being stuck with the one fixed pairing. Each
# entry is (icon, default label, page to link, that page's link text);
# 'custom' has no default label (the parent's own text is the whole point)
# and nothing to link to.
FRIDAY_PLAN_KINDS: dict[str, tuple[str, str, str | None, str | None]] = {
    "big_project": (
        "🎬", "Big Project — work on the next step",
        "pages/7_Big_Projects.py", "Big Projects",
    ),
    "travel_new": (
        "🧭", "Travel Journal — write about a trip",
        "pages/9_Landons_Travels.py", "Travels",
    ),
    "travel_catchup": (
        "🧭", "Travel Journal — catch up on older trips",
        "pages/9_Landons_Travels.py", "Travels",
    ),
    "life_skills": (
        "🛠️", "Life Skills — work on a skill",
        "pages/6_Life_Skills.py", "Life Skills",
    ),
    "choice_topics": (
        "⭐", "Choice Topics — work on a topic",
        "pages/6_Life_Skills.py", "Life Skills",
    ),
    "custom": ("📝", "", None, None),
}


def big_project_status_text(db: Database, student_id: int) -> str:
    """'<title> — <next step>', or a nudge to pick one at all -- the same
    smart label the Week grid's Friday cell has always shown for Big
    Projects, factored out so a parent-added friday_plan_items row can reuse
    it as that item's default text instead of a generic string."""
    active = db.active_big_project(student_id)
    if active is None:
        return "Big Projects — pick one to work on this year"
    steps = db.list_project_steps(active["id"])
    next_step = next((s for s in steps if s["active"] and not s["completed_on"]), None)
    if next_step:
        return f"{md(active['title'])} — {md(next_step['title'])}"
    # Steps exist and aren't all done, but none of them are in To Do yet --
    # a real, different state from "all done", not the same thing.
    if any(not s["completed_on"] for s in steps):
        return f"{md(active['title'])} — pull a step into To Do"
    return f"{md(active['title'])} — all done! 🎉"


def render_friday_plan(db: Database, student: dict[str, Any], plan_date: str) -> None:
    """Friday's cell on the Week grid, and the This Week page's own
    "review this week" display, both render whatever a parent has set for
    that specific Friday through this one function. No rows yet for that
    date falls back to the original fixed Big Project + Travel Journal
    pairing, so a week nobody's customized reads exactly as it always has."""
    items = db.list_friday_plan_items(student["id"], plan_date)
    if not items:
        st.markdown(f"🎬 {big_project_status_text(db, student['id'])}")
        st.page_link("pages/7_Big_Projects.py", label="Open", icon="➡️")
        st.markdown("🧭 **Travel Journal** — write about a trip")
        st.page_link("pages/9_Landons_Travels.py", label="Open", icon="➡️")
        return

    for item in items:
        icon, default_label, page, page_label = FRIDAY_PLAN_KINDS[item["kind"]]
        if item["kind"] == "big_project" and not item["label"]:
            text = big_project_status_text(db, student["id"])
        else:
            text = md(item["label"]) if item["label"] else default_label
        st.markdown(f"{icon} {text}")
        if page:
            st.page_link(page, label="Open", icon="➡️")


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
            st.caption(f"Re-grade the hand-in for **{md(item.title)}**")
            verdicts = list(config.ASSESSMENT_VERDICTS)
            current = item.verdict if item.verdict in verdicts else verdicts[0]
            new_verdict = st.selectbox(
                "Grade",
                verdicts,
                index=verdicts.index(current),
                format_func=lambda v: config.ASSESSMENT_VERDICT_LABELS[v],
                key=f"grade_item_verdict_{subject}_{item.lesson_id}",
            )
            if st.button(
                "Save grade",
                key=f"grade_item_save_{subject}_{item.lesson_id}",
                type="primary",
            ):
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


_STREAK_MILESTONES = (3, 5, 10, 20, 30, 50)

# Same fixed printed-poster palette as the Week grid and first-day cover --
# a comic callout on purpose, picked from three celebration directions
# sampled before building (balloons, snow, this) as the one that matched
# the app's own printed-comic look everywhere else.
_STREAK_BURST_INK = theming.PRINTED_COMIC_INK
_STREAK_BURST_PAPER = theming.PRINTED_COMIC_PAPER
_STREAK_BURST_POP = theming.PRINTED_COMIC_WEEKDAY_COLORS[1]
_STREAK_BURST_CSS = f"""
<style>
div[class*="st-key-streak_milestone_burst"] {{
  background: {_STREAK_BURST_PAPER};
  border: 3px solid {_STREAK_BURST_INK};
  border-radius: 6px;
  padding: 10px 16px 8px;
  position: relative;
  overflow: hidden;
  box-shadow: 3px 3px 0 0 {_STREAK_BURST_INK};
  margin: 2px 4px 8px 2px;
}}
div[class*="st-key-streak_milestone_burst"]::before {{
  content: "";
  position: absolute;
  inset: 0;
  border-radius: 6px;
  pointer-events: none;
  opacity: .14;
  background-image: radial-gradient(circle, {_STREAK_BURST_INK} 1.6px, transparent 1.8px);
  background-size: 9px 9px;
}}
div[class*="st-key-streak_milestone_burst"] > div {{
  position: relative;  /* keep text above the dot texture */
}}
</style>
"""


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


def render_streak(db: Database, student: dict[str, Any]) -> None:
    """His run of school days in a row. Student-facing, on Home.

    The one thing on his page that rewards showing up rather than scoring
    well -- deliberately, since everything else Compass checks is about the
    quality of one piece of work. Weekends don't break it (see
    compass.weekly), so it survives Monday morning. Neither does a
    deliberate day off -- a holiday unchecked in This Week's school-days
    picker leaves no lesson planned for that date at all, and
    planned_days/planned_weeks together are what tell that apart from a day
    he actually had work waiting and skipped (see
    weekly._is_deliberate_day_off for why both are needed).

    Ordinary days stay quiet -- just the count, no superlative. The old copy
    added "-- your best yet!" whenever `streak >= best`, but a streak IS the
    record every single day once it's ever been the longest he's had, so
    that fired on nearly every day of an ongoing streak and read as
    meaningless. Milestones (_STREAK_MILESTONES) get an actual comic-style
    callout instead, and only on the day he actually lands on one --
    `today_done` gates it so reopening the app later the same week, still
    sitting on a milestone number from a day he already saw it, doesn't
    show the celebration again.
    """
    active = db.active_days(student["id"])
    planned_days = db.planned_days(student["id"])
    planned_weeks = db.planned_weeks(student["id"])
    streak = weekly.current_streak(
        active, planned_days=planned_days, planned_weeks=planned_weeks
    )

    if not streak:
        if active:
            st.caption("🔥 Finish something today to start a new streak.")
    else:
        best = weekly.best_streak(
            active, planned_days=planned_days, planned_weeks=planned_weeks
        )
        today_done = date.today().isoformat() in active

        if today_done and streak in _STREAK_MILESTONES:
            st.markdown(_STREAK_BURST_CSS, unsafe_allow_html=True)
            with st.container(key="streak_milestone_burst"):
                st.markdown(
                    f'<div style="font-weight:900; font-size:11px; letter-spacing:.06em; '
                    f'color:{_STREAK_BURST_POP};">MILESTONE!</div>'
                    f'<div style="font-weight:900; font-size:22px; line-height:1.1; '
                    f'color:{_STREAK_BURST_INK};">🎉 {streak} DAYS IN A ROW</div>'
                    + (
                        f'<div style="font-size:12px; font-weight:700; '
                        f'color:{_STREAK_BURST_INK};">A new personal best.</div>'
                        if streak >= best
                        else ""
                    ),
                    unsafe_allow_html=True,
                )
        else:
            plural = "s" if streak != 1 else ""
            line = f"🔥 **{streak} school day{plural} in a row**"
            if best > streak:
                line += f" · best: {best}"
            if not today_done:
                line += "  \nFinish something today to keep it alive."
            st.success(line)

    # The numbers behind the Level bar next to this card -- "how much have I
    # actually done." Reported directly: show "lessons completed, quizzes
    # passed etc, heaviest by volume subject" right here. Always rendered (even
    # at zero) so the card keeps a stable shape, and built from xp.learner_stats
    # off the same completion signal the Level bar uses, so the two never
    # disagree.
    _render_learner_kpis(db, student)


def _render_learner_kpis(db: Database, student: dict[str, Any]) -> None:
    """The compact KPI strip under his streak -- finished lessons, passed
    quizzes, and the subject he's put the most work into. Custom HTML rather
    than st.metric so three-plus tiles stay short instead of stacking into a
    tall block that unbalances the header row."""
    stats = xp_module.learner_stats(db, student["id"])

    tiles = [
        ("📚", stats.lessons_done, "lessons done"),
        ("🎯", stats.quizzes_passed, "quizzes passed"),
        ("🛠️", stats.skills_done, "life skills"),
        ("🧭", stats.trips_written, "trips written"),
    ]
    cells = "".join(
        f'<div style="flex:1 1 64px; min-width:64px; text-align:center; '
        f'padding:6px 4px; background:var(--c-panel); border-radius:8px;">'
        f'<div style="font-size:20px; font-weight:800; line-height:1.1;">{icon} {value}</div>'
        f'<div style="font-size:11px; color:var(--c-dim);">{label}</div>'
        f"</div>"
        for icon, value, label in tiles
    )
    st.markdown(
        f'<div style="display:flex; gap:6px; flex-wrap:wrap; margin-top:8px;">{cells}</div>',
        unsafe_allow_html=True,
    )
    if stats.heaviest_subject:
        st.caption(
            f"💪 Most work so far: **{md(stats.heaviest_subject.title())}** "
            f"({stats.heaviest_subject_count} lesson"
            f"{'s' if stats.heaviest_subject_count != 1 else ''})"
        )


def render_daily_due(db: Database, student: dict[str, Any], today: str) -> None:
    """The day's small recurring work -- words to review, where his book is,
    and any life skills due -- folded into the header card beside the streak
    and KPIs instead of a separate three-tile row lower down. Reported: "fold
    in the daily work for reading words, life skills KPI and if any are due
    that day, and reading progression of book up in this one container." Kept
    laid out as one lined-up row of three -- Words, Reading, Life Skills side by
    side rather than stacked -- so the whole "what do I owe today" reads at a
    glance in the space next to the Level card."""
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

    st.divider()
    st.markdown("**📌 Due today**")
    words_col, reading_col, skills_col = st.columns(3)

    with words_col:
        st.markdown("**🔤 Words**")
        if due_words:
            st.page_link(
                "pages/3_English.py", label=f"{len(due_words)} to review", icon="➡️"
            )
        else:
            st.caption("Caught up ✅")

    with reading_col:
        st.markdown("**📖 Reading**")
        if book:
            st.caption(md(book["title"]))
            if book.get("total_pages"):
                st.progress(
                    min((book["current_page"] or 0) / book["total_pages"], 1.0),
                    text=f"p{book['current_page']}/{book['total_pages']}",
                )
        else:
            st.caption("No book yet")

    with skills_col:
        st.markdown(f"**🛠️ Life Skills ({len(due_skills)})**")
        if due_skills:
            for skill in due_skills:
                st.page_link(
                    "pages/6_Life_Skills.py", label=md(skill["title"]), icon="➡️"
                )
        else:
            st.caption("Nothing due ✅")
        # +later, and the Student's Choice / Coding counts (both live on the
        # same Life Skills page) ride as one compact caption under the column.
        extra: list[str] = []
        if later_skills:
            extra.append(f"+{later_skills} later")
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


# --- story movement: the one shared backlog/schedule control --------------------
#
# One consistent control for moving any "story" -- a lesson, a Big Project
# step, a Choice Topic, a Life Skill, a Coding Camp module -- around the
# board: a date picker to assign or move it to a day, or send it back to the
# Backlog. Lives on every card that already carries an `active` flag and a
# `scheduled_for` date, in place of that surface's own scattered buttons.


def render_story_move_control(
    *,
    key: str,
    active: bool,
    scheduled_for: str | None,
    set_active: Callable[[bool], None],
    schedule: Callable[[str | None], None],
    validate_schedule: Callable[[str], str | None] | None = None,
    show_backlog_toggle: bool = True,
) -> None:
    """`key` must be unique per story (the caller's own id namespace, e.g.
    `f"step_{step['id']}"`). `set_active`/`schedule` are the two writes this
    control ever makes -- callers pass their own db call, e.g.
    `lambda a: db.set_project_step_active(step["id"], a)`.

    `validate_schedule`, if given, is called with the picked date before
    `schedule` -- return an error string to block the move (shown in place,
    the popover stays open) or `None` to let it through. Only lessons need
    this (two lessons from the same agent can't share a day); every other
    story type leaves it unset.

    `show_backlog_toggle` stays on its default (on) for every caller today.
    Backlogging and un-backlogging are each their own one-way button --
    "Send to backlog" only when `active`, "Take out of Backlog" only when
    not -- never a single checkbox meaning opposite things depending on
    which state it started in. That used to read as "uncheck this to
    bring it back," which for a lesson meant something genuinely
    destructive: unchecking it called `set_active(True)`, and a lesson's
    own implementation of that used to silently reschedule to *today*,
    overwriting whatever day a parent had just picked in the very same
    popover (reported directly -- "i moved two math lessons from backlog
    to their own dates... and they have disappeared"). Picking a new day
    in "Assign to a specific day" already takes a story out of the
    backlog on its own, for every story kind (each one's own `schedule`
    write does this) -- "Take out of Backlog" is only there for
    reactivating *without* also changing the day.

    Widget keys fold in the current `scheduled_for` value for the date
    picker (the same trick `render_life_skill_catalog_manager` uses for
    its own checkbox -- `schedule` can change what's "current" as a side
    effect of a different widget's write, and a fixed key would read a
    stale session_state value as a fresh pick on the next run and
    silently redo it) -- but not for the backlog buttons, since a
    `st.button`'s own return value never persists across a rerun the way
    a checkbox's does, so there's no stale state for a fixed key to leak.
    """
    # Icon-only when there's nothing to report yet -- this sits in a narrow
    # top-right corner on a card grid (three cards to a row), and a two-word
    # label wraps into an unreadable vertical sliver at that width. The
    # other two states already read fine at that width on their own.
    #
    # `active` is checked *before* `scheduled_for`: every story type here
    # keeps its old scheduled_for/planned_for value even after being sent to
    # backlog (none of the set_active/send_to_backlog implementations clear
    # it), so a backlogged story with a leftover date would otherwise still
    # show "📅 <that date>" here instead of "🗄️ Backlog" -- exactly the
    # trigger for it no longer reading as backlogged at a glance.
    if not active:
        label = "🗄️ Backlog"
    elif scheduled_for:
        label = f"📅 {scheduled_for}"
    else:
        label = "📅"
    with st.popover(label, use_container_width=False, help="Move to a day, or send to Backlog"):
        if not active:
            st.caption("🗄️ Currently in the Backlog.")

        assign = st.checkbox(
            "Assign to a specific day",
            value=bool(scheduled_for),
            key=f"move_{key}_assign_{scheduled_for}",
        )
        if assign:
            picked = st.date_input(
                "Day",
                value=date.fromisoformat(scheduled_for) if scheduled_for else date.today(),
                key=f"move_{key}_date_{scheduled_for}",
            )
            if picked.isoformat() != scheduled_for:
                problem = validate_schedule(picked.isoformat()) if validate_schedule else None
                if problem:
                    st.error(problem)
                else:
                    schedule(picked.isoformat())
                    st.rerun()
        elif scheduled_for:
            schedule(None)
            st.rerun()

        if show_backlog_toggle:
            st.divider()
            if active:
                if st.button("🗄️ Send to backlog", key=f"move_{key}_send_to_backlog"):
                    set_active(False)
                    st.rerun()
            else:
                if st.button("↩️ Take out of Backlog", key=f"move_{key}_take_out_of_backlog"):
                    set_active(True)
                    st.rerun()


# Where a story's own full content already renders elsewhere in the app --
# the Math/Science/English/History pages are planning tools with no
# per-lesson content view, so a lesson's real "deeper review" destination is
# Activity Log's own review queue, not its subject page. (page, link label,
# the tab that content lives under.)
#
# Life Skills' and Big Projects' own Checklist tab is each page's first tab,
# so a plain st.page_link there already lands exactly where it says --
# Streamlit opens a page on its first tab with no way to request another
# one. Activity Log's own "To review" tab is its *third* tab (behind "The
# record" and "Log something manually"), so the exact same page_link there
# always landed on the wrong screen instead -- confirmed live: "the
# navigation for next week's board, go to full lesson, doesn't actually
# work." A lesson's own deep link is handled separately below instead of
# through this table, as a same-page dialog that needs no tab at all.
_BOARD_DEEP_LINK: dict[str, tuple[str, str, str]] = {
    "life_skill": ("pages/6_Life_Skills.py", "Open it", "Checklist"),
    "coding_module": ("pages/6_Life_Skills.py", "Open it", "Coding Camp"),
    "choice_topic": ("pages/6_Life_Skills.py", "Open it", "Life Skills"),
    "project_step": ("pages/7_Big_Projects.py", "Open it", "Checklist"),
    "travel_entry": ("pages/9_Landons_Travels.py", "Open it", "Travel journal"),
}


def _render_board_deep_link(
    kind: str, item: dict[str, Any] | None = None, *, db: Database | None = None
) -> None:
    if kind == "lesson":
        # A page_link can only ever open a page on its *first* tab, and
        # Activity Log's lesson-review tab isn't its first -- no target
        # this function could name would ever actually land there. A
        # same-page st.dialog sidesteps the whole problem: no navigation,
        # no tab to miss, works identically for a lesson on this week's
        # board or next week's.
        assert item is not None

        @st.dialog(f"📘 {item['title']}", width="large")
        def _show_full_lesson() -> None:
            # for_parent is left unset so render_lesson falls back to
            # is_parent() -- on Landon's own board the assessment and answer
            # key stay hidden, exactly as they do in his normal lesson view.
            # The PDF matches: parent=is_parent() gives the parent the whole
            # lesson (answer key included) and Landon a clean copy of just the
            # lesson itself (no answer key, no assessment, no parent notes), so
            # he can print his own board lesson without it carrying anything he
            # isn't meant to see.
            parent = is_parent()
            st.download_button(
                "🖨️ Print to PDF",
                data=partial(lesson_to_pdf, item["payload"], parent=parent),
                file_name=suggested_pdf_filename(item["payload"]),
                mime="application/pdf",
                key=f"board_pdf_{item['id']}",
            )
            # In student view, hand render_lesson the db/lesson_id/metadata (and
            # student) so a writing activity gets its real text box + Word-doc
            # upload right here, not just instructions to write on paper --
            # reported directly: a writing assignment on his board "should be a
            # text input box for that writing assignment and upload file." The
            # parent keeps the plain preview (db left off) so their view stays
            # the read-only answer-key copy, not an input surface.
            student = db.ensure_default_student() if (db is not None and not parent) else None
            render_lesson(
                item["payload"],
                db=None if parent else db,
                lesson_id=item["id"],
                metadata=item.get("metadata") or {},
                student=student,
                # For him, the comic layout renders each activity open (not
                # tucked in a collapsed expander), so the writing box + upload
                # sit right there to fill in rather than a click deep. The
                # parent keeps the plain preview.
                comic_layout=not parent,
                comic_frame_title=f"📘 {item['title']}",
            )

        if st.button("🔍 View full lesson", key=f"board_view_lesson_{item['id']}"):
            _show_full_lesson()
        return

    page, label, tab_hint = _BOARD_DEEP_LINK[kind]
    st.page_link(page, label=label, icon="🔍")
    st.caption(f'Under the "{tab_hint}" tab.')


def _render_board_detail(
    description: str | None = None,
    materials: str | None = None,
    *,
    pace: str | None = None,
    note: str | None = None,
) -> None:
    """The actual content of a non-lesson board card -- what the step/skill/
    trip *is* -- rendered inside the expander regardless of `interactive`.

    Without this, a life-skill or coding card showed only its category and a
    project-step or travel card showed nothing at all: on Landon's read-only
    board (interactive=False) every parent-only affordance is stripped, so
    those cards opened to an empty body. Reported directly against his board:
    "life skill and big project arent loading in the board correctly with the
    lesson or steps." The description is the lesson/step itself and belongs on
    both boards; the move control and deep link stay parent-only above this."""
    if description:
        st.write(md(description))
    if materials:
        st.caption(f"🧰 You'll need: {md(materials)}")
    if pace:
        st.caption(f"⏳ {pace}")
    if note:
        st.caption(note)


def _render_board_estimate_editor(db: Database, kind: str, item: dict[str, Any]) -> None:
    """A compact, parent-only "how long is this block" input on a board card --
    the sprint-points-style estimate a parent asked to be able to set ("just
    like point scorng in sprints"). Pre-filled with the card's current
    effective estimate (their own saved one, or the rough default); saving a
    new number stores an override, and setting it to 0 clears back to the
    default. The day header's total and the card's own tag re-sum from this on
    the next run, so it doubles as the balance dial for the whole day."""
    widget_key = f"board_est_{kind}_{item['id']}"

    def _save(kind=kind, item_id=item["id"], key=widget_key) -> None:
        raw = st.session_state.get(key)
        # 0 (or blank) clears the override so the card falls back to its
        # default; any other number is stored as the parent's own estimate.
        db.set_board_estimate(kind, item_id, int(raw) if raw else None)

    st.number_input(
        "⏱️ Estimate (min)",
        min_value=0,
        max_value=600,
        step=5,
        value=board_item_minutes(kind, item),
        key=widget_key,
        on_change=_save,
        help="Your rough time for this block — feeds the day's total. Set to 0 to use the default.",
    )


def _project_step_pace(item: dict[str, Any]) -> str | None:
    """A step's loose day range as a pace phrase -- "a few days to a week is
    the idea", never a deadline (same framing pages/7_Big_Projects.py's own
    step rows use). None when the step carries no range to show."""
    lo, hi = item.get("min_days"), item.get("max_days")
    if not lo and not hi:
        return None
    if lo == hi:
        return f"about {lo} day" if lo == 1 else f"about {lo} days"
    return f"about {lo}-{hi} days"


_TRAVEL_BOARD_PROMPTS = {
    "planned": "✍️ Time to write this trip up.",
    "needs_revision": "↩️ Sent back — give it another pass.",
    "submitted": "📤 Written up — waiting on a parent to read it.",
    "completed": "✅ Written up and in the journal.",
}


def board_item_minutes(kind: str, item: dict[str, Any]) -> int:
    """A minutes estimate for one board story, so the weekly board can show a
    per-card time and sum a per-day total -- the "is this day too heavy or too
    light" gauge a parent asked for.

    A parent's own saved estimate wins first (`item["estimate_minutes"]`, set by
    set_board_estimate -- the sprint-points-style override, any int including 0).
    With none saved it falls back to a sensible default: a lesson's real
    estimate (its own `estimated_minutes`, else the sum of its activities'
    minutes, else its credited minutes); a travel entry's writing +
    social-studies credit; and a round, tunable per-kind block
    (config.BOARD_BLOCK_MINUTES) for the rest, which carry no stored duration.
    All estimates for balancing a week, not a claim of exact time -- callers
    render them with a "≈"."""
    override = item.get("estimate_minutes")
    if override is not None:
        return int(override)
    if kind == "lesson":
        payload = item.get("payload") or {}
        est = payload.get("estimated_minutes")
        if est:
            return int(est)
        activity_total = sum(int(a.get("minutes") or 0) for a in payload.get("activities") or [])
        if activity_total:
            return activity_total
        credit_total = sum(int(c.get("minutes") or 0) for c in payload.get("subject_credits") or [])
        if credit_total:
            return credit_total
        return int(config.DEFAULT_SETTINGS["default_lesson_minutes"])
    if kind == "travel_entry":
        return (
            config.TRAVEL_JOURNAL_WRITING_MINUTES
            + config.TRAVEL_JOURNAL_SOCIAL_STUDIES_MINUTES
        )
    return config.BOARD_BLOCK_MINUTES.get(kind, 30)


def format_board_minutes(total: int) -> str:
    """Whole minutes as a compact "1h 30m" / "45m" / "2h" -- the board's own
    time labels. 0 or negative reads as "0m" rather than a blank."""
    if total <= 0:
        return "0m"
    hours, minutes = divmod(int(total), 60)
    if hours and minutes:
        return f"{hours}h {minutes}m"
    if hours:
        return f"{hours}h"
    return f"{minutes}m"


_BOARD_MOVE_NOTICE_KEY = "_board_move_notice"


def _board_schedule(
    schedule: Callable[[str | None], None], board_week_start: date
) -> Callable[[str | None], None]:
    """Wraps a board card's own `schedule` write with a note whenever the
    picked day lands outside the week currently on screen.

    `board_for_week` only ever returns the one week it was asked for, so a
    story moved to a date in a different week simply isn't in that result
    at all -- it doesn't render anywhere on the board a parent is looking
    at, with nothing to say where it went. It hasn't vanished; it's on
    whatever week that date belongs to now.

    This can't just call `st.toast` -- the move control that calls this
    always follows it with `st.rerun()`, and a toast fired in the same run
    that immediately reruns never reaches the browser at all (confirmed
    against this app's own Streamlit version: it silently drops). Instead
    the note is stashed in `session_state` and rendered once, as a real
    `st.info`, by `render_board_move_notice` at the top of the Board tab
    on the *next* run -- session_state is what actually survives a rerun.
    """

    def _wrapped(new_date: str | None) -> None:
        schedule(new_date)
        if not new_date:
            return
        moved_week = weekly.week_start(date.fromisoformat(new_date))
        if moved_week != board_week_start:
            when = "next week's" if moved_week > board_week_start else "an earlier week's"
            st.session_state[_BOARD_MOVE_NOTICE_KEY] = (
                f"Moved to {new_date} -- that's on {when} board, not this one. "
                "Nothing was lost; switch weeks above to see it."
            )

    return _wrapped


def render_board_move_notice() -> None:
    """Shows and clears whatever `_board_schedule` stashed on the previous
    run, if anything -- call once, near the top of the Board tab, before
    any card can queue a new one of its own."""
    notice = st.session_state.pop(_BOARD_MOVE_NOTICE_KEY, None)
    if notice:
        st.info(notice)


def render_board_card(
    db: Database,
    kind: str,
    item: dict[str, Any],
    *,
    today_iso: str,
    board_week_start: date,
    interactive: bool = True,
) -> None:
    """One compact card for the unified weekly board (the "Board" tab on
    `pages/14_Mission_Control.py`) -- a title, a one-line status, and the same
    shared move control every other surface already uses, right on the
    card face instead of nested inside an expander several clicks deep.
    This is the whole point of the board: one place to see and rearrange
    every subject's stories at once, not a new way of moving them.

    `kind` is one of the six values `weekly.board_for_week` tags each
    story with -- "lesson", "life_skill", "coding_module", "choice_topic",
    "project_step", "travel_entry" -- and picks which fields/db calls this
    reads. Moving a lesson to a day is never blocked, even when that day
    already holds another lesson of the same subject: two can share a day on
    purpose (a fresh lesson plus one from a prior day still awaiting his
    revision), so there is no same-day collision guard.

    `board_week_start` is the Monday of whichever week is currently on
    screen -- every move control's `schedule` write is wrapped in
    `_board_schedule` so moving a story to a date outside that week fires
    a toast saying so, rather than the card just disappearing with no
    explanation (see that function's own docstring).

    Every card wears a colored, labeled bar naming its subject (for a lesson)
    or kind (for everything else) -- see board_card_tag. The day itself is
    already unmistakable from the big colored column header, so the card's own
    color is free to encode "what is this" instead of repeating the day.

    Each story collapses into its own expander, title as the header --
    same "closed until you need it" rhythm as the Backlog panel's own
    epic sections, so a board with a dozen cards in one column reads as a
    dozen one-line rows, not a wall of open detail.

    `interactive` (default True) is what lets the exact same card serve both
    the parent's This Week Board tab and the student's own read-only Board on
    Home. False drops every parent-only affordance -- the move control (a
    parent reschedules/backlogs, he never does) and the "View full details"
    deep links into parent management tabs -- leaving just the card's own
    content and, for a lesson, the "View full lesson" dialog, which is his to
    open too. Nothing about a card's data or layout changes, so a Tuesday
    card reads identically on either board.
    """
    with st.container(border=True):
        # A colored, labeled bar across the top -- color + word together name
        # the subject (for a lesson) or kind (for everything else) at a glance,
        # collapsed or open, whichever day it sits under. See board_card_tag.
        tag_color, tag_icon, tag_label = board_card_tag(kind, item)
        # The estimate sits on the right of the always-visible tag bar (so it
        # reads whether the card is open or collapsed) -- one glance tells you
        # how heavy this block is, and the day header below sums them.
        est = format_board_minutes(board_item_minutes(kind, item))
        st.markdown(
            f'<div style="background:{tag_color}; color:#fff; margin:-1px -1px 8px; '
            f'padding:3px 9px 3px; border-radius:2px 2px 0 0; font-size:10.5px; '
            f'font-weight:800; text-transform:uppercase; letter-spacing:.06em; '
            f'display:flex; justify-content:space-between; gap:8px;">'
            f"<span>{tag_icon} {tag_label}</span>"
            f'<span style="opacity:.9; font-weight:700;">≈{est}</span></div>',
            unsafe_allow_html=True,
        )
        if kind == "lesson":
            icon = SUBJECT_ICONS.get(item["agent"], "📘")
            done = bool((item.get("metadata") or {}).get("student_done_on"))
            marker = "✅" if done else "⬜"
            with st.expander(f"{marker} {icon} **{md(item['title'])}**", expanded=False):
                st.caption(f"{item['agent'].replace('_', ' ').title()} agent")
                status_note = {
                    "submitted": "📤 waiting on you to review",
                    "needs_revision": "↩️ sent back — waiting on him",
                }.get(item["status"])
                if status_note:
                    st.caption(status_note)
                if interactive:
                    # Parent-only: how many written pieces to expect back from
                    # this one, so a day's review load is legible at a glance.
                    handins = hand_in_summary(item.get("payload") or {})
                    st.caption(handins if handins else "📝 No written hand-ins")
                    _render_board_estimate_editor(db, kind, item)
                if interactive and item["status"] in ("planned", "needs_revision"):
                    # No collision check on the target day: a day can hold more
                    # than one lesson of the same subject on purpose (a fresh
                    # lesson plus one from a prior day still waiting on his
                    # revision, say), so moving a subject into any day is never
                    # blocked ("just dont block me moving subject into a day.
                    # there could be two in one day.").
                    render_story_move_control(
                        key=f"board_lesson_{item['id']}",
                        active=not weekly.is_backlogged(item, today_iso),
                        scheduled_for=(item.get("metadata") or {}).get("planned_for"),
                        set_active=lambda a, lid=item["id"]: (
                            db.unhold_lesson(lid) if a else db.send_to_backlog(lid)
                        ),
                        schedule=_board_schedule(
                            lambda d, lid=item["id"]: (
                                db.reschedule_lesson(lid, d) if d else None
                            ),
                            board_week_start,
                        ),
                    )
                _render_board_deep_link(kind, item, db=db)

        elif kind == "life_skill":
            earned = bool(item["completed_on"])
            marker = "✅" if earned else "⬜"
            label = f"{marker} {BOARD_KIND_ICONS['life_skill']} **{md(item['title'])}**"
            with st.expander(label, expanded=False):
                st.caption(item["category"])
                _render_board_detail(item.get("description"), item.get("materials"))
                if interactive:
                    _render_board_estimate_editor(db, kind, item)
                    render_story_move_control(
                        key=f"board_ls_{item['id']}",
                        active=bool(item["active"]),
                        scheduled_for=item["scheduled_for"],
                        set_active=lambda a, sid=item["id"]: db.set_life_skill_active(sid, a),
                        schedule=_board_schedule(
                            lambda s, sid=item["id"]: db.schedule_life_skill(sid, s),
                            board_week_start,
                        ),
                    )
                _render_board_deep_link(kind)

        elif kind == "coding_module":
            earned = bool(item["completed_on"])
            marker = "✅" if earned else "⬜"
            label = f"{marker} {BOARD_KIND_ICONS['coding_module']} **{md(item['title'])}**"
            with st.expander(label, expanded=False):
                st.caption(item["category"])
                _render_board_detail(item.get("description"), item.get("materials"))
                if interactive:
                    _render_board_estimate_editor(db, kind, item)
                    render_story_move_control(
                        key=f"board_coding_{item['id']}",
                        active=bool(item["active"]),
                        scheduled_for=item["scheduled_for"],
                        set_active=lambda a, mid=item["id"]: db.set_coding_module_active(mid, a),
                        schedule=_board_schedule(
                            lambda s, mid=item["id"]: db.schedule_coding_module(mid, s),
                            board_week_start,
                        ),
                    )
                _render_board_deep_link(kind)

        elif kind == "choice_topic":
            label = (
                f"{BOARD_KIND_ICONS['choice_topic']} **{md(item['title'])}** — {item['status']}"
            )
            with st.expander(label, expanded=False):
                if item["category"]:
                    st.caption(item["category"])
                _render_board_detail(item.get("description"))
                if interactive:
                    _render_board_estimate_editor(db, kind, item)
                    if item["status"] not in ("done", "declined"):
                        render_story_move_control(
                            key=f"board_choice_{item['id']}",
                            active=bool(item["active"]),
                            scheduled_for=item["scheduled_for"],
                            set_active=lambda a, tid=item["id"]: db.set_choice_topic_active(tid, a),
                            schedule=_board_schedule(
                                lambda s, tid=item["id"]: db.schedule_choice_topic(tid, s),
                                board_week_start,
                            ),
                        )
                    else:
                        st.caption("Closed out — nothing left to move.")
                _render_board_deep_link(kind)

        elif kind == "project_step":
            done = bool(item["completed_on"])
            marker = "✅" if done else "⬜"
            label = f"{marker} {BOARD_KIND_ICONS['project_step']} **{md(item['title'])}**"
            with st.expander(label, expanded=False):
                _render_board_detail(
                    item.get("description"),
                    item.get("materials"),
                    pace=_project_step_pace(item),
                )
                if interactive:
                    _render_board_estimate_editor(db, kind, item)
                    if not done:
                        render_story_move_control(
                            key=f"board_step_{item['id']}",
                            active=bool(item["active"]),
                            scheduled_for=item["scheduled_for"],
                            set_active=lambda a, sid=item["id"]: db.set_project_step_active(sid, a),
                            schedule=_board_schedule(
                                lambda s, sid=item["id"]: db.schedule_project_step(sid, s),
                                board_week_start,
                            ),
                        )
                    else:
                        st.caption("Done — nothing left to move.")
                _render_board_deep_link(kind)

        elif kind == "travel_entry":
            title = md(item["title"]) if item["title"] else "Untitled trip"
            label = f"{BOARD_KIND_ICONS['travel_entry']} **{title}** — {item['status']}"
            with st.expander(label, expanded=False):
                where = item.get("state") or ""
                if where:
                    st.caption(f"📍 {md(where)}")
                _render_board_detail(note=_TRAVEL_BOARD_PROMPTS.get(item["status"]))
                if interactive:
                    _render_board_estimate_editor(db, kind, item)
                    if item["status"] != "completed":
                        render_story_move_control(
                            key=f"board_travel_{item['id']}",
                            active=bool(item["active"]),
                            scheduled_for=item["scheduled_for"],
                            set_active=lambda a, eid=item["id"]: db.set_travel_entry_active(eid, a),
                            schedule=_board_schedule(
                                lambda s, eid=item["id"]: db.schedule_travel_entry(eid, s),
                                board_week_start,
                            ),
                        )
                    else:
                        st.caption("Completed — nothing left to move.")
                _render_board_deep_link(kind)


# --- shared weekly board day grid: parent This Week tab + student Home board ---

# The grid is a header row plus one row per subject/kind, each its own
# st.columns(5). To keep every row's five day columns lined up under the same
# day headers -- and scrolling together on a narrow screen rather than each
# row scrolling on its own -- the horizontal scroll lives on the OUTER
# container (the one keyed "..._days_row"); every inner row is forced to the
# same fixed width (5 columns x 220px, never wrapping), so they all move as
# one when the container scrolls. Column min-width also stops a long title
# from squeezing narrower than one of its own words on a laptop screen.
_WEEK_BOARD_SCROLL_CSS = """
<style>
div[class*="st-key-"][class*="_days_row"] {
  overflow-x: auto !important;
  padding-bottom: 6px;
}
div[class*="st-key-"][class*="_days_row"] div[data-testid="stHorizontalBlock"] {
  flex-wrap: nowrap !important;
  min-width: max-content !important;
}
div[class*="st-key-"][class*="_days_row"] div[data-testid="stColumn"] {
  min-width: 220px !important;
  flex: 0 0 220px !important;
}
/* Same floor height on every card so a row of them reads as one even band
   across the week, short titles and long ones alike. */
div[class*="st-key-"][class*="_days_row"] div[data-testid="stColumn"]
  div[data-testid="stExpander"] {
  min-height: 84px;
}
</style>
"""


def render_board_days(
    db: Database,
    student: dict[str, Any],
    week_start: date,
    board: dict[str, list[tuple[str, dict[str, Any]]]],
    *,
    key_prefix: str,
    interactive: bool = True,
) -> None:
    """The five Mon-Fri day columns of the weekly sprint board, for one
    already-computed `board` (from weekly.board_for_week). Shared verbatim
    between the parent's This Week Board tab and the student's own read-only
    Board on Home -- the only difference between the two is `interactive`,
    threaded straight through to render_board_card (see its docstring). The
    caller owns week selection and, on the parent side, the Product Backlog
    panel below; this is only the day grid the two have in common.

    `key_prefix` namespaces the horizontal-scroll container so two boards
    rendered in one script run (the student's this-week and next-week views,
    say) never share a container key. The colored day pills are the same
    "Sunday Funnies" palette Home's own Week grid and the parent Board use.

    Each day is its own column and its cards pack to the top of it: a header
    row of day pills, then the five day columns, each listing only the cards
    actually planned for that day, top-first. Cards within a day still sort by
    a stable subject/kind order (`_BOARD_ROW_ORDER`, so Math sits above Science
    above English...), but a day never reserves an empty slot for a subject it
    doesn't have -- reported directly: "no matter what subject are in the day,
    the list should always stay populated at the top", so a lone project no
    longer sits marooned at the bottom of its column under blank space where
    other days' subjects would line up.
    """
    days = weekly.week_dates(week_start, include_friday=True)
    today = date.today()
    today_iso = today.isoformat()

    # day_index -> [(kind, item), ...], each day's cards sorted by the stable
    # subject/kind order so a column reads Math, Science, English... top-down.
    def _row_rank(entry: tuple[str, dict[str, Any]]) -> int:
        ident = _board_identity(entry[0], entry[1])
        return _BOARD_ROW_ORDER.index(ident) if ident in _BOARD_ROW_ORDER else len(_BOARD_ROW_ORDER)

    by_day: dict[int, list[tuple[str, dict[str, Any]]]] = {}
    for day_index, day_date in enumerate(days):
        cards = list(board[day_date.isoformat()])
        cards.sort(key=_row_rank)
        by_day[day_index] = cards
    any_cards = any(by_day.values())

    st.markdown(_WEEK_BOARD_SCROLL_CSS, unsafe_allow_html=True)
    with st.container(key=f"{key_prefix}_days_row"):
        # Header row: the day pills, aligned above their own column of cards.
        header_columns = st.columns(5)
        for index, (column, day_date) in enumerate(zip(header_columns, days)):
            color = theming.PRINTED_COMIC_WEEKDAY_COLORS[index]
            with column:
                today_tag = " · Today" if day_date == today else ""
                st.markdown(
                    f'<span style="display:inline-block; padding:2px 10px 3px; '
                    f'border-radius:3px; background:{color}; '
                    f'color:{theming.PRINTED_COMIC_PAPER}; font-weight:900; font-size:15px; '
                    f'text-transform:uppercase; letter-spacing:-.01em; '
                    f'text-shadow:1.5px 1.5px 0 rgba(0,0,0,.35);">'
                    f"{day_date.strftime('%a')}</span>",
                    unsafe_allow_html=True,
                )
                # A day's own total, so a heavy day (or a suspiciously light
                # one) reads at a glance right under its date -- the sum of
                # every card's own estimate below it (see board_item_minutes).
                day_items = board[day_date.isoformat()]
                day_minutes = sum(board_item_minutes(k, it) for k, it in day_items)
                total_note = (
                    f" · ≈{format_board_minutes(day_minutes)}" if day_items else ""
                )
                st.caption(day_date.strftime("%b %-d") + today_tag + total_note)

        if not any_cards:
            st.caption("Nothing planned this week.")

        # One row of five day columns; each column stacks its own day's cards
        # from the top, so a day is never padded out with empty slots for
        # subjects it doesn't have.
        day_columns = st.columns(5)
        for day_index, column in enumerate(day_columns):
            with column:
                for kind, item in by_day.get(day_index, []):
                    render_board_card(
                        db, kind, item,
                        today_iso=today_iso,
                        board_week_start=week_start,
                        interactive=interactive,
                    )


_BOARD_BACKLOG_SCROLL_CSS = """
<style>
div[class*="st-key-"][class*="_backlog_row_"] div[data-testid="stHorizontalBlock"] {
  overflow-x: auto !important;
  flex-wrap: nowrap !important;
  padding-bottom: 6px;
}
div[class*="st-key-"][class*="_backlog_row_"] div[data-testid="stColumn"] {
  min-width: 220px !important;
  flex: 0 0 220px !important;
}
</style>
"""


def render_board_backlog(
    db: Database,
    student: dict[str, Any],
    board: dict[str, list[tuple[str, dict[str, Any]]]],
    *,
    key_prefix: str,
    board_week_start: date,
    interactive: bool = True,
    today_iso: str | None = None,
) -> None:
    """The Product Backlog panel -- every currently-parked story, any week it
    came from, grouped by epic. Shared by the parent's Mission Control board
    (interactive: the move control on each card is how a parked story gets a
    day) and Landon's read-only Home board (interactive=False -> no move
    controls, just each card's own detail and, on a lesson, the
    View-full-lesson dialog). Reported directly: from his board he should be
    able to "view full lesson for anything thats in view there. backlog or
    assigned a date."

    `key_prefix` namespaces each epic's own scroll container so the parent
    board and the student board never share a container key.
    """
    today_iso = today_iso or date.today().isoformat()

    st.markdown(_BOARD_BACKLOG_SCROLL_CSS, unsafe_allow_html=True)
    by_epic = weekly.group_backlog_by_epic(board["backlog"])
    if not sum(len(items) for items in by_epic.values()):
        st.caption("Nothing parked.")
        return
    for epic in weekly.EPIC_ORDER:
        items = by_epic.get(epic, [])
        if not items:
            continue
        icon = EPIC_ICONS.get(epic, "📘")
        with st.expander(f"{icon} {epic} ({len(items)})", expanded=True):
            with st.container(key=f"{key_prefix}_backlog_row_{epic.replace(' ', '_')}"):
                backlog_columns = st.columns(min(len(items), 4))
                for position, (kind, item) in enumerate(items):
                    with backlog_columns[position % len(backlog_columns)]:
                        render_board_card(
                            db, kind, item,
                            today_iso=today_iso,
                            board_week_start=board_week_start,
                            interactive=interactive,
                        )


# --- per-subject week view: the same day board, scoped to one agent ------------

# Same min-width-plus-scroll fix This Week's own Board tab uses (see
# pages/14_Mission_Control.py's own _BOARD_SCROLL_CSS and the README section on
# why: st.columns has no minimum width, so five equal fractions of even a
# full-width row squeeze a long title narrower than one of its own words
# has room for on a real laptop screen). Kept as its own copy rather than
# imported from that page -- a page can't import from another page in
# this app's layout -- scoped to this function's own container keys.
_SUBJECT_WEEK_SCROLL_CSS = """
<style>
div[class*="st-key-subject_week_days_row"] div[data-testid="stHorizontalBlock"],
div[class*="st-key-subject_week_backlog_row"] div[data-testid="stHorizontalBlock"] {
  overflow-x: auto !important;
  flex-wrap: nowrap !important;
  padding-bottom: 6px;
}
div[class*="st-key-subject_week_days_row"] div[data-testid="stColumn"],
div[class*="st-key-subject_week_backlog_row"] div[data-testid="stColumn"] {
  min-width: 220px !important;
  flex: 0 0 220px !important;
}
</style>
"""


def render_subject_week_tab(db: Database, student: dict[str, Any], agent: str) -> None:
    """The same This/Next week day board This Week's own Board tab already
    gives, scoped to just this one subject's own lessons -- so a parent
    checking in on Math, say, can see, move, or open a lesson in full
    detail without a separate trip to This Week. Reported directly: "shouldn't
    I still be able to go to each core curriculum tab... and also get the
    level of detail and view into lessons, kinda like the board view of
    this week and next."

    Reuses `weekly.board_for_week` and `render_board_card` verbatim -- both
    are already kind- and agent-agnostic -- so this is purely a filtered
    view over the exact same data This Week's Board tab reads, never a
    second query or a second card renderer to keep in sync. Session-state
    keys are namespaced per agent (`f"subject_week_{agent}_..."`), so
    Math's own "week to view" and Science's don't collide with each other
    or with This Week's own `board_week_picker`, even though session_state
    is shared across every page in one browser session.
    """
    key_prefix = f"subject_week_{agent}"
    picker_key = f"{key_prefix}_picker"
    if picker_key not in st.session_state:
        st.session_state[picker_key] = date.today()

    jump_columns = st.columns([1, 1, 5])
    if jump_columns[0].button("This week", key=f"{key_prefix}_jump_this"):
        st.session_state[picker_key] = date.today()
        st.rerun()
    if jump_columns[1].button("Next week", key=f"{key_prefix}_jump_next"):
        st.session_state[picker_key] = weekly.default_plan_target()
        st.rerun()

    week_start = weekly.week_start(st.date_input("Week to view", key=picker_key))
    days = weekly.week_dates(week_start, include_friday=True)
    st.caption(f"{days[0].strftime('%b %-d')} – {days[-1].strftime('%b %-d, %Y')}")

    # Any cross-week move made from here needs the same explanation This
    # Week's own Board tab gives -- otherwise a story moved from this page
    # would just vanish from view with nothing to say where it went (see
    # _board_schedule's own docstring).
    render_board_move_notice()

    board = weekly.board_for_week(db, student, week_start)
    today_iso = date.today().isoformat()

    st.markdown(_SUBJECT_WEEK_SCROLL_CSS, unsafe_allow_html=True)
    with st.container(key=f"subject_week_days_row_{agent}"):
        columns = st.columns(5)
        for index, (column, day) in enumerate(zip(columns, days)):
            color = theming.PRINTED_COMIC_WEEKDAY_COLORS[index]
            with column:
                today_tag = " · Today" if day == date.today() else ""
                st.markdown(
                    f'<span style="display:inline-block; padding:2px 10px 3px; '
                    f'border-radius:3px; background:{color}; '
                    f'color:{theming.PRINTED_COMIC_PAPER}; font-weight:900; font-size:15px; '
                    f'text-transform:uppercase; letter-spacing:-.01em; '
                    f'text-shadow:1.5px 1.5px 0 rgba(0,0,0,.35);">'
                    f"{day.strftime('%a')}</span>",
                    unsafe_allow_html=True,
                )
                st.caption(day.strftime("%b %-d") + today_tag)
                day_items = [
                    (kind, item)
                    for kind, item in board[day.isoformat()]
                    if kind == "lesson" and item["agent"] == agent
                ]
                if not day_items:
                    st.caption("Nothing here.")
                for kind, item in day_items:
                    render_board_card(
                        db, kind, item,
                        today_iso=today_iso,
                        board_week_start=week_start,
                    )

    backlog_items = [
        (kind, item) for kind, item in board["backlog"] if kind == "lesson" and item["agent"] == agent
    ]
    if backlog_items:
        st.divider()
        st.markdown(f"**📋 Backlog** ({len(backlog_items)})")
        with st.container(key=f"subject_week_backlog_row_{agent}"):
            backlog_columns = st.columns(min(len(backlog_items), 4))
            for position, (kind, item) in enumerate(backlog_items):
                with backlog_columns[position % len(backlog_columns)]:
                    render_board_card(
                        db, kind, item,
                        today_iso=today_iso,
                        board_week_start=week_start,
                    )


# --- life skill cards: the catalog grid and its manager -------------------------

LIFE_SKILL_CATEGORY_ICONS = {
    "Money": "💵",
    "Cooking": "🍳",
    "Vehicle": "🚗",
    "Communication": "💬",
    "Home": "🏠",
    "Growing Up": "🌱",
}
LIFE_SKILL_DEFAULT_ICON = "🎖️"  # any category a parent types in beyond the starter five
LIFE_SKILL_CARDS_PER_ROW = 3

# Was "Neon Pop" -- its own fixed pink/teal skin, picked before the app
# consolidated onto one theme, and never migrated when it did. Now reads
# from `compass.theme`'s own CSS custom properties (--c-border, --c-primary,
# etc.) like every other surface, so it stops clashing whenever the theme's
# palette moves. The story is always on the card; nothing here is
# click-to-reveal. A checkbox is the only thing that changes `completed_on`,
# and only the checked state changes how a card looks -- brought in via two
# *static* rules keyed off a suffix baked into each card's own container
# `key` (`..._earned` / `..._locked`) rather than one generated <style>
# block per skill, the same technique the old badge case used: a container
# `key` becomes a `st-key-<key>` class token, and `[class*=...]` matches on
# that token's substring.
_LIFE_SKILL_CARD_CSS = """
<style>
.cp-ls-tallybar {
  font-weight: 800; font-size: 15px; color: var(--c-text);
  border-bottom: 2px solid var(--c-border); padding-bottom: 10px; margin-bottom: 10px;
}
.cp-ls-tallybar .cp-ls-tally {
  font-family: var(--c-mono);
  font-size: 13px; color: var(--c-dim); font-weight: 400;
}
div[class*="st-key-ls_card_"][class*="_locked"],
div[class*="st-key-ls_card_"][class*="_earned"] {
  border-radius: var(--c-radius) !important;
  border: 1px solid var(--c-border) !important;
  padding: 14px 16px 8px !important;
  background: var(--c-panel) !important;
  box-shadow: var(--c-glow);
  position: relative;
  margin-bottom: 16px;
}
div[class*="st-key-ls_card_"][class*="_earned"] {
  border-color: var(--c-primary) !important;
  box-shadow: 0 4px 18px rgba(242, 183, 5, .25);
}
.cp-ls-seal {
  display: none; position: absolute; top: -16px; right: 14px; width: 52px; height: 52px;
  border-radius: 50%; align-items: center; justify-content: center; font-size: 19px;
  background: radial-gradient(circle at 32% 28%, var(--c-seal-highlight), var(--c-primary) 75%);
  border: 3px solid var(--c-primary);
  box-shadow: 0 0 16px rgba(242, 183, 5, .45);
  transform: rotate(12deg);
}
div[class*="st-key-ls_card_"][class*="_earned"] .cp-ls-seal { display: flex; }
.cp-ls-title { font-weight: 800; font-size: 14.5px; color: var(--c-text); padding-right: 34px; line-height: 1.3; }
.cp-ls-cat {
  font-size: 10.5px; color: var(--c-border); text-transform: uppercase; letter-spacing: .1em;
  margin: 3px 0 8px; font-family: var(--c-mono);
}
.cp-ls-story { font-size: 12.5px; line-height: 1.5; color: var(--c-text); opacity: .92; margin: 0 0 8px; }
.cp-ls-needs { font-size: 11.5px; color: var(--c-dim); margin-bottom: 2px; }
.cp-ls-needs b { color: var(--c-text); }
div[class*="st-key-ls_card_"] input[type="checkbox"] { accent-color: var(--c-primary); }
div[class*="st-key-ls_card_"] [data-testid="stWidgetLabel"] p { font-weight: 700; font-size: 12.5px; }
/* His view (render_student_life_skills): earned badges up top, then the
   skills a parent assigned him as bordered cards below. */
div[class*="st-key-ls_badge_"] {
  border-radius: var(--c-radius) !important;
  border: 2px solid var(--c-primary) !important;
  padding: 12px 10px !important;
  background: var(--c-panel) !important;
  box-shadow: 0 4px 18px rgba(242, 183, 5, .25);
  text-align: center;
  margin-bottom: 14px;
}
.cp-ls-badge-seal { font-size: 30px; line-height: 1; }
.cp-ls-badge-title { font-weight: 800; font-size: 13px; color: var(--c-text); line-height: 1.25; margin-top: 4px; }
.cp-ls-badge-cat {
  font-size: 10px; color: var(--c-border); text-transform: uppercase; letter-spacing: .08em;
  font-family: var(--c-mono); margin-top: 2px;
}
.cp-ls-badge-date { font-size: 10.5px; color: var(--c-dim); margin-top: 3px; }
div[class*="st-key-ls_assigned_"] {
  border-radius: var(--c-radius) !important;
  border: 1px solid var(--c-border) !important;
  padding: 12px 16px 6px !important;
  background: var(--c-panel) !important;
  box-shadow: var(--c-glow);
  margin-bottom: 12px;
}
.cp-ls-atitle { font-weight: 800; font-size: 14.5px; color: var(--c-text); line-height: 1.3; }
div[class*="st-key-ls_assigned_"] input[type="checkbox"] { accent-color: var(--c-primary); }
</style>
"""


def render_student_life_skills(db: Database, skills: list[dict[str, Any]]) -> None:
    """His own Life Skills surface: the badges he's already earned up top,
    then the skills a parent has assigned him below, each a bordered card in
    the same "what's on your plate" style the rest of the app uses. Not a
    checklist grid, and no move control -- choosing which skills he works on,
    and pinning them to specific days, is a parent's call on the Master list;
    his job here is to do the assigned ones and mark them done. Reported
    directly: "his activity q of assigned life task skills... badges unlocked
    up top, and below in the backlog style uniform across app, are ones i
    select for him. these can and will be assigned during the week on specific
    dates of my chosing."

    Visibility is this function's own rule (unchanged): a skill shows only if
    it's `active` (unlocked/assigned from the Master list) or already
    `completed_on` -- an earned badge stays even if a parent later re-locks it.
    Marking one done is his to do; un-marking and removing are parent actions
    on the Master list, deliberately not offered here.
    """
    visible = [s for s in skills if s["active"] or s["completed_on"]]
    if not visible:
        return
    earned = [s for s in visible if s["completed_on"]]
    assigned = [s for s in visible if not s["completed_on"]]

    st.markdown(_LIFE_SKILL_CARD_CSS, unsafe_allow_html=True)
    st.markdown(
        f'<div class="cp-ls-tallybar">🥇 <span class="cp-ls-tally">'
        f"{len(earned)} / {len(visible)} earned</span></div>",
        unsafe_allow_html=True,
    )

    if earned:
        st.markdown("**🏅 Badges earned**")
        for row_start in range(0, len(earned), LIFE_SKILL_CARDS_PER_ROW):
            row = earned[row_start : row_start + LIFE_SKILL_CARDS_PER_ROW]
            columns = st.columns(LIFE_SKILL_CARDS_PER_ROW)
            for index, skill in enumerate(row):
                icon = LIFE_SKILL_CATEGORY_ICONS.get(skill["category"], LIFE_SKILL_DEFAULT_ICON)
                with columns[index], st.container(key=f"ls_badge_{skill['id']}"):
                    st.markdown(
                        f'<div class="cp-ls-badge-seal">{icon}</div>'
                        f'<div class="cp-ls-badge-title">{html.escape(skill["title"])}</div>'
                        f'<div class="cp-ls-badge-cat">{html.escape(skill["category"])}</div>'
                        f'<div class="cp-ls-badge-date">✅ {skill["completed_on"]}</div>',
                        unsafe_allow_html=True,
                    )

    st.markdown("**📋 Assigned to you**")
    if not assigned:
        st.caption("Nothing assigned right now — your parent will add some here.")
    for skill in assigned:
        icon = LIFE_SKILL_CATEGORY_ICONS.get(skill["category"], LIFE_SKILL_DEFAULT_ICON)
        with st.container(key=f"ls_assigned_{skill['id']}"):
            when = f" · 📅 {skill['scheduled_for']}" if skill["scheduled_for"] else ""
            st.markdown(
                f'<div class="cp-ls-atitle">{icon} {html.escape(skill["title"])}</div>'
                f'<div class="cp-ls-cat">{html.escape(skill["category"])}{when}</div>',
                unsafe_allow_html=True,
            )
            if skill["description"]:
                st.markdown(
                    f'<div class="cp-ls-story">{html.escape(skill["description"])}</div>',
                    unsafe_allow_html=True,
                )
            if skill["materials"]:
                st.markdown(
                    f'<div class="cp-ls-needs"><b>You\'ll need:</b> '
                    f'{html.escape(skill["materials"])}</div>',
                    unsafe_allow_html=True,
                )
            if st.checkbox("Mark done", value=False, key=f"ls_done_{skill['id']}"):
                db.set_life_skill_done(skill["id"], True)
                st.rerun()


def render_life_skill_catalog_manager(db: Database, skills: list[dict[str, Any]]) -> None:
    """The pace control: every catalog skill, active or not, one row each,
    title and status collapsed by default -- open a row for the full mission,
    materials, and credit subject before deciding whether to unlock it.
    Plain and utilitarian on purpose -- this is a parent's management view,
    not the kid-facing card grid, so it doesn't need the Neon Pop treatment
    the checklist itself has.

    An already-earned skill's checkbox still reflects and controls `active`,
    even though the checklist shows it either way (see the `active OR
    completed_on` filter at the call site) -- re-locking a finished skill
    just stops it counting toward "what's next," it never hides the badge.

    Each row also gets a date picker to assign the skill to a specific day
    -- purely a due-date, layered on top of `active`/`completed_on` rather
    than replacing either: a skill still needs unlocking to be visible at
    all, and assigning a day just adds a "do this one on Wednesday" pin on
    top of that. Left on "No specific day" (the default, and what every
    skill starts as), nothing changes from before this existed.
    """
    by_category: dict[str, list[dict[str, Any]]] = {}
    for skill in skills:
        by_category.setdefault(skill["category"], []).append(skill)

    unlocked = sum(1 for s in skills if s["active"])
    st.caption(f"{unlocked} / {len(skills)} unlocked")

    for category, items in by_category.items():
        st.subheader(category)
        for skill in items:
            status = "✅ earned" if skill["completed_on"] else ("🔓 unlocked" if skill["active"] else "🔒 locked")
            if skill["scheduled_for"] and not skill["completed_on"]:
                status += f" · 📅 assigned {skill['scheduled_for']}"
            with st.expander(f"{skill['title']} — {status}"):
                columns = st.columns([5, 1])
                if skill["description"]:
                    columns[0].markdown(f"**The mission:** {skill['description']}")
                if skill["materials"]:
                    columns[0].caption(f"You'll need: {skill['materials']}")
                columns[0].caption(f"Credits toward {subjects.label(skill['credit_subject'])}")
                if skill["completed_on"]:
                    columns[0].caption(f"✅ Earned {skill['completed_on']}")
                # Keyed on `skill["active"]` itself, not just the skill's id --
                # `schedule_life_skill` below can flip `active` as a side
                # effect of a *different* widget's write. A fixed key would
                # keep this checkbox's old session_state value across that
                # change (Streamlit ignores `value=` once a key already has
                # state), read the now-stale value as a fresh user click on
                # the next run, and write the lock straight back, silently
                # undoing the unlock. Folding the current value into the key
                # forces a brand-new widget -- freshly seeded from `value=`
                # -- any time `active` changes for any reason at all.
                active = columns[1].checkbox(
                    "Unlocked",
                    value=bool(skill["active"]),
                    key=f"ls_active_{skill['id']}_{skill['active']}",
                )
                if active != bool(skill["active"]):
                    db.set_life_skill_active(skill["id"], active)
                    st.rerun()

                assign = columns[0].checkbox(
                    "Assign this to a specific day",
                    value=bool(skill["scheduled_for"]),
                    key=f"ls_assign_toggle_{skill['id']}",
                )
                if assign:
                    picked = columns[0].date_input(
                        "Day",
                        value=date.fromisoformat(skill["scheduled_for"])
                        if skill["scheduled_for"]
                        else date.today(),
                        key=f"ls_assign_date_{skill['id']}",
                    )
                    if picked.isoformat() != skill["scheduled_for"]:
                        db.schedule_life_skill(skill["id"], picked.isoformat())
                        st.rerun()
                elif skill["scheduled_for"]:
                    db.schedule_life_skill(skill["id"], None)
                    st.rerun()


# --- Coding Camp: same shape as Core Life Skills, its own catalog, folded
# into the Life Skills page as a flat section (see pages/6_Life_Skills.py's
# "Coding" tab) rather than a top-level page of its own -----------------------
#
# Plain expander rows throughout, on the same reasoning
# render_life_skill_catalog_manager's own docstring gives for its half of Life
# Skills -- a v1 checklist doesn't need the Neon Pop card grid Life Skills'
# checklist has to be a real, working feature; that's a separate, later
# polish pass, not a reason to hold this back.


def render_coding_module_cards(db: Database, modules: list[dict[str, Any]], can_edit: bool) -> None:
    """The checklist itself. Takes the *full* catalog, not a pre-filtered
    list -- visibility is this function's own rule: a module shows only if
    it's `active` (unlocked from *Master list*) or already `completed_on`,
    same reasoning render_student_life_skills already gives."""
    modules = [m for m in modules if m["active"] or m["completed_on"]]
    if not modules:
        return

    by_category: dict[str, list[dict[str, Any]]] = {}
    for module in modules:
        by_category.setdefault(module["category"], []).append(module)
    done = sum(1 for m in modules if m["completed_on"])
    st.caption(f"🏆 {done} / {len(modules)} built")

    for category, items in by_category.items():
        complete = sum(1 for i in items if i["completed_on"])
        st.subheader(f"{category} — {complete}/{len(items)}")
        for module in items:
            earned = bool(module["completed_on"])
            badge = f"✅ built {module['completed_on']}" if earned else (
                f"📅 assigned {module['scheduled_for']}" if module["scheduled_for"] else ""
            )
            with st.container(border=True):
                title_col, move_col = st.columns([5, 1])
                with title_col:
                    st.markdown(f"**{md(module['title'])}**" + (f" — {badge}" if badge else ""))
                if is_parent():
                    with move_col:
                        render_story_move_control(
                            key=f"coding_{module['id']}",
                            active=bool(module["active"]),
                            scheduled_for=module["scheduled_for"],
                            set_active=lambda a, mid=module["id"]: db.set_coding_module_active(mid, a),
                            schedule=lambda s, mid=module["id"]: db.schedule_coding_module(mid, s),
                        )
                if module["description"]:
                    st.caption(md(module["description"]))
                if module["materials"]:
                    st.caption(f"You'll need: {md(module['materials'])}")
                # Visible to both of you, always -- this is the actual
                # "how to do this" content the checklist used to be missing
                # entirely, not a parent-only planning step. Generating one
                # in the first place still only happens from the Coding
                # tab's own "Plan a build guide" section (spends real API
                # cost, so parent-gated there), but once it exists, reading
                # it is exactly what he needs it for.
                plan = db.latest_coding_plan(module["student_id"], module["id"])
                if plan:
                    with st.expander("📖 How to build this", expanded=False):
                        render_coding_plan(plan["payload"])
                columns = st.columns([1, 1])
                checked = columns[0].checkbox(
                    "Mark done", value=earned, key=f"coding_done_{module['id']}"
                )
                if checked != earned:
                    db.set_coding_module_done(module["id"], checked)
                    st.rerun()
                if can_edit and columns[1].button("🗑️ Remove", key=f"coding_remove_{module['id']}"):
                    db.delete_coding_module(module["id"])
                    st.rerun()


def render_coding_module_catalog_manager(db: Database, modules: list[dict[str, Any]]) -> None:
    """The pace control -- identical shape to `render_life_skill_catalog_manager`,
    just for the Coding Camp catalog: every module, active or not, one row
    each, collapsed by default, with an unlock toggle and an optional
    assign-to-a-day date picker layered on top."""
    by_category: dict[str, list[dict[str, Any]]] = {}
    for module in modules:
        by_category.setdefault(module["category"], []).append(module)

    unlocked = sum(1 for m in modules if m["active"])
    st.caption(f"{unlocked} / {len(modules)} unlocked")

    for category, items in by_category.items():
        st.subheader(category)
        for module in items:
            status = (
                "✅ built" if module["completed_on"]
                else ("🔓 unlocked" if module["active"] else "🔒 locked")
            )
            if module["scheduled_for"] and not module["completed_on"]:
                status += f" · 📅 assigned {module['scheduled_for']}"
            with st.expander(f"{module['title']} — {status}"):
                columns = st.columns([5, 1])
                if module["description"]:
                    columns[0].markdown(f"**The idea:** {module['description']}")
                if module["materials"]:
                    columns[0].caption(f"You'll need: {module['materials']}")
                columns[0].caption(f"Credits toward {subjects.label(module['credit_subject'])}")
                if module["completed_on"]:
                    columns[0].caption(f"✅ Built {module['completed_on']}")
                # Same reasoning render_life_skill_catalog_manager's own key
                # gives: folding `active` into the key forces a fresh widget
                # any time it changes for any reason, so a stale
                # session_state value from before never writes the lock
                # straight back.
                active = columns[1].checkbox(
                    "Unlocked",
                    value=bool(module["active"]),
                    key=f"coding_active_{module['id']}_{module['active']}",
                )
                if active != bool(module["active"]):
                    db.set_coding_module_active(module["id"], active)
                    st.rerun()

                assign = columns[0].checkbox(
                    "Assign this to a specific day",
                    value=bool(module["scheduled_for"]),
                    key=f"coding_assign_toggle_{module['id']}",
                )
                if assign:
                    picked = columns[0].date_input(
                        "Day",
                        value=date.fromisoformat(module["scheduled_for"])
                        if module["scheduled_for"]
                        else date.today(),
                        key=f"coding_assign_date_{module['id']}",
                    )
                    if picked.isoformat() != module["scheduled_for"]:
                        db.schedule_coding_module(module["id"], picked.isoformat())
                        st.rerun()
                elif module["scheduled_for"]:
                    db.schedule_coding_module(module["id"], None)
                    st.rerun()


# --- choice topics: Tier 3, folded into the Life Skills page --------------------

_CHOICE_STATUS_FLOW = {
    "proposed": ("Approve", "approved"),
    "approved": ("Start", "active"),
    "active": ("Mark done", "done"),
}


def render_choice_topics_section(db: Database, student: dict[str, Any]) -> None:
    """Tier 3 -- freedom of choice. Used to be its own top-level page
    (pages/5_Choice_Topics.py); folded in here as a Life Skills tab instead,
    on the same "his to pick, light parent approval" reasoning that already
    put the two side by side -- purely a nav simplification. The underlying
    `choice_topics` table, its status flow, and its own `active` backlog
    gate are completely untouched; only where the page lives moved.
    """
    st.caption(
        "A running list he curates, with light parent approval. No prerequisite logic, no "
        "agent picking the 'optimal' next step — this is the counterweight to Tier 1's "
        "structure. Hours still count."
    )
    with st.form("add_choice", clear_on_submit=True):
        st.markdown("**Add a topic** — goes on the list for a parent to review and approve.")
        columns = st.columns([2, 1, 1])
        title = columns[0].text_input("What do you want to learn?")
        category = columns[1].text_input("Category", placeholder="e.g. coding, music, cars")
        credit_subject = columns[2].selectbox(
            "Credits toward",
            subjects.SUBJECT_KEYS,
            index=subjects.SUBJECT_KEYS.index("occupational_education"),
            format_func=subjects.label,
        )
        description = st.text_area("Anything else about it?", height=80)
        if st.form_submit_button("Add to the list", type="primary") and title.strip():
            db.add_choice_topic(
                student["id"],
                title.strip(),
                description.strip(),
                category.strip(),
                credit_subject,
            )
            st.rerun()

    topics = db.list_choice_topics(student["id"])
    if not topics:
        st.info("The list is empty. Add whatever he's into this week.")

    # Backlog vs visible to him, same gate Life Skills and lessons already
    # have, unrelated to `status` -- a proposed/approved/active topic can
    # still be parked out of his view. He never sees a backlogged topic at
    # all; a parent sees everything, with a way to move each one back and
    # forth (see the "🗄️"/"➡️" button below).
    visible_topics = (
        topics if is_parent()
        else [t for t in topics if t["active"] or t["status"] in ("done", "declined")]
    )

    for topic in visible_topics:
        with st.container(border=True):
            columns = st.columns([4, 1, 1, 1])
            badge = {
                "proposed": "🕓 proposed",
                "approved": "👍 approved",
                "active": "🔥 active",
                "done": "✅ done",
                "declined": "🚫 declined",
            }[topic["status"]]
            if not topic["active"]:
                badge += " · 🗄️ backlogged"
            category_label = f" · *{md(topic['category'])}*" if topic["category"] else ""
            columns[0].markdown(f"**{md(topic['title'])}**{category_label} — {badge}")
            if topic["description"]:
                columns[0].caption(md(topic["description"]))
            columns[0].caption(f"Credits toward {subjects.label(topic['credit_subject'])}")
            if topic["parent_note"]:
                columns[0].caption(f"Parent: {md(topic['parent_note'])}")

            # "Approve"/"Decline" are the actual review step -- he proposes,
            # a parent decides, or the "light parent approval" this page
            # promises is fiction and he's approving his own ideas. Once a
            # topic clears that step, "Start"/"Mark done" are just his own
            # progress tracking and stay open to either of you, same as a
            # Life Skills checkbox.
            awaiting_review = topic["status"] == "proposed"
            action = _CHOICE_STATUS_FLOW.get(topic["status"])
            if action and (not awaiting_review or is_parent()):
                if columns[1].button(action[0], key=f"advance_{topic['id']}"):
                    db.set_choice_status(topic["id"], action[1])
                    st.rerun()
            if awaiting_review:
                if is_parent():
                    if columns[2].button("Decline", key=f"decline_{topic['id']}"):
                        db.set_choice_status(topic["id"], "declined")
                        st.rerun()
                else:
                    columns[1].caption("Waiting on parent review")
            elif columns[2].button("Remove", key=f"remove_{topic['id']}"):
                db.delete_choice_topic(topic["id"])
                st.rerun()

            # Freedom to move a topic between Backlog and a specific day
            # whenever a parent decides -- the same shared control every
            # other story type uses. Not offered on a closed-out topic: a
            # done or declined one is already exempt from the visibility
            # filter above, so there's nothing left for this to do to it.
            if is_parent() and topic["status"] not in ("done", "declined"):
                with columns[3]:
                    render_story_move_control(
                        key=f"choice_{topic['id']}",
                        active=bool(topic["active"]),
                        scheduled_for=topic["scheduled_for"],
                        set_active=lambda a, tid=topic["id"]: db.set_choice_topic_active(tid, a),
                        schedule=lambda s, tid=topic["id"]: db.schedule_choice_topic(tid, s),
                    )

    if not is_parent():
        return

    st.divider()
    st.subheader("Log time on a choice topic")
    st.caption(
        "These hours count toward the 1,000-hour floor in full. The compliance page "
        "shows Tier 3's share against the family guideline — a warning, never a block."
    )
    # Named for eligibility-to-log, not the `active` backlog column -- a
    # backlogged topic still logs fine (a parent parking it doesn't
    # retroactively undo hours already worth logging).
    loggable = [t for t in topics if t["status"] in ("approved", "active", "done")]
    if not loggable:
        st.info("Approve a topic first and it'll show up here.")
        return

    with st.form("log_choice"):
        topic = st.selectbox(
            "Topic", loggable, format_func=lambda t: f"{t['title']} ({t['status']})"
        )
        columns = st.columns(3)
        occurred_on = columns[0].date_input("Date", value=date.today())
        minutes = columns[1].number_input(
            "Minutes", min_value=5, max_value=600, value=60, step=15
        )
        credit_subject = columns[2].selectbox(
            "Credits toward",
            subjects.SUBJECT_KEYS,
            index=subjects.SUBJECT_KEYS.index(topic["credit_subject"])
            if topic["credit_subject"] in subjects.SUBJECT_KEYS
            else subjects.SUBJECT_KEYS.index("occupational_education"),
            format_func=subjects.label,
        )
        note = st.text_input("What did he actually do?")
        if st.form_submit_button("Log hours", type="primary"):
            db.log_activity(
                student_id=student["id"],
                title=topic["title"],
                tier=config.TIER_CHOICE,
                primary_subject=credit_subject,
                minutes=int(minutes),
                subject_credits={credit_subject: int(minutes)},
                occurred_on=occurred_on.isoformat(),
                description=note,
                source="choice",
            )
            if topic["status"] == "approved":
                db.set_choice_status(topic["id"], "active")
            st.success("Logged.")
            st.rerun()


# --- vocabulary review: multiple choice, auto-graded ---------------------------

VOCAB_STREAK_HYPE = ["Nice!", "Boom!", "Nailed it!", "You got it!", "Crushed it!", "Sweet!"]
VOCAB_STREAK_ON_FIRE = 5  # streak length that earns balloons, not just a toast

VOCAB_QUIZ_CHOICES = 4  # the correct definition plus up to three decoys
VOCAB_QUIZ_MIN_DEFINED_WORDS = 2  # need at least one other word to draw a decoy from


def _render_vocab_done_button(db: Database, student: dict[str, Any], today: str) -> None:
    """A real, persisted "he reviewed his words today" signal -- unlike the
    Concentration game's own streak/reviewed-count (session state only, gone
    the moment the browser session ends), this survives a refresh or a new
    session, and is what render_today_checklist reads to show it alongside
    lesson and life-skill completions. Always available, not gated behind
    clearing every due word in one sitting -- same trust-his-click
    philosophy as a lesson's own "I'm done for today" button, and the same
    reason that one exists: nothing here was actually prompting him to treat
    this as a real, completable task.
    """
    if db.vocab_reviewed_on(student["id"], today):
        st.success("✅ Marked done for today.")
        return
    if st.button("✅ I'm done with words for today", key="vocab_done_today"):
        db.mark_vocab_reviewed(student["id"], today)
        st.rerun()


def render_vocab_quiz(db: Database, student: dict[str, Any]) -> None:
    """Vocabulary review: multiple choice, auto-graded. The word shows, four
    possible definitions follow -- the real one plus up to three decoys
    pulled from his own other vocabulary words (no AI call needed, and a
    decoy that's a real definition of a real word he's also learning is a
    more honest test than an invented one) -- pick one, get graded
    immediately.

    Replaced a Concentration/memory-match game that mostly tested spatial
    memory (where was that card?) rather than whether he actually knew a
    definition -- matching two already-visible cards never required
    recalling one cold. This asks him to recall it directly instead, same
    db.record_vocabulary_review() call either way, so the Leitner schedule
    underneath means the same thing regardless of which review mode came
    before it.

    One word on screen at a time, not a whole board of them -- a wrong
    pick's reveal (the real definition, right there next to what he
    guessed) is the actual teaching moment, so it stays up until he clicks
    past it rather than auto-advancing to the next word.
    """
    today = date.today().isoformat()
    due = [entry for entry in db.vocabulary_due(student["id"], limit=25) if entry["definition"]]
    streak = st.session_state.setdefault("vocab_streak", 0)
    best_streak = st.session_state.setdefault("vocab_best_streak", 0)
    reviewed = st.session_state.setdefault("vocab_reviewed_count", 0)
    state = st.session_state.setdefault("vocab_quiz", {})
    # Answering a word moves its own next_review_on forward regardless of
    # right or wrong (see record_vocabulary_review), so it drops out of
    # `due` the instant he picks -- before he's even seen the reveal. A
    # mid-reveal word (picked is set, waiting on "Next word") has to keep
    # showing anyway, even once `due` no longer contains it or is empty.
    mid_reveal = state.get("picked") is not None

    st.markdown(_COMIC_PANEL_CSS, unsafe_allow_html=True)
    with st.container(key="comic_frame_vocab"):
        st.markdown(
            '<div class="comic-frame-title">🔤 Words to Review</div>', unsafe_allow_html=True
        )

        if not due and not mid_reveal:
            if reviewed:
                st.success(
                    f"🎉 All caught up! {reviewed} word(s) reviewed, best streak {best_streak}."
                )
                st.balloons()
            else:
                st.success("Nothing due for review today.")
            _render_vocab_done_button(db, student, today)
            return

        all_defined = [w for w in db.list_vocabulary(student["id"]) if w["definition"]]
        if len(all_defined) < VOCAB_QUIZ_MIN_DEFINED_WORDS and not mid_reveal:
            st.info(
                "Add a few more words (with definitions) from his reading before he can be "
                "quizzed on them."
            )
            _render_vocab_done_button(db, student, today)
            return

        if "word_id" not in state:
            word = due[0]
            decoy_pool = [w["definition"] for w in all_defined if w["id"] != word["id"]]
            random.shuffle(decoy_pool)
            choices = [word["definition"]] + decoy_pool[: VOCAB_QUIZ_CHOICES - 1]
            random.shuffle(choices)
            state.clear()
            state.update(word_id=word["id"], choices=choices, picked=None)

        word = next(w for w in all_defined if w["id"] == state["word_id"])

        with st.container(key=f"comic_panel_vocab_{word['id']}"):
            # No issue tag here, unlike the activity panels -- the metrics
            # row right below already shows the streak, and a badge
            # repeating the same number just above it read as duplicative
            # rather than styled.
            metrics = st.columns(3)
            metrics[0].metric("🔥 Streak", streak)
            metrics[1].metric("✅ Reviewed", reviewed)
            metrics[2].metric("Left today", len(due))

            st.markdown(f"## {md(word['word'].upper())}")

            if state["picked"] is None:
                st.caption("Which definition is correct?")
                for index, choice in enumerate(state["choices"]):
                    if st.button(
                        md(choice), key=f"vocab_choice_{word['id']}_{index}", width="stretch"
                    ):
                        correct = choice == word["definition"]
                        state["picked"] = choice
                        db.record_vocabulary_review(word["id"], correct=correct)
                        st.session_state["vocab_reviewed_count"] = reviewed + 1
                        if correct:
                            new_streak = streak + 1
                            st.session_state["vocab_streak"] = new_streak
                            st.session_state["vocab_best_streak"] = max(best_streak, new_streak)
                            if new_streak >= VOCAB_STREAK_ON_FIRE:
                                st.balloons()
                                st.toast(f"🚀 {new_streak} in a row — you're on fire!")
                            else:
                                st.toast(
                                    f"{random.choice(VOCAB_STREAK_HYPE)} 🔥 {new_streak} in a row"
                                )
                        else:
                            st.session_state["vocab_streak"] = 0
                            st.toast("❌ Not quite.")
                        st.rerun()
            else:
                for choice in state["choices"]:
                    if choice == word["definition"]:
                        st.success(f"✅ {md(choice)}")
                    elif choice == state["picked"]:
                        st.error(f"❌ {md(choice)} — your pick")
                    else:
                        st.write(md(choice))
                if st.button("Next word ▶️", type="primary", key="vocab_next_word"):
                    state.clear()
                    st.rerun()

        st.divider()
        _render_vocab_done_button(db, student, today)


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


# --- the first-day-of-school celebration ----------------------------------------

_FIRST_DAY_INK = theming.PRINTED_COMIC_INK
_FIRST_DAY_PAPER = theming.PRINTED_COMIC_COVER_PAPER
_FIRST_DAY_CARD_PAPER = theming.PRINTED_COMIC_PAPER
# Same four of the five "Sunday Funnies" week-grid colors (compass_week's own
# red, index 0, is reserved for the masthead's own shadow, below) -- just in
# blue/green/gold/purple order rather than Home's Mon-Fri order, to suit this
# feature's own blurb layout. Deliberately the same fixed printed-poster
# palette, not theme.py's own themed `Theme` tokens, same reasoning as that
# styling: a printed comic page doesn't re-theme itself for the room it's
# read in.
_FIRST_DAY_COLORS = (
    theming.PRINTED_COMIC_WEEKDAY_COLORS[2],
    theming.PRINTED_COMIC_WEEKDAY_COLORS[3],
    theming.PRINTED_COMIC_WEEKDAY_COLORS[1],
    theming.PRINTED_COMIC_WEEKDAY_COLORS[4],
)
_FIRST_DAY_WINDOW_DAYS = 14
_FIRST_DAY_CARD_CSS = f"""
<style>
div[class*="st-key-first_day_cover"] {{
  background: {_FIRST_DAY_PAPER};
  border: 4px solid {_FIRST_DAY_INK};
  border-radius: 4px;
  box-shadow: 10px 10px 0 0 {_FIRST_DAY_INK};
  padding: 28px 26px 20px;
  position: relative;
  margin: 4px 0 22px;
}}
div[class*="st-key-first_day_cover"]::before {{
  content: "";
  position: absolute;
  inset: 0;
  border-radius: 4px;
  pointer-events: none;
  opacity: .12;
  background-image: radial-gradient(circle, {_FIRST_DAY_INK} 1.6px, transparent 1.8px);
  background-size: 10px 10px;
}}
div[class*="st-key-first_day_blurb_"], div[class*="st-key-first_day_toc_"] {{
  background: {_FIRST_DAY_CARD_PAPER};
  border: 3px solid {_FIRST_DAY_INK};
  border-radius: 4px;
  padding: 10px 14px;
  box-shadow: 5px 5px 0 0 {_FIRST_DAY_INK};
  margin-bottom: 12px;
}}
</style>
"""


def render_first_day_celebration(db: Database, student: dict[str, Any]) -> bool:
    """A one-time "Issue #1" comic-cover celebration on the actual first day
    of the school year. Sampled three visual directions and picked this one
    before building -- matches the Week grid's own Sunday Funnies styling
    on purpose, same fixed printed palette rather than theme.py's tokens.

    Shown once: tracked by comparing this year's computed start date
    (school_year_bounds) against whichever start date was last celebrated,
    not by the literal calendar day, so opening the app a few days late
    still gets the moment instead of silently missing it forever -- as
    long as it's within _FIRST_DAY_WINDOW_DAYS of the real start. school_year_bounds
    always returns a start <= today (it's "the year containing today"), so
    that alone can't tell us whether the year *just* started or started
    months ago -- the window check is what actually gates this to "the
    first day" instead of "any day before it's dismissed."

    "See what's inside" flips to _render_first_day_contents -- a real table
    of contents (every Big Project, choice topic, life skill, and the travel
    log so far), tracked in st.session_state so it survives the rerun that
    button click causes. "Let's go!" dismisses from either side.

    Returns whether it actually rendered, so the caller can st.stop() --
    this is meant to be the whole page that render, not a banner stacked
    above the usual one.
    """
    year_start, _ = db.school_year_bounds()
    if db.get_setting("first_day_celebrated_start", "") == year_start:
        return False
    days_since_start = (date.today() - date.fromisoformat(year_start)).days
    if not (0 <= days_since_start < _FIRST_DAY_WINDOW_DAYS):
        return False

    if st.session_state.get("first_day_view") == "contents":
        _render_first_day_contents(db, student, year_start)
        return True

    first_name = student["name"].split()[0]
    book = db.current_book(student["id"])
    upcoming = db.upcoming_book(student["id"])
    project = db.active_big_project(student["id"])

    st.markdown(_FIRST_DAY_CARD_CSS, unsafe_allow_html=True)
    st.title("COMPASS")
    st.caption(f"A {md(student['name'])} Production")

    with st.container(key="first_day_cover"):
        st.markdown(
            f'<div style="font-weight:900; font-size:13px; letter-spacing:.05em; '
            f'color:{_FIRST_DAY_COLORS[0]};">ISSUE №1</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<div style="font-weight:900; font-size:44px; line-height:.95; '
            f'color:{_FIRST_DAY_INK}; text-shadow:3px 3px 0 #e14b3a; margin:2px 0 12px;">'
            "THE FIRST DAY!</div>",
            unsafe_allow_html=True,
        )
        st.markdown(
            f"**Grade {student['grade']} starts now, {first_name} — "
            "let's see what this year's made of.**"
        )

    blurbs: list[tuple[str, str, str]] = []
    if book:
        text = f"**{md(book['title'])}**"
        if upcoming:
            text += f" — with **{md(upcoming['title'])}** queued up for the second half."
        else:
            text += " — he's mid-book, and English picks up exactly where he left off."
        blurbs.append(("THIS ISSUE:", _FIRST_DAY_COLORS[0], text))
    if project:
        next_step = next(
            (s for s in db.list_project_steps(project["id"]) if s["active"] and not s["completed_on"]),
            None,
        )
        text = f"His **{md(project['title'])}**"
        text += (
            f" — {md(next_step['title'])}, whenever he's ready to dive in."
            if next_step
            else " — every step done so far!"
        )
        blurbs.append(("GUEST-STARRING:", _FIRST_DAY_COLORS[1], text))
    blurbs.append((
        "ALSO IN THIS ISSUE:",
        _FIRST_DAY_COLORS[2],
        "**Landon's Travels** — new stamps in the journal whenever the next trip happens.",
    ))
    blurbs.append((
        "NEXT ISSUE:",
        _FIRST_DAY_COLORS[3],
        "New worlds in Science, new eras in History, and Math's next level — all waiting.",
    ))

    columns = st.columns(2)
    for index, (eyebrow, color, text) in enumerate(blurbs):
        with columns[index % 2], st.container(key=f"first_day_blurb_{index}"):
            st.markdown(
                f'<div style="font-weight:900; font-size:12px; letter-spacing:.03em; '
                f'color:{color};">{eyebrow}</div>',
                unsafe_allow_html=True,
            )
            st.markdown(text)

    peek_col, go_col = st.columns(2)
    with peek_col:
        if st.button("📖 See what's inside →", key="first_day_peek", width="stretch"):
            st.session_state["first_day_view"] = "contents"
            st.rerun()
    with go_col:
        if st.button("Let's go! →", key="first_day_go", type="primary", width="stretch"):
            db.set_setting("first_day_celebrated_start", year_start)
            st.rerun()

    return True


def _render_first_day_contents(db: Database, student: dict[str, Any], year_start: str) -> None:
    """The "table of contents" flip side of the first-day cover -- real
    detail instead of counts: a from-the-parents note first (this is his
    first year of homeschooling, and what's expected of him), then
    literally every book ever added, no status filter at all (unlike
    current_book()/upcoming_book(), which are about picking *the one* the
    English agent reads from right now -- this is "what's on his list for
    the year," a different question, and internal reading-progress
    bookkeeping shouldn't hide a book from it), every Big Project with its
    actual objective, every choice topic and life skill with its
    description, and the travel log's real entries. Two explainer
    sections (Check-In, Morning Routine) carry no per-student data at all
    -- they exist purely so he knows what those two daily habits are and
    what's expected, since the rest of Home introduces them by name
    without ever spelling that out. Choice Topics, Life Skills, and Travel
    are explicitly labeled examples -- their content is either a starter
    catalog or just whatever's logged so far, not a fixed or complete
    assignment list, and the label is there so he doesn't mistake one for
    the other. Three more explainer sections (Where Everything Lives, How
    Your Lessons Work, How The Week Comes Together) round out the same
    "orient him to the app" job as Check-In/Morning Routine -- every other
    feature here got its own explainer, but the core daily subjects and
    the app's own shape never did until now. Reachable only from the
    cover's "See what's inside" button.
    """
    student_id = student["id"]
    books = db.list_books(student_id)
    # Excludes the automatic Travel Log project (see
    # Database.ensure_travel_log_project) -- it's not a pick among these in
    # the sense this table of contents means, and it's always there from
    # day one regardless of what's actually "on deck" for the year.
    projects = [
        p for p in db.list_big_projects(student_id)
        if not p["shelved"] and p["kind"] != "travel_log"
    ]
    active_project = db.active_big_project(student_id)
    choice_topics = [
        t for t in db.list_choice_topics(student_id) if t["status"] not in ("done", "declined")
    ]
    life_skills = [s for s in db.list_life_skills(student_id) if s["active"] and not s["completed_on"]]
    travel = db.list_travel_entries(student_id)

    st.markdown(_FIRST_DAY_CARD_CSS, unsafe_allow_html=True)
    st.title("COMPASS")
    st.caption("Inside This Issue")

    if st.button("← Back to the cover", key="first_day_back"):
        st.session_state["first_day_view"] = "cover"
        st.rerun()

    sections: list[tuple[str, str, str]] = []

    sections.append((
        "💛 FROM YOUR PARENTS",
        _FIRST_DAY_COLORS[3],
        "This is your first year of homeschooling. It's a big change — and we "
        "believe in you. This is going to be a great year.\n\n"
        "Here's what we're hoping for: **take your time** with each lesson, "
        "actually **read what's given to you**, and **give it your all**. Each "
        "lesson comes with explanations, examples, and videos built in — so if "
        "something doesn't click, check there first before getting stuck.\n\n"
        "Try your hardest. Grow. That's the whole goal this year.",
    ))

    sections.append((
        "🧭 WHERE EVERYTHING LIVES",
        _FIRST_DAY_COLORS[0],
        "Down the left side: **Math, Science, English,** and **History** are "
        "your daily subjects. **Choice Topics, Life Skills,** and **Big "
        "Projects** are yours to steer. **Check-In** and **Landon's Travels** "
        "round it out. **Home** is where your day actually starts — that's "
        "where everything shows up.",
    ))

    sections.append((
        "📖 HOW YOUR LESSONS WORK",
        _FIRST_DAY_COLORS[1],
        "Math, Science, English, and History each get their own lesson, built "
        "just for you — not a worksheet pulled from a textbook. Open the "
        "subject, read through it, and work through the activities. Some come "
        "with a video, some with practice problems, some with a project. Take "
        "your time, but take it seriously — this is the real work of the "
        "year.",
    ))

    sections.append((
        "🗓️ HOW THE WEEK COMES TOGETHER",
        _FIRST_DAY_COLORS[2],
        "Lessons don't appear out of nowhere — they get planned ahead of time "
        "and show up on **Home** when it's time for them. Some weeks "
        "everything's ready to go by Monday; other times a new one lands the "
        "night before. Either way, Home is where you check each morning to "
        "see what's next.",
    ))

    if books:
        term_notes = {
            "first_half": " — first half of the year",
            "second_half": " — second half of the year",
        }
        items = []
        for book in books:
            marker = "⭐ " if book["status"] == "reading" else ""
            byline = f" by {md(book['author'])}" if book["author"] else ""
            term_note = term_notes.get(book["term"], "")
            item = f"{marker}**{md(book['title'])}**{byline}{term_note}"
            if book["ai_summary"]:
                item += f"  \n{md(book['ai_summary'])}"
            items.append(item)
        text = "\n\n".join(items)
    else:
        text = "No book started yet — the first pick is still ahead."
    sections.append(("📚 THIS YEAR'S BOOKS", _FIRST_DAY_COLORS[0], text))

    if projects:
        items = []
        for project in projects:
            is_active = bool(active_project and project["id"] == active_project["id"])
            marker = "⭐ " if is_active else ""
            item = f"{marker}**{md(project['title'])}**"
            item += f"  \n{md(project['vision'])}" if project["vision"] else "  \nNo objective set yet."
            if is_active:
                steps = db.list_project_steps(project["id"])
                next_step = next((s for s in steps if s["active"] and not s["completed_on"]), None)
                if next_step:
                    item += f"  \nNext up: {md(next_step['title'])}"
            items.append(item)
        text = "\n\n".join(items)
    else:
        text = "Nothing picked yet — Big Projects is wide open."
    sections.append(("🎬 BIG PROJECTS ON DECK", _FIRST_DAY_COLORS[1], text))

    sections.append((
        "💬 CHECK-IN",
        _FIRST_DAY_COLORS[2],
        "Once a day, pick how you're feeling and add a note if you want to. "
        "**Your parents can read it** — no secrets, just an honest heads-up on how "
        "things are going. There's no wrong answer, and no grade on it either.",
    ))

    sections.append((
        "🧘 MORNING ROUTINE",
        _FIRST_DAY_COLORS[3],
        "A few minutes of stretching, breathing, or a quick mindfulness moment to "
        "start the day feeling good, before anything else. Pick whichever one "
        "sounds good that morning.",
    ))

    if choice_topics:
        items = ["*A few examples — see Choice Topics to add whatever you're curious about.*"]
        for topic in choice_topics[:6]:
            item = f"**{md(topic['title'])}**"
            if topic["description"]:
                item += f"  \n{md(topic['description'])}"
            items.append(item)
        text = "\n\n".join(items)
    else:
        text = "Nothing on deck yet — Choice Topics is wide open."
    sections.append(("⭐ THINGS HE WANTS TO LEARN (EXAMPLES)", _FIRST_DAY_COLORS[0], text))

    if life_skills:
        items = ["*A few examples from the catalog — see Life Skills for the whole list.*"]
        for skill in life_skills[:6]:
            item = f"**{md(skill['title'])}**"
            if skill["description"]:
                item += f"  \n{md(skill['description'])}"
            items.append(item)
        text = "\n\n".join(items)
    else:
        text = "None unlocked yet."
    sections.append(("🛠️ LIFE SKILLS UNLOCKED (EXAMPLES)", _FIRST_DAY_COLORS[1], text))

    if travel:
        items = ["*A few examples so far — see Landon's Travels for the whole log.*"]
        for entry in travel[:4]:
            item = f"**{md(entry['title'] or entry['state'])}** ({md(entry['state'])})"
            if entry["story"]:
                item += f"  \n{md(entry['story'])}"
            items.append(item)
        if len(travel) > 4:
            items.append(f"...and {len(travel) - 4} more stamped so far.")
        text = "\n\n".join(items)
    else:
        text = "No stamps yet — the first trip of the year starts the log."
    sections.append(("🗺️ LANDON'S TRAVELS SO FAR (EXAMPLES)", _FIRST_DAY_COLORS[2], text))

    for index, (eyebrow, color, text) in enumerate(sections):
        with st.container(key=f"first_day_toc_{index}"):
            st.markdown(
                f'<div style="font-weight:900; font-size:12px; letter-spacing:.03em; '
                f'color:{color};">{eyebrow}</div>',
                unsafe_allow_html=True,
            )
            st.markdown(text)

    if st.button("Let's go! →", key="first_day_go_from_toc", type="primary", width="stretch"):
        db.set_setting("first_day_celebrated_start", year_start)
        st.rerun()


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


def render_fun_fact() -> None:
    """Student view only -- a small reward for showing up, not a lesson.
    Same card styling as an st.info, so it reads as part of the page rather
    than an ad. Rotates daily; see fun_facts.fact_of_the_day for why that's
    deterministic rather than random."""
    st.info(f"🎲 **Fun fact of the day**\n\n{fun_facts.fact_of_the_day()}")


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


def render_xp_level(db: Database, student: dict[str, Any]) -> None:
    """His level bar -- everything he finishes turned into visible progress.
    A rank, a level number, and a fill toward the next level, computed live
    (see compass.xp) so it climbs the moment he finishes something. Student
    view only; pure motivation, not a grade."""
    state = xp_module.compute(db, student["id"])
    render_card_heading(f"🧭 Level {state.level} — {state.title}")
    st.progress(
        state.fraction,
        text=f"{state.total} XP · {state.to_next} to Level {state.level + 1}",
    )

    # The next real-world reward he's climbing toward, plus what he's already
    # unlocked -- the "movie night / sundae party" idea made concrete. Parent
    # delivers it (and can edit the whole list -- see render_xp_reward_editor);
    # the app just tracks the milestones.
    ladder = xp_module.reward_ladder(db)
    given = xp_module.given_thresholds(db)
    rewards = xp_module.rewards_for_total(state.total, ladder, given)
    upcoming = xp_module.next_reward(state.total, ladder)
    if upcoming is not None:
        to_go = upcoming.threshold - state.total
        st.caption(
            f"🎁 Next reward: {upcoming.emoji} **{md(upcoming.name)}** — {to_go} XP to go"
        )
    else:
        st.caption("🏆 You've earned every reward — legend.")
    # Earned-but-not-given reads as a win he can act on ("go ask!"), not a dim,
    # disabled-looking line -- reported: "it says unlocked, but its greyed out."
    # Given ones are the quiet, already-happened list.
    to_claim = [r for r in rewards if r.earned_unclaimed]
    claimed = [r for r in rewards if r.given]
    if to_claim:
        line = " · ".join(f"{r.emoji} {md(r.name)}" for r in to_claim)
        st.success(f"🎉 Earned — go ask a parent to claim: {line}")
    if claimed:
        st.caption("✅ Already got: " + " · ".join(f"{r.emoji} {md(r.name)}" for r in claimed))

    # The one thing that costs XP -- shown only when it's actually happened, and
    # kept factual rather than scolding.
    penalty = xp_module.sent_back_penalty(db, student["id"])
    if penalty:
        st.caption(
            f"↩️ −{penalty} XP from lessons sent back — nail it the first time to keep them."
        )

    # How the score actually works, spelled out for him -- reported directly:
    # "we ned to tell landon how the xp works. assignments turned back to him
    # hurt his score." Built from the same config knobs the scoring uses, so the
    # numbers here can never drift from what he actually earns and loses.
    with st.expander("ℹ️ How XP works"):
        st.markdown(
            "**Earn XP for finishing stuff:**\n"
            f"- ✅ Finish a lesson: **+{config.XP_PER_LESSON}**\n"
            f"- 🧠 Pass a quiz: **+{config.XP_QUIZ_PASS_BONUS}**\n"
            f"- 📐 Master a math skill: **+{config.XP_PER_MASTERED_SKILL}**\n"
            f"- 🛠️ Life skill or 💻 coding module: **+{config.XP_PER_LIFE_SKILL}** each\n"
            f"- ⭐ A Student's Choice topic: **+{config.XP_PER_CHOICE_TOPIC}**\n"
            f"- 🧭 Write up a trip: **+{config.XP_PER_TRAVEL_ENTRY}**\n\n"
            "**The one thing that costs XP:**\n"
            f"- ↩️ Every time a lesson gets **sent back** for a redo: "
            f"**−{config.XP_SENT_BACK_PENALTY}** (each time). Read the whole "
            "assignment and do every part the first time, and you never lose any.\n\n"
            "Your XP fills the bar toward the next **level**, and hitting XP "
            "milestones unlocks **rewards** — the next one's shown right above."
        )


def render_earned_rewards(db: Database, student: dict[str, Any]) -> None:
    """Parent-only: the reward alert the parent actually needs. Reported: "i
    need to know as the parent when he hits one." His XP crossing a reward
    threshold is computed live, but nothing told the parent -- so this surfaces
    every reward he's **earned but not yet been given**, each with a button to
    mark it handed over. Absent entirely when there's nothing to deliver, so it
    reads as a notification, not another always-on panel."""
    state = xp_module.compute(db, student["id"])
    ladder = xp_module.reward_ladder(db)
    given = xp_module.given_thresholds(db)
    rewards = xp_module.rewards_for_total(state.total, ladder, given)
    to_deliver = [r for r in rewards if r.earned_unclaimed]
    already_given = [r for r in rewards if r.given]

    name = student.get("name") or "He"
    if to_deliver:
        with st.container(border=True, key="parent_earned_rewards"):
            count = len(to_deliver)
            st.markdown(
                f"### 🎁 {md(name)} earned {count} reward{'s' if count != 1 else ''} — time to deliver"
            )
            st.caption(
                "He hit the XP milestone for these. Hand it over in real life, "
                "then mark it given so it clears from here and shows as claimed "
                "on his screen."
            )
            for reward in to_deliver:
                cols = st.columns([4, 2])
                cols[0].markdown(
                    f"{reward.emoji} **{md(reward.name)}**  \n"
                    f"<span style='color:var(--c-dim); font-size:12px;'>"
                    f"earned at {reward.threshold} XP</span>",
                    unsafe_allow_html=True,
                )
                if cols[1].button(
                    "✅ Mark as given", key=f"reward_given_{reward.threshold}", width="stretch"
                ):
                    xp_module.set_reward_given(db, reward.threshold, True)
                    st.rerun()

    if already_given:
        line = " · ".join(f"{r.emoji} {md(r.name)}" for r in already_given)
        st.caption(f"✅ Already given: {line}")
        # An undo, tucked away, in case one was marked by mistake.
        with st.expander("Undo a 'given'"):
            for reward in already_given:
                if st.button(
                    f"↩️ Un-give {reward.emoji} {md(reward.name)}",
                    key=f"reward_ungive_{reward.threshold}",
                ):
                    xp_module.set_reward_given(db, reward.threshold, False)
                    st.rerun()

    if not to_deliver:
        upcoming = xp_module.next_reward(state.total, ladder)
        if upcoming is not None:
            to_go = upcoming.threshold - state.total
            st.caption(
                f"🎯 Nothing to hand over right now — next up is "
                f"{upcoming.emoji} **{md(upcoming.name)}** at {upcoming.threshold} XP "
                f"({to_go} to go)."
            )


def render_xp_reward_editor(db: Database) -> None:
    """Parent-only: edit the ladder of XP rewards he unlocks -- reported
    directly: "parent also needs ability to edit, adjust list of xp rewards."
    A live table (add/remove rows) over `xp.reward_ladder`; Save writes the
    `xp_rewards` setting, Reset clears back to the config defaults. The student
    XP card reads the same ladder, so a change here is what he sees next load."""
    ladder = xp_module.reward_ladder(db)
    st.caption(
        "The milestones he unlocks as his XP climbs. Edit the numbers and names, "
        "add or delete rows, then Save. The app tracks when he's earned one — you "
        "decide when to actually make it happen."
    )
    rows = [{"XP needed": t, "Emoji": e, "Reward": n} for t, n, e in ladder]
    edited = st.data_editor(
        rows,
        num_rows="dynamic",
        hide_index=True,
        key="xp_reward_editor",
        column_config={
            "XP needed": st.column_config.NumberColumn(min_value=0, step=10),
            "Emoji": st.column_config.TextColumn(width="small"),
            "Reward": st.column_config.TextColumn(width="large"),
        },
    )
    save_col, reset_col = st.columns(2)
    if save_col.button("Save rewards", type="primary", key="save_xp_rewards"):
        xp_module.set_reward_ladder(
            db,
            [
                {
                    "threshold": row.get("XP needed"),
                    "name": row.get("Reward"),
                    "emoji": row.get("Emoji"),
                }
                for row in edited
            ],
        )
        st.success("Rewards saved.")
        st.rerun()
    if reset_col.button("Reset to defaults", key="reset_xp_rewards"):
        db.set_setting("xp_rewards", "")
        st.rerun()


def render_week_progress(db: Database, student: dict[str, Any]) -> None:
    """A small fuel gauge for the week: how many of this week's planned lessons
    he's finished. Effort made visible -- reported wish: "little things ... to
    make this fun." Reads his own `student_done_on` signal, so it fills in the
    moment he finishes something, never waiting on a parent to log hours. Shown
    only once there's actually a plan for the week (nothing to gauge otherwise).
    """
    week_start = weekly.week_start()
    week_lessons = weekly.latest_per_day(
        db.lessons_for_week(student["id"], week_start.isoformat())
    )
    total = len(week_lessons)
    if not total:
        return
    done = sum(
        1 for lesson in week_lessons
        if (lesson.get("metadata") or {}).get("student_done_on")
    )
    fraction = done / total
    if done >= total:
        label = f"🏁 All {total} lessons done this week — you crushed it!"
    else:
        label = f"⚡ {done} of {total} lessons done this week — keep it rolling!"
    st.progress(fraction, text=label)


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
