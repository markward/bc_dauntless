# Bridge Menu Hotkeys (F1–F5) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** F1–F5 toggle the five bridge menus in the CEF crew-menu bar through the SDK's own input pipeline (stock mapping: F1 Helm, F2 Tactical, F3 XO, F4 Science, F5 Engineering), with panel-owned open-state shared by keys and clicks, and ESC closing an open menu before the pause menu.

**Architecture:** Per the spec ([2026-06-12-bridge-menu-hotkeys-design.md](../specs/2026-06-12-bridge-menu-hotkeys-design.md)). Host polls GLFW F1–F5 edges → `g_kInputManager.OnKeyDown(WC_Fn)` → existing SDK chain (`KeyConfig` registration + `DefaultKeyboardBinding` bindings, both already run at startup) → `ET_INPUT_TALK_TO_*` at the TCW → new `crew_menu_hotkeys` handlers → `CrewMenuPanel.toggle_menu`. Open-state moves from JS to the panel; JS renders the payload's `"open"` flag and sends `toggle:<id>` on title clicks.

**Tech Stack:** pybind11 constants (C++ rebuild), Python shims, pytest focused subsets ONLY (full suite OOMs — >100 GB RAM). If `uv run` hangs >60s another session holds the uv lock — use `.venv/bin/python -m pytest` instead.

**Key verified facts (do not re-derive):**
- `engine/appc/input.py`: `TGInputManager.OnKeyDown(wc)` emits only if `wc in self._registered`; `KeyConfig.MapScancodes()` (already called in host_loop `_bootstrap_sdk_input`, ~line 110) does `RegisterUnicodeKey(App.WC_F1, App.KY_F1, pDatabase, "F1")` — real ints make those registrations live. `DefaultKeyboardBinding.Initialize()` (also already called) binds `(WC_Fn, KS_KEYDOWN) → ET_INPUT_TALK_TO_*` with destination defaulting to the TCW (sdk DefaultKeyboardBinding.py:121-125). Only KS_KEYDOWN is bound for F-keys.
- Existing WC_/KY_ constants in input.py: WC_LBUTTON 0x01, WC_RBUTTON 0x02, WC_MBUTTON 0x04. Use 0x70–0x74 for F1–F5 (Windows VK_F1..F5 values — mnemonic, no collision).
- `native/src/host/host_bindings.cc` keys block at ~line 1312 has `KEY_F7..KEY_F10, KEY_F12`; F1–F5 missing. Host exposes `key_pressed(key)` (rising edge) and `key_state(key)` (level) but NO `key_released` — derive falling edges from `key_state` with a prev dict.
- Mouse poll call site: `engine/host_loop.py:2692` `_poll_mouse_buttons(_h)` — add the F-key poll beside it.
- ESC modal ladder: `engine/host_loop.py:2360-2378` — `elif` chain (mission_picker → developer_options → ship_property_viewer → configuration_panel → `else: pause.apply(_h)`). Crew-menu close becomes a new `elif` immediately before the final `else`.
- `CrewMenuPanel` (engine/ui/crew_menu_panel.py): `_snapshot_node` builds nodes, `dispatch_event` handles `click:<id>`, `_widgets_by_id` map rebuilt each render. `ensure_widget_id(widget)` from engine/appc/tg_ui/widgets.
- `crew_menus.js`: module-level `crewMenuOpenId` + title onclick toggles local class — to be replaced by payload-driven `open`.
- `reset_sdk_globals` (engine/host_loop.py ~1330s) has a best-effort try-block that nulls `TacticalControlWindow._instance`, re-points `g_kKeyboardBinding.SetDefaultDestination(TacticalControlWindow.GetInstance())`, resets st_widgets + ship_display + LoadBridge flag. The hotkeys `rewire()` goes right after the keyboard re-point.
- TGL label lookup pattern (LoadBridge.py epilogue): `App.g_kLocalizationManager.Load("data/TGL/Bridge Menus.tgl")` → `GetString("Helm")` → `tcw.FindMenu(label)` → `Unload(db)`.
- App constants `ET_INPUT_TALK_TO_HELM/TACTICAL/XO/SCIENCE/ENGINEERING` already exist (App.py 1041–1045).
- Panel registration/construction: engine/host_loop.py ~2231 (`crew_menu_panel = CrewMenuPanel()`).

**Branch:** create `feat/bridge-menu-hotkeys` off main before Task 1.

---

### Task 1: WC/KY F-key constants + registration smoke test

