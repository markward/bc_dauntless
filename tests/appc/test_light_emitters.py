import math
import pytest
from engine.appc.light_emitters import (
    default_emitter_spec, baked_emitters, emitter_spec_to_struct,
    resolve_emitter_intensity, _derive_up)
from engine.appc.properties import SubsystemProperty
from engine.appc.subsystem_glow import HEALTHY, DISABLED, DESTROYED
from engine.ui.ship_property_viewer import emitter_spec_to_calls


def _prop_with_emitters(specs):
    p = SubsystemProperty()
    # Record directly via the setters (mirrors what the writer would emit).
    for j, s in enumerate(specs):
        p.SetLightEmitterKind(j, s["kind"])
        px, py, pz = s["position"]; p.SetLightEmitterPosition(j, px, py, pz)
        ax, ay, az = s["axis"];     p.SetLightEmitterAxis(j, ax, ay, az)
        p.SetLightEmitterLength(j, s["length"])
        p.SetLightEmitterRadius(j, s["radius"])
        r, g, b = s["color"];       p.SetLightEmitterColor(j, r, g, b)
        p.SetLightEmitterIntensity(j, s["intensity"])
    return p


def test_default_specs_have_all_keys():
    for kind in ("point", "strip", "cone"):
        s = default_emitter_spec(kind)
        assert s["kind"] == kind
        assert set(s) == {"kind", "position", "axis", "length", "radius", "radius_y",
                           "up", "color", "intensity"}


def test_default_cone_spec_has_circular_radius_y_and_an_up():
    s = default_emitter_spec("cone")
    assert s["radius_y"] == pytest.approx(s["radius"])
    assert len(s["up"]) == 3


def test_baked_emitters_roundtrip():
    specs = [default_emitter_spec("point"), default_emitter_spec("cone")]
    specs[1]["radius"] = 1.0; specs[1]["length"] = 2.0
    p = _prop_with_emitters(specs)
    got = baked_emitters(p)
    assert len(got) == 2
    assert got[0]["kind"] == "point"
    assert got[1]["kind"] == "cone"
    assert got[1]["radius"] == pytest.approx(1.0)


def _apply_calls(prop, calls):
    for name, args in calls:
        getattr(prop, name)(*args)


def test_elliptical_cone_roundtrips_radius_y_and_up_through_calls():
    spec = default_emitter_spec("cone")
    spec["radius"] = 1.0
    spec["radius_y"] = 2.5
    spec["length"] = 3.0
    spec["axis"] = (0.0, -1.0, 0.0)
    spec["up"] = (1.0, 0.0, 0.0)
    p = SubsystemProperty()
    _apply_calls(p, emitter_spec_to_calls(0, spec))

    got = baked_emitters(p)
    assert len(got) == 1
    assert got[0]["radius_y"] == pytest.approx(2.5)
    assert got[0]["up"] == pytest.approx((1.0, 0.0, 0.0))


def test_legacy_cone_without_radius_y_or_up_setters_loads_circular():
    # Mirrors a saved cone written before this feature: only the original
    # Kind/Position/Axis/Length/Radius/Color/Intensity setters were emitted.
    specs = [default_emitter_spec("cone")]
    specs[0]["radius"] = 1.0
    specs[0]["length"] = 2.0
    specs[0]["axis"] = (0.0, -1.0, 0.0)
    p = _prop_with_emitters(specs)   # legacy writer: no RadiusY/Up setters

    got = baked_emitters(p)
    assert len(got) == 1
    assert got[0]["radius_y"] == pytest.approx(got[0]["radius"])
    assert got[0]["up"] == pytest.approx(_derive_up(specs[0]["axis"]))


def test_point_struct_is_degenerate_segment():
    d = emitter_spec_to_struct(default_emitter_spec("point"))
    assert "position_b" not in d          # point => pos_b defaults to pos_a native-side
    assert d.get("cos_half_angle", -1.0) < 0.0


def test_strip_struct_has_two_endpoints():
    s = default_emitter_spec("strip")
    s["position"] = (0.0, 0.0, 0.0); s["axis"] = (0.0, 1.0, 0.0); s["length"] = 2.0
    d = emitter_spec_to_struct(s)
    assert d["position"] == pytest.approx((0.0, -1.0, 0.0))
    assert d["position_b"] == pytest.approx((0.0, 1.0, 0.0))


