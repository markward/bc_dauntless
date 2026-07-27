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


def _glow_grid(host, cx, cy):
    """Full sampled pixel grid (r+g+b per sample) — for byte-identical compares."""
    grid = []
    for dx in range(-60, 61, 2):
        for dy in range(-40, 41, 2):
            r, g, b, _ = host.read_pixel(cx + dx, cy + dy)
            grid.append(r + g + b)
    return tuple(grid)


def test_box_region_accepts_identity_orientation():
    """add_box_region takes optional forward/up; an identity-oriented box lights
    a point inside it (brightens the glow) like the 2-arg box, and — rendered
    against a matching instance in the SAME session — is byte-identical to the
    axis-aligned box (R = I). Two separate host sessions are NOT deterministic
    (GL lifecycle), so both variants are compared inside one session using two
    instances toggled by set_visible."""
    if not GALAXY_NIF.is_file() or not GALAXY_TEX.is_dir():
        pytest.skip("BC assets not available")
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    import _dauntless_host as H
    H.init(640, 360, "test_box_glow")
    XFORM = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
    HALF = (5000.0, 5000.0, 5000.0)
    try:
        h = H.load_model(str(GALAXY_NIF), str(GALAXY_TEX))
        iid_ax = H.create_instance(h)   # legacy 2-arg (axis-aligned) box
        iid_id = H.create_instance(h)   # 4-arg identity-oriented box
        for iid in (iid_ax, iid_id):
            H.set_world_transform(iid, XFORM)
        H.set_camera(eye=(0.0, 0.0, 1500.0), target=(0.0, 0.0, 0.0),
                     up=(0.0, 1.0, 0.0), fov_y_rad=1.0472, near=1.0, far=100000.0)
        H.set_lighting((0.0, 0.0, 0.0), [])

        i_ax = H.add_box_region(iid_ax, (0.0, 0.0, 0.0), HALF)
        i_id = H.add_box_region(iid_id, (0.0, 0.0, 0.0), HALF,
                                (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
        assert i_ax >= 0 and i_id >= 0
        H.set_glow_region_gain(iid_ax, i_ax, 2.5, (0.0, 0.0, 0.0))
        H.set_glow_region_gain(iid_id, i_id, 2.5, (0.0, 0.0, 0.0))

        fw, fh = H.framebuffer_size()
        cx, cy = fw // 2, fh // 2

        # Baseline: no glow region visible.
        H.set_visible(iid_ax, False)
        H.set_visible(iid_id, False)
        H.frame()
        baseline = _max_glow(H, cx, cy)

        # Axis-aligned box only. Grab two consecutive frames to measure the
        # renderer's own frame-to-frame temporal dither (the noise floor below
        # which "byte-identical" is unobservable).
        H.set_visible(iid_ax, True)
        H.frame()
        grid_ax1 = _glow_grid(H, cx, cy)
        H.frame()
        grid_ax2 = _glow_grid(H, cx, cy)
        boost_ax = _max_glow(H, cx, cy)
        self_noise = max(abs(a - b) for a, b in zip(grid_ax1, grid_ax2))

        # Identity-oriented box only (same model, same transform). With R = I the
        # shader's body->box rotation is a no-op, so this must match the
        # axis-aligned box to within that temporal-noise floor.
        H.set_visible(iid_ax, False)
        H.set_visible(iid_id, True)
        H.frame()
        boost_id = _max_glow(H, cx, cy)
        grid_id = _glow_grid(H, cx, cy)
        id_vs_ax = max(abs(a - b) for a, b in zip(grid_id, grid_ax2))

        assert boost_id > baseline, (
            f"identity-oriented box gain did not brighten glow "
            f"(baseline={baseline}, boosted={boost_id})")
        # Identity orientation must not shift the lit region beyond the renderer's
        # own frame-to-frame noise (a broken R would clip/shift fragments and blow
        # this budget). Small absolute floor guards a near-zero measured noise.
        budget = max(self_noise * 3, 15)
        assert id_vs_ax <= budget, (
            f"identity-oriented box diverges from the axis-aligned box "
            f"(max per-sample diff {id_vs_ax} > budget {budget}, "
            f"self_noise {self_noise}) — R != I for the identity basis?")
    finally:
        H.destroy_instance(iid_ax)
        H.destroy_instance(iid_id)
        H.shutdown()
        os.environ.pop("OPEN_STBC_HOST_HEADLESS", None)


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
