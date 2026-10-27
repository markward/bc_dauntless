"""The boot notice splash through the real pre-boot pump loop, headless.

engine/ui/boot_notice_panel.py's schedule is covered in
tests/unit/test_boot_notice_panel.py. This drives host_loop._begin_boot_notice
end to end with a fake 60 Hz wall clock, a fake renderer and a fake CEF
that drops every push until its page loads (the gate
tests/host/test_first_run_pump_loop.py models) and answers the arm payload
one frame later, the way the page's dauntlessEvent does. Then the wiring
into run(): when the splash shows, and that the game loads behind it.
"""
import json
import re
import sys
import types

import pytest

from engine import host_loop
from tests.helpers.source_guards import code_only
from tests.host.test_first_run_pump_loop import _FakeCefState

FRAME_S = 1.0 / 60.0


class _Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class _Page(_FakeCefState):
    """A page that acknowledges the arm payload on the frame after it lands."""

    def __init__(self):
        super().__init__()
        self.pending_events = []

    def cef_execute_javascript(self, script):
        super().cef_execute_javascript(script)
        if self.page_loaded and '"ack": true' in script:
            self.pending_events.append("boot-notice/shown")

    def deliver(self):
        events, self.pending_events = self.pending_events, []
        for e in events:
            self.event_handler(e)


@pytest.fixture
def rig(monkeypatch):
    page = _Page()
    mod = types.ModuleType("_dauntless_host")
    for n in ("cef_execute_javascript", "cef_set_load_end_handler",
              "cef_set_event_handler", "cef_send_mouse_move",
              "cef_send_mouse_click", "cursor_pos", "framebuffer_size"):
        setattr(mod, n, getattr(page, n))
    mod.keys = types.SimpleNamespace(MOUSE_BUTTON_LEFT=0)
    monkeypatch.setitem(sys.modules, "_dauntless_host", mod)

    clock = _Clock()
    state = {"frames": 0, "load_at_frame": 20, "close_at_frame": None,
             "hologram": [], "ack_at": None, "pushes": []}

    def frame():
        state["frames"] += 1
        clock.t += FRAME_S
        if state["frames"] == state["load_at_frame"]:
            page.fire_load_end()
        had = bool(page.pending_events)
        page.deliver()
        if had and state["ack_at"] is None:
            state["ack_at"] = clock.t

    monkeypatch.setattr(host_loop.r, "frame", frame)
    monkeypatch.setattr(host_loop.r, "should_close",
                        lambda: state["close_at_frame"] is not None
                        and state["frames"] >= state["close_at_frame"])
    monkeypatch.setattr(host_loop.r, "set_hologram_only_mode",
                        lambda on, c: state["hologram"].append((on, c)))
    monkeypatch.setattr(host_loop.host_io, "mouse_button_pressed", lambda b: False)
    monkeypatch.setattr(host_loop.host_io, "mouse_button_released", lambda b: False)
    return page, clock, state


def _opacity_trace(page):
    """(index in page.pushed, opacity) for every opacity push that landed."""
    out = []
    for i, s in enumerate(page.pushed):
        m = re.fullmatch(r"setBootNotice\((.*)\);", s)
        if m and m.group(1) != "null":
            out.append(json.loads(m.group(1))["opacity"])
    return out


def _play(clock, load_s):
    """Fade in, load for `load_s` seconds of wall clock with nothing pumped
    (as run() does), then finish. Returns (held panel, release time, end)."""
    panel = host_loop._begin_boot_notice(clock=clock)
    assert panel is not None
    clock.t += load_s
    released_at = clock.t
    outcome = host_loop._finish_boot_notice(panel)
    assert outcome == "shown"
    return panel, released_at, clock.t


def test_the_fade_in_is_timed_from_page_load_not_from_the_loop(rig):
    page, clock, state = rig
    start = clock.t
    host_loop._begin_boot_notice(clock=clock)
    # The ~20 frames before the page loaded did not eat the fade-in.
    assert state["ack_at"] - start == pytest.approx(20 * FRAME_S, abs=2 * FRAME_S)
    assert clock.t - state["ack_at"] == pytest.approx(
        1.0 + 0.15, abs=2 * FRAME_S)


def test_the_begin_hands_back_with_the_notice_at_full_opacity_and_up(rig):
    page, clock, state = rig
    host_loop._begin_boot_notice(clock=clock)
    trace = _opacity_trace(page)
    assert trace[-1] == 1.0
    assert "setBootNotice(null);" not in page.pushed
    # Pumping stops here: the window holds this frame through the load.
    assert state["hologram"] == [(True, (0.0, 0.0, 0.0)), (False, (0.0, 0.0, 0.0))]


