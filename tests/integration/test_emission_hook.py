"""Integration tests for the LaunchObject emission hook.

Builds a synthetic ship-like object whose PropertySet exposes a single
ObjectEmitterProperty per launch type. Verifies the hook resolves the
correct emitter, computes the world-frame transform, and records the
event in App._emission_recorder.
"""
import pytest

import App
import tools.mission_harness as mh
from engine.appc.math import TGPoint3, TGMatrix3
from engine.appc.properties import (
    ObjectEmitterProperty,
    TGModelPropertyManager,
    TGModelPropertySet,
)


@pytest.fixture(autouse=True)
def reset_recorder():
    from engine.core.ids import _registry as _ID_REGISTRY

    App._emission_recorder.disable()
    App._emission_recorder.clear()
    snapshot = set(_ID_REGISTRY.keys())

    yield

    # Clean up any synthetic-ship IDs inserted during the test.
    for k in list(_ID_REGISTRY):
        if k not in snapshot:
            del _ID_REGISTRY[k]

    App._emission_recorder.disable()
    App._emission_recorder.clear()


def _make_emitter(name, local_pos, fwd, up, right, kind):
    e = App.ObjectEmitterProperty_Create(name)
    e.SetPosition(local_pos)
    e.SetOrientation(fwd, up, right)
    e.SetEmittedObjectType(kind)
    return e


def _make_synthetic_ship(emitters, world_loc, world_rot, obj_id, monkeypatch):
    """Return a stand-in for a ShipClass: implements the calls
    Actions.ShipScriptActions.LaunchObject needs, no more. Registers itself
    in engine.core.ids._registry so App.TGObject_GetTGObjectPtr resolves it,
    and monkeypatches App.ShipClass_Cast to accept the synthetic ship."""

    class _Set:
        def GetPropertiesByType(self, type_cls):
            # The engine wraps templates in TGModelPropertyInstance via the
            # standard TGModelPropertySet machinery. Reuse it.
            tps = TGModelPropertySet()
            for e in emitters:
                tps.AddToSet("Scene Root", e)
            return tps.GetPropertiesByType(type_cls)

    class _Ship:
        def GetPropertySet(self): return _Set()
        def GetWorldRotation(self): return world_rot
        def GetWorldLocation(self): return TGPoint3(world_loc.x, world_loc.y, world_loc.z)
        def GetObjID(self): return obj_id

    ship = _Ship()
    # App.TGObject_GetTGObjectPtr looks up engine.core.ids._registry
    from engine.core.ids import _registry as _ID_REGISTRY
    _ID_REGISTRY[obj_id] = ship
    # App.ShipClass_Cast checks isinstance(obj, ShipClass); for a synthetic
    # ship we shortcut it to a pass-through for the duration of the test.
    monkeypatch.setattr(App, "ShipClass_Cast", lambda obj: obj)
    return ship


def test_hook_resolves_shuttle_emitter_and_records(monkeypatch):
    mh.setup_sdk()
    from engine.appc.emission import install_launch_object_hook
    install_launch_object_hook()
    App._emission_recorder.enable()

    shuttle = _make_emitter(
        "Shuttle Bay",
        local_pos=TGPoint3(0.0, -2.0, -0.17),
        fwd=TGPoint3(0.0, -1.0, 0.0),
        up=TGPoint3(0.0, 0.0, 1.0),
        right=TGPoint3(-1.0, 0.0, 0.0),
        kind=ObjectEmitterProperty.OEP_SHUTTLE,
    )

    # Identity rotation; world location at origin
    R = TGMatrix3()
    ship = _make_synthetic_ship([shuttle], TGPoint3(0, 0, 0), R, obj_id=4242, monkeypatch=monkeypatch)

    import Actions.ShipScriptActions as ssa
    rc = ssa.LaunchObject(None, 4242, "test-shuttle", ObjectEmitterProperty.OEP_SHUTTLE)
    assert rc == 0

    events = App._emission_recorder.events()
    assert len(events) == 1
    e = events[0]
    assert e["ship_id"] == 4242
    assert e["emitter_name"] == "Shuttle Bay"
    assert e["emitter_type"] == ObjectEmitterProperty.OEP_SHUTTLE
    # Identity rotation, origin world location → world position == local position
    assert abs(e["world_position"][0] - 0.0)   < 1e-9
    assert abs(e["world_position"][1] - (-2.0)) < 1e-9
    assert abs(e["world_position"][2] - (-0.17)) < 1e-9


