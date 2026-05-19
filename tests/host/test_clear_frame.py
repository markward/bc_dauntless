"""Verify frame() executes a full opaque pass without raising."""
import os
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
GALAXY_NIF = PROJECT_ROOT / "game" / "data" / "Models" / "Ships" / "Galaxy" / "Galaxy.nif"
GALAXY_TEX = PROJECT_ROOT / "game" / "data" / "Models" / "SharedTextures" / "FedShips" / "High"


def test_frame_runs_opaque_pass():
    if not GALAXY_NIF.is_file():
        pytest.skip("BC asset not available")
    if not GALAXY_TEX.is_dir():
        pytest.skip("BC texture dir not available")
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    import _dauntless_host
    try:
        _dauntless_host.init(256, 256, "opaque-pass")
    except RuntimeError as e:
        pytest.skip(f"no GL context: {e}")
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
            eye=(0.0, 0.0, 1500.0), target=(0.0, 0.0, 0.0), up=(0.0, 1.0, 0.0),
            fov_y_rad=1.0472, near=1.0, far=10000.0,
        )
        for _ in range(3):
            _dauntless_host.frame()
    finally:
        _dauntless_host.shutdown()
