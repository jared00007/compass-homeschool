"""The five themes, and the CSS that puts one of them on the page.

Streamlit's own theming lives in `.streamlit/config.toml` and is read once when
the server starts, so it cannot answer "let him pick his own look" — that needs to
change per session, per person, without a restart. And there is no variable layer
to swap: as of 1.61 Streamlit bakes theme values into generated class names and
declares no CSS custom properties at all.

So this module does it the other way round. It declares its own custom properties
on `:root`, then repaints Streamlit's surfaces through them using `data-testid`
selectors — which are stable across versions because Streamlit's own test suite
depends on them. Everything the CSS can't reach (the insides of dropdown popovers,
date pickers, text inputs) is covered by keeping `config.toml` on a neutral dark
base, which is why all five themes here are dark. A light theme would need that
base changed and the app relaunched; it is not something a picker can do.

The backdrop rule: the page ground and the sidebar are fixed, not themed. Color
lives on the containers -- expanders, alerts, metrics, buttons -- never on the
page behind them. `BACKDROP_BG`/`BACKDROP_SIDE` are the only place that ground is
defined, and no `Theme` below carries its own version to override them with.
"""

from __future__ import annotations

from dataclasses import dataclass

# Faces that ship with macOS, so nothing downloads and the app looks right with no
# signal at a trailhead.
SANS = '-apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif'
MONO = 'ui-monospace, "SF Mono", "Cascadia Mono", Menlo, Consolas, monospace'

# The static backdrop. Fixed across every theme, on purpose -- see module docstring.
BACKDROP_BG = "#0A0A0D"
BACKDROP_SIDE = "#050506"


@dataclass(frozen=True)
class Theme:
    key: str
    name: str
    tagline: str

    panel: str       # cards, expanders, metrics, alerts -- the containers
    text: str
    dim: str         # captions, secondary text
    primary: str     # one job: what needs the reader
    alt: str         # links, subject tags, secondary accent
    border: str

    radius: str = "3px"
    heading_font: str = SANS
    body_font: str = SANS
    mono_font: str = MONO
    heading_caps: str = "none"
    heading_track: str = "0"
    heading_weight: str = "700"
    heading_stroke: str = "0px"       # an inked outline behind the page title
    heading_fill: str = "var(--c-text)"  # the page title's own colour, separate
    # from body text so a theme can make it pop without recoloring every h2-h4
    panel_texture: str = "none"       # a background-image every container gets
    glow: str = "none"
    # Two-tone container frame (Arcade's marquee edge). None on either side means
    # "use `border`, plain" -- most themes leave both unset.
    border_top: str | None = None
    border_bottom: str | None = None
    # A 4px stripe across each container's top edge. Transparent is a no-op;
    # only High-Vis's chevron uses this for real.
    top_bar: str = "transparent"

    # Semantic colours. Kept separate from `primary` on purpose — "this needs you"
    # and "this is wrong" must never be the same colour, or a warning stops reading
    # as a warning.
    good: str = "#3FB37F"
    warn: str = "#E0A32E"
    bad: str = "#E5544B"


