# Set Course Button + "Setting Course" Popup — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Helm "Set Course" parent menu with a button that opens a simple `cp-*` modal showing "Setting course…", structured as a foundation for real course-setting.

**Architecture:** Override happens purely in the engine render layer (`crew_menu_panel.py`) — the SDK menu tree is untouched. The `SortedRegionMenu` node is snapshotted as a leaf `button` instead of a `menu`; its click invokes an injected callback that opens a new `SettingCoursePanel` (`Panel` subclass) reusing the shared `cp-*` modal CSS. Host loop wires the callback and registers/ESC-routes the panel.

**Tech Stack:** Python 3 (engine), pytest (tests), CEF + vanilla JS/HTML/CSS (renderer UI). No new dependencies.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-06-21-set-course-button-popup-design.md`.
- Do **not** modify any file under `sdk/Build/scripts/` — the SDK is ground truth; the override is engine-side only.
- Panel name is `"setting-course"`; CEF section id is `setting-course-panel`; JS render fn is `setSettingCoursePanel`; cancel event is `setting-course/cancel`. These names avoid collision with the unrelated `set-course` panel on the `feat/set-course-popup` branch.
- Reuse the existing `cp-*` CSS from `native/assets/ui-cef/css/configuration_panel.css`. Do not add a new stylesheet.
- The popup is **not** dev-gated (registered unconditionally) and does **not** pause the sim.
- Run the test suite with `uv run pytest <path> -v` (never the full suite unguarded; target specific test files). Panel/crew unit tests live under `tests/unit/`.

---

### Task 1: SettingCoursePanel (new panel, pure-Python, fully unit-tested)

**Files:**
- Create: `engine/ui/setting_course_panel.py`
- Test: `tests/unit/test_setting_course_panel.py`

**Interfaces:**
- Consumes: `engine.ui.panel.Panel` (abstract base — requires `name` property, `render_payload()`, `dispatch_event(action)`; provides default `invalidate()`).
- Produces:
  - `SettingCoursePanel()` — constructor, no args.
  - `.name` → `"setting-course"`
  - `.open(course_menu=None) -> None` — show; stores `course_menu`.
  - `.close() -> None` — hide.
  - `.is_open() -> bool`
  - `.render_payload() -> Optional[str]` — `setSettingCoursePanel({...});` or `None` when unchanged.
  - `.dispatch_event(action: str) -> bool`
  - `.handle_key_esc() -> None`
  - `.invalidate() -> None`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_setting_course_panel.py`:

```python
"""Unit tests for SettingCoursePanel — the placeholder Set Course modal."""
import json

from engine.ui.setting_course_panel import SettingCoursePanel


def _payload_dict(js: str) -> dict:
    """Extract the JSON arg from `setSettingCoursePanel(<json>);`."""
    assert js.startswith("setSettingCoursePanel(")
    assert js.endswith(");")
    inner = js[len("setSettingCoursePanel("):-len(");")]
    return json.loads(inner)


def test_name_is_setting_course():
    assert SettingCoursePanel().name == "setting-course"


def test_starts_hidden():
    p = SettingCoursePanel()
    assert p.is_open() is False
    js = p.render_payload()
    assert _payload_dict(js) == {"visible": False}


def test_open_emits_visible_message_payload():
    p = SettingCoursePanel()
    p.render_payload()  # flush the initial hidden payload
    p.open()
    assert p.is_open() is True
    data = _payload_dict(p.render_payload())
    assert data["visible"] is True
    assert data["title"] == "Set Course"
    assert data["message"] == "Setting course…"
    assert data["destinations"] == []


def test_render_is_snapshot_cached():
    p = SettingCoursePanel()
    p.open()
    first = p.render_payload()
    assert first is not None
    assert p.render_payload() is None  # no state change -> no re-emit


def test_cancel_closes_and_emits_hidden():
    p = SettingCoursePanel()
    p.open()
    p.render_payload()
    assert p.dispatch_event("cancel") is True
    assert p.is_open() is False
    assert _payload_dict(p.render_payload()) == {"visible": False}


def test_unknown_action_returns_false():
    p = SettingCoursePanel()
    assert p.dispatch_event("frobnicate") is False


def test_handle_key_esc_closes_when_open():
    p = SettingCoursePanel()
    p.open()
    p.handle_key_esc()
    assert p.is_open() is False


def test_invalidate_forces_reemit():
    p = SettingCoursePanel()
    p.open()
    p.render_payload()
    assert p.render_payload() is None
    p.invalidate()
    assert p.render_payload() is not None


def test_open_stores_course_menu_for_future_wiring():
    p = SettingCoursePanel()
    sentinel = object()
    p.open(course_menu=sentinel)
    assert p._course_menu is sentinel
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_setting_course_panel.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.ui.setting_course_panel'`

