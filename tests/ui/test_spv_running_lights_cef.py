"""Task 11 (spec 2026-10-22 section 2): the Ship Property Viewer's running
light rows ("Running Lights" group, one row per light, "+ Add"), the Add
modal with its page-drawn Type dropdown, the Running Light form, the
right-click Edit... / Remove menu, the placing hint and the refusal line.
Static checks on HTML/JS/CSS plus a node harness that EXECUTES the renderer
and handlers, following test_spv_physical_tab_cef.py."""
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HTML = ROOT / "native/assets/ui-cef/index.html"
JS_PATH = ROOT / "native/assets/ui-cef/js/ship_property_viewer.js"
WHEEL_PATH = ROOT / "native/assets/ui-cef/js/colour_wheel.js"
CSS = ROOT / "native/assets/ui-cef/css/ship_property_viewer.css"
NODE = shutil.which("node")


def _read(p):
    return Path(p).read_text(encoding="utf-8")


# --- static -------------------------------------------------------------------

def test_add_modal_exists_and_is_hidden():
    html = _read(HTML)
    m = re.search(r'<div id="spv-add"[^>]*>', html)
    assert m
    assert "spv-modal-backdrop" in m.group(0)
    assert "display:none" in m.group(0).replace(" ", "")
    block = html[m.start():html.index("</div>\n      </div>", m.start())]
    for needle in ('id="spv-add-title"', 'id="spv-add-dd"', 'id="spv-add-dd-menu"',
                   'id="spv-add-form"', 'id="spv-add-ok"', "spv-dd__btn",
                   "spv-modal__btn--primary"):
        assert needle in block, needle
    # The dropdown list is the context-menu look, closed by default.
    menu = re.search(r'<div id="spv-add-dd-menu"[^>]*>', html).group(0)
    assert "spv-ctxmenu" in menu and "display:none" in menu.replace(" ", "")


def test_running_light_menu_items_exist_and_are_hidden():
    html = _read(HTML)
    for item, text in (("spv-ctx-rledit", "Edit…"), ("spv-ctx-rlremove", "Remove")):
        m = re.search(r'<div id="%s"[^>]*>([^<]*)</div>' % item, html)
        assert m, item
        assert "display:none" in m.group(0).replace(" ", ""), item
        assert m.group(1) == text
    js = _read(JS_PATH)
    body = js[js.index("function spvShowMenuItems"):js.index("function spvOpenMenuAt")]
    for key in ("spv-ctx-rledit", "spv-ctx-rlremove"):
        assert key in body, key


def test_add_modal_is_closed_by_spv_hide_overlays():
    js = _read(JS_PATH)
    m = re.search(r"function spvHideOverlaysNoEvent\(\) \{\s*\[([^\]]*)\]", js)
    assert m and "'spv-add'" in m.group(1)


def test_add_types_registry():
    js = _read(JS_PATH)
    m = re.search(r"var SPV_ADD_TYPES = \{\s*running_light: \{", js)
    assert m
    block = js[m.start():js.index("};", m.start())]
    for key in ("label: 'Running Light'", "render:", "collect:",
                "submitAction: 'rl/place_begin'"):
        assert key in block, key


def _css_block():
    css = _read(CSS)
    start = css.index("/* ---- Running lights")
    return css, css[start:]


def test_css_new_rules_present():
    _, block = _css_block()
    for sel in (".spv-add-row", ".spv-dd", ".spv-dd__btn"):
        assert sel in block, sel


def test_css_new_rules_use_only_the_existing_palette():
    css, block = _css_block()
    rest = css[:css.index("/* ---- Running lights")]
    colour = re.compile(r"#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)")
    found = colour.findall(block)
    assert found, "expected the new rules to use palette colours"
    for c in found:
        assert c in rest, "new colour outside the existing palette: " + c


# --- node harness ---------------------------------------------------------------

