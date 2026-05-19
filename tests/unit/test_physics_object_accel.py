"""Unit tests for PhysicsObjectClass.GetAccelerationTG and PhysicsObjectClass_Cast.

These two pieces unblock the real SDK Intercept.Update, which calls
GetPredictedPosition(loc, GetVelocityTG(), GetAccelerationTG(), t) and
guards the call with App.PhysicsObjectClass_Cast(target)."""
import App
from engine.appc.math import TGPoint3
from engine.appc.objects import ObjectClass, PhysicsObjectClass
from engine.appc.placement import PlacementObject
from engine.appc.ships import ShipClass


def test_get_acceleration_tg_returns_zero_vector():
    """Phase 1 kinematic model: acceleration is the integrator's per-tick
    ramp, not stored on the object. Zero is the right default — degrades
    GetPredictedPosition(p, v, a, t) gracefully to p + v*t."""
    obj = PhysicsObjectClass()
    a = obj.GetAccelerationTG()
    assert isinstance(a, TGPoint3)
    assert (a.x, a.y, a.z) == (0.0, 0.0, 0.0)


def test_get_acceleration_tg_returns_fresh_vec_each_call():
    """Caller may mutate the returned vec; subsequent calls must not see
    the mutation. Mirrors GetVelocityTG's defensive-copy contract."""
    obj = PhysicsObjectClass()
    a1 = obj.GetAccelerationTG()
    a1.SetXYZ(99.0, 99.0, 99.0)
    a2 = obj.GetAccelerationTG()
    assert (a2.x, a2.y, a2.z) == (0.0, 0.0, 0.0)


def test_physics_object_class_cast_returns_input_for_ship():
    """ShipClass extends DamageableObject extends PhysicsObjectClass, so a
    ShipClass IS a PhysicsObjectClass. Cast returns the ship."""
    ship = ShipClass()
    assert App.PhysicsObjectClass_Cast(ship) is ship


def test_physics_object_class_cast_returns_none_for_non_physics():
    """A bare ObjectClass (e.g. PlacementObject) is NOT a PhysicsObjectClass.
    Cast returns None so SDK guards (`if pPhysicsObject is None:`) work."""
    placement = PlacementObject()
    assert App.PhysicsObjectClass_Cast(placement) is None


def test_physics_object_class_cast_returns_none_for_none():
    """None input → None output, no AttributeError."""
    assert App.PhysicsObjectClass_Cast(None) is None
