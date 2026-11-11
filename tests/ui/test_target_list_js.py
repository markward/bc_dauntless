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
  classList: {add: c => panelCls.add(c), remove: c => panelCls.delete(c),
              toggle(c, on) { if (on) panelCls.add(c); else panelCls.delete(c); }},
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
    minimized: panelCls.has("target-list--minimized"),
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


def test_bars_are_shields_left_then_hull_right():
    out = _run([{"push": _state([_row()])}])[0]["body"]
    assert out.index("target-list__bar--shields") < out.index("target-list__bar--hull")
    assert 'target-list__bar--shields" style="--bar-pct:50%"' in out
    assert 'target-list__bar--hull" style="--bar-pct:80%"' in out


def test_bars_are_vertical_and_drain_from_the_top():
    import re
    css = (ROOT / "native/assets/ui-cef/css/target_list.css").read_text(encoding="utf-8")
    fill = re.search(r"\.target-list__bar::after\s*\{([^}]*)\}", css).group(1)
    # Fill anchored at the bottom, its HEIGHT is the percent: losing health
    # lowers the top edge.
    assert re.search(r"bottom:\s*0", fill)
    assert re.search(r"height:\s*var\(--bar-pct\)", fill)
    assert "width: var(--bar-pct)" not in css


def test_minimized_flag_collapses_the_panel():
    o = _run([{"push": dict(_state([_row()]), minimized=True)},
              {"push": dict(_state([_row()]), minimized=False)},
              {"push": _state([_row()])}])
    assert [x["minimized"] for x in o] == [True, False, False]


def test_header_has_the_minimize_button_and_minimized_hides_the_rest():
    import re
    html = (ROOT / "native/assets/ui-cef/index.html").read_text(encoding="utf-8")
    header = re.search(r'<div class="target-list__header">(.*?)</div>', html, re.S).group(1)
    assert "dauntlessEvent('target/__minimize__')" in header
    assert 'class="bc-panel__minimize' in header
    css = (ROOT / "native/assets/ui-cef/css/target_list.css").read_text(encoding="utf-8")
    # One rule hides the strips and the list; only the header stays.
    rule = re.search(r"((?:[^{}]*\.target-list--minimized[^{}]*)+)\{\s*display:\s*none;?\s*\}", css)
    assert rule, "no minimized display:none rule"
    for part in ("tabs", "body", "sort"):
        assert ".target-list__%s" % part in rule.group(1), part
    assert ".target-list__header" not in rule.group(1)


def test_commander_row_draws_the_chevron_before_the_name():
    out = _run([{"push": _state([dict(_row(), commander=True)])}])[0]["body"]
    chev = 'target-list__marker target-list__marker--commander'
    assert chev in out
    assert out.index(chev) < out.index("target-list__name")


def test_commander_chevron_sits_beside_a_protect_marker():
    out = _run([{"push": _state([dict(_row(), commander=True,
                                      marker="protect")])}])[0]["body"]
    assert "target-list__marker--commander" in out
    assert "target-list__marker--protect" in out


def test_non_commander_row_has_no_chevron():
    out = _run([{"push": _state([_row(), dict(_row(name="B"), commander=False)])}])[0]["body"]
    assert "target-list__marker--commander" not in out


def test_focus_row_draws_the_dotted_crosshair_after_the_chevron():
    out = _run([{"push": _state([dict(_row(), commander=True, focus=True)])}])[0]["body"]
    foc = 'target-list__marker target-list__marker--focus'
    assert foc in out
    assert out.index('--commander') < out.index(foc) < out.index("target-list__name")
    assert '<circle cx="5" cy="6" r="1.2" fill="currentColor"' in out


def test_non_focus_row_has_no_focus_marker():
    out = _run([{"push": _state([_row(), dict(_row(name="B"), focus=False)])}])[0]["body"]
    assert "target-list__marker--focus" not in out
