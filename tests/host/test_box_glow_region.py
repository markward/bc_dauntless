"""A Box glow region brightens the hull's glow inside a body-axis-aligned box.

Adds a box covering the whole ship with gain>1; the box inside-test must match
so the gain applies and the sampled glow gets brighter than the unlit baseline.
Guards the shader box branch + the native upload path against regression.
"""
import os
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
GALAXY_NIF = PROJECT_ROOT / "game" / "data" / "Models" / "Ships" / "Galaxy" / "Galaxy.nif"
GALAXY_TEX = PROJECT_ROOT / "game" / "data" / "Models" / "SharedTextures" / "FedShips" / "High"


def _max_glow(host, cx, cy):
    m = 0
    for dx in range(-60, 61, 2):
        for dy in range(-40, 41, 2):
            r, g, b, _ = host.read_pixel(cx + dx, cy + dy)
            m = max(m, r + g + b)
    return m


def test_box_region_gain_brightens_inside():
    if not GALAXY_NIF.is_file() or not GALAXY_TEX.is_dir():
        pytest.skip("BC assets not available")
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    import _dauntless_host as H
    H.init(640, 360, "test_box_glow")
    try:
        h = H.load_model(str(GALAXY_NIF), str(GALAXY_TEX))
        iid = H.create_instance(h)
        H.set_world_transform(iid, [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1])
        H.set_camera(eye=(0.0, 0.0, 1500.0), target=(0.0, 0.0, 0.0),
                     up=(0.0, 1.0, 0.0), fov_y_rad=1.0472, near=1.0, far=100000.0)
        H.set_lighting((0.0, 0.0, 0.0), [])
        H.frame()
        fw, fh = H.framebuffer_size()
        cx, cy = fw // 2, fh // 2
        baseline = _max_glow(H, cx, cy)

        idx = H.add_box_region(iid, (0.0, 0.0, 0.0), (5000.0, 5000.0, 5000.0))
        assert idx >= 0
        H.set_glow_region_gain(iid, idx, 2.5, (0.0, 0.0, 0.0))
        H.frame()
        boosted = _max_glow(H, cx, cy)

        assert boosted > baseline, (
            f"box gain did not brighten glow inside the box "
            f"(baseline={baseline}, boosted={boosted}) — box inside-test broken?")
    finally:
        H.destroy_instance(iid)
        H.shutdown()
        os.environ.pop("OPEN_STBC_HOST_HEADLESS", None)
