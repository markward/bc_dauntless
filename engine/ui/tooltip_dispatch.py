"""Tooltip owner-selection + UpdateToolTip dispatch (reconstructs BC's native
tooltip loop). BC natively calls <station>UpdateToolTip(pChar) on a cadence while
a character's tooltip is up; those SDK handlers (BridgeHandlers.HelmUpdateToolTip
etc.) write status keys 1-3. Nothing calls them in Dauntless, so this module runs
the real handlers for the current tooltip owner on a throttle.

select_owner picks the focused officer (open crew menu wins over hover). The host
loop resolves hover via bridge_officer_picking and the open-menu officer via the
crew menu panel, sets the current tooltip owner, and calls run_update_tooltip.
"""
from __future__ import annotations


def select_owner(hover, open_menu):
    """Focused officer: an open crew menu outranks hover (BC shows the menu
    officer's box); else the hovered officer; else None."""
    if open_menu is not None:
        return open_menu
    return hover


# Cached once: the REAL BridgeHandlers module (its *UpdateToolTip bodies).
_real_bridge_handlers = None


def _bridge_handlers():
    """Return the REAL BridgeHandlers module -- deliberately NOT the same
    object as ``sys.modules["BridgeHandlers"]``.

    tools/mission_harness.py and tests/conftest.py both keep "BridgeHandlers"
    whole-module-stubbed at that shared name, and that stubbing is load-
    bearing: BridgeHandlers.DropMenusTurnBack() ->
    DropOutOfManualFireMode() -> Bridge.TacticalMenuHandlers.
    ResetPickFireButton() dereferences TacticalControlWindow.GetTacticalMenu()
    with no None-guard and RAISES whenever no tactical menu has been wired up
    -- and MissionLib.StartCutscene calls BridgeHandlers.DropMenusTurnBack()
    unconditionally on *every* cutscene start (sdk/Build/scripts/MissionLib.py
    :744,1268,2138). That crash is exactly the live regression the 2026-07-12
    re-stub (see the comment on "BridgeHandlers" in both twin stub lists)
    fixed. Replacing the shared stub with the real module -- which is what a
    literal "just remove it from both stub lists" would do -- reintroduces
    that crash on every cutscene in the game.

    The *UpdateToolTip functions never call DropMenusTurnBack, so this loads
    a private second instance of the real module (pop the shared stub out of
    sys.modules, import fresh through the SDK loader so it re-resolves to the
    real file, then restore the shared stub) and caches only that instance.
    Every other caller's `import BridgeHandlers` continues to see the shared,
    still-inert stub -- this function is the only thing that ever sees the
    real one.
    """
    global _real_bridge_handlers
    if _real_bridge_handlers is None:
        import sys
        import importlib
        _saved = sys.modules.pop("BridgeHandlers", None)
        try:
            _real_bridge_handlers = importlib.import_module("BridgeHandlers")
        finally:
            sys.modules.pop("BridgeHandlers", None)
            if _saved is not None:
                sys.modules["BridgeHandlers"] = _saved
    return _real_bridge_handlers


def _station_name_for(officer):
    from engine.ui import crew_menu_hotkeys
    return crew_menu_hotkeys.station_name_for(officer)


def run_update_tooltip(owner, now, state, period=0.25) -> None:
    """Throttled call into BridgeHandlers.<station>UpdateToolTip(owner). `state`
    is a mutable dict carrying {"last": <time>}; `period` is the min seconds
    between calls. No-op when the owner has no station handler (non-station
    characters show only their key-0 status)."""
    if owner is None:
        return
    if now - state.get("last", -1e9) < period:
        return
    station = _station_name_for(owner)
    if not station:
        return
    handlers = _bridge_handlers()
    fn = getattr(handlers, station + "UpdateToolTip", None)
    if fn is None:
        return
    state["last"] = now
    try:
        fn(owner)
    except Exception:
        pass        # a handler fault must never break the frame
