"""End-to-end backdrop rendering tests.

Note: Pixel-readback tests on macOS GLFW hidden windows are unreliable —
the read_pixel binding samples GL_FRONT, but headless contexts on macOS
do not reliably present the BACK→FRONT swap, so the function returns
the buffer's initial state regardless of what we drew. Visible-window
runs show the backdrop correctly. Tests here exercise the wiring (no
crashes, descriptors flow through) and rely on visual smoke for the
actual rendered pixels.
"""
import os
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).parent.parent.parent
GAME = PROJECT_ROOT / "game"
GALAXY_NIF = GAME / "data" / "Models" / "Ships" / "Galaxy" / "Galaxy.nif"
STARS_TGA = GAME / "data" / "stars.tga"

_PIXEL_TESTS_RELIABLE = sys.platform != "darwin"


def _star_descriptor():
    return {
        "texture_path": str(STARS_TGA),
        "kind": "star",
        "h_tile": 22.0, "v_tile": 11.0,
        "h_span": 1.0, "v_span": 1.0,
        "world_rotation": [1, 0, 0, 0, 1, 0, 0, 0, 1],
        "target_poly_count": 256,
    }


def _setup_for_pixel_test():
    if not STARS_TGA.is_file():
        pytest.skip("BC assets not available")
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    import _dauntless_host
    _dauntless_host.init(640, 360, "test_backdrops_integration")
    # These are backdrop-plumbing tests, not filmic tests. The filmic pass adds
    # grain (frame-varying, so no exact pixel assertion can hold), a vignette
    # (so an "empty" frame is not uniform) and chromatic aberration. Off, an
    # empty frame is exactly flat and repeated renders are near-identical.
    _dauntless_host.filmic_set_enabled(False)
    _dauntless_host.set_camera(
        eye=(0.0, 0.0, 1500.0),
        target=(0.0, 0.0, 0.0),
        up=(0.0, 1.0, 0.0),
        fov_y_rad=1.0472, near=1.0, far=100000.0,
    )
    return _dauntless_host


@pytest.mark.skipif(not _PIXEL_TESTS_RELIABLE,
                    reason="macOS hidden GLFW windows do not present BACK→FRONT swaps")
def test_backdrop_overpaints_clear_color():
    """With the backdrop bound the rendered row must NOT match the empty-frame
    floor. The starfield is sparse black-with-stars drawn over a black clear,
    so binding it changes the row either way.

    The floor is asserted to be FLAT rather than equal to a constant. The old
    assertion demanded exactly 3648 (64 px x 57), which encoded two things that
    are not properties of this feature: that 0.10 * 255 = 25.5 rounds up (this
    GPU rounds it down, giving 56/px), and that no post-processing touches an
    empty frame (the HDR pass does, giving 53/px). Flatness is the property
    that actually means "nothing was drawn", and it holds on any driver.
    """
    h = _setup_for_pixel_test()
    try:
        # Establish the no-backdrop baseline.
        h.set_backdrops([])
        floor_row = _sample_row_values(h, 32)
        assert len(set(floor_row)) == 1, (
            f"empty-backdrop row should be a flat clear colour, got "
            f"{sorted(set(floor_row))}")
        floor = sum(floor_row)

        h.set_backdrops([_star_descriptor()])
        with_stars = sum(_sample_row_values(h, 32))
        assert with_stars != floor, (
            f"row sum unchanged after binding starfield ({with_stars}); "
            f"backdrop did not render")
    finally:
        h.shutdown()


