"""National Parks -- a family tracker, deliberately standalone for now: no
hours, no subject credit, nothing touching Compliance or Activity Log. Real
coordinates, a real traced US coastline -- see compass/national_parks.py's
own docstring for where that data comes from.
"""

from __future__ import annotations

from datetime import date

import streamlit as st

from compass import national_parks as parks
from compass.ui import is_parent, page_setup

db, student = page_setup("National Parks", icon="🏞️")

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
    st.metric("Parks visited", f"{len(visited_keys)} / {len(parks.PARKS)}")

    insets = parks.map_insets()
    pins_by_inset: dict[str, list[str]] = {"conus": [], "alaska": [], "hawaii": []}
    for p in parks.PARKS:
        placed = parks.project(p.lat, p.lon)
        if placed is None:
            continue
        inset_name, x, y = placed
        visited = p.key in visited_keys
        fill = "var(--c-primary)" if visited else "none"
        stroke = "var(--c-text)" if visited else "var(--c-dim)"
        title = f"{p.name}, {p.states}" + (" -- visited" if visited else "")
        pins_by_inset[inset_name].append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.5" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="1.4"><title>{title}</title></circle>'
        )

    def svg_for(name: str) -> str:
        box = insets[name]
        pins = "".join(pins_by_inset[name])
        return (
            f'<svg width="{box["w"]}" height="{box["h"]}" viewBox="0 0 {box["w"]} {box["h"]}" '
            'style="display:block;">'
            f'<path d="{box["path"]}" fill="var(--c-panel)" stroke="var(--c-border)" '
            'stroke-width="1.2"/>'
            f"{pins}</svg>"
        )

    st.markdown(
        '<div style="border:1px solid var(--c-border); border-radius:var(--c-radius); '
        'padding:14px; background:var(--c-panel); box-shadow:var(--c-glow); '
        f'display:inline-block;">{svg_for("conus")}</div>',
        unsafe_allow_html=True,
    )

    inset_columns = st.columns(2)
    with inset_columns[0]:
        st.caption("Alaska")
        st.markdown(
            '<div style="border:1px solid var(--c-border); border-radius:var(--c-radius); '
            f'padding:10px; background:var(--c-panel); display:inline-block;">{svg_for("alaska")}</div>',
            unsafe_allow_html=True,
        )
    with inset_columns[1]:
        st.caption("Hawaii")
        st.markdown(
            '<div style="border:1px solid var(--c-border); border-radius:var(--c-radius); '
            f'padding:10px; background:var(--c-panel); display:inline-block;">{svg_for("hawaii")}</div>',
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
