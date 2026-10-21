"""prewarm_trace_accel builds a model's ray-trace BVH from its MODEL handle.

The binding replaces the BVH half of the removed hull_volume_prewarm /
hull_volume_prewarm_model bindings (layered damage phase 4). Without it a
hull's BVH builds lazily on its first trace, in combat (perf-register
SIG-039/040: 7.7 ms on a station). The build is observed through the
test-only `_test_only_trace_accel_built` probe, so a binding that silently
did nothing would fail here.
"""
import os

import pytest

pytest.importorskip("_dauntless_host")
import _dauntless_host as h  # noqa: E402
from engine import paths  # noqa: E402
from tests.helpers import bc_assets  # noqa: E402


@pytest.fixture(scope="module")
def host():
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    try:
        h.init(64, 64, "test_prewarm_trace_accel_gl")
    except RuntimeError as e:
        pytest.skip(f"no GL context: {e}")
    try:
        yield h
    finally:
        h.shutdown()


def _shuttle(host):
    nif = bc_assets.require_game_asset("data/Models/Ships/Shuttle/Shuttle.nif")
    search = [str(p) for p in paths.game_asset_dirs("data/Models/Ships/Shuttle")]
    return host.load_model(str(nif), search)


def test_prewarm_builds_the_bvh_without_an_instance(host):
    model = _shuttle(host)
    assert not host._test_only_trace_accel_built(model)
    probe_before = host.create_instance(model)
    host.prewarm_trace_accel(model)
    probe_after = host.create_instance(model)
    assert host._test_only_trace_accel_built(model)
    # No hidden instance between the probes: slots are handed out in order.
    assert probe_after.index == probe_before.index + 1


def test_unknown_handle_is_a_silent_noop(host):
    host.prewarm_trace_accel(999999)
    assert not host._test_only_trace_accel_built(999999)
