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
    assert b["adding"] is False                     # list view by default
    assert b["add_ship"] is None
    assert b["add_bridge"] == "GalaxyBridge"        # first available preselected
    assert b["can_add"] is False
    assert b["default"] == {"bridge": "GalaxyBridge", "bridge_label": "Galaxy",
                            "bridge_missing": False}
    assert b["edit_default"] is False


def _open_add(p):
    p.open(); p.dispatch_event("tab:bridges")
    assert p.dispatch_event("bridge:add_open") is True


def test_add_open_enters_the_add_view_with_a_fresh_selection(pins):
    p = _make(pins); p.open(); p.dispatch_event("tab:bridges")
    p.dispatch_event("bridge:add_open"); p.dispatch_event("bridge:ship:BirdOfPrey")
    p.dispatch_event("bridge:bridge:SovereignBridge")
    p.dispatch_event("bridge:cancel")
    assert p.dispatch_event("bridge:add_open") is True
    b = _body(p)["bridges"]
    assert b["adding"] is True
    assert b["add_ship"] is None
    assert b["add_bridge"] == "GalaxyBridge"        # back to the first available
    assert b["can_add"] is False


def test_select_ship_then_save_maps_it_and_returns_to_the_list(pins):
    p = _make(pins); _open_add(p)
    assert p.dispatch_event("bridge:ship:BirdOfPrey") is True
    assert _body(p)["bridges"]["can_add"] is True
    assert p.dispatch_event("bridge:bridge:SovereignBridge") is True
    assert p.dispatch_event("bridge:add") is True
    b = _body(p)["bridges"]
    assert pins.pins()["BirdOfPrey"] == "SovereignBridge"
    assert [s["id"] for s in b["ships"]] == ["KessokLight"]
    assert b["adding"] is False                     # Save leaves the view
    assert b["add_ship"] is None                    # selection cleared
    assert b["can_add"] is False


def test_cancel_discards_the_selection_and_returns_to_the_list(pins):
    p = _make(pins); _open_add(p)
    p.dispatch_event("bridge:ship:BirdOfPrey")
    assert p.dispatch_event("bridge:cancel") is True
    b = _body(p)["bridges"]
    assert b["adding"] is False
    assert b["add_ship"] is None
    assert len(pins.pins()) == 3


def test_cancel_outside_the_add_view_is_rejected(pins):
    p = _make(pins); p.open(); p.dispatch_event("tab:bridges")
    assert p.dispatch_event("bridge:cancel") is False


def test_selection_outside_the_add_view_is_rejected(pins):
    p = _make(pins); p.open(); p.dispatch_event("tab:bridges")
    assert p.dispatch_event("bridge:ship:BirdOfPrey") is False
    assert p.dispatch_event("bridge:bridge:SovereignBridge") is False
    assert p.dispatch_event("bridge:add") is False
    assert _body(p)["bridges"]["add_ship"] is None


def test_add_open_is_rejected_when_every_ship_is_mapped(fake_install, tmp_path):
    p = _make(bs.load_bridge_pins(tmp_path / "bridges.json"))
    p.open(); p.dispatch_event("tab:bridges")
    for ship in ("BirdOfPrey", "KessokLight"):
        p.dispatch_event("bridge:add_open")
        p.dispatch_event("bridge:ship:" + ship)
        p.dispatch_event("bridge:add")
    assert p.dispatch_event("bridge:add_open") is False
    b = _body(p)["bridges"]
    assert b["ships"] == [] and b["adding"] is False


def test_esc_in_the_add_view_cancels_the_add_not_the_panel(pins):
    p = _make(pins); _open_add(p)
    p.dispatch_event("bridge:ship:BirdOfPrey")
    p.handle_key_esc()
    assert p.is_open()
    b = _body(p)["bridges"]
    assert b["adding"] is False and b["add_ship"] is None
    p.handle_key_esc()
    assert not p.is_open()


def test_edit_opens_the_view_on_the_rows_ship_and_current_bridge(pins):
    p = _make(pins); p.open(); p.dispatch_event("tab:bridges")
    assert p.dispatch_event("bridge:edit:Akira") is True
    b = _body(p)["bridges"]
    assert b["adding"] is True and b["edit_ship"] == "Akira"
    assert b["add_ship"] == "Akira"
    assert b["add_bridge"] == "SovereignBridge"     # the row's current bridge
    assert b["can_add"] is True                     # Save is live at once


