"""Tier 3 — freedom of choice. A plain feature; deliberately no agent.

The whole point of this tier is that the topic selection is his, not an agent's
"optimal next step". Compass tracks the hours and gets out of the way.
"""

from __future__ import annotations

from datetime import date

import streamlit as st

from compass import config
from compass.subjects import SUBJECT_KEYS, label
from compass.ui import is_parent, page_setup

db, student = page_setup("Choice Topics", icon="⭐")

st.title(f"⭐ {config.tier_label(config.TIER_CHOICE, student['name'])}")
st.caption(
    "A running list he curates, with light parent approval. No prerequisite logic, no "
    "agent picking the 'optimal' next step — this is the counterweight to Tier 1's "
    "structure. Hours still count."
)

STATUS_FLOW = {
    "proposed": ("Approve", "approved"),
    "approved": ("Start", "active"),
    "active": ("Mark done", "done"),
}

tab_labels = ["The list"] + (["Log time"] if is_parent() else [])
tabs = st.tabs(tab_labels)
add_tab = tabs[0]
log_tab = tabs[1] if is_parent() else None

with add_tab:
    with st.form("add_choice", clear_on_submit=True):
        st.markdown("**Add a topic** — he can add straight to the list; approval is separate.")
        columns = st.columns([2, 1, 1])
        title = columns[0].text_input("What do you want to learn?")
        category = columns[1].text_input("Category", placeholder="e.g. coding, music, cars")
        credit_subject = columns[2].selectbox(
            "Credits toward",
            SUBJECT_KEYS,
            index=SUBJECT_KEYS.index("occupational_education"),
            format_func=label,
        )
        description = st.text_area("Anything else about it?", height=80)
        if st.form_submit_button("Add to the list", type="primary") and title.strip():
            db.add_choice_topic(
                student["id"],
                title.strip(),
                description.strip(),
                category.strip(),
                credit_subject,
            )
            st.rerun()

    topics = db.list_choice_topics(student["id"])
    if not topics:
        st.info("The list is empty. Add whatever he's into this week.")

    for topic in topics:
        with st.container(border=True):
            columns = st.columns([4, 1, 1])
            badge = {
                "proposed": "🕓 proposed",
                "approved": "👍 approved",
                "active": "🔥 active",
                "done": "✅ done",
                "declined": "🚫 declined",
            }[topic["status"]]
            category = f" · *{topic['category']}*" if topic["category"] else ""
            columns[0].markdown(f"**{topic['title']}**{category} — {badge}")
            if topic["description"]:
                columns[0].caption(topic["description"])
            columns[0].caption(f"Credits toward {label(topic['credit_subject'])}")
            if topic["parent_note"]:
                columns[0].caption(f"Parent: {topic['parent_note']}")

            action = STATUS_FLOW.get(topic["status"])
            if action and columns[1].button(action[0], key=f"advance_{topic['id']}"):
                db.set_choice_status(topic["id"], action[1])
                st.rerun()
            if topic["status"] == "proposed":
                if columns[2].button("Decline", key=f"decline_{topic['id']}"):
                    db.set_choice_status(topic["id"], "declined")
                    st.rerun()
            elif columns[2].button("Remove", key=f"remove_{topic['id']}"):
                db.delete_choice_topic(topic["id"])
                st.rerun()

if log_tab is not None:
  with log_tab:
    st.subheader("Log time on a choice topic")
    st.caption(
        "These hours count toward the 1,000-hour floor in full. The compliance page "
        "shows Tier 3's share against the family guideline — a warning, never a block."
    )
    active = [
        t for t in db.list_choice_topics(student["id"]) if t["status"] in ("approved", "active", "done")
    ]
    if not active:
        st.info("Approve a topic first and it'll show up here.")
    else:
        with st.form("log_choice"):
            topic = st.selectbox(
                "Topic", active, format_func=lambda t: f"{t['title']} ({t['status']})"
            )
            columns = st.columns(3)
            occurred_on = columns[0].date_input("Date", value=date.today())
            minutes = columns[1].number_input(
                "Minutes", min_value=5, max_value=600, value=60, step=15
            )
            credit_subject = columns[2].selectbox(
                "Credits toward",
                SUBJECT_KEYS,
                index=SUBJECT_KEYS.index(topic["credit_subject"])
                if topic["credit_subject"] in SUBJECT_KEYS
                else SUBJECT_KEYS.index("occupational_education"),
                format_func=label,
            )
            note = st.text_input("What did he actually do?")
            if st.form_submit_button("Log hours", type="primary"):
                db.log_activity(
                    student_id=student["id"],
                    title=topic["title"],
                    tier=config.TIER_CHOICE,
                    primary_subject=credit_subject,
                    minutes=int(minutes),
                    subject_credits={credit_subject: int(minutes)},
                    occurred_on=occurred_on.isoformat(),
                    description=note,
                    source="choice",
                )
                if topic["status"] == "approved":
                    db.set_choice_status(topic["id"], "active")
                st.success("Logged.")
                st.rerun()
