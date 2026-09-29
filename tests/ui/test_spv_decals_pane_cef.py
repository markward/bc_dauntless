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
  placements: [{name: "top", has_mask: true}, {name: NAME, has_mask: false},
               {name: "bad", has_mask: false, unreadable: true}],
  selected: "top", adding: false, adding_name: null, reposition: false,
  error: "Name refused: nope", hint: "Not shown in game — no registry",
  can_add: true, suggested_names: ["bottom", "port"],
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
out.no_sidebar_nudge = typeof shipPropertyViewerDecalNudge === "undefined";
shipPropertyViewerDecalAddCancel();
shipPropertyViewerDecalDefault(el({name: "Excalibur"}));
shipPropertyViewerDecalDeleteAsk(el({name: "bad"}));
out.confirm_bad = els["spv-decals-body"].innerHTML;
shipPropertyViewerDecalDeleteYes(el({name: "bad"}));
shipPropertyViewerDecalClearDefault();
out.events = events;
renderSPVDecals(Object.assign({}, base, {default_registry: null, hint: null}));
out.no_default = els["spv-decals-body"].innerHTML;
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


def test_render_shows_registries_placements_and_error(run):
    assert run["expanded"] is True
    h = run["html"]
    assert "Excalibur" in h and "Zhukov &#9733;" in h
    assert "top" in h and "no mask" in h
    assert "we&#39;ird&quot;&amp;" in h, "names are HTML-escaped"
    assert "Name refused: nope" in h


def test_the_sidebar_has_no_numbers_block(run):
    """Mark, live: the placement numbers live in the top-right tool panels
    (renderSPVToolPanels), never in the sidebar pane."""
    h = run["html"]
    assert "Selected:" not in h and "Width" not in h and "spv-step" not in h
    assert run["no_sidebar_nudge"] is True


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
        "ship-property-viewer/decal-add-cancel",
        "ship-property-viewer/decal-default:Excalibur",
        "ship-property-viewer/decal-delete:bad",
        "ship-property-viewer/decal-default:",
    ]


def _row(html, name):
    """The one placement row whose data-name is `name`."""
    import re
    rows = re.findall(r'<div class="spv-sys-row[^"]*"[^>]*>.*?</div>', html)
    return [r for r in rows if 'data-name="%s"' % name in r]


def test_an_unreadable_placement_is_listed_but_not_selectable(run):
    [bad] = _row(run["html"], "bad")
    assert "(unreadable)" in bad
    assert "shipPropertyViewerDecalSelect" not in bad
    [top] = _row(run["html"], "top")
    assert "shipPropertyViewerDecalSelect" in top


def test_an_unreadable_placement_can_be_deleted_with_a_confirm(run):
    assert ('shipPropertyViewerDecalDeleteAsk' in run["html"]
            and 'data-name="bad"' in run["html"])
    assert "Delete &ldquo;bad&rdquo;?" in run["confirm_bad"]


def test_the_not_in_game_hint_is_shown(run):
    assert "Not shown in game" in run["html"]
    assert "Not shown in game" not in run["no_default"]


def test_clear_default_is_offered_only_when_a_default_is_set(run):
    assert "shipPropertyViewerDecalClearDefault" in run["html"]
    assert "shipPropertyViewerDecalClearDefault" not in run["no_default"]


def test_leaving_collapses_and_empties_the_pane(run):
    assert run["collapsed"] is True


# ── the top-right tool panels a selected decal drives ─────────────────────
# renderSPVToolPanels (called by setShipPropertyViewer) builds the Position /
# Scale / Rotate panels from transform_coords / scale_values / rotate_values.

_PANEL_IDS = ["spv-coords", "spv-coord-rows", "spv-coord-actions", "spv-coord-paste",
              "spv-scale", "spv-scale-rows", "spv-scale-actions", "spv-scale-paste",
              "spv-rotate", "spv-rotate-rows", "spv-rotate-actions", "spv-rotate-paste"]

