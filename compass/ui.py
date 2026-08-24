"""Streamlit helpers shared across pages.

Kept out of `compass/` core modules on purpose — the agents, storage, and
compliance layers know nothing about Streamlit, so they stay testable and
reusable if the UI is ever replaced.
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

from compass import auth, config, fun_facts, subjects, theme as theming
from compass.backup import auto_snapshot
from compass.agents import (
    GeneratedLesson,
    LessonAgent,
    LessonGenerationError,
    StudentContext,
)
from compass.agents.quiz import grade, passed as quiz_passes
from compass.compliance import declaration_status
from compass.export import lesson_to_docx, suggested_filename
from compass.morning_routines import MORNING_ROUTINES, routine_for_date
from compass.school_calendar import days_until, next_annual_date
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
        st.markdown(f"### 🧭 Compass\n**{student['name']}** · Grade {student['grade']}")
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
        if lesson["status"] == "planned" and (not current or lesson["id"] != current.lesson_id)
    ]
    if pending:
        st.warning(
            f"⚠️ **{pending[0]['title']}** is already generated and unlogged for this "
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


def render_lesson(lesson: dict[str, Any], for_parent: bool | None = None) -> None:
    """Render a lesson. In student view the answer key never reaches the page.

    The redaction happens here rather than in a CSS class or an expander, because
    anything sent to the browser can be read out of it. What a student must not
    see is simply not written.
    """
    parent = is_parent() if for_parent is None else for_parent

    st.subheader(md(lesson.get("title", "Lesson")))
    if lesson.get("overview"):
        st.write(md(lesson["overview"]))

    objectives = lesson.get("learning_objectives") or []
    if objectives:
        st.markdown("**Learning objectives**")
        for objective in objectives:
            st.markdown(f"- {md(objective)}")

    # Materials before activities on purpose -- knowing what you need is part
    # of being set up to start, not a footnote to read after being told what
    # to do.
    materials = lesson.get("materials") or []
    if materials:
        st.markdown("**Materials**")
        for item in materials:
            st.markdown(f"- {md(item)}")

    activities = lesson.get("activities") or []
    if activities:
        st.markdown("**Activities**")
        for index, activity in enumerate(activities, start=1):
            header = (
                f"{index}. {md(activity.get('title', 'Activity'))} · "
                f"{activity.get('kind', '')} · {activity.get('minutes', 0)} min"
            )
            with st.expander(header, expanded=False):
                # Video first, if this specific activity has one -- watch it
                # explained before reading the worked example, same "entry
                # into the lesson before the activity itself" reasoning as
                # materials, just scoped to the one activity it actually
                # matches instead of the lesson as a whole. Shown to both
                # views: verified against a real search result and
                # restricted to YouTube (see compass/agents/video.py) before
                # it ever gets this far, so there's nothing here for the
                # student's version to redact.
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
                    # A worked example, shown before the instructions -- see
                    # the move modeled once before being asked to do it,
                    # same "I do, you do" order a teacher would use. Raw HTML
                    # via unsafe_allow_html isn't run through Streamlit's
                    # markdown/LaTeX pass, so this one doesn't need `md()` --
                    # html.escape already makes it safe on its own terms.
                    st.markdown(
                        f'<div style="background:var(--c-panel); border-left:3px solid '
                        f'var(--c-alt); border-radius:var(--c-radius); padding:10px 14px; '
                        f'margin-bottom:10px; font-size:13.5px;">'
                        f'<b>📖 Here\'s how:</b><br>{html.escape(example).replace(chr(10), "<br>")}'
                        f"</div>",
                        unsafe_allow_html=True,
                    )
                st.write(md(activity.get("instructions", "")))

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
    elif assessment:
        st.markdown("**Assessment**")
        st.caption(
            "There's a check at the end of this lesson — your parent has it."
        )

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
        st.balloons()


def render_quiz(
    db: Database,
    student: dict[str, Any],
    lesson_id: int,
    metadata: dict[str, Any],
    quiz: list[dict[str, Any]],
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
    """
    if not quiz:
        return

    state_key = f"quiz_result_{lesson_id}"
    result = st.session_state.get(state_key)

    st.divider()
    st.markdown("### 📝 Check your understanding")

    with st.container(key=f"quiz_nocopy_{lesson_id}"):
        st.markdown(
            f"<style>.st-key-quiz_nocopy_{lesson_id} "
            "{ -webkit-user-select: none; user-select: none; }</style>",
            unsafe_allow_html=True,
        )

        if result is None:
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
            st.session_state[state_key] = {"picks": picks, "correct": correct}
            db.record_quiz_result(lesson_id, correct, total, did_pass)

            skill_id = metadata.get("skill_id")
            if did_pass and skill_id:
                db.set_mastery(
                    student["id"],
                    skill_id,
                    "mastered",
                    score=100 * correct / total,
                    notes="Auto-graded from the in-app quiz.",
                )
            st.rerun()
            return

        picks = result["picks"]
        correct, total = result["correct"], len(quiz)
        threshold = db.get_int_setting("quiz_pass_percent")
        did_pass = quiz_passes(correct, total, threshold)
        pct = round(100 * correct / total)
        if did_pass:
            st.success(f"**{correct} / {total} correct ({pct}%)** — nice work.")
            if metadata.get("skill_id"):
                st.caption("Counted toward mastery of this skill.")
        else:
            st.warning(
                f"**{correct} / {total} correct ({pct}%)** — under the "
                f"{threshold}% needed to pass. Ask your parent about another go."
            )

        for index, item in enumerate(quiz):
            pick = picks[index]
            right = pick == item["correct_index"]
            marker = "✅" if right else "❌"
            with st.expander(f"{marker} {index + 1}. {md(item['question'])}", expanded=False):
                for choice_index, choice in enumerate(item["choices"]):
                    tag = ""
                    if choice_index == item["correct_index"]:
                        tag = " — correct answer"
                    elif choice_index == pick:
                        tag = " — your answer"
                    st.markdown(f"- {md(choice)}{tag}")
                if item.get("explanation"):
                    st.caption(md(item["explanation"]))

        if st.button("Try again", key=f"quiz_retry_{lesson_id}"):
            del st.session_state[state_key]
            st.rerun()