**Files:**
- Modify: `engine/appc/input.py` (constants block, lines 14–24)
- Modify: `App.py` (the `from engine.appc.input import (...)` block)
- Test: `tests/unit/test_fkey_input_chain.py` (new)

- [ ] **Step 1: Write the failing test**

```python
"""F1-F5 reach the SDK input pipeline: KeyConfig registers WC_F1..F5 with
real codes, DefaultKeyboardBinding binds them to ET_INPUT_TALK_TO_*, and
OnKeyDown(WC_F1) lands an ET_INPUT_TALK_TO_HELM event at the TCW.
Spec: docs/superpowers/specs/2026-06-12-bridge-menu-hotkeys-design.md
"""
import App
from engine.appc.windows import TacticalControlWindow

STOCK_MAP = {
    "WC_F1": "ET_INPUT_TALK_TO_HELM",
    "WC_F2": "ET_INPUT_TALK_TO_TACTICAL",
    "WC_F3": "ET_INPUT_TALK_TO_XO",
    "WC_F4": "ET_INPUT_TALK_TO_SCIENCE",
    "WC_F5": "ET_INPUT_TALK_TO_ENGINEERING",
}


def test_fkey_constants_are_real_distinct_ints():
    wc = [getattr(App, f"WC_F{n}") for n in range(1, 6)]
    ky = [getattr(App, f"KY_F{n}") for n in range(1, 6)]
    assert all(type(v) is int for v in wc + ky)
    assert len(set(wc)) == 5
    # No collision with the mouse-button codes.
    assert not set(wc) & {App.WC_LBUTTON, App.WC_RBUTTON, App.WC_MBUTTON}


_received = []


def _record(dest, event):
    _received.append(event.GetEventType())


def test_f1_keydown_reaches_tcw_through_sdk_pipeline():
    _received.clear()
    TacticalControlWindow._instance = None
    tcw = TacticalControlWindow.GetInstance()
    App.g_kKeyboardBinding.SetDefaultDestination(tcw)
    tcw.AddPythonFuncHandlerForInstance(
        App.ET_INPUT_TALK_TO_HELM, __name__ + "._record")

    import KeyConfig
    KeyConfig.MapScancodes()
    import DefaultKeyboardBinding
    DefaultKeyboardBinding.Initialize()

    App.g_kInputManager.OnKeyDown(App.WC_F1)
    assert App.ET_INPUT_TALK_TO_HELM in _received


def test_stock_mapping_bound_for_all_five():
    import KeyConfig, DefaultKeyboardBinding
    KeyConfig.MapScancodes()
    DefaultKeyboardBinding.Initialize()
    from engine.appc.input import KS_KEYDOWN
    for wc_name, et_name in STOCK_MAP.items():
        key = (getattr(App, wc_name), KS_KEYDOWN)
        binding = App.g_kKeyboardBinding._bindings.get(key)
        assert binding is not None, wc_name
        assert binding[0] == getattr(App, et_name), wc_name
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/unit/test_fkey_input_chain.py -v`
Expected: FAIL — `type(v) is int` False (stubs); the pipeline tests fail on stub key codes collapsing to one binding.

- [ ] **Step 3: Implement constants**

In `engine/appc/input.py`, extend the constants block after `KY_MBUTTON`:

```python
# Function keys — Windows VK_F1..F5 values (KeyConfig.MapScancodes
# registers them; DefaultKeyboardBinding.py:121-125 binds them to
# ET_INPUT_TALK_TO_*). KY_ mirrors WC_ like the mouse buttons above.
WC_F1: int = 0x70
WC_F2: int = 0x71
WC_F3: int = 0x72
WC_F4: int = 0x73
WC_F5: int = 0x74
KY_F1: int = 0x70
KY_F2: int = 0x71
KY_F3: int = 0x72
KY_F4: int = 0x73
KY_F5: int = 0x74
```

In `App.py`, add `WC_F1, WC_F2, WC_F3, WC_F4, WC_F5, KY_F1, KY_F2, KY_F3, KY_F4, KY_F5,` to the existing `from engine.appc.input import (...)` list.

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/unit/test_fkey_input_chain.py -v`
Expected: all 3 PASS. If `KeyConfig.MapScancodes()` or `DefaultKeyboardBinding.Initialize()` raises on OTHER stub constants (WC_F6.., KY_SHIFT variants), they already run at host startup today, so they must already tolerate stubs — do not chase; if a NEW failure appears it means an int() call hit a stub that used to be absent: report it rather than patching broadly.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/input.py App.py tests/unit/test_fkey_input_chain.py
git commit -m "feat(hotkeys): real WC_F1-F5/KY_F1-F5 through the SDK input pipeline"
```

