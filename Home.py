"""Compass — homeschool curriculum home page."""

from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

from compass import config, daily, weekly
from compass.agents import all_agents
from compass.compliance import build_report
from compass.curriculum import frontier_report
from compass.subjects import label
from compass.ui import (
    context_for,
    is_parent,
    md,
    page_setup,
    render_board_backlog,
    render_board_days,
    render_brain_break,
    render_card_heading,
    render_daily_due,
    render_declaration_banner,
    render_first_day_celebration,
    render_message_thread,
    render_progress_panel,
    render_report_card,
    render_xp_reward_editor,
    render_today_checklist,
    render_travel_passport,
    render_reading_board_card,
    render_xp_level,
    _writing_rework_summary,
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
    # A rotating, on-theme hello under his name -- a tiny "make it fun" touch,
    # deterministic per day (compass.daily) so it holds all day but changes
    # morning to morning.
    st.caption(f"{daily.greeting_of_the_day()} Work down the list, or jump around — up to you.")

    # Two cards side by side. On the Today view: "Due today" on the LEFT (what he
    # owes today, the first thing to grab him), and his Level card on the RIGHT
    # with the progress KPIs at the bottom of it. Off the Today view there's
    # nothing due to show, so the Level+progress card stands alone, full width.
    # Bordered containers opt into the same balance CSS (theme.py) that equalizes
    # a row of `st.container(border=True)` cards.
    today_iso = date.today().isoformat()

    def _render_level_and_progress() -> None:
        render_xp_level(db, student)
        st.divider()
        render_progress_panel(db, student)

    if active_view == "today":
        header_columns = st.columns(2)
        with header_columns[0]:
            with st.container(border=True, key="landon_card_today"):
                render_daily_due(db, student, today_iso)
        with header_columns[1]:
            with st.container(border=True, key="landon_card_xp"):
                _render_level_and_progress()
    else:
        with st.container(border=True, key="landon_card_xp"):
            _render_level_and_progress()

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

        # Messages from his parent, right at the top -- auto-opens with a count
        # when there's something new, so it's the first thing he sees.
        render_message_thread(db, student, sender="student")

        # Morning Routine and Check-In no longer get their own cards here --
        # they're folded into the "Due today" list in the header card as tight
        # tiles that link out to their pages (render_daily_due), so the whole
        # "what do I do today" flow, start-of-day rituals included, lives in one
        # place up top instead of a separate row of cards.

        # Lessons -- a roster of *links* out to each subject's own page,
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
        for agent_key, (page_path, subject_label) in CORE_SUBJECT_PAGES.items():
            agent_lessons = db.list_lessons(student["id"], agent=agent_key, limit=10)
            lesson, marker = weekly.today_subject_status(agent_lessons, today)
            if lesson is not None:
                roster.append((lesson, marker, page_path, subject_label))

        # Each lesson gets its own bordered card -- the same white-box
        # treatment the Morning Routine and Check-In cards use -- with its
        # review-gate status spelled out on the card itself, rather than one
        # shared legend under a flat list of links.
        LESSON_STATUS_LABELS = {
            "✅": "approved",
            "📤": "waiting on a parent",
            "↩️": "sent back",
            "⬜": "not turned in yet",
            "📣": "a note from your parent to read",
        }
        # Big Project steps a parent assigned to a day (on the Board) belong on
        # his main list too, not just buried on the Board tab -- reported: "the
        # projects assigned on the board need to show on his main page under
        # lessons." Same due/upcoming shape as lessons and life skills, rendered
        # as the same white cards right under the lessons so it reads as one
        # to-do list.
        due_steps = db.due_project_steps(student["id"], today)

        render_card_heading(f"📚 Lessons ({len(roster) + len(due_steps)})")
        if not roster and not due_steps:
            with st.container(border=True, key="landon_card_lessons_empty"):
                st.caption(
                    "Nothing new is set up yet. Check back after your parent plans a lesson."
                )
        else:
            for lesson, marker, page_path, subject_label in roster:
                # A sent-back lesson gets its own key prefix so its card can be
                # tinted red and stand out from the rest of the roster -- it's
                # the one thing on the page that's actually waiting on *him* to
                # fix and turn back in, so it should never blend in with the
                # others ("if item is sent back, i want it to stand out for
                # sure"). Both keys still start with `landon_card` so both keep
                # the shared white fill; the sent-back rule paints over it.
                sent_back = marker == "↩️"
                card_key = (
                    f"landon_card_lesson_sentback_{lesson['id']}"
                    if sent_back
                    else f"landon_card_lesson_{lesson['id']}"
                )
                with st.container(border=True, key=card_key):
                    title = lesson["payload"].get("title", lesson["title"])
                    st.page_link(
                        page_path, label=f"{md(title)} — {subject_label}", icon=marker
                    )
                    if sent_back:
                        # Name the specific pieces that need work right on the
                        # card, so he knows which activity to open the lesson for
                        # rather than a blanket "something's wrong in here"
                        # ("its hard for him to know which actual activity has
                        # feedback/rework required").
                        flagged = _writing_rework_summary(
                            lesson["payload"].get("activities") or [],
                            lesson.get("metadata") or {},
                        )
                        if flagged:
                            names = ", ".join(
                                f"#{item['number']} {md(item['title'])}" for item in flagged
                            )
                            st.markdown(f":red[**↩️ Sent back — fix activity {names}**]")
                        else:
                            st.markdown(
                                ":red[**↩️ Sent back — open it to see what to fix**]"
                            )
                    else:
                        status_label = LESSON_STATUS_LABELS.get(marker)
                        if status_label:
                            st.caption(f"{marker} {status_label}")
            # Project steps go through the same submit -> review -> approve gate
            # a lesson does, so they carry the same four-state markers: his to do
            # (⬜), turned in and waiting on a parent (📤), sent back for a redo
            # (↩️, tinted red to stand out like a bounced lesson).
            PROJECT_STATUS_MARKERS = {
                "planned": ("⬜", "project step — not turned in yet"),
                "submitted": ("📤", "project step — waiting on a parent"),
                "needs_revision": ("↩️", "project step — sent back"),
            }
            for step in due_steps:
                status = step.get("status") or "planned"
                marker, step_label = PROJECT_STATUS_MARKERS.get(
                    status, ("⬜", "project step")
                )
                step_sent_back = status == "needs_revision"
                step_key = (
                    f"landon_card_lesson_sentback_project_{step['id']}"
                    if step_sent_back
                    else f"landon_card_project_{step['id']}"
                )
                with st.container(border=True, key=step_key):
                    project_title = step.get("project_title") or "Big Project"
                    st.page_link(
                        "pages/7_Big_Projects.py",
                        label=f"{md(step['title'])} — {md(project_title)}",
                        icon=marker,
                    )
                    if step_sent_back:
                        st.markdown(
                            ":red[**↩️ Sent back — open Big Projects to see what to fix**]"
                        )
                    else:
                        st.caption(f"{marker} {step_label}")

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
            with st.container(border=True, key="landon_card_travel"):
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
                        "week — see the **Board**."
                    )
                if later_trips_week:
                    st.caption(
                        f"{later_trips_week} more trip(s) assigned for a later week — "
                        "see the **Board**."
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
            with st.container(border=True, key="landon_card_feedback"):
                render_card_heading(f"💬 Feedback ({len(unread_feedback)})")
                for entry, marker in feedback_roster:
                    st.page_link(
                        "pages/9_Landons_Travels.py",
                        label=md(entry["title"] or entry["state"] or "Untitled trip"),
                        icon=marker,
                    )
                st.caption("📬 waiting on you to read  \n✅ read today")

        # Notes a parent left when *approving* a piece of writing no longer show
        # here -- feedback lives in the lesson, on the subject page, under the
        # activity it's about (see _render_pending_writing_notes). The subject's
        # own roster row above keeps pointing him there (a 📣 marker) until he's
        # read and replied to the note, so nothing is lost by moving it off his
        # main board.

        # Words to Review, Reading, and Life Skills used to be a three-tile row
        # here; they're now folded into the header card beside the streak/KPIs
        # (render_daily_due), so "what do I owe today" lives in one place up top
        # instead of a second row lower down the page.

        render_today_checklist(db, student)

        # 🎉 A one-time "nice work" the first time he's cleared his part of
        # today's lessons -- a little "make it fun" payoff. Fires once per day
        # (session-gated) and only when there's actually a roster to clear:
        # every subject's lesson is either approved (✅) or turned in and
        # waiting on a parent (📤), with nothing left needing his action.
        lessons_cleared = bool(roster) and all(
            marker in ("✅", "📤") for _, marker, _, _ in roster
        )
        celebrated_key = f"day_cleared_{today}"
        if lessons_cleared and not st.session_state.get(celebrated_key):
            st.session_state[celebrated_key] = True
            st.success("🎉 You cleared today's lessons — nice work!")

        # A collectible he fills in over the year -- shows only once he's got
        # travel entries, so it never sits empty.
        render_travel_passport(db, student)

        # A fun aside to end on: fun fact, riddle, word of the day, history.
        render_brain_break()

    # === Board ===================================================================
    # The same sprint board a parent sees on Mission Control's Board tab,
    # rendered read-only for him (render_board_days(interactive=False) -- no
    # move controls, no parent management deep links, just the cards and, on a
    # lesson, the View-full-lesson dialog). A forward week-pager, not just a
    # this/next toggle: a parent can schedule several weeks ahead, so he can
    # page forward as far as there's anything to see. Read-only either way --
    # this only lays out whatever a parent has already scheduled onto a day.

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
        # The standing daily-reading card, read-only for him, shown once on the
        # this-week view (it's the same every day, so it doesn't repeat under
        # future weeks).
        if offset == 0:
            render_reading_board_card(db, student, can_edit=False)
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

# The weekly XP goal and reward he's climbing toward, editable here -- the XP
# card itself is student-only, so this is where a parent sets what he's working
# toward each week.
with st.expander("🎁 Weekly reward"):
    render_xp_reward_editor(db)

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
st.page_link(
    "pages/14_Mission_Control.py", label="Review & full record — Mission Control", icon="🚀"
)
