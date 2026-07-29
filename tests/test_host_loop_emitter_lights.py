"""Tests for the Task-5 per-frame subsystem-light-emitter producer.

Mirrors the torpedo producer (`_build_dynamic_light_render_data`): body-frame
emitter specs cached per ship at spawn are transformed to world space each
frame and health-gated before being handed to `host_io.set_dynamic_lights`.
See `.superpowers/sdd/2026-07-29-subsystem-light-emitters/task-5-brief.md`.
"""
import math

import pytest

from engine.appc.math import TGPoint3, TGMatrix3
from engine.appc.properties import SubsystemProperty
from engine.appc import light_emitters
from engine.host_loop import (
    _build_emitter_light_render_data,
    _build_ship_emitter_cache,
)


def _point_prop(position, color=(1.0, 0.5, 0.25), radius=3.0, intensity=2.5):
    """A SubsystemProperty carrying one baked point light emitter."""
    p = SubsystemProperty("sub")
    p.SetLightEmitterKind(0, "point")
    px, py, pz = position
    p.SetLightEmitterPosition(0, px, py, pz)
    p.SetLightEmitterAxis(0, 0.0, -1.0, 0.0)
    p.SetLightEmitterLength(0, 0.0)
    p.SetLightEmitterRadius(0, radius)
    r, g, b = color
    p.SetLightEmitterColor(0, r, g, b)
    p.SetLightEmitterIntensity(0, intensity)
    return p


def _emitter_prop(kind, position, axis=(0.0, -1.0, 0.0), length=2.0, radius=1.0,
                   color=(1.0, 0.5, 0.25), intensity=2.5):
    """A SubsystemProperty carrying one baked emitter of arbitrary `kind`."""
    p = SubsystemProperty("sub")
    p.SetLightEmitterKind(0, kind)
    px, py, pz = position
    p.SetLightEmitterPosition(0, px, py, pz)
    ax, ay, az = axis
    p.SetLightEmitterAxis(0, ax, ay, az)
    p.SetLightEmitterLength(0, length)
    p.SetLightEmitterRadius(0, radius)
    r, g, b = color
    p.SetLightEmitterColor(0, r, g, b)
    p.SetLightEmitterIntensity(0, intensity)
    return p


class _Sub:
    """Fake subsystem: carries a baked-emitter property and a health state."""

    def __init__(self, prop, destroyed=False, disabled=False):
        self._prop = prop
        self._destroyed = destroyed
        self._disabled = disabled

    def GetProperty(self):
        return self._prop

    def IsDestroyed(self):
        return self._destroyed

    def IsDisabled(self):
        return self._disabled


class _Ship:
    """Fake ship: only the getters the producer/cache-build actually touch."""

    def __init__(self, loc=(0.0, 0.0, 0.0), rot=None):
        self._loc = TGPoint3(*loc)
        self._rot = rot if rot is not None else TGMatrix3()

    def GetWorldLocation(self):
        return self._loc

    def GetWorldRotation(self):
        return self._rot


def test_healthy_point_emitter_identity_pose_produces_one_light():
    ship = _Ship()
    body_pos = (1.0, 2.0, 3.0)
    prop = _point_prop(body_pos, color=(0.2, 0.4, 0.6), radius=4.0, intensity=1.5)
    sub = _Sub(prop)
    spec = light_emitters.baked_emitters(prop)[0]

    ship_instances = {ship: 42}
    ship_emitters = {42: [(sub, False, 0.0, spec)]}

    out = _build_emitter_light_render_data(ship_instances, ship_emitters)

    assert len(out) == 1
    d = out[0]
    assert d["position"] == (1.0, 2.0, 3.0)   # identity rotation, zero loc
    assert d["color"] == (0.2, 0.4, 0.6)
    assert d["radius"] == 4.0
    assert d["intensity"] == 1.5


def test_destroyed_parent_subsystem_emits_no_light():
    ship = _Ship()
    prop = _point_prop((1.0, 0.0, 0.0))
    sub = _Sub(prop, destroyed=True)
    spec = light_emitters.baked_emitters(prop)[0]

    ship_instances = {ship: 7}
    ship_emitters = {7: [(sub, False, 0.0, spec)]}

    out = _build_emitter_light_render_data(ship_instances, ship_emitters)
    assert out == []


def test_rotated_translated_ship_transforms_body_position_to_world():
    loc = (10.0, -5.0, 2.0)
    rot = TGMatrix3()
    rot.MakeZRotation(math.pi / 2.0)  # 90 degrees about Z
    ship = _Ship(loc=loc, rot=rot)
    body_pos = (1.0, 0.0, 0.0)
    prop = _point_prop(body_pos)
    sub = _Sub(prop)
    spec = light_emitters.baked_emitters(prop)[0]

    ship_instances = {ship: 3}
    ship_emitters = {3: [(sub, False, 0.0, spec)]}

    out = _build_emitter_light_render_data(ship_instances, ship_emitters)
    assert len(out) == 1

    expected_off = TGPoint3(*body_pos)
    expected_off.MultMatrixLeft(rot)
    expected = (loc[0] + expected_off.x, loc[1] + expected_off.y, loc[2] + expected_off.z)

    got = out[0]["position"]
    for g, e in zip(got, expected):
        assert g == pytest.approx(e)


