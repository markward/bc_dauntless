"""Pure view primitives: show_menu/hide_menu set view state ONLY.

They must never call MenuUp/MenuDown and never acknowledge — CharacterClass.MenuUp
is the canonical primitive that drives them (BC layering). That one-way rule is
what makes recursion impossible.
"""
from __future__ import annotations

import engine.ui.crew_menu_panel as cmp_mod
from engine.ui.crew_menu_panel import CrewMenuPanel
from engine.appc.characters import STMenu


def _panel() -> CrewMenuPanel:
    p = CrewMenuPanel.__new__(CrewMenuPanel)   # bypass heavy __init__ (CEF/TCW)
    p._open_menu_id = None
    p._expanded_ids = set()
    return p


def _patch_ids(monkeypatch):
    ids: dict[int, int] = {}
    nxt = [1]

    def _ensure(m):
        if id(m) not in ids:
            ids[id(m)] = nxt[0]
            nxt[0] += 1
        return ids[id(m)]

    monkeypatch.setattr(cmp_mod, "ensure_widget_id", _ensure)
    return _ensure


def test_show_menu_opens_and_is_idempotent(monkeypatch):
    ensure = _patch_ids(monkeypatch)
    p, helm = _panel(), STMenu("Helm")
    p._expanded_ids.add(99)

    p.show_menu(helm)
    assert p._open_menu_id == ensure(helm)
    assert p._expanded_ids == set()      # reopened menu starts collapsed

    p._expanded_ids.add(7)
    p.show_menu(helm)                    # already open -> no-op (does NOT reset)
    assert p._open_menu_id == ensure(helm)
    assert p._expanded_ids == {7}


def test_show_menu_switches(monkeypatch):
    ensure = _patch_ids(monkeypatch)
    p, helm, tac = _panel(), STMenu("Helm"), STMenu("Tactical")
    p.show_menu(helm)
    p.show_menu(tac)
    assert p._open_menu_id == ensure(tac)     # single-open view state


def test_hide_menu_closes_and_is_idempotent(monkeypatch):
    _patch_ids(monkeypatch)
    p, helm = _panel(), STMenu("Helm")
    p.show_menu(helm)
    p.hide_menu()
    assert p._open_menu_id is None
    assert p._expanded_ids == set()
    p.hide_menu()                        # idempotent
    assert p._open_menu_id is None


def test_show_menu_fires_activation_event(monkeypatch):
    _patch_ids(monkeypatch)
    p, helm = _panel(), STMenu("Helm")
    fired = []
    monkeypatch.setattr(helm, "SendActivationEvent",
                        lambda: fired.append(True), raising=False)
    p.show_menu(helm)
    assert fired == [True]               # BC broadcasts activation on open


def test_show_hide_never_touch_menuup(monkeypatch):
    """The one-way rule: view primitives must not call back into MenuUp/MenuDown."""
    _patch_ids(monkeypatch)
    p, helm = _panel(), STMenu("Helm")
    calls = []
    monkeypatch.setattr(p, "_officer_for_menu",
                        lambda m: (_ for _ in ()).throw(AssertionError(
                            "show_menu must not resolve/notify officers")),
                        raising=False)
    p.show_menu(helm)      # must not raise -> proves it never resolved an officer
    p.hide_menu()
    assert calls == []


def test_get_panel_returns_wired_panel(monkeypatch):
    from engine.ui import crew_menu_hotkeys
    monkeypatch.setattr(crew_menu_hotkeys, "_wired_panel", None, raising=False)
    assert crew_menu_hotkeys.get_panel() is None
    sentinel = object()
    monkeypatch.setattr(crew_menu_hotkeys, "_wired_panel", sentinel, raising=False)
    assert crew_menu_hotkeys.get_panel() is sentinel
