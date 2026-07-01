"""_poll_function_keys derives rising/falling edges from host_io.key_state
and forwards them into g_kInputManager as WC_F1..F5."""
import App
from engine import host_io
from engine.host_loop import _poll_function_keys, _fn_key_prev
from engine.input_map import InputMap


class _FakeKeys:
    KEY_F1, KEY_F2, KEY_F3, KEY_F4, KEY_F5 = 290, 291, 292, 293, 294


class _FakeHost:
    keys = _FakeKeys()

    def __init__(self):
        self.down = set()

    def key_state(self, key):
        return key in self.down


def setup_function(_):
    _fn_key_prev.clear()


def test_edges_forwarded(monkeypatch):
    # Default InputMap binds talk_helm→F1 (GLFW 290) … talk_engineering→F5.
    im = InputMap()
    calls = []
    monkeypatch.setattr(App.g_kInputManager, "OnKeyDown",
                        lambda wc: calls.append(("down", wc)))
    monkeypatch.setattr(App.g_kInputManager, "OnKeyUp",
                        lambda wc: calls.append(("up", wc)))
    host = _FakeHost()
    # Key reads route through host_io.key_state; point that at the fake host.
    monkeypatch.setattr(host_io, "_h", host)
    _poll_function_keys(host, im)              # all up: nothing
    assert calls == []
    host.down.add(290)
    _poll_function_keys(host, im)              # F1 rising edge
    assert calls == [("down", App.WC_F1)]
    _poll_function_keys(host, im)              # held: no repeat
    assert calls == [("down", App.WC_F1)]
    host.down.clear()
    _poll_function_keys(host, im)              # falling edge
    assert calls == [("down", App.WC_F1), ("up", App.WC_F1)]


def test_absent_host_is_noop(monkeypatch):
    im = InputMap()
    # host_io._h is None when the native module is absent (headless); the
    # host_io.key_state wrapper then returns False and no edges fire.
    monkeypatch.setattr(host_io, "_h", None)
    _poll_function_keys(None, im)              # must not raise

    class _NoKeys:
        pass
    _poll_function_keys(_NoKeys(), im)         # must not raise


def test_poller_routes_key_state_through_host_io(monkeypatch):
    """The poller must read key state via the host_io.key_state wrapper, not
    a raw module handle — so patching the wrapper alone drives the edges."""
    im = InputMap()                            # talk_helm → F1 (GLFW 290)
    calls = []
    monkeypatch.setattr(App.g_kInputManager, "OnKeyDown",
                        lambda wc: calls.append(("down", wc)))
    monkeypatch.setattr(App.g_kInputManager, "OnKeyUp",
                        lambda wc: calls.append(("up", wc)))
    down = {290}
    monkeypatch.setattr(host_io, "key_state", lambda k: k in down)
    _poll_function_keys(None, im)              # F1 rising edge via the wrapper
    assert calls == [("down", App.WC_F1)]
    down.clear()
    _poll_function_keys(None, im)              # falling edge via the wrapper
    assert calls == [("down", App.WC_F1), ("up", App.WC_F1)]
