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
