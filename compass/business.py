"""Landon's little business -- a homeschool project where he runs a real
neighborhood yard-work service (leaf raking to start).

Deliberately kept concrete and bite-size: he fills in a few fields -- the
business name, what he offers and for how much, a line about himself, how to
reach him (a parent's contact) -- and the app turns that into a printable
flyer. The "smarts" ride along in small, real pieces (naming, pricing, a short
pitch) rather than a big business-plan document, which suits a 13-year-old who
tries hard but finds paper-heavy work discouraging.

This module is pure data + HTML: the profile shape, the preset services, and
the flyer builder. No database, no Streamlit, so the flyer layout can be tested
directly. compass.ui.render_business_builder does the form and the storage.
"""

from __future__ import annotations

import html
from typing import Any

# The starter menu of services, as (key, emoji, label, baseline_price) --
# concrete, checkbox-able, leaf-season first. He ticks the ones he offers; each
# price box starts pre-filled with a reasonable baseline (a starting point for a
# young teen in a typical neighborhood) that he can change. Two free-text custom
# slots let him add his own (see the builder UI).
PRESET_SERVICES: tuple[tuple[str, str, str, str], ...] = (
    ("rake", "🍂", "Rake leaves", "$25"),
    ("bag", "🗑️", "Bag & haul the leaves", "$15"),
    ("walkways", "🧹", "Clear leaves off walkways & drive", "$10"),
    ("branches", "🌿", "Haul branches & sticks", "$20"),
    ("beds", "🌱", "Tidy garden beds", "$15"),
    ("winter", "❄️", "Winter yard prep", "$20"),
)

# A few slogans he can borrow if he's stuck -- examples, not required. Kept at
# his level: short, friendly, nothing clever he has to explain.
SLOGAN_IDEAS: tuple[str, ...] = (
    "Your yard, done right.",
    "Leaves gone. Yard clean. Done.",
    "Hard worker, fair price.",
    "The neighborhood's leaf crew.",
    "I rake so you don't have to!",
)


# The flyer carries NO phone number or email -- the safest choice for a 13-year-
# old going door to door. Instead it closes with a warm, in-person follow-up: he
# hands over the flyer and offers to stop back by to talk. This is the default
# wording; he can tweak it in the builder, but there's deliberately nowhere to
# put a personal number.
DEFAULT_CLOSING = (
    "I'd love to help with your yard! If any of this sounds good, I'll stop back "
    "by later this week to talk more. Does that sound good? 🍂"
)


def default_profile() -> dict[str, Any]:
    """A blank business profile -- the shape stored per student."""
    return {
        "name": "",
        "slogan": "",
        "about": "",
        "area": "",
        # The flyer's closing line -- how he follows up, in person. No phone/email.
        "closing": DEFAULT_CLOSING,
        # Each service: {"emoji", "label", "price"} -- preset or custom.
        "services": [],
    }


def _clean_services(services: Any) -> list[dict[str, str]]:
    """Keep only services that have a label, each with a trimmed label, emoji,
    and price string -- so a half-filled custom slot never lands on the flyer."""
    out: list[dict[str, str]] = []
    for service in services or []:
        if not isinstance(service, dict):
            continue
        label = str(service.get("label") or "").strip()
        if not label:
            continue
        out.append(
            {
                "emoji": str(service.get("emoji") or "").strip(),
                "label": label,
                "price": str(service.get("price") or "").strip(),
            }
        )
    return out


def is_ready_for_flyer(profile: dict[str, Any]) -> bool:
    """Enough to make a flyer worth printing: a name and at least one service."""
    return bool((profile.get("name") or "").strip()) and bool(_clean_services(profile.get("services")))


def _e(value: Any) -> str:
    """HTML-escape a user-entered value for safe inline rendering."""
    return html.escape(str(value or "").strip())


