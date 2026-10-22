"""Shared hue/saturation wheel (spec 2026-10-08-bridge-emitters §12.4)."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
JS = ROOT / "native/assets/ui-cef/js/colour_wheel.js"
HTML = ROOT / "native/assets/ui-cef/index.html"
SPV = ROOT / "native/assets/ui-cef/js/ship_property_viewer.js"

_HARNESS = r"""
const fs = require('fs'); const vm = require('vm');
const ctx = {Math, document: {getElementById: () => null}};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[process.argv.length - 1], 'utf8'), ctx);
const out = {
  red: ctx.colourHsToRgb(0, 1), green: ctx.colourHsToRgb(120, 1),
  white: ctx.colourHsToRgb(200, 0), orange: ctx.colourRgbToHs([1, 0.5, 0]),
  round: ctx.colourRgbToHs(ctx.colourHsToRgb(250, 0.4)),
  black: ctx.colourRgbToHs([0, 0, 0]),
};
process.stdout.write(JSON.stringify(out));
"""


def _run():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed")
    r = subprocess.run([node, "-e", _HARNESS, "--", str(JS)], capture_output=True,
                       text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_hs_rgb_conversions():
    out = _run()
    assert out["red"] == pytest.approx([1, 0, 0])
    assert out["green"] == pytest.approx([0, 1, 0])
    assert out["white"] == pytest.approx([1, 1, 1])
    assert out["orange"]["hue"] == pytest.approx(30)
    assert out["orange"]["sat"] == pytest.approx(1)
    assert out["round"]["hue"] == pytest.approx(250)
    assert out["round"]["sat"] == pytest.approx(0.4)
    assert out["black"] == {"hue": 0, "sat": 0}


def test_the_page_loads_the_wheel_before_its_users():
    html = HTML.read_text(encoding="utf-8")
    w = html.index('src="js/colour_wheel.js"')
    assert w < html.index('src="js/ship_property_viewer.js"')
    assert w < html.index('src="js/bridge_emitters.js"')


def test_the_spv_no_longer_carries_its_own_wheel():
    src = SPV.read_text(encoding="utf-8")
    for gone in ("function spvHsToRgb", "function spvRgbToHs", "_spvWheelBase",
                 "_spvSetHueSatFromEvent"):
        assert gone not in src
    assert "new ColourWheel(" in src


_DRAG = r"""
const fs = require('fs'); const vm = require('vm');
function canvas() {
  const ls = {};
  return {width: 20, height: 20, ls,
    addEventListener: (k, f) => { ls[k] = f; },
    setPointerCapture: () => {},
    getBoundingClientRect: () => ({left: 0, top: 0, width: 20, height: 20}),
    getContext: () => ({createImageData: (w, h) => ({data: new Array(w * h * 4).fill(0)}),
                        putImageData: () => {}, beginPath: () => {}, arc: () => {},
                        stroke: () => {}})};
}
const ctx = {Math, document: {getElementById: () => null}};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[process.argv.length - 1], 'utf8'), ctx);
const c = canvas(); const calls = [];
const wheel = new ctx.ColourWheel(c, {hue: 0, sat: 0}, (hs, final) => calls.push(final));
c.ls.pointerdown({pointerId: 1, clientX: 15, clientY: 10});
const during = wheel.dragging;
c.ls.lostpointercapture({pointerId: 1});
const after = wheel.dragging;
c.ls.pointerup({pointerId: 1, clientX: 15, clientY: 10});
process.stdout.write(JSON.stringify({during, after, calls}));
"""


def test_a_lost_pointer_capture_ends_the_drag_without_committing():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed")
    r = subprocess.run([node, "-e", _DRAG, "--", str(JS)], capture_output=True, text=True,
                       timeout=30)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["during"] is True and out["after"] is False
    assert out["calls"] == [False]          # the pointerdown preview only; no commit
