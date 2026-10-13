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


def default_profile() -> dict[str, Any]:
    """A blank business profile -- the shape stored per student."""
    return {
        "name": "",
        "slogan": "",
        "about": "",
        "area": "",
        "contact": "",
        "goal": "",
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
    contact = _e(profile.get("contact"))
    goal = _e(profile.get("goal"))
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
    contact_block = (
        f'<div style="margin-top:14px; background:{accent}; color:#fff; border-radius:10px; '
        f'padding:12px 16px; text-align:center; font-size:18px; font-weight:800;">'
        f"📞 Call or text to book: {contact}</div>" if contact else ""
    )
    goal_block = (
        f'<div style="margin-top:10px; text-align:center; font-size:12px; color:#8a7a5c;">'
        f"Every job helps me save for {goal} — thanks for the work!</div>" if goal else ""
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
        f"    {about_block}{area_block}{contact_block}{goal_block}"
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
