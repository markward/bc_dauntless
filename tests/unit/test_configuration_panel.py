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
            dust_on=True, specular_on=True, hdr_on=True, rim_on=True,
            decals_on=True, fov_deg=70, shadows_on=True,
        ),
        set_dust=Mock(),
        set_specular=Mock(),
        set_hdr=Mock(),
        set_rim=Mock(),
        set_decals=Mock(),
        set_smaa=Mock(),
        set_subtitles=Mock(),
        set_fov_rad=Mock(),
        set_shadows=Mock(),
        set_procedural_sky=Mock(),
        set_filmic=Mock(),
        set_motion_blur=Mock(),
        set_warp_flythrough=Mock(),
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
        dust_on=False, specular_on=True, hdr_on=True, rim_on=False,
        decals_on=False, fov_deg=62,
    ))
    p.open()
    payload = p.render_payload()
    body = json.loads(payload[len("setConfigurationPanel("):-2])
    assert body["settings"] == {
        "dust_on": False, "specular_on": True, "hdr_on": True, "rim_on": False,
        "decals_on": False, "smaa_on": True,
        "subtitles_on": True, "shadows_on": True, "procedural_sky_on": True,
        "filmic_on": True, "motion_blur_on": True, "warp_flythrough_on": True,
        "fov_deg": 62,
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


def test_dispatch_toggle_procedural_sky_flips_and_calls_applier():
    p, kw = _make()
    p.open()
    assert p.dispatch_event("toggle:procedural_sky") is True
    kw["set_procedural_sky"].assert_called_once_with(False)
    # Second toggle flips back.
    assert p.dispatch_event("toggle:procedural_sky") is True
    kw["set_procedural_sky"].assert_called_with(True)


def test_procedural_sky_on_in_render_payload():
    p, _ = _make(initial_settings=SettingsSnapshot(
        dust_on=True, specular_on=True, hdr_on=True, rim_on=True,
        decals_on=True, fov_deg=70, shadows_on=True, procedural_sky_on=False,
    ))
    p.open()
    payload = p.render_payload()
    body = json.loads(payload[len("setConfigurationPanel("):-len(");")])
    assert body["settings"]["procedural_sky_on"] is False


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
    p.dispatch_event("fov:30")
    (called_rad,), _ = kw["set_fov_rad"].call_args
    assert called_rad == pytest.approx(math.radians(40))


def test_dispatch_fov_clamps_high():
    p, kw = _make()
    p.open()
    p.dispatch_event("fov:120")
    (called_rad,), _ = kw["set_fov_rad"].call_args
    assert called_rad == pytest.approx(math.radians(80))


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
    last = len(p._focusables()) - 1  # ctrl:smaa is the last focusable
    r = _FakeReader()
    r.press(r.keys.KEY_UP)
    p.handle_input(r)
    payload = p.render_payload()
    body = json.loads(payload[len("setConfigurationPanel("):-2])
    assert body["focused"] == last


def test_focus_wraps_at_bottom():
    p, _ = _make()
    p.open()
    n = len(p._focusables())
    r = _FakeReader()
    for _ in range(n + 1):  # step onto the last item, then once more to wrap
        r.press(r.keys.KEY_DOWN)
        p.handle_input(r)
    payload = p.render_payload()
    body = json.loads(payload[len("setConfigurationPanel("):-2])
    assert body["focused"] == 0


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
    for _ in range(4):  # focus → fov (index 3: tab, dust, specular, fov)
        r.press(r.keys.KEY_DOWN); p.handle_input(r)
    r.press(r.keys.KEY_RIGHT); p.handle_input(r)
    (called_rad,), _ = kw["set_fov_rad"].call_args
    assert called_rad == pytest.approx(math.radians(75))  # 70 + 5


def test_left_arrow_on_fov_row_decrements_and_clamps():
    p, kw = _make(initial_settings=SettingsSnapshot(
        dust_on=True, specular_on=True, hdr_on=True, rim_on=True,
        decals_on=True, fov_deg=40,
    ))
    p.open()
    r = _FakeReader()
    for _ in range(4):  # focus → fov (index 3: tab, dust, specular, fov)
        r.press(r.keys.KEY_DOWN); p.handle_input(r)
    r.press(r.keys.KEY_LEFT); p.handle_input(r)
    # Still 40 (clamped), but applier still fires (consistency: every
    # press emits the current state to the renderer).
    (called_rad,), _ = kw["set_fov_rad"].call_args
    assert called_rad == pytest.approx(math.radians(40))


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


# ---- rim toggle -----------------------------------------------------------

def test_toggle_rim_fires_applier_and_flips_state():
    p, kw = _make()
    p.open()
    assert p._settings.rim_on is True
    handled = p.dispatch_event("toggle:rim")
    assert handled is True
    kw["set_rim"].assert_called_once_with(False)
    assert p._settings.rim_on is False


def test_render_payload_includes_rim_on():
    p, _ = _make()
    p.open()
    js = p.render_payload()
    assert js is not None
    payload = json.loads(js[len("setConfigurationPanel("):-len(");")])
    assert payload["settings"]["rim_on"] is True


def test_rim_is_a_graphics_focusable():
    p, _ = _make()
    focusables = p._focusables()
    assert ("ctrl", "rim") in focusables


# ---- hdr toggle -----------------------------------------------------------

def test_toggle_hdr_fires_applier_and_flips_state():
    p, kw = _make()
    p.open()
    assert p._settings.hdr_on is True
    assert p.dispatch_event("toggle:hdr") is True
    kw["set_hdr"].assert_called_once_with(False)
    assert p._settings.hdr_on is False


def test_render_payload_includes_hdr_on():
    p, _ = _make()
    p.open()
    payload = json.loads(p.render_payload()[len("setConfigurationPanel("):-len(");")])
    assert payload["settings"]["hdr_on"] is True


def test_hdr_is_a_graphics_focusable_before_rim():
    p, _ = _make()
    f = p._focusables()
    assert ("ctrl", "hdr") in f and ("ctrl", "rim") in f
    assert f.index(("ctrl", "hdr")) < f.index(("ctrl", "rim"))


# ---- damage decals toggle -------------------------------------------------

def test_toggle_decals_fires_applier_and_flips_state():
    p, kw = _make()
    p.open()
    assert p._settings.decals_on is True
    assert p.dispatch_event("toggle:decals") is True
    kw["set_decals"].assert_called_once_with(False)
    assert p._settings.decals_on is False


def test_render_payload_includes_decals_on():
    p, _ = _make()
    p.open()
    payload = json.loads(p.render_payload()[len("setConfigurationPanel("):-len(");")])
    assert payload["settings"]["decals_on"] is True


def test_decals_is_a_graphics_focusable():
    p, _ = _make()
    assert ("ctrl", "decals") in p._focusables()


def test_space_on_decals_row_toggles():
    p, kw = _make()
    p.open()
    r = _FakeReader()
    # Navigate down to the decals control and activate it.
    focusables = p._focusables()
    # Reaching index i needs i+1 down-presses (first press lands on index 0).
    steps = focusables.index(("ctrl", "decals")) + 1
    for _ in range(steps):
        r.press(r.keys.KEY_DOWN); p.handle_input(r)
    r.press(r.keys.KEY_SPACE); p.handle_input(r)
    kw["set_decals"].assert_called_once_with(False)
    assert p._settings.decals_on is False


# ---- smaa toggle ----------------------------------------------------------

def test_toggle_smaa_fires_applier_and_flips_state():
    p, kw = _make()
    p.open()
    assert p._settings.smaa_on is True
    assert p.dispatch_event("toggle:smaa") is True
    kw["set_smaa"].assert_called_once_with(False)
    assert p._settings.smaa_on is False


def test_render_payload_includes_smaa_on():
    p, _ = _make()
    p.open()
    payload = json.loads(p.render_payload()[len("setConfigurationPanel("):-len(");")])
    assert payload["settings"]["smaa_on"] is True


def test_smaa_is_a_graphics_focusable():
    p, _ = _make()
    assert ("ctrl", "smaa") in p._focusables()


def test_space_on_smaa_row_toggles():
    p, kw = _make()
    p.open()
    p._focused = p._focusables().index(("ctrl", "smaa"))

    class _Keys:
        KEY_DOWN = 1; KEY_UP = 2; KEY_SPACE = 3; KEY_ENTER = 4
        KEY_LEFT = 5; KEY_RIGHT = 6

    class _H:
        keys = _Keys()
        def key_pressed(self, code):
            return code == _Keys.KEY_SPACE

    p.handle_input(_H())
    kw["set_smaa"].assert_called_once_with(False)
    assert p._settings.smaa_on is False


def test_dispatch_toggle_smaa_flips_and_calls_applier():
    p, kw = _make()
    p.open()
    assert p.dispatch_event("toggle:smaa") is True
    kw["set_smaa"].assert_called_once_with(False)
    assert p.dispatch_event("toggle:smaa") is True
    kw["set_smaa"].assert_called_with(True)


# ---- subtitles toggle / gameplay tab --------------------------------------

def test_render_payload_includes_subtitles_on():
    p, _ = _make()
    p.open()
    payload = p.render_payload()
    data = json.loads(payload[len("setConfigurationPanel("):-len(");")])
    assert data["settings"]["subtitles_on"] is True


def test_toggle_subtitles_flips_and_calls_applier():
    p, kwargs = _make()
    p.open()
    p.dispatch_event("toggle:subtitles")
    kwargs["set_subtitles"].assert_called_once_with(False)
    # state reflects the new value
    payload = p.render_payload()
    data = json.loads(payload[len("setConfigurationPanel("):-len(");")])
    assert data["settings"]["subtitles_on"] is False


def test_gameplay_tab_focusables_include_subtitles():
    p, _ = _make(tabs=[("graphics", "Graphics"), ("gameplay", "Gameplay")])
    p.dispatch_event("tab:gameplay")
    focusables = p._focusables()
    assert ("ctrl", "subtitles") in focusables
    # graphics controls are not present on the gameplay tab
    assert ("ctrl", "dust") not in focusables


def test_initial_subtitles_off_round_trips():
    p, _ = _make(initial_settings=SettingsSnapshot(
        dust_on=True, specular_on=True, hdr_on=True, rim_on=True,
        decals_on=True, fov_deg=70, subtitles_on=False,
    ))
    p.open()
    payload = p.render_payload()
    data = json.loads(payload[len("setConfigurationPanel("):-len(");")])
    assert data["settings"]["subtitles_on"] is False


# ---- dynamic shadows toggle -----------------------------------------------

def test_dispatch_toggle_shadows_flips_and_calls_applier():
    p, kw = _make()
    p.open()
    assert p.dispatch_event("toggle:shadows") is True
    kw["set_shadows"].assert_called_once_with(False)
    # Second toggle flips back.
    assert p.dispatch_event("toggle:shadows") is True
    kw["set_shadows"].assert_called_with(True)


def test_dispatch_toggle_filmic_flips_and_calls_applier():
    p, kw = _make()
    p.open()
    assert p.dispatch_event("toggle:filmic") is True
    kw["set_filmic"].assert_called_once_with(False)
    assert p.dispatch_event("toggle:filmic") is True
    kw["set_filmic"].assert_called_with(True)


def test_filmic_on_in_render_payload():
    p, _ = _make(initial_settings=SettingsSnapshot(
        dust_on=True, specular_on=True, hdr_on=True, rim_on=True,
        decals_on=True, fov_deg=70, shadows_on=True,
        procedural_sky_on=True, filmic_on=False,
    ))
    p.open()
    payload = p.render_payload()
    body = json.loads(payload[len("setConfigurationPanel("):-len(");")])
    assert body["settings"]["filmic_on"] is False


def test_dispatch_toggle_motion_blur_flips_and_calls_applier():
    p, kw = _make()
    p.open()
    assert p.dispatch_event("toggle:motion_blur") is True
    kw["set_motion_blur"].assert_called_once_with(False)
    assert p.dispatch_event("toggle:motion_blur") is True
    kw["set_motion_blur"].assert_called_with(True)


def test_motion_blur_on_in_render_payload():
    p, _ = _make(initial_settings=SettingsSnapshot(
        dust_on=True, specular_on=True, hdr_on=True, rim_on=True,
        decals_on=True, fov_deg=70, shadows_on=True,
        procedural_sky_on=True, filmic_on=True, motion_blur_on=False,
    ))
    p.open()
    payload = p.render_payload()
    body = json.loads(payload[len("setConfigurationPanel("):-len(");")])
    assert body["settings"]["motion_blur_on"] is False


def test_dispatch_toggle_warp_flythrough_flips_and_calls_applier():
    p, kw = _make()
    p.open()
    assert p.dispatch_event("toggle:warp_flythrough") is True
    kw["set_warp_flythrough"].assert_called_once_with(False)
    assert p.dispatch_event("toggle:warp_flythrough") is True
    kw["set_warp_flythrough"].assert_called_with(True)


def test_warp_flythrough_on_in_render_payload():
    p, _ = _make(initial_settings=SettingsSnapshot(
        dust_on=True, specular_on=True, hdr_on=True, rim_on=True,
        decals_on=True, fov_deg=70, shadows_on=True,
        procedural_sky_on=True, filmic_on=True, motion_blur_on=True,
        warp_flythrough_on=False,
    ))
    p.open()
    payload = p.render_payload()
    body = json.loads(payload[len("setConfigurationPanel("):-len(");")])
    assert body["settings"]["warp_flythrough_on"] is False