---

### Task 2: GLFW KEY_F1–F5 exposure (C++)

**Files:**
- Modify: `native/src/host/host_bindings.cc` (keys block, ~line 1312)

- [ ] **Step 1: Add constants**

Next to the existing `keys.attr("KEY_F7") = GLFW_KEY_F7;` lines, add (matching alignment style):

```cpp
    keys.attr("KEY_F1")    = GLFW_KEY_F1;
    keys.attr("KEY_F2")    = GLFW_KEY_F2;
    keys.attr("KEY_F3")    = GLFW_KEY_F3;
    keys.attr("KEY_F4")    = GLFW_KEY_F4;
    keys.attr("KEY_F5")    = GLFW_KEY_F5;
```

- [ ] **Step 2: Rebuild**

Run: `cmake --build build -j 2>&1 | tail -2`
Expected: `Built target dauntless` (no reconfigure needed for .cc edits).

- [ ] **Step 3: Verify the binding**

Run: `.venv/bin/python -c "import sys; sys.path.insert(0, 'build/python'); import _open_stbc_host as h; print(h.keys.KEY_F1, h.keys.KEY_F5)"`
Expected: `290 294` (GLFW F1..F5). If the module name differs, check `ls build/python/` and adapt.

- [ ] **Step 4: Commit**

```bash
git add native/src/host/host_bindings.cc
git commit -m "feat(hotkeys): expose GLFW KEY_F1-F5 to Python"
```

---

### Task 3: CrewMenuPanel open-state ownership

**Files:**
- Modify: `engine/ui/crew_menu_panel.py`
- Test: `tests/unit/test_crew_menu_panel.py` (append)

- [ ] **Step 1: Write the failing tests (append; file already has `_build_helm_with_button` and imports)**

```python
def test_toggle_menu_open_switch_close():
    helm, _ = _build_helm_with_button()
    from engine.appc.characters import STTopLevelMenu
    tactical = STTopLevelMenu("Tactical")
    TacticalControlWindow.GetInstance().AddMenuToList(tactical)
    panel = CrewMenuPanel()
    panel.render_payload()

    panel.toggle_menu(helm)
    assert panel.has_open_menu()
    payload = json.loads(panel.render_payload()[len("setCrewMenus("):-2])
    opens = {m["label"]: m["open"] for m in payload["menus"]}
    assert opens == {"Helm": True, "Tactical": False}

    panel.toggle_menu(tactical)            # switch: single-open invariant
    payload = json.loads(panel.render_payload()[len("setCrewMenus("):-2])
    opens = {m["label"]: m["open"] for m in payload["menus"]}
    assert opens == {"Helm": False, "Tactical": True}

    panel.toggle_menu(tactical)            # same again: close
    assert not panel.has_open_menu()


def test_close_open_menu_returns_whether_closed():
    helm, _ = _build_helm_with_button()
    panel = CrewMenuPanel()
    panel.render_payload()
    assert panel.close_open_menu() is False
    panel.toggle_menu(helm)
    assert panel.close_open_menu() is True
    assert panel.close_open_menu() is False


def test_dispatch_toggle_action():
    helm, _ = _build_helm_with_button()
    panel = CrewMenuPanel()
    panel.render_payload()
    wid = ensure_widget_id(helm)
    assert panel.dispatch_event(f"toggle:{wid}") is True
    assert panel.has_open_menu()
    assert panel.dispatch_event(f"toggle:{wid}") is True
    assert not panel.has_open_menu()
    assert panel.dispatch_event("toggle:999999") is True   # stale: dropped
    assert panel.dispatch_event("toggle:zap") is True      # malformed: dropped


def test_open_state_changes_force_reemit():
    helm, _ = _build_helm_with_button()
    panel = CrewMenuPanel()
    assert panel.render_payload() is not None
    assert panel.render_payload() is None
    panel.toggle_menu(helm)
    assert panel.render_payload() is not None   # open flag changed payload
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/unit/test_crew_menu_panel.py -v`
Expected: the 4 new tests FAIL (`toggle_menu` missing); existing 11 pass.

- [ ] **Step 3: Implement**

In `engine/ui/crew_menu_panel.py`:

