import sys

from engine.appc.characters import (
    CharacterClass,
    CharacterClass_GetCurrentToolTipOwner,
    CharacterClass_SetCurrentToolTipOwner,
    DropCharacterToolTips,
)
from engine.ui import tooltip_dispatch


def test_owner_set_get_roundtrip():
    ch = CharacterClass()
    CharacterClass_SetCurrentToolTipOwner(ch)
    assert CharacterClass_GetCurrentToolTipOwner() is ch
    CharacterClass_SetCurrentToolTipOwner(None)
    assert CharacterClass_GetCurrentToolTipOwner() is None


def test_drop_clears_owner():
    ch = CharacterClass()
    CharacterClass_SetCurrentToolTipOwner(ch)
    DropCharacterToolTips()
    assert CharacterClass_GetCurrentToolTipOwner() is None


def test_should_drop_tooltips_only_for_owner():
    a, b = CharacterClass(), CharacterClass()
    CharacterClass_SetCurrentToolTipOwner(a)
    assert a._should_drop_tooltips() is True
    assert b._should_drop_tooltips() is False
    CharacterClass_SetCurrentToolTipOwner(None)


# ── Task 7: dispatcher (select_owner + run_update_tooltip) ──────────────────

def test_select_owner_prefers_open_menu_then_hover():
    a, b = object(), object()
    assert tooltip_dispatch.select_owner(hover=a, open_menu=b) is b   # menu wins
    assert tooltip_dispatch.select_owner(hover=a, open_menu=None) is a
    assert tooltip_dispatch.select_owner(hover=None, open_menu=None) is None


def test_run_update_tooltip_calls_station_handler(monkeypatch):
    calls = []

    class _Handlers:
        def HelmUpdateToolTip(self, ch):
            calls.append(ch)

    monkeypatch.setattr(tooltip_dispatch, "_bridge_handlers",
                        lambda: _Handlers(), raising=False)
    monkeypatch.setattr(tooltip_dispatch, "_station_name_for",
                        lambda ch: "Helm", raising=False)

    owner = object()
    state = {"last": -999.0}
    tooltip_dispatch.run_update_tooltip(owner, now=10.0, state=state, period=0.25)
    assert calls == [owner]
    # Within the throttle window: no second call.
    tooltip_dispatch.run_update_tooltip(owner, now=10.1, state=state, period=0.25)
    assert calls == [owner]
    # After the window: called again.
    tooltip_dispatch.run_update_tooltip(owner, now=10.4, state=state, period=0.25)
    assert calls == [owner, owner]


def test_run_update_tooltip_noop_when_no_station_handler(monkeypatch):
    """A non-station character (station_name_for -> None) is a silent no-op --
    matches BridgeHandlers coverage (only the 5 bridge officers have
    <station>UpdateToolTip; e.g. Picard/Data/Saalek/Korbus don't route here)."""
    monkeypatch.setattr(tooltip_dispatch, "_station_name_for",
                        lambda ch: None, raising=False)
    state = {"last": -999.0}
    tooltip_dispatch.run_update_tooltip(object(), now=10.0, state=state, period=0.25)
    assert state["last"] == -999.0   # never advanced -- handler never reached


def test_bridge_handlers_loads_real_module_without_disturbing_shared_stub():
    """_bridge_handlers() must return the REAL BridgeHandlers module (its
    *UpdateToolTip bodies are actual code, not a chainable stub) while leaving
    sys.modules["BridgeHandlers"] -- the shared stub every other SDK caller
    imports -- untouched. Unstubbing that shared name would let
    MissionLib.StartCutscene's unconditional BridgeHandlers.DropMenusTurnBack()
    call reach the real, crash-prone body (see the docstring on
    tooltip_dispatch._bridge_handlers); this proves the isolation holds."""
    import inspect

    before = sys.modules.get("BridgeHandlers")
    assert before is not None
    assert type(before).__name__ == "_StubModule"

    real = tooltip_dispatch._bridge_handlers()

    after = sys.modules.get("BridgeHandlers")
    assert after is before                     # shared stub identity unchanged
    assert type(after).__name__ == "_StubModule"
    assert real is not before                  # dispatcher's copy is a different object
    assert inspect.isfunction(real.HelmUpdateToolTip)   # real code, not a _Stub
