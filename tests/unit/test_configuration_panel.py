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
            fov_deg=70,
        ),
        set_dust=Mock(),
        set_hdr=Mock(),
        set_rim=Mock(),
        set_smaa=Mock(),
        set_subtitles=Mock(),
        set_disable_annoying_dialogue=Mock(),
        set_ai_difficulty=Mock(),
        set_fov_rad=Mock(),
        set_shadows=Mock(),
        set_procedural_sky=Mock(),
        set_filmic=Mock(),
        set_motion_blur=Mock(),
        set_volumetric_nebulae=Mock(),
        set_nebula_lightning=Mock(),
        set_hdr_lens_flare=Mock(),
        set_ship_light_emitters=Mock(),
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
        fov_deg=62,
    ))
    p.open()
    payload = p.render_payload()
    body = json.loads(payload[len("setConfigurationPanel("):-2])
    assert body["settings"] == {
        "smaa_on": True,
        "subtitles_on": True, "improved_space_on": True,
        "camera_realism_on": True, "realistic_lighting_on": True,
        "disable_annoying_dialogue_on": True,
        "ai_difficulty": 1,
        "fov_deg": 62,
    }


# ---- dispatch_event ------------------------------------------------------

def test_dispatch_cancel_closes():
    p, _ = _make()
    p.open()
    assert p.dispatch_event("cancel") is True
    assert p.is_open() is False


def test_dispatch_fov_sets_and_applies_radians():
    p, kw = _make()
    p.open()
    assert p.dispatch_event("fov:45") is True
    kw["set_fov_rad"].assert_called_once()
    (called_rad,), _ = kw["set_fov_rad"].call_args
    assert called_rad == pytest.approx(math.radians(45))


def test_dispatch_fov_clamps_low():
    p, kw = _make()
    p.open()
    p.dispatch_event("fov:10")
    (called_rad,), _ = kw["set_fov_rad"].call_args
    assert called_rad == pytest.approx(math.radians(25))


def test_dispatch_fov_clamps_high():
    p, kw = _make()
    p.open()
    p.dispatch_event("fov:120")
    (called_rad,), _ = kw["set_fov_rad"].call_args
    assert called_rad == pytest.approx(math.radians(55))


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
    p.dispatch_event("toggle:improved_space")
    second = p.render_payload()
    assert second is not None
    body = json.loads(second[len("setConfigurationPanel("):-2])
    assert body["settings"]["improved_space_on"] is False


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
    """Focusable order with one Graphics tab: [tab:graphics, ctrl:smaa,
    ctrl:fov, ...]. First ↓ from unfocused lands on index 0 (the tab row)."""
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
    last = len(p._focusables()) - 1
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


def test_walking_focus_to_a_row_and_pressing_space_activates_it():
    """Arrow-walk + activate in one path — the keyboard equivalent of a click.
    Index is looked up rather than counted so row reordering can't retarget it."""
    p, kw = _make()
    p.open()
    steps = p._focusables().index(("ctrl", "improved_space")) + 1
    r = _FakeReader()
    for _ in range(steps):
        r.press(r.keys.KEY_DOWN); p.handle_input(r)
    r.press(r.keys.KEY_SPACE); p.handle_input(r)
    kw["set_dust"].assert_called_once_with(False)


def test_right_arrow_on_fov_row_increments():
    p, kw = _make(initial_settings=SettingsSnapshot(
        fov_deg=30,
    ))
    p.open()
    r = _FakeReader()
    for _ in range(p._focusables().index(("ctrl", "fov")) + 1):
        r.press(r.keys.KEY_DOWN); p.handle_input(r)
    r.press(r.keys.KEY_RIGHT); p.handle_input(r)
    (called_rad,), _ = kw["set_fov_rad"].call_args
    assert called_rad == pytest.approx(math.radians(35))  # 30 + 5


def test_left_arrow_on_fov_row_decrements_and_clamps():
    p, kw = _make(initial_settings=SettingsSnapshot(
        fov_deg=25,
    ))
    p.open()
    r = _FakeReader()
    for _ in range(p._focusables().index(("ctrl", "fov")) + 1):
        r.press(r.keys.KEY_DOWN); p.handle_input(r)
    r.press(r.keys.KEY_LEFT); p.handle_input(r)
    # Still 25 (clamped at FOV_MIN), but applier still fires (consistency:
    # every press emits the current state to the renderer).
    (called_rad,), _ = kw["set_fov_rad"].call_args
    assert called_rad == pytest.approx(math.radians(25))


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
        fov_deg=70, subtitles_on=False,
    ))
    p.open()
    payload = p.render_payload()
    data = json.loads(payload[len("setConfigurationPanel("):-len(");")])
    assert data["settings"]["subtitles_on"] is False


