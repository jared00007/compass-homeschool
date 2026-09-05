"""Science Agent — spiderweb branching, location-aware."""

from __future__ import annotations

import streamlit as st

from compass.agents import get_agent
from compass.ui import (
    api_status_banner,
    context_for,
    difficulty_override_control,
    generate_series_and_log,
    is_parent,
    md,
    page_setup,
    render_past_lessons,
    render_proposal,
    render_subject_week_tab,
    student_lesson_view,
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
    render_past_lessons(db, student, "science", "science")
    st.stop()

week_tab, plan_tab, web_tab = st.tabs(["This week", "Plan a lesson", "The web"])

with week_tab:
    render_subject_week_tab(db, student, "science")

with plan_tab:
    api_ok = api_status_banner()

    columns = st.columns([2, 1, 1])
    with columns[0]:
        location = st.text_input(
            "Location-specific (optional)",
            placeholder="e.g. Olympic National Park, Hoh Rain Forest",
            help=(
                "If you're somewhere with hands-on science nearby -- a park, a trail, a "
                "garden -- the lesson builds around it. Leave blank for a normal at-home "
                "lesson continuing the current thread."
            ),
        )
    with columns[1]:
        minutes = st.number_input("Minutes", min_value=15, max_value=240, value=75, step=15)
    with columns[2]:
        pool = db.unexplored_web_nodes(student["id"], "science", location or None)
        st.metric("Open branches", len(pool))

    branch_options = [(0, "Let the agent choose the next branch")] + [
        (n["id"], f"{'  ' * n['depth']}{n['topic']}") for n in pool
    ]
    picked_id = st.selectbox(
        "Which thread to pull",
        [o[0] for o in branch_options],
        format_func=lambda i: dict(branch_options)[i],
        help="Open branches proposed by earlier lessons. The agent takes the top one "
             "unless you choose.",
    )

    seed_topic = st.text_input(
        "Or start something new entirely (optional)",
        placeholder="e.g. why nurse logs grow hemlocks and not spruce",
        help="Typing here ignores the branches above and starts a fresh thread. The "
             "existing branches stay in the web for later.",
    )
    parent_note = st.text_input(
        "Note for this lesson (optional)", placeholder="e.g. keep it to a two-hour hike"
    )
    difficulty = difficulty_override_control(db, key="science_difficulty")

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

    generate_series_and_log(
        db,
        student,
        agent,
        ctx,
        proposal,
        primary_subject="science",
        spinner="Planning the days and researching each lesson — this can take a few minutes.",
        api_ok=api_ok,
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
        st.caption(
            "Each lesson proposes 2-4 new branches and follows one, so the web grows. "
            "Prune anything you know you'll never teach — an unfollowed branch costs "
            "nothing, but a long list makes the useful ones harder to see."
        )
        for node in sorted(open_nodes, key=lambda n: (n["depth"], n["id"])):
            parent = by_id.get(node["parent_id"])
            lineage = f" ← {parent['topic']}" if parent else ""
            where = f" · {node['location']}" if node["location"] else ""
            row = st.columns([6, 1])
            row[0].markdown(
                f"**{md(node['topic'])}**{where}  \n<small>{md(node['rationale'])}{md(lineage)}</small>",
                unsafe_allow_html=True,
            )
            if row[1].button("Dismiss", key=f"sci_drop_{node['id']}"):
                db.delete_web_node(node["id"])
                st.rerun()

        st.subheader("Already explored")
        for node in sorted(explored, key=lambda n: n["explored_on"] or "", reverse=True):
            st.markdown(f"- ✅ {md(node['topic'])} — *{node['explored_on']}*")
