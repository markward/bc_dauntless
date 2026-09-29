"""Task 7 (spec 2026-09-25 section 7): the Model Parts pane renders as a node
tree in CEF -- rows for the part and its Anchor / {State} Transformation /
Breakage children, right-click menus to add/remove them, popups (Add/Edit Anchor, Make
Breakable/Edit Breakage, the Add State Transformation picker) for their
attributes -- the rows themselves carry names only -- and a toast banner. Static text assertions on the
JS/HTML/CSS, following the style of test_ship_property_viewer_action_row.py,
plus (fix round 1, escaping) a node-harness test that actually EXECUTES
renderSPVModelParts and the row handlers, following
test_subtitle_styling.py's `_NODE_HARNESS` pattern.
"""
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import html as html_stdlib

import pytest

ROOT = Path(__file__).resolve().parents[2]
HTML = "native/assets/ui-cef/index.html"
JS = "native/assets/ui-cef/js/ship_property_viewer.js"
CSS = "native/assets/ui-cef/css/ship_property_viewer.css"
JS_PATH = ROOT / JS

NODE = shutil.which("node")


def _read(path):
    return open(path, encoding="utf-8").read()


# --- Task 6's old per-part controls must be GONE -----------------------------

def test_removed_handlers_are_gone():
    js = _read(JS)
    for fn in ("shipPropertyViewerPartAngle", "shipPropertyViewerPartPreview",
               "shipPropertyViewerPartDetach"):
        assert fn not in js, fn


def test_spv_part_controls_html_helper_is_gone():
    js = _read(JS)
    assert "spvPartControlsHtml" not in js


# --- part/* actions the tree must dispatch -----------------------------------

def test_js_dispatches_every_part_action():
    js = _read(JS)
    for action in ("part/select_node:", "part/add_anchor:", "part/add_state:",
                   "part/make_breakable:", "part/remove:",
                   "part/set_transition:", "part/set_break:",
                   "part/begin_add_state:", "part/cancel_add_state"):
        assert action in js, action


def test_model_parts_select_still_used_for_the_part_row():
    js = _read(JS)
    assert "model_parts/select:" in js


# --- toast element -----------------------------------------------------------

def test_toast_element_exists_in_index():
    index = _read(HTML)
    assert 'id="spv-toast"' in index


def test_toast_is_rendered_from_the_payload():
    js = _read(JS)
    # model_parts.toast is the only place the toast lives (per Task 6) --
    # assert the JS reads that key, not some other invented field.
    assert "spv-toast" in js
    assert ".toast" in js


# --- context menu items -------------------------------------------------------

def test_menu_labels_present():
    index = _read(HTML)
    js = _read(JS)
    combined = index + js
    for label in ("Add Anchor…", "Add State Transformation…", "Make Breakable…",
                  "Edit Anchor…", "Edit Breakage…"):
        assert label in combined, label


_DIV_TAG_RE = re.compile(r"<(/?)div\b[^>]*>")


def _element_block(html, elem_id):
    """The real `<div id="elem_id" ...> ... </div>` block, found by counting
    nested <div>/</div> tags from the element's own opening tag rather than a
    hardcoded character window (which would silently stop covering the menu
    the moment it grew past that window, or falsely include markup from
    whatever comes after it)."""
    id_at = html.index('id="%s"' % elem_id)
    open_start = html.rindex("<div", 0, id_at + 1)
    depth = 0
    for m in _DIV_TAG_RE.finditer(html, open_start):
        depth += 1 if not m.group(1) else -1
        if depth == 0:
            return html[open_start:m.end()]
    raise AssertionError("no closing </div> for #%s" % elem_id)


def test_new_menu_items_live_inside_the_one_ctxmenu_element():
    """Resolved-in-advance: reuse #spv-ctxmenu, not a second menu element."""
    section = _element_block(_read(HTML), "spv-ctxmenu")
    assert "spv-ctx-addanchor" in section
    assert "spv-ctx-addstate" in section
    assert "spv-ctx-makebreakable" in section
    assert "spv-ctx-removenode" in section
    assert "spv-ctx-editanchor" in section
    assert "spv-ctx-editbreak" in section
    # Edit sits ABOVE Remove on a child row's menu.
    assert section.index("spv-ctx-editanchor") < section.index("spv-ctx-removenode")
    assert section.index("spv-ctx-editbreak") < section.index("spv-ctx-removenode")


