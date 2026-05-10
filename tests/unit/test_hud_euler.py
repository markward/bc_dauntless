import math
import pytest
from engine.appc.math import TGMatrix3
from engine.host_loop import _extract_ypr


def test_identity_gives_zero():
    R = TGMatrix3()
    yaw, pitch, roll = _extract_ypr(R)
    assert yaw   == pytest.approx(0.0, abs=1e-4)
    assert pitch == pytest.approx(0.0, abs=1e-4)
    assert roll  == pytest.approx(0.0, abs=1e-4)


def test_pure_yaw_90():
    """MakeZRotation(90 deg): forward swings to +X."""
    R = TGMatrix3()
    R.MakeZRotation(math.radians(90))
    yaw, pitch, roll = _extract_ypr(R)
    assert yaw   == pytest.approx(90.0, abs=0.1)
    assert pitch == pytest.approx(0.0,  abs=0.1)
    assert roll  == pytest.approx(0.0,  abs=0.1)


def test_pure_pitch_up_45():
    """MakeXRotation(-45 deg): nose up 45 deg in BC convention (+X = nose down)."""
    R = TGMatrix3()
    R.MakeXRotation(math.radians(-45))
    yaw, pitch, roll = _extract_ypr(R)
    assert yaw   == pytest.approx(0.0,  abs=0.1)
    assert pitch == pytest.approx(45.0, abs=0.1)
    assert roll  == pytest.approx(0.0,  abs=0.1)


def test_pure_roll_right_60():
    """MakeYRotation(-60 deg): roll right 60 deg in BC convention (+Y = roll left)."""
    R = TGMatrix3()
    R.MakeYRotation(math.radians(-60))
    yaw, pitch, roll = _extract_ypr(R)
    assert yaw   == pytest.approx(0.0,  abs=0.1)
    assert pitch == pytest.approx(0.0,  abs=0.1)
    assert roll  == pytest.approx(60.0, abs=0.1)


def test_yaw_negative():
    R = TGMatrix3()
    R.MakeZRotation(math.radians(-45))
    yaw, pitch, roll = _extract_ypr(R)
    assert yaw   == pytest.approx(-45.0, abs=0.1)
    assert pitch == pytest.approx(0.0,   abs=0.1)
    assert roll  == pytest.approx(0.0,   abs=0.1)
