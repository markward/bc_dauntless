"""Quick Battle Setup's victory view (layout B), run for real under node.

Executes native/assets/ui-cef/js/quick_battle_setup.js against a minimal fake
DOM (same approach as test_qb_warp_in_stepper_js.py): each element keeps its
own innerHTML and hidden flag, and a click is dispatched straight to qbsClick
with a fake target built from a button in the rendered HTML. The ships view's
renderers are stubbed out.

The victory view draws Python's `setup.victory` payload as two columns,
Victory and Defeat, each a fixed default card, the added conditions and
"+ Add condition".

Spec: docs/superpowers/specs/2026-10-27-quickbattle-condition-stacks-design.md
Look: docs/superpowers/specs/2026-10-27-quickbattle-conditions-mockup.html
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
const rect = () => ({left: 100, right: 200, top: 100, bottom: 120, width: 100, height: 20});
function mk(a, extra) {
  const cls = a["class"] || "";
  const el = Object.assign({
    a: a, cls: cls, disabled: false,
    getAttribute: k => (k in a ? a[k] : null),
    getBoundingClientRect: rect,
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
    style: {}, hidden: id.startsWith("qbs-v") || id === "qbs-menu",
    addEventListener() {}, getBoundingClientRect: rect,
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
global.window = {addEventListener() {}, innerWidth: 1600, innerHeight: 900};
global.setTimeout = () => 0;
global.dauntlessEvent = e => events.push(e);

(0, eval)(fs.readFileSync(process.argv[1], "utf8"));
["renderGroups", "renderEras", "renderSpecies", "renderCatalog", "renderFooter",
 "renderSheet", "renderConfirm", "qbsPresetToast"].forEach(n => { global[n] = () => {}; });

function payload(o) {
  return {open: true, view: o.view || "victory", groups: [], draft: null, can_start: true,
    summary: "", victory: o.victory};
}
function buttons(id) {
  const out = [];
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
function snap() {
  return {
    vcondHidden: ctl("qbs-vcond").hidden,
    groupsHidden: ctl("qbs-groups").hidden, mainHidden: ctl("qbs-main").hidden,
    cogOn: !!(ctl("qbs-victory-btn").on || {})["qbs-victory-btn--on"],
    victory: ctl("qbs-vc-victory").innerHTML, defeat: ctl("qbs-vc-defeat").innerHTML,
    menu: ctl("qbs-menu").innerHTML, menuHidden: ctl("qbs-menu").hidden,
    events: events.slice(),
  };
}

const out = [];
for (const s of JSON.parse(process.argv[2])) {
  if (s.push) setQuickBattleSetup(payload(s.push));
  else if (s.click) {
    // [element id, data-action, data-arg (optional), text (optional)]
    const [id, action, arg, text] = s.click;
    const b = buttons(id).filter(x => x.a["data-action"] === action &&
        (arg == null || x.a["data-arg"] === arg) &&
        (text == null || x.text.includes(text)))[0];
    if (!b) { out.push({missing: s.click}); continue; }
    out.push({clicked: s.click, disabled: b.disabled});
    qbsClick({target: b});
  }
  else if (s.cog) qbsClick({target: mk({"data-action": "victory-view", "class": "cp-done-button"})});
  if (s.snap) out.push(snap());
}
console.log(JSON.stringify(out));
"""


