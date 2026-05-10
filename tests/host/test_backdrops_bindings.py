"""Tests for the _open_stbc_host.set_backdrops binding."""
import os


def test_set_backdrops_empty_list_does_not_raise():
    import _open_stbc_host
    _open_stbc_host.set_backdrops([])


def test_set_backdrops_single_star_descriptor_does_not_raise():
    import _open_stbc_host
    _open_stbc_host.set_backdrops([{
        "texture_path": "/dev/null",  # no init() yet → texture load deferred
        "kind": "star",
        "h_tile": 22.0, "v_tile": 11.0,
        "h_span": 1.0, "v_span": 1.0,
        "world_rotation": [1, 0, 0, 0, 1, 0, 0, 0, 1],
        "target_poly_count": 256,
    }])


def test_set_backdrops_many_descriptors_does_not_raise():
    import _open_stbc_host
    descriptor = {
        "texture_path": "/dev/null",
        "kind": "backdrop",
        "h_tile": 1.0, "v_tile": 1.0,
        "h_span": 1.0, "v_span": 1.0,
        "world_rotation": [1, 0, 0, 0, 1, 0, 0, 0, 1],
        "target_poly_count": 256,
    }
    _open_stbc_host.set_backdrops([descriptor] * 10)


def test_renderer_module_set_backdrops_wrapper_exists():
    from engine import renderer
    assert hasattr(renderer, "set_backdrops")
    renderer.set_backdrops([])
