"""The system-nebula table prebuild against a real GL context.

set_system_nebula_profile builds the far-field table on the main thread —
seconds in a Debug build, on every warp arrival. system_nebula_prebuild moves
that build to a worker so a warp can pay it during the tunnel; once
system_nebula_prebuilt says True, the push is only the texture upload.

This pays for ONE real build (the prebuild); the cache's own logic is covered
with a fake builder in native/tests/renderer/system_nebula_cache_test.cc.
"""
import os
import time

import pytest

pytest.importorskip("_dauntless_host")
import _dauntless_host as h  # noqa: E402

from engine import renderer  # noqa: E402


@pytest.fixture(scope="module")
def host():
    """A GL context for this module only.

    shutdown() in teardown is NOT optional: init() raises if the host is
    already initialised, so leaving the context up makes every later host
    test in the session fail at its own init().
    """
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    h.init(320, 180, "test_system_nebula_prebuild_gl")
    try:
        yield h
    finally:
        h.set_system_nebula_profile(None)
        h.shutdown()


def _three_row_profile() -> dict:
    # A k_sys no other test uses, so the session cache cannot already hold it.
    return {
        "r": [0.0, 60000.0, 240000.0],
        "nebula": [0.1, 1.0, 0.05],
        "k_sys": 1.2345e-5,
        "star_radius": 2000.0,
        "cloud_rgb": (0.6, 0.35, 0.7),
        "star_rgb": (1.0, 1.0, 1.0),
    }


def test_prebuild_returns_at_once_and_makes_the_push_cheap(host):
    d = _three_row_profile()

    t0 = time.perf_counter()
    renderer.system_nebula_prebuild(d)
    assert time.perf_counter() - t0 < 0.05, "prebuild must not build on the caller"

    deadline = time.monotonic() + 60.0
    while not renderer.system_nebula_prebuilt(d):
        assert time.monotonic() < deadline, "prebuild never finished"
        time.sleep(0.01)

    t0 = time.perf_counter()
    renderer.set_system_nebula_profile(d)
    assert time.perf_counter() - t0 < 0.2, "a prebuilt profile must not rebuild"
    assert host.system_nebula_has_profile()


def test_prebuilt_is_false_for_a_profile_never_built(host):
    d = _three_row_profile()
    d["k_sys"] = 9.876e-6
    assert renderer.system_nebula_prebuilt(d) is False


def test_prebuild_validates_rows(host):
    d = _three_row_profile()
    d["nebula"] = [0.1]
    with pytest.raises(ValueError):
        renderer.system_nebula_prebuild(d)
    with pytest.raises(ValueError):
        renderer.system_nebula_prebuilt(d)
