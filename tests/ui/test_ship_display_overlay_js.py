"""ship_display.js places damage icons as a fraction of the 128 px frame,
run for real under node against a minimal fake DOM."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
JS_PATH = ROOT / "native/assets/ui-cef/panels/ship_display/ship_display.js"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node not installed")

_HARNESS = r"""
const fs = require("fs");
function mkEl() {
  const el = {children: [], style: {}, dataset: {}, className: "", hidden: false,
    innerHTML: "", textContent: "",
    appendChild(c) { el.children.push(c); },
    removeAttribute() {}, querySelector: () => null};
  Object.defineProperty(el, "innerHTML", {
    get() { return el._h || ""; },
    set(v) { el._h = v; if (v === "") el.children = []; }});
  return el;
}
const overlay = mkEl();
const root = mkEl();
root.querySelector = sel => (sel === '[data-bind="damage-overlay"]' ? overlay : null);
global.document = {getElementById: id => (id === "ship-display-target" ? root : null),
                   createElement: () => mkEl()};
global.window = {};
(0, eval)(fs.readFileSync(process.argv[1], "utf8"));
window.setShipDisplay("target", JSON.parse(process.argv[2]));
console.log(JSON.stringify(overlay.children.map(c => ({
  left: c.style.left, top: c.style.top, state: c.dataset.state, key: c.dataset.iconKey}))));
"""


def test_damage_icon_position_is_fraction_of_128_frame():
    state = {"visible": True, "damage_icons": [
        {"icon_key": "warp-pod", "icon_svg": "<svg/>", "x_px": 4, "y_px": 90,
         "state": "damaged"}]}
    r = subprocess.run([NODE, "-e", _HARNESS, "--", str(JS_PATH), json.dumps(state)],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    icons = json.loads(r.stdout.strip().splitlines()[-1])
    assert len(icons) == 1
    assert icons[0]["left"] == "3.13%"
    assert icons[0]["top"] == "70.31%"
    assert icons[0]["key"] == "warp-pod"
