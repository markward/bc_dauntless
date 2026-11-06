"""The target panel's subsystem picker, run for real under node.

Executes native/assets/ui-cef/panels/ship_display/subsystem_picker.js. The pure
functions are called directly; renderSubsystemPicker gets a fake root whose
querySelector returns fake elements holding innerHTML.

Spec: docs/superpowers/specs/2026-11-05-target-list-and-panel-redesign (task 6)
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
JS_PATH = ROOT / "native/assets/ui-cef/panels/ship_display/subsystem_picker.js"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node not installed")

_HARNESS = r"""
const fs = require("fs");
const events = [];
global.dauntlessEvent = e => events.push(e);
global.window = global;
global.document = {};
(0, eval)(fs.readFileSync(process.argv[1], "utf8"));
function fakeEl() {
  const handlers = {};
  let inner = "";
  const el = {textContent: "", handlers, sets: 0,
    get innerHTML() { return inner; },
    set innerHTML(v) { inner = v; el.sets++; },
    addEventListener(t, f) { handlers[t] = f; }};
  return el;
}
function fakeRoot() {
  const host = fakeEl(), layer = fakeEl();
  return {host, layer, querySelector(sel) {
    if (sel === '[data-bind="subsystems"]') return host;
    if (sel === '[data-bind="lock-layer"]') return layer;
    return null;
  }};
}
function tgt(attrs) {
  return {closest(sel) {
    const m = /^\[([\w-]+)\]$/.exec(sel);
    return m && (m[1] in attrs) ? {getAttribute: k => attrs[k]} : null;
  }};
}
const calls = JSON.parse(process.argv[2]);
const out = eval("(function(){" + calls + "})()");
console.log(JSON.stringify(out));
"""


def _run(body):
    r = subprocess.run([NODE, "-e", _HARNESS, "--", str(JS_PATH), body],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def _js(expr_body):
    return _run(json.dumps(expr_body))


def test_family_columns():
    assert _js("return [6,7,8,9,10,3].map(pickerFamilyColumns);") == [6, 8, 8, 6, 6, 6]


def test_member_columns():
    assert _js("return [1,2,3,8,0].map(pickerMemberColumns);") == [1, 2, 3, 3, 1]


def test_caption_priority():
    assert _js("""return [
      pickerCaption({open_family:'A', locked:'B'}, 'H'),
      pickerCaption({open_family:'A', locked:'B'}, null),
      pickerCaption({open_family:null, locked:'B'}, null),
      pickerCaption({open_family:null, locked:null}, null)];""") == ["H", "A", "B", ""]


_STATE = """
var cannons = {name:'Disruptor Cannons', lockable:false, state:'healthy', 
  x_px:0, y_px:0, members:[{name:'Port Cannon 2', state:'healthy'},
  {name:'Star Cannon 1', state:'healthy'}, {name:'Star Cannon 2', state:'healthy'}]};
