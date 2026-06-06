"""Tests for ConfigurationPanel — pause-menu Configuration modal.

The panel subclasses engine.ui.panel.Panel and is pumped by
PanelRegistry like the mission picker. These tests cover state,
dispatch, render_payload, and keyboard input without touching CEF
or _dauntless_host.
"""
import json
import math
from unittest.mock import Mock

import pytest

from engine.ui.configuration_panel import ConfigurationPanel, SettingsSnapshot


# ---- construction --------------------------------------------------------

def _make(**overrides):
    """Factory: panel with no-op appliers unless overridden."""
    kwargs = dict(
        tabs=[("graphics", "Graphics")],
        initial_settings=SettingsSnapshot(
            dust_on=True, specular_on=True, fov_deg=70,
        ),
        set_dust=Mock(),
        set_specular=Mock(),
        set_fov_rad=Mock(),
    )
    kwargs.update(overrides)
    return ConfigurationPanel(**kwargs), kwargs


def test_name_is_configuration():
    p, _ = _make()
    assert p.name == "configuration"


def test_initially_closed():
    p, _ = _make()
    assert p.is_open() is False


def test_open_close_round_trip():
    p, _ = _make()
    p.open()
    assert p.is_open() is True
    p.close()
    assert p.is_open() is False


def test_initial_settings_round_trip_to_render_payload():
    p, _ = _make(initial_settings=SettingsSnapshot(
        dust_on=False, specular_on=True, fov_deg=62,
    ))
    p.open()
    payload = p.render_payload()
    body = json.loads(payload[len("setConfigurationPanel("):-2])
    assert body["settings"] == {
        "dust_on": False, "specular_on": True, "fov_deg": 62,
    }


# ---- dispatch_event ------------------------------------------------------

def test_dispatch_cancel_closes():
    p, _ = _make()
    p.open()
    assert p.dispatch_event("cancel") is True
    assert p.is_open() is False


def test_dispatch_toggle_dust_flips_and_calls_applier():
    p, kw = _make()
    p.open()
    assert p.dispatch_event("toggle:dust") is True
    kw["set_dust"].assert_called_once_with(False)
    # Second toggle flips back.
    assert p.dispatch_event("toggle:dust") is True
    kw["set_dust"].assert_called_with(True)


def test_dispatch_toggle_specular_flips_and_calls_applier():
    p, kw = _make()
    p.open()
    assert p.dispatch_event("toggle:specular") is True
    kw["set_specular"].assert_called_once_with(False)


def test_dispatch_fov_sets_and_applies_radians():
    p, kw = _make()
    p.open()
    assert p.dispatch_event("fov:62") is True
    kw["set_fov_rad"].assert_called_once()
    (called_rad,), _ = kw["set_fov_rad"].call_args
    assert called_rad == pytest.approx(math.radians(62))


def test_dispatch_fov_clamps_low():
    p, kw = _make()
    p.open()
    p.dispatch_event("fov:42")
    (called_rad,), _ = kw["set_fov_rad"].call_args
    assert called_rad == pytest.approx(math.radians(55))


def test_dispatch_fov_clamps_high():
    p, kw = _make()
    p.open()
    p.dispatch_event("fov:120")
    (called_rad,), _ = kw["set_fov_rad"].call_args
    assert called_rad == pytest.approx(math.radians(75))


def test_dispatch_fov_garbage_value_returns_false():
    p, kw = _make()
    p.open()
    assert p.dispatch_event("fov:not-a-number") is False
    kw["set_fov_rad"].assert_not_called()


def test_dispatch_tab_select_known_tab():
    p, _ = _make(tabs=[("graphics", "Graphics"), ("audio", "Audio")])
    p.open()
    assert p.dispatch_event("tab:audio") is True
    payload = p.render_payload()
    body = json.loads(payload[len("setConfigurationPanel("):-2])
    assert body["selected_tab"] == "audio"


def test_dispatch_tab_unknown_returns_false():
    p, _ = _make()
    p.open()
    assert p.dispatch_event("tab:nonexistent") is False


def test_dispatch_unknown_returns_false():
    p, _ = _make()
    p.open()
    assert p.dispatch_event("bogus") is False


# ---- render_payload dedup -------------------------------------------------

def test_render_payload_first_emit_then_dedups():
    p, _ = _make()
    p.open()
    first = p.render_payload()
    assert first is not None
    assert first.startswith("setConfigurationPanel(")
    assert p.render_payload() is None  # no change → no re-emit


def test_render_payload_re_emits_after_change():
    p, _ = _make()
    p.open()
    p.render_payload()
    p.dispatch_event("toggle:dust")
    second = p.render_payload()
    assert second is not None
    body = json.loads(second[len("setConfigurationPanel("):-2])
    assert body["settings"]["dust_on"] is False


