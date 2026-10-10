"""Emitter profiles over time (spec 2026-10-08-bridge-emitters §6.3, §11.3)."""
import math

import pytest

from engine.bridge_editor import profiles as pr

PROF = {
    "fade_s": 0.5,
    "green": {"tint": [1, 1, 1], "level": 1},
    "red": {"tint": [1, 0.1, 0.1], "level": 0.5,
            "wave": {"shape": "sine", "period_s": 2.0, "min": 0.2}},
}


def test_state_names():
    assert [pr.state_name(a) for a in (0, 1, 2, 7, -1)] == ["green", "yellow", "red", "green", "green"]


def test_steady_and_missing_waves_are_one():
    assert pr.wave_factor(None, 3.0) == 1.0
    assert pr.wave_factor({"shape": "steady"}, 3.0) == 1.0


def test_sine_peaks_at_phase_zero_and_bottoms_at_min():
    w = {"shape": "sine", "period_s": 2.0, "min": 0.2}
    assert pr.wave_factor(w, 0.0) == pytest.approx(1.0)
    assert pr.wave_factor(w, 1.0) == pytest.approx(0.2)
    assert pr.wave_factor(w, 2.0) == pytest.approx(1.0)
    assert pr.wave_factor(w, 0.0, phase=0.5) == pytest.approx(0.2)


def test_hard_square_is_on_for_its_duty():
    w = {"shape": "square", "period_s": 1.0, "duty": 0.25}
    assert pr.wave_factor(w, 0.1) == 1.0
    assert pr.wave_factor(w, 0.5) == 0.0


def test_soft_square_ramps_over_soft():
    w = {"shape": "square", "period_s": 1.0, "duty": 0.5, "soft": 0.2}
    assert pr.wave_factor(w, 0.0) == pytest.approx(0.0)
    assert pr.wave_factor(w, 0.1) == pytest.approx(0.5)      # half way up (smoothstep 0.5)
    assert pr.wave_factor(w, 0.3) == pytest.approx(1.0)
    assert pr.wave_factor(w, 0.6) == pytest.approx(0.5)      # half way down
    assert pr.wave_factor(w, 0.8) == pytest.approx(0.0)


def test_state_output_is_tint_times_level_times_wave():
    rgb, k = pr.state_output(PROF, "red", 1.0)              # sine trough: 0.2
    assert k == pytest.approx(0.1)
    assert rgb == pytest.approx((0.1, 0.01, 0.01))


def test_missing_state_is_off():
    assert pr.state_output(PROF, "yellow", 0.0) == ((0.0, 0.0, 0.0), 0.0)


def test_profile_of_defaults_to_steady_white():
    doc = {"profiles": {"p": PROF}}
    assert pr.profile_of(doc, {}) is pr.STEADY_WHITE
    assert pr.profile_of(doc, {"profile": "p"}) is PROF
    for s in pr.STATES:
        assert pr.state_output(pr.STEADY_WHITE, s, 0.0) == ((1.0, 1.0, 1.0), 1.0)


def test_alert_fade_starts_settled():
    f = pr.AlertFade(2)
    assert f.output(PROF, 0.0) == pr.state_output(PROF, "red", 0.0)


def test_fade_is_continuous():
    f = pr.AlertFade(0)
    f.set_alert(1)                        # green -> yellow (off)
    assert f.output(PROF, 0.0)[1] == pytest.approx(1.0)     # still all green
    f.advance(0.25)
    assert f.output(PROF, 0.0)[1] == pytest.approx(0.5)     # half way
    f.advance(0.25)
    assert f.output(PROF, 0.0)[1] == pytest.approx(0.0)     # settled: off
    f.advance(10.0)
    assert f.output(PROF, 0.0)[1] == pytest.approx(0.0)


def test_second_change_mid_fade_starts_from_the_new_previous():
    f = pr.AlertFade(0)
    f.set_alert(1)
    f.advance(0.25)
    f.set_alert(2)                        # yellow -> red, from yellow (off)
    rgb, k = f.output(PROF, 0.0)
    assert k == pytest.approx(0.0)
    assert all(math.isfinite(c) for c in rgb)


def test_zero_fade_switches_at_once():
    p = dict(PROF, fade_s=0)
    f = pr.AlertFade(0)
    f.set_alert(2)
    assert f.output(p, 0.0) == pr.state_output(p, "red", 0.0)


def test_same_alert_is_not_a_change():
    f = pr.AlertFade(0)
    f.set_alert(0)
    assert f.output(PROF, 0.0) == pr.state_output(PROF, "green", 0.0)
