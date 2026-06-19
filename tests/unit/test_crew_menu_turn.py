"""Tests: crew-menu open/close/switch drives MenuUp/MenuDown on the resolved officer.

Exercises the REAL toggle_menu / close_open_menu on CrewMenuPanel.
The test bypasses heavy __init__ (TacticalControlWindow, CEF), sets only the
state that toggle_menu touches (_open_menu_id, _expanded_ids), and monkeypatches:
  - ensure_widget_id   -> deterministic ints per menu object
  - _menu_officer      -> returns the fake officer matching the open id
  - crew_menu_hotkeys.resolve_character  (via _acknowledge path, unused here)
  - the _acknowledge method (to skip speech, irrelevant to turn testing)

Officers are stubs with MenuUp/MenuDown call recorders.
"""
from __future__ import annotations

import engine.ui.crew_menu_panel as cmp_mod
from engine.ui.crew_menu_panel import CrewMenuPanel
from engine.appc.characters import STMenu


# ── Helpers ──────────────────────────────────────────────────────────────────

class _Officer:
    def __init__(self, name: str):
        self.name = name
        self._up = False
        self.up_calls = 0
        self.down_calls = 0

    def MenuUp(self) -> int:
        self._up = True
        self.up_calls += 1
        return 1  # truthy

    def MenuDown(self) -> None:
        self._up = False
        self.down_calls += 1

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

def _patch_panel(monkeypatch, panel, officers_by_id: dict):
    """Wire up ensure_widget_id and _menu_officer so toggle_menu resolves cleanly.

    officers_by_id: {int_wid: _Officer}  (None value = no officer for that id)
    """
    # Map from menu object identity -> widget id (assigned on first call, stable).
    _id_map: dict[int, int] = {}
    _next_id = [1]

    def _ensure_widget_id(m):
        oid = id(m)
        if oid not in _id_map:
            _id_map[oid] = _next_id[0]
            _next_id[0] += 1
        return _id_map[oid]

    monkeypatch.setattr(cmp_mod, "ensure_widget_id", _ensure_widget_id)

    # _menu_officer reads _open_menu_id then resolves via open_menu_label() +
    # crew_menu_hotkeys.  We patch the method directly to avoid App/TGL deps.
    def _menu_officer(self=panel):
        return officers_by_id.get(panel._open_menu_id)

    monkeypatch.setattr(panel, "_menu_officer", _menu_officer, raising=False)

    # Silence _acknowledge (speech system, not relevant to turn tests).
    monkeypatch.setattr(panel, "_acknowledge", lambda menu: None, raising=False)


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_open_calls_menu_up(monkeypatch):
    """Opening a menu calls MenuUp() on the resolved officer."""
    helm = _make_menu("Helm")
    officer = _Officer("Helm")
    panel = _make_panel()

    # ensure_widget_id will assign wid=1 to the first menu it sees.
    _patch_panel(monkeypatch, panel, officers_by_id={1: officer})

    panel.toggle_menu(helm)  # open

    assert officer.is_up, "MenuUp() should have been called on open"
    assert officer.up_calls == 1
    assert officer.down_calls == 0


def test_close_same_calls_menu_down(monkeypatch):
    """Toggling the same menu again closes it and calls MenuDown()."""
    helm = _make_menu("Helm")
    officer = _Officer("Helm")
    panel = _make_panel()

    _patch_panel(monkeypatch, panel, officers_by_id={1: officer})

    panel.toggle_menu(helm)  # open  -> MenuUp
    panel.toggle_menu(helm)  # close -> MenuDown

    assert not officer.is_up, "MenuDown() should have been called on close"
    assert officer.up_calls == 1
    assert officer.down_calls == 1


def test_switch_menu_turns_old_down_new_up(monkeypatch):
    """Switching A→B calls MenuDown(A) then MenuUp(B) (single toggle call)."""
    menu_a = _make_menu("Helm")
    menu_b = _make_menu("Tactical")
    officer_a = _Officer("Helm")
    officer_b = _Officer("Tactical")
    panel = _make_panel()

    # ensure_widget_id assigns 1 to the first menu seen, 2 to the second.
    _patch_panel(monkeypatch, panel, officers_by_id={1: officer_a, 2: officer_b})

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
    officer = _Officer("Helm")
    panel = _make_panel()

    _patch_panel(monkeypatch, panel, officers_by_id={1: officer})

    panel.toggle_menu(helm)      # open -> MenuUp
    result = panel.close_open_menu()  # -> MenuDown

    assert result is True, "close_open_menu should return True when a menu was open"
    assert not officer.is_up
    assert officer.down_calls == 1


def test_close_open_menu_no_open_is_noop(monkeypatch):
    """close_open_menu() with nothing open returns False without crashing."""
    panel = _make_panel()
    _patch_panel(monkeypatch, panel, officers_by_id={})

    result = panel.close_open_menu()

    assert result is False


def test_no_officer_resolved_does_not_crash(monkeypatch):
    """If _menu_officer returns None, toggle_menu still works cleanly."""
    helm = _make_menu("Helm")
    panel = _make_panel()

    _patch_panel(monkeypatch, panel, officers_by_id={1: None})

    # Must not raise.
    panel.toggle_menu(helm)
    panel.toggle_menu(helm)


def test_disabled_menu_ignored(monkeypatch):
    """toggle_menu ignores disabled menus (MenuUp must NOT be called)."""
    helm = _make_menu("Helm")
    helm.SetDisabled()  # disabled
    officer = _Officer("Helm")
    panel = _make_panel()

    _patch_panel(monkeypatch, panel, officers_by_id={1: officer})

    panel.toggle_menu(helm)

    assert not officer.is_up
    assert officer.up_calls == 0
