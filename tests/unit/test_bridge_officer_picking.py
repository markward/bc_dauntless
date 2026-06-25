"""Bridge officer click-picking — pure projection + menu-open helper.

pick() is driven with a fake host / renderer / bridge-camera and a fake App
module (injected via sys.modules) so the geometry is exercised without a live
engine. open_menu_for_label is tested against a fake TacticalControlWindow."""
import sys
import types

import pytest

from engine.ui import bridge_officer_picking as bop
from engine.ui import crew_menu_hotkeys


# --- fakes ------------------------------------------------------------------

class _FakeOfficer:
    def __init__(self, iid, hidden=False):
        self._render_instance = iid
        self._hidden = hidden

    def IsHidden(self):
        return self._hidden


class _FakeRenderer:
    """get_instance_head_center(iid) -> world head position from a table."""
    def __init__(self, heads):
        self._heads = heads   # iid -> (x, y, z)

    def get_instance_head_center(self, iid):
        return self._heads.get(iid)


class _FakeHost:
    def __init__(self, fb=(800, 600)):
        self._fb = fb

    def framebuffer_size(self):
        return self._fb


class _FakeCamera:
    """Eye at origin looking down +Y, +Z up — an officer at (0, +d, 0) projects
    to screen centre (the aim reticle)."""
    def compute_camera(self):
        return ((0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0),
                bop.math.radians(60.0))


def _install_fake_app(monkeypatch, officers):
    """officers: char_name -> _FakeOfficer (or absent => GetObject returns None).
    TGL GetString is identity (label == key)."""
    bridge = object()

    class _DB:
        def GetString(self, key):
            return key

    app = types.ModuleType("App")
    app.g_kSetManager = types.SimpleNamespace(
        GetSet=lambda name: bridge if name == "bridge" else None)
    app.g_kLocalizationManager = types.SimpleNamespace(
        Load=lambda path: _DB(), Unload=lambda db: None)
    app.CharacterClass_GetObject = lambda b, name: officers.get(name)
    monkeypatch.setitem(sys.modules, "App", app)
    return bridge


# --- pick() -----------------------------------------------------------------

def test_centred_officer_returns_its_label(monkeypatch):
    _install_fake_app(monkeypatch, {"Helm": _FakeOfficer(iid=7)})
    r = _FakeRenderer({7: (0.0, 5.0, 0.0)})       # straight ahead → screen centre
    out = bop.pick(_FakeHost(), r, _FakeCamera())
    assert out == {"label": "Helm"}


def test_off_centre_officer_returns_none(monkeypatch):
    _install_fake_app(monkeypatch, {"Helm": _FakeOfficer(iid=7)})
    r = _FakeRenderer({7: (5.0, 5.0, 0.0)})       # off to the right, not aimed at
    assert bop.pick(_FakeHost(), r, _FakeCamera()) is None


def test_officer_behind_camera_returns_none(monkeypatch):
    _install_fake_app(monkeypatch, {"Helm": _FakeOfficer(iid=7)})
    r = _FakeRenderer({7: (0.0, -5.0, 0.0)})      # behind the eye
    assert bop.pick(_FakeHost(), r, _FakeCamera()) is None


def test_nearest_to_centre_wins(monkeypatch):
    # Helm straight ahead (screen centre); Tactical slightly off — Helm wins.
    _install_fake_app(monkeypatch, {
        "Helm": _FakeOfficer(iid=1),
        "Tactical": _FakeOfficer(iid=2),
    })
    r = _FakeRenderer({1: (0.0, 5.0, 0.0), 2: (0.3, 5.0, 0.2)})
    assert bop.pick(_FakeHost(), r, _FakeCamera()) == {"label": "Helm"}


def test_hidden_officer_is_skipped(monkeypatch):
    _install_fake_app(monkeypatch, {"Helm": _FakeOfficer(iid=7, hidden=True)})
    r = _FakeRenderer({7: (0.0, 5.0, 0.0)})
    assert bop.pick(_FakeHost(), r, _FakeCamera()) is None


def test_officer_without_render_instance_is_skipped(monkeypatch):
    _install_fake_app(monkeypatch, {"Helm": _FakeOfficer(iid=None)})
    r = _FakeRenderer({})
    assert bop.pick(_FakeHost(), r, _FakeCamera()) is None


def test_no_bridge_set_returns_none(monkeypatch):
    app = types.ModuleType("App")
    app.g_kSetManager = types.SimpleNamespace(GetSet=lambda name: None)
    monkeypatch.setitem(sys.modules, "App", app)
    r = _FakeRenderer({7: (0.0, 5.0, 0.0)})
    assert bop.pick(_FakeHost(), r, _FakeCamera()) is None


# --- open_menu_for_label ----------------------------------------------------

class _FakePanel:
    def __init__(self):
        self.toggled = []

    def toggle_menu(self, menu):
        self.toggled.append(menu)


def _install_fake_tcw(monkeypatch, menus):
    """menus: label -> menu object (FindMenu returns None for others)."""
    import engine.appc.windows as windows
    fake = types.SimpleNamespace(FindMenu=lambda label: menus.get(label))
    monkeypatch.setattr(windows.TacticalControlWindow, "GetInstance",
                        staticmethod(lambda: fake))


