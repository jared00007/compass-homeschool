"""The instructional record: every logged activity, plus manual entry."""

from __future__ import annotations

from datetime import date, timedelta
from functools import partial

import streamlit as st

from compass import config
from compass.agents.framework import GeneratedLesson, TopicProposal
from compass.export import lesson_to_docx, suggested_filename
from compass.subjects import SUBJECT_KEYS, label
from compass.ui import log_lesson_form, md, page_setup, parent_only

db, student = page_setup("Activity Log", icon="🗂️")

if not parent_only("The hours record is for your parent."):
    st.stop()

st.title("🗂️ Activity Log")
st.caption(
    "Every hour that counts. Activities created from agent lessons land here "
    "automatically; anything else can be logged by hand."
)

all_lessons = db.list_lessons(student["id"], limit=50)
to_review = [l for l in all_lessons if l["status"] == "planned"]
history = [l for l in all_lessons if l["status"] != "planned"]
# Stable sort: lessons he's already marked done float to the top of "to review"
# since they're the most time-sensitive -- he's waiting on you, not the other
# way around. Relative order within each group (most recent first) is preserved.
to_review.sort(key=lambda l: 0 if (l.get("metadata") or {}).get("student_done_on") else 1)

log_tab, add_tab, lessons_tab = st.tabs(
    ["The record", "Log something manually", f"To review ({len(to_review)})"]
)

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
                    f"**{activity['occurred_on']} — {md(activity['title'])}** "
                    f"({activity['minutes']} min){where}"
                )
                columns[0].caption(
                    f"{config.tier_label(activity['tier'], student['name'])} · "
                    f"source: {activity['source']}"
                )
                if activity["description"]:
                    columns[0].caption(md(activity["description"]))
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
            "Tier", config.TIERS, format_func=lambda t: config.tier_label(t, student["name"])
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
    st.subheader("To review")
    st.caption(
        "Lessons nothing has been logged for yet. Lessons he's already marked done as "
        "finished sort to the top — those are waiting on you."
    )
    show_history = st.checkbox("Also show completed and skipped lessons")
    visible = to_review + history if show_history else to_review

    if not all_lessons:
        st.info("No lessons generated yet.")
    elif not visible:
        st.success("Nothing waiting on you right now.")

    badge_map = {"planned": "🕓 planned", "completed": "✅ completed", "skipped": "⏭️ skipped"}
    for lesson in visible:
        student_done_on = (lesson.get("metadata") or {}).get("student_done_on")
        if lesson["status"] == "planned" and student_done_on:
            badge = "🎓 he's done — needs logging"
        else:
            badge = badge_map[lesson["status"]]
        with st.expander(f"{badge} · {lesson['created_at'][:10]} · {md(lesson['title'])}"):
            st.caption(
                f"{lesson['agent']} agent · strategy: {lesson['strategy']} · "
                f"topic: {md(lesson['topic'])}"
            )
            if lesson["rationale"]:
                st.caption(f"Why: {md(lesson['rationale'])}")
            if student_done_on and lesson["status"] != "completed":
                st.caption(f"🎓 He marked this done on {student_done_on} — not logged yet.")
            quiz_result = (lesson.get("metadata") or {}).get("quiz_result")
            if quiz_result and quiz_result.get("total"):
                pct = round(100 * quiz_result["correct"] / quiz_result["total"])
                verdict = "🎯 passed" if quiz_result.get("passed") else "below the pass threshold"
                st.caption(
                    f"📝 Quiz: {quiz_result['correct']}/{quiz_result['total']} ({pct}%) — "
                    f"{verdict}, graded {quiz_result.get('graded_on', '?')}"
                )
            st.write(md(lesson["payload"].get("overview", "")))
            credits = lesson["payload"].get("subject_credits") or []
            if credits:
                st.markdown(
                    "Credit: "
                    + " · ".join(f"{label(c['subject'])} {c['minutes']}m" for c in credits)
                )
            st.download_button(
                "📄 Download as Word doc",
                data=partial(lesson_to_docx, lesson["payload"]),
                file_name=suggested_filename(lesson["payload"]),
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                key=f"docx_{lesson['id']}",
            )
            if lesson["status"] == "planned":
                st.divider()
                generated = GeneratedLesson(
                    lesson_id=lesson["id"],
                    proposal=TopicProposal(
                        topic=lesson["topic"],
                        rationale=lesson["rationale"],
                        strategy=lesson["strategy"],
                    ),
                    payload=lesson["payload"],
                    warnings=[],
                )
                tier = (
                    config.TIER_LIFE_SKILLS
                    if lesson["agent"] == "life_skills"
                    else config.TIER_CORE
                )
                log_lesson_form(
                    db,
                    student,
                    generated,
                    source=lesson["agent"],
                    primary_subject=lesson["subject"],
                    key_prefix=f"activitylog_{lesson['id']}",
                    tier=tier,
                )
                skip_col, remove_col = st.columns(2)
                if skip_col.button("Mark skipped instead", key=f"skip_{lesson['id']}"):
                    db.set_lesson_status(lesson["id"], "skipped")
                    st.rerun()
                # Distinct from "skipped": skipped keeps the record (he was offered
                # this and it didn't happen); remove is for a lesson that shouldn't
                # exist at all, like an accidental double-generate of the same topic.
                if remove_col.button("Remove", key=f"remove_lesson_{lesson['id']}"):
                    db.delete_lesson(lesson["id"])
                    st.rerun()
