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

    def caption(self, *args, **kwargs):
        pass

    def button(self, *args, **kwargs):
        return False

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


class _AssignSt(_FakeSt):
    """Drives the assign branch: the checkbox reads as ticked, the date picker
    returns `picked`, and the "Assign to this day" button reports `click`."""

    def __init__(self, *, picked, click: bool) -> None:
        super().__init__()
        self._picked = picked
        self._click = click

    def checkbox(self, *args, **kwargs):
        return True  # "Assign to a specific day" is ticked

    def date_input(self, *args, **kwargs):
        return self._picked

    def button(self, label, *args, **kwargs):
        return self._click if "Assign to this day" in label else False


def test_ticking_assign_without_the_button_does_not_schedule(monkeypatch):
    """The reported bug: merely opening the picker (the box ticked, the date
    defaulting to today) used to fire schedule() and jump the card to today.
    Now nothing is written until the Assign button is clicked."""
    import datetime as _dt

    scheduled: list[str | None] = []
    fake = _AssignSt(picked=_dt.date.today(), click=False)
    monkeypatch.setattr(ui, "st", fake)
    ui.render_story_move_control(
        key="x", active=True, scheduled_for=None,
        set_active=lambda a: None, schedule=lambda s: scheduled.append(s),
    )
    assert scheduled == []  # nothing scheduled just from opening the picker


def test_clicking_assign_schedules_the_picked_day(monkeypatch):
    import datetime as _dt

    picked = _dt.date.today() + _dt.timedelta(days=5)
    scheduled: list[str | None] = []
    fake = _AssignSt(picked=picked, click=True)
    monkeypatch.setattr(ui, "st", fake)
    ui.render_story_move_control(
        key="x", active=False, scheduled_for=None,
        set_active=lambda a: None, schedule=lambda s: scheduled.append(s),
    )
    assert scheduled == [picked.isoformat()]  # the day the parent chose


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


# --- the optional Delete section (lessons only) ------------------------------
# Reported: "i need the ability to DELETE a single generated [lesson] in its
# edit card ... a simple delete, and then warning, once gone its gone for good."


class _DeleteSt(_FakeSt):
    """Drives the delete branch: `confirm` is what the confirm checkbox
    reports, `click` is what the Delete button reports. Records every button
    label + disabled flag so a test can assert the gate."""

    def __init__(self, *, confirm: bool = False, click: bool = False) -> None:
        super().__init__()
        self._confirm = confirm
        self._click = click
        self.buttons: list[tuple[str, bool]] = []

    def checkbox(self, label, *args, **kwargs):
        return self._confirm if "delete" in label.lower() else False

    def button(self, label, *args, **kwargs):
        self.buttons.append((label, bool(kwargs.get("disabled"))))
        return self._click if label == "🗑️ Delete" else False


def _run_with_delete(monkeypatch, fake, deleted):
    monkeypatch.setattr(ui, "st", fake)
    ui.render_story_move_control(
        key="x",
        active=True,
        scheduled_for=None,
        set_active=lambda a: None,
        schedule=lambda s: None,
        delete=lambda: deleted.append(True),
    )


def test_no_delete_button_when_delete_is_not_wired(monkeypatch):
    fake = _DeleteSt()
    monkeypatch.setattr(ui, "st", fake)
    ui.render_story_move_control(
        key="x", active=True, scheduled_for=None,
        set_active=lambda a: None, schedule=lambda s: None,
    )
    assert not any(label == "🗑️ Delete" for label, _ in fake.buttons)


def test_delete_button_is_disabled_until_confirmed(monkeypatch):
    deleted: list[bool] = []
    fake = _DeleteSt(confirm=False, click=False)
    _run_with_delete(monkeypatch, fake, deleted)
    delete_btns = [(label, disabled) for label, disabled in fake.buttons if label == "🗑️ Delete"]
    assert delete_btns == [("🗑️ Delete", True)]  # present but disabled
    assert deleted == []  # nothing deleted


def test_confirming_and_clicking_delete_fires_the_callback(monkeypatch):
    deleted: list[bool] = []
    fake = _DeleteSt(confirm=True, click=True)
    _run_with_delete(monkeypatch, fake, deleted)
    delete_btns = [(label, disabled) for label, disabled in fake.buttons if label == "🗑️ Delete"]
    assert delete_btns == [("🗑️ Delete", False)]  # enabled once confirmed
    assert deleted == [True]  # callback fired
