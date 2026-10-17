"""A Set Course system row is split in CEF: the caret opens its regions, the
rest of the row sets course to the system's default region.

BC's system node is a menu that also selects (Systems/Utils.py:24);
CrewMenuPanel flags it `sets_course`. Executes the real appendCrewRows under
node with a minimal DOM, following test_subtitle_styling.py's _NODE_HARNESS.
"""
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
JS_PATH = ROOT / "native/assets/ui-cef/js/crew_menus.js"
NODE = shutil.which("node")

_NODE_HARNESS = r"""
const fs = require("fs");

function makeEl(tag) {
  const classes = new Set();
  const el = {
    tag: tag, children: [], style: {}, attrs: {}, textContent: "",
    onclick: null,
    appendChild: function (c) { el.children.push(c); return c; },
    setAttribute: function (k, v) { el.attrs[k] = v; },
    classList: {
      add: function (c) { classes.add(c); },
      contains: function (c) { return classes.has(c); },
    },
  };
  Object.defineProperty(el, "className", {
    get: function () { return Array.from(classes).join(" "); },
    set: function (v) {
      classes.clear();
      String(v).split(/\s+/).filter(Boolean).forEach(function (c) { classes.add(c); });
    },
  });
  return el;
}

global.document = {createElement: makeEl};
const events = [];
global.dauntlessEvent = function (e) { events.push(e); };

eval(fs.readFileSync(process.argv[2], "utf8"));

function find(el, cls) {
  if (el.classList.contains(cls)) return el;
  for (const c of el.children) { const f = find(c, cls); if (f) return f; }
  return null;
}

// Simulates a browser click: the target's handler, then bubbling to the row
// unless stopPropagation was called.
function click(target, row) {
  let stopped = false;
  const ev = {stopPropagation: function () { stopped = true; }};
  if (target !== row && target.onclick) target.onclick(ev);
  if (!stopped && row.onclick) row.onclick(ev);
}

const nodes = JSON.parse(process.argv[3]);
const body = makeEl("div");
appendCrewRows(body, nodes, 0);
const out = {};
for (const row of body.children) {
  const label = find(row, "crew-menu__label").textContent;
  const caret = find(row, "crew-menu__caret");
  events.length = 0;
  if (caret) click(caret, row);
  const caretEvents = events.slice();
  events.length = 0;
  click(find(row, "crew-menu__label"), row);
  out[label] = {caret: caretEvents, label: events.slice(),
                caretClass: caret ? caret.className : null};
}
process.stdout.write(JSON.stringify(out));
"""


def _run(nodes):
    if NODE is None:
        pytest.skip("node not installed")
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
        f.write(_NODE_HARNESS)
        harness = f.name
    try:
        result = subprocess.run(
            [NODE, harness, str(JS_PATH), json.dumps(nodes)],
            capture_output=True, text=True, timeout=10)
    finally:
        Path(harness).unlink()
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _region(id_, label):
    return {"id": id_, "type": "button", "label": label, "enabled": True,
            "visible": True, "chosen": False}


def _menu(id_, label, **extra):
    return {"id": id_, "type": "menu", "label": label, "enabled": True,
            "visible": True, "chosen": False, "expanded": False,
            "openable": True, "children": [_region(id_ + 1, "Haven Colony")],
            **extra}


def test_a_system_rows_caret_expands_and_its_label_sets_course():
    out = _run([_menu(10, "Vesuvi", sets_course=True)])["Vesuvi"]
    assert out["caret"] == ["crew-menu/expand:10"]
    assert out["label"] == ["crew-menu/click:10"]
    # The caret is its own hit target, styled as one.
    assert "crew-menu__caret--split" in out["caretClass"]


def test_a_plain_submenu_row_still_expands_from_anywhere():
    out = _run([_menu(20, "Hail")])["Hail"]
    assert out["caret"] == ["crew-menu/expand:20"]
    assert out["label"] == ["crew-menu/expand:20"]
    assert "crew-menu__caret--split" not in out["caretClass"]


def test_a_disabled_system_row_does_nothing():
    out = _run([_menu(30, "Vesuvi", sets_course=True, enabled=False)])["Vesuvi"]
    assert out["caret"] == [] and out["label"] == []