def flyer_inner_html(profile: dict[str, Any], student_name: str = "") -> str:
    """The flyer itself, as inline-styled HTML (no <style> block), so it renders
    the same inside Streamlit's markdown and inside a standalone download. Uses
    only inline styles for exactly that reason. Everything user-entered is
    escaped."""
    name = _e(profile.get("name")) or "My Yard Business"
    slogan = _e(profile.get("slogan"))
    about = _e(profile.get("about"))
    area = _e(profile.get("area"))
    # The closing line is how he follows up -- in person, no phone/email. A blank
    # one falls back to the friendly default rather than leaving the flyer open.
    closing = _e(profile.get("closing")) or _e(DEFAULT_CLOSING)
    who = _e(student_name)

    accent = "#c0553b"      # warm autumn red
    leaf_band = "#f6efe2"   # soft paper band

    rows = []
    for service in _clean_services(profile.get("services")):
        price = f'<span style="font-weight:800; color:{accent}; white-space:nowrap;">{_e(service["price"])}</span>' if service["price"] else ""
        rows.append(
            f'<div style="display:flex; justify-content:space-between; align-items:baseline; '
            f'gap:12px; padding:7px 2px; border-bottom:1px dashed #d8cdb8;">'
            f'<span style="font-size:18px;">{_e(service["emoji"])} {_e(service["label"])}</span>'
            f"{price}</div>"
        )
    services_block = "".join(rows) or (
        '<div style="padding:8px 2px; color:#8a7a5c;">(add what you offer)</div>'
    )

    slogan_block = (
        f'<div style="font-size:19px; font-style:italic; color:#5c4a2e; margin-top:4px;">'
        f"“{slogan}”</div>" if slogan else ""
    )
    about_block = (
        f'<div style="margin-top:16px; font-size:15px; color:#3f3524; line-height:1.5;">{about}</div>'
        if about else ""
    )
    area_block = (
        f'<div style="margin-top:6px; font-size:13px; color:#8a7a5c;">📍 {area}</div>'
        if area else ""
    )
    # The warm, in-person follow-up -- the whole "how to book" on a kid's flyer,
    # with no number or email to put out there.
    contact_block = (
        f'<div style="margin-top:16px; background:{accent}; color:#fff; border-radius:10px; '
        f'padding:14px 18px; text-align:center; font-size:16px; font-weight:700; line-height:1.4;">'
        f"👋 {closing}</div>"
    )
    by_block = (
        f'<div style="margin-top:2px; font-size:13px; color:#8a7a5c;">Run by {who}</div>'
        if who else ""
    )

    return (
        f'<div style="max-width:560px; margin:0 auto; border:3px solid {accent}; '
        f'border-radius:16px; overflow:hidden; font-family:-apple-system,Segoe UI,Roboto,sans-serif; '
        f'background:#fffdf8;">'
        f'  <div style="background:{leaf_band}; padding:22px 24px 18px; text-align:center; '
        f'border-bottom:3px solid {accent};">'
        f'    <div style="font-size:34px; font-weight:900; color:#2e2416; letter-spacing:-.01em;">'
        f"🍂 {name}</div>"
        f"    {slogan_block}{by_block}"
        f"  </div>"
        f'  <div style="padding:20px 26px 24px;">'
        f'    <div style="font-size:13px; font-weight:800; text-transform:uppercase; '
        f'letter-spacing:.08em; color:{accent}; margin-bottom:4px;">What I do</div>'
        f"    {services_block}"
        f"    {about_block}{area_block}{contact_block}"
        f"  </div>"
        f"</div>"
    )


def flyer_document(profile: dict[str, Any], student_name: str = "") -> str:
    """A standalone, printable HTML document wrapping the flyer -- what the
    download button hands over. Opening it in a browser and hitting print gives
    a clean one-page flyer."""
    name = _e(profile.get("name")) or "My Yard Business"
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        f"<title>{name} — flyer</title>"
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "</head>"
        '<body style="margin:0; padding:28px; background:#fff;">'
        f"{flyer_inner_html(profile, student_name)}"
        "</body></html>"
    )


# --- the door-knock script ------------------------------------------------------
# The hardest part for a 13-year-old isn't the raking -- it's walking up and
# saying something. So the app writes him the words: a short, friendly thing he
# can read off (or practice until he doesn't need to), built from his own
# business details so it's never generic. Plain text on purpose -- it's for
# reading aloud, not printing pretty.


