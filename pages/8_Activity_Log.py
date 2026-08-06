"""The instructional record: every logged activity, plus manual entry."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from compass import config
from compass.subjects import SUBJECT_KEYS, label
from compass.ui import page_setup, parent_only

db, student = page_setup("Activity Log", icon="🗂️")

if not parent_only("The hours record is for your parent."):
    st.stop()

st.title("🗂️ Activity Log")
st.caption(
    "Every hour that counts. Activities created from agent lessons land here "
    "automatically; anything else can be logged by hand."
)

log_tab, add_tab, lessons_tab = st.tabs(["The record", "Log something manually", "Generated lessons"])

with log_tab:
    columns = st.columns([1, 1, 2])
    start = columns[0].date_input("From", value=date.today() - timedelta(days=30))
    end = columns[1].date_input("To", value=date.today())

    activities = db.list_activities(student["id"], start=start.isoformat(), end=end.isoformat())

    if not activities:
        st.info("Nothing logged in this range.")
    else:
        total = sum(a["minutes"] for a in activities)
        metrics = st.columns(3)
        metrics[0].metric("Activities", len(activities))
        metrics[1].metric("Hours", round(total / 60, 1))
        metrics[2].metric("Days", len({a["occurred_on"] for a in activities}))

        for activity in activities:
            with st.container(border=True):
                columns = st.columns([5, 1])
                where = f" · {activity['location']}" if activity["location"] else ""
                columns[0].markdown(
                    f"**{activity['occurred_on']} — {activity['title']}** "
                    f"({activity['minutes']} min){where}"
                )
                columns[0].caption(
                    f"{config.TIER_LABELS.get(activity['tier'], activity['tier'])} · "
                    f"source: {activity['source']}"
                )
                if activity["description"]:
                    columns[0].caption(activity["description"])
                credits = " · ".join(
                    f"{label(s)} {m}m" for s, m in activity["credits"].items()
                )
                columns[0].markdown(f"<small>Credit: {credits}</small>", unsafe_allow_html=True)
                if columns[1].button("Delete", key=f"del_act_{activity['id']}"):
                    db.delete_activity(activity["id"])
                    st.rerun()

with add_tab:
    st.subheader("Log an activity by hand")
    st.caption(
        "Total minutes count toward the 1,000-hour floor. Add a second or third subject "
        "credit when the activity genuinely taught it."
    )
    with st.form("manual_log", clear_on_submit=True):
        columns = st.columns([2, 1, 1])
        title = columns[0].text_input("What was it?")
        occurred_on = columns[1].date_input("Date", value=date.today())
        minutes = columns[2].number_input(
            "Total minutes", min_value=5, max_value=600, value=60, step=15
        )

        columns = st.columns([1, 1, 2])
        tier = columns[0].selectbox(
            "Tier", config.TIERS, format_func=lambda t: config.TIER_LABELS[t]
        )
        primary = columns[1].selectbox("Primary subject", SUBJECT_KEYS, format_func=label)
        location = columns[2].text_input("Location (optional)")

        description = st.text_area("Description", height=80)

        st.markdown("**Subject credit**")
        st.caption("Leave a subject at 0 to skip it. The primary subject is filled in for you.")
        credits: dict[str, int] = {}
        credit_columns = st.columns(3)
        for index, subject_key in enumerate(SUBJECT_KEYS):
            with credit_columns[index % 3]:
                credits[subject_key] = st.number_input(
                    label(subject_key),
                    min_value=0,
                    max_value=600,
                    value=0,
                    step=15,
                    key=f"manual_credit_{subject_key}",
                )

        if st.form_submit_button("Log it", type="primary") and title.strip():
            selected = {k: v for k, v in credits.items() if v > 0}
            if primary not in selected:
                selected[primary] = int(minutes)
            db.log_activity(
                student_id=student["id"],
                title=title.strip(),
                tier=tier,
                primary_subject=primary,
                minutes=int(minutes),
                subject_credits=selected,
                occurred_on=occurred_on.isoformat(),
                description=description.strip(),
                source="manual",
                location=location.strip(),
            )
            st.success("Logged.")
            st.rerun()

with lessons_tab:
    st.subheader("Generated lessons")
    st.caption("Everything the agents have written, whether or not it's been logged yet.")
    lessons = db.list_lessons(student["id"], limit=50)
    if not lessons:
        st.info("No lessons generated yet.")
    for lesson in lessons:
        badge = {"planned": "🕓 planned", "completed": "✅ completed", "skipped": "⏭️ skipped"}[
            lesson["status"]
        ]
        with st.expander(f"{badge} · {lesson['created_at'][:10]} · {lesson['title']}"):
            st.caption(
                f"{lesson['agent']} agent · strategy: {lesson['strategy']} · "
                f"topic: {lesson['topic']}"
            )
            if lesson["rationale"]:
                st.caption(f"Why: {lesson['rationale']}")
            st.write(lesson["payload"].get("overview", ""))
            credits = lesson["payload"].get("subject_credits") or []
            if credits:
                st.markdown(
                    "Credit: "
                    + " · ".join(f"{label(c['subject'])} {c['minutes']}m" for c in credits)
                )
            if lesson["status"] == "planned":
                if st.button("Mark skipped", key=f"skip_{lesson['id']}"):
                    db.set_lesson_status(lesson["id"], "skipped")
                    st.rerun()
