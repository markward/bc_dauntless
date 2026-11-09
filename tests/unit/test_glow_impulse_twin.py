"""The impulse-glow gain the renderer evaluates in C++ (glow_impulse.h) is the
twin of subsystem_glow's Python: same constants, same ease, same pulse.

`ShipGlowController` pushes (start, target, t0, powered) on change and the
renderer evaluates the eased, pulsing gain at upload from the game clock
(perf tier 1, spec 2026-11-08 §2.3). If the two drift, the engines brighten
differently from what light_emitters' cast light (Python impulse_gain) shows.
"""
import itertools
import math
import struct

import pytest

from engine.appc import subsystem_glow as sg

import _dauntless_host as _h   # no skip: a missing build must fail loudly


def _f32(x):
    """`x` as the float32 the C++ store and u_decal_time hold."""
    return struct.unpack("f", struct.pack("f", x))[0]


def _grid():
    starts = (0.0, 0.2, 1.0 / 9.0, 0.75, 1.0)
    targets = (0.0, 0.5, 1.0)
    t0s = (0.0, 3.25, 41.0)
    offsets = (-0.5, 0.0, 0.01, 0.1, 0.35, 1.0, 2.5, 7.0)
    for start, target, t0, off, powered in itertools.product(
            starts, targets, t0s, offsets, (True, False)):
        # The renderer holds game times as float32 (the flicker clock is
        # u_decal_time); compare the formulas, not that quantisation.
        yield _f32(start), _f32(target), _f32(t0), _f32(t0 + off), powered


def test_cpp_constants_match_python():
    assert hasattr(_h, "glow_impulse_gain_eval"), (
        "stale build: rebuild build/ (cmake --build build -j)")
    for start, target, t0, now, powered in _grid():
        want = sg.impulse_gain(sg.eased_frac(start, target, t0, now), now,
                               powered)
        got = _h.glow_impulse_gain_eval(start, target, t0, now, powered)
        assert abs(got - want) < 1e-5, (start, target, t0, now, powered)


def test_cpp_matches_python_ease_closed_form():
    assert hasattr(_h, "glow_impulse_gain_eval"), (
        "stale build: rebuild build/ (cmake --build build -j)")
    # Powered at now = 0 mod 2.5 s (the 0.4 Hz pulse period) makes sin() 0,
    # so the gain is base(eased) alone: invert it to read back C++'s ease.
    for start, target in itertools.product((0.0, 0.3, 1.0), (0.0, 0.6, 1.0)):
        for k in range(1, 6):
            now = 2.5 * k
            t0 = now - 0.05 * k * k
            want = sg.eased_frac(start, target, t0, now)
            gain = _h.glow_impulse_gain_eval(start, target, t0, now, True)
            got = (gain - sg.GAIN_IDLE) / (sg.GAIN_MAX - sg.GAIN_IDLE)
            assert abs(got - want) < 1e-5, (start, target, t0, now)


def test_python_closed_form_is_the_documented_ease():
    # target + (start - target) * exp(-(now - t0) / tau); start before t0.
    assert sg.eased_frac(0.2, 1.0, 5.0, 4.0) == 0.2
    assert sg.eased_frac(0.2, 1.0, 5.0, 5.0) == 0.2
    want = 1.0 + (0.2 - 1.0) * math.exp(-0.7 / sg.IMPULSE_EASE_TAU)
    assert sg.eased_frac(0.2, 1.0, 5.0, 5.7) == pytest.approx(want, abs=1e-15)
    # Settles to exactly 0 below IMPULSE_SETTLE_EPS when the target is 0.
    assert sg.eased_frac(1.0, 0.0, 0.0, 10.0) == 0.0
    assert sg.eased_frac(1.0, 0.0, 0.0, 0.1) > 0.0
