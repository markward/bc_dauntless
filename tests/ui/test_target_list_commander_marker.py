"""Target list rows carry a `commander` flag: True only for the current
commander of a led wing. Always on (no dev mode, no toggle); the page draws
a command chevron from it (tests/ui/test_target_list_js.py)."""
import json

import App
import pytest

from engine import dev_mode
from engine.appc.ships import ShipClass
from engine.wings import roster, service
from tests.unit.test_target_list_view import (
    _listed, _setup_game_with_player)


@pytest.fixture(autouse=True)
def _clean():
    service.reset_all()
    yield
    service.reset_all()


@pytest.fixture
def scene(monkeypatch):
    """Lead + Wingman in one wing, Loner in none. Yields (view, wing)."""
    from engine.core.game import _set_current_game
    from engine.ui.target_list_view import TargetListView
    # Production: no developer flag.
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: False)
    App._reset_target_menu_singleton()
    tm = App.STTargetMenu_CreateW("Targets")
    game, player, mission = _setup_game_with_player()
    try:
        for n in ("Lead", "Wingman", "Loner"):
            mission.GetEnemyGroup().AddName(n)
        ships = []
        for n in ("Lead", "Wingman", "Loner"):
            s = ShipClass(); s.SetName(n); ships.append(s)
        tm.set_contacts(_listed(*ships))
        tm.ResetAffiliationColors()
        wing = roster.create_wing("w1", mission.GetEnemyGroup())
        roster.add_member(wing, "Lead")
        roster.add_member(wing, "Wingman")
        wing.commander = "Lead"
        yield TargetListView(), wing
    finally:
        _set_current_game(None)


def _rows(js):
    return {r["name"]: r for r in json.loads(js[len("setTargetList("):-2])["rows"]}


def test_commander_flag_only_on_the_current_commander(scene):
    view, _wing = scene
    rows = _rows(view.render_payload())
    assert rows["Lead"]["commander"] is True
    assert rows["Wingman"]["commander"] is False
    assert rows["Loner"]["commander"] is False


def test_label_is_never_prefixed(scene):
    view, _wing = scene
    rows = _rows(view.render_payload())
    assert rows["Lead"]["label"] == "Lead"


def test_leaderless_wing_has_no_commander(scene):
    view, wing = scene
    wing.leaderless = True
    rows = _rows(view.render_payload())
    assert not any(r["commander"] for r in rows.values())


def test_handover_re_emits_and_moves_the_flag(scene):
    view, wing = scene
    assert view.render_payload() is not None
    assert view.render_payload() is None          # unchanged: no re-emit
    wing.commander = "Wingman"
    rows = _rows(view.render_payload())
    assert rows["Lead"]["commander"] is False
    assert rows["Wingman"]["commander"] is True


def test_focus_flag_only_on_the_player_wings_primary(scene):
    view, wing = scene
    wing.primary = "Loner"
    service.set_player_wing(wing.wing_id)
    rows = _rows(view.render_payload())
    assert rows["Loner"]["focus"] is True
    assert rows["Lead"]["focus"] is False
    assert rows["Wingman"]["focus"] is False


def test_focus_re_emits_when_the_primary_changes(scene):
    view, wing = scene
    wing.primary = "Loner"
    service.set_player_wing(wing.wing_id)
    assert view.render_payload() is not None
    assert view.render_payload() is None
    wing.primary = "Wingman"
    rows = _rows(view.render_payload())
    assert rows["Wingman"]["focus"] is True and rows["Loner"]["focus"] is False


def test_no_player_wing_no_focus(scene):
    view, wing = scene
    wing.primary = "Loner"
    rows = _rows(view.render_payload())
    assert not any(r["focus"] for r in rows.values())
