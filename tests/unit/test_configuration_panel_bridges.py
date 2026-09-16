"""Bridges tab of ConfigurationPanel: payload, actions, exclusion rule,
per-tab reset scope, focus order, and no-op construction without pins."""
import json
from unittest.mock import Mock

import pytest

from engine.ui.configuration_panel import ConfigurationPanel, SettingsSnapshot
from engine import bridge_selection as bs
from tests.helpers.bridge_fixtures import fake_install   # noqa: F401 (fixture)


def _make(pins=None, tabs=None):
    kwargs = dict(
        tabs=tabs or [("graphics", "Graphics"), ("bridges", "Bridges")],
        initial_settings=SettingsSnapshot(fov_deg=70),
        set_dust=Mock(), set_hdr=Mock(), set_rim=Mock(), set_aa_mode=Mock(),
        set_subtitles=Mock(), set_disable_annoying_dialogue=Mock(),
        set_ai_difficulty=Mock(), set_fov_rad=Mock(), set_shadows=Mock(),
        set_procedural_sky=Mock(), set_filmic=Mock(), set_motion_blur=Mock(),
        set_dof=Mock(), set_volumetric_nebulae=Mock(), set_nebula_lightning=Mock(),
        set_hdr_lens_flare=Mock(), set_ship_light_emitters=Mock(),
        set_camera_shake=Mock(), set_ambient_gradient=Mock(),
        bridge_pins=pins,
    )
    return ConfigurationPanel(**kwargs)


def _body(panel):
    return json.loads(panel.render_payload()[len("setConfigurationPanel("):-2])


@pytest.fixture
def pins(fake_install, tmp_path):
    return bs.load_bridge_pins(tmp_path / "bridges.json")


def test_without_pins_no_bridges_block_and_tab_dispatch_is_inert():
    p = _make(pins=None)
    p.open()
    assert "bridges" not in _body(p)
    assert p.dispatch_event("bridge:add") is False


def test_payload_lists_pins_unpinned_ships_and_bridges(pins):
    p = _make(pins); p.open(); p.dispatch_event("tab:bridges")
    b = _body(p)["bridges"]
    assert [r["ship"] for r in b["pins"]] == ["Galaxy", "Sovereign", "Akira"]
    assert b["pins"][2] == {"ship": "Akira", "ship_label": "Akira",
                            "bridge": "SovereignBridge", "bridge_label": "Sovereign",
                            "ship_missing": False, "bridge_missing": False}
    assert [s["id"] for s in b["ships"]] == ["BirdOfPrey", "KessokLight"]
    assert b["ships"][0]["label"] == "Bird of Prey"
    assert b["bridges_available"] == [{"id": "GalaxyBridge", "label": "Galaxy"},
                                      {"id": "SovereignBridge", "label": "Sovereign"}]
    assert b["add_ship"] is None
    assert b["add_bridge"] == "GalaxyBridge"        # first available preselected
    assert b["can_add"] is False
    assert b["default_bridge_label"] == "Galaxy"


def test_select_ship_then_add_pins_and_drops_it_from_the_list(pins):
    p = _make(pins); p.open(); p.dispatch_event("tab:bridges")
    assert p.dispatch_event("bridge:ship:BirdOfPrey") is True
    assert _body(p)["bridges"]["can_add"] is True
    assert p.dispatch_event("bridge:bridge:SovereignBridge") is True
    assert p.dispatch_event("bridge:add") is True
    b = _body(p)["bridges"]
    assert pins.pins()["BirdOfPrey"] == "SovereignBridge"
    assert [s["id"] for s in b["ships"]] == ["KessokLight"]
    assert b["add_ship"] is None                    # selection cleared
    assert b["can_add"] is False


def test_add_without_a_ship_is_rejected(pins):
    p = _make(pins); p.open(); p.dispatch_event("tab:bridges")
    assert p.dispatch_event("bridge:add") is False
    assert len(pins.pins()) == 3


def test_selecting_a_pinned_ship_is_rejected(pins):
    p = _make(pins); p.open(); p.dispatch_event("tab:bridges")
    assert p.dispatch_event("bridge:ship:Galaxy") is False


def test_selecting_an_unknown_bridge_is_rejected(pins):
    p = _make(pins); p.open(); p.dispatch_event("tab:bridges")
    assert p.dispatch_event("bridge:bridge:VoyagerBridge") is False


def test_remove_deletes_the_pin(pins):
    p = _make(pins); p.open(); p.dispatch_event("tab:bridges")
    assert p.dispatch_event("bridge:remove:Akira") is True
    assert "Akira" not in pins.pins()
    assert "Akira" in [s["id"] for s in _body(p)["bridges"]["ships"]]


