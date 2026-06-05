# Configuration Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a **Configuration** entry to the pause menu that opens a modal with a left-side vertical tab strip; first iteration ships a **Graphics** tab with Space Dust toggle, Specular Highlights toggle, and Exterior Camera FOV slider (55–75°). Settings apply live; no persistence.

**Architecture:** New `ConfigurationPanel` Python class (subclass of `engine.ui.panel.Panel`) registered on the existing `PanelRegistry`, pumped each tick, hidden/shown via the same mission-picker arbitration pattern. Pause menu gains a third row whose handler opens the panel. Specular toggle requires new C++ host binding + opaque-shader uniform; dust and FOV reuse existing knobs.

**Tech Stack:** Python 3 (engine/ui), pytest, pybind11 (host bindings), GLSL 330, CEF (JS/HTML/CSS).

**Spec:** `docs/superpowers/specs/2026-06-05-configuration-panel-design.md`

---

## File Map

**Create**
- `engine/ui/configuration_panel.py` — `ConfigurationPanel` Panel subclass.
- `tests/unit/test_configuration_panel.py` — model + dispatch + render_payload tests.
- `native/assets/ui-cef/js/configuration_panel.js` — render fn + click handlers.
- `native/assets/ui-cef/css/configuration_panel.css` — modal + tab strip + control styles.

**Modify**
- `engine/renderer.py` — add `set_specular_enabled` wrapper.
- `engine/ui/pause_menu.py` — `default_pause_menu` gains `on_configuration` and inserts a row; slug-collision seed updated.
- `engine/host_loop.py` — construct + register panel, route ESC, extend pause-menu arbitration.
- `native/src/host/host_bindings.cc` — add `specular_set_enabled` binding + global flag.
- `native/src/renderer/frame.cc` — emit `u_specular_enabled` uniform from the flag on shader bind.
- `native/src/renderer/shaders/opaque.frag` — add `u_specular_enabled` uniform and short-circuit spec accumulator.
- `native/assets/ui-cef/ship_status.html` — new `#configuration-panel` section + JS/CSS includes.
- `tests/unit/test_pause_menu_model.py` — extend for the Configuration row and slug-collision.

---

## Task 1: Specular toggle — C++ runtime flag, host binding, shader

**Files:**
- Modify: `native/src/host/host_bindings.cc` (around line 636 alongside `dust_set_enabled`)
- Modify: `native/src/renderer/frame.cc:95-98`
- Modify: `native/src/renderer/shaders/opaque.frag`

No unit test — this is a build + visual gate. Task 7 visually verifies. Implementation is small enough to be auditable.

- [ ] **Step 1: Add `u_specular_enabled` uniform and short-circuit in opaque.frag**

Edit `native/src/renderer/shaders/opaque.frag`. After the existing `uniform float u_specular_power;` line (line 15) add:

```glsl
uniform int u_specular_enabled;
```

Replace the existing per-light spec accumulator (line 38-40) and final `spec` assignment (line 46) so the spec contribution is zero when the uniform is 0. New `void main()` body:

```glsl
void main() {
    vec3 n = normalize(v_normal_ws);
    vec3 V = normalize(u_camera_pos_ws - v_position_ws);

    vec3 lit_dir  = vec3(0.0);
    vec3 spec_acc = vec3(0.0);
    for (int i = 0; i < u_dir_light_count; ++i) {
        vec3 L  = normalize(u_dir_light_dir_ws[i]);
        float nl = max(dot(n, L), 0.0);
        lit_dir += nl * u_dir_light_color[i];

        if (u_specular_enabled != 0) {
            vec3 H = normalize(L + V);
            float s = pow(max(dot(n, H), 0.0), u_specular_power) * step(0.0, nl);
            spec_acc += s * u_dir_light_color[i];
        }
    }

    vec4 base = texture(u_base_color, v_uv);
    vec3 lit  = (u_ambient_light + lit_dir) * u_diffuse_color * base.rgb;
    vec4 glow = texture(u_glow_map, v_uv);
    vec3 spec = (u_specular_enabled != 0)
        ? spec_acc * u_specular_color * texture(u_specular_map, v_uv).rgb
        : vec3(0.0);

    frag_color = vec4(lit + u_emissive_color + glow.rgb * glow.a + spec, 1.0);
}
```

- [ ] **Step 2: Add the runtime flag and accessors next to `g_dust_pass`**

Edit `native/src/host/host_bindings.cc`. Above the `m.def("dust_set_enabled", ...)` block (around line 636) add a TU-static flag and a small accessor:

```cpp
// Toggle for the opaque-pass specular term. Default on so existing
// renders look identical until the user flips the Configuration row.
// frame.cc reads this when binding the opaque shader and writes the
// uniform u_specular_enabled.
static bool g_specular_enabled = true;

namespace dauntless_specular {
    bool enabled() { return g_specular_enabled; }
    void set_enabled(bool v) { g_specular_enabled = v; }
}
```

- [ ] **Step 3: Add the pybind binding**

In `native/src/host/host_bindings.cc`, immediately after the `m.def("dust_set_enabled", ...)` block (around line 641), add:

```cpp
    m.def("specular_set_enabled",
          [](bool enabled) { dauntless_specular::set_enabled(enabled); },
          py::arg("enabled"),
          "Toggle the opaque-pass specular term. Default: on.");
```

- [ ] **Step 4: Wire the uniform from frame.cc**

Edit `native/src/renderer/frame.cc`. First, declare the accessor near the top of the file (after existing renderer-namespace includes, but before the anonymous namespace where the draw routine lives). Add:

```cpp
namespace dauntless_specular {
    bool enabled();  // defined in host_bindings.cc
}
```

Then, in the opaque-pass loop, after the existing `shader.set_float("u_specular_power", ...)` line (frame.cc:97-98) add:

```cpp
            shader.set_int("u_specular_enabled",
                           dauntless_specular::enabled() ? 1 : 0);
```

- [ ] **Step 5: Reconfigure + build**

Shader edits are not picked up by an incremental cmake --build. Per project memory you MUST reconfigure first:

```bash
cmake -B build -S . && cmake --build build -j
```

