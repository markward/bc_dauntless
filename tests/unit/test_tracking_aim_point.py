import math
from engine.appc.math import TGPoint3, TGMatrix3
from engine.cameras.tracking import _TrackingCamera


class _Obj:
    def __init__(self, loc, rot):
        self._loc, self._rot = loc, rot
    def GetWorldLocation(self): return self._loc
    def GetWorldRotation(self): return self._rot


def _identity():
    R = TGMatrix3(); R.MakeIdentity(); return R


def test_aim_point_overrides_target_world_location():
    cam = _TrackingCamera()
    cam.set_ship_radius(5.0)
    player = _Obj(TGPoint3(0, 0, 0), _identity())
    target = _Obj(TGPoint3(200, 0, 0), _identity())
    aim = TGPoint3(200, 10, 0)   # an off-centre subsystem on the target

    # dt=None → solver geometry only (deterministic, no springs).
    eye_h, look_h, up_h = cam.compute(player=player, target=target, dt=None)
    eye_a, look_a, up_a = cam.compute(player=player, target=target, dt=None,
                                      aim_point=aim)
    # The forward direction must shift toward the aim point's +Y
    # (it did not before).  forward = look_at − eye.
    fwd_h_y = look_h[1] - eye_h[1]
    fwd_a_y = look_a[1] - eye_a[1]
    assert fwd_a_y > fwd_h_y + 0.01
