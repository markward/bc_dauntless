"""Shift+1/2/3 → SetAlertLevel(GREEN/YELLOW/RED) on the player ship.

Mirrors BC's DefaultKeyboardBinding (WC_EXCLAMATION/WC_AT_SIGN/
WC_NUMBER_SIGN → ET_SET_ALERT_LEVEL). The shift modifier disambiguates
from the impulse-throttle keys (KEY_1..9), which share digit codes —
holding Shift while pressing a digit must NOT bump the throttle.
"""
from engine.appc.ships import ShipClass
from engine.host_loop import _PlayerControl, _apply_alert_keys


class _FakeKeys:
    KEY_W = 1; KEY_S = 2; KEY_A = 3; KEY_D = 4
    KEY_Q = 5; KEY_E = 6; KEY_R = 7
    KEY_0 = 10; KEY_1 = 11; KEY_2 = 12; KEY_3 = 13
    KEY_4 = 14; KEY_5 = 15; KEY_6 = 16; KEY_7 = 17; KEY_8 = 18; KEY_9 = 19
    KEY_LEFT_SHIFT = 30
    KEY_RIGHT_SHIFT = 31


class _FakeKeyReader:
    keys = _FakeKeys()

    def __init__(self):
        self.held = set()
        self.pressed_once = set()

    def key_state(self, key):
        return key in self.held

    def key_pressed(self, key):
        if key in self.pressed_once:
            self.pressed_once.discard(key)
            return True
        return False


class _FakePoint:
    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x, self.y, self.z = float(x), float(y), float(z)


class _FakeShip(ShipClass):
    def __init__(self):
        super().__init__()
        self._pos = _FakePoint(0.0, 0.0, 0.0)
        from engine.appc.math import TGMatrix3
        self._rot = TGMatrix3()

    def GetTranslate(self):
        return _FakePoint(self._pos.x, self._pos.y, self._pos.z)

    def SetTranslateXYZ(self, x, y, z):
        self._pos = _FakePoint(x, y, z)

    def GetWorldRotation(self):
        from engine.appc.math import TGMatrix3
        out = TGMatrix3()
        out.set_from_tuple(self._rot.as_tuple())
        return out

    def SetMatrixRotation(self, mat):
        self._rot = mat


def test_shift_plus_1_sets_green_alert():
    ship = _FakeShip()
    ship.SetAlertLevel(ShipClass.RED_ALERT)
    reader = _FakeKeyReader()
    reader.held.add(reader.keys.KEY_LEFT_SHIFT)
    reader.pressed_once.add(reader.keys.KEY_1)
    _apply_alert_keys(reader, ship)
    assert ship.GetAlertLevel() == ShipClass.GREEN_ALERT


def test_shift_plus_2_sets_yellow_alert():
    ship = _FakeShip()
    reader = _FakeKeyReader()
    reader.held.add(reader.keys.KEY_LEFT_SHIFT)
    reader.pressed_once.add(reader.keys.KEY_2)
    _apply_alert_keys(reader, ship)
    assert ship.GetAlertLevel() == ShipClass.YELLOW_ALERT


def test_shift_plus_3_sets_red_alert():
    ship = _FakeShip()
    reader = _FakeKeyReader()
    reader.held.add(reader.keys.KEY_LEFT_SHIFT)
    reader.pressed_once.add(reader.keys.KEY_3)
    _apply_alert_keys(reader, ship)
    assert ship.GetAlertLevel() == ShipClass.RED_ALERT


def test_right_shift_also_works():
    ship = _FakeShip()
    reader = _FakeKeyReader()
    reader.held.add(reader.keys.KEY_RIGHT_SHIFT)
    reader.pressed_once.add(reader.keys.KEY_2)
    _apply_alert_keys(reader, ship)
    assert ship.GetAlertLevel() == ShipClass.YELLOW_ALERT


def test_digit_without_shift_does_not_change_alert():
    ship = _FakeShip()
    ship.SetAlertLevel(ShipClass.YELLOW_ALERT)
    reader = _FakeKeyReader()
    # No shift held.
    reader.pressed_once.add(reader.keys.KEY_1)
    _apply_alert_keys(reader, ship)
    assert ship.GetAlertLevel() == ShipClass.YELLOW_ALERT


def test_shift_held_alone_does_not_change_alert():
    ship = _FakeShip()
    reader = _FakeKeyReader()
    reader.held.add(reader.keys.KEY_LEFT_SHIFT)
    _apply_alert_keys(reader, ship)
    assert ship.GetAlertLevel() == ShipClass.GREEN_ALERT


def test_shift_digit_does_not_bump_throttle():
    """Holding Shift while pressing 5 must NOT set impulse to level 5 —
    the digit is consumed by the alert handler instead."""
    pc = _PlayerControl()
    ship = _FakeShip()
    reader = _FakeKeyReader()
    reader.held.add(reader.keys.KEY_LEFT_SHIFT)
    reader.pressed_once.add(reader.keys.KEY_5)
    pc.apply(ship, dt=1.0/60, h=reader)
    assert pc.impulse_level == 0


def test_plain_digit_still_bumps_throttle():
    """Sanity: without shift, the existing throttle binding still works."""
    pc = _PlayerControl()
    ship = _FakeShip()
    reader = _FakeKeyReader()
    reader.pressed_once.add(reader.keys.KEY_5)
    pc.apply(ship, dt=1.0/60, h=reader)
    assert pc.impulse_level == 5
