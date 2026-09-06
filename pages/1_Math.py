"""Math Agent — prerequisite graph walk."""

from __future__ import annotations

import streamlit as st

from compass.curriculum import (
    MATH_GRAPH,
    STRANDS,
    available_skills,
    frontier_report,
    missing_prerequisites,
    prerequisite_chain,
)
from compass.ui import (
    is_parent,
    page_setup,
    render_past_lessons,
    render_subject_week_tab,
    student_lesson_view,
)

db, student = page_setup("Math", icon="📐")

st.title("📐 Math Agent")
st.caption(
    "Walks a hand-authored 8th-grade prerequisite graph. A skill unlocks only when "
    "every prerequisite is mastered — the agent reasons over the graph, it does not "
    "invent it."
)

mastered = db.mastered_skills(student["id"])
mastery = db.mastery_map(student["id"])
frontier = frontier_report(mastered)
ready = available_skills(mastered)

# Student view: his lesson, without the answer key or the admin surface.
if not is_parent():
    student_lesson_view(db, student, "math", "math")
    render_past_lessons(db, student, "math", "math")
    st.stop()

week_tab, mastery_tab, graph_tab = st.tabs(
    ["This week", "Record mastery", "The graph"]
)

# --- this week's (and next's) own board, scoped to Math ------------------------

with week_tab:
    render_subject_week_tab(db, student, "math")
    st.caption("✍️ Generate new lessons from **Mission Control → Plan a lesson**.")

# --- mastery -----------------------------------------------------------------

with mastery_tab:
    st.subheader("Record mastery")
    st.caption(
        "This is the only thing that unlocks the next node. Record it after he does the "
        "assessment — the agent reads this, not the lesson history."
    )

    all_skills = sorted(MATH_GRAPH.values(), key=lambda s: (s.strand, s.title))
    target = st.selectbox(
        "Skill",
        all_skills,
        format_func=lambda s: f"{s.title} — {STRANDS[s.strand]}",
    )

    missing = missing_prerequisites(target.id, mastered)
    if missing:
        st.warning(
            "Locked. Unmastered prerequisites: "
            + ", ".join(MATH_GRAPH[m].title for m in missing)
        )
        chain = prerequisite_chain(target.id, mastered)
        if chain:
            st.caption(
                "Teaching order to get there: "
                + " → ".join(MATH_GRAPH[c].title for c in chain)
            )

    current = mastery.get(target.id, {})
    with st.form("mastery_form"):
        columns = st.columns(3)
        with columns[0]:
            status_options = ["not_started", "in_progress", "mastered"]
            current_status = current.get("status", "not_started")
            status = st.selectbox(
                "Status",
                status_options,
                index=status_options.index(current_status)
                if current_status in status_options
                else 0,
            )
        with columns[1]:
            score = st.number_input(
                "Score (%)", min_value=0, max_value=100, value=int(current.get("score") or 0)
            )
        with columns[2]:
            st.markdown(f"**Strand**\n\n{STRANDS[target.strand]}")
        notes = st.text_area("Notes", value=current.get("notes", ""))
        if st.form_submit_button("Save mastery", type="primary"):
            db.set_mastery(
                student["id"],
                target.id,
                status,
                score=float(score) if score else None,
                notes=notes,
            )
            st.success(f"Recorded {target.title} as {status.replace('_', ' ')}.")
            st.rerun()

# --- graph -------------------------------------------------------------------

with graph_tab:
    columns = st.columns(3)
    columns[0].metric("Skills mastered", f"{frontier['mastered_count']} / {frontier['total_skills']}")
    columns[1].metric("Unlocked and ready", len(ready))
    columns[2].metric("Still locked", frontier["locked_count"])

    st.subheader("Progress by strand")
    for strand_key, strand_label in STRANDS.items():
        counts = frontier["by_strand"][strand_key]
        total = counts["total"] or 1
        st.progress(
            counts["mastered"] / total,
            text=f"{strand_label} — {counts['mastered']} / {counts['total']}",
        )

    st.subheader("Full scope and sequence")
    st.caption(
        "Hand-authored and version-controlled, so it can be handed to a district as the "
        "year's documented math plan."
    )
    for strand_key, strand_label in STRANDS.items():
        with st.expander(strand_label):
            for skill in [s for s in MATH_GRAPH.values() if s.strand == strand_key]:
                if skill.id in mastered:
                    marker = "✅"
                elif not missing_prerequisites(skill.id, mastered):
                    marker = "🔓"
                else:
                    marker = "🔒"
                prereqs = (
                    ", ".join(MATH_GRAPH[p].title for p in skill.prerequisites) or "none"
                )
                st.markdown(
                    f"{marker} **{skill.title}** — {skill.description}  \n"
                    f"<small>Prerequisites: {prereqs}</small>",
                    unsafe_allow_html=True,
                )
