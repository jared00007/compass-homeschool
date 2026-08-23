"""Compass — homeschool curriculum home page."""

from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

from compass import config, weekly
from compass.agents import course_summary, life_skills
from compass.compliance import build_report
from compass.curriculum import frontier_report
from compass.subjects import label
from compass.ui import (
    SUBJECT_ICONS,
    is_parent,
    md,
    page_setup,
    render_declaration_banner,
    render_friday_plan,
    render_fun_fact,
    render_lesson,
    render_morning_routine,
    render_school_start_countdown,
    render_today_checklist,
)

db, student = page_setup("Home", icon="🧭")

# --- student view -------------------------------------------------------------
# When a PIN is set, this is what he lands on: today's work, and nothing that
# would spoil it. Two tabs -- Day is the checklist he works top to bottom
# (start the day feeling good, check in, then the actual lessons), Week is a
# read-only glance at the whole week at once so he can see what's coming
# without having to click through five separate days.

if not is_parent():
    st.title(f"Hi {student['name'].split()[0]} 👋")
    st.caption("Here's what's set up for you. Work down the list, or jump around — up to you.")
    render_school_start_countdown(db)
    render_fun_fact()

    st.divider()

    # "Sunday Funnies" week-grid styling -- one of three retro comic
    # directions sampled and approved before building (see Home's own week
    # tab). Colors are hardcoded to this one printed look on purpose, not
    # pulled from theme.py.
    _WEEK_DAY_COLORS = ("#e14b3a", "#f0ac1f", "#3564c4", "#3f9450", "#8c4fa8")  # Mon-Fri
    _WEEK_INK = "#211a14"
    _WEEK_PAPER = "#fffaf0"
    _WEEK_TODAY_BURST = (
        '<div style="position:absolute; top:-14px; right:-10px; width:46px; height:46px; '
        f'border-radius:999px; background:{_WEEK_DAY_COLORS[1]}; border:2.5px solid {_WEEK_INK}; '
        'display:flex; align-items:center; justify-content:center; font-weight:900; '
        f'font-size:9px; color:{_WEEK_INK}; letter-spacing:-.02em; transform:rotate(-12deg); '
        f'box-shadow:3px 3px 0 0 {_WEEK_INK}; z-index:1;">TODAY!</div>'
    )
    _WEEK_CARD_CSS = (
        "<style>\n"
        'div[class*="st-key-week_day_"] {\n'
        f"  background: {_WEEK_PAPER};\n"
        f"  border: 3px solid {_WEEK_INK};\n"
        "  border-radius: 3px;\n"
        "  padding: 14px 14px 4px;\n"
        "  position: relative;\n"
        f"  box-shadow: 6px 6px 0 0 {_WEEK_INK};\n"
        "  margin-bottom: 10px;\n"
        "}\n"
        'div[class*="st-key-week_day_"] [data-testid="stCaptionContainer"] { color: #6b5f4d; }\n'
        'div[class*="st-key-week_day_0"] { transform: rotate(-1.1deg); }\n'
        'div[class*="st-key-week_day_1"] { transform: rotate(.8deg); }\n'
        'div[class*="st-key-week_day_2"] { transform: rotate(-.6deg); }\n'
        'div[class*="st-key-week_day_3"] { transform: rotate(1deg); }\n'
        'div[class*="st-key-week_day_4"] { transform: rotate(-1deg); }\n'
        + "".join(
            f'div[class*="st-key-week_day_{i}"]::before {{ content:""; position:absolute; '
            "inset:0; border-radius:2px; pointer-events:none; opacity:.16; "
            f"background-image: radial-gradient(circle, {c} 1.6px, transparent 1.7px); "
            "background-size: 9px 9px; }\n"
            for i, c in enumerate(_WEEK_DAY_COLORS)
        )
        + "</style>"
    )

    def _render_week_grid(week_start_date: date) -> None:
        """The 5-column Monday-Friday layout, shared by This Week and
        Upcoming Week -- same read-only glance at whatever's been planned,
        just pointed at a different Monday. Monday-Thursday get whatever
        Tier 1 subject was planned for that day; Friday is deliberately
        never a new-content day (see compass/weekly.py), so it points at
        the next step on whichever Big Project he's chosen as this year's
        (db.active_big_project -- picked on the Big Projects page, never
        guessed at here) plus a Travel Journal entry -- low-effort, but
        each is enough on its own to make Friday an instructional day that
        counts, which a truly empty "light day" isn't guaranteed to be (see
        compass.compliance's day-count pace warning).

        Styled as a "Sunday Funnies" comic strip -- thick ink border, a hard
        offset shadow instead of a soft glow, a halftone dot tint, and a
        different classic comic color per weekday -- picked from three
        sample directions shown and approved before building. A fixed
        "printed" look on purpose, like the rest of this app's styling:
        colors are hardcoded, not pulled from theme.py's tokens, the same
        way a printed comic page doesn't re-theme itself for the room it's
        read in.
        """
        day_dates = [week_start_date + timedelta(days=i) for i in range(5)]
        day_names = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")
        today_date = date.today()

        week_lessons = weekly.latest_per_day(
            db.lessons_for_week(student["id"], week_start_date.isoformat())
        )
        lessons_by_day: dict[str, list[dict]] = {}
        for lesson in week_lessons:
            planned_for = lesson["metadata"].get("planned_for", "")
            lessons_by_day.setdefault(planned_for, []).append(lesson)

        checked_in_dates = {
            e["entry_date"] for e in db.list_journal_entries(student["id"], limit=60)
        }

        st.markdown(_WEEK_CARD_CSS, unsafe_allow_html=True)
        day_columns = st.columns(5)
        for index, (column, day_name, day_date) in enumerate(
            zip(day_columns, day_names, day_dates)
        ):
            day_iso = day_date.isoformat()
            color = _WEEK_DAY_COLORS[index]
            # week_start_date in the key, not just the index -- this
            # function runs once per tab (This Week, Upcoming Week), and a
            # bare "week_day_0" key would collide the second time it's
            # called in the same script run. The CSS below still matches on
            # the "week_day_N" prefix alone, so this doesn't need a second
            # set of style rules.
            with column, st.container(key=f"week_day_{index}_{week_start_date.isoformat()}"):
                if day_date == today_date:
                    st.markdown(_WEEK_TODAY_BURST, unsafe_allow_html=True)
                st.markdown(
                    f'<span style="display:inline-block; padding:2px 10px 3px; '
                    f'border-radius:3px; background:{color}; color:{_WEEK_PAPER}; '
                    f'font-weight:900; font-size:15px; text-transform:uppercase; '
                    f'letter-spacing:-.01em; text-shadow:1.5px 1.5px 0 rgba(0,0,0,.35);">'
                    f"{day_name}</span>",
                    unsafe_allow_html=True,
                )
                st.caption(day_date.strftime("%b %-d"))

                # Nothing shown at all for a day that hasn't arrived yet -- a
                # check-in can't have happened, so a "—" here was never a
                # status, just noise (every cell reads that way at once on
                # Upcoming Week, where every day is still in the future).
                if day_iso in checked_in_dates:
                    st.caption("💬 Checked in")
                elif day_date <= today_date:
                    st.caption("💬 No check-in yet")

                if day_name == "Friday":
                    st.caption("🎬 Light day — review the week, plus a quick win:")
                    render_friday_plan(db, student, day_iso)
                else:
                    day_lessons = lessons_by_day.get(day_iso, [])
                    if not day_lessons:
                        st.caption("Nothing planned yet.")
                    for lesson in day_lessons:
                        icon = SUBJECT_ICONS.get(lesson["agent"], "📘")
                        done = bool(lesson["metadata"].get("student_done_on"))
                        marker = "✅" if done else "⬜"
                        quiz = lesson["metadata"].get("quiz_result") or {}
                        badge = " 🎯" if quiz.get("passed") else ""
                        st.markdown(f"{marker} {icon} {md(lesson['title'])}{badge}")

    def _render_extra_activities() -> None:
        st.markdown(
            """
            <div style="background:var(--c-panel); border-left:4px solid var(--c-alt);
                 border-radius:var(--c-radius); padding:14px 18px; margin:18px 0 4px;
                 box-shadow:var(--c-glow);">
              <div style="font-weight:800; font-size:15px; margin-bottom:2px;">
                ✨ Extra activities — if there's time
              </div>
              <div style="font-size:13px; color:var(--c-dim);">
                Anytime this week, not just Friday — worth a look whenever a day's
                light on assignments.
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        extra_columns = st.columns(4)
        extra_columns[0].page_link("pages/7_Big_Projects.py", label="Big Projects", icon="🎬")
        extra_columns[1].page_link("pages/6_Life_Skills.py", label="Life Skills", icon="🛠️")
        extra_columns[2].page_link("pages/5_Choice_Topics.py", label="Choice Topics", icon="⭐")
        extra_columns[3].page_link("pages/9_Landons_Travels.py", label="Travels", icon="🧭")

    this_week_start = weekly.week_start()
    this_week_end = (this_week_start + timedelta(days=4)).isoformat()  # Friday

    day_tab, week_tab, upcoming_tab = st.tabs(
        ["📅 Today", "🗓️ This Week", "🔜 Upcoming Week"]
    )

    # === Today ===================================================================

    with day_tab:
        # 1. Morning routine -- start the day with a stretch/breathing/mindfulness
        # pick before anything else on the list.
        render_morning_routine(db, student)

        st.divider()

        # 2. Check-in -- its own self-contained status, same as morning routine.
        today = date.today().isoformat()
        checked_in = db.journal_entry_for_date(student["id"], today) is not None
        st.markdown("### 💬 Check-In")
        row = st.columns([5, 2])
        with row[0]:
            if checked_in:
                st.success("✅ You've checked in today.")
            else:
                st.caption("Take a second to say how you're doing today.")
        with row[1]:
            st.page_link(
                "pages/8_Check_In.py",
                label="Check in again" if checked_in else "Open Check-In",
                icon="➡️",
            )

        st.divider()

        # 3. Lessons ready for you. Life-skill plans and course-documentation
        # drafts live in the same table but are written *to the parent* --
        # "demonstrate once, then hand him the jack and stay quiet" is not his
        # to read, and a drafted course description is paperwork, not a lesson.
        # A lesson he's already marked done (student_lesson_view's own signal,
        # separate from `status`) drops off here too -- otherwise it sits here
        # forever until the parent logs it, which can be days.
        all_planned = [
            lesson
            for lesson in db.list_lessons(student["id"], limit=25)
            if lesson["status"] == "planned"
            and lesson["agent"] not in (life_skills.AGENT_KEY, course_summary.AGENT_KEY)
            and not (lesson.get("metadata") or {}).get("student_done_on")
        ]
        # A lesson planned ahead (This Week -- Friday planning) carries which
        # day it's meant for. Only what's actually due now belongs here --
        # today's, anything overdue from an earlier day, and anything
        # generated the ordinary on-demand way (no day attached, so there's
        # nothing to defer). A lesson planned for a *later* day used to show
        # here too, which meant "Lessons (14)" was really a whole week's
        # worth stacked into one list -- read at a glance, that's 10+ hours
        # that looks like it's all due today. Later days now live on the
        # This Week / Upcoming Week tabs instead -- split on this week's own
        # Friday, not just "today," since on a Friday itself (the week's last
        # scheduled day) *nothing* dated after today can still be "later this
        # week" -- it's necessarily a future week, and mislabeling it "this
        # week" points at the wrong tab.
        due_now = []
        later_this_week = 0
        later_week = 0
        for lesson in all_planned:
            planned_for = (lesson.get("metadata") or {}).get("planned_for")
            if planned_for and planned_for > today:
                if planned_for <= this_week_end:
                    later_this_week += 1
                else:
                    later_week += 1
            else:
                due_now.append(lesson)
        due_now.sort(key=lambda l: (l.get("metadata") or {}).get("planned_for") or "9999-99-99")

        st.markdown(f"### 📚 Lessons ({len(due_now)})")
        if not due_now:
            st.caption("Nothing new is set up yet. Check back after your parent plans a lesson.")
        else:
            for lesson in due_now:
                with st.container(border=True):
                    payload = lesson["payload"]
                    planned_for = (lesson.get("metadata") or {}).get("planned_for")
                    day_badge = ""
                    if planned_for and planned_for < today:
                        weekday = date.fromisoformat(planned_for).strftime("%A")
                        day_badge = f" · ⚠️ was due {weekday}"
                    elif planned_for == today:
                        day_badge = " · Today"
                    st.markdown(f"⬜ **{md(payload.get('title', lesson['title']))}**")
                    st.caption(
                        f"{lesson['agent'].title()} · {payload.get('estimated_minutes', '?')} min"
                        f"{day_badge}"
                    )
                    if payload.get("overview"):
                        st.write(md(payload["overview"]))
                    with st.expander("Open this lesson", expanded=False):
                        render_lesson(payload, for_parent=False)
        if later_this_week:
            st.caption(
                f"{later_this_week} more lesson(s) planned for later this week — "
                "see the **This Week** tab."
            )
        if later_week:
            st.caption(
                f"{later_week} more lesson(s) planned for a later week — see the "
                "**Upcoming Week** tab."
            )

        st.divider()

        # 4. Vocabulary review.
        # Same limit render_vocab_review uses, so this count matches what he'll
        # actually see when he clicks through rather than under- or over-stating it.
        due = db.vocabulary_due(student["id"], limit=25)
        st.markdown("### 🔤 Words to Review")
        row = st.columns([5, 2])
        with row[0]:
            if due:
                st.caption(f"{len(due)} word(s) due today.")
            else:
                st.success("✅ Nothing due today.")
        with row[1]:
            if due:
                st.page_link("pages/3_English.py", label="Review them", icon="➡️")

        st.divider()
        if render_today_checklist(db, student):
            st.divider()
        columns = st.columns(2)

        with columns[0]:
            st.markdown("#### 📖 Reading")
            book = db.current_book(student["id"])
            if book:
                st.markdown(f"**{book['title']}**")
                if book["total_pages"]:
                    st.progress(
                        min((book["current_page"] or 0) / book["total_pages"], 1.0),
                        text=f"page {book['current_page']} of {book['total_pages']}",
                    )
            else:
                st.caption("No book set up yet.")

        with columns[1]:
            st.markdown("#### ⭐ Your choice topics")
            topics = [
                t
                for t in db.list_choice_topics(student["id"])
                if t["status"] in ("active", "approved")
            ]
            if topics:
                for topic in topics[:4]:
                    st.markdown(f"- {md(topic['title'])}")
            else:
                st.caption("Nothing yet — add something you want to learn.")
            st.page_link("pages/5_Choice_Topics.py", label="Add a topic", icon="➡️")

    # === This Week / Upcoming Week ===============================================
    # Both read-only -- the plan itself is set by a parent on This Week (Friday
    # planning), these just lay out what's already there day by day so he can
    # see the week ahead without clicking into Monday through Friday one at a
    # time. Upcoming Week is only ever as populated as however far ahead a
    # parent has actually planned -- usually nothing until the Friday before.

    next_week_start = this_week_start + timedelta(days=7)

    with week_tab:
        st.caption(
            f"{this_week_start.strftime('%b %-d')} – "
            f"{(this_week_start + timedelta(days=4)).strftime('%b %-d')} · "
            "only shows what's been planned through weekly planning -- anything "
            "generated on the fly still shows up on **Today**, not here."
        )
        _render_week_grid(this_week_start)
        _render_extra_activities()

    with upcoming_tab:
        st.caption(
            f"{next_week_start.strftime('%b %-d')} – "
            f"{(next_week_start + timedelta(days=4)).strftime('%b %-d')} · "
            "next week's plan, once your parent sets it up -- usually on a "
            "Friday, for the week ahead."
        )
        _render_week_grid(next_week_start)
        _render_extra_activities()

    st.stop()

# --- parent view --------------------------------------------------------------

st.title("🧭 Compass")
st.caption(
    f"Multi-agent homeschool curriculum for {student['name']}, grade {student['grade']}."
)
render_school_start_countdown(db)
render_declaration_banner(db, student)

nudge = weekly.planning_nudge(db, student["id"])
if nudge is not None:
    severity, message = nudge
    getattr(st, severity)(message)

report = build_report(db, student["id"])
pace = report.pace()

# --- headline compliance numbers ---------------------------------------------

columns = st.columns(4)
columns[0].metric(
    "Instructional hours",
    f"{report.total_hours:g}",
    delta=f"{pace['ahead_by']:+g} vs pace",
    help=f"Washington requires {config.WA_ANNUAL_HOURS} hours per year.",
)
columns[1].metric("Days of instruction", report.instructional_days, help=f"Target {report.day_target}.")
columns[2].metric(
    "Subjects covered",
    f"{report.subjects_covered} / 11",
    delta=None if report.all_subjects_covered else "gap",
    delta_color="off" if report.all_subjects_covered else "inverse",
)
columns[3].metric("Activities logged", report.activity_count)

pace_text = (
    f"about {pace['hours_per_week_needed']:g} hrs/week"
    if pace["achievable"]
    else f"{pace['remaining_days']} days left — see Compliance"
)
st.progress(
    report.hour_progress,
    text=f"{report.total_hours:g} of {report.hour_target} hours "
    f"({report.hours_remaining:g} to go · {pace_text})",
)

for warning in report.warnings:
    st.warning(warning)

st.divider()

# --- what each agent would do next -------------------------------------------

st.subheader("What each agent would plan next")
st.caption(
    "Computed locally from his actual state — no model call. This is the strategy "
    "layer's answer before any lesson is written."
)

AGENT_PAGES = {
    "math": ("📐 Math", "pages/1_Math.py"),
    "science": ("🔬 Science", "pages/2_Science.py"),
    "english": ("📖 English", "pages/3_English.py"),
    "history": ("🏛️ History", "pages/4_History.py"),
}

from compass.agents import all_agents  # noqa: E402
from compass.ui import context_for  # noqa: E402

agent_columns = st.columns(4)
for column, (key, agent) in zip(agent_columns, all_agents().items()):
    with column:
        title, page = AGENT_PAGES.get(key, (agent.name, None))
        st.markdown(f"#### {title}")
        try:
            proposal = agent.propose_topic(context_for(db, student))
        except Exception as exc:  # a strategy should never take down the home page
            st.error(f"Strategy error: {exc}")
            continue
        if proposal.blocked:
            st.warning(md(proposal.blocked_reason))
        else:
            st.markdown(f"**{md(proposal.topic)}**")
            st.caption(md(proposal.rationale))
        if page:
            st.page_link(page, label=f"Open {title}", icon="➡️")

st.divider()

# --- coverage + math frontier -------------------------------------------------

left, right = st.columns([3, 2])

with left:
    st.subheader("The eleven required subjects")
    for subject in report.subjects:
        icon = "✅" if subject.has_instruction else "⬜"
        last = f" · last taught {subject.last_taught}" if subject.last_taught else ""
        st.markdown(f"{icon} **{subject.label}** — {subject.hours:g} hrs{last}")
    st.page_link("pages/11_Compliance.py", label="Full compliance dashboard", icon="📋")

with right:
    st.subheader("Math graph")
    frontier = frontier_report(db.mastered_skills(student["id"]))
    st.metric(
        "Skills mastered",
        f"{frontier['mastered_count']} / {frontier['total_skills']}",
    )
    available = frontier["available"]
    st.caption(f"{len(available)} skill(s) unlocked and ready, {frontier['locked_count']} locked.")
    for skill in available[:5]:
        st.markdown(f"- {skill.title}")

    st.subheader("Tier balance")
    for tier in config.TIERS:
        minutes = report.minutes_by_tier.get(tier, 0)
        if minutes:
            st.markdown(
                f"- **{config.tier_label(tier, student['name'])}** — {round(minutes / 60, 1):g} hrs"
            )
    if report.tier3_minutes:
        st.caption(
            f"Tier 3 is {report.tier3_percent:g}% of logged hours "
            f"(family guideline: {report.tier3_cap_percent}%)."
        )

st.divider()

# --- recent quiz results -------------------------------------------------------
# Passing a quiz auto-records mastery, but nothing else surfaced that it had even
# happened -- a parent had no way to see he'd taken and passed one at all, only
# the skill dropdown on Math's own "Record mastery" tab, if you knew to check it.

st.subheader("Recent quiz results")
quizzed = [
    lesson
    for lesson in db.list_lessons(student["id"], limit=25)
    if (lesson.get("metadata") or {}).get("quiz_result", {}).get("total")
]
quizzed.sort(key=lambda l: l["metadata"]["quiz_result"]["graded_on"], reverse=True)
if not quizzed:
    st.caption("No quizzes taken yet.")
else:
    for lesson in quizzed[:5]:
        result = lesson["metadata"]["quiz_result"]
        pct = round(100 * result["correct"] / result["total"])
        verdict = "🎯 passed" if result["passed"] else "below the pass threshold"
        st.markdown(
            f"**{result['graded_on']}** — {lesson['title']} "
            f"({lesson['agent'].title()}) — {result['correct']}/{result['total']} "
            f"({pct}%) — {verdict}"
        )

st.divider()

# --- recent activity ----------------------------------------------------------

st.subheader("Recently logged")
recent = db.list_activities(student["id"], limit=8)
if not recent:
    st.caption("Nothing logged yet. Generate a lesson, or log an activity directly.")
else:
    for activity in recent:
        credit_summary = " · ".join(
            f"{label(subject)} {minutes}m" for subject, minutes in activity["credits"].items()
        )
        st.markdown(
            f"**{activity['occurred_on']}** — {md(activity['title'])} "
            f"({activity['minutes']} min) — {credit_summary}"
        )
st.page_link("pages/10_Activity_Log.py", label="Full activity log", icon="🗂️")