def doorknock_script(profile: dict[str, Any], student_name: str = "") -> str:
    """A short, practice-able 'what to say at the door' script, in plain text,
    built from his business details. Kept to a handful of friendly lines a
    nervous kid can actually get through -- a greeting, who he is, what he does,
    the ask, and a polite close."""
    who = (student_name or "").strip()
    name = (profile.get("name") or "").strip()
    services = _clean_services(profile.get("services"))
    # Two or three services, lower-cased and strung together naturally.
    labels = [s["label"].strip().rstrip(".").lower() for s in services[:3] if s["label"].strip()]
    if len(labels) >= 2:
        offer = ", ".join(labels[:-1]) + ", and " + labels[-1]
    elif labels:
        offer = labels[0]
    else:
        offer = "yard work like raking leaves"

    hello = f"Hi! My name is {who}." if who else "Hi there!"
    biz = f"I started my own little business called {name}." if name else "I started my own little yard-work business."

    lines = [
        hello + " I live right here in the neighborhood.",
        biz,
        f"I can {offer} — I work hard and do a really good job.",
        "Would you like your yard done this week?",
        "Here's a flyer with everything I offer. If you'd like, I can stop back "
        "by later this week to talk more. Thanks so much!",
    ]

    tips = (
        "— Tips —\n"
        "• Smile and look them in the eye.\n"
        "• Speak slow and a little louder than feels normal.\n"
        "• If they say no, say \"No problem, have a great day!\" and move on.\n"
        "• Always hand them a flyer so they can find you again."
    )
    return "\n".join(lines) + "\n\n" + tips


# --- the receipt / thank-you slip -----------------------------------------------
# After a job, handing the customer a little receipt is what makes it feel like a
# real business (and teaches the money side -- what was charged, what it was
# for). Built per-job from the money log; printable like the flyer.


def receipt_inner_html(profile: dict[str, Any], job: dict[str, Any], student_name: str = "") -> str:
    """One job's receipt as inline-styled HTML -- business name, date, who it was
    for, what was done, and the amount, closed with a thank-you. Everything
    user-entered is escaped. Mirrors the flyer's inline-only styling so it
    renders identically in Streamlit and in a standalone download."""
    name = _e(profile.get("name")) or "My Yard Business"
    who = _e(student_name)
    contact = _e(profile.get("contact"))
    job_date = _e(job.get("job_date"))
    customer = _e(job.get("customer")) or "Valued customer"
    description = _e(job.get("description")) or "Yard work"
    try:
        amount = f"${float(job.get('earned') or 0):,.2f}"
    except (TypeError, ValueError):
        amount = "$0.00"
    number = _e(job.get("id"))

    accent = "#c0553b"
    leaf_band = "#f6efe2"

    number_block = (
        f'<span style="font-size:13px; color:#8a7a5c;">Receipt #{number}</span>' if number else ""
    )
    contact_block = (
        f'<div style="margin-top:10px; font-size:13px; color:#8a7a5c;">Questions? {contact}</div>'
        if contact else ""
    )
    by_block = (
        f'<div style="font-size:13px; color:#8a7a5c;">Run by {who}</div>' if who else ""
    )

    return (
        f'<div style="max-width:480px; margin:0 auto; border:3px solid {accent}; '
        f'border-radius:16px; overflow:hidden; font-family:-apple-system,Segoe UI,Roboto,sans-serif; '
        f'background:#fffdf8;">'
        f'  <div style="background:{leaf_band}; padding:18px 22px; border-bottom:3px solid {accent}; '
        f'display:flex; justify-content:space-between; align-items:center; gap:12px;">'
        f'    <div>'
        f'      <div style="font-size:24px; font-weight:900; color:#2e2416;">🍂 {name}</div>'
        f"      {by_block}"
        f"    </div>"
        f'    <div style="text-align:right;">'
        f'      <div style="font-size:15px; font-weight:800; text-transform:uppercase; '
        f'letter-spacing:.08em; color:{accent};">Receipt</div>'
        f"      {number_block}"
        f"    </div>"
        f"  </div>"
        f'  <div style="padding:20px 24px 22px;">'
        f'    <div style="display:flex; justify-content:space-between; font-size:14px; color:#5c4a2e; margin-bottom:4px;">'
        f'      <span>Date</span><span style="font-weight:700;">{job_date}</span></div>'
        f'    <div style="display:flex; justify-content:space-between; font-size:14px; color:#5c4a2e; '
        f'padding-bottom:12px; border-bottom:1px dashed #d8cdb8;">'
        f'      <span>For</span><span style="font-weight:700;">{customer}</span></div>'
        f'    <div style="display:flex; justify-content:space-between; align-items:baseline; gap:12px; '
        f'padding:12px 0; border-bottom:1px dashed #d8cdb8;">'
        f'      <span style="font-size:16px;">{description}</span>'
        f'      <span style="font-weight:800; font-size:18px; color:{accent}; white-space:nowrap;">{amount}</span></div>'
        f'    <div style="display:flex; justify-content:space-between; align-items:baseline; margin-top:12px;">'
        f'      <span style="font-size:16px; font-weight:800; color:#2e2416;">Paid — thank you!</span>'
        f'      <span style="font-weight:900; font-size:20px; color:{accent};">{amount}</span></div>'
        f"    {contact_block}"
        f"  </div>"
        f"</div>"
    )


