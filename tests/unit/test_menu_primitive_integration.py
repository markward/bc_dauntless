"""End-to-end (headless): the two entry points both work through the ONE primitive.

  scripted:  AT_MENU_UP  -> CharacterClass.MenuUp() -> panel view opens, NO ack
  click:     toggle_menu -> CharacterClass.MenuUp() -> panel view opens, ACK fires

This is the layering the SDK demands (BridgeHandlers: `if (pCharacter.MenuUp()):
CharacterInteraction(...)`), and the ack asymmetry is the whole point.
"""
from __future__ import annotations

import engine.appc.characters as chars
import engine.ui.crew_menu_panel as cmp_mod
from engine.appc.ai import CharacterAction
from engine.ui.crew_menu_panel import CrewMenuPanel
from engine.appc.characters import STMenu


def _panel():
    p = CrewMenuPanel.__new__(CrewMenuPanel)
    p._open_menu_id = None
    p._expanded_ids = set()
    return p


def _setup(monkeypatch):
    panel, menu = _panel(), STMenu("Engineering")
    ids = {}
    nxt = [1]

    def _ensure(m):
        if id(m) not in ids:
            ids[id(m)] = nxt[0]
            nxt[0] += 1
        return ids[id(m)]

    monkeypatch.setattr(cmp_mod, "ensure_widget_id", _ensure)

    officer = chars.CharacterClass.__new__(chars.CharacterClass)
    officer._data = {}
    officer._menu = menu
    monkeypatch.setattr(type(officer), "GetMenu", lambda self: self._menu,
                        raising=False)
    monkeypatch.setattr(type(officer), "_notify_menu",
                        lambda self, turn: None, raising=False)
    monkeypatch.setattr(chars, "dispatch_character_menu",
                        lambda character, is_open: None)
    monkeypatch.setattr(chars, "_get_menu_panel", lambda: panel)

    monkeypatch.setattr(panel, "_officer_for_menu", lambda m: officer,
                        raising=False)
    monkeypatch.setattr(panel, "open_officer",
                        lambda: officer if panel._open_menu_id is not None else None,
                        raising=False)
    monkeypatch.setattr("engine.appc.characters.CharacterClass_Cast",
                        lambda c: c)

    acks = []
    monkeypatch.setattr(panel, "_acknowledge", lambda m: acks.append(m),
                        raising=False)
    return panel, menu, officer, acks, _ensure


def test_scripted_at_menu_up_raises_menu_silently(monkeypatch):
    panel, menu, officer, acks, ensure = _setup(monkeypatch)

    CharacterAction(officer, CharacterAction.AT_MENU_UP).Play()

    assert panel._open_menu_id == ensure(menu)   # the menu is UP
    assert officer._data["MenuUp"] is True
    assert acks == []                            # scripted -> silent

    CharacterAction(officer, CharacterAction.AT_MENU_DOWN).Play()
    assert panel._open_menu_id is None           # and back DOWN
    assert officer._data["MenuUp"] is False


def test_click_raises_menu_and_acknowledges(monkeypatch):
    panel, menu, officer, acks, ensure = _setup(monkeypatch)

    panel.toggle_menu(menu)                      # the CEF click / hotkey path

    assert panel._open_menu_id == ensure(menu)   # same primitive raised it
    assert officer._data["MenuUp"] is True
    assert acks == [menu]                        # click -> "Yes sir"
