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
from typing import Any

import streamlit as st

from compass import (
    auth,
    config,
    fun_facts,
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
from compass.agents import writing_review
from compass.agents.quiz import grade, passed as quiz_passes, select_questions
from compass.compliance import declaration_status
from compass.export import lesson_to_docx, suggested_filename
from compass.morning_routines import MORNING_ROUTINES, routine_for_date
from compass.storage.db import Database
from compass.writing_checks import check_writing


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
    # Before anything renders, so the page never flashes unstyled.
    st.markdown(theming.css(), unsafe_allow_html=True)
    _sidebar(db, student)
    return db, student


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


def _sidebar(db: Database, student: dict[str, Any]) -> None:
    with st.sidebar:
        st.markdown(f"### 🧭 Compass\n**{md(student['name'])}** · Grade {student['grade']}")
        start, end = db.school_year_bounds()
        st.caption(f"School year {start} → {end}")
        _profile_control(db, student)
        st.divider()
        _mode_control(db)
    _hide_parent_only_nav()


# Pages that are entirely parent admin -- record-keeping, settings, spend --
# rather than something he does. Each already gates its own content behind
# parent_only(), so hiding the tab is UX cleanup on top of that, not the only
# thing standing between him and it: typing the URL directly still hits the
# same PIN gate the tab would have.
_PARENT_ONLY_PAGES = (
    "Activity_Log",
    "Compliance",
    "Student_Profile",
    "Courses",
    "This_Week",
    "Model_Costs",
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
        /* Once the pages above are hidden, the ones left over fit without
        Streamlit's "View N more" collapse -- toggling it would just open onto
        empty space, so it goes too rather than becoming a dead click. */
        [data-testid="stSidebarNavViewButton"] {{ display: none !important; }}
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
    with st.expander("Parent unlock"):
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
            "or remove the old one from Activity Log → To review."
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

    st.divider()
    for warning in generated.warnings:
        st.caption(f"⚠️ {warning}")
    render_lesson(generated.payload)
    st.download_button(
        "📄 Download as Word doc",
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


def _comic_kind_pill_html(kind: str) -> str:
    variant = _COMIC_KIND_PILL_VARIANT.get(kind, "neutral")
    icon = _COMIC_KIND_ICONS.get(kind, "📌")
    label = html.escape(kind or "activity")
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
) -> None:
    """The inside of one activity: video, worked example, instructions, and
    (when it applies) the typed-response box. Shared by both the plain
    expander layout and the comic-panel layout so the two never drift apart."""
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

    if _needs_written_response(activity):
        saved = ((metadata or {}).get("writing_responses") or {}).get(str(index), "")
        if not parent and db is not None and lesson_id is not None:
            review = ((metadata or {}).get("writing_review") or {}).get(str(index), {})
            status = review.get("status", config.WRITING_DRAFT)

            if status == config.WRITING_APPROVED:
                st.success("✅ Your parent approved this one.")
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
            response = st.text_area(
                "Your response",
                value=st.session_state.get(draft_key, saved),
                height=160,
                key=draft_key,
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
            if submit_col.button(
                "Submit for review", key=f"submit_writing_{lesson_id}_{index}", type="primary"
            ):
                problems = check_writing(response, activity.get("writing_requirements"))
                if problems:
                    for problem in problems:
                        st.error(problem)
                else:
                    db.save_writing_response(lesson_id, index, response)
                    db.set_writing_review(lesson_id, index, config.WRITING_SUBMITTED)
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
            f"{_comic_kind_pill_html(activity.get('kind', ''))}",
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

        if activities:
            st.markdown("**Activities**")
            for index, activity in enumerate(activities, start=1):
                header = (
                    f"{index}. {md(activity.get('title', 'Activity'))} · "
                    f"{activity.get('kind', '')} · {activity.get('minutes', 0)} min"
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
    if assessment and parent:
        st.markdown("**Assessment**")
        st.caption(
            "A check you run with him after the lesson -- separate from the "
            "on-screen quiz below, which he takes and grades himself. Use "
            "this to actually confirm he's got it, not just that he sat "
            "through the lesson."
        )
        st.markdown(f"*{md(assessment.get('kind', ''))}* — {md(assessment.get('description', ''))}")
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
                st.session_state[state_key] = {
                    "picks": picks,
                    "correct": correct,
                    "duration_seconds": duration_seconds,
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
                db.record_quiz_result(
                    lesson_id, student["id"], correct, total, did_pass,
                    detail=detail, duration_seconds=duration_seconds,
                )

                skill_id = metadata.get("skill_id")
                if skill_id:
                    mastery_threshold = db.get_int_setting("math_mastery_percent")
                    if quiz_passes(correct, total, mastery_threshold):
                        db.set_mastery(
                            student["id"],
                            skill_id,
                            "mastered",
                            score=100 * correct / total,
                            notes="Auto-graded from the in-app quiz.",
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
            if st.button(retry_label, key=f"quiz_retry_{lesson_id}"):
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


def render_assessment_card(
    db: Database, student: dict[str, Any], lesson: dict[str, Any], key_prefix: str
) -> None:
    """The parent's digital check on a lesson -- right where hours get
    logged (Activity Log's own review card), not a separate page hop and a
    re-type. Math (a `skill_id` in metadata) gets a plain approve/not-yet
    decision -- "Approve" writes status="mastered" (unlocking the next
    skill) at whatever score he actually got, "Not yet" writes
    status="in_progress"; every other agent gets a lighter three-way call
    since there's no mastery graph to gate. This is deliberately not the
    same not_started/in_progress/mastered dropdown Math -> Record mastery
    offers -- that page is a general "set any skill's status anytime" tool,
    while this card is answering one narrow question about one specific
    attempt, and a bare status picker sitting right under a caption saying
    "mastery needs 100%" read like the parent wasn't allowed to approve
    anything less, when the real rule is the quiz's own auto-approval, not
    a ceiling on what a parent can decide by hand. Either way, any writing
    response he's saved (see render_lesson's own writing-activity handling)
    shows first, since that's usually the actual evidence the check is
    based on.

    Renders nothing at all for a lesson with no assessment, no skill_id,
    and no writing activity -- most Life Skills/Choice lessons, say.

    The actual decision (mastery, the 5-band verdict, a writing activity's
    approve/bounce) only opens up once `lesson["status"] == "submitted"` --
    he has to turn the whole lesson in first. Approving folds in logging
    the hours in the same click (see _log_hours_for_lesson), since that's
    the same act now: approved *is* completed. Sending anything back sets
    the lesson to "needs_revision" and reopens it to him (see
    student_lesson_view), with no hours logged until he resubmits and it's
    approved for real.
    """
    payload = lesson["payload"]
    metadata = lesson.get("metadata") or {}
    assessment = payload.get("assessment") or {}
    skill_id = metadata.get("skill_id")
    writing_activities = [
        (index, activity)
        for index, activity in enumerate(payload.get("activities") or [])
        if _needs_written_response(activity)
    ]

    # Reading-check results count as something to show: a lesson that's only
    # "read these chapters" has no assessment, no skill, and nothing typed,
    # but whether the reading happened is exactly what a parent opens this
    # card to find out.
    reading_checks = metadata.get("reading_checks") or {}
    if not assessment and not skill_id and not writing_activities and not reading_checks:
        return

    st.markdown("**Assessment**")
    if assessment.get("description"):
        st.caption(f"*{md(assessment.get('kind', ''))}* — {md(assessment['description'])}")
    if assessment.get("mastery_criteria"):
        st.caption(f"Counts as mastered when: {md(assessment['mastery_criteria'])}")

    # Whether the reading actually happened, before any judgment about what
    # he wrote about it -- a thin response to a chapter he skimmed is a
    # different problem from a thin response to one he read.
    for activity_index, activity in enumerate(payload.get("activities") or []):
        stored = reading_checks.get(str(activity_index))
        if not stored:
            continue
        correct, total = stored.get("correct", 0), stored.get("total", 0)
        label = f"📖 Reading check — {md(activity.get('title', 'Reading'))}: {correct}/{total}"
        if total and correct == total:
            st.caption(f"{label} ✅")
        else:
            st.warning(f"{label} — worth asking whether he actually did the reading.")

    responses = metadata.get("writing_responses") or {}
    review_map = metadata.get("writing_review") or {}
    for index, activity in writing_activities:
        text = responses.get(str(index), "")
        review = review_map.get(str(index), {})
        status = review.get("status", config.WRITING_DRAFT)

        st.markdown(f"*His response — {md(activity.get('title', 'Writing'))}*")
        if text:
            st.write(md(text))
        else:
            st.caption("He hasn't written a response yet.")
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
                if not any(
                    ai_review.get(k) for k in ("concerns", "missing", "strengths")
                ):
                    st.caption("Nothing flagged.")
                st.caption(
                    "Advisory only, and it can be wrong -- it never approves "
                    "anything on its own."
                )

        if status == config.WRITING_APPROVED:
            st.success("✅ Approved.")
        elif status == config.WRITING_NEEDS_REVISION:
            history = _feedback_history(
                review, history_key="feedback_history", single_key="feedback"
            )
            if len(history) <= 1:
                st.warning(
                    "↩️ Sent back for revision"
                    + (f": {md(history[0])}" if history else ".")
                )
            else:
                st.warning("↩️ Sent back for revision — every note you've given so far:")
                for note in history:
                    st.markdown(f"- {md(note)}")
        elif status == config.WRITING_SUBMITTED and lesson["status"] == "submitted":
            st.info("⏳ He's submitted this — awaiting your review.")
            review_key = f"{key_prefix}_writing_review_{lesson['id']}_{index}"
            with st.form(review_key):
                feedback = st.text_area(
                    "Feedback (shown to him if you send it back)", key=f"{review_key}_feedback"
                )
                approve_col, bounce_col = st.columns(2)
                approve = approve_col.form_submit_button("✅ Approve", type="primary")
                bounce = bounce_col.form_submit_button("↩️ Send back for revision")
            if approve:
                db.set_writing_review(lesson["id"], index, config.WRITING_APPROVED)
                st.rerun()
            elif bounce:
                db.set_writing_review(
                    lesson["id"], index, config.WRITING_NEEDS_REVISION, feedback
                )
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

    # The lesson-wide decision (mastery, or the 5-band verdict) waits for
    # every writing activity to be individually approved first -- grading
    # the whole lesson while a piece of it still has its own pending
    # approve/bounce call would put two "send it back" buttons on the
    # screen for the same lesson at once.
    writing_all_approved = all(
        (review_map.get(str(index)) or {}).get("status") == config.WRITING_APPROVED
        for index, _ in writing_activities
    )

    if skill_id:
        current = db.mastery_map(student["id"]).get(skill_id, {})
        quiz_result = metadata.get("quiz_result") or {}
        latest_score = (
            round(100 * quiz_result["correct"] / quiz_result["total"])
            if quiz_result.get("total")
            else current.get("score")
        )
        if current.get("status") == "mastered":
            st.success(f"✅ Already approved — mastered at {current.get('score') or '?'}%.")
        st.caption(
            "The quiz only auto-approves a perfect score -- you decide here, at any "
            "score, whether that's good enough to move on."
        )
        # The decision only opens up once he's actually turned the lesson
        # in -- a lesson still in progress or already sent back has nothing
        # new for a parent to act on yet (see student_lesson_view for the
        # other side of this gate) -- and once any writing activity in it
        # has been approved on its own.
        if lesson["status"] == "submitted" and writing_all_approved:
            with st.form(f"{key_prefix}_assess_{lesson['id']}"):
                notes = st.text_area("Notes (optional)", value=current.get("notes", ""))
                feedback = st.text_area(
                    "Feedback (shown to him if you send it back for more practice)"
                )
                minutes, where, credits = _hours_inputs(
                    lesson["payload"], f"{key_prefix}_hrs_{lesson['id']}"
                )
                approve_col, practice_col = st.columns(2)
                approve = approve_col.form_submit_button(
                    "✅ Approve & log hours", type="primary"
                )
                keep_practicing = practice_col.form_submit_button(
                    "🔁 Not yet — send back for more practice"
                )
            if approve:
                db.set_mastery(
                    student["id"], skill_id, "mastered", score=latest_score, notes=notes
                )
                _log_hours_for_lesson(
                    db, student, lesson, minutes=minutes, location=where, credits=credits
                )
                st.success("Approved and logged — the next skill is unlocked.")
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
                approve = approve_col.form_submit_button(
                    "✅ Approve & log hours", type="primary"
                )
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
        elif len(history) == 1:
            st.warning(f"↩️ Sent back: {md(history[0])}")
        elif history:
            st.warning(
                "↩️ Sent back — everything your parent has flagged so far:\n\n"
                + "\n".join(f"- {md(note)}" for note in history)
            )
        else:
            st.warning("↩️ Sent back — check below for what to fix.")
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

SUBJECT_ICONS = {"math": "📐", "science": "🔬", "english": "📖", "history": "🏛️"}

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
        "pages/5_Choice_Topics.py", "Choice Topics",
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
    next_step = next(
        (s for s in db.list_project_steps(active["id"]) if not s["completed_on"]),
        None,
    )
    if next_step:
        return f"{md(active['title'])} — {md(next_step['title'])}"
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
        st.caption(
            "No grades yet — they'll show up here once there are quizzes and "
            "assignments to average."
        )
        return

    columns = st.columns(len(subject_grades))
    for column, grade in zip(columns, subject_grades):
        label = gradebook.AGENT_LABELS.get(grade.subject, grade.subject.title())
        icon = SUBJECT_ICONS.get(grade.subject, "📘")
        with column:
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

    for grade in subject_grades:
        if not grade.graded:
            continue
        label = gradebook.AGENT_LABELS.get(grade.subject, grade.subject.title())
        heading = (
            f"What makes up the {label} grade"
            if for_parent
            else f"What makes up your {label} grade"
        )
        with st.expander(heading):
            for component in grade.components:
                st.markdown(
                    f"- **{component.label}** — {component.percent:.0f}% "
                    f"·  {component.weight}% of the grade  \n"
                    f"  <span style='color:var(--c-dim); font-size:12px;'>"
                    f"{html.escape(component.detail)}</span>",
                    unsafe_allow_html=True,
                )
            if for_parent:
                st.caption(
                    "Weights are settings — `grade_weights_"
                    f"{grade.subject}` on the Student Profile page."
                )


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
  border-radius: 4px;
  padding: 10px 16px 8px;
  position: relative;
  box-shadow: 5px 5px 0 0 {_STREAK_BURST_INK};
  transform: rotate(-1deg);
  margin-bottom: 4px;
}}
div[class*="st-key-streak_milestone_burst"]::before {{
  content: "";
  position: absolute;
  inset: 0;
  border-radius: 4px;
  pointer-events: none;
  opacity: .14;
  background-image: radial-gradient(circle, {_STREAK_BURST_INK} 1.6px, transparent 1.8px);
  background-size: 9px 9px;
}}
</style>
"""


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
        return

    best = weekly.best_streak(active, planned_days=planned_days, planned_weeks=planned_weeks)
    today_done = date.today().isoformat() in active

    if today_done and streak in _STREAK_MILESTONES:
        st.markdown(_STREAK_BURST_CSS, unsafe_allow_html=True)
        with st.container(key="streak_milestone_burst"):
            st.markdown(
                f'<div style="font-weight:900; font-size:11px; letter-spacing:.06em; '
                f'color:{_STREAK_BURST_POP};">MILESTONE!</div>'
                f'<div style="font-weight:900; font-size:22px; line-height:1.05; '
                f'color:{_STREAK_BURST_INK};">🎉 {streak} DAYS IN A ROW</div>',
                unsafe_allow_html=True,
            )
            if streak >= best:
                st.caption("A new personal best.")
    else:
        plural = "s" if streak != 1 else ""
        line = f"🔥 **{streak} school day{plural} in a row**"
        if best > streak:
            line += f" · best: {best}"
        if not today_done:
            line += "  \nFinish something today to keep it alive."
        st.success(line)

    next_milestone = next((m for m in _STREAK_MILESTONES if m > streak), None)
    if next_milestone:
        st.progress(
            streak / next_milestone,
            text=f"{next_milestone - streak} more to reach {next_milestone}",
        )


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

    st.markdown("### 🧘 Morning Routine")
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
</style>
"""


def render_life_skill_cards(db: Database, skills: list[dict[str, Any]], can_edit: bool) -> None:
    """The checklist itself -- a grid of cards, one per skill, grouped by
    category. Every card always shows its own story: what the skill is and
    what it takes to finish. A checkbox is the only thing that changes
    `completed_on`; check it and the card itself turns gold, no separate
    view to open first.

    Takes the *full* catalog, not a pre-filtered list -- visibility is this
    function's own rule, not every caller's to remember: a skill shows only
    if it's `active` (unlocked from *Master list*) or already `completed_on`.
    An earned skill stays visible even if a parent re-locks it later; taking
    away an already-shown badge is a worse experience than an inactive skill
    just never appearing yet.

    `can_edit` gates the remove button -- a management action, same tier as
    *Add a skill*. Marking a skill done is deliberately not gated: the
    original checkbox let either of you check one off, and this keeps that
    same parity rather than quietly taking it away from him.
    """
    skills = [s for s in skills if s["active"] or s["completed_on"]]
    if not skills:
        return

    st.markdown(_LIFE_SKILL_CARD_CSS, unsafe_allow_html=True)

    by_category: dict[str, list[dict[str, Any]]] = {}
    for skill in skills:
        by_category.setdefault(skill["category"], []).append(skill)
    done = sum(1 for s in skills if s["completed_on"])
    st.markdown(
        f'<div class="cp-ls-tallybar">🥇 <span class="cp-ls-tally">{done} / {len(skills)} earned</span></div>',
        unsafe_allow_html=True,
    )

    for category, items in by_category.items():
        icon = LIFE_SKILL_CATEGORY_ICONS.get(category, LIFE_SKILL_DEFAULT_ICON)
        complete = sum(1 for i in items if i["completed_on"])
        st.subheader(f"{category} — {complete}/{len(items)}")

        for row_start in range(0, len(items), LIFE_SKILL_CARDS_PER_ROW):
            row = items[row_start : row_start + LIFE_SKILL_CARDS_PER_ROW]
            columns = st.columns(LIFE_SKILL_CARDS_PER_ROW)
            for index, skill in enumerate(row):
                earned = bool(skill["completed_on"])
                state = "earned" if earned else "locked"
                with columns[index], st.container(key=f"ls_card_{skill['id']}_{state}"):
                    story = html.escape(skill["description"]) if skill["description"] else "No mission notes yet."
                    needs = (
                        f'<div class="cp-ls-needs"><b>You\'ll need:</b> {html.escape(skill["materials"])}</div>'
                        if skill["materials"]
                        else ""
                    )
                    st.markdown(
                        f'<div class="cp-ls-seal">{icon}</div>'
                        f'<div class="cp-ls-title">{html.escape(skill["title"])}</div>'
                        f'<div class="cp-ls-cat">{html.escape(category)}</div>'
                        f'<div class="cp-ls-story">{story}</div>'
                        f"{needs}",
                        unsafe_allow_html=True,
                    )
                    checked = st.checkbox(
                        f"Earned {skill['completed_on']}" if earned else "Mark done",
                        value=earned,
                        key=f"ls_done_{skill['id']}",
                    )
                    if checked != earned:
                        db.set_life_skill_done(skill["id"], checked)
                        st.rerun()
                    if can_edit and st.button("🗑️ Remove", key=f"ls_remove_{skill['id']}"):
                        db.delete_life_skill(skill["id"])
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
            with st.expander(f"{skill['title']} — {status}"):
                columns = st.columns([5, 1])
                if skill["description"]:
                    columns[0].markdown(f"**The mission:** {skill['description']}")
                if skill["materials"]:
                    columns[0].caption(f"You'll need: {skill['materials']}")
                columns[0].caption(f"Credits toward {subjects.label(skill['credit_subject'])}")
                if skill["completed_on"]:
                    columns[0].caption(f"✅ Earned {skill['completed_on']}")
                active = columns[1].checkbox(
                    "Unlocked", value=bool(skill["active"]), key=f"ls_active_{skill['id']}"
                )
                if active != bool(skill["active"]):
                    db.set_life_skill_active(skill["id"], active)
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
            (s for s in db.list_project_steps(project["id"]) if not s["completed_on"]), None
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
    projects = [p for p in db.list_big_projects(student_id) if not p["shelved"]]
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
                next_step = next((s for s in steps if not s["completed_on"]), None)
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


def render_fun_fact() -> None:
    """Student view only -- a small reward for showing up, not a lesson.
    Same card styling as an st.info, so it reads as part of the page rather
    than an ad. Rotates daily; see fun_facts.fact_of_the_day for why that's
    deterministic rather than random."""
    st.info(f"🎲 **Fun fact of the day**\n\n{fun_facts.fact_of_the_day()}")


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
