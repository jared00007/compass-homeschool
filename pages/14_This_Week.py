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
from compass.agents.strategies import ERAS, SCIENCE_DOMAINS
from compass.compliance import build_report
from compass.ui import (
    EPIC_ICONS,
    FRIDAY_PLAN_KINDS,
    SUBJECT_ICONS,
    md,
    page_setup,
    parent_only,
    render_board_card,
    render_friday_plan,
    render_lesson,
    render_story_move_control,
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


def _idea_options(db, student_id: int, key: str) -> list[tuple[str, str]]:
    """Monday's optional topic picker for Science/History: real open
    branches from earlier lessons (if any exist yet -- a fresh topic web,
    like right after the school-year reset, has none), plus the built-in
    domain/era rotation those same strategies fall back to automatically
    when a web is empty -- ready-made ideas at both levels of specificity,
    rather than a blank box. Value encodes which kind of pick it is:
    "node:<id>" for an existing branch, "domain:<index>" for a built-in
    rotation entry, so the caller can route it to node_id or seed_topic.
    """
    options: list[tuple[str, str]] = [("auto", "Let the agent choose automatically")]
    options += [
        (f"node:{n['id']}", f"🔗 {n['topic']}")
        for n in db.unexplored_web_nodes(student_id, key)
    ]
    if key == "science":
        options += [(f"domain:{i}", f"💡 {label}") for i, label in enumerate(SCIENCE_DOMAINS)]
    elif key == "history":
        options += [(f"domain:{i}", f"💡 {label}") for i, (_, label) in enumerate(ERAS)]
    return options


board_tab, review_tab, plan_tab = st.tabs(["📋 Board", "Review this week", "Plan next week"])

# --- Board: every subject's stories, one week, one place ------------------------
#
# The actual point of the whole redesign this tab is part of: before this,
# rearranging a story meant navigating into whichever subject's own page it
# lived on, then several clicks deep into a nested expander, to reach the
# exact same shared move control this tab now surfaces directly on every
# card. This tab changes nothing about *how* a story moves -- only where a
# parent has to go to do it.

with board_tab:
    # Seeded once, before the buttons below ever run -- a button writes
    # straight into this same session_state key and reruns, so the
    # date_input picks up the jump on the very next run instead of needing
    # a second click. Defaults to this week on a fresh session.
    if "board_week_picker" not in st.session_state:
        st.session_state["board_week_picker"] = date.today()

    jump_columns = st.columns([1, 1, 5])
    if jump_columns[0].button("This week", key="board_jump_this_week"):
        st.session_state["board_week_picker"] = date.today()
        st.rerun()
    if jump_columns[1].button("Next week", key="board_jump_next_week"):
        # Same Monday "Plan next week" itself targets by default -- the
        # actual point of this button: right after a Friday planning
        # session generates next week's lessons, this is the one click
        # that shows them laid out on the same board, ready to move
        # around, instead of hand-picking next week's date here too.
        st.session_state["board_week_picker"] = weekly.default_plan_target()
        st.rerun()

    board_week_start = weekly.week_start(
        st.date_input(
            "Week to view",
            key="board_week_picker",
            help="Any day in the week you want to see -- snapped to that week's Monday. "
            "The buttons above jump straight to this week or next week.",
        )
    )
    board_days = weekly.week_dates(board_week_start, include_friday=True)
    st.caption(
        f"{board_days[0].strftime('%b %-d')} – {board_days[-1].strftime('%b %-d, %Y')}"
    )

    board = weekly.board_for_week(db, student, board_week_start)
    all_lessons_for_board = db.list_lessons(student["id"], limit=200)
    today_iso_for_board = date.today().isoformat()

    # Product Backlog panel (left) + the sprint board itself (right) --
    # every story currently parked, any week it originally came from, is
    # grouped by epic here rather than sitting in a sixth day-column. The
    # move control on each card is exactly what "assign" means: opening it
    # is how a parked story gets a day (or moves to a different one),
    # nothing new to build for that beyond a new place to put the card.
    panel_col, board_col = st.columns([1, 3], gap="large")

    with panel_col:
        st.markdown("**📋 Product Backlog**")
        backlog_by_epic = weekly.group_backlog_by_epic(board["backlog"])
        total_backlogged = sum(len(items) for items in backlog_by_epic.values())
        if not total_backlogged:
            st.caption("Nothing parked.")
        for epic in weekly.EPIC_ORDER:
            items = backlog_by_epic.get(epic, [])
            if not items:
                continue
            icon = EPIC_ICONS.get(epic, "📘")
            with st.expander(f"{icon} {epic} ({len(items)})", expanded=True):
                for kind, item in items:
                    render_board_card(
                        db, kind, item,
                        today_iso=today_iso_for_board,
                        all_lessons_for_collision=all_lessons_for_board,
                    )

    with board_col:
        board_columns = st.columns(5)
        for column, day_date in zip(board_columns, board_days):
            with column:
                st.markdown(f"**{day_date.strftime('%a')}**")
                st.caption(day_date.strftime("%b %-d"))
                day_items = board[day_date.isoformat()]
                if not day_items:
                    st.caption("Nothing here.")
                for kind, item in day_items:
                    render_board_card(
                        db, kind, item,
                        today_iso=today_iso_for_board,
                        all_lessons_for_collision=all_lessons_for_board,
                    )

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
    # Friday's included here even though it's unchecked by default below --
    # the whole point is to have it available to opt into for this one week.
    full_week_dates = weekly.week_dates(target_week_start, include_friday=True)
    st.caption(
        f"Planning {full_week_dates[0].strftime('%b %-d')} – "
        f"{full_week_dates[-1].strftime('%b %-d, %Y')}."
    )

    st.markdown("**School days this week**")
    st.caption(
        "Uncheck a day to skip it entirely -- a holiday, a field trip, whatever. "
        "Friday's unchecked by default (it's normally the review/light day below), "
        "but check it when another day's out and you want four real lesson days "
        "anyway -- a holiday Monday, say, made up for with a Friday lesson instead. "
        "Applies to every subject below; nothing gets generated for an unchecked "
        "day, and Math's practice notes ('day 2 of 3', say) count against however "
        "many days are actually checked, not always four."
    )
    day_columns = st.columns(len(full_week_dates))
    target_dates = []
    for column, day in zip(day_columns, full_week_dates):
        with column:
            is_school_day = st.checkbox(
                day.strftime("%A"),
                value=day.weekday() != 4,
                key=f"weekplan_schoolday_{day.isoformat()}",
            )
        if is_school_day:
            target_dates.append(day)
    if not target_dates:
        st.info("No school days checked above — check at least one to plan anything.")

    existing = weekly.latest_per_day(
        db.lessons_for_week(student["id"], target_week_start.isoformat())
    )
    existing_by_agent: dict[str, list[dict]] = {}
    for lesson in existing:
        existing_by_agent.setdefault(lesson["agent"], []).append(lesson)
    # Broader than `existing` (this target week only) on purpose -- moving a
    # lesson onto a day in a *different* week must still catch a same-agent
    # collision there, same scope Activity Log's own Backlog tab checks.
    all_lessons_for_collision = db.list_lessons(student["id"], limit=50)

    st.caption(
        "Each subject plans on its own click -- at most four lessons at a time, "
        "never all sixteen in one shot. A batch that large can run well past "
        "ten minutes -- long enough for the browser connection to drop, or for "
        "clicking to another page before it finishes (see the warning below), "
        "either of which silently strands whatever hadn't been reached yet. "
        "The three spiderweb/timeline/reading-driven subjects each get four "
        "fresh topics; Math gets one skill framed across the week (see This "
        "Week's own notes on why). Science and History offer Monday's topic as "
        "a picklist -- open branches from earlier lessons, plus the built-in "
        "domain/era rotation -- or type something new entirely; this is where a "
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
        # Not literally "Monday" once a day's been unchecked above -- this is
        # really "the first checked day still missing," whichever weekday
        # that turns out to be.
        first_day_missing = (
            key != "math" and bool(target_dates) and target_dates[0] in missing_dates
        )
        first_day_label = target_dates[0].strftime("%A") if target_dates else "First day's"

        with st.container(border=True):
            st.markdown(f"**{_agent_label(key)}**")
            seed = ""
            picked_node_id = ""
            if first_day_missing and key in ("science", "history"):
                idea_options = _idea_options(db, student["id"], key)
                idea_labels = dict(idea_options)
                picked_idea = st.selectbox(
                    f"{first_day_label}'s topic -- pick an idea, or let the agent choose",
                    [value for value, _ in idea_options],
                    format_func=lambda v: idea_labels[v],
                    key=f"weekplan_idea_{key}",
                    help="Open branches proposed by earlier lessons, plus the built-in "
                    "topic rotation those same lessons fall back to automatically when "
                    "there's nothing open yet.",
                )
                if picked_idea.startswith("node:"):
                    picked_node_id = picked_idea.split(":", 1)[1]
                elif picked_idea.startswith("domain:"):
                    domain_index = int(picked_idea.split(":", 1)[1])
                    seed = SCIENCE_DOMAINS[domain_index] if key == "science" else ERAS[domain_index][1]
                seed_override = st.text_input(
                    "Or type something specific instead (optional)",
                    key=f"weekplan_seed_{key}",
                    help="Typing here ignores the pick above and starts something new; "
                    "the branches/domains stay available for later.",
                )
                if seed_override.strip():
                    seed = seed_override.strip()
                    picked_node_id = ""
            elif first_day_missing:
                seed = st.text_input(
                    f"{first_day_label}'s topic (optional, leave blank to let the agent choose)",
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
                    day_results = weekly.plan_missing_days(
                        db, student, AGENTS[key], target_week_start,
                        target_dates, missing_dates,
                        is_math=(key == "math"),
                        skill_id=skill_id,
                        seed_topics={0: seed.strip()} if seed.strip() else None,
                        node_ids={0: picked_node_id} if picked_node_id else None,
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

                    # Sprint-board freedom: send this lesson back to Backlog,
                    # or move it to a different day entirely -- the same
                    # shared control every other story type uses, offered
                    # for every agent including math (moving a day doesn't
                    # touch the shared skill_id the way regenerating one
                    # would, so math isn't excluded here the way it is below).
                    def _validate_weekplan_move(new_date: str, lesson=lesson) -> str | None:
                        collision = any(
                            other["agent"] == lesson["agent"]
                            and other["id"] != lesson["id"]
                            and (other.get("metadata") or {}).get("planned_for") == new_date
                            for other in all_lessons_for_collision
                        )
                        if collision:
                            return (
                                f"⚠️ Already a {lesson['agent']} lesson planned for that "
                                "day -- pick a different one."
                            )
                        return None

                    render_story_move_control(
                        key=f"weekplan_lesson_{lesson['id']}",
                        active=not weekly.is_backlogged(lesson, date.today().isoformat()),
                        scheduled_for=lesson["metadata"].get("planned_for"),
                        set_active=lambda a, lid=lesson["id"]: (
                            db.reschedule_lesson(lid, date.today().isoformat())
                            if a else db.send_to_backlog(lid)
                        ),
                        schedule=lambda d, lid=lesson["id"]: (
                            db.reschedule_lesson(lid, d) if d else None
                        ),
                        validate_schedule=_validate_weekplan_move,
                    )

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
    # This widget always exists for Friday, whether or not Friday's also
    # checked above as a lesson day this particular week -- its date is
    # derived from the Monday directly rather than indexed off
    # target_dates (which may or may not include Friday, and may hold
    # fewer than four either way).
    friday_date = target_week_start + timedelta(days=4)
    st.markdown(f"**Friday's plan** — {friday_date.strftime('%b %-d')}")
    st.caption(
        "Friday's the review/light day by default -- check it above in the "
        "school-days picker to make it a real lesson day instead, just for "
        "this week. This is what shows on the Week grid either way, alongside "
        "any subject lesson you did plan for Friday. Pick any mix of the "
        "standard options below, or add your own; nothing picked yet falls "
        "back to the original Big Project + Travel Journal pairing."
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