def test_part_menu_has_one_add_state_entry_and_no_per_state_items():
    """ONE "Add State Transformation…" entry that opens the Python-driven
    picker -- the old label + indented per-state items are gone."""
    section = _element_block(_read(HTML), "spv-ctxmenu")
    js = _read(JS)
    assert section.count("Add State Transformation") == 1
    assert 'id="spv-ctx-addstate"' in section
    assert "spv-ctx-addstate-items" not in section
    assert "spv-ctx-addstate-group" not in section
    for label in ("Cruising", "Yellow Alert", "Red Alert", "Warp"):
        assert label not in section, label
    assert "spvRenderAddStateItems" not in js
    assert "spv-ctxmenu__item--sub" not in js
    assert "shipPropertyViewerCtxAddState(" not in js


def test_remove_menu_item_present_for_child_rows():
    index = _read(HTML)
    assert ">Remove<" in index


# --- popups: steppers, not keyboard input ---------------------------------
#
# This engine has no keyboard->CEF forwarding (every sibling SPV numeric
# control -- radius, light shape/extent, emitter intensity -- is a mouse
# stepper for that reason), so the part popups are steppers too.

_POPUPS = ("spv-part-anchor", "spv-part-break", "spv-part-addstate")


def test_popups_exist_as_modals():
    index = _read(HTML)
    for pid in _POPUPS:
        block = _element_block(index, pid)
        assert 'class="spv-modal-backdrop"' in block, pid
        assert 'class="spv-modal"' in block, pid
        assert "spv-modal__title" in block, pid
        assert 'type="number"' not in block, pid
        assert "<input" not in block, pid
    anchor = _element_block(index, "spv-part-anchor")
    assert "Transition time" in anchor
    brk = _element_block(index, "spv-part-break")
    assert "Breaks off after taking" in brk
    assert "of the ship&#39;s hull strength" in brk or \
        "of the ship's hull strength" in brk
    assert "Add State Transformation" in _element_block(index, "spv-part-addstate")


def test_every_popup_is_hidden_by_spv_hide_overlays():
    js = _read(JS)
    m = re.search(r"function spvHideOverlaysNoEvent\(\) \{\s*\[([^\]]*)\]", js)
    assert m, "spvHideOverlaysNoEvent's id list"
    ids = re.findall(r"'([^']+)'", m.group(1))
    for pid in _POPUPS:
        assert pid in ids, pid


# --- row idiom reuse ----------------------------------------------------------

def test_rows_reuse_the_subsystem_tree_classes():
    js = _read(JS)
    assert "spv-sys-row" in js
    assert "spv-sys-row--child" in js
    assert "spv-sys-row--chosen" in js
    assert "spv-sys-row--dirty" in js


def test_rows_use_the_shared_indent_formula():
    js = _read(JS)
    assert "10 + " in js and "* 14" in js


# --- stylesheet has the new rules --------------------------------------------

def test_css_defines_toast_and_drops_the_inline_field_rules():
    css = _read(CSS)
    js = _read(JS)
    assert "#spv-toast" in css
    assert "spv-part-inline-field" not in css
    assert "spv-part-inline-field" not in js
    assert "spv-part-choice" in css, "the picker's selectable state rows"


# --- fix round 1, ruling 1: no part name interpolated into a JS literal -----
#
# `spvEscAttr` (which HTML-escaped a name and then dropped it into a
# single-quoted JS string INSIDE an on* attribute) is gone. The browser
# HTML-decodes an attribute value before the on* text is compiled into a
# handler, so an entity like `&#39;` decodes back to a raw `'` there and
# terminates the JS string early -- a part literally named e.g.
# "Nacelle's Strut" would produce a syntax error and the handler would
# never fire, for every row/menu/stepper this task added plus the
# pre-existing model_parts/select action. The fix: every handler call in an
# on* attribute is now a bare `handlerName(this)` / `(event, this)`, and the
# name/kind travel only as ordinary (once-escaped) data-* attribute values,
# read back via `.dataset`.