def test_edit_save_replaces_the_bridge_and_returns_to_the_list(pins):
    p = _make(pins); p.open(); p.dispatch_event("tab:bridges")
    p.dispatch_event("bridge:edit:Akira")
    assert p.dispatch_event("bridge:bridge:GalaxyBridge") is True
    assert p.dispatch_event("bridge:add") is True
    b = _body(p)["bridges"]
    assert pins.pins()["Akira"] == "GalaxyBridge"
    assert [r["ship"] for r in b["pins"]] == ["Galaxy", "Sovereign", "Akira"]
    assert b["adding"] is False and b["edit_ship"] is None


def test_edit_cancel_keeps_the_old_bridge(pins):
    p = _make(pins); p.open(); p.dispatch_event("tab:bridges")
    p.dispatch_event("bridge:edit:Akira"); p.dispatch_event("bridge:bridge:GalaxyBridge")
    p.handle_key_esc()
    assert p.is_open()
    assert pins.pins()["Akira"] == "SovereignBridge"
    b = _body(p)["bridges"]
    assert b["adding"] is False and b["edit_ship"] is None and b["add_ship"] is None


def test_edit_of_an_unmapped_ship_is_rejected(pins):
    p = _make(pins); p.open(); p.dispatch_event("tab:bridges")
    assert p.dispatch_event("bridge:edit:BirdOfPrey") is False
    assert _body(p)["bridges"]["adding"] is False


def test_edit_allows_a_row_whose_ship_or_bridge_is_missing(fake_install, tmp_path):
    f = tmp_path / "bridges.json"
    f.write_text('{"version": 1, "pins": {"LCIntrepid": "VoyagerBridge"}}')
    pins = bs.load_bridge_pins(f)
    p = _make(pins); p.open(); p.dispatch_event("tab:bridges")
    assert p.dispatch_event("bridge:edit:LCIntrepid") is True
    b = _body(p)["bridges"]
    assert b["add_bridge"] == "GalaxyBridge"        # unavailable -> first available
    p.dispatch_event("bridge:add")
    assert pins.pins()["LCIntrepid"] == "GalaxyBridge"


def test_edit_view_does_not_change_ship_and_has_no_ship_rows(pins):
    p = _make(pins); p.open(); p.dispatch_event("tab:bridges")
    p.dispatch_event("bridge:edit:Akira")
    assert p.dispatch_event("bridge:ship:BirdOfPrey") is False
    assert p._focusables() == [
        ("tab", "graphics"), ("tab", "bridges"),
        ("bridge_pick", "GalaxyBridge"), ("bridge_pick", "SovereignBridge"),
        ("ctrl", "bridge_cancel"), ("ctrl", "bridge_add"),
    ]


def test_edit_default_opens_the_view_on_the_current_default(pins):
    p = _make(pins); p.open(); p.dispatch_event("tab:bridges")
    assert p.dispatch_event("bridge:edit_default") is True
    b = _body(p)["bridges"]
    assert b["adding"] is True and b["edit_default"] is True
    assert b["edit_ship"] is None and b["add_bridge"] == "GalaxyBridge"
    assert b["can_add"] is True
    assert p.dispatch_event("bridge:ship:BirdOfPrey") is False   # no ship here
    assert p._focusables() == [
        ("tab", "graphics"), ("tab", "bridges"),
        ("bridge_pick", "GalaxyBridge"), ("bridge_pick", "SovereignBridge"),
        ("ctrl", "bridge_cancel"), ("ctrl", "bridge_add"),
    ]


def test_edit_default_save_sets_the_default_and_returns(pins):
    p = _make(pins); p.open(); p.dispatch_event("tab:bridges")
    p.dispatch_event("bridge:edit_default")
    p.dispatch_event("bridge:bridge:SovereignBridge")
    assert p.dispatch_event("bridge:add") is True
    b = _body(p)["bridges"]
    assert pins.default_bridge() == "SovereignBridge"
    assert b["default"]["bridge_label"] == "Sovereign"
    assert b["adding"] is False and b["edit_default"] is False
    assert len(pins.pins()) == 3                    # no row was added


