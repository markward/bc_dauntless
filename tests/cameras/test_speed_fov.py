"""Speed-linked FOV: the exterior FOV widens with the player's speed, +4 deg
at 4000 kph and above, linearly below. Additive on the user's FOV setting and
never written back to the persisted base."""
import inspect
import math
import re

import pytest

from engine.units import GUPS_TO_KPH


def _gups(kph: float) -> float:
    return kph / GUPS_TO_KPH


def test_speed_fov_boost_is_linear_to_four_degrees_at_4000_kph():
    from engine.cameras import speed_fov_boost_rad, SPEED_FOV_BOOST_DEG, SPEED_FOV_FULL_KPH
    assert (SPEED_FOV_BOOST_DEG, SPEED_FOV_FULL_KPH) == (4.0, 4000.0)
    assert speed_fov_boost_rad(0.0) == 0.0
    assert speed_fov_boost_rad(_gups(2000.0)) == pytest.approx(math.radians(2.0))
    assert speed_fov_boost_rad(_gups(4000.0)) == pytest.approx(math.radians(4.0))


def test_speed_fov_boost_clamps_at_full_speed_either_way():
    from engine.cameras import speed_fov_boost_rad
    assert speed_fov_boost_rad(_gups(12000.0)) == pytest.approx(math.radians(4.0))    # warp
    assert speed_fov_boost_rad(_gups(-12000.0)) == pytest.approx(math.radians(-4.0))


def test_speed_fov_boost_is_signed_so_reversing_narrows():
    """The argument is the FORWARD speed (velocity . ship-forward), not
    |velocity|: astern motion narrows the FOV on the same curve."""
    from engine.cameras import speed_fov_boost_rad
    assert speed_fov_boost_rad(_gups(-2000.0)) == pytest.approx(math.radians(-2.0))
    assert speed_fov_boost_rad(_gups(-4000.0)) == pytest.approx(math.radians(-4.0))


def test_director_set_speed_widens_the_effective_fov_not_the_base():
    from engine.cameras.director import _CameraDirector
    d = _CameraDirector()
    base = d.fov_y_rad
    d.set_speed(_gups(4000.0))
    assert d.fov_y_rad == base                                   # persisted setting untouched
    assert d.effective_fov_y_rad == pytest.approx(base + math.radians(4.0))
    d.set_speed(0.0)
    assert d.effective_fov_y_rad == pytest.approx(base)


def test_director_speed_boost_reaches_the_tracking_projection_but_not_the_distance_scale():
    """Tracking frames by screen fraction, so its v_fov_rad must be the FOV
    actually rendered. The FOV distance compensation stays keyed to the
    BASE FOV: compensating the speed widening away would dolly the camera
    in at speed and cancel the cue."""
    from engine.cameras.director import _CameraDirector
    from engine.cameras import fov_distance_scale
    d = _CameraDirector()
    d.set_fov(math.radians(45.0))
    d.set_speed(_gups(4000.0))
    assert d.tracking.v_fov_rad == pytest.approx(math.radians(49.0))
    assert d.chase.fov_scale    == pytest.approx(fov_distance_scale(math.radians(45.0)))
    assert d.tracking.fov_scale == pytest.approx(fov_distance_scale(math.radians(45.0)))


def test_director_set_fov_keeps_the_current_speed_boost():
    from engine.cameras.director import _CameraDirector
    d = _CameraDirector()
    d.set_speed(_gups(2000.0))
    d.set_fov(math.radians(40.0))
    assert d.effective_fov_y_rad == pytest.approx(math.radians(42.0))
    assert d.tracking.v_fov_rad  == pytest.approx(math.radians(42.0))


class _View:
    def __init__(self, bridge): self.is_bridge = bridge; self.is_exterior = not bridge


class _Player:
    def __init__(self, vel):
        from engine.appc.math import TGPoint3, TGMatrix3
        self._vel = TGPoint3(*vel)
        self._loc = TGPoint3(0.0, 0.0, 0.0)
        self._rot = TGMatrix3()
    def GetWorldLocation(self): return self._loc
    def GetWorldRotation(self): return self._rot
    def GetVelocityTG(self):    return self._vel
    def GetRadius(self):        return 1.0
    def GetTarget(self):        return None


@pytest.mark.parametrize("bridge", [False, True])
def test_compute_camera_feeds_the_players_speed_to_the_director(bridge):
    """Both view modes: the boost must track speed even while on the bridge
    so switching to the exterior view does not start from a stale value."""
    from engine import host_loop
    from engine.cameras.director import _CameraDirector
    d = _CameraDirector()
    v = _gups(4000.0)
    host_loop._compute_camera(_View(bridge), d, player=_Player((0.0, v, 0.0)), dt=None)
    assert d.effective_fov_y_rad == pytest.approx(d.fov_y_rad + math.radians(4.0))


def test_compute_camera_feeds_the_forward_component_so_reverse_narrows():
    """Identity rotation: ship-forward is +Y. Full impulse ASTERN must
    narrow, not widen — |velocity| cannot tell the two apart."""
    from engine import host_loop
    from engine.cameras.director import _CameraDirector
    d = _CameraDirector()
    v = _gups(4000.0)
    host_loop._compute_camera(_View(False), d, player=_Player((0.0, -v, 0.0)), dt=None)
    assert d.effective_fov_y_rad == pytest.approx(d.fov_y_rad - math.radians(4.0))


def test_compute_camera_ignores_sideways_drift():
    """Only the along-forward component counts; a pure lateral slide (a
    tractor tow, a collision shove) is not 'going fast'."""
    from engine import host_loop
    from engine.cameras.director import _CameraDirector
    d = _CameraDirector()
    v = _gups(4000.0)
    host_loop._compute_camera(_View(False), d, player=_Player((v, 0.0, 0.0)), dt=None)
    assert d.effective_fov_y_rad == pytest.approx(d.fov_y_rad)


def test_exterior_render_and_unproject_paths_use_the_effective_fov():
    """Source guard (the frame body is not unit-testable): the exterior
    r.set_camera, the manual-aim camera note and the reticle projection
    must all read director.effective_fov_y_rad, or the drawn frame and the
    cursor/reticle math disagree by up to 4 deg at speed."""
    src = re.sub(r"\s+", " ", inspect.getsource(__import__("engine.host_loop").host_loop.run))
    assert "r.set_camera(eye=eye, target=target, up=up_vec, fov_y_rad=director.effective_fov_y_rad" in src
    assert "manual_aim.note_camera(eye, target, up_vec, director.effective_fov_y_rad" in src
    assert "_ReticleCam(eye=eye, target=target, up=up_vec, fov_y_rad=director.effective_fov_y_rad" in src
