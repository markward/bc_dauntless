"""ship_iter: walk every ship in every active set."""
import App
from engine.appc.sets import SetClass
from engine.appc.ship_iter import iter_ships, iter_set_objects
from engine.appc.ships import ShipClass_Create


def test_iter_ships_empty_when_no_sets():
    """Fresh App.g_kSetManager has no sets — iter yields nothing."""
    App.g_kSetManager._sets.clear()
    assert list(iter_ships()) == []


def test_iter_ships_yields_ships_with_scripts():
    App.g_kSetManager._sets.clear()
    pSet = SetClass()
    App.g_kSetManager.AddSet(pSet, "test_set")
    ship = ShipClass_Create("Galaxy")
    ship.SetScript("test_script")
    pSet.AddObjectToSet(ship, "ship_1")
    found = list(iter_ships())
    assert ship in found


def test_iter_set_objects_yields_via_values():
    """Confirms we still walk _objects.values() rather than GetFirstObject
    — see the comment block in the helper for why."""
    App.g_kSetManager._sets.clear()
    pSet = SetClass()
    App.g_kSetManager.AddSet(pSet, "test_set")
    ship = ShipClass_Create("Galaxy")
    pSet.AddObjectToSet(ship, "ship_1")
    found = list(iter_set_objects(pSet))
    assert ship in found


def test_iter_ships_survives_set_mutation_mid_iteration():
    """A ship's AI tick can add objects to (or delete from) sets mid-tick — the
    E6M2 dock AI adds waypoints / the Graff control-room set / PlaceObjectByName
    targets while tick_all_ai is walking iter_ships(). Iterating the live
    _objects / _sets views then raised 'dictionary changed size during
    iteration'. iter_ships must snapshot so mid-iteration mutation can't crash."""
    App.g_kSetManager._sets.clear()
    pSet = SetClass()
    App.g_kSetManager.AddSet(pSet, "test_set")
    ship = ShipClass_Create("Galaxy")
    pSet.AddObjectToSet(ship, "ship_1")

    # Walk iter_ships and, on the first ship, mutate BOTH the set's _objects
    # and the set manager's _sets (the two dicts iter_ships walks). Pre-fix this
    # raised RuntimeError: dictionary changed size during iteration.
    seen = []
    for s in iter_ships():
        seen.append(s)
        if len(seen) == 1:
            other = ShipClass_Create("Galaxy")
            pSet.AddObjectToSet(other, "ship_added_mid_tick")   # mutate _objects
            newSet = SetClass()
            App.g_kSetManager.AddSet(newSet, "set_added_mid_tick")  # mutate _sets
    assert ship in seen
