"""Tests for the _dauntless_host.set_dynamic_lights binding.

Task 10 adds the Python -> C++ full-replace dynamic-light list (the light
core itself and the shader loop landed in Tasks 8-9; this task only wires the
list through). Mirrors tests/host/test_set_torpedoes_binding.py's full-replace
idiom: required keys are parsed unconditionally (missing key raises), the
lone optional key (`position_b`) degenerates to a point light when absent or
None, and the list is silently clamped rather than erroring past the native
per-frame cap.
"""
import pytest

pytest.importorskip("_dauntless_host")

_REQUIRED_FIELDS = {
    "position":  (1.0, 2.0, 3.0),
    "color":     (1.0, 0.5, 0.2),
    "radius":    10.0,
    "intensity": 2.0,
}


def _point_light():
    return dict(_REQUIRED_FIELDS)


def _segment_light():
    d = dict(_REQUIRED_FIELDS)
    d["position_b"] = (4.0, 5.0, 6.0)
    return d


def test_point_and_segment_light_in_one_call_does_not_raise():
    import _dauntless_host
    _dauntless_host.set_dynamic_lights([_point_light(), _segment_light()])


def test_position_b_none_behaves_as_absent():
    import _dauntless_host
    d = _point_light()
    d["position_b"] = None
    _dauntless_host.set_dynamic_lights([d])


def test_empty_list_does_not_raise():
    import _dauntless_host
    _dauntless_host.set_dynamic_lights([])


@pytest.mark.parametrize("missing_key", sorted(_REQUIRED_FIELDS.keys()))
def test_descriptor_missing_a_required_key_raises(missing_key):
    import _dauntless_host
    d = _point_light()
    del d[missing_key]
    with pytest.raises(Exception):
        _dauntless_host.set_dynamic_lights([d])


def test_excess_entries_beyond_the_frame_cap_are_clamped_not_errored():
    import _dauntless_host
    lights = [_point_light() for _ in range(65)]
    _dauntless_host.set_dynamic_lights(lights)
