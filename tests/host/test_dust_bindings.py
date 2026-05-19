"""Tests for the _dauntless_host.dust_set_enabled / dust_set_density bindings."""
import os


def test_dust_set_enabled_before_init_is_silent():
    import _dauntless_host
    # No init() yet — call should be a no-op, not a crash.
    _dauntless_host.dust_set_enabled(True)
    _dauntless_host.dust_set_enabled(False)


def test_dust_set_density_before_init_is_silent():
    import _dauntless_host
    _dauntless_host.dust_set_density(100)


def test_dust_toggle_after_init_does_not_crash():
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    import _dauntless_host
    _dauntless_host.init(64, 64, "test_dust_bindings")
    try:
        _dauntless_host.dust_set_enabled(False)
        _dauntless_host.dust_set_enabled(True)
        _dauntless_host.dust_set_density(1024)
        _dauntless_host.dust_set_density(0)
        _dauntless_host.dust_set_density(-5)        # clamped to 0 internally
        _dauntless_host.dust_set_density(10_000_000)  # clamped to 50000
    finally:
        _dauntless_host.shutdown()


def test_renderer_facade_exposes_dust_helpers():
    from engine import renderer
    assert hasattr(renderer, "set_dust_enabled")
    assert hasattr(renderer, "set_dust_density")


def test_renderer_facade_callable_after_init():
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    from engine import renderer
    renderer.init(64, 64, "test_dust_facade")
    try:
        renderer.set_dust_enabled(False)
        renderer.set_dust_enabled(True)
        renderer.set_dust_density(2048)
    finally:
        renderer.shutdown()


def test_frame_with_dust_disabled_does_not_crash():
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    import _dauntless_host
    _dauntless_host.init(64, 64, "test_dust_frame")
    try:
        _dauntless_host.dust_set_enabled(False)
        _dauntless_host.set_camera(
            eye=(0.0, 0.0, 100.0),
            target=(0.0, 0.0, 0.0),
            up=(0.0, 1.0, 0.0),
            fov_y_rad=1.0472,
            near=1.0,
            far=200000.0,
        )
        _dauntless_host.frame()
    finally:
        _dauntless_host.shutdown()


def test_key_f7_exposed():
    import _dauntless_host
    assert hasattr(_dauntless_host.keys, "KEY_F7")
