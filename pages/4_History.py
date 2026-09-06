"""History & Social Studies Agent — timeline coverage, location override."""

from __future__ import annotations

import streamlit as st

from compass.agents.strategies import ERAS
from compass.ui import (
    is_parent,
    md,
    page_setup,
    render_past_lessons,
    render_subject_week_tab,
    student_lesson_view,
)

db, student = page_setup("History", icon="🏛️")

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

week_tab, timeline_tab = st.tabs(["This week", "Timeline coverage"])

with week_tab:
    render_subject_week_tab(db, student, "history")
    st.caption("✍️ Generate new lessons from **Mission Control → Plan a lesson**.")

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
