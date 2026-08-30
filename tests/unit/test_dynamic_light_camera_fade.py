"""Camera-distance fade + cull gate on dynamic lights.

Both dynamic-light producers (`_build_dynamic_light_render_data` for in-flight
torpedoes, `_build_emitter_light_render_data` for authored subsystem emitters)
walked every candidate every frame with no distance gate at all, and native's
`set_dynamic_lights` then hard-clamped the result to 64 in insertion order.

The gate fades a light's intensity 1 -> 0 across a band well outside weapons
range and drops it entirely beyond the band, keyed on the CAMERA eye (not the
player ship) so a distant cutscene camera gates on what is actually being
looked at.
"""
import math

import App
import pytest

from engine.appc.math import TGPoint3, TGMatrix3
from engine.appc.properties import SubsystemProperty
from engine.appc import light_emitters
from engine.appc.projectiles import Torpedo, register
from engine.appc import projectiles
from engine.host_loop import (
    DYN_LIGHT_CULL_GU,
    DYN_LIGHT_FADE_START_GU,
    _TORPEDO_LIGHT_INTENSITY,
    _build_dynamic_light_render_data,
    _build_emitter_light_render_data,
    _camera_distance_fade,
    _note_camera_eye,
)

# Midpoint of the fade band. Kept as an expression, not a literal, so a
# re-tune of either threshold moves the sample point with it.
_MID_GU = (DYN_LIGHT_FADE_START_GU + DYN_LIGHT_CULL_GU) / 2.0


@pytest.fixture(autouse=True)
def clean_camera_and_registry():
    """Each test owns the camera eye and the torpedo registry outright."""
    projectiles._active.clear()
    _note_camera_eye(None)
    yield
    projectiles._active.clear()
    _note_camera_eye(None)


# ---------------------------------------------------------------------------
# The fade curve itself
# ---------------------------------------------------------------------------

def test_unknown_camera_never_dims():
    """No eye cached yet (first frame, or headless) must mean full intensity,
    NOT a cull -- otherwise the very first frame of a mission renders unlit."""
    _note_camera_eye(None)
    assert _camera_distance_fade((1e6, 0.0, 0.0)) == 1.0


def test_inside_fade_start_is_full_intensity():
    _note_camera_eye((0.0, 0.0, 0.0))
    assert _camera_distance_fade((20.0, 0.0, 0.0)) == 1.0


def test_exactly_at_fade_start_is_still_full_intensity():
    _note_camera_eye((0.0, 0.0, 0.0))
    assert _camera_distance_fade((DYN_LIGHT_FADE_START_GU, 0.0, 0.0)) == 1.0


def test_beyond_cull_distance_returns_none():
    """None is the caller's signal to skip building the light entirely -- the
    whole point of the gate is the work NOT done, so 0.0 would be wrong."""
    _note_camera_eye((0.0, 0.0, 0.0))
    assert _camera_distance_fade((100.0, 0.0, 0.0)) is None


def test_exactly_at_cull_distance_returns_none():
    _note_camera_eye((0.0, 0.0, 0.0))
    assert _camera_distance_fade((DYN_LIGHT_CULL_GU, 0.0, 0.0)) is None


def test_band_midpoint_is_smoothstep_half():
    """Smoothstep is symmetric about its midpoint, so the exact centre of the
    band is 0.5 -- a value a plain linear ramp would also produce, which is
    why the monotonic-shape test below exists alongside this one."""
    _note_camera_eye((0.0, 0.0, 0.0))
    assert _camera_distance_fade((_MID_GU, 0.0, 0.0)) == pytest.approx(0.5)


def test_fade_decreases_monotonically_across_the_band():
    _note_camera_eye((0.0, 0.0, 0.0))
    span = DYN_LIGHT_CULL_GU - DYN_LIGHT_FADE_START_GU
    samples = [
        _camera_distance_fade((DYN_LIGHT_FADE_START_GU + span * f, 0.0, 0.0))
        for f in (0.0, 0.2, 0.4, 0.6, 0.8, 0.99)
    ]
    assert all(s is not None for s in samples)
    for earlier, later in zip(samples, samples[1:]):
        assert later < earlier


