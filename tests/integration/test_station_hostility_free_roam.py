"""Station self-defence in free roam: hit a station twice and it fires back;
it stays hostile across its own system and calms down when the player leaves.

Free roam is the SDK Quick Battle the game boots into. Hits go through the real
combat.apply_hit; the station's AI is BC's StarbaseAttack, ticked by the
headless sim.
"""
import pytest

pytest.importorskip("_dauntless_host")

from tests.helpers import headless_mission as hm  # noqa: E402
from tests.integration.test_quickbattle_setup_e2e import world  # noqa: E402,F401
from tests.integration.test_home_stations_free_roam import (  # noqa: E402
    _player, _warp_to_starbase_12)


def _close_to(player, station, gu=25.0):
    """Arrival is ~300 GU out, beyond phaser range; a player who is hitting a
    station is next to it."""
    from engine.appc.math import TGPoint3
    at = station.GetWorldLocation()
    player.SetTranslateXYZ(at.x + gu, at.y, at.z)


def _run(seconds):
    """The sim tick plus the host's per-frame weapon and combat steps: the
    sim tick alone never fires a weapon."""
    from engine import host_loop
    from engine.core.loop import GameLoop, TICK_DELTA
    loop = GameLoop()
    for _ in range(int(round(seconds / TICK_DELTA))):
        hm._sim_tick(loop)
        ships = list(host_loop._all_ships_for_tick())
        host_loop._advance_weapons(ships, TICK_DELTA)
        host_loop._advance_combat(ships, TICK_DELTA, ship_instances=None,
                                  push_render_data=False)


def _station(player):
    return player.GetContainingSet().GetObject("Starbase 12")


def _hit(station, player):
    from engine.appc import combat
    combat.apply_hit(station, 50.0, station.GetWorldLocation(), player,
                     weapon_type="phaser")


def _enemies():
    import App
    return App.Game_GetCurrentGame().GetCurrentEpisode().GetCurrentMission(
        ).GetEnemyGroup()


def _turn_hostile(world):
    from engine.systems import station_hostility
    player = _warp_to_starbase_12()
    hm.tick(1.0)
    station = _station(player)
    _hit(station, player)
    hm.tick(6.0)
    _hit(station, player)
    assert station_hostility.is_hostile(station)
    return player, station


def test_starbase_12_fires_back(world):
    player = _warp_to_starbase_12()
    hm.tick(1.0)
    station = _station(player)
    _close_to(player, station)
    shields, hull = player.GetShields(), player.GetHull()
    start = (hull.GetCondition(),
             sum(shields.GetCurShields(i) for i in range(6)))
    _hit(station, player)
    hm.tick(6.0)
    _hit(station, player)
    assert _enemies().IsNameInGroup("Starbase 12")
    _run(20.0)
    now = (hull.GetCondition(),
           sum(shields.GetCurShields(i) for i in range(6)))
    assert now[0] < start[0] or now[1] < start[1], (start, now)


def test_the_dry_docks_keep_it_hostile(world):
    from engine.systems import station_hostility
    player, station = _turn_hostile(world)
    button = hm.the_warp_button()
    hm.plot_course(button, "Systems.DryDock.DryDock")
    hm.warp_and_wait(button, player)
    assert player.GetContainingSet().GetName() == "DryDock"
    assert station_hostility.is_hostile(station)
    assert _enemies().IsNameInGroup("Starbase 12")


def test_leaving_tau_ceti_ends_it(world):
    from engine.systems import station_hostility
    player, station = _turn_hostile(world)
    button = hm.the_warp_button()
    hm.plot_course(button, "Systems.Vesuvi.Vesuvi4")
    hm.warp_and_wait(button, player)
    assert player.GetContainingSet().GetName() != "Starbase12"
    assert not station_hostility.is_hostile(station)
    assert not _enemies().IsNameInGroup("Starbase 12")
    assert station.GetAI() is None


def test_a_campaign_mission_never_counts(world):
    from engine.systems import station_hostility
    import App
    assert station_hostility._active
    hm.load("Maelstrom.Episode1.E1M1.E1M1")
    player = App.Game_GetCurrentPlayer()
    import loadspacehelper
    from tests.helpers.mapped_regions import load_region
    sb = load_region("TauCeti", "Starbase12")
    station = App.ShipClass_GetObject(sb, "Starbase 12")
    assert station is not None
    assert not station_hostility._active
    from engine.appc import combat
    for _ in range(2):
        combat.apply_hit(station, 50.0, station.GetWorldLocation(), player,
                         weapon_type="phaser")
        hm.tick(6.0)
    assert not station_hostility.is_hostile(station)
