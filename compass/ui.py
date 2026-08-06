"""Streamlit helpers shared across pages.

Kept out of `compass/` core modules on purpose — the agents, storage, and
compliance layers know nothing about Streamlit, so they stay testable and
reusable if the UI is ever replaced.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from typing import Any

import streamlit as st

from compass import auth, config, subjects, theme as theming
from compass.backup import auto_snapshot
from compass.agents import GeneratedLesson, LessonAgent, StudentContext
from compass.storage.db import Database


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
    # Before anything renders, so the page never flashes the wrong colours.
    st.markdown(theming.css(current_theme(db)), unsafe_allow_html=True)
    _sidebar(db, student)
    return db, student


# --- theme -------------------------------------------------------------------


def _theme_key(db: Database) -> str:
    """Which settings key holds the theme for whoever is looking."""
    return theming.PARENT_KEY if is_parent() else theming.STUDENT_KEY


def current_theme(db: Database) -> theming.Theme:
    return theming.get(db.get_setting(_theme_key(db), theming.DEFAULT_THEME))


def _theme_control(db: Database) -> None:
    """Theme picker. Deliberately not tucked inside an expander — the whole
    point is that he finds it and changes it himself."""
    keys = list(theming.THEMES)
    active = db.get_setting(_theme_key(db), theming.DEFAULT_THEME)

    chosen = st.selectbox(
        "🎨 Look",
        keys,
        index=keys.index(active) if active in keys else 0,
        format_func=lambda k: theming.THEMES[k].name,
        key="theme_choice",
        help="Changes how Compass looks. Your parent's view keeps its own setting."
        if not is_parent()
        else "Changes how Compass looks for you. His view keeps its own setting.",
    )
    st.caption(theming.THEMES[chosen].tagline)
    if chosen != active:
        db.set_setting(_theme_key(db), chosen)
        st.rerun()


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
        _theme_control(db)


def _profile_control(db: Database, student: dict[str, Any]) -> None:
    """Edit the student's name, grade, age, and interests.

    Parent-only: `interests` feeds every agent's system prompt, so this is
    configuration, not a preference — the same reasoning that keeps Tier 1
    strategy choices out of student hands.
    """
    if not is_parent():
        return
    with st.expander("✏️ Edit his profile"):
        with st.form("edit_profile"):
            name = st.text_input("Name", value=student["name"])
            columns = st.columns(2)
            grade = columns[0].text_input("Grade", value=student["grade"])
            age = columns[1].number_input(
                "Age", min_value=5, max_value=19, value=int(student["age"] or 13)
            )
            interests = st.text_area(
                "Interests he's told us about",
                value=student.get("interests") or "",
                height=70,
                help="Read by every agent when it writes a lesson.",
            )
            if st.form_submit_button("Save", type="primary"):
                db.update_student(
                    student["id"],
                    name=name.strip() or "Student",
                    grade=grade.strip() or "8",
                    age=int(age),
                    interests=interests.strip(),
                )
                st.success("Saved.")
                st.rerun()


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
        if st.button("Switch to student view", use_container_width=True):
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
        if st.button("Unlock", use_container_width=True):
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


# --- lesson rendering --------------------------------------------------------


def render_proposal(agent: LessonAgent, proposal) -> None:
    if proposal.blocked:
        st.warning(f"**{agent.name} can't plan a lesson yet.**\n\n{proposal.blocked_reason}")
        return
    st.info(f"**Next up: {proposal.topic}**\n\n{proposal.rationale}")
    if proposal.context_lines:
        with st.expander("What the agent knows going in"):
            for line in proposal.context_lines:
                st.markdown(f"- {line}")


def render_lesson(lesson: dict[str, Any], for_parent: bool | None = None) -> None:
    """Render a lesson. In student view the answer key never reaches the page.

    The redaction happens here rather than in a CSS class or an expander, because
    anything sent to the browser can be read out of it. What a student must not
    see is simply not written.
    """
    parent = is_parent() if for_parent is None else for_parent

    st.subheader(lesson.get("title", "Lesson"))
    if lesson.get("overview"):
        st.write(lesson["overview"])

    objectives = lesson.get("learning_objectives") or []
    if objectives:
        st.markdown("**Learning objectives**")
        for objective in objectives:
            st.markdown(f"- {objective}")

    activities = lesson.get("activities") or []
    if activities:
        st.markdown("**Activities**")
        for index, activity in enumerate(activities, start=1):
            header = (
                f"{index}. {activity.get('title', 'Activity')} · "
                f"{activity.get('kind', '')} · {activity.get('minutes', 0)} min"
            )
            with st.expander(header, expanded=index == 1):
                st.write(activity.get("instructions", ""))

    columns = st.columns(2)
    with columns[0]:
        materials = lesson.get("materials") or []
        if materials:
            st.markdown("**Materials**")
            for item in materials:
                st.markdown(f"- {item}")
    with columns[1]:
        assessment = lesson.get("assessment") or {}
        if assessment and parent:
            st.markdown("**Assessment**")
            st.markdown(f"*{assessment.get('kind', '')}* — {assessment.get('description', '')}")
            if assessment.get("mastery_criteria"):
                st.markdown(f"**Mastery:** {assessment['mastery_criteria']}")
        elif assessment:
            st.markdown("**Assessment**")
            st.caption(
                "There's a check at the end of this lesson — your parent has it."
            )

    if parent:
        if lesson.get("parent_notes"):
            with st.expander("Notes for the parent"):
                st.write(lesson["parent_notes"])

        video = lesson.get("video") or {}
        if video.get("found") and video.get("url"):
            with st.expander(f"▶️ Suggested video — {video.get('title') or 'watch'}"):
                st.markdown(f"**[{video.get('title', 'Watch')}]({video['url']})**")
                if video.get("channel"):
                    st.caption(video["channel"])
                if video.get("why"):
                    st.write(video["why"])
                st.caption(
                    "Preview it and share the link yourself rather than handing him the "
                    "open YouTube app — Compass can verify the video, not what it "
                    "recommends afterward."
                )

        credits = lesson.get("subject_credits") or []
        if credits:
            st.markdown("**Subject credit (feeds the WA compliance dashboard)**")
            for credit in credits:
                st.markdown(
                    f"- **{subjects.label(credit['subject'])}** — {credit['minutes']} min · "
                    f"{credit.get('justification', '')}"
                )

        branches = lesson.get("branches") or []
        if branches:
            with st.expander(f"Branches this opens up ({len(branches)})"):
                for branch in branches:
                    st.markdown(f"- **{branch.get('topic')}** — {branch.get('rationale', '')}")


def render_life_skill_plan(plan: dict[str, Any]) -> None:
    """Render a life-skill teaching plan. Parent-facing throughout.

    Unlike a Tier 1 lesson there's no student view of this and no redaction to
    do: a life skill is something the parent runs standing next to him, so the
    plan is addressed to them. Guard the call site, not the fields.
    """
    st.subheader(plan.get("title", "Session plan"))
    if plan.get("overview"):
        st.write(plan["overview"])

    columns = st.columns(2)
    with columns[0]:
        prep = (plan.get("prep") or "").strip()
        if prep and prep.lower().rstrip(".") != "nothing":
            st.markdown("**Before you start**")
            st.write(prep)
    with columns[1]:
        materials = plan.get("materials") or []
        if materials:
            st.markdown("**What you need**")
            for item in materials:
                st.markdown(f"- {item}")

    steps = plan.get("steps") or []
    if steps:
        st.markdown("**How to run it**")
        for index, step in enumerate(steps, start=1):
            header = f"{index}. {step.get('title', 'Step')} · {step.get('minutes', 0)} min"
            with st.expander(header, expanded=index == 1):
                st.markdown("**He does**")
                st.write(step.get("what_he_does", ""))
                st.markdown("**You do**")
                st.write(step.get("what_you_do", ""))

    if plan.get("done_looks_like"):
        st.success(f"**Done looks like:** {plan['done_looks_like']}")

    watch_for = plan.get("watch_for") or []
    if watch_for:
        with st.expander(f"Where this goes wrong ({len(watch_for)})"):
            for item in watch_for:
                st.markdown(f"- {item}")

    follow_ups = plan.get("follow_ups") or []
    if follow_ups:
        with st.expander("Making it stick"):
            for item in follow_ups:
                st.markdown(f"- {item}")

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


def student_lesson_view(
    db: Database, student: dict[str, Any], agent_key: str, subject_label: str
) -> None:
    """What the student sees on a subject page: his work, and nothing else."""
    lessons = db.list_lessons(student["id"], agent=agent_key, limit=5)
    planned = [l for l in lessons if l["status"] == "planned"]
    current = planned[0] if planned else (lessons[0] if lessons else None)

    if current is None:
        st.info(
            f"No {subject_label} lesson has been set up yet. Ask your parent to plan one."
        )
        return

    if current["status"] == "completed":
        st.caption("This one's already marked done — here it is again.")
    render_lesson(current["payload"], for_parent=False)

    older = [l for l in lessons if l["id"] != current["id"]]
    if older:
        with st.expander(f"Earlier {subject_label} lessons ({len(older)})"):
            for lesson in older:
                st.markdown(f"**{lesson['created_at'][:10]} — {lesson['title']}**")
                st.caption(lesson["payload"].get("overview", ""))


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