def _done_lessons(db: Database, student_id: int, agent_key: str) -> list[dict[str, Any]]:
    lessons = db.list_lessons(student_id, agent=agent_key, limit=10)
    return [l for l in lessons if (l.get("metadata") or {}).get("student_done_on")]


def student_lesson_view(
    db: Database, student: dict[str, Any], agent_key: str, subject_label: str
) -> None:
    """What the student sees on a subject page: his work, and nothing else.

    "Done" here is his own signal (`metadata.student_done_on`), not the
    parent's `status` -- logging hours is a separate act the parent still
    controls. Marking a lesson done just moves it out of here and into
    render_past_lessons's list, reopenable there; it never touches hours,
    credits, or the compliance record.

    Deliberately doesn't render "Past lessons" itself -- a page with its own
    content after the current lesson (English's Words to Review, for one)
    needs that section last, not sandwiched in the middle of the page.
    Call render_past_lessons() once, at the very end, after everything else
    on the page -- every subject page should, even ones with nothing of
    their own following it today, so a page added later doesn't have to
    remember this rule.
    """
    lessons = db.list_lessons(student["id"], agent=agent_key, limit=10)
    todo = [
        l for l in lessons
        if l["status"] != "skipped" and not (l.get("metadata") or {}).get("student_done_on")
    ]
    done = _done_lessons(db, student["id"], agent_key)
    current = todo[0] if todo else None

    if current is None:
        if done:
            st.success("Nothing left to do for now — nice work. Look back below if you want.")
        else:
            st.info(
                f"No {subject_label} lesson has been set up yet. Ask your parent to plan one."
            )
    else:
        if current["status"] == "completed":
            st.caption("This one's already marked done — here it is again.")
        render_lesson(current["payload"], for_parent=False)
        render_quiz(
            db,
            student,
            current["id"],
            current.get("metadata") or {},
            current["payload"].get("quiz") or [],
        )
        if st.button("✅ I'm done for today", key=f"student_done_{current['id']}", type="primary"):
            db.mark_student_done(current["id"])
            st.rerun()


