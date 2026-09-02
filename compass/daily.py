"""Little daily delights for the student home view -- a rotating greeting, a
riddle, a word of the day, and a history flashback. Same deterministic-by-date
pattern as `fun_facts`: the same pick holds all day regardless of how many
times the page reruns, and rotates on its own without any external API.

Everything here is low-stakes flavor, not a lesson or a compliance record --
its whole job is to make opening the app a little more fun. The history
entries are deliberately *not* pinned to the calendar date (that would need
365 date-accurate events and invites errors); they're a rotating set of real,
well-known moments, framed as a "flashback" rather than "on this exact day."
"""

from __future__ import annotations

from datetime import date

# Rotating hellos -- the big "Hi <name>" stays put for identity; this is the
# line under it, leaning into the app's own compass/navigation theme.
GREETINGS = [
    "Ready to explore today?",
    "New day, new territory.",
    "Let's chart the course.",
    "Time to find your bearings.",
    "Adventure's calling. 🧭",
    "Onward — let's make it count.",
    "What'll you discover today?",
    "The map's yours today.",
    "Full steam ahead.",
    "Big things ahead — let's go.",
    "Fresh start. You've got this. 💪",
    "Time to level up.",
    "Every expert was once a beginner. Let's roll.",
    "Small steps, real progress.",
    "Let's turn today into a win.",
]

# (question, answer) -- reveal-on-tap, so the fun is in the guess.
RIDDLES = [
    ("What has to be broken before you can use it?", "An egg."),
    ("I'm tall when I'm young and short when I'm old. What am I?", "A candle."),
    ("What has hands but can't clap?", "A clock."),
    ("What has a head and a tail but no body?", "A coin."),
    ("What gets wetter the more it dries?", "A towel."),
    ("What has many keys but can't open a single lock?", "A piano."),
    ("What can travel around the world while staying in one corner?", "A stamp."),
    ("The more you take, the more you leave behind. What are they?", "Footsteps."),
    ("What has a neck but no head?", "A bottle."),
    ("What goes up but never comes down?", "Your age."),
    ("What has words but never speaks?", "A book."),
    ("What has teeth but can't bite?", "A comb."),
    ("What building has the most stories?", "A library."),
    ("What has a thumb and four fingers but isn't alive?", "A glove."),
    ("What can you catch but not throw?", "A cold."),
    ("What kind of band never plays music?", "A rubber band."),
    ("Where does today come before yesterday?", "In a dictionary."),
    ("What has legs but doesn't walk?", "A table."),
    ("What has a ring but no finger?", "A telephone."),
    ("What comes down but never goes up?", "Rain."),
    ("I have branches but no fruit, trunk, or leaves. What am I?", "A bank."),
    ("What can fill a room but takes up no space?", "Light."),
    ("What has cities but no houses, forests but no trees, and water but no fish?", "A map."),
    ("What gets bigger the more you take away from it?", "A hole."),
    ("What two things can you never eat for breakfast?", "Lunch and dinner."),
    ("What has an eye but cannot see?", "A needle."),
    ("What runs all around a yard but never moves?", "A fence."),
    ("What has one head, one foot, and four legs?", "A bed."),
    ("What invention lets you look right through a wall?", "A window."),
    ("If you drop me I'm sure to crack, but smile at me and I'll smile back. What am I?", "A mirror."),
]

