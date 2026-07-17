"""engine.audio.hum_diagnostic -- the --developer engine-hum console readout
(Part 2 of the exterior-audio-fidelity live-verification pass).

This is a DIAGNOSTIC, not a fix: the design brief only asks that it be
printed roughly once a second, gated behind --developer, throttled, and out
of the 60 Hz hot path when disabled. These tests pin: the pure gain/doppler
math against the reference formulas, the enable/disable + throttle gating
(never touching stdout when off), and that a report actually reads the live
hum_allocator/attached_sources state once triggered.
"""
import math
import os
import struct

import pytest

os.environ.setdefault("OPEN_STBC_AUDIO", "0")
_dauntless_host = pytest.importorskip("_dauntless_host")

from engine.audio import hum_diagnostic
from engine.audio.engine_rumble import HUM_MIN_DISTANCE, HUM_MAX_DISTANCE
from engine.audio.attached_sources import SPEED_OF_SOUND_GU


@pytest.fixture
def reset_dev_mode():
    import _dauntless_host as _h
    original = getattr(_h, "developer_mode", False)
    try:
        yield
    finally:
        _h.developer_mode = original


@pytest.fixture(autouse=True)
def reset_diagnostic():
    hum_diagnostic.reset_for_tests()
    yield
    hum_diagnostic.reset_for_tests()


# ── pure math ────────────────────────────────────────────────────────────

def test_gain_at_ref_distance_is_1():
    gain, past_floor = hum_diagnostic.gain_for_distance(HUM_MIN_DISTANCE)
    assert gain == pytest.approx(1.0)
    assert past_floor is False


def test_gain_at_max_distance_is_the_floor():
    """ref/max = 4.375/35.0 = 0.125 -- the floor value the user's report
    describes as never changing beyond 35 GU."""
    gain, past_floor = hum_diagnostic.gain_for_distance(HUM_MAX_DISTANCE)
    assert gain == pytest.approx(HUM_MIN_DISTANCE / HUM_MAX_DISTANCE)
    assert past_floor is False        # exactly AT the max, not yet past it


def test_gain_past_max_distance_stays_pinned_at_the_floor():
    gain_at_max, _ = hum_diagnostic.gain_for_distance(HUM_MAX_DISTANCE)
    gain_far, past_floor = hum_diagnostic.gain_for_distance(HUM_MAX_DISTANCE * 10.0)
    assert gain_far == pytest.approx(gain_at_max)
    assert past_floor is True


def test_gain_below_ref_distance_clamps_to_1():
    gain, past_floor = hum_diagnostic.gain_for_distance(0.0)
    assert gain == pytest.approx(1.0)
    assert past_floor is False


def test_gain_midpoint_matches_reference_formula():
    d = 20.0
    expected = HUM_MIN_DISTANCE / (HUM_MIN_DISTANCE + 1.0 * (d - HUM_MIN_DISTANCE))
    gain, _ = hum_diagnostic.gain_for_distance(d)
    assert gain == pytest.approx(expected)


def test_doppler_zero_speed_is_zero_cents():
    assert hum_diagnostic.doppler_cents(0.0) == 0.0


def test_doppler_matches_probed_20_gups_result():
    """Design brief: 'at a realistic 20 GU/s the velocity is 20.0 GU/s ->
    ~104 cents of doppler.' Pins the formula against that live probe."""
    cents = hum_diagnostic.doppler_cents(20.0)
    assert cents == pytest.approx(104.0, abs=1.0)


def test_doppler_matches_1200_log2_c_over_c_minus_v():
    v = 50.0
    expected = 1200.0 * math.log2(SPEED_OF_SOUND_GU / (SPEED_OF_SOUND_GU - v))
    assert hum_diagnostic.doppler_cents(v) == pytest.approx(expected)


def test_doppler_at_or_above_speed_of_sound_does_not_blow_up():
    """A discontinuity (teleport/warp) must degrade to 0, not raise or -inf."""
    assert hum_diagnostic.doppler_cents(SPEED_OF_SOUND_GU) == 0.0
    assert hum_diagnostic.doppler_cents(SPEED_OF_SOUND_GU * 2.0) == 0.0


def test_doppler_negative_speed_uses_magnitude():
    assert hum_diagnostic.doppler_cents(-20.0) == pytest.approx(
        hum_diagnostic.doppler_cents(20.0))


# ── enable/disable + throttle gating ────────────────────────────────────

def test_disabled_by_default():
    assert hum_diagnostic.is_enabled() is False


def test_toggle_flips_state_and_prints_a_line(capsys):
    hum_diagnostic.toggle()
    assert hum_diagnostic.is_enabled() is True
    out = capsys.readouterr().out
    assert "ON" in out

    hum_diagnostic.toggle()
    assert hum_diagnostic.is_enabled() is False
    out = capsys.readouterr().out
    assert "OFF" in out


