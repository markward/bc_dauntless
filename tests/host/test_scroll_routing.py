"""Unit tests for _route_scroll_wheel — the per-frame mouse-wheel router."""
from engine.host_loop import _route_scroll_wheel, _PlayerControl, _WHEEL_PX_PER_NOTCH


class _FakeWheel:
    def __init__(self):
        self.calls = []

    def __call__(self, x, y, delta_y):
        self.calls.append((x, y, delta_y))


def test_zero_scroll_does_nothing():
    pc = _PlayerControl(); pc.impulse_level = 4
    wheel = _FakeWheel()
    _route_scroll_wheel(0.0, route_to_panel=False, mx=10, my=20,
                        send_wheel=wheel, player_control=pc, can_throttle=True)
    assert pc.impulse_level == 4
    assert wheel.calls == []


def test_over_panel_forwards_to_cef_not_throttle():
    pc = _PlayerControl(); pc.impulse_level = 4
    wheel = _FakeWheel()
    _route_scroll_wheel(1.0, route_to_panel=True, mx=10, my=20,
                        send_wheel=wheel, player_control=pc, can_throttle=True)
    assert pc.impulse_level == 4  # throttle untouched
    assert wheel.calls == [(10, 20, _WHEEL_PX_PER_NOTCH)]


def test_over_panel_scales_and_signs_delta():
    wheel = _FakeWheel()
    _route_scroll_wheel(-2.0, route_to_panel=True, mx=5, my=6,
                        send_wheel=wheel, player_control=None, can_throttle=False)
    assert wheel.calls == [(5, 6, -2 * _WHEEL_PX_PER_NOTCH)]


# Throttle direction is negated relative to the raw accumulator (see
# _route_scroll_wheel): a wheel-up gesture produces a negative accumulator on
# the target platform and must INCREASE speed.
def test_open_space_wheel_up_increments_throttle():
    pc = _PlayerControl(); pc.impulse_level = 4
    wheel = _FakeWheel()
    _route_scroll_wheel(-1.0, route_to_panel=False, mx=0, my=0,
                        send_wheel=wheel, player_control=pc, can_throttle=True)
    assert pc.impulse_level == 5
    assert wheel.calls == []


def test_open_space_wheel_down_decrements_throttle():
    pc = _PlayerControl(); pc.impulse_level = 1
    _route_scroll_wheel(1.0, route_to_panel=False, mx=0, my=0,
                        send_wheel=_FakeWheel(), player_control=pc, can_throttle=True)
    assert pc.impulse_level == 0


def test_throttle_blocked_when_cannot_throttle():
    pc = _PlayerControl(); pc.impulse_level = 4
    _route_scroll_wheel(1.0, route_to_panel=False, mx=0, my=0,
                        send_wheel=_FakeWheel(), player_control=pc, can_throttle=False)
    assert pc.impulse_level == 4  # bridge view / no player → no throttle


def test_multi_notch_open_space():
    # Three wheel-up notches (negative accumulator) → +3 impulse.
    pc = _PlayerControl(); pc.impulse_level = 0
    _route_scroll_wheel(-3.0, route_to_panel=False, mx=0, my=0,
                        send_wheel=_FakeWheel(), player_control=pc, can_throttle=True)
    assert pc.impulse_level == 3


def test_panel_route_with_no_send_wheel_is_safe():
    # No CEF binding available → no crash, no throttle change.
    pc = _PlayerControl(); pc.impulse_level = 4
    _route_scroll_wheel(1.0, route_to_panel=True, mx=0, my=0,
                        send_wheel=None, player_control=pc, can_throttle=True)
    assert pc.impulse_level == 4