def receipt_document(profile: dict[str, Any], job: dict[str, Any], student_name: str = "") -> str:
    """A standalone, printable HTML receipt -- what the per-job download hands
    over. Open and print for a clean little slip to give the customer."""
    name = _e(profile.get("name")) or "My Yard Business"
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        f"<title>{name} — receipt</title>"
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "</head>"
        '<body style="margin:0; padding:28px; background:#fff;">'
        f"{receipt_inner_html(profile, job, student_name)}"
        "</body></html>"
    )


# --- the neighborhood map (his lead / customer tracker) -------------------------
# Who said yes, who to come back to, and which houses to skip (the not-so-friendly
# nos). Drawn as a playful street map: each street is a lane, each house a little
# pin colored by status. Pure HTML/SVG so it renders the same in the app and in a
# printable download, and can be tested without a browser.

# (key, emoji, short label, long label, color) -- the three states a house can be
# in. 'customer' = said yes (his repeat customers live here); 'maybe' = come back
# later; 'avoid' = skip this one.
HOUSE_STATUSES: tuple[tuple[str, str, str, str, str], ...] = (
    ("customer", "🟢", "Customer", "Said yes — a customer!", "#2e8b57"),
    ("maybe", "🟡", "Maybe", "Maybe / come back later", "#d99a00"),
    ("avoid", "🔴", "Skip", "Skip this one (not friendly)", "#c0392b"),
)
_HOUSE_BY_KEY = {s[0]: s for s in HOUSE_STATUSES}


def house_status(key: str) -> tuple[str, str, str, str, str]:
    """The (key, emoji, short, long, color) tuple for a status, defaulting to
    'maybe' for anything unrecognized."""
    return _HOUSE_BY_KEY.get(key, _HOUSE_BY_KEY["maybe"])


def house_label(house: dict[str, Any]) -> str:
    """A short identifier for a house: its number and nickname when it has both
    ("42 — Blue house"), or whichever one it has. Plain text, for lists."""
    number = str(house.get("number") or "").strip()
    nick = str(house.get("nickname") or "").strip()
    if number and nick:
        return f"{number} — {nick}"
    return number or nick or "A house"


def _house_pin(house: dict[str, Any]) -> str:
    _k, emoji, _short, _long, color = house_status(house.get("status"))
    number = _e(house.get("number"))
    nick = _e(house.get("nickname"))
    # Lead with the number (the real identifier); nickname rides along smaller.
    primary = number or nick or "A house"
    secondary = nick if (number and nick) else ""
    secondary_block = (
        f'<div style="font-size:10px; color:#8a7a5c; line-height:1.1; '
        f'word-break:break-word;">{secondary}</div>' if secondary else ""
    )
    return (
        f'<div style="display:flex; flex-direction:column; align-items:center; '
        f'width:92px; text-align:center;">'
        f'<div style="font-size:30px; line-height:1;">🏠</div>'
        f'<div style="margin-top:-8px; font-size:15px;">{emoji}</div>'
        f'<div style="margin-top:2px; font-size:12px; font-weight:800; color:{color}; '
        f'line-height:1.15; word-break:break-word;">{primary}</div>'
        f"{secondary_block}"
        f"</div>"
    )