def render_past_lessons(db: Database, student: dict[str, Any], agent_key: str) -> None:
    """The reopenable archive of lessons he's marked done -- always the last
    thing on a subject page. See student_lesson_view's docstring for why
    this is a separate call rather than folded into it.
    """
    done = _done_lessons(db, student["id"], agent_key)
    if not done:
        return
    st.divider()
    st.subheader("Past lessons")
    labels = [f"{l['created_at'][:10]} — {l['title']}" for l in done]
    choice = st.selectbox(
        "Look back at a finished lesson",
        labels,
        index=None,
        placeholder="Pick one to reopen",
        key=f"past_lesson_pick_{agent_key}",
    )
    if choice is not None:
        selected = done[labels.index(choice)]
        render_lesson(selected["payload"], for_parent=False)
        render_quiz(
            db,
            student,
            selected["id"],
            selected.get("metadata") or {},
            selected["payload"].get("quiz") or [],
        )


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


def render_today_checklist(db: Database, student: dict[str, Any]) -> bool:
    """His own "what I did today" list -- a fun accomplishment checklist, not
    a compliance record. Built entirely from his own signals (student_done_on,
    a quiz result graded today, a life skill either of you checked off today)
    so it never depends on the parent having logged anything yet -- that gap
    was the exact thing that made "current lesson" confusing before.

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

    if not done_today and not skills_today:
        return False

    st.subheader(f"✅ Today ({len(done_today) + len(skills_today)})")
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
  background: radial-gradient(circle at 32% 28%, #FFE9A0, var(--c-primary) 75%);
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


VOCAB_STREAK_HYPE = ["Nice!", "Boom!", "Nailed it!", "You got it!", "Crushed it!", "Sweet!"]
VOCAB_STREAK_ON_FIRE = 5  # streak length that earns balloons, not just a toast


VOCAB_MEMORY_ROUND_SIZE = 6  # pairs per round -- 12 face-down cards
VOCAB_MEMORY_COLUMNS = 6  # more, narrower columns -- half the card size of 3
VOCAB_MEMORY_CARD_BACK = "**?**"

_VOCAB_CARD_CSS = """
<style>
div[class*="st-key-vocab_card_"] button {
  aspect-ratio: 1 / 1;
  height: auto !important;
  min-height: 60px;
  padding: 7px !important;
  display: flex;
  align-items: center;
  justify-content: center;
  text-align: center;
  white-space: normal !important;
}
div[class*="st-key-vocab_card_"] button p {
  font-size: 0.8rem;
  line-height: 1.25;
}
/* The card back's "?" is the only bold text this grid ever shows -- markdown
   bold renders as a nested <strong>, which nothing else here uses, so this
   reaches the glyph itself without touching revealed word/definition text. */
