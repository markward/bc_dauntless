# tests/integration/test_world_to_body_binding.py
"""world_to_body host binding — world hit point -> ship body frame.

Skips when the native module or BC assets are unavailable (matches the
renderer test suite's asset gating).
"""
import math
import os
from pathlib import Path

import pytest

_host = pytest.importorskip("_dauntless_host")

PROJECT_ROOT = Path(__file__).parent.parent.parent
GALAXY_NIF = PROJECT_ROOT / "game" / "data" / "Models" / "Ships" / "Galaxy" / "Galaxy.nif"
GALAXY_TEX = PROJECT_ROOT / "game" / "data" / "Models" / "SharedTextures" / "FedShips" / "High"


def _ensure_init():
    """Init the host in headless mode if not already up."""
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    if not hasattr(_host, "init"):
        pytest.skip("host lacks init binding")
    _host.init(1, 1, "test_world_to_body")


def test_world_to_body_round_trips_under_translation():
    if not hasattr(_host, "load_model") or not hasattr(_host, "create_instance"):
        pytest.skip("host lacks model-load bindings")
    if not GALAXY_NIF.is_file() or not GALAXY_TEX.is_dir():
        pytest.skip("Galaxy NIF not available")

    _ensure_init()
    try:
        handle = _host.load_model(str(GALAXY_NIF), str(GALAXY_TEX))
        iid = _host.create_instance(handle)

        # Identity rotation, translate ship to (100, 0, 0).
        # Row-major layout (matches set_world_transform's expected form;
        # translation in the last column of the top-left 3x4 block).
        world = [1.0, 0.0, 0.0, 100.0,
                 0.0, 1.0, 0.0, 0.0,
                 0.0, 0.0, 1.0, 0.0,
                 0.0, 0.0, 0.0, 1.0]
        _host.set_world_transform(iid, world)

        res = _host.world_to_body(
            instance_id=iid, world_point=(110.0, 0.0, 0.0),
            world_normal=(1.0, 0.0, 0.0))
        assert res is not None
        body_pt, body_nrm = res
        # With identity rotation and unit scale, body point = world - translation.
        assert body_pt[0] == pytest.approx(10.0, abs=1e-4)
        assert body_pt[1] == pytest.approx(0.0, abs=1e-4)
        # Direction is translation-invariant and length-normalised.
        n = math.sqrt(sum(c * c for c in body_nrm))
        assert n == pytest.approx(1.0, abs=1e-4)
    finally:
        _host.shutdown()


def test_world_to_body_stale_id_returns_none():
    """A destroyed instance returns None rather than crashing."""
    if not hasattr(_host, "load_model") or not hasattr(_host, "create_instance"):
        pytest.skip("host lacks model-load bindings")
    if not GALAXY_NIF.is_file() or not GALAXY_TEX.is_dir():
        pytest.skip("Galaxy NIF/tex not available — cannot obtain a typed InstanceId")

    _ensure_init()
    try:
        handle = _host.load_model(str(GALAXY_NIF), str(GALAXY_TEX))
        stale = _host.create_instance(handle)
        _host.destroy_instance(stale)

        result = _host.world_to_body(
            instance_id=stale,
            world_point=(0.0, 0.0, 0.0),
            world_normal=(1.0, 0.0, 0.0))
        assert result is None
    finally:
        _host.shutdown()
