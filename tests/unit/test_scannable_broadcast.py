"""ObjectClass.SetScannable / IsScannable.

Bridge/ScienceMenuHandlers.TargetChanged (sdk/.../ScienceMenuHandlers.py:488)
gates the "Scan Target" button's enabled state on pTarget.IsScannable(); the
engine had no implementation at all, so App's __getattr__/TGObject._Stub
fallback returned a truthy stub -- meaning the button silently enabled for
EVERY target regardless of real scannability.

Default is True (scannable), not False like IsHailable. Evidence
(docs cross-checked against sdk/Build/scripts):
  * SetScannable(FALSE) appears only ~9 times total across the whole 1228-file
    SDK, and every one of those call sites also calls SetTargetable(FALSE)/
    SetHailable(FALSE) in the same breath to narratively hide a specific ship
    until a reveal beat (Episode6/E6M4's cloaked Kessok + Keldon derelict,
    Episode6/E6M2's escape pods, Episode3/E3M1's Amagon asteroid,
    Episode3/E3M2's invisible Kessok) -- and those SAME ships are then
    SetScannable(TRUE)'d back on reveal.
  * The vast majority of ships/planets spawned across the SDK never call
    SetScannable at all. If the engine default were False, Science's core
    "scan any nearby ship/planet" feature would be silently dead in every
    mission that doesn't explicitly opt in -- implausible for a headline
    bridge-station feature.
  * This matches _targetable's already-established default of 1 (see
    properties.py / subsystems.py), not _hailable's narrower opt-in default
    of False (dialogue is per-character, scanning is not).
  * The decompiled Appc corpus's swig_ObjectClass_SetScannable/IsScannable
    thunks (06_physics_collision.c) are pure vtable pass-throughs and do not
    reveal the C++-side default value directly -- the SDK call-site census
    above is what settles it.
"""
import App
from engine.appc.objects import ObjectClass
from engine.appc.ships import ShipClass_Create
from engine.appc.planet import Planet_Create, Sun_Create

_received: list = []


def _on_scannable_change(dest, event):
    _received.append((event.GetSource(), event.GetBool()))


def _subscribe():
    _received.clear()
    App.g_kEventManager.AddBroadcastPythonFuncHandler(
        App.ET_SCANNABLE_CHANGE, None, __name__ + "._on_scannable_change")


def test_default_scannable_is_true_for_bare_object():
    assert ObjectClass().IsScannable() == 1


def test_default_scannable_is_true_for_ship_and_planet_and_sun():
    assert ShipClass_Create("Galaxy").IsScannable() == 1
    assert Planet_Create(100.0, "x.nif").IsScannable() == 1
    assert Sun_Create(800.0, 200.0, 100.0).IsScannable() == 1


def test_set_scannable_false_then_true_reflects_state():
    obj = ObjectClass()
    obj.SetScannable(0)
    assert obj.IsScannable() == 0
    obj.SetScannable(1)
    assert obj.IsScannable() == 1


def test_set_scannable_false_broadcasts_change():
    _subscribe()
    obj = ObjectClass()
    obj.SetName("Kessok")
    obj.SetScannable(0)
    assert len(_received) == 1
    src, val = _received[0]
    assert src is obj
    assert val == 0


def test_set_scannable_true_broadcasts_bool_one_after_disable():
    obj = ObjectClass()
    obj.SetScannable(0)
    _subscribe()  # subscribe after the disable so we only capture the re-enable
    obj.SetScannable(1)
    assert len(_received) == 1
    assert _received[0][1] == 1


def test_no_broadcast_when_state_unchanged():
    _subscribe()
    obj = ObjectClass()
    obj.SetScannable(1)      # already True (default) -> no event
    assert _received == []
    obj.SetScannable(0)
    obj.SetScannable(0)      # already False -> no second event
    assert len(_received) == 1


def test_planet_inherits_scannable_broadcast():
    _subscribe()
    p = Planet_Create(200.0, "iceplanet.nif")
    p.SetName("Haven")
    assert p.IsScannable() == 1
    p.SetScannable(0)
    assert len(_received) == 1
    assert _received[0][0] is p
    assert p.IsScannable() == 0
