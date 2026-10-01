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
    assert ("_doToggleRow('Far Tier', 'far_tier', s.far_tier, "
            "isFoc('far_tier'))") in text
    assert "out.push({kind: 'ctrl', target: 'far_tier'});" in text