def _run(steps):
    r = subprocess.run([NODE, "-e", _HARNESS, "--", str(JS_PATH), json.dumps(steps)],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    missing = [o for o in out if "missing" in o]
    assert not missing, missing
    return [o for o in out if "clicked" not in o]


def _row(eid, title, group="Cardassians", allegiance="enemy", icon=None):
    return {"id": eid, "title": title, "group_name": group,
            "allegiance": allegiance, "icon": icon}


def _ships(cid, mode="any", ships=(), addable=()):
    return {"id": cid, "kind": "ships", "mode": mode, "minutes": None,
            "ships": list(ships), "addable": list(addable)}


def _timer(cid, minutes=5):
    return {"id": cid, "kind": "timer", "mode": "any", "minutes": minutes,
            "ships": [], "addable": []}


def _victory(vic=(), defeat=(), vic_timer=True, defeat_timer=True):
    return {"stacks": [
        {"side": "victory", "can_add_timer": vic_timer, "conditions": list(vic)},
        {"side": "defeat", "can_add_timer": defeat_timer, "conditions": list(defeat)}]}


def _push(view="victory", **kw):
    return {"push": {"view": view, "victory": _victory(**kw)}}


def _step(step, **extra):
    step = dict(step)
    step.update(extra)
    return step


def _card(html, cid):
    """The markup of one added condition's card, up to the next card."""
    i = html.index('<div class="vc-cond" data-cond="%s">' % cid)
    j = html.find('<div class="vc-cond"', i + 1)
    return html[i:] if j < 0 else html[i:j]


def test_view_toggle_hides_ships_view():
    ships, vic, back = _run([
        _step(_push(view="ships"), snap=1),
        _step(_push(view="victory"), snap=1),
        _step(_push(view="ships"), snap=1)])
    assert ships["vcondHidden"] and not ships["cogOn"]
    assert not ships["groupsHidden"] and not ships["mainHidden"]
    assert not vic["vcondHidden"] and vic["cogOn"]
    assert vic["groupsHidden"] and vic["mainHidden"]
    assert back["vcondHidden"] and not back["cogOn"]
    assert not back["groupsHidden"] and not back["mainHidden"]


def test_cog_click_sends_victory_view():
    (s,) = _run([_push(view="ships"), {"cog": 1, "snap": 1}])
    assert s["events"] == ["quick-battle-setup/victory-view"]


def test_defaults_render_fixed_cards():
    (s,) = _run([_step(_push(), snap=1)])
    v, d = s["victory"], s["defeat"]
    assert ">Victory<" in v and ">Any one of these wins<" in v
    assert ">Defeat<" in d and ">Any one of these loses<" in d
    for col, name in ((v, "Destroy All Ships"), (d, "Player Ship Destroyed")):
        m = re.search(r'<div class="vc-cond vc-cond--fixed">(.*?)</div></div>', col)
        assert m, col
        assert ">%s<" % name in m.group(1) and ">Default<" in m.group(1)
        assert "data-action" not in m.group(1) and "vc-x" not in m.group(1)
        assert "+ Add condition" in col


def test_ships_condition_sentence_agrees():
    any_, all_, win = _run([
        _step(_push(defeat=[_ships("c1", "any")]), snap=1),
        _step(_push(defeat=[_ships("c1", "all")]), snap=1),
        _step(_push(vic=[_ships("c2", "any")]), snap=1)])
    d = any_["defeat"]
    assert ">Ships Destroyed<" in d
    assert "Lose when" in d and "of these is destroyed" in d
    assert re.search(r'<button class="cp-toggle cp-toggle--on"[^>]*>ANY</button>', d)
    assert re.search(r'<button class="cp-toggle"[^>]*>ALL</button>', d)
    a = all_["defeat"]
    assert "of these are destroyed" in a and "of these is destroyed" not in a
    assert re.search(r'<button class="cp-toggle cp-toggle--on"[^>]*>ALL</button>', a)
    assert "Win when" in win["victory"] and "Lose when" not in win["victory"]


def test_ship_rows_with_art_and_remove():
    galor = _row("e3", "Galor", icon="file:///cache/Galor.png")
    s, after = _run([
        _step(_push(vic=[_ships("c1", ships=[galor])]), snap=1),
        {"click": ["qbs-vc-victory", "cond-ship-remove", "c1:e3"], "snap": 1}])
    v = s["victory"]
    assert '<img src="file:///cache/Galor.png"' in v and 'class="qbs-noart' not in v
    assert ">Galor<" in v and ">Cardassians<" in v
    assert "--a: var(--qbs-enemy)" in v
    assert after["events"] == ["quick-battle-setup/cond-ship-remove:c1:e3"]


def test_ship_row_without_icon_says_no_art():
    (s,) = _run([_step(_push(vic=[_ships("c1", ships=[_row("e3", "Galor")])]), snap=1)])
    assert 'class="qbs-noart' in s["victory"] and "<img" not in s["victory"]


def test_payload_strings_are_escaped():
    bad = _row("e3", "<b>Evil</b>", group="A & B")
    (s,) = _run([_step(_push(vic=[_ships("c1", ships=[bad])]), snap=1)])
    assert "<b>Evil</b>" not in s["victory"] and "&lt;b&gt;Evil" in s["victory"]
    assert "A &amp; B" in s["victory"]


def test_mode_toggle_and_remove_send_verbs():
    (s,) = _run([
        _push(defeat=[_ships("c1", "any")]),
        {"click": ["qbs-vc-defeat", "cond-mode", "c1:all"]},
        {"click": ["qbs-vc-defeat", "cond-remove", "c1"], "snap": 1}])
    assert s["events"] == ["quick-battle-setup/cond-mode:c1:all",
                           "quick-battle-setup/cond-remove:c1"]


def test_timer_stepper():
    five, one, sixty, s = _run([
        _step(_push(defeat=[_timer("t1", 5)]), snap=1),
        _step(_push(defeat=[_timer("t1", 1)]), snap=1),
        _step(_push(defeat=[_timer("t1", 60)]), snap=1),
        _push(defeat=[_timer("t1", 5)]),
        {"click": ["qbs-vc-defeat", "cond-minutes", "t1:4"]},
        {"click": ["qbs-vc-defeat", "cond-minutes", "t1:6"], "snap": 1}])
    d = five["defeat"]
    assert ">Timer<" in d and ">5 min<" in d
    assert "Lose when" in d and "run out" in d
    assert s["events"] == ["quick-battle-setup/cond-minutes:t1:4",
                           "quick-battle-setup/cond-minutes:t1:6"]

    def btn(html, sign):
        return re.search(r'<button class="qbs-qty__btn"[^>]*>%s</button>' % sign, html).group(0)
    assert "disabled" in btn(one["defeat"], "−") and "disabled" not in btn(one["defeat"], r"\+")
    assert "disabled" in btn(sixty["defeat"], r"\+") and "disabled" not in btn(sixty["defeat"], "−")
    assert "disabled" not in btn(d, "−") and "disabled" not in btn(d, r"\+")


def test_victory_timer_sentence_says_win():
    (s,) = _run([_step(_push(vic=[_timer("t2", 5)]), snap=1)])
    assert "Win when" in s["victory"] and "run out" in s["victory"]


def test_add_condition_menu():
    menu, no_timer, s = _run([
        _push(),
        {"click": ["qbs-vc-victory", "cond-add-menu"], "snap": 1},
        _push(vic_timer=False),
        {"click": ["qbs-vc-victory", "cond-add-menu"], "snap": 1},
        _push(),
        {"click": ["qbs-vc-victory", "cond-add-menu"]},
        {"click": ["qbs-menu", "cond-add", "victory:ships"], "snap": 1}])
    assert not menu["menuHidden"]
    assert ">Ships Destroyed<" in menu["menu"] and ">Timer<" in menu["menu"]
    assert 'data-arg="victory:timer"' in menu["menu"]
    assert ">Ships Destroyed<" in no_timer["menu"] and "Timer" not in no_timer["menu"]
    assert s["events"] == ["quick-battle-setup/cond-add:victory:ships"]
    assert s["menuHidden"]


def test_add_condition_menu_carries_its_side():
    (s,) = _run([
        _push(),
        {"click": ["qbs-vc-defeat", "cond-add-menu"], "snap": 1}])
    assert 'data-arg="defeat:ships"' in s["menu"] and 'data-arg="defeat:timer"' in s["menu"]


def test_add_ship_menu_lists_addable():
    addable = [_row("e5", "Keldon"), _row("e6", "Freighter", "Civilians", "neutral")]
    menu, s = _run([
        _push(vic=[_ships("c1", addable=addable)]),
        {"click": ["qbs-vc-victory", "cond-ship-menu"], "snap": 1},
        {"click": ["qbs-menu", "cond-ship-add", "c1:e6"], "snap": 1}])
    assert "Keldon" in menu["menu"] and "Freighter" in menu["menu"]
    assert not menu["menuHidden"]
    assert s["events"] == ["quick-battle-setup/cond-ship-add:c1:e6"]


def test_add_ship_menu_empty_says_so():
    (s,) = _run([
        _push(vic=[_ships("c1")]),
        {"click": ["qbs-vc-victory", "cond-ship-menu"], "snap": 1}])
    assert re.search(r'<div class="qbs-menu__empty">No ships to add</div>', s["menu"])
    assert "cond-ship-add" not in s["menu"]


def test_two_conditions_each_render_their_own_card():
    (s,) = _run([_step(_push(defeat=[_ships("c1", "any"), _timer("t1", 7)]), snap=1)])
    d = s["defeat"]
    assert "Ships Destroyed" in _card(d, "c1") and "Timer" not in _card(d, "c1")
    assert ">7 min<" in _card(d, "t1")