- [ ] **Step 3: Write minimal implementation**

Create `engine/ui/setting_course_panel.py`:

```python
"""SettingCoursePanel — placeholder Set Course modal.

A minimal cp-* modal shown when the Helm "Set Course" button is clicked.
It currently displays a "Setting course…" message; the `destinations`
payload field is the seam where the real warp-destination list will be
wired in later (from the SortedRegionMenu passed to `open`).

Modeled on engine.ui.developer_options_panel.DeveloperOptionsPanel: a
Panel subclass pumped by PanelRegistry, reusing the configuration panel's
cp-* CSS. Reached from a Helm crew-menu click (not the pause menu).

Spec: docs/superpowers/specs/2026-06-21-set-course-button-popup-design.md
"""
from __future__ import annotations

import json
from typing import Optional

from engine.ui.panel import Panel


class SettingCoursePanel(Panel):
    def __init__(self) -> None:
        super().__init__()
        self._visible = False
        self._course_menu = None
        self._last_pushed: Optional[tuple] = None

    @property
    def name(self) -> str:
        return "setting-course"

    def is_open(self) -> bool:
        return self._visible

    def open(self, course_menu=None) -> None:
        # course_menu is the SortedRegionMenu whose region children will
        # populate the destination list in a future iteration.
        self._course_menu = course_menu
        self._visible = True

    def close(self) -> None:
        self._visible = False

    def handle_key_esc(self) -> None:
        if self._visible:
            self.close()

    def render_payload(self) -> Optional[str]:
        snapshot = (self._visible,)
        if snapshot == self._last_pushed:
            return None
        self._last_pushed = snapshot
        if not self._visible:
            return "setSettingCoursePanel(" + json.dumps({"visible": False}) + ");"
        payload = {
            "visible": True,
            "title": "Set Course",
            "message": "Setting course…",
            "destinations": [],
        }
        return "setSettingCoursePanel(" + json.dumps(payload) + ");"

    def dispatch_event(self, action: str) -> bool:
        if action == "cancel":
            self.close()
            return True
        return False

    def invalidate(self) -> None:
        self._last_pushed = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_setting_course_panel.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add engine/ui/setting_course_panel.py tests/unit/test_setting_course_panel.py
git commit -m "feat(set-course): SettingCoursePanel placeholder modal"
```

---

### Task 2: Render Set Course as a button + route its click

**Files:**
- Modify: `engine/ui/crew_menu_panel.py` (`__init__`, `_snapshot_node`, `dispatch_event`)
- Test: `tests/unit/test_crew_menu_set_course_override.py`

**Interfaces:**
- Consumes:
  - `engine.appc.tg_ui.st_widgets.SortedRegionMenu` (subclass of `STMenu`; constructor `SortedRegionMenu(label="")`).
  - `engine.appc.characters.STMenu` / `STButton` (already imported in the module). `STMenu` has `AddChild(child)`, `_children` list, `GetLabel()`, `IsEnabled()`, `IsVisible()`.
  - `engine.appc.tg_ui.widgets.ensure_widget_id(widget) -> int` (already imported).