(a) `__init__`: add `self._open_menu_id: Optional[int] = None`.

(b) `_snapshot_node`: in the `if isinstance(widget, STMenu):` block that adds
`children`, also mark top-level open state. Simplest correct placement:
in `render_payload`, after building each top-level node, set the flag. Replace
the menus list-comprehension with:

```python
        menus = []
        for m in TacticalControlWindow.GetInstance().GetMenuList():
            node = self._snapshot_node(m)
            if node is not None:
                node["open"] = (node["id"] == self._open_menu_id)
                menus.append(node)
        payload = json.dumps({"menus": menus})
```

(keep the rest of `render_payload` unchanged).

(c) New methods after `dispatch_event`:

```python
    def toggle_menu(self, menu) -> None:
        """Open `menu` (closing any other), or close it if already open.
        Single-open invariant shared by hotkeys and CEF title clicks."""
        wid = ensure_widget_id(menu)
        self._open_menu_id = None if self._open_menu_id == wid else wid

    def has_open_menu(self) -> bool:
        return self._open_menu_id is not None

    def close_open_menu(self) -> bool:
        """Close any open menu; True if one was open (ESC consumes the
        press in that case — see host_loop's modal ladder)."""
        if self._open_menu_id is None:
            return False
        self._open_menu_id = None
        return True
```

(d) `dispatch_event`: handle toggles before the click branch:

```python
        if action.startswith("toggle:"):
            try:
                wid = int(action[len("toggle:"):])
            except ValueError:
                _logger.info("crew-menu: malformed toggle action %r", action)
                return True
            widget = self._widgets_by_id.get(wid)
            if widget is None:
                _logger.info("crew-menu: stale toggle id %d dropped", wid)
                return True
            self.toggle_menu(widget)
            return True
```

(keep the existing `click:` handling unchanged below it; the method's first
line `if not action.startswith("click:"): return False` must become a final
`return False` fallthrough — restructure to:

```python
    def dispatch_event(self, action: str) -> bool:
        if action.startswith("toggle:"):
            ...as above...
        if action.startswith("click:"):
            ...existing body...
        return False
```
)

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/unit/test_crew_menu_panel.py -v`
Expected: all 15 PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/ui/crew_menu_panel.py tests/unit/test_crew_menu_panel.py
git commit -m "feat(hotkeys): CrewMenuPanel owns dropdown open-state (toggle/close API)"
```

---

### Task 4: CEF JS — payload-driven open state

**Files:**
- Modify: `native/assets/ui-cef/js/crew_menus.js`

No Python test (JS); guarded by Task 7's integration test + visual check.

- [ ] **Step 1: Edit crew_menus.js**

Delete the module-level `let crewMenuOpenId = null;`. In `renderCrewMenu`:

```javascript
function renderCrewMenu(menu) {
  const wrap = document.createElement("div");
  wrap.className = "crew-menu" + (menu.open ? " open" : "");
  const title = document.createElement("div");
  title.className = "crew-menu-title" + (menu.enabled ? "" : " disabled");
  title.textContent = menu.label;
  // Open-state lives in CrewMenuPanel (shared with F1-F5 hotkeys);
  // the next setCrewMenus payload re-renders with the new state.
  title.onclick = () => dauntlessEvent("crew-menu/toggle:" + menu.id);
  wrap.appendChild(title);
  const drop = document.createElement("div");
  drop.className = "crew-menu-drop";
  for (const child of menu.children || []) {
    drop.appendChild(renderCrewMenuEntry(child));
  }
  wrap.appendChild(drop);
  return wrap;
}
```

(`renderCrewMenuEntry` and `setCrewMenus` unchanged.)

- [ ] **Step 2: Sanity-check Python side still green**

Run: `.venv/bin/python -m pytest tests/unit/test_crew_menu_panel.py -q`
Expected: 15 passed.

- [ ] **Step 3: Commit**

```bash
git add native/assets/ui-cef/js/crew_menus.js
git commit -m "feat(hotkeys): crew menu dropdowns render panel-owned open state"
```

---

### Task 5: crew_menu_hotkeys — event handlers + rewire

**Files:**
- Create: `engine/ui/crew_menu_hotkeys.py`
- Test: `tests/unit/test_crew_menu_hotkeys.py` (new)

- [ ] **Step 1: Write the failing test**

