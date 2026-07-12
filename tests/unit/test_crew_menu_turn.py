"""Tests: crew-menu open/close/switch drives MenuUp/MenuDown on the resolved officer.

Exercises the REAL toggle_menu / close_open_menu on CrewMenuPanel, which now
DELEGATES to BC's canonical primitive (CharacterClass.MenuUp/MenuDown — the thing
that actually raises/lowers the view, turns the officer, and fires the
ET_CHARACTER_MENU tutorial signal).

The test bypasses heavy __init__ (TacticalControlWindow, CEF), sets only the
state that toggle_menu touches (_open_menu_id, _expanded_ids), and monkeypatches:
  - ensure_widget_id     -> deterministic ints per menu object
  - _officer_for_menu    -> the fake officer owning a TARGET menu
  - open_officer         -> the fake officer owning the OPEN menu
  - the _acknowledge method (to skip speech, irrelevant to turn testing)

Officers are stubs that behave like the real MenuUp/MenuDown: they drive the
panel's pure view primitives and record the open/close tutorial signal.
"""
from __future__ import annotations

import engine.ui.crew_menu_panel as cmp_mod
from engine.ui.crew_menu_panel import CrewMenuPanel
from engine.appc.characters import STMenu


# ── Helpers ──────────────────────────────────────────────────────────────────

class _Officer:
    """Fake officer that behaves like the REAL CharacterClass.MenuUp: it drives
    the panel view (that is the whole point of the canonical primitive)."""

    def __init__(self, name: str, panel=None, menu=None):
        self.name = name
        self._up = False
        self.up_calls = 0
        self.down_calls = 0
        # 1 = opened, 0 = closed — the ET_CHARACTER_MENU tutorial signal, which
        # the real MenuUp/MenuDown fire via dispatch_character_menu.
        self.menu_events: list[int] = []
        self._panel = panel
        self._menu = menu

    def MenuUp(self) -> int:
        self._up = True
        self.up_calls += 1
        if self._panel is not None and self._menu is not None:
            other = self._panel.open_officer()
            if other is not None and other is not self:
                other.MenuDown()
            self._panel.show_menu(self._menu)
        self.menu_events.append(1)
        return 1

    def MenuDown(self) -> None:
        self._up = False
        self.down_calls += 1
        if self._panel is not None and self._panel.open_officer() is self:
            self._panel.hide_menu()
        self.menu_events.append(0)

    @property
    def is_up(self) -> bool:
        return self._up


def _make_menu(label: str) -> STMenu:
    """Create a real STMenu (enabled by default from __init__)."""
    m = STMenu(label)
    return m


def _make_panel() -> CrewMenuPanel:
    """Construct a minimal CrewMenuPanel without calling heavy __init__.
    Sets only the attributes toggle_menu / close_open_menu read or write."""
    panel = CrewMenuPanel.__new__(CrewMenuPanel)
    panel._open_menu_id = None
    panel._expanded_ids = set()
    return panel


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _patch_panel(monkeypatch, panel, officers_by_menu: dict):
    """Wire ensure_widget_id + officer resolution for the DELEGATING toggle_menu.

    officers_by_menu: {menu_object: _Officer|None}. toggle_menu now resolves the
    TARGET menu's officer (_officer_for_menu) before opening, and the OPEN menu's
    officer (open_officer) to close/switch."""
    ids: dict[int, int] = {}
    nxt = [1]

    def _ensure(m):
        if id(m) not in ids:
            ids[id(m)] = nxt[0]
            nxt[0] += 1
        return ids[id(m)]

    monkeypatch.setattr(cmp_mod, "ensure_widget_id", _ensure)

    def _officer_for_menu(menu, _p=panel):
        return officers_by_menu.get(menu)

    def _open_officer(_p=panel):
        for m, off in officers_by_menu.items():
            if panel._open_menu_id == _ensure(m):
                return off
        return None

    monkeypatch.setattr(panel, "_officer_for_menu", _officer_for_menu, raising=False)
    monkeypatch.setattr(panel, "open_officer", _open_officer, raising=False)
    monkeypatch.setattr(panel, "_acknowledge", lambda menu: None, raising=False)


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_open_calls_menu_up(monkeypatch):
    """Opening a menu calls MenuUp() on the resolved officer."""
    helm = _make_menu("Helm")
    panel = _make_panel()
    officer = _Officer("Helm", panel=panel, menu=helm)
    _patch_panel(monkeypatch, panel, officers_by_menu={helm: officer})

    panel.toggle_menu(helm)  # open

    assert officer.is_up, "MenuUp() should have been called on open"
    assert officer.up_calls == 1
    assert officer.down_calls == 0


def test_close_same_calls_menu_down(monkeypatch):
    """Toggling the same menu again closes it and calls MenuDown()."""
    helm = _make_menu("Helm")
    panel = _make_panel()
    officer = _Officer("Helm", panel=panel, menu=helm)
    _patch_panel(monkeypatch, panel, officers_by_menu={helm: officer})

    panel.toggle_menu(helm)  # open  -> MenuUp
    panel.toggle_menu(helm)  # close -> MenuDown

    assert not officer.is_up, "MenuDown() should have been called on close"
    assert officer.up_calls == 1
    assert officer.down_calls == 1
    assert panel._open_menu_id is None, "the view must actually close"


