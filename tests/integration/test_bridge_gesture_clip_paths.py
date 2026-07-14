"""Regression test for the console-gesture clip-path bug (root cause traced
via a live GalaxyBridge load): CommonAnimations.ConsoleSlide/PushingButtons
re-register their own gesture-clip NAME on every gesture build, with a path
built by string concatenation and NO file extension. Under the OLD
last-write-wins AnimationManager.LoadAnimation, that extension-less
re-registration clobbered the good, extensioned path GalaxyBridge's
PreloadAnimations had already registered, leaving the clip unloadable and the
gesture silently never playing.

This drives the REAL SDK end to end (LoadBridge.Load("GalaxyBridge") + the
real Bridge.Characters.SmallAnimations.DBEConsoleInteraction gesture builder
for the Engineer's "PushingButtons" key) and asserts every resolved clip path
still has a file extension.
"""
import App

from engine.appc.bridge_placement import registered_module_path
from engine.bridge_idle_gestures import build_sequence_clips

from tests.integration.test_sdk_bridge_load import _fresh_world, _load_sdk_loadbridge


def test_engineer_pushing_buttons_gesture_clips_all_have_a_file_extension():
    _fresh_world()
    sdk_loadbridge = _load_sdk_loadbridge()
    sdk_loadbridge.Load("GalaxyBridge")

    bridge = App.g_kSetManager.GetSet("bridge")
    engineer = App.CharacterClass_Cast(bridge.GetObject("Engineer"))
    assert engineer is not None

    module_path = registered_module_path(engineer, "PushingButtons")
    assert module_path == "Bridge.Characters.SmallAnimations.DBEConsoleInteraction"

    clips = build_sequence_clips(module_path, engineer, App.g_kAnimationManager)

    assert clips, "the gesture builder must resolve at least one clip"
    for path, _duration in clips:
        basename = path.rsplit("/", 1)[-1]
        assert "." in basename, (
            "unloadable clip path (no file extension) - this is exactly the "
            "console-gesture bug: %r" % (path,)
        )

    App.g_kSetManager._sets.clear()
    from engine.core.game import _set_current_game
    _set_current_game(None)