# ---- "Disable Annoying Dialogue" toggle / gameplay tab --------------------

def test_render_payload_includes_disable_annoying_dialogue_on():
    p, _ = _make()
    p.open()
    payload = p.render_payload()
    data = json.loads(payload[len("setConfigurationPanel("):-len(");")])
    assert data["settings"]["disable_annoying_dialogue_on"] is True


def test_toggle_disable_annoying_dialogue_flips_and_calls_applier():
    p, kwargs = _make()
    p.open()
    p.dispatch_event("toggle:disable_annoying_dialogue")
    kwargs["set_disable_annoying_dialogue"].assert_called_once_with(False)
    # state reflects the new value
    payload = p.render_payload()
    data = json.loads(payload[len("setConfigurationPanel("):-len(");")])
    assert data["settings"]["disable_annoying_dialogue_on"] is False


def test_gameplay_tab_focusables_include_disable_annoying_dialogue():
    p, _ = _make(tabs=[("graphics", "Graphics"), ("gameplay", "Gameplay")])
    p.dispatch_event("tab:gameplay")
    focusables = p._focusables()
    assert ("ctrl", "disable_annoying_dialogue") in focusables
    # Subtitles stays first on the gameplay tab.
    assert focusables.index(("ctrl", "subtitles")) \
        < focusables.index(("ctrl", "disable_annoying_dialogue"))


def test_initial_disable_annoying_dialogue_off_round_trips():
    p, _ = _make(initial_settings=SettingsSnapshot(
        fov_deg=70, disable_annoying_dialogue_on=False,
    ))
    p.open()
    payload = p.render_payload()
    data = json.loads(payload[len("setConfigurationPanel("):-len(");")])
    assert data["settings"]["disable_annoying_dialogue_on"] is False


# ---- AI difficulty (Gameplay tab) ---------------------------------------

def test_dispatch_ai_difficulty_sets_and_applies():
    p, kw = _make()
    p.open()
    assert p.dispatch_event("ai_difficulty:2") is True
    kw["set_ai_difficulty"].assert_called_once_with(2)
    assert p._settings.ai_difficulty == 2


def test_dispatch_ai_difficulty_clamps_high():
    p, kw = _make()
    p.open()
    p.dispatch_event("ai_difficulty:9")
    kw["set_ai_difficulty"].assert_called_once_with(2)
    assert p._settings.ai_difficulty == 2


def test_dispatch_ai_difficulty_clamps_low():
    p, kw = _make()
    p.open()
    p.dispatch_event("ai_difficulty:-3")
    kw["set_ai_difficulty"].assert_called_once_with(0)
    assert p._settings.ai_difficulty == 0


def test_dispatch_ai_difficulty_garbage_returns_false():
    p, kw = _make()
    p.open()
    assert p.dispatch_event("ai_difficulty:nope") is False
    kw["set_ai_difficulty"].assert_not_called()


def test_ai_difficulty_in_render_payload():
    p, _ = _make(initial_settings=SettingsSnapshot(
        fov_deg=70, ai_difficulty=2,
    ))
    p.open()
    payload = p.render_payload()
    body = json.loads(payload[len("setConfigurationPanel("):-len(");")])
    assert body["settings"]["ai_difficulty"] == 2


def test_ai_difficulty_initial_clamped_in_constructor():
    p, _ = _make(initial_settings=SettingsSnapshot(
        fov_deg=70, ai_difficulty=99,
    ))
    assert p._settings.ai_difficulty == 2


def test_ai_difficulty_is_a_gameplay_focusable():
    p, _ = _make(tabs=[("graphics", "Graphics"), ("gameplay", "Gameplay")])
    p.dispatch_event("tab:gameplay")
    focusables = p._focusables()
    assert ("ctrl", "ai_difficulty") in focusables


# ---- Camera Realism (HDR + filmic + motion blur + lens flare) ------

_CAMERA_REALISM_APPLIERS = ("set_hdr", "set_filmic", "set_motion_blur",
                         "set_hdr_lens_flare")


def test_dispatch_toggle_camera_realism_fans_out_to_every_applier():
    p, kw = _make()
    p.open()
    assert p._settings.camera_realism_on is True
    assert p.dispatch_event("toggle:camera_realism") is True
    for name in _CAMERA_REALISM_APPLIERS:
        kw[name].assert_called_once_with(False)
    assert p._settings.camera_realism_on is False


