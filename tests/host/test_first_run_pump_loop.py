"""The first-run screen's PUMP LOOP: page-load gating and mouse forwarding.

FirstRunPanel's own decisions (tests/unit/test_first_run_panel.py) and the
wiring into _resolve_paths_or_report (tests/host/test_host_loop_first_run.py)
are both covered elsewhere. This file is the gap neither covers: the actual
frame loop inside _run_first_run_screen -- driven here with fakes for
r.frame/should_close/set_hologram_only_mode and the _h.cef_* bindings,
modelling the REAL semantics that made the screen dead on arrival at the
final review:

  CRITICAL 1 -- cef_lifecycle.cc's execute_javascript() silently drops every
  push until the browser's own load-end fires (CreateBrowser is async,
  ~340ms measured), and CreateBrowser is asynchronous relative to the pump
  loop starting. Without a load-end handler wired to panel.invalidate(), the
  screen's only payload goes out on frame 1 -- before the page can receive
  it -- and nothing ever re-pushes, because render_payload() diffs against
  its own cache and the snapshot never changes on its own. FakeCef's
  page_loaded gate models exactly this.

  CRITICAL 2 -- run()'s cef_send_mouse_move/click bindings are only ever
  called from INSIDE the game loop (pause menu, crew menus, ...), which does
  not exist yet while this screen is up. Without forwarding wired into this
  loop specifically, nothing on the page is ever clickable.

This is the test that would have caught both: it is written to fail against
the pre-fix loop and pass against the fixed one, proven by running it
against a backed-up copy of the broken source (see the fix commit's report
for the RED/GREEN transcript).
"""
import sys
import types

import pytest

from engine import host_loop, paths


class FakeStore:
    def has(self, section, key):
        return False

    def get(self, section, key):
        raise KeyError((section, key))

    def set(self, section, key, value):
        pass


def _unresolved_resolution():
    """A Resolution with neither root set -- the shape that hands off to
    the first-run screen in the first place."""
    return paths.resolve(argv=[], env={}, store=FakeStore())


class _FakeCefState:
    """Records what the pump loop actually does to CEF, and models the one
    piece of real CEF behaviour that matters here: execute_javascript is a
    no-op until page_loaded flips True (cef_lifecycle.cc's own gate)."""

    def __init__(self):
        self.page_loaded = False
        self.pushed = []       # scripts that reached the "page"
        self.dropped = []      # scripts pushed while the gate was shut
        self.load_end_handler = None
        self.event_handler = None
        self.mouse_moves = []
        self.mouse_clicks = []
        self.cursor = (0, 0)
        self.fb_size = (1280, 720)

    def cef_execute_javascript(self, script):
        if self.page_loaded:
            self.pushed.append(script)
        else:
            self.dropped.append(script)

    def cef_set_load_end_handler(self, cb):
        self.load_end_handler = cb

    def cef_set_event_handler(self, cb):
        self.event_handler = cb

    def cef_send_mouse_move(self, x, y):
        self.mouse_moves.append((x, y))

    def cef_send_mouse_click(self, x, y, button, is_down):
        self.mouse_clicks.append((x, y, button, is_down))

    def cursor_pos(self):
        return self.cursor

    def framebuffer_size(self):
        return self.fb_size

    def fire_load_end(self):
        """Simulate the browser actually finishing its (async) load."""
        self.page_loaded = True
        if self.load_end_handler is not None:
            self.load_end_handler()


@pytest.fixture
def fake_cef(monkeypatch):
    """A fake `_dauntless_host` module standing in for the compiled
    extension -- same technique test_first_run_panel.py's
    test_a_raising_binding_is_treated_as_no_picker uses."""
    state = _FakeCefState()
    fake_module = types.ModuleType("_dauntless_host")
    fake_module.cef_execute_javascript = state.cef_execute_javascript
    fake_module.cef_set_load_end_handler = state.cef_set_load_end_handler
    fake_module.cef_set_event_handler = state.cef_set_event_handler
    fake_module.cef_send_mouse_move = state.cef_send_mouse_move
    fake_module.cef_send_mouse_click = state.cef_send_mouse_click
    fake_module.cursor_pos = state.cursor_pos
    fake_module.framebuffer_size = state.framebuffer_size
    fake_module.keys = types.SimpleNamespace(MOUSE_BUTTON_LEFT=0)
    monkeypatch.setitem(sys.modules, "_dauntless_host", fake_module)
    return state


@pytest.fixture
def fake_renderer(monkeypatch):
    """Stub r.should_close/r.frame/r.set_hologram_only_mode so the loop
    runs a bounded number of iterations without a real window. `frames`
    counts completed r.frame() calls; should_close() flips True once it
    reaches `max_frames`."""
    calls = {"frames": 0, "max_frames": 3, "hologram": []}

    def should_close():
        return calls["frames"] >= calls["max_frames"]

    def frame():
        calls["frames"] += 1

    def set_hologram_only_mode(on, colour):
        calls["hologram"].append(on)

    monkeypatch.setattr(host_loop.r, "should_close", should_close)
    monkeypatch.setattr(host_loop.r, "frame", frame)
    monkeypatch.setattr(host_loop.r, "set_hologram_only_mode", set_hologram_only_mode)
    return calls


@pytest.fixture
def no_mouse_edges(monkeypatch):
    """No button state at all -- isolates the pure move-forwarding tests
    from click forwarding."""
    monkeypatch.setattr(host_loop.host_io, "mouse_button_pressed", lambda b: False)
    monkeypatch.setattr(host_loop.host_io, "mouse_button_released", lambda b: False)