def test_a_quick_load_keeps_the_five_second_schedule(rig):
    page, clock, state = rig
    _, released_at, end = _play(clock, load_s=0.5)
    assert end - state["ack_at"] == pytest.approx(5.0, abs=2 * FRAME_S)
    assert page.pushed[-1] == "setBootNotice(null);"


def test_a_long_load_holds_the_notice_then_fades_for_two_seconds(rig):
    page, clock, state = rig
    _, released_at, end = _play(clock, load_s=6.0)
    assert end - released_at == pytest.approx(2.0, abs=2 * FRAME_S)
    assert page.pushed[-1] == "setBootNotice(null);"


def test_pushes_before_the_page_loads_are_dropped_and_harmless(rig):
    page, clock, state = rig
    _play(clock, load_s=0.5)
    assert page.dropped and all('"ack": true' in s for s in page.dropped)


def test_the_fade_in_hold_and_fade_out_reach_the_page(rig):
    page, clock, state = rig
    _play(clock, load_s=3.0)
    trace = _opacity_trace(page)

    peak = trace.index(1.0)
    rise = trace[:peak + 1]
    fall = [o for o in trace[peak + 1:] if o != 1.0]
    assert rise[0] == 0.0
    assert rise == sorted(rise)
    # ~60 pushes to climb in 1 s at 60 Hz; the hold pushes nothing new.
    assert 55 <= len([o for o in rise if 0.0 < o < 1.0]) <= 62
    assert fall == sorted(fall, reverse=True)
    assert 110 <= len(fall) <= 122
    assert fall[-1] < 0.05


def test_the_scene_pass_is_off_and_black_while_the_notice_pumps(rig):
    page, clock, state = rig
    _play(clock, load_s=1.0)
    black = (0.0, 0.0, 0.0)
    assert state["hologram"] == [(True, black), (False, black)] * 2


def test_closing_the_window_ends_the_splash(rig):
    page, clock, state = rig
    state["close_at_frame"] = 30
    assert host_loop._begin_boot_notice(clock=clock) is None
    assert state["frames"] == 30


def test_a_page_that_never_loads_gives_up_rather_than_hang(rig, capsys):
    page, clock, state = rig
    state["load_at_frame"] = None
    assert host_loop._begin_boot_notice(clock=clock) is None
    assert "[boot-notice]" in capsys.readouterr().err


# ── when it shows ───────────────────────────────────────────────────────

def test_shown_on_a_normal_launch():
    assert host_loop._boot_notice_wanted({}, None, True, modules={})


@pytest.mark.parametrize("environ, max_ticks, cef_ready, modules", [
    ({"OPEN_STBC_HOST_HEADLESS": "1"}, None, True, {}),
    ({}, 2, True, {}),
    ({}, None, False, {}),
    ({}, None, True, {"pytest": object()}),
])
def test_never_in_headless_scripted_cefless_or_test_runs(
        environ, max_ticks, cef_ready, modules):
    assert not host_loop._boot_notice_wanted(environ, max_ticks, cef_ready,
                                             modules=modules)


def test_the_suite_itself_never_shows_it():
    assert not host_loop._boot_notice_wanted({}, None, True)


def test_run_loads_the_game_behind_the_notice():
    """Fade in after the pre-boot screens; load the SDK, the mission and
    every bit of loop setup behind it; fade out right before the game loop.
    The pump loop replaces run()'s CEF handlers, so both are put back after
    the fade-out, and the frame clock restarts so the fade is not replayed
    as up to MAX_FRAME_DT of sim time on the first frame."""
    import inspect
    source = code_only(inspect.getsource(host_loop.run))
    resolve_at = source.index("_resolve_paths_or_report(")
    mods_at = source.index("run_mods_screen(")
    begin_at = source.index("_begin_boot_notice(")
    prewarm_at = source.index("_prewarm_sdk_modules()")
    mission_at = source.index("controller.loader.load")
    clock_at = source.index("_previous_real_time = time.monotonic()")
    finish_at = source.index("_finish_boot_notice(")
    loop_at = source.index("while not r.should_close():")
    assert (resolve_at < mods_at < begin_at < prewarm_at < mission_at
            < clock_at < finish_at < loop_at)

    after = source[finish_at:loop_at]
    assert "_cef_set_event_handler(registry.dispatch)" in after
    assert "_cef_set_load_end(_on_cef_load_end)" in after
    assert "_previous_real_time = time.monotonic()" in after
