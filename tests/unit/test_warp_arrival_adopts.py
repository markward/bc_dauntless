"""Arrival adopts a set that already exists rather than re-running
Initialize() over it.

With sets persisting (see test_warp_leaves_the_set_standing.py), arriving
somewhere already visited is now the normal case. ChangeRenderedSetAction
must consult App.g_kSetManager.GetSet(name) first and only fall back to
importing the region module and calling Initialize() when no set is
registered yet -- re-running Initialize() over a live set would duplicate
its content and reset whatever a mission had already staged there.
"""
import sys
import types

import App
from engine.appc import warp
from engine.appc.sets import SetClass_Create


def setup_function(_):
    # App.g_kSetManager._sets is global and conftest deliberately does not
    # auto-clear it (see test_warp_leaves_the_set_standing.py's own note).
    App.g_kSetManager._sets.clear()
    App.g_kSetManager.ClearRenderedSet()
    warp.configure_warp_hooks(realize=None, teardown=None)


def teardown_function(_):
    App.g_kSetManager._sets.clear()
    App.g_kSetManager.ClearRenderedSet()
    warp.configure_warp_hooks(realize=None, teardown=None)


def _space_set(name):
    pSet = SetClass_Create()
    App.g_kSetManager.AddSet(pSet, name)
    return pSet


def _ship_in(pSet, name):
    ship = App.ShipClass_Create()
    ship.SetName(name)
    pSet.AddObjectToSet(ship, name)
    return ship


def _objects_in(name):
    pSet = App.g_kSetManager.GetSet(name)
    return pSet.GetObjectList() if pSet is not None else []


def _region_module(name):
    """A fake region module, 'FakeRegion.<name>', whose Initialize() finds-
    or-creates the named set and drops one freshly-created object into it
    every time it runs -- the shape of a real BC region module's
    Initialize(). Calling it twice therefore leaves two objects behind: the
    'duplicate content' failure this guards against. Registered once per
    name; sys.modules caches it exactly like a real import would."""
    mod_name = "FakeRegion.%s" % name
    mod = sys.modules.get(mod_name)
    if mod is None:
        mod = types.ModuleType(mod_name)
        mod.calls = 0

        def Initialize():
            mod.calls += 1
            pSet = App.g_kSetManager.GetSet(name)
            if pSet is None:
                pSet = _space_set(name)
            _ship_in(pSet, "region-object-%d" % mod.calls)

        mod.Initialize = Initialize
        sys.modules[mod_name] = mod
    return mod_name


def _poison_module(name):
    """A fake region module whose Initialize() blows up. Used only where the
    destination set already exists, so ChangeRenderedSetAction must never
    even import/call it -- this proves the guard actually skips the call,
    rather than merely proving its effects happened to be harmless."""
    mod_name = "FakeRegion.Poison.%s" % name
    mod = sys.modules.get(mod_name)
    if mod is None:
        mod = types.ModuleType(mod_name)

        def Initialize():
            raise AssertionError(
                "Initialize() must not run: %r already has a set" % name)

        mod.Initialize = Initialize
        sys.modules[mod_name] = mod
    return mod_name


def _arrive_at(name, module=None):
    """Drive the real arrival path: ChangeRenderedSetAction_Create(module),
    exactly as WarpSequence hands ChangeRenderedSetAction its destination
    module string."""
    if module is None:
        module = _region_module(name)
    warp.ChangeRenderedSetAction_Create(module).Play()


def test_arriving_at_an_existing_set_adopts_it():
    existing = _space_set("Ona1")
    ship = _ship_in(existing, "Sensor Post 1")
    _arrive_at("Ona1", module=_poison_module("Ona1"))
    assert App.g_kSetManager.GetSet("Ona1") is existing
    assert existing.GetObject("Sensor Post 1") is ship


def test_arriving_at_a_missing_set_creates_it():
    assert App.g_kSetManager.GetSet("Ona2") is None
    _arrive_at("Ona2")
    assert App.g_kSetManager.GetSet("Ona2") is not None


def test_arriving_twice_does_not_duplicate_content():
    """Re-running Initialize() over a live set is the failure this guards."""
    _arrive_at("Ona2")
    before = len(_objects_in("Ona2"))
    _arrive_at("Ona2")
    assert len(_objects_in("Ona2")) == before


def test_a_destination_with_no_region_module_is_not_an_error():
    """A set that already exists (a mission's own set, not a region module's)
    must arrive cleanly. The module name is deliberately unimportable --
    proving the guard means it is never even attempted."""
    mission_set = _space_set("FedOutpostSet_Graff")
    _arrive_at("FedOutpostSet_Graff", module="NoSuchRegion.FedOutpostSet_Graff")
    assert App.g_kSetManager.GetSet("FedOutpostSet_Graff") is mission_set
