"""Faction emblems sit between a star and its name, inside the label, so a
hidden name hides them (Mark, 2026-10-25). Executes the real
starMapSystemLabelsHtml under node, following test_crew_menu_system_row_js.py.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
JS_PATH = ROOT / "native/assets/ui-cef/js/star_map.js"
CSS_PATH = ROOT / "native/assets/ui-cef/css/star_map.css"
NODE = shutil.which("node")

_HARNESS = r"""
const fs = require("fs");
global.document = {getElementById: function () { return null; },
                   addEventListener: function () {}};
global.window = global;
eval(fs.readFileSync(process.argv[2], "utf8"));
process.stdout.write(starMapSystemLabelsHtml(JSON.parse(process.argv[3])));
"""

FED = "file:///assets/insignias/federation.svg"
CARD = "file:///assets/insignias/cardassian.svg"


def _render(state, tmp_path):
    if NODE is None:
        pytest.skip("node not installed")
    harness = tmp_path / "harness.js"
    harness.write_text(_HARNESS)
    out = subprocess.run([NODE, str(harness), str(JS_PATH), json.dumps(state)],
                         capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return out.stdout


def _label(sid, name, icons, offered=True):
    return {"id": sid, "label": name, "x": 10, "y": 20, "visible": True,
            "offered": offered, "icons": icons}


def test_each_emblem_sits_before_the_name(tmp_path):
    html = _render({"labels": [_label("tauceti", "Tau Ceti", [FED, CARD])]},
                   tmp_path)
    fed, card, name = (html.index(FED), html.index(CARD),
                       html.index("Tau Ceti"))
    assert fed < card < name
    assert html.count('class="sm-label__icon"') == 2


def test_a_system_with_no_station_has_no_emblem(tmp_path):
    html = _render({"labels": [_label("vesuvi", "Vesuvi", [])]}, tmp_path)
    assert "sm-label__icon" not in html and "Vesuvi" in html


def test_a_hidden_name_hides_its_emblem(tmp_path):
    state = {"labels": [_label("prendel", "Prendel", [CARD], offered=False)]}
    assert _render(state, tmp_path) == ""
    state["show_all_labels"] = True
    html = _render(state, tmp_path)
    assert CARD in html and "sm-label--inert" in html


def test_an_emblem_url_is_escaped(tmp_path):
    html = _render({"labels": [_label("x", "X", ['a"><b>'])]}, tmp_path)
    assert "<b>" not in html


def test_the_emblem_is_sized_to_the_name():
    css = CSS_PATH.read_text(encoding="utf-8")
    block = css[css.index(".sm-label__icon"):]
    block = block[:block.index("}")]
    assert "height: 1em" in block
