"""Landon's Travels -- a family travel journal, now behind the same kind of
review gate a lesson goes through: writing an entry submits it, a parent
approves it (which also logs its flat Writing + Social Studies credit
automatically, no separate "Log hours" click needed for the ordinary case)
or sends it back with a note to revise. A parent can also assign a trip to
be written up on a specific day ahead of time -- a stub entry (trip
details, no story yet) that shows up on Home and the Week grid until he
writes it. Either way, a parent can still log real extra minutes against
any entry when it was genuine researched work, well beyond the flat
default, or seed it as an open History topic
(compass.storage.db.add_web_node) to be picked up by a real generated
lesson later -- never automatic. Real state borders and National Park
pins -- see compass/national_parks.py's own docstring for where that data
comes from.
"""

from __future__ import annotations

import html
from datetime import date, timedelta
from functools import partial

import streamlit as st

from compass import config
from compass import national_parks as parks
from compass import theme as theming
from compass.export import travel_journal_filename, travel_journal_to_docx
from compass.ui import (
    is_parent,
    md,
    page_setup,
    render_story_move_control,
    render_travel_feedback_reply_form,
)

db, student = page_setup("Landon's Travels", icon="🧭")

# Single-quoted -- theme.THEME's font stacks embed their own double-quoted
# font names (e.g. "Segoe UI", "SF Mono"), which would otherwise prematurely
# close a double-quoted HTML style="..." attribute the moment they're
# interpolated in, silently truncating every CSS declaration after it.
_MONO_FONT = theming.THEME.mono_font.replace('"', "'")

st.title("🧭 Landon's Travels")
st.caption(
    "Every state has a story -- National Parks are part of it, not the "
    "whole map. Writing an entry submits it for review, same as a lesson -- "
    "approving it logs its Writing/Social Studies credit automatically."
)

entries = db.list_travel_entries(student["id"])
if not is_parent():
    # A backlogged entry is a parent's own "not yet" call -- hide it from
    # him same as every other story type's own Backlog, not just from the
    # due-count on Home. Never hides a completed one: `active` only ever
    # changes through the move control, which itself never offers a
    # completed entry (see `_render_entry`), so there's no live path for a
    # family's finished trips to ever go missing here.
    entries = [e for e in entries if e["active"] or e["status"] == "completed"]

# An "open pick" -- assigned via "assign him to pick" below -- has no state
# or title yet because he hasn't chosen the trip. That blank pair is the
# reliable signal for one: a parent-assigned *specific* trip always has a
# title (the add form requires it), so this can't collide with that case.
# Grouped separately below instead of by state/year, which would otherwise
# show a blank-named group.
open_pick_entries = [
    e for e in entries
    if not e["title"] and not e["state"] and e["status"] in ("planned", "needs_revision")
]
open_pick_ids = {e["id"] for e in open_pick_entries}
graded_entries = [e for e in entries if e["id"] not in open_pick_ids]

visited_states = {e["state"] for e in graded_entries}
visited_park_keys = {e["park_key"] for e in graded_entries if e["park_key"]}
newest_park_key = next((e["park_key"] for e in graded_entries if e["park_key"]), None)

entries_by_state: dict[str, list[dict]] = {}
for e in graded_entries:
    entries_by_state.setdefault(e["state"], []).append(e)


def _school_year_group(visited_on: str) -> tuple[int, str]:
    """(sort key, label) for the school year containing this date -- e.g.
    (2025, "2025-26"). A real year is worth grouping by once this journal
    has stacked up several of them, the same way state already groups a
    single year's worth of trips."""
    start, _ = db.school_year_bounds(on=date.fromisoformat(visited_on))
    start_year = int(start[:4])
    return start_year, f"{start_year}-{str(start_year + 1)[-2:]}"


entries_by_year: dict[str, list[dict]] = {}
year_sort_keys: dict[str, int] = {}
for e in graded_entries:
    sort_key, label = _school_year_group(e["visited_on"])
    entries_by_year.setdefault(label, []).append(e)
    year_sort_keys[label] = sort_key