def test_strip_and_cone_transform_correctly_on_rotated_translated_ship():
    """The point-only tests above never exercise `direction`/`position_b`.

    A strip's two endpoints and a cone's direction must transform the same
    way the producer documents: positions get loc + R*body (translation
    included), direction gets R*body only (rotation-only, no translation).
    """
    loc = (10.0, -5.0, 2.0)
    rot = TGMatrix3()
    rot.MakeZRotation(math.pi / 2.0)  # 90 degrees about Z
    ship = _Ship(loc=loc, rot=rot)

    strip_body_pos = (1.0, 0.0, 0.0)
    strip_axis = (0.0, 1.0, 0.0)
    strip_length = 2.0
    strip_prop = _emitter_prop("strip", strip_body_pos, axis=strip_axis,
                                length=strip_length)
    strip_sub = _Sub(strip_prop)
    strip_spec = light_emitters.baked_emitters(strip_prop)[0]

    cone_body_pos = (0.0, 2.0, 0.0)
    cone_axis = (0.0, -1.0, 0.0)
    cone_prop = _emitter_prop("cone", cone_body_pos, axis=cone_axis,
                               length=1.0, radius=1.0)
    cone_sub = _Sub(cone_prop)
    cone_spec = light_emitters.baked_emitters(cone_prop)[0]

    ship_instances = {ship: 9}
    ship_emitters = {9: [(strip_sub, False, 0.0, strip_spec),
                          (cone_sub, False, 1.0, cone_spec)]}

    out = _build_emitter_light_render_data(ship_instances, ship_emitters)
    assert len(out) == 2
    strip_out, cone_out = out[0], out[1]

    # Strip endpoints: body-frame half-offsets from emitter_spec_to_struct,
    # THEN loc + R*body (translation included) by the producer.
    half = strip_length / 2.0
    body_a = TGPoint3(strip_body_pos[0] - strip_axis[0] * half,
                       strip_body_pos[1] - strip_axis[1] * half,
                       strip_body_pos[2] - strip_axis[2] * half)
    body_b = TGPoint3(strip_body_pos[0] + strip_axis[0] * half,
                       strip_body_pos[1] + strip_axis[1] * half,
                       strip_body_pos[2] + strip_axis[2] * half)
    body_a.MultMatrixLeft(rot)
    body_b.MultMatrixLeft(rot)
    expected_a = (loc[0] + body_a.x, loc[1] + body_a.y, loc[2] + body_a.z)
    expected_b = (loc[0] + body_b.x, loc[1] + body_b.y, loc[2] + body_b.z)
    for g, e in zip(strip_out["position"], expected_a):
        assert g == pytest.approx(e)
    for g, e in zip(strip_out["position_b"], expected_b):
        assert g == pytest.approx(e)

    # Cone direction: rotation-only (R*body), NO translation added.
    body_dir = TGPoint3(*cone_axis)
    body_dir.MultMatrixLeft(rot)
    expected_dir = (body_dir.x, body_dir.y, body_dir.z)
    for g, e in zip(cone_out["direction"], expected_dir):
        assert g == pytest.approx(e)
    # Sanity: a unit direction, not a translated point -- proves `loc`
    # (magnitude ~10) was never added in.
    for g in cone_out["direction"]:
        assert abs(g) <= 1.0 + 1e-6


# ---------------------------------------------------------------------------
# Per-ship emitter cache build (spawn-time)
# ---------------------------------------------------------------------------

class _StubShipNoSubsystems:
    """Ship with no impulse engine and an empty subsystem walk — exercises
    the never-block-spawn guards with nothing to find."""

    def GetImpulseEngineSubsystem(self):
        return None


def test_cache_build_empty_ship_returns_no_entries(monkeypatch):
    import engine.host_loop as host_loop

    monkeypatch.setattr(
        "engine.ui.ship_property_viewer._iter_subsystems", lambda ship: [])

    ship = _StubShipNoSubsystems()
    entries = _build_ship_emitter_cache(ship)
    assert entries == []


def test_cache_build_marks_impulse_membership_and_assigns_phase(monkeypatch):
    prop_impulse = _point_prop((0.0, -1.0, 0.0))
    prop_other = _point_prop((0.0, 1.0, 0.0))
    impulse_sub = _Sub(prop_impulse)
    other_sub = _Sub(prop_other)

    class _ImpulseAgg:
        def GetNumChildSubsystems(self):
            return 0  # no children -> impulse_engines returns [self-parent]

    class _Ship2:
        def __init__(self):
            self._impulse_agg = _ImpulseAgg()

        def GetImpulseEngineSubsystem(self):
            return self._impulse_agg

    ship = _Ship2()

    # _iter_subsystems is patched to yield the impulse aggregator itself
    # (matching impulse_engines' no-children fallback) plus an unrelated sub.
    monkeypatch.setattr(
        "engine.ui.ship_property_viewer._iter_subsystems",
        lambda s: [ship._impulse_agg, other_sub]
        if s is ship else [])

    # The impulse aggregator needs GetProperty for baked_emitters to find
    # anything; graft it on for this test.
    ship._impulse_agg.GetProperty = lambda: prop_impulse

    entries = _build_ship_emitter_cache(ship)
    assert len(entries) == 2

    by_impulse = {e[1] for e in entries}
    assert True in by_impulse and False in by_impulse
    impulse_entry = [e for e in entries if e[1] is True][0]
    other_entry = [e for e in entries if e[1] is False][0]
    assert impulse_entry[0] is ship._impulse_agg
    assert other_entry[0] is other_sub
    # phase = j * 1.7 + subsystem_index; both are index-0 emitters on their
    # subsystem (j=0), so phase == subsystem_index (0 then 1).
    assert {round(e[2], 3) for e in entries} == {0.0, 1.0}