```python
"""ET_INPUT_TALK_TO_* events toggle the matching crew menu.
Spec: docs/superpowers/specs/2026-06-12-bridge-menu-hotkeys-design.md
"""
import App
from engine.appc.characters import STTopLevelMenu
from engine.appc.windows import TacticalControlWindow
from engine.ui import crew_menu_hotkeys
from engine.ui.crew_menu_panel import CrewMenuPanel


def setup_function(_):
    TacticalControlWindow._instance = None
    crew_menu_hotkeys._wired_panel = None


def _build(labels=("Helm", "Tactical")):
    tcw = TacticalControlWindow.GetInstance()
    menus = {}
    for label in labels:
        m = STTopLevelMenu(label)
        tcw.AddMenuToList(m)
        menus[label] = m
    panel = CrewMenuPanel()
    panel.render_payload()
    return tcw, panel, menus


def _fire(event_type, tcw):
    evt = App.TGEvent_Create()
    evt.SetEventType(event_type)
    evt.SetDestination(tcw)
    App.g_kEventManager.AddEvent(evt)


def test_talk_to_helm_toggles_helm_menu():
    tcw, panel, menus = _build()
    crew_menu_hotkeys.wire(tcw, panel)
    _fire(App.ET_INPUT_TALK_TO_HELM, tcw)
    assert panel._open_menu_id is not None
    _fire(App.ET_INPUT_TALK_TO_HELM, tcw)
    assert panel._open_menu_id is None


def test_switching_keys_switches_menus():
    tcw, panel, menus = _build()
    crew_menu_hotkeys.wire(tcw, panel)
    from engine.appc.tg_ui.widgets import ensure_widget_id
    _fire(App.ET_INPUT_TALK_TO_HELM, tcw)
    assert panel._open_menu_id == ensure_widget_id(menus["Helm"])
    _fire(App.ET_INPUT_TALK_TO_TACTICAL, tcw)
    assert panel._open_menu_id == ensure_widget_id(menus["Tactical"])


def test_missing_menu_is_dropped_not_raised():
    tcw, panel, _ = _build(labels=("Helm",))   # no Science menu
    crew_menu_hotkeys.wire(tcw, panel)
    _fire(App.ET_INPUT_TALK_TO_SCIENCE, tcw)   # must not raise
    assert panel._open_menu_id is None


def test_rewire_targets_fresh_tcw():
    tcw, panel, _ = _build()
    crew_menu_hotkeys.wire(tcw, panel)
    TacticalControlWindow._instance = None
    fresh = TacticalControlWindow.GetInstance()
    helm = STTopLevelMenu("Helm")
    fresh.AddMenuToList(helm)
    panel.render_payload()
    crew_menu_hotkeys.rewire()
    _fire(App.ET_INPUT_TALK_TO_HELM, fresh)
    assert panel._open_menu_id is not None


def test_rewire_without_wire_is_noop():
    crew_menu_hotkeys.rewire()   # must not raise
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/unit/test_crew_menu_hotkeys.py -v`
Expected: FAIL with ImportError (module missing).

- [ ] **Step 3: Implement `engine/ui/crew_menu_hotkeys.py`**