def test_maybe_report_silent_when_toggle_off_even_under_developer(
        reset_dev_mode, capsys):
    import _dauntless_host as _h
    _h.developer_mode = True
    hum_diagnostic.maybe_report(listener_pos=(0.0, 0.0, 0.0), player=None, dt=5.0)
    assert capsys.readouterr().out == ""


def test_maybe_report_silent_when_developer_off_even_with_toggle_on(
        reset_dev_mode, capsys):
    import _dauntless_host as _h
    _h.developer_mode = False
    hum_diagnostic.toggle()
    capsys.readouterr()  # drain toggle()'s own ON/OFF announcement
    hum_diagnostic.maybe_report(listener_pos=(0.0, 0.0, 0.0), player=None, dt=5.0)
    assert capsys.readouterr().out == ""


def test_maybe_report_throttled_to_once_per_second(reset_dev_mode, capsys):
    import _dauntless_host as _h
    _h.developer_mode = True
    hum_diagnostic.toggle()
    capsys.readouterr()  # drain toggle()'s own ON/OFF announcement

    hum_diagnostic.maybe_report(listener_pos=(0.0, 0.0, 0.0), player=None, dt=0.3)
    assert capsys.readouterr().out == "", "must not report before the 1s period elapses"

    hum_diagnostic.maybe_report(listener_pos=(0.0, 0.0, 0.0), player=None, dt=0.3)
    assert capsys.readouterr().out == ""

    hum_diagnostic.maybe_report(listener_pos=(0.0, 0.0, 0.0), player=None, dt=0.5)
    out = capsys.readouterr().out
    assert "listener=" in out, "accumulated dt crossed 1.0s -- must report now"


def test_maybe_report_resets_accumulator_after_reporting(reset_dev_mode, capsys):
    import _dauntless_host as _h
    _h.developer_mode = True
    hum_diagnostic.toggle()

    hum_diagnostic.maybe_report(listener_pos=(0.0, 0.0, 0.0), player=None, dt=1.5)
    capsys.readouterr()  # drain the first report

    hum_diagnostic.maybe_report(listener_pos=(0.0, 0.0, 0.0), player=None, dt=0.4)
    assert capsys.readouterr().out == "", "accumulator must have reset after reporting"


# ── report content (real hum_allocator/attached_sources state) ─────────

class _Loc:
    def __init__(self, x, y, z): self.x, self.y, self.z = x, y, z


class _Ship:
    def __init__(self, name, loc):
        self._name = name
        self._loc = _Loc(*loc)
    def GetName(self): return self._name
    def GetWorldLocation(self): return self._loc
    def GetNode(self): return self
    def GetImpulseEngineSubsystem(self): return self._sub
    _sub = None


class _Prop:
    def GetEngineSound(self): return "Federation Engines"


class _Sub:
    def GetProperty(self): return _Prop()


def _wav():
    data = struct.pack("<h", 0) * 8
    return (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
            + b"fmt " + struct.pack("<I", 16)
            + struct.pack("<HHIIHH", 1, 1, 22050, 44100, 2, 16)
            + b"data" + struct.pack("<I", len(data)) + data)


@pytest.fixture
def humming_ship(tmp_path, monkeypatch):
    from engine.audio import hum_allocator
    from engine.audio.tg_sound import (
        TGSound, TGSoundManager, init_audio_for_tests, shutdown_audio_for_tests,
    )
    hum_allocator.reset_for_tests()
    init_audio_for_tests()
    wav = tmp_path / "e.wav"
    wav.write_bytes(_wav())
    TGSoundManager.instance().LoadSound(str(wav), "Federation Engines", TGSound.LS_3D)

    ship = _Ship("Rutledge", loc=(10.0, 0.0, 0.0))
    ship._sub = _Sub()
    monkeypatch.setattr(hum_allocator, "_roster", lambda: [ship])
    hum_allocator.update(listener_pos=(0.0, 0.0, 0.0))
    assert ship in hum_allocator._humming, "sanity: the ship must actually be humming"

    yield ship

    shutdown_audio_for_tests()
    hum_allocator.reset_for_tests()


def test_report_prints_distance_gain_and_doppler_for_each_humming_ship(
        reset_dev_mode, humming_ship, capsys):
    import _dauntless_host as _h
    _h.developer_mode = True
    hum_diagnostic.toggle()

    hum_diagnostic.maybe_report(
        listener_pos=(0.0, 0.0, 0.0), player=None, dt=1.0)

    out = capsys.readouterr().out
    assert "Rutledge" in out
    assert "dist=" in out
    assert "gain=" in out
    assert "speed=" in out
    assert "doppler=" in out


def test_report_flags_player_ship_and_prints_its_own_distance(
        reset_dev_mode, humming_ship, capsys):
    import _dauntless_host as _h
    _h.developer_mode = True
    hum_diagnostic.toggle()

    hum_diagnostic.maybe_report(
        listener_pos=(0.0, 0.0, 0.0), player=humming_ship, dt=1.0)

    out = capsys.readouterr().out
    assert "player ship dist=" in out
    assert "PLAYER" in out
