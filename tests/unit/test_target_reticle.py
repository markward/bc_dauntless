import math
from engine.appc.math import TGPoint3, TGMatrix3
from engine.appc.subsystems import ShipSubsystem
from engine.ui.target_reticle import target_aim_point, build_target_reticle


class _Sub(ShipSubsystem):
    pass


def _ship(loc, rot, radius=5.0):
    class _Ship:
        def __init__(self):
            self._t = None
            self._sub = None
        def GetWorldLocation(self): return loc
        def GetWorldRotation(self): return rot
        def GetRadius(self): return radius
        def GetTarget(self): return self._t
        def GetTargetSubsystem(self): return self._sub
    return _Ship()


def _identity():
    R = TGMatrix3(); R.MakeIdentity(); return R


def test_aim_point_no_target_is_none():
    p = _ship(TGPoint3(0, 0, 0), _identity())
    assert target_aim_point(p) is None


def test_aim_point_target_no_subsystem_is_hull_centre():
    tgt = _ship(TGPoint3(200, 0, 0), _identity())
    p = _ship(TGPoint3(0, 0, 0), _identity()); p._t = tgt
    a = target_aim_point(p)
    assert (abs(a.x - 200) < 1e-6 and abs(a.y) < 1e-6 and abs(a.z) < 1e-6)


def test_aim_point_subsystem_uses_rotated_world_pos():
    R = TGMatrix3(); R.MakeZRotation(math.pi / 2.0)
    tgt = _ship(TGPoint3(200, 0, 0), R)
    sub = _Sub("Port Nacelle"); sub._position = TGPoint3(10, 0, 0)
    sub.SetParentShip(tgt)
    tgt._sub = sub
    p = _ship(TGPoint3(0, 0, 0), _identity()); p._t = tgt
    a = target_aim_point(p)
    # ship (200,0,0) + R·(10,0,0) = (200, 10, 0)
    assert abs(a.x - 200) < 1e-5 and abs(a.y - 10) < 1e-5 and abs(a.z) < 1e-5


def test_aim_point_destroyed_subsystem_falls_back_to_hull():
    tgt = _ship(TGPoint3(200, 0, 0), _identity())
    sub = _Sub("Port Nacelle"); sub._position = TGPoint3(10, 0, 0)
    sub.SetParentShip(tgt); sub.SetDestroyed(True)
    tgt._sub = sub
    p = _ship(TGPoint3(0, 0, 0), _identity()); p._t = tgt
    a = target_aim_point(p)
    assert abs(a.x - 200) < 1e-6 and abs(a.y) < 1e-6


def test_build_reticle_invisible_without_target():
    p = _ship(TGPoint3(0, 0, 0), _identity())
    r = build_target_reticle(p)
    assert r.visible is False


def test_build_reticle_box_only_when_no_subsystem():
    tgt = _ship(TGPoint3(200, 0, 0), _identity(), radius=7.0)
    p = _ship(TGPoint3(0, 0, 0), _identity()); p._t = tgt
    r = build_target_reticle(p)
    assert r.visible is True
    assert abs(r.ship_radius - 7.0) < 1e-6
    assert r.subtarget_pos is None


def test_build_reticle_ship_center_is_hull_not_subsystem():
    R = TGMatrix3(); R.MakeZRotation(math.pi / 2.0)
    tgt = _ship(TGPoint3(200, 0, 0), R, radius=6.0)
    sub = ShipSubsystem("Port Nacelle"); sub._position = TGPoint3(10, 0, 0)
    sub.SetParentShip(tgt); tgt._sub = sub
    p = _ship(TGPoint3(0, 0, 0), _identity()); p._t = tgt
    r = build_target_reticle(p)
    # ship_center stays at the hull centre…
    assert abs(r.ship_center[0] - 200) < 1e-6
    assert abs(r.ship_center[1] - 0) < 1e-6
    # …while the subtarget sits at the rotated subsystem mount (200,10,0).
    assert r.subtarget_pos is not None
    assert abs(r.subtarget_pos[0] - 200) < 1e-5
    assert abs(r.subtarget_pos[1] - 10) < 1e-5


def test_build_reticle_subtarget_agrees_with_aim_point():
    R = TGMatrix3(); R.MakeZRotation(math.pi / 2.0)
    tgt = _ship(TGPoint3(200, 0, 0), R)
    sub = _Sub("Port Nacelle"); sub._position = TGPoint3(10, 0, 0)
    sub.SetParentShip(tgt); tgt._sub = sub
    p = _ship(TGPoint3(0, 0, 0), _identity()); p._t = tgt
    r = build_target_reticle(p)
    a = target_aim_point(p)
    assert r.subtarget_pos is not None
    assert abs(r.subtarget_pos[0] - a.x) < 1e-9
    assert abs(r.subtarget_pos[1] - a.y) < 1e-9
    assert abs(r.subtarget_pos[2] - a.z) < 1e-9
