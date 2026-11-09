"""The wing developer toggles are gone (Mark, 2026-11-09): wings are switched
per battle on the Quick Battle setup screen and the commander chevron is
always on in the target list. The Combat tab's Python and JS focusable lists
stay aligned."""
import json
import re

import pytest

from engine import dev_mode
from engine.ui.developer_options_panel import DeveloperOptionsPanel

JS = "native/assets/ui-cef/js/developer_options.js"


@pytest.fixture(autouse=True)
def _dev_on(monkeypatch):
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: True)


def _payload(p):
    js = p.render_payload()
    assert js is not None
    return json.loads(js[js.index("(") + 1: js.rindex(")")])


def test_no_wing_rows_in_payload_or_dispatch():
    p = DeveloperOptionsPanel()
    p.open()
    s = _payload(p)["settings"]
    assert "wing_ai" not in s and "wing_markers" not in s
    assert not p.dispatch_event("toggle:wing_ai")
    assert not p.dispatch_event("toggle:wing_markers")


def test_no_wing_rows_in_js():
    text = open(JS).read()
    assert "wing_ai" not in text and "wing_markers" not in text
    assert "Show Wing Commanders" not in text


def test_combat_focusables_match_js():
    p = DeveloperOptionsPanel()
    p.open()
    py = [t for k, t in p._focusables() if k == "ctrl"]
    text = open(JS).read()
    block = re.search(r"if \(state\.selected_tab === 'combat'\) \{(.*?)\n    \}",
                      text, re.S).group(1)
    js = re.findall(r"target: '(\w+)'", block)
    assert py == js
    assert "quick_repair" in py
