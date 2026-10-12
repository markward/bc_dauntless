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
    if (step.call) vm.runInContext(step.call, ctx);
    out.push({body: el('bridge-emitters-body').innerHTML,
              bar: el('be-bar').innerHTML,
              hint: el('be-hint').textContent,
              dock_display: el('be-dock').style.display,
              hover: el('be-hover').textContent,
              status: el('be-status').textContent,
              settings: el('be-settings').innerHTML,
              root_class: root.className || '',
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


SETTINGS = {"open": False, "has_lights": True, "room_light": [
    {"state": s, "value": 0.0, "source": "default"}
    for s in ("offline", "green", "yellow", "red", "special")]}


def _state(**over):
    st = {"visible": True, "in_bridge": True, "state": "green", "playing": True,
          "dirty": False, "can_save": True, "can_undo": False, "status": "",
          "hint": "Hold Shift: fly", "hover": None, "selected": None,
          "settings": SETTINGS}
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


MAT = {"name": "alcove", "kind": "linked", "used_by": 4,
       "finish": {"roughness": {"value": 1.0, "source": "default"},
                  "metalness": {"value": 0.0, "source": "default"},
                  "emission": {"value": 1.0, "source": "map"}},
       "emission_source": "texture",
       "modifiers": [{"type": "state", "scope": ["red"], "tint": [1, 0.1, 0.1], "level": 0.5},
                     {"type": "animation", "scope": ["red"], "shape": "square",
                      "period_s": 1, "min": 0.2, "duty": 0.5, "soft": 0.1, "phase": 0},
                     {"type": "transition", "scope": ["red"], "seconds": 0.2}]}


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
    assert "material-new" in body and "_beToggleAddLight()" in body
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


def test_material_tab_shows_finish_with_emission_and_the_modifier_stack():
    sel = _sel(tab="material", material="alcove", material_data=MAT, expanded=["mod:1", "mod:2"])
    [out] = _run([{"state": _state(selected=sel)}])
    body = out["body"]
    assert "material-rename:" in body and "finish:roughness:" in body
    # Emission is a Finish row (Mark 2026-10-12), editable over a map.
    assert "finish:emission:" in body and "source: emission map · Map 19_emissive" in body
    i = body.index("finish:emission:")
    assert "disabled" not in body[body.rindex("<input", 0, i):body.index(">", i)]
    assert "emission-source:" not in body          # the map is the source
    assert "Emission</span>" not in body and "fade:" not in body and "strength" not in body
    assert "_beToggleAdd()" in body and "mod-add:emitter" not in body
    assert "expand:mod:0" in body and "mod:0:level:" not in body     # collapsed
    assert "mod:1:duty:" in body and "mod:2:seconds:" in body          # expanded
    assert ">State<" in body and ">Transition (0.2 s)<" in body
    assert "mod:0:scope:red" in body and "mod-remove:0" in body
    assert "<select" not in body


def test_no_material_offers_new_on_the_material_tab():
    [out] = _run([{"state": _state(selected=_sel(tab="material"))}])
    assert "material-new" in out["body"] and "_beToggleAdd()" in out["body"]


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


def test_without_a_map_the_source_chips_follow_the_emission_row():
    fin = dict(MAT["finish"], emission={"value": 0.0, "source": "default"})
    m = dict(MAT, finish=fin, emission_source="flat")
    sel = _sel(tab="material", material="alcove", material_data=m, has_emission_map=False)
    [out] = _run([{"state": _state(selected=sel)}])
    body = out["body"]
    assert "emission-source:texture" in body and "emission-source:flat" in body
    assert body.index("finish:emission:") < body.index("emission-source:texture")
    assert "be-chip active" in body[body.index("emission-source:flat") - 80:
                                    body.index("emission-source:flat")]


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



def _finish_row(body, ch):
    i = body.index(f"<label>{ch}</label>")
    return body[i:body.index("</div>", i)]


def test_a_slider_row_shows_the_value_and_a_pencil_not_a_number_box():
    sel = _sel(tab="material", material="alcove", material_data=MAT)
    [out] = _run([{"state": _state(selected=sel)}])
    row = _finish_row(out["body"], "metalness")
    assert 'type="range"' in row and 'type="number"' not in row
    assert "_beToggleType(" in row and ">0.00<" in row          # the value, as text


def test_the_pencil_swaps_the_slider_for_a_typed_number_and_back():
    sel = _sel(tab="material", material="alcove", material_data=MAT)
    first, typed, back = _run([
        {"state": _state(selected=sel)},
        {"call": "_beToggleType('finish:metalness')"},
        {"call": "_beToggleType('finish:metalness')"}])
    row = _finish_row(typed["body"], "metalness")
    assert 'type="number"' in row and 'type="range"' not in row
    assert "finish:metalness:" in row
    assert 'type="range"' in _finish_row(typed["body"], "roughness")   # only that row
    assert 'type="range"' in _finish_row(back["body"], "metalness")


def test_the_typed_mode_survives_a_payload_refresh():
    sel = _sel(tab="material", material="alcove", material_data=MAT)
    *_, after = _run([{"state": _state(selected=sel)},
                      {"call": "_beToggleType('finish:emission')"},
                      {"state": _state(selected=sel, status="Saved")}])
    assert 'type="number"' in _finish_row(after["body"], "emission")


def test_a_map_driven_row_has_no_pencil():
    fin = dict(MAT["finish"], roughness={"value": 1.0, "source": "map"})
    sel = _sel(tab="material", material="alcove", material_data=dict(MAT, finish=fin))
    [out] = _run([{"state": _state(selected=sel)}])
    row = _finish_row(out["body"], "roughness")
    assert "disabled" in row and "_beToggleType(" not in row


def test_a_state_level_is_a_slider_row_too():
    sel = _sel(tab="material", material="alcove", material_data=MAT, expanded=["mod:0"])
    [out] = _run([{"state": _state(selected=sel)},
                  {"call": "_beToggleType('mod:0:level')"}][:1])
    row = _finish_row(out["body"], "level")
    assert 'type="range"' in row and "_beToggleType('mod:0:level')" in row


def test_add_modifier_is_one_menu_button_until_opened():
    """Blender-style (Mark 2026-10-12): one "Add Modifier" button opens a
    list -- drawn in the page, as CEF OSR shows no <select> popup."""
    sel = _sel(tab="material", material="alcove", material_data=MAT)
    closed, opened, again = _run([{"state": _state(selected=sel)},
                                  {"call": "_beToggleAdd()"},
                                  {"call": "_beToggleAdd()"}])
    assert "Add Modifier" in closed["body"] and "mod-add:state" not in closed["body"]
    body = opened["body"]
    for kind, words in (("state", "Replaces the emission"), ("animation", "Pulses"),
                        ("transition", "Blend time")):
        assert f"mod-add:{kind}" in body and words in body
    assert "<select" not in body
    assert "mod-add:state" not in again["body"]


def test_picking_a_modifier_closes_the_menu():
    sel = _sel(tab="material", material="alcove", material_data=MAT)
    _c, opened = _run([{"state": _state(selected=sel)}, {"call": "_beToggleAdd()"}])
    i = opened["body"].index("mod-add:state")
    onclick = opened["body"][opened["body"].rindex("onclick=", 0, i):opened["body"].index(">", i)]
    assert "_beAddOpen = false" in onclick



# ── Bridge Settings: the cog, bottom right (Mark 2026-10-12) ────────────────

def test_the_cog_shows_closed_settings():
    [out] = _run([{"state": _state()}])
    assert "bridge-emitters/settings-toggle" in out["settings"] and "⚙" in out["settings"]
    assert "room:" not in out["settings"]


def test_open_settings_list_a_room_light_slider_per_state():
    rows = [dict(r) for r in SETTINGS["room_light"]]
    rows[3] = {"state": "red", "value": 0.2, "source": "bridge"}
    settings = dict(SETTINGS, open=True, room_light=rows)
    [out] = _run([{"state": _state(settings=settings)}])
    html = out["settings"]
    assert "Bridge Settings" in html and "Room light" in html
    for s in ("offline", "green", "yellow", "red", "special"):
        assert f"bridge-emitters/room:{s}:" in html and f"_beToggleType('room:{s}')" in html
    assert "room-clear:red" in html and "room-clear:green" not in html   # only set rows
    assert "own lights" in html                       # why the default is 0
    assert "<select" not in html


def test_the_cog_moves_left_of_the_dock_while_it_shows():
    [closed] = _run([{"state": _state()}])
    [docked] = _run([{"state": _state(selected=_sel())}])
    assert "be-has-dock" not in closed["root_class"] and "be-has-dock" in docked["root_class"]


# ── Lights with size (spec §16.4) ───────────────────────────────────────────

def test_add_light_is_one_menu_button_until_opened():
    closed, opened, again = _run([{"state": _state(selected=_sel())},
                                  {"call": "_beToggleAddLight()"},
                                  {"call": "_beToggleAddLight()"}])
    assert "Add Light" in closed["body"] and "light-add:strip" not in closed["body"]
    body = opened["body"]
    for kind, words in (("spot", "cone"), ("strip", "edge"), ("panel", "front")):
        assert f"light-add:{kind}" in body and words in body
    assert "<select" not in body
    assert "light-add:strip" not in again["body"]


def test_picking_a_light_closes_the_menu():
    _c, opened = _run([{"state": _state(selected=_sel())}, {"call": "_beToggleAddLight()"}])
    i = opened["body"].index("light-add:strip")
    onclick = opened["body"][opened["body"].rindex("onclick=", 0, i):opened["body"].index(">", i)]
    assert "_beAddLightOpen = false" in onclick


def test_a_strip_shows_edge_chips_and_start_end_sliders_not_place_and_aim():
    strip = {"shape": "strip", "edge": "left", "start": 0.2, "end": 0.9, "offset": 1,
             "range": 200, "intensity": 40}
    [out] = _run([{"state": _state(selected=_sel(lights=[strip], expanded=["light:0"]))}])
    body = out["body"]
    assert "Strip" in body
    for e in ("top", "bottom", "left", "right"):
        assert f"light:0:edge:{e}" in body
    assert 'be-chip active"' in body.split("light:0:edge:left")[0].rsplit("<button", 1)[1]
    assert "light:0:start" in body and "light:0:end" in body
    assert "light:0:offset:" in body and "light:0:intensity:" in body
    assert "light-place:0" not in body and "light-aim:0" not in body


def test_a_panel_shows_x_and_y_spans():
    panel = {"shape": "panel", "x": [0, 0.5], "y": [0, 1], "offset": 0, "range": 200,
             "intensity": 2}
    [out] = _run([{"state": _state(selected=_sel(lights=[panel], expanded=["light:0"]))}])
    body = out["body"]
    assert "Panel" in body
    for f in ("x0", "x1", "y0", "y1", "offset", "range", "intensity"):
        assert f"light:0:{f}" in body
    assert "light:0:edge:" not in body


def test_a_spot_entry_is_unchanged():
    spot = {"position": [1, 2, 3], "direction": [0, 0, -1], "inner_deg": 30,
            "outer_deg": 60, "range": 200, "intensity": 2000}
    [out] = _run([{"state": _state(selected=_sel(lights=[spot], expanded=["light:0"]))}])
    assert "light-place:0" in out["body"] and "light:0:inner_deg:" in out["body"]
