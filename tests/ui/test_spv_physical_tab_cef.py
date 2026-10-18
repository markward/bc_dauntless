"""Task 6 (spec 2026-10-17 section 7): the Ship Property Viewer's
Functional / Physical tab strip, the Physical list and its context menus.
Static checks on HTML/JS/CSS plus a node harness that EXECUTES the renderer
and handlers, following test_spv_part_tree_cef.py."""
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
CSS = ROOT / "native/assets/ui-cef/css/ship_property_viewer.css"
NODE = shutil.which("node")


def _read(p):
    return Path(p).read_text(encoding="utf-8")


def test_tab_strip_under_header():
    html = _read(HTML)
    a = html.index("spv-syslist__header")
    b = html.index('id="spv-systabs"')
    c = html.index('id="spv-syslist-body"')
    assert a < b < c
    assert 'id="spv-physical-body"' in html
    assert html[b:c].count("spv-tab") >= 2


def test_new_menu_items_hidden_by_default():
    html = _read(HTML)
    for item in ("spv-ctx-moveto", "spv-ctx-reset", "spv-ctx-moveall",
                 "spv-ctx-resetall"):
        m = re.search(r'<div id="%s"[^>]*>' % item, html)
        assert m, item
        assert "display:none" in m.group(0).replace(" ", ""), item
    m = re.search(r'<div id="spv-ctxsub"[^>]*>', html)
    assert m and "spv-ctxmenu" in m.group(0)
    js = _read(JS_PATH)
    body = js[js.index("function spvShowMenuItems"):js.index("function spvOpenMenuAt")]
    for key in ("spv-ctx-moveto", "spv-ctx-reset", "spv-ctx-moveall",
                "spv-ctx-resetall"):
        assert key in body, key


def _physical_code():
    js = _read(JS_PATH)
    return js[js.index("// ---- Physical tab"):js.index("// ---- end Physical tab")]


def test_no_guess_wording():
    html = _read(HTML)
    css = _read(CSS)
    block = html[html.index('id="spv-systabs"'):html.index('id="spv-syslist-body"')]
    css_block = css[css.index("/* ---- Physical tab"):]
    for text in (_physical_code(), block, css_block):
        assert "guess" not in text.lower()


def test_css_values():
    css = _read(CSS)
    block = css[css.index("/* ---- Physical tab"):]
    for needle in ("rgba(10, 10, 16, 0.97)", "rgb(216, 94, 86)",
                   "rgba(255, 230, 160, 0.25)", "5px 0 4px", "0.12em",
                   "rgba(235, 225, 255, 0.5)", "rgba(255, 214, 90, 0.12)",
                   "rgb(255, 200, 60)", "rgb(255, 140, 120)", "0.08em",
                   "rgba(235, 225, 255, 0.38)"):
        assert needle in block, needle