var beam = {name:'Disruptor Beam', lockable:false, state:'healthy', members:[{name:'Disruptor', state:'healthy'}]};
var phasers = {name:'Phasers', lockable:true, state:'healthy', members:[{name:'Dorsal 1', state:'healthy'},{name:'Dorsal 2', state:'healthy'}]};
var hull = {name:'Hull', lockable:true, state:'healthy', members:[]};
var impulse = {name:'Impulse', lockable:false, state:'healthy', members:[{name:'Impulse Port', state:'healthy'},{name:'Impulse Star', state:'healthy'}]};
function st(locked){ return {ship:'Warbird 1', families:[cannons,beam,phasers,hull,impulse], open_family:null, locked:locked||null}; }
"""


def _click(code):
    return _js(_STATE + code)


def test_double_click_family_with_members():
    r = _click("var a=pickerClick(st(),'family','Disruptor Cannons',1000,{name:null,t:0});"
               "var b=pickerClick(st(),'family','Disruptor Cannons',1200,a.last);"
               "var c=pickerClick(st(),'family','Disruptor Cannons',1300,b.last);"
               "return [b.events, c.events];")
    assert r[0] == ["ship-target/show/Disruptor Cannons", "target/Warbird 1/Port Cannon 2"]
    # double consumed last: a third quick click is single again (2+ members -> open)
    assert r[1] == ["ship-target/open/Disruptor Cannons"]


def test_double_click_no_members():
    r = _click("var a=pickerClick(st(),'family','Hull',1000,{name:null,t:0});"
               "return pickerClick(st(),'family','Hull',1100,a.last).events;")
    # a single subsystem closes whatever family was open (mockup v54)
    assert r == ["ship-target/close", "target/Warbird 1/Hull"]


def test_single_click_lockable_with_members():
    r = _click("return [pickerClick(st(),'family','Phasers',0,{name:null,t:0}).events,"
               "pickerClick(st('Phasers'),'family','Phasers',0,{name:null,t:0}).events];")
    assert r == [["ship-target/show/Phasers", "target/Warbird 1/Phasers"], ["target/Warbird 1"]]


def test_single_click_one_member():
    r = _click("return [pickerClick(st(),'family','Disruptor Beam',0,{name:null,t:0}).events,"
               "pickerClick(st('Disruptor'),'family','Disruptor Beam',0,{name:null,t:0}).events];")
    assert r == [["ship-target/show/Disruptor Beam", "target/Warbird 1/Disruptor"],
                 ["target/Warbird 1"]]


def test_single_click_two_plus_members_opens():
    r = _click("return pickerClick(st(),'family','Impulse',0,{name:null,t:0}).events;")
    assert r == ["ship-target/open/Impulse"]


def test_single_click_no_members():
    r = _click("return [pickerClick(st(),'family','Hull',0,{name:null,t:0}).events,"
               "pickerClick(st('Hull'),'family','Hull',0,{name:null,t:0}).events];")
    # locking or unlocking a single subsystem closes the open family: the
    # member blocks of a family the lock has left must not stay on screen
    assert r == [["ship-target/close", "target/Warbird 1/Hull"],
                 ["ship-target/close", "target/Warbird 1"]]


def test_member_click_toggles():
    r = _click("return [pickerClick(st(),'member','Dorsal 1',0,{name:null,t:0}).events,"
               "pickerClick(st('Dorsal 1'),'member','Dorsal 1',0,{name:null,t:0}).events];")
    assert r == [["target/Warbird 1/Dorsal 1"], ["target/Warbird 1"]]


def test_slow_clicks_are_two_singles():
    r = _click("var a=pickerClick(st(),'family','Disruptor Cannons',1000,{name:null,t:0});"
               "return pickerClick(st(),'family','Disruptor Cannons',1400,a.last).events;")
    assert r == ["ship-target/open/Disruptor Cannons"]


def test_constant():
    assert _js("return PICKER_DOUBLE_CLICK_MS;") == 350


_AKIRA = """
function fam(n, st, ms, x, y) { return {name:n, state:st||'healthy', icon_key:'k1',
  lockable:false, x_px:x||0, y_px:y||0, members:ms||[]}; }
