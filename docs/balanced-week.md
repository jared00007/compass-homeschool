# Balanced Week — reshaping Compass from a 4-subject grind into a real year

## Why

Compass today is a **four-lane academic engine**: math, science, history, English,
generated on repeat and stacked into the day. But a real 8th-grade year — and
Washington's own eleven-subject requirement — is *academics plus a life*: art,
music, PE, health, hands-on skills, projects, reading for fun, and a lot of
downtime. "Grind four subjects all year" isn't a lighter school; it's a
**narrower** one, and it burns a kid out.

This is the plan to level Compass up into a **balanced week**: academics as the
backbone, enrichment filling the rest of the subjects, and downtime made
legitimate — without throwing away the lesson engine that already works.

## Principles

1. **Build on what's here, don't rewrite.** The lesson shape (Learn → worked
   example → two checks → quiz) stays. The **Board** already schedules six item
   types to days with a Backlog — that is the composition backbone.
2. **Not more content — a better *mix*.** The fix is composition and pacing, not
   piling on more to do.
3. **A day has a target and an end.** "Enough for today" is a feature, not a
   guilt trip.
4. **Enrichment is real school.** Art, PE, a documentary, a build — these count
   (and fill the WA subjects that are currently thin), they aren't filler.

## The model: Blocks and the Day

Everything Landon does is a **Block** with a type:

- **Core lesson** — math / science / history / English (the existing engine).
- **Enrichment** — art & music, PE / movement / health, watch (documentary),
  life skill, coding, big-project step, field observation, free reading, choice
  topic. (Most already exist; art/music and PE are the new light tracks.)
- **Break / Recess** — explicit, legitimate downtime.

A **Day** is a small, varied set of blocks with a **target** (e.g. 2 core + 1
enrichment + breaks), not an open-ended stack. A **Week** is five days composed
to a rhythm the parent sets.

## Phases

### Phase 1 — Pacing: a day is a mix, and it ends
- A **daily target** the parent sets (how many core lessons/enrichment counts as
  a full day; lighter on some days).
- **"Enough for today"**: once he clears the target, Home flips to *"Core work's
  done — the rest is yours,"* and the red "due" nagging stops.
- Home **"Today's mix"**: the day rendered as a short varied set, not a lesson
  pile.
- *Smallest, highest-value slice — the direct burnout fix.*

### Phase 2 — Fill the missing subjects (light enrichment tracks)
- **Art & Music** track: a light generator / quick-log — make something, listen
  and respond, a creative challenge. Credits `art_and_music`.
- **PE / Movement / Health** track: quick-log a workout, a sport, a walk, a
  health topic. Credits `health`.
- **Watch / Documentary** block: pick or log an educational video; credits the
  subject it fits.
- All become **Board kinds** so they schedule into the day like everything else,
  and feed the compliance dashboard's thin subjects.

### Phase 3 — The Balanced-Week planner (compose, don't stack)
- A **"Plan the week"** tool that lays out a *balanced* week: core lessons spread
  across days and **capped per day**, enrichment slotted in, some days lighter —
  so the parent isn't hand-stacking four lessons a day.
- Optional **rotation** so variety is automatic (art one day, PE another…).
- This is the part that **changes how lessons are generated/scheduled**: you plan
  a week's *mix*, and core lessons are a bounded part of it, not the whole thing.

### Phase 4 — Recess & rewards
- A **Recess menu** of quick, no-stakes break content (riddle, movement
  challenge, doodle, would-you-rather, curiosity of the day).
- The weekly reward loop ties to a **balanced** week (a real mix), not just core
  grind.

## What changes about lesson generation

Not the lesson *shape* — that's good and stays. What changes is **composition and
volume**: instead of generating a four-lesson day, you plan a week's mix where
core academics are capped and enrichment is lighter-weight (quick-log or a small
generation, not a full Learn→quiz lesson every time). The core generators are
untouched; a new layer sits *above* them.

## Data model (sketch, to firm up during build)

- **Board is the backbone.** It already schedules `lesson`, `life_skill`,
  `coding_module`, `choice_topic`, `project_step`, `travel_entry` to days.
- **New Board kinds**: `art_music`, `movement` (PE/health), `watch`. Each is a
  lightweight row (title, minutes, subject credit, done state) + a quick-log,
  mirroring how life skills / coding already work.
- **Day target / rhythm**: a small settings model — core-lessons-per-day and
  which days are lighter — read by Home to compute "enough for today."
- **"Enough for today"** is derived (blocks done vs the day's target), like the
  weekly XP is derived — no new heavy state.

## Open decisions (need the parent's call)

1. **Daily rhythm defaults** — what's a "full day"? e.g. 2 core + 1 enrichment
   Mon–Thu, lighter Fri? Or a minutes cap?
2. **Auto-rotate enrichment**, or the parent picks each block?
3. **Art/PE**: mostly **quick-log** (parent/Landon records what they did) or
   **AI-generated** light activities to do? (Quick-log is simpler and honest;
   generation adds cost.)
4. **Build order** — recommend 1 → 2 → 3 → 4, each shippable on its own.
