"""Core life skills — a parent-maintained checklist. Deliberately not agentic.

Distinct from the 11 required subjects and distinct from Tier 3 choice. The design
call here was: a simple checklist with completion tracking is enough. Don't build
this agentic by default.
"""

from __future__ import annotations

from datetime import date

import streamlit as st

from compass import config
from compass.subjects import SUBJECT_KEYS, label
from compass.ui import page_setup

db, student = page_setup("Life Skills", icon="🛠️")

st.title("🛠️ Core Life Skills")
st.caption(
    "Budgeting, cooking, vehicle basics, communication. Parent-defined, no agent — a "
    "checklist with completion tracking is enough for now."
)

skills = db.list_life_skills(student["id"])

if not skills:
    st.info("No checklist yet.")
    if st.button("Seed the starter checklist", type="primary"):
        count = db.seed_life_skills(student["id"])
        st.success(f"Added {count} starter skills.")
        st.rerun()

done = [s for s in skills if s["completed_on"]]
if skills:
    columns = st.columns(3)
    columns[0].metric("Skills complete", f"{len(done)} / {len(skills)}")
    columns[1].metric("Categories", len({s["category"] for s in skills}))
    columns[2].progress(len(done) / len(skills), text="Overall")

checklist_tab, log_tab, manage_tab = st.tabs(["Checklist", "Log time", "Add a skill"])

with checklist_tab:
    by_category: dict[str, list[dict]] = {}
    for skill in skills:
        by_category.setdefault(skill["category"], []).append(skill)

    for category, items in by_category.items():
        complete = sum(1 for i in items if i["completed_on"])
        st.subheader(f"{category} — {complete}/{len(items)}")
        for skill in items:
            columns = st.columns([5, 1])
            checked = columns[0].checkbox(
                skill["title"],
                value=bool(skill["completed_on"]),
                key=f"skill_{skill['id']}",
                help=skill["description"] or None,
            )
            if checked != bool(skill["completed_on"]):
                db.set_life_skill_done(skill["id"], checked)
                st.rerun()
            if skill["completed_on"]:
                columns[0].caption(f"Completed {skill['completed_on']}")
            if columns[1].button("Remove", key=f"del_skill_{skill['id']}"):
                db.delete_life_skill(skill["id"])
                st.rerun()

with log_tab:
    st.subheader("Log time on a life skill")
    st.caption(
        "Health and occupational education are two of the eleven required subjects, and "
        "this track is where most of that coverage genuinely comes from."
    )
    if not skills:
        st.info("Add or seed the checklist first.")
    else:
        with st.form("log_life_skill"):
            skill = st.selectbox(
                "Skill", skills, format_func=lambda s: f"{s['category']} — {s['title']}"
            )
            columns = st.columns(3)
            occurred_on = columns[0].date_input("Date", value=date.today())
            minutes = columns[1].number_input(
                "Minutes", min_value=5, max_value=600, value=45, step=15
            )
            credit_subject = columns[2].selectbox(
                "Credits toward",
                SUBJECT_KEYS,
                index=SUBJECT_KEYS.index(skill["credit_subject"])
                if skill["credit_subject"] in SUBJECT_KEYS
                else SUBJECT_KEYS.index("occupational_education"),
                format_func=label,
            )
            note = st.text_input("What did he do?")
            mark_done = st.checkbox("Mark this skill complete", value=False)
            if st.form_submit_button("Log hours", type="primary"):
                db.log_activity(
                    student_id=student["id"],
                    title=skill["title"],
                    tier=config.TIER_LIFE_SKILLS,
                    primary_subject=credit_subject,
                    minutes=int(minutes),
                    subject_credits={credit_subject: int(minutes)},
                    occurred_on=occurred_on.isoformat(),
                    description=note,
                    source="life_skills",
                )
                if mark_done:
                    db.set_life_skill_done(skill["id"], True, note)
                st.success("Logged.")
                st.rerun()

with manage_tab:
    with st.form("add_life_skill", clear_on_submit=True):
        columns = st.columns([1, 2, 1])
        category = columns[0].text_input("Category", value="General")
        title = columns[1].text_input("Skill")
        credit_subject = columns[2].selectbox(
            "Credits toward",
            SUBJECT_KEYS,
            index=SUBJECT_KEYS.index("occupational_education"),
            format_func=label,
        )
        description = st.text_area("What does 'done' look like?", height=80)
        if st.form_submit_button("Add skill", type="primary") and title.strip():
            db.add_life_skill(
                student["id"],
                title.strip(),
                category.strip() or "General",
                description.strip(),
                credit_subject,
            )
            st.rerun()

    if skills and not any(s["completed_on"] for s in skills):
        st.caption(
            "Revisit whether this track needs agentic generation later. It does not today."
        )
