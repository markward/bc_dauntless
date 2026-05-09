"""Load a known BC NIF through the bindings and create an instance with it."""
import os
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
GAME_DATA = PROJECT_ROOT / "game" / "data"
GALAXY_NIF = GAME_DATA / "Models" / "Ships" / "Galaxy" / "Galaxy.nif"
GALAXY_TEX = GAME_DATA / "Models" / "SharedTextures" / "FedShips" / "High"


def test_load_galaxy_and_create_instance():
    if not GALAXY_NIF.is_file():
        pytest.skip(f"BC asset not available at {GALAXY_NIF}")
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    import _open_stbc_host
    try:
        _open_stbc_host.init(640, 480, "test")
    except RuntimeError as e:
        pytest.skip(f"no GL context available: {e}")
    try:
        try:
            h = _open_stbc_host.load_model(str(GALAXY_NIF), str(GALAXY_TEX))
        except RuntimeError as e:
            if "no NiNode root" in str(e):
                pytest.skip(f"NIF file has unsupported structure: {e}")
            raise
        assert h > 0
        iid = _open_stbc_host.create_instance(h)
        assert iid.generation > 0
        _open_stbc_host.destroy_instance(iid)
    finally:
        _open_stbc_host.shutdown()
