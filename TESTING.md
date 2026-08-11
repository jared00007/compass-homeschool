# Compass — Test Procedure

Everything to verify before the school year starts, in the order that finds problems
soonest. Total API cost if you run every test: **about $2**.

There's an interactive version of this checklist that saves your progress as you go:
<https://claude.ai/code/artifact/3cca995a-36ab-4c91-93ae-1cd25830a952>. This file is
the same content, offline, with Markdown checkboxes you can tick in any editor.

**Items marked ⚠ CRITICAL** are ones where being wrong costs you the year rather than
an afternoon.

**How to use the Pass line:** if what you see doesn't match it, that's a finding. Write
it down rather than moving on.

---

## 1 · Setup and smoke test — *no cost*

Prove the thing runs before testing what it does.

- [ ] **App launches from the icon**
  Double-click `Compass.command`. On a fresh Mac, right-click → Open the first time.
  *Pass: browser opens to Compass; Terminal window stays open.*

- [ ] **API key is recognised**
  Read the Terminal window as it starts.
  *Pass: prints `✓ API key loaded (…abc123)`, not a warning.*

- [ ] **You relaunched after updating**
  If you pulled changes, quit the Terminal window (`Ctrl-C`) and launch again.
  *Pass: no grey `ImportError` box. Streamlit keeps shared code loaded from startup, so
  updating a running app leaves it half-reloaded. Refreshing the browser won't fix it.*

- [ ] **All eleven pages open**
  Click every sidebar item: Home, Math, Science, English, History, Choice Topics, Life
  Skills, Landon's Travels, Activity Log, Compliance, Student Profile.
  *Pass: every page renders, no red error boxes.*

- [ ] **Student details are right**
  Sidebar → **✏️ Edit his profile** → the Student Profile page. If it says "Student",
  correct the name, grade, and age, and Save; add his real interests one at a time below
  (each becomes its own removable chip).
  *Pass: sidebar and Home immediately show his real name and grade. The "What each agent
  would plan next" cards on Home pick up his interests too — that's the same field feeding
  every lesson, not just cosmetic.*

- [ ] **App survives without a key**
  Quit, rename `.env` to `.env.off`, relaunch. The launcher will ask for a key in the
  Terminal — **press Enter to skip it**.
  *Pass: it says it's running without a key, then a red banner appears on the four agent
  pages and on Life Skills → Plan a session. Compliance, Activity Log, Math → The graph,
  Choice Topics and the Life Skills checklist all still work. Rename the file back after.*

- [ ] **The key prompt writes the file for you**
  With no `.env` present, relaunch and paste your key at the Terminal prompt instead of
  skipping.
  *Pass: reports `Saved to .env`, the file now exists, and you aren't asked again next launch.*

- [ ] **Themes switch, and stay separate**
  Sidebar → **🎨 Look**. Try all five (Comic Book, Arcade, Tech Tree, High-Vis, Blueprint).
  Then set a parent PIN, switch to student view, and pick a different one there.
  *Pass: each page repaints instantly — expanders, warning banners, the metric tiles on
  Home and Compliance. His pick and yours don't affect each other; switching between
  parent and student view always shows the right one back.*

- [ ] **The page background never actually changes**
  Flip between all five themes on any page.
  *Pass: the background and the sidebar stay the exact same warm off-white throughout —
  only the cards, tiles, and banners on top of it change colour. If the page itself
  shifts colour when you switch themes, that's a bug — the backdrop is supposed to be
  fixed.*

- [ ] **Primary buttons are readable on every theme**
  Look at "Generate lesson" (or any primary button) on all five themes.
  *Pass: the button text is clearly legible against its background on every theme —
  white text on Arcade and Blueprint, dark text on the other three. If any button's
  text nearly disappears into its background, that's a real accessibility bug.*

- [ ] **The sidebar scrolls on a short window**
  Shrink the browser window's height until the sidebar's content is clearly taller than
  it. Scroll with the mouse over the sidebar.
  *Pass: the sidebar scrolls independently of the page and reaches the mode control and
  the Look picker at the bottom. If nothing scrolls no matter where you try, that's the
  bug this item exists to catch — say so rather than just resizing back to a taller
  window and moving on.*

