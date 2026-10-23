"""Quick Battle Setup's victory view, run for real under node.

Executes native/assets/ui-cef/js/quick_battle_setup.js against a minimal fake
DOM (same approach as test_qb_warp_in_stepper_js.py): each element keeps its
own innerHTML and hidden flag, and a click is dispatched straight to qbsClick
with a fake target built from a button in the rendered HTML. The ships view's
renderers are stubbed out.

Spec: docs/superpowers/specs/2026-10-23-quickbattle-victory-conditions-design.md
"""
import json
import re
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
const els = {};
const events = [];
function attrs(tagText) {
  const out = {};
  tagText.replace(/([\w-]+)="([^"]*)"/g, (_, k, v) => { out[k] = v; return ""; });
  return out;
}
function mk(a, extra) {
  const cls = a["class"] || "";
  const el = Object.assign({
    a: a, cls: cls, disabled: false,
    getAttribute: k => (k in a ? a[k] : null),
    closest: sel => (sel === "[data-action]" && "data-action" in a) ? el : null,
    classList: {contains: c => cls.split(" ").includes(c)},
  }, extra || {});
  return el;
}
function ctl(id) {
  if (els[id]) return els[id];
  let inner = "";
  els[id] = {
    set innerHTML(v) { inner = v; }, get innerHTML() { return inner; },
    style: {}, hidden: id.startsWith("qbs-v"), addEventListener() {},
    contains: () => id === "quick-battle-setup",
    classList: {contains: () => false,
                toggle(c, on) { (els[id].on = els[id].on || {})[c] = !!on; }},
  };
  return els[id];
}
global.document = {
  getElementById: ctl, activeElement: null, addEventListener() {},
  querySelector: () => null,
};
global.window = {addEventListener() {}};
global.setTimeout = () => 0;
global.dauntlessEvent = e => events.push(e);

(0, eval)(fs.readFileSync(process.argv[1], "utf8"));
["renderGroups", "renderEras", "renderSpecies", "renderCatalog", "renderFooter",
 "renderSheet", "renderConfirm", "qbsPresetToast"].forEach(n => { global[n] = () => {}; });

function types(km) {
  return [
    {id: "elimination", label: "Elimination", description: "Destroy every enemy to win.",
     available: true, reason: null},
    {id: "kobayashi_maru", label: "Kobayashi Maru", description: "Keep one ship alive",
     available: km, reason: km ? null : "Needs a neutral or friendly ship"},
  ];
}
function payload(o) {
  return {open: true, view: o.view, groups: [], draft: null, can_start: true,
    summary: "", victory: {type: o.type || "elimination", protect: o.protect || null,
      time_limit_min: o.time || 0, rule: "Rule line.", types: types(o.km !== false),
      candidates: [{group: "g2", group_name: "Civilians", allegiance: "neutral",
        entries: [{id: "e7", title: "SS Kobayashi Maru"}]}]}};
}
function buttons(id) {
  const out = [];
  const re = /<(button|div)[^>]*>(?:[^<]*)<\/\1>|<(?:button|div)[^>]*data-action[^>]*>/g;
  const h = ctl(id).innerHTML;
  const tagRe = /<(button|div)\b[^>]*>/g;
  let m;
  while ((m = tagRe.exec(h))) {
    const a = attrs(m[0]);
    const end = h.indexOf("</" + m[1] + ">", m.index);
    out.push(mk(a, {disabled: /\sdisabled[\s>]/.test(m[0]),
                    text: h.slice(m.index, end).replace(/<[^>]*>/g, "")}));
  }
  return out;
}
function find(sel) {
  const [id, what] = sel.split("|");
  const bs = buttons(id);
  if (what.startsWith("action:")) return bs.filter(b => b.a["data-action"] === what.slice(7) && (!what.includes("@") || true))[0];
  return null;
}
function snap() {
  return {
    vtypesHidden: ctl("qbs-vtypes").hidden, vbodyHidden: ctl("qbs-vbody").hidden,
    groupsHidden: ctl("qbs-groups").hidden, mainHidden: ctl("qbs-main").hidden,
    cogOn: !!(ctl("qbs-victory-btn").on || {})["qbs-victory-btn--on"],
    types: ctl("qbs-vtypes").innerHTML, body: ctl("qbs-vbody").innerHTML,
    events: events.slice(),
  };
}

