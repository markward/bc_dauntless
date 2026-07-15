"""Tests for the _dauntless_host.set_torpedoes binding's disruptor-bolt keys.

Task 1-2 made every dict passed to set_torpedoes carry the authentic
disruptor-bolt keys (id, is_disruptor, forward, shell_color,
bolt_core_color, bolt_length, bolt_width) unconditionally, for BOTH
projectile families. This pins that the C++ binding parses them
unconditionally too: a well-formed dict of either family must not raise,
and a dict missing one of the new keys must raise (no silent stub-style
degradation).
"""
import pytest

pytest.importorskip("_dauntless_host")

_TORPEDO_QUAD_FIELDS = {
    "position":       (0.0, 0.0, 0.0),
    "core_texture":   "/dev/null",
    "core_color":     (1.0, 1.0, 1.0, 1.0),
    "core_size_a":    1.0,
    "core_size_b":    1.0,
    "glow_texture":   "/dev/null",
    "glow_color":     (1.0, 1.0, 1.0, 1.0),
    "glow_size_a":    1.0,
    "glow_size_b":    1.0,
    "glow_size_c":    1.0,
    "flares_texture": "/dev/null",
    "flares_color":   (1.0, 1.0, 1.0, 1.0),
    "num_flares":     4,
    "flares_size_a":  1.0,
    "flares_size_b":  1.0,
    "age":            0.0,
}

_DISRUPTOR_BOLT_FIELDS = {
    "id":              1,
    "is_disruptor":    True,
    "forward":         (0.0, 0.0, 1.0),
    "shell_color":     (1.0, 0.0, 0.0, 1.0),
    "bolt_core_color": (1.0, 1.0, 1.0, 1.0),
    "bolt_length":     3.5,
    "bolt_width":      0.3,
}


def _photon_descriptor():
    d = dict(_TORPEDO_QUAD_FIELDS)
    d.update(_DISRUPTOR_BOLT_FIELDS)
    d["id"] = 1
    d["is_disruptor"] = False
    return d


def _disruptor_descriptor():
    d = dict(_TORPEDO_QUAD_FIELDS)
    d.update(_DISRUPTOR_BOLT_FIELDS)
    d["id"] = 2
    d["is_disruptor"] = True
    return d


def test_photon_style_descriptor_with_all_keys_does_not_raise():
    import _dauntless_host
    _dauntless_host.set_torpedoes([_photon_descriptor()])


def test_disruptor_style_descriptor_with_all_keys_does_not_raise():
    import _dauntless_host
    _dauntless_host.set_torpedoes([_disruptor_descriptor()])


def test_both_families_in_one_call_does_not_raise():
    import _dauntless_host
    _dauntless_host.set_torpedoes([_photon_descriptor(), _disruptor_descriptor()])


@pytest.mark.parametrize("missing_key", sorted(_DISRUPTOR_BOLT_FIELDS.keys()))
def test_descriptor_missing_a_new_key_raises(missing_key):
    import _dauntless_host
    d = _photon_descriptor()
    del d[missing_key]
    with pytest.raises(Exception):
        _dauntless_host.set_torpedoes([d])
