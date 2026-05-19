"""Tests for the _dauntless_host.set_suns binding."""
import os


def test_set_suns_empty_list_does_not_raise():
    import _dauntless_host
    _dauntless_host.set_suns([])


def test_set_suns_single_descriptor_does_not_raise():
    import _dauntless_host
    _dauntless_host.set_suns([{
        "position":          (0.0, 0.0, 0.0),
        "radius":            4000.0,
        "base_texture_path": "/dev/null",
        "corona_radius":     8000.0,
    }])


def test_set_suns_many_descriptors_does_not_raise():
    import _dauntless_host
    descriptor = {
        "position":          (100.0, 200.0, 300.0),
        "radius":            1000.0,
        "base_texture_path": "/dev/null",
        "corona_radius":     2000.0,
    }
    _dauntless_host.set_suns([descriptor] * 5)


def test_renderer_module_set_suns_wrapper_exists():
    from engine import renderer
    assert hasattr(renderer, "set_suns")
    renderer.set_suns([])


def test_frame_after_set_suns_does_not_crash():
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    import _dauntless_host
    _dauntless_host.init(64, 64, "test_sun_bindings")
    try:
        _dauntless_host.set_suns([{
            "position":          (0.0, 0.0, 0.0),
            "radius":            4000.0,
            "base_texture_path": "/dev/null",
            "corona_radius":     8000.0,
        }])
        _dauntless_host.set_camera(
            eye=(0.0, 0.0, 10000.0),
            target=(0.0, 0.0, 0.0),
            up=(0.0, 1.0, 0.0),
            fov_y_rad=1.0472,
            near=1.0,
            far=200000.0,
        )
        _dauntless_host.frame()   # must not crash or raise
    finally:
        _dauntless_host.shutdown()