def test_render_payload_close_emits_hide_then_dedups():
    p, _ = _make()
    p.open()
    p.render_payload()
    p.close()
    out = p.render_payload()
    body = json.loads(out[len("setConfigurationPanel("):-2])
    assert body == {"visible": False}
    assert p.render_payload() is None


def test_invalidate_re_emits():
    p, _ = _make()
    p.open()
    first = p.render_payload()
    assert p.render_payload() is None
    p.invalidate()
    re_emit = p.render_payload()
    assert re_emit == first


# ---- keyboard input ------------------------------------------------------

class _FakeKeys:
    KEY_UP = 1
    KEY_DOWN = 2
    KEY_LEFT = 3
    KEY_RIGHT = 4
    KEY_SPACE = 5
    KEY_ENTER = 6
    KEY_ESCAPE = 7


class _FakeReader:
    def __init__(self):
        self.keys = _FakeKeys()
        self._pressed = set()

    def press(self, key):
        self._pressed.add(key)

    def key_pressed(self, key):
        if key in self._pressed:
            self._pressed.discard(key)
            return True
        return False


def test_handle_input_when_closed_is_noop():
    p, kw = _make()
    r = _FakeReader()
    r.press(r.keys.KEY_DOWN)
    p.handle_input(r)
    kw["set_dust"].assert_not_called()


def test_focus_first_down_lands_on_first_focusable():
    """Focusable order with one Graphics tab: [tab:graphics, ctrl:dust,
    ctrl:specular, ctrl:fov]. First ↓ from unfocused lands on index 0
    (the tab row)."""
    p, _ = _make()
    p.open()
    r = _FakeReader()
    r.press(r.keys.KEY_DOWN)
    p.handle_input(r)
    payload = p.render_payload()
    body = json.loads(payload[len("setConfigurationPanel("):-2])
    assert body["focused"] == 0


def test_focus_first_up_lands_on_last_focusable():
    p, _ = _make()
    p.open()
    r = _FakeReader()
    r.press(r.keys.KEY_UP)
    p.handle_input(r)
    payload = p.render_payload()
    body = json.loads(payload[len("setConfigurationPanel("):-2])
    assert body["focused"] == 3  # ctrl:fov is last in a 4-item list


def test_focus_wraps_at_bottom():
    p, _ = _make()
    p.open()
    r = _FakeReader()
    for _ in range(5):
        r.press(r.keys.KEY_DOWN)
        p.handle_input(r)
    payload = p.render_payload()
    body = json.loads(payload[len("setConfigurationPanel("):-2])
    assert body["focused"] == 0  # 0,1,2,3,wrap→0


def test_space_on_dust_row_toggles():
    p, kw = _make()
    p.open()
    # Walk focus to ctrl:dust (index 1).
    r = _FakeReader()
    r.press(r.keys.KEY_DOWN); p.handle_input(r)  # 0
    r.press(r.keys.KEY_DOWN); p.handle_input(r)  # 1
    r.press(r.keys.KEY_SPACE); p.handle_input(r)
    kw["set_dust"].assert_called_once_with(False)


def test_right_arrow_on_fov_row_increments():
    p, kw = _make()
    p.open()
    r = _FakeReader()
    for _ in range(4):  # focus → fov (index 3)
        r.press(r.keys.KEY_DOWN); p.handle_input(r)
    r.press(r.keys.KEY_RIGHT); p.handle_input(r)
    (called_rad,), _ = kw["set_fov_rad"].call_args
    assert called_rad == pytest.approx(math.radians(71))  # 70 + 1


def test_left_arrow_on_fov_row_decrements_and_clamps():
    p, kw = _make(initial_settings=SettingsSnapshot(
        dust_on=True, specular_on=True, fov_deg=55,
    ))
    p.open()
    r = _FakeReader()
    for _ in range(4):
        r.press(r.keys.KEY_DOWN); p.handle_input(r)
    r.press(r.keys.KEY_LEFT); p.handle_input(r)
    # Still 55 (clamped), but applier still fires (consistency: every
    # press emits the current state to the renderer).
    (called_rad,), _ = kw["set_fov_rad"].call_args
    assert called_rad == pytest.approx(math.radians(55))


def test_handle_input_missing_optional_keys_does_not_crash():
    """Older bindings may lack KEY_LEFT/RIGHT/SPACE; navigation must
    degrade silently. Only KEY_UP/DOWN/ENTER are required."""

    class _MinimalKeys:
        KEY_UP = 1
        KEY_DOWN = 2
        KEY_ENTER = 3

    class _MinimalReader:
        def __init__(self):
            self.keys = _MinimalKeys()

        def key_pressed(self, key):
            return False

    p, _ = _make()
    p.open()
    p.handle_input(_MinimalReader())  # must not raise


def test_handle_key_esc_when_open_closes():
    p, _ = _make()
    p.open()
    p.handle_key_esc()
    assert p.is_open() is False


def test_handle_key_esc_when_closed_is_noop():
    p, _ = _make()
    p.handle_key_esc()
    assert p.is_open() is False
