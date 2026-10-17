"""The impostor-atlas prefetch bindings against a real GL context.

far_prefetch_atlases starts decoding the far pass's atlases on worker threads;
far_pump_atlas_uploads(n) uploads at most n finished ones and returns how many
are still pending, so a warp can pay the decode during the tunnel. The decode,
budget and failure rules are pinned in native/tests/renderer/far_pass_test.cc
(FarPassPrefetchTest); this only checks the bindings reach the global pass.
"""
import os
import time

import pytest

pytest.importorskip("_dauntless_host")
import _dauntless_host as h  # noqa: E402

from engine import renderer  # noqa: E402
from engine.paths import PROJECT_ROOT  # noqa: E402

_MAJORS = os.path.join(PROJECT_ROOT, "native", "assets", "rocks", "majors")


def _entry(name: str) -> dict:
    d = os.path.join(_MAJORS, name)
    return {"albedo": os.path.join(d, "impostor_base.png"),
            "normal": os.path.join(d, "impostor_normal.png"),
            "avg_albedo": (0.5, 0.5, 0.5)}


def test_with_no_far_pass_prefetch_is_a_noop_and_pump_returns_zero():
    # No init() in this test: the host has no far pass.
    renderer.far_prefetch_atlases()
    assert renderer.far_pump_atlas_uploads(4) == 0


def test_prefetch_then_pump_drains_the_far_pass():
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    try:
        h.init(64, 64, "test_far_atlas_prefetch_gl")
    except RuntimeError as e:
        pytest.skip(f"no GL context: {e}")
    try:
        renderer.far_set_catalogue(
            [_entry("carbonaceous_01"), _entry("icy_01")], [])
        renderer.far_prefetch_atlases()
        assert renderer.far_pump_atlas_uploads(0) == 2, \
            "both atlases pending on the global far pass"
        deadline = time.monotonic() + 60.0
        while renderer.far_pump_atlas_uploads(1) > 0:
            assert time.monotonic() < deadline, "prefetch never finished"
            time.sleep(0.001)
        renderer.far_prefetch_atlases()
        assert renderer.far_pump_atlas_uploads(4) == 0, \
            "loaded atlases are not prefetched again"
    finally:
        renderer.far_set_catalogue([], [])
        h.shutdown()
