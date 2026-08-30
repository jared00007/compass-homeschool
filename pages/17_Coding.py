"""Coding Camp -- a parent-maintained checklist, same shape as Core Life
Skills throughout (its own table, its own catalog, the same active/backlog
gate and schedule/due model). Requested directly: "code camp, code games,
code use cases for a teenager to make it fun" -- every module in the
starter catalog is framed around something he'd actually want to build or
show off, not an abstract exercise.

Deliberately not agentic, same reasoning Life Skills' own page gives: you
decide what he builds here, not a model. No "plan a session" agent tab
either, at least not yet -- v1 is the checklist itself.
"""

from __future__ import annotations

from datetime import date

import streamlit as st

from compass import config
from compass.subjects import SUBJECT_KEYS, label
from compass.ui import (
    is_parent,
    page_setup,
    render_coding_module_cards,
    render_coding_module_catalog_manager,
)

db, student = page_setup("Coding", icon="💻")

st.title("💻 Coding Camp")
st.caption(
    "Games, automations, and things worth showing off -- **you** decide what he "
    "builds here, there's no agent picking the next module. The checklist unlocks "
    "gradually: *Master list* is where you release more, at whatever pace fits the year."
)

modules = db.list_coding_modules(student["id"])

if not modules:
    st.info("No checklist yet.")
    if st.button("Seed the starter catalog", type="primary"):
        count = db.seed_coding_modules(student["id"])
        st.success(f"Added {count} modules to the master list.")
        st.rerun()

if is_parent():
    checklist_tab, log_tab, master_tab, manage_tab = st.tabs(
        ["Checklist", "Log time", "Master list", "Add a module"]
    )
else:
    checklist_tab = st.container()
    log_tab = master_tab = manage_tab = None

with checklist_tab:
    render_coding_module_cards(db, modules, can_edit=is_parent())

if log_tab is not None:
  with log_tab:
    st.subheader("Log time on a coding module")
    st.caption(
        "Occupational education is one of the eleven required subjects, and most "
        "modules here credit it -- a few, where the real work is design or real "
        "numbers, credit art & music or math instead."
    )
    if not modules:
        st.info("Add or seed the checklist first.")
    else:
        with st.form("log_coding_module"):
            module = st.selectbox(
                "Module", modules, format_func=lambda m: f"{m['category']} — {m['title']}"
            )
            columns = st.columns(3)
            occurred_on = columns[0].date_input("Date", value=date.today())
            minutes = columns[1].number_input(
                "Minutes", min_value=5, max_value=600, value=45, step=15
            )
            credit_subject = columns[2].selectbox(
                "Credits toward",
                SUBJECT_KEYS,
                index=SUBJECT_KEYS.index(module["credit_subject"])
                if module["credit_subject"] in SUBJECT_KEYS
                else SUBJECT_KEYS.index("occupational_education"),
                format_func=label,
            )
            note = st.text_input("What did he build or work on?")
            mark_done = st.checkbox("Mark this module done", value=False)
            if st.form_submit_button("Log hours", type="primary"):
                db.log_activity(
                    student_id=student["id"],
                    title=module["title"],
                    tier=config.TIER_CODING,
                    primary_subject=credit_subject,
                    minutes=int(minutes),
                    subject_credits={credit_subject: int(minutes)},
                    occurred_on=occurred_on.isoformat(),
                    description=note,
                    source="coding",
                )
                if mark_done:
                    db.set_coding_module_done(module["id"], True, note)
                # No rerun here on purpose -- the form submit already causes
                # one, and an extra manual one right after st.success() wipes
                # the confirmation before it ever renders.
                st.success("Logged.")

if master_tab is not None:
  with master_tab:
    st.caption(
        "Everything Compass knows how to show him, unlocked or not. Turn one on and "
        "it shows up on the checklist immediately -- nothing here picks for you, "
        "this is purely the pace control."
    )
    if not modules:
        st.info("Seed or add a module first -- there's nothing to manage yet.")
    else:
        render_coding_module_catalog_manager(db, modules)

if manage_tab is not None:
  with manage_tab:
    with st.form("add_coding_module", clear_on_submit=True):
        columns = st.columns([1, 2, 1])
        category = columns[0].text_input("Category", value="General")
        title = columns[1].text_input("Module")
        credit_subject = columns[2].selectbox(
            "Credits toward",
            SUBJECT_KEYS,
            index=SUBJECT_KEYS.index("occupational_education"),
            format_func=label,
        )
        description = st.text_area(
            "The idea -- what does he build, and what does 'done' look like?", height=80
        )
        materials = st.text_input(
            "What you'll need (optional)", placeholder="e.g. a laptop, Python, replit.com"
        )
        if st.form_submit_button("Add module", type="primary") and title.strip():
            db.add_coding_module(
                student["id"],
                title.strip(),
                category.strip() or "General",
                description.strip(),
                credit_subject,
                materials.strip(),
            )
            st.rerun()

    st.caption(
        "Nothing here chooses modules for you, and that's deliberate -- you know "
        "your family and a model doesn't."
    )