---

## 2 · Each agent generates — *≈ $1.10*

One lesson from each. Math first — cheapest and fastest.

- [ ] **Math generates**
  Math → Plan a lesson → Generate. About 85 seconds.
  *Pass: lesson with activities, an assessment, and mastery criteria specific enough to grade.*

- [ ] **Add the book he is reading**
  English → Books → title, author, page count. English refuses to run without one.
  *Pass: book shows as "reading"; the block message disappears.*

- [ ] **English generates off that book**
  English → Plan a lesson → Generate.
  *Pass: the lesson quotes or refers to that specific book, not a generic passage.*

- [ ] **Science generates with a location**
  Science → type somewhere real you'll actually be → Generate. ~3.5 minutes.
  *Pass: names real specifics of that place; includes a hands-on or field activity.*

- [ ] **History generates with a location**
  History → same or another location → Generate. Up to 6 minutes; slowest agent.
  *Pass: a genuine local connection, or an honest fallback to the least-covered era.*

- [ ] **Every lesson shows subject credits**
  Scroll to the bottom of each generated lesson.
  *Pass: each credit names a subject, minutes, and which part of the lesson earns it.*

- [ ] **Every lesson includes a quiz**
  As the parent, expand "Quiz answer key" under any generated lesson.
  *Pass: three to five questions, four choices each, exactly one marked correct, an
  explanation on each.*

---

## 3 · The full loop — *no cost*

Generate → teach → log → dashboard. The path you'll walk every day.

- [ ] **Log a generated lesson**
  Use "Log this as completed" under any lesson. Set the date and save.
  *Pass: success message; lesson shows "completed" in Activity Log → Generated lessons.*

- [ ] ⚠ **CRITICAL — Edited minutes are respected**
  Log one lesson with minutes changed, say 60 down to 35.
  *Pass: Activity Log shows 35, not 60. What you type is what's recorded.*

- [ ] ⚠ **CRITICAL — Edited credits are respected**
  Before saving, zero out one secondary subject credit.
  *Pass: that subject gets no hours from this activity on Compliance.*

- [ ] **Hours reach the dashboard**
  Open Compliance; check total hours and the subject table.
  *Pass: total rose by the minutes you logged; credited subjects show hours.*

- [ ] **Manual logging works**
  Activity Log → Log something manually. A museum, a hike, a documentary.
  *Pass: appears in the record with the credits you chose.*

- [ ] **Deleting corrects the record**
  Delete a test activity from the Activity Log.
  *Pass: Compliance total drops by exactly that activity's minutes.*

- [ ] ⚠ **CRITICAL — Taking the quiz never shows the answer early**
  Set a PIN, switch to student view, open the Math quiz. Before answering anything,
  view page source or check the DOM (right-click → Inspect) for the questions.
  *Pass: no correct answer is findable anywhere on the page before you submit.*

- [ ] **A passing quiz score auto-records Math mastery**
  As the student, answer every question right and submit. Then unlock the parent view
  and check Math → Record mastery for that skill — do this *without* touching the
  Record mastery form yourself first.
  *Pass: the skill already shows "mastered", with a note that it was auto-graded.*

- [ ] **A failing quiz score does not touch mastery**
  Take a different lesson's quiz and get most of it wrong.
  *Pass: score and pass/fail message are correct; the skill's mastery status is unchanged.*

---

## 4 · Guardrails — *no cost*

Deliberate refusals. These should block, and tell you why.

- [ ] **English blocks with no current book**
  Mark the current book "Finished", then go to Plan a lesson.
  *Pass: refuses and explains, rather than inventing a generic passage. Mark "Resume" after.*

- [ ] **Math blocks a locked skill**
  Math → Record mastery → pick something advanced like the Pythagorean Theorem.
  *Pass: shows it's locked, names missing prerequisites, gives the teaching order to reach it.*

- [ ] **Math finishes what he started**
  Mark any available skill "In progress". Return to Plan a lesson.
  *Pass: offers that same skill again rather than unlocking something new.*

