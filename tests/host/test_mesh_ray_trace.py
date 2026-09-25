"""Binding-level tests for _dauntless_host.ray_trace_mesh against a real
Galaxy NIF. The pure C++ algorithm is unit-tested with synthetic models
in native/tests/renderer/ray_trace_test.cc; this file validates the
Python<->C++ marshalling and the scenegraph/model lookup path.
"""
import os

import pytest

from tests.helpers import bc_assets

GALAXY_NIF = bc_assets.GAME_ROOT / "data" / "Models" / "Ships" / "Galaxy" / "Galaxy.nif"
GALAXY_TEX = bc_assets.GAME_ROOT / "data" / "Models" / "SharedTextures" / "FedShips" / "High"


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
    # Move the Galaxy out by +500 in x. The ray is INSTANCE-RELATIVE (world
    # origin minus the instance's translation), and so is the hit it returns.
    h.set_world_transform(iid, _translation_mat(500.0, 0.0, 0.0))
    tx, ty, tz = h.instance_translation(iid)
    assert (tx, ty, tz) == (500.0, 0.0, 0.0)
    # World ray along +z at x=0 -> 500 to the ship's left: misses.
    miss = h.ray_trace_mesh(iid,
                            origin=(0.0 - tx, 0.0 - ty, -1000.0 - tz),
                            direction=(0.0, 0.0, 1.0),
                            max_dist=2000.0)
    assert miss is None
    # World ray at x=500 goes through the ship's centre: hits.
    hit = h.ray_trace_mesh(iid,
                           origin=(500.0 - tx, 0.0 - ty, -1000.0 - tz),
                           direction=(0.0, 0.0, 1.0),
                           max_dist=2000.0)
    assert hit is not None
    point, _, _ = hit
    assert abs(point[0] + tx - 500.0) < 1.0


def test_a_million_gu_out_the_relative_hit_matches_the_origin_hit(galaxy_instance):
    """The floating render origin: a Galaxy at game scale 1e6 + 0.3 GU out
    (float32 carries only 1/16 GU there) returns the same instance-relative
    hit as the same Galaxy at the origin, to 1e-4 GU."""
    h, iid = galaxy_instance
    s = 0.0055                      # NIF units -> GU for a Galaxy (~3.6 GU)
    origin_rel = (0.013, 0.021, -10.0)
    direction = (0.0, 0.0, 1.0)

    def scaled_at(x):
        return [s, 0.0, 0.0, x,
                0.0, s, 0.0, 0.0,
                0.0, 0.0, s, 0.0,
                0.0, 0.0, 0.0, 1.0]

    h.set_world_transform(iid, scaled_at(0.0))
    near = h.ray_trace_mesh(iid, origin_rel, direction, 20.0)
    h.set_world_transform(iid, scaled_at(1e6 + 0.3))
    assert h.instance_translation(iid)[0] == 1e6 + 0.3
    far = h.ray_trace_mesh(iid, origin_rel, direction, 20.0)
    assert near is not None and far is not None
    assert far[0] == pytest.approx(near[0], abs=1e-4)
    assert far[1] == pytest.approx(near[1], abs=1e-4)
    assert far[2] == pytest.approx(near[2], abs=1e-4)


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