def test_esc_attr_helper_is_gone():
    js = _read(JS)
    assert "spvEscAttr" not in js


def test_row_handlers_take_the_element_not_an_interpolated_string():
    """Every row/menu on* attribute calls its handler with a bare element
    reference -- never with a name baked into the attribute text."""
    js = _read(JS)
    for call in ("shipPropertyViewerPartRowClick(this)",
                 "shipPropertyViewerPartRowMenu(event, this)",
                 "shipPropertyViewerPartNodeRowClick(this)",
                 "shipPropertyViewerPartChildMenu(event, this)"):
        assert call in js, call


def test_handlers_read_identity_from_dataset():
    js = _read(JS)
    assert ".dataset.partName" in js
    assert ".dataset.nodeKind" in js
    assert ".dataset.hasAnchor" in js
    assert ".dataset.missingStates" in js
    assert ".dataset.breakable" in js
    assert ".dataset.value" in js  # the Edit popups' pre-fill
    assert ".dataset.state" in js  # the picker's chosen state


_NODE_HARNESS = r"""
const fs = require("fs");
global.window = global;

function makeEl() {
  const classes = new Set();
  return {
    innerHTML: "", style: {}, textContent: "", checked: false, disabled: false,
    classList: {
      toggle: function (c, v) { if (v) classes.add(c); else classes.delete(c); },
      contains: function (c) { return classes.has(c); },
    },
    contains: function () { return false; },
    addEventListener: function () {},
  };
}

const IDS = [
  "spv-parts", "spv-parts-body", "spv-parts-showall-cb", "spv-toast",
  "spv-ctxmenu", "spv-ctx-radius", "spv-ctx-addlight", "spv-ctx-light",
  "spv-ctx-removelight", "spv-ctx-addemitter", "spv-ctx-editemitter",
  "spv-ctx-removeemitter", "spv-ctx-addanchor", "spv-ctx-addstate",
  "spv-ctx-makebreakable", "spv-ctx-editanchor", "spv-ctx-editbreak",
  "spv-ctx-removenode", "spv-radius", "spv-light", "spv-emitter",
  "spv-confirm",
  "spv-part-anchor", "spv-part-anchor-title", "spv-part-anchor-value",
  "spv-part-anchor-ok",
  "spv-part-break", "spv-part-break-title", "spv-part-break-value",
  "spv-part-break-ok",
  "spv-part-addstate", "spv-part-addstate-list", "spv-part-addstate-add",
];
const els = {};
IDS.forEach(function (id) { els[id] = makeEl(); });
global.document = {
  getElementById: function (id) { return els[id] || null; },
  addEventListener: function () {},
};
let events = [];
global.dauntlessEvent = function (s) { events.push(s); };

eval(fs.readFileSync(process.argv[2], "utf8"));

const out = {};
function take(key) { out[key] = events; events = []; }
function shown(id) { return els[id].style.display; }
function ev() { return {preventDefault: function () {}, stopPropagation: function () {},
                        clientX: 10, clientY: 20}; }

// A name with all three characters the original bug mishandled: a single
// quote (breaks a '...' JS string on decode), a double quote (would break a
// "..." attribute), and an ampersand (must not be double-escaped).
const NAME = "Nacelle's \"Strut\" & Co";

function render(rows, picker) {
  renderSPVModelParts({
    expanded: true, show_all: false, selected_box: null, toast: null,
    add_state_picker: picker || null, rows: rows,
  });
  return els["spv-parts-body"].innerHTML;
}

out.partRowHtml = render([{
  kind: "part", name: NAME, depth: 0, chosen: false, dirty: true,
  has_anchor: false, missing_states: ["cruise", "warp"], breakable: false,
}]);
// A CHOSEN Anchor and a CHOSEN Breakage: the rows that used to grow inline
// fields.
out.childRowsHtml = render([
  {kind: "part", name: NAME, depth: 0, chosen: false, dirty: true,
   has_anchor: true, missing_states: ["red"], breakable: true},
  {kind: "anchor", part: NAME, label: "Anchor", depth: 1, chosen: true, value: 3.5},
  {kind: "state", part: NAME, state: "warp", label: "Warp Transformation",
   depth: 1, chosen: false},
  {kind: "breakage", part: NAME, label: "Breakage", depth: 1, chosen: true,
   value: 35},
]);

// Simulate real clicks: a bare object carrying `dataset`, exactly what a
// real on*="handler(this)" call hands the handler once the browser has
// already HTML-decoded the attribute -- no JS re-parse in between, so a
// quote in NAME cannot corrupt it.
shipPropertyViewerPartRowClick({dataset: {partName: NAME}});
shipPropertyViewerPartNodeRowClick({dataset: {partName: NAME, nodeKind: "anchor"}});
take("clickEvents");

function menuState() {
  const m = {};
  ["addanchor", "addstate", "makebreakable", "editanchor", "editbreak",
   "removenode"].forEach(function (k) { m[k] = shown("spv-ctx-" + k); });
  return m;
}
const partEl = {dataset: {partName: NAME, hasAnchor: "false",
                          missingStates: "cruise,warp", breakable: "false"}};
const fullEl = {dataset: {partName: NAME, hasAnchor: "true",
                          missingStates: "", breakable: "true"}};
shipPropertyViewerPartRowMenu(ev(), partEl); out.menuPart = menuState();
shipPropertyViewerPartRowMenu(ev(), fullEl); out.menuFull = menuState();
shipPropertyViewerPartChildMenu(ev(), {dataset: {partName: NAME, nodeKind: "anchor", value: "3.5"}});
out.menuAnchor = menuState();
shipPropertyViewerPartChildMenu(ev(), {dataset: {partName: NAME, nodeKind: "warp"}});
out.menuState = menuState();
shipPropertyViewerPartChildMenu(ev(), {dataset: {partName: NAME, nodeKind: "breakage", value: "35"}});
out.menuBreak = menuState();
take("menuEvents");

// Add Anchor… : default 2.00, +0.25 twice, Add.
shipPropertyViewerPartRowMenu(ev(), partEl);
take("addAnchorMenuEvents");
shipPropertyViewerCtxAddAnchor();
out.addAnchor = {title: els["spv-part-anchor-title"].textContent,
                 ok: els["spv-part-anchor-ok"].textContent,
                 value: els["spv-part-anchor-value"].textContent,
                 shown: shown("spv-part-anchor"), menu: shown("spv-ctxmenu")};
take("addAnchorOpenEvents");
shipPropertyViewerPartAnchorStep(0.25); shipPropertyViewerPartAnchorStep(0.25);
shipPropertyViewerPartAnchorApply();
out.addAnchorClosed = shown("spv-part-anchor");
take("addAnchorEvents");
// The floor: never below 0.25 s.
shipPropertyViewerCtxAddAnchor();
for (let k = 0; k < 20; k++) shipPropertyViewerPartAnchorStep(-0.25);
out.anchorFloor = els["spv-part-anchor-value"].textContent;
shipPropertyViewerPartAnchorCancel();
take("anchorCancelEvents");

// Edit Anchor… : pre-filled from the row's data-value, Apply.
shipPropertyViewerPartChildMenu(ev(), {dataset: {partName: NAME, nodeKind: "anchor", value: "3.5"}});
shipPropertyViewerCtxEditAnchor();
out.editAnchor = {title: els["spv-part-anchor-title"].textContent,
                  ok: els["spv-part-anchor-ok"].textContent,
                  value: els["spv-part-anchor-value"].textContent};
shipPropertyViewerPartAnchorStep(-0.25);
shipPropertyViewerPartAnchorApply();
take("editAnchorEvents");

// Make Breakable… : default 20, +5, Add; clamps 5..100.
shipPropertyViewerPartRowMenu(ev(), partEl);
shipPropertyViewerCtxMakeBreakable();
out.makeBreak = {title: els["spv-part-break-title"].textContent,
                 ok: els["spv-part-break-ok"].textContent,
                 value: els["spv-part-break-value"].textContent,
                 shown: shown("spv-part-break")};
shipPropertyViewerPartBreakStep(5);
shipPropertyViewerPartBreakApply();
take("makeBreakEvents");
shipPropertyViewerCtxMakeBreakable();
for (let k = 0; k < 30; k++) shipPropertyViewerPartBreakStep(5);
out.breakCeil = els["spv-part-break-value"].textContent;
for (let k = 0; k < 30; k++) shipPropertyViewerPartBreakStep(-5);
out.breakFloor = els["spv-part-break-value"].textContent;
shipPropertyViewerPartBreakCancel();
take("breakCancelEvents");

// Edit Breakage… : pre-filled, Apply.
shipPropertyViewerPartChildMenu(ev(), {dataset: {partName: NAME, nodeKind: "breakage", value: "35"}});
shipPropertyViewerCtxEditBreak();
out.editBreak = {title: els["spv-part-break-title"].textContent,
                 ok: els["spv-part-break-ok"].textContent,
                 value: els["spv-part-break-value"].textContent};
shipPropertyViewerPartBreakApply();
take("editBreakEvents");

// Add State Transformation… : the menu entry only ASKS Python.
shipPropertyViewerPartRowMenu(ev(), partEl);
take("beginMenuEvents");
shipPropertyViewerCtxAddStateBegin();
out.beginShown = shown("spv-part-addstate");
take("beginEvents");

// Python answers with the picker in the payload.
render([], {name: NAME, states: ["cruise", "warp"]});
out.picker = {shown: shown("spv-part-addstate"),
              list: els["spv-part-addstate-list"].innerHTML,
              addDisabled: els["spv-part-addstate-add"].disabled};
shipPropertyViewerAddStateAdd();          // nothing chosen: no-op
take("pickerNoChoiceEvents");
shipPropertyViewerAddStateChoose({dataset: {state: "warp"}});
out.pickerChosen = {addDisabled: els["spv-part-addstate-add"].disabled,
                    list: els["spv-part-addstate-list"].innerHTML};
// A re-push while open keeps the choice.
render([], {name: NAME, states: ["cruise", "warp"]});
out.pickerRepushDisabled = els["spv-part-addstate-add"].disabled;
shipPropertyViewerAddStateAdd();
out.pickerAfterAdd = shown("spv-part-addstate");
take("pickerAddEvents");
render([], null);
out.pickerClosed = shown("spv-part-addstate");
render([], {name: NAME, states: ["red"]});
out.pickerFreshDisabled = els["spv-part-addstate-add"].disabled;
shipPropertyViewerAddStateCancel();
take("pickerCancelEvents");

process.stdout.write(JSON.stringify(out));
"""


