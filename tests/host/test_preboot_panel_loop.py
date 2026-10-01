"""_run_preboot_panel: the shared pre-boot pump loop (first-run picker and the
Mods screen). Mouse and page-load behaviour are guarded by
test_first_run_pump_loop.py through _run_first_run_screen; this file covers
what the extraction added -- keyboard forwarding, Escape, teardown."""
import sys
import types

import pytest

from engine import host_loop
from tests.host.test_first_run_pump_loop import _FakeCefState


class _Panel:
    name = "mods"
    teardown_script = "setModsScreen(null);"

    def __init__(self):
        self.outcome = None
        self.esc = 0
        self.events = []

    def render_payload(self): return None
    def dispatch_event(self, a): self.events.append(a); return True
    def invalidate(self): pass
    def handle_key_esc(self): self.esc += 1


@pytest.fixture
def cef(monkeypatch):
    state = _FakeCefState()
    state.sent_keys = []
    state.queue = [(0, ord("a"), 0, 1, 0), (1, 256, 53, 1, 0)]   # 'a', then ESC press
    mod = types.ModuleType("_dauntless_host")
    for n in ("cef_execute_javascript", "cef_set_load_end_handler", "cef_set_event_handler",
              "cef_send_mouse_move", "cef_send_mouse_click", "cursor_pos", "framebuffer_size"):
        setattr(mod, n, getattr(state, n))
    mod.drain_text_events = lambda: [state.queue.pop(0)] if state.queue else []
    mod.cef_send_key_event = lambda *ev: state.sent_keys.append(ev)
    mod.keys = types.SimpleNamespace(MOUSE_BUTTON_LEFT=0, KEY_ESCAPE=256)
    monkeypatch.setitem(sys.modules, "_dauntless_host", mod)
    state.page_loaded = True
    return state


@pytest.fixture
def renderer(monkeypatch):
    calls = {"frames": 0}
    monkeypatch.setattr(host_loop.r, "should_close", lambda: calls["frames"] >= 3)
    monkeypatch.setattr(host_loop.r, "frame", lambda: calls.__setitem__("frames", calls["frames"] + 1))
    monkeypatch.setattr(host_loop.r, "set_hologram_only_mode", lambda on, c: None)
    monkeypatch.setattr(host_loop.host_io, "mouse_button_pressed", lambda b: False)
    monkeypatch.setattr(host_loop.host_io, "mouse_button_released", lambda b: False)
    return calls


def test_text_events_are_forwarded_and_escape_reaches_the_panel(cef, renderer):
    p = _Panel()
    host_loop._run_preboot_panel(p)
    assert cef.sent_keys == [(0, ord("a"), 0, 1, 0), (1, 256, 53, 1, 0)]
    assert p.esc == 1


def test_events_route_by_panel_name(cef, renderer):
    p = _Panel()
    renderer["frames"] = 2
    host_loop._run_preboot_panel(p)
    cef.event_handler("mods/quit")
    cef.event_handler("first-run/continue")
    assert p.events == ["quit"]


def test_teardown_pushes_the_panels_script(cef, renderer):
    p = _Panel()
    host_loop._run_preboot_panel(p)
    assert cef.pushed[-1] == "setModsScreen(null);"


def test_loop_ends_on_outcome(cef, renderer):
    p = _Panel()
    p.outcome = "play"
    host_loop._run_preboot_panel(p)
    assert renderer["frames"] == 0
