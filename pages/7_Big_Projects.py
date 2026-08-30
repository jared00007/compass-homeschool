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
"""

from __future__ import annotations

from datetime import date

import streamlit as st

from compass import config
from compass.agents import LessonGenerationError, project_chunker
from compass.subjects import SUBJECT_KEYS, label
from compass.ui import api_status_banner, is_parent, md, page_setup

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


projects = db.list_big_projects(student["id"])
visible_projects = [p for p in projects if not p["shelved"]]

if not projects:
    st.info("No projects yet.")
    if st.button("Add this year's starter projects", type="primary"):
        count = db.seed_big_projects(student["id"])
        st.success(f"Added {count} project{'s' if count != 1 else ''}.")
        st.rerun()
elif len(visible_projects) > 1:
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
        steps = db.list_project_steps(project["id"])
        done = sum(1 for s in steps if s["completed_on"])
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
            if steps:
                st.progress(done / len(steps), text=f"{done} / {len(steps)} steps done")
                total_min = sum(s["min_days"] for s in steps)
                total_max = sum(s["max_days"] for s in steps)
                st.caption(
                    f"⏳ Roughly {_day_range(total_min, total_max)} total at a relaxed "
                    f"pace -- this is a filler for when there's time, not something to rush."
                )
            elif is_parent():
                # Only while it has zero steps -- see project_chunker's own
                # docstring on why this never offers to regenerate a project
                # that already has real progress on it.
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
            # picking one is a real decision, not a formality.
            if project["id"] == active_id:
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
            # The first not-done step is highlighted as "up next" -- steps
            # aren't hard-locked (either of you can check any of them off,
            # same parity as Life Skills), but the sprint-style point of this
            # feature is having one clear next thing rather than a flat list.
            next_step_id = next((s["id"] for s in steps if not s["completed_on"]), None)
            for index, step in enumerate(steps, start=1):
                is_next = step["id"] == next_step_id
                row_key = f"step_row_next_{step['id']}" if is_next else f"step_row_{step['id']}"
                with st.container(key=row_key):
                    columns = st.columns([1, 20])
                    with columns[0]:
                        checked = st.checkbox(
                            "Done",
                            value=bool(step["completed_on"]),
                            key=f"step_done_{step['id']}",
                            label_visibility="collapsed",
                        )
                        if checked != bool(step["completed_on"]):
                            db.set_project_step_done(step["id"], checked)
                            st.rerun()
                    with columns[1]:
                        badge = " · ▶ up next" if is_next and not checked else ""
                        pace = f" · ⏳ {_day_range(step['min_days'], step['max_days'])}"
                        # Always collapsed on a fresh launch -- the "up next"
                        # badge and the pace both show right in the label, so
                        # nothing important is hidden by keeping it closed
                        # until he actually taps it open.
                        with st.expander(
                            f"{index}. {md(step['title'])}{pace}{badge}", expanded=False
                        ):
                            if step["description"]:
                                st.write(md(step["description"]))
                            meta = []
                            if step["materials"]:
                                meta.append(f"**You'll need:** {md(step['materials'])}")
                            meta.append(f"Credits toward {label(step['credit_subject'])}")
                            st.caption(" · ".join(meta))
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
    if not projects:
        st.info("Add a project first -- there's nothing to log yet.")
    else:
        all_steps = [
            (project, step)
            for project in projects
            for step in db.list_project_steps(project["id"])
        ]
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
        if st.form_submit_button("Add project", type="primary") and title.strip():
            db.add_big_project(student["id"], title.strip(), vision.strip())
            st.rerun()

    st.divider()

    st.markdown("#### Add a step to an existing project")
    if not projects:
        st.caption("Add a project first.")
    else:
        with st.form("add_project_step", clear_on_submit=True):
            project = st.selectbox(
                "Project", projects, format_func=lambda p: p["title"], key="step_project"
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
            if st.form_submit_button("Add step", type="primary") and step_title.strip():
                db.add_project_step(
                    project["id"],
                    step_title.strip(),
                    description.strip(),
                    materials.strip(),
                    credit_subject,
                    int(min_days),
                    int(max_days),
                )
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
