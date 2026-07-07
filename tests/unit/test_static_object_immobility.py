import App
import pytest
from engine.appc.math import TGPoint3
from engine.appc.ships import ShipClass


def _reset_app_state():
    App.g_kSetManager._sets.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def test_isimmobile_false_by_default():
    assert ShipClass().IsImmobile() is False


def test_isimmobile_true_when_static():
    s = ShipClass()
    s.SetStatic(True)
    assert s.IsImmobile() is True


def test_isimmobile_true_when_stationary():
    s = ShipClass()
    s.SetStationary(1)
    assert s.IsImmobile() is True


def test_isimmobile_true_when_both():
    s = ShipClass()
    s.SetStatic(True)
    s.SetStationary(1)
    assert s.IsImmobile() is True


def test_isimmobile_reverts_when_static_cleared():
    s = ShipClass()
    s.SetStatic(True)
    s.SetStatic(False)
    assert s.IsImmobile() is False


from engine.appc.objects import PhysicsObjectClass
from engine.appc.ship_motion import _step_ship_motion


def _rot_cols(ship):
    R = ship.GetWorldRotation()
    return [(R.GetCol(i).x, R.GetCol(i).y, R.GetCol(i).z) for i in range(3)]


def test_immobile_ship_does_not_translate_despite_speed_setpoint():
    s = ShipClass()
    s.SetStatic(True)
    s.SetTranslateXYZ(10.0, 20.0, 30.0)
    # A non-zero linear setpoint that would move a mobile ship.
    s.SetSpeed(50.0, TGPoint3(0.0, 1.0, 0.0),
               PhysicsObjectClass.DIRECTION_MODEL_SPACE)
    _step_ship_motion(s, 1.0)
    p = s.GetTranslate()
    assert (p.x, p.y, p.z) == pytest.approx((10.0, 20.0, 30.0))


def test_immobile_ship_does_not_rotate_despite_angular_setpoint():
    s = ShipClass()
    s.SetStationary(1)
    before = _rot_cols(s)
    # A non-zero angular-velocity setpoint that would spin a mobile ship.
    s.SetTargetAngularVelocityDirect(TGPoint3(0.0, 1.0, 0.0))
    _step_ship_motion(s, 1.0)
    assert _rot_cols(s) == pytest.approx(before)


def test_mobile_ship_still_moves_control():
    # Guard: the early-return must not affect ordinary ships.
    s = ShipClass()
    s.SetTranslateXYZ(0.0, 0.0, 0.0)
    s.SetSpeed(50.0, TGPoint3(0.0, 1.0, 0.0),
               PhysicsObjectClass.DIRECTION_MODEL_SPACE)
    _step_ship_motion(s, 1.0)
    p = s.GetTranslate()
    assert (p.x, p.y, p.z) != pytest.approx((0.0, 0.0, 0.0))
