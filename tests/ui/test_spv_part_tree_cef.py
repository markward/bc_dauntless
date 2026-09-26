"""Task 7 (spec 2026-09-25 section 7): the Model Parts pane renders as a node
tree in CEF -- rows for the part and its Anchor / {State} Transformation /
Breakage children, right-click menus to add/remove them, inline fields on the
Anchor and Breakage rows, and a toast banner. Static text assertions on the
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
                   "part/set_transition:", "part/set_break:"):
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
    for label in ("Add Anchor", "Add State Transformation", "Make Breakable"):
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


def test_add_state_submenu_lists_missing_states_dynamically():
    """No hardcoded per-state item in the ctxmenu markup -- the JS fills the
    submenu per-row from the row's own missing_states, using the spec's
    state labels."""
    index = _read(HTML)
    js = _read(JS)
    assert 'id="spv-ctx-addstate-items"' in index
    for label in ("Cruising", "Yellow Alert", "Red Alert"):
        assert label not in index, "state label must not be hardcoded in HTML"
    for label in ("Cruising", "Yellow Alert", "Red Alert", "Warp"):
        assert label in js, label


def test_remove_menu_item_present_for_child_rows():
    index = _read(HTML)
    assert ">Remove<" in index


# --- inline fields on Anchor / Breakage: steppers, not keyboard input -------
#
# Fix round 1, ruling 2: this engine has no keyboard->CEF forwarding (every
# sibling SPV numeric control -- radius, light shape/extent, emitter
# intensity -- is a mouse stepper for that reason), so the Anchor/Breakage
# inline fields must be too, not <input type="number">.

def test_inline_field_labels_present():
    js = _read(JS)
    assert "Transition time:" in js
    assert "Breaks off after taking" in js
    assert "of the ship's hull strength" in js


def test_inline_fields_are_steppers_not_keyboard_input():
    js = _read(JS)
    assert 'type="number"' not in js
    assert "shipPropertyViewerAnchorStep" in js
    assert "shipPropertyViewerBreakStep" in js


def test_transition_stepper_step_and_floor():
    js = _read(JS)
    assert "shipPropertyViewerAnchorStep(this, -0.25)" in js
    assert "shipPropertyViewerAnchorStep(this, 0.25)" in js
    assert "Math.max(0.25," in js


def test_break_stepper_step_and_clamp():
    js = _read(JS)
    assert "shipPropertyViewerBreakStep(this, -5)" in js
    assert "shipPropertyViewerBreakStep(this, 5)" in js
    assert "Math.min(100, Math.max(5," in js


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

def test_css_defines_toast_and_inline_field_rules():
    css = _read(CSS)
    assert "#spv-toast" in css
    assert "spv-part-inline-field" in css


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
    assert ".dataset.value" in js  # the steppers' pre-click value


_ESCAPING_NODE_HARNESS = r"""
const fs = require("fs");
global.window = global;

function makeEl() {
  const classes = new Set();
  return {
    innerHTML: "", style: {}, textContent: "", checked: false,
    classList: {
      toggle: function (c, v) { if (v) classes.add(c); else classes.delete(c); },
      contains: function (c) { return classes.has(c); },
    },
  };
}

const els = {
  "spv-parts": makeEl(), "spv-parts-body": makeEl(),
  "spv-parts-showall-cb": makeEl(), "spv-toast": makeEl(),
};
global.document = {
  getElementById: function (id) { return els[id] || null; },
  addEventListener: function () {},
};
const events = [];
global.dauntlessEvent = function (s) { events.push(s); };

eval(fs.readFileSync(process.argv[2], "utf8"));

// A name with all three characters the original bug mishandled: a single
// quote (breaks a '...' JS string on decode), a double quote (would break a
// "..." attribute), and an ampersand (must not be double-escaped).
const NAME = "Nacelle's \"Strut\" & Co";

renderSPVModelParts({
  expanded: true, show_all: false, selected_box: null, toast: null,
  rows: [{
    kind: "part", name: NAME, depth: 0, chosen: false, dirty: true,
    has_anchor: false, missing_states: ["cruise", "warp"], breakable: false,
  }],
});
const partRowHtml = els["spv-parts-body"].innerHTML;

renderSPVModelParts({
  expanded: true, show_all: false, selected_box: null, toast: null,
  rows: [{
    kind: "anchor", part: NAME, label: "Anchor", depth: 1,
    chosen: true, value: 2.0,
  }],
});
const anchorRowHtml = els["spv-parts-body"].innerHTML;

// Simulate real clicks: a bare object carrying `dataset`, exactly what a
// real on*="handler(this)" call hands the handler once the browser has
// already HTML-decoded the attribute -- no JS re-parse in between, so a
// quote in NAME cannot corrupt it.
shipPropertyViewerPartRowClick({dataset: {partName: NAME}});
shipPropertyViewerPartNodeRowClick({dataset: {partName: NAME, nodeKind: "anchor"}});
shipPropertyViewerAnchorStep({dataset: {partName: NAME, value: "2"}}, 0.25);
shipPropertyViewerBreakStep({dataset: {partName: NAME, value: "20"}}, 5);

process.stdout.write(JSON.stringify({
  partRowHtml: partRowHtml, anchorRowHtml: anchorRowHtml, events: events,
}));
"""


def _run_escaping_harness():
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
        f.write(_ESCAPING_NODE_HARNESS)
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


def _payload_of(events, prefix):
    matches = [e for e in events if e.startswith(prefix)]
    assert matches, (prefix, events)
    return json.loads(matches[0][len(prefix):])


NAME = 'Nacelle\'s "Strut" & Co'


@pytest.mark.skipif(NODE is None, reason="node not found on PATH")
def test_a_quoted_part_name_survives_render_and_click_round_trip():
    """Actually EXECUTE renderSPVModelParts and the click/menu/stepper
    handlers via node (following test_subtitle_styling.py's harness
    pattern) for a part named with a single quote, a double quote and an
    ampersand, rather than pattern-matching source text -- this pins real
    behaviour instead of a string that merely looks right."""
    out = _run_escaping_harness()

    # No on* attribute anywhere in the rendered rows may contain the name
    # (or even a readable fragment of it) -- that is exactly the shape of
    # the bug this fixes: a name baked into a JS string literal inside
    # onclick/oncontextmenu.
    for html in (out["partRowHtml"], out["anchorRowHtml"]):
        for on_attr in re.findall(r'on\w+="([^"]*)"', html):
            assert NAME not in on_attr, on_attr
            assert "Nacelle" not in on_attr, on_attr

    # The name DOES travel -- but only as an ordinary, once-HTML-escaped
    # data-* attribute value. Decode it exactly as a browser would
    # (html.unescape) and confirm it round-trips losslessly.
    m = re.search(r'data-part-name="([^"]*)"', out["partRowHtml"])
    assert m, out["partRowHtml"]
    assert html_stdlib.unescape(m.group(1)) == NAME

    # And the click/menu/stepper handlers -- which read `this.dataset`
    # instead of an interpolated argument -- dispatch the exact,
    # uncorrupted name.
    assert ("ship-property-viewer/model_parts/select:" + NAME) in out["events"]
    assert _payload_of(out["events"], "ship-property-viewer/part/select_node:") == {
        "name": NAME, "kind": "anchor"}
    assert _payload_of(out["events"], "ship-property-viewer/part/set_transition:") == {
        "name": NAME, "seconds": 2.25}
    assert _payload_of(out["events"], "ship-property-viewer/part/set_break:") == {
        "name": NAME, "percent": 25}
