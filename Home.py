"""Compass — homeschool curriculum home page."""

from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

from compass import config, weekly
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
    render_board_backlog,
    render_board_days,
    render_card_heading,
    render_declaration_banner,
    render_first_day_celebration,
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
        ("board", "🗓️", "Board"),
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
    # A view key left over from before This Week + Upcoming Week were folded
    # into one Board -- snap it to the Board so an old session_state value
    # doesn't land on a view that no longer has a nav button.
    if active_view in ("week", "upcoming"):
        active_view = "board"
    nav_columns = st.columns(3)
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

    # A plain styled div, not `st.title` -- the fixed theme reserves the
    # loud, gold, all-caps h1 treatment for a page's one real title (see
    # theme.py), and Landon said the giant shouted version of this looked
    # bad next to everything else now packed onto Home. This sidesteps that
    # global rule the same way render_card_heading does below, since it
    # isn't a real `<h1>` for the theme's CSS to catch.
    st.markdown(
        f'<div style="font-size:30px; font-weight:700; color:var(--c-text); '
        f'margin-bottom:2px;">Hi {md(student["name"].split()[0])} 👋</div>',
        unsafe_allow_html=True,
    )
    # The date, right under his name -- reported directly: "on the home screen,
    # can we add the date for landon to see somewhere." A real, readable
    # weekday + date (not the ISO string), so he always knows what day it is
    # and which day's work he's looking at.
    st.markdown(
        f'<div style="font-size:15px; font-weight:600; color:var(--c-primary); '
        f'margin:0 0 4px;">📅 {date.today().strftime("%A, %B %-d, %Y")}</div>',
        unsafe_allow_html=True,
    )
    st.caption("Here's what's set up for you. Work down the list, or jump around — up to you.")

    # Streak and fun fact are a matched pair, side by side, same width and
    # height -- not the streak tucked under the greeting with fun fact off
    # on its own. Bordered containers opt both into the same balance CSS
    # (theme.py) that equalizes a row of `st.container(border=True)` cards.
    header_columns = st.columns(2)
    with header_columns[0]:
        with st.container(border=True):
            render_streak(db, student)
    with header_columns[1]:
        with st.container(border=True):
            render_fun_fact()

    st.divider()

    # Shared with both the Today card below and the Week grid further down
    # -- a travel entry assigned to a day goes through the same review gate
    # a lesson does, so it gets the same four-state marker set instead of
    # skills' plain done/not-done one.
    TRAVEL_MARKERS = {
        "planned": "⬜",
        "submitted": "📤",
        "needs_revision": "↩️",
    }

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
        extra_columns = st.columns(2)
        extra_columns[0].page_link("pages/7_Big_Projects.py", label="Big Projects", icon="🎬")
        extra_columns[1].page_link("pages/6_Life_Skills.py", label="Life Skills", icon="🛠️")

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
                    "see **Mission Control**."
                )
            if later_week:
                st.caption(
                    f"{later_week} more lesson(s) planned for a later week — see "
                    "**Upcoming Week**."
                )

        # 2b. Travel journal entries a parent assigned to a specific day --
        # only when there's actually one due or upcoming, same as Life
        # Skills used to render before it joined the row below: most
        # families never assign a trip, so most Home pages never show
        # this at all. Unlike Life Skills, an assigned trip goes through
        # the same review gate a lesson does (see pages/9_Landons_Travels.py),
        # so it gets the same four-state TRAVEL_MARKERS set (defined above,
        # shared with the Week grid) instead of a plain done/not-done one.
        due_trips = db.due_travel_entries(student["id"], today)
        upcoming_trips = db.upcoming_travel_entries(student["id"], today)
        later_trips_this_week = sum(
            1 for t in upcoming_trips if t["scheduled_for"] <= this_week_end
        )
        later_trips_week = len(upcoming_trips) - later_trips_this_week
        if due_trips or upcoming_trips:
            with st.container(border=True):
                render_card_heading(f"🧭 Travel Journal ({len(due_trips)})")
                for trip in due_trips:
                    marker = TRAVEL_MARKERS.get(trip["status"], "⬜")
                    when = (
                        "today" if trip["scheduled_for"] == today
                        else f"since {trip['scheduled_for']}"
                    )
                    st.page_link(
                        "pages/9_Landons_Travels.py",
                        label=f"{md(trip['title'] or trip['state'] or 'Pick a trip to write about')} — {when}",
                        icon=marker,
                    )
                if due_trips:
                    st.caption("⬜ not written yet  \n📤 waiting on a parent  \n↩️ sent back")
                else:
                    st.caption("Nothing due today.")
                if later_trips_this_week:
                    st.caption(
                        f"{later_trips_this_week} more trip(s) assigned for later this "
                        "week — see **Mission Control**."
                    )
                if later_trips_week:
                    st.caption(
                        f"{later_trips_week} more trip(s) assigned for a later week — "
                        "see **Upcoming Week**."
                    )

        # 2c. Feedback he hasn't acknowledged yet -- separate from the due
        # card above, since this isn't about writing anything, it's about
        # actually reading what a parent already said about a trip he
        # already turned in. Home only tees this up -- a link out to where
        # the feedback and the read/reply gate actually live (same "the
        # roster is links out, not embedded content" shape as the Lessons
        # card above) -- reading and replying both happen on the journal
        # page. Once he does, it doesn't just vanish: it stays on today's
        # roster with a ✅ instead of a 📬, exactly how a lesson approved
        # today still shows here rather than disappearing the instant it's
        # done (see weekly.today_subject_status) -- a real confirmation
        # it went through, not just an assumption.
        unread_feedback = db.unread_travel_feedback(student["id"])
        read_today_feedback = db.travel_feedback_read_today(student["id"], today)
        feedback_roster = [(e, "📬") for e in unread_feedback] + [
            (e, "✅") for e in read_today_feedback
        ]
        if feedback_roster:
            with st.container(border=True):
                render_card_heading(f"💬 Feedback ({len(unread_feedback)})")
                for entry, marker in feedback_roster:
                    st.page_link(
                        "pages/9_Landons_Travels.py",
                        label=md(entry["title"] or entry["state"] or "Untitled trip"),
                        icon=marker,
                    )
                st.caption("📬 waiting on you to read  \n✅ read today")

        # 3. Words to Review, Reading, and Life Skills all in one row of
        # three equal columns -- small, single-purpose tiles that each just
        # say what's outstanding and link to where it's actually done,
        # rather than each getting its own full-width or half-width row.
        # Cuts the page's overall length versus stacking them, and every
        # tile always renders (even with nothing due) so the row never
        # shifts shape depending on what's assigned.
        #
        # Life Skills' own tile also folds in Student's Choice and Coding --
        # both now live as tabs on the same page (see pages/6_Life_Skills.py),
        # so a separate tile per tab would just be the same "Open Life
        # Skills" link three times over. One tile, one link; the due-skills
        # list stays the tile's primary content since that's the one with
        # actual per-item day tracking, with the other two as compact counts.
        due_skills = db.due_life_skills(student["id"], today)
        upcoming_skills = db.upcoming_life_skills(student["id"], today)
        later_skills_this_week = sum(
            1 for s in upcoming_skills if s["scheduled_for"] <= this_week_end
        )
        later_skills_week = len(upcoming_skills) - later_skills_this_week

        due = db.vocabulary_due(student["id"], limit=25)
        book = db.current_book(student["id"])
        topics = [
            t
            for t in db.list_choice_topics(student["id"])
            if t["status"] in ("active", "approved")
        ]
        due_coding = db.due_coding_modules(student["id"], today)

        extras_columns = st.columns(3)
        with extras_columns[0]:
            with st.container(border=True):
                render_card_heading("🔤 Words to Review")
                if due:
                    st.caption(f"{len(due)} word(s) due today.")
                    st.page_link("pages/3_English.py", label="Review them", icon="➡️")
                else:
                    st.success("✅ Nothing due today.")
        with extras_columns[1]:
            with st.container(border=True):
                render_card_heading("📖 Reading")
                if book:
                    st.markdown(f"**{md(book['title'])}**")
                    if book["total_pages"]:
                        st.progress(
                            min((book["current_page"] or 0) / book["total_pages"], 1.0),
                            text=f"page {book['current_page']} of {book['total_pages']}",
                        )
                    st.page_link("pages/3_English.py", label="Open English", icon="➡️")
                else:
                    st.caption("No book set up yet.")
        with extras_columns[2]:
            with st.container(border=True):
                render_card_heading(f"🛠️ Life Skills ({len(due_skills)})")
                # `due_life_skills`/`upcoming_life_skills` -- see those
                # docstrings for why "assigned" is `<=`/`>` today, not `==`:
                # a family that never assigns a day never sees anything
                # here but the plain "nothing assigned" state.
                if due_skills:
                    for skill in due_skills:
                        when = (
                            "today" if skill["scheduled_for"] == today
                            else f"since {skill['scheduled_for']}"
                        )
                        st.page_link(
                            "pages/6_Life_Skills.py",
                            label=f"{md(skill['title'])} — {when}",
                            icon="🛠️",
                        )
                else:
                    st.caption("Nothing due today.")
                if later_skills_this_week:
                    st.caption(f"+{later_skills_this_week} later this week")
                if later_skills_week:
                    st.caption(f"+{later_skills_week} later")
                if topics:
                    st.caption(f"⭐ {len(topics)} on Student's Choice")
                if due_coding:
                    st.caption(f"💻 {len(due_coding)} coding module(s) due")
                st.page_link("pages/6_Life_Skills.py", label="Open Life Skills", icon="➡️")

        render_today_checklist(db, student)

    # === Board ===================================================================
    # The exact same sprint board a parent sees on This Week, rendered
    # read-only for him (render_board_days(interactive=False) -- no move
    # controls, no parent management deep links, just the cards and, on a
    # lesson, the View-full-lesson dialog). A forward week-pager, not just a
    # this/next toggle: a parent can plan several weeks ahead now (This Week's
    # "Plan next week" takes any target week), so he can page forward as far as
    # there's anything to see. Read-only either way -- the plan is set by a
    # parent's Friday planning; this only lays out what's already scheduled.

    if active_view == "board":
        # 0 = this week; never goes before it (the past is on the record, not
        # something he re-plans), and forward as far as he likes.
        offset = max(0, int(st.session_state.get("student_board_offset", 0)))

        nav_columns = st.columns([1, 1, 1, 3])
        if nav_columns[0].button(
            "◀ Earlier", key="student_board_prev", width="stretch", disabled=offset == 0
        ):
            st.session_state["student_board_offset"] = max(0, offset - 1)
            st.rerun()
        if nav_columns[1].button(
            "This week", key="student_board_this", width="stretch",
            type="primary" if offset == 0 else "secondary",
        ):
            st.session_state["student_board_offset"] = 0
            st.rerun()
        if nav_columns[2].button("Later ▶", key="student_board_next", width="stretch"):
            st.session_state["student_board_offset"] = offset + 1
            st.rerun()

        board_week_start = this_week_start + timedelta(days=7 * offset)
        board_range = weekly.week_dates(board_week_start, include_friday=True)
        when = "this week" if offset == 0 else "next week" if offset == 1 else f"{offset} weeks out"
        tail = (
            "everything set up for you this week — today's work included."
            if offset == 0
            else f"the plan for {when}, once your parent sets it up -- usually on a Friday."
        )
        st.caption(
            f"{board_range[0].strftime('%b %-d')} – "
            f"{board_range[-1].strftime('%b %-d, %Y')} · {tail}"
        )
        student_board = weekly.board_for_week(db, student, board_week_start)
        render_board_days(
            db, student, board_week_start, student_board,
            key_prefix="student_board", interactive=False,
        )
        # Parked stories, read-only, so he can open the full lesson for anything
        # not pinned to a day too -- reported directly: from his board he should
        # be able to "view full lesson for anything thats in view there. backlog
        # or assigned a date." The backlog is week-agnostic (the same whichever
        # week is on screen), so it's shown once, on the this-week view, rather
        # than repeated under every future week.
        if offset == 0 and student_board["backlog"]:
            st.divider()
            st.markdown("**📋 Not scheduled yet**")
            st.caption("Set up for you, without a set day — peek anytime.")
            render_board_backlog(
                db, student, student_board,
                key_prefix="student_board", board_week_start=board_week_start,
                interactive=False,
            )
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