- Produces:
  - `CrewMenuPanel(on_set_course=None)` — new optional constructor kwarg; stored as `self._on_set_course`. Called as `self._on_set_course(widget)` where `widget` is the clicked `SortedRegionMenu`.
  - `_snapshot_node` emits `{"id","type":"button","label","enabled","visible"}` (no `children`/`expanded`) for a `SortedRegionMenu`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_crew_menu_set_course_override.py`:

```python
"""The Helm Set Course (SortedRegionMenu) is projected as a leaf button and
its click opens the setting-course panel instead of expanding inline."""
import pytest

from engine.appc.characters import STButton, STMenu
from engine.appc.tg_ui.st_widgets import SortedRegionMenu
from engine.appc.tg_ui.widgets import ensure_widget_id
from engine.ui.crew_menu_panel import CrewMenuPanel


def _snapshot(panel, widget):
    return panel._snapshot_node(widget)


def test_sorted_region_menu_snapshots_as_childless_button():
    panel = CrewMenuPanel()
    sc = SortedRegionMenu("Set Course")
    sc.AddChild(STButton("Alpha Centauri"))
    node = _snapshot(panel, sc)
    assert node["type"] == "button"
    assert node["label"] == "Set Course"
    assert "children" not in node
    assert "expanded" not in node


def test_plain_menu_still_snapshots_as_menu_with_children():
    panel = CrewMenuPanel()
    m = STMenu("Hail")
    m.AddChild(STButton("Enterprise"))
    node = _snapshot(panel, m)
    assert node["type"] == "menu"
    assert len(node["children"]) == 1


def test_click_on_set_course_invokes_callback_with_widget():
    seen = []
    panel = CrewMenuPanel(on_set_course=lambda w: seen.append(w))
    sc = SortedRegionMenu("Set Course")
    wid = ensure_widget_id(sc)
    # Populate the id->widget map the way render_payload does.
    panel._snapshot_node(sc)
    panel._widgets_by_id[wid] = sc
    handled = panel.dispatch_event("click:" + str(wid))
    assert handled is True
    assert seen == [sc]


def test_click_on_set_course_fires_no_sdk_button_event():
    import App
    panel = CrewMenuPanel(on_set_course=lambda w: None)
    sc = SortedRegionMenu("Set Course")
    wid = ensure_widget_id(sc)
    panel._widgets_by_id[wid] = sc
    before = App.g_kEventManager.GetEventCount() \
        if hasattr(App.g_kEventManager, "GetEventCount") else None
    panel.dispatch_event("click:" + str(wid))
    # A SortedRegionMenu is not an STButton, so SendActivationEvent /
    # ET_ST_BUTTON_CLICKED must never run. Assert by type, not event queue:
    assert not isinstance(sc, STButton)


def test_none_callback_is_silent_noop():
    panel = CrewMenuPanel()  # on_set_course defaults to None
    sc = SortedRegionMenu("Set Course")
    wid = ensure_widget_id(sc)
    panel._widgets_by_id[wid] = sc
    # Must not raise.
    assert panel.dispatch_event("click:" + str(wid)) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_crew_menu_set_course_override.py -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'on_set_course'` (and the snapshot tests fail because `SortedRegionMenu` snapshots as `menu`).

- [ ] **Step 3: Write minimal implementation**

In `engine/ui/crew_menu_panel.py`:

(a) Add the import near the existing `from engine.appc.characters import STButton, STMenu`:

```python
from engine.appc.tg_ui.st_widgets import SortedRegionMenu
```

(b) Change `__init__` to accept the callback. Replace the signature line
`def __init__(self):` with:

```python
    def __init__(self, on_set_course=None):
```

and add, at the end of `__init__` (after `self._expanded_ids = set()`):

```python
        # Injected by host_loop: opens the SettingCoursePanel when the Helm
        # Set Course button is clicked. None -> click is a silent no-op
        # (keeps headless construction and existing tests working).
        self._on_set_course = on_set_course