div[class*="st-key-vocab_card_"] button p strong {
  font-size: 1.8rem;
  font-family: var(--c-mono);
  color: var(--c-alt);
  text-shadow: 0 0 8px var(--c-alt);
}
</style>
"""


def render_vocab_memory(db: Database, student: dict[str, Any]) -> None:
    """The one vocabulary review mode: classic Concentration. A shuffled grid
    of face-down cards -- half words, half definitions -- flip two, and
    either they're a pair or they're not.

    This replaced two earlier, separate modes (a one-at-a-time flashcard
    recall drill, and "Trading Cards," a two-column click-word-then-
    click-definition match with everything visible up front) with a single
    view, and it's also a second attempt at a face-down grid specifically --
    an earlier Memory Match build was scrapped because a matched pair
    *vanished* the instant it resolved, leaving nothing on screen to anchor
    the memory of where it had been. The fix here isn't a different genre of
    game, just: a resolved pair stays face-up, in place, marked solved
    (`disabled=True`, no further click does anything) -- exactly like real
    Concentration, where cleared pairs stay on the table rather than
    teleporting away. The grid never shrinks or reflows mid-round.

    A mismatch also stays face-up rather than silently flipping back on its
    own -- a live per-second auto-flip would need a background timer loop,
    which this project has avoided everywhere else (see the round clock
    below), and a *silent* auto-flip-on-next-click would be confusing in a
    static-until-clicked UI: nothing else here ever changes without him
    clicking something first. Instead the whole grid disables and a single
    "Not a match — flip back" button is the only thing left to press,
    so seeing the wrong pair and dismissing it are two separate, deliberate
    steps rather than one that also happens to reveal a third card.

    Scoring rule, unchanged from Trading Cards: a pair matched on the first
    attempt it's involved in counts as "knew it"; a pair that took a
    mismatch first still counts as "missed" once it's eventually matched --
    same db.record_vocabulary_review() the parent-facing Vocabulary tab
    already calls, so which review mode he uses doesn't change what the
    Leitner schedule means. The streak breaks the moment a mismatch
    happens, not once the pair eventually resolves -- the number on screen
    should never lag behind reality.

    The round timer and best-time record are carried over unchanged from
    Trading Cards -- wall-clock (`time.time()` at round start vs. now),
    refreshed on every click rather than a live tick, same reasoning as
    above. `vocab_best_round_seconds` is the same settings key Trading Cards
    used; it's still "fastest round," just at a different game.
    """
    due = db.vocabulary_due(student["id"], limit=25)
    streak = st.session_state.setdefault("vocab_streak", 0)
    best_streak = st.session_state.setdefault("vocab_best_streak", 0)
    reviewed = st.session_state.setdefault("vocab_reviewed_count", 0)

    if not due:
        if reviewed:
            st.success(f"🎉 All caught up! {reviewed} word(s) reviewed, best streak {best_streak}.")
            st.balloons()
        else:
            st.success("Nothing due for review today.")
        return

    due_ids = {entry["id"] for entry in due}
    state = st.session_state.setdefault("vocab_memory", {})
    round_ids = state.get("round_ids", [])
    resolved = state.get("resolved", set())
    remaining = [i for i in round_ids if i not in resolved]

    # Checked against `remaining`, not `round_ids`, for the same reason
    # Trading Cards checked it this way: a pair he just matched drops out of
    # `due` immediately (its next_review_on moves forward), so checking the
    # *whole* round here would treat every single match as "stale" and
    # restart the round on the very next render.
    if not remaining or any(i not in due_ids for i in remaining):
        round_ids = [entry["id"] for entry in due[:VOCAB_MEMORY_ROUND_SIZE]]
        cards = [(f"{i}_word", i, "word") for i in round_ids] + [
            (f"{i}_def", i, "def") for i in round_ids
        ]
        random.shuffle(cards)
        state.clear()
        state.update(
            card_order=[c[0] for c in cards],
            card_vocab={c[0]: c[1] for c in cards},
            card_side={c[0]: c[2] for c in cards},
            round_ids=round_ids,
            flipped=[],
            mismatch=False,
            resolved=set(),
            missed=set(),
            start_time=time.time(),
        )
        resolved = state["resolved"]

    # Looked up from the full deck, not `due` -- a resolved pair (by
    # definition) has just dropped out of `due`, its next_review_on pushed
    # forward, but it still needs its word and definition to render.
    by_id = {v["id"]: v for v in db.list_vocabulary(student["id"]) if v["id"] in round_ids}

    elapsed = time.time() - state["start_time"]
    metrics = st.columns(4)
    metrics[0].metric("🔥 Streak", streak)
    metrics[1].metric("✅ Reviewed", reviewed)
    metrics[2].metric("Left today", len(due))
    metrics[3].metric("⏱️ This round", f"{int(elapsed // 60)}:{int(elapsed % 60):02d}")

    pairs_done = len(resolved)
    st.progress(
        pairs_done / len(round_ids),
        text=f"Round progress — {pairs_done} / {len(round_ids)} pairs found",
    )

    best_raw = db.get_setting("vocab_best_round_seconds")
    if best_raw:
        best_seconds = float(best_raw)
        st.caption(f"🏆 Best round: {int(best_seconds // 60)}:{int(best_seconds % 60):02d}")

    flipped = state["flipped"]
    if state["mismatch"]:
        st.caption("Not a match — take a look, then flip them back.")
    else:
        st.caption("Flip two cards. Word and definition, same pair.")

    st.markdown(_VOCAB_CARD_CSS, unsafe_allow_html=True)
    columns = st.columns(VOCAB_MEMORY_COLUMNS)
    for index, card_id in enumerate(state["card_order"]):
        vocab_id = state["card_vocab"][card_id]
        column = columns[index % VOCAB_MEMORY_COLUMNS]
        is_resolved = vocab_id in resolved
        is_flipped = card_id in flipped
        face_up = is_resolved or is_flipped
        if face_up:
            entry = by_id.get(vocab_id) or {}
            text = entry.get("word") if state["card_side"][card_id] == "word" else entry.get(
                "definition"
            )
            label = f"✅ {text}" if is_resolved else str(text)
        else:
            label = VOCAB_MEMORY_CARD_BACK
        if column.button(
            label,
            key=f"vocab_card_{card_id}",
            width="stretch",
            disabled=is_resolved or state["mismatch"] or is_flipped,
        ):
            flipped.append(card_id)
            if len(flipped) == 2:
                first_vocab, second_vocab = (state["card_vocab"][c] for c in flipped)
                if first_vocab == second_vocab:
                    clean = first_vocab not in state["missed"]
                    db.record_vocabulary_review(first_vocab, correct=clean)
                    resolved.add(first_vocab)
                    state["flipped"] = []
                    st.session_state["vocab_reviewed_count"] = reviewed + 1
                    round_done = len(resolved) == len(state["round_ids"])

                    if clean:
                        new_streak = streak + 1
                        st.session_state["vocab_streak"] = new_streak
                        st.session_state["vocab_best_streak"] = max(best_streak, new_streak)

                    if round_done:
                        round_seconds = time.time() - state["start_time"]
                        if not best_raw or round_seconds < float(best_raw):
                            db.set_setting("vocab_best_round_seconds", str(round_seconds))
                            st.toast("🏆 New record round!")
                        st.balloons()
                        st.toast("🎉 Round complete!")
                    elif clean and new_streak >= VOCAB_STREAK_ON_FIRE:
                        st.balloons()
                        st.toast(f"🚀 {new_streak} in a row — you're on fire!")
                    elif clean:
                        st.toast(f"{random.choice(VOCAB_STREAK_HYPE)} 🔥 {new_streak} in a row")
                    else:
                        st.toast("✅ Got it that time!")
                else:
                    state["missed"].update((first_vocab, second_vocab))
                    state["mismatch"] = True
                    st.session_state["vocab_streak"] = 0
                    st.toast("❌ Not a match.")
            st.rerun()

    if state["mismatch"]:
        if st.button(
            "↩️ Not a match — flip back",
            key="vocab_flip_back",
            type="primary",
            width="stretch",
        ):
            state["flipped"] = []
            state["mismatch"] = False
            st.rerun()


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


# --- school-year and Declaration of Intent countdowns -------------------------


def render_school_start_countdown(db: Database) -> None:
    """Shown to both parent and student -- there's nothing here to redact."""
    next_start = next_annual_date(db.get_setting("school_year_start") or "09-01")
    remaining = days_until(next_start)
    when = f"{next_start.strftime('%B')} {next_start.day}"
    if remaining <= 0:
        st.caption(f"🎉 Today's the first day of school ({when}).")
    else:
        plural = "s" if remaining != 1 else ""
        st.caption(f"🗓️ {remaining} day{plural} until the first day of school ({when}).")