```python
"""F1-F5 → crew menu toggles.

The SDK pipeline (KeyConfig + DefaultKeyboardBinding, both run at host
startup) turns F-key presses into ET_INPUT_TALK_TO_* events at the
TacticalControlWindow. Stock BC's handlers (BridgeHandlers.TalkTo*) open a
bridge *character* menu — a dead end headless (no characters in the bridge
set) — so these handlers open the corresponding CEF crew menu instead: the
trigger chain is faithful, the effect is the dauntless re-style.

Spec: docs/superpowers/specs/2026-06-12-bridge-menu-hotkeys-design.md
"""
from __future__ import annotations

import logging

_logger = logging.getLogger(__name__)

# TGL keys in "data/TGL/Bridge Menus.tgl" for each TALK_TO event, in the
# stock binding order (DefaultKeyboardBinding.py:121-125).
_EVENT_TO_TGL_KEY = None   # built lazily — App import must stay deferred

_wired_panel = None


def _event_map():
    global _EVENT_TO_TGL_KEY
    if _EVENT_TO_TGL_KEY is None:
        import App
        _EVENT_TO_TGL_KEY = {
            App.ET_INPUT_TALK_TO_HELM:        "Helm",
            App.ET_INPUT_TALK_TO_TACTICAL:    "Tactical",
            App.ET_INPUT_TALK_TO_XO:          "XO",
            App.ET_INPUT_TALK_TO_SCIENCE:     "Science",
            App.ET_INPUT_TALK_TO_ENGINEERING: "Engineer",
        }
    return _EVENT_TO_TGL_KEY


def wire(tcw, panel) -> None:
    """Register TALK_TO handlers on `tcw`; remember `panel` for rewire()."""
    global _wired_panel
    _wired_panel = panel
    for event_type in _event_map():
        tcw.AddPythonFuncHandlerForInstance(
            event_type, __name__ + "._on_talk_to")


def rewire() -> None:
    """Mission-swap hook: re-register on the current TCW singleton.
    No-op when wire() was never called (headless tests, early reset)."""
    if _wired_panel is None:
        return
    from engine.appc.windows import TacticalControlWindow
    wire(TacticalControlWindow.GetInstance(), _wired_panel)


def _resolve_label(tgl_key: str) -> str:
    """Menu label for a TGL key — same lookup LoadBridge's epilogue uses.
    Headless TGL falls back to the key string, which matches the labels
    the handlers were built with."""
    import App
    db = App.g_kLocalizationManager.Load("data/TGL/Bridge Menus.tgl")
    label = str(db.GetString(tgl_key))
    App.g_kLocalizationManager.Unload(db)
    return label


def _on_talk_to(dest, event) -> None:
    """Instance handler: toggle the menu matching the event type."""
    panel = _wired_panel
    if panel is None:
        return
    tgl_key = _event_map().get(event.GetEventType())
    if tgl_key is None:
        return
    from engine.appc.windows import TacticalControlWindow
    tcw = TacticalControlWindow.GetInstance()
    menu = tcw.FindMenu(_resolve_label(tgl_key))
    if menu is None:
        _logger.info("crew-menu hotkey: no '%s' menu to toggle", tgl_key)
        return
    panel.toggle_menu(menu)
```

NOTE — verify the TGL key for Engineering: the SDK builds the Engineer menu
with `pDatabase.GetString("Engineer")` in Bridge/EngineerMenuHandlers.py —
grep it (`grep -n 'GetString' sdk/Build/scripts/Bridge/EngineerMenuHandlers.py | head -3`)
and use the exact key the handler uses for its top-level menu label, so
`FindMenu` matches. Do the same check for "XO" and "Science". Adjust the
`_event_map` values to the verified keys.

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/unit/test_crew_menu_hotkeys.py tests/unit/test_crew_menu_panel.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/ui/crew_menu_hotkeys.py tests/unit/test_crew_menu_hotkeys.py
git commit -m "feat(hotkeys): TALK_TO event handlers toggle CEF crew menus"
```

---

### Task 6: host_loop — F-key poll, ESC ordering, wiring, reset

**Files:**
- Modify: `engine/host_loop.py` (4 sites)
- Test: `tests/unit/test_fkey_poll.py` (new), `tests/unit/test_reset_sdk_globals_menus.py` (append)

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_fkey_poll.py`:

```python
"""_poll_function_keys derives rising/falling edges from host.key_state
and forwards them into g_kInputManager as WC_F1..F5."""
import App
from engine.host_loop import _poll_function_keys, _fn_key_prev


class _FakeKeys:
    KEY_F1, KEY_F2, KEY_F3, KEY_F4, KEY_F5 = 290, 291, 292, 293, 294


class _FakeHost:
    keys = _FakeKeys()

    def __init__(self):
        self.down = set()

    def key_state(self, key):
        return key in self.down


def setup_function(_):
    _fn_key_prev.clear()


def test_edges_forwarded(monkeypatch):
    calls = []
    monkeypatch.setattr(App.g_kInputManager, "OnKeyDown",
                        lambda wc: calls.append(("down", wc)))
    monkeypatch.setattr(App.g_kInputManager, "OnKeyUp",
                        lambda wc: calls.append(("up", wc)))
    host = _FakeHost()
    _poll_function_keys(host)                  # all up: nothing
    assert calls == []
    host.down.add(290)
    _poll_function_keys(host)                  # F1 rising edge
    assert calls == [("down", App.WC_F1)]
    _poll_function_keys(host)                  # held: no repeat
    assert calls == [("down", App.WC_F1)]
    host.down.clear()
    _poll_function_keys(host)                  # falling edge
    assert calls == [("down", App.WC_F1), ("up", App.WC_F1)]


def test_absent_host_is_noop():
    _poll_function_keys(None)                  # must not raise

    class _NoKeys:
        pass
    _poll_function_keys(_NoKeys())             # must not raise
```

