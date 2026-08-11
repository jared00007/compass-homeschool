"""National Parks -- a family tracker, deliberately standalone for now: no
hours, no subject credit, nothing touching Compliance or Activity Log. Real
coordinates, a real traced US coastline -- see compass/national_parks.py's
own docstring for where that data comes from.
"""

from __future__ import annotations

from datetime import date

import streamlit as st

from compass import national_parks as parks
from compass import theme as theming
from compass.ui import is_parent, page_setup

db, student = page_setup("National Parks", icon="🏞️")

# Single-quoted -- the real heading font stack (theming.THEME.heading_font)
# has its own double-quoted font names ("Avenir Next", "Segoe UI") inside it,
# which would otherwise prematurely close a double-quoted HTML style="..."
# attribute the moment they're interpolated in, silently truncating every
# CSS declaration after it. Confirmed live: the truncated tail was being
# parsed as bogus HTML attributes instead of CSS.
_HEADING_FONT = theming.THEME.heading_font.replace('"', "'")

st.title("🏞️ National Parks")
st.caption(
    "Every trip counts. Mark a park visited and log when you went -- a family "
    "record, kept separate from the compliance hours."
)

visits = db.list_park_visits(student["id"])
visited_keys = {v["park_key"] for v in visits}
visits_by_park: dict[str, list[dict]] = {}
for v in visits:
    visits_by_park.setdefault(v["park_key"], []).append(v)

map_tab, list_tab = st.tabs(["The map", "All parks"])

with map_tab:
    visited_count = len(visited_keys)
    newest_visit = visits[0] if visits else None  # list_park_visits is already newest-first
    newest_key = newest_visit["park_key"] if newest_visit else None

    heading_html = f'{visited_count} CONQUERED!' if visited_count else "0 SO FAR -- LET'S GO!"
    banner_html = ""
    if newest_key:
        newest_park = parks.park_by_key(newest_key)
        banner_html = (
            '<div style="position:relative; margin-top:-18px; margin-left:8px; '
            'display:inline-block; z-index:3;">'
            '<div style="background:#FF5A36; color:#FFFBF0; '
            f'font-family:{_HEADING_FONT}; '
            'font-weight:900; font-size:14px; text-transform:uppercase; padding:8px 16px; '
            'border:3px solid #241C12; border-radius:4px; transform:rotate(-2deg); '
            'box-shadow:3px 3px 0 rgba(0,0,0,.4); display:inline-block;">'
            f"★ latest: {newest_park.name}!</div></div>"
        )

    st.markdown(
        f"""
        <div style="position:relative; padding:22px; background:#241C12; border-radius:8px; margin-top:22px;">
          <div style="position:absolute; top:-26px; left:24px; transform:rotate(-3deg);
               font-family:{_HEADING_FONT}; font-weight:900; font-size:30px;
               text-transform:uppercase; color:var(--c-primary); -webkit-text-stroke:1.4px #241C12;
               text-shadow:3px 3px 0 rgba(0,0,0,.5); letter-spacing:.02em; z-index:2;">
            {heading_html}
          </div>
          <div style="background:var(--c-panel); border:3px solid #241C12; border-radius:6px;
               padding:16px; margin-top:10px; box-shadow: 6px 6px 0 rgba(0,0,0,.35);">
            {parks.render_map_svg("conus", visited_keys, newest_key)}
            <div style="display:flex; gap:14px; margin-top:10px;">
              <div style="flex:1;">
                <div style="font-size:11px; color:var(--c-dim); text-transform:uppercase;
                     margin-bottom:4px; font-weight:700;">Alaska</div>
                {parks.render_map_svg("alaska", visited_keys, newest_key)}
              </div>
              <div style="flex:1;">
                <div style="font-size:11px; color:var(--c-dim); text-transform:uppercase;
                     margin-bottom:4px; font-weight:700;">Hawaii</div>
                {parks.render_map_svg("hawaii", visited_keys, newest_key)}
              </div>
            </div>
          </div>
          {banner_html}
          <div style="display:flex; gap:12px; margin-top:20px;">
            <div style="flex:1; background:var(--c-primary); border:3px solid #241C12;
                 border-radius:6px; padding:10px 14px; text-align:center;
                 box-shadow:3px 3px 0 rgba(0,0,0,.3); transform:rotate(-1deg);">
              <div style="font-family:var(--c-mono); font-size:26px; font-weight:900;">
                {visited_count}<span style="font-size:14px;">/{len(parks.PARKS)}</span>
              </div>
              <div style="font-size:10px; text-transform:uppercase; font-weight:700;">Parks conquered</div>
            </div>
            <div style="flex:1; background:#FFFBF0; border:3px solid #241C12; border-radius:6px;
                 padding:10px 14px; text-align:center; box-shadow:3px 3px 0 rgba(0,0,0,.3);
                 transform:rotate(1deg);">
              <div style="font-family:var(--c-mono); font-size:26px; font-weight:900; color:var(--c-border);">
                {len(parks.PARKS) - visited_count}
              </div>
              <div style="font-size:10px; text-transform:uppercase; font-weight:700; color:var(--c-border);">
                Still out there
              </div>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.divider()
    st.subheader("Log a visit")
    st.caption(
        "A park can be logged more than once -- a return trip gets its own entry, "
        "nothing overwrites the last one."
    )
    with st.form("log_visit", clear_on_submit=True):
        form_columns = st.columns([2, 1])
        park_choice = form_columns[0].selectbox(
            "Park",
            parks.PARKS,
            format_func=lambda p: f"{'📍 ' if p.key in visited_keys else ''}{p.name} ({p.states})",
        )
        visited_on = form_columns[1].date_input("Date", value=date.today())
        if st.form_submit_button("Log this visit", type="primary"):
            db.add_park_visit(student["id"], park_choice.key, visited_on.isoformat())
            st.rerun()

with list_tab:
    for region in parks.REGIONS:
        region_parks = [p for p in parks.PARKS if p.region == region]
        region_visited = sum(1 for p in region_parks if p.key in visited_keys)
        with st.expander(f"{region} — {region_visited}/{len(region_parks)}"):
            for p in region_parks:
                park_visits = sorted(
                    visits_by_park.get(p.key, []), key=lambda v: v["visited_on"], reverse=True
                )
                columns = st.columns([4, 2])
                badge = "📍 visited" if park_visits else "— not yet"
                columns[0].markdown(f"**{p.name}** · {p.states} — {badge}")
                if park_visits:
                    with columns[1]:
                        for entry in park_visits:
                            date_col, remove_col = st.columns([2, 1])
                            date_col.caption(entry["visited_on"])
                            if is_parent() and remove_col.button(
                                "Remove", key=f"remove_visit_{entry['id']}"
                            ):
                                db.delete_park_visit(entry["id"])
                                st.rerun()