def test_edit_default_cancel_keeps_it(pins):
    p = _make(pins); p.open(); p.dispatch_event("tab:bridges")
    p.dispatch_event("bridge:edit_default"); p.dispatch_event("bridge:bridge:SovereignBridge")
    p.handle_key_esc()
    assert pins.default_bridge() == "GalaxyBridge"
    assert _body(p)["bridges"]["edit_default"] is False


def test_there_is_no_remove_for_the_default(pins):
    p = _make(pins); p.open(); p.dispatch_event("tab:bridges")
    assert p.dispatch_event("bridge:remove:__default__") is True   # a no-op remove
    assert pins.default_bridge() == "GalaxyBridge"
    assert ("bridge_remove", "__default__") not in p._focusables()


def test_edit_is_a_list_view_control(pins):
    p = _make(pins); _open_add(p)
    assert p.dispatch_event("bridge:edit:Akira") is False


def test_add_without_a_ship_is_rejected(pins):
    p = _make(pins); _open_add(p)
    assert p.dispatch_event("bridge:add") is False
    assert len(pins.pins()) == 3
    assert _body(p)["bridges"]["adding"] is True    # still on the add view


def test_selecting_a_pinned_ship_is_rejected(pins):
    p = _make(pins); _open_add(p)
    assert p.dispatch_event("bridge:ship:Galaxy") is False


def test_selecting_an_unknown_bridge_is_rejected(pins):
    p = _make(pins); _open_add(p)
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


def test_focusables_mirror_the_list_view_rows(pins):
    p = _make(pins); p.open(); p.dispatch_event("tab:bridges")
    assert p._focusables() == [
        ("tab", "graphics"), ("tab", "bridges"),
        ("bridge_edit", "Galaxy"), ("bridge_remove", "Galaxy"),
        ("bridge_edit", "Sovereign"), ("bridge_remove", "Sovereign"),
        ("bridge_edit", "Akira"), ("bridge_remove", "Akira"),
        ("ctrl", "bridge_edit_default"),
        ("ctrl", "bridge_add_open"), ("ctrl", "reset_bridges"),
    ]


def test_focusables_mirror_the_add_view_rows(pins):
    p = _make(pins); _open_add(p)
    assert p._focusables() == [
        ("tab", "graphics"), ("tab", "bridges"),
        ("bridge_ship", "BirdOfPrey"), ("bridge_ship", "KessokLight"),
        ("bridge_pick", "GalaxyBridge"), ("bridge_pick", "SovereignBridge"),
        ("ctrl", "bridge_cancel"), ("ctrl", "bridge_add"),
    ]


def test_keyboard_activation_drives_the_view_transitions(pins):
    """Enter on the focused Add Mapping / Cancel / Save controls fires the
    same actions the mouse does. _focused is set directly: the focus index
    is what handle_input reads, and the test is about the activation branch,
    not the arrow-key walk."""
    keys = Mock(KEY_DOWN=1, KEY_UP=2, KEY_SPACE=3, KEY_ENTER=4, KEY_LEFT=5, KEY_RIGHT=6)
    def press(code):
        h = Mock(keys=keys); h.key_pressed = lambda c: c == code
        return h
    p = _make(pins); p.open(); p.dispatch_event("tab:bridges")
    p._focused = p._focusables().index(("ctrl", "bridge_add_open"))
    p.handle_input(press(keys.KEY_ENTER))
    assert _body(p)["bridges"]["adding"] is True
    assert p._focused == -1                         # focus resets across views
    p.dispatch_event("bridge:cancel")
    p._focused = p._focusables().index(("bridge_edit", "Akira"))
    p.handle_input(press(keys.KEY_ENTER))
    assert _body(p)["bridges"]["edit_ship"] == "Akira"
    p._focused = p._focusables().index(("ctrl", "bridge_cancel"))
    p.handle_input(press(keys.KEY_ENTER))
    assert _body(p)["bridges"]["adding"] is False
    p.dispatch_event("bridge:add_open"); p.dispatch_event("bridge:ship:BirdOfPrey")
    p._focused = p._focusables().index(("ctrl", "bridge_add"))
    p.handle_input(press(keys.KEY_ENTER))
    assert pins.pins()["BirdOfPrey"] == "GalaxyBridge"
    assert _body(p)["bridges"]["adding"] is False


