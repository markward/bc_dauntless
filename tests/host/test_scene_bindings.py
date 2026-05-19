"""Verify scene-graph + camera bindings round-trip through pybind11."""
import os


def test_instance_lifecycle_without_window():
    # No init() — these calls don't need a GL context yet.
    import _dauntless_host
    iid = _dauntless_host.create_instance(123)
    assert iid.generation > 0
    _dauntless_host.set_world_transform(iid, [
        1.0, 0.0, 0.0, 5.0,
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        0.0, 0.0, 0.0, 1.0,
    ])
    _dauntless_host.set_visible(iid, False)
    _dauntless_host.destroy_instance(iid)


def test_set_world_transform_rejects_wrong_length():
    import _dauntless_host
    import pytest
    iid = _dauntless_host.create_instance(0)
    try:
        with pytest.raises(RuntimeError):
            _dauntless_host.set_world_transform(iid, [0.0] * 12)
    finally:
        _dauntless_host.destroy_instance(iid)


def test_set_camera_does_not_raise():
    import _dauntless_host
    _dauntless_host.set_camera(
        eye=(0.0, 0.0, 5.0),
        target=(0.0, 0.0, 0.0),
        up=(0.0, 1.0, 0.0),
        fov_y_rad=1.0472,
        near=0.1,
        far=10000.0,
    )


def test_set_backdrops_does_not_raise():
    import _dauntless_host
    _dauntless_host.set_backdrops([])


def test_set_world_transform_rejects_wrong_length_after_init():
    """Validation must hold post-init too — the GL context is irrelevant
    to the length check, but a regression that bypasses it (e.g. a fast
    path added later) would only surface in this state."""
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    import _dauntless_host
    import pytest
    try:
        _dauntless_host.init(64, 64, "post-init-mat4-test")
    except RuntimeError as e:
        pytest.skip(f"no GL context available: {e}")
    iid = _dauntless_host.create_instance(0)
    try:
        with pytest.raises(RuntimeError):
            _dauntless_host.set_world_transform(iid, [0.0] * 12)
        with pytest.raises(RuntimeError):
            _dauntless_host.set_world_transform(iid, [0.0] * 17)
        with pytest.raises(RuntimeError):
            _dauntless_host.set_world_transform(iid, [])
    finally:
        _dauntless_host.destroy_instance(iid)
        _dauntless_host.shutdown()
