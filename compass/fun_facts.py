"""A small fixed list of facts for the student home view. Deterministic by
date rather than random -- the same fact holds all day regardless of how
many times the page reruns, and rotates without needing an external API or
its failure modes for something this low-stakes.
"""

from __future__ import annotations

from datetime import date

FACTS = [
    "Octopuses have three hearts, and two of them stop beating when it swims.",
    "A day on Venus is longer than a year on Venus.",
    "Bananas are berries, but strawberries aren't.",
    "The Eiffel Tower grows about 6 inches taller in summer heat.",
    "Sharks existed before trees did.",
    "A single bolt of lightning is hotter than the surface of the sun.",
    "Wombat poop is cube-shaped.",
    "There are more possible chess games than atoms in the observable universe.",
    "Honey never spoils -- archaeologists have eaten 3,000-year-old honey.",
    "The Great Wall of China is not visible from space with the naked eye.",
    "A group of flamingos is called a flamboyance.",
    "Your stomach gets an entirely new lining every few days so it doesn't digest itself.",
    "Some turtles can breathe through their butts.",
    "The inventor of the Frisbee was turned into a Frisbee after he died.",
    "Hot water can freeze faster than cold water under the right conditions.",
    "A bolt of lightning strikes Earth about 8 million times a day.",
    "Cleopatra lived closer in time to the Moon landing than to the building of the Great Pyramid.",
    "Sea otters hold hands while sleeping so they don't drift apart.",
    "The shortest war in history lasted about 38 minutes.",
    "There's a species of jellyfish that can revert back to a baby stage and is biologically immortal.",
    "Mount Everest grows about 4 millimeters taller every year.",
    "A blue whale's heart is about the size of a small car.",
    "It rains diamonds on Jupiter and Saturn.",
    "The first computer bug was an actual moth stuck in a relay in 1947.",
    "Humans share about 60% of their DNA with a banana.",
    "Antarctica is the largest desert in the world.",
    "A group of crows is called a murder.",
    "Venus is the only planet that spins clockwise.",
    "The longest recorded flight of a chicken is 13 seconds.",
    "Space smells like burnt steak, according to astronauts.",
    "The unicorn is the national animal of Scotland.",
    "An octopus can taste with its arms.",
    "The dot over a lowercase i or j has a name: a tittle.",
    "Some metals are so reactive they explode on contact with water.",
    "A day on Mars is only about 40 minutes longer than a day on Earth.",
    "The world's oldest known recipe is for beer.",
    "Butterflies taste with their feet.",
    "There are more stars in the universe than grains of sand on every beach on Earth.",
    "A shrimp's heart is in its head.",
    "The Mona Lisa has no eyebrows.",
    "Squirrels forget where they bury most of their nuts, planting forests by accident.",
]


def fact_of_the_day(today: date | None = None) -> str:
    """The same fact all day, every day -- deterministic on the date, not
    random, so it doesn't change if the page reruns twice in a minute."""
    today = today or date.today()
    return FACTS[today.toordinal() % len(FACTS)]
