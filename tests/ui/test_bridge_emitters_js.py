"""Behaviour of bridge_emitters.js's setBridgeEmitters (spec
2026-10-08-bridge-emitters §8), run under node against a minimal fake DOM.

Pins two review findings: a payload (every hover change sends one) must not
rebuild the body while a field inside the dock has focus -- that wiped a
half-typed value -- and the exterior-view message must say how to get to the
bridge, because SPACE is ignored while the editor is open."""
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
const ctx = {document, dauntlessEvent: () => {}, String, Number};
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
              hover: el('be-hover').textContent,
              status: el('be-status').textContent,
              save_disabled: el('be-save').disabled,
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
    st = {"visible": True, "in_bridge": True, "hover": "floor", "dirty": False,
          "can_save": True, "can_undo": False, "status": "",
          "selected": {"key": "7:redalertpanel", "block": 7, "name": "redalertpanel",
                       "display_name": "redalertpanel",
                       "node_chain": ["Scene Root", "Red On GlowAlpha"],
                       "textures": ["redalertpanel.tga"],
                       "material": {"roughness": {"value": 1.0, "source": "default"},
                                    "metalness": {"value": 0.0, "source": "default"}}}}
    st.update(over)
    return st


def test_hover_goes_to_its_own_element_as_text():
    [out] = _run([{"state": _state(hover="<b>panel</b>")}])
    assert out["hover"] == "<b>panel</b>"           # textContent: never parsed
    assert "<b>panel</b>" not in out["body"]
    assert 'id="be-hover"' in out["body"]


def test_a_focused_field_in_the_dock_is_not_rebuilt_but_status_hover_and_buttons_are():
    first, second = _run([
        {"state": _state()},
        {"focus": {"id": "be-num-roughness", "tag": "INPUT", "type": "number"},
         "state": _state(hover="floor 2", status="Saved x.json", can_save=False,
                         selected=dict(_state()["selected"], name="other",
                                       display_name="other", key="9:other"))},
    ])
    assert second["body"] == first["body"]           # the half-typed field survives
    assert second["hover"] == "floor 2"
    assert second["status"] == "Saved x.json"
    assert second["save_disabled"] is True


def test_the_body_rebuilds_again_once_focus_leaves_the_dock():
    _first, _held, after = _run([
        {"state": _state()},
        {"focus": {"id": "be-num-roughness", "tag": "INPUT", "type": "number"},
         "state": _state(selected=dict(_state()["selected"], display_name="other"))},
        {"focus": None,
         "state": _state(selected=dict(_state()["selected"], display_name="other"))},
    ])
    assert "other" in after["body"]


def test_shape_row_shows_the_display_name_escaped():
    sel = dict(_state()["selected"], name="", display_name="(node) <wall> & co")
    [out] = _run([{"state": _state(selected=sel)}])
    assert "(node) &lt;wall&gt; &amp; co" in out["body"]


def test_outside_the_bridge_the_message_says_how_to_get_there():
    [out] = _run([{"state": _state(in_bridge=False)}])
    assert ("Close this, press Space to go to the bridge, then reopen "
            "Bridge Emitters") in out["body"]
    assert out["display"] == "block"


def test_hidden_state_hides_the_root():
    [out] = _run([{"state": {"visible": False}}])
    assert out["display"] == "none"