_PANEL_HARNESS = r"""
const fs = require("fs");
global.window = global;
function makeEl() {
  const classes = new Set();
  return {innerHTML: "", style: {}, textContent: "", disabled: false,
          classList: {toggle: function (c, v) { if (v) classes.add(c); else classes.delete(c); },
                      contains: function (c) { return classes.has(c); }}};
}
const IDS = %s;
let els = {};
function reset() { els = {}; IDS.forEach(function (i) { els[i] = makeEl(); }); }
global.document = {getElementById: function (id) { return els[id] || null; },
                   addEventListener: function () {}};
global.dauntlessEvent = function () {};
eval(fs.readFileSync(process.argv[2], "utf8"));
function snap() {
  const o = {};
  IDS.forEach(function (i) { o[i] = {html: els[i].innerHTML, display: els[i].style.display,
                                     disabled: els[i].disabled}; });
  return o;
}
const cases = {
  decal_move: {transform_coords: {x: 1, y: 2, z: 3, has_clipboard: false, can_paste: false,
                                  decal: true, step_scale: 100}},
  mount_move: {transform_coords: {x: 1, y: 2, z: 3, has_clipboard: true, can_paste: true}},
  decal_rotate: {rotate_values: {fields: [{label: "Roll", value: 12.5}], has_clipboard: false,
                                 can_paste: false, decal: true}},
  mount_rotate: {rotate_values: {fields: [{label: "X", value: 1}, {label: "Y", value: 2},
                                          {label: "Z", value: 3}],
                                 has_clipboard: false, can_paste: false}},
  decal_scale: {scale_values: {kind: "decal", fields: [
                  {label: "Width", value: 119.5, step_scale: 100},
                  {label: "Depth", value: 2, step_scale: 10}],
                  has_clipboard: false, can_paste: false, decal: true}},
  mount_scale: {scale_values: {kind: "radius", fields: [{label: "Radius", value: 0.5}],
                               has_clipboard: false, can_paste: false}},
  none: {},
};
const out = {};
Object.keys(cases).forEach(function (k) { reset(); renderSPVToolPanels(cases[k]); out[k] = snap(); });
console.log(JSON.stringify(out));
""" % json.dumps(_PANEL_IDS)


@pytest.fixture(scope="module")
def panels():
    if NODE is None:
        pytest.skip("node not installed")
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
        f.write(_PANEL_HARNESS)
        harness = f.name
    res = subprocess.run([NODE, harness, str(JS)], capture_output=True,
                         text=True, check=True)
    Path(harness).unlink()
    return json.loads(res.stdout.strip().splitlines()[-1])


def test_the_panel_markup_has_rows_and_action_hosts():
    html = HTML.read_text(encoding="utf-8")
    for i in _PANEL_IDS:
        assert 'id="%s"' % i in html, i


def test_a_decal_move_panel_steps_in_gu_and_hides_copy_paste_mirror(panels):
    c = panels["decal_move"]
    assert c["spv-coords"]["display"] == "block"
    rows = c["spv-coord-rows"]["html"]
    assert "3.000" in rows
    # 0.01 / 0.1 GU = 1 / 10 NIF units, labelled as such.
    assert "shipPropertyViewerCoordNudge(2,10)" in rows
    assert "shipPropertyViewerCoordNudge(0,-1)" in rows
    assert "+10<" in rows and "&minus;1<" in rows
    assert c["spv-coord-actions"]["display"] == "none"


def test_a_mount_move_panel_is_unchanged(panels):
    c = panels["mount_move"]
    rows = c["spv-coord-rows"]["html"]
    for ax in ("X", "Y", "Z"):
        assert ">%s<" % ax in rows
    assert "shipPropertyViewerCoordNudge(0,0.1)" in rows
    assert "shipPropertyViewerCoordNudge(2,-0.01)" in rows
    assert "+0.1<" in rows and "&minus;0.01<" in rows
    assert c["spv-coord-actions"]["display"] == ""
    assert c["spv-coord-paste"]["disabled"] is False       # can_paste: true
    assert panels["decal_move"]["spv-coord-paste"]["disabled"] is True


def test_a_decal_rotate_panel_has_only_roll(panels):
    c = panels["decal_rotate"]
    assert c["spv-rotate"]["display"] == "block"
    rows = c["spv-rotate-rows"]["html"]
    assert ">Roll<" in rows and "12.5&deg;" in rows
    assert "shipPropertyViewerRotateNudge(0,5)" in rows
    assert "shipPropertyViewerRotateNudge(1," not in rows
    assert c["spv-rotate-actions"]["display"] == "none"


def test_a_mount_rotate_panel_keeps_three_rows(panels):
    rows = panels["mount_rotate"]["spv-rotate-rows"]["html"]
    assert "shipPropertyViewerRotateNudge(2,-1)" in rows
    assert "+5&deg;<" in rows
    assert panels["mount_rotate"]["spv-rotate-actions"]["display"] == ""


def test_a_decal_scale_panel_has_width_and_depth_steppers(panels):
    c = panels["decal_scale"]
    rows = c["spv-scale-rows"]["html"]
    assert ">Width<" in rows and ">Depth<" in rows and "119.500" in rows
    assert "shipPropertyViewerScaleNudge(0,10)" in rows
    assert "shipPropertyViewerScaleNudge(1,0.1)" in rows
    assert "shipPropertyViewerScaleNudge(1,-1)" in rows
    assert c["spv-scale-actions"]["display"] == "none"


def test_a_mount_scale_panel_is_unchanged(panels):
    c = panels["mount_scale"]
    assert "shipPropertyViewerScaleNudge(0,-0.1)" in c["spv-scale-rows"]["html"]
    assert c["spv-scale-actions"]["display"] == ""


def test_no_values_hide_every_panel(panels):
    c = panels["none"]
    assert all(c[i]["display"] == "none"
               for i in ("spv-coords", "spv-scale", "spv-rotate"))