# Same three non-'completed' states a lesson can sit in, same semantic
# colors the rest of the app already uses for them (var(--c-dim)/
# var(--c-alt)/var(--c-bad) -- never the accent, which means "yours to act
# on" everywhere else, not "here's a status"). 'completed' and any
# pre-existing entry from before this column existed get no badge at all.
TRAVEL_ENTRY_STATUS_BADGES: dict[str, tuple[str, str]] = {
    "planned": ("📝 Not written yet", "var(--c-dim)"),
    "submitted": ("📤 Waiting on a parent", "var(--c-alt)"),
    "needs_revision": ("↩️ Sent back", "var(--c-bad)"),
}


def _render_entry(entry: dict) -> None:
    """One trip's card, plus its actions -- shared between the by-state and
    by-year groupings so neither duplicates this whole block. Three tiers:
    writing/revising a not-yet-submitted entry is open to anyone (same as
    the original add-entry form always was); approving or sending one back
    is parent-only, gated on `status == "submitted"`; edit/log
    hours/remove/suggest-lesson stay parent-only same as always."""
    park = parks.park_by_key(entry["park_key"]) if entry["park_key"] else None
    park_tag = (
        f'<div style="font-size:11px; color:var(--c-border); text-transform:uppercase; '
        f'letter-spacing:.03em; margin:4px 0 8px; font-weight:700;">📍 {html.escape(park.name)}</div>'
        if park
        else ""
    )
    # Only entries a parent actually put through the gate (assigned a day,
    # or written up since this feature shipped) ever show a badge --
    # 'completed' covers both an approved entry and every pre-existing one
    # from before this column existed, and neither needs a status called
    # out. See TRAVEL_ENTRY_STATUS_BADGES below.
    badge_label, badge_color = TRAVEL_ENTRY_STATUS_BADGES.get(entry["status"], (None, None))
    badge_tag = ""
    if badge_label:
        badge_text = badge_label
        if entry["scheduled_for"] and entry["status"] in ("planned", "needs_revision"):
            badge_text += f" · assigned {entry['scheduled_for']}"
        badge_tag = (
            f'<div style="font-size:11px; color:{badge_color}; font-weight:700; margin:2px 0 6px;">'
            f"{badge_text}</div>"
        )
        if entry["status"] == "needs_revision" and entry["revision_note"].strip():
            badge_tag += (
                f'<div style="font-size:12.5px; color:var(--c-text); background:var(--c-panel); '
                f'border-left:3px solid {badge_color}; padding:4px 8px; margin-bottom:6px;">'
                f'{html.escape(entry["revision_note"].strip())}</div>'
            )
    story_text = entry["story"].strip()
    story_html = (
        html.escape(story_text).replace("\n", "<br>")
        if story_text
        else '<span style="color:var(--c-dim);">No story written yet.</span>'
    )
    extra_lines = []
    if entry["favorite_moment"].strip():
        extra_lines.append(
            f'<div><b>Favorite moment:</b> {html.escape(entry["favorite_moment"].strip())}</div>'
        )
    if entry["would_return"].strip():
        extra_lines.append(
            f'<div><b>Would go back?</b> {html.escape(entry["would_return"].strip())}</div>'
        )
    extra_html = (
        f'<div style="font-size:13px; color:var(--c-text); margin-top:8px;">{"".join(extra_lines)}</div>'
        if extra_lines
        else ""
    )
    st.markdown(
        f"""
        <div style="background:var(--c-panel); border:1px solid var(--c-border);
             border-radius:var(--c-radius); padding:16px 18px; box-shadow:var(--c-glow);
             margin-bottom:12px;">
          <div style="display:flex; justify-content:space-between; align-items:baseline; gap:10px;">
            <div style="font-weight:800; font-size:16px;">
              {html.escape(entry["title"]) or "Untitled trip"}
            </div>
            <div style="font-size:12px; color:var(--c-dim); font-family:{_MONO_FONT};
                 white-space:nowrap;">{entry["visited_on"]}</div>
          </div>
          {park_tag}
          {badge_tag}
          <div style="font-size:13.5px; line-height:1.6; color:var(--c-text);
               margin-top:{"4px" if (park_tag or badge_tag) else "10px"};">
            {story_html}
          </div>
          {extra_html}
        </div>
        """,
        unsafe_allow_html=True,
    )

    # A real st.markdown call, not folded into the raw-HTML card above --
    # feedback is often a whole paragraph or two with its own formatting
    # (bold, bullets, a line per point), and that only renders properly
    # through Streamlit's actual markdown engine, not the html.escape'd
    # plain text the story/revision_note get.
    if entry["status"] == "completed" and entry["parent_feedback"].strip():
        with st.container(border=True):
            st.markdown("💬 **Feedback from your parent**")
            st.markdown(md(entry["parent_feedback"]))
            if entry["feedback_read_at"]:
                st.caption(f"✅ Read {entry['feedback_read_at'][:10]} — he said:")
                st.markdown(f"> {md(entry['feedback_reply'])}")
            else:
                st.caption("📬 Not read yet")
                render_travel_feedback_reply_form(db, entry, key_prefix="travels")

    # Writing it up (a parent-assigned stub) or revising it (sent back) is
    # every family member's to do, not just a parent's -- shown before the
    # parent-only action row below, and open to anyone regardless of
    # is_parent(), the same way the original "Add a travel entry" form
    # always was.
    if entry["status"] in ("planned", "needs_revision"):
        # The parent's checklist for this entry, if they set one -- shown as a
        # plain bulleted list so he knows exactly what to hit before he starts,
        # and it stays visible while he writes (the whole block re-renders).
        requirement_lines = [
            line.strip() for line in (entry.get("requirements") or "").splitlines()
            if line.strip()
        ]
        if requirement_lines:
            with st.container(border=True):
                st.markdown("**📝 What to include in this entry**")
                for line in requirement_lines:
                    st.markdown(f"- {html.escape(line)}")

        composing = st.session_state.get("composing_travel_entry") == entry["id"]
        verb = "Write it up" if entry["status"] == "planned" else "Revise & resubmit"
        if st.button(f"✍️ {verb}" if not composing else "Cancel", key=f"compose_entry_{entry['id']}"):
            st.session_state["composing_travel_entry"] = None if composing else entry["id"]
            st.rerun()
        if composing:
            # An open pick (see the assign-him-to-pick UI) has no state or
            # title yet -- he picks the trip himself here, on top of writing
            # it up. A parent-assigned specific trip already has both, so
            # this form stays exactly what it always was for that case.
            is_open_pick = not entry["title"] and not entry["state"]
            with st.form(f"compose_travel_entry_{entry['id']}"):
                if is_open_pick:
                    st.caption("You're picking this trip -- fill in where and when, then write it up.")
                    pick_columns = st.columns([2, 1])
                    new_state = pick_columns[0].selectbox("State", parks.STATES)
                    new_visited_on = pick_columns[1].date_input("Date", value=date.today())
                    new_title = st.text_input(
                        "Title", placeholder="e.g. Glaciers Before They're Gone"
                    )
                    new_park = st.selectbox(
                        "National Park (optional)",
                        [None, *parks.PARKS],
                        format_func=lambda p: (
                            "No park this trip" if p is None else f"{p.name} ({p.states})"
                        ),
                    )
                new_story = st.text_area(
                    "The story",
                    value=entry["story"],
                    height=140,
                    help="Take your time here. Details, details, details. Who was there, "
                    f"what you did, what you remember -- at least "
                    f"{config.TRAVEL_JOURNAL_MIN_STORY_WORDS} words.",
                )
                compose_columns = st.columns(2)
                new_favorite = compose_columns[0].text_input(
                    "Favorite moment (optional)", value=entry["favorite_moment"]
                )
                new_return = compose_columns[1].text_input(
                    "Would you go back? (optional)", value=entry["would_return"]
                )
                if st.form_submit_button("Submit for review", type="primary"):
                    update_fields = dict(
                        story=new_story.strip(),
                        favorite_moment=new_favorite.strip(),
                        would_return=new_return.strip(),
                    )
                    if is_open_pick:
                        update_fields.update(
                            state=new_state,
                            title=new_title.strip(),
                            visited_on=new_visited_on.isoformat(),
                            park_key=new_park.key if new_park else None,
                        )
                    word_count = len(new_story.split())
                    missing = []
                    if word_count < config.TRAVEL_JOURNAL_MIN_STORY_WORDS:
                        missing.append(
                            f"needs at least {config.TRAVEL_JOURNAL_MIN_STORY_WORDS} words "
                            f"of real detail ({word_count} so far)"
                        )
                    if is_open_pick and not new_title.strip():
                        missing.append("needs a title")
                    db.update_travel_entry(entry["id"], **update_fields)
                    if not missing:
                        db.submit_travel_entry(entry["id"])
                        st.session_state["composing_travel_entry"] = None
                        st.rerun()
                    else:
                        st.warning("Saved your progress, but not ready to submit yet -- " + "; ".join(missing) + ".")

    if is_parent() and entry["status"] == "submitted":
        reviewing = st.session_state.get("reviewing_travel_entry") == entry["id"]
        # Outside a form, same reasoning as park_choice/assign_day above --
        # this needs to be readable the moment Approve is clicked, not just
        # on some later form submit. Optional and shown to him alongside
        # the approved entry -- not a fix request like revision_note, so it
        # doesn't gate approval the way a missing revision note would.
        feedback_note = st.text_area(
            "Feedback (optional, shown to him)",
            key=f"approve_feedback_{entry['id']}",
            height=200,
            placeholder="e.g. Great detail about the hike -- loved reading this one.",
        )
        review_columns = st.columns([1, 1, 4])
        if review_columns[0].button("✅ Approve", key=f"approve_entry_{entry['id']}", type="primary"):
            db.approve_travel_entry(entry["id"], feedback_note.strip())
            st.rerun()
        if review_columns[1].button(
            "Cancel" if reviewing else "↩️ Send back", key=f"reviewbounce_entry_{entry['id']}"
        ):
            st.session_state["reviewing_travel_entry"] = None if reviewing else entry["id"]
            st.rerun()
        if reviewing:
            with st.form(f"send_back_travel_entry_{entry['id']}"):
                note = st.text_input(
                    "What should he fix or add?",
                    placeholder="e.g. more detail on what you actually did there",
                )
                if st.form_submit_button("Send back", type="primary"):
                    db.send_travel_entry_back(entry["id"], note.strip())
                    st.session_state["reviewing_travel_entry"] = None
                    st.rerun()

    if is_parent():
        editing = st.session_state.get("editing_travel_entry") == entry["id"]
        logging_hours = st.session_state.get("logging_travel_entry") == entry["id"]
        # Not offered on a completed entry -- same as Choice Topics/Big
        # Project steps, there's nothing left for a move to do to a trip
        # that's already been written up and approved.
        movable = entry["status"] != "completed"
        button_columns = st.columns([1, 1, 1, 1, 1, 3] if movable else [1, 1, 1, 1, 4])
        if button_columns[0].button(
            "Cancel" if editing else "Edit", key=f"edit_entry_{entry['id']}"
        ):
            st.session_state["editing_travel_entry"] = None if editing else entry["id"]
            st.rerun()
        if button_columns[1].button(
            "Cancel" if logging_hours else "Log hours", key=f"log_entry_{entry['id']}"
        ):
            st.session_state["logging_travel_entry"] = None if logging_hours else entry["id"]
            st.rerun()
        if button_columns[2].button("Remove", key=f"remove_entry_{entry['id']}"):
            db.delete_travel_entry(entry["id"])
            st.rerun()
        if movable:
            with button_columns[4]:
                render_story_move_control(
                    key=f"travel_{entry['id']}",
                    active=bool(entry["active"]),
                    scheduled_for=entry["scheduled_for"],
                    set_active=lambda a, eid=entry["id"]: db.set_travel_entry_active(eid, a),
                    schedule=lambda s, eid=entry["id"]: db.schedule_travel_entry(eid, s),
                    show_backlog_toggle=False,
                )
        if button_columns[3].button("Suggest lesson", key=f"suggest_entry_{entry['id']}"):
            rationale = (
                f"A real family trip: {story_text[:400]}"
                if story_text
                else f"A real family trip to {entry['state']}"
                + (f", including {park.name}" if park else "") + "."
            )
            db.add_web_node(
                student["id"],
                "history",
                topic=entry["title"] or f"Our trip to {entry['state']}",
                rationale=rationale,
                location=entry["state"],
            )
            st.success(
                "Added to History's open topics -- pick it up next time a "
                "history lesson gets generated."
            )

        if logging_hours:
            with st.form(f"log_travel_entry_{entry['id']}"):
                st.caption(
                    "Splits like the manual Activity Log entry does -- leave a "
                    "subject at 0 to skip it."
                )
                log_columns = st.columns(3)
                writing_minutes = log_columns[0].number_input(
                    "Writing minutes", min_value=0, max_value=300, value=30, step=5
                )
                social_studies_minutes = log_columns[1].number_input(
                    "Social Studies minutes", min_value=0, max_value=300, value=0, step=5
                )
                log_date = log_columns[2].date_input(
                    "Date", value=date.fromisoformat(entry["visited_on"])
                )
                if st.form_submit_button("Log hours", type="primary"):
                    credits = {
                        k: v
                        for k, v in {
                            "writing": int(writing_minutes),
                            "social_studies": int(social_studies_minutes),
                        }.items()
                        if v > 0
                    }
                    if credits:
                        db.log_activity(
                            student_id=student["id"],
                            title=entry["title"] or f"Travel writing -- {entry['state']}",
                            tier=config.TIER_CHOICE,
                            primary_subject=next(iter(credits)),
                            minutes=sum(credits.values()),
                            subject_credits=credits,
                            occurred_on=log_date.isoformat(),
                            description=entry["story"],
                            source="travel_journal",
                        )
                        st.session_state["logging_travel_entry"] = None
                        st.success("Logged.")
                        st.rerun()

        if editing:
            park_options = [None, *parks.PARKS]
            park_index = park_options.index(park) if park else 0
            state_index = (
                parks.STATES.index(entry["state"]) if entry["state"] in parks.STATES else 0
            )
            with st.form(f"edit_travel_entry_{entry['id']}"):
                edit_columns = st.columns([2, 1])
                edit_state = edit_columns[0].selectbox(
                    "State", parks.STATES, index=state_index
                )
                edit_date = edit_columns[1].date_input(
                    "Date", value=date.fromisoformat(entry["visited_on"])
                )
                edit_park = st.selectbox(
                    "National Park (optional)",
                    park_options,
                    index=park_index,
                    format_func=lambda p: (
                        "No park this trip" if p is None else f"{p.name} ({p.states})"
                    ),
                )
                edit_title = st.text_input("Title", value=entry["title"])
                edit_story = st.text_area(
                    "The story",
                    value=entry["story"],
                    height=140,
                    help=(
                        "Who was there? What was it like? What was your favorite "
                        "part? Real detail, not just a one-line recap."
                    ),
                )
                edit_extra_columns = st.columns(2)
                edit_favorite_moment = edit_extra_columns[0].text_input(
                    "Favorite moment (optional)", value=entry["favorite_moment"]
                )
                edit_would_return = edit_extra_columns[1].text_input(
                    "Would you go back? (optional)", value=entry["would_return"]
                )
                # The checklist he sees while writing -- editable only while the
                # entry is still his to write (planned / sent back). On a
                # completed entry it's done its job, so it's left out here.
                edit_requirements = (
                    st.text_area(
                        "What he has to include (one requirement per line)",
                        value=entry.get("requirements") or "",
                        height=200,
                        help="He sees these as a checklist while writing. Leave "
                        "blank for a free-form entry.",
                    )
                    if entry["status"] in ("planned", "needs_revision")
                    else None
                )
                # Only a completed entry has feedback to fix -- approving is
                # the only other place it's set, and that box is already
                # this same size for exactly this reason (a single-line
                # text_input used to flatten a pasted, multi-paragraph note
                # into one line with no way to go back and redo it).
                edit_feedback = (
                    st.text_area(
                        "Feedback (shown to him)",
                        value=entry["parent_feedback"],
                        height=200,
                        help="Fix formatting or reword it -- this replaces what he currently sees.",
                    )
                    if entry["status"] == "completed"
                    else None
                )
                if st.form_submit_button("Save changes", type="primary") and edit_title.strip():
                    db.update_travel_entry(
                        entry["id"],
                        state=edit_state,
                        visited_on=edit_date.isoformat(),
                        title=edit_title.strip(),
                        story=edit_story.strip(),
                        park_key=edit_park.key if edit_park else None,
                        favorite_moment=edit_favorite_moment.strip(),
                        would_return=edit_would_return.strip(),
                        **(
                            {"requirements": edit_requirements.strip()}
                            if edit_requirements is not None
                            else {}
                        ),
                    )
                    # Its own call, not folded into the dict above -- this
                    # is the one field that also decides whether to mark
                    # the entry unread again (see set_travel_entry_feedback),
                    # a side effect none of the other fields have.
                    if edit_feedback is not None:
                        db.set_travel_entry_feedback(entry["id"], edit_feedback.strip())
                    st.session_state["editing_travel_entry"] = None
                    st.rerun()


