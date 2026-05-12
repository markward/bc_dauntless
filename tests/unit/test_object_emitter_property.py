from engine.appc.properties import ObjectEmitterProperty
from engine.appc.math import TGPoint3


def test_oep_constants_distinct_integers():
    assert isinstance(ObjectEmitterProperty.OEP_UNKNOWN, int)
    assert isinstance(ObjectEmitterProperty.OEP_SHUTTLE, int)
    assert isinstance(ObjectEmitterProperty.OEP_PROBE, int)
    assert isinstance(ObjectEmitterProperty.OEP_DECOY, int)
    constants = {
        ObjectEmitterProperty.OEP_UNKNOWN,
        ObjectEmitterProperty.OEP_SHUTTLE,
        ObjectEmitterProperty.OEP_PROBE,
        ObjectEmitterProperty.OEP_DECOY,
    }
    assert len(constants) == 4


def test_default_state():
    p = ObjectEmitterProperty("Shuttle Bay")
    assert p.GetName() == "Shuttle Bay"
    assert p.GetEmittedObjectType() == ObjectEmitterProperty.OEP_UNKNOWN
    assert p.GetPosition() is None
    assert p.GetForward() is None
    assert p.GetUp() is None
    assert p.GetRight() is None


def test_set_emitted_object_type_round_trip():
    p = ObjectEmitterProperty("Probe Launcher")
    p.SetEmittedObjectType(ObjectEmitterProperty.OEP_PROBE)
    assert p.GetEmittedObjectType() == ObjectEmitterProperty.OEP_PROBE


def test_set_position_round_trip_and_copy_semantics():
    p = ObjectEmitterProperty("Shuttle Bay")
    src = TGPoint3(1.0, 2.0, 3.0)
    p.SetPosition(src)
    src.SetXYZ(99.0, 99.0, 99.0)  # mutate source after set
    got = p.GetPosition()
    assert (got.x, got.y, got.z) == (1.0, 2.0, 3.0)
    got.SetXYZ(77.0, 77.0, 77.0)  # mutate returned copy
    got2 = p.GetPosition()
    assert (got2.x, got2.y, got2.z) == (1.0, 2.0, 3.0)


def test_set_orientation_round_trip_and_copy_semantics():
    p = ObjectEmitterProperty("Shuttle Bay")
    fwd = TGPoint3(0.0, 1.0, 0.0)
    up  = TGPoint3(0.0, 0.0, 1.0)
    right = TGPoint3(1.0, 0.0, 0.0)
    p.SetOrientation(fwd, up, right)
    fwd.SetXYZ(9.0, 9.0, 9.0)
    up.SetXYZ(9.0, 9.0, 9.0)
    right.SetXYZ(9.0, 9.0, 9.0)
    assert (p.GetForward().x, p.GetForward().y, p.GetForward().z) == (0.0, 1.0, 0.0)
    assert (p.GetUp().x,      p.GetUp().y,      p.GetUp().z)      == (0.0, 0.0, 1.0)
    assert (p.GetRight().x,   p.GetRight().y,   p.GetRight().z)   == (1.0, 0.0, 0.0)
    # Returned values are fresh copies
    got = p.GetForward()
    got.SetXYZ(5.0, 5.0, 5.0)
    assert (p.GetForward().x, p.GetForward().y, p.GetForward().z) == (0.0, 1.0, 0.0)
