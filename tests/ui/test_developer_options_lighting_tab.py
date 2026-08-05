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
