"""Big Projects -- parent-curated, multi-step creative projects that build
toward one finished thing, run agile-sprint style: small ordered steps, each
one small enough to actually finish in a sitting, each with its own
materials list and its own subject credit. The starter catalog seeds a
handful of options at once (Lego stop-motion film, mini podcast, toy
photography) so there's a real menu to pick from and stick with, rather
than one thing pushed on him.

A step can be added by hand (same as Life Skills) or, for a brand-new
project with nothing on it yet, drafted all at once with AI (see
compass.agents.project_chunker) -- offered only while the project has zero
steps, so there's never a question of reconciling an AI draft against a
parent's own edits or his already-checked-off progress.

A project is also either 'linear' (the above -- one fixed, ordered sequence)
or 'choice' (see big_projects.mode): a branching tree instead, where
finishing a step reveals whichever steps branch off of it (project_steps.
parent_step_id) as the next set of paths to choose between, rather than
there being exactly one next step. See _step_chain/_step_choices/
_render_choice_steps below.
"""

from __future__ import annotations

from datetime import date

import streamlit as st

from compass import config
from compass import national_parks as parks
from compass.agents import LessonGenerationError, project_chunker
from compass.subjects import SUBJECT_KEYS, label
from compass.ui import api_status_banner, is_parent, md, page_setup, render_story_move_control

db, student = page_setup("Big Projects", icon="🎬")

st.title("🎬 Big Projects")
st.caption(
    "One big thing, broken into small steps. Check a step off when it's "
    "done -- the project bar fills up as you go, and every step earns real "
    "school credit."
)

def _day_range(min_days: int, max_days: int) -> str:
    """A pace, not a deadline -- there's deliberately no due date anywhere
    behind this, just a loose expectation of how long a step is worth
    taking."""
    if min_days == max_days:
        return f"{min_days} day" if min_days == 1 else f"{min_days} days"
    return f"{min_days}-{max_days} days"


def _step_chain(steps: list[dict]) -> list[dict]:
    """The path actually taken through a `mode='choice'` project's tree so
    far: starting from the roots (`parent_step_id is None`), follow whichever
    child at each level is completed, stopping the moment no completed child
    is found at that level. A sibling branch that was never picked just
    never enters the chain -- it isn't deleted or hidden, it's simply not
    part of the story so far."""
    by_parent: dict[int | None, list[dict]] = {}
    for step in steps:
        by_parent.setdefault(step["parent_step_id"], []).append(step)
    chain: list[dict] = []
    parent_id: int | None = None
    while True:
        done_child = next((s for s in by_parent.get(parent_id, []) if s["completed_on"]), None)
        if done_child is None:
            return chain
        chain.append(done_child)
        parent_id = done_child["id"]


def _step_choices(steps: list[dict], tip_id: int | None) -> list[dict]:
    """What's on offer next at the current tip of the chain (or at the roots,
    if nothing's been finished yet) -- unlocked, not already done. A locked
    (still-backlogged) sibling doesn't show up as a pick here; a parent
    unlocks it from the move control or Add / manage first, same as any
    other story."""
    return [
        s for s in steps
        if s["parent_step_id"] == tip_id and not s["completed_on"] and s["active"]
    ]


