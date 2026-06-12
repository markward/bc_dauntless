"""_poll_function_keys derives rising/falling edges from host.key_state
and forwards them into g_kInputManager as WC_F1..F5."""
import App
from engine.host_loop import _poll_function_keys, _fn_key_prev


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
    calls = []
    monkeypatch.setattr(App.g_kInputManager, "OnKeyDown",
                        lambda wc: calls.append(("down", wc)))
    monkeypatch.setattr(App.g_kInputManager, "OnKeyUp",
                        lambda wc: calls.append(("up", wc)))
    host = _FakeHost()
    _poll_function_keys(host)                  # all up: nothing
    assert calls == []
    host.down.add(290)
    _poll_function_keys(host)                  # F1 rising edge
    assert calls == [("down", App.WC_F1)]
    _poll_function_keys(host)                  # held: no repeat
    assert calls == [("down", App.WC_F1)]
    host.down.clear()
    _poll_function_keys(host)                  # falling edge
    assert calls == [("down", App.WC_F1), ("up", App.WC_F1)]


def test_absent_host_is_noop():
    _poll_function_keys(None)                  # must not raise

    class _NoKeys:
        pass
    _poll_function_keys(_NoKeys())             # must not raise
