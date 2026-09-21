"""Recess -- quick, no-stakes breaks, because half of a real school day isn't a
lesson at all.

A rotating menu of tiny things to do in the gaps: move, doodle, wonder, argue a
silly side. Same deterministic-by-date pattern as `daily.py` -- today's break
holds all day no matter how many times the page reruns, and rotates on its own
with no external call and no cost. Nothing here is graded, logged, or tracked;
its whole job is to make it OK to step away from the work.
"""

from __future__ import annotations

from datetime import date

# (emoji, kind, prompt). A spread of break types so it never feels like one
# thing -- move your body, make something, wonder about something, take a side.
RECESS_BREAKS: tuple[tuple[str, str, str], ...] = (
    ("🏃", "Move", "20 jumping jacks, 10 push-ups, 10 squats. Go."),
    ("🚶", "Move", "Head outside and walk around the block — no phone, just look around."),
    ("🤸", "Move", "Stretch for 3 minutes: reach for the sky, touch your toes, twist side to side."),
    ("🧘", "Move", "Balance on one foot for 30 seconds. Now the other. Now with your eyes closed."),
    ("💃", "Move", "Put on one song and dance like nobody's watching (because nobody is)."),
    ("✏️", "Make", "Draw the weirdest creature you can imagine in 2 minutes. Give it a name."),
    ("🎨", "Make", "Doodle your name as if it were a logo for a band or a game."),
    ("🏗️", "Make", "Build the tallest thing you can from stuff on the table. 5 minutes."),
    ("🎵", "Make", "Tap out a beat on the table for 60 seconds. Try to make it a real rhythm."),
    ("🤔", "Wonder", "Look up how tall the tallest tree on Earth is. Were you close?"),
    ("🌌", "Wonder", "Look up how long light from the Sun takes to reach us. Wild, right?"),
    ("🦖", "Wonder", "Pick any animal and look up one thing about it you didn't know."),
    ("🗺️", "Wonder", "Find the farthest place from where you are right now on a map. How would you get there?"),
    ("⚖️", "Would you rather", "Fly, or be invisible? Pick one and give your real reason."),
    ("⚖️", "Would you rather", "One horse-sized duck, or 100 duck-sized horses? Defend your answer."),
    ("⚖️", "Would you rather", "Always be 10 minutes late, or always be 20 minutes early? Why?"),
    ("⚖️", "Would you rather", "Never use a touchscreen again, or never use a keyboard again?"),
    ("😌", "Chill", "Close your eyes and take 10 slow breaths. That's the whole thing."),
    ("🥪", "Chill", "Go make yourself a snack. You've earned it."),
    ("📞", "Chill", "Tell someone in your house one good thing about your day so far."),
)


def recess_of_the_day(today: date | None = None) -> tuple[str, str, str]:
    """Today's break -- deterministic by date so it holds all day and rotates on
    its own. Returns (emoji, kind, prompt)."""
    today = today or date.today()
    return RECESS_BREAKS[today.toordinal() % len(RECESS_BREAKS)]
