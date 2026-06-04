"""Test that the glow/emissive pass adds light to a zero-ambient render.

Galaxy.nif's NiImages reference Ent-D_*_glow.tga files directly (BC's
AddLOD "_glow" suffix convention). model_build.cc detects the suffix and
routes those textures into Material::StageSlot::Glow; with ambient=0 and
no directionals, those glow pixels are the only contributors.
"""
import os
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
GALAXY_NIF = PROJECT_ROOT / "game" / "data" / "Models" / "Ships" / "Galaxy" / "Galaxy.nif"
GALAXY_TEX = PROJECT_ROOT / "game" / "data" / "Models" / "SharedTextures" / "FedShips" / "High"


def test_glow_contributes_to_unlit_frame():
    if not GALAXY_NIF.is_file():
        pytest.skip(f"BC asset not available at {GALAXY_NIF}")
    if not GALAXY_TEX.is_dir():
        pytest.skip(f"BC texture dir not available at {GALAXY_TEX}")

    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    import _dauntless_host

    _dauntless_host.init(640, 360, "test_glow_unlit")
    try:
        h = _dauntless_host.load_model(str(GALAXY_NIF), str(GALAXY_TEX))
        iid = _dauntless_host.create_instance(h)
        _dauntless_host.set_world_transform(iid, [
            1.0, 0.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            0.0, 0.0, 0.0, 1.0,
        ])
        _dauntless_host.set_camera(
            eye=(0.0, 0.0, 1500.0),
            target=(0.0, 0.0, 0.0),
            up=(0.0, 1.0, 0.0),
            fov_y_rad=1.0472,
            near=1.0,
            far=100000.0,
        )

        _dauntless_host.set_lighting((0.0, 0.0, 0.0), [])
        _dauntless_host.frame()

        fw, fh = _dauntless_host.framebuffer_size()
        cx, cy = fw // 2, fh // 2

        # Glow contributions on the Galaxy are tiny window-strip / engine
        # highlights — 1–2 px clusters. A coarse stride misses them between
        # samples; step 2 reliably catches at least one.
        max_brightness = 0
        for dx in range(-60, 61, 2):
            for dy in range(-40, 41, 2):
                r, g, b, _ = _dauntless_host.read_pixel(cx + dx, cy + dy)
                max_brightness = max(max_brightness, r + g + b)

        assert max_brightness > 80, (
            f"Expected glow to illuminate at least one sampled pixel above "
            f"background level (~57) with zero ambient lighting; "
            f"max r+g+b across saucer region = {max_brightness}."
        )
    finally:
        _dauntless_host.destroy_instance(iid)
        _dauntless_host.shutdown()
        os.environ.pop("OPEN_STBC_HOST_HEADLESS", None)
