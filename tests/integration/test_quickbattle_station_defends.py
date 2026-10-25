"""Headless: a Quick Battle station fights back.

Every phaser on the stock Fed Starbase has its ArcHeightAngles authored
larger-first (fedstarbase.py), so a gate reading them literally as
lo <= pitch <= hi admitted nothing and the station never fired, though its
StarbaseAI targeted the player and called StartFiring every 3 s. Driven
from the setup panel through BC's own AI and the host's per-frame weapon and
combat steps (host_loop._advance_weapons / _advance_combat): the sim tick
alone never fires a weapon.
"""
import pytest

pytest.importorskip("_dauntless_host")

from tests.integration.test_quickbattle_setup_e2e import (  # noqa: E402,F401
    _do, _go, _ships, world,
)


def _shields(ship):
    sh = ship.GetShields()
    return [sh.GetCurShields(i) for i in range(6)]


def test_enemy_fed_starbase_phasers_hit_the_player(world):
    hl, _c, panel, QB = world
    import App
    from engine import host_loop
    from engine.core.loop import GameLoop, TICK_DELTA
    from tests.helpers import headless_mission as hm

    _do(panel, "add:FedStarbase")
    _go(hl, panel)
    station = [s for n, s in _ships(QB).items() if n != "Player"][0]
    assert station.GetObjID() in QB.g_kShips
    player = App.Game_GetCurrentGame().GetPlayer()
    before = _shields(player)

    # StarbaseAI holds 7 s before StarbaseAttack runs; give it 20 s.
    loop = GameLoop()
    for _ in range(int(round(20.0 / TICK_DELTA))):
        hm._sim_tick(loop)
        ships = list(host_loop._all_ships_for_tick())
        host_loop._advance_weapons(ships, TICK_DELTA)
        host_loop._advance_combat(ships, TICK_DELTA, ship_instances=None,
                                  push_render_data=False)

    assert sum(_shields(player)) < sum(before)