def test_elliptical_cone_struct_has_two_tangents_and_unit_up_no_cos_half_angle():
    s = default_emitter_spec("cone")
    s["radius"] = 1.0; s["radius_y"] = 2.0; s["length"] = 4.0
    s["axis"] = (0.0, -1.0, 0.0); s["up"] = (1.0, 0.0, 0.0)
    d = emitter_spec_to_struct(s)
    assert d["direction"] == pytest.approx((0.0, -1.0, 0.0))
    assert "cos_half_angle" not in d
    assert d["spot_tan_x"] == pytest.approx(1.0 / 4.0)
    assert d["spot_tan_y"] == pytest.approx(2.0 / 4.0)
    ux, uy, uz = d["up"]
    assert math.sqrt(ux * ux + uy * uy + uz * uz) == pytest.approx(1.0)


def test_circular_cone_struct_has_equal_tangents():
    s = default_emitter_spec("cone")
    s["radius"] = 1.0; s["length"] = 1.0; s["axis"] = (0.0, -1.0, 0.0)
    d = emitter_spec_to_struct(s)
    assert "cos_half_angle" not in d
    assert d["spot_tan_x"] == pytest.approx(d["spot_tan_y"])


def test_cone_reach_is_length_not_base_radius():
    # The drawn cone frustum extends `length` (DebugCone's M[2] = forward *
    # length); the light must fade out at that same distance, not at the
    # base radius. Angular spread (spot_tan_x/y) stays driven by the base
    # radii -- only the attenuation `radius` (reach) changes to `length`.
    s = default_emitter_spec("cone")
    s["radius"] = 1.0; s["radius_y"] = 2.5; s["length"] = 6.0
    d = emitter_spec_to_struct(s)
    assert d["radius"] == pytest.approx(6.0)
    assert d["spot_tan_x"] == pytest.approx(1.0 / 6.0)
    assert d["spot_tan_y"] == pytest.approx(2.5 / 6.0)


def test_emitter_spec_to_calls_emits_radius_y_and_up_only_when_elliptical():
    circ = default_emitter_spec("cone")
    circ["radius"] = 1.0; circ["radius_y"] = 1.0
    names = [n for n, _a in emitter_spec_to_calls(0, circ)]
    assert "SetLightEmitterRadiusY" not in names
    assert "SetLightEmitterUp" not in names

    ellip = default_emitter_spec("cone")
    ellip["radius"] = 1.0; ellip["radius_y"] = 2.0
    names2 = [n for n, _a in emitter_spec_to_calls(0, ellip)]
    assert "SetLightEmitterRadiusY" in names2
    assert "SetLightEmitterUp" in names2


class _Sub:
    def __init__(self, destroyed=False, disabled=False):
        self._d, self._x = destroyed, disabled
    def IsDestroyed(self): return self._d
    def IsDisabled(self): return self._x


def test_healthy_emitter_is_full_intensity():
    s = default_emitter_spec("point"); s["intensity"] = 3.0
    assert resolve_emitter_intensity(s, _Sub(), now=0.0) == pytest.approx(3.0)


def test_destroyed_emitter_is_off():
    s = default_emitter_spec("point")
    assert resolve_emitter_intensity(s, _Sub(destroyed=True), now=0.0) is None


def test_disabled_emitter_flickers_over_time():
    s = default_emitter_spec("point"); s["intensity"] = 4.0
    vals = [resolve_emitter_intensity(s, _Sub(disabled=True), now=t * 0.05)
            for t in range(40)]
    assert all(v is None or v <= 4.0 + 1e-6 for v in vals)
    present = [v for v in vals if v is not None]
    assert len(set(round(v, 3) for v in present)) > 1   # not a single steady value


def test_impulse_emitter_scales_with_throttle():
    s = default_emitter_spec("point"); s["intensity"] = 1.0
    lo = resolve_emitter_intensity(s, _Sub(), now=0.0, throttle_frac=0.0,
                                   is_impulse=True, powered=True)
    hi = resolve_emitter_intensity(s, _Sub(), now=0.0, throttle_frac=1.0,
                                   is_impulse=True, powered=True)
    assert hi > lo


def test_disabled_impulse_emitter_gets_no_throttle_brightening():
    # Faithfulness fix: ShipGlowController only throttle-brightens a HEALTHY
    # impulse region. A DISABLED impulse-pod emitter must NOT scale with
    # throttle_frac -- it gets flicker only (impulse_gain is neutralized to
    # 1.0 because `powered and (state == HEALTHY)` is False while disabled).
    # Use the same `now` for both throttle levels so both pass through the
    # identical flicker(now, phase) factor -- if throttle brightening leaked
    # through, hi would exceed lo.
    s = default_emitter_spec("point"); s["intensity"] = 1.0
    lo = resolve_emitter_intensity(s, _Sub(disabled=True), now=0.0,
                                   throttle_frac=0.0, is_impulse=True,
                                   powered=True)
    hi = resolve_emitter_intensity(s, _Sub(disabled=True), now=0.0,
                                   throttle_frac=1.0, is_impulse=True,
                                   powered=True)
    assert hi == pytest.approx(lo)
