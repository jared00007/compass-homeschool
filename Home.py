"""Compass — homeschool curriculum home page."""

from __future__ import annotations

import streamlit as st

from compass import config
from compass.agents import life_skills
from compass.compliance import build_report
from compass.curriculum import frontier_report
from compass.subjects import label
from compass.ui import (
    is_parent,
    page_setup,
    render_declaration_banner,
    render_lesson,
    render_school_start_countdown,
    render_today_checklist,
)

db, student = page_setup("Home", icon="🧭")

# --- student view -------------------------------------------------------------
# When a PIN is set, this is what he lands on: today's work, and nothing that
# would spoil it.

if not is_parent():
    st.title(f"Hi {student['name'].split()[0]} 👋")
    st.caption("Here's what's set up for you. Open a subject in the sidebar for the details.")
    render_school_start_countdown(db)

    if render_today_checklist(db, student):
        st.divider()

    # Life-skill plans live in the same table but are written *to the parent* —
    # "demonstrate once, then hand him the jack and stay quiet" is not his to read.
    # A lesson he's already marked done (student_lesson_view's own signal, separate
    # from `status`) drops off here too -- otherwise it sits under "Ready for you"
    # forever until the parent logs it, which can be days.
    planned = [
        lesson
        for lesson in db.list_lessons(student["id"], limit=25)
        if lesson["status"] == "planned"
        and lesson["agent"] != life_skills.AGENT_KEY
        and not (lesson.get("metadata") or {}).get("student_done_on")
    ]

    if not planned:
        st.info("Nothing new is set up yet. Check back after your parent plans a lesson.")
    else:
        st.subheader(f"Ready for you ({len(planned)})")
        for lesson in planned:
            with st.container(border=True):
                payload = lesson["payload"]
                st.markdown(f"### {payload.get('title', lesson['title'])}")
                st.caption(f"{lesson['agent'].title()} · {payload.get('estimated_minutes', '?')} min")
                if payload.get("overview"):
                    st.write(payload["overview"])
                with st.expander("Open this lesson"):
                    render_lesson(payload, for_parent=False)

    st.divider()
    columns = st.columns(3)

    with columns[0]:
        st.markdown("#### 📖 Reading")
        book = db.current_book(student["id"])
        if book:
            st.markdown(f"**{book['title']}**")
            if book["total_pages"]:
                st.progress(
                    min((book["current_page"] or 0) / book["total_pages"], 1.0),
                    text=f"page {book['current_page']} of {book['total_pages']}",
                )
        else:
            st.caption("No book set up yet.")

    with columns[1]:
        st.markdown("#### 🔤 Words to review")
        # Same limit render_vocab_review uses, so this count matches what he'll
        # actually see when he clicks through rather than under- or over-stating it.
        due = db.vocabulary_due(student["id"], limit=25)
        st.metric("Due today", len(due))
        if due:
            st.page_link("pages/3_English.py", label="Review them", icon="➡️")

    with columns[2]:
        st.markdown("#### ⭐ Your choice topics")
        topics = [
            t for t in db.list_choice_topics(student["id"]) if t["status"] in ("active", "approved")
        ]
        if topics:
            for topic in topics[:4]:
                st.markdown(f"- {topic['title']}")
        else:
            st.caption("Nothing yet — add something you want to learn.")
        st.page_link("pages/6_Choice_Topics.py", label="Add a topic", icon="➡️")

    st.stop()

# --- parent view --------------------------------------------------------------

st.title("🧭 Compass")
st.caption(
    f"Multi-agent homeschool curriculum for {student['name']}, grade {student['grade']}."
)
render_school_start_countdown(db)
render_declaration_banner(db, student)

report = build_report(db, student["id"])
pace = report.pace()

# --- headline compliance numbers ---------------------------------------------

columns = st.columns(4)
columns[0].metric(
    "Instructional hours",
    f"{report.total_hours:g}",
    delta=f"{pace['ahead_by']:+g} vs pace",
    help=f"Washington requires {config.WA_ANNUAL_HOURS} hours per year.",
)
columns[1].metric("Days of instruction", report.instructional_days, help=f"Target {report.day_target}.")
columns[2].metric(
    "Subjects covered",
    f"{report.subjects_covered} / 11",
    delta=None if report.all_subjects_covered else "gap",
    delta_color="off" if report.all_subjects_covered else "inverse",
)
columns[3].metric("Activities logged", report.activity_count)

