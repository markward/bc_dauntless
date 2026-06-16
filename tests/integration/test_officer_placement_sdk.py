"""Step 4: the real SDK bridge crew resolve to real placement clips, and the
recording animation surfaces stay faithful."""
import importlib.util
import sys
from pathlib import Path

import pytest

import App
from engine.core.game import Game, Episode, Mission, _set_current_game
from engine.appc.bridge_placement import capture_placement
from engine.appc.characters import CharacterClass

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
    _fresh_world()
    mod = _load_sdk_loadbridge()
    yield mod
    App.g_kSetManager._sets.clear()
    _set_current_game(None)


def test_standard_crew_resolve_to_expected_clips(sdk_loadbridge):
    sdk_loadbridge.Load("GalaxyBridge")
    bridge = App.g_kSetManager.GetSet("bridge")

    expected = {
        "Tactical": "data/animations/db_stand_t_l.nif",
        "Helm":     "data/animations/db_stand_h_m.nif",
        "XO":       "data/animations/db_stand_c_m.nif",
        "Science":  "data/animations/db_StoL1_S.nif",
        "Engineer": "data/animations/db_EtoL1_s.nif",
    }
    for slot, clip in expected.items():
        off = App.CharacterClass_Cast(bridge.GetObject(slot))
        assert off is not None, slot
        p = capture_placement(off)
        assert p is not None and p["clip_nif"] == clip, (slot, p)

    # Science/Engineer use move-from-station clips -> sample at frame 0.
    assert capture_placement(App.CharacterClass_Cast(bridge.GetObject("Science")))["sample_at_start"] is True
    assert capture_placement(App.CharacterClass_Cast(bridge.GetObject("Engineer")))["sample_at_start"] is True


def test_all_characters_in_set_are_enumerable(sdk_loadbridge):
    sdk_loadbridge.Load("GalaxyBridge")
    bridge = App.g_kSetManager.GetSet("bridge")
    chars = bridge.GetClassObjectList(CharacterClass)
    # 5 standard crew + 3 random extras.
    assert len(chars) >= 5


def test_recording_surfaces_capture_without_error(sdk_loadbridge):
    sdk_loadbridge.Load("GalaxyBridge")
    bridge = App.g_kSetManager.GetSet("bridge")
    # Capturing placement runs against the real recording surfaces
    # (g_kAnimationManager, TGAnimPosition_Create) for every officer in the set.
    chars = bridge.GetClassObjectList(CharacterClass)
    assert chars
    for off in chars:
        capture_placement(off)
