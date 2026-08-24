"""Landon's Travels -- a family travel journal. Entries are pure journal by
default, same as Choice Topics and Life Skills: writing them logs nothing on
its own, but a parent can log real minutes against a specific entry when it
was genuine researched work, not just a two-sentence trip recap, or seed it
as an open History topic (compass.storage.db.add_web_node) to be picked up
by a real generated lesson later -- never automatic, either way. Real state
borders and National Park pins -- see compass/national_parks.py's own
docstring for where that data comes from.
"""

from __future__ import annotations

import html
from datetime import date

import streamlit as st

from compass import config
from compass import national_parks as parks
from compass import theme as theming
from compass.ui import is_parent, page_setup

db, student = page_setup("Landon's Travels", icon="🧭")

# Single-quoted -- theme.THEME's font stacks embed their own double-quoted
# font names (e.g. "Segoe UI", "SF Mono"), which would otherwise prematurely
# close a double-quoted HTML style="..." attribute the moment they're
# interpolated in, silently truncating every CSS declaration after it.
_MONO_FONT = theming.THEME.mono_font.replace('"', "'")

st.title("🧭 Landon's Travels")
st.caption(
    "Every state has a story -- National Parks are part of it, not the "
    "whole map. Entries are a family record first; a parent can log real "
    "minutes against one when it was genuine researched writing."
)

entries = db.list_travel_entries(student["id"])
visited_states = {e["state"] for e in entries}
visited_park_keys = {e["park_key"] for e in entries if e["park_key"]}
newest_park_key = next((e["park_key"] for e in entries if e["park_key"]), None)

entries_by_state: dict[str, list[dict]] = {}
for e in entries:
    entries_by_state.setdefault(e["state"], []).append(e)

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
    st.subheader("Add a travel entry")
    st.caption(
        "Every trip gets its own entry -- it doesn't have to be about a park. "
        "If there wasn't one that trip, just tell the state's story. Past "
        "trips count too -- write up one we've already taken."
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
            help="Take your time here. Details, details, details.",
        )

        if st.form_submit_button("Save this entry", type="primary") and title.strip():
            db.add_travel_entry(
                student["id"],
                state_choice,
                visited_on.isoformat(),
                title=title.strip(),
                story=story.strip(),
                park_key=park_choice.key if park_choice else None,
            )
            st.session_state["travel_entry_just_saved"] = True
            st.rerun()

    st.divider()

    if not entries_by_state:
        st.caption("No entries yet -- add the first trip above.")

    for state_name in sorted(entries_by_state):
        state_entries = entries_by_state[state_name]
        count_label = "entry" if len(state_entries) == 1 else "entries"
        with st.expander(f"{state_name} — {len(state_entries)} {count_label}"):
            for entry in state_entries:
                park = parks.park_by_key(entry["park_key"]) if entry["park_key"] else None
                park_tag = (
                    f'<div style="font-size:11px; color:var(--c-border); text-transform:uppercase; '
                    f'letter-spacing:.03em; margin:4px 0 8px; font-weight:700;">📍 {html.escape(park.name)}</div>'
                    if park
                    else ""
                )
                story_text = entry["story"].strip()
                story_html = (
                    html.escape(story_text).replace("\n", "<br>")
                    if story_text
                    else '<span style="color:var(--c-dim);">No story written yet.</span>'
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
                      <div style="font-size:13.5px; line-height:1.6; color:var(--c-text);
                           margin-top:{"4px" if park_tag else "10px"};">
                        {story_html}
                      </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                if is_parent():
                    editing = st.session_state.get("editing_travel_entry") == entry["id"]
                    logging_hours = st.session_state.get("logging_travel_entry") == entry["id"]
                    button_columns = st.columns([1, 1, 1, 1, 4])
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
                            if st.form_submit_button("Save changes", type="primary") and edit_title.strip():
                                db.update_travel_entry(
                                    entry["id"],
                                    state=edit_state,
                                    visited_on=edit_date.isoformat(),
                                    title=edit_title.strip(),
                                    story=edit_story.strip(),
                                    park_key=edit_park.key if edit_park else None,
                                )
                                st.session_state["editing_travel_entry"] = None
                                st.rerun()
