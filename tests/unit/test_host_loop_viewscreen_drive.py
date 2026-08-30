import os
import types
from engine.host_loop import (
    drive_viewscreen_static_and_brightness, ViewscreenBrightnessRamp)


class FakeRenderer:
    def __init__(self):
        self.brightness = None
        self.static = None
        self.source = None
        self.off_textures = []
    def set_viewscreen_brightness(self, b): self.brightness = b
    def set_viewscreen_static(self, on, intensity): self.static = (on, intensity)
    def set_viewscreen_static_source(self, paths): self.source = list(paths)
    def set_viewscreen_off_texture(self, path): self.off_textures.append(path)


class FakeVS:
    def __init__(self, on=1, static_on=0, fmin=0.0, fmax=0.0,
                 group="View Screen Static", off_texture=None):
        self._on = on
        self._static_on = static_on
        self._static_min = fmin
        self._static_max = fmax
        self._static_icon_group = group
        self._off_texture = off_texture
    def IsOn(self): return self._on
    def IsStaticOn(self): return self._static_on
    def GetRemoteCam(self): return None


def _controller(vs):
    c = types.SimpleNamespace()
    c.viewscreen_obj = vs
    c.comm_set_ids = {}
    c.comm_instances_by_set = {}
    return c


def test_static_off_sets_false_and_brightness():
    r = FakeRenderer()
    vs = FakeVS(on=1, static_on=0)
    drive_viewscreen_static_and_brightness(
        r, _controller(vs), ViewscreenBrightnessRamp(), 0.0,
        intensity_fn=lambda a, b: 0.5)
    assert r.static == (False, 0.0)
    assert r.brightness == 0.0   # forward feed, ramp just started


def test_static_on_resolves_paths_and_intensity():
    r = FakeRenderer()
    vs = FakeVS(on=1, static_on=1, fmin=0.8, fmax=1.0)
    drive_viewscreen_static_and_brightness(
        r, _controller(vs), ViewscreenBrightnessRamp(), 0.0,
        intensity_fn=lambda a, b: (a + b) / 2)
    assert r.static == (True, 0.9)
    assert r.source is not None and len(r.source) == 3   # noise frames sent


def test_static_max_zero_stays_off():
    r = FakeRenderer()
    vs = FakeVS(on=1, static_on=1, fmin=0.0, fmax=0.0)
    drive_viewscreen_static_and_brightness(
        r, _controller(vs), ViewscreenBrightnessRamp(), 0.0,
        intensity_fn=lambda a, b: 0.5)
    assert r.static == (False, 0.0)


def test_off_texture_is_resolved_and_pushed_once():
    # MissionLib.ShowLoadingText sets this before every mission load; without
    # it reaching the renderer the off screen draws the 1x1 white fallback.
    r = FakeRenderer()
    vs = FakeVS(on=0, off_texture="data/Icons/ViewscreenLoading.tga")
    c = _controller(vs)
    ramp = ViewscreenBrightnessRamp()
    drive_viewscreen_static_and_brightness(r, c, ramp, 0.0,
                                           intensity_fn=lambda a, b: 0.5)
    assert len(r.off_textures) == 1
    pushed = r.off_textures[0]
    assert pushed.endswith("game/data/Icons/ViewscreenLoading.tga")
    assert os.path.isabs(pushed)
    # Unchanged next frame -> not re-sent (the TGA is decoded on change only).
    drive_viewscreen_static_and_brightness(r, c, ramp, 0.016,
                                           intensity_fn=lambda a, b: 0.5)
    assert len(r.off_textures) == 1


def test_no_off_texture_pushes_empty_path():
    r = FakeRenderer()
    drive_viewscreen_static_and_brightness(
        r, _controller(FakeVS(on=1)), ViewscreenBrightnessRamp(), 0.0,
        intensity_fn=lambda a, b: 0.5)
    assert r.off_textures == [""]


def test_screen_off_signature_is_off():
    r = FakeRenderer()
    ramp = ViewscreenBrightnessRamp()
    vs = FakeVS(on=0)
    drive_viewscreen_static_and_brightness(
        r, _controller(vs), ramp, 0.0, intensity_fn=lambda a, b: 0.5)
    # off signature established; advancing keeps the same signature ramping up
    drive_viewscreen_static_and_brightness(
        r, _controller(vs), ramp, ViewscreenBrightnessRamp.DURATION_S,
        intensity_fn=lambda a, b: 0.5)
    assert r.brightness == 1.0
