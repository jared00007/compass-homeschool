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
from compass.ui import SUBJECT_ICONS, md, page_setup, parent_only, render_lesson

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


def _latest_per_day(lessons: list[dict]) -> list[dict]:
    """Regenerating a day inserts a fresh lesson rather than replacing the
    old one -- same "newest wins, nothing gets deleted" approach already
    used for life-skill plans (`Database.latest_life_skill_plan`). Keyed on
    (agent, planned_for) so a superseded lesson just stops being shown here
    rather than needing to be deleted; it's still there for Activity Log's
    own "to review" cleanup if it was never logged.

    `lessons` must already be sorted oldest-first (planned_for, id), which
    is exactly what `Database.lessons_for_week` returns -- iterating in that
    order and overwriting a dict keyed by (agent, planned_for) naturally
    keeps the newest entry for each day.
    """
    latest: dict[tuple[str, str], dict] = {}
    for lesson in lessons:
        key = (lesson["agent"], lesson["metadata"].get("planned_for", ""))
        latest[key] = lesson
    return sorted(
        latest.values(), key=lambda l: (l["metadata"].get("planned_for", ""), l["id"])
    )


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

    week_lessons = _latest_per_day(db.lessons_for_week(student["id"], this_week_start.isoformat()))
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
    st.markdown("**Filler time, if there's room left today**")
    st.caption(
        "Friday's light on purpose -- whatever's left over goes to Big Projects or "
        "Life Skills, ad hoc."
    )
    link_columns = st.columns(2)
    link_columns[0].page_link("pages/7_Big_Projects.py", label="Big Projects", icon="🎬")
    link_columns[1].page_link("pages/6_Life_Skills.py", label="Life Skills", icon="🛠️")

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

    existing = _latest_per_day(db.lessons_for_week(student["id"], target_week_start.isoformat()))
    existing_by_agent: dict[str, list[dict]] = {}
    for lesson in existing:
        existing_by_agent.setdefault(lesson["agent"], []).append(lesson)

    if not existing:
        st.markdown("**Nothing planned yet for this week.**")
        st.caption(
            "The three spiderweb/timeline/reading-driven subjects each get four fresh "
            "topics; Math gets one skill framed across the week (see This Week's own "
            "notes on why). Optionally point Monday at something specific instead of "
            "the agent's automatic pick -- this is where a Class CrunchLabs unit would "
            "get slotted into Science on purpose."
        )
        seed_topics: dict[str, str] = {}
        for key in ("science", "english", "history"):
            seed_topics[key] = st.text_input(
                f"{_agent_label(key)} — Monday's topic (optional, leave blank to let the agent choose)",
                key=f"weekplan_seed_{key}",
            )

        if st.button("Plan next week", type="primary"):
            status = st.status("Planning next week…", expanded=True)
            any_errors = False
            for key in AGENT_ORDER:
                agent = AGENTS[key]
                status.write(f"{_agent_label(key)} …")
                if key == "math":
                    day_results = weekly.plan_math_week(db, student, target_week_start)
                else:
                    seed = seed_topics.get(key, "").strip()
                    day_results = weekly.plan_subject_week(
                        db, student, agent, target_week_start,
                        seed_topics={0: seed} if seed else None,
                    )
                for day in day_results:
                    if day.error:
                        any_errors = True
                        status.write(f"  ⚠️ {day.target_date}: {day.error}")
            if any_errors:
                # Leave the status open with the errors visible rather than
                # rerunning immediately -- a rerun starts a fresh script
                # execution where nothing written into this status box
                # survives, so the parent would see the spinner flash and
                # then just land back on this same screen with no idea why.
                status.update(
                    label="Finished with some errors — see above.",
                    state="error", expanded=True,
                )
            else:
                status.update(
                    label="Done planning next week.", state="complete", expanded=False
                )
                st.rerun()
    else:
        st.markdown("**Already planned:**")
        st.caption(
            "Filling in only covers days that don't have a lesson yet — it never "
            "touches a day that's already planned, whether he's done it or not. To "
            "replace a specific day on purpose, open it below and use **Regenerate "
            "just this day**."
        )
        for key in AGENT_ORDER:
            lessons = existing_by_agent.get(key, [])
            covered = {lesson["metadata"].get("planned_for") for lesson in lessons}
            missing_dates = [d for d in target_dates if d.isoformat() not in covered]

            with st.container(border=True):
                header_columns = st.columns([5, 2])
                with header_columns[0]:
                    st.markdown(f"**{_agent_label(key)}**")
                with header_columns[1]:
                    button_label = "Plan this week" if not lessons else "Fill in missing days"
                    if st.button(
                        button_label, key=f"regen_week_{key}", disabled=not missing_dates
                    ):
                        with st.spinner(f"Planning {_agent_label(key)}…"):
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
                                result = weekly.plan_day(
                                    db, student, AGENTS[key], target_week_start, target,
                                    skill_id=skill_id, parent_note=note,
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
                    st.caption(f"Not planned yet — use **{button_label}** to set it up.")
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
