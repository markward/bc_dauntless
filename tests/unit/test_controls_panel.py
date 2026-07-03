"""ConfigurationPanel Controls tab — key-remap dispatch, capture, persistence.

Covers the controls-specific behaviour added on top of the existing
ConfigurationPanel: entering capture, applying a bound key, block-and-warn on
conflict, reserved-key rejection, reset, and render_payload shape/idempotency.
No CEF or _dauntless_host.
"""
import json
from unittest.mock import Mock

from engine.ui.configuration_panel import ConfigurationPanel, SettingsSnapshot
from engine.appc.config_mapping import TGConfigMapping
from engine.input_map import InputMap


def _make(tmp_path):
    im = InputMap(config_mapping=TGConfigMapping(),
                  filename=str(tmp_path / "Keybindings.cfg"))
    panel = ConfigurationPanel(
        tabs=[("graphics", "Graphics"), ("controls", "Controls")],
        initial_settings=SettingsSnapshot(
            dust_on=True, specular_on=True, hdr_on=True, rim_on=True,
            decals_on=True, fov_deg=70, shadows_on=True,
        ),
        set_dust=Mock(), set_specular=Mock(), set_hdr=Mock(), set_rim=Mock(),
        set_decals=Mock(), set_smaa=Mock(), set_subtitles=Mock(),
        set_disable_annoying_dialogue=Mock(), set_ai_difficulty=Mock(),
        set_fov_rad=Mock(), set_shadows=Mock(), set_procedural_sky=Mock(),
        set_filmic=Mock(), set_motion_blur=Mock(), set_warp_flythrough=Mock(),
        set_volumetric_nebulae=Mock(), set_nebula_lightning=Mock(),
        set_hdr_lens_flare=Mock(),
        input_map=im,
    )
    return panel, im


def _payload(panel):
    panel._last_pushed = None  # force re-render
    script = panel.render_payload()
    return json.loads(script[len("setConfigurationPanel("):-2])


def test_rebind_enters_capture(tmp_path):
    p, _ = _make(tmp_path)
    p.open()
    assert p.dispatch_event("rebind:fire_primary") is True
    assert p.capturing_action == "fire_primary"


def test_bind_applies_and_persists(tmp_path):
    p, im = _make(tmp_path)
    p.open()
    p.dispatch_event("rebind:fire_primary")
    assert p.dispatch_event("bind:fire_primary:J") is True
    assert im.name("fire_primary") == "J"
    assert p.capturing_action is None
    # Persisted to disk: a fresh map loading the same file sees it.
    im2 = InputMap(config_mapping=TGConfigMapping(), filename=im._filename)
    im2.load()
    assert im2.name("fire_primary") == "J"


def test_conflict_blocks_and_warns(tmp_path):
    p, im = _make(tmp_path)
    p.open()
    p.dispatch_event("rebind:fire_primary")
    # X is the stock secondary-fire key → conflict.
    assert p.dispatch_event("bind:fire_primary:X") is True
    assert im.name("fire_primary") == "F"          # unchanged
    assert im.name("fire_secondary") == "X"        # unchanged
    assert p.capturing_action == "fire_primary"    # stays in capture
    assert "already bound" in p._controls_message


def test_reserved_key_rejected(tmp_path):
    p, im = _make(tmp_path)
    p.open()
    p.dispatch_event("rebind:fire_primary")
    assert p.dispatch_event("bind:fire_primary:Space") is True
    assert im.name("fire_primary") == "F"          # unchanged
    assert p.capturing_action == "fire_primary"
    assert "can't be bound" in p._controls_message


def test_capture_cancel(tmp_path):
    p, _ = _make(tmp_path)
    p.open()
    p.dispatch_event("rebind:fire_primary")
    assert p.dispatch_event("capture_cancel") is True
    assert p.capturing_action is None


def test_controls_reset_restores_defaults(tmp_path):
    p, im = _make(tmp_path)
    p.open()
    p.dispatch_event("rebind:fire_primary")
    p.dispatch_event("bind:fire_primary:J")
    assert im.name("fire_primary") == "J"
    assert p.dispatch_event("controls_reset") is True
    assert im.name("fire_primary") == "F"


def test_switching_tab_cancels_capture(tmp_path):
    p, _ = _make(tmp_path)
    p.open()
    p.dispatch_event("rebind:fire_primary")
    p.dispatch_event("tab:graphics")
    assert p.capturing_action is None


def test_render_payload_includes_controls(tmp_path):
    p, _ = _make(tmp_path)
    p.open()
    p.dispatch_event("tab:controls")
    body = _payload(p)
    assert any(r["id"] == "fire_primary" and r["key"] == "F"
               for r in body["controls"])
    assert body["capturing_action"] is None
    # Capturing surfaces the label for the overlay.
    p.dispatch_event("rebind:fire_primary")
    body = _payload(p)
    assert body["capturing_action"] == "fire_primary"
    assert body["capturing_label"] == "Fire Phasers"


def test_render_payload_idempotent_when_unchanged(tmp_path):
    p, _ = _make(tmp_path)
    p.open()
    assert p.render_payload() is not None   # first push
    assert p.render_payload() is None        # unchanged → no re-emit