_FIRST_DAY_INK = "#211a14"
_FIRST_DAY_PAPER = "#fbf1d6"
_FIRST_DAY_CARD_PAPER = "#fffaf0"
# Same four of the five "Sunday Funnies" week-grid colors (compass_week's own
# red is reserved for the masthead's own shadow, below) -- deliberately the
# same fixed printed-poster palette, not theme.py's tokens, same reasoning as
# that styling: a printed comic page doesn't re-theme itself for the room
# it's read in.
_FIRST_DAY_COLORS = ("#3564c4", "#3f9450", "#f0ac1f", "#8c4fa8")
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
    detail instead of counts: literally every book ever added, no status
    filter at all (unlike current_book()/upcoming_book(), which are about
    picking *the one* the English agent reads from right now -- this is
    "what's on his list for the year," a different question, and internal
    reading-progress bookkeeping shouldn't hide a book from it), every Big
    Project with
    its actual objective, every choice topic and life skill with its
    description, and the travel log's real entries. Two explainer
    sections (Check-In, Morning Routine) carry no per-student data at all
    -- they exist purely so he knows what those two daily habits are and
    what's expected, since the rest of Home introduces them by name
    without ever spelling that out. Choice Topics, Life Skills, and Travel
    are explicitly labeled examples -- their content is either a starter
    catalog or just whatever's logged so far, not a fixed or complete
    assignment list, and the label is there so he doesn't mistake one for
    the other. Reachable only from the cover's "See what's inside" button.
    """
    student_id = student["id"]
    books = db.list_books(student_id)
    projects = db.list_big_projects(student_id)
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