def test_dispatch_toggle_camera_realism_twice_flips_back_on():
    p, kw = _make()
    p.open()
    p.dispatch_event("toggle:camera_realism")
    assert p.dispatch_event("toggle:camera_realism") is True
    for name in _CAMERA_REALISM_APPLIERS:
        kw[name].assert_called_with(True)
    assert p._settings.camera_realism_on is True


def test_camera_realism_off_in_render_payload():
    p, _ = _make(initial_settings=SettingsSnapshot(
        fov_deg=70, camera_realism_on=False,
    ))
    p.open()
    body = json.loads(p.render_payload()[len("setConfigurationPanel("):-len(");")])
    assert body["settings"]["camera_realism_on"] is False


def test_absorbed_sub_toggles_no_longer_dispatch_or_focus():
    """The four settings folded into Camera Realism must leave no
    orphan row behind — a stale action would toggle one effect out of step
    with the master and the panel would show neither."""
    p, kw = _make()
    p.open()
    f = p._focusables()
    for target in ("hdr", "filmic", "motion_blur", "hdr_lens_flare"):
        assert p.dispatch_event("toggle:" + target) is False
        assert ("ctrl", target) not in f
    for name in _CAMERA_REALISM_APPLIERS:
        kw[name].assert_not_called()


def test_space_on_camera_realism_row_toggles():
    p, kw = _make()
    p.open()
    p._focused = p._focusables().index(("ctrl", "camera_realism"))
    r = _FakeReader()
    r.press(r.keys.KEY_SPACE)
    p.handle_input(r)
    for name in _CAMERA_REALISM_APPLIERS:
        kw[name].assert_called_once_with(False)


# ---- Realistic Lighting (rim + shadows + nebula lightning + ship lights) --

_REALISTIC_LIGHTING_APPLIERS = ("set_rim", "set_shadows", "set_nebula_lightning",
                                "set_ship_light_emitters")


def test_dispatch_toggle_realistic_lighting_fans_out_to_every_applier():
    p, kw = _make()
    p.open()
    assert p._settings.realistic_lighting_on is True
    assert p.dispatch_event("toggle:realistic_lighting") is True
    for name in _REALISTIC_LIGHTING_APPLIERS:
        kw[name].assert_called_once_with(False)
    assert p._settings.realistic_lighting_on is False


def test_dispatch_toggle_realistic_lighting_twice_flips_back_on():
    p, kw = _make()
    p.open()
    p.dispatch_event("toggle:realistic_lighting")
    assert p.dispatch_event("toggle:realistic_lighting") is True
    for name in _REALISTIC_LIGHTING_APPLIERS:
        kw[name].assert_called_with(True)
    assert p._settings.realistic_lighting_on is True


def test_realistic_lighting_off_in_render_payload():
    p, _ = _make(initial_settings=SettingsSnapshot(
        fov_deg=70,
        realistic_lighting_on=False,
    ))
    p.open()
    body = json.loads(p.render_payload()[len("setConfigurationPanel("):-len(");")])
    assert body["settings"]["realistic_lighting_on"] is False


def test_realistic_lighting_is_focusable_after_camera_realism():
    p, _ = _make()
    f = p._focusables()
    assert (f.index(("ctrl", "camera_realism"))
            < f.index(("ctrl", "realistic_lighting")))


def test_absorbed_lighting_sub_toggles_no_longer_dispatch_or_focus():
    p, kw = _make()
    p.open()
    f = p._focusables()
    for target in ("rim", "shadows", "nebula_lightning"):
        assert p.dispatch_event("toggle:" + target) is False
        assert ("ctrl", target) not in f
    for name in _REALISTIC_LIGHTING_APPLIERS:
        kw[name].assert_not_called()


def test_space_on_realistic_lighting_row_toggles():
    p, kw = _make()
    p.open()
    p._focused = p._focusables().index(("ctrl", "realistic_lighting"))
    r = _FakeReader()
    r.press(r.keys.KEY_SPACE)
    p.handle_input(r)
    for name in _REALISTIC_LIGHTING_APPLIERS:
        kw[name].assert_called_once_with(False)


# ---- Improved Space Visuals (dust + volumetric nebulae + procedural sky) --

_IMPROVED_SPACE_APPLIERS = ("set_dust", "set_procedural_sky",
                            "set_volumetric_nebulae")


def test_dispatch_toggle_improved_space_fans_out_to_every_applier():
    p, kw = _make()
    p.open()
    assert p._settings.improved_space_on is True
    assert p.dispatch_event("toggle:improved_space") is True
    for name in _IMPROVED_SPACE_APPLIERS:
        kw[name].assert_called_once_with(False)
    assert p._settings.improved_space_on is False


