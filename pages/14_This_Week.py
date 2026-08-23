"""This Week -- Friday reviews the week just finished, then plans the week
ahead, so Monday through Thursday he opens a lesson that's already sitting
there instead of someone remembering to generate one that morning.

Math is handled differently from the other three subjects here -- see
compass/weekly.py's module docstring for why: its next skill only unlocks
once a real assessment gets graded, so nothing changes between four calls
made in the same Friday sitting the way it does for Science, English, and
History (each of those updates its own state -- a new web branch, an era
touched -- the moment a lesson is generated). Math gets one skill, framed
across the week, instead of four different topics.

Parent-only throughout: planning ahead means previewing lesson content
before he's meant to see it, same reasoning as everywhere else generation
happens.
"""

from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

from compass import weekly
from compass.agents import all_agents
from compass.compliance import build_report
from compass.ui import (
    FRIDAY_PLAN_KINDS,
    SUBJECT_ICONS,
    md,
    page_setup,
    parent_only,
    render_friday_plan,
    render_lesson,
)

db, student = page_setup("This Week", icon="🗓️")

st.title("🗓️ This Week")
st.caption(
    "Friday reviews the week that just finished, then plans the next one -- "
    "so Monday through Thursday, a lesson is already waiting instead of "
    "someone remembering to generate it that morning."
)

if not parent_only("Weekly planning is for your parent."):
    st.stop()

AGENTS = all_agents()
AGENT_ORDER = ("math", "science", "english", "history")


def _agent_label(key: str) -> str:
    agent = AGENTS.get(key)
    return f"{SUBJECT_ICONS.get(key, '📘')} {agent.name if agent else key.title()}"


def _day_label(iso_date: str) -> str:
    if not iso_date:
        return "no day set"
    return date.fromisoformat(iso_date).strftime("%A, %b %-d")


review_tab, plan_tab = st.tabs(["Review this week", "Plan next week"])

# --- Review this week ----------------------------------------------------------

with review_tab:
    this_week_start = weekly.week_start()
    this_week_friday = this_week_start + timedelta(days=4)
    st.subheader(
        f"{this_week_start.strftime('%b %-d')} – {this_week_friday.strftime('%b %-d, %Y')}"
    )

    report = build_report(
        db, student["id"], start=this_week_start.isoformat(), end=this_week_friday.isoformat()
    )
    columns = st.columns(3)
    columns[0].metric("Hours logged this week", f"{report.total_hours:g}")
    columns[1].metric("Days of instruction", report.instructional_days)
    columns[2].metric("Activities logged", report.activity_count)

    week_lessons = weekly.latest_per_day(
        db.lessons_for_week(student["id"], this_week_start.isoformat())
    )
    if not week_lessons:
        st.info(
            "Nothing was planned for this week -- either it predates this feature, "
            "or a Friday planning session got skipped. Head to **Plan next week** "
            "to set up the week ahead."
        )
    else:
        st.markdown("**This week's plan**")
        for lesson in week_lessons:
            planned_for = lesson["metadata"].get("planned_for", "")
            done = bool(lesson["metadata"].get("student_done_on"))
            quiz = lesson["metadata"].get("quiz_result") or {}
            marker = "✅" if done else "⬜"
            extra = ""
            if quiz.get("total"):
                pct = round(100 * quiz["correct"] / quiz["total"])
                extra = f" — quiz {quiz['correct']}/{quiz['total']} ({pct}%)"
            label = f"{marker} **{_agent_label(lesson['agent'])}** — {md(lesson['title'])}{extra}"
            st.markdown(f"- {label} · {_day_label(planned_for)}")

    st.divider()
    st.markdown(f"**Friday's plan** — {this_week_friday.strftime('%b %-d')}")
    st.caption("Friday's light on purpose -- see **Plan next week** to change what's set here.")
    render_friday_plan(db, student, this_week_friday.isoformat())

# --- Plan next week --------------------------------------------------------------

