"""Quick Battle Setup's Warp-in stepper, run for real under node.

Executes the actual native/assets/ui-cef/js/quick_battle_setup.js against a
minimal fake DOM (innerHTML strings are parsed back into buttons/inputs), in
the style of test_crew_menu_system_row_js.py. There is no jsdom, so layout,
real focus and real event bubbling are NOT modelled: a click is dispatched
straight to qbsClick with a fake target, focus is a pointer, and `change` /
`blur` are fired by hand. The other panes' renderers are stubbed out.

Spec: docs/superpowers/specs/2026-10-22-warp-in-arrivals-and-qb-delay-design.md
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
JS_PATH = ROOT / "native/assets/ui-cef/js/quick_battle_setup.js"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node not installed")

_HARNESS = r"""
const fs = require("fs");
const html = {};          // element id -> innerHTML
const timers = [];
const events = [];
let active = null;
let delayEl = null;       // the live .qbs-delay input (reset on each re-render)

function attrs(tagText) {
  const out = {};
  tagText.replace(/([\w-]+)="([^"]*)"/g, (_, k, v) => { out[k] = v; return ""; });
  return out;
}
function mk(cls, a, extra) {
  const l = {change: [], blur: []};
  const el = Object.assign({
    cls: cls, a: a, disabled: false, value: "", listeners: l,
    getAttribute: k => (k in a ? a[k] : null),
    closest: sel => {
      if (sel === "[data-action]") return "data-action" in a ? el : null;
      if (sel === ".qbs-delay") return cls.split(" ").includes("qbs-delay") ? el : null;
      return null;
    },
    classList: {contains: c => cls.split(" ").includes(c)},
    contains: n => n === el,
    addEventListener: (t, f) => { (l[t] = l[t] || []).push(f); },
    focus: () => { active = el; },
    select: () => {},
    blur: () => { if (active === el) active = null; (l.blur || []).forEach(f => f({target: el})); },
  }, extra || {});
  return el;
}
function ctl(id) {
  return {
    set innerHTML(v) { html[id] = v; if (id === "qbs-groups") delayEl = null; }, get innerHTML() { return html[id] || ""; },
    style: {}, hidden: true, addEventListener() {}, contains: () => id === "quick-battle-setup",
    classList: {contains: () => false},
    scrollWidth: 0, clientWidth: 0,
  };
}
global.document = {
  getElementById: id => ctl(id),
  get activeElement() { return active; },
  addEventListener() {},
  querySelector: sel => {
    if (!sel.endsWith(".qbs-delay")) return null;
    const m = /<input class="qbs-delay"[^>]*>/.exec(html["qbs-groups"] || "");
    if (!m) return null;
    const a = attrs(m[0]);
    if (!delayEl) delayEl = mk("qbs-delay", a, {value: a.value});
    return delayEl;
  },
};
global.window = {addEventListener() {}};
global.setTimeout = f => { timers.push(f); return 0; };
global.dauntlessEvent = e => events.push(e);

(0, eval)(fs.readFileSync(process.argv[1], "utf8"));
["renderEras", "renderSpecies", "renderCatalog", "renderFooter", "renderSheet",
 "renderConfirm", "qbsPresetToast"].forEach(n => { global[n] = () => {}; });
QBS.catalog = {
  allegiances: [{id: "enemy", label: "Enemy"}],
  directions: [{id: "ahead", label: "Ahead"}, {id: "behind", label: "Behind"}],
  distances: [{id: "near", label: "Near", km: 5}],
  difficulties: [{id: "normal", label: "Normal"}],
};

