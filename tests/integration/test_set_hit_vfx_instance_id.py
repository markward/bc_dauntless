# tests/integration/test_set_hit_vfx_instance_id.py
"""set_hit_vfx instance_id seam — accepts a scenegraph::InstanceId object.

Regression for the int->InstanceId type fix (A6 Defect 1): the descriptor's
`instance_id` field is now a scenegraph::InstanceId, so the host binding must
cast the Python InstanceId object, not an int. This test passes a real
InstanceId (from create_instance) plus spark fields and asserts set_hit_vfx
does not raise. set_hit_vfx only fills a vector (no GL), so it runs headless.

Skips when the native module or BC assets are unavailable (matches the
renderer test suite's asset gating).
"""
import os
from pathlib import Path

import pytest

_host = pytest.importorskip("_dauntless_host")

PROJECT_ROOT = Path(__file__).parent.parent.parent
GALAXY_NIF = PROJECT_ROOT / "game" / "data" / "Models" / "Ships" / "Galaxy" / "Galaxy.nif"
GALAXY_TEX = PROJECT_ROOT / "game" / "data" / "Models" / "SharedTextures" / "FedShips" / "High"


def _ensure_init():
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    if not hasattr(_host, "init"):
        pytest.skip("host lacks init binding")
    _host.init(1, 1, "test_set_hit_vfx_instance_id")


def test_set_hit_vfx_accepts_instance_id_object():
    if not hasattr(_host, "load_model") or not hasattr(_host, "create_instance"):
        pytest.skip("host lacks model-load bindings")
    if not hasattr(_host, "set_hit_vfx"):
        pytest.skip("host lacks set_hit_vfx binding")
    if not GALAXY_NIF.is_file() or not GALAXY_TEX.is_dir():
        pytest.skip("Galaxy NIF not available — cannot obtain a typed InstanceId")

    _ensure_init()
    try:
        handle = _host.load_model(str(GALAXY_NIF), str(GALAXY_TEX))
        iid = _host.create_instance(handle)

        # Carries a real InstanceId object in instance_id, plus spark fields.
        _host.set_hit_vfx([
            {
                "position": (0.0, 0.0, 0.0),
                "normal": (0.0, 1.0, 0.0),
                "severity": 2,
                "age": 0.05,
                "instance_id": iid,
                "body_point": (1.0, 2.0, 3.0),
                "body_normal": (0.0, 0.0, 1.0),
                "weapon_kind": 0,
                "spark_count": 6,
            }
        ])

        # None instance_id with no sparks must also be accepted.
        _host.set_hit_vfx([
            {
                "position": (0.0, 0.0, 0.0),
                "normal": (0.0, 1.0, 0.0),
                "severity": 1,
                "age": 0.05,
            }
        ])
    finally:
        _host.shutdown()
