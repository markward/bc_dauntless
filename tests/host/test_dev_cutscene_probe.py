# tests/host/test_dev_cutscene_probe.py
"""The dev cutscene-camera probe sets up a live PlacementWatch on the current
player so _active_cutscene_camera() engages, and reverts on stop."""
import App
from engine.appc.math import TGPoint3
from engine.core.game import Game, _set_current_game
from engine import dev_cutscene_probe
from engine.host_loop import _active_cutscene_camera


def _player_in_set(set_name):
    s = App.SetClass_Create()
    App.g_kSetManager.AddSet(s, set_name)
    ship = App.ShipClass_Create("Galaxy")
    ship.SetTranslate(TGPoint3(0.0, 0.0, 0.0))
    s.AddObjectToSet(ship, "player")
    App.g_kSetManager.MakeRenderedSet(set_name)
    return s, ship


def _make_current_player(ship):
    game = Game()
    game.SetPlayer(ship)
    _set_current_game(game)
    return game


def test_probe_start_engages_override_then_stop_reverts():
    s, ship = _player_in_set("probe_set")
    _make_current_player(ship)
    dev_cutscene_probe._active[0] = False   # clean state

    dev_cutscene_probe.start()
    try:
        assert dev_cutscene_probe.is_active()
        cc = _active_cutscene_camera()
        assert cc is not None                       # override engaged
        eye, fwd, up = cc[1].Update(0.0)
        # Vantage sits off the ship (starboard/up/behind), not at the origin.
        assert (eye[0] ** 2 + eye[1] ** 2 + eye[2] ** 2) > 1.0
    finally:
        dev_cutscene_probe.stop()

    assert not dev_cutscene_probe.is_active()
    assert _active_cutscene_camera() is None         # reverted
    App.g_kSetManager.DeleteSet("probe_set")


def test_probe_start_without_player_is_safe():
    game = Game()
    game.SetPlayer(None)
    _set_current_game(game)
    dev_cutscene_probe._active[0] = False
    dev_cutscene_probe.start()                        # must not raise
    assert not dev_cutscene_probe.is_active()
