from engine.appc import warp_in_dials as d


def setup_function(_):
    d.reset()


def test_defaults_and_order():
    assert d.DIAL_ORDER == tuple(d.DEFAULTS)
    assert d.get("slide_radii") == 10.0


def test_step_clamps_at_zero():
    for _ in range(10):
        d._step("core_radii", -1)
    assert d.get("core_radii") == 0.0


def test_tint_clamps_at_one():
    for _ in range(10):
        d._step("tint_b", 1)
    assert d.get("tint_b") == 1.0


def test_reset_restores_defaults():
    d._step("intensity", 1)
    assert d.get("intensity") != 4.0
    d.reset()
    assert d.current() == d.DEFAULTS


def test_timing_dials_default_to_the_shader_constants_and_clamp():
    # Spec 6.3 tuning: "streak and ring timing". Defaults = kStreakEnd /
    # kRingRise in renderer/warp_in_flash_shape.h.
    assert d.DIAL_ORDER[-2:] == ("streak_end", "ring_rise")
    assert d.get("streak_end") == 0.9
    assert d.get("ring_rise") == 0.05
    for _ in range(40):
        d._step("streak_end", -1)
        d._step("ring_rise", -1)
    assert d.get("streak_end") == 0.05
    assert d.get("ring_rise") == 0.01
    for _ in range(40):
        d._step("streak_end", 1)
    assert d.get("streak_end") == 1.0
