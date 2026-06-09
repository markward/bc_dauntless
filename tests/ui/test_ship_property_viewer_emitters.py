from engine.appc.ships import ShipClass_Create
from engine.appc.properties import ObjectEmitterProperty
from engine.appc.math import TGPoint3
from engine.ui.ship_property_viewer import build_descriptors


def _emitter_prop(name, x, y, z):
    p = ObjectEmitterProperty(name)
    pos = TGPoint3(); pos.SetXYZ(x, y, z)
    p.SetPosition(pos)
    p.SetEmittedObjectType(ObjectEmitterProperty.OEP_SHUTTLE)
    return p


def test_emitter_appears_as_mount_descriptor():
    ship = ShipClass_Create("X")
    ship.GetPropertySet().AddToSet("Scene Root", _emitter_prop("Shuttle Bay", 0.0, 0.05, 0.57))
    ship.SetupProperties()

    descs = build_descriptors(ship)
    mounts = [d for d in descs if d.get("kind") == "mount"]
    assert len(mounts) == 1
    assert mounts[0]["name"] == "Shuttle Bay"
    assert mounts[0]["state"] == "mount"
    assert mounts[0]["world_pos"] == (0.0, 0.05, 0.57)
    assert mounts[0]["properties"]["emitted_type"] == ObjectEmitterProperty.OEP_SHUTTLE
