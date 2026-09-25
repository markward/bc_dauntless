"""ET_WARP_BUTTON_PRESSED runs the button's handler chain, newest first, and
ends in the engine step that replaces SDK WarpPressed (spec §1)."""
import sys, types
import App
from engine.appc import warp_button
from engine.appc.tg_ui.st_widgets import STWarpButton

calls = []


def _mod(name, **fns):
    m = types.ModuleType(name)
    for k, v in fns.items():
        setattr(m, k, v)
    sys.modules[name] = m
    return m


def setup_function(_):
    calls.clear()
    warp_button._engage_override = lambda b: calls.append(("engine", b))


def teardown_function(_):
    warp_button._engage_override = None
    for n in ("_t_old", "_t_new", "Bridge.HelmMenuHandlers"):
        sys.modules.pop(n, None)


def _button():
    b = STWarpButton("Warp")
    b.set_player_destination("Systems.Vesuvi.Vesuvi4")
    return b


def test_handlers_run_newest_first_then_the_engine_step():
    _mod("_t_old", H=lambda o, e: (calls.append("old"), o.CallNextHandler(e)))
    _mod("_t_new", H=lambda o, e: (calls.append("new"), o.CallNextHandler(e)))
    b = _button()
    b.AddPythonFuncHandlerForInstance(App.ET_WARP_BUTTON_PRESSED, "_t_old.H")
    b.AddPythonFuncHandlerForInstance(App.ET_WARP_BUTTON_PRESSED, "_t_new.H")
    warp_button.press(b)
    assert calls == ["new", "old", ("engine", b)]


def test_a_swallowing_handler_stops_the_warp():
    _mod("_t_new", H=lambda o, e: calls.append("refused"))
    b = _button()
    b.AddPythonFuncHandlerForInstance(App.ET_WARP_BUTTON_PRESSED, "_t_new.H")
    warp_button.press(b)
    assert calls == ["refused"]


def test_sdk_warp_pressed_is_replaced_by_the_engine_step():
    _mod("Bridge.HelmMenuHandlers",
         WarpPressed=lambda o, e: calls.append("WarpPressed"))
    b = _button()
    b.AddPythonFuncHandlerForInstance(
        App.ET_WARP_BUTTON_PRESSED, "Bridge.HelmMenuHandlers.WarpPressed")
    warp_button.press(b)
    assert calls == [("engine", b)]


def test_the_engine_step_is_the_oldest_even_with_no_bridge():
    b = _button()
    warp_button.press(b)
    assert calls == [("engine", b)]


def test_the_event_names_the_button_as_destination():
    seen = []
    _mod("_t_new", H=lambda o, e: (seen.append(e.GetDestination()),
                                   o.CallNextHandler(e)))
    b = _button()
    b.AddPythonFuncHandlerForInstance(App.ET_WARP_BUTTON_PRESSED, "_t_new.H")
    warp_button.press(b)
    assert seen == [b]


# ── the engine step itself (no override) ────────────────────────────────────

def test_a_refused_gate_leaves_the_helm_menu_enabled(monkeypatch):
    """Review Focus 1: a refusal (by the gate or a mission) must not grey the
    Helm menu -- only a warp that actually starts does."""
    warp_button._engage_override = None
    from engine.appc import warp_gates
    from engine import bridge_officers
    disabled = []
    monkeypatch.setattr(bridge_officers, "disable_helm_menu",
                        lambda: disabled.append(1))
    monkeypatch.setattr(warp_gates, "warp_gate",
                        lambda p: warp_gates.GateResult(False, None, True, "t"))
    monkeypatch.setattr(App, "Game_GetCurrentPlayer",
                        lambda: App.ShipClass_Create())
    warp_button.press(_button())
    assert disabled == []


def test_pressing_during_an_active_warp_does_nothing(monkeypatch):
    """Review Focus 3."""
    warp_button._engage_override = None
    from engine.appc import warp as _w
    started = []
    monkeypatch.setattr(_w, "execute_warp", lambda b: started.append(b))
    monkeypatch.setattr(warp_button, "is_warp_active", lambda p: True)
    monkeypatch.setattr(App, "Game_GetCurrentPlayer",
                        lambda: App.ShipClass_Create())
    warp_button.press(_button())
    assert started == []
