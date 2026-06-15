"""The real SDK LoadBridge.Load runs end-to-end against loud stubs.

Imports the SDK module DIRECTLY (importlib from sdk/Build/scripts) so this test
is valid both before and after the root LoadBridge.py shadow is removed.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

import App
import engine.appc._stub_trace as st
from engine.core.game import Game, Episode, Mission, _set_current_game

SDK_LOADBRIDGE = (
    Path(__file__).resolve().parents[2]
    / "sdk" / "Build" / "scripts" / "LoadBridge.py"
)


def _fresh_world():
    # Mirror tests/integration/test_bridge_menu_activation.py::_fresh_world:
    # reset the UI/menu singletons the SDK menu handlers touch, clear stale
    # sets + event handlers, then build a Game/Episode/Mission context.
    from engine.appc.windows import TacticalControlWindow
    from engine.appc.target_menu import _reset_target_menu_singleton
    from engine.appc.tg_ui import st_widgets
    from engine.sdk_ui.widgets.ship_display import (
        _reset_create_count as _reset_ship_display,
    )

    TacticalControlWindow._instance = None
    _reset_target_menu_singleton()
    st_widgets._reset_module_state()
    _reset_ship_display()
    App.g_kSetManager._sets.clear()
    # Handlers re-register on each Load; clear stale ones from prior tests.
    App.g_kEventManager._broadcast_handlers.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()
    # Game/Episode/Mission scaffolding.
    game = Game()
    episode = Episode()
    mission = Mission()
    episode.SetCurrentMission(mission)
    game.SetCurrentEpisode(episode)
    _set_current_game(game)
    # Drop any stale stub modules so the handlers' import chains see the
    # real SDK modules.
    for name in list(sys.modules):
        mod = sys.modules[name]
        if name.startswith("Bridge.") and "StubModule" in type(mod).__name__:
            sys.modules.pop(name)
    return game


def _sdk_loader(path):
    # Reuse the SAME _SDKLoader the production _SDKFinder (installed on
    # sys.meta_path by tests/conftest.py) uses, so the Python-1.5 compat AST
    # fixes are applied — crucially _FixDottedImport, which makes
    # `__import__("Bridge.Characters.FemaleExtra1")` return the leaf module
    # rather than the root package. A raw spec_from_file_location would skip
    # those fixes and break the SDK's __import__ + pModule.CreateCharacter(...)
    # extras path. We pull the loader class off the live finder so the test
    # doesn't depend on conftest being importable as a top-level module.
    for finder in sys.meta_path:
        if type(finder).__name__ == "_SDKFinder":
            loader_cls = type(finder).find_spec.__globals__["_SDKLoader"]
            return loader_cls(path)
    raise RuntimeError("_SDKFinder not installed on sys.meta_path")


def _load_sdk_loadbridge():
    # Load the SDK module directly from sdk/Build/scripts, bypassing the root
    # LoadBridge.py shadow.
    spec = importlib.util.spec_from_file_location(
        "_sdk_LoadBridge", str(SDK_LOADBRIDGE),
        loader=_sdk_loader(str(SDK_LOADBRIDGE)),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def sdk_loadbridge():
    st.reset()
    _fresh_world()
    mod = _load_sdk_loadbridge()
    yield mod
    App.g_kSetManager._sets.clear()
    _set_current_game(None)
    st.reset()


def test_sdk_load_runs_end_to_end_and_populates_crew(sdk_loadbridge):
    sdk_loadbridge.Load("GalaxyBridge")

    bridge = App.g_kSetManager.GetSet("bridge")
    assert App.BridgeSet_Cast(bridge) is not None          # a real BridgeSet

    for station in ("Tactical", "Helm", "XO", "Science", "Engineer"):
        assert App.CharacterClass_Cast(bridge.GetObject(station)) is not None

    extras = [n for n in ("MaleExtra1", "MaleExtra2", "MaleExtra3",
                          "FemaleExtra1", "FemaleExtra2", "FemaleExtra3")
              if bridge.GetObject(n) is not None]
    assert len(extras) == 3

    fired = st.fired()
    # Steps 3 + 5b: these are now REAL and must have left the summary.
    assert "BridgeObjectClass_Create" not in fired
    assert "g_kModelManager.LoadModel" not in fired
    assert "ViewScreenObject_Create" not in fired
    assert "BridgeSet.GetViewScreen" not in fired
    assert "BridgeSet.SetViewScreen" not in fired
    assert "BridgeSet.GetConfig" not in fired
    assert "BridgeSet.SetConfig" not in fired
    assert "BridgeSet.IsSameConfig" not in fired
    assert "BridgeSet.DeleteCameraFromSet" not in fired
    # Still-stubbed control-flow symbols prove the SDK path actually ran.
    assert "BridgeSet_Create" in fired
    assert "ZoomCameraObjectClass_Create" in fired

    # The SDK-created bridge object carries the bridge NIF for the host to
    # realize (mesh selection is config-driven, not hardcoded).
    bridge_obj = bridge.GetObject("bridge")
    assert bridge_obj is not None
    assert bridge_obj.nif.endswith("DBridge.nif")
    assert bridge_obj.render_instance is None      # host fills this in live

    # Step 5b: the SDK-created viewscreen carries DBridgeViewScreen.nif for
    # the host to realize; render_instance stays None until the host runs.
    viewscreen = bridge.GetViewScreen()
    assert viewscreen is not None
    assert viewscreen.nif.endswith("DBridgeViewScreen.nif")
    assert viewscreen.render_instance is None


def test_summary_prints_outstanding_stubs(sdk_loadbridge, capsys):
    sdk_loadbridge.Load("GalaxyBridge")
    capsys.readouterr()
    st.dump_stub_summary()
    err = capsys.readouterr().err
    assert "still need fleshing out" in err
    # Step 5b: the viewscreen + BridgeSet.* are real now; only the zoom
    # camera remains stubbed for step 5a.
    assert "ZoomCameraObjectClass_Create" in err
    assert "ViewScreenObject_Create" not in err
    assert "BridgeObjectClass_Create" not in err
