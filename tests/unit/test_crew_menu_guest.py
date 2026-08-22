"""Guest crew menus: a menu whose owner is NOT one of the five station officers.

BC's guests (BridgeHandlers.TalkToGuest hunts Picard -> Data -> Saalek in the
"bridge" set) carry a mission-made menu built by Bridge/PicardMenuHandlers.
CrewMenuPanel used to resolve the owning officer through the five-station TGL
LABEL table only, so a guest's menu was ownerless as far as the panel was
concerned: it could be shown, but closing it took the view-only branch and left
the guest's MenuUp flag set, with no turn-back and no ET_CHARACTER_MENU close
event (the same bug class as E8M2's Liu / E3M1's MacCray).

CharacterClass.SetMenu already stamps the reverse link (menu.SetOwner(self)), so
ownership is directly readable and needs no label lookup at all.
"""
from __future__ import annotations

import pytest

from engine.appc.characters import CharacterClass, STTopLevelMenu
from engine.ui.crew_menu_panel import CrewMenuPanel


def setup_function(_):
    _reset_menu_world()


def teardown_function(_):
    _reset_menu_world()


def _reset_menu_world():
    from engine.appc.windows import TacticalControlWindow
    from engine.ui import crew_menu_hotkeys
    TacticalControlWindow._instance = None
    crew_menu_hotkeys._wired_panel = None
    crew_menu_hotkeys._label_cache.clear()


def _panel() -> CrewMenuPanel:
    """Minimal panel — bypasses the heavy __init__ (CEF/TCW), as the sibling
    crew-menu tests do."""
    p = CrewMenuPanel.__new__(CrewMenuPanel)
    p._open_menu_id = None
    p._expanded_ids = set()
    return p


def _guest(name: str = "Picard") -> tuple[CharacterClass, STTopLevelMenu]:
    """A guest character holding their own mission-made menu, built exactly as
    Bridge/PicardMenuHandlers.CreateMenus does: attach it to the character
    (`pPicard.SetMenu(pMenu)`, :41) and register it on the tactical control
    window (`pTCW.AddMenuToList(pMenu)`, :43). The registration is what lets the
    panel resolve an open menu id back to its menu."""
    from engine.appc.windows import TacticalControlWindow
    guest = CharacterClass()
    guest.SetCharacterName(name)
    menu = STTopLevelMenu(name)
    guest.SetMenu(menu)
    TacticalControlWindow.GetInstance().AddMenuToList(menu)
    return guest, menu


@pytest.fixture
def bridge_set():
    """A live "bridge" set, as LoadBridge installs one. Registered on the real
    SetManager so the strict character lookup resolves against it, and
    removed afterwards so no guest leaks into another test."""
    import App
    from engine.appc.bridge_set import BridgeSet
    App.g_kSetManager.AddSet(BridgeSet(), "bridge")
    try:
        yield App.g_kSetManager.GetSet("bridge")
    finally:
        App.g_kSetManager.RemoveSet("bridge")


def _bridge_set():
    import App
    return App.g_kSetManager.GetSet("bridge")


def _guest_aboard(name: str):
    """Put a guest, holding their own menu, in the "bridge" set — the state
    E1M1 reaches via Bridge.Characters.<name>.CreateCharacter(pBridgeSet)."""
    guest, menu = _guest(name)
    _bridge_set().AddObjectToSet(guest, name)
    return guest, menu


def test_guest_hunt_finds_the_guest_aboard(bridge_set):
    """BC's TalkToGuest hunts Picard -> Data -> Saalek in the bridge set and
    takes the first one found (BridgeHandlers.py:933-937)."""
    from engine.ui import crew_menu_hotkeys
    guest, _menu = _guest_aboard("Data")

    assert crew_menu_hotkeys.resolve_guest() is guest


def test_guest_hunt_prefers_picard_over_later_guests(bridge_set):
    """The SDK's order is load-bearing when two guests are aboard."""
    from engine.ui import crew_menu_hotkeys
    picard, _ = _guest_aboard("Picard")
    _guest_aboard("Saalek")

    assert crew_menu_hotkeys.resolve_guest() is picard


