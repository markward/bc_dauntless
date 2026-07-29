import math
import pytest
from engine.appc.light_emitters import (
    default_emitter_spec, baked_emitters, emitter_spec_to_struct)
from engine.appc.properties import SubsystemProperty


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
        assert set(s) == {"kind", "position", "axis", "length", "radius", "color", "intensity"}


def test_baked_emitters_roundtrip():
    specs = [default_emitter_spec("point"), default_emitter_spec("cone")]
    specs[1]["radius"] = 1.0; specs[1]["length"] = 2.0
    p = _prop_with_emitters(specs)
    got = baked_emitters(p)
    assert len(got) == 2
    assert got[0]["kind"] == "point"
    assert got[1]["kind"] == "cone"
    assert got[1]["radius"] == pytest.approx(1.0)


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


def test_cone_struct_derives_half_angle():
    s = default_emitter_spec("cone")
    s["radius"] = 1.0; s["length"] = 1.0; s["axis"] = (0.0, -1.0, 0.0)
    d = emitter_spec_to_struct(s)
    assert d["direction"] == pytest.approx((0.0, -1.0, 0.0))
    assert d["cos_half_angle"] == pytest.approx(math.cos(math.atan2(1.0, 1.0)))