THEMES: dict[str, Theme] = {
    "comic": Theme(
        key="comic",
        name="Comic Book",
        tagline="Ink borders, pop-art shadow",
        panel="#1C160F", text="#F5EFE4", dim="#B7A88E",
        primary="#FFD400", alt="#3D7AFF", border="#E63946",
        radius="3px",
        heading_font='"Avenir Next", "Helvetica Neue", ' + SANS,
        heading_caps="uppercase", heading_track=".02em", heading_weight="800",
        heading_stroke="1.4px", heading_fill="var(--c-primary)",
        panel_texture=(
            "repeating-radial-gradient(circle at 100% 0%, "
            "rgba(255,255,255,.075) 0 1px, transparent 1px 7px)"
        ),
        glow="5px 5px 0 rgba(0,0,0,.8)",
    ),
    "arcade": Theme(
        key="arcade",
        name="Arcade",
        tagline="Cabinet art, louder neon",
        panel="#22102F", text="#F5E9FF", dim="#B294D4",
        primary="#FF2D78", alt="#22F0FF", border="#4A2166",
        radius="2px",
        heading_font='"Futura", "Futura PT", "Century Gothic", "Avenir Next", ' + SANS,
        heading_caps="uppercase", heading_track=".11em", heading_weight="700",
        panel_texture=(
            "repeating-linear-gradient(to bottom, rgba(255,255,255,.05) 0 1px, "
            "transparent 1px 3px), "
            "radial-gradient(ellipse 100% 55% at 50% 0%, rgba(34,240,255,.16), transparent 70%)"
        ),
        glow="0 0 10px rgba(255,45,120,.7), 0 0 26px rgba(34,240,255,.28)",
        border_top="#FF2D78", border_bottom="#22F0FF",
        warn="#FFEA00",
    ),
    "techtree": Theme(
        key="techtree",
        name="Tech Tree",
        tagline="Ember on deep pine",
        panel="#0C1A16", text="#EAFBF3", dim="#79A296",
        primary="#FF8C1A", alt="#3FE0C4", border="#1F3A31",
        radius="3px",
        heading_caps="uppercase", heading_track=".05em", heading_weight="800",
        panel_texture=(
            "radial-gradient(ellipse 150% 100% at 50% -20%, "
            "rgba(63,224,196,.20), transparent 60%)"
        ),
        glow="0 0 20px rgba(255,140,26,.5)",
    ),
    "highvis": Theme(
        key="highvis",
        name="High-Vis",
        tagline="Rally truck, chevron on every card",
        panel="#1B1C21", text="#F7F7F2", dim="#9C9FA6",
        primary="#FF6A28", alt="#FFDE5C", border="#33363D",
        radius="2px",
        heading_font='"Avenir Next Condensed", "HelveticaNeue-CondensedBold", '
                     '"Arial Narrow", ' + SANS,
        heading_caps="uppercase", heading_track=".03em", heading_weight="800",
        panel_texture=(
            "repeating-linear-gradient(135deg, rgba(255,222,92,.07) 0 10px, "
            "transparent 10px 28px)"
        ),
        glow="0 0 16px rgba(255,106,40,.55)",
        top_bar="repeating-linear-gradient(135deg, var(--c-primary) 0 6px, var(--c-alt) 6px 12px)",
    ),
    "blueprint": Theme(
        key="blueprint",
        name="Blueprint",
        tagline="Drafting grid, per panel",
        panel="#082140", text="#E7F3FC", dim="#7FA8C7",
        primary="#FF3B2E", alt="#5CC4F5", border="#1C5F8F",
        radius="0px",
        heading_caps="uppercase", heading_track=".08em", heading_weight="700",
        panel_texture=(
            "repeating-linear-gradient(to right, rgba(92,196,245,.14) 0 1px, "
            "transparent 1px 22px), "
            "repeating-linear-gradient(to bottom, rgba(92,196,245,.14) 0 1px, "
            "transparent 1px 22px)"
        ),
        glow="0 0 16px rgba(255,59,46,.45)",
        good="#4FC3A1", warn="#F2B441",
    ),
}

DEFAULT_THEME = "techtree"

#: Settings keys. Parent and student get their own, because the person doing two
#: hours on the compliance page and the person opening one lesson want different
#: things, and neither should have to overrule the other.
STUDENT_KEY = "theme_student"
PARENT_KEY = "theme_parent"


def get(key: str | None) -> Theme:
    """Resolve a stored key to a theme, tolerating one that no longer exists."""
    return THEMES.get(key or "", THEMES[DEFAULT_THEME])


