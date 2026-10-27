"""The boot notice splash through the real pre-boot pump loop, headless.

engine/ui/boot_notice_panel.py's schedule is covered in
tests/unit/test_boot_notice_panel.py. This drives host_loop._run_boot_notice
end to end with a fake 60 Hz wall clock, a fake renderer and a fake CEF
that drops every push until its page loads (the gate
tests/host/test_first_run_pump_loop.py models) and answers the arm payload
one frame later, the way the page's dauntlessEvent does. Then the wiring
into run(): when the splash shows, and that it comes before the mission.
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


def test_the_splash_runs_five_seconds_from_page_load_then_boot_continues(rig):
    page, clock, state = rig
    start = clock.t

    outcome = host_loop._run_boot_notice(clock=clock)

    assert outcome == "shown"
    assert state["ack_at"] is not None
    # Measured from the acknowledgement, not from the start of the loop:
    # the ~20 frames before the page loaded did not eat the fade-in.
    assert state["ack_at"] - start == pytest.approx(20 * FRAME_S, abs=2 * FRAME_S)
    assert clock.t - state["ack_at"] == pytest.approx(5.0, abs=2 * FRAME_S)
    assert page.pushed[-1] == "setBootNotice(null);"


def test_pushes_before_the_page_loads_are_dropped_and_harmless(rig):
    page, clock, state = rig
    host_loop._run_boot_notice(clock=clock)
    assert page.dropped and all('"ack": true' in s for s in page.dropped)


def test_the_fade_in_hold_and_fade_out_reach_the_page(rig):
    page, clock, state = rig
    host_loop._run_boot_notice(clock=clock)
    trace = _opacity_trace(page)

    peak = trace.index(1.0)
    rise = trace[:peak + 1]
    fall = trace[peak + 1:]
    assert rise[0] == 0.0
    assert rise == sorted(rise)
    # ~60 pushes to climb in 1 s at 60 Hz; the 2 s hold pushes nothing new.
    assert 55 <= len([o for o in rise if 0.0 < o < 1.0]) <= 62
    assert fall == sorted(fall, reverse=True)
    assert 110 <= len(fall) <= 122
    assert fall[-1] < 0.05


def test_the_scene_pass_is_off_and_black_for_the_whole_splash(rig):
    page, clock, state = rig
    host_loop._run_boot_notice(clock=clock)
    assert state["hologram"] == [(True, (0.0, 0.0, 0.0)), (False, (0.0, 0.0, 0.0))]


def test_closing_the_window_ends_the_splash(rig):
    page, clock, state = rig
    state["close_at_frame"] = 60
    assert host_loop._run_boot_notice(clock=clock) is None
    assert state["frames"] == 60


def test_a_page_that_never_loads_gives_up_rather_than_hang(rig, capsys):
    page, clock, state = rig
    state["load_at_frame"] = None
    assert host_loop._run_boot_notice(clock=clock) == "unshown"
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


def test_run_shows_it_after_the_preboot_screens_and_before_the_mission():
    import inspect
    source = code_only(inspect.getsource(host_loop.run))
    resolve_at = source.index("_resolve_paths_or_report(")
    mods_at = source.index("run_mods_screen(")
    notice_at = source.index("_run_boot_notice(")
    mission_at = source.index("controller.loader.load")
    assert resolve_at < mods_at < notice_at < mission_at
