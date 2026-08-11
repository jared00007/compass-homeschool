"""Compass's one fixed look, and the CSS that puts it on the page.

Streamlit's own theming lives in `.streamlit/config.toml` and is read once when
the server starts, so it cannot answer "give every container real texture and a
title stroke" -- there is no variable layer to hook into. As of 1.61 Streamlit
bakes theme values into generated class names and declares no CSS custom
properties at all.

So this module does it the other way round. It declares its own custom properties
on `:root`, then repaints Streamlit's surfaces through them using `data-testid`
selectors — which are stable across versions because Streamlit's own test suite
depends on them. Everything the CSS can't reach (the insides of dropdown popovers,
date pickers, and the compliance dataframe, which renders to a canvas) is covered
by keeping `config.toml`'s base theme in step with this one -- light, to match --
so those native surfaces already look right underneath it.

This used to be five swappable themes with a per-person picker in the sidebar.
Retired on request: one consistent look, everywhere, for everyone -- picked after
previewing all five live and choosing Comic Book. `THEME` is the whole decision;
there is no lookup, no stored preference, and no picker UI left to remove it from.

The backdrop rule still holds: the page ground and the sidebar are fixed, not
themed. Color lives on the containers -- expanders, alerts, metrics, buttons --
never on the page behind them. `BACKDROP_BG`/`BACKDROP_SIDE` are the only place
that ground is defined, and `THEME` carries no version of its own to override it
with.
"""

from __future__ import annotations

from dataclasses import dataclass

# Faces that ship with macOS, so nothing downloads and the app looks right with no
# signal at a trailhead.
SANS = '-apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif'
MONO = 'ui-monospace, "SF Mono", "Cascadia Mono", Menlo, Consolas, monospace'

# The static backdrop. A warm, bright off-white pair rather than pure white/grey
# -- chosen, not inherited. See module docstring for why this stays fixed.
BACKDROP_BG = "#FBF1D6"
BACKDROP_SIDE = "#EAF1FC"
# A faint ink-blue texture on the sidebar only -- same repeating-gradient
# technique as a theme's own `panel_texture`, echoing the border/nav-accent
# blue instead of leaving the sidebar a flat, unvibed panel.
BACKDROP_SIDE_TEXTURE = (
    "repeating-radial-gradient(circle at 0 0, rgba(46,94,170,.10) 0 1.6px, "
    "transparent 1.6px 9px)"
)


@dataclass(frozen=True)
class Theme:
    key: str

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
    heading_stroke_color: str = "#000"
    heading_shadow: str = "none"      # a flat offset shadow behind the page title,
    # same comic-panel technique as `glow` on containers -- gives the title real
    # dimension instead of just being colored text
    heading_fill: str = "var(--c-text)"  # the page title's own colour, separate
    # from body text so it can pop without recoloring every h2-h4
    # The primary button prints in this colour over `primary`. Defaults to the
    # theme's own dark `text` -- checked with a contrast calculator against
    # `primary`, not by eye, since "looks fine" and "clears WCAG AA" aren't
    # the same claim.
    button_text: str = "var(--c-text)"
    panel_texture: str = "none"       # a background-image every container gets
    glow: str = "none"
    # Two-tone container frame. None on either side means "use `border`, plain".
    border_top: str | None = None
    border_bottom: str | None = None
    # A 4px stripe across each container's top edge. Transparent is a no-op.
    top_bar: str = "transparent"

    # Semantic colours. Kept separate from `primary` on purpose — "this needs you"
    # and "this is wrong" must never be the same colour, or a warning stops reading
    # as a warning.
    good: str = "#2F9B68"
    warn: str = "#B9791A"
    bad: str = "#C43B32"


THEME = Theme(
    key="comic",
    panel="#FFFBF0", text="#241C12", dim="#8A7A5E",
    primary="#F2B705", alt="#2F63E0", border="#2E5EAA",
    radius="3px",
    heading_font='"Avenir Next", "Helvetica Neue", ' + SANS,
    heading_caps="uppercase", heading_track=".02em", heading_weight="800",
    # A thin warm-ink stroke plus an offset shadow reads as a comic panel
    # title; the original 1.1px pure-black stroke was heavy enough to look
    # like a dark outline rather than an accent -- picked after previewing
    # four variants live and choosing this one.
    heading_stroke="0.6px", heading_stroke_color="#241C12",
    heading_shadow="3px 3px 0 rgba(36,28,18,.35)",
    heading_fill="var(--c-primary)",
    panel_texture=(
        "repeating-radial-gradient(circle at 100% 0%, "
        "rgba(36,28,18,.05) 0 1px, transparent 1px 7px)"
    ),
    glow="3px 3px 0 rgba(36,28,18,.16)",
)


