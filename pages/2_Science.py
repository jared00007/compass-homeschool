"""Science Agent — spiderweb branching, location-aware."""

from __future__ import annotations

import streamlit as st

from compass.ui import (
    is_parent,
    md,
    page_setup,
    render_past_lessons,
    render_subject_week_tab,
    student_lesson_view,
)

db, student = page_setup("Science", icon="🔬")

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

week_tab, web_tab = st.tabs(["This week", "The web"])

with week_tab:
    render_subject_week_tab(db, student, "science")
    st.caption("✍️ Generate new lessons from **Mission Control → Plan a lesson**.")

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