# (word, part of speech, definition) -- real grade-8 vocabulary.
WORDS = [
    ("resilient", "adjective", "able to recover quickly from difficulty"),
    ("meticulous", "adjective", "very careful about small details"),
    ("candid", "adjective", "honest and direct"),
    ("tenacious", "adjective", "holding on firmly; not giving up"),
    ("ambiguous", "adjective", "open to more than one meaning; unclear"),
    ("gregarious", "adjective", "sociable; enjoying the company of others"),
    ("procrastinate", "verb", "to keep putting off something you should do"),
    ("scrutinize", "verb", "to examine closely and carefully"),
    ("benevolent", "adjective", "kind and generous"),
    ("nostalgia", "noun", "a fond longing for the past"),
    ("pragmatic", "adjective", "practical rather than idealistic"),
    ("eloquent", "adjective", "fluent and persuasive in speech or writing"),
    ("inevitable", "adjective", "certain to happen; unavoidable"),
    ("obsolete", "adjective", "out of date; no longer used"),
    ("plausible", "adjective", "seeming reasonable or probably true"),
    ("verbose", "adjective", "using more words than necessary"),
    ("diligent", "adjective", "showing careful, steady effort"),
    ("apathy", "noun", "a lack of interest or concern"),
    ("conundrum", "noun", "a confusing and difficult problem"),
    ("empathy", "noun", "the ability to understand another person's feelings"),
    ("frugal", "adjective", "careful with money; not wasteful"),
    ("intricate", "adjective", "very detailed or complicated"),
    ("novice", "noun", "a beginner"),
    ("perseverance", "noun", "steady persistence despite difficulty"),
    ("quell", "verb", "to put an end to; to calm"),
    ("relentless", "adjective", "never stopping; unyielding"),
    ("skeptical", "adjective", "not easily convinced; doubtful"),
    ("vivid", "adjective", "producing strong, clear images in the mind"),
    ("ubiquitous", "adjective", "seeming to be everywhere at once"),
    ("audacious", "adjective", "boldly daring"),
]

# Real, well-known moments from history -- a rotating "flashback," not tied to
# the exact calendar date. Kept to widely-agreed facts to stay accurate.
HISTORY = [
    "The compass was invented in ancient China and changed navigation forever. 🧭",
    "The Great Wall of China stretches over 13,000 miles and took roughly 2,000 years to build.",
    "Egyptians built the Great Pyramid of Giza about 4,500 years ago from around 2.3 million stone blocks.",
    "Gutenberg's printing press, from around 1440, made books cheap enough for ordinary people to own.",
    "At its peak, the Roman Empire ruled around 60 million people.",
    "The first modern Olympic Games were held in Athens in 1896.",
    "In 1969, Apollo 11 landed the first humans on the Moon.",
    "The U.S. Declaration of Independence was signed in 1776.",
    "The Titanic sank on its very first voyage in 1912.",
    "Leonardo da Vinci sketched designs for flying machines centuries before the airplane existed.",
    "The Wright brothers made the first powered airplane flight in 1903 — it lasted 12 seconds.",
    "The Berlin Wall fell in 1989, reuniting a city split for nearly 30 years.",
    "Vikings reached North America around the year 1000, roughly 500 years before Columbus.",
    "The Rosetta Stone, found in 1799, became the key to reading Egyptian hieroglyphs.",
    "George Washington was elected the first U.S. president in 1789.",
    "The transcontinental railroad, finished in 1869, connected the U.S. from coast to coast.",
    "The Magna Carta, signed in 1215, limited the power of the English king.",
    "Ancient Greece is often called the birthplace of democracy.",
    "Marie Curie won Nobel Prizes in two different sciences — physics and chemistry.",
    "The Eiffel Tower was built for the 1889 World's Fair and was meant to be temporary.",
    "Pompeii was buried by the eruption of Mount Vesuvius in 79 AD and preserved for centuries.",
    "The telephone was patented by Alexander Graham Bell in 1876.",
    "Some ancient Roman roads were built so well that parts are still in use today.",
    "The Renaissance, beginning in the 1300s, sparked huge leaps in art and science.",
    "Sliced bread first went on sale in 1928 — that's where 'the best thing since sliced bread' comes from.",
    "The Mayans developed a written language and a remarkably accurate calendar.",
    "The Library of Alexandria was one of the largest collections of knowledge in the ancient world.",
    "Mount Everest is the tallest mountain on Earth, first summited in 1953.",
    "The first photograph ever taken, in the 1820s, needed hours of exposure time.",
    "The steam engine helped launch the Industrial Revolution in the 1700s.",
]


def _pick(items: list, today: date | None) -> object:
    """The same pick all day, deterministic on the date -- so nothing changes
    when the page reruns twice in a minute."""
    today = today or date.today()
    return items[today.toordinal() % len(items)]


def greeting_of_the_day(today: date | None = None) -> str:
    return _pick(GREETINGS, today)


def riddle_of_the_day(today: date | None = None) -> tuple[str, str]:
    return _pick(RIDDLES, today)


def word_of_the_day(today: date | None = None) -> tuple[str, str, str]:
    return _pick(WORDS, today)


def history_flashback(today: date | None = None) -> str:
    return _pick(HISTORY, today)
