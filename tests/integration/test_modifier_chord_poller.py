"""_poll_modifier_chords: modifier+key chords → g_kInputManager.OnChordDown.

Drives the poller with a fake host.keys namespace and a patched
host_io.key_state, per the established poller-test pattern (patch host_io,
never the native module).
"""
from types import SimpleNamespace
from unittest.mock import patch

import App
import engine.host_loop as host_loop


def _fake_keys():
    ns = SimpleNamespace()
    # GLFW codes are arbitrary ints for the test — internal consistency only.
    ns.KEY_LEFT_ALT, ns.KEY_RIGHT_ALT = 342, 346
    ns.KEY_LEFT_CONTROL, ns.KEY_RIGHT_CONTROL = 341, 345
    ns.KEY_LEFT_SHIFT, ns.KEY_RIGHT_SHIFT = 340, 344
    for i, ch in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
        setattr(ns, "KEY_" + ch, 65 + i)
    for d in range(10):
        setattr(ns, "KEY_%d" % d, 48 + d)
    for f in range(1, 13):
        setattr(ns, "KEY_F%d" % f, 289 + f)
    return ns


class _KeyState:
    def __init__(self):
        self.down = set()

    def __call__(self, code):
        return 1 if code in self.down else 0


def setup_function(_fn):
    host_loop._chord_prev.clear()


def test_alt_number_chord_emits_on_rising_edge_only():
    keys = _fake_keys()
    host = SimpleNamespace(keys=keys)
    ks = _KeyState()
    calls = []
    with patch.object(host_loop.host_io, "key_state", ks), \
         patch.object(App.g_kInputManager, "OnChordDown",
                      side_effect=lambda wc: calls.append(("down", wc))), \
         patch.object(App.g_kInputManager, "OnKeyUp",
                      side_effect=lambda wc: calls.append(("up", wc))):
        ks.down = {keys.KEY_LEFT_ALT, keys.KEY_1}
        host_loop._poll_modifier_chords(host)
        host_loop._poll_modifier_chords(host)      # held: no repeat
        ks.down = {keys.KEY_LEFT_ALT}
        host_loop._poll_modifier_chords(host)      # released: keyup
    assert calls == [("down", App.WC_ALT_1), ("up", App.WC_ALT_1)]


def test_no_modifier_no_emission():
    keys = _fake_keys()
    host = SimpleNamespace(keys=keys)
    ks = _KeyState()
    calls = []
    with patch.object(host_loop.host_io, "key_state", ks), \
         patch.object(App.g_kInputManager, "OnChordDown",
                      side_effect=lambda wc: calls.append(wc)):
        ks.down = {keys.KEY_1}
        host_loop._poll_modifier_chords(host)
    assert calls == []


def test_debug_chords_gated_behind_dev_mode():
    import engine.dev_mode as dev_mode
    keys = _fake_keys()
    host = SimpleNamespace(keys=keys)
    ks = _KeyState()
    calls = []
    with patch.object(host_loop.host_io, "key_state", ks), \
         patch.object(App.g_kInputManager, "OnChordDown",
                      side_effect=lambda wc: calls.append(wc)):
        ks.down = {keys.KEY_LEFT_SHIFT, keys.KEY_G}     # Shift+G god mode
        with patch.object(dev_mode, "is_enabled", return_value=False):
            host_loop._poll_modifier_chords(host)
        assert calls == [], "debug chord must not emit outside --developer"
        host_loop._chord_prev.clear()
        with patch.object(dev_mode, "is_enabled", return_value=True):
            host_loop._poll_modifier_chords(host)
        assert calls == [App.WC_CAPS_G]


def test_base_keys_suppressed_while_alt_held():
    keys = _fake_keys()
    ks = _KeyState()
    downs, ups = [], []
    keymap = ((keys.KEY_F, 0x46),)   # WC_F = 0x46
    with patch.object(host_loop.host_io, "key_state", ks), \
         patch.object(App.g_kInputManager, "OnKeyDown",
                      side_effect=lambda wc: downs.append(wc)), \
         patch.object(App.g_kInputManager, "OnKeyUp",
                      side_effect=lambda wc: ups.append(wc)):
        host_loop._fn_key_prev.clear()
        ks.down = {keys.KEY_F}
        host_loop._poll_key_table(keymap)                  # plain F: fires
        assert downs == [0x46]
        ks.down = {keys.KEY_F, keys.KEY_LEFT_ALT}
        host_loop._poll_key_table(keymap, suppress=True)   # Alt held: released
        assert ups == [0x46]
        host_loop._poll_key_table(keymap, suppress=True)   # stays quiet
        assert downs == [0x46]


def test_alt_t_and_alt_c_drive_direct_toggles_not_events():
    keys = _fake_keys()
    host = SimpleNamespace(keys=keys)
    ks = _KeyState()
    chord_calls, tractor_calls = [], []
    with patch.object(host_loop.host_io, "key_state", ks), \
         patch.object(App.g_kInputManager, "OnChordDown",
                      side_effect=lambda wc: chord_calls.append(wc)), \
         patch.object(App, "ToggleTractorFromInput",
                      side_effect=lambda: tractor_calls.append(1)):
        ks.down = {keys.KEY_LEFT_ALT, keys.KEY_T}
        host_loop._poll_modifier_chords(host)
        host_loop._poll_modifier_chords(host)      # held: one toggle only
    assert tractor_calls == [1]
    assert App.WC_ALT_T not in chord_calls