def test_leaving_the_tab_leaves_the_add_view_and_clears_the_selection(pins):
    p = _make(pins); _open_add(p)
    p.dispatch_event("bridge:ship:BirdOfPrey")
    p.dispatch_event("tab:graphics"); p.dispatch_event("tab:bridges")
    b = _body(p)["bridges"]
    assert b["adding"] is False and b["add_ship"] is None


def test_closing_the_panel_leaves_the_add_view(pins):
    p = _make(pins); _open_add(p)
    p.close(); p.open()
    assert _body(p)["bridges"]["adding"] is False


def test_payload_is_not_repushed_when_nothing_changed(pins):
    p = _make(pins); p.open(); p.dispatch_event("tab:bridges")
    assert p.render_payload() is not None
    assert p.render_payload() is None
    p.dispatch_event("bridge:add_open")
    assert p.render_payload() is not None
    assert p.render_payload() is None
    p.dispatch_event("bridge:ship:BirdOfPrey")
    assert p.render_payload() is not None


def test_closed_panel_does_not_compute_the_bridges_block(pins, monkeypatch):
    # render_payload used to call _bridges_block() -- rows()/unpinned_ships()/
    # available_bridges()/json.dumps -- unconditionally, on every pump, even
    # while the panel is closed. Spy on rows() to prove it now runs only
    # while the panel is visible.
    calls = []
    real_rows = pins.rows
    monkeypatch.setattr(pins, "rows", lambda: (calls.append(1), real_rows())[1])
    p = _make(pins)

    assert p.render_payload() is not None    # closed -> the hide payload
    assert calls == []

    p.open(); p.dispatch_event("tab:bridges")
    assert p.render_payload() is not None
    assert calls == [1]


# ---- JS mirrors -----------------------------------------------------------------

def _js_source():
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    return (root / "native/assets/ui-cef/js/configuration_panel.js").read_text()


def _js_bridges_renderers():
    """Source of _cpRenderBridgesBody and the per-view renderers it
    dispatches to, concatenated."""
    import re
    return "\n".join(re.findall(r"function _cpRenderBridges\w*\(.*?\n\}", _js_source(), re.S))


def test_js_focusable_list_has_a_bridges_branch_in_python_order():
    """_cpFocusableList's bridges branch must push, per view, exactly what
    ConfigurationPanel._focusables does: add view = one bridge_ship per
    unmapped ship, one bridge_pick per available bridge, then bridge_cancel
    and bridge_add; list view = one bridge_remove per mapping, then
    bridge_add_open and reset_bridges. Space on a focused row otherwise
    fires the wrong control."""
    import re
    src = _js_source()
    branch = re.search(r"selected_tab === 'bridges'\)\s*\{(.*?)\n    \}", src, re.S)
    assert branch, "no bridges branch in _cpFocusableList"
    body = branch.group(1)
    adding, listing = re.split(r"\}\s*else\s*\{", body)
    assert "b.adding" in adding
    assert re.findall(r"kind: '(\w+)'", adding) == ["bridge_ship", "bridge_pick", "ctrl", "ctrl"]
    assert re.findall(r"target: '(\w+)'", adding) == ["bridge_cancel", "bridge_add"]
    assert re.findall(r"kind: '(\w+)'", listing) == ["bridge_edit", "bridge_remove", "ctrl", "ctrl", "ctrl"]
    assert re.findall(r"target: '(\w+)'", listing) == ["bridge_edit_default", "bridge_add_open", "reset_bridges"]


def test_js_renders_the_bridges_tab_and_dispatches_every_action():
    src = _js_source()
    assert "_cpRenderBridgesBody" in src
    assert "selected_tab === 'bridges'" in src
    for action in ("configuration/bridge:ship:", "configuration/bridge:bridge:",
                   "configuration/bridge:add\\'", "configuration/bridge:add_open",
                   "configuration/bridge:edit:", "configuration/bridge:edit_default",
                   "configuration/bridge:cancel", "configuration/bridge:remove:",
                   "configuration/reset:bridges"):
        assert action in src, action