def test_missing_rows_are_flagged_not_hidden(fake_install, tmp_path):
    f = tmp_path / "bridges.json"
    f.write_text('{"version": 1, "pins": {"LCIntrepid": "VoyagerBridge"}}')
    p = _make(bs.load_bridge_pins(f)); p.open(); p.dispatch_event("tab:bridges")
    row = _body(p)["bridges"]["pins"][0]
    assert row["ship_missing"] is True and row["bridge_missing"] is True
    assert row["bridge_label"] == "Voyager"


def test_reset_bridges_deletes_the_file_and_touches_nothing_else(pins, tmp_path):
    on_reset = Mock(return_value={})
    p = _make(pins); p._on_reset = on_reset
    p.open(); p.dispatch_event("tab:bridges")
    p.dispatch_event("bridge:remove:Akira")
    assert (tmp_path / "bridges.json").exists()
    assert p.dispatch_event("reset:bridges") is True
    assert not (tmp_path / "bridges.json").exists()
    assert pins.pins() == bs.DEFAULT_PINS
    on_reset.assert_not_called()                     # settings.json untouched


def test_reset_bridges_without_pins_is_rejected():
    p = _make(None)
    assert p.dispatch_event("reset:bridges") is False


def test_focusables_mirror_the_rendered_rows(pins):
    p = _make(pins); p.open(); p.dispatch_event("tab:bridges")
    assert p._focusables() == [
        ("tab", "graphics"), ("tab", "bridges"),
        ("bridge_remove", "Galaxy"), ("bridge_remove", "Sovereign"),
        ("bridge_remove", "Akira"),
        ("bridge_ship", "BirdOfPrey"), ("bridge_ship", "KessokLight"),
        ("bridge_pick", "GalaxyBridge"), ("bridge_pick", "SovereignBridge"),
        ("ctrl", "bridge_add"), ("ctrl", "reset_bridges"),
    ]


def test_leaving_the_tab_clears_the_add_selection(pins):
    p = _make(pins); p.open(); p.dispatch_event("tab:bridges")
    p.dispatch_event("bridge:ship:BirdOfPrey")
    p.dispatch_event("tab:graphics"); p.dispatch_event("tab:bridges")
    assert _body(p)["bridges"]["add_ship"] is None


def test_payload_is_not_repushed_when_nothing_changed(pins):
    p = _make(pins); p.open(); p.dispatch_event("tab:bridges")
    assert p.render_payload() is not None
    assert p.render_payload() is None
    p.dispatch_event("bridge:ship:BirdOfPrey")
    assert p.render_payload() is not None


# ---- JS mirrors -----------------------------------------------------------------

def _js_source():
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    return (root / "native/assets/ui-cef/js/configuration_panel.js").read_text()


def test_js_focusable_list_has_a_bridges_branch_in_python_order():
    """_cpFocusableList's bridges branch must push, in order: one
    bridge_remove per pin, one bridge_ship per unpinned ship, one bridge_pick
    per available bridge, then bridge_add and reset_bridges — the order
    ConfigurationPanel._focusables uses. Space on a focused row otherwise
    fires the wrong control."""
    import re
    src = _js_source()
    branch = re.search(r"selected_tab === 'bridges'\)\s*\{(.*?)\n    \}", src, re.S)
    assert branch, "no bridges branch in _cpFocusableList"
    body = branch.group(1)
    order = [m for m in re.findall(r"kind: '(\w+)'", body)]
    assert order == ["bridge_remove", "bridge_ship", "bridge_pick", "ctrl", "ctrl"]
    assert re.search(r"target: 'bridge_add'", body)
    assert re.search(r"target: 'reset_bridges'", body)


def test_js_renders_the_bridges_tab_and_dispatches_every_action():
    src = _js_source()
    assert "_cpRenderBridgesBody" in src
    assert "selected_tab === 'bridges'" in src
    for action in ("configuration/bridge:ship:", "configuration/bridge:bridge:",
                   "configuration/bridge:add", "configuration/bridge:remove:",
                   "configuration/reset:bridges"):
        assert action in src, action


def test_js_shows_missing_markers_and_never_uses_a_native_select():
    src = _js_source()
    assert "(missing)" in src
    assert "(ship not installed)" in src
    assert "<select" not in src.lower()


def test_js_onclick_ids_are_js_escaped_not_just_html_escaped():
    import re
    src = _js_source()
    assert "function _cpEventArg(" in src
    body = re.search(r"function _cpRenderBridgesBody\(.*?\n\}", src, re.S).group(0)
    for arg in ("p.ship", "s.id", "x.id"):
        assert "_cpEventArg(" + arg + ")" in body, arg
        assert "escapeHtmlCP(" + arg + ")" not in body, arg
