"""Binding-level tests for _dauntless_host.ray_trace_mesh against a real
Galaxy NIF. The pure C++ algorithm is unit-tested with synthetic models
in native/tests/renderer/ray_trace_test.cc; this file validates the
Python<->C++ marshalling and the scenegraph/model lookup path.
"""
import os
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
GALAXY_NIF = PROJECT_ROOT / "game" / "data" / "Models" / "Ships" / "Galaxy" / "Galaxy.nif"
GALAXY_TEX = PROJECT_ROOT / "game" / "data" / "Models" / "SharedTextures" / "FedShips" / "High"


def _identity_mat():
    return [1.0, 0.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            0.0, 0.0, 0.0, 1.0]


def _translation_mat(x, y, z):
    return [1.0, 0.0, 0.0, x,
            0.0, 1.0, 0.0, y,
            0.0, 0.0, 1.0, z,
            0.0, 0.0, 0.0, 1.0]


@pytest.fixture
def galaxy_instance():
    """Headless host with a single Galaxy at world origin; yields the
    (_dauntless_host module, InstanceId) and shuts down on teardown."""
    if not GALAXY_NIF.is_file():
        pytest.skip("BC asset not available")
    if not GALAXY_TEX.is_dir():
        pytest.skip("BC texture dir not available")
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    import _dauntless_host
    try:
        _dauntless_host.init(256, 256, "ray-trace-tests")
    except RuntimeError as e:
        pytest.skip(f"no GL context: {e}")
    try:
        h = _dauntless_host.load_model(str(GALAXY_NIF), str(GALAXY_TEX))
        iid = _dauntless_host.create_instance(h)
        _dauntless_host.set_world_transform(iid, _identity_mat())
        yield _dauntless_host, iid
    finally:
        _dauntless_host.shutdown()


def test_ray_through_center_returns_hit_on_or_near_hull(galaxy_instance):
    h, iid = galaxy_instance
    # Galaxy bounding sphere fits within ~300 units of origin; ray from
    # (0,0,-1000) along +z must hit somewhere on the hull at t < 1000.
    result = h.ray_trace_mesh(iid,
                              origin=(0.0, 0.0, -1000.0),
                              direction=(0.0, 0.0, 1.0),
                              max_dist=2000.0)
    assert result is not None, "Ray fired straight at Galaxy should produce a hit"
    point, normal, t = result
    assert 0.0 < t < 1000.0
    # Hit point and t consistent: point ≈ origin + dir * t.
    assert abs(point[0] - 0.0) < 1.0
    assert abs(point[1] - 0.0) < 1.0
    assert abs(point[2] - (-1000.0 + t)) < 1.0
    # Normal is unit length and faces the incoming ray (dot <= 0 with +z).
    nlen = (normal[0]**2 + normal[1]**2 + normal[2]**2) ** 0.5
    assert abs(nlen - 1.0) < 0.01
    assert normal[2] <= 0.01


def test_ray_far_from_ship_returns_none(galaxy_instance):
    h, iid = galaxy_instance
    # Ray parallel to +z at x=10000 is well outside the bounding sphere.
    result = h.ray_trace_mesh(iid,
                              origin=(10000.0, 10000.0, -100.0),
                              direction=(0.0, 0.0, 1.0),
                              max_dist=1000.0)
    assert result is None


def test_max_dist_clip_returns_none(galaxy_instance):
    h, iid = galaxy_instance
    # Aimed straight at Galaxy but capped before reaching it.
    result = h.ray_trace_mesh(iid,
                              origin=(0.0, 0.0, -1000.0),
                              direction=(0.0, 0.0, 1.0),
                              max_dist=10.0)
    assert result is None


def test_instance_world_transform_translates_hit(galaxy_instance):
    h, iid = galaxy_instance
    # Move the Galaxy out by +500 in x; the same ray (along +z at x=0) now
    # misses; a ray at x=500 hits.
    h.set_world_transform(iid, _translation_mat(500.0, 0.0, 0.0))
    miss = h.ray_trace_mesh(iid,
                            origin=(0.0, 0.0, -1000.0),
                            direction=(0.0, 0.0, 1.0),
                            max_dist=2000.0)
    assert miss is None
    hit = h.ray_trace_mesh(iid,
                           origin=(500.0, 0.0, -1000.0),
                           direction=(0.0, 0.0, 1.0),
                           max_dist=2000.0)
    assert hit is not None
    point, _, _ = hit
    assert abs(point[0] - 500.0) < 1.0


def test_invalid_instance_id_raises(galaxy_instance):
    h, iid = galaxy_instance
    # Create then immediately destroy a second instance; the stale id is
    # no longer alive in the world.
    model_h = h.load_model(str(GALAXY_NIF), str(GALAXY_TEX))
    stale = h.create_instance(model_h)
    h.destroy_instance(stale)
    with pytest.raises(RuntimeError):
        h.ray_trace_mesh(stale,
                         origin=(0.0, 0.0, 0.0),
                         direction=(0.0, 0.0, 1.0),
                         max_dist=10.0)