def _render_step_gate(step: dict) -> None:
    """The submit -> review -> approve loop for one not-yet-completed step,
    the same gate lessons and travel entries use, viewer-aware.

    Student: a "📬 Submit for review" button (with an optional note for a
    digital review; a step he did off-screen just submits with no note and gets
    the same manual review), the sent-back feedback when it's been bounced, and
    a plain "waiting on a parent" line once it's in. Parent: on a submitted step,
    his note (if any) plus Approve / Send-back; on a still-open step, the direct
    "mark done" and the shared move control, exactly as before."""
    sid = step["id"]
    status = step.get("status") or "planned"
    if is_parent():
        if status == "submitted":
            if step.get("submission"):
                st.markdown("**📤 He turned this in:**")
                st.write(md(step["submission"]))
            else:
                st.caption("📤 He marked this done (nothing typed) — check it with him.")
            approve_col, back_col = st.columns(2)
            if approve_col.button("✅ Approve", key=f"approve_step_{sid}", type="primary"):
                db.approve_project_step(sid)
                st.rerun()
            with back_col.popover("↩️ Send back"):
                note = st.text_area("What should he fix?", key=f"stepfb_{sid}")
                if st.button("Send it back", key=f"sendback_step_{sid}"):
                    db.send_project_step_back(sid, note.strip())
                    st.rerun()
        else:
            if status == "needs_revision":
                st.caption("↩️ Sent back — waiting on him to redo and turn it in again.")
            if st.button("✅ Mark done", key=f"parent_done_step_{sid}"):
                db.set_project_step_done(sid, True)
                st.rerun()
            render_story_move_control(
                key=f"step_{sid}",
                active=bool(step["active"]),
                scheduled_for=step["scheduled_for"],
                set_active=lambda a, s=sid: db.set_project_step_active(s, a),
                schedule=lambda d, s=sid: db.schedule_project_step(s, d),
                show_backlog_toggle=False,
            )
    else:
        if status == "submitted":
            st.caption("📤 Turned in — waiting on a parent to review.")
            return
        if status == "needs_revision" and step.get("feedback"):
            st.warning(f"↩️ Sent back: {md(step['feedback'])}")
        note = st.text_area(
            "Anything to tell your parent about it? (optional)",
            key=f"step_submission_{sid}",
        )
        if st.button("📬 Submit for review", key=f"submit_step_{sid}", type="primary"):
            db.submit_project_step(sid, note.strip())
            st.rerun()


def _step_status_icon(step: dict) -> str:
    """The at-a-glance marker in the step row's left column, replacing the old
    done/not-done checkbox now that a step moves through four states."""
    return {
        "planned": "⬜",
        "submitted": "📤",
        "needs_revision": "↩️",
        "completed": "✅",
    }.get(step.get("status") or ("completed" if step["completed_on"] else "planned"), "⬜")


def _render_choice_step(step: dict, index: int) -> None:
    """One offered-next step, same card shape the linear rendering below
    uses for its own rows -- the status icon and the shared submit -> review ->
    approve gate (_render_step_gate), same as a linear step."""
    row_key = f"step_row_next_{step['id']}"
    with st.container(key=row_key):
        columns = st.columns([1, 20])
        with columns[0]:
            st.markdown(f"### {_step_status_icon(step)}")
        with columns[1]:
            pace = f" · ⏳ {_day_range(step['min_days'], step['max_days'])}"
            with st.expander(f"{index}. {md(step['title'])}{pace} · ▶ choose this", expanded=False):
                if step["description"]:
                    st.write(md(step["description"]))
                meta = []
                if step["materials"]:
                    meta.append(f"**You'll need:** {md(step['materials'])}")
                meta.append(f"Credits toward {label(step['credit_subject'])}")
                st.caption(" · ".join(meta))
                if not step["completed_on"]:
                    st.divider()
                    _render_step_gate(step)


def _render_choice_steps(steps: list[dict]) -> None:
    """A `mode='choice'` project's Checklist body: the path taken so far as
    a plain, read-only list, then whatever's on offer next. Nothing here is
    hard-locked to one path -- like the linear rendering, either of you can
    check any offered step off; the branching is in what's *offered*, not in
    who's allowed to pick."""
    chain = _step_chain(steps)
    for i, step in enumerate(chain, start=1):
        st.caption(f"✅ {i}. {md(step['title'])} · earned {step['completed_on']}")

    tip_id = chain[-1]["id"] if chain else None
    choices = _step_choices(steps, tip_id)
    all_children = [s for s in steps if s["parent_step_id"] == tip_id]

    if choices:
        st.markdown("**Choose your next step:**")
        for i, step in enumerate(choices, start=len(chain) + 1):
            _render_choice_step(step, i)
    elif not steps:
        if is_parent():
            st.caption("No steps yet -- add a starting step or two in the Add / manage tab.")
    elif not all_children:
        st.success("🏁 End of this path!")
    elif is_parent():
        st.caption(
            "Nothing unlocked at this branch yet -- pull one in from "
            "Backlog below, or the Add / manage tab."
        )


