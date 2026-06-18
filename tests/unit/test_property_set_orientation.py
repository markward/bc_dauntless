"""Bug B regression: typed ``SetOrientation`` on
``EnergyWeaponProperty`` and ``PositionOrientationProperty``.

Galaxy hardpoint scripts call ``DorsalPhaser1.SetOrientation(forward,
up)`` to point a phaser bank's firing-arc reference frame. Prior to
this fix the call fell through ``TGModelProperty.__getattr__`` to the
data-bag and was silently dropped, so every bank kept its default
Direction = (0, 1, 0) -- i.e. every phaser arc was centred on the
ship's nose. Same bug class for ``PositionOrientationProperty``'s
three-arg form used by Viewscreen* / FirstPersonCamera mounts.

See ``docs/instrumented_experiments/hardpoint_handling_research.md``
section "Bug B" for the full investigation.
"""
from engine.appc.math import TGPoint3
from engine.appc.properties import (
    PhaserProperty,
    PositionOrientationProperty,
    PulseWeaponProperty,
    TractorBeamProperty,
)
from engine.appc.subsystems import _emitter_in_arc


def test_set_orientation_stores_forward_direction():
    p = PhaserProperty("DorsalPhaser1")
    p.SetOrientation(TGPoint3(-1.0, 0.0, 0.0), TGPoint3(0.0, 0.0, 1.0))
    d = p.GetDirection()
    assert (d.x, d.y, d.z) == (-1.0, 0.0, 0.0)


def test_set_orientation_stores_up_axis():
    p = PhaserProperty("DorsalPhaser1")
    p.SetOrientation(TGPoint3(-1.0, 0.0, 0.0), TGPoint3(0.0, 0.0, 1.0))
    u = p.GetUp()
    assert (u.x, u.y, u.z) == (0.0, 0.0, 1.0)


def test_set_orientation_derives_right_as_forward_cross_up():
    """right = forward × up — right-handed (post 2026-06-18 un-mirror), so
    GetRight() is the true starboard axis."""
    p = PhaserProperty("DorsalPhaser1")
    p.SetOrientation(TGPoint3(-1.0, 0.0, 0.0), TGPoint3(0.0, 0.0, 1.0))
    r = p.GetRight()
    # (-1,0,0) × (0,0,1) = (0, 1, 0)
    assert (r.x, r.y, r.z) == (0.0, 1.0, 0.0)


def test_get_orientation_forward_mirrors_phaserbank_api():
    p = PhaserProperty("DorsalPhaser1")
    p.SetOrientation(TGPoint3(-1.0, 0.0, 0.0), TGPoint3(0.0, 0.0, 1.0))
    f = p.GetOrientationForward()
    assert (f.x, f.y, f.z) == (-1.0, 0.0, 0.0)
    u = p.GetOrientationUp()
    assert (u.x, u.y, u.z) == (0.0, 0.0, 1.0)
    r = p.GetOrientationRight()
    assert (r.x, r.y, r.z) == (0.0, 1.0, 0.0)


def test_set_orientation_available_on_pulse_and_tractor():
    """EnergyWeaponProperty hierarchy — all share the same setter."""
    for cls in (PulseWeaponProperty, TractorBeamProperty):
        p = cls("any")
        p.SetOrientation(TGPoint3(1.0, 0.0, 0.0), TGPoint3(0.0, 0.0, 1.0))
        assert (p.GetDirection().x, p.GetDirection().y, p.GetDirection().z) == (1.0, 0.0, 0.0)


def test_orientation_does_not_leak_to_data_bag():
    p = PhaserProperty("DorsalPhaser1")
    p.SetOrientation(TGPoint3(-1.0, 0.0, 0.0), TGPoint3(0.0, 0.0, 1.0))
    leaks = [k for k in p._data.keys() if k[0] == "Orientation"]
    assert leaks == [], f"SetOrientation fell through to data-bag: {leaks}"


