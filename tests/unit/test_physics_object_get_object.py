"""App.PhysicsObjectClass_GetObject(pSet, name): returns the physics object under
`name`, else None. Backs the SDK FollowWaypoints destination lookup
(sdk/.../FollowWaypoints.py:132) — without it the truthy _NamedStub made the
PlacementObject_GetObject fallback unreachable and collapsed every waypoint AI's
destination."""
from engine.appc.objects import (
    PhysicsObjectClass, ObjectClass, PhysicsObjectClass_GetObject,
)
from engine.appc.ships import ShipClass
from engine.appc.sets import SetClass_Create


def test_returns_physics_object_by_name():
    pSet = SetClass_Create(); pSet.SetName("S")
    ship = ShipClass()                      # ShipClass is a PhysicsObjectClass
    pSet.AddObjectToSet(ship, "WP1")
    assert PhysicsObjectClass_GetObject(pSet, "WP1") is ship


def test_returns_none_for_non_physics_object():
    pSet = SetClass_Create(); pSet.SetName("S")
    obj = ObjectClass()                     # plain ObjectClass, NOT a physics obj
    pSet.AddObjectToSet(obj, "Marker")
    assert PhysicsObjectClass_GetObject(pSet, "Marker") is None


def test_returns_none_when_absent():
    pSet = SetClass_Create(); pSet.SetName("S")
    assert PhysicsObjectClass_GetObject(pSet, "Nope") is None


def test_returns_none_for_none_set():
    assert PhysicsObjectClass_GetObject(None, "WP1") is None