def title_enforcer_script() -> str:
    """A belt-and-suspenders backstop for the page title's colour/stroke, on
    top of the `h1 *` CSS rule in `css()` that's the actual fix.

    The real bug (see `css()`'s comment on this): the visible glyphs live in
    a child `<span>` Streamlit wraps the heading text in, which a blanket
    `.stApp span` rule gives its own explicit (non-gold) colour -- the `<h1>`
    itself was gold the whole time, `getComputedStyle` on it said so, and
    that was never the element actually painting the text. Found only by
    sampling rendered pixels directly; every earlier check that inspected
    the `<h1>`'s own computed style was quietly checking the wrong element.

    This script is kept as a second layer in case a future Streamlit release
    restructures the heading markup in some other way the CSS selector
    doesn't anticipate. `<script>` tags inside `st.markdown(unsafe_allow_html=True)`
    are inert -- confirmed directly, browsers never execute script inserted
    via `innerHTML`-style rendering, which is how Streamlit renders markdown.
    `st.components.v1.html()` is the one Streamlit primitive that runs in a
    same-origin iframe with a real `srcdoc` document, so its script actually
    executes -- and `window.parent` from inside it reaches back into the
    real page. A `MutationObserver` keeps it applied across every rerun,
    since Streamlit replaces the title element's DOM node on each one.
    """
    t = THEME
    return f"""
<script>
(function() {{
  var win = window.parent;
  function apply() {{
    var els = win.document.querySelectorAll(
      '[data-testid="stHeading"] h1, [data-testid="stHeading"] h1 *, .stApp h1, .stApp h1 *'
    );
    els.forEach(function(el) {{
      el.style.setProperty('color', '{t.primary}', 'important');
      el.style.setProperty('-webkit-text-stroke', '{t.heading_stroke} {t.heading_stroke_color}', 'important');
      el.style.setProperty('text-shadow', '{t.heading_shadow}', 'important');
    }});
  }}
  apply();
  if (win.__compassTitleObserver) {{ win.__compassTitleObserver.disconnect(); }}
  var obs = new MutationObserver(apply);
  obs.observe(win.document.body, {{childList: true, subtree: true}});
  win.__compassTitleObserver = obs;
}})();
</script>
"""


def css() -> str:
    """The stylesheet that paints Streamlit in `THEME`.

    Selectors are `data-testid` attributes wherever possible. They are what
    Streamlit's own tests target, which makes them the most stable hook available
    — far more so than the emotion class names, which rehash between releases.
    """
    t = THEME
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
  --c-heading-stroke-color: {t.heading_stroke_color};
  --c-heading-shadow: {t.heading_shadow};
  --c-heading-fill: {t.heading_fill};
  --c-button-text: {t.button_text};
  --c-good: {t.good};
  --c-warn: {t.warn};
  --c-bad: {t.bad};
  --c-head: {t.heading_font};
  --c-body: {t.body_font};
  --c-mono: {t.mono_font};
}}

/* --- grounds -----------------------------------------------------------
   Fixed. Reads from BACKDROP_BG/BACKDROP_SIDE, never from a `Theme` field
   -- there isn't one to override this with. */