def test_hook_picks_correct_emitter_by_type(monkeypatch):
    mh.setup_sdk()
    from engine.appc.emission import install_launch_object_hook
    install_launch_object_hook()
    App._emission_recorder.enable()

    shuttle = _make_emitter("Shuttle Bay", TGPoint3(0,-2,0), TGPoint3(0,-1,0),
                            TGPoint3(0,0,1), TGPoint3(-1,0,0), ObjectEmitterProperty.OEP_SHUTTLE)
    probe = _make_emitter("Probe Launcher", TGPoint3(0,3.35,0), TGPoint3(0,1,0),
                          TGPoint3(0,0,1), TGPoint3(1,0,0), ObjectEmitterProperty.OEP_PROBE)
    decoy = _make_emitter("Decoy launcher", TGPoint3(0,0,1), TGPoint3(0,1,0),
                          TGPoint3(0,0,1), TGPoint3(1,0,0), ObjectEmitterProperty.OEP_DECOY)

    R = TGMatrix3()
    ship = _make_synthetic_ship([shuttle, probe, decoy], TGPoint3(0,0,0), R, obj_id=4243, monkeypatch=monkeypatch)

    import Actions.ShipScriptActions as ssa
    ssa.LaunchObject(None, 4243, "p", ObjectEmitterProperty.OEP_PROBE)
    ssa.LaunchObject(None, 4243, "d", ObjectEmitterProperty.OEP_DECOY)
    ssa.LaunchObject(None, 4243, "s", ObjectEmitterProperty.OEP_SHUTTLE)

    events = App._emission_recorder.events()
    assert [e["emitter_name"] for e in events] == ["Probe Launcher", "Decoy launcher", "Shuttle Bay"]
    assert [e["emitter_type"] for e in events] == [
        ObjectEmitterProperty.OEP_PROBE,
        ObjectEmitterProperty.OEP_DECOY,
        ObjectEmitterProperty.OEP_SHUTTLE,
    ]


def test_hook_no_match_records_nothing(monkeypatch):
    mh.setup_sdk()
    from engine.appc.emission import install_launch_object_hook
    install_launch_object_hook()
    App._emission_recorder.enable()

    shuttle = _make_emitter("Shuttle Bay", TGPoint3(0,-2,0), TGPoint3(0,-1,0),
                            TGPoint3(0,0,1), TGPoint3(-1,0,0), ObjectEmitterProperty.OEP_SHUTTLE)
    R = TGMatrix3()
    _make_synthetic_ship([shuttle], TGPoint3(0,0,0), R, obj_id=4244, monkeypatch=monkeypatch)

    import Actions.ShipScriptActions as ssa
    rc = ssa.LaunchObject(None, 4244, "phantom-probe", ObjectEmitterProperty.OEP_PROBE)
    assert rc == 0
    assert App._emission_recorder.events() == []


def test_hook_applies_world_rotation_and_translation(monkeypatch):
    mh.setup_sdk()
    from engine.appc.emission import install_launch_object_hook
    install_launch_object_hook()
    App._emission_recorder.enable()

    # Local-frame emitter at +Y=3.35 (probe launcher offset on sovereign)
    probe = _make_emitter("Probe Launcher",
                          TGPoint3(0.0, 3.35, 0.0),
                          TGPoint3(0.0, 1.0, 0.0),
                          TGPoint3(0.0, 0.0, 1.0),
                          TGPoint3(1.0, 0.0, 0.0),
                          ObjectEmitterProperty.OEP_PROBE)
    # 90° rotation about z: x→y, y→-x (column-vector convention)
    R = TGMatrix3()
    R.SetRow(0, TGPoint3(0.0, -1.0, 0.0))
    R.SetRow(1, TGPoint3(1.0,  0.0, 0.0))
    R.SetRow(2, TGPoint3(0.0,  0.0, 1.0))
    world_loc = TGPoint3(10.0, 20.0, 30.0)
    _make_synthetic_ship([probe], world_loc, R, obj_id=4245, monkeypatch=monkeypatch)

    import Actions.ShipScriptActions as ssa
    ssa.LaunchObject(None, 4245, "p", ObjectEmitterProperty.OEP_PROBE)

    e = App._emission_recorder.events()[0]
    # Expected world position: R · (0, 3.35, 0) + (10, 20, 30)
    #   R · (0, 3.35, 0) = (-3.35, 0, 0)
    #   + (10, 20, 30) = (6.65, 20, 30)
    assert abs(e["world_position"][0] - 6.65) < 1e-9
    assert abs(e["world_position"][1] - 20.0) < 1e-9
    assert abs(e["world_position"][2] - 30.0) < 1e-9
    # Expected world_forward: R · (0,1,0) = (-1, 0, 0)
    assert abs(e["world_forward"][0] - (-1.0)) < 1e-9
    assert abs(e["world_forward"][1] -   0.0)  < 1e-9
    assert abs(e["world_forward"][2] -   0.0)  < 1e-9
    # Expected world_up: R · (0,0,1) = (0, 0, 1)
    assert abs(e["world_up"][0] - 0.0) < 1e-9
    assert abs(e["world_up"][1] - 0.0) < 1e-9
    assert abs(e["world_up"][2] - 1.0) < 1e-9


def test_hook_records_nothing_when_recorder_disabled(monkeypatch):
    mh.setup_sdk()
    from engine.appc.emission import install_launch_object_hook
    install_launch_object_hook()
    App._emission_recorder.disable()  # explicit

    shuttle = _make_emitter("Shuttle Bay", TGPoint3(0,-2,0), TGPoint3(0,-1,0),
                            TGPoint3(0,0,1), TGPoint3(-1,0,0), ObjectEmitterProperty.OEP_SHUTTLE)
    R = TGMatrix3()
    _make_synthetic_ship([shuttle], TGPoint3(0,0,0), R, obj_id=4246, monkeypatch=monkeypatch)

    import Actions.ShipScriptActions as ssa
    rc = ssa.LaunchObject(None, 4246, "s", ObjectEmitterProperty.OEP_SHUTTLE)
    assert rc == 0
    assert App._emission_recorder.events() == []
