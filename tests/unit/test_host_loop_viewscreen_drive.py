import types
import engine.host_loop as _hl
from engine.host_loop import (
    drive_viewscreen_static_and_brightness, ViewscreenBrightnessRamp)
import engine.dev_mode as _dev_mode


class FakeRenderer:
    def __init__(self):
        self.brightness = None
        self.static = None
        self.source = None
    def set_viewscreen_brightness(self, b): self.brightness = b
    def set_viewscreen_static(self, on, intensity): self.static = (on, intensity)
    def set_viewscreen_static_source(self, paths): self.source = list(paths)


class FakeVS:
    def __init__(self, on=1, static_on=0, fmin=0.0, fmax=0.0,
                 group="View Screen Static"):
        self._on = on
        self._static_on = static_on
        self._static_min = fmin
        self._static_max = fmax
        self._static_icon_group = group
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


# ── Dev-gated logging tests ──────────────────────────────────────────────────

def test_logging_fires_on_signature_change(monkeypatch, capsys):
    """Log emitted when the feed signature changes (dev mode on)."""
    monkeypatch.setattr(_dev_mode, "is_enabled", lambda: True)
    r = FakeRenderer()
    vs_off = FakeVS(on=0)
    vs_on  = FakeVS(on=1, static_on=1, fmin=0.8, fmax=1.0)
    ctrl = _controller(vs_off)
    ramp = ViewscreenBrightnessRamp()

    # First call: screen off — should log the "off" state.
    drive_viewscreen_static_and_brightness(r, ctrl, ramp, 0.0, intensity_fn=lambda a, b: 0.9)
    out1 = capsys.readouterr().out
    assert "[viewscreen]" in out1

    # Second call: same state — no new log line.
    drive_viewscreen_static_and_brightness(r, ctrl, ramp, 0.0, intensity_fn=lambda a, b: 0.9)
    out2 = capsys.readouterr().out
    assert out2 == ""

    # State changes: screen on with static — should log again.
    ctrl.viewscreen_obj = vs_on
    drive_viewscreen_static_and_brightness(r, ctrl, ramp, 0.0, intensity_fn=lambda a, b: 0.9)
    out3 = capsys.readouterr().out
    assert "[viewscreen]" in out3
    assert "static=on" in out3


def test_logging_silent_when_dev_mode_off(monkeypatch, capsys):
    """No log output when dev mode is disabled."""
    monkeypatch.setattr(_dev_mode, "is_enabled", lambda: False)
    r = FakeRenderer()
    vs = FakeVS(on=1, static_on=1, fmin=0.8, fmax=1.0)
    ctrl = _controller(vs)
    ramp = ViewscreenBrightnessRamp()

    drive_viewscreen_static_and_brightness(r, ctrl, ramp, 0.0, intensity_fn=lambda a, b: 0.9)
    out = capsys.readouterr().out
    # No viewscreen log lines when dev mode is off.
    assert "[viewscreen]" not in out


def test_logging_silent_when_state_unchanged(monkeypatch, capsys):
    """No log output on repeated calls with the same state (dev mode on)."""
    monkeypatch.setattr(_dev_mode, "is_enabled", lambda: True)
    r = FakeRenderer()
    vs = FakeVS(on=0)
    ctrl = _controller(vs)
    ramp = ViewscreenBrightnessRamp()

    # First call logs.
    drive_viewscreen_static_and_brightness(r, ctrl, ramp, 0.0, intensity_fn=lambda a, b: 0.5)
    capsys.readouterr()  # consume

    # Repeated calls with the same state must produce no output.
    for _ in range(5):
        drive_viewscreen_static_and_brightness(r, ctrl, ramp, 0.0, intensity_fn=lambda a, b: 0.5)
    out = capsys.readouterr().out
    assert out == ""


def test_logging_intensity_in_message(monkeypatch, capsys):
    """Log line includes intensity value when static is on (dev mode on)."""
    monkeypatch.setattr(_dev_mode, "is_enabled", lambda: True)
    r = FakeRenderer()
    vs = FakeVS(on=1, static_on=1, fmin=0.8, fmax=1.0)
    ctrl = _controller(vs)
    ramp = ViewscreenBrightnessRamp()

    drive_viewscreen_static_and_brightness(r, ctrl, ramp, 0.0, intensity_fn=lambda a, b: 0.9)
    out = capsys.readouterr().out
    assert "0.8" in out  # fmin
    assert "1.0" in out  # fmax
