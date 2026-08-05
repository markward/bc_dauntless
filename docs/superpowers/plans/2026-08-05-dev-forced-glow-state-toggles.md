# Developer Forced Glow-State Toggles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two dev-only toggles that force every subsystem's visual glow state to DISABLED (flicker) or DESTROYED (off) so light behaviour can be previewed without combat damage.

**Architecture:** A `dev_light_preview` flag module (mirrors `dev_combat_cheats`) + a two-line dev-gated override at the top of `subsystem_glow.glow_state`; a new "Lighting" tab of two toggles in the Developer Options panel + its CEF JS. Pure visual, dev-gated, production byte-identical.

**Tech Stack:** Python 3 (pytest), CEF (JS). No C++.

**Design doc:** `docs/superpowers/specs/2026-08-05-dev-forced-glow-state-toggles-design.md`

## Global Constraints

- **Dev-mode gated** at the getter (`forced_glow_state()` ANDs `dev_mode.is_enabled()`) — production byte-identical even if a flag were somehow set.
- **Mutually exclusive** via a single `_forced_state` variable (setting one clears the other).
- **Pure visual** — never writes real IsDisabled/IsDestroyed; no gameplay/AI/collision effect.
- **No import cycle:** `dev_light_preview` imports `subsystem_glow` (for the DISABLED/DESTROYED constants); `subsystem_glow.glow_state` LAZY-imports `dev_light_preview` inside the function (`dev_mode` imports neither, so this is safe).
- CEF mouse-only for clicks (the panel's existing keyboard focus-nav is reused).
- No renderer/C++/persistence change. Gate: `scripts/check_tests.sh`.

---

### Task 1: `dev_light_preview` module + `glow_state` override

**Files:**
- Create: `engine/dev_light_preview.py`
- Modify: `engine/appc/subsystem_glow.py` (`glow_state`, ~line 94)
- Test: `tests/unit/test_dev_light_preview.py` (create)

**Interfaces:**
- Consumes: `engine.dev_mode.is_enabled()`; `subsystem_glow.DISABLED`, `.DESTROYED`, `.HEALTHY`.
- Produces: `dev_light_preview.set_systems_damaged(bool)`, `.set_systems_disabled(bool)`, `.forced_glow_state()`, `.systems_damaged_active()`, `.systems_disabled_active()`, `.reset()`. Task 2's panel calls the setters/active-getters.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_dev_light_preview.py`. Patch dev-mode enablement the way other dev-flag tests do — check `tests/unit/test_dev_combat_cheats.py` (if present) or grep how `dev_mode.is_enabled` is toggled in tests (likely `monkeypatch.setattr(dev_mode, "_enabled", True)` or a `dev_mode` test helper). Mirror that.

```python
import pytest
from engine import dev_light_preview, dev_mode
from engine.appc import subsystem_glow


@pytest.fixture(autouse=True)
def _dev_on(monkeypatch):
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: True)
    dev_light_preview.reset()
    yield
    dev_light_preview.reset()


def test_damaged_and_disabled_are_mutually_exclusive():
    dev_light_preview.set_systems_damaged(True)
    assert dev_light_preview.forced_glow_state() == subsystem_glow.DISABLED
    assert dev_light_preview.systems_damaged_active()
    assert not dev_light_preview.systems_disabled_active()
    # turning on 'disabled' clears 'damaged'
    dev_light_preview.set_systems_disabled(True)
    assert dev_light_preview.forced_glow_state() == subsystem_glow.DESTROYED
    assert dev_light_preview.systems_disabled_active()
    assert not dev_light_preview.systems_damaged_active()
    # turning it off returns to no forced state
    dev_light_preview.set_systems_disabled(False)
    assert dev_light_preview.forced_glow_state() is None


def test_forced_state_gated_off_when_dev_disabled(monkeypatch):
    dev_light_preview.set_systems_damaged(True)
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: False)
    assert dev_light_preview.forced_glow_state() is None
    assert not dev_light_preview.systems_damaged_active()


def test_glow_state_returns_forced_for_any_sub():
    class _Sub:
        def IsDestroyed(self): return False
        def IsDisabled(self): return False
    dev_light_preview.set_systems_damaged(True)
    assert subsystem_glow.glow_state(_Sub()) == subsystem_glow.DISABLED
    assert subsystem_glow.glow_state(None) == subsystem_glow.DISABLED
    dev_light_preview.set_systems_disabled(True)
    assert subsystem_glow.glow_state(_Sub()) == subsystem_glow.DESTROYED


def test_glow_state_real_classification_when_not_forced():
    class _Healthy:
        def IsDestroyed(self): return False
        def IsDisabled(self): return False
    class _Dis:
        def IsDestroyed(self): return False
        def IsDisabled(self): return True
    # no forced state -> real classification (byte-identical to today)
    assert subsystem_glow.glow_state(_Healthy()) == subsystem_glow.HEALTHY
    assert subsystem_glow.glow_state(_Dis()) == subsystem_glow.DISABLED
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_dev_light_preview.py -v`
Expected: FAIL — `engine.dev_light_preview` does not exist.

- [ ] **Step 3: Create the flag module**

Create `engine/dev_light_preview.py` exactly as the design doc specifies (imports `dev_mode` + `subsystem_glow`; `_forced_state`; `set_systems_damaged`/`set_systems_disabled` mutually exclusive; `forced_glow_state` ANDed with `dev_mode.is_enabled()`; `systems_damaged_active`/`systems_disabled_active`; `reset`). Include the module docstring noting it's the dev seam and the damaged→DISABLED / disabled→DESTROYED mapping.

- [ ] **Step 4: Add the `glow_state` override**

In `engine/appc/subsystem_glow.py`, at the TOP of `glow_state(sub)` (before the `if sub is None` check), add the lazy-import override:

```python
def glow_state(sub) -> str:
    """Three-state classification. Destroyed dominates disabled; None=healthy.
    A dev-only forced-state preview (Developer Options -> Lighting) overrides
    this for ALL subsystems when set -- purely visual, gated on dev mode."""
    from engine import dev_light_preview          # lazy: avoids an import cycle
    forced = dev_light_preview.forced_glow_state()
    if forced is not None:
        return forced
    if sub is None:
        return HEALTHY
    if sub.IsDestroyed():
        return DESTROYED
    if sub.IsDisabled():
        return DISABLED
    return HEALTHY
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_dev_light_preview.py -v`
Expected: PASS.

- [ ] **Step 6: Regression — glow/emitter suites unaffected**

Run: `uv run pytest tests/ -k "glow or emitter or subsystem_glow" -q`
Expected: PASS (production path unchanged — no forced state set, and default test dev-mode is off).

- [ ] **Step 7: Commit**

```bash
git add engine/dev_light_preview.py engine/appc/subsystem_glow.py tests/unit/test_dev_light_preview.py
git commit -m "feat(dev): forced glow-state preview flag + glow_state override"
```

---

### Task 2: Developer Options "Lighting" tab + toggles

**Files:**
- Modify: `engine/ui/developer_options_panel.py`
- Modify: `native/assets/ui-cef/js/developer_options.js`
- Test: `tests/ui/test_developer_options_lighting_tab.py` (create)

**Interfaces:**
- Consumes: Task 1's `dev_light_preview.set_systems_damaged`, `.set_systems_disabled`, `.systems_damaged_active`, `.systems_disabled_active`.
- Produces: the "Lighting" tab + `toggle:systems_damaged` / `toggle:systems_disabled` dispatch handling + payload `settings.systems_damaged` / `.systems_disabled`.

- [ ] **Step 1: Write the failing test**

Create `tests/ui/test_developer_options_lighting_tab.py`. Build a `DeveloperOptionsPanel` with dev-mode enabled (patch `dev_mode.is_enabled`), open it, and assert the lighting tab + toggle behaviour:

```python
import json
import pytest
from engine.ui.developer_options_panel import DeveloperOptionsPanel
from engine import dev_light_preview, dev_mode
from engine.appc import subsystem_glow


@pytest.fixture(autouse=True)
def _dev_on(monkeypatch):
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: True)
    dev_light_preview.reset()
    yield
    dev_light_preview.reset()


def _payload(p):
    js = p.render_payload()
    assert js is not None
    return json.loads(js[js.index("(") + 1: js.rindex(")")])


def test_lighting_tab_present_and_toggles_mutually_exclusive():
    p = DeveloperOptionsPanel()
    p.open()
    data = _payload(p)
    assert any(t["id"] == "lighting" for t in data["tabs"])
    assert data["settings"]["systems_damaged"] is False
    assert data["settings"]["systems_disabled"] is False

    assert p.dispatch_event("tab:lighting")
    assert p.dispatch_event("toggle:systems_damaged")
    assert dev_light_preview.forced_glow_state() == subsystem_glow.DISABLED
    data = _payload(p)
    assert data["settings"]["systems_damaged"] is True
    assert data["settings"]["systems_disabled"] is False

    # turning on 'disabled' clears 'damaged' in BOTH the flag and the panel mirror
    assert p.dispatch_event("toggle:systems_disabled")
    assert dev_light_preview.forced_glow_state() == subsystem_glow.DESTROYED
    data = _payload(p)
    assert data["settings"]["systems_damaged"] is False
    assert data["settings"]["systems_disabled"] is True

    # toggling it off returns to no forced state
    assert p.dispatch_event("toggle:systems_disabled")
    assert dev_light_preview.forced_glow_state() is None


def test_lighting_focusables_include_the_two_controls():
    p = DeveloperOptionsPanel()
    p.open()
    p.dispatch_event("tab:lighting")
    foc = p._focusables()
    assert ("ctrl", "systems_damaged") in foc
    assert ("ctrl", "systems_disabled") in foc


JS = "native/assets/ui-cef/js/developer_options.js"

def test_js_renders_lighting_toggles():
    text = open(JS).read()
    assert "systems_damaged" in text
    assert "systems_disabled" in text
    assert "Set Systems Damaged" in text
    assert "Set Systems Disabled" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/ui/test_developer_options_lighting_tab.py -v`
Expected: FAIL — no lighting tab / no `systems_damaged` handling / JS lacks the toggles.

- [ ] **Step 3: Panel — tab, mirrors, payload, dispatch, focusables**

In `engine/ui/developer_options_panel.py`:
- Add `from engine import dev_light_preview as light_preview` near the `cheats` import.
- `_tabs`: `[("combat", "Combat"), ("lighting", "Lighting")]`.
- `__init__` and `open()`: add `self._systems_damaged = light_preview.systems_damaged_active()` and `self._systems_disabled = light_preview.systems_disabled_active()`.
- `render_payload` snapshot tuple: append `self._systems_damaged, self._systems_disabled`; `settings` dict: add `"systems_damaged": self._systems_damaged, "systems_disabled": self._systems_disabled`.
- `dispatch_event`: add (the mutually-exclusive setters mean BOTH mirrors must be re-synced after either toggle):

```python
        if action == "toggle:systems_damaged":
            light_preview.set_systems_damaged(not self._systems_damaged)
            self._systems_damaged = light_preview.systems_damaged_active()
            self._systems_disabled = light_preview.systems_disabled_active()
            return True
        if action == "toggle:systems_disabled":
            light_preview.set_systems_disabled(not self._systems_disabled)
            self._systems_damaged = light_preview.systems_damaged_active()
            self._systems_disabled = light_preview.systems_disabled_active()
            return True
```

- `_focusables`: after the combat block, add:

```python
        if self._selected_tab == "lighting":
            out += [("ctrl", "systems_damaged"), ("ctrl", "systems_disabled")]
```

- [ ] **Step 4: CEF JS — lighting body + focusables**

In `native/assets/ui-cef/js/developer_options.js`:
- `_doFocusableList`: add, after the combat block:

```javascript
    if (state.selected_tab === 'lighting') {
        out.push({kind: 'ctrl', target: 'systems_damaged'});
        out.push({kind: 'ctrl', target: 'systems_disabled'});
    }
```

- Add a renderer mirroring `_doRenderCombatBody`:

```javascript
function _doRenderLightingBody(state, focusables) {
    const focused = focusables[state.focused] || {};
    const isFoc = (target) => focused.kind === 'ctrl' && focused.target === target;
    const s = state.settings;
    let html = '';
    html += _doToggleRow('Set Systems Damaged', 'systems_damaged',
                         s.systems_damaged, isFoc('systems_damaged'));
    html += _doToggleRow('Set Systems Disabled', 'systems_disabled',
                         s.systems_disabled, isFoc('systems_disabled'));
    return html;
}
```

- `setDeveloperOptions`: extend the body selection:

```javascript
        body.innerHTML =
            (state.selected_tab === 'combat')   ? _doRenderCombatBody(state, focusables)
          : (state.selected_tab === 'lighting') ? _doRenderLightingBody(state, focusables)
          : '';
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/ui/test_developer_options_lighting_tab.py -v`
Expected: PASS.

- [ ] **Step 6: Full gate**

Run: `scripts/check_tests.sh`
Expected: OK — no new failures (1 known baselined). No C++ changed.

- [ ] **Step 7: Commit**

```bash
git add engine/ui/developer_options_panel.py native/assets/ui-cef/js/developer_options.js tests/ui/test_developer_options_lighting_tab.py
git commit -m "feat(dev): Developer Options Lighting tab — force damaged/disabled light states"
```

---

## Self-review notes

- **Spec coverage:** flag module + `glow_state` hook (Task 1); panel tab + toggles + JS (Task 2). Full coverage.
- **Type consistency:** `forced_glow_state()` returns `subsystem_glow.DISABLED`/`DESTROYED`/`None`; panel toggle keys `systems_damaged`/`systems_disabled` match the dispatch strings and the JS; payload `settings` keys match what the JS reads.
- **Ordering:** Task 2's panel calls Task 1's setters/getters — Task 1 first.
- **Risk:** import cycle (mitigated: lazy import in `glow_state`, verified `dev_mode` imports neither appc nor the flag module); the mutually-exclusive re-sync of both mirrors after either toggle (both toggle handlers re-read both active getters).