def test_js_bridges_copy_says_mapped_never_pinned():
    """The UI vocabulary is "mapping"/"mapped"; "pin" is the internal name
    (BridgePins, bridges.json) and must not leak into the panel text. The
    check is on rendered-text fragments inside the Bridges renderer, not on
    identifiers like b.pins, which stay."""
    import re
    body = _js_bridges_renderers()
    visible = re.findall(r">([^<'\"]*?)<|'([^']*?)'", body)
    texts = " ".join(a or b for a, b in visible)
    assert not re.search(r"\bpin(ned|s)?\b", texts, re.I), texts
    for copy in ("Mapped", "Add Mapping", "Edit Mapping", "Edit", "Cancel", "Save",
                 "No ships mapped.", "Every ship is mapped.", "Default"):
        assert copy in body, copy
    assert "Ships without a mapping use the" not in body


def test_js_default_row_has_edit_but_no_remove():
    import re
    body = _js_bridges_renderers()
    row = re.search(r"cp-bridges__default.*?</div>';", body, re.S).group(0)
    assert "_cpIconButton('Edit default', CP_ICON_PENCIL" in row
    assert "bridge:edit_default" in row
    assert "Remove" not in row and "bridge:remove" not in row


def test_js_shows_missing_markers_and_never_uses_a_native_select():
    src = _js_source()
    assert "(missing)" in src
    assert "(not playable)" in src
    assert "(ship not installed)" not in src
    assert "<select" not in src.lower()


def test_js_onclick_ids_are_js_escaped_not_just_html_escaped():
    src = _js_source()
    assert "function _cpEventArg(" in src
    body = _js_bridges_renderers()
    for arg in ("p.ship", "s.id", "x.id"):
        assert "_cpEventArg(" + arg + ")" in body, arg
        assert "escapeHtmlCP(" + arg + ")" not in body, arg


def test_js_preserves_scroll_positions_across_a_rerender():
    """Every Python push rebuilds the tab body with innerHTML, which drops
    the ship list's scroll position — clicking a ship (a payload change)
    snapped the list back to the top so the pick vanished off-screen.
    setConfigurationPanel must read the scrollTop of the scrolling
    containers before the swap and write it back after."""
    import re
    src = _js_source()
    fn = re.search(r"function setConfigurationPanel\(.*?\n\}", src, re.S).group(0)
    swap = fn.index("body.innerHTML")
    assert "_cpCaptureScroll(body)" in fn[:swap], "scroll not captured before the rebuild"
    assert "_cpRestoreScroll(body" in fn[swap:], "scroll not restored after the rebuild"
    capture = re.search(r"function _cpCaptureScroll\(.*?\n\}", src, re.S).group(0)
    restore = re.search(r"function _cpRestoreScroll\(.*?\n\}", src, re.S).group(0)
    assert "scrollTop" in capture and "scrollTop" in restore
    assert re.search(r"CP_SCROLLERS = \[[^\]]*'\.cp-bridges__ships'", src)


def test_js_row_actions_are_icon_buttons_with_css_hover_text():
    """Edit/Remove are icon buttons. The host's CefDisplayHandler has no
    OnTooltip, so a title= attribute never shows under OSR; hover text is
    drawn by the page from data-tip via a CSS ::after rule."""
    import re
    from pathlib import Path
    src = _js_source()
    body = _js_bridges_renderers()
    row = re.search(r"cp-bridges__pin.*?</div>';", body, re.S).group(0)
    assert "_cpIconButton('Edit mapping', CP_ICON_PENCIL" in row
    assert "_cpIconButton('Remove mapping', CP_ICON_CROSS" in row
    assert ">Edit</button>" not in row and ">Remove</button>" not in row
    helper = re.search(r"function _cpIconButton\(.*?\n\}", src, re.S).group(0)
    assert "data-tip=\"' + tip" in helper and "aria-label=\"' + tip" in helper
    assert "title=" not in helper
    for const in ("CP_ICON_PENCIL", "CP_ICON_CROSS"):
        assert re.search(r"const %s =\s*'<svg" % const, src), const
    root = Path(__file__).resolve().parents[2]
    css = (root / "native/assets/ui-cef/css/configuration_panel.css").read_text()
    assert re.search(r"\[data-tip\][^{]*:hover::after", css)
    assert re.search(r"\.cp-focused\[data-tip\]::after|\[data-tip\]\.cp-focused::after", css)
    assert "content: attr(data-tip)" in css
