"""Unit tests for ObjectClass transform methods and PhysicsObjectClass."""
import math
import pytest
import App
from engine.appc.math import TGPoint3, TGMatrix3
from engine.appc.objects import ObjectClass, PhysicsObjectClass, DamageableObject


# ── ObjectClass transform ─────────────────────────────────────────────────────

def test_object_set_translate_xyz_roundtrip():
    obj = ObjectClass()
    obj.SetTranslateXYZ(1.0, 2.0, 3.0)
    loc = obj.GetWorldLocation()
    assert isinstance(loc, TGPoint3)
    assert loc.x == 1.0 and loc.y == 2.0 and loc.z == 3.0


def test_object_set_translate_point_roundtrip():
    obj = ObjectClass()
    obj.SetTranslate(TGPoint3(4.0, 5.0, 6.0))
    loc = obj.GetTranslate()
    assert loc.x == 4.0 and loc.y == 5.0 and loc.z == 6.0


def test_object_get_translate_returns_copy():
    obj = ObjectClass()
    obj.SetTranslateXYZ(1.0, 2.0, 3.0)
    a = obj.GetTranslate()
    b = obj.GetTranslate()
    a.x = 99.0
    assert obj.GetTranslate().x == 1.0  # mutation of returned copy does not affect stored state


def test_object_get_world_location_returns_copy():
    obj = ObjectClass()
    obj.SetTranslateXYZ(1.0, 2.0, 3.0)
    loc = obj.GetWorldLocation()
    loc.x = 99.0
    assert obj.GetWorldLocation().x == 1.0


def test_object_default_position_is_origin():
    obj = ObjectClass()
    loc = obj.GetWorldLocation()
    assert loc.x == 0.0 and loc.y == 0.0 and loc.z == 0.0


def test_object_set_matrix_rotation_roundtrip():
    obj = ObjectClass()
    m = TGMatrix3()
    m.MakeZRotation(0.5)
    obj.SetMatrixRotation(m)
    r = obj.GetWorldRotation()
    assert isinstance(r, TGMatrix3)
    assert abs(r.GetEntry(0, 0) - math.cos(0.5)) < 1e-10


def test_object_get_rotation_returns_copy():
    obj = ObjectClass()
    m = TGMatrix3()
    m.MakeZRotation(1.0)
    obj.SetMatrixRotation(m)
    r = obj.GetRotation()
    r.SetEntry(0, 0, 99.0)
    assert obj.GetRotation().GetEntry(0, 0) != 99.0


def test_object_set_angle_axis_rotation():
    obj = ObjectClass()
    axis = TGPoint3(0.0, 0.0, 1.0)
    obj.SetAngleAxisRotation(math.pi / 2, axis)
    r = obj.GetWorldRotation()
    x = r.MultPoint(TGPoint3(1.0, 0.0, 0.0))
    assert abs(x.y - 1.0) < 1e-10


def test_object_align_to_vectors_produces_orthonormal_matrix():
    obj = ObjectClass()
    fwd = TGPoint3(1.0, 0.0, 0.0)
    up = TGPoint3(0.0, 0.0, 1.0)
    obj.AlignToVectors(fwd, up)
    r = obj.GetWorldRotation()
    # Rows should be unit length
    for i in range(3):
        row = r.GetRow(i)
        assert abs(row.Length() - 1.0) < 1e-6
    # Rows should be mutually orthogonal
    r0, r1, r2 = r.GetRow(0), r.GetRow(1), r.GetRow(2)
    assert abs(r0.Dot(r1)) < 1e-6
    assert abs(r0.Dot(r2)) < 1e-6
    assert abs(r1.Dot(r2)) < 1e-6


def test_object_align_to_vectors_with_tutorial_placement():
    """Test with actual values from M2Biranu1_P.py LoadPlacements."""
    obj = ObjectClass()
    fwd = TGPoint3(0.802961, -0.595512, -0.024877)
    up = TGPoint3(0.060600, 0.040047, 0.997359)
    obj.AlignToVectors(fwd, up)
    r = obj.GetWorldRotation()
    # All rows must be unit length
    for i in range(3):
        assert abs(r.GetRow(i).Length() - 1.0) < 1e-5


def test_object_scale_roundtrip():
    obj = ObjectClass()
    obj.SetScale(2.5)
    assert obj.GetScale() == 2.5


def test_object_hidden_flag():
    obj = ObjectClass()
    assert not obj.IsHidden()
    obj.SetHidden(True)
    assert obj.IsHidden()


def test_object_radius_roundtrip():
    obj = ObjectClass()
    obj.SetRadius(500.0)
    assert obj.GetRadius() == 500.0


def test_object_containing_set_initially_none():
    obj = ObjectClass()
    assert obj.GetContainingSet() is None


# ── PhysicsObjectClass ────────────────────────────────────────────────────────

def test_physics_direction_constants():
    assert PhysicsObjectClass.DIRECTION_MODEL_SPACE == 0
    assert PhysicsObjectClass.DIRECTION_WORLD_SPACE == 1


def test_physics_set_velocity_roundtrip():
    obj = PhysicsObjectClass()
    v = TGPoint3(1.0, 2.0, 3.0)
    obj.SetVelocity(v)
    w = obj.GetVelocityTG()
    assert isinstance(w, TGPoint3)
    assert w.x == 1.0 and w.y == 2.0 and w.z == 3.0


def test_physics_get_velocity_returns_copy():
    obj = PhysicsObjectClass()
    obj.SetVelocity(TGPoint3(1.0, 0.0, 0.0))
    v = obj.GetVelocityTG()
    v.x = 99.0
    assert obj.GetVelocityTG().x == 1.0


def test_physics_set_angular_velocity_roundtrip():
    obj = PhysicsObjectClass()
    v = TGPoint3(0.0, 0.0, 1.0)
    obj.SetAngularVelocity(v, PhysicsObjectClass.DIRECTION_WORLD_SPACE)
    w = obj.GetAngularVelocityTG()
    assert w.z == 1.0


def test_physics_mass_roundtrip():
    obj = PhysicsObjectClass()
    obj.SetMass(1000.0)
    assert obj.GetMass() == 1000.0


def test_physics_rotational_inertia_roundtrip():
    obj = PhysicsObjectClass()
    obj.SetRotationalInertia(500.0)
    assert obj.GetRotationalInertia() == 500.0


def test_physics_static_flag():
    obj = PhysicsObjectClass()
    assert not obj.IsStatic()
    obj.SetStatic(True)
    assert obj.IsStatic()


def test_physics_use_physics_flag():
    obj = PhysicsObjectClass()
    assert not obj.IsUsingPhysics()
    obj.SetUsePhysics(True)
    assert obj.IsUsingPhysics()


def test_physics_apply_force_does_not_raise():
    obj = PhysicsObjectClass()
    obj.ApplyForce(TGPoint3(0.0, 1.0, 0.0))


def test_physics_is_subclass_of_object():
    obj = PhysicsObjectClass()
    assert isinstance(obj, ObjectClass)


def test_damageable_object_is_physics_object():
    obj = DamageableObject()
    assert isinstance(obj, PhysicsObjectClass)


# ── App-level direction constants ─────────────────────────────────────────────

def test_app_physicsobj_direction_constants():
    assert App.PhysicsObjectClass.DIRECTION_MODEL_SPACE == 0
    assert App.PhysicsObjectClass.DIRECTION_WORLD_SPACE == 1
