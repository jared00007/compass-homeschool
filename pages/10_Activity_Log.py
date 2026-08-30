"""The instructional record: every logged activity, plus manual entry."""

from __future__ import annotations

from datetime import date, timedelta
from functools import partial

import streamlit as st

from compass import config, gradebook, weekly
from compass.agents.framework import GeneratedLesson, TopicProposal
from compass.export import lesson_to_docx, suggested_filename
from compass.subjects import SUBJECT_KEYS, label
from compass.ui import log_lesson_form, md, page_setup, parent_only, render_assessment_card

db, student = page_setup("Activity Log", icon="🗂️")

if not parent_only("The hours record is for your parent."):
    st.stop()

st.title("🗂️ Activity Log")
st.caption(
    "Every hour that counts. Activities created from agent lessons land here "
    "automatically; anything else can be logged by hand."
)

def _lesson_date(lesson: dict) -> str:
    """The date that actually matters for review: the day a lesson is
    *planned for*, if it was batch-planned -- not when it happened to be
    generated. Those agree for an ordinary on-demand lesson, but not once
    a whole week gets batch-planned in one sitting: every lesson in that
    batch shares the same created_at, which tells you nothing about which
    day each one is actually for."""
    return (lesson.get("metadata") or {}).get("planned_for") or lesson["created_at"][:10]


def _needs_attention(lesson: dict, today_iso: str) -> bool:
    """Genuinely waiting on you: he's turned it in, or it's overdue and
    still untouched -- but only within its own week. Once that week ends
    it's backlogged instead (see the Backlog section below): out of his
    own view entirely, and no longer something today's date should keep
    flagging as urgent. A lesson sent back for revision ('needs_revision')
    is waiting on HIM, not you -- it gets its own quieter section below
    rather than being counted here."""
    if lesson["status"] == "submitted":
        return True
    planned_for = (lesson.get("metadata") or {}).get("planned_for")
    if not planned_for or planned_for >= today_iso:
        return False
    return not weekly.is_backlogged(lesson, today_iso)


def _review_badge(lesson: dict, today_iso: str) -> str:
    if lesson["status"] != "planned":
        return {
            "completed": "✅ completed",
            "skipped": "⏭️ skipped",
            "submitted": "📤 waiting on you to review",
            "needs_revision": "↩️ sent back — waiting on him",
        }[lesson["status"]]
    # Sent there on purpose, distinct from a lesson whose own week simply
    # ran out -- it may not even be overdue yet, so falling through to the
    # checks below could show a wrong "overdue" badge on something a
    # parent chose to park ahead of its due date.
    if (lesson.get("metadata") or {}).get("held_back"):
        return "🗄️ backlogged"
    planned_for = (lesson.get("metadata") or {}).get("planned_for")
    if planned_for and planned_for < today_iso:
        return "⚠️ overdue"
    return "🕓 planned"


