"""The console-gesture clip-path bug, pinned end-to-end against the REAL SDK.

Bridge/Characters/CommonAnimations.py:647,655 (ConsoleSlide / PushingButtons)
register their gesture clip with a path built by string concatenation and NO
file extension:

    kAM.LoadAnimation("data/animations/" + pcAnimName, pcAnimName)

...while the file on disk is "DB_E_pushing_buttons_A.NIF". If the engine hands
that literal path to the loader, the clip never loads and the officers' console
gestures silently never play.

This drives the REAL SDK end to end (LoadBridge.Load("GalaxyBridge") + the real
Bridge.Characters.SmallAnimations.DBEConsoleInteraction gesture builder for the
Engineer's "PushingButtons" key) and asserts every clip path it produces is
LOADABLE once the host's asset resolver has had a look at it.

It asserts at the RESOLVER, not at the registry. It used to assert the registry
never held an extension-less path (by making AnimationManager first-write-wins);
that was the wrong mechanism and it broke E1M1's opening, because BC also
re-registers a name in order to CORRECT a typo - see
tests/unit/test_animation_manager.py::
test_a_later_registration_must_win_or_the_captains_sit_camera_breaks. The
registry faithfully keeps BC's last word, extension-less or not; tolerating a
missing extension is the FILE LOADER's job, exactly as in BC.
"""
from pathlib import Path

import App
import pytest

from engine.appc.bridge_placement import registered_module_path
from engine.bridge_idle_gestures import build_sequence_clips
from engine.host_loop import PROJECT_ROOT, _resolve_asset_path

from tests.integration.test_sdk_bridge_load import _fresh_world, _load_sdk_loadbridge

REAL_ANIMATIONS = PROJECT_ROOT / "game" / "data" / "animations"


def _engineer_pushing_buttons_clip_paths():
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

    App.g_kSetManager._sets.clear()
    from engine.core.game import _set_current_game
    _set_current_game(None)

    return [path for path, _duration in clips]


def test_the_sdk_really_does_register_an_extension_less_gesture_clip_path():
    # Pins the premise of the whole fix: this is BC's own content bug, it is
    # still live, and the registry deliberately does NOT paper over it.
    paths = _engineer_pushing_buttons_clip_paths()
    bare = [p for p in paths if "." not in p.rsplit("/", 1)[-1]]
    assert bare, (
        "expected CommonAnimations' console-gesture builder to register at "
        "least one extension-less path; got %r" % (paths,)
    )


def test_every_gesture_clip_path_resolves_to_a_loadable_file(tmp_path):
    # Stand up an asset tree holding each clip under the UPPERCASE ".NIF" the
    # shipped game uses, then assert the host resolver maps every SDK-produced
    # path - extension-less ones included - onto an existing file. (The real
    # game/ tree is gitignored and absent in CI, hence tmp_path; the test below
    # covers the real tree when it IS present.)
    paths = _engineer_pushing_buttons_clip_paths()

    anims = tmp_path / "data" / "animations"
    anims.mkdir(parents=True)
    for path in paths:
        name = path.rsplit("/", 1)[-1]
        stem = name.rsplit(".", 1)[0] if "." in name else name
        (anims / (stem + ".NIF")).write_bytes(b"")

    for path in paths:
        resolved = _resolve_asset_path(path, tmp_path)
        assert resolved is not None
        assert Path(resolved).exists(), (
            "unloadable clip path - this is exactly the console-gesture bug: "
            "%r -> %r" % (path, resolved)
        )


@pytest.mark.skipif(
    not REAL_ANIMATIONS.is_dir(),
    reason="game/ is gitignored and not present in this checkout",
)
def test_every_gesture_clip_path_resolves_against_the_real_game_tree():
    for path in _engineer_pushing_buttons_clip_paths():
        resolved = _resolve_asset_path(path, PROJECT_ROOT / "game")
        assert Path(resolved).exists(), (
            "unloadable clip path against the SHIPPED assets: %r -> %r"
            % (path, resolved)
        )
