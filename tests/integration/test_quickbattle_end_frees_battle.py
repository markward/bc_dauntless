"""Headless: a Quick Battle's End frees the battle.

Before release 0.3.2 nothing a battle built was ever freed: the strong id
registry, never-released events, condition handler lists that held their AIs,
proximity checks left in the region set's manager, menu rows and an SDK
module-level dict (ConditionIncomingTorps.g_dInternalInstances) between them
kept every ship, AI tree, condition and event handler alive for the session.
Each later battle ran with all earlier ones still attached, which is what made
the second Quick Battle of a session slower.
"""
import gc
import weakref

import pytest

pytest.importorskip("_dauntless_host")

from tests.integration.test_quickbattle_setup_e2e import (  # noqa: E402
    _do, _go, world,  # noqa: F401  (world is the fixture)
)


def _battle_ships(QB):
    import App
    return [s for s in QB.g_pSet.GetClassObjectList(App.CT_DAMAGEABLE_OBJECT)
            if s.GetName() != "Player"]


def _fight(seconds: float) -> None:
    from engine.core.loop import GameLoop
    loop = GameLoop()
    for _ in range(int(seconds * 60)):
        loop.tick()


def _end(hl, QB) -> None:
    from engine.appc import ai_driver
    QB.EndSimulation()
    hl._process_object_deletions()
    ai_driver.release_root_scratch()
    gc.collect()


def _registered_proximity_checks() -> int:
    import App
    n = 0
    for s in list(App.g_kSetManager._sets.values()):
        pm = s.__dict__.get("_proximity_manager")
        if pm is not None:
            n += len(pm._proximity_checks)
    return n


def test_end_combat_frees_every_ship_the_battle_spawned(world):
    hl, _c, panel, QB = world
    _do(panel, "add:Warbird", "add:BirdOfPrey", "add:Galor")
    _go(hl, panel)
    ships = _battle_ships(QB)
    assert len(ships) >= 3
    refs = [weakref.ref(s) for s in ships]
    del ships
    _fight(5.0)                         # AI builds its conditions and checks
    _end(hl, QB)
    alive = [r().GetName() for r in refs if r() is not None]
    assert alive == []


def test_a_second_battle_starts_from_what_the_first_left(world):
    """The id registry, proximity checks and native rows after the second
    End are no larger than after the first: nothing accumulates per battle."""
    hl, _c, panel, QB = world
    from engine.appc import native_combat
    from engine.core import ids
    _do(panel, "add:Warbird", "add:BirdOfPrey")

    def battle():
        _go(hl, panel)
        _fight(3.0)
        _end(hl, QB)
        return (len(ids._registry), _registered_proximity_checks(),
                len(native_combat._registry))

    first = battle()
    second = battle()
    # Allow a little slack for bridge-crew reaction objects that are
    # still in flight when a battle ends.
    assert second[0] <= first[0] + 50, (first, second)
    assert second[1] <= first[1], (first, second)
    assert second[2] <= first[2] + 10, (first, second)
