"""The Developer Options Combat tab's Python and JS focusable lists stay
aligned (keyboard focus walks the same rows the page draws)."""
import re
from pathlib import Path

import pytest

from engine import dev_mode
from engine.ui.developer_options_panel import DeveloperOptionsPanel

JS = str(Path(__file__).resolve().parents[2]
         / "native/assets/ui-cef/js/developer_options.js")


@pytest.fixture(autouse=True)
def _dev_on(monkeypatch):
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: True)


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