def _run_harness():
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
        f.write(_NODE_HARNESS)
        harness_path = f.name
    try:
        result = subprocess.run(
            [NODE, harness_path, str(JS_PATH)],
            capture_output=True, text=True, timeout=10,
        )
    finally:
        Path(harness_path).unlink()
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.fixture(scope="module")
def harness():
    if NODE is None:
        pytest.skip("node not found on PATH")
    return _run_harness()


def _payload_of(events, prefix):
    matches = [e for e in events if e.startswith(prefix)]
    assert matches, (prefix, events)
    assert len(matches) == 1, matches
    return json.loads(matches[0][len(prefix):])


NAME = 'Nacelle\'s "Strut" & Co'
EV = "ship-property-viewer/"


def test_a_quoted_part_name_survives_render_and_click_round_trip(harness):
    """Actually EXECUTE renderSPVModelParts and the click/menu handlers via
    node (following test_subtitle_styling.py's harness pattern) for a part
    named with a single quote, a double quote and an ampersand, rather than
    pattern-matching source text -- this pins real behaviour instead of a
    string that merely looks right."""
    out = harness
    # No on* attribute anywhere in the rendered rows may contain the name
    # (or even a readable fragment of it) -- that is exactly the shape of
    # the bug this fixes: a name baked into a JS string literal inside
    # onclick/oncontextmenu.
    for html in (out["partRowHtml"], out["childRowsHtml"], out["picker"]["list"]):
        for on_attr in re.findall(r'on\w+="([^"]*)"', html):
            assert NAME not in on_attr, on_attr
            assert "Nacelle" not in on_attr, on_attr

    # The name DOES travel -- but only as an ordinary, once-HTML-escaped
    # data-* attribute value. Decode it exactly as a browser would
    # (html.unescape) and confirm it round-trips losslessly.
    m = re.search(r'data-part-name="([^"]*)"', out["partRowHtml"])
    assert m, out["partRowHtml"]
    assert html_stdlib.unescape(m.group(1)) == NAME

    assert (EV + "model_parts/select:" + NAME) in out["clickEvents"]
    assert _payload_of(out["clickEvents"], EV + "part/select_node:") == {
        "name": NAME, "kind": "anchor"}


