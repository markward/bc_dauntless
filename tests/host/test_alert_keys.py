"""Shift+1/2/3 → GREEN/YELLOW/RED alert on the player ship.

Mirrors BC's DefaultKeyboardBinding (WC_EXCLAMATION/WC_AT_SIGN/
WC_NUMBER_SIGN → ET_SET_ALERT_LEVEL with EST_ALERT_*), which
BridgeHandlers.SetAlertLevel forwards to the XO's menu — so the XO speaks,
the SDK plays the klaxon, and XOMenuHandlers posts the level to the ship.
With no bridge XO handling it, the key sets the level directly. The shift
modifier disambiguates from the impulse-throttle keys (KEY_1..9), which
share digit codes — holding Shift while pressing a digit must NOT bump the
throttle.
"""
import App
import pytest
import Bridge.XOMenuHandlers  # noqa: F401 -- handler lookup reads sys.modules
from engine.appc.sets import SetClass
from engine.appc.ships import ShipClass, apply_pending_alert_levels
from engine.core.game import Game, _set_current_game
from engine.host_loop import _PlayerControl, _apply_alert_keys


@pytest.fixture(autouse=True)
def _no_bridge_set():
    """g_kSetManager is not reset between tests: park any leaked "bridge"
    set so the no-XO cases really have no XO, and restore it after."""
    mgr = App.g_kSetManager
    saved = mgr.GetSet("bridge")
    if saved is not None:
        mgr.DeleteSet("bridge")
    yield
    if mgr.GetSet("bridge") is not None:
        mgr.DeleteSet("bridge")
    if saved is not None:
        mgr.AddSet(saved, "bridge")


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
    ship.SetAlertLevel(ShipClass.GREEN_ALERT)
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


_XO_SAW = []


def _record_xo_alert(pMenu, pEvent):
    _XO_SAW.append(pEvent.GetInt())
    pMenu.CallNextHandler(pEvent)


def _bridge_xo_and_player():
    """A bridge set whose XO holds a menu wired like XOMenuHandlers.CreateMenus
    (plus a recorder, newest, standing in for XOCharacterHandlers), and the
    current game's player.

    The player is assigned BEFORE the bridge exists: Game.SetPlayer attaches
    the real bridge officers (bridge_officers.configure_for_player), and
    Saffi's AttachMenuToXO would stack XOCharacterHandlers above the
    recorder that stands in for it here."""
    player = _FakeShip()
    game = Game()
    game.SetPlayer(player)
    _set_current_game(game)

    menu = App.STTopLevelMenu_CreateW("Commander")
    menu.AddPythonFuncHandlerForInstance(App.ET_SET_ALERT_LEVEL,
                                         "Bridge.XOMenuHandlers.SetAlertLevel")
    menu.AddPythonFuncHandlerForInstance(App.ET_SET_ALERT_LEVEL,
                                         __name__ + "._record_xo_alert")
    xo = App.CharacterClass_Create("b.nif", "h.nif")
    xo.SetMenu(menu)
    bridge = SetClass()
    bridge.AddObjectToSet(xo, "XO")
    App.g_kSetManager.AddSet(bridge, "bridge")

    player.SetAlertLevel(ShipClass.GREEN_ALERT)
    return player


def test_shift_plus_3_goes_through_the_xo_menu():
    """BC's binding: the XO's menu gets EST_ALERT_RED (her line, the SDK's
    klaxon), and XOMenuHandlers' post to the ship sets the level."""
    _XO_SAW.clear()
    player = _bridge_xo_and_player()
    reader = _FakeKeyReader()
    reader.held.add(reader.keys.KEY_LEFT_SHIFT)
    reader.pressed_once.add(reader.keys.KEY_3)

    _apply_alert_keys(reader, player)
    apply_pending_alert_levels()            # the next GameLoop tick

    assert _XO_SAW == [App.CharacterClass.EST_ALERT_RED]
    assert player.GetAlertLevel() == ShipClass.RED_ALERT


def test_shift_plus_1_through_the_xo_menu_sets_green():
    _XO_SAW.clear()
    player = _bridge_xo_and_player()
    player.SetAlertLevel(ShipClass.RED_ALERT)
    reader = _FakeKeyReader()
    reader.held.add(reader.keys.KEY_LEFT_SHIFT)
    reader.pressed_once.add(reader.keys.KEY_1)

    _apply_alert_keys(reader, player)
    apply_pending_alert_levels()            # the next GameLoop tick

    assert _XO_SAW == [App.CharacterClass.EST_ALERT_GREEN]
    assert player.GetAlertLevel() == ShipClass.GREEN_ALERT


def test_an_xo_menu_with_no_alert_handler_falls_back_to_direct():
    """A bare XO menu (no XOMenuHandlers) would swallow the event; the key
    must still change the alert."""
    xo = App.CharacterClass_Create("b.nif", "h.nif")
    xo.SetMenu(App.STTopLevelMenu_CreateW("Commander"))
    bridge = SetClass()
    bridge.AddObjectToSet(xo, "XO")
    App.g_kSetManager.AddSet(bridge, "bridge")
    ship = _FakeShip()
    ship.SetAlertLevel(ShipClass.GREEN_ALERT)
    reader = _FakeKeyReader()
    reader.held.add(reader.keys.KEY_LEFT_SHIFT)
    reader.pressed_once.add(reader.keys.KEY_3)

    _apply_alert_keys(reader, ship)

    assert ship.GetAlertLevel() == ShipClass.RED_ALERT


def test_alert_keys_respect_the_keyboard_lockout():
    """RemoveControl (TopWindow.AllowKeyboardInput(0)) blocks BC's alert
    binding like every non-crew-menu key (engine/appc/input.py)."""
    top = App.TopWindow_GetTopWindow()
    ship = _FakeShip()
    ship.SetAlertLevel(ShipClass.GREEN_ALERT)
    reader = _FakeKeyReader()
    reader.held.add(reader.keys.KEY_LEFT_SHIFT)
    reader.pressed_once.add(reader.keys.KEY_3)
    top.AllowKeyboardInput(0)
    try:
        _apply_alert_keys(reader, ship)
    finally:
        top.AllowKeyboardInput(1)

    assert ship.GetAlertLevel() == ShipClass.GREEN_ALERT


def _raise(pMenu, pEvent):
    raise AttributeError("'NoneType' object has no attribute 'IsOn'")


def test_a_raising_xo_handler_does_not_escape_the_key_press():
    """XOCharacterHandlers.SetAlertLevel calls pShields.IsOn() unguarded; a
    shieldless player ship raises there. A button click swallows and logs it
    (SendActivationEvent); the key press must too, not kill the host loop."""
    menu = App.STTopLevelMenu_CreateW("Commander")
    menu.AddPythonFuncHandlerForInstance(App.ET_SET_ALERT_LEVEL,
                                         __name__ + "._raise")
    xo = App.CharacterClass_Create("b.nif", "h.nif")
    xo.SetMenu(menu)
    bridge = SetClass()
    bridge.AddObjectToSet(xo, "XO")
    App.g_kSetManager.AddSet(bridge, "bridge")
    reader = _FakeKeyReader()
    reader.held.add(reader.keys.KEY_LEFT_SHIFT)
    reader.pressed_once.add(reader.keys.KEY_3)

    _apply_alert_keys(reader, _FakeShip())            # must not raise
