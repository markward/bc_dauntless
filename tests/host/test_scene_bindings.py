"""Verify scene-graph + camera bindings round-trip through pybind11."""
import os
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
DOOR_NIF = PROJECT_ROOT / "game" / "data" / "Animations" / "DB_door_L1.NIF"


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


def test_destroy_instance_stale_id_does_not_purge_a_recycled_instance():
    """destroy_instance purges bridge node-anim state keyed on id.index -- but
    g_world.destroy_instance silently no-ops on a stale id (index recycled by
    a newer generation). Before the fix the purge ran UNCONDITIONALLY, so a
    double-destroy on a stale id whose index a live instance has since
    recycled would wipe that live instance's node-anim clips out from under
    it. Regression: destroy the SAME (now-stale) id a second time, after its
    index has been recycled by a new instance with an active clip, and prove
    the new instance's clip survives."""
    if not DOOR_NIF.is_file():
        pytest.skip(f"BC asset not available at {DOOR_NIF}")
    import _dauntless_host

    old = _dauntless_host.create_instance(0)
    _dauntless_host.destroy_instance(old)              # frees old.index

    new = _dauntless_host.create_instance(0)           # recycles old.index (LIFO free list)
    assert new.index == old.index
    assert new.generation != old.generation

    _dauntless_host.play_instance_node_clip(new, str(DOOR_NIF), False, False)
    assert _dauntless_host._debug_bridge_node_anim_active_count(new.index) == 1

    _dauntless_host.destroy_instance(old)              # stale: must be a no-op
    assert _dauntless_host._debug_bridge_node_anim_active_count(new.index) == 1, \
        "a stale double-destroy must not purge the recycled instance's clip"

    _dauntless_host.destroy_instance(new)


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
