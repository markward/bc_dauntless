"""Load a known BC NIF through the bindings and create an instance with it."""
import os
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
GAME_DATA = PROJECT_ROOT / "game" / "data"
GALAXY_NIF = GAME_DATA / "Models" / "Ships" / "Galaxy" / "Galaxy.nif"
GALAXY_TEX = GAME_DATA / "Models" / "SharedTextures" / "FedShips" / "High"


def test_load_model_dedupes_by_nif_path():
    """Two load_model calls with the same nif_path return the same handle.
    Callers that fan out (e.g. host_loop creating one instance per ship of
    the same class) get a single underlying AssetCache load + a single
    public ModelHandle to share."""
    if not GALAXY_NIF.is_file():
        pytest.skip(f"BC asset not available at {GALAXY_NIF}")
    if not GALAXY_TEX.is_dir():
        pytest.skip(f"BC texture dir not available at {GALAXY_TEX}")
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    import _dauntless_host
    try:
        _dauntless_host.init(640, 480, "dedupe-test")
    except RuntimeError as e:
        pytest.skip(f"no GL context available: {e}")
    try:
        h1 = _dauntless_host.load_model(str(GALAXY_NIF), str(GALAXY_TEX))
        h2 = _dauntless_host.load_model(str(GALAXY_NIF), str(GALAXY_TEX))
        assert h1 == h2, f"load_model didn't dedupe: got {h1} and {h2}"
    finally:
        _dauntless_host.shutdown()


def test_load_galaxy_and_create_instance():
    if not GALAXY_NIF.is_file():
        pytest.skip(f"BC asset not available at {GALAXY_NIF}")
    if not GALAXY_TEX.is_dir():
        pytest.skip(f"BC texture dir not available at {GALAXY_TEX}")
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    import _dauntless_host
    try:
        _dauntless_host.init(640, 480, "test")
    except RuntimeError as e:
        pytest.skip(f"no GL context available: {e}")
    try:
        h = _dauntless_host.load_model(str(GALAXY_NIF), str(GALAXY_TEX))
        assert h > 0
        iid = _dauntless_host.create_instance(h)
        assert iid.generation > 0
        _dauntless_host.destroy_instance(iid)
    finally:
        _dauntless_host.shutdown()
