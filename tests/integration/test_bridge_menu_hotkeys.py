"""F1 end-to-end: real five menus built, OnKeyDown(WC_F1) through the real
SDK pipeline marks Helm open in the CrewMenuPanel payload."""
import json

import App
import LoadBridge
from engine.appc.windows import TacticalControlWindow
from engine.ui import crew_menu_hotkeys
from engine.ui.crew_menu_panel import CrewMenuPanel

from tests.integration.test_bridge_menu_activation import _fresh_world


def _payload_opens(panel):
    payload = panel.render_payload()
    if payload is None:
        return None
    data = json.loads(payload[len("setCrewMenus("):-2])
    return {m["label"]: m["open"] for m in data["menus"]}


def test_f1_toggles_helm_end_to_end():
    _fresh_world()
    # _fresh_world clears _broadcast_handlers, which removes the
    # ET_KEYBOARD_EVENT → KeyboardBinding.OnKeyboardEvent registration made
    # at App module-load time.  Re-register so OnKeyDown → BindKey → TALK_TO
    # fires correctly (same call App.py makes at startup).
    from engine.appc.input import register_input_handlers
    register_input_handlers(App.g_kEventManager)
    try:
        LoadBridge.Load("GalaxyBridge")
        tcw = TacticalControlWindow.GetInstance()
        App.g_kKeyboardBinding.SetDefaultDestination(tcw)
        import KeyConfig, DefaultKeyboardBinding
        KeyConfig.MapScancodes()
        DefaultKeyboardBinding.Initialize()

        panel = CrewMenuPanel()
        panel.render_payload()
        crew_menu_hotkeys.wire(tcw, panel)

        App.g_kInputManager.OnKeyDown(App.WC_F1)
        from engine.appc.tg_ui.widgets import ensure_widget_id
        helm_menu = tcw.FindMenu(crew_menu_hotkeys._resolve_label("Helm"))
        assert helm_menu is not None
        assert panel._open_menu_id == ensure_widget_id(helm_menu)
        opens = _payload_opens(panel)
        helm_label = [k for k, v in opens.items() if v]
        assert len(helm_label) == 1            # exactly one open

        # F2 = Tactical.  After LoadBridge the Tactical menu gets
        # SetNotVisible() but NOT SetDisabled(), so toggle_menu (which guards
        # only on IsEnabled) will still toggle it.  If that assumption ever
        # changes and F2 stops working, switch this leg to F4 (Science).
        App.g_kInputManager.OnKeyDown(App.WC_F2)   # switch to Tactical
        opens2 = _payload_opens(panel)
        open2 = [k for k, v in opens2.items() if v]
        assert len(open2) == 1
        assert open2 != helm_label

        App.g_kInputManager.OnKeyDown(App.WC_F2)   # same key: close
        opens3 = _payload_opens(panel)
        assert not any(opens3.values())
    finally:
        from engine.core.game import _set_current_game
        _set_current_game(None)
        crew_menu_hotkeys._wired_panel = None
        crew_menu_hotkeys._label_cache.clear()