function payload(n) {
  return {open: true, groups: [{id: "g1", name: "Foes", allegiance: "enemy",
    summary: "", entries: [], player: false}],
    draft: {group: "g1", allegiance: "enemy", direction: "ahead",
            distance: "near", difficulty: "normal", warp_in: n}};
}
function buttons() {
  const out = [];
  const re = /<button[^>]*>[^<]*<\/button>/g;
  let m;
  while ((m = re.exec(html["qbs-groups"] || ""))) {
    const a = attrs(m[0]);
    const cls = a["class"] || "";
    out.push(mk(cls, a, {disabled: /^<button[^>]*\sdisabled[\s>]/.test(m[0]),
                         text: m[0].replace(/<[^>]*>/g, "")}));
  }
  return out;
}
function pick(which) {
  const bs = buttons();
  if (which === "minus") return bs.filter(b => b.cls === "qbs-qty__btn")[0];
  if (which === "plus") return bs.filter(b => b.cls === "qbs-qty__btn")[1];
  if (which === "value") return bs.filter(b => b.cls.includes("qbs-delay-value"))[0];
  if (which === "input") return document.querySelector(".qbs-delay");
}
function snapshot() {
  const bs = buttons();
  const h = html["qbs-groups"] || "";
  const dirBlock = h.split("Direction</div>")[1].split("Distance</div>")[0];
  const input = /<input class="qbs-delay"/.test(h);
  const val = bs.filter(b => b.cls.includes("qbs-delay-value"))[0];
  return {
    minusDisabled: bs.filter(b => b.cls === "qbs-qty__btn")[0].disabled,
    value: val ? val.text : null,
    hasInput: input,
    inputValue: input ? attrs(/<input class="qbs-delay"[^>]*>/.exec(h)[0]).value : null,
    direction: dirBlock.replace(/<[^>]*>/g, "|").split("|").filter(Boolean),
    directionDisabled: /disabled/.test(dirBlock),
    events: events.slice(),
  };
}

const out = [];
for (const s of JSON.parse(process.argv[2])) {
  if (s.push !== undefined) setQuickBattleSetup(payload(s.push));
  else if (s.click) qbsClick({target: pick(s.click)});
  else if (s.type !== undefined) {
    // The page's own listeners, as wired by renderGroups, on the live input.
    const inp = pick("input"); inp.value = s.type;
    active = inp;
    qbsDelayChange({target: inp});
  }
  else if (s.flush) { while (timers.length) timers.shift()(); }
  if (s.snap) out.push(snapshot());
}
console.log(JSON.stringify(out));
"""


def _run(steps):
    r = subprocess.run([NODE, "-e", _HARNESS, "--", str(JS_PATH), json.dumps(steps)],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


EV = "quick-battle-setup/draft:warp_in:"


def test_minus_disabled_at_zero_enabled_at_one():
    zero, one = _run([{"push": 0, "snap": 1}, {"push": 1, "snap": 1}])
    assert zero["minusDisabled"] is True
    assert one["minusDisabled"] is False


def test_clicking_disabled_minus_at_zero_emits_nothing():
    (s,) = _run([{"push": 0}, {"click": "minus"}, {"snap": 1}])
    assert s["events"] == []


def test_minus_and_plus_emit_adjacent_values():
    (s,) = _run([{"push": 5}, {"click": "minus"}, {"click": "plus"}, {"snap": 1}])
    assert s["events"] == [EV + "4", EV + "6"]


def test_plus_from_zero_emits_one():
    (s,) = _run([{"push": 0}, {"click": "plus"}, {"snap": 1}])
    assert s["events"] == [EV + "1"]


def test_value_reads_start_at_zero_else_minutes():
    zero, five = _run([{"push": 0, "snap": 1}, {"push": 5, "snap": 1}])
    assert zero["value"] == "Start"
    assert five["value"] == "5 min"


def test_clicking_value_swaps_in_the_input_and_sends_nothing():
    before, after = _run([{"push": 5, "snap": 1}, {"click": "value", "snap": 1}])
    assert before["hasInput"] is False
    assert after["hasInput"] is True and after["inputValue"] == "5"
    assert after["value"] is None
    assert after["events"] == []


def test_typed_digits_commit():
    (s,) = _run([{"push": 5}, {"click": "value"}, {"type": "12"}, {"snap": 1}])
    assert s["events"] == [EV + "12"]


@pytest.mark.parametrize("bad", ["abc", "-1", "2.5", "", "  "])
def test_non_whole_minutes_send_nothing_and_restore_the_value(bad):
    (s,) = _run([{"push": 5}, {"click": "value"}, {"type": bad},
                 {"flush": 1, "snap": 1}])
    assert s["events"] == []
    assert s["hasInput"] is False
    assert s["value"] == "5 min"


def test_direction_is_a_disabled_random_while_delayed():
    zero, delayed = _run([{"push": 0, "snap": 1}, {"push": 3, "snap": 1}])
    assert zero["directionDisabled"] is False
    assert zero["direction"] == ["Ahead", "Behind"]
    assert delayed["directionDisabled"] is True
    assert delayed["direction"] == ["Random"]
