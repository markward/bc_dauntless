"""End-to-end Phase C scene setup: load → instance → transform → camera → shutdown."""
import os
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
GALAXY_NIF = PROJECT_ROOT / "game" / "data" / "Models" / "Ships" / "Galaxy" / "Galaxy.nif"
GALAXY_TEX = PROJECT_ROOT / "game" / "data" / "Models" / "SharedTextures" / "FedShips" / "High"


def test_scene_setup_round_trip():
    if not GALAXY_NIF.is_file():
        pytest.skip(f"BC asset not available at {GALAXY_NIF}")
    if not GALAXY_TEX.is_dir():
        pytest.skip(f"BC texture dir not available at {GALAXY_TEX}")
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    import _open_stbc_host
    try:
        _open_stbc_host.init(800, 600, "scene-setup")
    except RuntimeError as e:
        pytest.skip(f"no GL context available: {e}")

    try:
        ship = _open_stbc_host.load_model(str(GALAXY_NIF), str(GALAXY_TEX))

        ids = []
        for x in (-50.0, 0.0, 50.0):
            iid = _open_stbc_host.create_instance(ship)
            _open_stbc_host.set_world_transform(iid, [
                1.0, 0.0, 0.0, x,
                0.0, 1.0, 0.0, 0.0,
                0.0, 0.0, 1.0, 0.0,
                0.0, 0.0, 0.0, 1.0,
            ])
            ids.append(iid)

        _open_stbc_host.set_camera(
            eye=(0.0, 30.0, 200.0),
            target=(0.0, 0.0, 0.0),
            up=(0.0, 1.0, 0.0),
            fov_y_rad=1.0472,
            near=1.0,
            far=10000.0,
        )

        # Phase C: no drawing yet. Exercise the frame() path to confirm
        # everything still teardowns cleanly.
        _open_stbc_host.frame()

        for iid in ids:
            _open_stbc_host.destroy_instance(iid)
    finally:
        _open_stbc_host.shutdown()


def test_set_backdrops_does_not_crash_in_frame():
    """Replaces the legacy skybox slot test. Drive the new backdrop API
    end-to-end through frame() to ensure the pass renders without GL
    errors when fed an empty descriptor list."""
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    import _open_stbc_host
    try:
        _open_stbc_host.init(256, 256, "backdrops-test")
    except RuntimeError as e:
        pytest.skip(f"no GL: {e}")
    try:
        _open_stbc_host.set_backdrops([])
        _open_stbc_host.set_camera(
            eye=(0, 0, 1500), target=(0, 0, 0), up=(0, 1, 0),
            fov_y_rad=1.0472, near=1.0, far=10000.0,
        )
        _open_stbc_host.frame()  # must not raise
    finally:
        _open_stbc_host.shutdown()
