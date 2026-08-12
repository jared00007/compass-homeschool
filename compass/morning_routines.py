"""Morning routines -- a short, parent-curated menu of stretches, breathing
exercises, and quick mindfulness practices to start the day on a positive
note. Static content, not agent-generated, same reasoning as the Life
Skills catalog: this is personal to the family, not something worth an API
call for.

Washington's Health subject explicitly covers "physical, nutritional, and
mental wellbeing" (RCW 28A.225), so completing one of these earns real
credit toward that subject, not just a feel-good checkbox.
"""

from __future__ import annotations

from datetime import date

MorningRoutine = tuple[str, str, str, int, str, tuple[str, ...]]
# (key, title, icon, duration_minutes, intro, steps)

MORNING_ROUTINES: tuple[MorningRoutine, ...] = (
    ("wake_up_stretch", "Wake-Up Stretch", "🌤️", 5,
     "Loosen up before you start moving -- nothing intense, just wake the body up.",
     (
         "Reach both arms overhead and lean side to side, 5 slow breaths each way.",
         "Roll your shoulders back 10 times, then forward 10 times.",
         "Fold forward, let your arms hang, and sway gently for 30 seconds.",
         "Slow neck rolls, 5 each direction.",
         "Reach up onto your toes, arms overhead, one big stretch, then relax.",
     )),
    ("box_breathing", "Box Breathing", "🌬️", 3,
     "A simple breathing pattern that calms your body down fast -- good for a morning that already feels rushed.",
     (
         "Sit or stand comfortably, relax your shoulders.",
         "Breathe in slowly through your nose for 4 counts.",
         "Hold your breath for 4 counts.",
         "Breathe out slowly through your mouth for 4 counts.",
         "Hold empty for 4 counts. Repeat the whole cycle 5 times.",
     )),
    ("sun_salutation", "Sun Salutation Basics", "🧘", 6,
     "A simple beginner yoga flow to wake up your whole body, not just stretch one part of it.",
     (
         "Stand tall, hands together at your chest.",
         "Reach both arms up high, lean back slightly.",
         "Fold forward, hands toward your feet, knees soft.",
         "Step back into a plank position, hold for 3 breaths.",
         "Lower down, then press up into a gentle backbend (cobra).",
         "Push back into downward dog, hold for 5 breaths.",
         "Walk your feet forward, fold, then roll up to standing.",
     )),
    ("gratitude_scan", "Gratitude + Body Scan", "🌱", 4,
     "A quiet couple of minutes to notice how you're actually feeling before the day gets going.",
     (
         "Lie down or sit somewhere comfortable, close your eyes.",
         "Think of one thing you're actually looking forward to today.",
         "Slowly notice each part of your body, toes to head -- just notice, don't judge it.",
         "Take 5 slow, deep breaths.",
         "Open your eyes when you're ready.",
     )),
    ("energizing_flow", "Energizing Morning Flow", "⚡", 5,
     "A little more movement, for a day you want to hit the ground running on.",
     (
         "10 jumping jacks.",
         "10 bodyweight squats.",
         "20-second plank hold.",
         "Reach up, big stretch, 3 slow breaths.",
         "Shake out your arms and legs.",
     )),
    ("quiet_mind", "Quiet Mind Minute", "🌙", 2,
     "Short and simple, for a morning you don't have much time.",
     (
         "Sit still, close your eyes.",
         "Breathe normally, just pay attention to the breath moving in and out.",
         "If your mind wanders, that's normal -- just come back to the breath.",
         "Do this for one full minute.",
         "Open your eyes, take one big stretch.",
     )),
)

MORNING_ROUTINES_BY_KEY = {r[0]: r for r in MORNING_ROUTINES}


def routine_for_date(iso_date: str) -> MorningRoutine:
    """Deterministic day-to-day rotation via the date's ordinal day count --
    stable within a day, cycles cleanly across days, no randomness that
    would make two people looking at the same day see different suggestions.
    """
    day_number = date.fromisoformat(iso_date).toordinal()
    return MORNING_ROUTINES[day_number % len(MORNING_ROUTINES)]