def neighborhood_map_html(houses: list[dict[str, Any]], student_name: str = "") -> str:
    """His houses as a friendly street map -- streets as lanes, houses as pins
    colored by status, grouped by street. Inline-styled only, everything escaped.
    Empty until he's added a house."""
    accent = "#c0553b"
    cleaned = [
        h for h in (houses or [])
        if (h.get("nickname") or "").strip() or (h.get("number") or "").strip()
    ]
    if not cleaned:
        return (
            '<div style="padding:18px; border:2px dashed #d8cdb8; border-radius:14px; '
            'text-align:center; color:#8a7a5c; font-family:-apple-system,Segoe UI,Roboto,sans-serif;">'
            "Add a house below and it'll show up on your map. 🗺️</div>"
        )

    # Group by street, keeping the order list_business_houses already returns.
    streets: dict[str, list[dict[str, Any]]] = {}
    for h in cleaned:
        streets.setdefault((h.get("street") or "").strip(), []).append(h)

    lanes = []
    for street, group in streets.items():
        pins = "".join(_house_pin(h) for h in group)
        label = _e(street) or "Around the neighborhood"
        lanes.append(
            f'<div style="margin:0 0 6px;">'
            f'<div style="font-size:12px; font-weight:800; text-transform:uppercase; '
            f'letter-spacing:.06em; color:{accent}; margin-bottom:4px;">🛣️ {label}</div>'
            f'<div style="display:flex; flex-wrap:wrap; gap:10px; align-items:flex-start; '
            f'padding:12px 10px; background:#f6efe2; border-radius:12px; '
            f'border:1px solid #e4d9c2;">{pins}</div>'
            f"</div>"
        )

    legend = " &nbsp; ".join(
        f'<span style="white-space:nowrap;">{emoji} {_e(short)}</span>'
        for _k, emoji, short, _long, _c in HOUSE_STATUSES
    )
    who = _e(student_name)
    title = f"{who}'s neighborhood map" if who else "My neighborhood map"
    return (
        f'<div style="max-width:620px; margin:0 auto; border:3px solid {accent}; '
        f'border-radius:16px; overflow:hidden; font-family:-apple-system,Segoe UI,Roboto,sans-serif; '
        f'background:#fffdf8;">'
        f'  <div style="background:{accent}; color:#fff; padding:12px 18px; font-size:18px; '
        f'font-weight:900;">🗺️ {title}</div>'
        f'  <div style="padding:14px 16px;">{"".join(lanes)}'
        f'    <div style="margin-top:10px; font-size:12px; color:#5c4a2e;">{legend}</div>'
        f"  </div>"
        f"</div>"
    )


def neighborhood_map_document(houses: list[dict[str, Any]], student_name: str = "") -> str:
    """A standalone, printable version of the map -- the download for the fridge."""
    who = _e(student_name)
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        f"<title>{who or 'My'} neighborhood map</title>"
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "</head>"
        '<body style="margin:0; padding:28px; background:#fff;">'
        f"{neighborhood_map_html(houses, student_name)}"
        "</body></html>"
    )


# --- "help me write it" (AI slogan + about line) --------------------------------
# A young teen often freezes on the writing bits -- the slogan and the one-line
# "why I'm good at this." These two pure helpers build the request; the actual
# model call lives in the UI layer (compass.ui.render_business_builder), so this
# module stays pure and testable. The schema is a plain closed JSON-schema object
# (same shape compass.agents.llm._object produces) so no import is needed here.

COPY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "slogan": {
            "type": "string",
            "description": (
                "A short, catchy slogan for his yard-work business -- five or six "
                "words, friendly, nothing he'd have to explain. Written at a "
                "13-year-old's level."
            ),
        },
        "about": {
            "type": "string",
            "description": (
                "One upbeat sentence a neighbor would read, in his own voice, about "
                "why he's good at this -- hard-working, reliable, careful. First "
                "person, plain words, no bragging he couldn't back up."
            ),
        },
    },
    "required": ["slogan", "about"],
    "additionalProperties": False,
}


def copy_system_prompt(name: str, age: int, interests: str, services: list[str]) -> str:
    """The system prompt for the 'help me write it' suggestion -- all the context
    the model needs to write a slogan and an about-line that sound like this kid's
    actual business."""
    biz = (name or "a neighborhood yard-work business").strip()
    offer = ", ".join(s.strip() for s in services if s.strip()) or "raking leaves and other yard work"
    return (
        f"You help a homeschooled {age}-year-old named {name or 'a student'} write the "
        f"words for his own little yard-work business. The business is called "
        f"\"{biz}\" and he offers: {offer}. His interests: {interests}. "
        f"Write for HIM to use with neighbors: warm, plain, honest, at his level -- "
        f"nothing slick or corporate, nothing he couldn't say out loud. Return only "
        f"the slogan and the about-line as the structured fields."
    )


COPY_USER_PROMPT = "Write my slogan and my one-line 'about me' now."