def css(theme: Theme) -> str:
    """The stylesheet that paints Streamlit in this theme.

    Selectors are `data-testid` attributes wherever possible. They are what
    Streamlit's own tests target, which makes them the most stable hook available
    — far more so than the emotion class names, which rehash between releases.
    """
    t = theme
    border_top = t.border_top or t.border
    border_bottom = t.border_bottom or t.border
    return f"""
<style id="compass-theme" data-theme="{t.key}">
:root {{
  --c-panel: {t.panel};
  --c-text: {t.text};
  --c-dim: {t.dim};
  --c-primary: {t.primary};
  --c-alt: {t.alt};
  --c-border: {t.border};
  --c-border-top: {border_top};
  --c-border-bottom: {border_bottom};
  --c-top-bar: {t.top_bar};
  --c-radius: {t.radius};
  --c-glow: {t.glow};
  --c-panel-texture: {t.panel_texture};
  --c-heading-stroke: {t.heading_stroke};
  --c-heading-fill: {t.heading_fill};
  --c-good: {t.good};
  --c-warn: {t.warn};
  --c-bad: {t.bad};
  --c-head: {t.heading_font};
  --c-body: {t.body_font};
  --c-mono: {t.mono_font};
}}

/* --- grounds -----------------------------------------------------------
   Fixed. Every theme above reads from BACKDROP_BG/BACKDROP_SIDE, never
   from its own field -- there isn't one to override this with. */
.stApp {{ background: {BACKDROP_BG}; font-family: var(--c-body); }}
[data-testid="stAppViewContainer"] {{ position: relative; z-index: 1; }}
[data-testid="stHeader"] {{ background: transparent; }}
[data-testid="stSidebar"] {{
  background: {BACKDROP_SIDE};
  border-right: 1px solid var(--c-border);
  /* Streamlit sets `height: auto` as an *inline* style on this element, which
     beats any stylesheet rule regardless of selector specificity -- `!important`
     is the only way a stylesheet wins that fight. Without it, the sidebar simply
     grows to fit its content, and once enough controls stack up (nine nav links,
     the profile editor, the mode control, the theme picker) that content outgrows
     a short window with nothing to scroll: not the sidebar, not the page behind
     it. Confirmed live: a 760px-tall window clipped everything below "Parent
     view" with no scrollbar reachable by any means, including the mouse wheel. */
  height: 100vh !important;
  overflow-y: auto !important;
}}
[data-testid="stSidebarNavSeparator"] {{ border-color: var(--c-border); }}

/* --- type ------------------------------------------------------------ */
.stApp, .stApp p, .stApp li, .stApp label, .stApp span,
[data-testid="stMarkdownContainer"] {{ color: var(--c-text); }}

[data-testid="stHeading"] h1, [data-testid="stHeading"] h2,
[data-testid="stHeading"] h3, [data-testid="stHeading"] h4,
.stApp h1, .stApp h2, .stApp h3, .stApp h4 {{
  color: var(--c-text);
  font-family: var(--c-head);
  font-weight: {t.heading_weight};
  letter-spacing: {t.heading_track};
  text-transform: {t.heading_caps};
}}
/* The page title (st.title -> h1) is the one heading that gets to be loud --
   an inked stroke and, for Comic Book, the accent as its actual fill colour.
   Everything smaller (h2-h4: section headers, card titles) stays plain text
   colour, or a page reads as shouting by the third subheading. */
[data-testid="stHeading"] h1, .stApp h1 {{
  color: var(--c-heading-fill);
  -webkit-text-stroke: var(--c-heading-stroke) #000;
}}

/* Captions carry most of the app's explanatory writing. They must stay
   readable, so they are dimmed but never faded out. */
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p,
[data-testid="stMetricLabel"], [data-testid="stWidgetLabel"] p {{
  color: var(--c-dim);
}}

.stApp a, .stApp a:visited {{ color: var(--c-alt); }}
.stApp code {{
  font-family: var(--c-mono);
  color: var(--c-alt);
  background: var(--c-panel);
}}

/* --- containers --------------------------------------------------------
   Every themed surface: expanders, alerts, metric tiles. All four get the
   same treatment -- panel colour, texture, glow, and (mostly no-op) top
   bar -- so a theme only has to say what its containers look like once. */
[data-testid="stVerticalBlockBorderWrapper"]:has(> div > [data-testid="stVerticalBlock"]) {{
  border-radius: var(--c-radius);
}}

[data-testid="stExpander"] details,
[data-testid="stAlertContainer"],
[data-testid="stMetric"] {{
  background-color: var(--c-panel);
  background-image: var(--c-panel-texture);
  background-repeat: no-repeat;
  border: 1px solid var(--c-border);
  border-top-color: var(--c-border-top);
  border-bottom-color: var(--c-border-bottom);
  border-radius: var(--c-radius);
  box-shadow: var(--c-glow);
  position: relative;
  overflow: hidden;
}}
[data-testid="stExpander"] details::before,
[data-testid="stAlertContainer"]::before,
[data-testid="stMetric"]::before {{
  content: ""; position: absolute; inset: 0 0 auto 0; height: 4px;
  background: var(--c-top-bar);
}}
[data-testid="stExpander"] summary:hover {{ color: var(--c-primary); }}
[data-testid="stMetric"] {{ padding: .6rem .9rem; }}

/* --- numbers ---------------------------------------------------------
   Deliberately *not* the accent. An early build painted every metric in it,
   which made the compliance page read as a wall of alarms — "0 / 1000 hours"
   in Blueprint's red looked like a failure rather than a September Tuesday.
   The accent means "this is yours to act on"; a figure is just a figure. Size,
   weight and tabular figures carry the emphasis instead.

   The inner <p> has to be named explicitly: the blanket `.stApp p` rule above
   is equally specific and comes first, so inheritance alone loses. */
[data-testid="stMetricValue"], [data-testid="stMetricValue"] p {{
  color: var(--c-text);
  font-family: var(--c-mono);
  font-variant-numeric: tabular-nums;
}}

/* Dataframes render to a canvas, so their cells are out of CSS's reach and
   follow the base theme in config.toml instead. Framing the wrapper is all
   that can be done here — which is why every shipped theme is dark. */
[data-testid="stDataFrame"] {{
  border: 1px solid var(--c-border);
  border-radius: var(--c-radius);
  box-shadow: var(--c-glow);
}}

/* --- buttons --------------------------------------------------------- */
[data-testid="stBaseButton-secondary"] {{
  background: var(--c-panel);
  color: var(--c-text);
  border: 1px solid var(--c-border);
  border-radius: var(--c-radius);
}}
[data-testid="stBaseButton-secondary"]:hover {{
  border-color: var(--c-primary);
  color: var(--c-primary);
}}
[data-testid="stBaseButton-primary"],
[data-testid="stBaseButton-primaryFormSubmit"] {{
  background: var(--c-primary);
  color: var(--c-panel);
  border: 1px solid var(--c-primary);
  border-radius: var(--c-radius);
  box-shadow: var(--c-glow);
  font-weight: 600;
}}
[data-testid="stBaseButton-primary"]:hover,
[data-testid="stBaseButton-primaryFormSubmit"]:hover {{
  filter: brightness(1.12);
  color: var(--c-panel);
}}
[data-testid="stBaseButton-secondaryFormSubmit"] {{
  background: var(--c-panel);
  color: var(--c-text);
  border: 1px solid var(--c-border);
  border-radius: var(--c-radius);
}}

/* --- progress --------------------------------------------------------
   The fill is the track's only child and carries no testid of its own, so
   it has to be reached positionally. */
[data-testid="stProgressBarTrack"] {{
  background: var(--c-border);
  border-radius: var(--c-radius);
  overflow: hidden;
}}
[data-testid="stProgressBarTrack"] > div {{ background: var(--c-primary); }}

/* --- inputs ---------------------------------------------------------- */
[data-baseweb="input"], [data-baseweb="select"] > div,
[data-baseweb="textarea"], [data-testid="stTextInputRootElement"] {{
  background: var(--c-panel);
  border-color: var(--c-border);
  border-radius: var(--c-radius);
}}
[data-baseweb="input"] input, [data-baseweb="textarea"] textarea {{
  color: var(--c-text);
}}

/* --- alerts ------------------------------------------------------------
   Severity comes back as a left rule, in semantic colour — deliberately
   never the accent. A warning that shares a hue with "here's your next
   lesson" stops reading as a warning. */
[data-testid="stAlertContainer"] {{ border-left: 3px solid var(--c-dim); }}
[data-testid="stAlert"] p, [data-testid="stAlert"] li {{ color: var(--c-text); }}
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentInfo"]) {{
  border-left-color: var(--c-alt);
}}
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentSuccess"]) {{
  border-left-color: var(--c-good);
}}
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentWarning"]) {{
  border-left-color: var(--c-warn);
}}
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentError"]) {{
  border-left-color: var(--c-bad);
}}

/* --- tabs and tables -------------------------------------------------- */
[data-baseweb="tab-list"] {{ background: transparent; border-bottom: 1px solid var(--c-border); }}
[data-baseweb="tab"] {{ color: var(--c-dim); }}
[data-baseweb="tab"][aria-selected="true"] {{ color: var(--c-primary); }}
[data-baseweb="tab-highlight"] {{ background: var(--c-primary); }}

.stApp [data-testid="stTable"] td, .stApp [data-testid="stTable"] th,
.stApp .stDataFrame {{ font-variant-numeric: tabular-nums; }}

/* --- sidebar nav ------------------------------------------------------ */
[data-testid="stSidebarNavLink"] {{ border-radius: var(--c-radius); }}
[data-testid="stSidebarNavLink"][aria-current="page"] {{
  background: var(--c-panel);
  color: var(--c-primary);
}}

hr, [data-testid="stSidebarNavSeparator"] {{ border-color: var(--c-border); }}
</style>
"""
