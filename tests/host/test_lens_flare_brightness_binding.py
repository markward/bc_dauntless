"""Tests for the _dauntless_host.set_lens_flares binding's optional
``brightness`` key (system-scale nebula render, Task 6).

There is no GL lens-flare readback test in native/tests/renderer (the only
test file there, lens_flare_pass_test.cc, exercises build_ngon_mesh -- pure
CPU geometry, no render() call), so this pins the binding contract instead:
a descriptor carrying ``brightness`` must not raise, and one that omits it
must not raise either (the field defaults to 1.0 in LensFlareDescriptor).
"""
import pytest

pytest.importorskip("_dauntless_host")


def _flare(**overrides):
    d = {"source_world_pos": (0.0, 0.0, 0.0), "elements": []}
    d.update(overrides)
    return d


def test_descriptor_with_brightness_is_stored():
    import _dauntless_host
    _dauntless_host.set_lens_flares([_flare(brightness=0.2)])
    assert _dauntless_host.lens_flares_brightness_debug() == pytest.approx([0.2])


def test_descriptor_without_brightness_defaults_to_one():
    """Omitting the key must not raise -- it defaults to 1.0 in C++, not a
    required field."""
    import _dauntless_host
    _dauntless_host.set_lens_flares([_flare()])
    assert _dauntless_host.lens_flares_brightness_debug() == pytest.approx([1.0])


def test_mixed_with_and_without_brightness_in_one_call():
    import _dauntless_host
    _dauntless_host.set_lens_flares([_flare(brightness=0.0), _flare()])
    assert _dauntless_host.lens_flares_brightness_debug() == pytest.approx([0.0, 1.0])


def test_set_lens_flares_updates_the_debug_count():
    import _dauntless_host
    _dauntless_host.set_lens_flares([_flare(brightness=0.5), _flare()])
    assert _dauntless_host.frame_state_debug()["lens_flares"] == 2
    _dauntless_host.set_lens_flares([])
    assert _dauntless_host.frame_state_debug()["lens_flares"] == 0