def test_fade_is_smoothstep_not_linear():
    """Pins the CURVE, not just the endpoints: at 25% into the band smoothstep
    gives 1 - (0.25^2 * (3 - 2*0.25)) = 0.84375, where a linear ramp gives
    0.75. Without this, a linear implementation passes every other test here."""
    _note_camera_eye((0.0, 0.0, 0.0))
    span = DYN_LIGHT_CULL_GU - DYN_LIGHT_FADE_START_GU
    got = _camera_distance_fade((DYN_LIGHT_FADE_START_GU + span * 0.25, 0.0, 0.0))
    assert got == pytest.approx(0.84375)


def test_distance_is_measured_in_three_dimensions():
    """A 3-4-5 triangle: a light 60 GU off in X and 80 in Y is 100 GU away, so
    it culls -- proving the gate uses the full vector length and not, say, the
    largest single axis (which would read 80 and keep it alive)."""
    _note_camera_eye((0.0, 0.0, 0.0))
    assert _camera_distance_fade((60.0, 80.0, 0.0)) is None


def test_distance_is_relative_to_the_camera_not_the_origin():
    """Camera parked far from the origin: a light sitting AT the origin is then
    beyond the cull radius, and one beside the camera is not. Catches an
    implementation that measures |light| instead of |light - eye|."""
    _note_camera_eye((1000.0, 0.0, 0.0))
    assert _camera_distance_fade((0.0, 0.0, 0.0)) is None
    assert _camera_distance_fade((1005.0, 0.0, 0.0)) == 1.0


def test_fade_band_sits_outside_weapons_range():
    """Design invariant, not an arithmetic restatement: a Galaxy's phasers are
    SetMaxDamageDistance(60.0) GU, so nothing may start dimming inside that
    envelope. Re-tuning the band down into weapons range must fail here."""
    assert DYN_LIGHT_FADE_START_GU > 60.0
    assert DYN_LIGHT_CULL_GU > DYN_LIGHT_FADE_START_GU


# ---------------------------------------------------------------------------
# Gate applied to the subsystem-emitter producer
# ---------------------------------------------------------------------------

def _point_prop(position=(0.0, 0.0, 0.0), intensity=2.0):
    p = SubsystemProperty("sub")
    p.SetLightEmitterKind(0, "point")
    p.SetLightEmitterPosition(0, *position)
    p.SetLightEmitterAxis(0, 0.0, -1.0, 0.0)
    p.SetLightEmitterLength(0, 0.0)
    p.SetLightEmitterRadius(0, 3.0)
    p.SetLightEmitterColor(0, 1.0, 0.5, 0.25)
    p.SetLightEmitterIntensity(0, intensity)
    return p


class _Sub:
    def __init__(self, prop):
        self._prop = prop

    def GetProperty(self):
        return self._prop

    def IsDestroyed(self):
        return False

    def IsDisabled(self):
        return False


class _Ship:
    def __init__(self, loc):
        self._loc = TGPoint3(*loc)
        self._rot = TGMatrix3()

    def GetWorldLocation(self):
        return self._loc

    def GetWorldRotation(self):
        return self._rot


def _emitter_lights_for_ship_at(loc, intensity=2.0):
    prop = _point_prop(intensity=intensity)
    sub = _Sub(prop)
    spec = light_emitters.baked_emitters(prop)[0]
    ship = _Ship(loc)
    return _build_emitter_light_render_data(
        {ship: 1}, {1: [(sub, False, False, 0.0, spec)]})


def test_emitter_lights_survive_inside_the_fade_band():
    _note_camera_eye((0.0, 0.0, 0.0))
    out = _emitter_lights_for_ship_at((20.0, 0.0, 0.0), intensity=2.0)
    assert len(out) == 1
    assert out[0]["intensity"] == pytest.approx(2.0)


def test_emitter_lights_dim_in_the_fade_band():
    _note_camera_eye((0.0, 0.0, 0.0))
    out = _emitter_lights_for_ship_at((_MID_GU, 0.0, 0.0), intensity=2.0)
    assert len(out) == 1
    assert out[0]["intensity"] == pytest.approx(1.0)   # 2.0 * smoothstep 0.5


def test_emitter_lights_dropped_beyond_the_cull_distance():
    _note_camera_eye((0.0, 0.0, 0.0))
    assert _emitter_lights_for_ship_at((100.0, 0.0, 0.0)) == []


