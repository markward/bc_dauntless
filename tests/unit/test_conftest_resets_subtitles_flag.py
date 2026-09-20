"""The per-test reset must restore crew_speech's subtitles flag.

engine.appc.crew_speech._subtitles_enabled is a module-level scalar that
host_loop.run() sets from the user's real settings.json (via
settings_store.apply_all). tests/host/test_host_loop_lighting.py::
test_verbose_mode_logs_lighting_on_tick0 boots the real host loop, so on a
machine whose settings.json says "subtitles": false every later subtitle /
crew-speech test in the session saw a disabled subtitle channel and failed
(17 tests, 2026-09-20) while passing in isolation. Two tests, ordered by
name, stand in for that pair here: the first flips the flag the way the
host boot does, the second asserts the autouse reset put it back."""
from engine.appc import crew_speech


def test_a_leaves_subtitles_disabled_like_a_host_boot_would():
    crew_speech.set_subtitles_enabled(False)
    assert crew_speech.subtitles_enabled() is False


def test_b_sees_subtitles_enabled_again():
    assert crew_speech.subtitles_enabled() is True, (
        "conftest._reset_leakable_engine_globals does not restore "
        "crew_speech._subtitles_enabled between tests")
