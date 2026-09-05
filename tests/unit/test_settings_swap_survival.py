"""Persisted settings must survive an in-process mission swap.

reset_sdk_globals() runs on every swap and its docstring asks that the list
be kept "in lockstep with what the SDK actually mutates" — so a future entry
could clear one of these and silently turn persistence back into session-only
state. Nothing else in the suite would catch that.

Covers the Python-side state only. The four pure-renderer flags (smaa, dust,
and the improved_space / camera_realism members) live in C++ with no headless
getter; their survival rests on reset_sdk_globals touching only
render_instances, plus a live check.

Spec: docs/superpowers/specs/2026-09-05-settings-persistence-design.md
"""
import math

from engine.appc import camera_shake, crew_speech, light_emitters
from engine.cameras.director import _CameraDirector
from engine.core import game as game_mod
from engine.host_loop import reset_sdk_globals


def test_reset_sdk_globals_preserves_persisted_settings():
    saved = (game_mod._difficulty,
             crew_speech._subtitles_enabled,
             crew_speech._annoying_dialogue_disabled,
             camera_shake.enabled(),
             light_emitters.enabled())
    director = _CameraDirector()
    try:
        # Dirty every piece of persisted Python-side state.
        game_mod.Game_SetDifficulty(2)
        crew_speech.set_subtitles_enabled(False)
        crew_speech.set_annoying_dialogue_disabled(False)
        camera_shake.set_enabled(False)
        light_emitters.set_enabled(False)
        director.set_fov(math.radians(25))

        reset_sdk_globals()

        assert game_mod.Game_GetDifficulty() == 2
        assert crew_speech.subtitles_enabled() is False
        assert crew_speech.annoying_dialogue_disabled() is False
        assert camera_shake.enabled() is False
        assert light_emitters.enabled() is False
        # NOTE: near-vacuous as written. `director` here is a LOCAL
        # _CameraDirector instance that reset_sdk_globals() holds no
        # reference to, and there is no module-level director for it to
        # reset — so this assertion cannot fail for the reason the module
        # docstring implies (that reset_sdk_globals might clobber a
        # persisted FOV). It only guards against a FUTURE regression where
        # reset_sdk_globals grows a module-level director default and resets
        # it unconditionally. Kept rather than deleted for that future case.
        assert director.fov_y_rad == math.radians(25)
    finally:
        # These are module globals; the conftest autouse reset does not cover
        # them, so leaving them dirty would pollute every later test.
        game_mod.Game_SetDifficulty(saved[0])
        crew_speech.set_subtitles_enabled(saved[1])
        crew_speech.set_annoying_dialogue_disabled(saved[2])
        camera_shake.set_enabled(saved[3])
        light_emitters.set_enabled(saved[4])