function mem(n, st, x, y) { return {name:n, state:st||'healthy', icon_key:'k1', x_px:x||0, y_px:y||0}; }
function akira(extra) {
  var fams = [fam('Phasers','healthy',[mem('Dorsal Phaser 2','healthy',54,30), mem('Dorsal Phaser 1','damaged',60,30)]),
    fam('Impulse','disabled'), fam('Warp'), fam('Sensors'), fam('Shields'), fam('Hull'), fam('Cloak'), fam('Tractors')];
  var s = Object.assign({ship_name:'Akira 1', families:fams, icons:{k1:'<svg id="G"/>'}, open_family:null, locked:null}, extra||{});
  return s;
}
"""


def _render(code):
    return _js(_AKIRA + "var root = fakeRoot();" + code)


def test_render_columns_and_buttons():
    r = _render("renderSubsystemPicker(root, akira()); var h1 = root.host.innerHTML;"
                "var s = akira(); s.families = s.families.concat([fam('A'),fam('B'),fam('C')]);"
                "var r2 = fakeRoot(); renderSubsystemPicker(r2, s); return [h1, r2.host.innerHTML];")
    assert r[0].count('<button') == 8
    assert "--cols:8" in r[0]
    assert "--cols:6" in r[1]


def test_render_states_and_locked():
    h = _render("renderSubsystemPicker(root, akira({locked:'Dorsal Phaser 2', open_family:'Phasers'}));"
                "return root.host.innerHTML;")
    assert 'data-state="disabled"' in h
    assert "subsys-btn--locked" in h
    assert "subsys-block--locked" in h
    assert "--member-cols:2" in h
    assert h.count('data-member=') == 2
    assert 'class="subsys-caption"' in h


def test_name_bar_empty_when_nothing():
    h = _render("renderSubsystemPicker(root, akira()); return root.host.innerHTML;")
    assert '<div class="subsys-caption"></div>' in h


def test_lock_marker_position():
    h = _render("renderSubsystemPicker(root, akira({locked:'Dorsal Phaser 2'}));"
                "return root.layer.innerHTML;")
    assert "lock-marker" in h
    assert "left:42.19%" in h and "top:23.44%" in h


def test_no_marker_without_position():
    h = _render("renderSubsystemPicker(root, akira({locked:'Impulse'})); return root.layer.innerHTML;")
    assert "lock-marker" not in h


def test_no_marker_when_not_locked():
    assert _render("renderSubsystemPicker(root, akira()); return root.layer.innerHTML;") == ""


def test_hover_updates_caption_without_rerender():
    r = _render("renderSubsystemPicker(root, akira());"
                "var before = root.host.innerHTML;"
                "var capEl = {textContent:''};"
                "root.host.querySelector = function(){ return capEl; };"
                "root.host.handlers.mouseover({target: tgt({'data-btn':'Phasers'})});"
                "var t1 = capEl.textContent;"
                "root.host.handlers.mouseleave();"
                "return [t1, capEl.textContent, before === root.host.innerHTML];")
    assert r == ["Phasers", "", True]


def test_quotes_in_names_survive():
    r = _render("""
      var s = akira(); s.families = [fam("O'Brien \\"X\\"", 'healthy', [mem("Q'1"), mem('Q"2')])];
      s.open_family = "O'Brien \\"X\\""; s.ship_name = "Ship's \\"Name\\"";
      renderSubsystemPicker(root, s);
      var h = root.host.innerHTML;
      root.host.handlers.click({target: tgt({'data-member': "Q'1"})});
      return [h, events.slice()];""")
    assert "O&#39;Brien &quot;X&quot;" in r[0] or "O&#x27;Brien" in r[0]
    assert "'" not in r[0].split('data-btn="')[1].split('"')[0]
    assert r[1] == ['target/Ship\'s "Name"/Q\'1']


def test_identical_picker_fields_skip_rebuild_and_keep_hover():
    r = _render("""
      var s = akira({speed_kph: 100});
      renderSubsystemPicker(root, s);
      var capEl = {textContent:''};
      root.host.querySelector = function(){ return capEl; };
      root.host.handlers.mouseover({target: tgt({'data-btn':'Phasers'})});
      var sets = [root.host.sets, root.layer.sets];
      renderSubsystemPicker(root, akira({speed_kph: 250, range_km: 3}));
      return [sets, [root.host.sets, root.layer.sets], root.host._pickerHover, capEl.textContent];""")
    assert r[0] == r[1]
    assert r[2] == "Phasers" and r[3] == "Phasers"


def test_changed_locked_rebuilds():
    r = _render("""
      renderSubsystemPicker(root, akira());
      var before = [root.host.sets, root.layer.sets];
      renderSubsystemPicker(root, akira({locked:'Dorsal Phaser 2'}));
      return [before, [root.host.sets, root.layer.sets]];""")
    assert r[1][0] == r[0][0] + 1 and r[1][1] == r[0][1] + 1


def test_ship_change_resets_double_click_memory():
    r = _render("""
      renderSubsystemPicker(root, akira({ship_name:'A'}));
      root.host.handlers.click({target: tgt({'data-btn':'Phasers'})});
      renderSubsystemPicker(root, akira({ship_name:'B'}));
      root.host.handlers.click({target: tgt({'data-btn':'Phasers'})});
      return events.slice();""")
    assert r == ["ship-target/open/Phasers", "ship-target/open/Phasers"]


def test_hover_rules_keep_gradients_and_tints():
    css = (ROOT / "native/assets/ui-cef/panels/ship_display/ship_display.css").read_text()
    import re
    for sel in (".subsys-btn:hover", ".subsys-block:hover"):
        m = re.search(re.escape(sel) + r"\s*\{([^}]*)\}", css)
        assert m, sel
        assert "background:" not in m.group(1).replace("background-color:", ""), sel


def test_buttons_and_marker_render_glyphs_from_icons_table():
    r = _render("renderSubsystemPicker(root, akira({locked:'Dorsal Phaser 2'}));"
                "return [root.host.innerHTML, root.layer.innerHTML];")
    assert r[0].count('<svg id="G"/>') == 8
    assert '<svg id="G"/>' in r[1]


def test_missing_icon_key_renders_empty_glyph():
    r = _render("renderSubsystemPicker(root, akira({locked:'Dorsal Phaser 2', icons:{}}));"
                "return [root.host.innerHTML, root.layer.innerHTML];")
    assert '<span class="subsys-btn__icon"></span>' in r[0]
    assert "lock-marker" in r[1]
    r = _render("var s = akira({locked:'Dorsal Phaser 2'}); delete s.icons;"
                "renderSubsystemPicker(root, s); return root.host.innerHTML;")
    assert "subsys-btn__icon" in r


def test_icons_change_rebuilds():
    r = _render("""
      renderSubsystemPicker(root, akira());
      var n = root.host.sets;
      renderSubsystemPicker(root, akira({icons:{k1:'<svg id="H"/>'}}));
      return [n, root.host.sets, root.host.innerHTML.indexOf('id="H"') >= 0];""")
    assert r[1] == r[0] + 1 and r[2] is True


def test_member_at_origin_still_locks_without_marker():
    r = _render("""
      var s = akira({families:[fam('Phasers','healthy',[mem('Zero')])]});
      renderSubsystemPicker(root, s);
      root.host.handlers.click({target: tgt({'data-member': 'Zero'})});
      var ev = events.slice();
      renderSubsystemPicker(root, Object.assign({}, s, {locked:'Zero'}));
      return [ev, root.layer.innerHTML];""")
    assert r[0] == ["target/Akira 1/Zero"]
    assert "lock-marker" not in r[1]


def test_open_and_locked_tint_survives_hover():
    css = (ROOT / "native/assets/ui-cef/panels/ship_display/ship_display.css").read_text()
    import re
    for sel in (".subsys-btn--open:hover", ".subsys-block--locked:hover"):
        m = re.search(re.escape(sel) + r"\s*\{([^}]*)\}", css)
        assert m, sel
        assert "background-color: rgba(216, 43, 43, 0.35)" in m.group(1), sel
        assert "background:" not in m.group(1).replace("background-color:", ""), sel
    # Disabled still wins: its hover rule is more specific than the tints.
    assert '.subsys-btn[data-state="disabled"]:hover' in css
    assert '.subsys-block[data-state="disabled"]:hover' in css
