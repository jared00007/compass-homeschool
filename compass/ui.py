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

from compass import config, subjects
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
    _sidebar(db, student)
    return db, student


def _sidebar(db: Database, student: dict[str, Any]) -> None:
    with st.sidebar:
        st.markdown(f"### 🧭 Compass\n**{student['name']}** · Grade {student['grade']}")
        start, end = db.school_year_bounds()
        st.caption(f"School year {start} → {end}")
        st.divider()
        st.caption(
            "Tier 1 is agent-planned and WA-mandated. Tier 2 is credited inside Tier 1 "
            "activities. Tier 3 is his to choose."
        )


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


def render_lesson(lesson: dict[str, Any]) -> None:
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
        if assessment:
            st.markdown("**Assessment**")
            st.markdown(f"*{assessment.get('kind', '')}* — {assessment.get('description', '')}")
            if assessment.get("mastery_criteria"):
                st.markdown(f"**Mastery:** {assessment['mastery_criteria']}")

    if lesson.get("parent_notes"):
        with st.expander("Notes for the parent"):
            st.write(lesson["parent_notes"])

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


def log_lesson_form(
    db: Database,
    student: dict[str, Any],
    generated: GeneratedLesson,
    source: str,
    primary_subject: str,
    location: str = "",
    key_prefix: str = "log",
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
            tier=config.TIER_CORE,
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