```

(c) In `_snapshot_node`, special-case the SortedRegionMenu **before** the
`STMenu` branch. Replace the opening type-decision block:

```python
        if isinstance(widget, STMenu):
            node_type = "menu"
        elif isinstance(widget, STButton):
            node_type = "button"
        else:
            self._log_unrecognised_once(type(widget).__name__)
            return None
```

with:

```python
        # Set Course (the one SortedRegionMenu) is projected as a leaf
        # button, not an expandable parent — its click opens a modal.
        if isinstance(widget, SortedRegionMenu):
            node_type = "button"
        elif isinstance(widget, STMenu):
            node_type = "menu"
        elif isinstance(widget, STButton):
            node_type = "button"
        else:
            self._log_unrecognised_once(type(widget).__name__)
            return None
```

and guard the children block so the SortedRegionMenu (an STMenu subclass)
does not get `children`/`expanded`. Replace:

```python
        if isinstance(widget, STMenu):
            node["expanded"] = wid in self._expanded_ids
            children = [self._snapshot_node(c) for c in widget._children]
            node["children"] = [c for c in children if c is not None]
        return node
```

with:

```python
        if isinstance(widget, STMenu) and not isinstance(widget, SortedRegionMenu):
            node["expanded"] = wid in self._expanded_ids
            children = [self._snapshot_node(c) for c in widget._children]
            node["children"] = [c for c in children if c is not None]
        return node
```

(d) In `dispatch_event`, inside the `click:` branch, handle the
SortedRegionMenu before the `STButton` branch. Locate:

```python
            if not widget.IsEnabled():
                return True
            root = self._root_of(wid)
            if isinstance(widget, STButton):
```

and insert the SortedRegionMenu branch between the `IsEnabled` guard and
the `root = ...` line:

```python
            if not widget.IsEnabled():
                return True
            if isinstance(widget, SortedRegionMenu):
                # Replace inline expand with the modal: collapse any open
                # crew menu, then open the Set Course popup. No SDK event.
                self._open_menu_id = None
                self._expanded_ids.clear()
                if self._on_set_course is not None:
                    self._on_set_course(widget)
                return True
            root = self._root_of(wid)
            if isinstance(widget, STButton):
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_crew_menu_set_course_override.py -v`
Expected: PASS (5 passed)

Also run the existing crew-menu tests to confirm no regression:

Run: `uv run pytest tests/unit/ -k crew -v`
Expected: PASS (all existing crew-menu tests still green)

- [ ] **Step 5: Commit**

```bash
git add engine/ui/crew_menu_panel.py tests/unit/test_crew_menu_set_course_override.py
git commit -m "feat(set-course): project Helm Set Course as button, route click to modal"
```

---

### Task 3: CEF assets — section, render fn, script tag

**Files:**
- Modify: `native/assets/ui-cef/index.html` (add `<section>` + `<script>`)
- Create: `native/assets/ui-cef/js/setting_course_panel.js`

**Interfaces:**
- Consumes: `setSettingCoursePanel(state)` is called by Python via
  `cef_execute_javascript` with `state = {visible, title, message, destinations}`
  or `{visible:false}`. The OK button and ESC both fire
  `dauntlessEvent('setting-course/cancel')`.
- Produces: a `#setting-course-panel` DOM section using the shared `cp-*`
  classes; `setSettingCoursePanel` shows/hides and fills title + message.

> **No automated test** — CEF/JS render is verified manually in-game (handoff
> step). This task ships the static assets the panel needs.

- [ ] **Step 1: Add the HTML section**

In `native/assets/ui-cef/index.html`, immediately after the
`</section>` that closes `#developer-options-panel` (the section that ends
right before the next overlay comment), insert:

```html
    <!-- Setting Course overlay (production).
         setSettingCoursePanel({visible, title, message, destinations})
         drives state; the OK button and ESC fire
         dauntlessEvent('setting-course/cancel'). Reuses the cp-* modal CSS.
         Placeholder: shows a "Setting course…" message; the destinations
         seam will later list warp targets.
         Spec: docs/superpowers/specs/2026-06-21-set-course-button-popup-design.md -->
    <section id="setting-course-panel" style="display:none">
      <div class="cp-modal">
        <div class="cp-header" id="setting-course-header">Set Course</div>
        <div class="cp-content">
          <div class="cp-body" id="setting-course-body"></div>
        </div>
        <div class="cp-footer">
          <button class="cp-done-button"
                  onclick="dauntlessEvent('setting-course/cancel')">
            OK
          </button>
        </div>
      </div>
    </section>
```

- [ ] **Step 2: Add the script tag**

In the same file, next to the other panel script tags (after
`<script src="js/developer_options.js"></script>`), add:

```html
    <script src="js/setting_course_panel.js"></script>
```

- [ ] **Step 3: Create the render function**

Create `native/assets/ui-cef/js/setting_course_panel.js`:

```javascript
// Setting Course panel render fn. Driven by Python via cef_execute_javascript:
//   setSettingCoursePanel({visible:true, title, message, destinations});
//   setSettingCoursePanel({visible:false});
// The OK button and ESC fire dauntlessEvent('setting-course/cancel').
// Reuses the cp-* classes from css/configuration_panel.css.
// Spec: docs/superpowers/specs/2026-06-21-set-course-button-popup-design.md.

function escapeHtmlSC(s) {
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function setSettingCoursePanel(state) {
    const root = document.getElementById('setting-course-panel');
    if (!root) return;
    if (!state || state.visible !== true) {
        root.style.display = 'none';
        return;
    }
    const header = document.getElementById('setting-course-header');
    if (header) header.textContent = state.title || 'Set Course';
    const body = document.getElementById('setting-course-body');
    if (body) {
        const dests = state.destinations || [];
        if (dests.length === 0) {
            // Placeholder: just the message.
            body.innerHTML = '<div class="cp-row__label">'
                + escapeHtmlSC(state.message || '') + '</div>';
        } else {
            // Future: render a clickable destination list. Each row fires
            // dauntlessEvent('setting-course/select:<id>').
            let html = '';
            for (let i = 0; i < dests.length; ++i) {
                const d = dests[i];
                html += '<div class="cp-row"'
                      + ' onclick="dauntlessEvent(\'setting-course/select:'
                      + escapeHtmlSC(d.id) + '\')">'
                      + '<div class="cp-row__label">'
                      + escapeHtmlSC(d.label) + '</div></div>';
            }
            body.innerHTML = html;
        }
    }
    root.style.display = 'flex';
}
```

- [ ] **Step 4: Sanity-check the HTML/JS edits**

Run: `node -e "require('./native/assets/ui-cef/js/setting_course_panel.js'); console.log('parse ok')" 2>/dev/null || node --check native/assets/ui-cef/js/setting_course_panel.js && echo "JS syntax ok"`
Expected: `JS syntax ok` (no syntax error)

Run: `grep -n "setting-course-panel\|setting_course_panel.js" native/assets/ui-cef/index.html`
Expected: the new `<section>` and `<script>` lines are present.

- [ ] **Step 5: Commit**

```bash
git add native/assets/ui-cef/index.html native/assets/ui-cef/js/setting_course_panel.js
git commit -m "feat(set-course): CEF setting-course modal section + render fn"
```

---

### Task 4: Host-loop wiring — construct, inject, register, ESC-route

**Files:**
- Modify: `engine/host_loop.py` (panel construction block ~3285-3303 and the `_modal_blockers` list ~3398)

