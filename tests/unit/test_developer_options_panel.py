"""Tests for DeveloperOptionsPanel — the dev-only Combat cheats modal.
Mirrors test_configuration_panel.py: covers state, dispatch (which must
write through to engine.dev_combat_cheats), render_payload dedup, and
keyboard input. Dev mode is forced on so the cheats getters reflect set
values."""
import json

import pytest


@pytest.fixture
def panel():
    import _dauntless_host
    import engine.dev_combat_cheats as cheats
    from engine.ui.developer_options_panel import DeveloperOptionsPanel
    original_dev = getattr(_dauntless_host, "developer_mode", False)
    _dauntless_host.developer_mode = True
    cheats.reset()
    p = DeveloperOptionsPanel()
    try:
        yield p, cheats
    finally:
        cheats.reset()
        _dauntless_host.developer_mode = original_dev


def _body(payload):
    return json.loads(payload[len("setDeveloperOptions("):-2])


# ---- construction / open-close -------------------------------------------

def test_name_is_developer_options(panel):
    p, _ = panel
    assert p.name == "developer-options"


def test_initially_closed(panel):
    p, _ = panel
    assert p.is_open() is False


def test_open_close_round_trip(panel):
    p, _ = panel
    p.open()
    assert p.is_open() is True
    p.close()
    assert p.is_open() is False


def test_open_resyncs_from_cheats_module(panel):
    p, cheats = panel
    cheats.set_god_mode(True)
    p.open()
    body = _body(p.render_payload())
    assert body["settings"]["god_mode"] is True


# ---- dispatch_event writes through to the cheats module ------------------

def test_toggle_god_mode_sets_cheat(panel):
    p, cheats = panel
    p.open()
    assert p.dispatch_event("toggle:god_mode") is True
    assert cheats.god_mode_active() is True
    assert p.dispatch_event("toggle:god_mode") is True
    assert cheats.god_mode_active() is False


def test_toggle_double_weapons_sets_cheat(panel):
    p, cheats = panel
    p.open()
    assert p.dispatch_event("toggle:double_weapons") is True
    assert cheats.double_player_weapons_active() is True


def test_toggle_no_npc_shields_sets_cheat(panel):
    p, cheats = panel
    p.open()
    assert p.dispatch_event("toggle:no_npc_shields") is True
    assert cheats.disable_npc_shields_active() is True


def test_dispatch_cancel_closes(panel):
    p, _ = panel
    p.open()
    assert p.dispatch_event("cancel") is True
    assert p.is_open() is False


def test_dispatch_tab_combat_ok(panel):
    p, _ = panel
    p.open()
    assert p.dispatch_event("tab:combat") is True


def test_dispatch_unknown_tab_returns_false(panel):
    p, _ = panel
    p.open()
    assert p.dispatch_event("tab:nope") is False


def test_dispatch_unknown_returns_false(panel):
    p, _ = panel
    p.open()
    assert p.dispatch_event("bogus") is False


# ---- render_payload -------------------------------------------------------

def test_render_payload_shape(panel):
    p, _ = panel
    p.open()
    body = _body(p.render_payload())
    assert body["visible"] is True
    assert body["tabs"] == [{"id": "combat", "label": "Combat"}]
    assert body["selected_tab"] == "combat"
    assert body["settings"] == {
        "god_mode": False, "double_weapons": False, "no_npc_shields": False,
    }


def test_render_payload_dedups(panel):
    p, _ = panel
    p.open()
    assert p.render_payload() is not None
    assert p.render_payload() is None


def test_render_payload_re_emits_after_toggle(panel):
    p, _ = panel
    p.open()
    p.render_payload()
    p.dispatch_event("toggle:god_mode")
    body = _body(p.render_payload())
    assert body["settings"]["god_mode"] is True


def test_render_payload_close_emits_hide(panel):
    p, _ = panel
    p.open()
    p.render_payload()
    p.close()
    out = p.render_payload()
    assert _body(out) == {"visible": False}


def test_invalidate_re_emits(panel):
    p, _ = panel
    p.open()
    first = p.render_payload()
    assert p.render_payload() is None
    p.invalidate()
    assert p.render_payload() == first


# ---- keyboard input -------------------------------------------------------

class _Keys:
    KEY_UP = 1; KEY_DOWN = 2; KEY_LEFT = 3; KEY_RIGHT = 4
    KEY_SPACE = 5; KEY_ENTER = 6; KEY_ESCAPE = 7


class _Reader:
    def __init__(self):
        self.keys = _Keys()
        self._pressed = set()
    def press(self, key):
        self._pressed.add(key)
    def key_pressed(self, key):
        if key in self._pressed:
            self._pressed.discard(key)
            return True
        return False


def test_handle_input_when_closed_is_noop(panel):
    p, cheats = panel
    r = _Reader()
    r.press(r.keys.KEY_DOWN)
    p.handle_input(r)
    assert cheats.god_mode_active() is False


def test_focusables_order(panel):
    p, _ = panel
    assert p._focusables() == [
        ("tab", "combat"),
        ("ctrl", "god_mode"),
        ("ctrl", "double_weapons"),
        ("ctrl", "no_npc_shields"),
    ]


def test_space_on_god_mode_row_toggles(panel):
    p, cheats = panel
    p.open()
    r = _Reader()
    steps = p._focusables().index(("ctrl", "god_mode")) + 1
    for _ in range(steps):
        r.press(r.keys.KEY_DOWN); p.handle_input(r)
    r.press(r.keys.KEY_SPACE); p.handle_input(r)
    assert cheats.god_mode_active() is True


def test_handle_key_esc_when_open_closes(panel):
    p, _ = panel
    p.open()
    p.handle_key_esc()
    assert p.is_open() is False
