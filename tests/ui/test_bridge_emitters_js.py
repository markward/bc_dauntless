"""Behaviour of bridge_emitters.js's setBridgeEmitters (spec
2026-10-08-bridge-emitters §8, §13.3), run under node against a minimal fake
DOM: the top-left bar (the editor's chrome), a dock shown only with a
selection, Object / Material tabs and the modifier stacks.

Pins earlier review findings: a payload (every hover change sends one) must
not rebuild the dock while a field inside it has focus -- that wiped a
half-typed value; the exterior-view message says how to reach the bridge;
and no control is a <select> (CEF OSR draws no popup for it)."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
JS = ROOT / "native/assets/ui-cef/js/bridge_emitters.js"

# A fake DOM just big enough for setBridgeEmitters: elements by id, created on
# demand; `contains` is true for elements flagged as living in the dock.
_HARNESS = r"""
const fs = require('fs');
const vm = require('vm');
const els = {};
function el(id) {
    if (!els[id]) els[id] = {id, innerHTML: '', textContent: '', style: {},
                              disabled: false, tagName: 'DIV', type: '',
                              inDock: false};
    return els[id];
}
const root = el('bridge-emitters-root');
root.contains = (n) => !!(n && n.inDock);
const document = {getElementById: el, activeElement: null, body: el('body')};
const ctx = {document, dauntlessEvent: () => {}, String, Number, Math};
vm.createContext(ctx);
const [jsPath, stepsJson] = process.argv.slice(-2);
vm.runInContext(fs.readFileSync(jsPath, 'utf8'), ctx);
const steps = JSON.parse(stepsJson);
const out = [];
for (const step of steps) {
    if (step.focus !== undefined) {
        if (step.focus === null) { document.activeElement = null; }
        else {
            const f = el(step.focus.id);
            f.tagName = step.focus.tag; f.type = step.focus.type || '';
            f.inDock = true;
            document.activeElement = f;
        }
    }
    if (step.state) ctx.setBridgeEmitters(step.state);
    out.push({body: el('bridge-emitters-body').innerHTML,
              bar: el('be-bar').innerHTML,
              hint: el('be-hint').textContent,
              dock_display: el('be-dock').style.display,
              hover: el('be-hover').textContent,
              status: el('be-status').textContent,
              display: root.style.display});
}
process.stdout.write(JSON.stringify(out));
"""


def _run(steps):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed")
    r = subprocess.run([node, "-e", _HARNESS, "--", str(JS), json.dumps(steps)],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _state(**over):
    st = {"visible": True, "in_bridge": True, "state": "green", "playing": True,
          "dirty": False, "can_save": True, "can_undo": False, "status": "",
          "hint": "Hold Shift: fly", "hover": None, "selected": None}
    st.update(over)
    return st


def _sel(**over):
    s = {"key": "7:p", "block": 7, "name": "p", "display_name": "panel",
         "node_chain": ["Scene Root"], "textures": ["Map 19.tga"], "tab": "object",
         "expanded": [], "has_emission_map": True, "material": None, "linked": False,
         "texture_material": "Map 19",
         "library": [{"name": "alcove", "used_by": 4}], "lights": [], "material_data": None}
    s.update(over)
    return s


MAT = {"name": "alcove", "kind": "linked", "used_by": 4, "finish": {"roughness": {"value": 1.0, "source": "default"},
                                    "metalness": {"value": 0.0, "source": "default"}},
       "emission": {"without_map": "texture", "strength": 1.0}, "fade_s": 0.5,
       "modifiers": [{"type": "emitter", "scope": ["red"], "tint": [1, 0.1, 0.1], "level": 0.5},
                     {"type": "animation", "scope": ["red"], "shape": "square",
                      "period_s": 1, "min": 0.2, "duty": 0.5, "soft": 0.1, "phase": 0}]}


def test_the_bar_carries_the_five_states_preview_and_file_actions():
    [out] = _run([{"state": _state(state="red")}])
    bar = out["bar"]
    for s in ("offline", "green", "yellow", "red", "special"):
        assert f"bridge-emitters/state:{s}" in bar
    assert 'be-state red active' in bar
    for a in ("preview-toggle", "undo", "revert", "save", "close"):
        assert f"bridge-emitters/{a}" in bar
    assert "BRIDGE EDITOR" in bar


def test_the_dock_is_hidden_without_a_selection():
    [out] = _run([{"state": _state()}])
    assert out["dock_display"] == "none"
    [out] = _run([{"state": _state(selected=_sel())}])
    assert out["dock_display"] == "flex"


def test_the_library_is_collapsed_until_its_caret_opens_it():
    [out] = _run([{"state": _state(selected=_sel())}])
    body = out["body"]
    assert "expand:material" in body and "Material: Map 19 (texture)" in body
    assert "material-link:alcove" not in body and "material-new" not in body


def test_object_tab_lists_the_library_and_the_emission_map_row():
    [out] = _run([{"state": _state(selected=_sel(expanded=["material"]))}])
    body = out["body"]
    assert "bridge-emitters/tab:material" in body
    assert "alcove — used by 4 objects" in body and "material-link:alcove" in body
    assert "material-new" in body and "light-add" in body
    assert "Emission map" in body and "steady" in body
    assert "<select" not in body


def test_object_tab_lights_are_indexed_entries():
    light = {"position": [1, 2, 3], "direction": [0, 0, -1], "inner_deg": 30,
             "outer_deg": 60, "range": 200, "intensity": 2000}
    [out] = _run([{"state": _state(selected=_sel(lights=[light, light], expanded=["light:1"]))}])
    body = out["body"]
    assert "expand:light:0" in body and "expand:light:1" in body
    assert "light:1:intensity:" in body and "light:0:intensity:" not in body
    assert "light-place:1" in body and "light-aim:1" in body and "light-remove:0" in body


def test_material_tab_shows_finish_surface_and_the_modifier_stack():
    sel = _sel(tab="material", material="alcove", material_data=MAT, expanded=["mod:1"])
    [out] = _run([{"state": _state(selected=sel)}])
    body = out["body"]
    assert "material-rename:" in body and "finish:roughness:" in body
    # The texture has an emission map: that IS the source, and nothing asks
    # what would glow without one (the TGA is part of the material).
    assert "source: emission map · Map 19_emissive" in body
    assert "emission:without_map" not in body and "without a map" not in body
    assert "emission:strength:" in body and "fade:" in body
    assert "surface" not in body.lower().replace("surface behind", "")
    assert "mod-add:emitter" in body and "mod-add:animation" in body
    assert "expand:mod:0" in body and "mod:0:level:" not in body     # collapsed
    assert "mod:1:duty:" in body and "mod:1:shape:sine" in body       # expanded
    assert "mod:0:scope:red" in body and "mod-remove:0" in body
    assert "<select" not in body


def test_no_material_offers_new_on_the_material_tab():
    [out] = _run([{"state": _state(selected=_sel(tab="material"))}])
    assert "material-new" in out["body"] and "mod-add:emitter" in out["body"]


def test_hover_and_status_are_text():
    [out] = _run([{"state": _state(hover="<b>x</b>", status="<i>s</i>")}])
    assert out["hover"] == "<b>x</b>" and out["status"] == "<i>s</i>"


def test_a_focused_field_in_the_dock_is_not_rebuilt_but_the_bar_is():
    first, second = _run([
        {"state": _state(selected=_sel())},
        {"focus": {"id": "be-rename", "tag": "INPUT", "type": "text"},
         "state": _state(state="red", status="Saved x.json",
                         selected=_sel(display_name="other"))},
    ])
    assert second["body"] == first["body"]           # the half-typed field survives
    assert "be-state red active" in second["bar"]
    assert second["status"] == "Saved x.json"


def test_the_body_rebuilds_again_once_focus_leaves_the_dock():
    _first, _held, after = _run([
        {"state": _state(selected=_sel())},
        {"focus": {"id": "be-rename", "tag": "INPUT", "type": "text"},
         "state": _state(selected=_sel(display_name="other"))},
        {"focus": None, "state": _state(selected=_sel(display_name="other"))},
    ])
    assert "other" in after["body"]


def test_the_object_name_is_escaped():
    [out] = _run([{"state": _state(selected=_sel(display_name="(node) <wall> & co"))}])
    assert "(node) &lt;wall&gt; &amp; co" in out["body"]


def test_outside_the_bridge_the_hint_says_how_to_get_there():
    [out] = _run([{"state": _state(in_bridge=False)}])
    assert "Close this, press Space to go to the bridge, then reopen Bridge Editor" in out["hint"]
    assert out["display"] == "block"


def test_hidden_state_hides_the_root():
    [out] = _run([{"state": {"visible": False}}])
    assert out["display"] == "none"


def test_enter_in_the_rename_field_commits_the_rename():
    # Review M5: text_capture turns Enter into a blur -> `change`; the field
    # must commit on change (the panel contract), not only via the button.
    sel = _sel(tab="material", material="alcove", material_data=MAT)
    [out] = _run([{"state": _state(selected=sel)}])
    i = out["body"].index('id="be-rename"')
    tag = out["body"][out["body"].rindex("<input", 0, i):out["body"].index(">", i)]
    assert "onchange=" in tag and "material-rename:" in tag


def test_without_a_map_the_choice_is_the_source():
    m = dict(MAT, emission={"without_map": "flat", "strength": 1.0})
    sel = _sel(tab="material", material="alcove", material_data=m, has_emission_map=False)
    [out] = _run([{"state": _state(selected=sel)}])
    body = out["body"]
    assert "<label>source</label>" in body and "no emission map" in body
    assert "emission:without_map:texture" in body and "emission:without_map:flat" in body
    assert "without a map" not in body


def test_the_library_does_not_repeat_the_texture_material():
    lib = [{"name": "Map 19", "used_by": 17, "texture": True},
           {"name": "alcove", "used_by": 4, "texture": False}]
    [out] = _run([{"state": _state(selected=_sel(expanded=["material"], library=lib))}])
    body = out["body"]
    assert "material-link:alcove" in body and "material-link:Map 19" not in body
    assert "texture · Map 19" in body


def test_the_unlink_chip_names_the_texture_material():
    [out] = _run([{"state": _state(selected=_sel(expanded=["material"]))}])
    body = out["body"]
    assert "texture · Map 19" in body and "material-link:" in body
    assert "Material: Map 19 (texture)" in body
    assert "material-duplicate" in body                 # split off the texture's material


def test_a_texture_material_says_so_on_the_material_tab():
    m = dict(MAT, name="Map 19", kind="texture", used_by=22)
    sel = _sel(tab="material", material="Map 19", material_data=m)
    [out] = _run([{"state": _state(selected=sel)}])
    assert "texture material · used by 22 objects" in out["body"]
