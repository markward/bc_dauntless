import math
from engine.appc.math import TGPoint3, TGMatrix3
from engine.appc.subsystems import ShipSubsystem
from engine.ui.reticle_text import build_reticle_text, _ReticleCam


def _identity():
    R = TGMatrix3(); R.MakeIdentity(); return R


def _ship(loc, vel=(0.0, 0.0, 0.0), name="Target", radius=5.0):
    class _Ship:
        def __init__(self):
            self._t = None; self._sub = None
        def GetWorldLocation(self): return loc
        def GetWorldRotation(self): return _identity()
        def GetRadius(self): return radius
        def GetVelocity(self, space=0): return TGPoint3(*vel)
        def GetName(self): return name
        def GetTarget(self): return self._t
        def GetTargetSubsystem(self): return self._sub
    return _Ship()


def _cam_facing_target():
    # Eye at (0,-50,0) looking down +Y; a target at +Y is on-screen.
    return _ReticleCam(eye=(0.0, -50.0, 0.0), target=(0.0, 0.0, 0.0),
                       up=(0.0, 0.0, 1.0), fov_y_rad=math.radians(60.0),
                       near=1.0, far=5000.0)


def test_text_hidden_without_target():
    p = _ship(TGPoint3(0, 0, 0))
    out = build_reticle_text(p, _cam_facing_target(), (1280, 720))
    assert out["visible"] is False


def test_text_name_and_line2_from_ship():
    # Target 205 GU ahead with radius 5 → surface distance 200 GU (BC's
    # readout is to the bounding sphere). 200*0.175 = 35.00 km; 1*630 = 630 kph.
    tgt = _ship(TGPoint3(0, 0, 0), vel=(1.0, 0.0, 0.0), name="Warbird")
    p = _ship(TGPoint3(0, -205, 0)); p._t = tgt
    out = build_reticle_text(p, _cam_facing_target(), (1280, 720))
    assert out["visible"] is True
    assert out["name"] == "Warbird"
    assert out["line2"] == "35.00 km / 630 kph"
    assert 0 <= out["name_xy"][0] <= 1280 and 0 <= out["name_xy"][1] <= 720


def test_range_is_surface_distance_for_planet():
    """BC's readout convention, confirmed live: orbiting Haven (radius
    90 GU) at the authored radius+150 GU CircleObject band, the original
    game reads ~25 km — the SURFACE distance (150 GU = 26.25 km), while a
    centre-distance readout would claim 42 km."""
    haven = _ship(TGPoint3(0, 0, 0), name="Haven", radius=90.0)
    p = _ship(TGPoint3(0, -240, 0)); p._t = haven   # orbit: 240 GU centres
    out = build_reticle_text(p, _cam_facing_target(), (1280, 720))
    assert out["line2"].startswith("26.25 km")


def test_text_name_is_subsystem_when_locked():
    tgt = _ship(TGPoint3(0, 0, 0), name="Warbird")
    sub = ShipSubsystem("Port Nacelle"); sub.SetParentShip(tgt)
    p = _ship(TGPoint3(0, -200, 0)); p._t = tgt; p._sub = sub
    out = build_reticle_text(p, _cam_facing_target(), (1280, 720))
    assert out["name"] == "Port Nacelle"


def test_text_hidden_when_target_behind_camera():
    tgt = _ship(TGPoint3(0, -500, 0), name="Warbird")
    p = _ship(TGPoint3(0, -400, 0)); p._t = tgt
    cam = _ReticleCam(eye=(0.0, 0.0, 0.0), target=(0.0, 100.0, 0.0),
                      up=(0.0, 0.0, 1.0), fov_y_rad=math.radians(60.0),
                      near=1.0, far=5000.0)
    out = build_reticle_text(p, cam, (1280, 720))
    assert out["visible"] is False