Expected: clean build, `build/dauntless` produced, no shader compile errors. (Validation that the toggle actually works happens in Task 7's visual run.)

- [ ] **Step 6: Commit**

```bash
git add native/src/host/host_bindings.cc \
        native/src/renderer/frame.cc \
        native/src/renderer/shaders/opaque.frag
git commit -m "feat(renderer): runtime specular-enabled flag

Adds a process-wide bool toggled via the new specular_set_enabled
host binding; opaque.frag short-circuits the per-light spec
accumulator and final spec term when off. Default on, so render
output is bit-identical until the new toggle flips it."
```

---

## Task 2: Python wrapper for specular toggle

**Files:**
- Modify: `engine/renderer.py` (alongside `set_dust_enabled` on line 133)

No unit test — this is a one-liner thin wrapper. Same pattern as `set_dust_enabled`, which has no test of its own.

- [ ] **Step 1: Add the wrapper**

Edit `engine/renderer.py`. Immediately after `set_dust_density` (line 141), add:

```python
def set_specular_enabled(enabled: bool) -> None:
    """Toggle the opaque-pass specular term. Default: on after init()."""
    _h.specular_set_enabled(enabled)
```

- [ ] **Step 2: Smoke test the binding**

Run a one-liner to confirm the binding is reachable from Python:

```bash
uv run python -c "import engine.renderer as r; r.set_specular_enabled(True); r.set_specular_enabled(False); print('ok')"
```

Expected: `ok` (no exception). If `AttributeError: module '_dauntless_host' has no attribute 'specular_set_enabled'`, the binary is stale — repeat Task 1 Step 5.

- [ ] **Step 3: Commit**

```bash
git add engine/renderer.py
git commit -m "feat(renderer): set_specular_enabled python wrapper"
```

---

## Task 3: `ConfigurationPanel` Python model

Largest task. Writes the panel class and a comprehensive unit-test file. TDD: each behaviour gets a test first, then the implementation grows incrementally.

**Files:**
- Create: `engine/ui/configuration_panel.py`
- Create: `tests/unit/test_configuration_panel.py`

- [ ] **Step 1: Write the failing test file skeleton**

Create `tests/unit/test_configuration_panel.py`:

```python
"""Tests for ConfigurationPanel — pause-menu Configuration modal.

The panel subclasses engine.ui.panel.Panel and is pumped by
PanelRegistry like the mission picker. These tests cover state,
dispatch, render_payload, and keyboard input without touching CEF
or _dauntless_host.
"""
import json
import math
from unittest.mock import Mock

import pytest

from engine.ui.configuration_panel import ConfigurationPanel, SettingsSnapshot


# ---- construction --------------------------------------------------------

def _make(**overrides):
    """Factory: panel with no-op appliers unless overridden."""
    kwargs = dict(
        tabs=[("graphics", "Graphics")],
        initial_settings=SettingsSnapshot(
            dust_on=True, specular_on=True, fov_deg=70,
        ),
        set_dust=Mock(),
        set_specular=Mock(),
        set_fov_rad=Mock(),
    )
    kwargs.update(overrides)
    return ConfigurationPanel(**kwargs), kwargs


def test_name_is_configuration():
    p, _ = _make()
    assert p.name == "configuration"


def test_initially_closed():
    p, _ = _make()
    assert p.is_open() is False


def test_open_close_round_trip():
    p, _ = _make()
    p.open()
    assert p.is_open() is True
    p.close()
    assert p.is_open() is False


def test_initial_settings_round_trip_to_render_payload():
    p, _ = _make(initial_settings=SettingsSnapshot(
        dust_on=False, specular_on=True, fov_deg=62,
    ))
    p.open()
    payload = p.render_payload()
    body = json.loads(payload[len("setConfigurationPanel("):-2])
    assert body["settings"] == {
        "dust_on": False, "specular_on": True, "fov_deg": 62,
    }
```

- [ ] **Step 2: Run the test file — expect import failures**

```bash
uv run pytest tests/unit/test_configuration_panel.py -x
```

Expected: `ImportError: cannot import name 'ConfigurationPanel' from 'engine.ui.configuration_panel'` (module does not exist).

- [ ] **Step 3: Create the module skeleton to make import work**

Create `engine/ui/configuration_panel.py`:

```python
"""Configuration panel — pause-menu modal with tabbed settings.

Subclasses engine.ui.panel.Panel; pumped by PanelRegistry like the
mission picker. Owns a SettingsSnapshot and three injected appliers
(dust, specular, fov). Every state mutation immediately fires the
matching applier — there is no Apply/Cancel; closing the panel does
not revert. Settings are not persisted across launches.

Spec: docs/superpowers/specs/2026-06-05-configuration-panel-design.md
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from engine.ui.panel import Panel


FOV_MIN = 55
FOV_MAX = 75


@dataclass
class SettingsSnapshot:
    dust_on: bool
    specular_on: bool
    fov_deg: int


class ConfigurationPanel(Panel):
    def __init__(self,
                 tabs: List[Tuple[str, str]],
                 initial_settings: SettingsSnapshot,
                 set_dust: Callable[[bool], None],
                 set_specular: Callable[[bool], None],
                 set_fov_rad: Callable[[float], None]):
        super().__init__()
        self._tabs = list(tabs)
        self._selected_tab = tabs[0][0]
        self._settings = SettingsSnapshot(
            dust_on=initial_settings.dust_on,
            specular_on=initial_settings.specular_on,
            fov_deg=int(initial_settings.fov_deg),
        )
        self._set_dust = set_dust
        self._set_specular = set_specular
        self._set_fov_rad = set_fov_rad
        self._visible: bool = False
        self._focused: int = -1
        self._last_pushed: Optional[tuple] = None

    @property
    def name(self) -> str:
        return "configuration"

    def is_open(self) -> bool:
        return self._visible

    def open(self) -> None:
        self._visible = True

    def close(self) -> None:
        self._visible = False
        self._focused = -1

    def render_payload(self) -> Optional[str]:
        snapshot = (
            self._visible,
            tuple(self._tabs),
            self._selected_tab,
            self._focused,
            self._settings.dust_on,
            self._settings.specular_on,
            self._settings.fov_deg,
        )
        if snapshot == self._last_pushed:
            return None
        self._last_pushed = snapshot
        if not self._visible:
            return "setConfigurationPanel(" + json.dumps({"visible": False}) + ");"
        payload = {
            "visible": True,
            "tabs": [{"id": tid, "label": label} for tid, label in self._tabs],
            "selected_tab": self._selected_tab,
            "focused": self._focused,
            "settings": {
                "dust_on": self._settings.dust_on,
                "specular_on": self._settings.specular_on,
                "fov_deg": self._settings.fov_deg,
            },
        }
        return "setConfigurationPanel(" + json.dumps(payload) + ");"

    def dispatch_event(self, action: str) -> bool:
        return False  # filled in step 6

    def invalidate(self) -> None:
        self._last_pushed = None
```

- [ ] **Step 4: Re-run tests**

```bash
uv run pytest tests/unit/test_configuration_panel.py -x
```

Expected: 4 tests pass (`test_name_is_configuration`, `test_initially_closed`, `test_open_close_round_trip`, `test_initial_settings_round_trip_to_render_payload`).

- [ ] **Step 5: Add dispatch_event tests**

Append to `tests/unit/test_configuration_panel.py`:

```python
# ---- dispatch_event ------------------------------------------------------

def test_dispatch_cancel_closes():
    p, _ = _make()
    p.open()
    assert p.dispatch_event("cancel") is True
    assert p.is_open() is False


def test_dispatch_toggle_dust_flips_and_calls_applier():
    p, kw = _make()
    p.open()
    assert p.dispatch_event("toggle:dust") is True
    kw["set_dust"].assert_called_once_with(False)
    # Second toggle flips back.
    assert p.dispatch_event("toggle:dust") is True
    kw["set_dust"].assert_called_with(True)


def test_dispatch_toggle_specular_flips_and_calls_applier():
    p, kw = _make()
    p.open()
    assert p.dispatch_event("toggle:specular") is True
    kw["set_specular"].assert_called_once_with(False)


def test_dispatch_fov_sets_and_applies_radians():
    p, kw = _make()
    p.open()
    assert p.dispatch_event("fov:62") is True
    kw["set_fov_rad"].assert_called_once()
    (called_rad,), _ = kw["set_fov_rad"].call_args
    assert called_rad == pytest.approx(math.radians(62))


def test_dispatch_fov_clamps_low():
    p, kw = _make()
    p.open()
    p.dispatch_event("fov:42")
    (called_rad,), _ = kw["set_fov_rad"].call_args
    assert called_rad == pytest.approx(math.radians(55))


def test_dispatch_fov_clamps_high():
    p, kw = _make()
    p.open()
    p.dispatch_event("fov:120")
    (called_rad,), _ = kw["set_fov_rad"].call_args
    assert called_rad == pytest.approx(math.radians(75))


def test_dispatch_fov_garbage_value_returns_false():
    p, kw = _make()
    p.open()
    assert p.dispatch_event("fov:not-a-number") is False
    kw["set_fov_rad"].assert_not_called()


def test_dispatch_tab_select_known_tab():
    p, _ = _make(tabs=[("graphics", "Graphics"), ("audio", "Audio")])
    p.open()
    assert p.dispatch_event("tab:audio") is True
    payload = p.render_payload()
    body = json.loads(payload[len("setConfigurationPanel("):-2])
    assert body["selected_tab"] == "audio"


def test_dispatch_tab_unknown_returns_false():
    p, _ = _make()
    p.open()
    assert p.dispatch_event("tab:nonexistent") is False


def test_dispatch_unknown_returns_false():
    p, _ = _make()
    p.open()
    assert p.dispatch_event("bogus") is False
```

- [ ] **Step 6: Run dispatch tests — expect failures**

```bash
uv run pytest tests/unit/test_configuration_panel.py -x
```

Expected: all dispatch_event tests fail (current implementation returns False unconditionally).

- [ ] **Step 7: Implement dispatch_event**

Replace the placeholder `dispatch_event` in `engine/ui/configuration_panel.py` with:

```python
    def dispatch_event(self, action: str) -> bool:
        if action == "cancel":
            self.close()
            return True
        if action == "toggle:dust":
            new_val = not self._settings.dust_on
            self._set_dust(new_val)
            self._settings.dust_on = new_val
            return True
        if action == "toggle:specular":
            new_val = not self._settings.specular_on
            self._set_specular(new_val)
            self._settings.specular_on = new_val
            return True
        if action.startswith("fov:"):
            raw = action[len("fov:"):]
            try:
                deg = int(raw)
            except ValueError:
                return False
            deg = max(FOV_MIN, min(FOV_MAX, deg))
            self._set_fov_rad(math.radians(deg))
            self._settings.fov_deg = deg
            return True
        if action.startswith("tab:"):
            tab_id = action[len("tab:"):]
            if any(tid == tab_id for tid, _ in self._tabs):
                self._selected_tab = tab_id
                return True
            return False
        return False
```

- [ ] **Step 8: Re-run tests**

```bash
uv run pytest tests/unit/test_configuration_panel.py -x
```

Expected: all tests pass.

- [ ] **Step 9: Add render_payload dedup tests**

Append to `tests/unit/test_configuration_panel.py`:

```python
# ---- render_payload dedup -------------------------------------------------

def test_render_payload_first_emit_then_dedups():
    p, _ = _make()
    p.open()
    first = p.render_payload()
    assert first is not None
    assert first.startswith("setConfigurationPanel(")
    assert p.render_payload() is None  # no change → no re-emit


def test_render_payload_re_emits_after_change():
    p, _ = _make()
    p.open()
    p.render_payload()
    p.dispatch_event("toggle:dust")
    second = p.render_payload()
    assert second is not None
    body = json.loads(second[len("setConfigurationPanel("):-2])
    assert body["settings"]["dust_on"] is False


def test_render_payload_close_emits_hide_then_dedups():
    p, _ = _make()
    p.open()
    p.render_payload()
    p.close()
    out = p.render_payload()
    body = json.loads(out[len("setConfigurationPanel("):-2])
    assert body == {"visible": False}
    assert p.render_payload() is None


def test_invalidate_re_emits():
    p, _ = _make()
    p.open()
    first = p.render_payload()
    assert p.render_payload() is None
    p.invalidate()
    re_emit = p.render_payload()
    assert re_emit == first
```

- [ ] **Step 10: Run dedup tests**

```bash
uv run pytest tests/unit/test_configuration_panel.py -x
```

Expected: all dedup tests pass. (Implementation already covers these — they're verifying behaviour, not driving new code.)

- [ ] **Step 11: Add keyboard handling tests**

Append to `tests/unit/test_configuration_panel.py`:

```python
# ---- keyboard input ------------------------------------------------------

class _FakeKeys:
    KEY_UP = 1
    KEY_DOWN = 2
    KEY_LEFT = 3
    KEY_RIGHT = 4
    KEY_SPACE = 5
    KEY_ENTER = 6
    KEY_ESCAPE = 7


class _FakeReader:
    def __init__(self):
        self.keys = _FakeKeys()
        self._pressed = set()

    def press(self, key):
        self._pressed.add(key)

    def key_pressed(self, key):
        if key in self._pressed:
            self._pressed.discard(key)
            return True
        return False


def test_handle_input_when_closed_is_noop():
    p, kw = _make()
    r = _FakeReader()
    r.press(r.keys.KEY_DOWN)
    p.handle_input(r)
    kw["set_dust"].assert_not_called()


def test_focus_first_down_lands_on_first_focusable():
    """Focusable order with one Graphics tab: [tab:graphics, ctrl:dust,
    ctrl:specular, ctrl:fov]. First ↓ from unfocused lands on index 0
    (the tab row)."""
    p, _ = _make()
    p.open()
    r = _FakeReader()
    r.press(r.keys.KEY_DOWN)
    p.handle_input(r)
    payload = p.render_payload()
    body = json.loads(payload[len("setConfigurationPanel("):-2])
    assert body["focused"] == 0


def test_focus_first_up_lands_on_last_focusable():
    p, _ = _make()
    p.open()
    r = _FakeReader()
    r.press(r.keys.KEY_UP)
    p.handle_input(r)
    payload = p.render_payload()
    body = json.loads(payload[len("setConfigurationPanel("):-2])
    assert body["focused"] == 3  # ctrl:fov is last in a 4-item list


def test_focus_wraps_at_bottom():
    p, _ = _make()
    p.open()
    r = _FakeReader()
    for _ in range(5):
        r.press(r.keys.KEY_DOWN)
        p.handle_input(r)
    payload = p.render_payload()
    body = json.loads(payload[len("setConfigurationPanel("):-2])
    assert body["focused"] == 0  # 0,1,2,3,wrap→0


def test_space_on_dust_row_toggles():
    p, kw = _make()
    p.open()
    # Walk focus to ctrl:dust (index 1).
    r = _FakeReader()
    r.press(r.keys.KEY_DOWN); p.handle_input(r)  # 0
    r.press(r.keys.KEY_DOWN); p.handle_input(r)  # 1
    r.press(r.keys.KEY_SPACE); p.handle_input(r)
    kw["set_dust"].assert_called_once_with(False)


def test_right_arrow_on_fov_row_increments():
    p, kw = _make()
    p.open()
    r = _FakeReader()
    for _ in range(4):  # focus → fov (index 3)
        r.press(r.keys.KEY_DOWN); p.handle_input(r)
    r.press(r.keys.KEY_RIGHT); p.handle_input(r)
    (called_rad,), _ = kw["set_fov_rad"].call_args
    assert called_rad == pytest.approx(math.radians(71))  # 70 + 1


def test_left_arrow_on_fov_row_decrements_and_clamps():
    p, kw = _make(initial_settings=SettingsSnapshot(
        dust_on=True, specular_on=True, fov_deg=55,
    ))
    p.open()
    r = _FakeReader()
    for _ in range(4):
        r.press(r.keys.KEY_DOWN); p.handle_input(r)
    r.press(r.keys.KEY_LEFT); p.handle_input(r)
    # Still 55 (clamped), but applier still fires (consistency: every
    # press emits the current state to the renderer).
    (called_rad,), _ = kw["set_fov_rad"].call_args
    assert called_rad == pytest.approx(math.radians(55))


def test_handle_input_missing_optional_keys_does_not_crash():
    """Older bindings may lack KEY_LEFT/RIGHT/SPACE; navigation must
    degrade silently. Only KEY_UP/DOWN/ENTER are required."""

    class _MinimalKeys:
        KEY_UP = 1
        KEY_DOWN = 2
        KEY_ENTER = 3

    class _MinimalReader:
        def __init__(self):
            self.keys = _MinimalKeys()

        def key_pressed(self, key):
            return False

    p, _ = _make()
    p.open()
    p.handle_input(_MinimalReader())  # must not raise


def test_handle_key_esc_when_open_closes():
    p, _ = _make()
    p.open()
    p.handle_key_esc()
    assert p.is_open() is False


def test_handle_key_esc_when_closed_is_noop():
    p, _ = _make()
    p.handle_key_esc()
    assert p.is_open() is False
```

- [ ] **Step 12: Run keyboard tests — expect failures**

```bash
uv run pytest tests/unit/test_configuration_panel.py -x
```

Expected: keyboard tests fail (`handle_input` / `handle_key_esc` don't exist yet).

- [ ] **Step 13: Implement handle_input + handle_key_esc**

Add the focusable-list helper and input handlers to `engine/ui/configuration_panel.py`. Insert these methods inside `ConfigurationPanel` (after `dispatch_event`):

```python
    def handle_key_esc(self) -> None:
        if self._visible:
            self.close()

    def handle_input(self, h) -> None:
        """Poll ↑/↓/←/→/Space/Enter when the panel is visible. Mirrors
        the bindings-module shape PauseMenuModel.handle_input uses.
        Missing optional keys (e.g. KEY_LEFT/RIGHT on older bindings)
        degrade silently."""
        if not self._visible:
            return
        keys = h.keys
        focusables = self._focusables()
        if not focusables:
            return

        if h.key_pressed(keys.KEY_DOWN):
            self._focused = 0 if self._focused < 0 else (self._focused + 1) % len(focusables)
        if h.key_pressed(keys.KEY_UP):
            self._focused = (len(focusables) - 1) if self._focused < 0 \
                else (self._focused - 1) % len(focusables)

        kind, target = focusables[self._focused] if self._focused >= 0 else (None, None)

        # Optional keys — older bindings may omit these. getattr-with-default
        # mirrors PauseMenuModel.handle_input's KEY_ENTER pattern.
        k_space = getattr(keys, "KEY_SPACE", None)
        k_enter = getattr(keys, "KEY_ENTER", None)
        k_left  = getattr(keys, "KEY_LEFT",  None)
        k_right = getattr(keys, "KEY_RIGHT", None)

        def _pressed(code):
            return code is not None and h.key_pressed(code)

        activate = _pressed(k_space) or _pressed(k_enter)

        if activate and kind == "ctrl" and target == "dust":
            self.dispatch_event("toggle:dust")
        elif activate and kind == "ctrl" and target == "specular":
            self.dispatch_event("toggle:specular")
        elif activate and kind == "tab":
            self.dispatch_event("tab:" + target)

        if kind == "ctrl" and target == "fov":
            if _pressed(k_right):
                self.dispatch_event("fov:" + str(self._settings.fov_deg + 1))
            if _pressed(k_left):
                self.dispatch_event("fov:" + str(self._settings.fov_deg - 1))

    def _focusables(self) -> list:
        """Ordered focusable list: tab rows then controls in the
        currently selected tab. For the only tab today (graphics):
        [('tab','graphics'), ('ctrl','dust'), ('ctrl','specular'),
         ('ctrl','fov')]."""
        out: list = [("tab", tid) for tid, _ in self._tabs]
        if self._selected_tab == "graphics":
            out += [("ctrl", "dust"), ("ctrl", "specular"), ("ctrl", "fov")]
        return out
```

- [ ] **Step 14: Run all tests**

```bash
uv run pytest tests/unit/test_configuration_panel.py -v
```

Expected: every test passes.

- [ ] **Step 15: Commit**

```bash
git add engine/ui/configuration_panel.py tests/unit/test_configuration_panel.py
git commit -m "feat(ui): ConfigurationPanel model

Panel subclass that owns the Graphics tab settings (dust, specular,
FOV) and three injected appliers fired on every mutation. Mouse
events arrive via dispatch_event (toggle:*, fov:N, tab:id, cancel);
keyboard nav via handle_input (arrows + space/enter, missing keys
degrade silently). No persistence — close does not revert."
```

---

## Task 4: Pause-menu Configuration row

**Files:**
- Modify: `engine/ui/pause_menu.py:168-208`
- Modify: `tests/unit/test_pause_menu_model.py`

- [ ] **Step 1: Update existing tests for the new signature**

Edit `tests/unit/test_pause_menu_model.py`. The current tests call `default_pause_menu(on_exit=..., on_cancel=...)`. They must all be updated to pass `on_configuration=...`. Use `lambda: None` for tests that don't care about that handler. Use `sed` for the bulk rewrite:

```bash
python - <<'PY'
import re, pathlib
p = pathlib.Path("tests/unit/test_pause_menu_model.py")
src = p.read_text()
# Match `default_pause_menu(on_exit=X, on_cancel=Y)` and insert
# on_configuration between them.
new = re.sub(
    r"default_pause_menu\(on_exit=([^,]+), on_cancel=([^)]+)\)",
    r"default_pause_menu(on_exit=\1, on_configuration=lambda: None, on_cancel=\2)",
    src,
)
p.write_text(new)
PY
```

Then by hand: update the expected action-id lists. Two test assertions need updating:

In `test_default_pause_menu_has_exit_and_cancel`:
```python
    assert [it.action_id for it in m.items] == ["exit", "configuration", "cancel"]
```

In `test_first_focus_prev_lands_on_last_row`:
```python
    assert m.focused_index == 2  # last row in a 3-item list
```

In `test_handle_input_arrows_and_enter`:
```python
    r.press(r.keys.KEY_DOWN)
    m.handle_input(r)
    assert m.focused_index == 0
    r.press(r.keys.KEY_DOWN)
    m.handle_input(r)
    assert m.focused_index == 1  # configuration
    r.press(r.keys.KEY_DOWN)
    m.handle_input(r)
    assert m.focused_index == 2  # cancel
    r.press(r.keys.KEY_ENTER)
    m.handle_input(r)
    assert cancelled == [1] and exited == []
```

In `test_render_payload_first_call_emits_full_state`:
```python
    assert [it["action"] for it in payload["items"]] == ["exit", "configuration", "cancel"]
    assert [it["label"] for it in payload["items"]] == ["Exit Program", "Configuration", "Cancel"]
```

In `test_default_pause_menu_dev_off_has_only_exit_and_cancel`:
```python
    assert [it.action_id for it in m.items] == ["exit", "configuration", "cancel"]
```

In `test_default_pause_menu_dev_on_appends_registered_entries`:
```python
    assert labels == ["Exit Program", "Configuration", "Cancel",
                      "Load Mission…", "Other Dev Thing"]
```

In `test_default_pause_menu_dev_on_with_empty_registry_omits_dev_rows`:
```python
    assert [it.action_id for it in m.items] == ["exit", "configuration", "cancel"]
```

- [ ] **Step 2: Add a new test for the Configuration handler**

Append to `tests/unit/test_pause_menu_model.py`:

```python
def test_default_pause_menu_configuration_row_fires_handler():
    """Selecting the Configuration row dispatches on_configuration."""
    fired = []
    m = default_pause_menu(
        on_exit=lambda: None,
        on_configuration=lambda: fired.append("config"),
        on_cancel=lambda: None,
    )
    assert m.dispatch_event("configuration") is True
    assert fired == ["config"]


def test_default_pause_menu_dev_label_configuration_does_not_shadow_production_row(
        reset_dev_mode_for_pause_menu):
    """A dev entry literally labelled 'Configuration' must not collide
    with the production row's action id."""
    import _dauntless_host
    import engine.dev_mode as dev_mode
    _dauntless_host.developer_mode = True
    dev_mode._dev_pause_menu_entries.clear()
    dev_mode.register_dev_pause_menu_entry("Configuration", lambda: None)
    m = default_pause_menu(
        on_exit=lambda: None,
        on_configuration=lambda: None,
        on_cancel=lambda: None,
    )
    ids = [it.action_id for it in m.items]
    assert ids[:3] == ["exit", "configuration", "cancel"]
    assert ids[3] != "configuration"  # disambiguated, e.g. "configuration-2"
```

- [ ] **Step 3: Run tests — expect failures**

```bash
uv run pytest tests/unit/test_pause_menu_model.py -x
```

Expected: `TypeError: default_pause_menu() got an unexpected keyword argument 'on_configuration'`.

- [ ] **Step 4: Update default_pause_menu**

Edit `engine/ui/pause_menu.py:168-208`. Replace `default_pause_menu` and `_slugify_action_id` with:

```python
def default_pause_menu(*,
                      on_exit: _Handler,
                      on_configuration: _Handler,
                      on_cancel: _Handler) -> PauseMenuModel:
    """Build the dauntless default pause menu: Exit Program +
    Configuration + Cancel.

    Handlers are injected so the model has no compile-time dependency
    on the host loop. The host loop wires on_exit to a quit flag,
    on_configuration to ConfigurationPanel.open + pause-menu-hide
    arbitration, and on_cancel to the pause-controller toggle.

    When dev_mode.is_enabled(), appends one row per entry in
    dev_pause_menu_entries() — in registration order, no separator.
    Dev row action_ids are slugified from the label and disambiguated
    against the production seed {"exit", "configuration", "cancel"}.
    """
    m = PauseMenuModel()
    m.add_item("Exit Program",  "exit",          on_exit)
    m.add_item("Configuration", "configuration", on_configuration)
    m.add_item("Cancel",        "cancel",        on_cancel)

    if dev_mode.is_enabled():
        used: set[str] = {"exit", "configuration", "cancel"}
        for label, handler in dev_mode.dev_pause_menu_entries():
            action_id = _slugify_action_id(label, used)
            used.add(action_id)
            m.add_item(label, action_id, handler)

    return m
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/unit/test_pause_menu_model.py -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add engine/ui/pause_menu.py tests/unit/test_pause_menu_model.py
git commit -m "feat(ui): pause-menu Configuration row

default_pause_menu now requires an on_configuration handler and
inserts a Configuration row between Exit Program and Cancel. The
slug-collision seed includes 'configuration' so a dev entry of
the same name is disambiguated."
```

---

## Task 5: CEF view (HTML / CSS / JS)

**Files:**
- Modify: `native/assets/ui-cef/ship_status.html`
- Create: `native/assets/ui-cef/css/configuration_panel.css`
- Create: `native/assets/ui-cef/js/configuration_panel.js`

No automated tests — Task 7 visually verifies.

- [ ] **Step 1: Add HTML section + asset links**

Edit `native/assets/ui-cef/ship_status.html`. Add to the `<head>` block (after the other stylesheet links, around line 11):

```html
    <link rel="stylesheet" href="css/configuration_panel.css">
```

In the body, after the `<section id="mission-picker" class="dev-only">` block (around line 43), insert:

```html
    <!-- Configuration overlay (production).
         setConfigurationPanel({...}) drives state; clicks fire
         dauntlessEvent('configuration/<verb>:<arg>'). ESC and the Done
         button both fire 'configuration/cancel'.
         Spec: docs/superpowers/specs/2026-06-05-configuration-panel-design.md -->
    <section id="configuration-panel">
      <div class="cp-modal">
        <div class="cp-header">Configuration</div>
        <div class="cp-content">
          <nav class="cp-tabstrip" id="cp-tabstrip"></nav>
          <div class="cp-body" id="cp-body"></div>
        </div>
        <div class="cp-footer">
          <button class="cp-done-button"
                  onclick="dauntlessEvent('configuration/cancel')">
            Done
          </button>
        </div>
      </div>
    </section>
```

At the bottom of the body, alongside the other `<script>` tags (around line 192), add:

```html
    <script src="js/configuration_panel.js"></script>
```

- [ ] **Step 2: Create the stylesheet**

Create `native/assets/ui-cef/css/configuration_panel.css`:

```css
/* Configuration panel — pause-menu modal with vertical left tab
   strip + per-tab body. Hidden by default; setConfigurationPanel
   flips display to 'flex'. Visual palette mirrors the existing
   pause-menu and mission-picker styling.
   Spec: docs/superpowers/specs/2026-06-05-configuration-panel-design.md */

#configuration-panel {
    display: none;
    position: fixed;
    inset: 0;
    align-items: center;
    justify-content: center;
    background: rgba(0, 0, 0, 0.55);
    z-index: 50;
}

.cp-modal {
    width: 640px;
    height: 420px;
    display: flex;
    flex-direction: column;
    background: #0a1620;
    color: #cfe2f3;
    border: 1px solid #2a4d6e;
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.6);
    font-family: sans-serif;
}

.cp-header {
    padding: 12px 16px;
    font-size: 18px;
    font-weight: bold;
    border-bottom: 1px solid #2a4d6e;
}

.cp-content {
    flex: 1;
    display: flex;
    min-height: 0;
}

.cp-tabstrip {
    flex: 0 0 140px;
    border-right: 1px solid #2a4d6e;
    background: #081220;
    display: flex;
    flex-direction: column;
}

.cp-tab {
    padding: 10px 16px;
    cursor: pointer;
    border-left: 3px solid transparent;
}

.cp-tab:hover {
    background: #102536;
}

.cp-tab--active {
    background: #102536;
    border-left-color: #4aa3df;
    font-weight: bold;
}

.cp-tab.cp-focused,
.cp-row.cp-focused {
    outline: 1px solid #4aa3df;
    outline-offset: -1px;
}

.cp-body {
    flex: 1;
    padding: 16px 20px;
    overflow-y: auto;
}

.cp-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 8px 4px;
    border-bottom: 1px solid #16283a;
}

.cp-row__label {
    font-size: 14px;
}

.cp-row__control {
    display: flex;
    align-items: center;
    gap: 8px;
}

.cp-toggle {
    width: 48px;
    height: 22px;
    border: 1px solid #2a4d6e;
    background: #0a1620;
    color: #cfe2f3;
    cursor: pointer;
    font-size: 12px;
}

.cp-toggle--on {
    background: #1f4d6e;
}

.cp-slider {
    width: 200px;
}

.cp-slider-value {
    width: 32px;
    text-align: right;
    font-variant-numeric: tabular-nums;
}

.cp-footer {
    padding: 10px 16px;
    border-top: 1px solid #2a4d6e;
    display: flex;
    justify-content: flex-end;
}

.cp-done-button {
    padding: 6px 18px;
    background: #1f4d6e;
    color: #cfe2f3;
    border: 1px solid #2a4d6e;
    cursor: pointer;
}

.cp-done-button:hover {
    background: #265c80;
}
```

- [ ] **Step 3: Create the JS render fn**

Create `native/assets/ui-cef/js/configuration_panel.js`:

```javascript
// Configuration panel render fn. Driven by Python via
// cef_execute_javascript:
//   setConfigurationPanel({visible:true, tabs, selected_tab, focused, settings});
//   setConfigurationPanel({visible:false});
// Click events fire dauntlessEvent('configuration/<verb>:<arg>').
// Spec: docs/superpowers/specs/2026-06-05-configuration-panel-design.md.

function escapeHtmlCP(s) {
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function _cpFocusableList(state) {
    // Mirror ConfigurationPanel._focusables on the Python side: tabs
    // first, then per-tab controls. Only Graphics ships in this pass.
    const out = state.tabs.map(t => ({kind: 'tab', target: t.id}));
    if (state.selected_tab === 'graphics') {
        out.push({kind: 'ctrl', target: 'dust'});
        out.push({kind: 'ctrl', target: 'specular'});
        out.push({kind: 'ctrl', target: 'fov'});
    }
    return out;
}

function _cpRenderTabstrip(state, focusables) {
    let html = '';
    for (let i = 0; i < state.tabs.length; ++i) {
        const t = state.tabs[i];
        const isActive = t.id === state.selected_tab;
        const isFocused = focusables[state.focused]
            && focusables[state.focused].kind === 'tab'
            && focusables[state.focused].target === t.id;
        const cls = 'cp-tab'
                  + (isActive ? ' cp-tab--active' : '')
                  + (isFocused ? ' cp-focused' : '');
        html += '<div class="' + cls + '"'
              +   ' onclick="dauntlessEvent(\'configuration/tab:' + t.id + '\')">'
              +     escapeHtmlCP(t.label)
              + '</div>';
    }
    return html;
}

function _cpRenderGraphicsBody(state, focusables) {
    const focused = focusables[state.focused] || {};
    const isFoc = (target) => focused.kind === 'ctrl' && focused.target === target;
    const s = state.settings;
    let html = '';

    // Space Dust toggle
    html += '<div class="cp-row' + (isFoc('dust') ? ' cp-focused' : '') + '">'
          +   '<div class="cp-row__label">Space Dust</div>'
          +   '<div class="cp-row__control">'
          +     '<button class="cp-toggle' + (s.dust_on ? ' cp-toggle--on' : '') + '"'
          +        ' onclick="dauntlessEvent(\'configuration/toggle:dust\')">'
          +       (s.dust_on ? 'On' : 'Off')
          +     '</button>'
          +   '</div>'
          + '</div>';

    // Specular Highlights toggle
    html += '<div class="cp-row' + (isFoc('specular') ? ' cp-focused' : '') + '">'
          +   '<div class="cp-row__label">Specular Highlights</div>'
          +   '<div class="cp-row__control">'
          +     '<button class="cp-toggle' + (s.specular_on ? ' cp-toggle--on' : '') + '"'
          +        ' onclick="dauntlessEvent(\'configuration/toggle:specular\')">'
          +       (s.specular_on ? 'On' : 'Off')
          +     '</button>'
          +   '</div>'
          + '</div>';

    // FOV slider — listen on 'change' (released), not 'input' (every
    // pixel), so dragging doesn't flood the CEF event channel.
    html += '<div class="cp-row' + (isFoc('fov') ? ' cp-focused' : '') + '">'
          +   '<div class="cp-row__label">Exterior Camera FOV</div>'
          +   '<div class="cp-row__control">'
          +     '<input class="cp-slider" type="range" min="55" max="75" step="1"'
          +        ' value="' + s.fov_deg + '"'
          +        ' onchange="dauntlessEvent(\'configuration/fov:\' + this.value)">'
          +     '<span class="cp-slider-value">' + s.fov_deg + '°</span>'
          +   '</div>'
          + '</div>';

    return html;
}

function setConfigurationPanel(state) {
    const root = document.getElementById('configuration-panel');
    if (!root) return;
    if (!state || state.visible !== true) {
        root.style.display = 'none';
        return;
    }
    const focusables = _cpFocusableList(state);
    const tabstrip = document.getElementById('cp-tabstrip');
    if (tabstrip) tabstrip.innerHTML = _cpRenderTabstrip(state, focusables);
    const body = document.getElementById('cp-body');
    if (body) {
        if (state.selected_tab === 'graphics') {
            body.innerHTML = _cpRenderGraphicsBody(state, focusables);
        } else {
            body.innerHTML = '';  // future tabs slot in here
        }
    }
    root.style.display = 'flex';
}
```

- [ ] **Step 4: Commit**

```bash
git add native/assets/ui-cef/ship_status.html \
        native/assets/ui-cef/css/configuration_panel.css \
        native/assets/ui-cef/js/configuration_panel.js
git commit -m "feat(ui-cef): configuration panel HTML/CSS/JS scaffold

Tabbed modal with left strip + per-tab body. Graphics tab renders
two toggles and a 55-75 FOV slider. Wired to Python via
setConfigurationPanel(state) and dauntlessEvent('configuration/*')."
```

---

## Task 6: Host-loop wiring

**Files:**
- Modify: `engine/host_loop.py` around the mission-picker block (lines 1992-2029) and ESC routing (lines 2112-2124), and the `_apply_pause_menu_side_effects` helper (lines 1005-1046).

Most fragile task — touches the live game loop. Read the existing mission-picker integration carefully before each edit.

- [ ] **Step 1: Generalize the pause-menu side-effect arbitration**

The existing helper takes a single `picker` argument. We need both the picker AND the configuration panel to hide the pause menu when open. Replace the `_NullPicker` block + `_apply_pause_menu_side_effects` (lines 1005-1046) with a list-based form:

```python
class _NullPicker:
    """Stand-in used when dev_mode is disabled (no MissionPicker
    constructed). Always reports closed so the pause-menu side-effects
    predicate degrades to its original behaviour."""
    def is_open(self) -> bool:
        return False


_NULL_PICKER = _NullPicker()


def _any_blocker_open(blockers) -> bool:
    """True if any of the supplied panel-like objects (each exposing
    is_open()) is currently visible. Used to gate the pause-menu
    visibility — the menu must hide whenever a modal overlays it."""
    return any(b.is_open() for b in blockers)


def _apply_pause_menu_side_effects(pause: "_PauseMenuController",
                                   view_mode: "_ViewModeController",
                                   h,
                                   blockers) -> None:
    """Mirror the pause flag into renderer state: show/hide the CEF
    pause-menu div and unlock the cursor while paused so the player can
    interact with the overlay. Idempotent — only fires when the
    effective visibility has changed since the last call. `h` is the
    bindings module (or fake) exposing cef_execute_javascript and
    set_cursor_locked. `blockers` is an iterable of objects with an
    is_open() method (today: mission picker + configuration panel);
    when any is open, the pause-menu must hide regardless of
    pause.is_open so the blocker isn't occluded.

    On close, the view-mode sync latch is invalidated so the next
    _apply_view_mode_side_effects call re-applies cursor lock + bridge
    pass state from whatever view mode is current.
    """
    target = pause.is_open and not _any_blocker_open(blockers)
    last = getattr(pause, "_last_synced_is_open", None)
    if last == target:
        return
    display = "'flex'" if target else "'none'"
    h.cef_execute_javascript(
        "document.getElementById('pause-menu').style.display = " + display + ";"
    )
    if target:
        h.set_cursor_locked(False)
    else:
        view_mode._last_synced_is_bridge = None
    pause._last_synced_is_open = target
```

- [ ] **Step 2: Construct + register the ConfigurationPanel**

Edit `engine/host_loop.py`. In the block where panels are constructed, after the `mission_picker` construction (around line 2014, before `from engine.ui.pause_menu import default_pause_menu` at line 2015), add:

```python
        # Configuration panel — production-visible pause-menu modal
        # exposing the Graphics tab (dust, specular, FOV). Settings
        # apply live; no persistence in this iteration. Construction
        # uses the live director FOV so opening the panel doesn't lie
        # about the current value.
        from engine.ui.configuration_panel import (
            ConfigurationPanel, SettingsSnapshot,
        )
        import math as _cp_math
        configuration_panel = ConfigurationPanel(
            tabs=[("graphics", "Graphics")],
            initial_settings=SettingsSnapshot(
                dust_on=True,
                specular_on=True,
                fov_deg=int(round(_cp_math.degrees(
                    director.fov_y_rad
                ))),
            ),
            set_dust=r.set_dust_enabled,
            set_specular=r.set_specular_enabled,
            set_fov_rad=director.set_fov,
        )
```

The camera director is named `director` in this scope (constructed at `engine/host_loop.py:1955`); the renderer module is already aliased as `r` at file-level (`engine/host_loop.py:16`), so both `r.set_dust_enabled` and `r.set_specular_enabled` resolve.

- [ ] **Step 3: Wire the pause-menu Configuration row**

In `engine/host_loop.py`, update the existing `default_pause_menu(...)` call (lines 2017-2020) to include the new handler:

```python
        pause_menu = default_pause_menu(
            on_exit=pause.request_quit,
            on_configuration=configuration_panel.open,
            on_cancel=pause.close,
        )
```

- [ ] **Step 4: Register the panel**

Below the existing `registry.register(...)` calls (line 2023-2029), add:

```python
        registry.register(configuration_panel)
```

Place it after `registry.register(sdk_mirror)` and before the dev-mode block — production panels register unconditionally.

- [ ] **Step 5: Update the ESC + arbitration call site**

Find the `_apply_pause_menu_side_effects(pause, view_mode, _h, mission_picker)` call (line 2117) and replace it with the list form:

```python
                _apply_pause_menu_side_effects(
                    pause, view_mode, _h,
                    [mission_picker, configuration_panel],
                )
```

ESC routing — find the block at lines 2107-2117. Extend the ESC-priority cascade so the configuration panel claims ESC after the mission picker:

```python
                # ESC priority: mission picker (when open) first, then
                # configuration panel (when open), otherwise the pause
                # menu toggle. Both modal blockers close on ESC and
                # return the user to the pause menu.
                if mission_picker.is_open():
                    if _h.key_pressed(_h.keys.KEY_ESCAPE):
                        mission_picker.handle_key_esc()
                elif configuration_panel.is_open():
                    if _h.key_pressed(_h.keys.KEY_ESCAPE):
                        configuration_panel.handle_key_esc()
                else:
                    pause.apply(_h)
```

- [ ] **Step 6: Suppress pause-menu input while the configuration panel is open + route input to the panel**

Find the block at lines 2118-2127. Replace the `if pause.is_open:` body with:

```python
                if pause.is_open:
                    # When the configuration panel is open it consumes
                    # keyboard input — pause-menu navigation would
                    # otherwise activate rows hidden behind the modal.
                    if configuration_panel.is_open():
                        configuration_panel.handle_input(_h)
                    elif not mission_picker.is_open():
                        pause_menu.handle_input(_h)
                        _script = pause_menu.render_payload()
                        if _script is not None:
                            _h.cef_execute_javascript(_script)
                    # Forward mouse to CEF only while paused — keeps
                    # normal-gameplay input out of the overlay. The
                    # event-handler callback installed at startup turns
                    # JS clicks into pause_menu.dispatch_event(name).
                    #
                    # cursor_pos() returns FRAMEBUFFER (physical) pixels —
                    # ... (rest of the existing comment + code unchanged)
```

Keep all lines after the mouse-forwarding comment block exactly as they were. The only change inside the `if pause.is_open:` body is the input-routing dispatch above.

- [ ] **Step 7: Build (no shader changes, no reconfigure needed)**

```bash
cmake --build build -j
```

Expected: clean build. If the build fails because of `camera_director` lookup or `r` alias mismatch, fix the names per step 2's grep guidance.

- [ ] **Step 8: Run the pause-menu host tests**

```bash
uv run pytest tests/host/test_pause_menu.py -v
```

Expected: existing tests pass (they should still construct the pause menu via `default_pause_menu`, which now requires `on_configuration`; if any test breaks because of the missing kwarg, add `on_configuration=lambda: None` at the test call site).

- [ ] **Step 9: Commit**

```bash
git add engine/host_loop.py tests/host/test_pause_menu.py
git commit -m "feat(host): wire ConfigurationPanel into the pause flow

Construct + register the panel, route the Configuration row to
ConfigurationPanel.open, extend ESC routing so the panel claims
ESC before falling through to the pause toggle, and generalize the
pause-menu side-effect arbitration to a blocker-list so the menu
hides whenever any modal (mission picker or configuration panel)
is visible."
```

---

## Task 7: Visual verification

**Files:** none modified — this is a manual run to confirm the wiring lands in the real CEF browser. Per CLAUDE.md, UI changes require launching the app and exercising the feature before declaring done.

- [ ] **Step 1: Launch the game**

Run the built binary:

```bash
./build/dauntless
```

- [ ] **Step 2: Open the pause menu**

Press ESC. Expected: pause menu overlay appears with three rows in this order — **Exit Program**, **Configuration**, **Cancel**.

- [ ] **Step 3: Click Configuration**

Expected: pause menu hides, configuration modal appears centred. Modal has:
- "Configuration" header
- Left tab strip with one entry: **Graphics** (highlighted as active)
- Body with three rows:
  - **Space Dust** with `On` toggle button (filled colour)
  - **Specular Highlights** with `On` toggle button (filled colour)
  - **Exterior Camera FOV** with a slider centred at 70° and the value `70°` next to it
- Footer with a **Done** button

- [ ] **Step 4: Toggle Space Dust off**

Click the Space Dust **On** button. Expected: button reads **Off** (de-filled). The dust-particle haze should disappear from behind the modal (modal sits on top of the scene but you can see edges).

Click again. Expected: dust returns, button reads **On**.

- [ ] **Step 5: Toggle Specular Highlights off**

Click the Specular Highlights **On** button. Expected: button reads **Off**, and any visible ship surfaces in the background scene lose their bright specular hotspots (matte appearance).

Click again. Expected: specular returns, button reads **On**.

- [ ] **Step 6: Drag the FOV slider**

Drag the slider all the way to the left (55°). Expected: readout shows `55°`; scene behind the modal noticeably narrows (longer effective focal length).

Drag to the right (75°). Expected: readout shows `75°`; scene widens.

Return to 70° (or somewhere in the middle).

- [ ] **Step 7: Press ESC**

Expected: configuration modal hides; pause menu reappears.

- [ ] **Step 8: Re-open Configuration**

Click Configuration again. Expected: modal re-opens. Settings reflect the **live engine state** — so if step 6 left the FOV at 70°, the slider should still show 70°, not jump back to a default. (This is the "seed from live state" guarantee.)

- [ ] **Step 9: Close via Done button**

Click **Done**. Expected: modal hides; pause menu reappears.

- [ ] **Step 10: Keyboard navigation smoke test**

With pause menu open, click Configuration (or arrow + Enter to it). Press ↓ four times to walk through the focusable list:

1. ↓ → focus highlights the Graphics tab row (left strip).
2. ↓ → focus highlights the Space Dust row.
3. ↓ → focus highlights the Specular Highlights row.
4. ↓ → focus highlights the FOV row.
5. ↓ → focus wraps back to the Graphics tab row.

With focus on the FOV row, press → and ← a few times. Expected: slider value increments / decrements by 1° per press, clamped to [55, 75].

With focus on Space Dust, press Space. Expected: toggle flips.

Press ESC. Expected: modal closes.

- [ ] **Step 11: Final full test run**

```bash
uv run pytest tests/unit/test_configuration_panel.py \
              tests/unit/test_pause_menu_model.py \
              tests/host/test_pause_menu.py -v
```

Expected: all pass.

- [ ] **Step 12: Run a broader sanity sweep**

Per project memory, full `pytest` OOMs the host. Use focused subsets — UI + host:

```bash
uv run pytest tests/unit/test_configuration_panel.py \
              tests/unit/test_pause_menu_model.py \
              tests/unit/test_dev_mission_picker.py \
              tests/host/test_pause_menu.py -v
```

Expected: all pass. If a mission-picker test breaks because of the blocker-list refactor, debug by re-reading Task 6 step 1 — the `_NullPicker` stand-in is still in use for dev-mode-off runs and must still satisfy `is_open()`.

- [ ] **Step 13: Commit the verification (no code, just a checkpoint)**

If any changes were needed during verification, commit those. Otherwise no commit is required — the prior commits are the deliverable.

---

## Notes

- **Per CLAUDE.md**, every shader edit requires `cmake -B build -S . && cmake --build build -j` (full reconfigure), not just `cmake --build`. Step 5 of Task 1 calls this out explicitly.
- **Per project memory**, the full pytest suite OOMs — Task 7 step 12 uses a focused subset.
- **Settings do not persist.** Re-launching the game returns dust/specular/FOV to their live engine defaults. If persistence is added later, the integration point is `ConfigurationPanel.__init__`'s `initial_settings` argument.
