"""`PlaceObjectByName` must resolve a marker in the object's OWN set.

Reported live: warping into E3M2's Vesuvi4 dropped the player inside the dust
cloud, taking immediate hull damage, instead of at that system's "Player
Start".

Root cause: `placement._waypoint_registry` is a flat dict keyed by the bare
marker name, so `Waypoint_Create(name, set_name, ...)` adds the waypoint to its
set and then registers it globally where the NEXT set's marker of the same name
overwrites it. Resolution was therefore "whichever set loaded last wins", not
"my set's marker".

The scale is not one name. Across the SDK: "Player Start" is defined in 104
files, "Sun" in 85, "Planet Location" in 57, and each of the 16 bridges defines
its own "View" / "Player Cam" / "Kiska Head" / "Saffi Head" camera markers. Any
of those could resolve to another set's copy.

E3M2 makes it concrete: it loads placements for Starbase 12, Vesuvi4 and
Vesuvi6, then loads the Vesuvi4 placements AGAIN into a DeepSpace temp set --
four `LoadPlacements` calls before the player ever warps, plus each system's own
file. The registry is only cleared on mission swap, never per set.

Geometry of the live symptom: Vesuvi4's real "Player Start" is
(-1.70, -335.76, 0.17); the nebula is centred (0, 1500, 0) with radius 1500 GU.
The correct arrival point is ~336 GU OUTSIDE the cloud, so arriving inside it
proves the marker resolved to a different set's.

The global registry is kept as a FALLBACK, not removed: a waypoint whose set
did not exist at `Waypoint_Create` time was never added to any set, and BC
scripts do place objects against markers loaded into a set they are not
currently in.
"""
import App
import pytest

from engine.appc.objects import ObjectClass
from engine.appc.placement import Waypoint_Create, _waypoint_registry
from engine.appc.sets import SetClass


@pytest.fixture
def two_sets():
    """Two sets, each with its OWN 'Player Start' at different coordinates --
    the E3M2 shape. `second` is created last, so it owns the global registry
    entry and is what the old code always returned."""
    first, second = SetClass(), SetClass()
    first.SetName("FirstSystem")
    second.SetName("SecondSystem")
    App.g_kSetManager._sets["FirstSystem"] = first
    App.g_kSetManager._sets["SecondSystem"] = second

    a = Waypoint_Create("Player Start", "FirstSystem", None)
    a.SetTranslateXYZ(-1.70, -335.76, 0.17)      # Vesuvi4's real marker
    b = Waypoint_Create("Player Start", "SecondSystem", None)
    b.SetTranslateXYZ(0.0, 1500.0, 0.0)          # inside the dust cloud

    yield first, second
    for n in ("FirstSystem", "SecondSystem"):
        App.g_kSetManager._sets.pop(n, None)
    _waypoint_registry.pop("Player Start", None)


def _xyz(obj):
    p = obj.GetWorldLocation()
    return (round(p.x, 3), round(p.y, 3), round(p.z, 3))


def test_an_object_lands_on_its_own_sets_marker(two_sets):
    """The reported bug. The object is in the FIRST set, but the SECOND set
    registered 'Player Start' later, so the old code sent it there."""
    first, _second = two_sets
    ship = ObjectClass()
    first.AddObjectToSet(ship, "Player")

    ship.PlaceObjectByName("Player Start")

    assert _xyz(ship) == (-1.7, -335.76, 0.17), (
        "resolved another set's marker -- this is the live warp overshoot")


def test_the_other_set_still_gets_its_own(two_sets):
    """Symmetry: the fix must not simply prefer the FIRST set instead."""
    _first, second = two_sets
    ship = ObjectClass()
    second.AddObjectToSet(ship, "Player")

    ship.PlaceObjectByName("Player Start")

    assert _xyz(ship) == (0.0, 1500.0, 0.0)


def test_load_order_no_longer_decides(two_sets):
    """Re-registering the second set's marker (what a fourth LoadPlacements
    does) must not move an object that lives in the first set."""
    first, _second = two_sets
    late = Waypoint_Create("Player Start", "SecondSystem", None)
    late.SetTranslateXYZ(999.0, 999.0, 999.0)

    ship = ObjectClass()
    first.AddObjectToSet(ship, "Player")
    ship.PlaceObjectByName("Player Start")

    assert _xyz(ship) == (-1.7, -335.76, 0.17)


def test_rotation_comes_from_the_same_marker(two_sets):
    """Position and orientation must not come from different waypoints --
    arriving at the right point facing the wrong way is its own bug."""
    first, _second = two_sets
    marker = first.GetObject("Player Start")
    ship = ObjectClass()
    first.AddObjectToSet(ship, "Player")

    ship.PlaceObjectByName("Player Start")

    expected = marker.GetWorldRotation()
    actual = ship.GetWorldRotation()
    for col in range(3):
        e, a = expected.GetCol(col), actual.GetCol(col)
        assert (round(e.x, 5), round(e.y, 5), round(e.z, 5)) == \
               (round(a.x, 5), round(a.y, 5), round(a.z, 5))


# ── the fallback, which must survive ────────────────────────────────────────

def test_an_object_in_no_set_still_resolves_globally(two_sets):
    """Kept deliberately. A waypoint whose set did not exist at
    Waypoint_Create time was never added to any set, so the global registry is
    the only way to reach it."""
    ship = ObjectClass()

    ship.PlaceObjectByName("Player Start")

    assert _xyz(ship) == (0.0, 1500.0, 0.0), "falls back to the global entry"


def test_a_set_without_the_marker_falls_back(two_sets):
    """An object in a set that has no such marker must still resolve, not
    silently stay where it was."""
    third = SetClass()
    third.SetName("ThirdSystem")
    App.g_kSetManager._sets["ThirdSystem"] = third
    try:
        ship = ObjectClass()
        third.AddObjectToSet(ship, "Player")

        ship.PlaceObjectByName("Player Start")

        assert _xyz(ship) == (0.0, 1500.0, 0.0)
    finally:
        App.g_kSetManager._sets.pop("ThirdSystem", None)


def test_an_unknown_marker_leaves_the_object_where_it_was(two_sets):
    """Unchanged behaviour: a missing name is a silent no-op, not a move to the
    origin. BC scripts place against markers that may not be loaded."""
    first, _second = two_sets
    ship = ObjectClass()
    first.AddObjectToSet(ship, "Player")
    ship.SetTranslateXYZ(7.0, 8.0, 9.0)

    ship.PlaceObjectByName("No Such Marker")

    assert _xyz(ship) == (7.0, 8.0, 9.0)


def test_a_non_waypoint_of_the_same_name_is_not_used(two_sets):
    """Sets are keyed by name too, and a SHIP could share a marker's name.
    Placing onto a ship's position would be a different bug wearing the same
    clothes, so the set lookup must type-check."""
    from engine.appc.ships import ShipClass

    third = SetClass()
    third.SetName("ThirdSystem")
    App.g_kSetManager._sets["ThirdSystem"] = third
    try:
        impostor = ShipClass()
        impostor.SetTranslateXYZ(42.0, 42.0, 42.0)
        third.AddObjectToSet(impostor, "Player Start")

        ship = ObjectClass()
        third.AddObjectToSet(ship, "Player")
        ship.PlaceObjectByName("Player Start")

        assert _xyz(ship) != (42.0, 42.0, 42.0), (
            "placed onto a SHIP that happened to share the marker's name")
        assert _xyz(ship) == (0.0, 1500.0, 0.0), "should fall back to the marker"
    finally:
        App.g_kSetManager._sets.pop("ThirdSystem", None)