def test_tree_rows_are_names_only(harness):
    """A chosen Anchor and a chosen Breakage -- the rows that used to grow
    inline fields -- render their label and nothing else: no stepper, no
    button, no value text."""
    html = harness["childRowsHtml"]
    assert "<button" not in html
    assert "spv-step" not in html
    assert "inline-field" not in html
    for text in ("Transition time", "Breaks off", "hull strength", "3.50",
                 "35%", "%"):
        assert text not in html, text
    # The visible text of the tree is exactly the names.
    visible = [t for t in re.split(r"<[^>]*>", html) if t.strip()]
    assert [html_stdlib.unescape(t) for t in visible] == [
        NAME, "Anchor", "Warp Transformation", "Breakage"]
    # The values ride along in data-* for the Edit popups to pre-fill.
    assert 'data-value="3.5"' in html
    assert 'data-value="35"' in html


def test_menus_show_the_right_entries(harness):
    none_, blk = "none", "block"
    assert harness["menuPart"] == {
        "addanchor": blk, "addstate": blk, "makebreakable": blk,
        "editanchor": none_, "editbreak": none_, "removenode": none_}
    # Anchor present, breakable, every state posed: nothing left to add.
    assert harness["menuFull"] == {
        "addanchor": none_, "addstate": none_, "makebreakable": none_,
        "editanchor": none_, "editbreak": none_, "removenode": none_}
    assert harness["menuAnchor"] == {
        "addanchor": none_, "addstate": none_, "makebreakable": none_,
        "editanchor": blk, "editbreak": none_, "removenode": blk}
    assert harness["menuState"] == {
        "addanchor": none_, "addstate": none_, "makebreakable": none_,
        "editanchor": none_, "editbreak": none_, "removenode": blk}
    assert harness["menuBreak"] == {
        "addanchor": none_, "addstate": none_, "makebreakable": none_,
        "editanchor": none_, "editbreak": blk, "removenode": blk}