def _render_travel_log_summary() -> None:
    """The Travel Log project's own card body: a trip-count summary and a
    link out to the real page (pages/9_Landons_Travels.py) -- see
    Database.ensure_travel_log_project. No project_steps rendering here on
    purpose; this project never has any. Nothing here duplicates that
    page's own review gate, map, or export -- this is a summary, not a
    second copy of the feature."""
    entries = db.list_travel_entries(student["id"])
    completed_entries = [e for e in entries if e["status"] == "completed"]
    completed = len(completed_entries)
    open_entries = [e for e in entries if e["status"] != "completed"]

    # Two quests, not just a trip tally: fill in the 50-state map, and collect
    # the 63 National Parks. Counted off *written-up* trips only -- an assigned
    # stub he hasn't done yet doesn't colour in a state. A state or park shows
    # up once no matter how many times he's been.
    states_logged = len({e["state"] for e in completed_entries if e["state"]})
    parks_logged = len({e["park_key"] for e in completed_entries if e["park_key"]})
    total_states = len(parks.STATES)
    total_parks = len(parks.PARKS)

    st.caption(
        f"🧭 {completed} trip{'s' if completed != 1 else ''} written up"
        + (f" · {len(open_entries)} still open" if open_entries else "")
    )
    st.progress(
        states_logged / total_states,
        text=f"🗺️ States logged — {states_logged} / {total_states}",
    )
    st.progress(
        parks_logged / total_parks,
        text=f"🏞️ National Parks visited — {parks_logged} / {total_parks}",
    )
    if states_logged == total_states:
        st.success("🎉 All 50 states logged — the whole map is filled in!")
    st.page_link("pages/9_Landons_Travels.py", label="Open Landon's Travels", icon="🧭")


projects = db.list_big_projects(student["id"])
visible_projects = [p for p in projects if not p["shelved"]]
# Excludes the automatic Travel Log row on purpose -- see
# Database.ensure_travel_log_project -- it's always present starting on the
# very first page view, but it isn't a real "you have a project" in the
# sense this banner and the starter-catalog button below care about.
has_steps_project = any(p["kind"] == "steps" for p in projects)

if not has_steps_project:
    st.info("No projects yet.")
    if st.button("Add this year's starter projects", type="primary"):
        count = db.seed_big_projects(student["id"])
        st.success(f"Added {count} project{'s' if count != 1 else ''}.")
        st.rerun()
elif sum(1 for p in visible_projects if p["kind"] == "steps") > 1:
    st.caption(
        "A few options on purpose -- pick **one** to actually work through this "
        "year with the button on its card below. That's also what Friday's "
        "quick-win nudge on Home points at."
    )

if is_parent():
    checklist_tab, log_tab, manage_tab = st.tabs(["Checklist", "Log time", "Add / manage"])
    api_ok = api_status_banner()
else:
    checklist_tab = st.container()
    log_tab = manage_tab = None
    api_ok = True

_STEP_CARD_CSS = """
<style>
div[class*="st-key-project_card_"] {
  border: 1px solid var(--c-border) !important;
  border-radius: var(--c-radius) !important;
  background: var(--c-panel) !important;
  box-shadow: var(--c-glow);
  padding: 16px !important;
  margin-bottom: 20px !important;
}
div[class*="st-key-step_row_"] {
  border-left: 3px solid var(--c-border) !important;
  border-radius: var(--c-radius) !important;
  padding: 10px 14px !important;
  margin-bottom: 8px !important;
}
div[class*="st-key-step_row_next_"] {
  border-left: 3px solid var(--c-alt) !important;
  background: var(--c-panel) !important;
}
</style>
"""

