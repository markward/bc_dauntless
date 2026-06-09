from engine.appc.ships import ShipClass_Create
from engine.appc.properties import ObjectEmitterProperty
from engine.appc.math import TGPoint3
from engine.appc.object_emitter import ObjectEmitter


def _emitter(name, oep_type, x, y, z):
    p = ObjectEmitterProperty(name)
    pos = TGPoint3(); pos.SetXYZ(x, y, z)
    p.SetPosition(pos)
    p.SetEmittedObjectType(oep_type)
    return p


def test_emitters_populated_from_property_set():
    ship = ShipClass_Create("X")
    ps = ship.GetPropertySet()
    ps.AddToSet("Scene Root",
                _emitter("Shuttle Bay", ObjectEmitterProperty.OEP_SHUTTLE, 0.0, 0.05, 0.57))
    ps.AddToSet("Scene Root",
                _emitter("Probe Launcher", ObjectEmitterProperty.OEP_PROBE, 0.0, 3.29, 0.27))
    ship.SetupProperties()

    emitters = ship.GetObjectEmitters()
    assert len(emitters) == 2
    names = sorted(e.GetName() for e in emitters)
    assert names == ["Probe Launcher", "Shuttle Bay"]
    assert all(isinstance(e, ObjectEmitter) for e in emitters)
    shuttle = next(e for e in emitters if e.GetName() == "Shuttle Bay")
    assert shuttle.GetEmittedObjectType() == ObjectEmitterProperty.OEP_SHUTTLE
    assert abs(shuttle.GetPosition().y - 0.05) < 1e-6


def test_emitters_idempotent_on_rerun():
    ship = ShipClass_Create("X")
    ship.GetPropertySet().AddToSet(
        "Scene Root",
        _emitter("Shuttle Bay", ObjectEmitterProperty.OEP_SHUTTLE, 0.0, 0.05, 0.57))
    ship.SetupProperties()
    ship.SetupProperties()
    assert len(ship.GetObjectEmitters()) == 1
