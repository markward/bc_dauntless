"""The CEF side of FlickerShields: ship_display.js turns the payload's
`shields_hidden` into root data attributes, and ship_display.css hides the
arcs BC keeps in each ShieldsDisplay pane (TOP_PANE: top/front/rear/left/
right, BOTTOM_PANE: bottom) -- never the silhouette, BC's SHIP_ICON."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_PANEL = (Path(__file__).resolve().parents[2]
          / "native" / "assets" / "ui-cef" / "panels" / "ship_display")
_NODE = shutil.which("node")

# Just enough DOM for setShipDisplay: one root, every query misses.
_HARNESS = """
var root = {hidden: true, dataset: {}, querySelector: function () { return null; }};
var document = {getElementById: function (id) {
    return id === "ship-display-player" ? root : null; }};
var window = {};
%s
var out = [];
var states = %s;
for (var i = 0; i < states.length; i++) {
    window.setShipDisplay("player", states[i]);
    out.push({top: root.dataset.shieldsTopHidden,
              bottom: root.dataset.shieldsBottomHidden});
}
console.log(JSON.stringify(out));
"""


def _run(states):
    js = (_PANEL / "ship_display.js").read_text(encoding="utf-8")
    src = _HARNESS % (js, json.dumps(states))
    result = subprocess.run([_NODE, "-e", src], capture_output=True,
                            text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.skipif(_NODE is None, reason="node not available to run JS")
def test_js_mirrors_each_pane_onto_the_root():
    base = {"visible": True, "shields_pct": [1.0] * 6}
    states = [
        dict(base, shields_hidden={"top_pane": True, "bottom_pane": True}),
        dict(base, shields_hidden={"top_pane": False, "bottom_pane": True}),
        dict(base, shields_hidden={"top_pane": False, "bottom_pane": False}),
        base,  # an older payload with no field shows the arcs
    ]
    assert _run(states) == [
        {"top": "true", "bottom": "true"},
        {"top": "false", "bottom": "true"},
        {"top": "false", "bottom": "false"},
        {"top": "false", "bottom": "false"},
    ]


def _hidden_classes(css, attr):
    out = set()
    for rule in re.finditer(r"([^{}]+)\{([^}]*)\}", css):
        selectors, body = rule.group(1), rule.group(2)
        if "visibility: hidden" not in body:
            continue
        for sel in selectors.split(","):
            m = re.search(r'\[data-shields-%s-hidden="true"\]\s+\.([\w-]+)'
                          % attr, sel)
            if m:
                out.add(m.group(1))
    return out


def test_css_hides_bcs_pane_contents_and_never_the_silhouette():
    css = (_PANEL / "ship_display.css").read_text(encoding="utf-8")
    assert _hidden_classes(css, "top") == {
        "shield--top", "shield--front", "shield--rear",
        "shield--left", "shield--right"}
    assert _hidden_classes(css, "bottom") == {"shield--bottom"}
    assert "silhouette" not in " ".join(
        _hidden_classes(css, "top") | _hidden_classes(css, "bottom"))