pace_text = (
    f"about {pace['hours_per_week_needed']:g} hrs/week"
    if pace["achievable"]
    else f"{pace['remaining_days']} days left — see Compliance"
)
st.progress(
    report.hour_progress,
    text=f"{report.total_hours:g} of {report.hour_target} hours "
    f"({report.hours_remaining:g} to go · {pace_text})",
)

for warning in report.warnings:
    st.warning(warning)

st.divider()

# --- what each agent would do next -------------------------------------------

st.subheader("What each agent would plan next")
st.caption(
    "Computed locally from his actual state — no model call. This is the strategy "
    "layer's answer before any lesson is written."
)

AGENT_PAGES = {
    "math": ("📐 Math", "pages/1_Math.py"),
    "science": ("🔬 Science", "pages/2_Science.py"),
    "english": ("📖 English", "pages/3_English.py"),
    "history": ("🏛️ History", "pages/4_History.py"),
}

from compass.agents import all_agents  # noqa: E402
from compass.ui import context_for  # noqa: E402

agent_columns = st.columns(4)
for column, (key, agent) in zip(agent_columns, all_agents().items()):
    with column:
        title, page = AGENT_PAGES.get(key, (agent.name, None))
        st.markdown(f"#### {title}")
        try:
            proposal = agent.propose_topic(context_for(db, student))
        except Exception as exc:  # a strategy should never take down the home page
            st.error(f"Strategy error: {exc}")
            continue
        if proposal.blocked:
            st.warning(proposal.blocked_reason)
        else:
            st.markdown(f"**{proposal.topic}**")
            st.caption(proposal.rationale)
        if page:
            st.page_link(page, label=f"Open {title}", icon="➡️")

st.divider()

# --- coverage + math frontier -------------------------------------------------

left, right = st.columns([3, 2])

with left:
    st.subheader("The eleven required subjects")
    for subject in report.subjects:
        icon = "✅" if subject.has_instruction else "⬜"
        last = f" · last taught {subject.last_taught}" if subject.last_taught else ""
        st.markdown(f"{icon} **{subject.label}** — {subject.hours:g} hrs{last}")
    st.page_link("pages/5_Compliance.py", label="Full compliance dashboard", icon="📋")

with right:
    st.subheader("Math graph")
    frontier = frontier_report(db.mastered_skills(student["id"]))
    st.metric(
        "Skills mastered",
        f"{frontier['mastered_count']} / {frontier['total_skills']}",
    )
    available = frontier["available"]
    st.caption(f"{len(available)} skill(s) unlocked and ready, {frontier['locked_count']} locked.")
    for skill in available[:5]:
        st.markdown(f"- {skill.title}")

    st.subheader("Tier balance")
    for tier in config.TIERS:
        minutes = report.minutes_by_tier.get(tier, 0)
        if minutes:
            st.markdown(
                f"- **{config.tier_label(tier, student['name'])}** — {round(minutes / 60, 1):g} hrs"
            )
    if report.tier3_minutes:
        st.caption(
            f"Tier 3 is {report.tier3_percent:g}% of logged hours "
            f"(family guideline: {report.tier3_cap_percent}%)."
        )

st.divider()

# --- recent activity ----------------------------------------------------------

st.subheader("Recently logged")
recent = db.list_activities(student["id"], limit=8)
if not recent:
    st.caption("Nothing logged yet. Generate a lesson, or log an activity directly.")
else:
    for activity in recent:
        credit_summary = " · ".join(
            f"{label(subject)} {minutes}m" for subject, minutes in activity["credits"].items()
        )
        st.markdown(
            f"**{activity['occurred_on']}** — {activity['title']} "
            f"({activity['minutes']} min) — {credit_summary}"
        )
st.page_link("pages/8_Activity_Log.py", label="Full activity log", icon="🗂️")