map_tab, journal_tab = st.tabs(["The map", "Travel journal"])

with map_tab:
    st.markdown(
        f"""
        <div style="background:var(--c-panel); border:1px solid var(--c-border);
             border-radius:var(--c-radius); padding:16px; box-shadow:var(--c-glow);">
          {parks.render_travel_map_svg("conus", visited_states, visited_park_keys, newest_park_key)}
          <div style="display:flex; gap:14px; margin-top:10px;">
            <div style="flex:1;">
              <div style="font-size:11px; color:var(--c-dim); text-transform:uppercase;
                   margin-bottom:4px; font-weight:700;">Alaska</div>
              {parks.render_travel_map_svg("alaska", visited_states, visited_park_keys, newest_park_key)}
            </div>
            <div style="flex:1;">
              <div style="font-size:11px; color:var(--c-dim); text-transform:uppercase;
                   margin-bottom:4px; font-weight:700;">Hawaii</div>
              {parks.render_travel_map_svg("hawaii", visited_states, visited_park_keys, newest_park_key)}
            </div>
          </div>
        </div>
        <div style="display:flex; gap:10px; margin-top:14px;">
          <div style="flex:1; background:var(--c-panel); border:1px solid var(--c-border);
               border-radius:var(--c-radius); padding:10px 14px; text-align:center;">
            <div style="font-family:{_MONO_FONT}; font-size:24px; font-weight:800;">
              {len(visited_states)}<span style="font-size:13px; color:var(--c-dim);">/{len(parks.STATES)}</span>
            </div>
            <div style="font-size:10px; color:var(--c-dim); text-transform:uppercase;">States visited</div>
          </div>
          <div style="flex:1; background:var(--c-panel); border:1px solid var(--c-border);
               border-radius:var(--c-radius); padding:10px 14px; text-align:center;">
            <div style="font-family:{_MONO_FONT}; font-size:24px; font-weight:800;">
              {len(visited_park_keys)}<span style="font-size:13px; color:var(--c-dim);">/{len(parks.PARKS)}</span>
            </div>
            <div style="font-size:10px; color:var(--c-dim); text-transform:uppercase;">Parks visited</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with journal_tab:
    if msg := st.session_state.pop("travel_entry_needs_more_detail", None):
        st.warning(msg)

    if open_pick_entries:
        count_label = "trip" if len(open_pick_entries) == 1 else "trips"
        st.subheader(f"🎯 Assigned: pick {len(open_pick_entries)} {count_label} of your own")
        st.caption("Choose where, write it up, submit for review -- same as any other entry.")
        for entry in open_pick_entries:
            _render_entry(entry)
        st.divider()

    st.subheader("Add a travel entry")
    st.caption(
        "Every trip gets its own entry -- it doesn't have to be about a park. "
        "If there wasn't one that trip, just tell the state's story. Past "
        "trips count too -- write up one we've already taken. **A real "
        "account of a real trip** -- who was there, what you did, what you "
        f"remember -- at least {config.TRAVEL_JOURNAL_MIN_STORY_WORDS} words. "
        "Not a one-line errand like a stop at the store."
    )
    # The park selector lives outside the form: form widgets only report
    # their values on submit, but picking a park needs to update the state
    # dropdown's default *immediately* so Landon can't save a trip whose
    # state doesn't match its park.
    PARK_FIELD = "travel_entry_park"
    if st.session_state.pop("travel_entry_just_saved", False):
        st.session_state[PARK_FIELD] = None

    park_choice = st.selectbox(
        "National Park (optional)",
        [None, *parks.PARKS],
        format_func=lambda p: "No park this trip" if p is None else f"{p.name} ({p.states})",
        key=PARK_FIELD,
        help="Picking a park fills in its state below -- it's still editable "
        "if this trip was really based somewhere else.",
    )

    default_state = parks.STATES[0]
    park_states: list[str] = []
    if park_choice is not None:
        park_states = [
            parks.STATE_ABBR[abbr] for abbr in park_choice.states.split("/") if abbr in parks.STATE_ABBR
        ]
        if park_states:
            default_state = park_states[0]
    if len(park_states) > 1:
        st.caption(
            f"{park_choice.name} spans {', '.join(park_states)} -- defaulted to "
            f"{default_state} below, change it if this trip was based in one of the others."
        )

    # Also outside the form, same reasoning as park_choice above -- a
    # checkbox *inside* a form doesn't rerun the script when clicked (only
    # the form's own submit button does), so a date_input that's only
    # supposed to appear once this box is checked would never actually
    # show up in a browser, only ever exist in whatever the script's very
    # first render happened to compute. Confirmed live: the box checked
    # fine, the date picker never appeared.
    assign_day: date | None = None
    if is_parent():
        assign = st.checkbox(
            "Assign this trip to be written up on a specific day",
            key="travel_entry_assign_toggle",
            help="Leave the story below blank and he'll see this as an assignment "
            "on Home and the Week grid until he fills it in.",
        )
        if assign:
            assign_day = st.date_input("Day", value=date.today(), key="travel_entry_assign_day")

        st.caption(
            "Or don't pick the trip for him -- assign him to choose his own "
            "and write about them, same review gate, due by a day you set."
        )
        open_pick_columns = st.columns([2, 2, 3])
        open_pick_count = open_pick_columns[0].number_input(
            "How many trips",
            min_value=1,
            max_value=config.TRAVEL_JOURNAL_MAX_OPEN_PICKS,
            value=2,
            step=1,
            key="travel_entry_open_pick_count",
        )
        open_pick_due = open_pick_columns[1].date_input(
            "Due by", value=date.today(), key="travel_entry_open_pick_due"
        )
        with open_pick_columns[2]:
            st.markdown("<div style='height:28px;'></div>", unsafe_allow_html=True)
            if st.button("🧭 Assign him to pick & write up", key="assign_open_travel_picks"):
                db.assign_open_travel_entries(
                    student["id"], int(open_pick_count), open_pick_due.isoformat(),
                    requirements=config.TRAVEL_JOURNAL_DEFAULT_REQUIREMENTS,
                )
                st.rerun()

        st.caption(
            "Or keep the portfolio growing without deciding anything yourself -- "
            "picks a real state (sometimes paired with one of its National Parks) "
            "he hasn't logged a trip for yet, due in a week."
        )
        if st.button("🎲 Assign a random trip", key="assign_random_travel_prompt"):
            state, park = parks.random_unvisited_prompt(visited_states, visited_park_keys)
            due = date.today() + timedelta(days=7)
            title = park.name if park else f"A trip to {state}"
            new_id = db.add_travel_entry(
                student["id"],
                state,
                due.isoformat(),
                title=title,
                park_key=park.key if park else None,
                status="planned",
                requirements=config.TRAVEL_JOURNAL_DEFAULT_REQUIREMENTS,
            )
            db.schedule_travel_entry(new_id, due.isoformat())
            st.success(f"Assigned: {title} -- due {due.isoformat()}.")
            st.rerun()

    with st.form("add_travel_entry", clear_on_submit=True):
        top_columns = st.columns([2, 1])
        state_choice = top_columns[0].selectbox(
            "State", parks.STATES, index=parks.STATES.index(default_state)
        )
        visited_on = top_columns[1].date_input("Date", value=date.today())

        title = st.text_input("Title", placeholder="e.g. Glaciers Before They're Gone")
        story = st.text_area(
            "The story",
            placeholder=(
                "Who was there? What was it like? What was your favorite part? "
                "Give real detail -- not just \"we went here and it was cool.\""
            ),
            height=140,
            help="Take your time here. Details, details, details. Leave this blank to "
            "just assign the trip for now -- see below.",
        )
        extra_columns = st.columns(2)
        favorite_moment = extra_columns[0].text_input(
            "Favorite moment (optional)", placeholder="e.g. Watching Old Faithful erupt"
        )
        would_return = extra_columns[1].text_input(
            "Would you go back? (optional)", placeholder="e.g. Yes, in the fall next time"
        )

        # Parent-only checklist he'll see while writing this trip up -- one
        # requirement per line, pre-filled with the standard "past trip memory"
        # structure. Clear it for a free-form entry, or rewrite it for this
        # trip. Only stored (and shown to him) when a parent assigns the trip.
        requirements = ""
        if is_parent():
            requirements = st.text_area(
                "What he has to include (one requirement per line)",
                value=config.TRAVEL_JOURNAL_DEFAULT_REQUIREMENTS,
                height=200,
                help="He sees these as a checklist while writing it up. Edit or "
                "clear them for this trip. Leave blank for a free-form entry.",
            )

        # Based on `assign_day` (known accurately outside the form, see
        # above), not on `story` -- a text_area inside a form only reports
        # its live value at submit time like every other form widget, so a
        # label reacting to what's currently typed would just show
        # whatever was there on the *previous* run, not this keystroke.
        submit_label = "Assign this trip" if assign_day is not None else "Save this entry"
        if st.form_submit_button(submit_label, type="primary") and title.strip():
            # A real story submits straight for review, same as a lesson --
            # a blank one (only reachable in parent view; the story field
            # is the whole point for anyone else) is a stub assignment with
            # nothing to review yet. A story that's too short to be a real
            # account doesn't submit either -- it saves as a stub instead,
            # so nothing typed is lost, and he can pick "Write it up" below
            # to finish it once it clears the bar.
            word_count = len(story.split())
            meets_requirement = word_count >= config.TRAVEL_JOURNAL_MIN_STORY_WORDS
            entry_status = "submitted" if (story.strip() and meets_requirement) else "planned"
            new_id = db.add_travel_entry(
                student["id"],
                state_choice,
                visited_on.isoformat(),
                title=title.strip(),
                story=story.strip(),
                park_key=park_choice.key if park_choice else None,
                favorite_moment=favorite_moment.strip(),
                would_return=would_return.strip(),
                status=entry_status,
                requirements=requirements.strip(),
            )
            if assign_day is not None:
                db.schedule_travel_entry(new_id, assign_day.isoformat())
            st.session_state["travel_entry_just_saved"] = True
            if story.strip() and not meets_requirement:
                st.session_state["travel_entry_needs_more_detail"] = (
                    f'Saved "{title.strip()}" but it needs at least '
                    f"{config.TRAVEL_JOURNAL_MIN_STORY_WORDS} words of real detail before "
                    f"it's ready to submit -- {word_count} so far. Find it below and pick "
                    '"Write it up" to keep going.'
                )
            st.rerun()

    st.divider()

    if graded_entries:
        header_columns = st.columns([2, 2])
        with header_columns[0]:
            group_mode = st.radio(
                "Group by", ["State", "School year"], horizontal=True, label_visibility="collapsed"
            )
        with header_columns[1]:
            export_entries = [
                dict(
                    e,
                    park_name=(parks.park_by_key(e["park_key"]).name if e["park_key"] else ""),
                )
                for e in graded_entries
            ]
            st.download_button(
                "📄 Export the Travel Journal",
                data=partial(travel_journal_to_docx, export_entries, student["name"]),
                file_name=travel_journal_filename(student["name"]),
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )

    if not entries_by_state:
        st.caption("No entries yet -- add the first trip above.")
    elif group_mode == "State":
        for state_name in sorted(entries_by_state):
            state_entries = entries_by_state[state_name]
            count_label = "entry" if len(state_entries) == 1 else "entries"
            with st.expander(f"{state_name} — {len(state_entries)} {count_label}"):
                for entry in state_entries:
                    _render_entry(entry)
    else:
        for year_label in sorted(entries_by_year, key=lambda label: year_sort_keys[label], reverse=True):
            year_entries = entries_by_year[year_label]
            count_label = "entry" if len(year_entries) == 1 else "entries"
            with st.expander(f"{year_label} — {len(year_entries)} {count_label}"):
                for entry in year_entries:
                    _render_entry(entry)