def test_the_screen_pushes_nothing_until_the_page_load_end_fires(
        fake_cef, fake_renderer, no_mouse_edges):
    """CRITICAL 1: with no load-end handler wired to panel.invalidate(),
    the screen's only payload goes out on frame 1 and is dropped, and
    nothing ever re-pushes."""
    fake_renderer["max_frames"] = 5

    host_loop._run_first_run_screen(_unresolved_resolution())

    assert fake_cef.dropped, (
        "the screen must still have TRIED to push while the page had not "
        "loaded -- otherwise this test can't distinguish 'never pushed' "
        "from 'correctly gated'"
    )
    assert fake_cef.pushed == [], (
        "the page never loaded in this run, so NOTHING should have "
        "reached it -- if this is non-empty, something pushed before the "
        "gate opened, or the loop is somehow bypassing the drop"
    )


def test_a_page_load_mid_run_gets_the_next_payload_through(
        fake_cef, fake_renderer, no_mouse_edges, monkeypatch):
    """The counterpart proof: once the browser's load-end actually fires
    (simulated here on the loop's 2nd r.frame() call, mimicking the real
    ~340ms-later CreateBrowser completion landing mid-loop), the panel's
    state must reach the page on a later frame instead of staying dropped
    forever. This is what the load-end handler registration buys --
    without CRITICAL 1's fix, page_loaded flipping true changes nothing,
    because nothing is listening for it to re-invalidate the panel's
    already-cached (and already dropped) snapshot, so render_payload()
    keeps returning None on every later frame.

    Filters out the unconditional "setFirstRun(null);" teardown push the
    `finally` block always makes on the way out -- that one reaches the
    page too (page_loaded is true by then in BOTH the broken and fixed
    loop, since nothing gates it on the load-end handler ever having
    fired), so counting it would pass against the broken loop as well and
    prove nothing.
    """
    fake_renderer["max_frames"] = 5
    calls = fake_renderer

    def frame_that_loads_on_call_2():
        calls["frames"] += 1
        if calls["frames"] == 2:
            fake_cef.fire_load_end()
    monkeypatch.setattr(host_loop.r, "frame", frame_that_loads_on_call_2)

    host_loop._run_first_run_screen(_unresolved_resolution())

    real_pushes = [s for s in fake_cef.pushed if s != "setFirstRun(null);"]
    assert real_pushes, (
        "once fire_load_end() ran, the screen's real STATE payload "
        "(setFirstRun({...}), not the teardown's setFirstRun(null)) must "
        "reach the page on a later frame instead of staying dropped "
        "forever -- this only happens if the load-end handler re-invalidates "
        "the panel so render_payload() has something new to emit"
    )


def test_mouse_position_is_forwarded_every_frame(
        fake_cef, fake_renderer, no_mouse_edges):
    """CRITICAL 2: without mouse-move forwarding wired into this loop
    specifically, the cursor never reaches CEF at all while this screen is
    up, and nothing on the page can ever be hovered or clicked."""
    fake_renderer["max_frames"] = 4

    host_loop._run_first_run_screen(_unresolved_resolution())

    assert len(fake_cef.mouse_moves) == 4, (
        "mouse position must be forwarded to CEF on every iteration of "
        "this loop, the same way run()'s pause-menu block forwards it "
        "every frame the pause menu is open"
    )


def test_a_left_click_press_edge_is_forwarded_to_cef(
        fake_cef, fake_renderer, monkeypatch):
    """A hover with no click forwarding would still leave Browse/Continue/
    Quit un-clickable -- the press EDGE (not just cursor position) must
    reach cef_send_mouse_click as a mouse-down."""
    fake_renderer["max_frames"] = 3
    state = {"checked": 0}

    def pressed(button):
        state["checked"] += 1
        return state["checked"] == 1  # a press on the very first poll only

    monkeypatch.setattr(host_loop.host_io, "mouse_button_pressed", pressed)
    monkeypatch.setattr(host_loop.host_io, "mouse_button_released", lambda b: False)

    host_loop._run_first_run_screen(_unresolved_resolution())

    downs = [c for c in fake_cef.mouse_clicks if c[3] is True]
    assert downs, (
        "a left-button press edge during the screen must be forwarded to "
        "CEF as a mouse-down (cef_send_mouse_click(..., is_down=True)), or "
        "clicking Browse/Continue/Quit does nothing"
    )


def test_a_left_click_release_edge_is_forwarded_to_cef(
        fake_cef, fake_renderer, monkeypatch):
    """The matching release edge must also reach CEF -- a click that never
    releases would leave the button stuck down in the page's own DOM."""
    fake_renderer["max_frames"] = 3
    state = {"checked": 0}

    def released(button):
        state["checked"] += 1
        return state["checked"] == 1

    monkeypatch.setattr(host_loop.host_io, "mouse_button_pressed", lambda b: False)
    monkeypatch.setattr(host_loop.host_io, "mouse_button_released", released)

    host_loop._run_first_run_screen(_unresolved_resolution())

    ups = [c for c in fake_cef.mouse_clicks if c[3] is False]
    assert ups, (
        "a left-button release edge during the screen must be forwarded "
        "to CEF as a mouse-up (cef_send_mouse_click(..., is_down=False))"
    )