def _render_review_card(
    lesson: dict, today_iso: str, *, show_reschedule: bool = False
) -> None:
    """One lesson's expander: badge + planned date + title as the header,
    full detail and the logging form inside. Shared by the attention
    list, every day column, the unscheduled section, backlog, and
    history -- the only thing that changes between them is which bucket a
    lesson lands in (and, for backlog, one extra action), never how it's
    rendered once it's there."""
    student_done_on = (lesson.get("metadata") or {}).get("student_done_on")
    badge = _review_badge(lesson, today_iso)
    with st.expander(f"{badge} · {_lesson_date(lesson)} · {md(lesson['title'])}"):
        st.caption(
            f"{lesson['agent']} agent · strategy: {lesson['strategy']} · "
            f"topic: {md(lesson['topic'])}"
        )
        if lesson["rationale"]:
            st.caption(f"Why: {md(lesson['rationale'])}")
        if student_done_on and lesson["status"] == "submitted":
            st.caption(f"🎓 He turned this in on {student_done_on}.")
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
        render_assessment_card(db, student, lesson, key_prefix=f"activitylog_{lesson['id']}")
        # For a graded subject, hours only ever get logged through the
        # combined Approve action inside render_assessment_card above --
        # there's nothing to log from 'planned' (nothing turned in yet).
        # This plain form stays for Life Skills and anything else that
        # never goes through the submit/review gate.
        if lesson["status"] == "planned" and lesson["agent"] not in gradebook.GRADED_AGENTS:
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
        if lesson["status"] in ("planned", "submitted", "needs_revision"):
            st.divider()
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
            # The freedom to move a story into the backlog whenever a parent
            # decides, not only once its own week has quietly run out --
            # never offered on one already there (that's what "Move to"
            # below is for).
            if lesson["status"] == "planned" and not weekly.is_backlogged(lesson, today_iso):
                if st.button("🗄️ Send to backlog", key=f"send_to_backlog_{lesson['id']}"):
                    db.send_to_backlog(lesson["id"])
                    st.rerun()
            # Backlog only -- an already-live lesson doesn't need this, it's
            # already showing up on whatever day it's for.
            if show_reschedule and lesson["status"] == "planned":
                move_columns = st.columns([3, 1])
                new_date = move_columns[0].date_input(
                    "Move to",
                    value=date.today() + timedelta(days=1),
                    min_value=date.today(),
                    key=f"reschedule_date_{lesson['id']}",
                )
                # Same agent, same target day, a different lesson already
                # sitting there -- moving this one in would silently shadow
                # it (latest_per_day keeps whichever lesson is newest), so
                # the move is refused rather than letting that happen quietly.
                collision = any(
                    other["agent"] == lesson["agent"]
                    and other["id"] != lesson["id"]
                    and (other.get("metadata") or {}).get("planned_for") == new_date.isoformat()
                    for other in all_lessons
                )
                if collision:
                    move_columns[1].button(
                        "Move", key=f"reschedule_{lesson['id']}", disabled=True
                    )
                    st.caption(
                        f"⚠️ Already a {lesson['agent']} lesson planned for that day -- "
                        "pick a different one."
                    )
                elif move_columns[1].button("Move", key=f"reschedule_{lesson['id']}"):
                    db.reschedule_lesson(lesson["id"], new_date.isoformat())
                    st.rerun()


_TRAVEL_REVIEW_BADGES = {
    "submitted": "📤 waiting on you to review",
    "needs_revision": "↩️ sent back — waiting on him",
}


def _render_travel_review_card(entry: dict) -> None:
    """A submitted (or sent-back) travel entry, reviewable right here --
    same Approve/Send back actions as pages/9_Landons_Travels.py, so a
    trip waiting on you doesn't only show up if you happen to visit that
    page. Approving logs the same flat Writing/Social Studies credit it
    always has."""
    badge = _TRAVEL_REVIEW_BADGES[entry["status"]]
    title = entry["title"] or entry["state"] or "Untitled trip"
    with st.expander(f"{badge} · {entry['visited_on']} · 🧭 {md(title)}"):
        if entry["story"]:
            st.write(md(entry["story"]))
        if entry["status"] == "needs_revision" and entry["revision_note"].strip():
            st.caption(f"You sent this back: {md(entry['revision_note'].strip())}")
        if entry["status"] == "submitted":
            feedback_note = st.text_area(
                "Feedback (optional, shown to him)",
                key=f"activitylog_approve_feedback_{entry['id']}",
                height=200,
                placeholder="e.g. Great detail about the hike -- loved reading this one.",
            )
            review_columns = st.columns([1, 1, 4])
            if review_columns[0].button(
                "✅ Approve", key=f"activitylog_approve_travel_{entry['id']}", type="primary"
            ):
                db.approve_travel_entry(entry["id"], feedback_note.strip())
                st.rerun()
            reviewing = st.session_state.get("activitylog_reviewing_travel") == entry["id"]
            if review_columns[1].button(
                "Cancel" if reviewing else "↩️ Send back",
                key=f"activitylog_bounce_travel_{entry['id']}",
            ):
                st.session_state["activitylog_reviewing_travel"] = (
                    None if reviewing else entry["id"]
                )
                st.rerun()
            if reviewing:
                with st.form(f"activitylog_send_back_travel_{entry['id']}"):
                    note = st.text_input(
                        "What should he fix or add?",
                        placeholder="e.g. more detail on what you actually did there",
                    )
                    if st.form_submit_button("Send back", type="primary"):
                        db.send_travel_entry_back(entry["id"], note.strip())
                        st.session_state["activitylog_reviewing_travel"] = None
                        st.rerun()
        st.page_link(
            "pages/9_Landons_Travels.py", label="Open in Landon's Travels", icon="🧭"
        )


