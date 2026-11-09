"""The main HDR scene target's colour format follows the nonfinite probe.

HdrFormat.ProbeOnPicksRgba16f: frame() picks the format of g_hdr_target (and
its MSAA twin) before the clear. Off, the scene runs R11F_G11F_B10F (half the
bandwidth); on, it runs RGBA16F, because the probe reads opaque.frag's cause
code from alpha and needs negatives / -Inf, which R11F_G11F_B10F drops.
"""
import os

import pytest


@pytest.fixture
def host():
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    import _dauntless_host
    try:
        _dauntless_host.init(128, 96, "hdr-scene-format")
    except RuntimeError as e:
        pytest.skip(f"no GL context: {e}")
    try:
        yield _dauntless_host
    finally:
        import engine.renderer
        engine.renderer.set_nonfinite_probe_enabled(False)
        _dauntless_host.shutdown()


def test_probe_off_scene_is_r11(host):
    import engine.renderer
    engine.renderer.set_nonfinite_probe_enabled(False)
    host.frame()
    assert host.hdr_scene_color_format() == "r11g11b10f"


def test_probe_on_scene_is_rgba16f(host):
    import engine.renderer
    host.frame()
    assert host.hdr_scene_color_format() == "r11g11b10f"
    engine.renderer.set_nonfinite_probe_enabled(True)
    host.frame()
    assert host.hdr_scene_color_format() == "rgba16f"
    # And back: the toggle reallocates both ways.
    engine.renderer.set_nonfinite_probe_enabled(False)
    host.frame()
    assert host.hdr_scene_color_format() == "r11g11b10f"
