"""Weapon-fire keys F/X/G reach the SDK input pipeline end-to-end.

KeyConfig registers WC_F/WC_X/WC_G with real distinct codes, DefaultKeyboard-
Binding binds them to ET_INPUT_FIRE_PRIMARY/SECONDARY/TERTIARY, and
OnKeyDown(WC_*) lands the matching fire event at the TCW.

Regression guard: before the fix, App.WC_F/WC_X/WC_G resolved to App._NamedStub
(int()==0), so KeyConfig registration and all three fire bindings collapsed
onto key 0 (last-write-wins) and keyboard fire was dead.  G (tertiary) drives
the Klingon Bird of Prey's disruptors.
"""
import App
from engine.appc.windows import TacticalControlWindow

STOCK_MAP = {
    "WC_F": "ET_INPUT_FIRE_PRIMARY",     # phasers
    "WC_X": "ET_INPUT_FIRE_SECONDARY",   # torpedoes
    "WC_G": "ET_INPUT_FIRE_TERTIARY",    # disruptors / pulse weapons
}


def test_fire_key_constants_are_real_distinct_ints():
    wc = [App.WC_F, App.WC_X, App.WC_G]
    ky = [App.KY_F, App.KY_X, App.KY_G]
    assert all(type(v) is int and v != 0 for v in wc + ky)
    assert len(set(wc)) == 3
    # No collision with mouse buttons or the F1-F5 function keys.
    others = {App.WC_LBUTTON, App.WC_RBUTTON, App.WC_MBUTTON,
              App.WC_F1, App.WC_F2, App.WC_F3, App.WC_F4, App.WC_F5}
    assert not set(wc) & others


_received = []


def _record(dest, event):
    _received.append(event.GetEventType())


def setup_function(_):
    # Re-register the ET_KEYBOARD_EVENT → KeyboardBinding handler that
    # _fresh_world() may have cleared (same call App.py makes at startup).
    from engine.appc.input import register_input_handlers
    register_input_handlers(App.g_kEventManager)


def teardown_function(_):
    TacticalControlWindow._instance = None
    _received.clear()


def test_g_keydown_reaches_tcw_as_fire_tertiary():
    """The disruptor path: pressing G lands ET_INPUT_FIRE_TERTIARY at the TCW."""
    _received.clear()
    TacticalControlWindow._instance = None
    tcw = TacticalControlWindow.GetInstance()
    App.g_kKeyboardBinding.SetDefaultDestination(tcw)
    tcw.AddPythonFuncHandlerForInstance(
        App.ET_INPUT_FIRE_TERTIARY, __name__ + "._record")

    import KeyConfig
    KeyConfig.MapScancodes()
    import DefaultKeyboardBinding
    DefaultKeyboardBinding.Initialize()

    App.g_kInputManager.OnKeyDown(App.WC_G)
    assert App.ET_INPUT_FIRE_TERTIARY in _received


def test_stock_fire_mapping_bound_for_all_three():
    import KeyConfig, DefaultKeyboardBinding
    KeyConfig.MapScancodes()
    DefaultKeyboardBinding.Initialize()
    from engine.appc.input import KS_KEYDOWN
    for wc_name, et_name in STOCK_MAP.items():
        key = (getattr(App, wc_name), KS_KEYDOWN)
        binding = App.g_kKeyboardBinding._bindings.get(key)
        assert binding is not None, wc_name
        assert binding[0] == getattr(App, et_name), wc_name