today = date.today()
today_iso = today.isoformat()

all_lessons = db.list_lessons(student["id"], limit=50)
to_review = [l for l in all_lessons if l["status"] in ("planned", "submitted", "needs_revision")]
history = [l for l in all_lessons if l["status"] in ("completed", "skipped")]
# Stable sort: anything he's turned in floats to the top of "to review"
# since it's the most time-sensitive -- he's waiting on you, not the other
# way around. Relative order within each group (most recent first) is preserved.
to_review.sort(key=lambda l: 0 if l["status"] == "submitted" else 1)

# Travel Journal entries go through the exact same submit/review gate as a
# lesson, so a trip waiting on you belongs in the same queue as everything
# else waiting on you -- not only visible if you happen to open Landon's
# Travels. A 'planned' (not-yet-written) stub isn't included here the way a
# 'planned' lesson is: there's nothing yet to *review* about a trip he
# hasn't written up, unlike an overdue lesson, which is itself the thing
# needing your attention.
all_travel_entries = db.list_travel_entries(student["id"])
travel_to_review = [t for t in all_travel_entries if t["status"] in ("submitted", "needs_revision")]
travel_to_review.sort(key=lambda t: 0 if t["status"] == "submitted" else 1)

# The tab's own number, not just "everything not yet completed" -- reported
# directly: a lesson simply scheduled for a future day, untouched, isn't
# something to review yet, the same reasoning travel_to_review above
# already uses for an unwritten stub. Only turned-in work, sent-back work,
# and anything genuinely overdue belongs in this count; the week's day
# board further down is a schedule view, not a review queue, and was
# quietly inflating this number even though nothing on it needed a look.
needs_review_count = (
    sum(1 for l in to_review if _needs_attention(l, today_iso) or l["status"] == "needs_revision")
    + len(travel_to_review)
)

