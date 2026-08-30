"""Core life skills — a parent-maintained checklist, with an on-demand planner.

Distinct from the 11 required subjects and distinct from Tier 3 choice. The design
call here was: a simple checklist with completion tracking is enough. Don't build
this agentic by default — and nothing on this page decides *what* he learns next.
That stays with the parent, because they know their family and a model does not.

The one thing the model earns a call for is the blank page *after* that decision:
turning a skill the parent already picked into a session they could actually run.
"""

from __future__ import annotations

from datetime import date

import streamlit as st

from compass import config
from compass.agents.life_skills import LifeSkillPlan, generate_plan
from compass.agents.llm import LessonGenerationError
from compass.subjects import SUBJECT_KEYS, label
from compass.ui import (
    api_status_banner,
    is_parent,
    log_lesson_form,
    page_setup,
    render_choice_topics_section,
    render_life_skill_cards,
    render_life_skill_catalog_manager,
    render_life_skill_plan,
)

db, student = page_setup("Life Skills", icon="🛠️")

st.title("🛠️ Core Life Skills")
st.caption(
    "Budgeting, cooking, vehicle basics, communication. **You** decide what he learns "
    "here — there's no agent picking the next skill. The checklist unlocks gradually: "
    "*Master list* is where you release more, at whatever pace fits the year. **Student's "
    "Choice** (Tier 3) lives here too now -- a different flavor of the same idea, just "
    "with him curating the list instead of you."
)

skills = db.list_life_skills(student["id"])

if not skills:
    st.info("No checklist yet.")
    if st.button("Seed the starter checklist", type="primary"):
        count = db.seed_life_skills(student["id"])
        st.success(f"Added {count} skills to the master list — 15 unlocked to start.")
        st.rerun()

if is_parent():
    checklist_tab, choice_tab, plan_tab, log_tab, master_tab, manage_tab = st.tabs(
        ["Checklist", "Student's Choice", "Plan a session", "Log time", "Master list", "Add a skill"]
    )
else:
    checklist_tab, choice_tab = st.container(), st.container()
    plan_tab = log_tab = master_tab = manage_tab = None

with checklist_tab:
    render_life_skill_cards(db, skills, can_edit=is_parent())

with choice_tab:
    if not is_parent():
        # No tab strip to label this section in student view (checklist_tab
        # and choice_tab are just two plain containers stacked on one page)
        # -- a header here is the only thing marking where one ends and the
        # other begins.
        st.divider()
        st.subheader("⭐ Student's Choice")
    render_choice_topics_section(db, student)

if plan_tab is not None:
  with plan_tab:
    st.caption(
        "You pick the skill; this only works out how to teach it — the order, the "
        "timing, what to demonstrate, where to stay quiet, and which of the eleven "
        "required subjects it honestly covers. It will never suggest a different skill."
    )
    if not skills:
        st.info("Add or seed the checklist first — there's nothing to plan yet.")
    else:
        api_ok = api_status_banner()
        # Default to what's still outstanding, but never hide a finished skill:
        # re-teaching one is a legitimate thing to want.
        open_skills = [s for s in skills if not s["completed_on"]] or skills

        columns = st.columns([2, 1, 1])
        with columns[0]:
            skill = st.selectbox(
                "Which skill",
                open_skills,
                format_func=lambda s: f"{s['category']} — {s['title']}",
                key="plan_skill",
            )
        with columns[1]:
            minutes = st.number_input(
                "Minutes", min_value=15, max_value=240, value=60, step=15, key="plan_minutes"
            )
        with columns[2]:
            where = st.text_input(
                "Where are you?", placeholder="optional", key="plan_where"
            )

        parent_note = st.text_input(
            "Anything it should know? (optional)",
            placeholder="e.g. he's watched me do this once — make him lead this time",
            key="plan_note",
        )
        research = st.checkbox(
            "Look things up first",
            key="plan_research",
            help=(
                "Slower, and roughly 15c dearer. Worth it for anything whose rules or "
                "prices change — permits, tax forms, insurance. Not for changing a tire."
            ),
        )
        st.caption(
            f"Hours will credit **{label(skill['credit_subject'])}** first. Change that "
            "on the skill itself if it's wrong."
        )

        saved = db.latest_life_skill_plan(student["id"], skill["id"])
        if saved:
            st.caption(f"A plan for this already exists, written {saved['created_at'][:10]}.")

        if st.button("Write a teaching plan", type="primary", disabled=not api_ok):
            with st.spinner("Working out how to teach this…"):
                try:
                    st.session_state["life_skill_plan"] = (
                        skill["id"],
                        generate_plan(
                            db,
                            student,
                            skill,
                            minutes=int(minutes),
                            parent_note=parent_note,
                            location=where,
                            use_web_search=research,
                        ),
                    )
                except LessonGenerationError as exc:
                    st.error(str(exc))
            st.rerun()

        cached = st.session_state.get("life_skill_plan")
        plan = None
        if cached and cached[0] == skill["id"]:
            plan = cached[1]
        elif saved:
            plan = LifeSkillPlan(lesson_id=saved["id"], payload=saved["payload"])

        if plan is not None:
            st.divider()
            for warning in plan.warnings:
                st.caption(f"⚠️ {warning}")
            render_life_skill_plan(plan.payload)
            st.divider()
            log_lesson_form(
                db,
                student,
                plan,
                source="life_skills",
                primary_subject=plan.payload["subject_credits"][0]["subject"],
                location=where,
                key_prefix="lifeskill",
                tier=config.TIER_LIFE_SKILLS,
            )
            if not skill["completed_on"] and st.button(
                "Mark this skill complete", key=f"plan_done_{skill['id']}"
            ):
                db.set_life_skill_done(skill["id"], True)
                st.rerun()

if log_tab is not None:
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
                # No rerun here on purpose -- the form submit already causes
                # one, and an extra manual one right after st.success() wipes
                # the confirmation before it ever renders.
                st.success("Logged.")

if master_tab is not None:
  with master_tab:
    st.caption(
        "Everything Compass knows how to show him, unlocked or not. Turn one on and it "
        "shows up on the checklist immediately — nothing here picks for you, this is "
        "purely the pace control."
    )
    if not skills:
        st.info("Seed or add a skill first — there's nothing to manage yet.")
    else:
        render_life_skill_catalog_manager(db, skills)

if manage_tab is not None:
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
        description = st.text_area("The story — what is this, and what does 'done' look like?", height=80)
        materials = st.text_input(
            "What you'll need (optional)", placeholder="e.g. a recipe, a grocery run, 90 minutes"
        )
        if st.form_submit_button("Add skill", type="primary") and title.strip():
            db.add_life_skill(
                student["id"],
                title.strip(),
                category.strip() or "General",
                description.strip(),
                credit_subject,
                materials.strip(),
            )
            st.rerun()

    st.caption(
        "Nothing here chooses skills for you, and that's deliberate — you know your "
        "family and a model doesn't. *Plan a session* only helps once you've chosen."
    )
