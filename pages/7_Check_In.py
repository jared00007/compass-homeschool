"""Check-In -- a daily feelings journal. One entry per day: a required
feeling pick plus an optional note about anything at all, not just school.
Fully visible to a parent by design, and told to him plainly on the page --
never a "private" space he's misled about.

The input card (feeling picker + note + Save) is his to fill in -- a parent
opening this page gets a read-only look back at what he's said, not a form
that lets them fill it in for him or overwrite it.
"""

from __future__ import annotations

import html
import sqlite3
from datetime import date

import streamlit as st

from compass import auth
from compass.ui import is_parent, page_setup

db, student = page_setup("Check-In", icon="💬")

# A parent only gets the read-only browse once a PIN actually separates
# "parent" from "student" -- families that haven't set one up yet share a
# single view, and gating the input card on is_parent() alone would have
# taken away the only way anyone could ever save a check-in.
browse_only = is_parent() and auth.pin_is_set(db)

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

today = date.today().isoformat()
todays_entry = db.journal_entry_for_date(student["id"], today)

if browse_only:
    st.caption(f"A look back at how {student['name'].split()[0]}'s been checking in.")
else:
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

    if is_parent():
        st.caption(
            "💡 Set a parent PIN (sidebar) to keep this as his own space to fill "
            "in, and get a read-only look back here instead."
        )

    FEELING_KEY = "checkin_feeling_choice"
    if FEELING_KEY not in st.session_state:
        st.session_state[FEELING_KEY] = None

    def _save_checkin() -> None:
        # Runs as an on_click callback, which fires *before* the rerun that
        # follows a button click -- the one place Streamlit allows touching a
        # widget's own session_state key, which is what clearing the form
        # after save actually requires.
        try:
            db.save_journal_entry(
                student["id"],
                today,
                st.session_state[FEELING_KEY],
                st.session_state.get("checkin_note", "").strip(),
            )
        except sqlite3.OperationalError:
            st.session_state["_checkin_error"] = True
        else:
            st.session_state["_checkin_saved"] = True
            st.session_state[FEELING_KEY] = None
            st.session_state["checkin_note"] = ""

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
        if todays_entry:
            # A refresh reloads this from the DB, not from anything still held
            # in memory -- this line is proof, on any later visit, that a save
            # actually landed, without having to notice a highlighted button
            # and separately reconcile that against an empty history list below.
            st.caption("✓ Saved for today — change it anytime before tomorrow.")
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

        st.text_area(
            "Want to say more? Anything -- school, friends, home, whatever's on "
            "your mind. (optional)",
            placeholder="Sometimes it helps just to get it out.",
            height=90,
            key="checkin_note",
        )

        save_disabled = st.session_state[FEELING_KEY] is None
        st.button(
            "Save today's check-in",
            type="primary",
            disabled=save_disabled,
            on_click=_save_checkin,
        )
        if st.session_state.pop("_checkin_error", False):
            st.error(
                "Couldn't save -- the app needs a full restart to pick up this "
                "update (closing and reopening the terminal/app, not just "
                "refreshing the browser tab)."
            )
        if st.session_state.pop("_checkin_saved", False):
            st.success("Saved.")
        if save_disabled:
            st.caption("⬆️ Pick a feeling above to save today's check-in.")

st.divider()

st.subheader("Check-in history")
# Today's is included here too, not just in the live card above -- the whole
# point of a journal is being able to look back over it, today included, and
# a "history" that hides the entry you just made isn't one.
entries = db.list_journal_entries(student["id"])

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
        date_label = f"Today, {entry['entry_date']}" if entry["entry_date"] == today else entry["entry_date"]
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
                      <div style="font-size:12px; color:var(--c-dim); white-space:nowrap;">{date_label}</div>
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