log_tab, add_tab, lessons_tab = st.tabs(
    ["The record", "Log something manually", f"To review ({needs_review_count})"]
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
        "Laid out the way the week itself gets planned — Monday through Thursday, "
        "one column each. Anything overdue or already turned in floats up top "
        "regardless of which day or week it's for, so it's never stuck a few "
        "columns over from where you're looking."
    )

    if travel_to_review:
        st.markdown(f"**🧭 Travel Journal** ({len(travel_to_review)})")
        for entry in travel_to_review:
            _render_travel_review_card(entry)
        st.divider()

    attention = [l for l in to_review if _needs_attention(l, today_iso)]
    attention.sort(
        key=lambda l: (
            0 if l["status"] == "submitted" else 1,
            (l.get("metadata") or {}).get("planned_for") or "",
        )
    )
    # Sent back for revision is waiting on him, not you -- its own quieter
    # section, pulled out of the day board entirely rather than mixed in
    # with lessons still simply due, so what's on your plate versus his
    # stays visually distinct.
    sent_back = [l for l in to_review if l["status"] == "needs_revision"]
    # Its whole week ended without being turned in -- pulled out of his own
    # view entirely (see weekly.is_backlogged/due_lessons). This is the only
    # place left to see it until it's explicitly moved to a new day below.
    backlog = [
        l for l in to_review
        if l["status"] == "planned" and weekly.is_backlogged(l, today_iso)
    ]
    backlog.sort(key=lambda l: (l.get("metadata") or {}).get("planned_for") or "")
    excluded_ids = (
        {l["id"] for l in attention} | {l["id"] for l in sent_back} | {l["id"] for l in backlog}
    )
    rest = [l for l in to_review if l["id"] not in excluded_ids]

    if not all_lessons:
        st.info("No lessons generated yet.")
    else:
        if attention:
            st.markdown(f"**⚠️ Needs your attention now** ({len(attention)})")
            for lesson in attention:
                _render_review_card(lesson, today_iso)
            st.divider()

        if sent_back:
            st.markdown(f"**↩️ Sent back — waiting on him** ({len(sent_back)})")
            st.caption(
                "Nothing to do here yet — just visible so you can see where things stand."
            )
            for lesson in sent_back:
                _render_review_card(lesson, today_iso)
            st.divider()

        if backlog:
            st.markdown(f"**🗄️ Backlog** ({len(backlog)})")
            st.caption(
                "His whole week for these came and went without being turned in -- "
                "pulled out of his own view entirely, not just marked late. Move one "
                "to a new day below to bring it back; it'll show up for him again "
                "exactly like a freshly planned lesson, once it's due."
            )
            for lesson in backlog:
                _render_review_card(lesson, today_iso, show_reschedule=True)
            st.divider()

        st.markdown("**📅 This week's plan**")
        st.caption(
            "Not more things waiting on you -- just the schedule, so you can see "
            "what's coming without switching pages. Nothing here counts toward "
            "the number above until it's actually turned in, sent back, or overdue."
        )
        picked_week = st.date_input(
            "Week to review (any day in it — snapped to that week's Monday)",
            value=today,
            key="review_week_picker",
        )
        target_week_start = weekly.week_start(picked_week)
        # Friday included even though it's not a lesson day by default --
        # This Week's school-days picker can opt it in as a substitute for a
        # holiday elsewhere in the week, and a lesson planned there needs a
        # real column here too, not a trip into the "other_week" bucket below.
        target_dates = weekly.week_dates(target_week_start, include_friday=True)
        st.caption(
            f"{target_dates[0].strftime('%b %-d')} – {target_dates[-1].strftime('%b %-d, %Y')}"
        )

        board_buckets: dict[str, list[dict]] = {d.isoformat(): [] for d in target_dates}
        unscheduled: list[dict] = []
        # Not overdue, not submitted, so it isn't in `attention` -- just an
        # ordinary planned lesson that happens to be scheduled for a week
        # other than the one on screen. A real bug, found by testing this
        # live: this used to fall through both branches below and vanish
        # entirely -- still counted in the tab's header total, but never
        # rendered anywhere on the page, so the header count and what was
        # actually visible silently stopped matching.
        other_week: list[dict] = []
        for lesson in rest:
            planned_for = (lesson.get("metadata") or {}).get("planned_for")
            if planned_for in board_buckets:
                board_buckets[planned_for].append(lesson)
            elif not planned_for:
                unscheduled.append(lesson)
            else:
                other_week.append(lesson)

        board_columns = st.columns(len(target_dates))
        for column, day in zip(board_columns, target_dates):
            with column:
                marker = " 👈" if day.isoformat() == today_iso else ""
                st.markdown(f"**{day.strftime('%A')}**{marker}")
                st.caption(day.strftime("%b %-d"))
                day_lessons = board_buckets[day.isoformat()]
                if not day_lessons:
                    st.caption("Nothing due.")
                for lesson in day_lessons:
                    _render_review_card(lesson, today_iso)

        if unscheduled:
            st.divider()
            st.markdown(f"**Not tied to a specific day** ({len(unscheduled)})")
            for lesson in unscheduled:
                _render_review_card(lesson, today_iso)

        if other_week:
            other_weeks = sorted({
                weekly.week_start(
                    date.fromisoformat((l.get("metadata") or {})["planned_for"])
                ).isoformat()
                for l in other_week
            })
            plural = "s" if len(other_week) != 1 else ""
            st.divider()
            st.caption(
                f"{len(other_week)} more lesson{plural} also scheduled, for a "
                f"different week (week of {', '.join(other_weeks)}) — change the "
                "date above to see them."
            )

        # Matches needs_review_count above -- the week's plan (whatever
        # week is picked) never factors into this, since none of it is
        # actually waiting on a review from you.
        if not attention and not sent_back and not travel_to_review:
            st.success("Nothing waiting on you right now.")

    show_history = st.checkbox("Also show completed and skipped lessons")
    if show_history:
        st.divider()
        st.markdown(f"**Completed & skipped** ({len(history)})")
        if not history:
            st.caption("Nothing logged yet.")
        for lesson in history:
            _render_review_card(lesson, today_iso)
