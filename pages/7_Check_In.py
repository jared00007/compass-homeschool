"""Check-In -- a daily feelings journal. One entry per day: a required
feeling pick plus an optional note about anything at all, not just school.
Fully visible to a parent by design, and told to him plainly on the page --
never a "private" space he's misled about.
"""

from __future__ import annotations

import html
import sqlite3
from datetime import date

import streamlit as st

from compass.ui import is_parent, page_setup

db, student = page_setup("Check-In", icon="💬")

FEELINGS: tuple[tuple[str, str], ...] = (
    ("😊", "Good"),
    ("😌", "Calm"),
    ("😕", "Frustrated"),
    ("😢", "Sad"),
    ("😠", "Angry"),
    ("😰", "Anxious"),
    ("😴", "Tired"),
    ("🤯", "Overwhelmed"),
)
FEELING_EMOJI = {label: emoji for emoji, label in FEELINGS}
FEELINGS_PER_ROW = 4

st.title("💬 Check-In")
st.caption("One tap for how you're doing, and a line if you want to say more.")

st.markdown(
    """
    <div style="background:var(--c-panel); border-left:3px solid var(--c-alt);
         border-radius:var(--c-radius); padding:12px 16px; margin-bottom:20px;
         font-size:13.5px; box-shadow:var(--c-glow);">
      👀 <b>Your parents can read what you write here.</b> No secrets, no
      surprises -- this is a space to check in honestly, not a hidden diary.
    </div>
    """,
    unsafe_allow_html=True,
)

today = date.today().isoformat()
todays_entry = db.journal_entry_for_date(student["id"], today)

FEELING_KEY = "checkin_feeling_choice"
if FEELING_KEY not in st.session_state:
    st.session_state[FEELING_KEY] = todays_entry["feeling"] if todays_entry else None

_TODAY_CARD_CSS = """
<style>
div[class*="st-key-checkin_today_card"] {
  border: 1px solid var(--c-border) !important;
  border-radius: var(--c-radius) !important;
  background: var(--c-panel) !important;
  box-shadow: var(--c-glow);
  padding: 18px !important;
}
</style>
"""
st.markdown(_TODAY_CARD_CSS, unsafe_allow_html=True)

with st.container(key="checkin_today_card"):
    st.markdown("**Today — how are you feeling?**")
    for row_start in range(0, len(FEELINGS), FEELINGS_PER_ROW):
        row = FEELINGS[row_start : row_start + FEELINGS_PER_ROW]
        columns = st.columns(FEELINGS_PER_ROW)
        for column, (emoji, label) in zip(columns, row):
            selected = st.session_state[FEELING_KEY] == label
            with column:
                if st.button(
                    f"{emoji} {label}",
                    key=f"feeling_{label}",
                    type="primary" if selected else "secondary",
                    width="stretch",
                ):
                    st.session_state[FEELING_KEY] = label
                    st.rerun()

    note = st.text_area(
        "Want to say more? Anything -- school, friends, home, whatever's on "
        "your mind. (optional)",
        value=todays_entry["note"] if todays_entry else "",
        placeholder="Sometimes it helps just to get it out.",
        height=90,
        key="checkin_note",
    )

    save_disabled = st.session_state[FEELING_KEY] is None
    if st.button("Save today's check-in", type="primary", disabled=save_disabled):
        try:
            db.save_journal_entry(
                student["id"], today, st.session_state[FEELING_KEY], note.strip()
            )
        except sqlite3.OperationalError:
            st.error(
                "Couldn't save -- the app needs a full restart to pick up this "
                "update (closing and reopening the terminal/app, not just "
                "refreshing the browser tab)."
            )
        else:
            st.success("Saved.")
            st.rerun()
    if save_disabled:
        st.caption("⬆️ Pick a feeling above to save today's check-in.")

st.divider()

st.subheader("Past check-ins")
entries = [e for e in db.list_journal_entries(student["id"]) if e["entry_date"] != today]
if not entries:
    st.caption("Nothing yet -- today's will be the first.")
else:
    for entry in entries:
        emoji = FEELING_EMOJI.get(entry["feeling"], "💬")
        note_html = (
            html.escape(entry["note"]).replace("\n", "<br>")
            if entry["note"]
            else '<span style="color:var(--c-dim);">No note.</span>'
        )
        columns = st.columns([20, 1])
        with columns[0]:
            st.markdown(
                f"""
                <div style="background:var(--c-panel); border:1px solid var(--c-border);
                     border-radius:var(--c-radius); padding:14px 16px; box-shadow:var(--c-glow);
                     margin-bottom:10px; display:flex; gap:14px; align-items:flex-start;">
                  <div style="font-size:26px; line-height:1;">{emoji}</div>
                  <div style="flex:1;">
                    <div style="display:flex; justify-content:space-between; align-items:baseline; gap:10px;">
                      <div style="font-weight:800; font-size:14px;">{html.escape(entry["feeling"])}</div>
                      <div style="font-size:12px; color:var(--c-dim); white-space:nowrap;">{entry["entry_date"]}</div>
                    </div>
                    <div style="font-size:13.5px; line-height:1.5; color:var(--c-text); margin-top:3px;">
                      {note_html}
                    </div>
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        if is_parent():
            with columns[1]:
                if st.button("🗑️", key=f"remove_checkin_{entry['id']}", help="Remove this entry"):
                    db.delete_journal_entry(entry["id"])
                    st.rerun()
