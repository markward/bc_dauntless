from engine.host_loop import ViewscreenBrightnessRamp


def test_ramp_fades_in_from_zero_over_duration():
    r = ViewscreenBrightnessRamp()
    # first call establishes the signature and starts the ramp at ~0
    b0 = r.update(("comm", 7), 0.0)
    assert b0 == 0.0
    # halfway through DURATION_S -> ~0.5
    b1 = r.update(("comm", 7), ViewscreenBrightnessRamp.DURATION_S / 2)
    assert abs(b1 - 0.5) < 1e-6
    # past the end -> clamped to 1.0
    b2 = r.update(("comm", 7), ViewscreenBrightnessRamp.DURATION_S)
    assert b2 == 1.0
    # stays settled at 1.0
    assert r.update(("comm", 7), 1.0) == 1.0


def test_ramp_resets_on_signature_change():
    r = ViewscreenBrightnessRamp()
    r.update(("comm", 7), ViewscreenBrightnessRamp.DURATION_S)  # settle at 1.0
    # ViewscreenOff -> forward: signature changes, fade restarts
    b = r.update(("forward",), 0.0)
    assert b == 0.0
    b = r.update(("forward",), ViewscreenBrightnessRamp.DURATION_S / 2)
    assert abs(b - 0.5) < 1e-6
