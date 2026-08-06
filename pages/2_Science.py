"""Science Agent — spiderweb branching, location-aware."""

from __future__ import annotations

import streamlit as st

from compass.agents import LessonGenerationError, get_agent
from compass.ui import (
    api_status_banner,
    is_parent,
    student_lesson_view,
    context_for,
    log_lesson_form,
    page_setup,
    render_lesson,
    render_proposal,
)

db, student = page_setup("Science", icon="🔬")
agent = get_agent("science")

st.title("🔬 Science Agent")
st.caption(
    "Spiderweb branching. Each lesson pulls one thread and proposes the next branches, "
    "so the year's path grows out of where you actually are."
)

# Student view: his lesson, without the answer key or the admin surface.
if not is_parent():
    student_lesson_view(db, student, "science", "science")
    st.stop()

plan_tab, web_tab = st.tabs(["Plan a lesson", "The web"])

with plan_tab:
    api_ok = api_status_banner()

    columns = st.columns([2, 1, 1])
    with columns[0]:
        location = st.text_input(
            "Where are you right now?",
            placeholder="e.g. Olympic National Park, Hoh Rain Forest",
            help="Drives the whole lesson. Leave blank for an at-home lesson.",
        )
    with columns[1]:
        minutes = st.number_input("Minutes", min_value=15, max_value=240, value=75, step=15)
    with columns[2]:
        pool = db.unexplored_web_nodes(student["id"], "science", location or None)
        st.metric("Open branches", len(pool))

    seed_topic = st.text_input(
        "Or force a specific thread (optional)",
        placeholder="e.g. why nurse logs grow hemlocks and not spruce",
    )
    parent_note = st.text_input(
        "Note for this lesson (optional)", placeholder="e.g. keep it to a two-hour hike"
    )

    ctx = context_for(
        db,
        student,
        location=location,
        minutes=minutes,
        parent_note=parent_note,
        seed_topic=seed_topic,
    )
    proposal = agent.propose_topic(ctx)
    render_proposal(agent, proposal)

    if st.button("Generate lesson", type="primary", disabled=not api_ok):
        with st.spinner("The Science Agent is researching and writing…"):
            try:
                st.session_state["science_lesson"] = agent.generate(ctx, proposal)
            except LessonGenerationError as exc:
                st.error(str(exc))

    generated = st.session_state.get("science_lesson")
    if generated:
        st.divider()
        for warning in generated.warnings:
            st.caption(f"⚠️ {warning}")
        render_lesson(generated.payload)
        st.divider()
        log_lesson_form(
            db,
            student,
            generated,
            source="science",
            primary_subject="science",
            location=location,
            key_prefix="science",
        )

with web_tab:
    nodes = db.web_nodes(student["id"], "science")
    if not nodes:
        st.info("The web is empty. Generate a lesson to plant the first thread.")
    else:
        explored = [n for n in nodes if n["explored_on"]]
        open_nodes = [n for n in nodes if not n["explored_on"]]

        columns = st.columns(3)
        columns[0].metric("Topics explored", len(explored))
        columns[1].metric("Open branches", len(open_nodes))
        columns[2].metric("Max depth", max((n["depth"] for n in nodes), default=0))

        by_id = {n["id"]: n for n in nodes}

        st.subheader("Open branches")
        st.caption("The next lesson is drawn from here, nearest the trunk first.")
        for node in sorted(open_nodes, key=lambda n: (n["depth"], n["id"])):
            parent = by_id.get(node["parent_id"])
            lineage = f" ← {parent['topic']}" if parent else ""
            where = f" · {node['location']}" if node["location"] else ""
            st.markdown(f"- **{node['topic']}**{where}  \n  <small>{node['rationale']}{lineage}</small>",
                        unsafe_allow_html=True)

        st.subheader("Already explored")
        for node in sorted(explored, key=lambda n: n["explored_on"] or "", reverse=True):
            st.markdown(f"- ✅ {node['topic']} — *{node['explored_on']}*")
