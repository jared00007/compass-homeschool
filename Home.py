"""Compass — homeschool curriculum home page."""

from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

from compass import config, theme, weekly
from compass.agents import all_agents
from compass.compliance import build_report
from compass.curriculum import frontier_report
from compass.subjects import label
from compass.ui import (
    SUBJECT_ICONS,
    context_for,
    is_parent,
    md,
    page_setup,
    render_card_heading,
    render_declaration_banner,
    render_first_day_celebration,
    render_friday_plan,
    render_fun_fact,
    render_morning_routine,
    render_report_card,
    render_streak,
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
    if render_first_day_celebration(db, student):
        st.stop()

    # Nav-first: which view of Home (not which page of the app -- that's the
    # sidebar, untouched) is showing, as a row of big buttons rather than the
    # small text tabs this used to be. A real `st.session_state` switch
    # rather than `st.tabs()` on purpose -- it's the only way to put shared
    # header content (greeting, streak, fun fact) *between* the nav row and
    # whichever view's body is showing, matching the picked design; content
    # rendered after `st.tabs()` but outside any `with tab:` block renders
    # below the whole tab widget, not between its bar and its panel.
    _HOME_VIEWS = (
        ("today", "📅", "Today"),
        ("week", "🗓️", "This Week"),
        ("upcoming", "🔜", "Upcoming Week"),
        ("grades", "🎓", "Grades"),
    )
    # A Streamlit button's default padding is sized for one button standing
    # alone, not four in a row acting as a nav bar -- slimmed down here,
    # scoped to just these four keys, so it reads as a compact tab strip
    # rather than four separate full-size buttons stacked side by side.
    st.markdown(
        """
        <style>
        div[class*="st-key-home_nav_"] button {
          padding-top: 0.35rem;
          padding-bottom: 0.35rem;
          font-size: 14px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    active_view = st.session_state.get("home_view", "today")
    nav_columns = st.columns(4)
    for nav_column, (view_key, view_icon, view_label) in zip(nav_columns, _HOME_VIEWS):
        with nav_column:
            if st.button(
                f"{view_icon}  {view_label}",
                key=f"home_nav_{view_key}",
                width="stretch",
                type="primary" if view_key == active_view else "secondary",
            ):
                # Rerun rather than just updating `active_view` in place --
                # the four buttons render in a single left-to-right pass, so
                # a button rendered *before* the one just clicked would
                # otherwise still compute its own primary/secondary look
                # from the stale value, one click behind (confirmed live:
                # clicking Grades left This Week looking pressed instead).
                # Restarting from the top lets every button's own render
                # read the same, already-updated session_state value.
                st.session_state["home_view"] = view_key
                st.rerun()

    # Compact header: greeting beside a narrow column holding streak and fun
    # fact stacked on top of each other -- side by side by side made the
    # streak and fact cards read as three competing banners in one row;
    # stacking the two small ones under each other reads as one card group
    # instead, and the streak's own milestone callout (comic-styled, wider
    # than the ordinary one-line version) has more of that column's width to
    # work with than a three-way split gave it.
    header_columns = st.columns([2, 1])
    with header_columns[0]:
        # A plain styled div, not `st.title` -- the fixed theme reserves the
        # loud, gold, all-caps h1 treatment for a page's one real title (see
        # theme.py), and Landon said the giant shouted version of this
        # looked bad next to everything else now packed onto Home. This
        # sidesteps that global rule the same way render_card_heading does
        # below, since it isn't a real `<h1>` for the theme's CSS to catch.
        st.markdown(
            f'<div style="font-size:30px; font-weight:700; color:var(--c-text); '
            f'margin-bottom:2px;">Hi {md(student["name"].split()[0])} 👋</div>',
            unsafe_allow_html=True,
        )
        st.caption("Here's what's set up for you. Work down the list, or jump around — up to you.")
    with header_columns[1]:
        render_streak(db, student)
        render_fun_fact()

    st.divider()

    # "Sunday Funnies" week-grid styling -- one of three retro comic
    # directions sampled and approved before building (see Home's own week
    # tab). Deliberately this one fixed printed-poster palette, not
    # theme.py's own themed `Theme` tokens -- see compass/theme.py's own
    # PRINTED_COMIC_* constants, shared with the first-day celebration so
    # the two can't drift out of sync with each other.
    _WEEK_DAY_COLORS = theme.PRINTED_COMIC_WEEKDAY_COLORS  # Mon-Fri
    _WEEK_INK = theme.PRINTED_COMIC_INK
    _WEEK_PAPER = theme.PRINTED_COMIC_PAPER
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

    # === Today ===================================================================
    # Grades get their own view rather than a block here: he asked to be
    # graded, so it needs to be somewhere he can actually go and look -- but
    # sitting above the checklist it would be the first thing he reads every
    # morning, which is the opposite of the point.

    if active_view == "today":
        # A 2-column card grid rather than one long stack of sections divided
        # by hairlines -- the same information, laid out to use the width a
        # desktop actually has instead of one narrow scrolling column.
        today = date.today().isoformat()

        # 1. Morning routine and Check-In, side by side, right under the
        # header -- balances the header row's left/right split instead of
        # leaving the space under the greeting empty until Lessons starts.
        # Both stay exactly as compact as they already render (Morning
        # Routine's own steps sit behind a collapsed expander), just moved
        # up rather than resized.
        grid_columns = st.columns(2)
        with grid_columns[0]:
            with st.container(border=True):
                render_morning_routine(db, student)
        with grid_columns[1]:
            with st.container(border=True):
                checked_in = db.journal_entry_for_date(student["id"], today) is not None
                render_card_heading("💬 Check-In")
                if checked_in:
                    st.success("✅ You've checked in today.")
                else:
                    st.caption("Take a second to say how you're doing today.")
                st.page_link(
                    "pages/8_Check_In.py",
                    label="Check in again" if checked_in else "Open Check-In",
                    icon="➡️",
                )

        # 2. Lessons -- a roster of *links* out to each subject's own page,
        # not the lesson's own content embedded here. Each subject's marker
        # reflects its real review-gate state (weekly.today_subject_status),
        # not just whether he's clicked anything: turned in and waiting on a
        # parent, sent back and waiting on him again, still untouched, or
        # fully approved -- a subject only drops off the roster once there's
        # truly nothing relevant to it today.
        CORE_SUBJECT_PAGES = {
            "math": ("pages/1_Math.py", "Math"),
            "science": ("pages/2_Science.py", "Science"),
            "english": ("pages/3_English.py", "English"),
            "history": ("pages/4_History.py", "History"),
        }
        roster: list[tuple[dict, str, str, str]] = []
        later_this_week = 0
        later_week = 0
        for agent_key, (page_path, subject_label) in CORE_SUBJECT_PAGES.items():
            agent_lessons = db.list_lessons(student["id"], agent=agent_key, limit=10)
            lesson, marker = weekly.today_subject_status(agent_lessons, today)
            if lesson is not None:
                roster.append((lesson, marker, page_path, subject_label))
            for candidate in agent_lessons:
                planned_for = (candidate.get("metadata") or {}).get("planned_for")
                if planned_for and planned_for > today and candidate["status"] == "planned":
                    if planned_for <= this_week_end:
                        later_this_week += 1
                    else:
                        later_week += 1

        with st.container(border=True):
            render_card_heading(f"📚 Lessons ({len(roster)})")
            if not roster:
                st.caption(
                    "Nothing new is set up yet. Check back after your parent plans a lesson."
                )
            else:
                roster_columns = st.columns(2)
                for index, (lesson, marker, page_path, subject_label) in enumerate(roster):
                    with roster_columns[index % 2]:
                        title = lesson["payload"].get("title", lesson["title"])
                        st.page_link(
                            page_path, label=f"{md(title)} — {subject_label}", icon=marker
                        )
                st.caption(
                    "✅ approved  \n"
                    "📤 waiting on a parent  \n"
                    "↩️ sent back  \n"
                    "⬜ not turned in yet"
                )
            if later_this_week:
                st.caption(
                    f"{later_this_week} more lesson(s) planned for later this week — "
                    "see **This Week**."
                )
            if later_week:
                st.caption(
                    f"{later_week} more lesson(s) planned for a later week — see "
                    "**Upcoming Week**."
                )

        # 2b. Life skills assigned to a specific day -- only when there's
        # actually one due, so a family that never assigns a day (the
        # default) never sees this card at all. Includes anything assigned
        # for today or earlier and still not done, same "never silently
        # drops it" rule an unfinished lesson already gets.
        due_skills = db.due_life_skills(student["id"], today)
        if due_skills:
            with st.container(border=True):
                render_card_heading(f"🛠️ Life Skills ({len(due_skills)})")
                for skill in due_skills:
                    when = "today" if skill["scheduled_for"] == today else f"since {skill['scheduled_for']}"
                    st.page_link(
                        "pages/6_Life_Skills.py",
                        label=f"{md(skill['title'])} — assigned {when}",
                        icon="🛠️",
                    )

        # 3. Vocabulary review and 4. Reading, side by side; Choice Topics
        # spans the full width below (its list can run a few items long).
        # Same limit render_vocab_review uses for "words due," so this count
        # matches what he'll actually see when he clicks through.
        due = db.vocabulary_due(student["id"], limit=25)
        grid_columns_2 = st.columns(2)
        with grid_columns_2[0]:
            with st.container(border=True):
                render_card_heading("🔤 Words to Review")
                if due:
                    st.caption(f"{len(due)} word(s) due today.")
                    st.page_link("pages/3_English.py", label="Review them", icon="➡️")
                else:
                    st.success("✅ Nothing due today.")
        with grid_columns_2[1]:
            with st.container(border=True):
                render_card_heading("📖 Reading")
                book = db.current_book(student["id"])
                if book:
                    st.markdown(f"**{md(book['title'])}**")
                    if book["total_pages"]:
                        st.progress(
                            min((book["current_page"] or 0) / book["total_pages"], 1.0),
                            text=f"page {book['current_page']} of {book['total_pages']}",
                        )
                else:
                    st.caption("No book set up yet.")

        with st.container(border=True):
            render_card_heading("⭐ Your Choice Topics")
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

        render_today_checklist(db, student)

    # === This Week / Upcoming Week ===============================================
    # Both read-only -- the plan itself is set by a parent on This Week (Friday
    # planning), these just lay out what's already there day by day so he can
    # see the week ahead without clicking into Monday through Friday one at a
    # time. Upcoming Week is only ever as populated as however far ahead a
    # parent has actually planned -- usually nothing until the Friday before.

    next_week_start = this_week_start + timedelta(days=7)

    if active_view == "week":
        st.caption(
            f"{this_week_start.strftime('%b %-d')} – "
            f"{(this_week_start + timedelta(days=4)).strftime('%b %-d')} · "
            "only shows what's been planned through weekly planning -- anything "
            "generated on the fly still shows up on **Today**, not here."
        )
        _render_week_grid(this_week_start)
        _render_extra_activities()

    elif active_view == "upcoming":
        st.caption(
            f"{next_week_start.strftime('%b %-d')} – "
            f"{(next_week_start + timedelta(days=4)).strftime('%b %-d')} · "
            "next week's plan, once your parent sets it up -- usually on a "
            "Friday, for the week ahead."
        )
        _render_week_grid(next_week_start)
        _render_extra_activities()

    elif active_view == "grades":
        st.caption(
            "One grade per subject, and what goes into each. Nothing here is "
            "based on how long you worked — only on what you turned in."
        )
        render_report_card(db, student, for_parent=False)

    st.stop()

# --- parent view --------------------------------------------------------------

st.title("🧭 Compass")
st.caption(
    f"Multi-agent homeschool curriculum for {student['name']}, grade {student['grade']}."
)
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

# --- grades --------------------------------------------------------------------
# The same report card he sees on his own Grades tab, read from the same
# gradebook -- there is deliberately no second, parent-only set of numbers.
# If a grade looks wrong here, it's wrong on his screen too.

st.subheader("Report card")
st.caption("Same numbers he sees. Hours logged and his streak are not part of any grade.")
render_report_card(db, student, for_parent=True)

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