Append to `tests/unit/test_reset_sdk_globals_menus.py`:

```python
def test_reset_rewires_hotkeys_to_fresh_tcw():
    from engine.ui import crew_menu_hotkeys
    from engine.ui.crew_menu_panel import CrewMenuPanel
    from engine.appc.characters import STTopLevelMenu
    panel = CrewMenuPanel()
    crew_menu_hotkeys.wire(TacticalControlWindow.GetInstance(), panel)

    reset_sdk_globals()

    fresh = TacticalControlWindow.GetInstance()
    helm = STTopLevelMenu("Helm")
    fresh.AddMenuToList(helm)
    panel.render_payload()
    evt = App.TGEvent_Create()
    evt.SetEventType(App.ET_INPUT_TALK_TO_HELM)
    evt.SetDestination(fresh)
    App.g_kEventManager.AddEvent(evt)
    assert panel._open_menu_id is not None
    crew_menu_hotkeys._wired_panel = None      # don't leak into other tests
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/unit/test_fkey_poll.py tests/unit/test_reset_sdk_globals_menus.py -v`
Expected: ImportError `_poll_function_keys`; the reset test fails (no rewire).

- [ ] **Step 3: Implement in engine/host_loop.py**

(a) Beside `_poll_mouse_buttons` (after line ~185), add:

```python
# Previous-frame F-key levels for edge detection (host has key_pressed for
# rising edges but no key_released; deriving both edges from key_state keeps
# the pair symmetric). Module-level so tests can reset it.
_fn_key_prev: dict = {}


def _poll_function_keys(host) -> None:
    """Forward F1-F5 edges into g_kInputManager (WC_F1..F5).

    From there the SDK pipeline (KeyConfig registration +
    DefaultKeyboardBinding bindings) produces ET_INPUT_TALK_TO_* events —
    see docs/superpowers/specs/2026-06-12-bridge-menu-hotkeys-design.md.
    """
    if host is None or not hasattr(host, "key_state"):
        return
    keys = getattr(host, "keys", None)
    if keys is None or not hasattr(keys, "KEY_F1"):
        return
    import App
    for glfw_key, wc in (
        (keys.KEY_F1, App.WC_F1),
        (keys.KEY_F2, App.WC_F2),
        (keys.KEY_F3, App.WC_F3),
        (keys.KEY_F4, App.WC_F4),
        (keys.KEY_F5, App.WC_F5),
    ):
        down = bool(host.key_state(glfw_key))
        was_down = _fn_key_prev.get(glfw_key, False)
        if down and not was_down:
            App.g_kInputManager.OnKeyDown(wc)
        elif was_down and not down:
            App.g_kInputManager.OnKeyUp(wc)
        _fn_key_prev[glfw_key] = down
```

(b) At the mouse-poll call site (~line 2692), after `_poll_mouse_buttons(_h)`:

```python
                _poll_function_keys(_h)
```

(c) ESC modal ladder (~line 2374): insert a new `elif` between the
configuration-panel branch and the final `else: pause.apply(_h)`:

```python
                elif crew_menu_panel.has_open_menu():
                    if _h.key_pressed(_h.keys.KEY_ESCAPE):
                        crew_menu_panel.close_open_menu()
```

(d) Where the panel is constructed (~line 2231, after
`registry.register(crew_menu_panel)`):

```python
        from engine.ui import crew_menu_hotkeys
        crew_menu_hotkeys.wire(tcw, crew_menu_panel)
```

(`tcw` is in scope from the bootstrap at the top of run(); if not, use
`TacticalControlWindow.GetInstance()` via `App.TacticalControlWindow_GetTacticalControlWindow()`.)

(e) In `reset_sdk_globals`, in the best-effort try-block right after the
`g_kKeyboardBinding.SetDefaultDestination(...)` re-point:

```python
        from engine.ui import crew_menu_hotkeys
        crew_menu_hotkeys.rewire()
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/unit/test_fkey_poll.py tests/unit/test_reset_sdk_globals_menus.py tests/unit/test_crew_menu_hotkeys.py tests/host/test_host_loop_unit.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/host_loop.py tests/unit/test_fkey_poll.py tests/unit/test_reset_sdk_globals_menus.py
git commit -m "feat(hotkeys): F-key poll, ESC-before-pause ordering, wire + rewire"
```

---

### Task 7: End-to-end integration + regression sweep