- [ ] **Agent adjustments are visible**
  Watch for small ⚠ notes above a generated lesson.
  *Pass: if the app corrected an over-claimed credit, it says so rather than fixing it silently.*

- [ ] ⚠ **CRITICAL — Credits can't exceed double the lesson**
  On each generated lesson, add up the subject credits.
  *Pass: the total is at most twice the lesson length — 120 minutes of credit on a 60-minute
  lesson, never more. If the app scaled something back, it says so above the lesson.*

---

## 5 · His real data — *no cost*

The highest-value hour in this whole plan, and it costs nothing.

- [ ] ⚠ **CRITICAL — Record his actual math mastery**
  Math → Record mastery. Mark everything he genuinely knows. Twenty minutes.
  *Pass: The graph shows a realistic mastered count; next topic is sensible for him.*

- [ ] **Mastery changes what's offered**
  After recording, return to Plan a lesson.
  *Pass: proposed skill moved on from integer operations to something at his level.*

- [ ] **Vocabulary arrives from English lessons**
  English → Vocabulary after generating a lesson.
  *Pass: words from the lesson are in the deck with definitions.*

- [ ] **Vocabulary review behaves**
  On a due word press "Knew it"; on another press "Missed".
  *Pass: "Knew it" moves the box up and pushes the date out; "Missed" drops to box 1, due tomorrow.*

- [ ] ⚠ **CRITICAL — He adds his own Tier 3 topics**
  Sit him down at Choice Topics; let him add three or four himself. Approve them.
  *Pass: they're his ideas, not yours. This is the point of the tier.*

- [ ] **Choice hours log**
  Choice Topics → Log time on an approved topic.
  *Pass: hours appear under Tier 3 — His choice.*

- [ ] **Life skills checklist is yours**
  Life Skills → seed the starter list, delete what you don't care about, add what you do.
  *Pass: the list reflects your family, not the default.*

- [ ] **Life skill hours log**
  Life Skills → Log time → tick "Mark this skill complete".
  *Pass: hours land under Core life skills; Health or Occupational Education gains coverage.*

- [ ] **A life-skill plan is worth having** — *≈ $0.20*
  Life Skills → Plan a session. Pick something hands-on and write a plan.
  *Pass: you could run it on Saturday without further thought. Real tools, real amounts,
  a step where it tells you to shut up and let him struggle. If it reads like a lecture
  outline, that's a finding.*

- [ ] ⚠ **CRITICAL — It plans, it doesn't choose**
  Read the plan for anything it says about *which* skill he should do.
  *Pass: nothing. It should never propose a different skill or claim he needs a
  prerequisite first. That's your call and it isn't invited.*

- [ ] **Plans stay on your side of the PIN**
  With a PIN set, switch to student view and open Home and Life Skills.
  *Pass: no teaching plan anywhere. "Demonstrate once then stay quiet" is not his to read.*

- [ ] **The plan is saved, not re-bought**
  Leave the page, come back, reselect the same skill.
  *Pass: the plan is still there without spending anything.*

---

## 6 · The compliance record — *no cost*

The part a district could ask about. Worth being fussy here.

- [ ] ⚠ **CRITICAL — Understand the counting rule**
  Compliance → expand "How these numbers are counted". Compare total hours to the subject table.
  *Pass: per-subject minutes add to MORE than total hours, and you understand why that's correct.*

- [ ] **All eleven subjects are tracked**
  Look at the subject table.
  *Pass: eleven rows; ones with no instruction are flagged and named in the warning.*

- [ ] **Tier breakdown looks sane**
  Check "Hours by tier".
  *Pass: tier hours add up to your total; the split matches how the week actually went.*

- [ ] **Tier 3 guideline warns without blocking**
  Log a deliberately large choice session so Tier 3 exceeds 20% of a small record.
  *Pass: a warning appears, hours still count in full, nothing is prevented.*

- [ ] **Date range filters**
  Narrow From / To to a single logged day.
  *Pass: only that day's hours are counted.*

