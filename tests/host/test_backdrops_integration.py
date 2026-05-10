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
    import _open_stbc_host
    _open_stbc_host.init(640, 360, "test_backdrops_integration")
    _open_stbc_host.set_camera(
        eye=(0.0, 0.0, 1500.0),
        target=(0.0, 0.0, 0.0),
        up=(0.0, 1.0, 0.0),
        fov_y_rad=1.0472, near=1.0, far=100000.0,
    )
    return _open_stbc_host


@pytest.mark.skipif(not _PIXEL_TESTS_RELIABLE,
                    reason="macOS hidden GLFW windows do not present BACK→FRONT swaps")
def test_backdrop_overpaints_clear_color():
    """With the backdrop bound the rendered row must NOT match the
    clear-color floor (64 px × 57 = 3648). The starfield is sparse
    black-with-stars: most pixels are darker than the clear color
    (texture sky is near-black) and stars push some pixels much
    brighter — either way the row sum departs from the floor.

    Compares against the no-backdrop baseline: empty backdrop list
    leaves the screen at clear color so its row sum is exactly 3648.
    Setting a backdrop must change that sum."""
    h = _setup_for_pixel_test()
    try:
        # Establish the no-backdrop baseline.
        h.set_backdrops([])
        floor = _settle_and_sample_row(h, 32)
        assert floor == 3648, (
            f"empty-backdrop row should be exact clear-color sum 3648, "
            f"got {floor}; clear-color or framebuffer setup changed?")

        h.set_backdrops([_star_descriptor()])
        with_stars = _settle_and_sample_row(h, 32)

        assert with_stars != floor, (
            f"row sum unchanged after binding starfield ({with_stars}); "
            f"backdrop did not render")
    finally:
        h.shutdown()


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
    """Rotation reference: rotating the camera 30° about the up axis
    must change the rendered backdrop. Translation along the camera
    forward must NOT change the same row (modulo float noise).

    Samples a 64-pixel horizontal stripe and sums the channels to make
    the test robust against single-pixel sparse-starfield misses."""
    h = _setup_for_pixel_test()
    try:
        h.set_backdrops([_star_descriptor()])

        baseline = _settle_and_sample_row(h, 32)

        # Translate forward 1000 units (camera moves toward origin).
        h.set_camera(
            eye=(0.0, 0.0, 500.0),
            target=(0.0, 0.0, -1000.0),
            up=(0.0, 1.0, 0.0),
            fov_y_rad=1.0472, near=1.0, far=100000.0,
        )
        translated = _settle_and_sample_row(h, 32)

        # Rotation: 30° about up axis from baseline view.
        import math
        a = math.radians(30)
        new_target = (math.sin(a) * -1000.0, 0.0, math.cos(a) * -1000.0)
        h.set_camera(
            eye=(0.0, 0.0, 1500.0),
            target=new_target,
            up=(0.0, 1.0, 0.0),
            fov_y_rad=1.0472, near=1.0, far=100000.0,
        )
        rotated = _settle_and_sample_row(h, 32)

        # Translation: same brightness sum within tolerance.
        assert abs(translated - baseline) <= 10, (
            f"translation should not change rendered stars: "
            f"baseline={baseline}, translated={translated}")

        # Rotation: brightness sum must differ from baseline. Stars are
        # bright enough that a 30° rotation typically swings the sum by
        # hundreds of channel-units.
        assert abs(rotated - baseline) > 50, (
            f"rotation should change rendered stars: "
            f"baseline={baseline}, rotated={rotated}")
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
