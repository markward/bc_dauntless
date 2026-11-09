import json

import pytest

from engine import dev_mode
from engine.ui.developer_options_panel import DeveloperOptionsPanel
from engine.wings import service


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: True)
    service.reset_all()
    service.reset_dev()
    yield
    service.reset_all()
    service.reset_dev()


def _payload(p):
    js = p.render_payload()
    assert js is not None
    return json.loads(js[js.index("(") + 1: js.rindex(")")])


def test_wing_toggles_round_trip_and_appear_in_payload():
    p = DeveloperOptionsPanel()
    p.open()
    s = _payload(p)["settings"]
    assert s["wing_ai"] is True
    assert s["wing_markers"] is False

    assert p.dispatch_event("toggle:wing_ai")
    assert service._dev_enabled is False
    assert _payload(p)["settings"]["wing_ai"] is False

    assert p.dispatch_event("toggle:wing_markers")
    assert service.show_markers() is True
    assert _payload(p)["settings"]["wing_markers"] is True


def test_wing_rows_are_focusable_on_combat_tab():
    p = DeveloperOptionsPanel()
    p.open()
    ctrls = [t for k, t in p._focusables() if k == "ctrl"]
    assert "wing_ai" in ctrls and "wing_markers" in ctrls