- [ ] **CSV export opens**
  Compliance → Download the instructional record. Open in Numbers or Excel.
  *Pass: one row per activity, a column per credited subject, readable by someone who isn't you.*

- [ ] **Declaration of Intent banner and countdown**
  Home page, parent view. Also check the first-day-of-school countdown at the top,
  visible in both parent and student view.
  *Pass: a due-date countdown referencing RCW 28A.200.010; a separate plain countdown to
  the first day of school shows on Home in both views.*

- [ ] **Marking the Declaration filed, and undoing it**
  Press "Mark as filed" on the Home banner. Then Compliance → Declaration of Intent →
  expand the details → "Undo — not actually filed".
  *Pass: banner turns into a green "filed on [today]" message; Undo reverts it to the
  countdown/overdue state.*

- [ ] ⚠ **CRITICAL — A missed deadline stays flagged, it doesn't quietly reset**
  Set "Filing deadline (MM-DD)" to yesterday's date, don't mark it filed, reload the page.
  *Pass: the banner reads as overdue for that date — it must NOT roll forward to a calm
  365-day countdown for next year just because the date passed.*

---

## 7 · Backups — *no cost*

Test the restore, not just the backup. An untested restore is not a backup.

- [ ] **A daily snapshot exists**
  Compliance → Backups.
  *Pass: "Last backed up" says Today.*

- [ ] **Back up on demand works**
  Press "Back up now".
  *Pass: snapshot count goes up by one.*

- [ ] **A snapshot downloads**
  Expand "All snapshots" → Download on any row.
  *Pass: a `.db` file lands in Downloads.*

- [ ] ⚠ **CRITICAL — Restore actually restores**
  Log a throwaway activity called TEST. Then restore a snapshot from before it.
  *Pass: TEST is gone from the Activity Log; the app keeps working normally.*

- [ ] **A mistaken restore is undoable**
  After that restore, look at the snapshot list.
  *Pass: a new "prerestore" snapshot holds the state you just replaced.*

- [ ] ⚠ **CRITICAL — Backups live somewhere else too**
  Drag the `backups` folder into iCloud or Dropbox.
  *Pass: a copy exists off this laptop. The only step that survives the drive failing.*

---

## 8 · Cost tracking — *no cost*

Check the app's numbers against the real bill once, early.

- [ ] **Spend is reported**
  Compliance → What the agents cost to run.
  *Pass: shows total spend, cost per lesson, per-agent breakdown.*

- [ ] **Per-agent costs look right**
  Compare against roughly $0.17 Math, $0.20 English, $0.27 Science, $0.42 History.
  *Pass: same ballpark.*

- [ ] **Token consumption is visible**
  Same page, the per-agent table.
  *Pass: input, output, and cached tokens plus web searches, broken out per agent. History
  should show the most of everything.*

- [ ] **Math and English now show web searches too**
  Same table — they used to show zero.
  *Pass: a small number (usually 0-2) per lesson, not the 3-6 Science and History run.
  That's the video lookup, not a location search — Math and English still don't ground
  lessons in the general web.*

- [ ] ⚠ **CRITICAL — Cross-check the real bill**
  platform.claude.com → Usage. Compare to what the app reports.
  *Pass: close enough that you trust the in-app number. It estimates a real bill; it isn't the bill.*

- [ ] **A spend limit is set**
  platform.claude.com → Settings → Limits.
  *Pass: a monthly cap exists. $20 is plenty.*

---

## 9 · Judgement calls — *no cost*

The tests only you can run. Slow down here — this decides whether you trust it in September.

- [ ] ⚠ **CRITICAL — Would you actually teach these lessons?**
  Reread the four lessons as a teacher, not a tester.
  *Pass: you'd teach them roughly as written. If they read like filler, that's the finding that matters most.*

- [ ] **Pitched right for him**
  Read the `overview`, `learning_objectives`, and activity instructions of a generated
  lesson as if you were him, not as the parent reviewing it.
  *Pass: short, plain sentences, second person, casual — not textbook prose. Stretching
  but not defeating; not written down to him either. If it reads like something written
  for you to approve rather than for him to read, that's the finding.*

