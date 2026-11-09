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


def _labels(monkeypatch, dev, markers):
    from engine.core.game import _set_current_game
    from engine.ui.target_list_view import TargetListView
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: dev)
    service.set_show_markers(markers)
    App._reset_target_menu_singleton()
    tm = App.STTargetMenu_CreateW("Targets")
    game, player, mission = _setup_game_with_player()
    try:
        mission.GetEnemyGroup().AddName("Lead")
        mission.GetEnemyGroup().AddName("Wingman")
        a = ShipClass(); a.SetName("Lead")
        b = ShipClass(); b.SetName("Wingman")
        tm.set_contacts(_listed(a, b))
        tm.ResetAffiliationColors()
        wing = roster.create_wing("w1", mission.GetEnemyGroup())
        roster.add_member(wing, "Lead")
        roster.add_member(wing, "Wingman")
        wing.commander = "Lead"
        js = TargetListView().render_payload()
        rows = json.loads(js[len("setTargetList("):-2])["rows"]
        return {r["name"]: r["label"] for r in rows}
    finally:
        _set_current_game(None)


def test_marker_only_on_commander_with_dev_and_toggle(monkeypatch):
    lab = _labels(monkeypatch, True, True)
    assert lab["Lead"].startswith("★ ")
    assert not lab["Wingman"].startswith("★")


def test_no_marker_without_toggle(monkeypatch):
    assert not _labels(monkeypatch, True, False)["Lead"].startswith("★")


def test_no_marker_without_dev_mode(monkeypatch):
    assert not _labels(monkeypatch, False, True)["Lead"].startswith("★")