**Files:**
- Test: `tests/integration/test_bridge_menu_hotkeys.py` (new)

- [ ] **Step 1: Write the integration test**

```python
"""F1 end-to-end: real five menus built, OnKeyDown(WC_F1) through the real
SDK pipeline marks Helm open in the CrewMenuPanel payload."""
import json

import App
import LoadBridge
from engine.appc.windows import TacticalControlWindow
from engine.ui import crew_menu_hotkeys
from engine.ui.crew_menu_panel import CrewMenuPanel

# Reuse the activation test's world setup wholesale.
from tests.integration.test_bridge_menu_activation import _fresh_world


def _payload_opens(panel):
    payload = panel.render_payload()
    if payload is None:
        return None
    data = json.loads(payload[len("setCrewMenus("):-2])
    return {m["label"]: m["open"] for m in data["menus"]}


def test_f1_toggles_helm_end_to_end():
    _fresh_world()
    try:
        LoadBridge.Load("GalaxyBridge")
        tcw = TacticalControlWindow.GetInstance()
        App.g_kKeyboardBinding.SetDefaultDestination(tcw)
        import KeyConfig, DefaultKeyboardBinding
        KeyConfig.MapScancodes()
        DefaultKeyboardBinding.Initialize()

        panel = CrewMenuPanel()
        panel.render_payload()
        crew_menu_hotkeys.wire(tcw, panel)

        App.g_kInputManager.OnKeyDown(App.WC_F1)
        from engine.appc.tg_ui.widgets import ensure_widget_id
        helm_menu = tcw.FindMenu(crew_menu_hotkeys._resolve_label("Helm"))
        assert helm_menu is not None
        assert panel._open_menu_id == ensure_widget_id(helm_menu)
        opens = _payload_opens(panel)
        helm_label = [k for k, v in opens.items() if v]
        assert len(helm_label) == 1            # exactly one open

        App.g_kInputManager.OnKeyDown(App.WC_F2)   # switch to Tactical
        opens2 = _payload_opens(panel)
        open2 = [k for k, v in opens2.items() if v]
        assert len(open2) == 1
        assert open2 != helm_label

        App.g_kInputManager.OnKeyDown(App.WC_F2)   # same key: close
        opens3 = _payload_opens(panel)
        assert not any(opens3.values())
    finally:
        from engine.core.game import _set_current_game
        _set_current_game(None)
        crew_menu_hotkeys._wired_panel = None
```

If `_fresh_world` from the activation test isn't importable (module-name
issues under the SDK finder), copy its body into a local helper instead —
do not weaken the assertions.

- [ ] **Step 2: Run it**

Run: `.venv/bin/python -m pytest tests/integration/test_bridge_menu_hotkeys.py -v -x`
Triage rule: same discipline as previous plans (shim-side state-sinks with
SDK citations only; never touch sdk/; never weaken assertions). The likely
gap class: `DefaultKeyboardBinding.Initialize()` binding tables colliding on
stub WC codes for keys we haven't defined — harmless (they collapse onto key
0, which we never press); only chase failures in the F1-F5 path.

- [ ] **Step 3: Feature-wide regression sweep**

Run: `.venv/bin/python -m pytest tests/integration/test_bridge_menu_hotkeys.py tests/integration/test_bridge_menu_activation.py tests/integration/test_helm_menu_creation.py tests/integration/test_crew_menu_round_trip.py tests/unit/test_fkey_input_chain.py tests/unit/test_fkey_poll.py tests/unit/test_crew_menu_hotkeys.py tests/unit/test_crew_menu_panel.py tests/unit/test_reset_sdk_globals_menus.py tests/unit/test_tactical_window_menus.py tests/host/test_host_loop_unit.py -q`
Expected: ALL pass.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_bridge_menu_hotkeys.py
git commit -m "test(hotkeys): F1/F2 end-to-end through the real SDK pipeline"
```

---

### Task 8: Visual verification + wrap-up

- [ ] **Step 1: Build + run**

```bash
cmake --build build -j && ./build/dauntless > /tmp/dauntless_hotkeys.log 2>&1 &
```

⚠️ HARD RULE (memory: no-desktop-interaction-during-verification): NEVER post
synthetic mouse/keyboard events — the machine is in active use. Ask Mark to
press F1–F5 and report, or rely on the integration tests + log. Evidence =
log lines; delete any screen capture that catches non-dauntless windows.

- [ ] **Step 2: Use superpowers:finishing-a-development-branch**
