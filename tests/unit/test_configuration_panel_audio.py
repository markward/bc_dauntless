"""The configuration panel's Audio tab: Music / Voice / SFX / UI sliders
(0-100, FOV-style: applied on release) and the 3D Audio toggle."""
import json
import re
from unittest.mock import Mock

import pytest

from engine.ui.configuration_panel import AUDIO_VOLUMES, SettingsSnapshot
from tests.unit.test_configuration_panel import _js_source, _make

_KEYS = [k for k, _label in AUDIO_VOLUMES]


def _audio_panel(**overrides):
    kw = dict(tabs=[("audio", "Audio")], set_audio_volume=Mock(),
              set_audio_3d=Mock(), on_change=Mock())
    kw.update(overrides)
    p, kwargs = _make(**kw)
    p.open()
    return p, kwargs


def _settings(p):
    payload = p.render_payload()
    return json.loads(payload[len("setConfigurationPanel("):-2])["settings"]


def test_the_rows_and_their_labels():
    assert AUDIO_VOLUMES == (("music_volume", "Music"), ("voice_volume", "Voice"),
                             ("sfx_volume", "SFX"), ("ui_volume", "UI"))


@pytest.mark.parametrize("key", _KEYS)
def test_a_released_slider_applies_and_persists(key):
    p, kw = _audio_panel()
    assert p.dispatch_event("volume:%s:40" % key) is True
    kw["set_audio_volume"].assert_called_once_with(key, 40)
    kw["on_change"].assert_called_once_with(key, 40)
    assert getattr(p._settings, key) == 40


def test_a_level_is_clamped_to_the_bar():
    p, kw = _audio_panel()
    p.dispatch_event("volume:sfx_volume:180")
    p.dispatch_event("volume:voice_volume:-3")
    assert p._settings.sfx_volume == 100
    assert p._settings.voice_volume == 0


@pytest.mark.parametrize("action", ["volume:sfx_volume:loud",
                                    "volume:fov_deg:30",
                                    "volume:sfx_volume"])
def test_a_bad_volume_event_is_refused(action):
    p, kw = _audio_panel()
    assert p.dispatch_event(action) is False
    kw["set_audio_volume"].assert_not_called()
    kw["on_change"].assert_not_called()


def test_a_raising_applier_does_not_report_a_change():
    p, kw = _audio_panel(set_audio_volume=Mock(side_effect=RuntimeError))
    with pytest.raises(RuntimeError):
        p.dispatch_event("volume:music_volume:10")
    kw["on_change"].assert_not_called()
    assert p._settings.music_volume == 100


def test_3d_audio_toggles():
    p, kw = _audio_panel()
    assert p.dispatch_event("toggle:audio_3d") is True
    kw["set_audio_3d"].assert_called_once_with(False)
    kw["on_change"].assert_called_once_with("audio_3d", False)
    assert p._settings.audio_3d_on is False


def test_reset_audio_takes_the_stores_defaults():
    reset = Mock(return_value={"music_volume": 100, "audio_3d_on": True})
    p, _kw = _audio_panel(
        on_reset=reset,
        initial_settings=SettingsSnapshot(fov_deg=45, music_volume=20,
                                          audio_3d_on=False))
    assert p.dispatch_event("reset:audio") is True
    reset.assert_called_once_with("audio")
    assert p._settings.music_volume == 100
    assert p._settings.audio_3d_on is True


def test_the_payload_carries_the_audio_settings_and_repushes_on_change():
    p, _kw = _audio_panel(initial_settings=SettingsSnapshot(
        fov_deg=45, voice_volume=60, audio_3d_on=False))
    s = _settings(p)
    assert {k: s[k] for k in _KEYS + ["audio_3d_on"]} == {
        "music_volume": 100, "voice_volume": 60, "sfx_volume": 100,
        "ui_volume": 100, "audio_3d_on": False}
    assert p.render_payload() is None
    p.dispatch_event("volume:ui_volume:30")
    assert _settings(p)["ui_volume"] == 30


def test_audio_tab_focusables():
    p, _kw = _audio_panel()
    assert p._focusables() == [("tab", "audio")] + [
        ("ctrl", k) for k in _KEYS] + [("ctrl", "audio_3d"), ("ctrl", "reset_audio")]


class _Keys:
    KEY_UP, KEY_DOWN, KEY_LEFT, KEY_RIGHT, KEY_SPACE, KEY_ENTER = range(6)


class _H:
    keys = _Keys

    def __init__(self, *pressed):
        self._pressed = set(pressed)

    def key_pressed(self, code):
        return code in self._pressed


def _focus(p, target):
    p._focused = p._focusables().index(("ctrl", target))


def test_arrow_keys_step_a_slider_by_five_and_stop_at_the_ends():
    p, kw = _audio_panel()
    _focus(p, "music_volume")
    p.handle_input(_H(_Keys.KEY_LEFT))
    assert p._settings.music_volume == 95
    p.handle_input(_H(_Keys.KEY_RIGHT))
    p.handle_input(_H(_Keys.KEY_RIGHT))
    assert p._settings.music_volume == 100


def test_space_toggles_3d_audio_and_activates_reset():
    reset = Mock(return_value={})
    p, kw = _audio_panel(on_reset=reset)
    _focus(p, "audio_3d")
    p.handle_input(_H(_Keys.KEY_SPACE))
    assert p._settings.audio_3d_on is False
    _focus(p, "reset_audio")
    p.handle_input(_H(_Keys.KEY_SPACE))
    reset.assert_called_once_with("audio")


def test_js_audio_focusables_match_python():
    """Same guard as the Graphics and Gameplay lockstep tests: if the JS list
    drifts from _focusables(), Space fires a different row than the one lit."""
    src = _js_source()
    rows = re.search(r"CP_AUDIO_VOLUMES = \[(.*?)\];", src, re.S)
    assert rows, "CP_AUDIO_VOLUMES not found"
    resets = re.search(r"CP_RESET_TARGETS = \{(.*?)\};", src, re.S)
    audio_reset = re.search(r"audio:\s*'(\w+)'", resets.group(1))
    assert audio_reset, "CP_RESET_TARGETS has no audio entry"
    js = (re.findall(r"\['(\w+)',", rows.group(1)) + ["audio_3d"]
          + [audio_reset.group(1)])
    p, _kw = _audio_panel()
    assert js == [t for kind, t in p._focusables() if kind == "ctrl"]


def test_js_labels_match_python():
    rows = re.search(r"CP_AUDIO_VOLUMES = \[(.*?)\];", _js_source(), re.S)
    pairs = re.findall(r"\['(\w+)',\s*'([^']+)'\]", rows.group(1))
    assert tuple(pairs) == AUDIO_VOLUMES


def test_js_sliders_are_0_to_100_and_apply_on_release_like_fov():
    src = _js_source()
    body = src[src.index("function _cpRenderAudioBody"):]
    body = body[:body.index("\nfunction ")]
    assert 'type="range" min="0" max="100" step="1"' in body
    assert "onchange=\"dauntlessEvent(\\'configuration/volume:' + key + ':\\' + this.value)\"" in body
    assert "oninput" not in body
    assert "_cpToggleRow('3D Audio', 'audio_3d'" in body
    assert "_cpResetRow('audio'" in body
