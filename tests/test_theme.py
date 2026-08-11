"""The theme layer.

One fixed look now, not five swappable ones -- picked (Comic Book) after
previewing all five live. Most of what's worth testing is still the parts
that would silently break without an obvious symptom: that the generated
CSS is actually well-formed (a stray brace in an f-string ships a broken
stylesheet with no error anywhere), that the backdrop stays fixed and light,
and that the accent/metric/button rules that used to matter across five
palettes still hold for the one that's left.
"""

from __future__ import annotations

import re
from pathlib import Path

from compass import theme

CONFIG_TOML = Path(__file__).resolve().parent.parent / ".streamlit" / "config.toml"


def _luminance(hex_color: str) -> float:
    """Rough perceived brightness, 0 (black) to 1 (white). Good enough to tell
    "light backdrop" from "dark backdrop" without needing exact colours."""
    r, g, b = (int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _wcag_luminance(hex_color: str) -> float:
    """Real (gamma-corrected) relative luminance, for a real WCAG contrast
    ratio -- unlike `_luminance`, which is only precise enough to tell "light"
    from "dark", not to certify a 4.5:1 claim."""
    def channel(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def _contrast_ratio(c1: str, c2: str) -> float:
    l1, l2 = _wcag_luminance(c1), _wcag_luminance(c2)
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def _resolve_button_text(t: theme.Theme) -> str:
    return t.text if t.button_text == "var(--c-text)" else t.button_text


def _config_toml_value(key: str) -> str:
    """Pull one `key = "value"` out of config.toml without a TOML parser.

    Deliberately not `tomllib` -- that's Python 3.11+ only, and `run.sh`
    supports 3.10. The file's `[theme]` section is a flat list of quoted
    scalars, simple enough that a regex is the right amount of machinery.
    """
    text = CONFIG_TOML.read_text()
    match = re.search(rf'^{re.escape(key)}\s*=\s*"([^"]*)"', text, re.MULTILINE)
    assert match, f"{key} not found in {CONFIG_TOML}"
    return match.group(1)


def test_theme_is_self_consistent():
    t = theme.THEME
    for field in ("panel", "text", "dim", "primary", "alt", "border"):
        value = getattr(t, field)
        assert re.fullmatch(r"#[0-9A-Fa-f]{6}", value), f"{field} = {value!r}"


def test_theme_has_no_bg_or_side_of_its_own():
    """The backdrop is fixed app-wide (BACKDROP_BG/BACKDROP_SIDE) precisely so
    `THEME` can't carry its own version to override it with."""
    assert not hasattr(theme.THEME, "bg")
    assert not hasattr(theme.THEME, "side")
    assert re.fullmatch(r"#[0-9A-Fa-f]{6}", theme.BACKDROP_BG)
    assert re.fullmatch(r"#[0-9A-Fa-f]{6}", theme.BACKDROP_SIDE)


def test_accent_is_never_a_semantic_colour():
    """The accent means "act on this". A warning must not borrow it."""
    t = theme.THEME
    assert t.primary.lower() not in {t.good.lower(), t.bad.lower()}


def test_css_is_balanced_and_carries_the_theme():
    css = theme.css()
    assert css.count("{") == css.count("}"), "unbalanced braces"
    assert "{{" not in css and "}}" not in css, "leaked f-string escapes"
    assert f'data-theme="{theme.THEME.key}"' in css
    assert theme.THEME.primary in css and theme.THEME.border in css
    assert "compass-theme" in css


def test_css_backdrop_matches_the_fixed_constants():
    css = theme.css()
    assert f".stApp {{ background: {theme.BACKDROP_BG};" in css
    assert f"background: {theme.BACKDROP_SIDE};" in css


def test_container_mechanics_are_present():
    """panel/texture/glow/border framing must reach the real containers --
    expanders, alerts, metrics -- not just live in unused CSS variables."""
    css = theme.css()
    assert '[data-testid="stExpander"] details,' in css
    assert '[data-testid="stMetric"] {' in css
    assert "--c-panel-texture" in css
    assert "--c-top-bar" in css


def test_comic_book_gives_the_page_title_its_stroke_and_accent_fill():
    t = theme.THEME
    assert t.key == "comic"
    assert t.heading_stroke != "0px"
    assert t.heading_fill == "var(--c-primary)"


def test_css_forces_the_sidebar_to_scroll():
    """Regression: Streamlit sets `height: auto` as an *inline* style on the
    sidebar, so it grows to fit its content instead of the window. Once enough
    controls stack up -- nine nav links, the profile editor, the mode control
    -- that content outgrew a short browser window with no scrollbar reachable
    anywhere, by mouse wheel or otherwise. `!important` is the only thing in a
    stylesheet that beats an inline style."""
    css = theme.css()
    block = css.split('[data-testid="stSidebar"]', 1)[1].split("}")[0]
    assert "height: 100vh !important" in block
    assert "overflow-y: auto !important" in block


def test_the_page_title_rule_reaches_its_own_descendants():
    """Regression, found only by sampling actual rendered pixels rather than
    trusting `getComputedStyle` on the `<h1>` itself: the visible glyphs live
    in a child `<span>` Streamlit wraps the heading text in (for
    `aria-labelledby`), and the blanket `.stApp span` colour rule matches
    that span directly -- an element's own explicit colour always wins over
    whatever its parent computed to, `!important` or not, since `!important`
    only wins the cascade for the element it's set on, not for children. The
    `<h1>` itself was gold the entire time; the span never was. `h1 *` must
    be in the selector, not just `h1`, or this regresses silently again."""
    css = theme.css()
    assert '[data-testid="stHeading"] h1 *' in css
    assert ".stApp h1 *" in css
    block = css.rsplit(".stApp h1 *", 1)[1].split("}")[0]
    assert "color: var(--c-heading-fill) !important" in block
    assert (
        "-webkit-text-stroke: var(--c-heading-stroke) var(--c-heading-stroke-color) "
        "!important" in block
    )
    assert "text-shadow: var(--c-heading-shadow) !important" in block


def test_css_never_paints_metrics_in_the_accent():
    """Regression: every metric in the accent made compliance read as alarms."""
    css = theme.css()
    # The selector is listed twice in one rule, so take the declaration block —
    # everything between the last mention of it and the closing brace.
    block = css.rsplit('[data-testid="stMetricValue"]', 1)[1].split("}")[0]
    assert "var(--c-text)" in block
    assert "var(--c-primary)" not in block


# --- the light-backdrop redesign ----------------------------------------------


def test_the_backdrop_is_actually_light_not_just_a_different_dark():
    """Regression for the point of this redesign: a bright ground, not a
    recolour of the previous near-black one."""
    assert _luminance(theme.BACKDROP_BG) > 0.85
    assert _luminance(theme.BACKDROP_SIDE) > 0.8


def test_the_panel_is_light_too():
    """The container, not just the backdrop -- a dark card floating on a
    light page would look like a mistake, not a design."""
    assert _luminance(theme.THEME.panel) > 0.85


def test_primary_buttons_use_dark_text_not_the_light_panel_colour():
    """Regression: the button rule used to print `color: var(--c-panel)`,
    which was safe when panel meant "dark" under the old backdrop. Panel is a
    light surface colour, so light-on-bright-primary text would be close to
    unreadable -- the fix is printing in `--c-button-text` instead, defaulting
    to `--c-text`."""
    css = theme.css()
    block = css.split('[data-testid="stBaseButton-primary"],', 1)[1].split("}")[0]
    assert "color: var(--c-button-text);" in block
    assert "var(--c-panel)" not in block


def test_the_primary_button_clears_wcag_aa_contrast():
    """Not "looks fine" -- an actual 4.5:1 check against the real button/text
    pairing, since two of the five original themes needed white button text
    rather than the default dark `text` to clear this."""
    t = theme.THEME
    ratio = _contrast_ratio(_resolve_button_text(t), t.primary)
    assert ratio >= 4.5, f"{ratio:.2f}:1"


def test_config_toml_base_theme_matches_the_backdrop():
    """compass/theme.py's own docstring claims config.toml is kept in step
    with the fixed theme -- this is the thing that would silently stop being
    true if one file changed without the other."""
    assert _config_toml_value("base") == "light"
    assert _config_toml_value("backgroundColor").upper() == theme.BACKDROP_BG.upper()
    assert _config_toml_value("secondaryBackgroundColor").upper() == theme.BACKDROP_SIDE.upper()