def test_add_anchor_popup_dispatches_numeric_seconds(harness):
    assert harness["addAnchor"] == {"title": "Add Anchor", "ok": "Add",
                                    "value": "2.00", "shown": "flex",
                                    "menu": "none"}
    # The menu announced the overlay; opening the popup from it keeps the
    # overlay open (no overlay:0) until Add/Cancel.
    assert harness["addAnchorMenuEvents"] == [EV + "overlay:1"]
    assert harness["addAnchorOpenEvents"] == []
    events = harness["addAnchorEvents"]
    payload = _payload_of(events, EV + "part/add_anchor:")
    assert payload == {"name": NAME, "seconds": 2.5}
    assert isinstance(payload["seconds"], (int, float))
    assert events[-1] == EV + "overlay:0", "closes through spvHideOverlays"
    assert harness["addAnchorClosed"] == "none"
    assert harness["anchorFloor"] == "0.25"
    assert harness["anchorCancelEvents"] == [EV + "overlay:0"]


def test_edit_anchor_popup_prefills_and_sets_the_transition(harness):
    assert harness["editAnchor"] == {"title": "Edit Anchor", "ok": "Apply",
                                     "value": "3.50"}
    events = harness["editAnchorEvents"]
    assert _payload_of(events, EV + "part/set_transition:") == {
        "name": NAME, "seconds": 3.25}
    assert not any(e.startswith(EV + "part/add_anchor") for e in events)
    assert events[-1] == EV + "overlay:0"