with plan_tab:
    default_target = weekly.default_plan_target()
    picked = st.date_input(
        "Week to plan (any day in the target week -- snapped to that week's Monday)",
        value=default_target,
    )
    target_week_start = weekly.week_start(picked)
    target_dates = weekly.week_dates(target_week_start)
    st.caption(
        f"Planning {target_dates[0].strftime('%b %-d')} – "
        f"{target_dates[-1].strftime('%b %-d, %Y')}."
    )

    existing = weekly.latest_per_day(
        db.lessons_for_week(student["id"], target_week_start.isoformat())
    )
    existing_by_agent: dict[str, list[dict]] = {}
    for lesson in existing:
        existing_by_agent.setdefault(lesson["agent"], []).append(lesson)

    st.caption(
        "Each subject plans on its own click -- at most four lessons at a time, "
        "never all sixteen in one shot. A batch that large can run well past "
        "ten minutes -- long enough for the browser connection to drop, or for "
        "clicking to another page before it finishes (see the warning below), "
        "either of which silently strands whatever hadn't been reached yet. "
        "The three spiderweb/timeline/reading-driven subjects each get four "
        "fresh topics; Math gets one skill framed across the week (see This "
        "Week's own notes on why). Optionally point a subject's Monday at "
        "something specific instead of its automatic pick -- this is where a "
        "Class CrunchLabs unit would get slotted into Science on purpose. "
        "Filling in only covers days that don't have a lesson yet -- it never "
        "touches a day that's already planned, whether he's done it or not. "
        "To replace a specific day on purpose, open it below and use "
        "**Regenerate just this day**."
    )
    st.warning(
        "⚠️ **Stay on this page until the spinner below finishes.** Clicking to "
        "Check-In, Home, or anywhere else mid-generation stops it immediately -- "
        "Streamlit cancels whatever a page was doing the moment you navigate "
        "away from it. Whatever day it already reached is saved; whatever day "
        "it hadn't gotten to yet just never happens, with no error shown. If "
        "that happens, come back here and click **Fill in missing days** again "
        "-- it only ever fills the actual gaps, never touches what already "
        "planned successfully."
    )

    for key in AGENT_ORDER:
        lessons = existing_by_agent.get(key, [])
        covered = {lesson["metadata"].get("planned_for") for lesson in lessons}
        missing_dates = [d for d in target_dates if d.isoformat() not in covered]
        monday_missing = key != "math" and target_dates[0] in missing_dates

        with st.container(border=True):
            st.markdown(f"**{_agent_label(key)}**")
            seed = ""
            if monday_missing:
                seed = st.text_input(
                    "Monday's topic (optional, leave blank to let the agent choose)",
                    key=f"weekplan_seed_{key}",
                )
            button_label = "Plan this week" if not lessons else "Fill in missing days"
            if st.button(button_label, key=f"regen_week_{key}", disabled=not missing_dates):
                with st.spinner(f"Planning {_agent_label(key)}… don't navigate away"):
                    # Math's missing days must continue the week's one
                    # shared skill rather than each proposing fresh --
                    # read it off whatever's already planned this week,
                    # or let the first missing day pick it naturally if
                    # nothing exists yet at all.
                    skill_id = lessons[0]["metadata"].get("skill_id", "") if (
                        key == "math" and lessons
                    ) else ""
                    day_results = []
                    for target in missing_dates:
                        index = target_dates.index(target)
                        note = weekly.MATH_STAGE_NOTES[index] if key == "math" else ""
                        day_seed = seed.strip() if index == 0 else ""
                        result = weekly.plan_day(
                            db, student, AGENTS[key], target_week_start, target,
                            seed_topic=day_seed, skill_id=skill_id, parent_note=note,
                        )
                        day_results.append(result)
                        if key == "math" and index == 0 and result.generated:
                            skill_id = result.generated.proposal.metadata.get(
                                "skill_id", ""
                            )
                day_errors = [d for d in day_results if d.error]
                for day in day_errors:
                    st.error(f"{day.target_date}: {day.error}")
                if not day_errors:
                    st.rerun()

            if not lessons:
                st.caption(f"Not planned yet — use **{button_label}** above to set it up.")
            for lesson in lessons:
                planned_for = lesson["metadata"].get("planned_for", "")
                done = bool(lesson["metadata"].get("student_done_on"))
                with st.expander(
                    f"{_day_label(planned_for)} — {md(lesson['title'])}"
                    + (" ✅" if done else ""),
                    expanded=False,
                ):
                    render_lesson(lesson["payload"], for_parent=True)
                    # Math isn't offered a single-day regenerate: its four days
                    # share one skill, so swapping just one out of sequence
                    # would need to re-derive that shared skill_id from a
                    # sibling day -- simpler and safer to fill in or fully
                    # replan (above) when math needs to change at all.
                    if key == "math":
                        continue
                    if done:
                        st.caption(
                            "⚠️ He's already marked this done — regenerating replaces "
                            "what's shown here but doesn't touch his completed record."
                        )
                    if st.button("Regenerate just this day", key=f"regen_day_{lesson['id']}"):
                        target = (
                            date.fromisoformat(planned_for)
                            if planned_for
                            else target_week_start
                        )
                        with st.spinner("Regenerating…"):
                            result = weekly.plan_day(
                                db, student, AGENTS[key], target_week_start, target
                            )
                        if result.error:
                            st.error(result.error)
                        else:
                            st.rerun()

    st.divider()
    # target_dates only ever holds the four scheduled dates (Monday-Thursday,
    # see weekly.week_dates) -- Friday isn't a lesson day, so its date is
    # derived from the Monday directly rather than indexed off that list.
    friday_date = target_week_start + timedelta(days=4)
    st.markdown(f"**Friday's plan** — {friday_date.strftime('%b %-d')}")
    st.caption(
        "Friday's never a new-content day (see the four subjects above) -- this is "
        "what actually shows on the Week grid instead. Pick any mix of the "
        "standard options below, or add your own; nothing picked yet falls back "
        "to the original Big Project + Travel Journal pairing."
    )

    friday_items = db.list_friday_plan_items(student["id"], friday_date.isoformat())
    for item in friday_items:
        icon, default_label, _, _ = FRIDAY_PLAN_KINDS[item["kind"]]
        text = md(item["label"]) if item["label"] else default_label
        item_columns = st.columns([8, 1])
        item_columns[0].markdown(f"{icon} {text}")
        if item_columns[1].button("✕", key=f"remove_friday_item_{item['id']}"):
            db.delete_friday_plan_item(item["id"])
            st.rerun()

    with st.form(f"add_friday_item_{friday_date.isoformat()}", clear_on_submit=True):
        form_columns = st.columns([2, 3])
        kind = form_columns[0].selectbox(
            "Add to Friday",
            list(FRIDAY_PLAN_KINDS),
            format_func=lambda k: f"{FRIDAY_PLAN_KINDS[k][0]} "
            + (FRIDAY_PLAN_KINDS[k][1] or "Custom…"),
        )
        label = form_columns[1].text_input(
            "Detail",
            placeholder="Required for Custom -- optional detail for the rest, "
            "e.g. \"catch up on 5 older trips\"",
        )
        if st.form_submit_button("Add") and (kind != "custom" or label.strip()):
            db.add_friday_plan_item(student["id"], friday_date.isoformat(), kind, label.strip())
            st.rerun()
