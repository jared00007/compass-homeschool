"""History & Social Studies Agent — timeline coverage, location override."""

from __future__ import annotations

import streamlit as st

from compass.agents import LessonGenerationError, get_agent
from compass.agents.strategies import ERAS
from compass.ui import (
    api_status_banner,
    context_for,
    log_lesson_form,
    page_setup,
    render_lesson,
    render_proposal,
)

db, student = page_setup("History", icon="🏛️")
agent = get_agent("history")

st.title("🏛️ History & Social Studies Agent")
st.caption(
    "Timeline-driven, with a standing override: if where you are has a real historical "
    "connection, that beats what's next in the sequence."
)

plan_tab, timeline_tab = st.tabs(["Plan a lesson", "Timeline coverage"])

with plan_tab:
    api_ok = api_status_banner()

    columns = st.columns([2, 1, 1])
    with columns[0]:
        location = st.text_input(
            "Where are you right now?",
            placeholder="e.g. Whitman Mission, Walla Walla WA",
            help="A genuine local connection takes priority over the next era in sequence.",
        )
    with columns[1]:
        minutes = st.number_input("Minutes", min_value=15, max_value=240, value=60, step=15)
    with columns[2]:
        pool = db.unexplored_web_nodes(student["id"], "history", location or None)
        st.metric("Open threads", len(pool))

    seed_topic = st.text_input(
        "Or force a specific topic (optional)",
        placeholder="e.g. the 1855 Walla Walla Treaty Council",
    )
    parent_note = st.text_input("Note for this lesson (optional)")

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
        with st.spinner("The History Agent is researching and writing…"):
            try:
                st.session_state["history_lesson"] = agent.generate(ctx, proposal)
            except LessonGenerationError as exc:
                st.error(str(exc))

    generated = st.session_state.get("history_lesson")
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
            source="history",
            primary_subject="history",
            location=location,
            key_prefix="history",
        )

with timeline_tab:
    lessons = db.list_lessons(student["id"], agent="history", limit=200)
    covered: dict[str, list[str]] = {key: [] for key, _ in ERAS}
    for lesson in lessons:
        era = lesson.get("metadata", {}).get("era")
        if era in covered:
            covered[era].append(lesson["title"])

    touched = sum(1 for key, _ in ERAS if covered[key])
    columns = st.columns(3)
    columns[0].metric("Eras touched", f"{touched} / {len(ERAS)}")
    columns[1].metric("History lessons", len(lessons))
    columns[2].metric("Open threads", len(db.unexplored_web_nodes(student["id"], "history")))

    st.subheader("Scope and sequence")
    st.caption("The agent teaches the least-covered era unless the location earns an override.")
    for key, era_label in ERAS:
        titles = covered[key]
        marker = "✅" if titles else "⬜"
        with st.expander(f"{marker} {era_label} — {len(titles)} lesson(s)"):
            if titles:
                for title in titles:
                    st.markdown(f"- {title}")
            else:
                st.caption("Nothing taught in this era yet.")

    open_threads = db.unexplored_web_nodes(student["id"], "history")
    if open_threads:
        st.subheader("Open threads")
        for node in open_threads:
            where = f" · {node['location']}" if node["location"] else ""
            st.markdown(f"- **{node['topic']}**{where} — <small>{node['rationale']}</small>",
                        unsafe_allow_html=True)