def _sample_row_values(h, y: int) -> list:
    """The per-pixel channel sums across a horizontal stripe."""
    h.frame()
    h.frame()
    fw, _ = h.framebuffer_size()
    return [sum(h.read_pixel(i * (fw // 64), y)[:3]) for i in range(64)]


def _sample_grid(h, step: int = 8) -> list:
    """Channel sums over a grid covering the whole framebuffer.

    A single row is a poor sample of a sparse starfield: whether it happens to
    cross a bright star is luck, and differs per machine. 3600 samples make the
    measurement about the image rather than about one row's fortune.
    """
    h.frame()
    h.frame()
    fw, fh = h.framebuffer_size()
    return [sum(h.read_pixel(x, y)[:3])
            for y in range(0, fh, step) for x in range(0, fw, step)]


def _changed_pixels(a: list, b: list) -> int:
    return sum(1 for x, y in zip(a, b) if x != y)


def _settle_and_sample_row(h, y: int) -> int:
    """Render two frames before sampling to defeat headless-window
    double-buffer staleness — on macOS GLFW hidden windows, read_pixel
    on GL_FRONT can return the previous frame's contents until a second
    swap_buffers has cycled. Then walk a horizontal stripe and sum
    R+G+B channels. The stars texture is sparse so a 64-pixel stripe
    is more robust than a single-pixel sample."""
    h.frame()
    h.frame()
    fw, _ = h.framebuffer_size()
    total = 0
    for i in range(64):
        x = i * (fw // 64)
        r, g, b, _ = h.read_pixel(x, y)
        total += int(r) + int(g) + int(b)
    return total


@pytest.mark.skipif(not _PIXEL_TESTS_RELIABLE,
                    reason="macOS hidden GLFW windows do not present BACK→FRONT swaps")
def test_camera_rotation_changes_pixels_translation_does_not():
    """Rotation reference: rotating the camera 30 degrees about the up axis
    must change the rendered backdrop. Translation along the camera forward
    must NOT change it -- the backdrop is at infinity.

    Both are measured against a control: the same view rendered twice. That
    self-calibrates the noise floor per machine instead of hard-coding one.
    The previous absolute thresholds (>50 changed, <=10 unchanged) were tuned
    to whichever machine wrote them, and summed a single 64-pixel row across a
    sparse starfield -- a measurement dominated by whether that row happened to
    cross a bright star.
    """
    h = _setup_for_pixel_test()
    try:
        h.set_backdrops([_star_descriptor()])

        def look_at(eye, target):
            h.set_camera(eye=eye, target=target, up=(0.0, 1.0, 0.0),
                         fov_y_rad=1.0472, near=1.0, far=100000.0)

        baseline_view = ((0.0, 0.0, 1500.0), (0.0, 0.0, -1000.0))

        look_at(*baseline_view)
        baseline = _sample_grid(h)

        # Control: re-render the identical view. Anything that changes here is
        # noise, not camera movement.
        look_at(*baseline_view)
        noise = _changed_pixels(baseline, _sample_grid(h))

        # Translate forward 1000 units (camera moves toward origin).
        look_at((0.0, 0.0, 500.0), (0.0, 0.0, -1000.0))
        translated = _changed_pixels(baseline, _sample_grid(h))

        # Rotation: 30 degrees about the up axis from the baseline view.
        import math
        a = math.radians(30)
        look_at((0.0, 0.0, 1500.0),
                (math.sin(a) * -1000.0, 0.0, math.cos(a) * -1000.0))
        rotated = _changed_pixels(baseline, _sample_grid(h))

        assert rotated > 10 * max(noise, 8), (
            f"rotation should change the rendered starfield: {rotated} pixels "
            f"changed, against a same-view control of {noise}")
        assert translated <= max(4 * noise, 64), (
            f"translation along forward should not change an infinite "
            f"backdrop: {translated} pixels changed, control {noise}")
    finally:
        h.shutdown()


@pytest.mark.skipif(not _PIXEL_TESTS_RELIABLE,
                    reason="macOS hidden GLFW windows do not present BACK→FRONT swaps")
def test_lighting_still_works_with_backdrops():
    """Regression: opaque pass lighting must not be broken by the new
    backdrop pass. Reuses the existing red-vs-black ambient assertion."""
    if not GALAXY_NIF.is_file():
        pytest.skip("BC assets not available")
    h = _setup_for_pixel_test()
    try:
        h.set_backdrops([_star_descriptor()])
        tex_search = str(GAME / "data" / "Models" / "SharedTextures" /
                         "FedShips" / "High")
        m = h.load_model(str(GALAXY_NIF), tex_search)
        iid = h.create_instance(m)
        h.set_world_transform(iid, [
            1, 0, 0, 0,
            0, 1, 0, 0,
            0, 0, 1, 0,
            0, 0, 0, 1,
        ])
        fw, fh = h.framebuffer_size()
        cx, cy = fw // 2, fh // 2

        h.set_lighting((1.0, 0.0, 0.0), [])
        h.frame()
        red_r, _, _, _ = h.read_pixel(cx, cy)

        h.set_lighting((0.0, 0.0, 0.0), [])
        h.frame()
        dark_r, _, _, _ = h.read_pixel(cx, cy)

        assert red_r > dark_r + 50, (
            f"lighting regressed after backdrops added: red_r={red_r}, dark_r={dark_r}")

        h.destroy_instance(iid)
    finally:
        h.shutdown()