with checklist_tab:
    if not projects:
        st.caption("Add the starter project above to get going.")
    elif not visible_projects:
        st.caption(
            "Everything's shelved right now"
            + (" -- check the Add / manage tab to bring one back." if is_parent() else ".")
        )
    st.markdown(_STEP_CARD_CSS, unsafe_allow_html=True)
    active_project = db.active_big_project(student["id"])
    active_id = active_project["id"] if active_project else None
    for project in visible_projects:
        # The Travel Log folder never has project_steps rows -- see
        # Database.ensure_travel_log_project -- so none of the step-list
        # machinery below applies to it at all.
        is_travel_log = project["kind"] == "travel_log"
        # A branching project (see big_projects.mode/_render_choice_steps)
        # doesn't have one fixed next step -- what's "up next" depends on
        # which path was actually taken, so it gets its own rendering below
        # instead of forcing it through the fixed-order layout underneath.
        is_choice = project["mode"] == "choice"
        steps = [] if is_travel_log else db.list_project_steps(project["id"])
        # Visible to both of you: committed to the current plan, same as
        # Life Skills' own `active OR completed_on` gate -- a step already
        # done stays visible regardless of this flag, so backlogging never
        # retroactively hides something he's already finished.
        visible_steps = [s for s in steps if s["active"] or s["completed_on"]]
        backlog_steps = [s for s in steps if not s["active"] and not s["completed_on"]]
        done = sum(1 for s in visible_steps if s["completed_on"])
        # A real st.expander can't wrap this card -- each step below is
        # already its own expander, and Streamlit doesn't allow nesting
        # them. A toggle button driving a plain show/hide gets the same
        # collapsible behavior at the project level without that limit.
        # Collapsed on every fresh app launch, on purpose -- nothing on this
        # page should greet him already expanded.
        open_key = f"project_open_{project['id']}"
        if open_key not in st.session_state:
            st.session_state[open_key] = False
        with st.container(key=f"project_card_{project['id']}"):
            header = st.columns([20, 3])
            with header[0]:
                star = "🌟 " if project["id"] == active_id else ""
                st.markdown(f"### {star}{md(project['title'])}")
            with header[1]:
                if st.button(
                    "Hide" if st.session_state[open_key] else "Show",
                    key=f"toggle_project_{project['id']}",
                    width="stretch",
                ):
                    st.session_state[open_key] = not st.session_state[open_key]
                    st.rerun()
            if is_travel_log:
                _render_travel_log_summary()
            elif is_choice:
                # No single "N of M steps done" number -- a branch never
                # taken was never really part of the plan, so there's no
                # fixed total to divide by, only how far the path taken has
                # gotten so far.
                st.caption(
                    f"🌳 Choose-your-path project · {done} step"
                    f"{'s' if done != 1 else ''} completed so far"
                )
            elif visible_steps:
                st.progress(done / len(visible_steps), text=f"{done} / {len(visible_steps)} steps done")
                total_min = sum(s["min_days"] for s in visible_steps)
                total_max = sum(s["max_days"] for s in visible_steps)
                st.caption(
                    f"⏳ Roughly {_day_range(total_min, total_max)} total at a relaxed "
                    f"pace -- this is a filler for when there's time, not something to rush."
                )
            elif steps:
                # Has steps, but every one of them is still sitting in
                # Backlog -- a different state from "no steps at all", and
                # from "all done" too.
                st.caption(
                    "Nothing in To Do yet"
                    + (" -- pull a step up from Backlog below." if is_parent() else ".")
                )
            elif is_parent():
                # Only while it has zero steps -- see project_chunker's own
                # docstring on why this never offers to regenerate a project
                # that already has real progress on it. Also not offered on
                # a choice-mode project at all: the AI chunker only ever
                # drafts one fixed sequence, not a branching tree, so it has
                # nothing useful to do here -- a choice project's steps are
                # always hand-built, in Add / manage.
                st.caption("No steps yet.")
                if st.button(
                    "✨ Chunk this project into steps with AI",
                    key=f"chunk_project_{project['id']}",
                    disabled=not api_ok,
                ):
                    with st.spinner("Drafting a step-by-step plan…"):
                        try:
                            drafted = project_chunker.generate_project_steps(
                                db, student, project
                            )
                            for step in drafted:
                                db.add_project_step(
                                    project["id"],
                                    step["title"],
                                    step["description"],
                                    step["materials"],
                                    step["credit_subject"],
                                    step["min_days"],
                                    step["max_days"],
                                )
                            st.rerun()
                        except LessonGenerationError as exc:
                            st.error(str(exc))

            # Deliberately no default -- Friday's nudge on Home only ever
            # points at what's chosen here, never an arbitrary guess, so
            # picking one is a real decision, not a formality. The Travel Log
            # folder sits out of this pick entirely -- big_project_status_text
            # assumes an active project has steps with a next one due, which
            # is never true for a travel log; Travel Journal already runs on
            # its own assignment schedule regardless of what's "active" here.
            if is_travel_log:
                pass
            elif project["id"] == active_id:
                st.success("🌟 This is the one you're working on this year.")
            elif st.button(
                "🌟 Work on this one this year", key=f"activate_project_{project['id']}"
            ):
                db.set_active_big_project(project["id"])
                st.rerun()

            if not st.session_state[open_key]:
                continue

            if project["vision"]:
                st.caption(md(project["vision"]))
            if is_choice:
                _render_choice_steps(steps)
                if is_parent() and backlog_steps:
                    st.markdown("**🗄️ Backlog**")
                    st.caption(
                        "Unlocked branches aren't offered above yet -- move one "
                        "into play here when you're ready for it to show up as a "
                        "choice. Parent-only: he never sees a step sitting here."
                    )
                    steps_by_id = {s["id"]: s for s in steps}
                    for step in backlog_steps:
                        parent = steps_by_id.get(step["parent_step_id"])
                        branches_from = (
                            f' (branches from "{md(parent["title"])}")' if parent
                            else " (a starting option)"
                        )
                        pace = f" · ⏳ {_day_range(step['min_days'], step['max_days'])}"
                        with st.expander(
                            f"{md(step['title'])}{pace}{branches_from}", expanded=False
                        ):
                            if step["description"]:
                                st.write(md(step["description"]))
                            meta = []
                            if step["materials"]:
                                meta.append(f"**You'll need:** {md(step['materials'])}")
                            meta.append(f"Credits toward {label(step['credit_subject'])}")
                            st.caption(" · ".join(meta))
                            render_story_move_control(
                                key=f"step_{step['id']}",
                                active=bool(step["active"]),
                                scheduled_for=step["scheduled_for"],
                                set_active=lambda a, sid=step["id"]: db.set_project_step_active(sid, a),
                                schedule=lambda s, sid=step["id"]: db.schedule_project_step(sid, s),
                            )
            else:
                # The first not-done step is highlighted as "up next" -- steps
                # aren't hard-locked (either of you can check any of them off,
                # same parity as Life Skills), but the sprint-style point of this
                # feature is having one clear next thing rather than a flat list.
                # Only ever picked from visible_steps -- a backlogged step isn't
                # committed to the plan yet, so it can't be "up next" no matter
                # where it sits in sort_order.
                next_step_id = next((s["id"] for s in visible_steps if not s["completed_on"]), None)
                for index, step in enumerate(visible_steps, start=1):
                    is_next = step["id"] == next_step_id
                    row_key = f"step_row_next_{step['id']}" if is_next else f"step_row_{step['id']}"
                    done = bool(step["completed_on"])
                    with st.container(key=row_key):
                        columns = st.columns([1, 20])
                        with columns[0]:
                            # The left column now shows the step's gate state at
                            # a glance instead of a bare checkbox -- submitting,
                            # reviewing, and approving all happen inside the
                            # expander via _render_step_gate.
                            st.markdown(f"### {_step_status_icon(step)}")
                        with columns[1]:
                            status = step.get("status") or "planned"
                            badge = " · ▶ up next" if is_next and not done else ""
                            if status == "submitted":
                                badge = " · 📤 waiting on you" if is_parent() else " · 📤 turned in"
                            elif status == "needs_revision":
                                badge = " · ↩️ sent back"
                            pace = f" · ⏳ {_day_range(step['min_days'], step['max_days'])}"
                            # Auto-open a step that needs someone's action (his to
                            # submit/redo, or yours to review) so the gate isn't
                            # hidden behind a tap; a done or backlog-quiet step
                            # stays collapsed.
                            needs_action = (
                                (status == "submitted" and is_parent())
                                or (status in ("planned", "needs_revision") and not is_parent() and is_next)
                            )
                            with st.expander(
                                f"{index}. {md(step['title'])}{pace}{badge}",
                                expanded=needs_action,
                            ):
                                if step["description"]:
                                    st.write(md(step["description"]))
                                meta = []
                                if step["materials"]:
                                    meta.append(f"**You'll need:** {md(step['materials'])}")
                                meta.append(f"Credits toward {label(step['credit_subject'])}")
                                st.caption(" · ".join(meta))
                                if not done:
                                    st.divider()
                                    _render_step_gate(step)

                if is_parent() and backlog_steps:
                    st.markdown("**🗄️ Backlog**")
                    st.caption(
                        "Not part of the current plan yet -- move one into To Do above "
                        "when you're ready for him to work on it. Parent-only: he never "
                        "sees a step sitting here."
                    )
                    for step in backlog_steps:
                        pace = f" · ⏳ {_day_range(step['min_days'], step['max_days'])}"
                        with st.expander(f"{md(step['title'])}{pace}", expanded=False):
                            if step["description"]:
                                st.write(md(step["description"]))
                            meta = []
                            if step["materials"]:
                                meta.append(f"**You'll need:** {md(step['materials'])}")
                            meta.append(f"Credits toward {label(step['credit_subject'])}")
                            st.caption(" · ".join(meta))
                            render_story_move_control(
                                key=f"step_{step['id']}",
                                active=bool(step["active"]),
                                scheduled_for=step["scheduled_for"],
                                set_active=lambda a, sid=step["id"]: db.set_project_step_active(sid, a),
                                schedule=lambda s, sid=step["id"]: db.schedule_project_step(sid, s),
                            )

            if is_parent() and st.button(
                "Not an interest -- shelve it", key=f"shelve_project_{project['id']}"
            ):
                db.set_big_project_shelved(project["id"], True)
                st.rerun()

