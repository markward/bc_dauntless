"""F1-F5 reach the SDK input pipeline: KeyConfig registers WC_F1..F5 with
real codes, DefaultKeyboardBinding binds them to ET_INPUT_TALK_TO_*, and
OnKeyDown(WC_F1) lands an ET_INPUT_TALK_TO_HELM event at the TCW.
Spec: docs/superpowers/specs/2026-06-12-bridge-menu-hotkeys-design.md
"""
import App
from engine.appc.windows import TacticalControlWindow

STOCK_MAP = {
    "WC_F1": "ET_INPUT_TALK_TO_HELM",
    "WC_F2": "ET_INPUT_TALK_TO_TACTICAL",
    "WC_F3": "ET_INPUT_TALK_TO_XO",
    "WC_F4": "ET_INPUT_TALK_TO_SCIENCE",
    "WC_F5": "ET_INPUT_TALK_TO_ENGINEERING",
}


def test_fkey_constants_are_real_distinct_ints():
    wc = [getattr(App, f"WC_F{n}") for n in range(1, 6)]
    ky = [getattr(App, f"KY_F{n}") for n in range(1, 6)]
    assert all(type(v) is int for v in wc + ky)
    assert len(set(wc)) == 5
    # No collision with the mouse-button codes.
    assert not set(wc) & {App.WC_LBUTTON, App.WC_RBUTTON, App.WC_MBUTTON}


_received = []


def _record(dest, event):
    _received.append(event.GetEventType())


def test_f1_keydown_reaches_tcw_through_sdk_pipeline():
    _received.clear()
    TacticalControlWindow._instance = None
    tcw = TacticalControlWindow.GetInstance()
    App.g_kKeyboardBinding.SetDefaultDestination(tcw)
    tcw.AddPythonFuncHandlerForInstance(
        App.ET_INPUT_TALK_TO_HELM, __name__ + "._record")

    import KeyConfig
    KeyConfig.MapScancodes()
    import DefaultKeyboardBinding
    DefaultKeyboardBinding.Initialize()

    App.g_kInputManager.OnKeyDown(App.WC_F1)
    assert App.ET_INPUT_TALK_TO_HELM in _received


def test_stock_mapping_bound_for_all_five():
    import KeyConfig, DefaultKeyboardBinding
    KeyConfig.MapScancodes()
    DefaultKeyboardBinding.Initialize()
    from engine.appc.input import KS_KEYDOWN
    for wc_name, et_name in STOCK_MAP.items():
        key = (getattr(App, wc_name), KS_KEYDOWN)
        binding = App.g_kKeyboardBinding._bindings.get(key)
        assert binding is not None, wc_name
        assert binding[0] == getattr(App, et_name), wc_name
