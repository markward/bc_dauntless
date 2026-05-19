"""Robustness checks on frame() — multiple sizes and a headless framebuffer
readback that asserts the M1 Basic ship gate actually produces non-black
pixels."""
import os
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
GALAXY_NIF = PROJECT_ROOT / "game" / "data" / "Models" / "Ships" / "Galaxy" / "Galaxy.nif"
GALAXY_TEX = PROJECT_ROOT / "game" / "data" / "Models" / "SharedTextures" / "FedShips" / "High"


def _headless():
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"


def test_frame_works_at_multiple_sizes():
    """Init/frame/shutdown cycles at several sizes. Proves frame()'s
    glViewport / aspect-update path is robust across dimensions including
    very small (64x64), square (256x256), and 16:9 (1280x720)."""
    _headless()
    import _dauntless_host
    for w, h in [(64, 64), (256, 256), (800, 600), (1280, 720)]:
        try:
            _dauntless_host.init(w, h, f"size-{w}x{h}")
        except RuntimeError as e:
            pytest.skip(f"no GL context available: {e}")
        try:
            fw, fh = _dauntless_host.framebuffer_size()
            assert fw > 0 and fh > 0, f"framebuffer_size returned ({fw}, {fh}) at requested ({w}, {h})"
            for _ in range(3):
                _dauntless_host.frame()
        finally:
            _dauntless_host.shutdown()


def test_zero_height_aspect_guard():
    """The frame() body has `if (fh > 0) g_camera.aspect = ...` to avoid
    a divide-by-zero on minimized windows. We can't easily produce a
    zero-height framebuffer in a test, but we can at least confirm the
    binding path runs cleanly at the smallest non-zero size and that
    framebuffer_size is consistent with set_camera being safe to call."""
    _headless()
    import _dauntless_host
    try:
        _dauntless_host.init(8, 8, "tiny")
    except RuntimeError as e:
        pytest.skip(f"no GL context: {e}")
    try:
        fw, fh = _dauntless_host.framebuffer_size()
        assert fw > 0 and fh > 0
        _dauntless_host.set_camera(
            eye=(0, 0, 1), target=(0, 0, 0), up=(0, 1, 0),
            fov_y_rad=1.0472, near=0.1, far=100.0,
        )
        _dauntless_host.frame()
    finally:
        _dauntless_host.shutdown()


def test_clear_color_visible_in_back_buffer():
    """Headless smoke: frame() with no instances should leave the back
    buffer at the documented dark-blue clear color (0.05, 0.07, 0.10).
    Reads the center pixel via the read_pixel binding."""
    _headless()
    import _dauntless_host
    try:
        _dauntless_host.init(64, 64, "clear-readback")
    except RuntimeError as e:
        pytest.skip(f"no GL context: {e}")
    try:
        _dauntless_host.frame()
        # The clear color is (0.05, 0.07, 0.10, 1.0) — converted to
        # 8-bit unsigned that's roughly (12, 17, 25, 255). Allow some
        # driver-side dithering / gamma slack.
        r, g, b, a = _dauntless_host.read_pixel(32, 32)
        assert a == 255, f"alpha should be opaque, got {a}"
        assert 5 < r < 25, f"red channel outside expected clear-color range: {r}"
        assert 8 < g < 30, f"green channel outside expected clear-color range: {g}"
        assert 15 < b < 40, f"blue channel outside expected clear-color range: {b}"
    finally:
        _dauntless_host.shutdown()


def test_m1_basic_ship_gate_renders_non_black():
    """Headless equivalent of the visible ship gate: boot the M1 Basic
    mission via host_loop, render a frame, read pixels around the center,
    assert at least some are non-clear-color (i.e., the Galaxy actually
    drew something on top of the background)."""
    if not GALAXY_NIF.is_file():
        pytest.skip(f"BC asset not available at {GALAXY_NIF}")
    if not GALAXY_TEX.is_dir():
        pytest.skip(f"BC texture dir not available at {GALAXY_TEX}")
    _headless()
    import _dauntless_host
    try:
        _dauntless_host.init(256, 256, "ship-gate-readback")
    except RuntimeError as e:
        pytest.skip(f"no GL context: {e}")
    try:
        h = _dauntless_host.load_model(str(GALAXY_NIF), str(GALAXY_TEX))
        iid = _dauntless_host.create_instance(h)
        _dauntless_host.set_world_transform(iid, [
            1.0, 0.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            0.0, 0.0, 0.0, 1.0,
        ])
        _dauntless_host.set_camera(
            eye=(0.0, 0.0, 1500.0), target=(0.0, 0.0, 0.0), up=(0.0, 1.0, 0.0),
            fov_y_rad=1.0472, near=1.0, far=10000.0,
        )
        _dauntless_host.frame()

        # Sample a 5x5 grid around the center. The Galaxy should occupy
        # roughly the center of the viewport; at least one sample should
        # differ meaningfully from the dark-blue clear color.
        # Clear-color is approximately r<25 g<30 b<40; ship-rendered
        # pixels are illuminated (white-fallback texture) so r,g,b are
        # all much higher.
        ship_pixels = 0
        textured_pixels = 0
        fw, fh = _dauntless_host.framebuffer_size()
        cx, cy = fw // 2, fh // 2
        step = max(1, min(fw, fh) // 20)
        for dx in (-2 * step, -step, 0, step, 2 * step):
            for dy in (-2 * step, -step, 0, step, 2 * step):
                r, g, b, _ = _dauntless_host.read_pixel(cx + dx, cy + dy)
                # Anything brighter than the clear color counts as ship.
                if r > 60 or g > 60 or b > 80:
                    ship_pixels += 1
                # White-fallback texture produces near-grey pixels (R≈G≈B).
                # Real BC textures have meaningful per-channel variation.
                # Accept anything where the channels differ by more than ~12
                # as evidence of real texturing (modulo lighting on a
                # neutral-diffuse material, channels would still drift).
                channel_spread = max(r, g, b) - min(r, g, b)
                if (r > 60 or g > 60 or b > 80) and channel_spread > 12:
                    textured_pixels += 1
        assert ship_pixels > 0, (
            f"no ship pixels found around center; framebuffer is just clear color. "
            f"This means the Galaxy didn't render — investigate FrameSubmitter, "
            f"shaders, or scene-graph wiring before treating as a flake."
        )
        assert textured_pixels > 0, (
            f"all {ship_pixels} ship pixels are near-grey — looks like the "
            f"white-fallback texture is being used instead of the real BC "
            f"textures. Investigate material→texture linkage in "
            f"assets::material_build."
        )
    finally:
        _dauntless_host.shutdown()
