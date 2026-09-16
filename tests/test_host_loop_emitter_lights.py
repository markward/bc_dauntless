"""Tests for the Task-5 per-frame subsystem-light-emitter producer.

Mirrors the torpedo producer (`_build_dynamic_light_render_data`) in shape,
but the light stays body-frame: cached per-ship structs (built once at
spawn) are health-gated and tagged with the ship's render `instance_id`,
and the renderer resolves them to world through the hull's own matrix. See
`.superpowers/sdd/2026-07-29-subsystem-light-emitters/task-5-brief.md` and
`.superpowers/sdd/2026-09-16-instance-attached-emitter-lights/task-4-brief.md`.
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
        raise AssertionError(
            "producer must not read GetWorldRotation: lights are body-frame and "
            "resolved by the renderer through inst->world")


def _entry(sub, spec, is_impulse=False, is_warp=False, phase=0.0):
    """One cache entry in the Task-3 layout, struct prebuilt like the real cache."""
    return (sub, is_impulse, is_warp, phase, spec,
            light_emitters.emitter_spec_to_struct(spec))


def test_healthy_point_emitter_identity_pose_produces_one_light():
    ship = _Ship()
    body_pos = (1.0, 2.0, 3.0)
    prop = _point_prop(body_pos, color=(0.2, 0.4, 0.6), radius=4.0, intensity=1.5)
    sub = _Sub(prop)
    spec = light_emitters.baked_emitters(prop)[0]

    ship_instances = {ship: 42}
    ship_emitters = {42: [_entry(sub, spec)]}

    out = _build_emitter_light_render_data(ship_instances, ship_emitters)

    assert len(out) == 1
    d = out[0]
    assert d["position"] == (1.0, 2.0, 3.0)   # identity rotation, zero loc
    assert d["color"] == (0.2, 0.4, 0.6)
    assert d["radius"] == 4.0
    assert d["intensity"] == 1.5
    assert d["instance_id"] == 42


def test_disabling_ship_light_emitters_produces_no_lights():
    """The Cinematic Lighting master toggle gates this producer. Off must
    drop every emitter light, not merely dim them."""
    ship = _Ship()
    prop = _point_prop((1.0, 2.0, 3.0))
    spec = light_emitters.baked_emitters(prop)[0]
    ship_instances = {ship: 42}
    ship_emitters = {42: [_entry(_Sub(prop), spec)]}

    assert _build_emitter_light_render_data(ship_instances, ship_emitters)

    light_emitters.set_enabled(False)
    try:
        assert light_emitters.enabled() is False
        assert _build_emitter_light_render_data(ship_instances, ship_emitters) == []
    finally:
        light_emitters.set_enabled(True)
    assert _build_emitter_light_render_data(ship_instances, ship_emitters)


def test_ship_light_emitters_enabled_by_default():
    assert light_emitters.enabled() is True


def test_destroyed_parent_subsystem_emits_no_light():
    ship = _Ship()
    prop = _point_prop((1.0, 0.0, 0.0))
    sub = _Sub(prop, destroyed=True)
    spec = light_emitters.baked_emitters(prop)[0]

    ship_instances = {ship: 7}
    ship_emitters = {7: [_entry(sub, spec)]}

    out = _build_emitter_light_render_data(ship_instances, ship_emitters)
    assert out == []


def test_rotated_translated_ship_emits_body_frame_position_and_instance_id():
    """The producer no longer transforms anything: the position stays the
    authored body-frame offset and the dict carries the ship's render
    instance id so the renderer resolves it through the hull's own matrix."""
    loc = (10.0, -5.0, 2.0)
    rot = TGMatrix3()
    rot.MakeZRotation(math.pi / 2.0)
    ship = _Ship(loc=loc, rot=rot)
    body_pos = (1.0, 0.0, 0.0)
    prop = _point_prop(body_pos)
    sub = _Sub(prop)
    spec = light_emitters.baked_emitters(prop)[0]

    ship_instances = {ship: 3}
    ship_emitters = {3: [_entry(sub, spec)]}

    out = _build_emitter_light_render_data(ship_instances, ship_emitters)
    assert len(out) == 1
    assert out[0]["position"] == pytest.approx(body_pos)
    assert out[0]["instance_id"] == 3
    assert "position_b" not in out[0]


def test_strip_and_cone_stay_body_frame_and_carry_instance_id():
    rot = TGMatrix3()
    rot.MakeZRotation(math.pi / 2.0)
    ship = _Ship(loc=(4.0, 4.0, 4.0), rot=rot)
    strip_prop = _emitter_prop("strip", (1.0, 2.0, 3.0), axis=(0.0, -1.0, 0.0), length=2.0)
    cone_prop = _emitter_prop("cone", (0.0, 0.0, 0.0), axis=(1.0, 0.0, 0.0),
                              length=2.0, radius=1.0)
    strip_spec = light_emitters.baked_emitters(strip_prop)[0]
    cone_spec = light_emitters.baked_emitters(cone_prop)[0]
    ship_instances = {ship: 9}
    ship_emitters = {9: [_entry(_Sub(strip_prop), strip_spec),
                         _entry(_Sub(cone_prop), cone_spec)]}

    out = _build_emitter_light_render_data(ship_instances, ship_emitters)
    assert len(out) == 2
    strip, cone = out
    assert strip["position"] == pytest.approx((1.0, 3.0, 3.0))
    assert strip["position_b"] == pytest.approx((1.0, 1.0, 3.0))
    assert strip["instance_id"] == 9
    assert cone["direction"] == pytest.approx((1.0, 0.0, 0.0))
    assert cone["up"] == pytest.approx(light_emitters.emitter_spec_to_struct(cone_spec)["up"])
    assert cone["instance_id"] == 9


def test_producer_does_not_mutate_the_cached_struct():
    """Per-frame output is a COPY: intensity/instance_id must never leak
    back into the cache entry shared across frames."""
    ship = _Ship()
    prop = _point_prop((1.0, 2.0, 3.0), intensity=2.0)
    spec = light_emitters.baked_emitters(prop)[0]
    entry = _entry(_Sub(prop), spec)
    out = _build_emitter_light_render_data({ship: 5}, {5: [entry]})
    assert out[0]["instance_id"] == 5
    assert "instance_id" not in entry[5]
    assert entry[5]["intensity"] == 2.0


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
    assert {round(e[3], 3) for e in entries} == {0.0, 1.0}


def test_cache_entries_carry_the_prebuilt_body_frame_struct(monkeypatch):
    """The static geometry is converted ONCE at cache build, not per frame.
    Entry layout: (sub, is_impulse, is_warp, phase, spec, struct)."""
    prop = _emitter_prop("strip", (1.0, 2.0, 3.0), axis=(0.0, -1.0, 0.0), length=2.0)
    sub = _Sub(prop)

    class _Ship3:
        pass
    ship = _Ship3()
    monkeypatch.setattr("engine.ui.ship_property_viewer._iter_subsystems",
                        lambda s: [sub] if s is ship else [])

    entries = _build_ship_emitter_cache(ship)
    assert len(entries) == 1
    assert len(entries[0]) == 6
    _sub, _imp, _warp, _ph, spec, struct = entries[0]
    assert struct == light_emitters.emitter_spec_to_struct(spec)
    # Body-frame strip: endpoints straddle the authored position along the axis.
    assert struct["position"] == pytest.approx((1.0, 3.0, 3.0))
    assert struct["position_b"] == pytest.approx((1.0, 1.0, 3.0))
    assert "instance_id" not in struct   # the producer adds it per frame
