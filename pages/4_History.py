"""History & Social Studies Agent — timeline coverage, location override."""

from __future__ import annotations

import streamlit as st

from compass.agents import get_agent
from compass.agents.strategies import ERAS
from compass.ui import (
    api_status_banner,
    context_for,
    difficulty_override_control,
    generate_and_log,
    is_parent,
    md,
    page_setup,
    render_past_lessons,
    render_proposal,
    render_subject_week_tab,
    student_lesson_view,
)

db, student = page_setup("History", icon="🏛️")
agent = get_agent("history")

st.title("🏛️ History & Social Studies Agent")
st.caption(
    "Timeline-driven, with a standing override: if where you are has a real historical "
    "connection, that beats what's next in the sequence."
)

# Student view: his lesson, without the answer key or the admin surface.
if not is_parent():
    student_lesson_view(db, student, "history", "history")
    render_past_lessons(db, student, "history", "history")
    st.stop()

week_tab, plan_tab, timeline_tab = st.tabs(["This week", "Plan a lesson", "Timeline coverage"])

with week_tab:
    render_subject_week_tab(db, student, "history")

with plan_tab:
    api_ok = api_status_banner()

    columns = st.columns([2, 1, 1])
    with columns[0]:
        location = st.text_input(
            "Location-specific (optional)",
            placeholder="e.g. Whitman Mission, Walla Walla WA",
            help=(
                "A real historical site or place ties the lesson to it instead of the "
                "next era in sequence. Leave blank to keep following the curriculum."
            ),
        )
    with columns[1]:
        minutes = st.number_input("Minutes", min_value=15, max_value=240, value=60, step=15)
    with columns[2]:
        pool = db.unexplored_web_nodes(student["id"], "history", location or None)
        st.metric("Open threads", len(pool))

    thread_options = [(0, "Let the agent choose (era coverage, or the location)")] + [
        (n["id"], n["topic"]) for n in pool
    ]
    picked_id = st.selectbox(
        "Which thread to follow",
        [o[0] for o in thread_options],
        format_func=lambda i: dict(thread_options)[i],
        help="Open threads proposed by earlier lessons.",
    )

    seed_topic = st.text_input(
        "Or start something new entirely (optional)",
        placeholder="e.g. the 1855 Walla Walla Treaty Council",
    )
    parent_note = st.text_input("Note for this lesson (optional)")
    difficulty = difficulty_override_control(db, key="history_difficulty")

    ctx = context_for(
        db,
        student,
        location=location,
        minutes=minutes,
        parent_note=parent_note,
        seed_topic=seed_topic,
        node_id=picked_id or None,
        difficulty=difficulty,
    )
    proposal = agent.propose_topic(ctx)
    render_proposal(agent, proposal)

    generate_and_log(
        db,
        student,
        agent,
        ctx,
        proposal,
        primary_subject="history",
        spinner="The History Agent is researching and writing…",
        api_ok=api_ok,
        location=location,
    )

with timeline_tab:
    lessons = db.list_lessons(student["id"], agent="history", limit=200)
    covered: dict[str, list[str]] = {key: [] for key, _ in ERAS}
    for lesson in lessons:
        era = lesson.get("metadata", {}).get("era")
        if era in covered:
            covered[era].append(lesson["title"])

    open_threads = db.unexplored_web_nodes(student["id"], "history")

    touched = sum(1 for key, _ in ERAS if covered[key])
    columns = st.columns(3)
    columns[0].metric("Eras touched", f"{touched} / {len(ERAS)}")
    columns[1].metric("History lessons", len(lessons))
    columns[2].metric("Open threads", len(open_threads))

    st.subheader("Scope and sequence")
    st.caption("The agent teaches the least-covered era unless the location earns an override.")
    for key, era_label in ERAS:
        titles = covered[key]
        marker = "✅" if titles else "⬜"
        with st.expander(f"{marker} {era_label} — {len(titles)} lesson(s)"):
            if titles:
                for title in titles:
                    st.markdown(f"- {md(title)}")
            else:
                st.caption("Nothing taught in this era yet.")

    if open_threads:
        st.subheader("Open threads")
        for node in open_threads:
            where = f" · {node['location']}" if node["location"] else ""
            row = st.columns([6, 1])
            row[0].markdown(
                f"**{md(node['topic'])}**{where} — <small>{md(node['rationale'])}</small>",
                unsafe_allow_html=True,
            )
            if row[1].button("Dismiss", key=f"hist_drop_{node['id']}"):
                db.delete_web_node(node["id"])
                st.rerun()
