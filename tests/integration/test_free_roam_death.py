"""A player death in free roam is final: the ship stays destroyed (spec
2026-10-26-station-self-defence §5.5). In a battle, Quick Battle's own handling
(the battle ends) is unchanged.
"""
import pytest

pytest.importorskip("_dauntless_host")

from tests.helpers import headless_mission as hm  # noqa: E402
from tests.integration.test_quickbattle_setup_e2e import (  # noqa: E402,F401
    _do, _go, _ships, world)


def _player():
    import App
    return App.Game_GetCurrentGame().GetPlayer()


def _run(seconds):
    """The sim tick plus the host's per-frame weapon and combat steps: the
    death cascade only advances in the latter."""
    from engine import host_loop
    from engine.core.loop import GameLoop, TICK_DELTA
    loop = GameLoop()
    for _ in range(int(round(seconds / TICK_DELTA))):
        hm._sim_tick(loop)
        ships = list(host_loop._all_ships_for_tick())
        host_loop._advance_weapons(ships, TICK_DELTA)
        host_loop._advance_combat(ships, TICK_DELTA, ship_instances=None,
                                  push_render_data=False)


def _kill(ship, killer=None):
    """Real hull damage through combat.apply_hit until the hull is gone."""
    from engine.appc import combat
    for _ in range(50):
        if ship.GetHull().GetCondition() <= 0:
            return
        combat.apply_hit(ship, 1.0e6, ship.GetWorldLocation(), killer,
                         weapon_type="phaser")
    assert ship.GetHull().GetCondition() <= 0


def _count_recreates(monkeypatch, QB):
    calls = []
    orig = QB.RecreatePlayer
    monkeypatch.setattr(QB, "RecreatePlayer",
                        lambda *a: calls.append(1) or orig(*a))
    return calls


def test_dying_in_free_roam_leaves_no_ship(world, monkeypatch):
    import App
    from engine.appc import ship_death
    _hl, _c, _panel, QB = world
    calls = _count_recreates(monkeypatch, QB)
    assert not QB.bInSimulation
    dead = _player()
    name = dead.GetName()
    _kill(dead)
    _run(30.0)
    assert calls == []
    for pSet in list(App.g_kSetManager._sets.values()):
        for obj in pSet.GetClassObjectList(App.CT_SHIP):
            assert not (obj.GetName() == name and obj is not dead), pSet.GetName()
    assert ship_death._out_of_action(dead)


def test_dying_in_a_battle_still_ends_it(world):
    hl, _c, panel, QB = world
    _do(panel, "add:Warbird")
    _go(hl, panel)
    assert QB.bInSimulation
    _kill(_player())
    _run(30.0)
    assert not QB.bInSimulation


def test_an_npc_death_runs_bc_as_before(world):
    hl, _c, panel, QB = world
    _do(panel, "add:Warbird")
    _go(hl, panel)
    npcs = [s for s in _ships(QB).values()
            if s is not _player() and s.GetObjID() in QB.g_kShips]
    assert npcs
    npc = npcs[0]
    ident = npc.GetObjID()
    _kill(npc, _player())
    _run(30.0)
    assert ident not in QB.g_kShips


def test_install_twice_wraps_once(world):
    from engine.quickbattle import free_roam_death
    _hl, _c, _panel, QB = world
    first = QB.ShipDestroyed
    assert free_roam_death.install(QB) is False
    assert QB.ShipDestroyed is first
    assert sum(1 for f in free_roam_death._chain(first)
               if free_roam_death._MARK in f.__dict__) == 1


def test_a_battle_can_start_after_a_free_roam_death(world):
    """Regression: the dead player stays in free roam, and starting a battle
    afterwards must still run and leave a new, live player."""
    hl, _c, panel, QB = world
    dead = _player()
    _kill(dead)
    _run(30.0)
    _do(panel, "add:Warbird")
    _go(hl, panel)
    assert QB.bInSimulation
    new = _player()
    assert new is not None and new is not dead
    assert not new.IsDead() and not new.IsDying()
    assert new.GetHull().GetCondition() > 0
