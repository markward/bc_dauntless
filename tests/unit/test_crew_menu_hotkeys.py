"""ET_INPUT_TALK_TO_* events toggle the matching crew menu.
Spec: docs/superpowers/specs/2026-06-12-bridge-menu-hotkeys-design.md
"""
import App
from engine.appc.characters import STTopLevelMenu
from engine.appc.windows import TacticalControlWindow
from engine.ui import crew_menu_hotkeys
from engine.ui.crew_menu_panel import CrewMenuPanel


def setup_function(_):
    TacticalControlWindow._instance = None
    crew_menu_hotkeys._wired_panel = None
    crew_menu_hotkeys._label_cache.clear()


def teardown_function(_):
    TacticalControlWindow._instance = None
    crew_menu_hotkeys._wired_panel = None
    crew_menu_hotkeys._label_cache.clear()


def _build(labels=("Helm", "Tactical")):
    tcw = TacticalControlWindow.GetInstance()
    menus = {}
    for label in labels:
        m = STTopLevelMenu(label)
        tcw.AddMenuToList(m)
        menus[label] = m
    panel = CrewMenuPanel()
    panel.render_payload()
    return tcw, panel, menus


def _fire(event_type, tcw):
    evt = App.TGEvent_Create()
    evt.SetEventType(event_type)
    evt.SetDestination(tcw)
    App.g_kEventManager.AddEvent(evt)


def test_talk_to_helm_toggles_helm_menu():
    tcw, panel, menus = _build()
    crew_menu_hotkeys.wire(tcw, panel)
    _fire(App.ET_INPUT_TALK_TO_HELM, tcw)
    assert panel._open_menu_id is not None
    _fire(App.ET_INPUT_TALK_TO_HELM, tcw)
    assert panel._open_menu_id is None


def test_switching_keys_switches_menus():
    tcw, panel, menus = _build()
    crew_menu_hotkeys.wire(tcw, panel)
    from engine.appc.tg_ui.widgets import ensure_widget_id
    _fire(App.ET_INPUT_TALK_TO_HELM, tcw)
    assert panel._open_menu_id == ensure_widget_id(menus["Helm"])
    _fire(App.ET_INPUT_TALK_TO_TACTICAL, tcw)
    assert panel._open_menu_id == ensure_widget_id(menus["Tactical"])


def test_missing_menu_is_dropped_not_raised():
    tcw, panel, _ = _build(labels=("Helm",))   # no Science menu
    crew_menu_hotkeys.wire(tcw, panel)
    _fire(App.ET_INPUT_TALK_TO_SCIENCE, tcw)   # must not raise
    assert panel._open_menu_id is None


def test_rewire_targets_fresh_tcw():
    tcw, panel, _ = _build()
    crew_menu_hotkeys.wire(tcw, panel)
    TacticalControlWindow._instance = None
    fresh = TacticalControlWindow.GetInstance()
    helm = STTopLevelMenu("Helm")
    fresh.AddMenuToList(helm)
    panel.render_payload()
    crew_menu_hotkeys.rewire()
    _fire(App.ET_INPUT_TALK_TO_HELM, fresh)
    assert panel._open_menu_id is not None


def test_rewire_without_wire_is_noop():
    crew_menu_hotkeys.rewire()   # must not raise


def test_labels_cached_at_wire_time():
    tcw, panel, menus = _build()
    crew_menu_hotkeys.wire(tcw, panel)
    assert crew_menu_hotkeys._label_cache[App.ET_INPUT_TALK_TO_HELM] == "Helm"
    # Headless TGL falls back to the key string — pin that assumption.
    assert crew_menu_hotkeys._resolve_label("Helm") == "Helm"


def test_resolve_character_maps_labels_to_officers():
    from engine.ui import crew_menu_hotkeys
    from engine.appc.characters import CharacterClass
    # Headless TGL falls back to the key, so label == key here.
    for label, expected in [
        ("Tactical", "Tactical"), ("Helm", "Helm"), ("Science", "Science"),
        ("Commander", "XO"), ("Engineering", "Engineer"),
    ]:
        char = crew_menu_hotkeys.resolve_character(label)
        assert isinstance(char, CharacterClass)
        assert char.GetCharacterName() == expected


def test_resolve_character_unknown_label_is_none():
    from engine.ui import crew_menu_hotkeys
    assert crew_menu_hotkeys.resolve_character("Bogus Menu") is None
