"""HUD panel cadences: radar 20 Hz, crew menu / player ship / weapons 10 Hz.

Continuous data may trail by the interval; discrete changes and every piece
of interaction draw on the next frame (mark_due, never a wait).
"""
import ast
from types import SimpleNamespace

import pytest

from engine import host_loop
from engine.ui import (crew_menu_panel, sensors_panel, ship_display_panel,
                       weapons_display_panel)
from engine.ui.crew_menu_panel import CrewMenuPanel
from engine.ui.panel_registry import PanelRegistry
from engine.ui.sensors_panel import SensorsPanel
from engine.ui.ship_display_panel import ShipDisplayPanel
from engine.ui.weapons_display_panel import WeaponsDisplayPanel
from tests.helpers import host_frame_source


class _Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


def _counting(panel):
    """Count render_payload calls (the snapshot builder) on one panel."""
    panel.builds = 0
    real = panel.render_payload

    def counted():
        panel.builds += 1
        return real()
    panel.render_payload = counted
    return panel


def _make_all():
    return [SensorsPanel(), CrewMenuPanel(), ShipDisplayPanel("player"),
            WeaponsDisplayPanel()]


def test_each_panel_declares_its_cadence():
    assert sensors_panel.SENSORS_POLL_S == 0.05
    assert crew_menu_panel.CREW_MENU_POLL_S == 0.1
    assert ship_display_panel.PLAYER_SHIP_POLL_S == 0.1
    assert weapons_display_panel.WEAPONS_POLL_S == 0.1
    assert SensorsPanel().poll_interval_s == 0.05
    assert CrewMenuPanel().poll_interval_s == 0.1
    assert ShipDisplayPanel("player").poll_interval_s == 0.1
    assert WeaponsDisplayPanel().poll_interval_s == 0.1
    assert ShipDisplayPanel("target").poll_interval_s == 0.0


@pytest.mark.parametrize("make", [SensorsPanel, CrewMenuPanel,
                                  lambda: ShipDisplayPanel("player"),
                                  WeaponsDisplayPanel])
def test_throttled_panel_skips_until_interval(make):
    clock = _Clock()
    reg = PanelRegistry(clock=clock)
    p = _counting(make())
    reg.register(p)
    reg.render_all()                       # first poll (starts due)
    assert p.builds == 1
    clock.advance(p.poll_interval_s * 0.4)
    reg.render_all()
    reg.render_all()
    assert p.builds == 1
    clock.advance(p.poll_interval_s)
    reg.render_all()
    assert p.builds == 2


def _crew_menu_setup():
    import App
    App.g_kSetManager  # noqa: B018  (import side effects only)
    clock = _Clock()
    reg = PanelRegistry(clock=clock)
    p = _counting(CrewMenuPanel())
    reg.register(p)
    reg.render_all()
    clock.advance(0.01)                    # well inside the interval
    return reg, p


class _FakeMenu:
    def SendActivationEvent(self):
        pass


@pytest.fixture
def fake_menu(monkeypatch):
    monkeypatch.setattr(crew_menu_panel, "ensure_widget_id", lambda m: 7)
    return _FakeMenu()


def test_keyboard_show_menu_draws_next_frame(fake_menu):
    reg, p = _crew_menu_setup()
    builds = p.builds
    p.show_menu(fake_menu)
    reg.render_all()
    assert p.builds == builds + 1


def test_keyboard_hide_menu_draws_next_frame(fake_menu):
    reg, p = _crew_menu_setup()
    p.show_menu(fake_menu)
    reg.render_all()
    builds = p.builds
    p.hide_menu()
    reg.render_all()
    assert p.builds == builds + 1


@pytest.fixture
def hud_world():
    host_loop._hud_change_state.clear()
    clock = _Clock()
    reg = PanelRegistry(clock=clock)
    panels = {p.name: _counting(p) for p in _make_all()}
    for p in panels.values():
        reg.register(p)
    reg.render_all()
    clock.advance(0.01)
    for p in panels.values():
        assert not p._render_due
    yield reg, panels
    host_loop._hud_change_state.clear()


class _Ship:
    def __init__(self):
        self.target = None
        self.sub = None
        self.alert = 0

    def GetTarget(self):
        return self.target

    def GetTargetSubsystem(self):
        return self.sub

    def GetAlertLevel(self):
        return self.alert


def test_target_change_marks_sensors_and_weapons_due(hud_world):
    reg, panels = hud_world
    ship = _Ship()
    host_loop._mark_hud_due_on_changes(reg, ship)      # baseline
    for p in panels.values():
        p._render_due = False
    ship.target = object()
    host_loop._mark_hud_due_on_changes(reg, ship)
    assert panels["sensors"]._render_due
    assert panels["weapons"]._render_due


def test_alert_change_marks_crew_menu_and_weapons_due(hud_world):
    reg, panels = hud_world
    ship = _Ship()
    host_loop._mark_hud_due_on_changes(reg, ship)
    for p in panels.values():
        p._render_due = False
    ship.alert = 2
    host_loop._mark_hud_due_on_changes(reg, ship)
    assert panels["crew-menu"]._render_due
    assert panels["weapons"]._render_due
    assert not panels["sensors"]._render_due


def test_no_change_marks_nothing(hud_world):
    reg, panels = hud_world
    ship = _Ship()
    host_loop._mark_hud_due_on_changes(reg, ship)
    for p in panels.values():
        p._render_due = False
    host_loop._mark_hud_due_on_changes(reg, ship)
    assert not any(p._render_due for p in panels.values())


def test_invalidate_all_still_redraws_throttled_panels(hud_world):
    reg, panels = hud_world
    before = {n: p.builds for n, p in panels.items()}
    reg.invalidate_all()
    reg.render_all()
    for n, p in panels.items():
        assert p.builds == before[n] + 1, n


def test_run_calls_the_helper_every_frame():
    tree = host_frame_source.run_tree()
    calls = [c for c in ast.walk(tree) if isinstance(c, ast.Call)
             and ast.unparse(c.func) == "_mark_hud_due_on_changes"]
    assert len(calls) == 1