if log_tab is not None:
  with log_tab:
    st.subheader("Log time on a project step")
    st.caption(
        "Every step credits a real subject -- writing, art, or occupational "
        "education -- so project time genuinely counts toward the compliance "
        "dashboard, not just the checklist."
    )
    all_steps = [
        (project, step)
        for project in projects
        for step in db.list_project_steps(project["id"])
    ]
    if not all_steps:
        # Not just "no projects" -- a fresh student always has at least the
        # Travel Log folder now (see Database.ensure_travel_log_project),
        # which never has steps of its own at all.
        st.info("Add a project and a step first -- there's nothing to log yet.")
    else:
        with st.form("log_project_step"):
            project_step = st.selectbox(
                "Step",
                all_steps,
                format_func=lambda ps: f"{ps[0]['title']} — {ps[1]['title']}",
            )
            columns = st.columns(3)
            occurred_on = columns[0].date_input("Date", value=date.today())
            minutes = columns[1].number_input(
                "Minutes", min_value=5, max_value=600, value=45, step=15
            )
            _, step = project_step
            credit_subject = columns[2].selectbox(
                "Credits toward",
                SUBJECT_KEYS,
                index=SUBJECT_KEYS.index(step["credit_subject"])
                if step["credit_subject"] in SUBJECT_KEYS
                else SUBJECT_KEYS.index("occupational_education"),
                format_func=label,
            )
            note = st.text_input("What did he do?")
            mark_done = st.checkbox("Mark this step done", value=False)
            if st.form_submit_button("Log hours", type="primary"):
                project, step = project_step
                db.log_activity(
                    student_id=student["id"],
                    title=f"{project['title']} — {step['title']}",
                    tier=config.TIER_PROJECTS,
                    primary_subject=credit_subject,
                    minutes=int(minutes),
                    subject_credits={credit_subject: int(minutes)},
                    occurred_on=occurred_on.isoformat(),
                    description=note,
                    source="big_projects",
                )
                if mark_done:
                    db.set_project_step_done(step["id"], True)
                # No rerun here on purpose -- the form submit already causes
                # one, and an extra manual one right after st.success() wipes
                # the confirmation before it ever renders (the same bug the
                # Check-In save button had).
                st.success("Logged.")

