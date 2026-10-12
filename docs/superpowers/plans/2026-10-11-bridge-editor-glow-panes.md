# Bridge Editor Glow + Profile Panes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Edit a shape's glow and its profile (per-alert colour, level, pulse, fade, phase) in the Bridge Editor, previewing each alert state live with pulses running while the game is paused.

**Architecture:** The panel (`engine/ui/bridge_emitters_panel.py`) gains glow/profile actions that edit the live document through one generic `_edit` helper (snapshot → mutate → keep the snapshot only if something changed) and push through `BridgeRuntime` as every edit already does. The panel also owns two preview values — the state tab (an alert level) and a play/pause flag — which the host loop reads through two pure helpers to drive everything alert-dependent and the bridge clock. The SPV's canvas hue/saturation wheel moves to a shared `js/colour_wheel.js` used by both panels.

**Tech Stack:** Python 3.11 (pytest), plain browser JS in CEF (node-run tests with a fake DOM).

**Spec:** `docs/superpowers/specs/2026-10-08-bridge-emitters-spike-design.md` §12 (and §8, §11).

## Global Constraints

- Worktree `/Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/dbridge-round7`, branch `feat/dbridge-round7`.
- ⛔ Never `git checkout -- <path>` / `git checkout .` / `git restore` / `git stash` / `git clean` / `git reset --hard` / `git add -A` / `git add .`. Explicit pathspecs only.
- The production render path must not change when the editor is closed: `preview_alert()` returns None and `preview_dt` returns the player dt.
- Values entering the document are clamped to the schema's ranges (§12.3): level ≥ 0, `period_s` ≥ 0.05, `min`/`duty`/`soft`/`phase` in [0, 1], `fade_s` ≥ 0, `scale` ≥ 0, tint channels ≥ 0 with max channel 1.
- A tint from the wheel is V = 1: the panel normalises any tint it writes so its max channel is 1.
- CEF OSR: no native tooltips (`title=` is a no-op), no native colour popup.
- Commit trailer: `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
- Done = `scripts/check_tests.sh` (with `DAUNTLESS_GAME_DIR="/Users/mward/Documents/Star Trek Bridge Commander/game"`) exits 0.

## Review Focus

1. **A body rebuild during a wheel drag** (a payload arrives every hover change) must not destroy the wheel mid-drag — Task 4 `_beEditingInDock` covers `_beWheel.dragging`.
2. **Renaming a profile used by several shapes** moves every reference; a rename to an existing or empty name is refused with a status — Task 2 `test_rename_moves_every_reference_and_refuses_clashes`.
3. **Switching a wave from square to sine** drops `duty`/`soft` so the saved document still validates — Task 2 `test_wave_shape_switch_keeps_the_document_valid`.
4. **Closing the editor** returns the bridge to the player's alert and the paused-aware clock — Task 3 `test_preview_is_none_and_dt_is_the_players_when_closed`.
5. **A shape with no profile** shows the tabs (preview) but no state editor, and state actions on it are ignored — Task 2 `test_state_edits_need_a_profile`.

---

### Task 1: Shared colour wheel

**Files:**
- Create: `native/assets/ui-cef/js/colour_wheel.js`
- Modify: `native/assets/ui-cef/js/ship_property_viewer.js` (replace `spvHsToRgb`, `spvRgbToHs`, `_spvWheelBase`, `spvDrawWheel` body, `_spvSetHueSatFromEvent`, the three pointer handlers and the wiring IIFE)
- Modify: `native/assets/ui-cef/index.html` (script tag before `ship_property_viewer.js`)
- Test: `tests/ui/test_colour_wheel_js.py`

**Interfaces:**
- Produces (global functions/constructor in the page):
  - `colourHsToRgb(hue, sat) -> [r, g, b]` (V = 1)
  - `colourRgbToHs([r, g, b]) -> {hue, sat}`
  - `new ColourWheel(canvas, {hue, sat}, onChange)`; `onChange({hue, sat}, final)` — `final` is true on pointer release; `.dragging` (bool); `.setHs(hue, sat)`; `.draw()`.

- [ ] **Step 1: Write the failing test** — `tests/ui/test_colour_wheel_js.py`:

```python
"""Shared hue/saturation wheel (spec 2026-10-08-bridge-emitters §12.4)."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
JS = ROOT / "native/assets/ui-cef/js/colour_wheel.js"
HTML = ROOT / "native/assets/ui-cef/index.html"
SPV = ROOT / "native/assets/ui-cef/js/ship_property_viewer.js"

_HARNESS = r"""
const fs = require('fs'); const vm = require('vm');
const ctx = {Math, document: {getElementById: () => null}};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[process.argv.length - 1], 'utf8'), ctx);
const out = {
  red: ctx.colourHsToRgb(0, 1), green: ctx.colourHsToRgb(120, 1),
  white: ctx.colourHsToRgb(200, 0), orange: ctx.colourRgbToHs([1, 0.5, 0]),
  round: ctx.colourRgbToHs(ctx.colourHsToRgb(250, 0.4)),
  black: ctx.colourRgbToHs([0, 0, 0]),
};
process.stdout.write(JSON.stringify(out));
"""


def _run():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed")
    r = subprocess.run([node, "-e", _HARNESS, "--", str(JS)], capture_output=True,
                       text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_hs_rgb_conversions():
    out = _run()
    assert out["red"] == pytest.approx([1, 0, 0])
    assert out["green"] == pytest.approx([0, 1, 0])
    assert out["white"] == pytest.approx([1, 1, 1])
    assert out["orange"]["hue"] == pytest.approx(30)
    assert out["orange"]["sat"] == pytest.approx(1)
    assert out["round"]["hue"] == pytest.approx(250)
    assert out["round"]["sat"] == pytest.approx(0.4)
    assert out["black"] == {"hue": 0, "sat": 0}


def test_the_page_loads_the_wheel_before_its_users():
    html = HTML.read_text()
    w = html.index('src="js/colour_wheel.js"')
    assert w < html.index('src="js/ship_property_viewer.js"')
    assert w < html.index('src="js/bridge_emitters.js"')


def test_the_spv_no_longer_carries_its_own_wheel():
    src = SPV.read_text()
    for gone in ("function spvHsToRgb", "function spvRgbToHs", "_spvWheelBase",
                 "_spvSetHueSatFromEvent"):
        assert gone not in src
    assert "new ColourWheel(" in src
```

- [ ] **Step 2: Run, watch fail** — `uv run pytest tests/ui/test_colour_wheel_js.py -q` → FAIL (file missing / script tag missing / SPV still has its wheel).

- [ ] **Step 3: Implement**

`native/assets/ui-cef/js/colour_wheel.js`:

```javascript
// Shared hue/saturation colour wheel (spec 2026-10-08-bridge-emitters §12.4),
// moved from ship_property_viewer.js. CEF OSR shows no native colour popup,
// so a canvas wheel is the working control. Hue = angle, saturation =
// radius, V = 1 always: brightness lives in a separate control (the SPV's
// intensity, the Bridge Editor's level).

function colourHsToRgb(hue, sat) {
    var h = ((hue % 360) + 360) % 360;
    var s = Math.max(0, Math.min(1, sat));
    var c = s;
    var x = c * (1 - Math.abs((h / 60) % 2 - 1));
    var m = 1 - c;
    var r, g, b;
    if (h < 60)       { r = c; g = x; b = 0; }
    else if (h < 120) { r = x; g = c; b = 0; }
    else if (h < 180) { r = 0; g = c; b = x; }
    else if (h < 240) { r = 0; g = x; b = c; }
    else if (h < 300) { r = x; g = 0; b = c; }
    else              { r = c; g = 0; b = x; }
    return [r + m, g + m, b + m];
}

function colourRgbToHs(rgb) {
    var r = rgb[0] || 0, g = rgb[1] || 0, b = rgb[2] || 0;
    var max = Math.max(r, g, b), min = Math.min(r, g, b);
    var d = max - min;
    var h = 0;
    if (d > 1e-6) {
        if (max === r) h = 60 * (((g - b) / d) % 6);
        else if (max === g) h = 60 * ((b - r) / d + 2);
        else h = 60 * ((r - g) / d + 4);
    }
    if (h < 0) h += 360;
    var sat = (max > 1e-6) ? d / max : 0;
    return {hue: h, sat: Math.max(0, Math.min(1, sat))};
}

// Base discs cached per canvas size; only the marker redraws per interaction.
var _colourWheelDiscs = {};

function ColourWheel(canvas, hs, onChange) {
    this.canvas = canvas;
    this.hue = hs.hue;
    this.sat = hs.sat;
    this.onChange = onChange || null;
    this.dragging = false;
    var self = this;
    canvas.addEventListener('pointerdown', function (e) {
        canvas.setPointerCapture(e.pointerId);
        self.dragging = true;
        self._fromEvent(e, false);
    });
    canvas.addEventListener('pointermove', function (e) {
        if (self.dragging) self._fromEvent(e, false);
    });
    canvas.addEventListener('pointerup', function (e) {
        if (!self.dragging) return;
        self.dragging = false;
        self._fromEvent(e, true);
    });
    this.draw();
}

ColourWheel.prototype._fromEvent = function (e, final) {
    var rect = this.canvas.getBoundingClientRect();
    var cx = rect.left + rect.width / 2, cy = rect.top + rect.height / 2;
    var R = Math.min(rect.width, rect.height) / 2 - 4;
    var dx = e.clientX - cx, dy = e.clientY - cy;
    var angle = Math.atan2(dy, dx) * 180 / Math.PI;
    if (angle < 0) angle += 360;
    this.hue = angle;
    this.sat = Math.max(0, Math.min(1, Math.sqrt(dx * dx + dy * dy) / R));
    this.draw();
    if (this.onChange) this.onChange({hue: this.hue, sat: this.sat}, final);
};

ColourWheel.prototype.setHs = function (hue, sat) {
    this.hue = hue;
    this.sat = sat;
    this.draw();
};

ColourWheel.prototype.draw = function () {
    var ctx = this.canvas.getContext('2d');
    var w = this.canvas.width, h = this.canvas.height;
    var cx = w / 2, cy = h / 2, R = Math.min(cx, cy) - 4;
    var key = w + 'x' + h;
    if (!_colourWheelDiscs[key]) {
        var img = ctx.createImageData(w, h);
        for (var y = 0; y < h; y++) {
            for (var x = 0; x < w; x++) {
                var dx = x - cx, dy = y - cy;
                var dist = Math.sqrt(dx * dx + dy * dy);
                var idx = (y * w + x) * 4;
                if (dist > R) { img.data[idx + 3] = 0; continue; }
                var angle = Math.atan2(dy, dx) * 180 / Math.PI;
                if (angle < 0) angle += 360;
                var rgb = colourHsToRgb(angle, Math.min(1, dist / R));
                img.data[idx]     = Math.round(rgb[0] * 255);
                img.data[idx + 1] = Math.round(rgb[1] * 255);
                img.data[idx + 2] = Math.round(rgb[2] * 255);
                img.data[idx + 3] = 255;
            }
        }
        _colourWheelDiscs[key] = img;
    }
    ctx.putImageData(_colourWheelDiscs[key], 0, 0);
    var rad = this.hue * Math.PI / 180;
    var r = this.sat * R;
    var mx = cx + Math.cos(rad) * r, my = cy + Math.sin(rad) * r;
    ctx.beginPath(); ctx.arc(mx, my, 5, 0, Math.PI * 2);
    ctx.strokeStyle = '#fff'; ctx.lineWidth = 2; ctx.stroke();
    ctx.beginPath(); ctx.arc(mx, my, 3, 0, Math.PI * 2);
    ctx.strokeStyle = '#000'; ctx.lineWidth = 1; ctx.stroke();
};
```

`ship_property_viewer.js`: delete `spvHsToRgb`, `spvRgbToHs`, `_spvWheelBase`, the body of `spvDrawWheel`, `_spvSetHueSatFromEvent`, `_spvWheelDragging`, `_spvWheelPointerDown/Move/Up`, and the `_spvWireEmitterWheel` IIFE (keep the comments that describe the modal). Put in their place:

```javascript
// The hue/sat wheel is the shared ColourWheel (js/colour_wheel.js).
var _spvWheel = null;
(function _spvWireEmitterWheel() {
    var canvas = document.getElementById('spv-emitter-wheel');
    if (!canvas || typeof ColourWheel === 'undefined') return;
    _spvWheel = new ColourWheel(canvas, {hue: 40, sat: 0.3}, function (hs) {
        if (!spvEmitter) return;
        spvEmitter.hue = hs.hue;
        spvEmitter.sat = hs.sat;
    });
})();

function spvDrawWheel() {
    if (_spvWheel && spvEmitter) _spvWheel.setHs(spvEmitter.hue, spvEmitter.sat);
}
```

and replace the two remaining calls: `spvRgbToHs(` → `colourRgbToHs(`, `spvHsToRgb(` → `colourHsToRgb(`.

`index.html`: add `    <script src="js/colour_wheel.js"></script>` on the line before `    <script src="js/ship_property_viewer.js"></script>`.

- [ ] **Step 4: Run** — `uv run pytest tests/ui/test_colour_wheel_js.py tests/ui -q -k "spv or colour or bridge_emitters"` → pass. Then `grep -n "spvHsToRgb\|spvRgbToHs" -r native/assets/ui-cef` → no output.

- [ ] **Step 5: Commit**

```bash
git add native/assets/ui-cef/js/colour_wheel.js native/assets/ui-cef/js/ship_property_viewer.js native/assets/ui-cef/index.html tests/ui/test_colour_wheel_js.py
git commit -m "refactor(ui): share the SPV hue/saturation wheel as js/colour_wheel.js (spec §12.4)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Panel actions and payload for glow and profiles

**Files:**
- Modify: `engine/ui/bridge_emitters_panel.py`
- Test: `tests/unit/test_bridge_emitters_panel.py`

**Interfaces:**
- Consumes: `ld.GLOW_SRCS`, `profiles.STATES`, `profiles.STEADY_WHITE`, `profiles.DEFAULT_FADE_S`.
- Produces — actions (`dispatch_event`, after the `bridge-emitters/` prefix):
  `glow-on`, `glow-off`, `glow:src:<src>`, `glow:scale:<v>`, `profile-select:<name or empty>`, `profile-new`, `profile-rename:<name>`, `tab:<green|yellow|red>`, `preview-toggle`, `state-on:<s>`, `state-off:<s>`, `state:<s>:tint:<r>,<g>,<b>`, `state:<s>:level:<v>`, `state:<s>:wave:<shape|period_s|min|duty|soft>:<v>`, `fade:<v>`, `phase:<v>`.
- Produces — payload: `selected` gains `glow` (dict or None), `has_emissive_map` (bool), `profile` (name or None), `profile_data` (dict copy or None), `phase` (float); the state gains `profiles` (`[{name, used_by}]`, sorted by name), `tab` (state name), `preview_playing` (bool).
- Produces — constructor kwarg `alert_provider=None` (callable → alert level; picks the tab on open).

- [ ] **Step 1: Write the failing tests** — append to `tests/unit/test_bridge_emitters_panel.py`:

```python
# ── Glow + profile panes (spec §12) ─────────────────────────────────────────

def _open_on_panel(env_rt):
    p, io, h, *_ , rt = env_rt
    p.open()
    click(p, h, (400.0, 300.0))          # selects mesh 1, block 7 "redalertpanel"
    return p, rt


def _em(p):
    return p._doc["shapes"]["7:redalertpanel"]["emitter"]


def test_glow_on_off_and_source(env_rt):
    p, rt = _open_on_panel(env_rt)
    p.dispatch_event("glow-on")
    assert _em(p)["glow"] == {"src": "texture"}          # no _emissive map on mesh 1
    p.dispatch_event("glow:src:emissive")                 # refused: no map
    assert _em(p)["glow"]["src"] == "texture"
    p.dispatch_event("glow:src:flat")
    p.dispatch_event("glow:scale:-3")
    assert _em(p)["glow"] == {"src": "flat", "scale": 0.0}
    p.dispatch_event("glow-off")
    assert "7:redalertpanel" not in p._doc["shapes"]      # emitter and entry left empty
    assert payload(p)["selected"]["glow"] is None


def test_profile_new_select_and_used_by(env_rt):
    p, rt = _open_on_panel(env_rt)
    p.dispatch_event("profile-new")
    assert _em(p)["profile"] == "profile 1"
    assert p._doc["profiles"]["profile 1"]["green"] == {"tint": [1, 1, 1], "level": 1}
    st = payload(p)
    assert st["profiles"] == [{"name": "profile 1", "used_by": 1}]
    assert st["selected"]["profile"] == "profile 1"
    p.dispatch_event("profile-new")                       # copies the current one
    assert _em(p)["profile"] == "profile 2"
    p.dispatch_event("profile-select:")
    assert "7:redalertpanel" not in p._doc["shapes"]
    assert [x["used_by"] for x in payload(p)["profiles"]] == [0, 0]


def test_rename_moves_every_reference_and_refuses_clashes(env_rt):
    p, rt = _open_on_panel(env_rt)
    p.dispatch_event("profile-new")
    ld.shape_entry(p._doc, 3, "floor")["emitter"] = {"profile": "profile 1"}
    p.dispatch_event("profile-new")                       # selected shape -> profile 2
    p.dispatch_event("profile-select:profile 1")
    p.dispatch_event("profile-rename:alcove")
    assert "profile 1" not in p._doc["profiles"] and "alcove" in p._doc["profiles"]
    assert _em(p)["profile"] == "alcove"
    assert p._doc["shapes"]["3:floor"]["emitter"]["profile"] == "alcove"
    p.dispatch_event("profile-rename:profile 2")          # clash
    assert _em(p)["profile"] == "alcove"
    assert "exists" in payload(p)["status"]
    p.dispatch_event("profile-rename:   ")                # empty
    assert _em(p)["profile"] == "alcove"


def test_state_edits_need_a_profile(env_rt):
    p, rt = _open_on_panel(env_rt)
    p.dispatch_event("state:red:level:2")
    p.dispatch_event("state-on:red")
    assert "7:redalertpanel" not in p._doc["shapes"]
    assert payload(p)["selected"]["profile_data"] is None


def test_state_on_off_tint_level(env_rt):
    p, rt = _open_on_panel(env_rt)
    p.dispatch_event("profile-new")
    prof = p._doc["profiles"]["profile 1"]
    p.dispatch_event("state-off:yellow")
    assert "yellow" not in prof
    p.dispatch_event("state-on:yellow")
    assert prof["yellow"] == {"tint": [1, 1, 1], "level": 1.0}
    p.dispatch_event("state:red:tint:0.5,0.1,0.05")       # normalised: max channel 1
    assert prof["red"]["tint"] == pytest.approx([1.0, 0.2, 0.1])
    p.dispatch_event("state:red:level:-1")
    assert prof["red"]["level"] == 0.0
    p.dispatch_event("state:red:level:6.5")               # the number field: any >= 0
    assert prof["red"]["level"] == 6.5


def test_wave_shape_switch_keeps_the_document_valid(env_rt):
    p, rt = _open_on_panel(env_rt)
    p.dispatch_event("profile-new")
    prof = p._doc["profiles"]["profile 1"]
    p.dispatch_event("state:red:wave:shape:square")
    assert prof["red"]["wave"] == {"shape": "square", "period_s": 1.0, "min": 0.0,
                                   "duty": 0.5, "soft": 0.0}
    p.dispatch_event("state:red:wave:period_s:0.001")
    p.dispatch_event("state:red:wave:duty:2")
    assert prof["red"]["wave"]["period_s"] == 0.05 and prof["red"]["wave"]["duty"] == 1.0
    p.dispatch_event("state:red:wave:shape:sine")
    assert prof["red"]["wave"] == {"shape": "sine", "period_s": 0.05, "min": 0.0}
    p.dispatch_event("state:red:wave:duty:0.3")           # square only: ignored
    assert "duty" not in prof["red"]["wave"]
    ld.validate(p._doc)
    p.dispatch_event("state:red:wave:shape:steady")
    assert "wave" not in prof["red"]
    ld.validate(p._doc)


def test_fade_and_phase_clamp(env_rt):
    p, rt = _open_on_panel(env_rt)
    p.dispatch_event("profile-new")
    p.dispatch_event("fade:-1")
    p.dispatch_event("phase:1.7")
    assert p._doc["profiles"]["profile 1"]["fade_s"] == 0.0
    assert _em(p)["phase"] == 1.0
    assert payload(p)["selected"]["phase"] == 1.0


def test_every_edit_is_one_undo_step_and_no_op_edits_add_none(env_rt):
    p, rt = _open_on_panel(env_rt)
    p.dispatch_event("profile-new")
    n = len(p._undo)
    p.dispatch_event("state:green:level:1")               # unchanged value
    assert len(p._undo) == n
    p.dispatch_event("state:green:level:2")
    assert len(p._undo) == n + 1
    p.dispatch_event("undo")
    assert p._doc["profiles"]["profile 1"]["green"]["level"] == 1


def test_tab_and_preview_toggle_are_not_document_edits(env_rt):
    p, rt = _open_on_panel(env_rt)
    n = len(p._undo)
    p.dispatch_event("tab:red")
    p.dispatch_event("preview-toggle")
    st = payload(p)
    assert st["tab"] == "red" and st["preview_playing"] is False
    assert len(p._undo) == n
    p.dispatch_event("tab:purple")
    assert payload(p)["tab"] == "red"
```

- [ ] **Step 2: Run, watch fail** — `uv run pytest tests/unit/test_bridge_emitters_panel.py -q` → the new tests FAIL (unknown actions return False; payload keys missing).

- [ ] **Step 3: Implement** in `engine/ui/bridge_emitters_panel.py`:

Imports: `from engine.bridge_editor import profiles` (beside the existing bridge_editor imports).

Module constants after `_LIGHT_FIELDS`:

```python
_WAVE_DEFAULTS = {"sine": {"period_s": 2.0, "min": 0.0},
                  "square": {"period_s": 1.0, "min": 0.0, "duty": 0.5, "soft": 0.0}}
_MIN_PERIOD_S = 0.05
_EMITTER_PREFIXES = ("glow", "profile", "state", "fade:", "phase:", "tab:", "preview-")
```

`__init__`: add `alert_provider=None` keyword, store `self._alert = alert_provider`, and in `_reset_session` add `self._tab = "green"` and `self._preview_playing = True`. In `open()`, after `_reset_session()`:

```python
        try:
            self._tab = profiles.state_name(self._alert()) if self._alert else "green"
        except Exception as e:  # noqa: BLE001 - a bad provider must not block the editor
            dev_mode.log_swallowed("bridge editor alert provider", e)
            self._tab = "green"
```

(import `dev_mode` from `engine` if the module does not already.)

`dispatch_event`: extend the `self._doc is None` guard's `startswith` tuple with `*_EMITTER_PREFIXES`, and before the final `else: return False` add:

```python
        elif self._emitter_action(action):
            self._after_change()
```

New methods (after the light actions):

```python
    # ── glow + profile (spec 2026-10-08-bridge-emitters §12) ──────────────
    def _edit(self, fn):
        """Run one document edit as one undo step: snapshot, mutate, and keep
        the snapshot only if the document changed (a no-op adds none)."""
        before = copy.deepcopy(self._doc)
        fn()
        if self._doc != before:
            self._undo.append(before)
            del self._undo[:-_UNDO_LIMIT]

    def _emitter(self, create=False):
        if self._selected is None or self._doc is None:
            return None
        if create:
            entry = ld.shape_entry(self._doc, self._selected.block, self._selected.name)
            return entry.setdefault("emitter", {})
        return self._doc["shapes"].get(self._selected.key, {}).get("emitter")

    def _drop_empty(self):
        entry = self._doc["shapes"].get(self._selected.key) if self._selected else None
        if entry is None:
            return
        if entry.get("emitter") == {}:
            del entry["emitter"]
        if set(entry) == {"block", "name"}:
            del self._doc["shapes"][self._selected.key]

    def _profile_name(self):
        return (self._emitter() or {}).get("profile")

    def _has_emissive_map(self):
        return bool(((self._selected_mesh_info() or {}).get("maps") or {}).get("emissive"))

    @staticmethod
    def _num(raw, lo=None, hi=None):
        try:
            v = float(raw)
        except ValueError:
            return None
        if v != v or v in (float("inf"), float("-inf")):
            return None
        if lo is not None:
            v = max(lo, v)
        if hi is not None:
            v = min(hi, v)
        return v

    def _emitter_action(self, action) -> bool:
        """Glow / profile / state / preview actions; False for anything else."""
        if action == "preview-toggle":
            self._preview_playing = not self._preview_playing
            return True
        if action.startswith("tab:"):
            if action[4:] in profiles.STATES:
                self._tab = action[4:]
            return True
        if self._selected is None:
            return action.startswith(_EMITTER_PREFIXES)
        if action == "glow-on":
            def on():
                em = self._emitter(create=True)
                em.setdefault("glow", {"src": "emissive" if self._has_emissive_map()
                                       else "texture"})
            self._edit(on)
        elif action == "glow-off":
            def off():
                em = self._emitter()
                if em is not None:
                    em.pop("glow", None)
                    self._drop_empty()
            self._edit(off)
        elif action.startswith("glow:"):
            field, _, raw = action[5:].partition(":")
            g = (self._emitter() or {}).get("glow")
            if g is None:
                return True
            if field == "src" and raw in ld.GLOW_SRCS and (
                    raw != "emissive" or self._has_emissive_map()):
                self._edit(lambda: g.__setitem__("src", raw))
            elif field == "scale":
                v = self._num(raw, lo=0.0)
                if v is not None:
                    self._edit(lambda: g.__setitem__("scale", v))
        elif action.startswith("profile-select:"):
            name = action[len("profile-select:"):]
            if name and name not in self._doc["profiles"]:
                return True
            def select():
                if name:
                    self._emitter(create=True)["profile"] = name
                else:
                    em = self._emitter()
                    if em is not None:
                        em.pop("profile", None)
                        self._drop_empty()
            self._edit(select)
        elif action == "profile-new":
            def new():
                n = 1
                while f"profile {n}" in self._doc["profiles"]:
                    n += 1
                cur = self._profile_name()
                src = self._doc["profiles"].get(cur) if cur else None
                data = copy.deepcopy(src) if src is not None else {
                    "fade_s": profiles.DEFAULT_FADE_S,
                    **copy.deepcopy(profiles.STEADY_WHITE)}
                self._doc["profiles"][f"profile {n}"] = data
                self._emitter(create=True)["profile"] = f"profile {n}"
            self._edit(new)
        elif action.startswith("profile-rename:"):
            self._rename(action[len("profile-rename:"):].strip())
        elif action.startswith(("state-on:", "state-off:", "state:", "fade:", "phase:")):
            self._state_action(action)
        else:
            return False
        return True

    def _rename(self, new):
        old = self._profile_name()
        if old is None:
            return
        if not new:
            self._status = "Rename refused: empty name"
            return
        if new in self._doc["profiles"]:
            if new != old:
                self._status = f"Rename refused: a profile named {new!r} exists"
            return
        def rename():
            self._doc["profiles"][new] = self._doc["profiles"].pop(old)
            for entry in self._doc["shapes"].values():
                em = entry.get("emitter")
                if em is not None and em.get("profile") == old:
                    em["profile"] = new
        self._edit(rename)
        self._status = f"Renamed {old!r} to {new!r}"

    def _state_action(self, action):
        name = self._profile_name()
        prof = self._doc["profiles"].get(name) if name else None
        if action.startswith("phase:"):
            v = self._num(action[6:], 0.0, 1.0)
            if v is not None and self._emitter() is not None:
                self._edit(lambda: self._emitter().__setitem__("phase", v))
            return
        if prof is None:
            return
        if action.startswith("fade:"):
            v = self._num(action[5:], lo=0.0)
            if v is not None:
                self._edit(lambda: prof.__setitem__("fade_s", v))
            return
        if action.startswith(("state-on:", "state-off:")):
            on, _, s = action.partition(":")
            if s not in profiles.STATES:
                return
            if on == "state-on":
                self._edit(lambda: prof.setdefault(s, {"tint": [1, 1, 1], "level": 1.0}))
            else:
                self._edit(lambda: prof.pop(s, None))
            return
        _, s, rest = action.split(":", 2) if action.count(":") >= 2 else ("", "", "")
        st = prof.get(s)
        if s not in profiles.STATES or st is None:
            return
        field, _, raw = rest.partition(":")
        if field == "tint":
            try:
                rgb = [max(0.0, float(c)) for c in raw.split(",")]
            except ValueError:
                return
            if len(rgb) != 3 or any(c != c or c == float("inf") for c in rgb):
                return
            m = max(rgb)
            rgb = [round(c / m, 4) for c in rgb] if m > 0 else [0.0, 0.0, 0.0]
            self._edit(lambda: st.__setitem__("tint", rgb))
        elif field == "level":
            v = self._num(raw, lo=0.0)
            if v is not None:
                self._edit(lambda: st.__setitem__("level", v))
        elif field == "wave":
            self._wave_field(st, raw)

    def _wave_field(self, st, arg):
        field, _, raw = arg.partition(":")
        wave = st.get("wave")
        if field == "shape":
            if raw == "steady":
                self._edit(lambda: st.pop("wave", None))
            elif raw in _WAVE_DEFAULTS:
                new = dict(_WAVE_DEFAULTS[raw], shape=raw)
                for k in ("period_s", "min", "duty", "soft"):
                    if wave and k in wave and k in new:
                        new[k] = wave[k]
                self._edit(lambda: st.__setitem__("wave", new))
            return
        if wave is None:
            return
        if field == "period_s":
            v = self._num(raw, lo=_MIN_PERIOD_S)
        elif field == "min" or (field in ("duty", "soft") and wave["shape"] == "square"):
            v = self._num(raw, 0.0, 1.0)
        else:
            return
        if v is not None:
            self._edit(lambda: wave.__setitem__(field, v))
```

`render_payload`: in the `sel = {...}` dict add

```python
                       "glow": self._glow_payload(),
                       "has_emissive_map": self._has_emissive_map(),
                       "profile": self._profile_name(),
                       "profile_data": self._profile_payload(),
                       "phase": float((self._emitter() or {}).get("phase", 0.0)),
```

and in `state` add `"profiles": self._profiles_payload(), "tab": self._tab, "preview_playing": self._preview_playing,`. Helpers:

```python
    def _glow_payload(self):
        g = (self._emitter() or {}).get("glow")
        return None if g is None else dict(g)

    def _profile_payload(self):
        name = self._profile_name()
        prof = self._doc["profiles"].get(name) if name else None
        return None if prof is None else copy.deepcopy(prof)

    def _profiles_payload(self):
        if self._doc is None:
            return []
        used = {}
        for entry in self._doc["shapes"].values():
            n = (entry.get("emitter") or {}).get("profile")
            if n is not None:
                used[n] = used.get(n, 0) + 1
        return [{"name": n, "used_by": used.get(n, 0)} for n in sorted(self._doc["profiles"])]
```

- [ ] **Step 4: Run** — `uv run pytest tests/unit/test_bridge_emitters_panel.py tests/unit/test_bridge_lighting_doc.py -q` → pass.

- [ ] **Step 5: Commit**

```bash
git add engine/ui/bridge_emitters_panel.py tests/unit/test_bridge_emitters_panel.py
git commit -m "feat(bridge): Bridge Editor glow and profile actions + payload (spec §12)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Preview — the state tab drives the bridge's alert and clock

**Files:**
- Modify: `engine/ui/bridge_emitters_panel.py` (`preview_alert`, `preview_dt`)
- Modify: `engine/host_loop.py` (two helpers; `_register_bridge_emitters` gains `alert_provider`; the per-frame bridge block)
- Test: `tests/unit/test_bridge_emitters_panel.py`, `tests/unit/test_bridge_editor_preview.py` (new), `tests/unit/test_bridge_lighting.py` (update its AST pin if it names `_player_dt` for the probe blend)

**Interfaces:**
- Produces: `BridgeEmittersPanel.preview_alert() -> Optional[int]` (None when closed; else the tab's level 0/1/2); `BridgeEmittersPanel.preview_dt(player_dt, frame_dt) -> float` (player dt when closed; frame dt when playing; 0 when paused).
- Produces: `host_loop._bridge_effective_alert(player_level, editor) -> int`; `host_loop._bridge_clock_dt(editor, player_dt, frame_dt) -> float` — both tolerate `_NULL_PICKER` (no such methods).

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_bridge_emitters_panel.py`:

```python
def test_preview_is_none_and_dt_is_the_players_when_closed(env):
    p, *_ = env
    assert p.preview_alert() is None
    assert p.preview_dt(0.0, 0.016) == 0.0
    assert p.preview_dt(0.02, 0.016) == 0.02


def test_preview_follows_the_tab_and_the_play_toggle(env):
    p, *_ = env
    p.open()
    assert p.preview_alert() == 0
    p.dispatch_event("tab:red")
    assert p.preview_alert() == 2
    assert p.preview_dt(0.0, 0.016) == 0.016          # paused sim, clock still runs
    p.dispatch_event("preview-toggle")
    assert p.preview_dt(0.0, 0.016) == 0.0
    p.close()
    assert p.preview_alert() is None


def test_open_starts_on_the_players_alert(tmp_path, monkeypatch):
    monkeypatch.setattr(ld.paths, "game_asset_dirs", lambda rel: [tmp_path / "stock" / rel])
    monkeypatch.setattr(ld.paths, "project_asset_root", lambda: tmp_path)
    p = bep.BridgeEmittersPanel(pose_provider=lambda: POSE, instance_provider=lambda: "iid",
                                in_bridge_provider=lambda: True, io=FakeIO(),
                                alert_provider=lambda: 1)
    p.open()
    assert p.preview_alert() == 1
```

`tests/unit/test_bridge_editor_preview.py`:

```python
"""Host-loop wiring of the Bridge Editor preview (spec §12.2)."""
from engine import host_loop


class Editor:
    def __init__(self, alert, dt):
        self._a, self._dt = alert, dt

    def preview_alert(self):
        return self._a

    def preview_dt(self, player_dt, frame_dt):
        return player_dt if self._a is None else self._dt


def test_the_editor_overrides_the_alert_only_while_open():
    assert host_loop._bridge_effective_alert(2, Editor(None, 0.0)) == 2
    assert host_loop._bridge_effective_alert(2, Editor(1, 0.0)) == 1
    assert host_loop._bridge_effective_alert(2, host_loop._NULL_PICKER) == 2


def test_the_clock_dt_comes_from_the_editor_when_it_has_one():
    assert host_loop._bridge_clock_dt(Editor(1, 0.016), 0.0, 0.016) == 0.016
    assert host_loop._bridge_clock_dt(Editor(None, 0.0), 0.02, 0.016) == 0.02
    assert host_loop._bridge_clock_dt(host_loop._NULL_PICKER, 0.02, 0.016) == 0.02
```

- [ ] **Step 2: Run, watch fail** — `uv run pytest tests/unit/test_bridge_emitters_panel.py tests/unit/test_bridge_editor_preview.py -q` → FAIL (no `preview_alert`, no helpers, no `alert_provider`).

- [ ] **Step 3: Implement**

Panel:

```python
    # ── preview (spec 2026-10-08-bridge-emitters §12.2) ───────────────────
    def preview_alert(self):
        """The alert level the bridge shows while the editor is open -- the
        state tab; None when closed (the player's alert then)."""
        return profiles.STATES.index(self._tab) if self._visible else None

    def preview_dt(self, player_dt, frame_dt):
        """The bridge clock's dt: the player's (paused-aware) when closed;
        while open the real frame time, or 0 when the preview is paused."""
        if not self._visible:
            return player_dt
        return frame_dt if self._preview_playing else 0.0
```

`host_loop.py`, near `_bridge_camera_pose`:

```python
def _bridge_effective_alert(player_level, editor):
    """The alert level the bridge draws: the Bridge Editor's preview tab
    while it is open (spec 2026-10-08-bridge-emitters §12.2), else the
    player's. `editor` may be _NULL_PICKER (no preview methods)."""
    fn = getattr(editor, "preview_alert", None)
    preview = fn() if fn is not None else None
    return player_level if preview is None else preview


def _bridge_clock_dt(editor, player_dt, frame_dt):
    """The bridge clock's dt (§11.3, §12.2): the editor's preview clock while
    it is open, else the paused-aware player dt."""
    fn = getattr(editor, "preview_dt", None)
    return player_dt if fn is None else fn(player_dt, frame_dt)
```

`_register_bridge_emitters(registry, bridge_camera, controller, view_mode, runtime=None, alert_provider=None)` passes `alert_provider=alert_provider` to `BridgeEmittersPanel(...)`; the call site (`bridge_emitters = _register_bridge_emitters(...)`) passes `alert_provider=_bridge_runtime_alert_level`.

Per-frame block (around `r.set_bridge_ambient_scale(...)` … `controller.bridge_runtime.tick(_player_dt)`): `bridge_emitters` is the panel from the same function's setup (verify it is in scope; it is assigned before the main loop). Replace:

- `r.set_bridge_ambient_scale(_bridge_lighting.player_bridge_ambient_scale(player))` with

```python
            _bridge_preview = getattr(bridge_emitters, "preview_alert", lambda: None)()
            r.set_bridge_ambient_scale(
                _bridge_lighting.player_bridge_ambient_scale(player) if _bridge_preview is None
                else _bridge_lighting.ambient_scale_for_alert(_bridge_preview))
```

- `_bridge_alert_level = _bridge_alert_level_of(player)` with
  `_bridge_alert_level = _bridge_effective_alert(_bridge_alert_level_of(player), bridge_emitters)`, and directly below it
  `_bridge_dt = _bridge_clock_dt(bridge_emitters, _player_dt, min(max(_frame_dt, 0.0), MAX_FRAME_DT))`
- `_bridge_probe_blend.update(_bridge_alert_level, _player_dt)` → `_bridge_probe_blend.update(_bridge_alert_level, _bridge_dt)`
- `controller.bridge_runtime.tick(_player_dt)` → `controller.bridge_runtime.tick(_bridge_dt)`

If `tests/unit/test_bridge_lighting.py`'s AST test asserts the probe blend is fed `_player_dt` literally, update it to `_bridge_dt` and add an assertion that `_bridge_dt` is assigned from `_bridge_clock_dt(...)` — the intent it pins (paused-aware, never wall time in production) is kept by `_bridge_clock_dt` returning `_player_dt` whenever the editor is closed. Ledger this as a ruling.

- [ ] **Step 4: Run** — `uv run pytest tests/unit/test_bridge_emitters_panel.py tests/unit/test_bridge_editor_preview.py tests/unit/test_bridge_lighting.py tests/unit/test_host_loop_bridge_emitters_registration.py -q` → pass.

- [ ] **Step 5: Commit**

```bash
git add engine/ui/bridge_emitters_panel.py engine/host_loop.py tests/unit/test_bridge_emitters_panel.py tests/unit/test_bridge_editor_preview.py tests/unit/test_bridge_lighting.py
git commit -m "feat(bridge): the editor's state tab previews the alert, with a running preview clock (spec §12.2)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Panel markup — Glow and Profile sections, state tabs, colour wheel

**Files:**
- Modify: `native/assets/ui-cef/js/bridge_emitters.js`, `native/assets/ui-cef/css/bridge_emitters.css`
- Test: `tests/ui/test_bridge_emitters_js.py`

**Interfaces:**
- Consumes: the Task 2 payload and action strings; `ColourWheel`, `colourRgbToHs`, `colourHsToRgb` (Task 1).

- [ ] **Step 1: Write the failing tests** — in `tests/ui/test_bridge_emitters_js.py`'s `_HARNESS`, add `Math` to the vm context (`const ctx = {document, dauntlessEvent: () => {}, String, Number, Math};` — the new markup uses `Math.min`), then append:

```python
PROFILE = {"fade_s": 0.5,
           "green": {"tint": [1, 1, 1], "level": 1},
           "red": {"tint": [1, 0.1, 0.1], "level": 0.5,
                   "wave": {"shape": "square", "period_s": 1, "min": 0.2,
                            "duty": 0.5, "soft": 0.1}}}


def _sel(**over):
    sel = dict(_state()["selected"], glow=None, has_emissive_map=False,
               profile=None, profile_data=None, phase=0.0)
    sel.update(over)
    return sel


def _st(sel, **over):
    return _state(selected=sel, profiles=[{"name": "alcove", "used_by": 4}],
                  tab="green", preview_playing=True, **over)


def test_glow_off_shows_only_the_toggle():
    [out] = _run([{"state": _st(_sel())}])
    assert "bridge-emitters/glow-on" in out["body"] or "glow-' + (this.checked" in out["body"]
    assert "glow:src:" not in out["body"]


def test_glow_on_lists_sources_and_disables_emissive_without_a_map():
    [out] = _run([{"state": _st(_sel(glow={"src": "texture"}))}])
    body = out["body"]
    assert 'value="emissive" disabled' in body
    assert 'value="texture" selected' in body
    assert "glow:scale:" in body


def test_profile_dropdown_counts_users_and_offers_none():
    [out] = _run([{"state": _st(_sel(profile="alcove", profile_data=PROFILE))}])
    body = out["body"]
    assert "none (steady white)" in body
    assert "alcove (4)" in body
    assert "profile-new" in body and "profile-rename:" in body


def test_tabs_show_without_a_profile_but_no_state_editor():
    [out] = _run([{"state": _st(_sel())}])
    body = out["body"]
    for t in ("green", "yellow", "red"):
        assert f"bridge-emitters/tab:{t}" in body
    assert "state:green:level:" not in body


def test_the_active_tab_shows_its_state_fields():
    [out] = _run([{"state": _st(_sel(profile="alcove", profile_data=PROFILE), tab="red")}])
    body = out["body"]
    assert 'be-tab active' in body
    assert "state:red:level:" in body
    assert "state:red:wave:duty:" in body and "state:red:wave:soft:" in body
    assert 'id="be-wheel"' in body
    assert "fade:" in body and "phase:" in body


def test_an_off_state_offers_to_turn_it_on():
    [out] = _run([{"state": _st(_sel(profile="alcove", profile_data=PROFILE), tab="yellow")}])
    assert "state-' + (this.checked" in out["body"]
    assert "state:yellow:level:" not in out["body"]


def test_preview_toggle_label_follows_playing():
    [out] = _run([{"state": _st(_sel(), preview_playing=False)}])
    assert "bridge-emitters/preview-toggle" in out["body"]
    assert "Play" in out["body"]
```

- [ ] **Step 2: Run, watch fail** — `uv run pytest tests/ui/test_bridge_emitters_js.py -q` → new tests FAIL.

- [ ] **Step 3: Implement** in `bridge_emitters.js`:

```javascript
function _beNumberRow(label, action, value, step) {
    return '<div class="be-row">'
        + '<label>' + _beEsc(label) + '</label>'
        + '<input type="number" step="' + (step || 0.01) + '" value="' + _beEsc(Number(value)) + '"'
        + ' onchange="dauntlessEvent(\'bridge-emitters/' + action + ':\' + this.value)">'
        + '</div>';
}

// Glow (spec §12.1): on/off, source, scale. "emissive map" is disabled when
// the shape's material has no _emissive sibling (title= is a no-op in CEF
// OSR, so the reason is a visible line).
function _beGlowSection(s) {
    const g = s.glow;
    let html = '<div class="cp-section-title">Glow</div>'
        + '<div class="be-row"><label>glow</label><input type="checkbox"' + (g ? ' checked' : '')
        + ' onchange="dauntlessEvent(\'bridge-emitters/glow-\' + (this.checked ? \'on\' : \'off\'))"></div>';
    if (!g) return html;
    const opt = function (v, label, dis) {
        return '<option value="' + v + '"' + (g.src === v ? ' selected' : '')
            + (dis ? ' disabled' : '') + '>' + label + '</option>';
    };
    html += '<div class="be-row"><label>source</label>'
        + '<select onchange="dauntlessEvent(\'bridge-emitters/glow:src:\' + this.value)">'
        + opt('emissive', 'emissive map', !s.has_emissive_map)
        + opt('texture', 'own texture', false) + opt('flat', 'flat', false) + '</select></div>';
    if (!s.has_emissive_map)
        html += '<div class="be-help">No _emissive map beside this texture.</div>';
    html += _beNumberRow('scale', 'glow:scale', g.scale === undefined ? 1 : g.scale, 0.1);
    return html;
}

const _BE_STATES = ['green', 'yellow', 'red'];

function _beStateFields(tab, st) {
    const w = st.wave || {shape: 'steady'};
    const lv = Number(st.level);
    let html = '<div class="be-row"><canvas id="be-wheel" width="120" height="120"></canvas>'
        + '<div id="be-swatch" class="be-swatch"></div></div>'
        + '<div class="be-row"><label>level</label>'
        + '<input type="range" min="0" max="4" step="0.01" value="' + Math.min(lv, 4) + '"'
        + ' onchange="dauntlessEvent(\'bridge-emitters/state:' + tab + ':level:\' + this.value)">'
        + '<input type="number" min="0" step="0.01" value="' + lv.toFixed(2) + '" style="width:56px"'
        + ' onchange="dauntlessEvent(\'bridge-emitters/state:' + tab + ':level:\' + this.value)"></div>';
    const shp = function (v) {
        return '<option value="' + v + '"' + (w.shape === v ? ' selected' : '') + '>' + v + '</option>';
    };
    html += '<div class="be-row"><label>pulse</label>'
        + '<select onchange="dauntlessEvent(\'bridge-emitters/state:' + tab + ':wave:shape:\' + this.value)">'
        + shp('steady') + shp('sine') + shp('square') + '</select></div>';
    if (w.shape !== 'steady') {
        html += _beNumberRow('period s', 'state:' + tab + ':wave:period_s', w.period_s, 0.05);
        html += _beNumberRow('min', 'state:' + tab + ':wave:min', w.min || 0, 0.05);
    }
    if (w.shape === 'square') {
        html += _beNumberRow('duty', 'state:' + tab + ':wave:duty', w.duty === undefined ? 0.5 : w.duty, 0.05);
        html += _beNumberRow('soft', 'state:' + tab + ':wave:soft', w.soft || 0, 0.05);
    }
    return html;
}

// Profile (spec §12.1): dropdown + New/Rename, then Green|Yellow|Red tabs --
// the selected tab is also the alert the bridge previews (§12.2).
function _beProfileSection(state) {
    const s = state.selected;
    let html = '<div class="cp-section-title">Profile</div>'
        + '<div class="be-row"><label>profile</label>'
        + '<select onchange="dauntlessEvent(\'bridge-emitters/profile-select:\' + this.value)">'
        + '<option value=""' + (s.profile ? '' : ' selected') + '>none (steady white)</option>';
    (state.profiles || []).forEach(function (p) {
        html += '<option value="' + _beEsc(p.name) + '"' + (p.name === s.profile ? ' selected' : '')
            + '>' + _beEsc(p.name) + ' (' + p.used_by + ')</option>';
    });
    html += '</select></div><div class="be-row">'
        + '<button onclick="dauntlessEvent(\'bridge-emitters/profile-new\')">New</button>';
    if (s.profile) {
        html += '<input type="text" id="be-rename" value="' + _beEsc(s.profile) + '" style="width:120px">'
            + '<button onclick="dauntlessEvent(\'bridge-emitters/profile-rename:\' + '
            + 'document.getElementById(\'be-rename\').value)">Rename</button>';
    }
    html += '</div><div class="be-tabs">';
    _BE_STATES.forEach(function (t) {
        html += '<button class="be-tab' + (state.tab === t ? ' active' : '') + '"'
            + ' onclick="dauntlessEvent(\'bridge-emitters/tab:' + t + '\')">' + t + '</button>';
    });
    html += '<button onclick="dauntlessEvent(\'bridge-emitters/preview-toggle\')">'
        + (state.preview_playing ? 'Pause' : 'Play') + '</button></div>';
    const prof = s.profile_data;
    if (!prof) {
        html += '<div class="be-help">Previewing ' + _beEsc(state.tab)
            + '. Pick or create a profile to edit its states.</div>';
        return html;
    }
    const st = prof[state.tab];
    html += '<div class="be-row"><label>' + _beEsc(state.tab) + '</label><input type="checkbox"'
        + (st ? ' checked' : '')
        + ' onchange="dauntlessEvent(\'bridge-emitters/state-\' + (this.checked ? \'on\' : \'off\') + \':'
        + state.tab + '\')"><span>' + (st ? 'on' : 'off in this state') + '</span></div>';
    if (st) html += _beStateFields(state.tab, st);
    html += _beNumberRow('fade s', 'fade', prof.fade_s === undefined ? 0.5 : prof.fade_s, 0.05);
    html += _beNumberRow('phase', 'phase', s.phase || 0, 0.05);
    return html;
}

// The wheel is a canvas inside the rebuilt body: mount it after every
// rebuild. A drag commits once, on release (one undo step); the swatch
// follows live. `_beWheel.dragging` also blocks rebuilds (_beEditingInDock).
var _beWheel = null;
function _beMountWheel(state) {
    _beWheel = null;
    const canvas = document.getElementById('be-wheel');
    const s = state.selected;
    if (!canvas || !canvas.getContext || typeof ColourWheel === 'undefined' || !s
        || !s.profile_data || !s.profile_data[state.tab]) return;
    const tab = state.tab;
    const tint = s.profile_data[tab].tint;
    const swatch = document.getElementById('be-swatch');
    const paint = function (rgb) {
        if (swatch) swatch.style.background = 'rgb(' + rgb.map(function (c) {
            return Math.round(Math.max(0, Math.min(1, c)) * 255);
        }).join(',') + ')';
    };
    paint(tint);
    _beWheel = new ColourWheel(canvas, colourRgbToHs(tint), function (hs, final) {
        const rgb = colourHsToRgb(hs.hue, hs.sat);
        paint(rgb);
        if (final) dauntlessEvent('bridge-emitters/state:' + tab + ':tint:'
            + rgb.map(function (c) { return c.toFixed(4); }).join(','));
    });
}
```

In `_beEditingInDock`, first line of the body: `if (_beWheel && _beWheel.dragging) return true;`.

In `_beBodyHtml`, after `html += _beLightSection(s.light);` add:

```javascript
            html += _beGlowSection(s);
            html += _beProfileSection(state);
```

In `setBridgeEmitters`, change the rebuild line to

```javascript
    if (body && !_beEditingInDock(root)) {
        body.innerHTML = _beBodyHtml(state);
        _beMountWheel(state);
    }
```

`bridge_emitters.css` — append:

```css
#bridge-emitters-root .be-tabs { display: flex; gap: 4px; margin: 6px 0; }
#bridge-emitters-root .be-tab { flex: 1; text-transform: capitalize; opacity: 0.6; }
#bridge-emitters-root .be-tab.active { opacity: 1; outline: 1px solid #f0b060; }
#bridge-emitters-root .be-swatch { width: 40px; height: 40px; border: 1px solid #888; }
#bridge-emitters-root canvas { cursor: crosshair; }
```

- [ ] **Step 4: Run** — `uv run pytest tests/ui/test_bridge_emitters_js.py tests/ui/test_colour_wheel_js.py -q` → pass.

- [ ] **Step 5: Commit**

```bash
git add native/assets/ui-cef/js/bridge_emitters.js native/assets/ui-cef/css/bridge_emitters.css tests/ui/test_bridge_emitters_js.py
git commit -m "feat(bridge): Bridge Editor glow + profile panes with state tabs and colour wheel (spec §12.1)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Docs, gate, live check

**Files:** `CLAUDE.md` (Bridge editor row), the spec's §10 log.

- [ ] **Step 1:** In `CLAUDE.md`'s "Bridge editor" row, replace `Hand-authored in the JSON until the editor panes land.` with `Edited in the dock's Glow + Profile panes (spec §12): the Green/Yellow/Red tab is also the alert the bridge previews, and a preview clock runs pulses while the editor pauses the game.`
- [ ] **Step 2:** Spec §10: add after G2: `| G3 | 2026-10-11 | Editor panes built (plan 2026-10-11-bridge-editor-glow-panes) | built; awaiting Mark's live check | 12 |`
- [ ] **Step 3:** Gate: `DAUNTLESS_GAME_DIR="/Users/mward/Documents/Star Trek Bridge Commander/game" scripts/check_tests.sh` → `OK — no new failures`.
- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md docs/superpowers/specs/2026-10-08-bridge-emitters-spike-design.md
git commit -m "docs(bridge): Bridge Editor glow + profile panes

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 5:** Hand to Mark (do not launch): `cd /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/dbridge-round7` then `./build/dauntless --developer`; check: select an alcove roof — Glow and Profile show `alcove (4)`; the tabs switch the whole bridge between green/yellow/red with a fade; the red pulse runs while the editor is open; Pause stops it; the wheel recolours on release and Undo reverts it; the Ship Property Viewer's light colour wheel still works.
