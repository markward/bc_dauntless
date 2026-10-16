"""hull_volume_prewarm_model bakes a hull volume from a model handle alone.

No instance may be created: the warp-tunnel preload runs before the ship is
realised. The no-instance check uses instance-id sequencing (the facade
exposes no instance count). The bake itself is observed through the on-disk
.dhv in a SUBPROCESS: the host's hull-volume cache is a process singleton
that freezes its root on first use, so an in-process run is order-dependent.
"""
import os
import subprocess
import sys
import textwrap

import pytest

pytest.importorskip("_dauntless_host")
import _dauntless_host as h  # noqa: E402
from engine import paths  # noqa: E402
from tests.helpers import bc_assets  # noqa: E402


@pytest.fixture(scope="module")
def host():
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    try:
        h.init(64, 64, "test_hull_volume_prewarm_model_gl")
    except RuntimeError as e:
        pytest.skip(f"no GL context: {e}")
    try:
        yield h
    finally:
        h.shutdown()


def test_prewarm_model_creates_no_instance(host, tmp_path):
    nif = bc_assets.require_game_asset("data/Models/Ships/Shuttle/Shuttle.nif")
    search = [str(p) for p in paths.game_asset_dirs("data/Models/Ships/Shuttle")]
    host.hull_volume_set_cache_root(str(tmp_path))
    model = host.load_model(str(nif), search)

    probe_before = host.create_instance(model)
    host.hull_volume_prewarm_model(model, 6.0)
    probe_after = host.create_instance(model)
    # No hidden instance between the probes: slots are handed out in order.
    assert probe_after.index == probe_before.index + 1


_CHILD = textwrap.dedent("""
    import os, sys
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    import _dauntless_host as h
    from engine import paths
    nif, root, res = sys.argv[1], sys.argv[2], float(sys.argv[3])
    search = [str(p) for p in paths.game_asset_dirs("data/Models/Ships/Shuttle")]
    h.init(64, 64, "prewarm-model-child")
    try:
        h.hull_volume_set_cache_root(root)
        model = h.load_model(nif, search)
        h.hull_volume_prewarm_model(999999, res)   # unknown handle: no-op
        h.hull_volume_prewarm_model(model, 0.0)    # non-positive: no-op
        n0 = len([f for _, _, fs in os.walk(root) for f in fs if f.endswith(".dhv")])
        h.hull_volume_prewarm_model(model, res)
        n1 = len([f for _, _, fs in os.walk(root) for f in fs if f.endswith(".dhv")])
        print("DHV", n0, n1)
    finally:
        h.shutdown()
""")


def test_prewarm_model_bakes_dhv_and_noops_are_silent(host, tmp_path):
    nif = bc_assets.require_game_asset("data/Models/Ships/Shuttle/Shuttle.nif")
    root = os.path.dirname(os.path.abspath(h.__file__))
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(
        [root, os.getcwd()]))
    out = subprocess.run(
        [sys.executable, "-c", _CHILD, str(nif), str(tmp_path), "6.0"],
        env=env, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    assert "DHV 0 1" in out.stdout, out.stdout[-500:]