if manage_tab is not None:
  with manage_tab:
    st.markdown("#### Add a project")
    with st.form("add_big_project", clear_on_submit=True):
        title = st.text_input("Project title")
        vision = st.text_area(
            "The vision -- what does the finished thing look like?", height=80
        )
        mode = st.radio(
            "How should this one flow?",
            ["linear", "choice"],
            format_func=lambda m: (
                "Fixed order -- step 1, then 2, then 3..." if m == "linear"
                else "Choose your path -- finish a step, then pick what's next"
            ),
            horizontal=True,
        )
        if st.form_submit_button("Add project", type="primary") and title.strip():
            db.add_big_project(student["id"], title.strip(), vision.strip(), mode=mode)
            st.rerun()

    st.divider()

    st.markdown("#### Add a step to an existing project")
    steppable_projects = [p for p in projects if p["kind"] != "travel_log"]
    if not steppable_projects:
        st.caption("Add a project first.")
    else:
        with st.form("add_project_step", clear_on_submit=True):
            project = st.selectbox(
                "Project", steppable_projects, format_func=lambda p: p["title"], key="step_project"
            )
            step_title = st.text_input("Step title")
            description = st.text_area("What happens in this step?", height=80)
            materials = st.text_input(
                "What you'll need (optional)", placeholder="e.g. cardboard, tape, a phone"
            )
            columns = st.columns(2)
            credit_subject = columns[0].selectbox(
                "Credits toward",
                SUBJECT_KEYS,
                index=SUBJECT_KEYS.index("occupational_education"),
                format_func=label,
                key="step_credit",
            )
            with columns[1]:
                pace_cols = st.columns(2)
                min_days = pace_cols[0].number_input(
                    "Pace: at least (days)", min_value=1, max_value=60, value=1, key="step_min_days"
                )
                max_days = pace_cols[1].number_input(
                    "up to (days)", min_value=1, max_value=60, value=1, key="step_max_days"
                )
            # `project` only reflects the browser's current pick once this
            # form is actually submitted (same limitation the Log time tab's
            # `credit_subject` default already lives with) -- good enough to
            # scope this list, since it's just deciding what shows up in the
            # dropdown below, not something written to the database.
            parent_step_id = None
            if project["mode"] == "choice":
                existing_steps = db.list_project_steps(project["id"])
                parent_options: list[int | None] = [None] + [s["id"] for s in existing_steps]
                titles_by_id = {s["id"]: s["title"] for s in existing_steps}
                parent_step_id = st.selectbox(
                    "Branches off of",
                    parent_options,
                    format_func=lambda sid: (
                        "Start of the project" if sid is None else titles_by_id[sid]
                    ),
                    key="step_parent",
                )
            if st.form_submit_button("Add step", type="primary") and step_title.strip():
                db.add_project_step(
                    project["id"],
                    step_title.strip(),
                    description.strip(),
                    materials.strip(),
                    credit_subject,
                    int(min_days),
                    int(max_days),
                    parent_step_id=parent_step_id,
                )
                st.rerun()

    st.divider()

    st.markdown("#### Reorder steps")
    st.caption(
        "The move control (Backlog / a specific day) never touches step "
        "*order* -- this is the only place to change which step comes "
        "next in a linear project's fixed sequence."
    )
    if not steppable_projects:
        st.caption("Add a project first.")
    else:
        reorder_project = st.selectbox(
            "Project", steppable_projects, format_func=lambda p: p["title"], key="reorder_project"
        )
        reorder_steps = db.list_project_steps(reorder_project["id"])
        if not reorder_steps:
            st.caption("No steps yet.")
        else:
            for i, step in enumerate(reorder_steps):
                cols = st.columns([6, 1, 1])
                cols[0].markdown(f"{i + 1}. {md(step['title'])}")
                if cols[1].button("↑", key=f"step_up_{step['id']}", disabled=i == 0):
                    db.move_project_step(step["id"], "up")
                    st.rerun()
                if cols[2].button(
                    "↓", key=f"step_down_{step['id']}", disabled=i == len(reorder_steps) - 1
                ):
                    db.move_project_step(step["id"], "down")
                    st.rerun()

    st.divider()

    st.markdown("#### Remove a step")
    removable = [
        (project, step)
        for project in projects
        for step in db.list_project_steps(project["id"])
    ]
    if not removable:
        st.caption("No steps yet.")
    else:
        target = st.selectbox(
            "Step to remove",
            removable,
            format_func=lambda ps: f"{ps[0]['title']} — {ps[1]['title']}",
            key="remove_step_pick",
        )
        if st.button("Remove step"):
            db.delete_project_step(target[1]["id"])
            st.rerun()

    st.divider()

    st.markdown("#### Shelved projects")
    st.caption(
        "Marked \"not an interest\" from the Checklist tab -- shelving is "
        "reversible, and a shelved project's steps and history stay put."
    )
    shelved_projects = [p for p in projects if p["shelved"]]
    if not shelved_projects:
        st.caption("Nothing shelved right now.")
    else:
        for project in shelved_projects:
            columns = st.columns([5, 1])
            columns[0].markdown(f"**{md(project['title'])}**")
            if columns[1].button("Bring back", key=f"unshelve_project_{project['id']}"):
                db.set_big_project_shelved(project["id"], False)
                st.rerun()