def test_no_guest_aboard_resolves_to_none(bridge_set):
    """With no guest in the set the hunt must come up empty — BC's
    `else: # Can't have guests in Multiplayer` branch.

    This is the trap: App.CharacterClass_GetObject AUTO-VIVIFIES a character
    for any name asked of it (a headless convenience for mission scripts that
    chain GetMenu() unguarded), so using it here would report a phantom Picard
    aboard every ship in the game and stamp him into the bridge set as a side
    effect. The strict lookup is the one that answers this question."""
    from engine.ui import crew_menu_hotkeys

    assert crew_menu_hotkeys.resolve_guest() is None
    assert bridge_set.GetObject("Picard") is None, "the hunt must not vivify a guest"


def test_guest_menu_resolves_to_its_owner():
    """_officer_for_menu must find the guest through menu ownership. No station
    label matches "Picard", so the label table can never answer this."""
    panel = _panel()
    guest, menu = _guest()

    assert panel._officer_for_menu(menu) is guest


def test_open_guest_menu_is_closeable(monkeypatch):
    """The close round-trip this resolution exists for: with the guest's menu
    open, close_open_menu() must go through the guest's MenuDown() — clearing
    IsMenuUp — not the view-only hide_menu() fallback."""
    panel = _panel()
    guest, menu = _guest()
    # MenuUp reaches the view through the globally-wired panel.
    from engine.ui import crew_menu_hotkeys
    monkeypatch.setattr(crew_menu_hotkeys, "_wired_panel", panel)

    assert guest.MenuUp() == 1
    assert panel.is_menu_open(menu)
    assert guest.IsMenuUp()

    assert panel.close_open_menu() is True
    assert not panel.has_open_menu()
    assert not guest.IsMenuUp(), \
        "close must lower the guest's menu, not just hide the view"


# ── The F6 event path (ET_INPUT_TALK_TO_GUEST) ───────────────────────────────

def _wired(panel_menus=()):
    """A wired TCW + panel, as the host loop sets up after a mission load."""
    import App
    from engine.appc.windows import TacticalControlWindow
    from engine.ui import crew_menu_hotkeys
    tcw = TacticalControlWindow.GetInstance()
    for label in panel_menus:
        tcw.AddMenuToList(STTopLevelMenu(label))
    panel = CrewMenuPanel()
    panel.render_payload()
    crew_menu_hotkeys.wire(tcw, panel)
    return tcw, panel


def _fire_talk_to_guest(tcw):
    import App
    evt = App.TGEvent_Create()
    evt.SetEventType(App.ET_INPUT_TALK_TO_GUEST)
    evt.SetDestination(tcw)
    App.g_kEventManager.AddEvent(evt)


def test_talk_to_guest_toggles_the_guest_menu(bridge_set):
    """F6 -> ET_INPUT_TALK_TO_GUEST must raise the guest's menu, and raise it
    down again on the second press (BC's TalkToGuest IsMenuUp() branch)."""
    tcw, panel = _wired()
    guest, menu = _guest_aboard("Picard")

    _fire_talk_to_guest(tcw)
    assert panel.is_menu_open(menu)
    assert guest.IsMenuUp()

    _fire_talk_to_guest(tcw)
    assert not panel.has_open_menu()
    assert not guest.IsMenuUp()


def test_talk_to_guest_supersedes_an_open_station_menu(bridge_set):
    """Single-open invariant across the station/guest boundary: F6 with the
    Helm menu up closes Helm and raises the guest."""
    from engine.ui import crew_menu_hotkeys
    tcw, panel = _wired(panel_menus=("Helm",))
    guest, guest_menu = _guest_aboard("Picard")
    crew_menu_hotkeys.open_menu_for_label(panel, "Helm")
    assert panel.has_open_menu()

    _fire_talk_to_guest(tcw)

    assert panel.is_menu_open(guest_menu)
    assert guest.IsMenuUp()


def test_talk_to_guest_with_no_guest_aboard_is_a_silent_noop(bridge_set):
    """Most missions have no guest. F6 must then do nothing at all — and in
    particular must not disturb a station menu the player has open."""
    from engine.ui import crew_menu_hotkeys
    tcw, panel = _wired(panel_menus=("Helm",))
    crew_menu_hotkeys.open_menu_for_label(panel, "Helm")
    open_before = panel._open_menu_id

    _fire_talk_to_guest(tcw)          # must not raise

    assert panel._open_menu_id == open_before
