"""Remapping a fire action moves which physical key the poller forwards.

_poll_fire_keys reads the physical key for each fire action from the InputMap
and forwards it as the fixed WC_F/WC_X/WC_G code.  Rebinding fire_primary should
make the new key fire phasers (WC_F) and the old key go silent — proving the
remap takes effect end-to-end through the poller without touching the BC
WC→ET binding table.
"""
import App
from engine import host_io
from engine.host_loop import _poll_fire_keys, _fn_key_prev
from engine.input_map import InputMap, GLFW_KEYS


class _FakeHost:
    def __init__(self):
        self.down = set()

    def key_state(self, key):
        return key in self.down


def setup_function(_):
    _fn_key_prev.clear()


def test_default_fire_key_forwards_wc_f(monkeypatch):
    im = InputMap()                       # fire_primary → F
    calls = []
    monkeypatch.setattr(App.g_kInputManager, "OnKeyDown",
                        lambda wc: calls.append(wc))
    host = _FakeHost()
    # Key reads route through host_io.key_state; point that at the fake host.
    monkeypatch.setattr(host_io, "_h", host)
    host.down.add(GLFW_KEYS["F"])
    _poll_fire_keys(host, im)
    assert App.WC_F in calls


def test_remapped_fire_key_forwards_wc_f_and_old_is_silent(monkeypatch):
    im = InputMap()
    im.set("fire_primary", "J")           # remap phasers F → J
    calls = []
    monkeypatch.setattr(App.g_kInputManager, "OnKeyDown",
                        lambda wc: calls.append(wc))
    monkeypatch.setattr(App.g_kInputManager, "OnKeyUp", lambda wc: None)

    host = _FakeHost()
    monkeypatch.setattr(host_io, "_h", host)
    # Old key F: no longer forwards primary fire.
    host.down.add(GLFW_KEYS["F"])
    _poll_fire_keys(host, im)
    assert App.WC_F not in calls

    # New key J: forwards WC_F (phasers).
    _fn_key_prev.clear()
    host.down.clear()
    host.down.add(GLFW_KEYS["J"])
    _poll_fire_keys(host, im)
    assert App.WC_F in calls