def test_make_breakable_popup_dispatches_numeric_percent(harness):
    assert harness["makeBreak"] == {"title": "Make Breakable", "ok": "Add",
                                    "value": "20", "shown": "flex"}
    events = harness["makeBreakEvents"]
    payload = _payload_of(events, EV + "part/make_breakable:")
    assert payload == {"name": NAME, "percent": 25}
    assert isinstance(payload["percent"], (int, float))
    assert events[-1] == EV + "overlay:0"
    assert harness["breakCeil"] == "100"
    assert harness["breakFloor"] == "5"
    assert harness["breakCancelEvents"] == [EV + "overlay:0"]


def test_edit_breakage_popup_prefills_and_sets_the_break(harness):
    assert harness["editBreak"] == {"title": "Edit Breakage", "ok": "Apply",
                                    "value": "35"}
    events = harness["editBreakEvents"]
    assert _payload_of(events, EV + "part/set_break:") == {
        "name": NAME, "percent": 35}
    assert events[-1] == EV + "overlay:0"


def test_add_state_menu_entry_asks_python_and_opens_nothing_itself(harness):
    """The anchor check is Python's: the menu entry only closes the menu and
    sends begin_add_state -- overlay:0 FIRST, so it cannot land after the
    picker has taken the overlay."""
    assert harness["beginEvents"] == [
        EV + "overlay:0", EV + "part/begin_add_state:" + NAME]
    assert harness["beginShown"] == "none"


def test_add_state_picker_is_driven_by_the_payload(harness):
    picker = harness["picker"]
    assert picker["shown"] == "flex"
    assert "Cruising" in picker["list"] and "Warp" in picker["list"]
    for label in ("Yellow Alert", "Red Alert"):
        assert label not in picker["list"], label
    assert 'data-state="warp"' in picker["list"]
    assert picker["addDisabled"] is True, "Add is disabled until a choice"
    assert harness["pickerNoChoiceEvents"] == []
    assert harness["pickerChosen"]["addDisabled"] is False
    assert "spv-part-choice--chosen" in harness["pickerChosen"]["list"]
    assert harness["pickerRepushDisabled"] is False, "a re-push keeps the choice"
    assert harness["pickerAddEvents"] == [
        EV + "part/add_state:" + json.dumps({"name": NAME, "state": "warp"},
                                            separators=(",", ":"))]
    assert harness["pickerClosed"] == "none"
    assert harness["pickerFreshDisabled"] is True, "a new picker starts unchosen"
    assert harness["pickerCancelEvents"] == [EV + "part/cancel_add_state"]


# --- ruling 18: the coord Paste button is kind-aware ------------------------

def test_coord_paste_button_reads_can_paste():
    """The Move panel's Paste greys on a wrong-kind clipboard, as the
    rotate and scale panels' do -- it reads the payload's can_paste, never
    has_clipboard alone."""
    js = _read(JS)
    # All three panels share spvShowPanel (see renderSPVToolPanels); the
    # Move panel goes through it too. Behaviour: test_spv_decals_pane_cef.py.
    start = js.index("function spvShowPanel(")
    block = js[start:js.index("el.style.display = 'block';", start)]
    assert "paste.disabled = !values.can_paste;" in block
    assert ("paste.classList.toggle('spv-coords__btn--disabled', "
            "!values.can_paste);") in block
    assert "has_clipboard" not in block
    assert "spvShowPanel('spv-coord', 'spv-coords', coords, rows);" in js