def test_open_menu_for_label_toggles_found_menu(monkeypatch):
    menu = object()
    _install_fake_tcw(monkeypatch, {"Helm": menu})
    panel = _FakePanel()
    assert crew_menu_hotkeys.open_menu_for_label(panel, "Helm") is True
    assert panel.toggled == [menu]


def test_open_menu_for_label_unknown_label_is_noop(monkeypatch):
    _install_fake_tcw(monkeypatch, {})
    panel = _FakePanel()
    assert crew_menu_hotkeys.open_menu_for_label(panel, "Nope") is False
    assert panel.toggled == []


def test_open_menu_for_label_none_panel_is_noop():
    assert crew_menu_hotkeys.open_menu_for_label(None, "Helm") is False


# --- click state machine (frame-by-frame, faithful mouse-edge semantics) -----

class _EdgeHost:
    """Mirrors the native mouse_button_pressed/released contract: pressed is
    read-only, released advances `prev`. A frame's _poll (pressed then released)
    advances prev exactly once."""
    def __init__(self):
        self._now = {}
        self._prev = {}
        self.keys = types.SimpleNamespace(MOUSE_BUTTON_LEFT=0)
        self.fire_down = 0
        self.fire_up = 0

    def set_down(self, button, down):
        self._now[button] = down

    def mouse_button_pressed(self, button):
        return self._now.get(button, False) and not self._prev.get(button, False)

    def mouse_button_released(self, button):
        now = self._now.get(button, False)
        prev = self._prev.get(button, False)
        self._prev[button] = now
        return prev and not now

    def poll(self):
        """Mimic _poll_mouse_buttons: fire on the surviving press/release edge."""
        b = self.keys.MOUSE_BUTTON_LEFT
        if self.mouse_button_pressed(b):
            self.fire_down += 1
        if self.mouse_button_released(b):
            self.fire_up += 1


class _OpenClosePanel:
    def __init__(self):
        self.open_label = None

    def has_open_menu(self):
        return self.open_label is not None

    def open_menu_label(self):
        return self.open_label

    def close_open_menu(self):
        if self.open_label is None:
            return False
        self.open_label = None
        return True


def _run_frame(host, panel, flag, aimed, monkeypatch):
    """One host-loop frame: handle_click (with pick stubbed to `aimed`) then
    the _poll_mouse_buttons fire poll. Returns the updated pick-active flag."""
    monkeypatch.setattr(bop, "pick", lambda h, r, cam: aimed)
    monkeypatch.setattr(crew_menu_hotkeys, "open_menu_for_label",
                        lambda p, label: setattr(p, "open_label", label) or True)
    flag = bop.handle_click(host, None, None, panel, flag)
    host.poll()
    return flag


def test_click_sequence_open_close_open_again(monkeypatch):
    """Reproduce the live flow: a first click opens, a click closes, and a
    later click opens again — i.e. the state machine never sticks."""
    host = _EdgeHost()
    panel = _OpenClosePanel()
    flag = False
    helm = {"label": "Helm"}

    # Frame 1: press while aiming Helm (menu closed) -> opens Helm, no fire.
    host.set_down(0, True)
    flag = _run_frame(host, panel, flag, helm, monkeypatch)
    assert panel.open_label == "Helm"
    assert host.fire_down == 0

    # Frame 2: hold.
    flag = _run_frame(host, panel, flag, helm, monkeypatch)
    # Frame 3: release -> menu stays open, flag clears.
    host.set_down(0, False)
    flag = _run_frame(host, panel, flag, helm, monkeypatch)
    assert panel.open_label == "Helm"
    assert flag is False

    # Frame 4: press again (menu open) -> closes, no fire.
    host.set_down(0, True)
    flag = _run_frame(host, panel, flag, helm, monkeypatch)
    assert panel.open_label is None
    # Frame 5: hold (menu now closed) -> must NOT reopen on the held button.
    flag = _run_frame(host, panel, flag, helm, monkeypatch)
    assert panel.open_label is None
    # Frame 6: release.
    host.set_down(0, False)
    flag = _run_frame(host, panel, flag, helm, monkeypatch)

    # Frame 7: fresh press while aiming Helm -> opens AGAIN.
    host.set_down(0, True)
    flag = _run_frame(host, panel, flag, helm, monkeypatch)
    assert panel.open_label == "Helm"
    assert host.fire_down == 0   # never fired phasers through the whole sequence


def test_empty_space_click_fires_phasers(monkeypatch):
    """No menu open, not aiming an officer: the press falls through to the
    fire poll (phasers), and the release is not swallowed."""
    host = _EdgeHost()
    panel = _OpenClosePanel()
    flag = False

    host.set_down(0, True)
    flag = _run_frame(host, panel, flag, None, monkeypatch)   # aimed=None
    assert host.fire_down == 1
    assert panel.open_label is None

    host.set_down(0, False)
    flag = _run_frame(host, panel, flag, None, monkeypatch)
    assert host.fire_up == 1
