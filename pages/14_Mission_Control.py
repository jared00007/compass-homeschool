"""Mission Control -- the parent's weekly planner. Friday reviews the week just
finished, then plans the week ahead, so Monday through Thursday he opens a
lesson that's already sitting there instead of someone remembering to generate
one that morning. (Named "This Week" originally; renamed because reviewing and
planning several weeks out from one screen is the main planning surface, not a
this-week-only view -- "That function is the main planner.")

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
from functools import partial

import streamlit as st

from compass import config, gradebook, weekly
from compass.agents import all_agents
from compass.agents.framework import GeneratedLesson, TopicProposal
from compass.agents.strategies import ERAS, SCIENCE_DOMAINS
from compass.compliance import build_report
from compass.export import (
    lesson_to_docx,
    lesson_to_pdf,
    suggested_filename,
    suggested_pdf_filename,
)
from compass.subjects import SUBJECT_KEYS, label
from compass.ui import (
    FRIDAY_PLAN_KINDS,
    SUBJECT_ICONS,
    hand_in_summary,
    log_lesson_form,
    md,
    page_setup,
    parent_only,
    render_board_backlog,
    render_board_days,
    render_board_move_notice,
    render_earned_rewards,
    render_friday_plan,
    render_lesson,
    render_lesson_review,
    render_report_card,
    render_story_move_control,
    render_xp_reward_editor,
)

db, student = page_setup("Mission Control", icon="🚀")

st.title("🚀 Mission Control")
st.caption(
    "Friday reviews the week that just finished, then plans the next one -- "
    "so Monday through Thursday, a lesson is already waiting instead of "
    "someone remembering to generate it that morning."
)

if not parent_only("Weekly planning is for your parent."):
    st.stop()

# Parent-admin pages fold in here instead of cluttering the sidebar, reached by
# a button (not another tab). Everything a parent (and only a parent) manages
# now hangs off this one hub, so the sidebar is just the student's own subjects.
_hub_links = st.columns(4)
if _hub_links[0].button("🎓 Course records", width="stretch", key="hub_courses"):
    st.switch_page("pages/13_Courses.py")
if _hub_links[1].button("🧑‍🎓 Profile", width="stretch", key="hub_profile"):
    st.switch_page("pages/12_Student_Profile.py")
if _hub_links[2].button("📋 Compliance", width="stretch", key="hub_compliance"):
    st.switch_page("pages/11_Compliance.py")
if _hub_links[3].button("💵 Spend", width="stretch", key="hub_costs"):
    st.switch_page("pages/15_Model_Costs.py")
st.divider()

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


# --- the review queue: reading his work and acting on it ------------------------


def _lesson_date(lesson: dict) -> str:
    """The date that actually matters for review: the day a lesson is
    *planned for*, if it was batch-planned -- not when it happened to be
    generated. Those agree for an ordinary on-demand lesson, but not once a
    whole week gets batch-planned in one sitting: every lesson in that batch
    shares the same created_at, which tells you nothing about which day each
    one is actually for."""
    return (lesson.get("metadata") or {}).get("planned_for") or lesson["created_at"][:10]


def _review_summary(lesson: dict) -> str:
    """A one-line, at-a-glance read of what's waiting inside a review card --
    what shows on the collapsed bar so you can triage the whole list without
    opening every one. Hand-ins waiting, whether the quiz is done and how he
    scored: the two things that decide whether this one needs a careful read
    or a quick approve."""
    payload = lesson.get("payload") or {}
    metadata = lesson.get("metadata") or {}
    bits: list[str] = []

    activities = payload.get("activities") or []
    hand_ins = sum(
        1
        for a in activities
        if a.get("kind") == "writing" or a.get("requires_written_response")
    )
    if hand_ins:
        bits.append(f"✍️ {hand_ins} hand-in{'s' if hand_ins != 1 else ''}")

    if payload.get("quiz"):
        quiz_result = metadata.get("quiz_result") or {}
        if quiz_result.get("total"):
            correct, total = quiz_result["correct"], quiz_result["total"]
            trophy = " 🎯" if quiz_result.get("passed") else ""
            bits.append(f"📝 quiz {correct}/{total}{trophy}")
        else:
            bits.append("📝 quiz not taken")

    minutes = sum(a.get("minutes", 0) for a in activities)
    if minutes:
        bits.append(f"⏱️ {minutes}m")

    return " · ".join(bits)


def _needs_attention(lesson: dict, today_iso: str) -> bool:
    """Genuinely waiting on you: he's turned it in, or it's overdue and still
    untouched -- but only within its own week. Once that week ends it's
    backlogged instead: out of his own view entirely, and no longer
    something today's date should keep flagging as urgent. A lesson sent
    back for revision is waiting on HIM, not you."""
    if lesson["status"] == "submitted":
        return True
    if lesson["status"] == "needs_revision":
        return False
    planned_for = (lesson.get("metadata") or {}).get("planned_for")
    if not planned_for or planned_for >= today_iso:
        return False
    return not weekly.is_backlogged(lesson, today_iso)


def _review_badge(lesson: dict, today_iso: str) -> str:
    if lesson["status"] != "planned":
        return {
            "completed": "✅ completed",
            "skipped": "⏭️ skipped",
            "submitted": "📤 turned in — waiting on you",
            "needs_revision": "↩️ sent back — waiting on him",
        }[lesson["status"]]
    if (lesson.get("metadata") or {}).get("held_back"):
        return "🗄️ backlogged"
    planned_for = (lesson.get("metadata") or {}).get("planned_for")
    if planned_for and planned_for < today_iso:
        return "⚠️ overdue"
    return "🕓 planned"


def _render_review_card_body(lesson: dict, today_iso: str) -> None:
    """Everything inside a lesson's review card: the printable copies, the
    whole lesson laid out with his work and the grading controls inline
    (render_lesson_review), the manual hours form for the non-graded
    subjects, and the skip/remove/move actions."""
    st.caption(
        f"{lesson['agent']} agent · strategy: {lesson['strategy']} · "
        f"topic: {md(lesson['topic'])}"
    )
    if lesson["rationale"]:
        st.caption(f"Why: {md(lesson['rationale'])}")
    student_done_on = (lesson.get("metadata") or {}).get("student_done_on")
    if student_done_on and lesson["status"] == "submitted":
        st.caption(f"🎓 He turned this in on {student_done_on}.")
    # Tell you up front how many written pieces this lesson should produce, so
    # you know what to expect back to grade -- "1 hand in or 2 hand in
    # activities." Skipped silently when there's nothing to hand in.
    handins = hand_in_summary(lesson["payload"])
    if handins:
        st.markdown(f"**{handins}**")
    credits = lesson["payload"].get("subject_credits") or []
    if credits:
        st.markdown(
            "Credit: "
            + " · ".join(f"{label(c['subject'])} {c['minutes']}m" for c in credits)
        )
    download_columns = st.columns(2)
    download_columns[0].download_button(
        "🖨️ Print to PDF",
        data=partial(lesson_to_pdf, lesson["payload"]),
        file_name=suggested_pdf_filename(lesson["payload"]),
        mime="application/pdf",
        key=f"pdf_{lesson['id']}",
    )
    download_columns[1].download_button(
        "📄 Word doc",
        data=partial(lesson_to_docx, lesson["payload"]),
        file_name=suggested_filename(lesson["payload"]),
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        key=f"docx_{lesson['id']}",
    )
    # The whole lesson, laid out the way his own screen lays it out, with
    # each submission and its approve/send-back controls sitting right under
    # the activity that produced it -- so grading is one read top to bottom.
    render_lesson_review(db, student, lesson, key_prefix=f"review_{lesson['id']}")
    # For a graded subject, hours only ever get logged through the combined
    # Approve action inside render_lesson_review above. This plain form stays
    # for Life Skills and anything else that never goes through the gate.
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
            key_prefix=f"review_{lesson['id']}",
            tier=tier,
        )
    if lesson["status"] in ("planned", "submitted", "needs_revision"):
        st.divider()
        skip_col, remove_col = st.columns(2)
        if skip_col.button("Mark skipped instead", key=f"skip_{lesson['id']}"):
            db.set_lesson_status(lesson["id"], "skipped")
            st.rerun()
        if remove_col.button("Remove", key=f"remove_lesson_{lesson['id']}"):
            db.delete_lesson(lesson["id"])
            st.rerun()
        # A lesson sent back for a redo is still an open story that might
        # genuinely need a later day. Not offered for 'submitted': it's
        # already turned in and waiting on a decision, not something to
        # reschedule out from under that.
        if lesson["status"] in ("planned", "needs_revision"):
            # No collision check on the target day: two lessons of the same
            # subject can share a day on purpose, so moving one is never
            # blocked ("just dont block me moving subject into a day").
            render_story_move_control(
                key=f"lesson_{lesson['id']}",
                active=not weekly.is_backlogged(lesson, today_iso),
                scheduled_for=(lesson.get("metadata") or {}).get("planned_for"),
                set_active=lambda a, lid=lesson["id"]: (
                    db.unhold_lesson(lid) if a else db.send_to_backlog(lid)
                ),
                schedule=lambda d, lid=lesson["id"]: db.reschedule_lesson(lid, d) if d else None,
            )


def _render_review_card(lesson: dict, today_iso: str, *, open: bool = False) -> None:
    """One lesson's review card, always a collapsible expander so a long
    review queue stays scannable -- reported directly: the ones waiting on you
    should "collapse to see just the bar level summary when closed and expand
    when time to review." `open` only sets the *starting* state (expanded for
    work that's genuinely waiting on you, collapsed for the quieter
    overdue/sent-back/backlog/history lists); either way it collapses to the
    same one-line summary bar. That bar carries a quick read of what's inside
    (hand-ins, quiz score, minutes) so you can triage without opening each."""
    header = f"{_review_badge(lesson, today_iso)} · {_lesson_date(lesson)} · {md(lesson['title'])}"
    summary = _review_summary(lesson)
    if summary:
        header += f"  ·  {summary}"
    with st.expander(header, expanded=open):
        _render_review_card_body(lesson, today_iso)


_TRAVEL_REVIEW_BADGES = {
    "submitted": "📤 turned in — waiting on you",
    "needs_revision": "↩️ sent back — waiting on him",
}


def _render_travel_review_card(entry: dict, *, open: bool = False) -> None:
    """A submitted (or sent-back) travel entry, reviewable right here -- same
    Approve/Send back actions as pages/9_Landons_Travels.py, so a trip
    waiting on you doesn't only show up if you happen to visit that page.
    Approving logs the same flat Writing/Social Studies credit it always
    has."""
    badge = _TRAVEL_REVIEW_BADGES[entry["status"]]
    title = entry["title"] or entry["state"] or "Untitled trip"
    header = f"{badge} · {entry['visited_on']} · 🧭 {md(title)}"

    def _body() -> None:
        if entry["story"]:
            st.write(md(entry["story"]))
        if entry["status"] == "needs_revision" and entry["revision_note"].strip():
            st.caption(f"You sent this back: {md(entry['revision_note'].strip())}")
        if entry["status"] == "submitted":
            feedback_note = st.text_area(
                "Feedback (optional, shown to him)",
                key=f"mc_approve_feedback_{entry['id']}",
                height=140,
                placeholder="e.g. Great detail about the hike -- loved reading this one.",
            )
            review_columns = st.columns([1, 1, 4])
            if review_columns[0].button(
                "✅ Approve", key=f"mc_approve_travel_{entry['id']}", type="primary"
            ):
                db.approve_travel_entry(entry["id"], feedback_note.strip())
                st.rerun()
            reviewing = st.session_state.get("mc_reviewing_travel") == entry["id"]
            if review_columns[1].button(
                "Cancel" if reviewing else "↩️ Send back",
                key=f"mc_bounce_travel_{entry['id']}",
            ):
                st.session_state["mc_reviewing_travel"] = None if reviewing else entry["id"]
                st.rerun()
            if reviewing:
                with st.form(f"mc_send_back_travel_{entry['id']}"):
                    note = st.text_input(
                        "What should he fix or add?",
                        placeholder="e.g. more detail on what you actually did there",
                    )
                    if st.form_submit_button("Send back", type="primary"):
                        db.send_travel_entry_back(entry["id"], note.strip())
                        st.session_state["mc_reviewing_travel"] = None
                        st.rerun()
        st.page_link("pages/9_Landons_Travels.py", label="Open in Landon's Travels", icon="🧭")

    with st.expander(header, expanded=open):
        _body()


# --- the parked-work and hours data every tab below reads ----------------------

today = date.today()
today_iso = today.isoformat()

all_lessons = db.list_lessons(student["id"], limit=50)
to_review = [l for l in all_lessons if l["status"] in ("planned", "submitted", "needs_revision")]
history = [l for l in all_lessons if l["status"] in ("completed", "skipped")]

all_travel_entries = db.list_travel_entries(student["id"])
travel_to_review = [
    t for t in all_travel_entries if t["status"] in ("submitted", "needs_revision")
]

lesson_backlog = [
    l for l in to_review
    if l["status"] == "planned" and weekly.is_backlogged(l, today_iso)
]
lesson_backlog.sort(key=lambda l: (l.get("metadata") or {}).get("planned_for") or "")

all_projects = db.list_big_projects(student["id"])
project_backlog = []
for project in all_projects:
    if project["shelved"] or project["kind"] == "travel_log":
        continue
    remaining = [s for s in db.list_project_steps(project["id"]) if not s["completed_on"]]
    if remaining:
        project_backlog.append((project, remaining))

all_topics = db.list_choice_topics(student["id"])
topic_backlog = [
    t for t in all_topics if not t["active"] and t["status"] not in ("done", "declined")
]

backlog_count = (
    len(lesson_backlog)
    + sum(len(steps) for _, steps in project_backlog)
    + len(topic_backlog)
)

# What's actually waiting on you: turned-in and sent-back work, plus anything
# genuinely overdue. A lesson simply scheduled for a future day isn't a review.
# Project steps a student has submitted count here too, so the badge reflects
# everything the review tab actually surfaces below.
submitted_step_count = len(db.submitted_project_steps(student["id"]))
needs_review_count = (
    sum(1 for l in to_review if _needs_attention(l, today_iso) or l["status"] == "needs_revision")
    + len(travel_to_review)
    + submitted_step_count
)


# The day grid's colored pills and its own horizontal-scroll fix now live in
# ui.render_board_days (shared with the student's Home board). The backlog
# panel below keeps its own row-scroll CSS, since it's parent-only and not
# part of that shared grid.

# `st.columns` splits its parent width into equal fractions with no floor --
# on a real laptop-width browser (not just the wide monitor a screenshot
# gets taken on), 5 even columns squeezes each card's expander label
# narrower than a single long word, forcing it to wrap letter-by-letter
# instead of at word breaks. Real Kanban boards (Trello, Jira) solve this
# by giving each column a fixed minimum width and letting the *row* scroll
# horizontally rather than letting columns keep shrinking -- this CSS does
# the same, scoped to any st.container(key=...) whose key starts with
# "board_days_row" (the day board) or "backlog_row_" (one per Backlog
# panel epic's own row of cards), both wrapped around a `st.columns` call
# below.
_BOARD_SCROLL_CSS = """
<style>
div[class*="st-key-board_days_row"] div[data-testid="stHorizontalBlock"],
div[class*="st-key-backlog_row_"] div[data-testid="stHorizontalBlock"] {
  overflow-x: auto !important;
  flex-wrap: nowrap !important;
  padding-bottom: 6px;
}
div[class*="st-key-board_days_row"] div[data-testid="stColumn"],
div[class*="st-key-backlog_row_"] div[data-testid="stColumn"] {
  min-width: 220px !important;
  flex: 0 0 220px !important;
}
</style>
"""

# The workflow views are a button row, matching the parent-admin hub buttons
# above rather than a separate tab strip -- reported: "the review, board, plan
# the week ... and record. all buttons just like the others." The Backlog is
# folded into the Board (its own parked-work section below the sprint board),
# and Grades joins the row so "base for all parent stuff" actually holds every
# parent surface. `mc_view` is the active one; each section below renders only
# when it's selected (the `if mc_view == ...` blocks that used to be `with
# <tab>:`), so the button row behaves exactly like the tabs did.
_MC_VIEWS = [
    ("review", f"✅ Review ({needs_review_count})"),
    ("board", f"📋 Board · Backlog ({backlog_count})"),
    ("plan", "📆 Plan next week"),
    ("record", "🗂️ Record"),
    ("grades", "📊 Grades"),
]
if "mc_view" not in st.session_state:
    st.session_state["mc_view"] = "review"
mc_view = st.session_state["mc_view"]
_view_cols = st.columns(len(_MC_VIEWS))
for _i, (_view_key, _view_label) in enumerate(_MC_VIEWS):
    if _view_cols[_i].button(
        _view_label,
        key=f"mc_viewbtn_{_view_key}",
        width="stretch",
        type="primary" if _view_key == mc_view else "secondary",
    ):
        st.session_state["mc_view"] = _view_key
        st.rerun()
st.divider()

# --- Board: every subject's stories, one week, one place ------------------------
#
# The actual point of the whole redesign this tab is part of: before this,
# rearranging a story meant navigating into whichever subject's own page it
# lived on, then several clicks deep into a nested expander, to reach the
# exact same shared move control this tab now surfaces directly on every
# card. This tab changes nothing about *how* a story moves -- only where a
# parent has to go to do it.

if mc_view == "board":
    # Seeded once, before the buttons below ever run -- a button writes
    # straight into this same session_state key and reruns, so the
    # date_input picks up the jump on the very next run instead of needing
    # a second click. Defaults to this week on a fresh session.
    if "board_week_picker" not in st.session_state:
        st.session_state["board_week_picker"] = date.today()

    # ◀/▶ step the viewed week by one at a time; This week / Next week jump
    # straight to those two. Planning several weeks out is already supported
    # (Plan next week takes any target week), so paging forward here is how a
    # parent reviews and rearranges those further-out weeks without typing a
    # date each time.
    jump_columns = st.columns([1, 1, 1, 1, 4])
    if jump_columns[0].button("◀ Prev", key="board_jump_prev"):
        current = st.session_state.get("board_week_picker", date.today())
        st.session_state["board_week_picker"] = weekly.week_start(current) - timedelta(days=7)
        st.rerun()
    if jump_columns[1].button("This week", key="board_jump_this_week"):
        st.session_state["board_week_picker"] = date.today()
        st.rerun()
    if jump_columns[2].button("Next week", key="board_jump_next_week"):
        # Same Monday "Plan next week" itself targets by default -- the
        # actual point of this button: right after a Friday planning
        # session generates next week's lessons, this is the one click
        # that shows them laid out on the same board, ready to move
        # around, instead of hand-picking next week's date here too.
        st.session_state["board_week_picker"] = weekly.default_plan_target()
        st.rerun()
    if jump_columns[3].button("Next ▶", key="board_jump_next"):
        current = st.session_state.get("board_week_picker", date.today())
        st.session_state["board_week_picker"] = weekly.week_start(current) + timedelta(days=7)
        st.rerun()

    board_week_start = weekly.week_start(
        st.date_input(
            "Week to view",
            key="board_week_picker",
            help="Any day in the week you want to see -- snapped to that week's Monday. "
            "The buttons above step a week at a time, or jump to this week or next.",
        )
    )
    board_days = weekly.week_dates(board_week_start, include_friday=True)
    st.caption(
        f"{board_days[0].strftime('%b %-d')} – {board_days[-1].strftime('%b %-d, %Y')}"
    )
    render_board_move_notice()

    board = weekly.board_for_week(db, student, board_week_start)
    today_iso_for_board = date.today().isoformat()

    # The sprint board itself, full width -- five columns is already a
    # tight squeeze on a laptop-width screen; splitting that same width
    # again with a side-by-side Backlog panel left every card title
    # wrapping character-by-character in practice, not just word-by-word.
    # The Product Backlog panel goes full-width below instead (see the
    # bottom of this block) so both get the room an expander's title
    # actually needs. Wrapped in a keyed container so _BOARD_SCROLL_CSS
    # can give this specific row of columns a real minimum width and let
    # it scroll horizontally, rather than keep shrinking on a narrower
    # window -- the same fix real Kanban boards use.
    st.markdown(_BOARD_SCROLL_CSS, unsafe_allow_html=True)
    render_board_days(
        db, student, board_week_start, board,
        key_prefix="board",
    )

    st.divider()

    # Product Backlog, full width below the board -- every story currently
    # parked, any week it originally came from, grouped by epic. The Backlog is
    # folded into the Board here (reported: "backlog can fold into the board"),
    # so this is the one place parked work lives; the move control on each card
    # is exactly what "assign" means. Shared with Landon's read-only Home board
    # via render_board_backlog.
    st.markdown("**📋 Product Backlog**")
    render_board_backlog(
        db, student, board,
        key_prefix="board", board_week_start=board_week_start,
        today_iso=today_iso_for_board,
    )

# --- Review: read his work, approve it or push it back --------------------------
#
# The parent's daily job, and the first thing this hub opens on. One
# prioritized queue: what he's turned in (open and ready to grade, his answer
# under each activity), then what's overdue, then what's already been sent
# back. No scheduling board here -- rearranging days is the Board tab's job --
# so this stays a read-and-decide surface, not a planner.

if mc_view == "review":
    this_week_start = weekly.week_start()
    this_week_friday = this_week_start + timedelta(days=4)
    report = build_report(
        db, student["id"], start=this_week_start.isoformat(), end=this_week_friday.isoformat()
    )
    pulse = st.columns(3)
    pulse[0].metric("Hours this week", f"{report.total_hours:g}")
    pulse[1].metric("Days of instruction", report.instructional_days)
    pulse[2].metric("Activities logged", report.activity_count)
    st.divider()

    # Reward alert: which rewards he's earned but not yet been handed --
    # reported: "i need to know as the parent when he hits one." Lives here in
    # Mission Control's review queue with the rest of what's waiting on a parent.
    render_earned_rewards(db, student)

    submitted_lessons = [l for l in to_review if l["status"] == "submitted"]
    submitted_lessons.sort(key=lambda l: (l.get("metadata") or {}).get("planned_for") or "")
    overdue = [
        l for l in to_review if l["status"] == "planned" and _needs_attention(l, today_iso)
    ]
    overdue.sort(key=lambda l: (l.get("metadata") or {}).get("planned_for") or "")
    # Planned but not yet due and not parked -- his week, still ahead of him.
    # Kept reachable (a Life Skills lesson logs its hours from here, and you
    # can preview or grade-ahead anything) but tucked below the work that's
    # actually waiting, not spread across a five-column day board the way the
    # old page did it.
    planned_ahead = [
        l for l in to_review
        if l["status"] == "planned"
        and not _needs_attention(l, today_iso)
        and not weekly.is_backlogged(l, today_iso)
    ]
    planned_ahead.sort(key=lambda l: (l.get("metadata") or {}).get("planned_for") or "")
    sent_back = [l for l in to_review if l["status"] == "needs_revision"]
    travel_waiting = [t for t in travel_to_review if t["status"] == "submitted"]
    travel_sent_back = [t for t in travel_to_review if t["status"] == "needs_revision"]

    submitted_steps = db.submitted_project_steps(student["id"])
    waiting_count = len(submitted_lessons) + len(travel_waiting) + len(submitted_steps)
    st.markdown(f"### ✅ Turned in — waiting on you ({waiting_count})")
    if not submitted_lessons and not travel_waiting and not submitted_steps:
        st.success("Nothing turned in to grade right now.")
    else:
        st.caption(
            "Each row collapses to a summary bar — hand-ins, quiz score, minutes — so "
            "you can scan the queue, then open the one you're ready to grade. Inside, "
            "the lesson is laid out the way he saw it, his answer under each activity."
        )
        # One thing waiting takes no click -- open it. A queue of several stays
        # collapsed to summary bars so it's scannable, the reported ask: "expand
        # and collapse to see just the bar level summary when closed and expand
        # when time to review."
        auto_open = waiting_count == 1
        for entry in travel_waiting:
            _render_travel_review_card(entry, open=auto_open)
        for lesson in submitted_lessons:
            _render_review_card(lesson, today_iso, open=auto_open)
        # Big Project steps he's submitted are reviewed on the Big Projects page
        # (where the project and its whole checklist live); surface the prompt
        # here so "needs review" isn't buried on another tab, then link out to
        # the actual Approve / Send-back controls.
        if submitted_steps:
            with st.container(border=True):
                st.markdown(f"**🏗️ {len(submitted_steps)} project step(s) turned in**")
                for step in submitted_steps:
                    project_title = step.get("project_title") or "Big Project"
                    st.markdown(f"- {md(step['title'])} — *{md(project_title)}*")
                st.page_link(
                    "pages/7_Big_Projects.py",
                    label="Review them in Big Projects",
                    icon="🏗️",
                )

    if overdue:
        st.divider()
        st.markdown(f"### ⚠️ Overdue — not turned in yet ({len(overdue)})")
        st.caption(
            "Past their day and still not handed in. Open one to nudge him, "
            "reschedule it, park it in the Backlog, or skip it."
        )
        for lesson in overdue:
            _render_review_card(lesson, today_iso)

    if sent_back or travel_sent_back:
        st.divider()
        st.markdown(
            f"### ↩️ Sent back — waiting on him ({len(sent_back) + len(travel_sent_back)})"
        )
        st.caption(
            "You've returned these. Nothing to do until he revises and turns them in again."
        )
        for entry in travel_sent_back:
            _render_travel_review_card(entry)
        for lesson in sent_back:
            _render_review_card(lesson, today_iso)

    if planned_ahead:
        st.divider()
        st.markdown(f"### 📅 Planned — not turned in yet ({len(planned_ahead)})")
        st.caption(
            "Scheduled and still ahead of him. Open one to preview it, log a Life "
            "Skills lesson's hours, or move it. Rearranging the week itself lives "
            "on the **📋 Board** tab."
        )
        for lesson in planned_ahead:
            _render_review_card(lesson, today_iso)

    if lesson_backlog:
        st.divider()
        st.info(
            f"🗄️ {len(lesson_backlog)} lesson(s) parked in the Backlog — see the "
            "**🗄️ Backlog** tab."
        )

# --- Plan next week --------------------------------------------------------------

if mc_view == "plan":
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
                    # No collision check on the target day: a day is allowed to
                    # hold two lessons of the same subject (a new one plus one
                    # from a prior day still waiting on his revision), so moving
                    # a subject into any day is never blocked.
                    render_story_move_control(
                        key=f"weekplan_lesson_{lesson['id']}",
                        active=not weekly.is_backlogged(lesson, date.today().isoformat()),
                        scheduled_for=lesson["metadata"].get("planned_for"),
                        set_active=lambda a, lid=lesson["id"]: (
                            db.unhold_lesson(lid) if a else db.send_to_backlog(lid)
                        ),
                        schedule=lambda d, lid=lesson["id"]: (
                            db.reschedule_lesson(lid, d) if d else None
                        ),
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
        friday_detail = form_columns[1].text_input(
            "Detail",
            placeholder="Required for Custom -- optional detail for the rest, "
            "e.g. \"catch up on 5 older trips\"",
        )
        if st.form_submit_button("Add") and (kind != "custom" or friday_detail.strip()):
            db.add_friday_plan_item(
                student["id"], friday_date.isoformat(), kind, friday_detail.strip()
            )
            st.rerun()

# --- Record: the hours ledger, and logging one by hand --------------------------

if mc_view == "record":
    st.markdown("### 🗂️ The instructional record")
    st.caption(
        "Every hour that counts. Activities created from agent lessons land here "
        "automatically; anything else can be logged by hand. Total minutes count "
        "toward the 1,000-hour floor."
    )

    with st.expander("➕ Log an activity by hand"):
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
            st.caption(
                "Leave a subject at 0 to skip it. The primary subject is filled in for you."
            )
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
                credit_summary = " · ".join(
                    f"{label(s)} {m}m" for s, m in activity["credits"].items()
                )
                columns[0].markdown(
                    f"<small>Credit: {credit_summary}</small>", unsafe_allow_html=True
                )
                if columns[1].button("Delete", key=f"del_act_{activity['id']}"):
                    db.delete_activity(activity["id"])
                    st.rerun()

    st.divider()
    show_history = st.checkbox("Also show completed and skipped lessons")
    if show_history:
        st.markdown(f"**Completed & skipped** ({len(history)})")
        if not history:
            st.caption("Nothing logged yet.")
        for lesson in history:
            _render_review_card(lesson, today_iso)


# --- Grades: the report card, editable, in the parent's own hub -----------------
#
# Reported: "how can the parent edit/review these grades ... i feel like this
# should also live in the mission control. thats base for all parent stuff." The
# full report card -- every subject's number, the per-item drill-down (worst
# first, with its traffic-light dots), and the hand-set override form inside each
# subject's breakdown -- renders here now, off the same gradebook the student
# sees, so there is still only one set of numbers.

if mc_view == "grades":
    st.markdown("### 📊 Report card")
    st.caption(
        "The same numbers he sees. Open a subject to read every graded item that "
        "made up its grade (worst first) and, at the bottom of each, set that "
        "subject's grade by hand if a number needs overriding."
    )
    render_report_card(db, student, for_parent=True)

    # The XP reward ladder he's climbing toward, editable here -- the student's
    # own XP card is view-only, so this is where a parent tunes what he unlocks.
    with st.expander("🎁 XP rewards he can unlock"):
        render_xp_reward_editor(db)