def test_set_orientation_returns_fresh_copies():
    p = PhaserProperty("DorsalPhaser1")
    fwd = TGPoint3(-1.0, 0.0, 0.0)
    up  = TGPoint3(0.0, 0.0, 1.0)
    p.SetOrientation(fwd, up)
    # Mutate sources after the call.
    fwd.SetXYZ(9.0, 9.0, 9.0)
    up.SetXYZ(9.0, 9.0, 9.0)
    d = p.GetDirection()
    u = p.GetUp()
    assert (d.x, d.y, d.z) == (-1.0, 0.0, 0.0)
    assert (u.x, u.y, u.z) == (0.0, 0.0, 1.0)
    # Returned copies must be independent of the stored values.
    d.SetXYZ(5.0, 5.0, 5.0)
    d2 = p.GetDirection()
    assert (d2.x, d2.y, d2.z) == (-1.0, 0.0, 0.0)


def test_default_orientation_is_sdk_body_frame():
    p = PhaserProperty("any")
    d = p.GetDirection()
    u = p.GetUp()
    r = p.GetRight()
    assert (d.x, d.y, d.z) == (0.0, 1.0, 0.0)
    assert (u.x, u.y, u.z) == (0.0, 0.0, 1.0)
    assert (r.x, r.y, r.z) == (1.0, 0.0, 0.0)


# ---------------------------------------------------------------------------
# PositionOrientationProperty (Bug B parallel) — Viewscreen / FirstPersonCamera
# ---------------------------------------------------------------------------

def test_position_orientation_property_three_arg_round_trip():
    p = PositionOrientationProperty("ViewscreenForward")
    fwd = TGPoint3(0.0, 1.0, 0.0)
    up  = TGPoint3(0.0, 0.0, 1.0)
    right = TGPoint3(1.0, 0.0, 0.0)
    p.SetOrientation(fwd, up, right)
    assert (p.GetForward().x, p.GetForward().y, p.GetForward().z) == (0.0, 1.0, 0.0)
    assert (p.GetUp().x,      p.GetUp().y,      p.GetUp().z)      == (0.0, 0.0, 1.0)
    assert (p.GetRight().x,   p.GetRight().y,   p.GetRight().z)   == (1.0, 0.0, 0.0)


def test_position_orientation_property_does_not_leak_to_data_bag():
    p = PositionOrientationProperty("ViewscreenForward")
    p.SetOrientation(TGPoint3(0, 1, 0), TGPoint3(0, 0, 1), TGPoint3(1, 0, 0))
    leaks = [k for k in p._data.keys() if k[0] == "Orientation"]
    assert leaks == []


# ---------------------------------------------------------------------------
# End-to-end arc gating — the original symptom this bug class produced.
# ---------------------------------------------------------------------------

class _FakeEmitter:
    """Minimal stand-in for ShipSubsystem matching _emitter_in_arc's reads."""
    _arc_set = True
    def __init__(self, d, r, aw, ah):
        self._direction = d
        self._right     = r
        self._arc_w     = aw
        self._arc_h     = ah
    def GetDirection(self):       return self._direction
    def GetRight(self):           return self._right
    def GetArcWidthAngles(self):  return self._arc_w
    def GetArcHeightAngles(self): return self._arc_h


def test_dorsal_phaser1_arc_rejects_target_dead_ahead():
    """DorsalPhaser1 fires toward body -X (port).  A target dead ahead
    (+Y) must be OUTSIDE its ±50° arc.  Before SetOrientation worked,
    every phaser bank's Direction stayed at the default +Y so this
    assertion failed by accepting the nose target on every bank."""
    p = PhaserProperty("DorsalPhaser1")
    p.SetOrientation(TGPoint3(-1.0, 0.0, 0.0), TGPoint3(0.0, 0.0, 1.0))
    # galaxy.py:414 — ±50°.
    arc_w = (-0.872665, 0.872665)
    arc_h = (-0.052360, 1.047198)
    emitter = _FakeEmitter(p.GetDirection(), p.GetRight(), arc_w, arc_h)
    assert _emitter_in_arc(emitter, ship=None,
                           aim_world=TGPoint3(0.0, 1.0, 0.0)) is False


def test_dorsal_phaser1_arc_accepts_target_to_port():
    p = PhaserProperty("DorsalPhaser1")
    p.SetOrientation(TGPoint3(-1.0, 0.0, 0.0), TGPoint3(0.0, 0.0, 1.0))
    arc_w = (-0.872665, 0.872665)
    arc_h = (-0.052360, 1.047198)
    emitter = _FakeEmitter(p.GetDirection(), p.GetRight(), arc_w, arc_h)
    assert _emitter_in_arc(emitter, ship=None,
                           aim_world=TGPoint3(-1.0, 0.0, 0.0)) is True