.stApp {{ background: {BACKDROP_BG}; font-family: var(--c-body); }}
[data-testid="stAppViewContainer"] {{ position: relative; z-index: 1; }}
[data-testid="stHeader"] {{ background: transparent; }}
[data-testid="stSidebar"] {{
  background: {BACKDROP_SIDE};
  background-image: {BACKDROP_SIDE_TEXTURE};
  border-right: 1px solid var(--c-border);
  /* Streamlit sets `height: auto` as an *inline* style on this element, which
     beats any stylesheet rule regardless of selector specificity -- `!important`
     is the only way a stylesheet wins that fight. Without it, the sidebar simply
     grows to fit its content, and once enough controls stack up (nine nav links,
     the profile editor, the mode control) that content outgrows a short window
     with nothing to scroll: not the sidebar, not the page behind it. Confirmed
     live: a 760px-tall window clipped everything below "Parent view" with no
     scrollbar reachable by any means, including the mouse wheel. */
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
   an inked stroke and the accent as its actual fill colour. Everything
   smaller (h2-h4: section headers, card titles) stays plain text colour, or
   a page reads as shouting by the third subheading.

   The real bug this rule exists to defeat, found only by sampling actual
   rendered pixels rather than trusting `getComputedStyle` on the `<h1>`
   itself: Streamlit wraps a heading's text in a child `<span>` (for
   `aria-labelledby`), and the blanket ".stApp span" colour rule two rules
   up (the one setting --c-text) matches that span directly. An element's
   own explicit colour always wins over whatever its parent computed to,
   `!important` or not -- `!important` only wins the cascade *for the
   element it's set on*, it doesn't propagate to children. So the `<h1>`
   itself was correctly gold the entire time; the visible glyphs, which
   live in that child span, never were. `h1 *` targets every descendant
   directly instead of depending on inheritance a more specific sibling
   rule can always defeat. */
[data-testid="stHeading"] h1, [data-testid="stHeading"] h1 *,
.stApp h1, .stApp h1 * {{
  color: var(--c-heading-fill) !important;
  -webkit-text-stroke: var(--c-heading-stroke) var(--c-heading-stroke-color) !important;
  text-shadow: var(--c-heading-shadow) !important;
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
   in the accent colour looked like a failure rather than a September Tuesday.
   The accent means "this is yours to act on"; a figure is just a figure. Size,
   weight and tabular figures carry the emphasis instead.

   The inner <p> has to be named explicitly: the blanket `.stApp p` rule above
   is equally specific and comes first, so inheritance alone loses.

   The white-space/overflow lines exist because Streamlit renders every metric
   value with `truncate: true` baked into the widget itself (Metric.*.js),
   which clips anything that doesn't fit the column to an ellipsis --
   "1.2 / 1..." instead of "1.2 / 1000". Four metrics per row (several pages
   here do that) leaves each one only a few hundred pixels wide, so this isn't
   an edge case, it's the normal width. The truncation is CSS on the value's
   own wrapper rather than something this app's Python controls, so the only
   place to defeat it is here: force it to wrap instead of clip. A number
   wrapping onto two lines still reads; a swallowed number does not. */
[data-testid="stMetricValue"], [data-testid="stMetricValue"] p {{
  color: var(--c-text);
  font-family: var(--c-mono);
  font-variant-numeric: tabular-nums;
  white-space: normal !important;
  overflow: visible !important;
  text-overflow: unset !important;
  overflow-wrap: break-word;
}}

/* Same clipping, same fix, for the little delta line under a metric
   ("+12 vs pace") -- it gets `truncate: true` from the same widget. */
[data-testid="stMetricDelta"], [data-testid="stMetricDelta"] p {{
  white-space: normal !important;
  overflow: visible !important;
  text-overflow: unset !important;
  overflow-wrap: break-word;
}}

/* And the metric's own label ("Subjects with instruction") -- same widget,
   same `truncate: true`, same fix. Deliberately not applied to the shared
   stWidgetLabel selector above: ordinary widget labels (text inputs, selects)
   don't get Streamlit's truncate behavior, so they don't need it. */
[data-testid="stMetricLabel"], [data-testid="stMetricLabel"] p {{
  white-space: normal !important;
  overflow: visible !important;
  text-overflow: unset !important;
  overflow-wrap: break-word;
}}

/* Dataframes render to a canvas, so their cells are out of CSS's reach and
   follow the base theme in config.toml instead. Framing the wrapper is all
   that can be done here — which is why config.toml's base is kept light, in
   step with this theme. */
[data-testid="stDataFrame"] {{
  border: 1px solid var(--c-border);
  border-radius: var(--c-radius);
  box-shadow: var(--c-glow);
}}

/* --- buttons ---------------------------------------------------------
   Primary buttons print in `--c-button-text`, not `--c-panel` -- panel is a
   light surface colour, and light-on-bright-primary would be close to
   unreadable. `--c-button-text` defaults to the theme's own dark `text`,
   checked against `primary` with a real contrast calculator (4.5:1, not
   "looks fine"). See the `button_text` field on `Theme`. */
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
  color: var(--c-button-text);
  border: 1px solid var(--c-primary);
  border-radius: var(--c-radius);
  box-shadow: var(--c-glow);
  font-weight: 600;
}}
[data-testid="stBaseButton-primary"]:hover,
[data-testid="stBaseButton-primaryFormSubmit"]:hover {{
  filter: brightness(1.06);
  color: var(--c-button-text);
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
/* `*` alongside the link itself, not just the link -- the label text lives in a
   child span, and per the page-title bug above, a child's own colour/weight/
   size always wins over the parent's, inherited or not. */
[data-testid="stSidebarNavLink"], [data-testid="stSidebarNavLink"] * {{
  font-size: 16px;
  font-weight: 700;
}}
[data-testid="stSidebarNavLink"][aria-current="page"] {{
  background: var(--c-panel);
  color: var(--c-primary);
}}

hr, [data-testid="stSidebarNavSeparator"] {{ border-color: var(--c-border); }}
</style>
"""
