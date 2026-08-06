"""The theme layer.

Themes are cosmetic, so most of what's worth testing is the parts that aren't:
that a stored key can't crash the app, that the parent's choice and the student's
choice stay separate, and that the generated CSS is actually well-formed — a
stray brace in an f-string ships a broken stylesheet with no error anywhere.
"""

from __future__ import annotations

import re

import pytest

from compass import theme
from compass.storage.db import Database


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    yield database
    database.close()


def test_every_theme_is_self_consistent():
    for key, t in theme.THEMES.items():
        assert t.key == key, "the dict key and the theme's own key must agree"
        assert t.name and t.tagline
        for field in ("bg", "panel", "side", "text", "dim", "primary", "alt", "border"):
            value = getattr(t, field)
            assert re.fullmatch(r"#[0-9A-Fa-f]{6}", value), f"{key}.{field} = {value!r}"


def test_the_default_theme_exists():
    assert theme.DEFAULT_THEME in theme.THEMES


def test_an_unknown_or_missing_key_falls_back_rather_than_raising():
    """A theme removed in a later version must not brick a saved setting."""
    assert theme.get("a-theme-that-was-deleted").key == theme.DEFAULT_THEME
    assert theme.get(None).key == theme.DEFAULT_THEME
    assert theme.get("").key == theme.DEFAULT_THEME


def test_accent_is_never_a_semantic_colour():
    """The accent means "act on this". A warning must not borrow it."""
    for key, t in theme.THEMES.items():
        assert t.primary.lower() not in {t.good.lower(), t.bad.lower()}, key


def test_css_is_balanced_and_carries_the_theme():
    for key, t in theme.THEMES.items():
        css = theme.css(t)
        assert css.count("{") == css.count("}"), f"{key} has unbalanced braces"
        assert "{{" not in css and "}}" not in css, f"{key} leaked f-string escapes"
        assert f'data-theme="{key}"' in css
        assert t.bg in css and t.primary in css and t.border in css
        assert "compass-theme" in css


def test_css_forces_the_sidebar_to_scroll():
    """Regression: Streamlit sets `height: auto` as an *inline* style on the
    sidebar, so it grows to fit its content instead of the window. Once enough
    controls stack up -- nine nav links, the profile editor, the mode control,
    the theme picker -- that content outgrew a short browser window with no
    scrollbar reachable anywhere, by mouse wheel or otherwise. `!important` is
    the only thing in a stylesheet that beats an inline style."""
    css = theme.css(theme.THEMES[theme.DEFAULT_THEME])
    block = css.split('[data-testid="stSidebar"]', 1)[1].split("}")[0]
    assert "height: 100vh !important" in block
    assert "overflow-y: auto !important" in block


def test_css_never_paints_metrics_in_the_accent():
    """Regression: every metric in the accent made compliance read as alarms."""
    css = theme.css(theme.THEMES["blueprint"])
    # The selector is listed twice in one rule, so take the declaration block —
    # everything between the last mention of it and the closing brace.
    block = css.rsplit('[data-testid="stMetricValue"]', 1)[1].split("}")[0]
    assert "var(--c-text)" in block
    assert "var(--c-primary)" not in block


def test_parent_and_student_keys_are_distinct(db):
    assert theme.PARENT_KEY != theme.STUDENT_KEY

    db.set_setting(theme.STUDENT_KEY, "arcade")
    db.set_setting(theme.PARENT_KEY, "blueprint")

    assert theme.get(db.get_setting(theme.STUDENT_KEY)).key == "arcade"
    assert theme.get(db.get_setting(theme.PARENT_KEY)).key == "blueprint"


def test_an_unset_choice_falls_back_to_the_default(db):
    assert theme.get(db.get_setting(theme.STUDENT_KEY)).key == theme.DEFAULT_THEME
