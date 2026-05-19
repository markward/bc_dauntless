"""Render a `_specular`-using ship and assert the opaque pass produces
non-black pixels under a directional light.

Smoke test — does not isolate the specular contribution numerically.
The strong assertions live in C++ tests:
  - native/tests/assets/cpu/material_build_test.cc verifies that
    _specular images route to Material::StageSlot::Gloss only.
  - native/tests/renderer/lighting_test.cc pins the gloss -> exponent
    mapping curve.

The Keldon is one of the BC ships that ships with _specular.tga files.
Its NIF references textures in SharedTextures/CardShips/High (not in
Ships/Keldon/High, which is empty on a stock install).
"""
import os
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
KELDON_NIF = PROJECT_ROOT / "game" / "data" / "Models" / "Ships" / "Keldon" / "Keldon.nif"
KELDON_TEX = PROJECT_ROOT / "game" / "data" / "Models" / "SharedTextures" / "CardShips" / "High"


def test_specular_ship_renders_with_directional_light():
    if not KELDON_NIF.is_file():
        pytest.skip(f"BC asset not available at {KELDON_NIF}")
    if not KELDON_TEX.is_dir():
        pytest.skip(f"BC texture dir not available at {KELDON_TEX}")

    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    import _dauntless_host

    _dauntless_host.init(640, 360, "test_specular")
    try:
        h = _dauntless_host.load_model(str(KELDON_NIF), str(KELDON_TEX))
        iid = _dauntless_host.create_instance(h)
        _dauntless_host.set_world_transform(iid, [
            1.0, 0.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            0.0, 0.0, 0.0, 1.0,
        ])
        _dauntless_host.set_camera(
            eye=(0.0, 0.0, 800.0),
            target=(0.0, 0.0, 0.0),
            up=(0.0, 1.0, 0.0),
            fov_y_rad=1.0472,
            near=1.0,
            far=100000.0,
        )

        # Ambient + one directional light positioned to put the spec
        # highlight near screen center. Light direction is "toward the
        # light source", so (0, 0, 1) means the light is in front of the
        # camera (viewer side), placing the half-vector close to the
        # surface normal on the saucer's front face.
        _dauntless_host.set_lighting(
            (0.1, 0.1, 0.1),
            [((0.0, 0.0, 1.0), (1.0, 1.0, 1.0))],
        )
        _dauntless_host.frame()

        fw, fh = _dauntless_host.framebuffer_size()
        cx, cy = fw // 2, fh // 2

        max_brightness = 0
        for dx in range(-60, 61, 20):
            for dy in range(-40, 41, 20):
                r, g, b, _ = _dauntless_host.read_pixel(cx + dx, cy + dy)
                max_brightness = max(max_brightness, r + g + b)

        assert max_brightness > 0, (
            "Expected Keldon to produce at least one non-black pixel "
            "with ambient + one directional light; sampled grid was "
            "entirely zero. (Smoke test — verifies the spec uniforms "
            "are wired up without GL errors, not that the specular "
            "term contributes specifically.)"
        )
    finally:
        _dauntless_host.destroy_instance(iid)
        _dauntless_host.shutdown()
        os.environ.pop("OPEN_STBC_HOST_HEADLESS", None)