def test_dispatch_toggle_improved_space_twice_flips_back_on():
    p, kw = _make()
    p.open()
    p.dispatch_event("toggle:improved_space")
    assert p.dispatch_event("toggle:improved_space") is True
    for name in _IMPROVED_SPACE_APPLIERS:
        kw[name].assert_called_with(True)
    assert p._settings.improved_space_on is True


def test_improved_space_off_in_render_payload():
    p, _ = _make(initial_settings=SettingsSnapshot(
        fov_deg=70, improved_space_on=False,
    ))
    p.open()
    body = json.loads(p.render_payload()[len("setConfigurationPanel("):-len(");")])
    assert body["settings"]["improved_space_on"] is False


def test_improved_space_leads_the_modern_vfx_masters():
    p, _ = _make()
    f = p._focusables()
    assert (f.index(("ctrl", "improved_space"))
            < f.index(("ctrl", "camera_realism"))
            < f.index(("ctrl", "realistic_lighting")))


def test_absorbed_space_sub_toggles_no_longer_dispatch_or_focus():
    p, kw = _make()
    p.open()
    f = p._focusables()
    for target in ("dust", "procedural_sky", "volumetric_nebulae"):
        assert p.dispatch_event("toggle:" + target) is False
        assert ("ctrl", target) not in f
    for name in _IMPROVED_SPACE_APPLIERS:
        kw[name].assert_not_called()


def test_space_on_improved_space_row_toggles():
    p, kw = _make()
    p.open()
    p._focused = p._focusables().index(("ctrl", "improved_space"))
    r = _FakeReader()
    r.press(r.keys.KEY_SPACE)
    p.handle_input(r)
    for name in _IMPROVED_SPACE_APPLIERS:
        kw[name].assert_called_once_with(False)


def test_decals_is_no_longer_a_setting():
    """Hull scorch is permanently on, matching the hull-breach pass — both are
    core damage feedback, neither is switchable. God mode's per-hit
    persist_decal=False is a separate mechanism and is unaffected."""
    p, _ = _make()
    p.open()
    assert p.dispatch_event("toggle:decals") is False
    assert ("ctrl", "decals") not in p._focusables()
    body = json.loads(p.render_payload()[len("setConfigurationPanel("):-len(");")])
    assert "decals_on" not in body["settings"]


def test_specular_is_no_longer_a_setting():
    """Specular highlights are permanently on — native g_specular_enabled
    defaults true and nothing can now clear it."""
    p, _ = _make()
    p.open()
    assert p.dispatch_event("toggle:specular") is False
    assert ("ctrl", "specular") not in p._focusables()
    body = json.loads(p.render_payload()[len("setConfigurationPanel("):-len(");")])
    assert "specular_on" not in body["settings"]


def test_warp_flythrough_is_no_longer_a_setting():
    """The set-to-set warp cinematic is core to how warp reads, not optional.
    No row, no focusable, no action — and nothing left to dispatch at."""
    p, _ = _make()
    p.open()
    assert p.dispatch_event("toggle:warp_flythrough") is False
    assert ("ctrl", "warp_flythrough") not in p._focusables()
    body = json.loads(p.render_payload()[len("setConfigurationPanel("):-len(");")])
    assert "warp_flythrough_on" not in body["settings"]


def test_smaa_is_the_first_graphics_control():
    p, _ = _make()
    ctrls = [t for kind, t in p._focusables() if kind == "ctrl"]
    assert ctrls[0] == "smaa"


def test_js_graphics_focusables_match_python():
    """configuration_panel.js mirrors _focusables() by hand. If the two lists
    drift, keyboard focus highlights the wrong row and Space toggles a
    different setting than the one the player sees selected."""
    import pathlib
    import re
    src = (pathlib.Path(__file__).resolve().parents[2]
           / "native/assets/ui-cef/js/configuration_panel.js").read_text()
    graphics = src.split("state.selected_tab === 'graphics'")[1] \
                  .split("else if")[0]
    js_targets = re.findall(r"kind:\s*'ctrl',\s*target:\s*'(\w+)'", graphics)
    p, _ = _make()
    py_targets = [t for kind, t in p._focusables() if kind == "ctrl"]
    assert js_targets == py_targets


def test_every_boolean_setting_reaches_the_ui():
    """See tests/helpers/panel_snapshot: a setting missing from render_payload's
    snapshot tuple toggles invisibly — the flag flips, the feature changes, and
    the control keeps showing its old state. Shipped that way on Developer
    Options; this is the same guard applied here."""
    from tests.helpers.panel_snapshot import assert_boolean_settings_redraw
    panel, _ = _make()
    panel.open()
    assert_boolean_settings_redraw(panel, lambda body: body.get("settings", {}))