**Interfaces:**
- Consumes:
  - `engine.ui.setting_course_panel.SettingCoursePanel` (Task 1).
  - `CrewMenuPanel(on_set_course=...)` (Task 2).
  - `registry.register(panel)` and the `_modal_blockers` list (existing).
- Produces: the live wiring — Helm Set Course click opens the panel; ESC/OK closes it.

> **No new automated test** — this is integration wiring exercised by the manual
> in-game handoff. Guard against regressions by running the existing host-loop
> import/smoke tests.

- [ ] **Step 1: Construct the panel and inject the callback**

In `engine/host_loop.py`, find the crew-menu construction:

```python
        from engine.ui.crew_menu_panel import CrewMenuPanel
        crew_menu_panel = CrewMenuPanel()
        registry.register(crew_menu_panel)
```

Replace it with:

```python
        from engine.ui.setting_course_panel import SettingCoursePanel
        setting_course_panel = SettingCoursePanel()
        from engine.ui.crew_menu_panel import CrewMenuPanel
        crew_menu_panel = CrewMenuPanel(on_set_course=setting_course_panel.open)
        registry.register(crew_menu_panel)
        registry.register(setting_course_panel)
```

- [ ] **Step 2: Add to the modal-blocker ESC ladder**

Find the `_modal_blockers` list:

```python
        _modal_blockers = [mission_picker, developer_options_panel,
                           ship_property_viewer, configuration_panel]
```

Replace with (append the setting-course panel):

```python
        _modal_blockers = [mission_picker, developer_options_panel,
                           ship_property_viewer, configuration_panel,
                           setting_course_panel]
```

- [ ] **Step 3: Verify host_loop still imports cleanly**

Run: `uv run python -c "import engine.host_loop; print('import ok')"`
Expected: `import ok`

- [ ] **Step 4: Run the broader UI test set for regressions**

Run: `uv run pytest tests/unit/test_setting_course_panel.py tests/unit/test_crew_menu_set_course_override.py tests/unit/test_crew_menu_panel.py -v`
Expected: PASS (new panel + override tests and existing crew-menu panel tests all green)

- [ ] **Step 5: Commit**

```bash
git add engine/host_loop.py
git commit -m "feat(set-course): wire SettingCoursePanel into host loop + ESC ladder"
```

---

### Task 5: Manual in-game verification (handoff)

**Files:** none (verification only).

This task is performed by the user / a live run, not a subagent. Document the
result in the PR.

- [ ] **Step 1: Rebuild** — CEF asset + Python changes need no C++ rebuild, but
  rebuild to be safe: `cmake -B build -S . && cmake --build build -j`
- [ ] **Step 2: Run** `./build/dauntless`, load a mission with a Helm station.
- [ ] **Step 3: Open the Helm menu.** Confirm "Set Course" renders as a leaf
  row with **no caret** (not an expandable parent).
- [ ] **Step 4: Click "Set Course".** Confirm the helm menu collapses and a
  `cp-*` modal titled "Set Course" appears showing "Setting course…".
- [ ] **Step 5: Press ESC and click OK.** Confirm both close the modal.

---

## Self-Review

- **Spec coverage:** Component 1 (render override) → Task 2. Component 2
  (SettingCoursePanel) → Task 1. Component 3 (CEF assets) → Task 3. Component 4
  (host-loop wiring) → Task 4. Testing section items 1-3 → Tasks 2,2,1
  respectively. Manual verify → Task 5. All covered.
- **Placeholder scan:** no TBD/TODO; every code step shows full code.
- **Type consistency:** `setSettingCoursePanel`, `setting-course`,
  `setting-course-panel`, `setting-course/cancel`, `on_set_course`,
  `SettingCoursePanel.open(course_menu=None)` used identically across tasks.
- **Ordering note:** Task 1 (panel) precedes Task 2 (which references the panel
  conceptually but does not import it — the callback is injected, so Tasks 1 and
  2 are independently testable). Task 4 depends on Tasks 1+2. Task 3 is
  independent of 1/2/4.
```
