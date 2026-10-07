import json
import pytest
from engine.ui.developer_options_panel import DeveloperOptionsPanel
from engine import dev_light_preview, dev_mode
from engine.appc import subsystem_glow


@pytest.fixture(autouse=True)
def _dev_on(monkeypatch):
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: True)
    dev_light_preview.reset()
    yield
    dev_light_preview.reset()


def _payload(p):
    js = p.render_payload()
    assert js is not None
    return json.loads(js[js.index("(") + 1: js.rindex(")")])


def test_lighting_tab_present_and_toggles_mutually_exclusive():
    p = DeveloperOptionsPanel()
    p.open()
    data = _payload(p)
    assert any(t["id"] == "lighting" for t in data["tabs"])
    assert data["settings"]["systems_damaged"] is False
    assert data["settings"]["systems_disabled"] is False

    assert p.dispatch_event("tab:lighting")
    assert p.dispatch_event("toggle:systems_damaged")
    assert dev_light_preview.forced_glow_state() == subsystem_glow.DISABLED
    data = _payload(p)
    assert data["settings"]["systems_damaged"] is True
    assert data["settings"]["systems_disabled"] is False

    # turning on 'disabled' clears 'damaged' in BOTH the flag and the panel mirror
    assert p.dispatch_event("toggle:systems_disabled")
    assert dev_light_preview.forced_glow_state() == subsystem_glow.DESTROYED
    data = _payload(p)
    assert data["settings"]["systems_damaged"] is False
    assert data["settings"]["systems_disabled"] is True

    # toggling it off returns to no forced state
    assert p.dispatch_event("toggle:systems_disabled")
    assert dev_light_preview.forced_glow_state() is None


def test_lighting_focusables_include_the_two_controls():
    p = DeveloperOptionsPanel()
    p.open()
    p.dispatch_event("tab:lighting")
    foc = p._focusables()
    assert ("ctrl", "systems_damaged") in foc
    assert ("ctrl", "systems_disabled") in foc


JS = "native/assets/ui-cef/js/developer_options.js"

def test_js_renders_lighting_toggles():
    text = open(JS).read()
    assert "systems_damaged" in text
    assert "systems_disabled" in text
    assert "Set Systems Damaged" in text
    assert "Set Systems Disabled" in text


def test_js_rock_catalogue_label_says_when_it_applies():
    """realize_set_objects reads the toggle too, so it applies to every rock
    loaded after toggling -- not only at mission load."""
    text = open(JS).read()
    assert ("Catalogue Rocks (off = stock BC; applies to rocks loaded after "
            "toggling)") in text
    assert "applies on mission load" not in text


def test_js_has_a_minor_rocks_row_and_focusable():
    text = open(JS).read()
    assert ("_doToggleRow('Minor Rocks', 'minor_rocks', s.minor_rocks, "
            "isFoc('minor_rocks'))") in text
    assert "out.push({kind: 'ctrl', target: 'minor_rocks'});" in text


def test_js_has_a_far_tier_row_and_focusable():
    text = open(JS).read()
    assert ("_doToggleRow('Rock Fields', 'far_tier', s.far_tier, "
            "isFoc('far_tier'))") in text
    assert "out.push({kind: 'ctrl', target: 'far_tier'});" in text


def test_js_has_rock_specks_and_rock_puffs_rows_and_focusables():
    text = open(JS).read()
    assert ("_doToggleRow('Rock Specks', 'rock_specks', s.rock_specks, "
            "isFoc('rock_specks'))") in text
    assert ("_doToggleRow('Rock Puffs', 'rock_puffs', s.rock_puffs, "
            "isFoc('rock_puffs'))") in text
    assert "out.push({kind: 'ctrl', target: 'rock_specks'});" in text
    assert "out.push({kind: 'ctrl', target: 'rock_puffs'});" in text


# ── Developer Options cleanup (2026-10-05): Environments + Diagnostics tabs,
# Combat's Sensor Occlusion switch ──────────────────────────────────────────

def test_js_renders_the_environments_body_function():
    text = open(JS).read()
    assert "function _doRenderEnvironmentsBody(state, focusables) {" in text
    assert "(state.selected_tab === 'environments') ? _doRenderEnvironmentsBody(state, focusables)" in text


def test_js_rock_rows_moved_out_of_the_lighting_focusable_list():
    """The rock-toggle focusables must come from the environments branch, not
    the lighting branch -- a stray row left in both tabs would make a row
    double-count in _focusables()."""
    text = open(JS).read()
    lighting_block = text[text.index("if (state.selected_tab === 'lighting') {"):
                           text.index("if (state.selected_tab === 'environments') {")]
    for target in ("rock_catalogue", "minor_rocks", "far_tier",
                   "rock_specks", "rock_puffs"):
        assert target not in lighting_block, (
            "%r still listed under the lighting focusable branch" % target)


def test_js_dial_group_row_moved_to_diagnostics():
    text = open(JS).read()
    diagnostics_body = text[text.index("function _doRenderDiagnosticsBody"):
                             text.index("function _doRenderLightingBody")]
    assert "dial_group" in diagnostics_body
    lighting_body = text[text.index("function _doRenderLightingBody"):
                          text.index("function _doRenderEnvironmentsBody")]
    assert "dial_group" not in lighting_body


def test_js_has_a_sensor_occlusion_row_and_focusable():
    text = open(JS).read()
    assert "_doToggleRow('Sensor Occlusion', 'sensor_occlusion'," in text
    assert "s.sensor_occlusion, isFoc('sensor_occlusion'));" in text
    assert "out.push({kind: 'ctrl', target: 'sensor_occlusion'});" in text


def test_js_has_a_planet_atmosphere_row_and_focusable():
    text = open(JS).read()
    assert ("_doToggleRow('Planet Atmospheres (off = airless; applies to "
            "planets realized after toggling)',\n"
            "                         'planet_atmosphere', s.planet_atmosphere, "
            "isFoc('planet_atmosphere'));") in text
    assert "out.push({kind: 'ctrl', target: 'planet_atmosphere'});" in text


def test_js_has_a_reload_atmospheres_action_row_and_focusable():
    text = open(JS).read()
    assert ("_doActionRow('Reload Planet Atmospheres', 'reload_atmospheres',\n"
            "                         'Reload', isFoc('reload_atmospheres'));") in text
    assert "out.push({kind: 'ctrl', target: 'reload_atmospheres'});" in text
