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
