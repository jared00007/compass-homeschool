"""Math Agent — prerequisite graph walk."""

from __future__ import annotations

import streamlit as st

from compass.agents import get_agent
from compass.curriculum import (
    MATH_GRAPH,
    STRANDS,
    available_skills,
    frontier_report,
    missing_prerequisites,
    prerequisite_chain,
)
from compass.ui import (
    api_status_banner,
    context_for,
    difficulty_override_control,
    generate_and_log,
    is_parent,
    page_setup,
    render_past_lessons,
    render_proposal,
    render_subject_week_tab,
    student_lesson_view,
)

db, student = page_setup("Math", icon="📐")
agent = get_agent("math")

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

week_tab, plan_tab, mastery_tab, graph_tab = st.tabs(
    ["This week", "Plan a lesson", "Record mastery", "The graph"]
)

# --- this week's (and next's) own board, scoped to Math ------------------------

with week_tab:
    render_subject_week_tab(db, student, "math")

# --- plan --------------------------------------------------------------------

with plan_tab:
    api_ok = api_status_banner()

    ready_ids = {s.id for s in ready}
    # Any 8th-grade skill can be chosen, not just the ones the graph has
    # unlocked -- a parent can deliberately teach out of sequence (reported: for
    # math "i couldnt chose the lesson to generate. it was linear"). The lock
    # marker still shows the graph's recommendation; a locked pick just asks for
    # a confirming tick before it'll generate.
    LET_AGENT = "Let the agent choose"
    all_skills = sorted(MATH_GRAPH.values(), key=lambda s: (s.strand, s.title))

    def _skill_label(skill) -> str:
        if skill.id in mastered:
            marker = "✅"
        elif skill.id in ready_ids:
            marker = "🔓"
        else:
            marker = "🔒"
        return f"{marker} {skill.title} — {STRANDS[skill.strand]}"

    columns = st.columns([2, 1, 1])
    with columns[0]:
        choice = st.selectbox(
            "Skill",
            [LET_AGENT] + all_skills,
            format_func=lambda o: o if isinstance(o, str) else _skill_label(o),
            help="🔓 unlocked · ✅ mastered · 🔒 prerequisites not all met (you can still pick it).",
        )
    with columns[1]:
        minutes = st.number_input("Minutes", min_value=15, max_value=180, value=60, step=5)
    with columns[2]:
        st.metric("Unlocked now", len(ready))

    parent_note = st.text_input(
        "Note for this lesson (optional)",
        placeholder="e.g. he struggled with negative signs last time",
    )
    difficulty = difficulty_override_control(db, key="math_difficulty")

    skill_id = ""
    override_prereqs = False
    if choice != LET_AGENT:
        skill_id = choice.id
        locked_missing = missing_prerequisites(skill_id, mastered)
        if locked_missing and skill_id not in mastered:
            st.warning(
                f"**{choice.title}** is out of sequence — these prerequisites aren't "
                "mastered yet: "
                + ", ".join(MATH_GRAPH[m].title for m in locked_missing)
                + ". You can still teach it now; the lesson will scaffold what it leans on."
            )
            override_prereqs = st.checkbox(
                "Generate it anyway (out of sequence)",
                key="math_override_prereqs",
            )

    ctx = context_for(
        db,
        student,
        minutes=minutes,
        parent_note=parent_note,
        skill_id=skill_id,
        override_prereqs=override_prereqs,
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
        primary_subject="math",
        spinner="The Math Agent is writing the lesson…",
        api_ok=api_ok,
    )

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
