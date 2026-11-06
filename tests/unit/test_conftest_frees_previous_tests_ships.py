"""The per-test reset frees the previous test's ships (2026-11-06).

Before, the conftest's hand-kept reset list had drifted 15 entries behind the
game's mission-swap teardown, and two of the missing registries held a STRONG
reference to every ship: engine.appc.ship_lifecycle._live (filled by
SetClass.AddObjectToSet) and engine.appc.registry_texture._pending (filled by
ReplaceTexture). So every ship any test built, with its whole subsystem/AI
graph, lived to the end of the run: the full suite peaked at 4.3 GB
(docs/reference/architecture/test-suite-memory.md). The conftest now calls
engine.host_loop.reset_mission_state, the SAME list the swap uses.

ORDERED pair: the first test builds a ship and leaves it in a set; the
second (run after it, in file order) must find it collected.
"""
import gc
import weakref

import App

_left = {}


def test_a_builds_a_ship_and_leaves_it_published():
    from engine.appc import registry_texture, ship_lifecycle
    pSet = App.SetClass_Create()
    App.g_kSetManager.AddSet(pSet, "LeakProbeSet")
    ship = App.ShipClass_Create()
    ship.SetName("LeakProbe")
    pSet.AddObjectToSet(ship, "LeakProbe")
    ship.ReplaceTexture("data/Models/Ships/Galaxy/Zhukov.tga", "ID")
    assert ship in ship_lifecycle.snapshot()
    assert id(ship) in registry_texture._pending
    _left["ship"] = weakref.ref(ship)
    # The set itself is a test's own business (the conftest deliberately
    # keeps g_kSetManager's sets); drop it so only the registries could hold
    # the ship.
    App.g_kSetManager.DeleteSet("LeakProbeSet")


def test_b_the_previous_tests_ship_was_freed():
    from engine.appc import registry_texture, ship_lifecycle
    assert ship_lifecycle.snapshot() == ()
    assert registry_texture._pending == {}
    gc.collect()
    assert _left["ship"]() is None, gc.get_referrers(_left["ship"]())
