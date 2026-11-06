"""Target list page, run for real under node against a minimal fake DOM.

Executes native/assets/ui-cef/js/target_list.js: rows (name, distance,
stacked bars; no caret, no subsystem rows), the filter tabs and the sort
strip reflecting `filters` / `sort`, and the strip click handlers.

Spec: docs/superpowers/specs/2026-11-05-target-list-and-target-panel-redesign-design.md
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
JS_PATH = ROOT / "native/assets/ui-cef/js/target_list.js"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node not installed")

_HARNESS = r"""
const fs = require("fs");
const events = [];
function btn(attrs) {
  const cls = new Set((attrs.cls || "").split(" ").filter(Boolean));
  const a = Object.assign({}, attrs.attrs);
  const el = {
    a: a,
    getAttribute: k => (k in a ? a[k] : null),
    setAttribute(k, v) { a[k] = String(v); },
    classList: {
      contains: c => cls.has(c),
      add: c => cls.add(c), remove: c => cls.delete(c),
      toggle(c, on) { if (on) cls.add(c); else cls.delete(c); },
    },
    closest(sel) { return el; },
  };
  el.cls = () => Array.from(cls);
  return el;
}
const tabs = ["FRIENDLY", "NEUTRAL", "ENEMY"].map(
  k => btn({cls: "target-list__tab", attrs: {"data-aff": k}}));
const sorts = ["name", "distance", "health"].map(
  k => btn({cls: "target-list__sort-opt", attrs: {"data-sort": k}}));
let body = "";
const bodyEl = {set innerHTML(v) { body = v; }, get innerHTML() { return body; }};
const panelCls = new Set(["target-list--hidden"]);
const panel = {
  classList: {add: c => panelCls.add(c), remove: c => panelCls.delete(c)},
  querySelectorAll: sel => sel.includes("tab") ? tabs : sorts,
};
const byId = {
  "target-list-panel": panel, "target-list-body": bodyEl,
  "target-list-tabs": {addEventListener() {}, querySelectorAll: () => tabs},
  "target-list-sort": {addEventListener() {}, querySelectorAll: () => sorts},
};
global.document = {getElementById: id => byId[id] || null};
global.dauntlessEvent = e => events.push(e);
(0, eval)(fs.readFileSync(process.argv[1], "utf8"));

const s = JSON.parse(process.argv[2]);
const out = [];
for (const step of s) {
  if (step.push) setTargetList(step.push);
  if (step.tab != null) targetListTabClick({target: tabs[step.tab]});
  if (step.sort != null) targetListSortClick({target: sorts[step.sort]});
  out.push({
    body, events: events.slice(), hidden: panelCls.has("target-list--hidden"),
    tabs: tabs.map(t => t.cls()), sorts: sorts.map(t => t.cls()),
    checked: sorts.map(t => t.getAttribute("aria-checked")),
  });
}
console.log(JSON.stringify(out));
"""


def _run(steps):
    r = subprocess.run([NODE, "-e", _HARNESS, str(JS_PATH), json.dumps(steps)],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _state(rows=None, sort="name", filters=None):
    return {
        "visible": True, "selected": None, "selected_subsystem": None,
        "filters": filters or {"FRIENDLY": True, "NEUTRAL": False, "ENEMY": True},
        "sort": sort,
        "rows": rows if rows is not None else [],
    }


def _row(name="Vor'cha", shields=True, dist=29.62):
    return {"name": name, "label": name, "affiliation": "ENEMY", "hull": 80,
            "shields": 50, "has_shields": shields, "dist_km": dist, "marker": None}


def test_row_has_distance_before_bars_and_no_caret_or_sub():
    out = _run([{"push": _state([_row()])}])[0]["body"]
    assert "target-list__caret" not in out
    assert "target-list__sub" not in out
    dist = '<span class="target-list__dist">29.62 km</span>'
    assert dist in out
    assert out.index(dist) < out.index("target-list__bars")


def test_row_without_shields_has_one_bar():
    out = _run([{"push": _state([_row(shields=False)])}])[0]["body"]
    assert out.count('class="target-list__bar ') == 1
    assert "target-list__bar--shields" not in out


def test_apostrophe_name_stays_intact_in_event():
    out = _run([{"push": _state([_row(name="Vor'cha")])}])[0]["body"]
    assert "target/Vor\\&#39;cha" in out


def test_tabs_reflect_filters_and_sort_reflects_state():
    o = _run([{"push": _state(sort="distance")}])[0]
    on = ["target-list__tab--on" in t for t in o["tabs"]]
    assert on == [True, False, True]
    assert ["target-list__sort-opt--on" in t for t in o["sorts"]] == [False, True, False]
    assert o["checked"] == ["false", "true", "false"]


def test_clicks_emit_events_and_active_sort_emits_nothing():
    o = _run([{"push": _state(sort="name")}, {"tab": 2}, {"sort": 1}, {"sort": 0}])
    assert o[-1]["events"] == ["target/__filter__/ENEMY", "target/__sort__/distance"]


def test_empty_rows_still_renders_and_responds():
    o = _run([{"push": _state(rows=[])}, {"tab": 0}, {"sort": 2}])
    assert o[0]["body"] == ""
    assert not o[0]["hidden"]
    assert o[-1]["events"] == ["target/__filter__/FRIENDLY", "target/__sort__/health"]