_NODE_HARNESS = r"""
const fs = require("fs");
global.window = global;
function makeEl() {
  const classes = new Set();
  return {
    innerHTML: "", style: {}, textContent: "", dataset: {},
    classList: {
      toggle: function (c, v) { if (v) classes.add(c); else classes.delete(c); },
      add: function (c) { classes.add(c); },
      remove: function (c) { classes.delete(c); },
      contains: function (c) { return classes.has(c); },
    },
    contains: function () { return false; },
    addEventListener: function () {},
    getBoundingClientRect: function () { return {right: 200, top: 50}; },
  };
}
const IDS = ["spv-ctxmenu", "spv-ctxsub", "spv-ctx-radius", "spv-ctx-addlight",
  "spv-ctx-light", "spv-ctx-removelight", "spv-ctx-addemitter",
  "spv-ctx-editemitter", "spv-ctx-removeemitter", "spv-ctx-addanchor",
  "spv-ctx-addstate", "spv-ctx-makebreakable", "spv-ctx-editanchor",
  "spv-ctx-editbreak", "spv-ctx-removenode", "spv-ctx-moveto", "spv-ctx-reset",
  "spv-ctx-moveall", "spv-ctx-resetall", "spv-systabs", "spv-tab-functional",
  "spv-tab-physical", "spv-syslist-body", "spv-physical-body", "spv-radius",
  "spv-confirm"];
const els = {};
IDS.forEach(function (id) { els[id] = makeEl(); });
global.document = {
  getElementById: function (id) { return els[id] || null; },
  addEventListener: function () {},
};
let events = [];
global.dauntlessEvent = function (s) { events.push(s); };
eval(fs.readFileSync(process.argv[2], "utf8"));
function ev() { return {preventDefault: function () {}, stopPropagation: function () {},
                        clientX: 10, clientY: 20}; }
const out = {};
function take(k) { out[k] = events; events = []; }

const payload = {
  tab: "physical", parts: ["birdofprey", "head"],
  groups: [
    {part: "old wing", missing: true, rows: [
      {key: "sub:1", name: "Phaser", kind: "subsystem", source: "set", chosen: false, index: 1}]},
    {part: "birdofprey", missing: false, rows: [
      {key: "sub:3", name: "Impulse", kind: "subsystem", source: "auto", chosen: true, index: 3},
      {key: "light:nav1", name: "nav1", kind: "running_light", source: "auto", chosen: false, index: null}]},
    {part: "head", missing: false, rows: []},
    {part: null, missing: false, rows: [
      {key: "sub:9", name: "Loose", kind: "subsystem", source: "auto", chosen: false, index: 9}]},
  ],
};
renderSPVPhysical(payload);
out.html = els["spv-physical-body"].innerHTML;
out.funcDisplay = els["spv-syslist-body"].style.display;
out.physDisplay = els["spv-physical-body"].style.display;
out.activeTab = els["spv-tab-physical"].classList.contains("spv-tab--active");
out.activeFunc = els["spv-tab-functional"].classList.contains("spv-tab--active");

shipPropertyViewerPhysRowClick({dataset: {key: "light:nav1", kind: "running_light", index: ""}});
renderSPVPhysical(payload);
out.lightChosen = els["spv-physical-body"].innerHTML;
take("lightEvents");
shipPropertyViewerPhysRowClick({dataset: {key: "sub:3", kind: "subsystem", index: "3"}});
renderSPVPhysical(payload);
out.afterSub = els["spv-physical-body"].innerHTML;
take("subEvents");

shipPropertyViewerPhysChildMenu(ev(), {dataset: {key: "sub:3", source: "auto", part: "birdofprey"}});
out.menuMoveTo = els["spv-ctx-moveto"].style.display;
out.menuReset = els["spv-ctx-reset"].style.display;
out.menuMoveAll = els["spv-ctx-moveall"].style.display;
shipPropertyViewerPhysOpenSub({dataset: {mode: "move"}});
out.sub = els["spv-ctxsub"].innerHTML;
out.subDisplay = els["spv-ctxsub"].style.display;
take("beforeMove");
shipPropertyViewerPhysPickPart({dataset: {part: "birdofprey"}});
take("moveEvents");

shipPropertyViewerPhysChildMenu(ev(), {dataset: {key: "sub:1", source: "set", part: "old wing"}});
out.setMoveToInert = els["spv-ctx-moveto"].classList.contains("spv-ctxmenu__item--inert");
out.setResetInert = els["spv-ctx-reset"].classList.contains("spv-ctxmenu__item--inert");
els["spv-ctxsub"].style.display = "none";
shipPropertyViewerPhysOpenSub({dataset: {mode: "move"}});
out.setSubDisplay = els["spv-ctxsub"].style.display;
shipPropertyViewerPhysReset();
take("resetEvents");
shipPropertyViewerPhysChildMenu(ev(), {dataset: {key: "sub:3", source: "auto", part: "birdofprey"}});
out.autoResetInert = els["spv-ctx-reset"].classList.contains("spv-ctxmenu__item--inert");
shipPropertyViewerPhysReset();
take("autoResetEvents");

shipPropertyViewerPhysGroupMenu(ev(), {dataset: {part: "old wing", missing: "true"}});
out.groupMoveAll = els["spv-ctx-moveall"].style.display;
out.groupMoveTo = els["spv-ctx-moveto"].style.display;
shipPropertyViewerPhysOpenSub({dataset: {mode: "moveall"}});
shipPropertyViewerPhysPickPart({dataset: {part: "head"}});
shipPropertyViewerPhysGroupMenu(ev(), {dataset: {part: "old wing", missing: "true"}});
shipPropertyViewerPhysResetAll();
take("groupEvents");

const NAME = 'a"b<c';
renderSPVPhysical({tab: "physical", parts: [NAME], groups: [
  {part: NAME, missing: false, rows: [
    {key: "sub:2", name: NAME, kind: "subsystem", source: "set", chosen: false, index: 2}]}]});
out.escHtml = els["spv-physical-body"].innerHTML;
shipPropertyViewerPhysChildMenu(ev(), {dataset: {key: "sub:2", source: "auto", part: "zzz"}});
shipPropertyViewerPhysOpenSub({dataset: {mode: "move"}});
out.escSub = els["spv-ctxsub"].innerHTML;
events = [];
shipPropertyViewerPhysPickPart({dataset: {part: NAME}});
take("escEvents");

shipPropertyViewerPhysTab({dataset: {tab: "functional"}});
take("tabEvents");

renderSPVPhysical(payload);
function hdrKey(part) { return part === null ? "none" : "p:" + part; }
out.expandedHtml = els["spv-physical-body"].innerHTML;
shipPropertyViewerPhysGroupToggle({dataset: {gkey: hdrKey("birdofprey")}});
out.collapsedHtml = els["spv-physical-body"].innerHTML;
renderSPVPhysical(payload);
out.rerenderHtml = els["spv-physical-body"].innerHTML;
shipPropertyViewerPhysGroupToggle({dataset: {gkey: hdrKey("birdofprey")}});
out.restoredHtml = els["spv-physical-body"].innerHTML;
shipPropertyViewerPhysGroupToggle({dataset: {gkey: hdrKey(null)}});
out.noPartCollapsed = els["spv-physical-body"].innerHTML;
shipPropertyViewerPhysGroupToggle({dataset: {gkey: hdrKey(null)}});
shipPropertyViewerPhysGroupToggle({dataset: {gkey: hdrKey("old wing")}});
out.missingCollapsed = els["spv-physical-body"].innerHTML;
take("toggleEvents");
shipPropertyViewerPhysGroupMenu(ev(), {dataset: {part: "old wing", missing: "true"}});
out.collapsedMenuMoveAll = els["spv-ctx-moveall"].style.display;
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
        r = subprocess.run([NODE, path, str(JS_PATH)], capture_output=True,
                           text=True, timeout=10)
    finally:
        Path(path).unlink()
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _order(html, *needles):
    pos = [html.index(n) for n in needles]
    assert pos == sorted(pos), (needles, pos)


def test_render_groups_and_tags(harness):
    h = harness["html"]
    _order(h, "old wing", "birdofprey", "head")
    assert "⚠ " in h and "(missing)" in h
    assert "No part" in h
    assert h.index("birdofprey") < h.index("No part")
    assert "AUTO" in h and "SET" in h
    assert "spv-sys-row--dirty" not in h
    assert harness["funcDisplay"] == "none"
    assert harness["physDisplay"] != "none"
    assert harness["activeTab"] is True and harness["activeFunc"] is False


def test_row_clicks(harness):
    assert harness["lightEvents"] == []
    assert re.search(r'spv-sys-row--chosen[^>]*data-key="light:nav1"',
                     harness["lightChosen"])
    assert harness["subEvents"] == ["ship-property-viewer/select_pin:3"]
    assert not re.search(r'spv-sys-row--chosen[^>]*data-key="light:nav1"',
                         harness["afterSub"])


def test_move_to_dispatches_json(harness):
    assert harness["menuMoveTo"] == "block" and harness["menuReset"] == "block"
    assert harness["menuMoveAll"] == "none"
    assert harness["subDisplay"] == "block"
    assert "✓" in harness["sub"]
    assert harness["moveEvents"] == [
        'ship-property-viewer/physical/move:{"key":"sub:3","part":"birdofprey"}',
        "ship-property-viewer/overlay:0"]


def test_inert_items(harness):
    assert harness["setMoveToInert"] is True
    assert harness["setResetInert"] is False
    assert harness["setSubDisplay"] != "block"
    assert ('ship-property-viewer/physical/reset:{"key":"sub:1"}'
            in harness["resetEvents"])
    assert harness["autoResetInert"] is True
    assert not any("physical/reset" in e for e in harness["autoResetEvents"])


def test_group_menu(harness):
    assert harness["groupMoveAll"] == "block" and harness["groupMoveTo"] == "none"
    ev = harness["groupEvents"]
    assert ('ship-property-viewer/physical/move_all:'
            '{"missing":"old wing","part":"head"}') in ev
    assert 'ship-property-viewer/physical/reset_all:{"missing":"old wing"}' in ev


def test_names_are_escaped(harness):
    for html in (harness["escHtml"], harness["escSub"]):
        assert "a&quot;b&lt;c" in html
        assert 'a"b<c' not in html
    assert harness["escEvents"][0] == (
        'ship-property-viewer/physical/move:{"key":"sub:2","part":"a\\"b<c"}')


def test_tab_click_dispatches(harness):
    assert harness["tabEvents"] == [
        'ship-property-viewer/physical/tab:{"tab":"functional"}']


def test_group_toggle(harness):
    exp, col = harness["expandedHtml"], harness["collapsedHtml"]
    assert 'data-key="sub:3"' in exp and 'data-key="light:nav1"' in exp
    assert 'data-key="sub:3"' not in col and 'data-key="light:nav1"' not in col
    assert 'data-key="sub:9"' in col  # other groups untouched
    assert col.count("▸") == 1 and col.count("▾") == exp.count("▾") - 1
    # state survives a re-render of the same payload
    assert 'data-key="sub:3"' not in harness["rerenderHtml"]
    assert harness["restoredHtml"] == exp
    # the No part and missing groups toggle too, with no event dispatched
    assert 'data-key="sub:9"' not in harness["noPartCollapsed"]
    assert 'data-key="sub:1"' not in harness["missingCollapsed"]
    assert harness["toggleEvents"] == []
    # a collapsed missing header still opens Move all to
    assert harness["collapsedMenuMoveAll"] == "block"
