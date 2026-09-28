"""The SPV Decals pane in CEF (spec 2026-09-28-spv-decal-editing-design.md
S3): markup present, and a node harness that EXECUTES renderSPVDecals and its
handlers (test_spv_part_tree_cef.py's `_NODE_HARNESS` pattern) -- the events
the pane fires are exactly the ones ShipPropertyViewerPanel dispatches."""
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HTML = ROOT / "native/assets/ui-cef/index.html"
JS = ROOT / "native/assets/ui-cef/js/ship_property_viewer.js"
CSS = ROOT / "native/assets/ui-cef/css/ship_property_viewer.css"
NODE = shutil.which("node")


def test_the_pane_markup_sits_in_the_left_column_after_model_parts():
    html = HTML.read_text(encoding="utf-8")
    left = html.index('id="spv-left"')
    parts = html.index('id="spv-parts"')
    decals = html.index('id="spv-decals"')
    assert left < parts < decals
    assert "ship-property-viewer/decal-pane" in html
    assert 'id="spv-decals-body"' in html


def test_the_pane_is_styled():
    css = CSS.read_text(encoding="utf-8")
    assert "#spv-decals.expanded #spv-decals-body" in css


_HARNESS = r"""
const fs = require("fs");
global.window = global;
function makeEl() {
  const classes = new Set();
  return {innerHTML: "", style: {}, textContent: "", checked: false,
          classList: {toggle: function (c, v) { if (v) classes.add(c); else classes.delete(c); },
                      contains: function (c) { return classes.has(c); }},
          contains: function () { return false; }, addEventListener: function () {}};
}
const els = {"spv-decals": makeEl(), "spv-decals-body": makeEl()};
global.document = {getElementById: function (id) { return els[id] || null; },
                   addEventListener: function () {}};
let events = [];
global.dauntlessEvent = function (s) { events.push(s); };
eval(fs.readFileSync(process.argv[2], "utf8"));

const NAME = "we'ird\"&";
const base = {active: true, has_model: true, registries: ["Excalibur", "Zhukov"],
  registry: "Zhukov", default_registry: "Zhukov",
  placements: [{name: "top", has_mask: true}, {name: NAME, has_mask: false}],
  selected: "top", adding: false, adding_name: null, reposition: false,
  error: "Name refused: nope", can_add: true, suggested_names: ["bottom", "port"],
  numbers: {centre: [1, 2, 3], width: 1.5, roll: 10, depth: 0.1, step: 0.075},
  dirty: false};
const out = {};
renderSPVDecals(base);
out.expanded = els["spv-decals"].classList.contains("expanded");
out.html = els["spv-decals-body"].innerHTML;
function el(data) { return {dataset: data}; }
shipPropertyViewerDecalRegistry(el({name: "Excalibur"}));
shipPropertyViewerDecalSelect(el({name: NAME}));
shipPropertyViewerDecalAddOpen();
out.picker = els["spv-decals-body"].innerHTML;
shipPropertyViewerDecalAddName(el({name: "bottom"}));
shipPropertyViewerDecalReposition();
shipPropertyViewerDecalDeleteAsk(el({name: "top"}));
out.confirm = els["spv-decals-body"].innerHTML;
shipPropertyViewerDecalDeleteYes(el({name: "top"}));
shipPropertyViewerDecalNudge(el({field: "width", delta: "0.075"}));
shipPropertyViewerDecalAddCancel();
shipPropertyViewerDecalDefault(el({name: "Excalibur"}));
out.events = events;
renderSPVDecals(Object.assign({}, base, {active: false}));
out.collapsed = !els["spv-decals"].classList.contains("expanded")
                && els["spv-decals-body"].innerHTML === "";
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def run():
    if NODE is None:
        pytest.skip("node not installed")
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
        f.write(_HARNESS)
        harness = f.name
    res = subprocess.run([NODE, harness, str(JS)], capture_output=True,
                         text=True, check=True)
    Path(harness).unlink()
    return json.loads(res.stdout.strip().splitlines()[-1])


def test_render_shows_registries_placements_error_and_numbers(run):
    assert run["expanded"] is True
    h = run["html"]
    assert "Excalibur" in h and "Zhukov &#9733;" in h
    assert "top" in h and "no mask" in h
    assert "we&#39;ird&quot;&amp;" in h, "names are HTML-escaped"
    assert "Name refused: nope" in h
    assert "Width" in h and "1.500" in h and "10.000&deg;" in h


def test_the_add_picker_offers_the_suggested_names(run):
    assert "bottom" in run["picker"] and "port" in run["picker"]


def test_delete_asks_before_it_fires(run):
    assert "Delete &ldquo;top&rdquo;?" in run["confirm"]


def test_the_handlers_fire_the_panel_actions(run):
    assert run["events"] == [
        "ship-property-viewer/decal-registry:Excalibur",
        "ship-property-viewer/decal-select:we'ird\"&",
        "ship-property-viewer/decal-add:bottom",
        "ship-property-viewer/decal-reposition",
        "ship-property-viewer/decal-delete:top",
        'ship-property-viewer/decal-nudge:{"field":"width","delta":0.075}',
        "ship-property-viewer/decal-add-cancel",
        "ship-property-viewer/decal-default:Excalibur",
    ]


def test_leaving_collapses_and_empties_the_pane(run):
    assert run["collapsed"] is True
