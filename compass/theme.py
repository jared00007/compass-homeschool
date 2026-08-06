"""The four themes, and the CSS that puts one of them on the page.

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
base, which is why all four themes here are dark. A light theme would need that
base changed and the app relaunched; it is not something a picker can do.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Faces that ship with macOS, so nothing downloads and the app looks right with no
# signal at a trailhead.
SANS = '-apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif'
MONO = 'ui-monospace, "SF Mono", "Cascadia Mono", Menlo, Consolas, monospace'


@dataclass(frozen=True)
class Theme:
    key: str
    name: str
    tagline: str

    bg: str          # page ground
    panel: str       # cards, expanders, inputs
    side: str        # sidebar ground
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
    texture: str = "none"
    glow: str = "none"

    # Semantic colours. Kept separate from `primary` on purpose — "this needs you"
    # and "this is wrong" must never be the same colour, or a warning stops reading
    # as a warning.
    good: str = "#3FB37F"
    warn: str = "#E0A32E"
    bad: str = "#E5544B"


THEMES: dict[str, Theme] = {
    "techtree": Theme(
        key="techtree",
        name="Tech Tree",
        tagline="Ember on deep pine",
        bg="#060D0C", panel="#0C1817", side="#040908",
        text="#E8F0EC", dim="#6E8880", primary="#FF7A18", alt="#2FB8A0",
        border="#172422", radius="3px",
        heading_caps="uppercase", heading_track=".045em", heading_weight="800",
        texture=(
            "radial-gradient(ellipse 120% 80% at 50% -10%, "
            "rgba(47,184,160,.10), transparent 60%)"
        ),
        glow="0 0 14px rgba(255,122,24,.45)",
    ),
    "arcade": Theme(
        key="arcade",
        name="Arcade",
        tagline="Cabinet art, four colours",
        bg="#14071F", panel="#1F0C2E", side="#0E0417",
        text="#F5E9FF", dim="#9C7CB8", primary="#FF3D7F", alt="#00E5FF",
        border="#35174A", radius="2px",
        heading_font='"Futura", "Futura PT", "Century Gothic", "Avenir Next", ' + SANS,
        heading_caps="uppercase", heading_track=".10em", heading_weight="700",
        texture=(
            "repeating-linear-gradient(to bottom, rgba(255,255,255,.035) 0 1px, "
            "transparent 1px 3px), "
            "radial-gradient(ellipse 90% 60% at 50% 0%, rgba(0,229,255,.10), transparent 65%)"
        ),
        glow="0 0 16px rgba(255,61,127,.5)",
        warn="#FFD400",
    ),
    "highvis": Theme(
        key="highvis",
        name="High-Vis",
        tagline="Rally truck, hazard tape",
        bg="#16171A", panel="#1E2024", side="#101114",
        text="#F2F2EE", dim="#8B8E95", primary="#FF5A1F", alt="#FFD23F",
        border="#2C2F35", radius="2px",
        heading_font='"Avenir Next Condensed", "HelveticaNeue-CondensedBold", '
                     '"Arial Narrow", ' + SANS,
        heading_caps="uppercase", heading_track=".02em", heading_weight="700",
        texture=(
            "repeating-linear-gradient(135deg, rgba(255,210,63,.04) 0 12px, "
            "transparent 12px 34px)"
        ),
        glow="0 0 10px rgba(255,90,31,.4)",
    ),
    "blueprint": Theme(
        key="blueprint",
        name="Blueprint",
        tagline="Drafting table, red callouts",
        bg="#071627", panel="#0B2038", side="#050F1C",
        text="#DDEBF7", dim="#6E93B4", primary="#FF4438", alt="#3FA9E0",
        border="#123A5C", radius="0px",
        heading_caps="uppercase", heading_track=".07em", heading_weight="600",
        texture=(
            "repeating-linear-gradient(to right, rgba(63,169,224,.07) 0 1px, "
            "transparent 1px 26px), "
            "repeating-linear-gradient(to bottom, rgba(63,169,224,.07) 0 1px, "
            "transparent 1px 26px)"
        ),
        glow="0 0 10px rgba(255,68,56,.45)",
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
    return f"""
<style id="compass-theme" data-theme="{t.key}">
:root {{
  --c-bg: {t.bg};
  --c-panel: {t.panel};
  --c-side: {t.side};
  --c-text: {t.text};
  --c-dim: {t.dim};
  --c-primary: {t.primary};
  --c-alt: {t.alt};
  --c-border: {t.border};
  --c-radius: {t.radius};
  --c-glow: {t.glow};
  --c-good: {t.good};
  --c-warn: {t.warn};
  --c-bad: {t.bad};
  --c-head: {t.heading_font};
  --c-body: {t.body_font};
  --c-mono: {t.mono_font};
}}

/* --- grounds --------------------------------------------------------- */
.stApp {{ background: var(--c-bg); font-family: var(--c-body); }}
.stApp::before {{
  content: ""; position: fixed; inset: 0; z-index: 0;
  background: {t.texture}; pointer-events: none;
}}
[data-testid="stAppViewContainer"] {{ position: relative; z-index: 1; }}
[data-testid="stHeader"] {{ background: transparent; }}
[data-testid="stSidebar"] {{
  background: var(--c-side);
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

/* --- containers ------------------------------------------------------ */
[data-testid="stVerticalBlockBorderWrapper"]:has(> div > [data-testid="stVerticalBlock"]) {{
  border-radius: var(--c-radius);
}}
[data-testid="stExpander"] details {{
  background: var(--c-panel);
  border: 1px solid var(--c-border);
  border-radius: var(--c-radius);
}}
[data-testid="stExpander"] summary:hover {{ color: var(--c-primary); }}

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
  color: var(--c-bg);
  border: 1px solid var(--c-primary);
  border-radius: var(--c-radius);
  box-shadow: var(--c-glow);
  font-weight: 600;
}}
[data-testid="stBaseButton-primary"]:hover,
[data-testid="stBaseButton-primaryFormSubmit"]:hover {{
  filter: brightness(1.12);
  color: var(--c-bg);
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

/* --- alerts ----------------------------------------------------------
   Streamlit's own tint sits on the *container*, not on stAlert, so that is
   what has to be repainted. Severity then comes back as a left rule, in
   semantic colour — deliberately never the accent. A warning that shares a
   hue with "here's your next lesson" stops reading as a warning. */
[data-testid="stAlertContainer"] {{
  background: var(--c-panel);
  border-radius: var(--c-radius);
  border-left: 3px solid var(--c-dim);
}}
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
