"""CharacterClass.MenuUp/MenuDown are BC's canonical menu primitive.

BC: `if (pCharacter.MenuUp()): CharacterInteraction(pCharacter)` (BridgeHandlers:612)
and `g_pXO.MenuUp()` (QuickBattle:3368) -- MenuUp RAISES the menu. It must drive the
panel, set the flag, turn the officer, and fire the tutorial event -- and must NOT
acknowledge (BC plays "Yes sir" in CharacterInteraction, click path only).
"""
from __future__ import annotations

import engine.appc.characters as chars


class _Menu:
    def __init__(self, enabled=True):
        self._enabled = enabled

    def IsEnabled(self):
        return 1 if self._enabled else 0


class _Panel:
    """Records the pure view calls MenuUp/MenuDown are supposed to make."""

    def __init__(self):
        self.shown = []
        self.hidden = 0
        self._officer = None

    def open_officer(self):
        return self._officer

    def show_menu(self, menu):
        self.shown.append(menu)

    def hide_menu(self):
        self.hidden += 1


def _officer(monkeypatch, menu, panel, turns, events):
    """A real CharacterClass with GetMenu/_notify_menu/dispatch stubbed."""
    c = chars.CharacterClass.__new__(chars.CharacterClass)
    c._data = {}
    c._menu = menu
    monkeypatch.setattr(type(c), "GetMenu", lambda self: self._menu, raising=False)
    monkeypatch.setattr(type(c), "_notify_menu",
                        lambda self, turn: turns.append(turn), raising=False)
    monkeypatch.setattr(chars, "dispatch_character_menu",
                        lambda character, is_open: events.append(is_open))
    monkeypatch.setattr(chars, "_get_menu_panel", lambda: panel)
    return c


def test_menu_up_raises_menu_sets_flag_turns_and_signals(monkeypatch):
    panel, turns, events = _Panel(), [], []
    menu = _Menu()
    c = _officer(monkeypatch, menu, panel, turns, events)

    assert c.MenuUp() == 1              # BridgeHandlers branches on this
    assert panel.shown == [menu]        # drove the view (the whole point)
    assert c._data["MenuUp"] is True
    assert turns == [True]              # turn-to-captain
    assert events == [True]             # tutorial signal


def test_menu_up_returns_zero_when_no_menu(monkeypatch):
    panel, turns, events = _Panel(), [], []
    c = _officer(monkeypatch, menu=chars._NULL_MENU, panel=panel,
                 turns=turns, events=events)
    assert c.MenuUp() == 0              # falsy _NULL_MENU -> nothing to raise
    assert panel.shown == []
    assert turns == [] and events == []


def test_menu_up_returns_zero_when_disabled(monkeypatch):
    panel, turns, events = _Panel(), [], []
    c = _officer(monkeypatch, _Menu(enabled=False), panel, turns, events)
    assert c.MenuUp() == 0              # stock BC: disabled menus don't raise
    assert panel.shown == []


def test_menu_up_closes_the_other_officers_menu(monkeypatch):
    """Single-open: raising B closes A (and turns A back)."""
    panel, turns, events = _Panel(), [], []
    other_down = []

    class _Other:
        def MenuDown(self):
            other_down.append(True)

    other = _Other()
    panel._officer = other
    menu = _Menu()
    c = _officer(monkeypatch, menu, panel, turns, events)

    assert c.MenuUp() == 1
    assert other_down == [True]         # previous officer closed + turned back
    assert panel.shown == [menu]


def test_menu_down_hides_clears_turns_back(monkeypatch):
    panel, turns, events = _Panel(), [], []
    menu = _Menu()
    c = _officer(monkeypatch, menu, panel, turns, events)
    panel._officer = c                  # this officer's menu is the open one
    c._data["MenuUp"] = True            # a REAL close: the menu must be up first

    c.MenuDown()
    assert panel.hidden == 1
    assert c._data["MenuUp"] is False
    assert turns == [False]             # turn-back
    assert events == [False]


def test_menu_down_never_up_is_a_pure_noop(monkeypatch):
    """SDK calls MenuDown() defensively (ContactStarfleet, DockStarbase12, ...)
    on officers whose menu was never up. That must dispatch NOTHING -- no
    close event, no turn request, no panel touch -- else it fires an unpaired
    close that trips the tutorial's ET_CHARACTER_MENU close-count."""
    panel, turns, events = _Panel(), [], []
    menu = _Menu()
    c = _officer(monkeypatch, menu, panel, turns, events)
    assert "MenuUp" not in c._data or c._data.get("MenuUp") is False

    c.MenuDown()
    assert panel.hidden == 0
    assert turns == []
    assert events == []


def test_menu_up_twice_with_panel_fires_open_once(monkeypatch):
    """A second MenuUp() on an already-open officer must not re-drive the
    view, re-request the turn, or re-dispatch the open event.

    The real CrewMenuPanel.open_officer() resolves dynamically from the
    open menu's ownership (c.GetMenu() is menu), so once show_menu has run
    the panel would already report `c` as the open officer; the fake
    _Panel has no menu-ownership resolver, so mirror that by setting
    panel._officer explicitly after the first (real) open."""
    panel, turns, events = _Panel(), [], []
    menu = _Menu()
    c = _officer(monkeypatch, menu, panel, turns, events)

    assert c.MenuUp() == 1
    panel._officer = c                  # panel now reflects c as the open officer
    assert c.MenuUp() == 1              # idempotent raise
    assert panel.shown == [menu]        # view driven exactly once
    assert turns == [True]              # turn requested exactly once
    assert events == [True]             # open event dispatched exactly once


def test_menu_up_twice_headless_fires_open_once(monkeypatch):
    """Same idempotency guarantee with no panel at all (headless)."""
    turns, events = [], []
    c = _officer(monkeypatch, _Menu(), panel=None, turns=turns, events=events)
    monkeypatch.setattr(chars, "_get_menu_panel", lambda: None)

    assert c.MenuUp() == 1
    assert c.MenuUp() == 1              # idempotent raise, headless
    assert turns == [True]              # turn requested exactly once
    assert events == [True]             # open event dispatched exactly once


def test_menu_down_does_not_hide_someone_elses_menu(monkeypatch):
    panel, turns, events = _Panel(), [], []
    panel._officer = object()           # a DIFFERENT officer is open
    c = _officer(monkeypatch, _Menu(), panel, turns, events)
    c.MenuDown()
    assert panel.hidden == 0            # must not close another officer's menu


def test_headless_no_panel_is_safe(monkeypatch):
    turns, events = [], []
    c = _officer(monkeypatch, _Menu(), panel=None, turns=turns, events=events)
    monkeypatch.setattr(chars, "_get_menu_panel", lambda: None)
    assert c.MenuUp() == 1              # flag + turn + event still fire
    assert turns == [True] and events == [True]
    c.MenuDown()                        # must not raise