- [ ] ⚠ **CRITICAL — Credit justifications are honest**
  For each secondary credit, find the activity it names. Does it produce a real artifact?
  *Pass: a 250-word argument earns writing; a two-sentence caption does not. Flag anything generous.*

- [ ] **Location grounding is real**
  Generate Science or History for somewhere you know well.
  *Pass: real species, real dates, real place names — not plausible-sounding filler.*

- [ ] ⚠ **CRITICAL — A suggested video, when there is one, is real and on-topic**
  Generate a few lessons across different agents (as the parent, before he ever sees them).
  When **▶️ Suggested video** appears, open the link yourself before he does.
  *Pass: the link actually opens, and the video genuinely matches today's topic. If a
  link is dead, wrong, or the section never appears at all across several lessons — the
  second is normal and not a bug, since a good video isn't always out there — note which.
  What would be a real problem: a link that doesn't work or doesn't match. Since he'll see
  this one directly, this check matters more than most.*

- [ ] **The suggested video is from a channel you'd actually recognize**
  Same generated lessons — check the channel named under the video, per subject: Khan
  Academy / Math Antics / Mashup Math for math; those plus Crash Course, SciShow, Bozeman
  Science, National Geographic for science; Khan Academy / Crash Course / TED-Ed for
  English and history.
  *Pass: the channel is one of that subject's approved names, not something unfamiliar.
  If you want a different channel trusted, edit `TRUSTED_CHANNELS` in
  `compass/agents/video.py` — this list is yours, not fixed.*

- [ ] **The video suggestion reaches student view too**
  With a PIN set and a lesson that has a suggested video, switch to student view and open
  the same lesson.
  *Pass: unlike the answer key, the video section is there for him too — title, channel,
  and link all visible. The parent-only line about YouTube's own recommendations should
  NOT appear in his view.*

- [ ] **Math assessments are gradeable**
  Read a math lesson's mastery criteria.
  *Pass: gradeable without judgement calls; you know what unlocks the next skill.*

- [ ] **Science branches are worth following**
  Science → The web. Read the open branches.
  *Pass: genuinely different directions, not four rewordings of the same idea.*

- [ ] **You can steer the web**
  Science → Plan a lesson → *Which thread to pull*. Pick a branch other than the default.
  *Pass: the proposed topic is the one you picked.*

- [ ] **Dismissing prunes without collateral damage**
  Science → The web → Dismiss a branch you'd never teach.
  *Pass: it's gone; anything that branched off it is still listed.*

- [ ] **A new direction doesn't wipe the web**
  Science → Plan a lesson → type something unrelated into the seed topic box, generate,
  then reopen The web.
  *Pass: your earlier open branches are still there.*

---

## 10 · A real week — *≈ $2–4*

The only test that answers the actual question: does this fit your mornings?

- [ ] ⚠ **CRITICAL — Run five consecutive school days**
  Generate the night before, teach, log the same day, record mastery when he's assessed.
  *Pass: five days without fighting the app.*

- [ ] **The daily loop fits**
  Notice how long your part actually takes.
  *Pass: around fifteen minutes of your attention. If it's an hour, something needs changing.*

- [ ] **He can use it himself**
  Have him open it, read his lesson, add a Tier 3 topic unassisted.
  *Pass: he manages without you narrating.*

- [ ] ⚠ **CRITICAL — The record matches the week**
  Friday: open Compliance and compare against what really happened.
  *Pass: the hours are recognisably your week. If inflated, fix the logging habit now.*

- [ ] **Data survives a restart**
  Quit and relaunch a few times over the week.
  *Pass: everything still there, every time.*

---

## If a test fails

Most failures fall into three buckets:

**It's a deliberate refusal.** English with no book, Math with a locked skill. The message
explains what to fix. Not a bug.

**It's a judgement call going the wrong way.** An inflated credit, a lesson pitched wrong,
weak location grounding. These are prompt problems, fixable — write down the exact lesson
and what was wrong with it.

**It's genuinely broken.** Note what you did, what you expected, and what happened instead.
The Terminal window usually has the real error in it.