_NODE_HARNESS = r"""
const fs = require("fs");
global.window = global;
function makeEl() {
  const classes = new Set();
  return {
    innerHTML: "", style: {}, textContent: "", value: "", dataset: {},
    disabled: false, checked: false,
    classList: {
      toggle: function (c, v) { if (v) classes.add(c); else classes.delete(c); },
      add: function (c) { classes.add(c); },
      remove: function (c) { classes.delete(c); },
      contains: function (c) { return classes.has(c); },
    },
    contains: function () { return false; },
    addEventListener: function () {},
    focus: function () {}, select: function () {},
    getBoundingClientRect: function () { return {right: 200, top: 50}; },
  };
}
const IDS = ["spv-ctxmenu", "spv-ctxsub", "spv-ctx-radius", "spv-ctx-addlight",
  "spv-ctx-light", "spv-ctx-removelight", "spv-ctx-addemitter",
  "spv-ctx-editemitter", "spv-ctx-removeemitter", "spv-ctx-addanchor",
  "spv-ctx-addstate", "spv-ctx-makebreakable", "spv-ctx-editanchor",
  "spv-ctx-editbreak", "spv-ctx-removenode", "spv-ctx-moveto", "spv-ctx-reset",
  "spv-ctx-moveall", "spv-ctx-resetall", "spv-ctx-rledit", "spv-ctx-rlremove",
  "spv-syslist-body", "spv-radius", "spv-confirm", "spv-light", "spv-emitter",
  "spv-parts", "spv-parts-body", "spv-toast",
  "spv-add", "spv-add-title", "spv-add-dd", "spv-add-dd-label",
  "spv-add-dd-text", "spv-add-dd-menu", "spv-add-form", "spv-add-ok",
  "spv-add-rl-name", "spv-add-rl-wheel", "spv-add-rl-radius",
  "spv-add-rl-period", "spv-add-rl-duration", "spv-add-rl-every",
  "spv-add-rl-onfor", "spv-add-rl-steady", "spv-add-rl-blinking"];
const els = {};
IDS.forEach(function (id) { els[id] = makeEl(); });
global.document = {
  getElementById: function (id) { return els[id] || null; },
  addEventListener: function () {},
};
let events = [];
global.dauntlessEvent = function (s) { events.push(s); };
eval(fs.readFileSync(process.argv[3], "utf8"));   // colour_wheel.js
// A recording stand-in for the canvas wheel (node has no canvas).
const wheels = [];
ColourWheel = function (canvas, hs, onChange) {
  this.canvas = canvas; this.hue = hs.hue; this.sat = hs.sat;
  this.onChange = onChange; wheels.push(this);
};
ColourWheel.prototype.setHs = function (h, s) { this.hue = h; this.sat = s; };
eval(fs.readFileSync(process.argv[2], "utf8"));   // ship_property_viewer.js
function ev() { return {preventDefault: function () {}, stopPropagation: function () {},
                        clientX: 10, clientY: 20}; }
const out = {};
function take(k) { out[k] = events; events = []; }
function shown(id) { return els[id].style.display; }

const NAME = 'Port "Nav" <1>';
const SPEC = {name: NAME, position: [1, 2, 3], color: [0, 1, 0], radius: 2.0,
              period: 4.0, duration: 1.0};
const STEADY = {name: "Keel", position: [0, 0, 0], color: [1, 1, 1], radius: 0.5,
                period: 3.0, duration: 0.0};
const RL = {placing: null, error: null, hint: null, next_name: "Running Light 3",
            defaults: {color: [1, 1, 1], radius: 1.0, period: 3.0, duration: 0.5},
            ranges: {radius: [0.1, 5.0], period: [0.5, 10.0], duration_min: 0.1}};
const ROWS = [
  {index: 0, name: "Hull", targetable: true, condition_pct: 100},
  {kind: "rl_group", name: "Running Lights", expanded: true, children: [
    {kind: "running_light", name: NAME, spec: SPEC, dirty: true, chosen: true},
    {kind: "running_light", name: "Keel", spec: STEADY, dirty: false, chosen: false}]},
  {kind: "rl_add", name: "+ Add"}];

renderSPVRunningLights(RL);
renderSPVSubsystemList(ROWS, null, null, null);
out.rows = els["spv-syslist-body"].innerHTML;
take("renderEvents");

shipPropertyViewerRlGroupToggle();
take("toggleEvents");
shipPropertyViewerRlRow({dataset: {name: NAME}});
take("selectEvents");

// "+ Add" -> the Add modal, nothing chosen yet.
shipPropertyViewerAddOpen();
out.addShown = shown("spv-add");
out.addTitle = els["spv-add-title"].textContent;
out.addForm = els["spv-add-form"].innerHTML;
out.addDdShown = shown("spv-add-dd");
out.addOkShown = shown("spv-add-ok");
out.addMenuShown = shown("spv-add-dd-menu");
take("openEvents");
shipPropertyViewerAddDdToggle();
out.ddMenuShown = shown("spv-add-dd-menu");
out.ddMenu = els["spv-add-dd-menu"].innerHTML;
shipPropertyViewerAddPick({dataset: {type: "running_light"}});
out.pickMenuShown = shown("spv-add-dd-menu");
out.pickTitle = els["spv-add-title"].textContent;
out.pickDdText = els["spv-add-dd-text"].textContent;
out.form = els["spv-add-form"].innerHTML;
out.okText = els["spv-add-ok"].textContent;
out.okShown = shown("spv-add-ok");
out.nameValue = els["spv-add-rl-name"].value;
out.radius0 = els["spv-add-rl-radius"].textContent;
out.period0 = els["spv-add-rl-period"].textContent;
out.duration0 = els["spv-add-rl-duration"].textContent;
out.blinking0 = els["spv-add-rl-blinking"].classList.contains("active");
out.everyShown0 = shown("spv-add-rl-every");
out.wheelCount = wheels.length;
out.wheelCanvas = wheels.length ? wheels[wheels.length - 1].canvas === els["spv-add-rl-wheel"] : false;
take("pickEvents");

// Steady hides both timing rows; Blinking brings them back.
shipPropertyViewerRlBlink(false);
out.steadyEvery = shown("spv-add-rl-every");
out.steadyOnFor = shown("spv-add-rl-onfor");
out.steadyActive = els["spv-add-rl-steady"].classList.contains("active");
shipPropertyViewerRlBlink(true);
out.blinkEvery = shown("spv-add-rl-every");
out.blinkOnFor = shown("spv-add-rl-onfor");

// Steps: size +0.1 twice, period -0.5 five times (clamps at 0.5), on-for
// can never exceed the period.
shipPropertyViewerRlStep("radius", 1); shipPropertyViewerRlStep("radius", 1);
for (let i = 0; i < 8; i++) shipPropertyViewerRlStep("period", -1);
out.periodMin = els["spv-add-rl-period"].textContent;
out.durationClamped = els["spv-add-rl-duration"].textContent;
shipPropertyViewerRlStep("period", 1); shipPropertyViewerRlStep("period", 1);
shipPropertyViewerRlStep("duration", 1);
for (let i = 0; i < 60; i++) shipPropertyViewerRlStep("radius", 1);
out.radiusMax = els["spv-add-rl-radius"].textContent;
for (let i = 0; i < 60; i++) shipPropertyViewerRlStep("radius", -1);
out.radiusMin = els["spv-add-rl-radius"].textContent;
shipPropertyViewerRlStep("radius", 1); shipPropertyViewerRlStep("radius", 1);
// Pure red from the wheel; a typed name.
wheels[wheels.length - 1].onChange({hue: 0, sat: 1}, true);
els["spv-add-rl-name"].value = '  Star "Nav"  ';
shipPropertyViewerAddSubmit();
out.afterSubmitShown = shown("spv-add");
take("placeEvents");

// Steady submits duration 0.
shipPropertyViewerAddOpen();
shipPropertyViewerAddPick({dataset: {type: "running_light"}});
shipPropertyViewerRlBlink(false);
shipPropertyViewerAddSubmit();
take("steadyEvents");

// Cancel closes with overlay:0 and sends nothing else.
shipPropertyViewerAddOpen();
events = [];
shipPropertyViewerAddCancel();
out.cancelShown = shown("spv-add");
take("cancelEvents");

// Right-click a light: only Edit... / Remove.
shipPropertyViewerRlMenu(ev(), {dataset: {name: NAME}});
out.menu = {};
IDS.filter(function (id) { return id.indexOf("spv-ctx-") === 0; }).forEach(function (id) {
  out.menu[id] = shown(id);
});
out.menuShown = shown("spv-ctxmenu");
take("menuEvents");

// Edit... -> the same modal, values from the row's spec.
shipPropertyViewerCtxRlEdit();
out.editShown = shown("spv-add");
out.editTitle = els["spv-add-title"].textContent;
out.editDdShown = shown("spv-add-dd");
out.editOk = els["spv-add-ok"].textContent;
out.editForm = els["spv-add-form"].innerHTML;
out.editRadius = els["spv-add-rl-radius"].textContent;
out.editPeriod = els["spv-add-rl-period"].textContent;
out.editDuration = els["spv-add-rl-duration"].textContent;
out.editWheel = {hue: wheels[wheels.length - 1].hue, sat: wheels[wheels.length - 1].sat};
take("editOpenEvents");
shipPropertyViewerRlStep("radius", 1);
shipPropertyViewerAddSubmit();
take("editEvents");

// Editing a steady light opens with the timing rows hidden.
shipPropertyViewerRlMenu(ev(), {dataset: {name: "Keel"}});
shipPropertyViewerCtxRlEdit();
out.editSteadyEvery = shown("spv-add-rl-every");
out.editSteadyActive = els["spv-add-rl-steady"].classList.contains("active");
shipPropertyViewerAddCancel();
events = [];

// Remove.
shipPropertyViewerRlMenu(ev(), {dataset: {name: NAME}});
events = [];
shipPropertyViewerCtxRlRemove();
take("removeEvents");

// The placing hint shows in the toast; an error renders under "+ Add".
renderSPVRunningLights({placing: "Running Light 3",
                        hint: "Click the hull to place Running Light 3 · Esc cancels",
                        error: "A light named 'x' <already> exists", next_name: "x"});
renderSPVModelParts({});
out.hintShown = shown("spv-toast");
out.hintText = els["spv-toast"].textContent;
renderSPVSubsystemList(ROWS, null, null, null);
out.errorRows = els["spv-syslist-body"].innerHTML;
renderSPVModelParts({toast: "Add an anchor first"});
out.partToast = els["spv-toast"].textContent;
renderSPVRunningLights(RL);
renderSPVModelParts({});
out.noHintShown = shown("spv-toast");
renderSPVSubsystemList(ROWS, null, null, null);
out.noErrorRows = els["spv-syslist-body"].innerHTML;
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def harness():
    if NODE is None:
        pytest.skip("node not found on PATH")
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
        f.write(_NODE_HARNESS)
        path = f.name
    try:
        r = subprocess.run([NODE, path, str(JS_PATH), str(WHEEL_PATH)],
                           capture_output=True, text=True, timeout=10)
    finally:
        Path(path).unlink()
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _row_divs(html):
    return re.findall(r'<div class="spv-sys-row[^"]*"[^>]*>.*?</div>', html, re.S)


def _prefix(event, verb):
    assert event.startswith("ship-property-viewer/" + verb + ":"), event
    return json.loads(event[len("ship-property-viewer/" + verb + ":"):])


def test_rows_render_group_lights_and_add_last(harness):
    rows = _row_divs(harness["rows"])
    assert len(rows) == 5
    hull, group, light, keel, add = rows
    assert "Running Lights" in group and "&#9662;" in group
    assert "spv-sys-row__bar" not in group
    assert "spv-sys-row__eye--shut" in group
    for r in (light, keel):
        assert "spv-sys-row--child" in r
        assert "spv-sys-row__eye--shut" in r
        assert "spv-sys-row__bar" not in r
    assert "spv-sys-row--chosen" in light and "spv-sys-row--dirty" in light
    assert "spv-sys-row--chosen" not in keel and "spv-sys-row--dirty" not in keel
    assert "spv-add-row" in add and "+ Add" in add
    assert "spv-sys-row__eye" not in add


def test_light_names_travel_in_data_attributes(harness):
    light = _row_divs(harness["rows"])[2]
    assert 'data-name="Port &quot;Nav&quot; &lt;1&gt;"' in light
    assert "Port &quot;Nav&quot; &lt;1&gt;" in light
    assert 'Port "Nav"' not in light
    # every on* handler is a bare call on `this` / `event`
    for handler in re.findall(r'on\w+="([^"]*)"', harness["rows"]):
        assert "Nav" not in handler and "Keel" not in handler


def test_rows_never_fire_select_pin(harness):
    for r in _row_divs(harness["rows"])[1:]:
        assert "shipPropertyViewerRow(" not in r
        assert "undefined" not in r
    assert harness["renderEvents"] == []


def test_group_toggle_and_light_select(harness):
    assert harness["toggleEvents"] == ["ship-property-viewer/rl/toggle_group"]
    assert harness["selectEvents"] == [
        'ship-property-viewer/rl/select:{"name":"Port \\"Nav\\" <1>"}']


def test_add_row_opens_the_modal(harness):
    assert harness["addShown"] == "flex"
    assert harness["addTitle"] == "Add"
    assert harness["addForm"] == ""
    assert harness["addDdShown"] != "none"
    assert harness["addOkShown"] == "none"
    assert harness["addMenuShown"] == "none"
    assert harness["openEvents"] == ["ship-property-viewer/overlay:1"]
    assert harness["ddMenuShown"] == "block"
    assert 'data-type="running_light"' in harness["ddMenu"]
    assert "Running Light" in harness["ddMenu"]
    assert "spv-ctxmenu__item" in harness["ddMenu"]


def test_choosing_running_light_renders_the_form(harness):
    assert harness["pickMenuShown"] == "none"
    assert harness["pickTitle"] == "Add Running Light"
    assert harness["pickDdText"] == "Running Light"
    form = harness["form"]
    order = [form.index(n) for n in (
        'id="spv-add-rl-name"', 'id="spv-add-rl-wheel"', "Size",
        "Steady", "Blinking", "Every", "On for")]
    assert order == sorted(order)
    assert re.search(r'<input[^>]*class="spv-modal__input"[^>]*id="spv-add-rl-name"', form) \
        or re.search(r'<input[^>]*id="spv-add-rl-name"[^>]*class="spv-modal__input"', form)
    assert re.search(r'<canvas id="spv-add-rl-wheel" width="140" height="140"', form)
    assert "spv-wheel-row" in form and "spv-stepper" in form
    assert "spv-step-btn" in form and "spv-shape-btn" in form
    assert harness["okText"] == "Place on hull"
    assert harness["okShown"] != "none"
    assert harness["nameValue"] == "Running Light 3"
    assert harness["radius0"] == "1.00"
    assert harness["period0"] == "3.0 s"
    assert harness["duration0"] == "0.5 s"
    assert harness["blinking0"] is True
    assert harness["everyShown0"] != "none"
    assert harness["wheelCount"] >= 1 and harness["wheelCanvas"] is True
    assert harness["pickEvents"] == []


def test_steady_hides_the_timing_rows(harness):
    assert harness["steadyEvery"] == "none" and harness["steadyOnFor"] == "none"
    assert harness["steadyActive"] is True
    assert harness["blinkEvery"] != "none" and harness["blinkOnFor"] != "none"


def test_steppers_clamp_to_the_payload_ranges(harness):
    assert harness["periodMin"] == "0.5 s"
    assert harness["durationClamped"] == "0.5 s"
    assert harness["radiusMax"] == "5.00"
    assert harness["radiusMin"] == "0.10"


def test_place_on_hull_dispatches_the_spec(harness):
    ev = harness["placeEvents"]
    assert ev[-1] == "ship-property-viewer/overlay:0"
    assert len(ev) == 2
    spec = _prefix(ev[0], "rl/place_begin")
    assert spec["name"] == 'Star "Nav"'
    assert spec["color"] == [1, 0, 0]
    assert spec["radius"] == pytest.approx(0.3)
    assert spec["period"] == pytest.approx(1.5)
    assert spec["duration"] == pytest.approx(0.6)
    assert "position" not in spec
    assert harness["afterSubmitShown"] == "none"


def test_steady_submits_duration_zero(harness):
    ev = harness["steadyEvents"]
    assert ev[0] == "ship-property-viewer/overlay:1"
    assert ev[-1] == "ship-property-viewer/overlay:0" and len(ev) == 3
    spec = _prefix(ev[1], "rl/place_begin")
    assert spec["duration"] == 0
    assert spec["period"] == pytest.approx(3.0)
    assert spec["radius"] == pytest.approx(1.0)
    assert spec["color"] == [1, 1, 1]


def test_cancel_closes_with_overlay_zero(harness):
    assert harness["cancelShown"] == "none"
    assert harness["cancelEvents"] == ["ship-property-viewer/overlay:0"]


def test_right_click_menu_shows_only_edit_and_remove(harness):
    menu = harness["menu"]
    for item, display in menu.items():
        want = "block" if item in ("spv-ctx-rledit", "spv-ctx-rlremove") else "none"
        assert display == want, item
    assert harness["menuShown"] == "block"
    assert harness["menuEvents"] == ["ship-property-viewer/overlay:1"]


def test_edit_reopens_the_form_with_the_lights_values(harness):
    assert harness["editShown"] == "flex"
    assert harness["editTitle"] == "Edit Running Light"
    assert harness["editDdShown"] == "none"
    assert harness["editOk"] == "Apply"
    form = harness["editForm"]
    assert 'id="spv-add-rl-name"' not in form          # read-only: no input
    assert "Port &quot;Nav&quot; &lt;1&gt;" in form
    assert harness["editRadius"] == "2.00"
    assert harness["editPeriod"] == "4.0 s"
    assert harness["editDuration"] == "1.0 s"
    assert harness["editWheel"]["hue"] == pytest.approx(120)
    assert harness["editWheel"]["sat"] == pytest.approx(1)
    assert harness["editOpenEvents"] == []
    assert harness["editSteadyEvery"] == "none"
    assert harness["editSteadyActive"] is True


def test_edit_dispatches_with_the_name_unchanged(harness):
    ev = harness["editEvents"]
    assert ev[-1] == "ship-property-viewer/overlay:0" and len(ev) == 2
    arg = _prefix(ev[0], "rl/edit")
    assert arg["name"] == 'Port "Nav" <1>'
    spec = arg["spec"]
    assert spec["radius"] == pytest.approx(2.1)
    assert spec["period"] == pytest.approx(4.0)
    assert spec["duration"] == pytest.approx(1.0)
    assert spec["color"] == pytest.approx([0, 1, 0])
    # validate_spec needs a position: an edit keeps the light's own.
    assert spec["position"] == [1, 2, 3]


def test_remove_dispatches(harness):
    assert harness["removeEvents"] == [
        'ship-property-viewer/rl/remove:{"name":"Port \\"Nav\\" <1>"}',
        "ship-property-viewer/overlay:0"]


def test_placing_hint_and_error(harness):
    assert harness["hintShown"] == "block"
    assert harness["hintText"] == "Click the hull to place Running Light 3 · Esc cancels"
    rows = harness["errorRows"]
    m = re.search(r'<div class="spv-decal-error">([^<]*)</div>', rows)
    assert m and m.group(1) == "A light named &#39;x&#39; &lt;already&gt; exists"
    assert rows.index("spv-add-row") < m.start()
    assert harness["partToast"] == "Add an anchor first"   # a part toast wins
    assert harness["noHintShown"] == "none"
    assert "spv-decal-error" not in harness["noErrorRows"]