def test_emitter_gate_is_per_ship_so_a_near_ship_is_unaffected():
    """One ship inside the band, one beyond it, in a single frame: the near
    ship keeps a full-intensity light and the far one contributes nothing.
    Catches a gate that culls the whole frame off the first ship it sees."""
    _note_camera_eye((0.0, 0.0, 0.0))
    near_prop, far_prop = _point_prop(intensity=2.0), _point_prop(intensity=2.0)
    near_spec = light_emitters.baked_emitters(near_prop)[0]
    far_spec = light_emitters.baked_emitters(far_prop)[0]
    near_ship, far_ship = _Ship((10.0, 0.0, 0.0)), _Ship((100.0, 0.0, 0.0))

    out = _build_emitter_light_render_data(
        {near_ship: 1, far_ship: 2},
        {1: [(_Sub(near_prop), False, False, 0.0, near_spec)],
         2: [(_Sub(far_prop), False, False, 0.0, far_spec)]})

    assert len(out) == 1
    assert out[0]["intensity"] == pytest.approx(2.0)


def test_emitter_lights_unaffected_when_no_camera_is_known():
    _note_camera_eye(None)
    out = _emitter_lights_for_ship_at((1e5, 0.0, 0.0), intensity=2.0)
    assert len(out) == 1
    assert out[0]["intensity"] == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# Gate applied to the torpedo producer
# ---------------------------------------------------------------------------

def _color(r, g, b, a=1.0):
    c = App.TGColorA()
    c.SetRGBA(r, g, b, a)
    return c


def _photon_at(position):
    t = Torpedo()
    t.CreateTorpedoModel(
        "data/Textures/Tactical/TorpedoCore.tga", _color(1.0, 0.99, 0.39), 0.2, 1.2,
        "data/Textures/Tactical/TorpedoGlow.tga", _color(1.0, 0.25, 0.0), 3.0, 0.3, 0.6,
        "data/Textures/Tactical/TorpedoFlares.tga", _color(1.0, 0.25, 0.0), 8, 0.7, 0.4,
    )
    t._position = App.TGPoint3(*position)
    register(t)
    return t


def test_torpedo_light_survives_inside_the_fade_band():
    _note_camera_eye((0.0, 0.0, 0.0))
    _photon_at((20.0, 0.0, 0.0))
    out = _build_dynamic_light_render_data()
    assert len(out) == 1
    assert out[0]["intensity"] == pytest.approx(_TORPEDO_LIGHT_INTENSITY)


def test_torpedo_light_dims_in_the_fade_band():
    _note_camera_eye((0.0, 0.0, 0.0))
    _photon_at((_MID_GU, 0.0, 0.0))
    out = _build_dynamic_light_render_data()
    assert len(out) == 1
    assert out[0]["intensity"] == pytest.approx(_TORPEDO_LIGHT_INTENSITY * 0.5)


def test_torpedo_light_dropped_beyond_the_cull_distance():
    _note_camera_eye((0.0, 0.0, 0.0))
    _photon_at((100.0, 0.0, 0.0))
    assert _build_dynamic_light_render_data() == []


def test_torpedo_light_unaffected_when_no_camera_is_known():
    _note_camera_eye(None)
    _photon_at((1e5, 0.0, 0.0))
    out = _build_dynamic_light_render_data()
    assert len(out) == 1
    assert out[0]["intensity"] == pytest.approx(_TORPEDO_LIGHT_INTENSITY)


# ---------------------------------------------------------------------------
# Mission-swap lifetime
# ---------------------------------------------------------------------------

def test_mission_swap_clears_the_cached_camera_eye():
    """The eye outlives the mission that produced it. The next mission's ships
    spawn wherever its sets put them, so carrying the old camera across the
    swap can cull their lights on the first frame — before the new camera
    solves. Clearing to None makes the gate inert until a real camera exists.

    Drives the REAL `_drain_pending_swap` rather than re-running its body, so
    deleting the reset line from the production block fails this test.
    """
    from engine.host_loop import HostController, MissionSession

    class _StubLoader:
        def load(self, name):
            return MissionSession(mission_name=name)

    class _FakeRenderer:
        def destroy_instance(self, iid):
            pass

    h = HostController()
    h.renderer = _FakeRenderer()
    h.loader = _StubLoader()
    h.session = MissionSession(mission_name="prev")

    _note_camera_eye((5000.0, 0.0, 0.0))
    assert _camera_distance_fade((0.0, 0.0, 0.0)) is None   # gate is live

    h.swap_mission("Next.Mission")
    h._drain_pending_swap()

    assert _camera_distance_fade((0.0, 0.0, 0.0)) == 1.0    # gate is inert
