"""Unit coverage for `render_story_move_control`'s own label logic --
the one bit of it worth testing in isolation from any real page, since
every caller across the app shares this exact function.
"""

from __future__ import annotations

from compass import ui


class _FakePopover:
    def __init__(self, label: str) -> None:
        self.label = label

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeSt:
    """Just enough of `st` to run one call of `render_story_move_control`
    without touching any real widget state -- `checkbox` always reports
    "nothing changed" so the function falls straight through to nothing
    but the label computation and the popover call itself."""

    def __init__(self) -> None:
        self.popover_labels: list[str] = []

    def popover(self, label, **kwargs):
        self.popover_labels.append(label)
        return _FakePopover(label)

    def checkbox(self, *args, **kwargs):
        return False

    def date_input(self, *args, **kwargs):
        return None

    def divider(self):
        pass

    def error(self, *args, **kwargs):
        pass

    def rerun(self):
        pass


def _label_for(monkeypatch, *, active: bool, scheduled_for: str | None) -> str:
    fake = _FakeSt()
    monkeypatch.setattr(ui, "st", fake)
    ui.render_story_move_control(
        key="x",
        active=active,
        scheduled_for=scheduled_for,
        set_active=lambda a: None,
        schedule=lambda s: None,
    )
    assert len(fake.popover_labels) == 1
    return fake.popover_labels[0]


def test_a_backlogged_story_shows_backlog_even_with_a_leftover_date(monkeypatch):
    """The actual bug this guards: none of `set_active`/`send_to_backlog`'s
    real implementations clear `scheduled_for`/`planned_for` when a story
    gets backlogged, so a story backlogged after already being assigned a
    day used to keep showing that stale date instead of reading as
    backlogged at a glance."""
    label = _label_for(monkeypatch, active=False, scheduled_for="2026-09-01")
    assert label == "🗄️ Backlog"


def test_an_active_scheduled_story_shows_its_date(monkeypatch):
    label = _label_for(monkeypatch, active=True, scheduled_for="2026-09-01")
    assert label == "📅 2026-09-01"


def test_an_active_unscheduled_story_shows_the_icon_alone(monkeypatch):
    label = _label_for(monkeypatch, active=True, scheduled_for=None)
    assert label == "📅"


def test_a_backlogged_unscheduled_story_also_shows_backlog(monkeypatch):
    label = _label_for(monkeypatch, active=False, scheduled_for=None)
    assert label == "🗄️ Backlog"
