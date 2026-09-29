"""_dauntless_host system-scale nebula bindings (developer-only render pass).

The pass itself is GL-tested in native/tests/renderer/system_nebula_pass_test.cc;
these pin the Python surface: shape validation, the host-down no-op, and the
set / clear round trip through a headless host.
"""
import os

import pytest


def _profile(**overrides):
    d = {
        "r": [0.0, 60000.0, 120000.0, 240000.0],
        "nebula": [0.0, 0.0, 1.0, 0.05],
        "k_sys": 2.0e-5,
        "star_radius": 2000.0,
        "cloud_rgb": (0.6, 0.35, 0.7),
        "star_rgb": (1.0, 1.0, 1.0),
    }
    d.update(overrides)
    return d


def test_before_init_is_silent_and_reports_no_profile():
    import _dauntless_host
    _dauntless_host.set_system_nebula_profile(None)
    _dauntless_host.set_system_nebula_profile(_profile())
    _dauntless_host.set_system_nebula_star((0.0, 0.0, 0.0))
    assert _dauntless_host.system_nebula_has_profile() is False


def test_mismatched_rows_are_rejected():
    import _dauntless_host
    with pytest.raises(ValueError):
        _dauntless_host.set_system_nebula_profile(_profile(nebula=[0.0, 1.0]))
    with pytest.raises(ValueError):
        _dauntless_host.set_system_nebula_profile(_profile(r=[], nebula=[]))


def test_set_and_clear_round_trip_after_init():
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    import _dauntless_host
    _dauntless_host.init(64, 64, "test_system_nebula_bindings")
    try:
        assert _dauntless_host.system_nebula_has_profile() is False
        _dauntless_host.set_system_nebula_profile(
            _profile(g=0.5, floor=0.02, scatter=1.5, far_gu=1.8e6))
        assert _dauntless_host.system_nebula_has_profile() is True
        _dauntless_host.set_system_nebula_star((1.0, 2.0, 3.0))
        _dauntless_host.frame()   # not --developer: the old path, no crash
        _dauntless_host.set_system_nebula_profile(None)
        assert _dauntless_host.system_nebula_has_profile() is False
    finally:
        _dauntless_host.shutdown()
    # a fresh host starts with no profile
    _dauntless_host.init(64, 64, "test_system_nebula_bindings_2")
    try:
        assert _dauntless_host.system_nebula_has_profile() is False
    finally:
        _dauntless_host.shutdown()


def test_dials_round_trip_and_rebuild_only_for_g_or_floor():
    """system_nebula_set_dials / system_nebula_dials Python surface: shape,
    the missing-key -> struct-default reset, and that a g/floor change is
    the only path that rebuilds (see the GL-level assertion in
    native/tests/renderer/system_nebula_pass_test.cc; this just pins that
    the Python round trip carries every value through unmangled)."""
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    import _dauntless_host
    _dauntless_host.init(64, 64, "test_system_nebula_dials")
    try:
        _dauntless_host.set_system_nebula_profile(_profile())
        _dauntless_host.system_nebula_set_dials({
            "lane_size": 12345.0, "lane_contrast": 0.4,
            "g": 0.25, "floor": 0.1, "near_range": 9000.0,
        })
        d = _dauntless_host.system_nebula_dials()
        assert d["lane_size"] == 12345.0
        assert d["lane_contrast"] == pytest.approx(0.4)
        assert d["g"] == pytest.approx(0.25)
        assert d["floor"] == pytest.approx(0.1)
        assert d["near_range"] == 9000.0
        # A key omitted resets that dial to the struct default (veil_scale).
        assert d["veil_scale"] == 1.0
        _dauntless_host.frame()   # not --developer: no crash either way
    finally:
        _dauntless_host.shutdown()


def test_star_accepts_none_for_a_sunless_set():
    """A sunless viewed set clears the star (the pass then lights clumps by
    the emissive floor only) -- before and after init."""
    import _dauntless_host
    _dauntless_host.set_system_nebula_star(None)
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    _dauntless_host.init(64, 64, "test_system_nebula_star_none")
    try:
        _dauntless_host.set_system_nebula_star((1.0, 2.0, 3.0))
        assert _dauntless_host.system_nebula_has_star() is True
        _dauntless_host.set_system_nebula_star(None)
        assert _dauntless_host.system_nebula_has_star() is False
    finally:
        _dauntless_host.shutdown()
