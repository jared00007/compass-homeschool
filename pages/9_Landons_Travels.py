"""Landon's Travels -- a family travel journal, deliberately standalone for
now: no hours, no subject credit, nothing touching Compliance or Activity
Log. Real state borders and National Park pins -- see
compass/national_parks.py's own docstring for where that data comes from.
"""

from __future__ import annotations

import html
from datetime import date

import streamlit as st

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
    "whole map. A family record, kept separate from the compliance hours."
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
        story = st.text_area("The story", placeholder="What happened on this trip?", height=140)

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
                if is_parent() and st.button("Remove", key=f"remove_entry_{entry['id']}"):
                    db.delete_travel_entry(entry["id"])
                    st.rerun()
