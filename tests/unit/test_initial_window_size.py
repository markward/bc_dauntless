"""DAUNTLESS_WINDOW_SIZE pins the starting window size, so a perf baseline is
taken at a known resolution (docs/reference/engine/perf-register.md, M-4): GPU cost
scales with the pixels drawn, and a 1280x720 capture cannot be compared with
one maximised on a 4K laptop screen."""
from engine.host_loop import _initial_window_size


def test_default_is_1280x720():
    assert _initial_window_size({}) == (1280, 720)


def test_reads_width_by_height():
    assert _initial_window_size({"DAUNTLESS_WINDOW_SIZE": "1920x1080"}) == (1920, 1080)
    assert _initial_window_size({"DAUNTLESS_WINDOW_SIZE": " 2560X1440 "}) == (2560, 1440)


def test_a_bad_value_falls_back_to_the_default():
    for bad in ("", "1920", "x1080", "axb", "0x720", "-5x10"):
        assert _initial_window_size({"DAUNTLESS_WINDOW_SIZE": bad}) == (1280, 720), bad