const out = [];
for (const s of JSON.parse(process.argv[2])) {
  if (s.push) setQuickBattleSetup(payload(s.push));
  else if (s.click) {
    const [id, action, arg] = s.click;
    const b = buttons(id).filter(x => x.a["data-action"] === action &&
        (arg === undefined || x.a["data-arg"] === arg))[0];
    if (!b) { out.push({missing: s.click}); continue; }
    qbsClick({target: b});
  }
  else if (s.cog) qbsClick({target: mk({"data-action": "victory-view", "class": "cp-done-button"})});
  else if (s.cardless) {
    const b = buttons(s.cardless).filter(x => x.cls.includes("vc-type") &&
        x.text.includes(s.text))[0];
    out.push({exists: !!b, hasAction: b ? "data-action" in b.a : null});
  }
  if (s.snap) out.push(snap());
}
console.log(JSON.stringify(out));
"""


def _run(steps):
    r = subprocess.run([NODE, "-e", _HARNESS, "--", str(JS_PATH), json.dumps(steps)],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_victory_view_swaps_panes():
    ships, vic, back = _run([
        {"push": {"view": "ships"}, "snap": 1},
        {"push": {"view": "victory"}, "snap": 1},
        {"push": {"view": "ships"}, "snap": 1}])
    assert ships["vtypesHidden"] and ships["vbodyHidden"]
    assert not ships["groupsHidden"] and not ships["mainHidden"]
    assert not ships["cogOn"]
    assert not vic["vtypesHidden"] and not vic["vbodyHidden"]
    assert vic["groupsHidden"] and vic["mainHidden"]
    assert vic["cogOn"]
    assert back["vtypesHidden"] and back["vbodyHidden"]
    assert not back["groupsHidden"] and not back["mainHidden"]


def test_cog_click_sends_victory_view():
    (s,) = _run([{"push": {"view": "ships"}}, {"cog": 1}, {"snap": 1}])
    assert s["events"] == ["quick-battle-setup/victory-view"]


def test_selected_type_card_is_marked_and_click_sends_type():
    (s,) = _run([{"push": {"view": "victory", "type": "elimination"}},
                 {"click": ["qbs-vtypes", "victory-type", "kobayashi_maru"]},
                 {"snap": 1}])
    assert s["events"] == ["quick-battle-setup/victory-type:kobayashi_maru"]
    assert s["types"].count("vc-type--on") == 1
    assert re.search(r'vc-type--on"[^>]*>.*?Elimination', s["types"])


def test_km_greyed_card_shows_reason_and_is_inert():
    card, s = _run([{"push": {"view": "victory", "km": False}},
                    {"cardless": "qbs-vtypes", "text": "Kobayashi"},
                    {"snap": 1}])
    assert card["exists"] and card["hasAction"] is False
    assert "Needs a neutral or friendly ship" in s["types"]
    assert "Keep one ship alive" not in s["types"]
    assert 'data-arg="kobayashi_maru"' not in s["types"]


def test_protect_toggle_sends_verb():
    (s,) = _run([{"push": {"view": "victory", "type": "kobayashi_maru"}},
                 {"click": ["qbs-vbody", "victory-protect", "e7"]},
                 {"snap": 1}])
    assert s["events"] == ["quick-battle-setup/victory-protect:e7"]
    assert "SS Kobayashi Maru" in s["body"]
    assert "qbs-group--neutral" in s["body"]


def test_chosen_protect_is_lit():
    (s,) = _run([{"push": {"view": "victory", "type": "kobayashi_maru", "protect": "e7"},
                  "snap": 1}])
    assert "vc-pick cp-toggle--on" in s["body"]


def test_elimination_body_has_no_protect_or_time_controls():
    (s,) = _run([{"push": {"view": "victory", "type": "elimination"}, "snap": 1}])
    assert "Rule line." in s["body"]
    assert "Ship to protect" not in s["body"] and "Time limit" not in s["body"]


def test_time_stepper_shows_none_then_minutes():
    zero, five, s = _run([
        {"push": {"view": "victory", "type": "kobayashi_maru", "time": 0}, "snap": 1},
        {"push": {"view": "victory", "type": "kobayashi_maru", "time": 5}, "snap": 1},
        {"push": {"view": "victory", "type": "kobayashi_maru", "time": 0}},
    ] + [{"click": ["qbs-vbody", "victory-time", "1"]}, {"snap": 1}])
    assert ">None<" in zero["body"] and "5 min" not in zero["body"]
    assert ">5 min<" in five["body"]
    minus = re.search(r'<button[^>]*data-arg="0"[^>]*>', zero["body"]).group(0)
    assert "disabled" in minus
    assert s["events"] == ["quick-battle-setup/victory-time:1"]
