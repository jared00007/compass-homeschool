"""SQLite storage layer.

One `Database` object wraps a connection and exposes typed-ish repository
methods. Every method that writes commits immediately — this is a single-family,
single-writer app, so there is no benefit to holding transactions open across UI
interactions.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Sequence

from compass import config

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

# The full life-skills master catalog: (category, title, credit_subject,
# description, materials, active). Written, not agent-generated -- plain,
# casual, kid-facing, matching how Tier 1 lesson content is written.
# `materials` is the short "what you'll need" list the card shows under the
# story. `active` is only a *default* for a brand-new checklist -- the
# original 15 start unlocked so a fresh family isn't staring at an empty
# page, the rest start locked so a year's worth of content doesn't land on
# the student all at once. A parent can flip either one anytime.
#
# Lives at module level (rather than inline in `seed_life_skills`) so
# `_backfill_life_skill_content`/`_backfill_life_skill_catalog` can share the
# same source of truth -- a checklist seeded before this text (or before the
# catalog grew) needs the same content, not a second copy that can drift.
LIFE_SKILL_CATALOG: Sequence[tuple[str, str, str, str, str, bool]] = (
    ("Money", "Build and follow a monthly budget", "occupational_education",
     "Figure out what money's coming in and what's going out, then make a "
     "simple plan so you don't run out before the month does. Set some "
     "categories, guess your spending, then check back and see how close "
     "you got.",
     "pencil and paper (or a spreadsheet), one real month of numbers", True),
    ("Money", "Open and reconcile a bank account", "occupational_education",
     "You'll open a real account (a parent's on it too) and learn to check "
     "it against your own math -- what you think you have vs. what the "
     "bank says you have. Catching the difference is the actual skill.",
     "a parent, ID, ~$20 to open with", True),
    ("Money", "Understand a paycheck: gross, net, withholding", "occupational_education",
     "A paycheck has two numbers that matter: what you earned and what you "
     "actually get to keep. Work through a sample stub and figure out "
     "where the rest of it goes.",
     "a sample pay stub, a calculator", True),
    ("Cooking", "Plan and cook a full meal for the family", "health",
     "Pick a meal, shop for it (or use what's in the kitchen), and cook "
     "the whole thing start to finish -- timing included, so everything's "
     "ready at the same time.",
     "a recipe, a grocery run, about 90 minutes", True),
    ("Cooking", "Read nutrition labels and plan a balanced week", "health",
     "Nutrition labels look like a wall of numbers until you know which "
     "three or four actually matter. Use them to plan a week of meals "
     "that aren't just convenient -- that are actually decent for you.",
     "a few labels from the pantry, a week's meal list", True),
    ("Cooking", "Kitchen safety and safe food handling", "health",
     "The stuff that keeps you from getting sick or hurt: washing hands "
     "right, not cross-contaminating raw meat, knowing when food's gone "
     "bad, and using a knife without losing a finger.",
     "a kitchen, a parent watching once", True),
    ("Vehicle", "Check and top off oil, coolant, washer fluid", "occupational_education",
     "The three fluids you should check before anyone tells you your car's "
     "in trouble. Takes ten minutes and can save you a much worse day "
     "later.",
     "the owner's manual, 10 minutes, the car", True),
    ("Vehicle", "Check tire pressure and change a tire", "occupational_education",
     "Two skills in one: reading a tire gauge so you know when a tire's "
     "actually low, and swapping one out on the side of the road if you "
     "have to.",
     "a tire gauge, the spare, the jack and lug wrench", True),
    ("Vehicle", "Jump-start a vehicle safely", "occupational_education",
     "A dead battery isn't a big deal if you know which cable goes where, "
     "and in what order. Get it wrong and you can actually fry something "
     "-- that's why the order matters.",
     "jumper cables, a second running car", True),
    ("Communication", "Write a clear, polite email to an adult", "language",
     "Emails to teachers, coaches, or businesses have their own rules -- "
     "not too casual, not stiff either, and always saying exactly what "
     "you need in the first two lines.",
     "a real email to send, 15 minutes", True),
    ("Communication", "Make a phone call to schedule an appointment", "language",
     "An actual phone call, not a text. Practice saying who you are, what "
     "you need, and getting a real time booked -- without freezing up.",
     "a real place to call, your calendar", True),
    ("Communication", "Introduce yourself and shake hands", "health",
     "Look someone in the eye, say your name clearly, and shake hands "
     "like you mean it. Small thing, but it's the first impression every "
     "single time.",
     "a person to practice on", True),
    ("Home", "Do laundry start to finish", "occupational_education",
     "Sorting, washing, drying, folding -- the whole loop, no help. "
     "Including not turning anyone's white shirt pink.",
     "a full hamper, the washer and dryer", True),
    ("Home", "Basic first aid and when to call for help", "health",
     "Cuts, burns, sprains -- what you can handle yourself, and where "
     "the line is where you stop and call 911 or a parent instead.",
     "a first aid kit", True),
    ("Home", "Read a map and navigate without GPS", "social_studies",
     "Your phone dies, or you're somewhere with no signal -- can you "
     "still get where you're going with an actual map? That's the whole "
     "skill.",
     "a paper map or atlas, a real trip to plan", True),
    # -- unlocked later, at the parent's pace --------------------------------
    ("Money", "Compare prices and figure out the better deal", "occupational_education",
     "Bigger isn't always cheaper. Check the unit price (price per ounce, "
     "per item) so you can actually tell which one's the better deal, not "
     "just which one looks like it.",
     "a store receipt or two products to compare", False),
    ("Money", "Understand credit, debit, and what interest costs you", "occupational_education",
     "The difference between spending money you have and money you're "
     "borrowing, and why a credit card that isn't paid off costs you extra "
     "every month it sits there.",
     "a sample statement or two", False),
    ("Cooking", "Grocery shop on a set budget", "health",
     "Given a list and a dollar amount, get everything on it without going "
     "over. Real math, done in a real store, under real pressure.",
     "a grocery list, a set budget, a store trip", False),
    ("Cooking", "Use the oven and stovetop safely without supervision", "health",
     "Preheating, timers, not walking away from something on the burner, "
     "and what to do if something starts smoking. The stuff that turns "
     "'can microwave a burrito' into 'can actually cook.'",
     "the kitchen, something simple to bake or saute", False),
    ("Vehicle", "Read the dashboard warning lights", "occupational_education",
     "Which lights mean 'pull over now,' which mean 'get it looked at this "
     "week,' and which are just a reminder. Guessing wrong in either "
     "direction is expensive.",
     "the owner's manual (has a full light key), the car", False),
    ("Vehicle", "Fill the tank and check tire tread", "occupational_education",
     "Pumping your own gas, and a fast way to tell if a tire's actually "
     "worn out (the penny test) instead of just eyeballing it.",
     "a car needing gas, a penny", False),
    ("Communication", "Handle a disagreement without it becoming a fight", "health",
     "Say what's actually bothering you without yelling, and actually "
     "listen to the other side before responding. Harder than it sounds, "
     "and worth practicing on purpose.",
     "a real (small) disagreement to work through", False),
    ("Communication", "Explain something you know to someone who doesn't", "language",
     "Pick something you're actually good at and teach it to someone in "
     "five minutes, out loud, without notes. Shows whether you really "
     "understand it or just recognize it.",
     "a topic you know well, a listener", False),
    ("Home", "Basic repairs: tighten, patch, and use the right tool", "occupational_education",
     "A wobbly hinge, a loose screw, a small hole in drywall -- the stuff "
     "that doesn't need a professional, just a screwdriver and knowing "
     "which one.",
     "a screwdriver set, whatever around the house actually needs fixing", False),
    ("Home", "Sew a button and patch a small tear", "occupational_education",
     "The two most common clothing repairs, both doable by hand in under "
     "ten minutes once you know the moves.",
     "needle, thread, a button or torn item", False),
    ("Digital Life", "Lock down your privacy settings", "occupational_education",
     "Go through what's actually public on your accounts vs. what you "
     "think is private, and fix the gap. Most of it defaults to more open "
     "than people realize.",
     "your actual accounts, a parent to check the settings with", False),
    ("Digital Life", "Spot a scam or phishing attempt", "occupational_education",
     "The red flags in a fake text, email, or DM asking for money, a "
     "password, or a click -- and what to do instead of clicking.",
     "a few real examples (a parent likely has some)", False),
    ("Digital Life", "Manage your own passwords safely", "occupational_education",
     "Not reusing the same password everywhere, and using a password "
     "manager instead of memorizing (or writing down) two dozen of them.",
     "your accounts, a password manager app", False),
    # -- the rest of the catalog: 150+ total, so a full school year has
    # somewhere to go. All locked by default -- same reasoning as above.
    ("Money", "Set a savings goal and actually hit it", "occupational_education",
     "Pick something real you want, figure out how much it costs, and save "
     "toward it in chunks instead of just wishing for it. The tracking is "
     "the skill, not the wanting.",
     "a savings goal, a place to track progress (jar, app, spreadsheet)", False),
    ("Money", "Split a bill fairly", "occupational_education",
     "Figure out who owes what when a group buys something together -- "
     "tip, tax, and uneven orders included. Doing it in your head, not "
     "just hoping it works out.",
     "a real receipt, a calculator", False),
    ("Money", "Understand taxes on a paycheck", "occupational_education",
     "Where federal, state, and payroll tax actually go, and why your "
     "first paycheck is smaller than you expected.",
     "a sample pay stub", False),
    ("Money", "Negotiate a price", "occupational_education",
     "Ask for a better price on something real -- a yard sale item, a "
     "used bike, a phone repair -- and actually go through with it "
     "instead of just paying the sticker price.",
     "something real to negotiate on", False),
    ("Money", "Spot a bad financial deal", "occupational_education",
     "Payday loans, 'buy now pay later,' extended warranties -- the "
     "offers that sound convenient but cost way more than they're worth "
     "once you do the math.",
     "a real ad or offer to break down", False),
    ("Money", "Read a receipt and catch a mistake", "occupational_education",
     "Check a real receipt against what you actually bought. Overcharges "
     "and double-scans happen more than you'd think, and nobody catches "
     "them if you don't look.",
     "a store receipt", False),
    ("Money", "Understand insurance basics", "occupational_education",
     "What a deductible and a premium actually are, using a real example "
     "-- car, health, or renters insurance, whichever's easiest to get a "
     "sample of.",
     "a sample insurance policy or quote", False),
    ("Money", "Keep savings separate from spending money", "occupational_education",
     "Keep 'money I'm saving' physically apart from 'money I might "
     "spend' so it doesn't quietly disappear. The separation is the "
     "whole trick.",
     "a second account or a labeled envelope/jar", False),
    ("Money", "Understand what a subscription actually costs over a year", "occupational_education",
     "Add up what a $10/month app really costs across 12 months, and "
     "decide honestly whether it's worth it once you see the real "
     "number.",
     "a list of your own or the family's subscriptions", False),
    ("Money", "Donate or give away something thoughtfully", "occupational_education",
     "Pick a cause or a person, decide how much time or money makes "
     "sense, and actually follow through -- giving well is its own "
     "skill, not just an impulse.",
     "something to give, somewhere to give it", False),
    ("Cooking", "Bake something from scratch", "health",
     "No box mix -- measure your own flour, sugar, and leavening, and "
     "get the ratios right. Baking punishes guessing more than cooking "
     "does.",
     "a from-scratch recipe, real baking ingredients", False),
    ("Cooking", "Cook for a dietary restriction", "health",
     "Make a full meal that's actually gluten-free, vegetarian, or "
     "allergy-safe for someone real -- not just skipping the obvious "
     "thing, but knowing what else has it hidden in it.",
     "a recipe, someone with a real restriction to cook for", False),
    ("Cooking", "Use a knife correctly for real prep", "health",
     "The claw grip, a rocking chop, and enough control to dice an "
     "onion without a single close call.",
     "a chef's knife, a cutting board, an onion or two", False),
    ("Cooking", "Meal prep for the week", "health",
     "Cook multiple servings in one session and portion them out, so "
     "the rest of the week doesn't depend on cooking from scratch every "
     "night.",
     "a recipe that scales, containers", False),
    ("Cooking", "Grill something safely", "health",
     "Light it, control the heat, and cook meat to an actual safe "
     "temperature instead of guessing by how it looks.",
     "a grill, a meat thermometer, something to grill", False),
    ("Cooking", "Make a proper cup of something hot", "health",
     "Coffee, tea, or hot chocolate done right instead of however's "
     "fastest -- ratios, temperature, and timing all actually matter.",
     "coffee/tea, a kettle or maker", False),
    ("Cooking", "Understand food expiration vs. 'best by'", "health",
     "Which dates actually mean 'don't eat this' and which just mean "
     "'not at its best' -- so the fridge doesn't get emptied over "
     "nothing, or kept full of something risky.",
     "a few items from your own fridge/pantry", False),
    ("Cooking", "Host a small meal for guests", "health",
     "Plan the menu, time it so everything's ready together, and "
     "actually serve people -- the hosting part is as much a skill as "
     "the cooking.",
     "a menu, real guests (even just family)", False),
    ("Cooking", "Preserve or store food properly", "health",
     "Freezing, proper fridge storage, or a simple canning/pickling "
     "project -- keeping food good longer instead of tossing it.",
     "food to preserve, containers or jars", False),
    ("Cooking", "Cook a meal on a camp stove or over a fire", "health",
     "No kitchen -- just a burner or open flame, and a meal that "
     "actually works with that limitation.",
     "a camp stove or fire pit, simple ingredients", False),
    ("Vehicle", "Parallel park", "occupational_education",
     "The maneuver everyone claims to hate because nobody actually "
     "practices it. Cones or real spots, doesn't matter -- just get it "
     "consistent.",
     "a car, a space to practice (cones optional)", False),
    ("Vehicle", "Understand your car insurance and what it covers", "occupational_education",
     "What's actually covered if something goes wrong, what your "
     "deductible means in a real dollar amount, and who to call first.",
     "the family's insurance card/policy", False),
    ("Vehicle", "Know what to do after a minor accident", "occupational_education",
     "The actual steps -- safety first, information exchange, photos, "
     "who you call -- worked through before you ever need them for "
     "real.",
     "nothing but a walkthrough of the steps", False),
    ("Vehicle", "Wash and detail a car properly", "occupational_education",
     "Not just a quick hose-down -- actually getting it clean, inside "
     "and out, without leaving swirl marks or missing the wheels.",
     "soap, sponge/mitt, a hose or car wash", False),
    ("Vehicle", "Understand basic dashboard maintenance reminders", "occupational_education",
     "Oil change intervals, mileage-based service, and how to actually "
     "track when the next one's due instead of waiting for something "
     "to break.",
     "the car's manual or maintenance record", False),
    ("Vehicle", "Load and secure cargo safely", "occupational_education",
     "Tie down or properly load something in a trunk or truck bed so "
     "it doesn't shift, fall out, or become a hazard at speed.",
     "cargo to move, straps or rope", False),
    ("Vehicle", "Drive safely in bad weather", "occupational_education",
     "What actually changes about how you drive in rain, snow, or ice "
     "-- following distance, braking, and when to just not go.",
     "the conversation, and real practice when conditions allow, with a parent", False),
    ("Vehicle", "Understand what 'totaled' means and basic car value", "occupational_education",
     "How an insurance company decides a car isn't worth fixing, and "
     "roughly how to tell what a car's actually worth before buying or "
     "selling one.",
     "a real listing or two to look at values", False),
    ("Communication", "Write a resume", "language",
     "Even with no job history yet -- school, volunteering, and life "
     "skills earned right here all count. The format and honesty both "
     "matter.",
     "a computer, a list of your own experience", False),
    ("Communication", "Handle a job interview", "language",
     "Answer real questions out loud, without reading off notes, for "
     "something you'd actually apply for.",
     "a parent or adult to run a practice interview", False),
    ("Communication", "Give constructive feedback without being harsh", "language",
     "Tell someone something isn't working without making them feel "
     "attacked -- specific, kind, and actually useful instead of vague "
     "or brutal.",
     "a real situation to give feedback on", False),
    ("Communication", "Apologize for real, not just say sorry", "health",
     "Own what you actually did, without an excuse attached, and mean "
     "it. The difference between a real apology and a reflex is "
     "obvious to everyone but the person saying it.",
     "a real moment when it's needed", False),
    ("Communication", "Ask for help when you actually need it", "health",
     "Say out loud that you're stuck, specifically, instead of quietly "
     "struggling or pretending you've got it. Harder than it sounds "
     "for a lot of people.",
     "a real situation where you're stuck", False),
    ("Communication", "Speak up in a group without waiting to be asked", "language",
     "Say your actual opinion in a group setting -- family, class, "
     "team -- instead of just going along with whatever's already "
     "been said.",
     "a real group conversation", False),
    ("Communication", "Write a thank-you note", "language",
     "A real one, specific to what you're thanking someone for, not a "
     "generic line. Handwritten if you can manage it.",
     "paper and a pen, a real reason to write one", False),
    ("Communication", "De-escalate a tense conversation", "health",
     "Notice when a conversation is heating up and actually bring the "
     "temperature down instead of adding to it.",
     "nothing but the moment it's needed", False),
    ("Home", "Deep clean a room start to finish", "occupational_education",
     "Not a quick tidy -- actually clean, including the parts nobody "
     "checks: baseboards, under furniture, behind doors.",
     "cleaning supplies, a room that needs it", False),
    ("Home", "Plan and pack for a trip", "occupational_education",
     "Make a real packing list for a real trip and actually stick to "
     "it -- nothing forgotten, nothing overpacked.",
     "a real trip to pack for", False),
    ("Home", "Organize a closet or drawer system that actually holds", "occupational_education",
     "Not a one-time cleanup -- a system that's still working a month "
     "later, because the setup made it easy to keep up.",
     "a closet or drawer, storage bins if needed", False),
    ("Home", "Take care of a pet's full needs for a week", "occupational_education",
     "Feeding, walking, cleanup, and attention, solo, for a real week "
     "-- not just the fun parts.",
     "a real pet (family's or a neighbor's), a full week", False),
    ("Home", "Water and care for houseplants or a garden bed", "occupational_education",
     "Keep something alive on purpose for a season -- knowing how much "
     "water and light it actually needs, not guessing.",
     "a plant or garden bed", False),
    ("Home", "Set up and troubleshoot a piece of home tech", "occupational_education",
     "A new WiFi router, smart device, or streaming setup -- installed "
     "and working, including fixing it when it doesn't connect the "
     "first time.",
     "a real device to set up", False),
    ("Home", "Change a light fixture or fix a simple electrical issue", "occupational_education",
     "Swap a light fixture, replace an outlet cover, or reset a "
     "breaker -- the safe, simple stuff that doesn't need an "
     "electrician, with power off first.",
     "a screwdriver, a parent supervising, power off at the breaker", False),
    ("Home", "Plan and cook for a family gathering or holiday", "occupational_education",
     "Take real ownership of one dish or the whole meal for an actual "
     "gathering, including the planning and timing, not just the "
     "cooking.",
     "a real gathering to cook for", False),
    ("Home", "Keep a home maintenance calendar", "occupational_education",
     "Track the stuff that needs doing on a schedule -- furnace "
     "filters, smoke detector batteries, gutter cleaning -- so it's "
     "not forgotten until something breaks.",
     "a calendar or planner, the house's actual maintenance needs", False),
    ("Home", "Move furniture safely without hurting yourself or the floor", "occupational_education",
     "Proper lifting technique, and actually protecting the floor -- "
     "sliders, blankets, or just enough people to carry it right.",
     "furniture to move, a second person if it's heavy", False),
    ("Digital Life", "Back up your important files and photos", "occupational_education",
     "Actually have a second copy somewhere -- cloud or external drive "
     "-- so losing a phone or laptop doesn't mean losing everything on "
     "it.",
     "your device, a cloud account or external drive", False),
    ("Digital Life", "Understand what you're agreeing to before you click accept", "occupational_education",
     "Skim a real terms-of-service or permissions request and "
     "understand roughly what it's actually asking for, instead of "
     "clicking through blind.",
     "a real app install or account signup", False),
    ("Digital Life", "Manage screen time on purpose, not by accident", "occupational_education",
     "Set your own limits on something and actually stick to them for "
     "a week, instead of just noticing afterward how much time went "
     "by.",
     "a phone or app with screen-time tracking", False),
    ("Digital Life", "Build something simple with code", "occupational_education",
     "A basic website, a small script, or a simple game -- something "
     "that actually runs, built from real instructions, not just "
     "copy-pasted.",
     "a computer, a beginner coding tutorial", False),
    ("Digital Life", "Understand how your data gets used online", "occupational_education",
     "What a company actually does with your searches, location, and "
     "purchase history -- and why 'free' apps aren't really free.",
     "a real app's privacy policy or settings page", False),
    ("Digital Life", "Manage a group chat or online community respectfully", "occupational_education",
     "Handle a disagreement, a rule-breaker, or just normal group "
     "dynamics in a chat or server without it turning into a mess.",
     "a real group chat you're part of", False),
    ("Digital Life", "Evaluate whether an online source is trustworthy", "occupational_education",
     "Check who wrote something, why, and whether it's backed by "
     "anything real before believing or sharing it.",
     "a real article or post to check", False),
    ("Digital Life", "Set healthy boundaries with people online", "occupational_education",
     "Block, mute, or walk away from something online the same way "
     "you'd leave an uncomfortable conversation in person -- and know "
     "it's okay to.",
     "the judgment call, when it's needed", False),
    ("Digital Life", "Understand your digital footprint", "occupational_education",
     "Search your own name and see what's actually out there, then "
     "think about what a stranger -- or a future employer -- would "
     "find.",
     "a device with internet access", False),
    ("Health & Safety", "Learn CPR and choking response", "health",
     "Real hands-on practice, not just watching a video -- what to "
     "actually do in the first minute before help arrives.",
     "a CPR class or certified instructor (many are free/cheap locally)", False),
    ("Health & Safety", "Build a home emergency kit", "health",
     "Water, food, flashlight, first aid, radio -- put together for "
     "real, checked and restocked, not just a vague plan in your head.",
     "a bin, the supply list, a shopping trip", False),
    ("Health & Safety", "Know your family's emergency meeting plan", "health",
     "Where to go and who to call if you're separated during an "
     "emergency -- fire, earthquake, or just a bad day gone sideways.",
     "a conversation with the family, written down somewhere", False),
    ("Health & Safety", "Understand your own allergies and how to manage them", "health",
     "What you're actually allergic to, what happens if exposed, and "
     "what to do about it -- including carrying and using an EpiPen if "
     "that applies to you.",
     "your actual medical info, an EpiPen if prescribed", False),
    ("Health & Safety", "Practice fire safety and know two ways out of every room", "health",
     "Actually walk it -- two real exits from your bedroom, and a plan "
     "for what happens if the main one's blocked.",
     "your own house, a walkthrough", False),
    ("Health & Safety", "Learn to swim well enough to be safe in open water", "health",
     "Not just float -- tread water, swim a real distance, and know "
     "your own limits in a lake, river, or ocean.",
     "access to a pool, lake, or swim lessons", False),
    ("Health & Safety", "Understand basic mental health warning signs -- in yourself and others", "health",
     "What actually counts as 'this isn't just a bad day' -- and who "
     "to tell if you notice it in yourself or a friend.",
     "the conversation, ideally with a parent or counselor", False),
    ("Health & Safety", "Get a full night's sleep on purpose for a week", "health",
     "Track it and actually protect it -- a real bedtime, no scrolling "
     "in bed, and notice what changes when you're not running on six "
     "hours.",
     "a way to track sleep (app or notebook)", False),
    ("Health & Safety", "Learn safe sun and heat exposure habits", "health",
     "Sunscreen that actually works, hydration, and knowing the real "
     "signs of heat exhaustion before it's a problem.",
     "sunscreen, water, a hot day to be smart about", False),
    ("Health & Safety", "Know how to handle a minor illness without panicking", "health",
     "A cold, a stomach bug, a fever -- what actually needs a doctor "
     "and what just needs rest, fluids, and time.",
     "a thermometer, basic over-the-counter guidance from a parent", False),
    ("Health & Safety", "Practice situational awareness in public", "health",
     "Notice exits, notice people, keep your head up instead of "
     "buried in a phone -- the boring habit that actually matters if "
     "something goes wrong.",
     "any public outing", False),
    ("Health & Safety", "Learn to safely use common household chemicals", "health",
     "Which cleaning products should never be mixed, how to read a "
     "warning label, and proper ventilation -- the stuff that turns "
     "'cleaning' into a hospital visit if ignored.",
     "household cleaning products, their labels", False),
    ("Time & Organization", "Keep a calendar you actually check", "occupational_education",
     "Every commitment, appointment, and deadline in one place -- and "
     "a real habit of looking at it, not just writing things down and "
     "forgetting.",
     "a planner or calendar app", False),
    ("Time & Organization", "Build a morning routine that actually works", "occupational_education",
     "Timed, tested, and adjusted until you're consistently out the "
     "door on time without a last-minute scramble.",
     "a clock, a week of mornings to test it", False),
    ("Time & Organization", "Break a big project into a real plan", "occupational_education",
     "Take something that feels overwhelming and split it into steps "
     "with actual deadlines, instead of starting the night before it's "
     "due.",
     "a real project or assignment", False),
    ("Time & Organization", "Practice saying no to protect your own time", "occupational_education",
     "Turn down a request you don't actually have room for, politely "
     "but clearly, instead of overcommitting and resenting it later.",
     "a real request to decline", False),
    ("Time & Organization", "Set and track a personal goal for a month", "occupational_education",
     "Something measurable, checked weekly, adjusted if it's not "
     "working -- not just a vague resolution you forget by day three.",
     "a goal, a way to track it", False),
    ("Time & Organization", "Declutter and maintain a workspace", "occupational_education",
     "A desk or study space that's actually set up to help you focus, "
     "kept that way on purpose, not cleaned once and left to pile up "
     "again.",
     "a desk or workspace", False),
    ("Time & Organization", "Manage multiple deadlines at once without missing one", "occupational_education",
     "A real week with more than one thing due, tracked and "
     "prioritized so nothing slips through.",
     "a real set of overlapping deadlines (school, chores, etc.)", False),
    ("Time & Organization", "Practice a consistent bedtime routine", "occupational_education",
     "Wind down the same way most nights -- screens off, same rough "
     "time -- and notice what it does to how the next day goes.",
     "a week to test it", False),
    ("Time & Organization", "Track your own spending or time for two weeks", "occupational_education",
     "Write down every dollar spent or every hour used for two real "
     "weeks, then actually look at the pattern -- most people are "
     "surprised.",
     "a notebook or app, two weeks", False),
    ("Time & Organization", "Plan a full free day well", "occupational_education",
     "A day with nothing scheduled, planned on purpose instead of "
     "drifting through it -- proof that 'free time' and 'wasted time' "
     "aren't the same thing.",
     "one real free day", False),
    ("Work & Career", "Do a full shift of real work for pay", "occupational_education",
     "Babysitting, yard work, a real job -- start to finish, showing "
     "up on time and seeing it through, for actual money.",
     "a real paid task or job", False),
    ("Work & Career", "Practice basic workplace etiquette", "occupational_education",
     "Showing up on time, communicating if you're running late, and "
     "how to actually talk to a boss or supervisor.",
     "a real or simulated work setting", False),
    ("Work & Career", "Explore three different careers seriously", "occupational_education",
     "Not just 'that sounds cool' -- actual research into what the job "
     "pays, what it takes to get there, and what a normal day looks "
     "like.",
     "internet access, maybe an informational interview", False),
    ("Work & Career", "Write a cover letter or introduction email for an opportunity", "occupational_education",
     "A real one, for something you'd actually apply to -- a job, a "
     "volunteer spot, a program.",
     "a real opportunity to apply for", False),
    ("Work & Career", "Understand how to read a job posting", "occupational_education",
     "What's actually required vs. nice-to-have, and how to tell if a "
     "posting is legitimate or a scam.",
     "a few real job postings", False),
    ("Work & Career", "Learn spreadsheet basics", "occupational_education",
     "Enter data, use a simple formula, sort a list -- the baseline "
     "spreadsheet skill almost every job eventually needs.",
     "a computer with spreadsheet software", False),
    ("Work & Career", "Practice professional phone and email tone", "occupational_education",
     "The difference between how you text a friend and how you email "
     "an employer -- and why mixing them up costs you.",
     "a real email or call to make", False),
    ("Work & Career", "Volunteer for a real cause and track the hours", "occupational_education",
     "Actual volunteer work, logged honestly, for something you care "
     "about -- not just for the resume line.",
     "a local volunteer opportunity", False),
    ("Work & Career", "Learn what an entrepreneur actually does day to day", "occupational_education",
     "Talk to or research someone who runs their own business -- past "
     "the highlight reel, into what a normal Tuesday looks like for "
     "them.",
     "an interview or solid research", False),
    ("Work & Career", "Understand your rights as a young worker", "occupational_education",
     "What hours you're legally allowed to work, what breaks you're "
     "owed, and who to tell if something's actually wrong.",
     "internet access (state labor department site)", False),
    ("Work & Career", "Practice public speaking to a real audience", "occupational_education",
     "A speech, a presentation, or just standing up and talking to "
     "more than five people without notes -- fear included.",
     "a real audience, even a small one", False),
    ("Work & Career", "Build a simple personal budget tied to a real income", "occupational_education",
     "Once there's actual money coming in -- allowance, a job, gifts "
     "-- track it against a real plan instead of spending as it "
     "arrives.",
     "real income, a budget tool", False),
    ("Civic & Legal", "Understand how local government actually works", "social_studies",
     "Who your mayor, city council, or county officials are, and what "
     "they actually control versus what's decided at the state or "
     "federal level.",
     "internet access, your local government's website", False),
    ("Civic & Legal", "Attend or watch a real public meeting", "social_studies",
     "A city council meeting, a school board meeting -- see how "
     "decisions that affect your actual town get made, in real time.",
     "a local meeting (many are livestreamed)", False),
    ("Civic & Legal", "Understand your rights if stopped by police", "social_studies",
     "What you're required to do, what you're not, and how to stay "
     "calm and safe through it -- a real, calm conversation, not just "
     "a Hollywood version.",
     "a conversation with a parent, maybe a real resource/pamphlet", False),
    ("Civic & Legal", "Register to vote as soon as you're eligible", "social_studies",
     "Know the process before you're actually old enough, so it's not "
     "a scramble the week of an election you care about.",
     "internet access, your state's voter registration site", False),
    ("Civic & Legal", "Understand a basic contract before signing anything", "social_studies",
     "What you're actually agreeing to in a phone plan, a lease, a gym "
     "membership -- reading past the first page.",
     "a real sample contract or agreement", False),
    ("Civic & Legal", "Learn what happens in small claims court", "social_studies",
     "How a normal person actually resolves a real dispute -- a "
     "deposit not returned, a bad repair job -- without a lawyer.",
     "internet access, your local court's info", False),
    ("Civic & Legal", "Understand jury duty and why it matters", "social_studies",
     "What it actually is, why it's not something to dodge, and what "
     "happens if you're called.",
     "the conversation/research", False),
    ("Civic & Legal", "Know the basics of your state's driving laws", "social_studies",
     "Not just how to drive -- what's actually legal: phone use, "
     "seatbelt law, what a ticket costs and does to insurance.",
     "your state's driver's handbook", False),
    ("Civic & Legal", "Understand how a tax return works, even before you file one", "social_studies",
     "What a W-2 is, roughly what a return means, and why some people "
     "get money back and others owe -- walked through with real "
     "numbers.",
     "a sample W-2 or tax form", False),
    ("Civic & Legal", "Participate in a community decision or local issue", "social_studies",
     "Speak at a meeting, sign a real petition, or write to a local "
     "official about something you actually care about.",
     "a real local issue", False),
    ("Outdoor & Wilderness", "Plan and go on a real hike", "occupational_education",
     "Pick the trail, check the weather, pack the right gear, and "
     "actually navigate it -- planning included, not just walking.",
     "a trail, weather check, day pack", False),
    ("Outdoor & Wilderness", "Set up a tent and camp overnight", "occupational_education",
     "Pitch it correctly, pack the right gear, and spend a real night "
     "outside -- not just in the backyard.",
     "a tent, camping gear, a campsite", False),
    ("Outdoor & Wilderness", "Build and safely put out a campfire", "occupational_education",
     "Start one without lighter fluid, keep it controlled, and put it "
     "out completely -- cold to the touch, not just no visible flame.",
     "a legal fire pit, wood, water or dirt to douse it", False),
    ("Outdoor & Wilderness", "Read a trail map and use a compass", "occupational_education",
     "No phone -- find your way using an actual paper map and compass, "
     "and know how to get back if you're turned around.",
     "a paper map, a compass", False),
    ("Outdoor & Wilderness", "Identify poisonous plants in your area", "health",
     "Poison ivy/oak, and anything else actually dangerous locally -- "
     "know it well enough to avoid it on sight.",
     "a local plant guide", False),
    ("Outdoor & Wilderness", "Purify water in the outdoors", "health",
     "Filter or treat water from a natural source well enough to "
     "actually drink it safely, using a real filter or tablets.",
     "a water filter or purification tablets, a natural water source", False),
    ("Outdoor & Wilderness", "Fish or forage responsibly", "occupational_education",
     "Catch something real (with a license if required) or forage "
     "something edible you've correctly identified -- know the rules, "
     "not just the how.",
     "fishing gear or a foraging guide, local regulations", False),
    ("Outdoor & Wilderness", "Handle basic outdoor first aid", "health",
     "A blister, a sprain, a bee sting, out in the field, without a "
     "fully stocked medicine cabinet nearby.",
     "a basic outdoor first aid kit", False),
    ("Outdoor & Wilderness", "Understand weather signs and when to turn back", "health",
     "Read the sky and conditions well enough to make the call to head "
     "back before a real problem starts.",
     "an outdoor trip where conditions are worth watching", False),
    ("Outdoor & Wilderness", "Leave no trace on a real trip", "occupational_education",
     "Pack out everything, including what most people leave behind, "
     "and leave a site exactly like you found it -- or better.",
     "a real outdoor outing, trash bags", False),
    ("Social & Etiquette", "Host or co-host a real gathering", "health",
     "Plan it, invite people, and actually run it -- from a small "
     "hangout to something bigger, hosting is its own skill.",
     "a real event to plan", False),
    ("Social & Etiquette", "Write and send real invitations", "health",
     "For a real event -- clear on the details, sent with enough "
     "notice, and actually followed up on.",
     "an event, a way to send invites", False),
    ("Social & Etiquette", "Practice good table manners at a real meal", "health",
     "Not just 'don't chew with your mouth open' -- how to actually "
     "navigate a sit-down meal, including one that's a little formal.",
     "a real sit-down meal", False),
    ("Social & Etiquette", "Be a good guest at someone else's home", "health",
     "Bring something, help clean up, know when it's time to leave -- "
     "the unwritten rules that make people want to invite you back.",
     "a real visit to someone else's home", False),
    ("Social & Etiquette", "Navigate a disagreement with a friend without losing the friendship", "health",
     "Say what's actually bothering you, hear them out, and come out "
     "the other side still friends -- a real, specific conflict, not a "
     "hypothetical.",
     "a real disagreement, when one comes up", False),
    ("Social & Etiquette", "Practice active listening in a real conversation", "health",
     "Actually listen instead of just waiting for your turn to talk -- "
     "and prove it by summarizing back what someone said.",
     "a real conversation partner", False),
    ("Social & Etiquette", "Handle rejection or disappointment gracefully", "health",
     "Not getting picked, not getting the answer you wanted -- react "
     "in a way you'd be fine with someone seeing.",
     "a real disappointment, when one happens", False),
    ("Social & Etiquette", "Include someone who's being left out", "health",
     "Notice it happening in a real group setting and actually do "
     "something -- not a lecture, just an action.",
     "a real group setting", False),
    ("Social & Etiquette", "Practice appropriate humor and know when to dial it back", "health",
     "Read a room well enough to know when a joke lands and when it "
     "doesn't -- and adjust in real time.",
     "a real social setting", False),
    ("Social & Etiquette", "Navigate a family conflict respectfully", "health",
     "Disagree with a parent or sibling on something real without it "
     "becoming a blowout -- state your case, actually listen, find a "
     "landing spot.",
     "a real family disagreement, when one comes up", False),
    ("Yard & Home Maintenance", "Mow a lawn correctly and safely", "occupational_education",
     "Real technique -- pattern, height, safety around obstacles -- "
     "not just pushing it around randomly.",
     "a mower, a lawn", False),
    ("Yard & Home Maintenance", "Rake and bag leaves or yard debris", "occupational_education",
     "A full yard, done properly, including where the bags/debris "
     "actually need to go afterward.",
     "a rake, bags, a yard", False),
    ("Yard & Home Maintenance", "Trim hedges or bushes with hand tools", "occupational_education",
     "Shape something on purpose, safely, without butchering it -- and "
     "clean up after.",
     "hand shears, a hedge or bush", False),
    ("Yard & Home Maintenance", "Clean out gutters", "occupational_education",
     "Actually clear them, safely, with someone spotting the ladder -- "
     "a job most people put off until it's a real problem.",
     "a ladder, gloves, a spotter", False),
    ("Yard & Home Maintenance", "Pressure wash a surface", "occupational_education",
     "Driveway, deck, or siding -- done right, without gouging wood or "
     "blasting mulch out of a bed.",
     "a pressure washer, the surface", False),
    ("Yard & Home Maintenance", "Plant something and keep it alive for a season", "occupational_education",
     "A tree, a garden bed, a few pots -- planted correctly and "
     "actually tended, not just planted and forgotten.",
     "plants, soil, tools", False),
    ("Yard & Home Maintenance", "Shovel snow or handle winter yard prep safely", "occupational_education",
     "Real technique so it doesn't wreck your back, plus knowing when "
     "ice makes it not worth doing alone.",
     "a shovel, snow (seasonal)", False),
    ("Yard & Home Maintenance", "Do a basic seasonal home walkthrough", "occupational_education",
     "Check weatherstripping, look for drafts, check the roof and "
     "foundation from the ground -- catching small problems before "
     "they're expensive ones.",
     "a checklist, a walk around the house", False),
    # -- Growing Up: emotional regulation, decision-making, and critical
    # thinking. All locked by default, same as everything past the starter
    # 15 -- a parent picks the pace here more deliberately than anywhere
    # else in the catalog. Credited to health (WA's subject explicitly
    # covers "mental wellbeing," not just physical).
    ("Growing Up", "Understand what's changing in your brain right now", "health",
     "Your brain is still building the part that handles impulse control "
     "and big emotions -- that's not an excuse, it's just how a "
     "13-year-old brain actually works. Learn what's really going on and "
     "why some days feel harder than others for a real reason.",
     "just you and a parent to talk it through", False),
    ("Growing Up", "Build your own feelings vocabulary", "health",
     "Most people only reach for 'fine,' 'mad,' or 'whatever.' Learn more "
     "precise words for what you're actually feeling -- the more exactly "
     "you can name it, the easier it is to do something about it.",
     "a list of feeling words to start from", False),
    ("Growing Up", "Build your own cool-down plan", "health",
     "Figure out what it actually feels like right before things get too "
     "big for you, and build your own specific plan for that exact moment "
     "-- not a generic breathing exercise, one that's actually yours.",
     "some quiet time to think it through with a parent", False),
    ("Growing Up", "The pause before you decide", "health",
     "A real, usable pause to put between an urge and an action -- what "
     "to ask yourself in that moment so the next thing you do is a "
     "decision, not just a reaction.",
     "a couple of real recent examples to walk through", False),
    ("Growing Up", "Weigh a decision before you make it", "health",
     "A simple way to actually think through a choice before making it -- "
     "what your real options are, what happens after each one, and what "
     "you actually want here versus what you want right this second.",
     "a real decision, past or upcoming, to practice on", False),
    ("Growing Up", "What I did isn't who I am", "health",
     "A bad choice is a thing that happened, not a life sentence on your "
     "character. Work through separating the two, so a mistake is "
     "something to fix and move past instead of something to carry "
     "around.",
     "an honest conversation", False),
)

# Seed catalog for Big Projects: (project title, vision, steps), where each
# step is (title, description, materials, credit_subject). Written by hand,
# same reasoning as LIFE_SKILL_CATALOG -- plain, casual, kid-facing, and
# ordered because later steps genuinely depend on earlier ones (you can't
# shoot a set you haven't built). The Lego stop-motion film is the first
# entry; more can be added to this tuple as new project ideas are agreed on.
BIG_PROJECT_CATALOG: Sequence[
    tuple[str, str, Sequence[tuple[str, str, str, str, int, int]]]
] = (
    (
        "Stop-Motion Lego Film",
        "Write, build, shoot, and edit your own short Lego stop-motion film -- "
        "start to finish, your story, released as a real finished film the "
        "family watches together.",
        (
            ("Pick your story",
             "Come up with a short story with a clear beginning, middle, and "
             "end. Keep it small on purpose -- 4 to 6 scenes is plenty for a "
             "first film.\n\n"
             "- Think up 2 or 3 different ideas before picking one -- a "
             "one-line version of each is enough (\"a heist to steal back a "
             "stolen treasure,\" \"two armies fighting over a castle\").\n"
             "- Pick the one that actually excites you most, not the "
             "easiest one to think of.\n"
             "- Say the whole story out loud to a parent, start to finish. "
             "If you get stuck explaining a part, that part isn't figured "
             "out yet -- that's fine, just notice it.\n"
             "- Write down three sentences: how it starts, the big problem "
             "in the middle, how it ends.\n\n"
             "**Before you move on:** can you tell the whole story in under "
             "a minute without stopping to think? If not, sit with it "
             "another day first -- a story you actually know cold makes "
             "every step after this one easier.",
             "paper and pencil (or just talk it through out loud)", "writing", 1, 2),
            ("Write your shot list",
             "Break the story into a numbered list of scenes -- a scene is "
             "anywhere the location or the action changes.\n\n"
             "- For each scene, write down three things: where it happens, "
             "who's in it, what happens.\n"
             "- Number them in order.\n"
             "- Rough sketches are fine -- stick figures and arrows for "
             "movement, it doesn't need to look good.\n\n"
             "**Before you move on:** count your scenes. 4-6 is the sweet "
             "spot for a first film -- more than that and the build-and-"
             "shoot step later gets long. More than 6? Look for two scenes "
             "you could combine into one.",
             "paper, pencil", "writing", 1, 1),
            ("Cast your minifigs",
             "Decide which minifig plays which character. Stop-motion lives "
             "or dies on consistency -- the same figure needs to look the "
             "same in every scene it's in.\n\n"
             "- Pull one minifig for every character in your story before "
             "you do anything else.\n"
             "- Line them up and match each one to a name in your story.\n"
             "- Take a photo of the lineup, or write down which fig is "
             "which character -- you will forget which one was who in a "
             "week.\n\n"
             "**Before you move on:** double-check every character in your "
             "story actually has a fig lined up. A character who doesn't "
             "exist yet in Lego form will trip you up when you get to "
             "building scenes.",
             "your Lego minifigs", "art_and_music", 1, 1),
            ("Build your first set",
             "Build or arrange the set for scene 1 -- for that specific "
             "scene, not just \"a cool set.\"\n\n"
             "- Reread scene 1 on your shot list before you build anything.\n"
             "- Start with what you already have (bricks, baseplates, "
             "existing builds); only reach for cardboard or craft supplies "
             "for what's missing -- a building front, hills, a backdrop "
             "sky.\n"
             "- Build slow, and stop partway through to check it from the "
             "angle the camera will actually see, not just from above.\n"
             "- Leave room for the camera and for hands to reach in and "
             "move minifigs between shots.\n\n"
             "**Before you move on:** stand back and look at the set the "
             "way the camera will see it. Does it look like the place in "
             "your head? Fix it now -- it's much harder to fix once you've "
             "started shooting.",
             "Lego bricks/baseplates, cardboard or foam board, scissors, "
             "tape or glue, paint or felt/cellophane for texture", "art_and_music", 1, 2),
            ("Set up your shooting station",
             "A stop-motion shoot needs two things above all: a camera that "
             "doesn't move, and light that doesn't change.\n\n"
             "- Pick a spot that won't need to move for a few days -- this "
             "isn't a one-sitting job.\n"
             "- Lock the camera down first: a tripod, or a phone wedged "
             "against something solid. Test it by taking two photos in a "
             "row and checking they line up exactly.\n"
             "- Point a desk lamp at the set instead of relying on a "
             "window -- daylight shifts during a shoot and causes flicker.\n"
             "- Install the stop-motion app and find onion-skin mode before "
             "you need it, not in the middle of shooting.\n\n"
             "**Before you move on:** take five test photos in a row "
             "without touching anything else in the room. If they all look "
             "identical, the station is solid. If anything shifted, fix it "
             "now, not mid-scene.",
             "phone or tablet, tripod or something to wedge it steady, a "
             "desk lamp, the Stop Motion Studio app (free)", "occupational_education", 1, 1),
            ("Shoot your first scene",
             "Go slowest on this one, on purpose -- it's brand new, and "
             "mistakes here are cheap to fix. Mistakes later cost more "
             "time.\n\n"
             "- Move one thing a small amount, take a photo, check the "
             "onion-skin, move it a small amount again. Small movements = "
             "smooth motion. Big jumps = jumpy motion.\n"
             "- Don't rush to finish the scene -- a 5-second scene shot "
             "slowly and carefully beats a 15-second scene shot in a "
             "hurry.\n"
             "- Play the shots back after every 10-15 of them to catch "
             "problems early, not after the whole scene is done.\n\n"
             "**Before you move on:** watch the whole scene back. Smooth, "
             "or jumpy in spots? Jumpy usually means the movements were too "
             "big -- worth reshooting that part now rather than living "
             "with it in the finished film.",
             "the set and shooting station from the last two steps", "occupational_education", 1, 2),
            ("Build and shoot the rest of your scenes",
             "Repeat the build-then-shoot loop, one scene at a time, in the "
             "same order as your shot list -- don't jump ahead to a scene "
             "you're more excited about.\n\n"
             "- Each scene: reread it, build or adjust the set, lock the "
             "camera down, shoot slowly, play it back.\n"
             "- It's fine for this to take several separate sessions -- add "
             "one step to this project per remaining scene, so each one "
             "gets its own checkbox instead of feeling like one giant "
             "task.\n\n"
             "**Before you move on to editing:** every scene on your shot "
             "list has its own finished clip. Don't start editing until "
             "they're all shot -- jumping back and forth between shooting "
             "and editing is how scenes get forgotten.",
             "same as the last three steps, one round per scene", "occupational_education", 5, 10),
            ("Add sound and voices",
             "This is the step that turns a silent slideshow into a "
             "movie.\n\n"
             "- Watch each scene silently first and decide what it needs: "
             "voices? footsteps? music? a sound effect?\n"
             "- Record voices in a quiet room, phone close to your mouth -- "
             "redo a line if it's muffled or rushed, don't just keep the "
             "first take.\n"
             "- Try foley before searching for \"real\" sound effects -- "
             "clapping, tapping a table, crinkling paper often sounds "
             "better than a stock sound.\n"
             "- Do one type of sound at a time (all the voices first, then "
             "effects, then music) instead of everything at once.\n\n"
             "**Before you move on:** watch it back with sound. Anything "
             "feel rushed or mumbled? Redo just that one clip -- you don't "
             "have to redo the whole thing.",
             "phone or tablet mic, a quiet room, CapCut or iMovie", "art_and_music", 2, 3),
            ("Edit it all together",
             "This is where all those small separate files finally become "
             "one finished film.\n\n"
             "- Import every scene clip in order first, before trimming "
             "anything -- get the whole film roughly assembled before you "
             "polish any one part.\n"
             "- Watch the rough assembly all the way through once. Notice "
             "what drags or feels rushed.\n"
             "- Trim the slow, boring bits and the too-fast confusing "
             "bits.\n"
             "- Add a simple transition (a cut or fade) between scenes -- "
             "nothing fancy needed for a first film.\n\n"
             "**Before you move on:** watch the full edit start to finish, "
             "no pausing. If a part is confusing on a first watch, a viewer "
             "who's never seen your story will be even more lost there -- "
             "that's the part to go back and fix.",
             "CapCut or iMovie, all your exported scene clips", "occupational_education", 2, 3),
            ("Add titles and credits",
             "Small thing, but it's what makes it feel like a finished "
             "film instead of a school assignment.\n\n"
             "- Title card: just the movie's name, on screen for a couple "
             "seconds at the start.\n"
             "- Credits at the end: \"Directed by\" you, cast (which "
             "minifig played who), any music you used.\n"
             "- Keep it simple -- plain text on a plain background is "
             "completely fine.\n\n"
             "**Before you move on:** read the credits out loud once. Did "
             "you credit everyone who's actually in it?",
             "CapCut or iMovie's title tools", "art_and_music", 1, 1),
            ("Premiere night",
             "The payoff for every step that came before it -- don't rush "
             "this one either.\n\n"
             "- Pick a night, tell the family it's happening ahead of "
             "time, no screens or interruptions during the watch.\n"
             "- Watch it start to finish without pausing to explain or "
             "apologize for anything -- let it just play.\n"
             "- Afterward, ask what people liked best. That's useful "
             "information for the next film, not just a nice moment.",
             "a TV or big screen, snacks", "art_and_music", 1, 1),
        ),
    ),
    (
        "Mini Podcast Series",
        "Plan, record, and release your own mini podcast series -- pick a "
        "subject you actually want to talk about, and turn it into real "
        "episodes people can listen to.",
        (
            ("Pick your show's topic",
             "A podcast is way easier to stick with when the topic is "
             "something you'd talk about anyway, not something you think "
             "you're supposed to make a show about.\n\n"
             "- A few starting points, pick one or mix your own: review "
             "games/movies/shows you actually play or watch, explain a "
             "topic you're genuinely into (space, history, a hobby, a "
             "sport), interview family members about their lives or "
             "opinions, retell a mystery or story episode by episode, an "
             "advice or opinions show, a recap of something happening "
             "now.\n"
             "- Decide: one big topic that carries every episode, or a "
             "different topic each episode?\n"
             "- Say your show's idea out loud in one sentence, the way "
             "you'd describe it to a friend.\n\n"
             "**Before you move on:** could you talk about this topic for "
             "5 minutes right now, off the top of your head, without "
             "running out of things to say? If not, it might be too "
             "narrow -- widen it a little.",
             "paper and pencil (or just talk it through out loud)", "writing", 1, 2),
            ("Decide: audio-only or video",
             "This changes almost everything after this step, so decide "
             "it on purpose instead of drifting into one.\n\n"
             "- **Audio-only:** simpler gear (just a phone or mic), faster "
             "to record and edit, no lighting or camera setup to worry "
             "about, and it's how most real podcasts actually work.\n"
             "- **Video podcast:** lets people see your face and "
             "reactions, works well for things like showing gameplay or "
             "holding up objects on screen, but takes the same "
             "camera-and-lighting setup as the stop-motion film, and "
             "editing takes longer.\n"
             "- If this is your first podcast, audio-only gets you to a "
             "finished episode faster -- you can always add video for a "
             "season two.\n\n"
             "**Before you move on:** write down which one you picked and "
             "why in one sentence. If you can't explain why, default to "
             "audio-only.",
             "none -- this is a decision, not a build", "occupational_education", 1, 1),
            ("Plan your first episode",
             "A podcast episode works better from a loose outline than a "
             "word-for-word script -- scripted episodes usually sound "
             "stiff.\n\n"
             "- Write a simple rundown: how you'll open (who you are, "
             "what the show is), 2-4 main points or segments, how you'll "
             "close.\n"
             "- Do the research before you record, not during: if you're "
             "reviewing something, finish it first and jot down specific "
             "moments and opinions, not vague ones. If you're explaining "
             "a topic, look up 3-5 real facts so what you say is actually "
             "accurate.\n"
             "- Listen to one episode of a real podcast in a similar "
             "style first -- notice how they open the show and how long "
             "they spend per topic.\n\n"
             "**Before you move on:** read your rundown out loud once, "
             "timing it. Way under 3 minutes? You probably need another "
             "talking point. Way over 15? Pick your best points and cut "
             "the rest.",
             "paper and pencil, whatever you're reviewing or researching", "writing", 1, 2),
            ("Set up your recording space",
             "Where you record matters almost as much as what you say -- "
             "a bad room makes even a good episode sound rough.\n\n"
             "- Pick a small, soft room if you can -- a closet with "
             "clothes in it, a bedroom with carpet and curtains. Hard, "
             "empty rooms echo.\n"
             "- Position the phone or mic a few inches from your mouth, "
             "slightly off to the side rather than dead-on, to avoid "
             "popping sounds on words like \"p\" and \"b.\"\n"
             "- Doing video too? Set up the same steady-camera and "
             "lamp-not-window lighting you used for the stop-motion "
             "film.\n"
             "- Record a 10-second test and actually listen back on "
             "headphones before committing to a real take.\n\n"
             "**Before you move on:** play your test clip back. Clear, no "
             "echo or background hum? Fix the room before you record for "
             "real, not after.",
             "phone or a mic, a quiet/soft-surfaced room, headphones for "
             "checking playback", "occupational_education", 1, 1),
            ("Record your first episode",
             "Aim for one solid pass, not a perfect one -- editing fixes "
             "more than you'd think.\n\n"
             "- Follow your rundown loosely -- talk naturally instead of "
             "reading it word for word.\n"
             "- It's fine to pause, mess up, and just redo the last "
             "sentence -- you'll cut the mess-up out later.\n"
             "- Doing video? Keep the camera locked down and the lighting "
             "steady the whole time, same lesson as the film shoot.\n"
             "- Before you stop, play back at least a full minute of what "
             "you recorded to make sure the audio actually came through "
             "and sounds right.\n\n"
             "**Before you move on:** listen to the whole raw recording "
             "once, start to finish. Enough there for a real episode, or "
             "did you run out of things to say partway through? Better to "
             "notice now than after editing.",
             "your recording setup from the last step", "occupational_education", 1, 1),
            ("Edit the episode",
             "Editing is where a rough recording turns into something "
             "people would actually want to listen to.\n\n"
             "- Cut the dead air, the long pauses, and the worst flubbed "
             "lines -- but don't remove every single \"um,\" a few is "
             "normal and cutting them all sounds robotic.\n"
             "- Add a short music clip at the start and end if you want "
             "one -- look for royalty-free/free-to-use music rather than "
             "a random song.\n"
             "- Listen to the whole edit once, headphones on, before "
             "calling it done.\n\n"
             "**Before you move on:** would you want to listen to this if "
             "someone else made it? If a section drags, trim it further -- "
             "much faster to fix now than after you've shared it.",
             "CapCut, iMovie, or a simple audio editor, your raw recording", "occupational_education", 1, 2),
            ("Design your cover art",
             "Every podcast needs a square image that represents the "
             "show -- small step, but it's what makes it feel like a real "
             "show instead of just an audio file.\n\n"
             "- Keep it simple: your show's title, plus one image or icon "
             "that fits the topic.\n"
             "- Make sure the title is readable even as a tiny "
             "thumbnail -- that's how it'll actually show up.\n\n"
             "**Before you move on:** shrink it down on screen until it's "
             "thumbnail-sized. Can you still read the title?",
             "CapCut, Canva, or any simple design app", "art_and_music", 1, 1),
            ("Share your episode",
             "Decide who this is for before you send it anywhere -- same "
             "as any of your recorded projects, this is a choice to make "
             "on purpose.\n\n"
             "- Private and family-only is a completely legitimate "
             "choice, and the simplest one -- a shared folder or a link "
             "works fine.\n"
             "- Want it more widely available someday? That's a bigger "
             "decision (a real podcast platform, a public account) worth "
             "a separate conversation with a parent first, not a "
             "default.\n\n"
             "**Before you move on:** confirm with a parent where this "
             "episode is actually going before you send or post it "
             "anywhere.",
             "wherever you and your family agree the file should live", "occupational_education", 1, 1),
            ("Record your next episodes",
             "Repeat the plan-record-edit loop from the last several "
             "steps, one episode at a time.\n\n"
             "- Each new episode: pick your topic (or the next segment of "
             "an ongoing one), plan a rundown, record, edit, done.\n"
             "- Add one step to this project per additional episode, so "
             "each one gets its own checkbox instead of the whole season "
             "feeling like one giant task.\n"
             "- It gets faster after the first one -- the setup and "
             "rhythm are already figured out.\n\n"
             "**Before you move on to wrapping up the season:** you've "
             "got at least 3 finished episodes. A season of one episode "
             "isn't really a series yet.",
             "same as the recording and editing steps, one round per episode", "occupational_education", 6, 9),
            ("Season listening party",
             "The payoff for a whole season of work.\n\n"
             "- Pick a night and actually play an episode (or your "
             "favorite moments from a few) for the family, out loud, "
             "together.\n"
             "- Let it just play -- no pausing to explain or apologize "
             "for anything.\n"
             "- Afterward, ask what people liked best, and what they'd "
             "want to hear more of in season two.",
             "a speaker, snacks", "art_and_music", 1, 1),
        ),
    ),
    (
        "Toy Photography",
        "Learn real photography technique and use it to shoot a themed "
        "photo series starring your own toys -- your subject, your "
        "style, turned into a finished collection you're proud to show "
        "off.",
        (
            ("Pick your toy and your theme",
             "Pick which toy or toys are starring in this -- Legos, "
             "action figures, dinosaurs, cars, whatever you actually want "
             "to shoot -- and a theme that gives the whole series a point "
             "instead of just random snapshots.\n\n"
             "- A few theme starting points: an adventure told across "
             "several photos, \"a day in the life of\" your toy, a \"tiny "
             "world\" series shot in different real locations around your "
             "house or yard, dramatic action or battle shots.\n"
             "- Pick a theme you can actually finish in 5-8 photos -- not "
             "an epic.\n\n"
             "**Before you move on:** can you describe your theme in one "
             "sentence? If it takes three sentences to explain, it's "
             "probably still two ideas -- pick one.",
             "the toy(s) you're shooting", "art_and_music", 1, 1),
            ("Learn the core techniques before you shoot",
             "This is the step that actually teaches you photography, "
             "not just \"take some pictures\" -- try each of these on "
             "purpose before your real shoot.\n\n"
             "- **Rule of thirds:** turn on your camera's grid lines. "
             "Instead of putting your toy dead center, line it up on one "
             "of the grid lines or where two lines cross -- it almost "
             "always looks more interesting.\n"
             "- **Get to eye level:** get down low, level with the toy, "
             "instead of shooting down from standing height. This is the "
             "single biggest thing that makes a toy photo look like a "
             "real scene instead of \"a toy on a table.\"\n"
             "- **Light:** soft, indirect light (near a window, an "
             "overcast day) looks better than harsh direct sun. Walk "
             "around your toy and watch how the shadows change before "
             "you pick your angle.\n"
             "- **Depth:** get close to your subject and let the "
             "background go soft/blurry if your camera does that (often "
             "called portrait mode) -- it makes the toy feel bigger and "
             "more real.\n"
             "- **Forced perspective:** put the toy close to the camera "
             "with something real far in the background (a tree, a "
             "hill) -- it can make a small toy look full-sized.\n"
             "- Actually go take 5 test shots right now, one technique at "
             "a time, and compare them.\n\n"
             "**Before you move on:** look at your 5 test shots. Which "
             "technique made the biggest difference? Keep that one in "
             "mind for your real shoot.",
             "your phone or camera, a few household objects to test with", "art_and_music", 1, 2),
            ("Scout your locations",
             "Find the real-world spots you'll actually shoot in before "
             "the day you shoot.\n\n"
             "- Walk around inside and outside and find 3-5 spots that "
             "fit your theme.\n"
             "- Check the light at each spot -- morning and afternoon "
             "light look very different in the same location.\n"
             "- Look for spots with an interesting background that isn't "
             "cluttered or messy right behind your toy.\n\n"
             "**Before you move on:** for each spot, can you say in one "
             "sentence what shot you'd get there? No answer for a spot? "
             "Drop it from the list.",
             "none -- just your eyes and your house/yard", "art_and_music", 1, 1),
            ("Plan your shot list",
             "Same idea as a shot list for a film -- a short plan so "
             "you're not standing there blank when you get to a "
             "location.\n\n"
             "- For each planned photo, jot down: which toy, which "
             "location, what's happening in the shot, which technique "
             "from the last step you're using.\n"
             "- Doesn't need to be long -- one line per shot is plenty.\n\n"
             "**Before you move on:** count your planned shots. 8-12 is a "
             "good range for a first collection -- covers a real series "
             "without dragging on forever.",
             "paper and pencil", "writing", 1, 1),
            ("Shoot your first batch",
             "Go slower than feels necessary on this one -- the goal "
             "isn't to burn through your shot list fast, it's to "
             "actually get good shots.\n\n"
             "- For each shot, take at least 3 variations -- a different "
             "angle, a different distance, a different bit of framing -- "
             "instead of one photo and moving on. Professionals call this "
             "\"covering\" a shot.\n"
             "- Check your screen after each setup, not just at the end -- "
             "catch a blurry or badly lit shot while the toy is still "
             "right there, not after you've packed up.\n"
             "- Use the eye-level and rule-of-thirds habits from step 2 "
             "on every single shot, on purpose, until they stop feeling "
             "like extra effort.\n\n"
             "**Before you move on:** for your first location, do you "
             "have at least one shot you're genuinely happy with? If not, "
             "it's worth going back before moving to the next spot.",
             "your shot list, the toy(s), your camera", "occupational_education", 1, 2),
            ("Review and cull your shots",
             "A real photography skill: being willing to ignore most of "
             "what you shot and keep only the best.\n\n"
             "- Go through everything from this location and pick your "
             "actual favorites -- expect to keep maybe 1 in 5.\n"
             "- For each favorite, say out loud (or write down) why it's "
             "the best version of that shot -- that's what teaches you to "
             "notice technique actually working.\n"
             "- Delete or archive the rest so they're not cluttering your "
             "search for favorites later.\n\n"
             "**Before you move on:** do your favorites actually use what "
             "you learned about thirds, eye level, light, and depth, or "
             "did you just pick the ones where the toy looks clearest? "
             "Both matter, but technique is the point of this project.",
             "your shots from this location", "art_and_music", 1, 1),
            ("Shoot your remaining locations",
             "Repeat the shoot-and-cull loop (the last two steps) once "
             "for each remaining spot on your list.\n\n"
             "- Same routine each time: reread your plan for that spot, "
             "check the light, shoot multiple variations, review and "
             "cull before moving on.\n"
             "- Add one step to this project per remaining location, so "
             "each one gets its own checkbox.\n\n"
             "**Before you move on to editing:** every location on your "
             "shot list has at least one favorite shot picked out.",
             "same as the last two steps, one round per location", "occupational_education", 3, 6),
            ("Edit your favorites",
             "Light editing only -- the goal is polishing a shot that "
             "already works, not rescuing one that doesn't.\n\n"
             "- Crop to improve the composition if needed.\n"
             "- Adjust brightness or straighten a tilted horizon.\n"
             "- Free apps like Snapseed work fine -- avoid heavy filters "
             "that hide the actual photo.\n\n"
             "**Before you move on:** compare the edited version to the "
             "original. Better version of the same photo, or does it "
             "look fake or overdone? If it's the second one, pull back.",
             "Snapseed or your phone's built-in editor, your favorite shots", "occupational_education", 1, 2),
            ("Put together your collection",
             "Turn your best shots into one finished thing, not just a "
             "folder of images.\n\n"
             "- Options: a printed photo book or scrapbook, a shared "
             "digital album, or a slideshow with captions.\n"
             "- Write a short caption for each photo -- what it is, or "
             "the little story it's telling.\n"
             "- Put them in an order that makes sense for your theme, not "
             "just the order you shot them.\n\n"
             "**Before you move on:** look at the whole collection in "
             "order, start to finish. One series, or a random pile of toy "
             "photos? If it's the second one, the captions and the order "
             "are what tie it together -- work on those.",
             "a scrapbook/photo album, or a digital album/slideshow tool, "
             "printing if you want physical copies", "art_and_music", 1, 2),
            ("Gallery night",
             "Show off the finished collection -- this is the payoff for "
             "all the shooting and culling.\n\n"
             "- Pick a night and actually show it to the family -- a "
             "slideshow, prints laid out on a table, or a shared album, "
             "whichever you made.\n"
             "- Let people look through it without narrating over every "
             "single photo -- let the captions do that work.\n"
             "- Ask which shots people liked best -- that's real feedback "
             "for next time.",
             "however you built your collection", "art_and_music", 1, 1),
        ),
    ),
)

# Leitner intervals in days, indexed by box number (1-5).
LEITNER_INTERVALS = {1: 1, 2: 3, 3: 7, 4: 16, 5: 35}


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = Path(db_path or config.DEFAULT_DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _rows(cursor: sqlite3.Cursor) -> list[dict[str, Any]]:
    return [dict(row) for row in cursor.fetchall()]


def _row(cursor: sqlite3.Cursor) -> dict[str, Any] | None:
    row = cursor.fetchone()
    return dict(row) if row else None


class Database:
    def __init__(self, db_path: str | Path | None = None):
        self.path = Path(db_path or config.DEFAULT_DB_PATH)
        self.conn = connect(self.path)
        self.migrate()

    # -- schema ---------------------------------------------------------------

    def migrate(self) -> None:
        self.conn.executescript(SCHEMA_PATH.read_text())
        # Runs first, right after executescript (which commits any pending
        # transaction before it runs) and before any other migration below
        # issues DML of its own -- it needs to toggle the foreign_keys
        # pragma, which SQLite silently no-ops in the middle of a
        # transaction, so nothing else can be allowed to open one first.
        self._migrate_activities_allow_projects_tier()
        # `CREATE TABLE IF NOT EXISTS` above only covers a table's first-ever
        # creation -- a family's existing life_skills table predates the
        # `materials`/`active` columns, so they need adding here instead.
        self._ensure_column("life_skills", "materials", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column("life_skills", "active", "INTEGER NOT NULL DEFAULT 1")
        self._ensure_column("project_steps", "min_days", "INTEGER NOT NULL DEFAULT 1")
        self._ensure_column("project_steps", "max_days", "INTEGER NOT NULL DEFAULT 1")
        self._ensure_column("big_projects", "shelved", "INTEGER NOT NULL DEFAULT 0")
        self._ensure_column("activities", "course_id", "INTEGER REFERENCES courses(id) ON DELETE SET NULL")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_activities_course ON activities (course_id)")
        # Runs before the migration below, not after: that migration inserts
        # travel_entries rows (from the old park_visits table) through
        # add_travel_entry, which writes every one of these columns -- if
        # they didn't exist yet, that INSERT would fail outright, the exact
        # opposite ordering hazard from the books rebuild further down.
        self._ensure_column("travel_entries", "favorite_moment", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column("travel_entries", "would_return", "TEXT NOT NULL DEFAULT ''")
        self._backfill_life_skill_content()
        self._backfill_life_skill_catalog()
        self._migrate_park_visits_to_travel_entries()
        self._migrate_interests_string_to_list()
        self._migrate_journal_entries_allow_multiple_per_day()
        self._migrate_books_allow_upcoming_status()
        # Runs after the rebuild above, not before: that rebuild recreates
        # `books` from its own hardcoded column list on a database old enough
        # to need it, which would otherwise silently drop a column added here
        # first, same failure shape _migrate_activities_allow_projects_tier's
        # own comment warns about.
        self._ensure_column("books", "ai_summary", "TEXT NOT NULL DEFAULT ''")
        self._backfill_big_project_step_content()
        self._backfill_big_project_catalog()
        self._backfill_declaration_url_default()
        for key, value in config.DEFAULT_SETTINGS.items():
            self.conn.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value)
            )
        self.conn.commit()

    def _ensure_column(self, table: str, column: str, ddl: str) -> None:
        existing = {row["name"] for row in self.conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

    def _backfill_declaration_url_default(self) -> None:
        """`declaration_url` predates knowing the family's actual district --
        it was seeded blank on purpose rather than guessed. Now that their
        real district packet has told us, upgrade it, but only if it's still
        sitting at that original blank default -- a parent who already typed
        their own value in keeps it untouched. `declaration_mail_to` needs no
        equivalent: it's a brand-new setting key, so the normal INSERT OR
        IGNORE seeding below already covers it for every database, new or
        existing."""
        row = self.conn.execute(
            "SELECT value FROM settings WHERE key = 'declaration_url'"
        ).fetchone()
        if row is not None and row["value"] == "":
            self.conn.execute(
                "UPDATE settings SET value = ? WHERE key = 'declaration_url'",
                (config.DEFAULT_SETTINGS["declaration_url"],),
            )

    def _migrate_activities_allow_projects_tier(self) -> None:
        """activities.tier had a CHECK constraint listing the tiers that
        predates Big Projects and Morning Routine -- SQLite can't ALTER a
        CHECK constraint in place, so this rebuilds the table with
        'projects'/'wellness' added, keeping every row (same id, so
        activity_subject_credits' foreign keys still point at the right
        one).

        Built new-name-first rather than rename-old-then-recreate: SQLite's
        ALTER TABLE RENAME rewrites *other* tables' foreign key clauses to
        follow the renamed table, so renaming `activities` away would leave
        activity_subject_credits permanently pointing at `activities_old`
        even after that table is long gone. Building `activities_new` and
        renaming it into the vacated `activities` name never touches
        anything that references `activities` by its real name, so that
        foreign key is never disturbed."""
        table = _row(
            self.conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='activities'"
            )
        )
        if table is None or "'wellness'" in (table["sql"] or ""):
            return  # no table yet, or already rebuilt with the new tiers
        self.conn.execute("PRAGMA foreign_keys = OFF")
        self.conn.execute(
            "CREATE TABLE activities_new ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,"
            "lesson_id INTEGER REFERENCES lessons(id) ON DELETE SET NULL,"
            "title TEXT NOT NULL,"
            "description TEXT NOT NULL DEFAULT '',"
            "tier TEXT NOT NULL CHECK (tier IN "
            "('core', 'folded', 'choice', 'life_skills', 'projects', 'wellness')),"
            "primary_subject TEXT NOT NULL,"
            "source TEXT NOT NULL DEFAULT 'manual',"
            "minutes INTEGER NOT NULL CHECK (minutes > 0),"
            "occurred_on TEXT NOT NULL,"
            "location TEXT NOT NULL DEFAULT '',"
            "created_at TEXT NOT NULL DEFAULT (datetime('now'))"
            ")"
        )
        self.conn.execute(
            "INSERT INTO activities_new "
            "(id, student_id, lesson_id, title, description, tier, primary_subject, "
            " source, minutes, occurred_on, location, created_at) "
            "SELECT id, student_id, lesson_id, title, description, tier, primary_subject, "
            "source, minutes, occurred_on, location, created_at FROM activities"
        )
        self.conn.execute("DROP TABLE activities")
        self.conn.execute("ALTER TABLE activities_new RENAME TO activities")
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_activities_student_date "
            "ON activities (student_id, occurred_on)"
        )
        self.conn.commit()
        self.conn.execute("PRAGMA foreign_keys = ON")

    def _migrate_park_visits_to_travel_entries(self) -> None:
        """`park_visits` (park-only, no state, no story) predates the
        state-first travel journal -- a family already running the old
        National Parks tracker has real visit rows sitting in it. Carry
        each one forward as its own travel entry (state derived from the
        park's own catalog entry) before retiring the old table, so nothing
        logged before this change quietly disappears."""
        has_old_table = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='park_visits'"
        ).fetchone()
        if not has_old_table:
            return
        from compass import national_parks as parks

        for row in _rows(self.conn.execute("SELECT * FROM park_visits")):
            park = parks.park_by_key(row["park_key"])
            state = parks.STATE_ABBR.get(park.states.split("/")[0], "") if park else ""
            title = park.name if park else row["park_key"]
            self.conn.execute(
                "INSERT INTO travel_entries "
                "(student_id, state, park_key, title, story, visited_on, created_at) "
                "VALUES (?, ?, ?, ?, '', ?, ?)",
                (
                    row["student_id"],
                    state,
                    row["park_key"],
                    title,
                    row["visited_on"],
                    row["created_at"],
                ),
            )
        self.conn.execute("DROP TABLE park_visits")

    def _migrate_interests_string_to_list(self) -> None:
        """`students.interests` used to be one free-text blob typed into a
        small textarea; carry any existing text into student_interests
        (split on commas, or kept whole if there weren't any) before the
        column is retired, so nothing a family already typed in is lost."""
        existing_columns = {
            row["name"] for row in self.conn.execute("PRAGMA table_info(students)")
        }
        if "interests" not in existing_columns:
            return
        for row in _rows(self.conn.execute("SELECT id, interests FROM students")):
            blob = (row["interests"] or "").strip()
            for item in blob.split(","):
                item = item.strip()
                if item:
                    self.conn.execute(
                        "INSERT INTO student_interests (student_id, text) VALUES (?, ?)",
                        (row["id"], item),
                    )
        try:
            self.conn.execute("ALTER TABLE students DROP COLUMN interests")
        except sqlite3.OperationalError:
            pass  # older SQLite without DROP COLUMN support -- harmless if left behind

    def _migrate_journal_entries_allow_multiple_per_day(self) -> None:
        """journal_entries originally had UNIQUE (student_id, entry_date), so
        a second same-day check-in overwrote the first. Families running that
        version have rows saved under it; SQLite can't just drop a
        constraint, so this rebuilds the table without it, keeping every row
        that's already there."""
        table = _row(
            self.conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='journal_entries'"
            )
        )
        if table is None or "UNIQUE" not in (table["sql"] or ""):
            return  # no table yet, or already rebuilt without the constraint
        self.conn.execute("ALTER TABLE journal_entries RENAME TO journal_entries_old")
        self.conn.execute(
            "CREATE TABLE journal_entries ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,"
            "entry_date TEXT NOT NULL,"
            "feeling TEXT NOT NULL,"
            "note TEXT NOT NULL DEFAULT '',"
            "created_at TEXT NOT NULL DEFAULT (datetime('now'))"
            ")"
        )
        self.conn.execute(
            "INSERT INTO journal_entries "
            "(id, student_id, entry_date, feeling, note, created_at) "
            "SELECT id, student_id, entry_date, feeling, note, created_at "
            "FROM journal_entries_old"
        )
        self.conn.execute("DROP TABLE journal_entries_old")
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_journal_entries_student "
            "ON journal_entries (student_id, entry_date)"
        )

    def _migrate_books_allow_upcoming_status(self) -> None:
        """books.status had a CHECK constraint predating 'upcoming' (a
        second-half book queued but not yet the one current_book() returns)
        and there was no `term` column at all -- SQLite can't ALTER a CHECK
        constraint in place, so this rebuilds the table with both added,
        keeping every row (same id, so vocabulary.source_book_id's foreign
        key still points at the right one).

        Built new-name-first rather than rename-old-then-recreate, same
        reasoning as _migrate_activities_allow_projects_tier: renaming
        `books` away would leave vocabulary's foreign key permanently
        pointing at `books_old`."""
        table = _row(
            self.conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='books'"
            )
        )
        if table is None or "'upcoming'" in (table["sql"] or ""):
            return  # no table yet, or already rebuilt with the new status/column
        # Unlike _migrate_activities_allow_projects_tier (which runs first,
        # right after executescript's own commit), this one runs later in
        # migrate() -- an earlier migration may have left a transaction open,
        # and the foreign_keys pragma silently no-ops mid-transaction.
        self.conn.commit()
        self.conn.execute("PRAGMA foreign_keys = OFF")
        self.conn.execute(
            "CREATE TABLE books_new ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,"
            "title TEXT NOT NULL,"
            "author TEXT NOT NULL DEFAULT '',"
            "reading_level TEXT NOT NULL DEFAULT '',"
            "total_pages INTEGER,"
            "current_page INTEGER NOT NULL DEFAULT 0,"
            "status TEXT NOT NULL DEFAULT 'reading' "
            "CHECK (status IN ('reading', 'finished', 'abandoned', 'upcoming')),"
            "term TEXT CHECK (term IN ('first_half', 'second_half')),"
            "started_on TEXT,"
            "finished_on TEXT,"
            "notes TEXT NOT NULL DEFAULT '',"
            "created_at TEXT NOT NULL DEFAULT (datetime('now'))"
            ")"
        )
        self.conn.execute(
            "INSERT INTO books_new "
            "(id, student_id, title, author, reading_level, total_pages, current_page, "
            " status, started_on, finished_on, notes, created_at) "
            "SELECT id, student_id, title, author, reading_level, total_pages, current_page, "
            "status, started_on, finished_on, notes, created_at FROM books"
        )
        self.conn.execute("DROP TABLE books")
        self.conn.execute("ALTER TABLE books_new RENAME TO books")
        self.conn.commit()
        self.conn.execute("PRAGMA foreign_keys = ON")

    def _backfill_life_skill_content(self) -> None:
        """Fill in `description`/`materials` for catalog skills seeded before
        that text existed -- `seed_life_skills` only ever runs once per
        student, so a checklist seeded in an earlier build stays blank
        forever otherwise. Matched by exact title, and only when the field is
        still blank, so a parent's own edit is never overwritten."""
        for _, title, _, description, materials, _ in LIFE_SKILL_CATALOG:
            self.conn.execute(
                "UPDATE life_skills SET description = ? "
                "WHERE title = ? AND description = ''",
                (description, title),
            )
            self.conn.execute(
                "UPDATE life_skills SET materials = ? "
                "WHERE title = ? AND materials = ''",
                (materials, title),
            )

    def _backfill_life_skill_catalog(self) -> None:
        """Top up an already-seeded checklist with any catalog entries it's
        missing -- `seed_life_skills` only fires once per student, so a
        family that seeded before the catalog grew (the 13 "unlocked later"
        entries) would otherwise never see them at all, active or not.
        New entries always land inactive, regardless of their catalog
        default, since a parent who already curated their active set didn't
        ask for anything new to suddenly appear on the student's page."""
        for row in self.conn.execute("SELECT id FROM students"):
            student_id = row["id"]
            existing_titles = {
                r["title"]
                for r in self.conn.execute(
                    "SELECT title FROM life_skills WHERE student_id = ?", (student_id,)
                )
            }
            if not existing_titles:
                continue  # never seeded at all -- seed_life_skills handles that path
            for order, (category, title, subject, description, materials, _) in enumerate(
                LIFE_SKILL_CATALOG
            ):
                if title in existing_titles:
                    continue
                self.conn.execute(
                    "INSERT INTO life_skills "
                    "(student_id, category, title, credit_subject, description, "
                    "materials, active, sort_order) VALUES (?, ?, ?, ?, ?, ?, 0, ?)",
                    (student_id, category, title, subject, description, materials, order),
                )

    # -- settings -------------------------------------------------------------

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        row = _row(self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)))
        if row is None:
            return default if default is not None else config.DEFAULT_SETTINGS.get(key)
        return row["value"]

    def get_int_setting(self, key: str) -> int:
        raw = self.get_setting(key)
        try:
            return int(float(raw))
        except (TypeError, ValueError):
            return int(float(config.DEFAULT_SETTINGS[key]))

    def set_setting(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )
        self.conn.commit()

    # -- students -------------------------------------------------------------

    def list_students(self) -> list[dict[str, Any]]:
        return _rows(self.conn.execute("SELECT * FROM students ORDER BY id"))

    def get_student(self, student_id: int) -> dict[str, Any] | None:
        return _row(self.conn.execute("SELECT * FROM students WHERE id = ?", (student_id,)))

    def create_student(self, name: str, grade: str, age: int | None = None) -> int:
        cur = self.conn.execute(
            "INSERT INTO students (name, grade, age) VALUES (?, ?, ?)",
            (name, grade, age),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def update_student(self, student_id: int, **fields: Any) -> None:
        allowed = {"name", "grade", "age"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        assignments = ", ".join(f"{k} = ?" for k in updates)
        self.conn.execute(
            f"UPDATE students SET {assignments} WHERE id = ?",
            (*updates.values(), student_id),
        )
        self.conn.commit()

    def ensure_default_student(self) -> dict[str, Any]:
        """First-run convenience: seed the student described in the design doc."""
        students = self.list_students()
        if students:
            return students[0]
        student_id = self.create_student(name="Student", grade="8", age=13)
        return self.get_student(student_id)  # type: ignore[return-value]

    # -- interests --------------------------------------------------------------

    def add_interest(self, student_id: int, text: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO student_interests (student_id, text) VALUES (?, ?)",
            (student_id, text),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def list_interests(self, student_id: int) -> list[dict[str, Any]]:
        return _rows(
            self.conn.execute(
                "SELECT * FROM student_interests WHERE student_id = ? ORDER BY id",
                (student_id,),
            )
        )

    def delete_interest(self, interest_id: int) -> None:
        self.conn.execute("DELETE FROM student_interests WHERE id = ?", (interest_id,))
        self.conn.commit()

    def interests_text(self, student_id: int) -> str:
        """Comma-joined interests, for feeding into an agent's system prompt."""
        return ", ".join(i["text"] for i in self.list_interests(student_id))

    # -- math mastery ---------------------------------------------------------

    def mastery_map(self, student_id: int) -> dict[str, dict[str, Any]]:
        rows = _rows(
            self.conn.execute("SELECT * FROM skill_mastery WHERE student_id = ?", (student_id,))
        )
        return {r["skill_id"]: r for r in rows}

    def mastered_skills(self, student_id: int) -> set[str]:
        return {
            r["skill_id"]
            for r in _rows(
                self.conn.execute(
                    "SELECT skill_id FROM skill_mastery "
                    "WHERE student_id = ? AND status = 'mastered'",
                    (student_id,),
                )
            )
        }

    def set_mastery(
        self,
        student_id: int,
        skill_id: str,
        status: str,
        score: float | None = None,
        notes: str = "",
        assessed_on: str | None = None,
    ) -> None:
        if status not in ("not_started", "in_progress", "mastered"):
            raise ValueError(f"invalid mastery status: {status}")
        self.conn.execute(
            """
            INSERT INTO skill_mastery
                (student_id, skill_id, status, score, notes, assessed_on, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(student_id, skill_id) DO UPDATE SET
                status = excluded.status,
                score = excluded.score,
                notes = excluded.notes,
                assessed_on = excluded.assessed_on,
                updated_at = datetime('now')
            """,
            (
                student_id,
                skill_id,
                status,
                score,
                notes,
                assessed_on or date.today().isoformat(),
            ),
        )
        self.conn.commit()

    # -- topic web (spiderweb strategies) -------------------------------------

    def add_web_node(
        self,
        student_id: int,
        agent: str,
        topic: str,
        rationale: str = "",
        location: str = "",
        parent_id: int | None = None,
        depth: int = 0,
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO topic_web "
            "(student_id, agent, topic, rationale, location, parent_id, depth) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (student_id, agent, topic, rationale, location, parent_id, depth),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def unexplored_web_nodes(
        self, student_id: int, agent: str, location: str | None = None
    ) -> list[dict[str, Any]]:
        """Candidate next topics, location-relevant ones first, then shallowest."""
        rows = _rows(
            self.conn.execute(
                "SELECT * FROM topic_web "
                "WHERE student_id = ? AND agent = ? AND explored_on IS NULL "
                "ORDER BY depth ASC, id ASC",
                (student_id, agent),
            )
        )
        if location:
            needle = location.strip().lower()
            rows.sort(key=lambda r: 0 if needle and needle in r["location"].lower() else 1)
        return rows

    def explored_topics(self, student_id: int, agent: str) -> list[str]:
        return [
            r["topic"]
            for r in _rows(
                self.conn.execute(
                    "SELECT topic FROM topic_web "
                    "WHERE student_id = ? AND agent = ? AND explored_on IS NOT NULL "
                    "ORDER BY explored_on DESC",
                    (student_id, agent),
                )
            )
        ]

    def mark_web_node_explored(self, node_id: int) -> None:
        self.conn.execute(
            "UPDATE topic_web SET explored_on = date('now') WHERE id = ?", (node_id,)
        )
        self.conn.commit()

    def get_web_node(self, node_id: int) -> dict[str, Any] | None:
        return _row(self.conn.execute("SELECT * FROM topic_web WHERE id = ?", (node_id,)))

    def delete_web_node(self, node_id: int) -> None:
        """Drop a branch nobody intends to follow.

        Children are re-parented by the schema's ON DELETE SET NULL rather than
        cascading — a grandchild topic is still a perfectly good lesson, and
        deleting a branch shouldn't silently take a subtree with it.
        """
        self.conn.execute("DELETE FROM topic_web WHERE id = ?", (node_id,))
        self.conn.commit()

    def web_nodes(self, student_id: int, agent: str) -> list[dict[str, Any]]:
        return _rows(
            self.conn.execute(
                "SELECT * FROM topic_web WHERE student_id = ? AND agent = ? ORDER BY id",
                (student_id, agent),
            )
        )

    # -- books ----------------------------------------------------------------

    def list_books(self, student_id: int, status: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM books WHERE student_id = ?"
        params: list[Any] = [student_id]
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY (status = 'reading') DESC, id DESC"
        return _rows(self.conn.execute(sql, params))

    def current_book(self, student_id: int) -> dict[str, Any] | None:
        return _row(
            self.conn.execute(
                "SELECT * FROM books WHERE student_id = ? AND status = 'reading' "
                "ORDER BY id DESC LIMIT 1",
                (student_id,),
            )
        )

    def add_book(
        self,
        student_id: int,
        title: str,
        author: str = "",
        reading_level: str = "",
        total_pages: int | None = None,
        notes: str = "",
        term: str | None = None,
        status: str = "reading",
    ) -> int:
        """`term` tags a book to a half of the school year
        ('first_half'/'second_half') for a family running two books, one per
        half; leave it `None` for an ad hoc pick with no such split -- the
        old, still-default behavior. Pass `status='upcoming'` to add a
        second-half book now without making it the one current_book()
        returns yet; started_on is only stamped for a book that starts
        reading immediately, since an upcoming book gets its own
        started_on once promote_upcoming_book actually starts it."""
        cur = self.conn.execute(
            "INSERT INTO books "
            "(student_id, title, author, reading_level, total_pages, notes, "
            " term, status, started_on) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                student_id, title, author, reading_level, total_pages, notes,
                term, status, date.today().isoformat() if status == "reading" else None,
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def upcoming_book(self, student_id: int) -> dict[str, Any] | None:
        """The book queued for later in the year, if any -- see
        current_book for the one actually in use right now."""
        return _row(
            self.conn.execute(
                "SELECT * FROM books WHERE student_id = ? AND status = 'upcoming' "
                "ORDER BY id ASC LIMIT 1",
                (student_id,),
            )
        )

    def promote_upcoming_book(self, student_id: int, book_id: int) -> None:
        """Makes `book_id` (assumed status='upcoming') the current book:
        whatever's currently 'reading' is marked finished, and this one
        starts. Not tied to any date -- a parent can call this the moment
        he actually finishes the first book, whether that's early, on
        schedule, or late."""
        self.conn.execute(
            "UPDATE books SET status = 'finished', finished_on = date('now') "
            "WHERE student_id = ? AND status = 'reading'",
            (student_id,),
        )
        self.conn.execute(
            "UPDATE books SET status = 'reading', started_on = date('now') WHERE id = ?",
            (book_id,),
        )
        self.conn.commit()

    def update_book(self, book_id: int, **fields: Any) -> None:
        allowed = {
            "title",
            "author",
            "reading_level",
            "total_pages",
            "current_page",
            "status",
            "notes",
            "finished_on",
            "ai_summary",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        if updates.get("status") == "finished" and "finished_on" not in updates:
            updates["finished_on"] = date.today().isoformat()
        assignments = ", ".join(f"{k} = ?" for k in updates)
        self.conn.execute(
            f"UPDATE books SET {assignments} WHERE id = ?", (*updates.values(), book_id)
        )
        self.conn.commit()

    # -- vocabulary (Leitner spaced repetition) -------------------------------

    def add_vocabulary(
        self,
        student_id: int,
        word: str,
        definition: str = "",
        source_book_id: int | None = None,
    ) -> None:
        self.conn.execute(
            "INSERT INTO vocabulary "
            "(student_id, word, definition, source_book_id, box, next_review_on) "
            "VALUES (?, ?, ?, ?, 1, date('now', '+1 day')) "
            "ON CONFLICT(student_id, word) DO UPDATE SET "
            "  definition = CASE WHEN excluded.definition != '' "
            "               THEN excluded.definition ELSE vocabulary.definition END",
            (student_id, word.strip(), definition, source_book_id),
        )
        self.conn.commit()

    def vocabulary_due(self, student_id: int, limit: int = 12) -> list[dict[str, Any]]:
        return _rows(
            self.conn.execute(
                "SELECT * FROM vocabulary WHERE student_id = ? AND next_review_on <= date('now') "
                "ORDER BY box ASC, next_review_on ASC LIMIT ?",
                (student_id, limit),
            )
        )

    def list_vocabulary(self, student_id: int) -> list[dict[str, Any]]:
        return _rows(
            self.conn.execute(
                "SELECT * FROM vocabulary WHERE student_id = ? "
                "ORDER BY next_review_on ASC, word ASC",
                (student_id,),
            )
        )

    def record_vocabulary_review(self, vocab_id: int, correct: bool) -> None:
        row = _row(self.conn.execute("SELECT * FROM vocabulary WHERE id = ?", (vocab_id,)))
        if row is None:
            return
        box = min(row["box"] + 1, 5) if correct else 1
        interval = LEITNER_INTERVALS[box]
        next_review = (date.today() + timedelta(days=interval)).isoformat()
        self.conn.execute(
            "UPDATE vocabulary SET box = ?, next_review_on = ?, "
            "times_correct = times_correct + ?, times_missed = times_missed + ? "
            "WHERE id = ?",
            (box, next_review, 1 if correct else 0, 0 if correct else 1, vocab_id),
        )
        self.conn.commit()

    # -- lessons --------------------------------------------------------------

    def save_lesson(
        self,
        student_id: int,
        agent: str,
        subject: str,
        topic: str,
        title: str,
        payload: dict[str, Any],
        strategy: str = "",
        rationale: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO lessons "
            "(student_id, agent, subject, topic, title, strategy, rationale, payload, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                student_id,
                agent,
                subject,
                topic,
                title,
                strategy,
                rationale,
                json.dumps(payload),
                json.dumps(metadata or {}),
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def get_lesson(self, lesson_id: int) -> dict[str, Any] | None:
        row = _row(self.conn.execute("SELECT * FROM lessons WHERE id = ?", (lesson_id,)))
        if row:
            row["payload"] = json.loads(row["payload"])
            row["metadata"] = json.loads(row["metadata"])
        return row

    def list_lessons(
        self, student_id: int, agent: str | None = None, limit: int = 25
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM lessons WHERE student_id = ?"
        params: list[Any] = [student_id]
        if agent:
            sql += " AND agent = ?"
            params.append(agent)
        sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
        params.append(limit)
        rows = _rows(self.conn.execute(sql, params))
        for row in rows:
            row["payload"] = json.loads(row["payload"])
            row["metadata"] = json.loads(row["metadata"])
        return rows

    def lessons_for_week(self, student_id: int, week_start: str) -> list[dict[str, Any]]:
        """Every lesson planned for one Monday-anchored week, earliest planned
        day first -- the raw material for both halves of `pages/14_This_Week.py`.

        Matched on `metadata.week_start`, not `created_at`: a lesson planned
        on Friday for the following Tuesday still belongs to *that* week's
        plan regardless of when it was actually generated.
        """
        rows = _rows(
            self.conn.execute(
                "SELECT * FROM lessons WHERE student_id = ? "
                "AND json_extract(metadata, '$.week_start') = ? "
                "ORDER BY json_extract(metadata, '$.planned_for'), id",
                (student_id, week_start),
            )
        )
        for row in rows:
            row["payload"] = json.loads(row["payload"])
            row["metadata"] = json.loads(row["metadata"])
        return rows

    def latest_life_skill_plan(self, student_id: int, skill_id: int) -> dict[str, Any] | None:
        """The most recent generated plan for one life skill, if there is one.

        Matched on the metadata rather than the title so that renaming a skill
        doesn't orphan its plan.
        """
        row = _row(
            self.conn.execute(
                "SELECT * FROM lessons WHERE student_id = ? AND agent = 'life_skills' "
                "AND json_extract(metadata, '$.life_skill_id') = ? "
                "ORDER BY created_at DESC, id DESC LIMIT 1",
                (student_id, skill_id),
            )
        )
        if row:
            row["payload"] = json.loads(row["payload"])
            row["metadata"] = json.loads(row["metadata"])
        return row

    def lesson_usage_between(
        self, student_id: int, start: str, end: str
    ) -> list[dict[str, Any]]:
        """Per-lesson token usage, by *generation* date.

        Generation date, not activity date — a lesson written in March and taught
        in April is billed in March.

        Pulls the `_usage` fields out with SQL rather than loading each payload
        and parsing it in Python. A full school year is several hundred lessons,
        and each payload carries the entire lesson text; deserializing all of it
        to read six integers would make this page crawl by spring.
        """
        return _rows(
            self.conn.execute(
                """
                SELECT
                    agent,
                    date(created_at) AS generated_on,
                    json_extract(payload, '$._usage.model')                       AS model,
                    json_extract(payload, '$._usage.input_tokens')                AS input_tokens,
                    json_extract(payload, '$._usage.output_tokens')               AS output_tokens,
                    json_extract(payload, '$._usage.cache_read_input_tokens')     AS cache_read_input_tokens,
                    json_extract(payload, '$._usage.cache_creation_input_tokens') AS cache_creation_input_tokens,
                    json_extract(payload, '$._usage.web_searches')                AS web_searches
                FROM lessons
                WHERE student_id = ? AND date(created_at) BETWEEN ? AND ?
                ORDER BY created_at DESC, id DESC
                """,
                (student_id, start, end),
            )
        )

    def set_lesson_status(self, lesson_id: int, status: str) -> None:
        if status not in ("planned", "completed", "skipped"):
            raise ValueError(f"invalid lesson status: {status}")
        self.conn.execute("UPDATE lessons SET status = ? WHERE id = ?", (status, lesson_id))
        self.conn.commit()

    def delete_lesson(self, lesson_id: int) -> None:
        """For a planned lesson nobody wants -- an accidental double-generate,
        say. Safe even if it was already logged: `activities.lesson_id` is
        `ON DELETE SET NULL`, so a logged activity just loses the back-link,
        not its own hours or credit."""
        self.conn.execute("DELETE FROM lessons WHERE id = ?", (lesson_id,))
        self.conn.commit()

    def mark_student_done(self, lesson_id: int) -> None:
        """The student's own "I'm done for today" signal.

        Deliberately separate from `status`, which only changes when the parent
        logs actual hours: this only controls what he sees as current versus
        past, and never touches hours, credits, or the compliance record.
        """
        self.conn.execute(
            "UPDATE lessons SET metadata = json_set(metadata, '$.student_done_on', ?) "
            "WHERE id = ?",
            (date.today().isoformat(), lesson_id),
        )
        self.conn.commit()

    def record_quiz_result(self, lesson_id: int, correct: int, total: int, passed: bool) -> None:
        """Stash the graded score into the lesson's metadata, alongside the
        strategy metadata already stored there (skill_id, era, and so on)."""
        self.conn.execute(
            "UPDATE lessons SET metadata = json_set(metadata, '$.quiz_result', json(?)) "
            "WHERE id = ?",
            (
                json.dumps(
                    {
                        "correct": correct,
                        "total": total,
                        "passed": passed,
                        "graded_on": date.today().isoformat(),
                    }
                ),
                lesson_id,
            ),
        )
        self.conn.commit()

    # -- activities and multi-subject credits ---------------------------------

    def log_activity(
        self,
        student_id: int,
        title: str,
        tier: str,
        primary_subject: str,
        minutes: int,
        subject_credits: dict[str, int],
        occurred_on: str | None = None,
        description: str = "",
        source: str = "manual",
        location: str = "",
        lesson_id: int | None = None,
    ) -> int:
        """Log instructional time, crediting one or more of the 11 WA subjects.

        `minutes` is the real elapsed time and is what counts toward the 1,000-hour
        floor. `subject_credits` may sum to more than `minutes` — that is Tier 2
        folding working as intended.
        """
        if minutes <= 0:
            raise ValueError("minutes must be positive")
        if not subject_credits:
            subject_credits = {primary_subject: minutes}

        cur = self.conn.execute(
            "INSERT INTO activities "
            "(student_id, lesson_id, title, description, tier, primary_subject, "
            " source, minutes, occurred_on, location) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                student_id,
                lesson_id,
                title,
                description,
                tier,
                primary_subject,
                source,
                int(minutes),
                occurred_on or date.today().isoformat(),
                location,
            ),
        )
        activity_id = int(cur.lastrowid)
        for subject, credit in subject_credits.items():
            credit = int(credit)
            if credit <= 0:
                continue
            self.conn.execute(
                "INSERT INTO activity_subject_credits (activity_id, subject, minutes) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(activity_id, subject) DO UPDATE SET minutes = excluded.minutes",
                (activity_id, subject, credit),
            )
        if lesson_id is not None:
            self.set_lesson_status(lesson_id, "completed")
        self.conn.commit()
        return activity_id

    def list_activities(
        self,
        student_id: int,
        start: str | None = None,
        end: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM activities WHERE student_id = ?"
        params: list[Any] = [student_id]
        if start:
            sql += " AND occurred_on >= ?"
            params.append(start)
        if end:
            sql += " AND occurred_on <= ?"
            params.append(end)
        sql += " ORDER BY occurred_on DESC, id DESC"
        if limit:
            sql += " LIMIT ?"
            params.append(limit)
        activities = _rows(self.conn.execute(sql, params))
        if not activities:
            return []
        ids = [a["id"] for a in activities]
        placeholders = ",".join("?" for _ in ids)
        credits = _rows(
            self.conn.execute(
                "SELECT * FROM activity_subject_credits "
                f"WHERE activity_id IN ({placeholders})",
                ids,
            )
        )
        by_activity: dict[int, dict[str, int]] = {}
        for credit in credits:
            by_activity.setdefault(credit["activity_id"], {})[credit["subject"]] = credit[
                "minutes"
            ]
        for activity in activities:
            activity["credits"] = by_activity.get(activity["id"], {})
        return activities

    def delete_activity(self, activity_id: int) -> None:
        self.conn.execute("DELETE FROM activities WHERE id = ?", (activity_id,))
        self.conn.commit()

    # -- Tier 3 choice topics -------------------------------------------------

    def list_choice_topics(self, student_id: int) -> list[dict[str, Any]]:
        return _rows(
            self.conn.execute(
                "SELECT * FROM choice_topics WHERE student_id = ? "
                "ORDER BY CASE status WHEN 'active' THEN 0 WHEN 'approved' THEN 1 "
                "WHEN 'proposed' THEN 2 WHEN 'done' THEN 3 ELSE 4 END, id DESC",
                (student_id,),
            )
        )

    def add_choice_topic(
        self,
        student_id: int,
        title: str,
        description: str = "",
        category: str = "",
        credit_subject: str = "occupational_education",
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO choice_topics "
            "(student_id, title, description, category, credit_subject) VALUES (?, ?, ?, ?, ?)",
            (student_id, title, description, category, credit_subject),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def set_choice_status(self, topic_id: int, status: str, parent_note: str = "") -> None:
        self.conn.execute(
            "UPDATE choice_topics SET status = ?, decided_on = date('now'), "
            "parent_note = CASE WHEN ? != '' THEN ? ELSE parent_note END WHERE id = ?",
            (status, parent_note, parent_note, topic_id),
        )
        self.conn.commit()

    def delete_choice_topic(self, topic_id: int) -> None:
        self.conn.execute("DELETE FROM choice_topics WHERE id = ?", (topic_id,))
        self.conn.commit()

    # -- Landon's Travels ---------------------------------------------------------

    def add_travel_entry(
        self,
        student_id: int,
        state: str,
        visited_on: str,
        title: str = "",
        story: str = "",
        park_key: str | None = None,
        favorite_moment: str = "",
        would_return: str = "",
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO travel_entries "
            "(student_id, state, park_key, title, story, favorite_moment, would_return, visited_on) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (student_id, state, park_key, title, story, favorite_moment, would_return, visited_on),
        )
        self.conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def list_travel_entries(self, student_id: int) -> list[dict[str, Any]]:
        return _rows(
            self.conn.execute(
                "SELECT * FROM travel_entries WHERE student_id = ? "
                "ORDER BY visited_on DESC, id DESC",
                (student_id,),
            )
        )

    def update_travel_entry(self, entry_id: int, **fields: Any) -> None:
        allowed = {
            "state", "park_key", "title", "story", "visited_on",
            "favorite_moment", "would_return",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        assignments = ", ".join(f"{k} = ?" for k in updates)
        self.conn.execute(
            f"UPDATE travel_entries SET {assignments} WHERE id = ?",
            (*updates.values(), entry_id),
        )
        self.conn.commit()

    def delete_travel_entry(self, entry_id: int) -> None:
        self.conn.execute("DELETE FROM travel_entries WHERE id = ?", (entry_id,))
        self.conn.commit()

    # -- Check-In (daily feelings journal) -------------------------------------

    def save_journal_entry(
        self, student_id: int, entry_date: str, feeling: str, note: str = ""
    ) -> int:
        """Every check-in is its own row -- a second one the same day sits
        alongside the first rather than replacing it, so a rough afternoon
        doesn't erase a fine morning from the record.

        created_at is stamped here in local time rather than left to the
        column's `datetime('now')` default (UTC) -- multiple entries in a
        day need a time-of-day a parent can actually read against the wall
        clock, not one that's off by the server's UTC offset."""
        cur = self.conn.execute(
            "INSERT INTO journal_entries (student_id, entry_date, feeling, note, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (student_id, entry_date, feeling, note, datetime.now().isoformat(sep=" ", timespec="seconds")),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def list_journal_entries(self, student_id: int, limit: int = 60) -> list[dict[str, Any]]:
        return _rows(
            self.conn.execute(
                "SELECT * FROM journal_entries WHERE student_id = ? "
                "ORDER BY entry_date DESC, id DESC LIMIT ?",
                (student_id, limit),
            )
        )

    def journal_entry_for_date(self, student_id: int, entry_date: str) -> dict[str, Any] | None:
        """Most recent check-in for that date, if any -- there can be more
        than one now, so this is "has he checked in today," not "the" entry."""
        return _row(
            self.conn.execute(
                "SELECT * FROM journal_entries WHERE student_id = ? AND entry_date = ? "
                "ORDER BY id DESC LIMIT 1",
                (student_id, entry_date),
            )
        )

    def delete_journal_entry(self, entry_id: int) -> None:
        self.conn.execute("DELETE FROM journal_entries WHERE id = ?", (entry_id,))
        self.conn.commit()

    # -- Big Projects (multi-step, sprint-style creative projects) ------------

    def list_big_projects(self, student_id: int) -> list[dict[str, Any]]:
        return _rows(
            self.conn.execute(
                "SELECT * FROM big_projects WHERE student_id = ? "
                "ORDER BY sort_order, id",
                (student_id,),
            )
        )

    def add_big_project(self, student_id: int, title: str, vision: str = "") -> int:
        next_order = self.conn.execute(
            "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM big_projects WHERE student_id = ?",
            (student_id,),
        ).fetchone()[0]
        cur = self.conn.execute(
            "INSERT INTO big_projects (student_id, title, vision, sort_order) "
            "VALUES (?, ?, ?, ?)",
            (student_id, title, vision, next_order),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def delete_big_project(self, project_id: int) -> None:
        self.conn.execute("DELETE FROM big_projects WHERE id = ?", (project_id,))
        self.conn.commit()

    def set_big_project_shelved(self, project_id: int, shelved: bool) -> None:
        """"Not an interest" -- a reversible parent-only back-burner, not a
        delete. Unlike delete_big_project, a shelved row survives migrate()'s
        catalog top-up (_backfill_big_project_catalog matches on title
        regardless of shelved), so shelving one of the starter catalog
        projects actually sticks across restarts instead of it quietly
        reappearing.

        Shelving the project he's actually working on this year also clears
        that pick -- "not an interest" and "the one you're working on" can't
        both be true, and leaving the old pick in place would have Friday's
        nudge (and everything else that reads active_big_project) still
        pointing at a project he just said he doesn't want."""
        self.conn.execute(
            "UPDATE big_projects SET shelved = ? WHERE id = ?", (int(shelved), project_id)
        )
        if shelved and self.get_setting("active_big_project_id") == str(project_id):
            self.set_setting("active_big_project_id", "")
        self.conn.commit()

    def active_big_project(self, student_id: int) -> dict[str, Any] | None:
        """The one project he's actually committed to working through this
        year, chosen on Big Projects -- Friday's nudge points at this
        specifically instead of guessing at an arbitrary project with steps
        left. None until he's deliberately picked one, which is the point:
        there's no default. Self-healing if the chosen project was since
        deleted -- the lookup just comes back empty, same as never having
        picked one, with nothing extra to clean up.
        """
        raw = self.get_setting("active_big_project_id")
        if not raw:
            return None
        return _row(
            self.conn.execute(
                "SELECT * FROM big_projects WHERE id = ? AND student_id = ?",
                (int(raw), student_id),
            )
        )

    def set_active_big_project(self, project_id: int | None) -> None:
        self.set_setting("active_big_project_id", str(project_id) if project_id else "")

    def list_project_steps(self, project_id: int) -> list[dict[str, Any]]:
        return _rows(
            self.conn.execute(
                "SELECT * FROM project_steps WHERE project_id = ? "
                "ORDER BY sort_order, id",
                (project_id,),
            )
        )

    def add_project_step(
        self,
        project_id: int,
        title: str,
        description: str = "",
        materials: str = "",
        credit_subject: str = "occupational_education",
        min_days: int = 1,
        max_days: int = 1,
    ) -> int:
        next_order = self.conn.execute(
            "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM project_steps WHERE project_id = ?",
            (project_id,),
        ).fetchone()[0]
        cur = self.conn.execute(
            "INSERT INTO project_steps "
            "(project_id, sort_order, title, description, materials, credit_subject, "
            " min_days, max_days) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (project_id, next_order, title, description, materials, credit_subject,
             max(1, min_days), max(min_days, max_days)),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def set_project_step_done(self, step_id: int, completed: bool) -> None:
        self.conn.execute(
            "UPDATE project_steps SET completed_on = ? WHERE id = ?",
            (date.today().isoformat() if completed else None, step_id),
        )
        self.conn.commit()

    def delete_project_step(self, step_id: int) -> None:
        self.conn.execute("DELETE FROM project_steps WHERE id = ?", (step_id,))
        self.conn.commit()

    def _insert_big_project(
        self,
        student_id: int,
        sort_order: int,
        title: str,
        vision: str,
        steps: Sequence[tuple[str, str, str, str, int, int]],
    ) -> int:
        project_id = self.conn.execute(
            "INSERT INTO big_projects (student_id, title, vision, sort_order) "
            "VALUES (?, ?, ?, ?)",
            (student_id, title, vision, sort_order),
        ).lastrowid
        for step_order, (
            step_title, description, materials, credit_subject, min_days, max_days,
        ) in enumerate(steps):
            self.conn.execute(
                "INSERT INTO project_steps "
                "(project_id, sort_order, title, description, materials, credit_subject, "
                " min_days, max_days) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (project_id, step_order, step_title, description, materials, credit_subject,
                 min_days, max_days),
            )
        return int(project_id)

    def seed_big_projects(self, student_id: int) -> int:
        """Seed the starter catalog, once -- a family that already added its
        own project (or deleted every starter one on purpose) never gets it
        pushed back on them. `_backfill_big_project_catalog` is the top-up
        path for a family that already seeded before the catalog grew."""
        if self.list_big_projects(student_id):
            return 0
        for order, (title, vision, steps) in enumerate(BIG_PROJECT_CATALOG):
            self._insert_big_project(student_id, order, title, vision, steps)
        self.conn.commit()
        return len(BIG_PROJECT_CATALOG)

    def _backfill_big_project_catalog(self) -> None:
        """Top up a family that already seeded projects with any catalog
        projects they're missing -- `seed_big_projects` only fires once per
        student, so a family that seeded before the catalog grew (e.g. the
        podcast and toy photography projects, added after the Lego film)
        would otherwise never see them at all. Matched by title, shelved or
        not, so a project the parent shelved (see set_big_project_shelved)
        stays gone -- it's still a row, just not a *missing* one. Never
        touches a project that's already there."""
        for row in self.conn.execute("SELECT id FROM students"):
            student_id = row["id"]
            existing_titles = {
                r["title"]
                for r in self.conn.execute(
                    "SELECT title FROM big_projects WHERE student_id = ?", (student_id,)
                )
            }
            if not existing_titles:
                continue  # never seeded at all -- seed_big_projects handles that path
            next_order = self.conn.execute(
                "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM big_projects WHERE student_id = ?",
                (student_id,),
            ).fetchone()[0]
            for title, vision, steps in BIG_PROJECT_CATALOG:
                if title in existing_titles:
                    continue
                self._insert_big_project(student_id, next_order, title, vision, steps)
                next_order += 1

    def _backfill_big_project_step_content(self) -> None:
        """Keeps an already-seeded starter project's step text (and pace)
        in sync with BIG_PROJECT_CATALOG when the catalog copy itself is
        revised (e.g. adding more detail, or adding day-range guidance).
        Unlike life skills' backfill this isn't guarding a parent's own
        edit -- there's no per-step edit UI -- so it overwrites
        unconditionally rather than only when blank. Matched by (project
        title, step title); never touches `completed_on`, so a step he's
        already checked off stays checked."""
        for project_title, _, steps in BIG_PROJECT_CATALOG:
            for project in _rows(
                self.conn.execute(
                    "SELECT id FROM big_projects WHERE title = ?", (project_title,)
                )
            ):
                for step_title, description, materials, credit_subject, min_days, max_days in steps:
                    self.conn.execute(
                        "UPDATE project_steps SET description = ?, materials = ?, "
                        "credit_subject = ?, min_days = ?, max_days = ? "
                        "WHERE project_id = ? AND title = ?",
                        (description, materials, credit_subject, min_days, max_days,
                         project["id"], step_title),
                    )

    # -- Core life skills -----------------------------------------------------

    def list_life_skills(self, student_id: int) -> list[dict[str, Any]]:
        return _rows(
            self.conn.execute(
                "SELECT * FROM life_skills WHERE student_id = ? "
                "ORDER BY category, sort_order, id",
                (student_id,),
            )
        )

    def add_life_skill(
        self,
        student_id: int,
        title: str,
        category: str = "General",
        description: str = "",
        credit_subject: str = "occupational_education",
        materials: str = "",
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO life_skills "
            "(student_id, title, category, description, credit_subject, materials) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (student_id, title, category, description, credit_subject, materials),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def set_life_skill_done(
        self, skill_id: int, completed: bool, notes: str = ""
    ) -> None:
        self.conn.execute(
            "UPDATE life_skills SET completed_on = ?, "
            "notes = CASE WHEN ? != '' THEN ? ELSE notes END WHERE id = ?",
            (date.today().isoformat() if completed else None, notes, notes, skill_id),
        )
        self.conn.commit()

    def set_life_skill_active(self, skill_id: int, active: bool) -> None:
        """Unlocks or hides a catalog skill from the student view. Never
        touches `completed_on` -- an already-earned skill stays visible to
        him regardless (see the `active OR completed_on` filter at the call
        site), so this only ever affects what's still ahead of him."""
        self.conn.execute(
            "UPDATE life_skills SET active = ? WHERE id = ?", (int(active), skill_id)
        )
        self.conn.commit()

    def delete_life_skill(self, skill_id: int) -> None:
        self.conn.execute("DELETE FROM life_skills WHERE id = ?", (skill_id,))
        self.conn.commit()

    def seed_life_skills(self, student_id: int) -> int:
        """Seed the full master catalog, once. Whether a skill starts
        unlocked is the catalog's own `active` default -- see
        `LIFE_SKILL_CATALOG`."""
        existing = self.list_life_skills(student_id)
        if existing:
            return 0
        for order, (category, title, subject, description, materials, active) in enumerate(
            LIFE_SKILL_CATALOG
        ):
            self.conn.execute(
                "INSERT INTO life_skills "
                "(student_id, category, title, credit_subject, description, materials, "
                "active, sort_order) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (student_id, category, title, subject, description, materials, int(active), order),
            )
        self.conn.commit()
        return len(LIFE_SKILL_CATALOG)

    # -- Declaration of Intent (WA RCW 28A.200.010) ---------------------------

    def declaration_status(self, student_id: int, due_on: str) -> dict[str, Any] | None:
        return _row(
            self.conn.execute(
                "SELECT * FROM declarations_of_intent WHERE student_id = ? AND due_on = ?",
                (student_id, due_on),
            )
        )

    def mark_declaration_filed(
        self, student_id: int, due_on: str, filed_on: str | None = None
    ) -> None:
        self.conn.execute(
            "INSERT INTO declarations_of_intent (student_id, due_on, filed_on) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(student_id, due_on) DO UPDATE SET filed_on = excluded.filed_on",
            (student_id, due_on, filed_on or date.today().isoformat()),
        )
        self.conn.commit()

    def clear_declaration_filed(self, student_id: int, due_on: str) -> None:
        self.conn.execute(
            "UPDATE declarations_of_intent SET filed_on = NULL "
            "WHERE student_id = ? AND due_on = ?",
            (student_id, due_on),
        )
        self.conn.commit()

    # -- district documents -----------------------------------------------------

    def save_district_document(
        self,
        student_id: int,
        category: str,
        filename: str,
        content: bytes,
        content_type: str = "application/pdf",
    ) -> None:
        """Uploading again replaces whatever was there for this category --
        one current copy per (student, category), not a growing pile of
        every year's packet."""
        self.conn.execute(
            "INSERT INTO district_documents "
            "(student_id, category, filename, content_type, content) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(student_id, category) DO UPDATE SET "
            "filename = excluded.filename, content_type = excluded.content_type, "
            "content = excluded.content, uploaded_on = datetime('now')",
            (student_id, category, filename, content_type, content),
        )
        self.conn.commit()

    def get_district_document(self, student_id: int, category: str) -> dict[str, Any] | None:
        return _row(
            self.conn.execute(
                "SELECT * FROM district_documents WHERE student_id = ? AND category = ?",
                (student_id, category),
            )
        )

    def delete_district_document(self, student_id: int, category: str) -> None:
        self.conn.execute(
            "DELETE FROM district_documents WHERE student_id = ? AND category = ?",
            (student_id, category),
        )
        self.conn.commit()

    # -- morning routine --------------------------------------------------------

    def log_morning_routine(self, student_id: int, entry_date: str, routine_key: str) -> None:
        """One per student per day -- picking a different routine the same
        day replaces the record rather than stacking, unlike Check-In."""
        self.conn.execute(
            "INSERT INTO morning_routine_log (student_id, entry_date, routine_key) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(student_id, entry_date) DO UPDATE SET "
            "routine_key = excluded.routine_key, completed_at = datetime('now')",
            (student_id, entry_date, routine_key),
        )
        self.conn.commit()

    def morning_routine_for_date(self, student_id: int, entry_date: str) -> dict[str, Any] | None:
        return _row(
            self.conn.execute(
                "SELECT * FROM morning_routine_log WHERE student_id = ? AND entry_date = ?",
                (student_id, entry_date),
            )
        )

    # -- Friday plan items --------------------------------------------------------

    def list_friday_plan_items(self, student_id: int, plan_date: str) -> list[dict[str, Any]]:
        return _rows(
            self.conn.execute(
                "SELECT * FROM friday_plan_items WHERE student_id = ? AND plan_date = ? "
                "ORDER BY sort_order, id",
                (student_id, plan_date),
            )
        )

    def add_friday_plan_item(
        self, student_id: int, plan_date: str, kind: str, label: str = ""
    ) -> int:
        next_order = self.conn.execute(
            "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM friday_plan_items "
            "WHERE student_id = ? AND plan_date = ?",
            (student_id, plan_date),
        ).fetchone()[0]
        cur = self.conn.execute(
            "INSERT INTO friday_plan_items "
            "(student_id, plan_date, kind, label, sort_order) VALUES (?, ?, ?, ?, ?)",
            (student_id, plan_date, kind, label, next_order),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def delete_friday_plan_item(self, item_id: int) -> None:
        self.conn.execute("DELETE FROM friday_plan_items WHERE id = ?", (item_id,))
        self.conn.commit()

    # -- courses (grades 6-12 credit documentation) ----------------------------

    def create_course(
        self,
        student_id: int,
        title: str,
        credit_subject: str,
        start_date: str,
        end_date: str,
        grade_level: str = "",
        description: str = "",
        goals: str = "",
        outline: str = "",
        credit_value: float = 1.0,
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO courses "
            "(student_id, title, credit_subject, grade_level, description, goals, "
            " outline, credit_value, start_date, end_date) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                student_id, title, credit_subject, grade_level, description, goals,
                outline, credit_value, start_date, end_date,
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def list_courses(self, student_id: int) -> list[dict[str, Any]]:
        return _rows(
            self.conn.execute(
                "SELECT * FROM courses WHERE student_id = ? ORDER BY start_date DESC, id DESC",
                (student_id,),
            )
        )

    def get_course(self, course_id: int) -> dict[str, Any] | None:
        return _row(self.conn.execute("SELECT * FROM courses WHERE id = ?", (course_id,)))

    def update_course(self, course_id: int, **fields: Any) -> None:
        allowed = {
            "title", "credit_subject", "grade_level", "description", "goals", "outline",
            "credit_value", "start_date", "end_date", "final_grade", "pass_fail",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        assignments = ", ".join(f"{k} = ?" for k in updates)
        self.conn.execute(
            f"UPDATE courses SET {assignments} WHERE id = ?",
            (*updates.values(), course_id),
        )
        self.conn.commit()

    def delete_course(self, course_id: int) -> None:
        """The activities logged toward this course aren't deleted -- the
        column's own ON DELETE SET NULL just untags them, so the hours stay
        on the compliance dashboard where they always counted."""
        self.conn.execute("DELETE FROM courses WHERE id = ?", (course_id,))
        self.conn.commit()

    def candidate_activities_for_course(
        self,
        student_id: int,
        credit_subject: str,
        start_date: str,
        end_date: str,
        course_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """Activities that could plausibly count toward this course: right
        subject, right date range, and not already claimed by a *different*
        course. Activities already tagged to this course itself are included
        too, so the picker shows the current state, not just what's still up
        for grabs."""
        return _rows(
            self.conn.execute(
                "SELECT * FROM activities WHERE student_id = ? AND primary_subject = ? "
                "AND occurred_on BETWEEN ? AND ? AND (course_id IS NULL OR course_id = ?) "
                "ORDER BY occurred_on, id",
                (student_id, credit_subject, start_date, end_date, course_id),
            )
        )

    def set_activity_course(self, activity_id: int, course_id: int | None) -> None:
        self.conn.execute(
            "UPDATE activities SET course_id = ? WHERE id = ?", (course_id, activity_id)
        )
        self.conn.commit()

    def course_activities(self, course_id: int) -> list[dict[str, Any]]:
        """Every activity tagged to this course, each carrying its full
        lesson (assignment content, assessment description, quiz result)
        when it came from one -- that lesson detail is exactly what the
        district's "assignments and assessments" and "how performance is
        assessed" requirements need, and it's already sitting in `lessons`
        rather than something this table has to duplicate."""
        activities = _rows(
            self.conn.execute(
                "SELECT * FROM activities WHERE course_id = ? ORDER BY occurred_on, id",
                (course_id,),
            )
        )
        for activity in activities:
            activity["lesson"] = (
                self.get_lesson(activity["lesson_id"]) if activity["lesson_id"] else None
            )
        return activities

    def course_minutes(self, course_id: int) -> int:
        row = self.conn.execute(
            "SELECT COALESCE(SUM(minutes), 0) AS total FROM activities WHERE course_id = ?",
            (course_id,),
        ).fetchone()
        return int(row["total"])

    def untagged_subject_minutes(self, student_id: int, start: str, end: str) -> dict[str, int]:
        """Total minutes per subject, this date range, not yet claimed by any
        course -- the raw material the Courses page nudges from: "this
        subject has enough hours sitting around to be worth turning into a
        course.\""""
        rows = self.conn.execute(
            "SELECT primary_subject, SUM(minutes) AS total FROM activities "
            "WHERE student_id = ? AND course_id IS NULL "
            "AND occurred_on BETWEEN ? AND ? GROUP BY primary_subject",
            (student_id, start, end),
        ).fetchall()
        return {row["primary_subject"]: int(row["total"]) for row in rows}

    # -- school-year helper ---------------------------------------------------

    def school_year_bounds(self, on: date | None = None) -> tuple[str, str]:
        """Inclusive (start, end) ISO dates of the school year containing `on`."""
        on = on or date.today()
        raw = self.get_setting("school_year_start") or "09-01"
        try:
            month, day = (int(part) for part in raw.split("-"))
        except (ValueError, AttributeError):
            month, day = 9, 1
        start_year = on.year if (on.month, on.day) >= (month, day) else on.year - 1
        start = date(start_year, month, day)
        end = date(start_year + 1, month, day) - timedelta(days=1)
        return start.isoformat(), end.isoformat()

    def school_year_midpoint(self, on: date | None = None) -> date:
        """Halfway between this school year's bounds -- the default nudge
        point for switching from a first-half book to a second-half one.
        Shifts automatically if school_year_start changes (e.g. starting a
        week early); it's only a default, since promote_upcoming_book can
        switch books early or late any time regardless of this date."""
        start, end = self.school_year_bounds(on)
        start_date = date.fromisoformat(start)
        end_date = date.fromisoformat(end)
        return start_date + (end_date - start_date) / 2

    def close(self) -> None:
        self.conn.close()