def test_switch_menu_turns_old_down_new_up(monkeypatch):
    """Switching A→B calls MenuDown(A) then MenuUp(B) (single toggle call)."""
    menu_a = _make_menu("Helm")
    menu_b = _make_menu("Tactical")
    panel = _make_panel()
    officer_a = _Officer("Helm", panel=panel, menu=menu_a)
    officer_b = _Officer("Tactical", panel=panel, menu=menu_b)
    _patch_panel(monkeypatch, panel,
                 officers_by_menu={menu_a: officer_a, menu_b: officer_b})

    panel.toggle_menu(menu_a)  # open A -> MenuUp(A)
    assert officer_a.is_up
    assert not officer_b.is_up

    panel.toggle_menu(menu_b)  # switch to B -> MenuDown(A) + MenuUp(B)
    assert not officer_a.is_up, "old officer should be turned back"
    assert officer_b.is_up, "new officer should be turned toward captain"
    assert officer_a.up_calls == 1
    assert officer_a.down_calls == 1
    assert officer_b.up_calls == 1
    assert officer_b.down_calls == 0


def test_close_open_menu_calls_menu_down(monkeypatch):
    """close_open_menu() calls MenuDown on the current officer."""
    helm = _make_menu("Helm")
    panel = _make_panel()
    officer = _Officer("Helm", panel=panel, menu=helm)
    _patch_panel(monkeypatch, panel, officers_by_menu={helm: officer})

    panel.toggle_menu(helm)      # open -> MenuUp
    result = panel.close_open_menu()  # -> MenuDown

    assert result is True, "close_open_menu should return True when a menu was open"
    assert not officer.is_up
    assert officer.down_calls == 1
    assert panel._open_menu_id is None


def test_close_open_menu_no_open_is_noop(monkeypatch):
    """close_open_menu() with nothing open returns False without crashing."""
    panel = _make_panel()
    _patch_panel(monkeypatch, panel, officers_by_menu={})

    result = panel.close_open_menu()

    assert result is False


def test_no_officer_resolved_does_not_crash(monkeypatch):
    """If no officer resolves for the menu, toggle_menu still works cleanly —
    the view opens and closes on the panel's own primitives."""
    helm = _make_menu("Helm")
    panel = _make_panel()

    _patch_panel(monkeypatch, panel, officers_by_menu={helm: None})

    # Must not raise, and must still honour the open/close view toggle.
    panel.toggle_menu(helm)
    assert panel._open_menu_id is not None
    panel.toggle_menu(helm)
    assert panel._open_menu_id is None


def test_disabled_menu_ignored(monkeypatch):
    """toggle_menu ignores disabled menus (MenuUp must NOT be called)."""
    helm = _make_menu("Helm")
    helm.SetDisabled()  # disabled
    panel = _make_panel()
    officer = _Officer("Helm", panel=panel, menu=helm)
    _patch_panel(monkeypatch, panel, officers_by_menu={helm: officer})

    panel.toggle_menu(helm)

    assert not officer.is_up
    assert officer.up_calls == 0


# ── ET_CHARACTER_MENU dispatch (E1M1 char-select tutorial signal) ────────────
# The signal now fires from MenuUp/MenuDown (BC's primitive), not from the panel;
# the fake officers record it exactly as the real dispatch_character_menu would.

def test_open_dispatches_character_menu_open(monkeypatch):
    """Opening a menu dispatches ET_CHARACTER_MENU(bool=1) to the officer."""
    helm = _make_menu("Helm")
    panel = _make_panel()
    officer = _Officer("Helm", panel=panel, menu=helm)
    _patch_panel(monkeypatch, panel, officers_by_menu={helm: officer})

    panel.toggle_menu(helm)  # open

    assert officer.menu_events == [1]


def test_close_dispatches_character_menu_close(monkeypatch):
    """The tutorial-advancing signal: closing a menu dispatches bool=0."""
    helm = _make_menu("Helm")
    panel = _make_panel()
    officer = _Officer("Helm", panel=panel, menu=helm)
    _patch_panel(monkeypatch, panel, officers_by_menu={helm: officer})

    panel.toggle_menu(helm)  # open  -> 1
    panel.toggle_menu(helm)  # close -> 0

    assert officer.menu_events == [1, 0]


def test_switch_dispatches_close_old_then_open_new(monkeypatch):
    """Switching A→B dispatches close(A) then open(B)."""
    menu_a = _make_menu("Helm")
    menu_b = _make_menu("Tactical")
    panel = _make_panel()
    officer_a = _Officer("Helm", panel=panel, menu=menu_a)
    officer_b = _Officer("Tactical", panel=panel, menu=menu_b)
    _patch_panel(monkeypatch, panel,
                 officers_by_menu={menu_a: officer_a, menu_b: officer_b})

    panel.toggle_menu(menu_a)  # open A -> A:[1]
    panel.toggle_menu(menu_b)  # switch -> A:[1,0], B:[1]

    assert officer_a.menu_events == [1, 0]
    assert officer_b.menu_events == [1]


def test_close_open_menu_dispatches_character_menu_close(monkeypatch):
    """close_open_menu() (ESC path) dispatches bool=0 to the officer."""
    helm = _make_menu("Helm")
    panel = _make_panel()
    officer = _Officer("Helm", panel=panel, menu=helm)
    _patch_panel(monkeypatch, panel, officers_by_menu={helm: officer})

    panel.toggle_menu(helm)       # open  -> [1]
    panel.close_open_menu()       # close -> [1, 0]

    assert officer.menu_events == [1, 0]
