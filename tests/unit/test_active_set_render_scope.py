"""Rendering is scoped to the player's active set; simulation stays global.

BC renders one space set at a time — the player at Serris 3 must not see the
Vesuvi 6 Facility or the Starbase 12 starbase bleed into the scene. But
off-screen scripted activity (e.g. M3Gameflow's Biranu1 duel while the player is
in Biranu2) must keep simulating. So:

  iter_active_ships  -> ships in the player's set only  (RENDER roster)
  iter_ships         -> ships in every set              (SIM roster)
"""
import App
import pytest

from engine.appc.ship_iter import iter_ships, iter_active_ships, active_set
from engine.appc.sets import SetClass
from engine.appc.ships import ShipClass
from engine.core.game import Game, _set_current_game


@pytest.fixture(autouse=True)
def _clean_sets_and_game():
    App.g_kSetManager._sets.clear()
    _set_current_game(None)
    yield
    App.g_kSetManager._sets.clear()
    _set_current_game(None)


def _make_set(name):
    s = SetClass()
    s.SetName(name)
    App.g_kSetManager.AddSet(s, name)
    return s


def test_active_set_is_the_players_set():
    home = _make_set("Serris3")
    away = _make_set("Vesuvi6")
    player = ShipClass()
    home.AddObjectToSet(player, "player")
    away.AddObjectToSet(ShipClass(), "Facility")

    game = Game()
    game.SetPlayer(player)
    _set_current_game(game)

    assert active_set() is home


def test_render_roster_excludes_other_sets_but_sim_roster_includes_them():
    home = _make_set("Serris3")
    away = _make_set("Vesuvi6")
    player = ShipClass()
    home.AddObjectToSet(player, "player")
    away.AddObjectToSet(ShipClass(), "Facility")

    game = Game()
    game.SetPlayer(player)
    _set_current_game(game)

    render = sorted(s.GetName() for s in iter_active_ships())
    sim = sorted(s.GetName() for s in iter_ships())

    assert render == ["player"]                       # no Facility bleed
    assert sim == ["Facility", "player"]              # sim still sees both


def test_render_roster_falls_back_to_all_sets_without_a_player():
    a = _make_set("SetA")
    b = _make_set("SetB")
    a.AddObjectToSet(ShipClass(), "Alpha")
    b.AddObjectToSet(ShipClass(), "Beta")
    # No current game/player -> active_set() is None -> render sees everything.
    assert active_set() is None
    assert sorted(s.GetName() for s in iter_active_ships()) == ["Alpha", "Beta"]
