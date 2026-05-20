# SDK UI Shim Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python-side shim (`engine/sdk_ui/`) that exposes the original Bridge Commander SDK's `App.TG*_Create*` / `App.ST*_Create*` API on top of the existing RmlUi-based native UI layer, so that unmodified SDK bridge UI scripts (`Bridge/*MenuHandlers.py`, `MissionLib.CreateGameOverScreen`, etc.) construct and dispatch events on the new engine.

**Architecture:** All `TG*`/`ST*` widget classes are pure Python wrappers around RmlUi element ids. The existing native `PanelDocument` API (`append_div`, `set_class`, `set_text`, `set_element_property`, `on_click`, etc.) is the transport; one new native binding (`reparent_element`) plus a per-element `element_bounds` readback and a `update_layout` pump are the only native additions. Widgets are eagerly created as children of a hidden "staging" div inside a single shared `sdk-ui` panel; `AddChild` moves them under their real parent via the in-panel reparent. Coordinates are stored in screen-fraction units; CSS is `%` against parent. Events are dispatched through a pure-Python event manager that resolves SDK-style `"module.func"` handler strings via `importlib`.

**Tech Stack:** Python 3 (shim), C++ + RmlUi (native bindings via pybind11), pytest (testing), CMake (build), `_dauntless_host` (the project's C++ extension module).

---

## Required reading before starting

Read these before Task 1:

- [docs/superpowers/specs/2026-05-19-sdk-ui-shim-design.md](../specs/2026-05-19-sdk-ui-shim-design.md) — the spec this plan implements
- [docs/superpowers/specs/2026-05-11-target-list-from-scene-design.md](../specs/2026-05-11-target-list-from-scene-design.md) — context for the target-list rewrite in Slice 5
- [sdk/Build/scripts/MissionLib.py:1990-2030](../../../sdk/Build/scripts/MissionLib.py#L1990-L2030) — the GameOverScreen, our Slice 1 verification target
- [native/src/ui/include/ui/PanelDocument.h](../../../native/src/ui/include/ui/PanelDocument.h) — existing native UI surface
- [native/src/host/host_bindings.cc:910-1050](../../../native/src/host/host_bindings.cc#L910-L1050) — existing pybind11 UI bindings
- [native/assets/ui/panel.rml](../../../native/assets/ui/panel.rml) and [components.rcss](../../../native/assets/ui/components.rcss) — RmlUi templates

---

## File structure

### New files (created in Slice 1 unless otherwise noted)

| Path | Role | Created in |
|---|---|---|
| `engine/sdk_ui/__init__.py` | Public re-exports | Slice 1 |
| `engine/sdk_ui/_panel.py` | Singleton allocation of the shared `sdk-ui` panel + staging div | Slice 1 |
| `engine/sdk_ui/_backend.py` | Native-binding indirection (real `_dauntless_host` + `FakeNativeBackend` for tests) | Slice 1 |
| `engine/sdk_ui/_fake_backend.py` | In-memory fake of the native UI surface | Slice 1 |
| `engine/sdk_ui/base.py` | `TGUIObject` base class | Slice 1 |
| `engine/sdk_ui/nipoint.py` | `NiPoint2` helper (out-arg for `GetScreenOffset`) | Slice 1 |
| `engine/sdk_ui/resolver.py` | `"module.func"` string → callable resolution | Slice 1 |
| `engine/sdk_ui/events.py` | `ET_*` constants, `TGEvent`, `g_kEventManager` | Slice 1 |
| `engine/sdk_ui/primitives.py` | `TGPane`, `TGParagraph`, `TGIcon` (icon stubbed until Slice 3) | Slice 1 |
| `engine/sdk_ui/buttons.py` | `STButton` (Slice 1); `STRoundedButton`, `STToggle`, `STTiledIcon`, `STFillGauge`, `STWarpButton`, `TGButton`, `TGTextButton` (Slice 4) |  |
| `engine/sdk_ui/stylized.py` | `STStylizedWindow`, `STSubPane` | Slice 1 (minimal) / Slice 3 (frame children) |
| `engine/sdk_ui/menus.py` | `STTopLevelMenu`, `STCharacterMenu`, `STMenu`, `STTargetMenu` | Slice 4 |
| `engine/sdk_ui/icons.py` | `g_kIconManager`, `TGIconGroup` | Slice 3 |
| `engine/sdk_ui/icon_classmap.py` | `(group, index) → css_class` table | Slice 3 |
| `engine/sdk_ui/theme.py` | `TGUITheme`, `g_kInterface` setters | Slice 3 |
| `engine/sdk_ui/target_list.py` | Engine-owned target-list wrapper + `TargetListController` | Slice 5 |
| `native/src/ui/include/ui/PanelDocument.h` | (existing — add: `reparent`, `element_bounds`, `update_layout`) | Slice 1 |
| `native/src/host/host_bindings.cc` | (existing — add pybind11 wrappers for the new methods) | Slice 1 |
| `native/assets/ui/sdk_ui.rcss` | New stylesheet for shim widget classes | Slice 1 / Slice 3 / Slice 5 |
| `tests/sdk_ui/*` | Unit + integration test files | All slices |

### Deleted in Slice 2

Entire `engine/ui/` directory: `panel.py`, `button.py`, `collapsible.py`, `stat_row.py`, `target_list.py`, `theme.py`, `bindings.py`, `_dom.py`, `__init__.py`.

### Modified

| Path | Why | Slice |
|---|---|---|
| `App.py` (project root) | Re-export `engine.sdk_ui` symbols as `App.TG*_Create*`, `App.ST*_Create*`, `App.g_kEventManager`, etc. | Slice 1 (foundation), expanded per slice |
| `engine/host_loop.py` | Stop using `engine.ui`; use SDK shim through `App.*` | Slice 2 |
| `engine/mission_picker.py` | Port off `UiPanel`/`UiButton`/`UiCollapsibleList` | Slice 2 |

---

## Architectural model (read before any task)

**Single panel + staging.** The shim allocates ONE C++ `PanelDocument` at first use, with anchor `"fullscreen"`. Inside it: two top-level divs — `staging` (hidden via CSS) and `active`. Every `*_Create*` immediately creates an element via `append_div(staging_id, css_class)`. When `parent.AddChild(child, x, y, z)` is called, the child is *reparented* (a new native binding) from `staging` to `parent`. Reparenting is in-panel, so the element-id remains stable.

**Why staging?** RmlUi requires elements to be created as children of an existing element. SDK code creates widgets before knowing their parent (`pBtn = STButton_CreateW(...)` then later `pPane.AddChild(pBtn, ...)`). Staging is where they live in the meantime. The `staging` div has `display: none` so widgets don't flash on screen before being placed.

**Coord conversion.** All Python-side coords are screen fractions in [0.0, 1.0] (SDK convention). At `AddChild` time the shim computes `left = (x / parent.GetWidth()) * 100 + '%'`, `top = (y / parent.GetHeight()) * 100 + '%'` and sets them as inline RCSS properties via `set_element_property(id, "left", "...")`. Sizing of top-level panes uses `vw/vh` against the viewport; nested panes inherit screen-relative boxes via CSS `%`.

**Layout pump.** After every `*_Create*` AND every `AddChild`, the shim calls a new native `update_layout(element_id)` binding so subsequent `GetWidth/GetHeight/GetScreenOffset` calls return real values. This matches SDK's synchronous semantics.

**Event flow.** `STButton_CreateW(label, event_template, flags)` stashes `event_template` on the button. The button's RmlUi click registration calls a generic Python dispatcher; the dispatcher clones the template (filling in source/destination), and invokes the `_EventManager`. The manager walks per-instance handlers on the destination, walks the conceptual-parent chain on `CallNextHandler`, then fires broadcast handlers.

**Handler name resolution.** Handler strings like `"MissionLib.RestartGame"` are split on the last `.` → `("MissionLib", "RestartGame")`, then `importlib.import_module("MissionLib")` + `getattr(mod, "RestartGame")`. Results are cached in `resolver._cache` after first lookup. Failures raise `EventHandlerError`.

---

## Slice 1 — Foundations + GameOverScreen

**Done when:** `MissionLib.CreateGameOverScreen()` (unmodified, loaded through `_SDKFinder`) constructs without errors, layout pumps successfully, and clicking the synthetic-event-dispatched "Restart" button calls `MissionLib.RestartGame`.

### Task 1.1: Scaffold `engine/sdk_ui/` module skeleton

**Files:**
- Create: `engine/sdk_ui/__init__.py`
- Create: `engine/sdk_ui/_backend.py`
- Create: `engine/sdk_ui/_fake_backend.py`
- Create: `tests/sdk_ui/__init__.py`
- Create: `tests/sdk_ui/test_backend_indirection.py`

- [ ] **Step 1: Write the failing test**

In `tests/sdk_ui/test_backend_indirection.py`:

```python
"""Backend indirection: production code calls _backend.get(), tests swap in fake."""
from engine.sdk_ui import _backend
from engine.sdk_ui._fake_backend import FakeNativeBackend


def test_get_returns_real_backend_by_default(monkeypatch):
    monkeypatch.setattr(_backend, "_override", None)
    backend = _backend.get()
    # In a normal pytest run the real _dauntless_host extension is importable
    # via tests/conftest.py's sys.path setup, so this should be the real module.
    assert backend is not None
    assert hasattr(backend, "append_div")


def test_set_override_swaps_backend():
    fake = FakeNativeBackend()
    _backend.set_override(fake)
    try:
        assert _backend.get() is fake
    finally:
        _backend.set_override(None)


def test_fake_backend_create_panel_returns_id():
    fake = FakeNativeBackend()
    pid = fake.create_panel("sdk-ui", "fullscreen", 100.0, 100.0)
    assert pid > 0
    # And panel_root() must return a non-zero element id we can append into.
    root = fake.panel_root(pid)
    assert root > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/sdk_ui/test_backend_indirection.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.sdk_ui'`.

- [ ] **Step 3: Create `engine/sdk_ui/__init__.py`**

```python
"""SDK UI shim — Python implementation of Bridge Commander's TG*/ST* widget API.

This package exposes the original SDK's UI primitives (TGPane, STButton,
STStylizedWindow, etc.) on top of the engine's RmlUi-backed PanelDocument.
SDK scripts under sdk/Build/scripts/ can import these via the project-root
App.py shim which re-exports our names as App.TGPane_Create etc.

Public API is added to __all__ incrementally as each widget is implemented.
"""
__all__: list[str] = []
```

- [ ] **Step 4: Create `engine/sdk_ui/_backend.py`**

```python
"""Indirection over the native UI binding module.

Production: returns the imported `_dauntless_host` extension.
Tests: swap in a `FakeNativeBackend` via `set_override(fake)`.

Why indirection: most of the shim's logic is translation, easily unit-tested
against a fake. The fake records calls and returns canned data; tests assert
on the recording. Only Layer 2 smoke tests use the real backend.
"""
from __future__ import annotations
from typing import Any, Optional

_override: Optional[Any] = None
_real: Optional[Any] = None


def get() -> Any:
    """Return the active backend — override if set, else the real module."""
    if _override is not None:
        return _override
    global _real
    if _real is None:
        import _dauntless_host
        _real = _dauntless_host
    return _real


def set_override(backend: Optional[Any]) -> None:
    """Swap in a backend for tests. Pass None to restore the real one."""
    global _override
    _override = backend
```

- [ ] **Step 5: Create `engine/sdk_ui/_fake_backend.py`**

```python
"""In-memory fake of the native UI binding surface.

Mirrors the methods the shim calls on `_dauntless_host`, recording every
invocation for test assertions and returning monotonically-increasing
integer ids for create/append operations.

Only the methods the shim actually uses are stubbed.  Unimplemented methods
raise AttributeError to surface accidental dependencies.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class _Element:
    eid: int
    parent: Optional[int]
    cls: str = ""
    text: str = ""
    visible: bool = True
    properties: dict[str, str] = field(default_factory=dict)
    on_click: Optional[Callable[[], None]] = None
    # Recorded "size" — tests can set this to make GetWidth/GetHeight return
    # specific values for centering-math assertions.
    width_px: float = 0.0
    height_px: float = 0.0
    x_px: float = 0.0
    y_px: float = 0.0


class FakeNativeBackend:
    def __init__(self) -> None:
        self._next_id = 1
        self.calls: list[tuple[str, tuple]] = []
        self.panels: dict[int, dict] = {}     # panel_id -> {root_id, anchor, w, h}
        self.elements: dict[int, _Element] = {}
        # Viewport: tests can set this to a non-default value to verify
        # screen-fraction math.
        self.viewport_w_px = 1920.0
        self.viewport_h_px = 1080.0

    def _record(self, name: str, *args) -> None:
        self.calls.append((name, args))

    def _new_id(self) -> int:
        i = self._next_id
        self._next_id += 1
        return i

    # ---- panel-level ----
    def create_panel(self, name: str, anchor: str, w_vw: float, h_vh: float) -> int:
        self._record("create_panel", name, anchor, w_vw, h_vh)
        pid = self._new_id()
        rid = self._new_id()
        self.panels[pid] = {"root_id": rid, "anchor": anchor, "w_vw": w_vw, "h_vh": h_vh}
        self.elements[rid] = _Element(eid=rid, parent=None)
        # Default to filling the viewport at the declared fraction.
        self.elements[rid].width_px = self.viewport_w_px * (w_vw / 100.0)
        self.elements[rid].height_px = self.viewport_h_px * (h_vh / 100.0)
        return pid

    def panel_root(self, pid: int) -> int:
        self._record("panel_root", pid)
        return self.panels[pid]["root_id"]

    def destroy_panel(self, pid: int) -> None:
        self._record("destroy_panel", pid)
        if pid in self.panels:
            rid = self.panels[pid]["root_id"]
            self._drop_subtree(rid)
            del self.panels[pid]

    def clear_panel(self, pid: int) -> None:
        self._record("clear_panel", pid)
        if pid in self.panels:
            rid = self.panels[pid]["root_id"]
            for eid in [e.eid for e in self.elements.values() if e.parent == rid]:
                self._drop_subtree(eid)

    def set_panel_visible(self, pid: int, visible: bool) -> None:
        self._record("set_panel_visible", pid, visible)

    def set_panel_css_var(self, pid: int, name: str, value: str) -> None:
        self._record("set_panel_css_var", pid, name, value)

    # ---- element-level ----
    def append_div(self, parent_id: int, class_names: str) -> int:
        self._record("append_div", parent_id, class_names)
        eid = self._new_id()
        self.elements[eid] = _Element(eid=eid, parent=parent_id, cls=class_names)
        return eid

    def remove_element(self, eid: int) -> None:
        self._record("remove_element", eid)
        self._drop_subtree(eid)

    def _drop_subtree(self, eid: int) -> None:
        children = [e.eid for e in self.elements.values() if e.parent == eid]
        for c in children:
            self._drop_subtree(c)
        self.elements.pop(eid, None)

    def set_class(self, eid: int, class_names: str) -> None:
        self._record("set_class", eid, class_names)
        if eid in self.elements:
            self.elements[eid].cls = class_names

    def set_text(self, eid: int, text: str) -> None:
        self._record("set_text", eid, text)
        if eid in self.elements:
            self.elements[eid].text = text
            # Approximate intrinsic-width measurement: 8 px per character at
            # default font. Tests that need precise sizes can override the
            # _Element directly.
            self.elements[eid].width_px = max(self.elements[eid].width_px, len(text) * 8.0)
            self.elements[eid].height_px = max(self.elements[eid].height_px, 16.0)

    def set_visible(self, eid: int, visible: bool) -> None:
        self._record("set_visible", eid, visible)
        if eid in self.elements:
            self.elements[eid].visible = visible

    def set_element_property(self, eid: int, name: str, value: str) -> None:
        self._record("set_element_property", eid, name, value)
        if eid in self.elements:
            self.elements[eid].properties[name] = value

    def on_click(self, eid: int, callback: Optional[Callable[[], None]]) -> None:
        self._record("on_click", eid, callback)
        if eid in self.elements:
            self.elements[eid].on_click = callback

    # ---- new bindings to add to native side in Tasks 1.3-1.5 ----
    def reparent_element(self, eid: int, new_parent_id: int) -> None:
        self._record("reparent_element", eid, new_parent_id)
        if eid in self.elements:
            self.elements[eid].parent = new_parent_id

    def update_layout(self, eid: int) -> None:
        self._record("update_layout", eid)
        # Fake doesn't actually lay out — sizes are set when text/dimensions are.

    def element_bounds(self, eid: int) -> tuple[float, float, float, float]:
        """Return (x, y, w, h) in screen pixels."""
        self._record("element_bounds", eid)
        if eid in self.elements:
            e = self.elements[eid]
            return (e.x_px, e.y_px, e.width_px, e.height_px)
        return (0.0, 0.0, 0.0, 0.0)

    def viewport_size(self) -> tuple[float, float]:
        """Return (w, h) of the viewport in screen pixels."""
        return (self.viewport_w_px, self.viewport_h_px)

    # ---- click simulation for tests ----
    def fire_click(self, eid: int) -> None:
        """Simulate a click on the given element. Tests use this to invoke
        registered on_click callbacks without going through real RmlUi."""
        if eid in self.elements and self.elements[eid].on_click:
            self.elements[eid].on_click()  # type: ignore[misc]
```

- [ ] **Step 6: Create `tests/sdk_ui/__init__.py`** (empty)

```python
```

- [ ] **Step 7: Run test to verify it passes**

Run: `uv run pytest tests/sdk_ui/test_backend_indirection.py -v`
Expected: PASS — all three tests green.

- [ ] **Step 8: Commit**

```bash
git add engine/sdk_ui/__init__.py engine/sdk_ui/_backend.py engine/sdk_ui/_fake_backend.py tests/sdk_ui/
git commit -m "feat(sdk_ui): scaffold backend indirection + fake native backend

Establishes the test seam for the shim: production code calls
engine.sdk_ui._backend.get() to reach the native module; tests inject a
FakeNativeBackend that records calls and returns canned data.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 1.2: NiPoint2 helper + shared-panel singleton

**Files:**
- Create: `engine/sdk_ui/nipoint.py`
- Create: `engine/sdk_ui/_panel.py`
- Create: `tests/sdk_ui/test_panel_singleton.py`

- [ ] **Step 1: Write the failing test**

`tests/sdk_ui/test_panel_singleton.py`:

```python
import pytest
from engine.sdk_ui import _backend, _panel
from engine.sdk_ui._fake_backend import FakeNativeBackend


@pytest.fixture
def fake():
    f = FakeNativeBackend()
    _backend.set_override(f)
    _panel.reset_for_tests()
    yield f
    _backend.set_override(None)
    _panel.reset_for_tests()


def test_panel_allocated_lazily_on_first_use(fake):
    # No panel created until something asks for the staging root.
    assert not any(name == "create_panel" for name, _ in fake.calls)
    staging = _panel.staging_root_id()
    # Now exactly one panel exists with anchor "fullscreen".
    calls = [c for c in fake.calls if c[0] == "create_panel"]
    assert len(calls) == 1
    assert calls[0][1][1] == "fullscreen"


def test_panel_allocation_is_idempotent(fake):
    a = _panel.staging_root_id()
    b = _panel.staging_root_id()
    assert a == b
    # And only one panel was created.
    assert sum(1 for c in fake.calls if c[0] == "create_panel") == 1


def test_active_root_separate_from_staging(fake):
    staging = _panel.staging_root_id()
    active = _panel.active_root_id()
    assert staging != active
    # Both should be element ids inside the same panel; both > 0.
    assert staging > 0 and active > 0


def test_reset_for_tests_destroys_panel(fake):
    _panel.staging_root_id()
    assert _panel._panel_id() is not None
    _panel.reset_for_tests()
    # The destroy_panel binding should have been called.
    assert any(c[0] == "destroy_panel" for c in fake.calls)
    assert _panel._panel_id() is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/sdk_ui/test_panel_singleton.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.sdk_ui._panel'`.

- [ ] **Step 3: Create `engine/sdk_ui/nipoint.py`**

```python
"""NiPoint2 — small out-arg helper used by TGUIObject.GetScreenOffset.

SDK code calls:
    kOffset = App.NiPoint2(0, 0)
    pObject.GetScreenOffset(kOffset)
    fX = kOffset.x; fY = kOffset.y

The real SDK NiPoint2 (sdk/Build/scripts/App.py:150) is a SWIG-wrapped C++
class. We provide a Python equivalent with just .x and .y attributes.
"""
from __future__ import annotations


class NiPoint2:
    __slots__ = ("x", "y")

    def __init__(self, x: float = 0.0, y: float = 0.0) -> None:
        self.x = float(x)
        self.y = float(y)

    def __repr__(self) -> str:
        return f"NiPoint2({self.x}, {self.y})"
```

- [ ] **Step 4: Create `engine/sdk_ui/_panel.py`**

```python
"""Singleton panel allocation for the SDK UI shim.

The shim uses one shared C++ PanelDocument for everything it renders. The
panel root has two long-lived children:

  - `staging` — hidden (display:none); freshly-created widgets live here
    between `*_Create*` and `AddChild`.
  - `active`  — visible; widgets are reparented here when added to a real
    parent. Top-level panes (those added to `App.g_kRootWindow`) become
    direct children of `active`.

This keeps reparenting in-panel (cheaper and simpler than cross-panel moves)
and ensures widgets don't flash on screen between creation and placement.
"""
from __future__ import annotations
from typing import Optional

from engine.sdk_ui import _backend

_panel_id_singleton: Optional[int] = None
_staging_id: Optional[int] = None
_active_id: Optional[int] = None


def _panel_id() -> Optional[int]:
    return _panel_id_singleton


def _ensure_panel() -> None:
    global _panel_id_singleton, _staging_id, _active_id
    if _panel_id_singleton is not None:
        return
    backend = _backend.get()
    _panel_id_singleton = backend.create_panel("sdk-ui", "fullscreen", 100.0, 100.0)
    root = backend.panel_root(_panel_id_singleton)
    _staging_id = backend.append_div(root, "bc-sdk-staging")
    backend.set_element_property(_staging_id, "display", "none")
    _active_id = backend.append_div(root, "bc-sdk-active")


def staging_root_id() -> int:
    _ensure_panel()
    assert _staging_id is not None
    return _staging_id


def active_root_id() -> int:
    _ensure_panel()
    assert _active_id is not None
    return _active_id


def panel_id() -> int:
    _ensure_panel()
    assert _panel_id_singleton is not None
    return _panel_id_singleton


def reset_for_tests() -> None:
    """Destroy the shared panel — called between tests to isolate state."""
    global _panel_id_singleton, _staging_id, _active_id
    if _panel_id_singleton is not None:
        _backend.get().destroy_panel(_panel_id_singleton)
    _panel_id_singleton = None
    _staging_id = None
    _active_id = None
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/sdk_ui/test_panel_singleton.py -v`
Expected: PASS (all four tests).

- [ ] **Step 6: Commit**

```bash
git add engine/sdk_ui/nipoint.py engine/sdk_ui/_panel.py tests/sdk_ui/test_panel_singleton.py
git commit -m "feat(sdk_ui): NiPoint2 + lazy single-panel singleton with staging/active divs

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 1.3: Add `reparent_element`, `element_bounds`, `update_layout` to PanelDocument

**Files:**
- Modify: `native/src/ui/include/ui/PanelDocument.h` (add three methods)
- Modify: `native/src/ui/PanelDocument.cc` (implement them)
- Modify: `native/src/host/host_bindings.cc` (add pybind11 wrappers)

- [ ] **Step 1: Add method declarations to PanelDocument.h**

In `native/src/ui/include/ui/PanelDocument.h`, after the existing `set_property` declaration:

```cpp
    /// Move an existing element to be a child of a different parent.
    /// Both must be in this panel. Used by the SDK UI shim to move widgets
    /// out of the hidden "staging" div when AddChild fires.
    void reparent(int element_id, int new_parent_id);

    /// Synchronously update the layout of the subtree rooted at element_id.
    /// Used by the shim after Create / AddChild so subsequent
    /// element_bounds() / GetScreenOffset() / GetWidth() reads see the new
    /// laid-out geometry.
    void update_layout(int element_id);

    /// Write the screen-pixel rect of an arbitrary element.
    /// (x, y) is the top-left in document coordinates; (w, h) is the
    /// rendered box size. Returns false (and writes zeros) if the element
    /// isn't owned by this panel or hasn't been laid out yet.
    bool element_bounds(int element_id,
                        float* out_x, float* out_y,
                        float* out_w, float* out_h) const noexcept;
```

- [ ] **Step 2: Add definitions to PanelDocument.cc**

Append to `native/src/ui/PanelDocument.cc`:

```cpp
void PanelDocument::reparent(int element_id, int new_parent_id) {
    auto it = elements_.find(element_id);
    auto pit = elements_.find(new_parent_id);
    if (it == elements_.end() || pit == elements_.end()) {
        throw std::runtime_error("PanelDocument::reparent: invalid id");
    }
    Rml::Element* el = it->second;
    Rml::Element* old_parent = el->GetParentNode();
    if (!old_parent) {
        throw std::runtime_error("PanelDocument::reparent: element has no parent");
    }
    Rml::ElementPtr el_ptr = old_parent->RemoveChild(el);
    pit->second->AppendChild(std::move(el_ptr));
    // elements_[element_id] still points to the same Rml::Element* — pointer
    // is stable across reparent in RmlUi 6.x; only ownership moved.
}

void PanelDocument::update_layout(int element_id) {
    auto it = elements_.find(element_id);
    if (it == elements_.end()) return;
    if (doc_) {
        doc_->UpdateDocument();  // pumps the whole document
    }
    (void)it;
}

bool PanelDocument::element_bounds(int element_id,
                                    float* out_x, float* out_y,
                                    float* out_w, float* out_h) const noexcept {
    if (out_x) *out_x = 0.f;
    if (out_y) *out_y = 0.f;
    if (out_w) *out_w = 0.f;
    if (out_h) *out_h = 0.f;
    auto it = elements_.find(element_id);
    if (it == elements_.end() || !it->second) return false;
    Rml::Element* el = it->second;
    Rml::Vector2f abs_offset = el->GetAbsoluteOffset();
    Rml::Vector2f box_size = el->GetBox().GetSize();
    if (out_x) *out_x = abs_offset.x;
    if (out_y) *out_y = abs_offset.y;
    if (out_w) *out_w = box_size.x;
    if (out_h) *out_h = box_size.y;
    return true;
}
```

- [ ] **Step 3: Add pybind11 wrappers to host_bindings.cc**

After the existing `m.def("on_dblclick", ...)` block (around line 1050) in `native/src/host/host_bindings.cc`:

```cpp
    m.def("reparent_element",
          [](int element_id, int new_parent_id) {
              if (!g_ui_system) return;
              for (auto& kv : g_ui_system->panels_for_bindings()) {
                  if (kv.second->has_element(element_id)) {
                      kv.second->reparent(element_id, new_parent_id);
                      return;
                  }
              }
          },
          "Move an element to be a child of a different element within "
          "the same panel.");

    m.def("update_layout",
          [](int element_id) {
              if (!g_ui_system) return;
              for (auto& kv : g_ui_system->panels_for_bindings()) {
                  if (kv.second->has_element(element_id)) {
                      kv.second->update_layout(element_id);
                      return;
                  }
              }
          },
          "Synchronously update document layout. Subsequent element_bounds "
          "calls reflect the new geometry.");

    m.def("element_bounds",
          [](int element_id) -> py::tuple {
              if (!g_ui_system) return py::make_tuple(0.0f, 0.0f, 0.0f, 0.0f);
              for (auto& kv : g_ui_system->panels_for_bindings()) {
                  if (kv.second->has_element(element_id)) {
                      float x = 0, y = 0, w = 0, h = 0;
                      kv.second->element_bounds(element_id, &x, &y, &w, &h);
                      return py::make_tuple(x, y, w, h);
                  }
              }
              return py::make_tuple(0.0f, 0.0f, 0.0f, 0.0f);
          },
          "Return (x, y, w, h) screen-pixel rect for any element by id.");

    m.def("viewport_size",
          []() -> py::tuple {
              if (!g_ui_system) return py::make_tuple(0.0f, 0.0f);
              // Pick any live panel's bounds; all use the same viewport.
              for (auto& kv : g_ui_system->panels_for_bindings()) {
                  float x = 0, y = 0, w = 0, h = 0;
                  if (kv.second->bounds(&x, &y, &w, &h)) {
                      // panel_bounds gives panel rect; viewport is harder
                      // without a direct API. We expose the framebuffer size
                      // by routing through ui_system's last-render cache.
                  }
                  break;
              }
              // Fall back: query GLFW. The host loop already tracks fb size;
              // we just need to expose it. For now, return zeros and the
              // shim falls back to the system's monitor query elsewhere.
              return py::make_tuple(0.0f, 0.0f);
          },
          "Return the current framebuffer (w, h) in pixels. Returns (0,0) "
          "if no viewport is initialised.");
```

(Note: `viewport_size` returning zeros is a known-incomplete stub here — Task 1.4 wires it through `UiSystem`.)

- [ ] **Step 4: Build native side**

Run: `cmake --build build -j`
Expected: success. The build produces `build/python/_open_stbc_host.cpython-*.so` (or similar — check current build output path).

Note: per CLAUDE.md the canonical build is `cmake -B build -S . && cmake --build build -j`; never run cmake from inside `native/`.

- [ ] **Step 5: Verify new bindings are importable**

Run: `uv run python -c "import _dauntless_host as h; print('reparent_element', hasattr(h, 'reparent_element')); print('update_layout', hasattr(h, 'update_layout')); print('element_bounds', hasattr(h, 'element_bounds'))"`
Expected output: all three lines say `True`.

- [ ] **Step 6: Commit**

```bash
git add native/src/ui/include/ui/PanelDocument.h native/src/ui/PanelDocument.cc native/src/host/host_bindings.cc
git commit -m "feat(native/ui): add reparent_element, update_layout, element_bounds bindings

Required by the upcoming SDK UI shim. reparent_element moves widgets out
of the staging div; update_layout makes Create / AddChild synchronously
recompute geometry; element_bounds queries any element's rendered rect.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 1.4: Wire viewport_size through UiSystem

**Files:**
- Modify: `native/src/ui/include/ui/UiSystem.h` (add accessor)
- Modify: `native/src/ui/UiSystem.cc` (track last fb size)
- Modify: `native/src/host/host_bindings.cc` (replace stub `viewport_size`)

- [ ] **Step 1: Add accessor to UiSystem.h**

After `void apply_scale_for_height_(int fb_height);` (in the private section), add a public accessor in the public section after `set_ui_scale`:

```cpp
    /// Return the framebuffer size most recently passed to render().
    /// Used by Python bindings to convert screen-pixel rects from
    /// element_bounds() into viewport-fraction coords.
    void framebuffer_size(int* out_w, int* out_h) const noexcept {
        if (out_w) *out_w = last_fb_width_;
        if (out_h) *out_h = last_fb_height_;
    }
```

(Note: `last_fb_width_` / `last_fb_height_` already exist as private members. UiSystem.cc already updates them in render().)

- [ ] **Step 2: Update host_bindings.cc `viewport_size`**

Replace the stub `viewport_size` from Task 1.3 with:

```cpp
    m.def("viewport_size",
          []() -> py::tuple {
              if (!g_ui_system) return py::make_tuple(0.0f, 0.0f);
              int w = 0, h = 0;
              g_ui_system->framebuffer_size(&w, &h);
              return py::make_tuple(static_cast<float>(w), static_cast<float>(h));
          },
          "Return the current framebuffer (w, h) in pixels.");
```

- [ ] **Step 3: Build**

Run: `cmake --build build -j`
Expected: success.

- [ ] **Step 4: Smoke-verify**

Run: `uv run python -c "import _dauntless_host as h; print(h.viewport_size())"`
Expected: prints `(0.0, 0.0)` because UiSystem hasn't rendered yet — that's correct.

- [ ] **Step 5: Commit**

```bash
git add native/src/ui/include/ui/UiSystem.h native/src/host/host_bindings.cc
git commit -m "feat(native/ui): expose framebuffer size to bindings

viewport_size() returns the most recent framebuffer dims that render()
processed; SDK shim uses this to convert pixel rects to screen fractions.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 1.5: `TGUIObject` base class

**Files:**
- Create: `engine/sdk_ui/base.py`
- Create: `tests/sdk_ui/test_base.py`

- [ ] **Step 1: Write the failing test**

`tests/sdk_ui/test_base.py`:

```python
import pytest
from engine.sdk_ui import _backend, _panel
from engine.sdk_ui._fake_backend import FakeNativeBackend
from engine.sdk_ui.base import TGUIObject
from engine.sdk_ui.nipoint import NiPoint2


@pytest.fixture
def fake():
    f = FakeNativeBackend()
    _backend.set_override(f)
    _panel.reset_for_tests()
    yield f
    _backend.set_override(None)
    _panel.reset_for_tests()


def test_object_creates_in_staging(fake):
    obj = TGUIObject(css_class="bc-test")
    # _element_id is set by the constructor (eager creation).
    assert obj._element_id > 0
    # The element's parent is the staging root.
    assert fake.elements[obj._element_id].parent == _panel.staging_root_id()
    assert fake.elements[obj._element_id].cls == "bc-test"


def test_add_child_reparents(fake):
    parent = TGUIObject(css_class="bc-parent")
    child = TGUIObject(css_class="bc-child")
    parent.AddChild(child)
    # Child's parent in the fake's tree is now the parent's element id.
    assert fake.elements[child._element_id].parent == parent._element_id
    # reparent_element was called.
    assert any(
        name == "reparent_element" and args[0] == child._element_id
        for name, args in fake.calls
    )


def test_add_child_sets_position_percent(fake):
    parent = TGUIObject(css_class="bc-parent", declared_w=0.5, declared_h=0.5)
    child = TGUIObject(css_class="bc-child")
    # Parent reports declared width 0.5 (screen-fraction). Child added at
    # x=0.25 → 50% of parent width.
    parent.AddChild(child, 0.25, 0.10, 0)
    props = fake.elements[child._element_id].properties
    assert props.get("left") == "50.0%"
    assert props.get("top") == "20.0%"


def test_set_visible_calls_backend(fake):
    obj = TGUIObject(css_class="bc-test")
    obj.SetNotVisible()
    assert fake.elements[obj._element_id].visible is False
    obj.SetVisible()
    assert fake.elements[obj._element_id].visible is True


def test_get_screen_offset_fills_nipoint2(fake):
    obj = TGUIObject(css_class="bc-test")
    # Plant a known rect on the fake.
    fake.elements[obj._element_id].x_px = 960.0   # 50% of 1920 viewport w
    fake.elements[obj._element_id].y_px = 540.0   # 50% of 1080 viewport h
    p = NiPoint2()
    obj.GetScreenOffset(p)
    assert abs(p.x - 0.5) < 1e-6
    assert abs(p.y - 0.5) < 1e-6


def test_get_width_height_returns_screen_fraction(fake):
    obj = TGUIObject(css_class="bc-test")
    fake.elements[obj._element_id].width_px = 192.0   # 10% of viewport
    fake.elements[obj._element_id].height_px = 108.0  # 10% of viewport
    assert abs(obj.GetWidth() - 0.1) < 1e-6
    assert abs(obj.GetHeight() - 0.1) < 1e-6


def test_get_width_falls_back_to_declared_for_root_panes(fake):
    # If declared and no fake size, declared wins (used for top-level panes
    # before AddChild causes a layout pump).
    fake.viewport_w_px = 1000.0
    fake.viewport_h_px = 1000.0
    obj = TGUIObject(css_class="bc-pane", declared_w=0.5, declared_h=0.5)
    # The fake's set_text never fired, so its width_px is 0 — declared takes
    # over.
    assert obj.GetWidth() == 0.5
    assert obj.GetHeight() == 0.5


def test_remove_child(fake):
    parent = TGUIObject(css_class="bc-parent")
    child = TGUIObject(css_class="bc-child")
    parent.AddChild(child)
    parent.RemoveChild(child)
    assert child._element_id not in fake.elements
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/sdk_ui/test_base.py -v`
Expected: FAIL with `ImportError: cannot import name 'TGUIObject'`.

- [ ] **Step 3: Create `engine/sdk_ui/base.py`**

```python
"""TGUIObject — base class for every shimmed SDK widget.

Lifecycle: every widget is eagerly created as a child of the staging div
(see _panel.staging_root_id()). When AddChild is called, the child is
reparented to its real parent and positioned via inline RCSS left/top
percentages computed from the parent's declared/rendered width.

The model is described in the plan's "Architectural model" section.
"""
from __future__ import annotations
from typing import Optional, TYPE_CHECKING

from engine.sdk_ui import _backend, _panel

if TYPE_CHECKING:
    from engine.sdk_ui.nipoint import NiPoint2


class TGUIObject:
    """Base for all TG*/ST* widgets in the shim."""

    def __init__(
        self,
        css_class: str,
        declared_w: Optional[float] = None,
        declared_h: Optional[float] = None,
    ) -> None:
        self._element_id: int = 0
        self._parent: Optional["TGUIObject"] = None
        self._children: list["TGUIObject"] = []
        # Declared size in screen-fraction units (used by GetWidth/Height when
        # the rendered box hasn't reported a size yet — typical for top-level
        # panes before they're laid out).
        self._declared_w: float = declared_w if declared_w is not None else 0.0
        self._declared_h: float = declared_h if declared_h is not None else 0.0
        self._css_class = css_class
        # Eagerly create the element in staging.
        backend = _backend.get()
        self._element_id = backend.append_div(_panel.staging_root_id(), css_class)
        # Pump layout so GetWidth/GetHeight has *something* to report.
        backend.update_layout(self._element_id)

    # -------- tree mutation --------
    def AddChild(
        self,
        child: "TGUIObject",
        x: float = 0.0,
        y: float = 0.0,
        z: int = 0,
    ) -> None:
        backend = _backend.get()
        backend.reparent_element(child._element_id, self._element_id)
        child._parent = self
        self._children.append(child)
        # Compute child position as % of self's width/height.
        pw = self.GetWidth() or self._declared_w or 1.0
        ph = self.GetHeight() or self._declared_h or 1.0
        # Avoid divide-by-zero — if both rendered and declared are zero,
        # treat parent as the viewport (x and y are already viewport-fractions).
        if pw <= 0.0:
            pw = 1.0
        if ph <= 0.0:
            ph = 1.0
        backend.set_element_property(child._element_id, "left", f"{(x / pw) * 100.0}%")
        backend.set_element_property(child._element_id, "top", f"{(y / ph) * 100.0}%")
        backend.set_element_property(child._element_id, "position", "absolute")
        if z:
            backend.set_element_property(child._element_id, "z-index", str(int(z)))
        # Re-pump layout now that the child has its real parent + position.
        backend.update_layout(child._element_id)

    def RemoveChild(self, child: "TGUIObject") -> None:
        backend = _backend.get()
        backend.remove_element(child._element_id)
        if child in self._children:
            self._children.remove(child)
        child._parent = None

    def RemoveAllChildren(self) -> None:
        for c in list(self._children):
            self.RemoveChild(c)

    def GetParent(self) -> Optional["TGUIObject"]:
        return self._parent

    def GetConceptualParent(self) -> Optional["TGUIObject"]:
        # Same as GetParent for now; menus override this for radio-group walks.
        return self._parent

    def SetParent(self, parent: "TGUIObject") -> None:
        # Some SDK code calls SetParent directly. Equivalent to a re-AddChild
        # at (0, 0) — caller is expected to fix position afterward.
        parent.AddChild(self)

    # -------- visibility / state --------
    def SetVisible(self) -> None:
        _backend.get().set_visible(self._element_id, True)

    def SetNotVisible(self) -> None:
        _backend.get().set_visible(self._element_id, False)

    def IsVisible(self) -> bool:
        return _backend.get().elements[self._element_id].visible \
            if hasattr(_backend.get(), "elements") else True

    def SetDisabled(self, disabled: bool) -> None:
        backend = _backend.get()
        cur = backend.elements[self._element_id].cls if hasattr(backend, "elements") else self._css_class
        classes = set(cur.split())
        if disabled:
            classes.add("bc-disabled")
        else:
            classes.discard("bc-disabled")
        backend.set_class(self._element_id, " ".join(sorted(classes)))

    def IsDisabled(self) -> bool:
        backend = _backend.get()
        cur = backend.elements[self._element_id].cls if hasattr(backend, "elements") else self._css_class
        return "bc-disabled" in cur.split()

    def SetFocus(self, child: Optional["TGUIObject"] = None) -> None:
        # Focus is implicit in RmlUi (last-clicked / tab-target). SDK calls
        # this to seed focus; we no-op for now and let runtime handle it.
        pass

    def HasFocus(self) -> bool:
        return False

    # -------- readback --------
    def GetScreenOffset(self, point: "NiPoint2") -> None:
        """Fill point with this element's screen-fraction position."""
        backend = _backend.get()
        x, y, _w, _h = backend.element_bounds(self._element_id)
        vw, vh = backend.viewport_size()
        if vw <= 0.0 or vh <= 0.0:
            point.x = 0.0
            point.y = 0.0
            return
        point.x = x / vw
        point.y = y / vh

    def GetWidth(self) -> float:
        backend = _backend.get()
        _x, _y, w, _h = backend.element_bounds(self._element_id)
        vw, _vh = backend.viewport_size()
        if vw > 0.0 and w > 0.0:
            return w / vw
        return self._declared_w

    def GetHeight(self) -> float:
        backend = _backend.get()
        _x, _y, _w, h = backend.element_bounds(self._element_id)
        _vw, vh = backend.viewport_size()
        if vh > 0.0 and h > 0.0:
            return h / vh
        return self._declared_h

    def SetWidth(self, w: float) -> None:
        self._declared_w = float(w)
        _backend.get().set_element_property(self._element_id, "width", f"{w * 100.0}%")

    def SetHeight(self, h: float) -> None:
        self._declared_h = float(h)
        _backend.get().set_element_property(self._element_id, "height", f"{h * 100.0}%")

    # -------- event handler registration (impl deferred until Task 1.7) --------
    def AddPythonFuncHandlerForInstance(self, event_type: int, handler_name: str) -> None:
        from engine.sdk_ui.events import g_kEventManager
        g_kEventManager._register_per_instance(self._element_id, event_type, handler_name)

    def CallNextHandler(self, event) -> None:
        from engine.sdk_ui.events import g_kEventManager
        g_kEventManager._propagate(self, event)

    def SetAlwaysHandleEvents(self) -> None:
        # No-op — events propagate by default in our model.
        pass

    def MoveToFront(self, child: "TGUIObject") -> None:
        _backend.get().set_element_property(child._element_id, "z-index", "999")

    def AlignTo(self, ref: "TGUIObject", my_corner: int, ref_corner: int) -> None:
        # Best-effort alignment via inline left/top. SDK uses bitmasked corner
        # constants — for now we just stack against ref's bottom-left.
        backend = _backend.get()
        x, y, _w, h = backend.element_bounds(ref._element_id)
        vw, vh = backend.viewport_size()
        if vw > 0 and vh > 0:
            backend.set_element_property(self._element_id, "left", f"{(x / vw) * 100.0}%")
            backend.set_element_property(self._element_id, "top", f"{((y + h) / vh) * 100.0}%")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/sdk_ui/test_base.py -v`
Expected: PASS (all eight tests).

- [ ] **Step 5: Commit**

```bash
git add engine/sdk_ui/base.py tests/sdk_ui/test_base.py
git commit -m "feat(sdk_ui): TGUIObject base class with staging/reparent lifecycle

Eager element creation in staging; AddChild reparents and positions via
inline RCSS % computed from parent width. GetScreenOffset/Width/Height
divide rendered pixel rects by the viewport size to return screen
fractions.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 1.6: `resolver.py` — string handler lookup

**Files:**
- Create: `engine/sdk_ui/resolver.py`
- Create: `tests/sdk_ui/test_resolver.py`

- [ ] **Step 1: Write the failing test**

`tests/sdk_ui/test_resolver.py`:

```python
import pytest
from engine.sdk_ui.resolver import resolve, EventHandlerError, clear_cache


def test_resolve_module_func():
    fn = resolve("os.path.join")
    assert callable(fn)
    assert fn("a", "b") == "a/b" or fn("a", "b") == "a\\b"


def test_resolve_caches(monkeypatch):
    clear_cache()
    n = [0]
    import importlib
    real_import = importlib.import_module

    def counting_import(name):
        n[0] += 1
        return real_import(name)

    monkeypatch.setattr(importlib, "import_module", counting_import)
    resolve("os.getcwd")
    resolve("os.getcwd")
    resolve("os.getcwd")
    assert n[0] == 1


def test_resolve_unknown_module_raises():
    clear_cache()
    with pytest.raises(EventHandlerError) as exc:
        resolve("no_such_module_xyz.foo")
    assert "no_such_module_xyz" in str(exc.value)


def test_resolve_unknown_attr_raises():
    clear_cache()
    with pytest.raises(EventHandlerError) as exc:
        resolve("os.no_such_attribute_xyz")
    assert "no_such_attribute_xyz" in str(exc.value)


def test_resolve_no_dot_raises():
    clear_cache()
    with pytest.raises(EventHandlerError):
        resolve("just_a_name")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/sdk_ui/test_resolver.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.sdk_ui.resolver'`.

- [ ] **Step 3: Create `engine/sdk_ui/resolver.py`**

```python
"""'module.func' string -> callable resolution for SDK event handlers.

SDK code registers handlers by name:

    pPane.AddPythonFuncHandlerForInstance(
        App.ET_LOAD_GAME, __name__ + '.RestartGame')

When the event fires we need to look 'MissionLib.RestartGame' back up.
This module does that, caching successful lookups for cheap re-dispatch.
"""
from __future__ import annotations
import importlib
from typing import Callable

_cache: dict[str, Callable] = {}


class EventHandlerError(RuntimeError):
    """Raised when a handler string can't be resolved to a callable."""


def resolve(handler_name: str) -> Callable:
    """Look up 'module.path.func' and return the callable.

    Failures raise EventHandlerError with the original cause chained so the
    test/debug experience surfaces what's wrong (missing module vs missing
    attribute).
    """
    if handler_name in _cache:
        return _cache[handler_name]
    if "." not in handler_name:
        raise EventHandlerError(
            f"handler name {handler_name!r} has no dot; expected 'module.func'")
    mod_name, _, attr_name = handler_name.rpartition(".")
    try:
        mod = importlib.import_module(mod_name)
    except ImportError as e:
        raise EventHandlerError(
            f"cannot import handler module {mod_name!r}: {e}") from e
    try:
        fn = getattr(mod, attr_name)
    except AttributeError as e:
        raise EventHandlerError(
            f"module {mod_name!r} has no attribute {attr_name!r}") from e
    if not callable(fn):
        raise EventHandlerError(
            f"{handler_name!r} resolves to a non-callable: {fn!r}")
    _cache[handler_name] = fn
    return fn


def clear_cache() -> None:
    """Drop all cached resolutions. Used by tests for isolation."""
    _cache.clear()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/sdk_ui/test_resolver.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/sdk_ui/resolver.py tests/sdk_ui/test_resolver.py
git commit -m "feat(sdk_ui): 'module.func' handler string resolver

Used by AddPythonFuncHandlerForInstance + broadcast handlers to map
SDK-style handler names to callables. Caches successful lookups.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 1.7: Event manager — `ET_*` constants, `TGEvent`, `g_kEventManager`

**Files:**
- Create: `engine/sdk_ui/events.py`
- Create: `tests/sdk_ui/test_events.py`

- [ ] **Step 1: Write the failing test**

`tests/sdk_ui/test_events.py`:

```python
import pytest
import sys
import types

from engine.sdk_ui import _backend, _panel
from engine.sdk_ui._fake_backend import FakeNativeBackend
from engine.sdk_ui.base import TGUIObject
from engine.sdk_ui.events import (
    ET_LOAD_GAME, ET_CANCEL, ET_NEW_GAME,
    TGEvent_Create, g_kEventManager,
)
from engine.sdk_ui import resolver


@pytest.fixture
def fake():
    f = FakeNativeBackend()
    _backend.set_override(f)
    _panel.reset_for_tests()
    g_kEventManager._reset()
    resolver.clear_cache()
    yield f
    _backend.set_override(None)
    _panel.reset_for_tests()
    g_kEventManager._reset()


def test_et_constants_are_distinct_ints():
    constants = {ET_LOAD_GAME, ET_CANCEL, ET_NEW_GAME}
    assert len(constants) == 3
    for c in constants:
        assert isinstance(c, int)


def test_tgevent_setters_and_getters(fake):
    ev = TGEvent_Create()
    obj = TGUIObject(css_class="bc-test")
    ev.SetDestination(obj)
    ev.SetEventType(ET_LOAD_GAME)
    assert ev.GetDestination() is obj
    assert ev.GetType() == ET_LOAD_GAME


def test_per_instance_handler_resolves_and_fires(fake):
    obj = TGUIObject(css_class="bc-test")
    # Install a fake handler module.
    mod = types.ModuleType("_fake_handlers_test")
    fired = []
    def handler(event):
        fired.append(("per_instance", event.GetType()))
    mod.handler = handler
    sys.modules["_fake_handlers_test"] = mod

    obj.AddPythonFuncHandlerForInstance(ET_LOAD_GAME, "_fake_handlers_test.handler")
    ev = TGEvent_Create()
    ev.SetDestination(obj)
    ev.SetEventType(ET_LOAD_GAME)
    g_kEventManager.dispatch(ev)

    assert fired == [("per_instance", ET_LOAD_GAME)]


def test_broadcast_handler_fires(fake):
    obj = TGUIObject(css_class="bc-test")
    mod = types.ModuleType("_fake_broadcast_test")
    fired = []
    mod.bcast = lambda event: fired.append("bcast")
    sys.modules["_fake_broadcast_test"] = mod

    g_kEventManager.AddBroadcastPythonFuncHandler(
        ET_NEW_GAME, obj, "_fake_broadcast_test.bcast")
    ev = TGEvent_Create()
    ev.SetEventType(ET_NEW_GAME)
    g_kEventManager.dispatch(ev)
    assert fired == ["bcast"]


def test_handler_propagates_to_parent_via_callnextkhandler(fake):
    grandparent = TGUIObject(css_class="bc-gp")
    parent = TGUIObject(css_class="bc-p")
    child = TGUIObject(css_class="bc-c")
    grandparent.AddChild(parent)
    parent.AddChild(child)

    mod = types.ModuleType("_fake_propagate_test")
    seq = []
    def parent_handler(event):
        seq.append("parent")
        # Calling CallNextHandler propagates up the conceptual-parent chain.
        # NB: invoked on the obj currently dispatching — for per-instance we
        # call obj.CallNextHandler(event) inside the handler.
        event.GetDestination().CallNextHandler(event)
    def gp_handler(event):
        seq.append("gp")
    mod.parent_handler = parent_handler
    mod.gp_handler = gp_handler
    sys.modules["_fake_propagate_test"] = mod

    # Register on child; child has no handler so it walks up.
    parent.AddPythonFuncHandlerForInstance(ET_CANCEL, "_fake_propagate_test.parent_handler")
    grandparent.AddPythonFuncHandlerForInstance(ET_CANCEL, "_fake_propagate_test.gp_handler")

    ev = TGEvent_Create()
    ev.SetDestination(child)
    ev.SetEventType(ET_CANCEL)
    g_kEventManager.dispatch(ev)
    assert seq == ["parent", "gp"]


def test_unknown_handler_raises_at_dispatch(fake):
    obj = TGUIObject(css_class="bc-test")
    obj.AddPythonFuncHandlerForInstance(ET_CANCEL, "no_such_module.nope")
    ev = TGEvent_Create()
    ev.SetDestination(obj)
    ev.SetEventType(ET_CANCEL)
    with pytest.raises(resolver.EventHandlerError):
        g_kEventManager.dispatch(ev)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/sdk_ui/test_events.py -v`
Expected: FAIL with import error.

- [ ] **Step 3: Create `engine/sdk_ui/events.py`**

```python
"""SDK event-system façade.

ET_* constants are flat integer enums. TGEvent is a small carrier object
(type, destination, source, payload). g_kEventManager is the singleton
dispatcher with per-instance and broadcast registries.

Handler resolution is delegated to resolver.resolve('module.func').
"""
from __future__ import annotations
from typing import Optional, TYPE_CHECKING

from engine.sdk_ui import resolver

if TYPE_CHECKING:
    from engine.sdk_ui.base import TGUIObject


# ── ET_* event-type constants ────────────────────────────────────────────
# Enumerated by grepping bridge UI + MissionLib for App.ET_*. Add new
# constants here as we expand widget coverage. Numeric values are stable
# (we never change a constant's int once assigned) so handler tables stay
# consistent across versions.

ET_LOAD_GAME              = 1
ET_NEW_GAME               = 2
ET_CANCEL                 = 3
ET_BUTTON_CLICKED         = 4
ET_TARGET_SELECTED        = 5
ET_MENU_OPEN              = 6
ET_MENU_CLOSE             = 7
ET_OPTION_CHANGED         = 8
ET_RESUME_GAME            = 9
ET_QUIT_TO_MAIN_MENU      = 10
ET_GAME_OVER              = 11
# Slice 4 expands the set; new entries get appended with the next integer.


class TGEvent:
    """A SDK event carrier. Cheap to construct; tested by reference."""
    __slots__ = ("_type", "_destination", "_source", "_x", "_y", "_payload", "_consumed")

    def __init__(self) -> None:
        self._type: int = 0
        self._destination: Optional["TGUIObject"] = None
        self._source: Optional["TGUIObject"] = None
        self._x: float = 0.0
        self._y: float = 0.0
        self._payload: object = None
        self._consumed: bool = False

    # Setters
    def SetEventType(self, t: int) -> None: self._type = int(t)
    def SetDestination(self, dst) -> None: self._destination = dst
    def SetSource(self, src) -> None: self._source = src
    def SetX(self, x: float) -> None: self._x = float(x)
    def SetY(self, y: float) -> None: self._y = float(y)
    def SetPayload(self, p) -> None: self._payload = p

    # Getters
    def GetType(self) -> int: return self._type
    def GetDestination(self): return self._destination
    def GetSource(self): return self._source
    def GetX(self) -> float: return self._x
    def GetY(self) -> float: return self._y
    def GetPayload(self): return self._payload


def TGEvent_Create() -> TGEvent:
    """SDK factory function. SDK code does pEvent = App.TGEvent_Create()."""
    return TGEvent()


class _EventManager:
    """Singleton dispatcher.

    Per-instance handlers are stored by (element_id, event_type).
    Broadcast handlers fire after per-instance, in registration order.
    """
    def __init__(self) -> None:
        # (element_id, event_type) -> [handler_name, ...]
        self._per_instance: dict[tuple[int, int], list[str]] = {}
        # event_type -> [(element_id, handler_name), ...]
        self._broadcast: dict[int, list[tuple[int, str]]] = {}

    def _reset(self) -> None:
        self._per_instance.clear()
        self._broadcast.clear()

    # SDK-public surface
    def AddBroadcastPythonFuncHandler(self, event_type: int, target, handler_name: str) -> None:
        key = int(event_type)
        self._broadcast.setdefault(key, []).append((target._element_id, handler_name))

    # Internal — called by TGUIObject.AddPythonFuncHandlerForInstance
    def _register_per_instance(self, element_id: int, event_type: int, handler_name: str) -> None:
        key = (element_id, int(event_type))
        self._per_instance.setdefault(key, []).append(handler_name)

    def dispatch(self, event: TGEvent) -> None:
        """Fire per-instance on destination, then broadcast handlers."""
        dst = event.GetDestination()
        if dst is not None:
            self._fire_per_instance(dst._element_id, event)
        for (target_eid, handler_name) in self._broadcast.get(event.GetType(), []):
            fn = resolver.resolve(handler_name)
            fn(event)

    def _fire_per_instance(self, element_id: int, event: TGEvent) -> None:
        handlers = self._per_instance.get((element_id, event.GetType()), [])
        for name in handlers:
            fn = resolver.resolve(name)
            fn(event)

    def _propagate(self, obj, event: TGEvent) -> None:
        """Walk up the conceptual-parent chain, firing per-instance handlers."""
        parent = obj.GetConceptualParent()
        if parent is None:
            return
        self._fire_per_instance(parent._element_id, event)


g_kEventManager = _EventManager()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/sdk_ui/test_events.py -v`
Expected: PASS (all six tests).

- [ ] **Step 5: Commit**

```bash
git add engine/sdk_ui/events.py tests/sdk_ui/test_events.py
git commit -m "feat(sdk_ui): event-manager facade with TGEvent + g_kEventManager

Per-instance + broadcast registries, CallNextHandler-driven parent-chain
propagation, handler-name resolution via resolver.resolve().

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 1.8: `TGPane_Create` and `TGParagraph_CreateW`

**Files:**
- Create: `engine/sdk_ui/primitives.py`
- Create: `tests/sdk_ui/test_primitives.py`

- [ ] **Step 1: Write the failing test**

`tests/sdk_ui/test_primitives.py`:

```python
import pytest
from engine.sdk_ui import _backend, _panel
from engine.sdk_ui._fake_backend import FakeNativeBackend
from engine.sdk_ui.primitives import TGPane_Create, TGParagraph_CreateW


@pytest.fixture
def fake():
    f = FakeNativeBackend()
    _backend.set_override(f)
    _panel.reset_for_tests()
    yield f
    _backend.set_override(None)
    _panel.reset_for_tests()


def test_tgpane_create_returns_object_with_declared_size(fake):
    p = TGPane_Create(0.5, 0.25)
    assert p.GetWidth() == 0.5
    assert p.GetHeight() == 0.25
    # Element exists in fake.
    assert p._element_id in fake.elements
    assert "bc-tgpane" in fake.elements[p._element_id].cls


def test_tgpane_create_default_size_is_unit(fake):
    p = TGPane_Create()
    assert p.GetWidth() == 1.0
    assert p.GetHeight() == 1.0


def test_tgparagraph_createw_stores_text_and_width(fake):
    para = TGParagraph_CreateW("Game Over", 0.45, None, "Serpentine", 12)
    # Text was set on the element.
    assert fake.elements[para._element_id].text == "Game Over"
    # GetWidth returns declared 0.45 (the paragraph wraps to that width).
    assert para.GetWidth() == 0.45
    assert "bc-tgparagraph" in fake.elements[para._element_id].cls
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/sdk_ui/test_primitives.py -v`
Expected: FAIL.

- [ ] **Step 3: Create `engine/sdk_ui/primitives.py`**

```python
"""Primitive widget factories: TGPane, TGParagraph, TGIcon (stub), TGFrame.

These map 1:1 onto SDK factory functions (App.TGPane_Create etc) and return
TGUIObject subclasses. The classes themselves are private — callers use the
factory functions.
"""
from __future__ import annotations
from typing import Optional

from engine.sdk_ui import _backend
from engine.sdk_ui.base import TGUIObject


class _TGPane(TGUIObject):
    pass


def TGPane_Create(w: float = 1.0, h: float = 1.0) -> _TGPane:
    """Bare rectangular container. (w, h) are screen-fractions."""
    return _TGPane(css_class="bc-tgpane", declared_w=float(w), declared_h=float(h))


class _TGParagraph(TGUIObject):
    pass


def TGParagraph_Create(
    text: str,
    width: float,
    font: Optional[str] = None,
    typeface: Optional[str] = None,
    size: int = 12,
) -> _TGParagraph:
    """ASCII variant — SDK uses this for English-only strings."""
    return _TGParagraph_internal(text, width, typeface, size)


def TGParagraph_CreateW(
    text: str,
    width: float,
    font: Optional[str] = None,
    typeface: Optional[str] = None,
    size: int = 12,
) -> _TGParagraph:
    """Wide-string variant — SDK uses this for localised strings.

    Signature mirrors:
        sdk/Build/scripts/MissionLib.py:2004:
        App.TGParagraph_CreateW(text, 0.45, None, "Serpentine", 12)
    """
    return _TGParagraph_internal(text, width, typeface, size)


def _TGParagraph_internal(
    text: str,
    width: float,
    typeface: Optional[str],
    size: int,
) -> _TGParagraph:
    p = _TGParagraph(
        css_class="bc-tgparagraph",
        declared_w=float(width),
        # Declared height is intrinsic; set by RmlUi layout. Leave at 0 so
        # GetHeight() falls back to the rendered value once laid out.
        declared_h=0.0,
    )
    backend = _backend.get()
    backend.set_text(p._element_id, text)
    # Inline width so the paragraph wraps to the declared screen-fraction.
    backend.set_element_property(p._element_id, "width", f"{width * 100.0}%")
    # Font/typeface stubbed for now — CSS classes in sdk_ui.rcss handle font
    # families; size could be wired via inline font-size if needed later.
    backend.update_layout(p._element_id)
    return p


# Stubs for Slice 4 (declared here so imports don't break).
def TGIcon_Create(group_name: str, index: int, color=None) -> "_TGIcon":
    return _TGIcon(css_class=f"bc-tgicon bc-tgicon-{group_name}-{index}")


class _TGIcon(TGUIObject):
    pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/sdk_ui/test_primitives.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/sdk_ui/primitives.py tests/sdk_ui/test_primitives.py
git commit -m "feat(sdk_ui): TGPane_Create, TGParagraph_Create[W], TGIcon_Create stub

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 1.9: `STButton_CreateW` (event-firing button)

**Files:**
- Create: `engine/sdk_ui/buttons.py`
- Create: `tests/sdk_ui/test_buttons.py`

- [ ] **Step 1: Write the failing test**

`tests/sdk_ui/test_buttons.py`:

```python
import pytest
import sys
import types

from engine.sdk_ui import _backend, _panel
from engine.sdk_ui._fake_backend import FakeNativeBackend
from engine.sdk_ui.events import TGEvent_Create, ET_LOAD_GAME, g_kEventManager
from engine.sdk_ui.buttons import STButton_CreateW, STBSF_SIZE_TO_TEXT
from engine.sdk_ui.primitives import TGPane_Create
from engine.sdk_ui import resolver


@pytest.fixture
def fake():
    f = FakeNativeBackend()
    _backend.set_override(f)
    _panel.reset_for_tests()
    g_kEventManager._reset()
    resolver.clear_cache()
    yield f
    _backend.set_override(None)
    _panel.reset_for_tests()
    g_kEventManager._reset()


def test_button_created_with_label(fake):
    ev = TGEvent_Create()
    ev.SetEventType(ET_LOAD_GAME)
    btn = STButton_CreateW("Restart", ev, STBSF_SIZE_TO_TEXT)
    assert fake.elements[btn._element_id].text == "Restart"
    assert "bc-stbutton" in fake.elements[btn._element_id].cls


def test_button_click_fires_event(fake):
    pane = TGPane_Create(0.5, 0.5)
    ev = TGEvent_Create()
    ev.SetDestination(pane)
    ev.SetEventType(ET_LOAD_GAME)
    btn = STButton_CreateW("Restart", ev, STBSF_SIZE_TO_TEXT)
    pane.AddChild(btn, 0.0, 0.0)

    mod = types.ModuleType("_button_handler_test")
    fired = []
    mod.handler = lambda event: fired.append(event.GetType())
    sys.modules["_button_handler_test"] = mod
    pane.AddPythonFuncHandlerForInstance(ET_LOAD_GAME, "_button_handler_test.handler")

    fake.fire_click(btn._element_id)
    assert fired == [ET_LOAD_GAME]


def test_button_dispatches_to_event_destination_not_button(fake):
    """The SDK convention: the event's SetDestination(pane) means handlers on
    the pane fire on click, not handlers on the button itself."""
    pane = TGPane_Create(0.5, 0.5)
    ev = TGEvent_Create()
    ev.SetDestination(pane)
    ev.SetEventType(ET_LOAD_GAME)
    btn = STButton_CreateW("Restart", ev, STBSF_SIZE_TO_TEXT)
    pane.AddChild(btn, 0.0, 0.0)

    mod = types.ModuleType("_button_dest_test")
    fired = []
    mod.h = lambda event: fired.append("hit")
    sys.modules["_button_dest_test"] = mod

    # Register on the BUTTON — should NOT fire.
    btn.AddPythonFuncHandlerForInstance(ET_LOAD_GAME, "_button_dest_test.h")
    fake.fire_click(btn._element_id)
    assert fired == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/sdk_ui/test_buttons.py -v`
Expected: FAIL with import error.

- [ ] **Step 3: Create `engine/sdk_ui/buttons.py`**

```python
"""Button factories. Slice 1 implements STButton_CreateW; Slice 4 adds the rest."""
from __future__ import annotations
from typing import Optional, TYPE_CHECKING

from engine.sdk_ui import _backend
from engine.sdk_ui.base import TGUIObject

if TYPE_CHECKING:
    from engine.sdk_ui.events import TGEvent


# SDK style flags for STButton_CreateW. Bitmask values are mirrored from the
# SDK's App.STBSF_* constants. Only the ones bridge UI / MissionLib actually
# pass are enumerated; new flags appended as needed.
STBSF_SIZE_TO_TEXT     = 1 << 0
STBSF_DEFAULT          = 1 << 1
STBSF_NO_AUTOHIGHLIGHT = 1 << 2


class _STButton(TGUIObject):
    """Themed bridge button.

    The construction event template is stashed on the instance and cloned
    when fired (so the same template can be reused if the SDK does that).
    """
    def __init__(self, label: str, event_template: Optional["TGEvent"], flags: int) -> None:
        super().__init__(css_class="bc-stbutton")
        backend = _backend.get()
        backend.set_text(self._element_id, label)
        self._event_template = event_template
        self._flags = flags
        backend.on_click(self._element_id, self._on_click)

    def _on_click(self) -> None:
        from engine.sdk_ui.events import TGEvent_Create, g_kEventManager
        if self._event_template is None:
            return
        # Clone the template (don't mutate it — SDK may reuse).
        ev = TGEvent_Create()
        ev.SetEventType(self._event_template.GetType())
        ev.SetDestination(self._event_template.GetDestination())
        ev.SetSource(self)
        ev.SetPayload(self._event_template.GetPayload())
        g_kEventManager.dispatch(ev)


def STButton_CreateW(label: str, event: Optional["TGEvent"], flags: int = 0) -> _STButton:
    """Wide-string SDK button factory. Mirrors:
        sdk/Build/scripts/MissionLib.py:2012:
        App.STButton_CreateW(label, pEvent, App.STBSF_SIZE_TO_TEXT)
    """
    return _STButton(label, event, flags)


def STButton_Create(label: str, event: Optional["TGEvent"], flags: int = 0) -> _STButton:
    """ASCII variant — same impl."""
    return _STButton(label, event, flags)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/sdk_ui/test_buttons.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/sdk_ui/buttons.py tests/sdk_ui/test_buttons.py
git commit -m "feat(sdk_ui): STButton_CreateW with event-template click dispatch

Click on button fires the construction-time event template (cloned, with
self as Source) through g_kEventManager. Handlers on the event's
Destination fire — matching SDK semantics.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 1.10: `STStylizedWindow_Create` (minimal, frame children stored)

**Files:**
- Create: `engine/sdk_ui/stylized.py`
- Create: `tests/sdk_ui/test_stylized.py`

- [ ] **Step 1: Write the failing test**

`tests/sdk_ui/test_stylized.py`:

```python
import pytest
from engine.sdk_ui import _backend, _panel
from engine.sdk_ui._fake_backend import FakeNativeBackend
from engine.sdk_ui.stylized import STStylizedWindow_Create, STStylizedWindow_CreateW
from engine.sdk_ui.primitives import TGPane_Create


@pytest.fixture
def fake():
    f = FakeNativeBackend()
    _backend.set_override(f)
    _panel.reset_for_tests()
    yield f
    _backend.set_override(None)
    _panel.reset_for_tests()


def test_stylized_window_create(fake):
    w = STStylizedWindow_Create("MyWindow", "RightBorder", None)
    assert "bc-ststylizedwindow" in fake.elements[w._element_id].cls
    # Template name is stored as a data attribute via class for CSS styling.
    assert "bc-tpl-RightBorder" in fake.elements[w._element_id].cls


def test_stylized_window_createw(fake):
    w = STStylizedWindow_CreateW("MyWindow", "RightBorder", "My Title", 0.5, 0.4)
    assert w.GetWidth() == 0.5
    assert w.GetHeight() == 0.4


def test_can_add_pane_child(fake):
    w = STStylizedWindow_Create("MyWindow", "RightBorder", None)
    pane = TGPane_Create(0.5, 0.5)
    w.AddChild(pane)
    assert fake.elements[pane._element_id].parent == w._element_id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/sdk_ui/test_stylized.py -v`
Expected: FAIL.

- [ ] **Step 3: Create `engine/sdk_ui/stylized.py`**

```python
"""Stylized window — themed window with frame chrome.

Slice 1 implements the bare element (a div with the right CSS classes).
Slice 3 expands the frame-children handling so TGIcon-based decoration
('NormalStyleFrame' indices 0-23) flows in via SetIconLocation +
TGIcon_Create. Until then, AddChild calls for those frame icons work as
plain decorative spans with no visual treatment.
"""
from __future__ import annotations
from typing import Optional

from engine.sdk_ui.base import TGUIObject


class _STStylizedWindow(TGUIObject):
    pass


def STStylizedWindow_Create(
    name: str,
    template: str,
    parent: Optional[TGUIObject] = None,
) -> _STStylizedWindow:
    """SDK signature mirrors:
        sdk/Build/scripts/MissionLib.py:1998:
        App.STStylizedWindow_Create('StylizedWindow', 'RightBorder', None)
    """
    classes = f"bc-ststylizedwindow bc-tpl-{template}"
    w = _STStylizedWindow(css_class=classes)
    if parent is not None:
        parent.AddChild(w)
    return w


def STStylizedWindow_CreateW(
    name: str,
    template: str,
    title: Optional[str] = None,
    w: float = 1.0,
    h: float = 1.0,
) -> _STStylizedWindow:
    """Wide-string variant with title and explicit dimensions."""
    classes = f"bc-ststylizedwindow bc-tpl-{template}"
    win = _STStylizedWindow(
        css_class=classes,
        declared_w=float(w),
        declared_h=float(h),
    )
    if title:
        from engine.sdk_ui import _backend
        _backend.get().set_element_property(win._element_id, "data-title", title)
    return win


class _STSubPane(TGUIObject):
    pass


def STSubPane_Create() -> _STSubPane:
    return _STSubPane(css_class="bc-stsubpane")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/sdk_ui/test_stylized.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/sdk_ui/stylized.py tests/sdk_ui/test_stylized.py
git commit -m "feat(sdk_ui): STStylizedWindow_Create[W] + STSubPane (minimal)

Frame-children support deferred to Slice 3 once icon manager lands. For
now these are styled divs with template class for CSS hooks.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 1.11: Re-export shim symbols through `App.py`

**Files:**
- Modify: `App.py` (project root)
- Create: `tests/sdk_ui/test_app_reexports.py`

- [ ] **Step 1: Write the failing test**

`tests/sdk_ui/test_app_reexports.py`:

```python
"""Verify App.py exposes shim factory functions and event-system symbols."""
import App


def test_re_exports_tgpane_create():
    assert hasattr(App, "TGPane_Create")
    p = App.TGPane_Create(0.5, 0.5)
    assert p.GetWidth() == 0.5


def test_re_exports_tgparagraph_createw():
    assert hasattr(App, "TGParagraph_CreateW")


def test_re_exports_stbutton_createw():
    assert hasattr(App, "STButton_CreateW")
    assert hasattr(App, "STBSF_SIZE_TO_TEXT")


def test_re_exports_stylized_window():
    assert hasattr(App, "STStylizedWindow_Create")
    assert hasattr(App, "STStylizedWindow_CreateW")


def test_re_exports_event_manager():
    assert hasattr(App, "g_kEventManager")
    assert hasattr(App, "TGEvent_Create")
    assert hasattr(App, "ET_LOAD_GAME")
    assert hasattr(App, "ET_CANCEL")
    assert hasattr(App, "ET_NEW_GAME")


def test_re_exports_nipoint2():
    assert hasattr(App, "NiPoint2")
    p = App.NiPoint2(1.5, 2.5)
    assert p.x == 1.5 and p.y == 2.5
```

(Plus a fixture in `tests/sdk_ui/conftest.py` to provide the fake backend — see step 3.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/sdk_ui/test_app_reexports.py -v`
Expected: FAIL — App.py doesn't export these yet.

- [ ] **Step 3: Create `tests/sdk_ui/conftest.py`**

```python
"""Provide the FakeNativeBackend as the default for all sdk_ui tests."""
import pytest
from engine.sdk_ui import _backend, _panel
from engine.sdk_ui._fake_backend import FakeNativeBackend


@pytest.fixture(autouse=True)
def _sdk_ui_fake_backend():
    f = FakeNativeBackend()
    _backend.set_override(f)
    _panel.reset_for_tests()
    yield f
    _backend.set_override(None)
    _panel.reset_for_tests()
```

This replaces the per-test `fake` fixtures in earlier tasks — keep both for now (the autouse fixture and the local `fake` fixtures coexist; the autouse one runs first and the local one re-sets the override).

- [ ] **Step 4: Add `g_kRootWindow` to `engine/sdk_ui/_panel.py`**

The "root window" is what SDK scripts AddChild top-level panes to. We wrap the `active` div as a `TGUIObject` and expose it as a module-level singleton:

```python
# At the bottom of engine/sdk_ui/_panel.py, add:

def root_window():
    """Return a TGUIObject wrapping the panel's `active` div.

    SDK scripts call App.g_kRootWindow.AddChild(pane, x, y) to make a
    top-level pane visible. This returns a wrapper that, when AddChild is
    called on it, reparents the pane out of staging into the active subtree.
    """
    from engine.sdk_ui.base import TGUIObject
    _ensure_panel()
    obj = TGUIObject.__new__(TGUIObject)
    obj._element_id = active_root_id()
    obj._parent = None
    obj._children = []
    obj._declared_w = 1.0
    obj._declared_h = 1.0
    obj._css_class = "bc-sdk-active"
    return obj
```

- [ ] **Step 5: Update `App.py` (project root) — append the re-export block**

At the end of `App.py`, before any closing module-level code, add:

```python
# ── SDK UI shim re-exports ───────────────────────────────────────────────
# All TG*/ST* widget factories, NiPoint2, the event manager, and ET_*
# constants are implemented in engine/sdk_ui/ and surfaced here so that
# SDK scripts (Bridge/*.py, MissionLib.py, etc.) can use the names they
# already reference.
from engine.sdk_ui.nipoint import NiPoint2
from engine.sdk_ui.primitives import (
    TGPane_Create,
    TGParagraph_Create,
    TGParagraph_CreateW,
    TGIcon_Create,
)
from engine.sdk_ui.buttons import (
    STButton_Create,
    STButton_CreateW,
    STBSF_SIZE_TO_TEXT,
    STBSF_DEFAULT,
    STBSF_NO_AUTOHIGHLIGHT,
)
from engine.sdk_ui.stylized import (
    STStylizedWindow_Create,
    STStylizedWindow_CreateW,
    STSubPane_Create,
)
from engine.sdk_ui.events import (
    TGEvent_Create,
    g_kEventManager,
    ET_LOAD_GAME,
    ET_NEW_GAME,
    ET_CANCEL,
    ET_BUTTON_CLICKED,
    ET_TARGET_SELECTED,
    ET_MENU_OPEN,
    ET_MENU_CLOSE,
    ET_OPTION_CHANGED,
    ET_RESUME_GAME,
    ET_QUIT_TO_MAIN_MENU,
    ET_GAME_OVER,
)

# Lazy property — first access triggers panel allocation.
class _RootWindowProxy:
    def __getattr__(self, name):
        from engine.sdk_ui._panel import root_window
        return getattr(root_window(), name)

g_kRootWindow = _RootWindowProxy()
```

Add `g_kRootWindow` to the test in step 1 of Task 1.11:

```python
def test_re_exports_root_window():
    assert hasattr(App, "g_kRootWindow")
    # Calling a method through the proxy should work.
    p = App.TGPane_Create(0.5, 0.5)
    App.g_kRootWindow.AddChild(p, 0.0, 0.0)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/sdk_ui/test_app_reexports.py -v`
Expected: PASS.

- [ ] **Step 7: Run full sdk_ui suite to verify no regressions**

Run: `uv run pytest tests/sdk_ui/ -v`
Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add App.py engine/sdk_ui/_panel.py tests/sdk_ui/test_app_reexports.py tests/sdk_ui/conftest.py
git commit -m "feat(App): re-export sdk_ui shim symbols + g_kRootWindow as App.TG*/App.ST*/App.g_*

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 1.12: Layer 2 smoke test — `MissionLib.CreateGameOverScreen`

**Files:**
- Create: `tests/sdk_ui/test_smoke_gameover.py`

This is the slice's verification target. It runs unmodified MissionLib code through the SDK finder and asserts: construction succeeds, no exceptions, click → handler.

- [ ] **Step 1: Inspect what MissionLib.CreateGameOverScreen needs**

Open [sdk/Build/scripts/MissionLib.py:1990-2034](../../../sdk/Build/scripts/MissionLib.py#L1990-L2034). The function uses:
- `App.TopWindow_GetTopWindow().AbortCutscene()` — need a stub
- `App.g_kLocalizationManager.Load(...)` — need a stub (returns object with `GetString(key) -> str`)
- `App.STStylizedWindow_Create` — present
- `App.TGPane_Create` — present
- `App.TGParagraph_CreateW` — present
- `App.TGEvent_Create` — present
- `App.STButton_CreateW` + `App.STBSF_SIZE_TO_TEXT` — present
- `App.ET_LOAD_GAME`, `App.ET_CANCEL`, `App.ET_NEW_GAME` — present
- `App.g_kEventManager.AddBroadcastPythonFuncHandler` — present
- `pCinematic.AddChild(...)`, `MoveToFront(...)`, `SetFocus(...)` — TGUIObject methods we have
- `App.g_kUtopiaModule.Pause(1)` — need a stub

So we need stubs for: `TopWindow_GetTopWindow`, `g_kLocalizationManager`, `g_kUtopiaModule`. They can be no-op fakes installed only for this test.

- [ ] **Step 2: Write the smoke test**

```python
"""Layer 2 smoke test: MissionLib.CreateGameOverScreen runs unmodified.

This is the Slice 1 verification target. It loads MissionLib via the
project-root SDK shim and exercises the GameOverScreen construction +
button-click path end-to-end. Uses the FakeNativeBackend (autouse fixture
in conftest) so no native UI is required.
"""
from __future__ import annotations
import sys
import types

import pytest

import App
from engine.sdk_ui import _backend


@pytest.fixture
def stub_app_globals(monkeypatch):
    """Install minimal stubs for App globals that MissionLib uses but the
    shim doesn't yet implement (TopWindow, localization, utopia module).
    """
    # TopWindow_GetTopWindow → returns an object with AbortCutscene + AddChild.
    class _FakeTopWin:
        def AbortCutscene(self): pass
        def AddChild(self, *a, **kw): pass
        def MoveToFront(self, *a, **kw): pass
        def SetFocus(self, *a, **kw): pass
        def GetWidth(self): return 1.0
        def GetHeight(self): return 1.0
    monkeypatch.setattr(App, "TopWindow_GetTopWindow", lambda: _FakeTopWin(), raising=False)

    # g_kLocalizationManager.Load(path) -> obj.GetString(key) -> str.
    class _FakeStringDb:
        def GetString(self, key): return key
    class _FakeLocMgr:
        def Load(self, path): return _FakeStringDb()
    monkeypatch.setattr(App, "g_kLocalizationManager", _FakeLocMgr(), raising=False)

    # g_kUtopiaModule.Pause(int) — no-op.
    class _FakeUtopia:
        def Pause(self, *a, **kw): pass
    monkeypatch.setattr(App, "g_kUtopiaModule", _FakeUtopia(), raising=False)


def test_game_over_screen_constructs(stub_app_globals):
    """The big claim: unmodified MissionLib code runs through the shim."""
    # Load MissionLib via the SDK finder (tests/conftest.py wires it).
    import MissionLib
    # CreateGameOverScreen takes a cinematic-pane argument in the SDK; we
    # provide a TGPane to stand in for it.
    pCinematic = App.TGPane_Create(1.0, 1.0)
    # Must not raise.
    MissionLib.CreateGameOverScreen(pCinematic)


def test_restart_button_dispatches_to_restart_game(stub_app_globals, monkeypatch):
    """Clicking the Restart button should invoke MissionLib.RestartGame."""
    import MissionLib
    fired = []
    original = getattr(MissionLib, "RestartGame", None)
    monkeypatch.setattr(MissionLib, "RestartGame",
                        lambda event: fired.append("restart"))

    pCinematic = App.TGPane_Create(1.0, 1.0)
    MissionLib.CreateGameOverScreen(pCinematic)

    # Find the button in the fake backend by its label text.
    backend = _backend.get()
    restart_eid = None
    for eid, e in backend.elements.items():
        if e.text == "Restart" and "bc-stbutton" in e.cls:
            restart_eid = eid
            break
    assert restart_eid is not None, "Restart button not found in element tree"
    backend.fire_click(restart_eid)
    assert fired == ["restart"]
```

- [ ] **Step 3: Run the smoke test**

Run: `uv run pytest tests/sdk_ui/test_smoke_gameover.py -v`

Expected outcome — one of:
- PASS (great, slice done).
- FAIL with `AttributeError: module 'App' has no attribute 'X'` — that names the next surface we need. Triage each: add a stub in `stub_app_globals`, or extend the shim, or extend `App.py` re-exports.

The very first run is likely to FAIL the first time with at least one missing surface. Iterate: identify the missing piece, add the smallest shim or stub needed, re-run. Repeat until both tests pass.

Common likely follow-ons (add as discovered):
- `App.g_kUtopiaModule.Pause` already stubbed.
- MissionLib may reference `App.TGSequence_Create` or similar timeline primitives — these are NOT in scope. If reached, stub them at the App-module level with no-op `lambda *a, **kw: types.SimpleNamespace(AddAction=lambda *a, **kw: None, Play=lambda *a, **kw: None)` for the duration of the test.

- [ ] **Step 4: Commit**

```bash
git add tests/sdk_ui/test_smoke_gameover.py
git commit -m "test(sdk_ui): smoke MissionLib.CreateGameOverScreen end-to-end

Layer 2 smoke: unmodified MissionLib runs through the shim, GameOverScreen
constructs, Restart click dispatches to MissionLib.RestartGame.

Slice 1 verification target met.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 1.13: Add `sdk_ui.rcss` skeleton + load into panel

**Files:**
- Create: `native/assets/ui/sdk_ui.rcss`
- Modify: `native/assets/ui/panel.rml` (add the new stylesheet link)

- [ ] **Step 1: Create `native/assets/ui/sdk_ui.rcss`** with skeleton rules

```css
/* sdk_ui.rcss — styling for the SDK UI shim widgets.
   Theme colours live in :root CSS vars (set by engine/sdk_ui/theme.py in
   Slice 3). Initial values are placeholders; the visual polish pass in
   Slice 5 tunes them.
*/

@spritesheet sdk-ui-noop {
    src: "ui/blank.png";
    /* No actual sprites yet — chrome is rendered via CSS in Slice 5. */
}

:root {
    --bc-main-background: rgb(20, 24, 36);
    --bc-main-border: rgb(120, 160, 220);
    --bc-main-text: rgb(220, 230, 245);
    --bc-disabled-text: rgb(120, 120, 120);
    --bc-affiliation-federation: rgb(100, 160, 240);
    --bc-affiliation-klingon: rgb(220, 80, 80);
    --bc-affiliation-romulan: rgb(120, 220, 120);
}

.bc-sdk-staging { display: none; }
.bc-sdk-active { position: absolute; width: 100%; height: 100%; }

.bc-tgpane { position: absolute; }

.bc-tgparagraph {
    color: var(--bc-main-text);
    font-family: sans-serif;
    font-size: 14dp;
}

.bc-stbutton {
    color: var(--bc-main-text);
    background-color: var(--bc-main-background);
    border: 1dp var(--bc-main-border);
    padding: 4dp 12dp;
    cursor: pointer;
}

.bc-stbutton:hover { background-color: var(--bc-main-border); color: var(--bc-main-background); }
.bc-stbutton.bc-disabled { color: var(--bc-disabled-text); cursor: arrow; }

.bc-ststylizedwindow {
    position: absolute;
    background-color: var(--bc-main-background);
    border: 1dp var(--bc-main-border);
    padding: 8dp;
}

.bc-stsubpane {
    position: relative;
}

.bc-tgicon {
    /* Stub — Slice 3 wires real visuals through icon_classmap.py. */
}
```

- [ ] **Step 2: Update `native/assets/ui/panel.rml` to load it**

```xml
<rml>
<head>
    <title>Panel</title>
    <link type="text/rcss" href="components.rcss"/>
    <link type="text/rcss" href="sdk_ui.rcss"/>
</head>
<body>
    <div id="root" class="bc-panel"></div>
</body>
</rml>
```

- [ ] **Step 3: Build and verify**

Run: `cmake --build build -j && uv run pytest tests/sdk_ui/ -v`
Expected: build succeeds, all tests still pass.

- [ ] **Step 4: Commit**

```bash
git add native/assets/ui/sdk_ui.rcss native/assets/ui/panel.rml
git commit -m "feat(assets/ui): sdk_ui.rcss skeleton + load from panel.rml

Establishes the theme-var contract and minimal styling for shim widgets.
Visual polish lands in Slice 5.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 1.14: Slice 1 wrap — full suite + manual smoke

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest -v`
Expected: all existing tests pass plus the new `tests/sdk_ui/` suite.

- [ ] **Step 2: Verify nothing else regressed**

Run: `uv run pytest tests/integration -v` (slow; allow time)
Expected: integration tests pass.

- [ ] **Step 3: Manual sanity check — does the engine still boot?**

Run: `./build/dauntless` (Ctrl-C to exit after a few seconds)
Expected: window appears, default mission loads, no crash on startup. (We haven't ported `engine/ui/` callers yet — that's Slice 2 — so the existing UI panels still appear unchanged.)

- [ ] **Step 4: Commit any final adjustments**

If anything required fixes during Step 1-3, commit them with a brief message. Otherwise no action.

**End of Slice 1.** The SDK shim is operational for the GameOverScreen path. Subsequent slices broaden coverage to bridge menus and replace the old `engine/ui/` infrastructure.

---

## Slice 2 — Delete `engine/ui/`, Port Internal Callers

**Done when:** `engine/ui/` is gone, mission-picker and target-list controller work via the SDK shim, all existing tests pass.

### Task 2.1: Inventory callers of `engine/ui/`

Audit the codebase for everything that imports from `engine.ui`.

- [ ] **Step 1: Find every caller**

Run: `git grep -nE "from engine\.ui|import engine\.ui" -- 'engine/**' 'tests/**'`
Expected: a list of files. Common candidates: `engine/host_loop.py`, `engine/mission_picker.py`, possibly `engine/audio/*` or `engine/ui/__init__.py` itself.

- [ ] **Step 2: Categorise each import site**

For each file, note which `engine.ui` symbols it uses (`UiPanel`, `UiButton`, `UiCollapsibleList`, `UiStatRow`, `target_list.TargetListController`, etc.). The pattern translation is:

| Old (`engine.ui`) | New (`engine.sdk_ui` via `App.*`) |
|---|---|
| `UiPanel(id, anchor, vw, vh)` | `App.TGPane_Create(vw/100, vh/100)` placed at anchor via `AddChild` to a parent at corner |
| `panel.collapsible(label, affiliation)` | `App.STStylizedWindow_CreateW(name, "RightBorder", label, w, h)` |
| `panel.button(label, on_click=...)` | `App.STButton_CreateW(label, event, App.STBSF_SIZE_TO_TEXT)` + event handler registration on the parent |
| `UiButton(...)` | `App.STButton_CreateW(...)` |
| `UiStatRow(label, value)` | `App.TGParagraph_CreateW(f"{label}: {value}", w)` |
| `target_list.TargetListController(panel)` | Same controller class, moved to `engine/sdk_ui/target_list.py` (Slice 5 polishes; Slice 2 just migrates) |

- [ ] **Step 3: Commit the inventory as a note** (optional)

```bash
echo "$(uv run git grep -nE 'from engine\.ui|import engine\.ui')" > /tmp/ui_callers.txt
# Keep /tmp/ui_callers.txt as a working note; don't commit it.
```

### Task 2.2: Port `engine/host_loop.py` UI setup

The host loop currently constructs `UiPanel`s and populates them with demo content. Port to SDK shim API.

**Files:**
- Modify: `engine/host_loop.py`

- [ ] **Step 1: Identify the UI construction block**

Open [engine/host_loop.py:824-854](../../../engine/host_loop.py#L824-L854) per the target-list-from-scene spec; this is where the demo target list lives. There may be other UI construction blocks — check the full file.

- [ ] **Step 2: Replace UiPanel construction with SDK shim**

Before:
```python
from engine.ui import UiPanel, UiCollapsibleList, UiButton
targets_panel = UiPanel("targets", anchor="top-right", width_vw=20, height_vh=60)
list_a = targets_panel.collapsible("Bird of Prey-1", affiliation="enemy")
list_a.button("Shield Gen", on_click=lambda: ...)
```

After:
```python
import App
targets_root = App.TGPane_Create(0.20, 0.60)  # 20% × 60% of viewport
# Use anchor by adding to a positioned container or setting style directly:
from engine.sdk_ui import _backend
_backend.get().set_element_property(targets_root._element_id, "position", "absolute")
_backend.get().set_element_property(targets_root._element_id, "right", "0%")
_backend.get().set_element_property(targets_root._element_id, "top", "0%")

# Collapsible list = STStylizedWindow with template that produces a list look.
list_a = App.STStylizedWindow_CreateW("BirdOfPrey1", "ListItem", "Bird of Prey-1", 0.20, 0.05)
targets_root.AddChild(list_a)

# Button with event template that dispatches a target-selected event.
shield_event = App.TGEvent_Create()
shield_event.SetDestination(list_a)
shield_event.SetEventType(App.ET_TARGET_SELECTED)
btn = App.STButton_CreateW("Shield Gen", shield_event, App.STBSF_SIZE_TO_TEXT)
list_a.AddChild(btn, 0.0, 0.0)
```

This is verbose because we now own the construction explicitly. In Slice 4 once `STTopLevelMenu_CreateW` lands the SDK code itself is cleaner, but the demo/placeholder content in host_loop is being replaced by the real target-list controller in Slice 5 anyway.

For Slice 2's purposes: **remove the entire demo UI construction in host_loop and replace with a single comment**: `# UI populated by mission scripts via SDK shim — no host-side demo content.` This is cleaner than porting placeholder content that's about to be replaced.

- [ ] **Step 3: Find and update any other engine.ui imports in host_loop**

Search: `grep -n "engine.ui\|UiPanel\|UiButton\|UiCollapsibleList\|UiStatRow" engine/host_loop.py`
Remove every reference.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/ -v`
Expected: existing host-loop and integration tests still pass.

- [ ] **Step 5: Boot the engine**

Run: `./build/dauntless`
Expected: starts cleanly. No top-left/top-right panels visible (we removed the demo). The target list reappears in Slice 5.

- [ ] **Step 6: Commit**

```bash
git add engine/host_loop.py
git commit -m "refactor(host_loop): remove demo UI; UI now flows via SDK shim from missions

Demo UiPanel construction removed. Target list reappears in Slice 5 via
the engine-owned target-list element + ship_lifecycle controller.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

### Task 2.3: Port `engine/mission_picker.py`

The mission picker currently uses `UiPanel`/`UiButton` for the mission list.

**Files:**
- Modify: `engine/mission_picker.py`
- Modify: `tests/test_mission_picker.py` (assertions update)

- [ ] **Step 1: Inspect current implementation**

Run: `grep -n "engine.ui\|UiPanel\|UiButton" engine/mission_picker.py`
Note the pattern: probably a `MissionPicker` class that builds a panel of buttons.

- [ ] **Step 2: Replace with SDK shim equivalents**

Pattern:
```python
# Before
from engine.ui import UiPanel, UiButton
self._panel = UiPanel("missions", anchor="center", width_vw=40, height_vh=70)
for m in missions:
    UiButton(self._panel.root_element, m.label, menu_level="header", on_click=lambda m=m: self._select(m))

# After
import App
self._panel = App.TGPane_Create(0.40, 0.70)
# Center via inline style:
from engine.sdk_ui import _backend
b = _backend.get()
b.set_element_property(self._panel._element_id, "position", "absolute")
b.set_element_property(self._panel._element_id, "left", "30%")
b.set_element_property(self._panel._element_id, "top", "15%")
for i, m in enumerate(missions):
    ev = App.TGEvent_Create()
    ev.SetDestination(self._panel)
    ev.SetEventType(App.ET_BUTTON_CLICKED)
    ev.SetPayload(m)
    btn = App.STButton_CreateW(m.label, ev, App.STBSF_SIZE_TO_TEXT)
    self._panel.AddChild(btn, 0.0, i * 0.05)
# Register one handler for all button clicks; payload identifies which.
self._panel.AddPythonFuncHandlerForInstance(
    App.ET_BUTTON_CLICKED, f"{__name__}._on_mission_picked")
```

Add a module-level handler:
```python
def _on_mission_picked(event):
    mission = event.GetPayload()
    # ... whatever the old _select did
```

- [ ] **Step 3: Update tests**

Open `tests/test_mission_picker.py`. Assertions that introspect `UiButton` attributes need replacement. Use the FakeNativeBackend to read element text and click via `fake.fire_click(eid)`.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_mission_picker.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/mission_picker.py tests/test_mission_picker.py
git commit -m "refactor(mission_picker): port off engine.ui to App.TG*/App.ST* shim

Mission list now built with TGPane + STButton, click events routed via
g_kEventManager with the mission as payload.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

### Task 2.4: Port `engine/ui/target_list.py` → `engine/sdk_ui/target_list.py` (Stage 1)

**Files:**
- Create: `engine/sdk_ui/target_list.py`
- Modify: `engine/host_loop.py` (wire the new controller)

- [ ] **Step 1: Read the existing target list spec**

[docs/superpowers/specs/2026-05-11-target-list-from-scene-design.md](../specs/2026-05-11-target-list-from-scene-design.md). The data flow (ship_lifecycle, mission swap, dead-ship cleanup) is unchanged; only the UI construction migrates.

- [ ] **Step 2: Create `engine/sdk_ui/target_list.py`**

Port the existing class from `engine/ui/target_list.py`. Where the old code calls `panel.collapsible(...)` or `row.button(...)`, replace with `App.STStylizedWindow_CreateW(...)` and `App.STButton_CreateW(...)` per the translation table in Task 2.1.

The engine-owned-element split lands in Slice 5; for Slice 2 the controller owns its own panel (a top-right TGPane sized for the list).

```python
"""TargetListController — ship-lifecycle-driven target list (Stage 1 only).

Subscribes to engine.appc.ship_lifecycle and mirrors live ships into rows.
Engine-owned-element refinement deferred to Slice 5.
"""
from __future__ import annotations
from typing import Optional

import App
from engine.appc import ship_lifecycle
from engine.sdk_ui import _backend


class TargetListController:
    def __init__(self, player):
        self._player = player
        # Top-right panel.
        self._panel = App.TGPane_Create(0.20, 0.60)
        b = _backend.get()
        b.set_element_property(self._panel._element_id, "position", "absolute")
        b.set_element_property(self._panel._element_id, "right", "0%")
        b.set_element_property(self._panel._element_id, "top", "0%")
        # Subscribe.
        self._unsubscribe = ship_lifecycle.subscribe(self._on_event)
        self._rows: dict = {}  # ship -> row widget
        # Seed from current snapshot.
        for ship in ship_lifecycle.live_snapshot():
            self._add_row(ship)

    def _on_event(self, kind: str, ship) -> None:
        if kind == "added":
            self._add_row(ship)
        elif kind == "destroyed":
            self._remove_row(ship)

    def _add_row(self, ship) -> None:
        if ship is self._player:
            return
        affiliation = "enemy"  # Determine from mission group; placeholder.
        label = ship.GetName() if hasattr(ship, "GetName") else "Unknown"
        row = App.STStylizedWindow_CreateW(label, "ListItem", label, 0.20, 0.05)
        # Event dispatched on row click.
        ev = App.TGEvent_Create()
        ev.SetDestination(row)
        ev.SetEventType(App.ET_TARGET_SELECTED)
        ev.SetPayload(ship)
        # Whole row clickable as a button:
        btn = App.STButton_CreateW(label, ev, App.STBSF_SIZE_TO_TEXT)
        row.AddChild(btn, 0.0, 0.0)
        self._panel.AddChild(row, 0.0, len(self._rows) * 0.05)
        row.AddPythonFuncHandlerForInstance(
            App.ET_TARGET_SELECTED, f"{__name__}._on_target_selected")
        self._rows[ship] = row

    def _remove_row(self, ship) -> None:
        row = self._rows.pop(ship, None)
        if row is None:
            return
        self._panel.RemoveChild(row)

    def teardown(self) -> None:
        if self._unsubscribe:
            self._unsubscribe()
            self._unsubscribe = None
        for row in list(self._rows.values()):
            self._panel.RemoveChild(row)
        self._rows.clear()


def _on_target_selected(event) -> None:
    """Module-level handler invoked by g_kEventManager.

    Sets the controller's player target. We look up the controller via a
    module-level reference set by the host loop in Slice 2 Task 2.5.
    """
    ship = event.GetPayload()
    controller = _active_controller()
    if controller is not None:
        controller._player.SetTarget(ship)


_controller_ref: Optional[TargetListController] = None


def _active_controller() -> Optional[TargetListController]:
    return _controller_ref


def set_active_controller(c: Optional[TargetListController]) -> None:
    global _controller_ref
    _controller_ref = c
```

- [ ] **Step 3: Wire into host_loop**

In `engine/host_loop.py`, after the player ship is created, instantiate the controller:

```python
from engine.sdk_ui import target_list as _target_list
target_list_controller = _target_list.TargetListController(player)
_target_list.set_active_controller(target_list_controller)
```

On mission swap teardown:
```python
target_list_controller.teardown()
_target_list.set_active_controller(None)
target_list_controller = _target_list.TargetListController(new_player)
_target_list.set_active_controller(target_list_controller)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/ -v`
Expected: PASS.

- [ ] **Step 5: Boot the engine**

Run: `./build/dauntless`
Expected: the top-right target list appears with rows for friendly/enemy Galaxies. Clicking a row should target that ship (verifiable via existing in-game indicators).

- [ ] **Step 6: Commit**

```bash
git add engine/sdk_ui/target_list.py engine/host_loop.py
git commit -m "feat(sdk_ui): port TargetListController to SDK shim (Stage 1)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

### Task 2.5: Delete `engine/ui/`

- [ ] **Step 1: Verify no more callers**

Run: `git grep -nE "from engine\.ui|import engine\.ui" -- 'engine/**' 'tests/**'`
Expected: no output (or only `engine/sdk_ui/...` if I named anything badly).

If any callers remain, port them before proceeding.

- [ ] **Step 2: Delete the directory**

Run: `git rm -r engine/ui/`

- [ ] **Step 3: Run the full test suite**

Run: `uv run pytest tests/ -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git commit -m "refactor: remove engine/ui/ — superseded by engine/sdk_ui/

All callers ported to App.TG*/App.ST* surface.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

**End of Slice 2.**

---

## Slice 3 — Icon Manager + Theme System

**Done when:** runtime theme switching propagates through CSS vars, `TGIcon_Create` renders as decorative spans with `(group, index)` CSS classes, `STStylizedWindow` frame children flow through without errors.

### Task 3.1: Icon manager + `TGIconGroup`

**Files:**
- Create: `engine/sdk_ui/icons.py`
- Create: `tests/sdk_ui/test_icons.py`

- [ ] **Step 1: Write the failing test**

`tests/sdk_ui/test_icons.py`:

```python
import App
from engine.sdk_ui import _backend
from engine.sdk_ui.icons import TGIconGroup


def test_icon_manager_create_group():
    g = App.g_kIconManager.CreateIconGroup("NormalStyleFrame")
    App.g_kIconManager.AddIconGroup(g)
    assert App.g_kIconManager.get_group("NormalStyleFrame") is g


def test_load_icon_texture_returns_handle():
    g = App.g_kIconManager.CreateIconGroup("MyGroup")
    t = g.LoadIconTexture("data/Icons/Bridge/NormalStyleFrame.tga")
    # Returns a handle (string or int) the group remembers.
    assert t is not None
    assert g._last_texture is t


def test_set_icon_location_stores_metadata():
    g = App.g_kIconManager.CreateIconGroup("MyGroup")
    t = g.LoadIconTexture("data/Icons/Bridge/NormalStyleFrame.tga")
    g.SetIconLocation(0, t, 0, 0, 12, 22)
    g.SetIconLocation(43, t, 0, 0, 12, 22,
                      TGIconGroup.ROTATE_0, TGIconGroup.MIRROR_HORIZONTAL)
    assert g.location(0) == (t, 0, 0, 12, 22, 0, 0)
    assert g.location(43) == (t, 0, 0, 12, 22, 0, TGIconGroup.MIRROR_HORIZONTAL)


def test_tgicon_create_applies_class_and_transform():
    g = App.g_kIconManager.CreateIconGroup("NormalStyleFrame")
    App.g_kIconManager.AddIconGroup(g)
    t = g.LoadIconTexture("data/Icons/Bridge/NormalStyleFrame.tga")
    g.SetIconLocation(0, t, 0, 0, 12, 22)
    g.SetIconLocation(43, t, 0, 0, 12, 22,
                      TGIconGroup.ROTATE_0, TGIconGroup.MIRROR_HORIZONTAL)

    icon0 = App.TGIcon_Create("NormalStyleFrame", 0)
    icon43 = App.TGIcon_Create("NormalStyleFrame", 43)

    e0 = _backend.get().elements[icon0._element_id]
    e43 = _backend.get().elements[icon43._element_id]
    assert "bc-tgicon-NormalStyleFrame-0" in e0.cls
    assert "bc-tgicon-NormalStyleFrame-43" in e43.cls
    # Index 43 has MIRROR_HORIZONTAL → transform scaleX(-1).
    assert "scaleX(-1)" in e43.properties.get("transform", "")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/sdk_ui/test_icons.py -v`
Expected: FAIL with import errors.

- [ ] **Step 3: Create `engine/sdk_ui/icons.py`**

```python
"""Icon manager — accepts SDK sprite metadata, renders as CSS classes.

SDK code calls (see sdk/Build/scripts/StylizedWindow.py:62-106):
    pGroup = App.g_kIconManager.CreateIconGroup("NormalStyleFrame")
    App.g_kIconManager.AddIconGroup(pGroup)
    pTexture = pGroup.LoadIconTexture("Data/Icons/Bridge/NormalStyleFrame.tga")
    pGroup.SetIconLocation(0, pTexture, 0, 0, 12, 22)
    ...

Then TGIcon_Create(group, index) emits a decorative span with:
    class="bc-tgicon bc-tgicon-<group>-<index>"
    style="transform: rotate(Ndeg) scaleX(-1)"  // if rotation/mirror specified

The actual sprite blit is NOT performed — Slice 5 visual polish styles the
spans via CSS rules per (group, index). This matches the spec's modernised
rendering target.
"""
from __future__ import annotations
from typing import Optional


class TGIconGroup:
    """Group of named icon sub-rects sharing one source texture."""
    # Rotation enum.
    ROTATE_0   = 0
    ROTATE_90  = 1
    ROTATE_180 = 2
    ROTATE_270 = 3

    # Mirror flags.
    MIRROR_NONE       = 0
    MIRROR_HORIZONTAL = 1
    MIRROR_VERTICAL   = 2

    def __init__(self, name: str) -> None:
        self.name = name
        self._last_texture: Optional[str] = None
        # index -> (texture, x, y, w, h, rotation, mirror)
        self._locations: dict[int, tuple] = {}

    def LoadIconTexture(self, path: str) -> str:
        """Return an opaque texture handle (the path itself for now)."""
        self._last_texture = path
        return path

    def SetIconLocation(
        self,
        index: int,
        texture: str,
        x: int, y: int, w: int, h: int,
        rotation: int = 0,
        mirror: int = 0,
    ) -> None:
        self._locations[index] = (texture, x, y, w, h, rotation, mirror)

    def location(self, index: int) -> Optional[tuple]:
        return self._locations.get(index)


class _IconManager:
    def __init__(self) -> None:
        self._groups: dict[str, TGIconGroup] = {}

    def CreateIconGroup(self, name: str) -> TGIconGroup:
        g = TGIconGroup(name)
        # Note: SDK has a separate AddIconGroup step. We don't auto-add here.
        return g

    def AddIconGroup(self, group: TGIconGroup) -> None:
        self._groups[group.name] = group

    def get_group(self, name: str) -> Optional[TGIconGroup]:
        return self._groups.get(name)


g_kIconManager = _IconManager()


# ── Real TGIcon_Create (replaces the stub in primitives.py) ─────────────
def TGIcon_Create(group_name: str, index: int, color=None) -> "TGUIObject":
    from engine.sdk_ui import _backend
    from engine.sdk_ui.base import TGUIObject

    cls = f"bc-tgicon bc-tgicon-{group_name}-{index}"
    icon = TGUIObject(css_class=cls)
    g = g_kIconManager.get_group(group_name)
    if g is not None:
        loc = g.location(index)
        if loc is not None:
            _texture, _x, _y, _w, _h, rotation, mirror = loc
            transforms = []
            if rotation == TGIconGroup.ROTATE_90:
                transforms.append("rotate(90deg)")
            elif rotation == TGIconGroup.ROTATE_180:
                transforms.append("rotate(180deg)")
            elif rotation == TGIconGroup.ROTATE_270:
                transforms.append("rotate(270deg)")
            if mirror == TGIconGroup.MIRROR_HORIZONTAL:
                transforms.append("scaleX(-1)")
            elif mirror == TGIconGroup.MIRROR_VERTICAL:
                transforms.append("scaleY(-1)")
            if transforms:
                _backend.get().set_element_property(
                    icon._element_id, "transform", " ".join(transforms))
    if color is not None:
        # Color may be a NiColorA-like with r/g/b in [0,1]. Best-effort.
        try:
            r = int(color.r * 255); g_c = int(color.g * 255); b = int(color.b * 255)
            _backend.get().set_element_property(
                icon._element_id, "color", f"rgb({r},{g_c},{b})")
        except AttributeError:
            pass
    return icon
```

- [ ] **Step 4: Update `App.py` re-exports**

In `App.py`, add:
```python
from engine.sdk_ui.icons import g_kIconManager, TGIconGroup
# Override the stub TGIcon_Create from primitives with the real one:
from engine.sdk_ui.icons import TGIcon_Create  # noqa: F811
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/sdk_ui/test_icons.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add engine/sdk_ui/icons.py App.py tests/sdk_ui/test_icons.py
git commit -m "feat(sdk_ui): icon manager + TGIconGroup + decorative-span TGIcon_Create

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

### Task 3.2: `icon_classmap.py` — friendly class names

**Files:**
- Create: `engine/sdk_ui/icon_classmap.py`
- Modify: `engine/sdk_ui/icons.py` (use the map)
- Modify: `native/assets/ui/sdk_ui.rcss` (initial decorative classes)

- [ ] **Step 1: Create `engine/sdk_ui/icon_classmap.py`**

```python
"""(icon-group, index) -> friendly CSS class fragment.

Names lifted from comments in sdk/Build/scripts/StylizedWindow.py. The
friendly name is used as an extra CSS class on TGIcon elements so the
stylesheet can target them with semantic selectors instead of raw integers.

Example: TGIcon_Create("NormalStyleFrame", 0) becomes
    class="bc-tgicon bc-tgicon-NormalStyleFrame-0 bc-frame-tl-curve"
"""
from __future__ import annotations

_MAP: dict[tuple[str, int], str] = {
    ("NormalStyleFrame", 0):  "bc-frame-tl-curve",
    ("NormalStyleFrame", 1):  "bc-frame-left-side",
    ("NormalStyleFrame", 2):  "bc-frame-bl-curve",
    ("NormalStyleFrame", 3):  "bc-frame-bottom-line",
    ("NormalStyleFrame", 4):  "bc-frame-bottom-line-rightcap",
    ("NormalStyleFrame", 5):  "bc-frame-titlebar",
    ("NormalStyleFrame", 6):  "bc-frame-titlebar-pre-rightcap",
    ("NormalStyleFrame", 7):  "bc-frame-titlebar-post-leftcap",
    ("NormalStyleFrame", 8):  "bc-frame-titlebar-post-rightcap",
    ("NormalStyleFrame", 9):  "bc-frame-minimize-pressed",
    ("NormalStyleFrame", 10): "bc-frame-minimize",
    ("NormalStyleFrame", 11): "bc-frame-minimize-disabled",
    ("NormalStyleFrame", 12): "bc-frame-restore-pressed",
    ("NormalStyleFrame", 13): "bc-frame-restore",
    ("NormalStyleFrame", 14): "bc-frame-restore-disabled",
    ("NormalStyleFrame", 15): "bc-frame-scrollup-pressed",
    ("NormalStyleFrame", 16): "bc-frame-scrollup",
    ("NormalStyleFrame", 17): "bc-frame-scrollup-disabled",
    ("NormalStyleFrame", 18): "bc-frame-scrolldown-pressed",
    ("NormalStyleFrame", 19): "bc-frame-scrolldown",
    ("NormalStyleFrame", 20): "bc-frame-scrolldown-disabled",
    ("NormalStyleFrame", 21): "bc-frame-pre-button-spacing",
    ("NormalStyleFrame", 22): "bc-frame-minimized-leftcap",
    ("NormalStyleFrame", 23): "bc-frame-under-titlebar-spacing",
    ("NormalStyleFrame", 30): "bc-frame-thin-sep-top",
    ("NormalStyleFrame", 31): "bc-frame-thin-sep",
    ("NormalStyleFrame", 32): "bc-frame-thin-sep-bottom",
    ("NormalStyleFrame", 40): "bc-frame-bl-scroll",
    ("NormalStyleFrame", 41): "bc-frame-bottom-scroll",
    ("NormalStyleFrame", 42): "bc-frame-bottom-scroll-rightcap",
    ("NormalStyleFrame", 43): "bc-frame-tr-curve",
    ("NormalStyleFrame", 44): "bc-frame-right-side",
}


def friendly_class(group: str, index: int) -> str:
    """Return the friendly class name, or empty string if unmapped."""
    return _MAP.get((group, index), "")
```

- [ ] **Step 2: Update `engine/sdk_ui/icons.py` to apply the friendly class**

In `TGIcon_Create`, change the `cls = ...` line to:

```python
from engine.sdk_ui.icon_classmap import friendly_class
friendly = friendly_class(group_name, index)
cls = f"bc-tgicon bc-tgicon-{group_name}-{index}"
if friendly:
    cls = f"{cls} {friendly}"
```

- [ ] **Step 3: Add minimal decorative rules to `sdk_ui.rcss`**

Append to `native/assets/ui/sdk_ui.rcss`:

```css
/* LCARS-inspired frame decoration. Slice 5 polishes these. */
.bc-frame-tl-curve { border-radius: 12dp 0 0 0; background-color: var(--bc-main-border); width: 12dp; height: 22dp; }
.bc-frame-tr-curve { border-radius: 0 12dp 0 0; background-color: var(--bc-main-border); width: 12dp; height: 22dp; }
.bc-frame-bl-curve { border-radius: 0 0 0 12dp; background-color: var(--bc-main-border); width: 12dp; height: 11dp; }
.bc-frame-left-side, .bc-frame-right-side { background-color: var(--bc-main-border); width: 4dp; }
.bc-frame-titlebar { background-color: var(--bc-main-border); height: 14dp; }
/* ... more as visual polish lands */
```

- [ ] **Step 4: Update test expectations**

Edit `tests/sdk_ui/test_icons.py::test_tgicon_create_applies_class_and_transform` to also assert:

```python
assert "bc-frame-tl-curve" in e0.cls
assert "bc-frame-tr-curve" in e43.cls
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/sdk_ui/test_icons.py -v && cmake --build build -j`
Expected: PASS + build success.

- [ ] **Step 6: Commit**

```bash
git add engine/sdk_ui/icon_classmap.py engine/sdk_ui/icons.py native/assets/ui/sdk_ui.rcss tests/sdk_ui/test_icons.py
git commit -m "feat(sdk_ui): icon classmap + initial decorative frame styles

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

### Task 3.3: Theme system

**Files:**
- Create: `engine/sdk_ui/theme.py`
- Create: `tests/sdk_ui/test_theme.py`
- Modify: `App.py` (re-export)
- Modify: `engine/sdk_ui/_fake_backend.py` (track set_panel_css_var calls)

- [ ] **Step 1: Write the failing test**

`tests/sdk_ui/test_theme.py`:

```python
import App
from engine.sdk_ui import _backend


def test_tguitheme_create_returns_singleton():
    t1 = App.TGUITheme_Create()
    t2 = App.TGUITheme_Create()
    # Per spec: repeat calls REPLACE the active theme; they're not the same.
    assert t1 is not t2


def test_set_main_background_color_propagates_to_css_var(fake_backend):
    App.TGUITheme_Create()
    App.g_kInterface.SetMainBackgroundColor(0.1, 0.2, 0.3)
    # set_panel_css_var should have been called with the rgb value.
    calls = [c for c in fake_backend.calls if c[0] == "set_panel_css_var"]
    assert any(
        args[1] == "--bc-main-background" and "rgb(" in args[2]
        for _, args in calls
    )


def test_set_disabled_text_color_propagates(fake_backend):
    App.TGUITheme_Create()
    App.g_kInterface.SetDisabledTextColor(0.5, 0.5, 0.5)
    calls = [c for c in fake_backend.calls if c[0] == "set_panel_css_var"]
    assert any(args[1] == "--bc-disabled-text" for _, args in calls)
```

Add a `fake_backend` fixture alias in conftest:

```python
# In tests/sdk_ui/conftest.py, expose the autouse fixture by name too.
@pytest.fixture
def fake_backend(_sdk_ui_fake_backend):
    return _sdk_ui_fake_backend
```

- [ ] **Step 2: Create `engine/sdk_ui/theme.py`**

```python
"""Theme — global color slots flowing through panel CSS variables."""
from __future__ import annotations
from typing import Optional

from engine.sdk_ui import _backend, _panel


_SLOTS = {
    "main_background":        "--bc-main-background",
    "main_border":            "--bc-main-border",
    "main_text":              "--bc-main-text",
    "submenu_background":     "--bc-submenu-background",
    "submenu_border":         "--bc-submenu-border",
    "submenu_text":           "--bc-submenu-text",
    "disabled_text":          "--bc-disabled-text",
    "affiliation_federation": "--bc-affiliation-federation",
    "affiliation_klingon":    "--bc-affiliation-klingon",
    "affiliation_romulan":    "--bc-affiliation-romulan",
}


class TGUITheme:
    def __init__(self) -> None:
        self._values: dict[str, tuple[float, float, float]] = {}

    def set(self, slot: str, r: float, g: float, b: float) -> None:
        if slot not in _SLOTS:
            return
        self._values[slot] = (r, g, b)
        rgb = f"rgb({int(r * 255)}, {int(g * 255)}, {int(b * 255)})"
        _backend.get().set_panel_css_var(_panel.panel_id(), _SLOTS[slot], rgb)


_active_theme: Optional[TGUITheme] = None


def TGUITheme_Create() -> TGUITheme:
    """Create a new theme and make it active. SDK calls this once at startup."""
    global _active_theme
    _active_theme = TGUITheme()
    return _active_theme


class _Interface:
    """g_kInterface — public color setters used by LoadInterface.py."""

    def _set(self, slot: str, r: float, g: float, b: float) -> None:
        if _active_theme is None:
            return
        _active_theme.set(slot, r, g, b)

    def SetMainBackgroundColor(self, r, g, b): self._set("main_background", r, g, b)
    def SetMainBorderColor(self, r, g, b):     self._set("main_border", r, g, b)
    def SetMainTextColor(self, r, g, b):       self._set("main_text", r, g, b)
    def SetSubmenuBackgroundColor(self, r, g, b): self._set("submenu_background", r, g, b)
    def SetSubmenuBorderColor(self, r, g, b):     self._set("submenu_border", r, g, b)
    def SetSubmenuTextColor(self, r, g, b):       self._set("submenu_text", r, g, b)
    def SetDisabledTextColor(self, r, g, b):      self._set("disabled_text", r, g, b)


g_kInterface = _Interface()
```

- [ ] **Step 3: Re-export from `App.py`**

```python
from engine.sdk_ui.theme import TGUITheme_Create, g_kInterface
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/sdk_ui/test_theme.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/sdk_ui/theme.py App.py tests/sdk_ui/test_theme.py
git commit -m "feat(sdk_ui): TGUITheme + g_kInterface color setters propagating to CSS vars

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

### Task 3.4: Smoke test — `LoadInterface.py` runs

**Files:**
- Create: `tests/sdk_ui/test_smoke_loadinterface.py`

- [ ] **Step 1: Write the smoke test**

```python
"""LoadInterface.py is one of the early SDK scripts — exercises theme + icons."""
import App
from engine.sdk_ui import _backend


def test_loadinterface_runs(_sdk_ui_fake_backend):
    import LoadInterface
    LoadInterface.SetupColors()  # or whatever the entry point is — adjust on first run
    # Theme vars were set:
    calls = [c for c in _sdk_ui_fake_backend.calls if c[0] == "set_panel_css_var"]
    assert len(calls) > 0
```

- [ ] **Step 2: Run — fix AttributeErrors iteratively**

Run: `uv run pytest tests/sdk_ui/test_smoke_loadinterface.py -v`

Expect AttributeErrors for missing symbols. For each: implement the smallest stub needed, re-run. Continue until PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/sdk_ui/test_smoke_loadinterface.py
git commit -m "test(sdk_ui): smoke LoadInterface.SetupColors through theme system

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

**End of Slice 3.**

---

## Slice 4 — Menu Composites + Remaining Widgets

**Done when:** all six `Bridge/*MenuHandlers.py` (Data, Engineer, Helm, Science, Tactical, XO) construct without error and route clicks.

### Task 4.1: Remaining button variants

**Files:**
- Modify: `engine/sdk_ui/buttons.py` (add STRoundedButton, TGButton, TGTextButton, STToggle, STTiledIcon, STFillGauge, STWarpButton)

- [ ] **Step 1: Write the failing tests**

Add to `tests/sdk_ui/test_buttons.py`:

```python
def test_strounded_button_create(fake):
    import App
    ev = App.TGEvent_Create()
    btn = App.STRoundedButton_CreateW("Rounded", ev, 0)
    assert "bc-strounded-button" in fake.elements[btn._element_id].cls


def test_tgbutton_create(fake):
    import App
    ev = App.TGEvent_Create()
    btn = App.TGButton_Create("Plain", ev, 0)
    assert "bc-tgbutton" in fake.elements[btn._element_id].cls


def test_tgtextbutton_create(fake):
    import App
    btn = App.TGTextButton_Create("Text")
    assert "bc-tgtextbutton" in fake.elements[btn._element_id].cls
    assert fake.elements[btn._element_id].text == "Text"


def test_sttoggle_create(fake):
    import App
    t = App.STToggle_CreateW("Enable")
    assert "bc-sttoggle" in fake.elements[t._element_id].cls


def test_stfillgauge_create(fake):
    import App
    g = App.STFillGauge_Create()
    assert "bc-stfillgauge" in fake.elements[g._element_id].cls


def test_sttiled_icon_create(fake):
    import App
    g = App.g_kIconManager.CreateIconGroup("TestGroup")
    App.g_kIconManager.AddIconGroup(g)
    t = g.LoadIconTexture("dummy.tga")
    g.SetIconLocation(0, t, 0, 0, 8, 8)
    tile = App.STTiledIcon_Create("TestGroup", 0)
    assert "bc-sttiled-icon" in fake.elements[tile._element_id].cls


def test_stwarp_button_create(fake):
    import App
    ev = App.TGEvent_Create()
    btn = App.STWarpButton_CreateW("Warp", ev, 0)
    assert "bc-stwarp-button" in fake.elements[btn._element_id].cls
```

- [ ] **Step 2: Implement**

Add to `engine/sdk_ui/buttons.py` after the existing `_STButton`/`STButton_CreateW`:

```python
class _STRoundedButton(_STButton):
    def __init__(self, label, event_template, flags):
        super().__init__(label, event_template, flags)
        _backend.get().set_class(self._element_id, "bc-stbutton bc-strounded-button")


def STRoundedButton_Create(label, event=None, flags=0):
    return _STRoundedButton(label, event, flags)


def STRoundedButton_CreateW(label, event=None, flags=0):
    return _STRoundedButton(label, event, flags)


class _TGButton(_STButton):
    def __init__(self, label, event_template, flags):
        super().__init__(label, event_template, flags)
        _backend.get().set_class(self._element_id, "bc-tgbutton")


def TGButton_Create(label, event=None, flags=0):
    return _TGButton(label, event, flags)


class _TGTextButton(TGUIObject):
    def __init__(self, label):
        super().__init__(css_class="bc-tgtextbutton")
        _backend.get().set_text(self._element_id, label)


def TGTextButton_Create(label):
    return _TGTextButton(label)


def TGTextButton_CreateW(label):
    return _TGTextButton(label)


class _STToggle(TGUIObject):
    def __init__(self, label):
        super().__init__(css_class="bc-sttoggle")
        _backend.get().set_text(self._element_id, label)
        self._on = False
        _backend.get().on_click(self._element_id, self._toggle)

    def _toggle(self):
        self._on = not self._on
        b = _backend.get()
        cls = b.elements[self._element_id].cls if hasattr(b, "elements") else "bc-sttoggle"
        classes = set(cls.split())
        if self._on:
            classes.add("bc-on")
        else:
            classes.discard("bc-on")
        b.set_class(self._element_id, " ".join(sorted(classes)))


def STToggle_CreateW(label):
    return _STToggle(label)


class _STTiledIcon(TGUIObject):
    pass


def STTiledIcon_Create(group: str, index: int):
    return _STTiledIcon(css_class=f"bc-sttiled-icon bc-sttiled-{group}-{index}")


class _STFillGauge(TGUIObject):
    def __init__(self):
        super().__init__(css_class="bc-stfillgauge")
        self._fill = 0.0

    def SetFill(self, fraction: float):
        self._fill = max(0.0, min(1.0, float(fraction)))
        _backend.get().set_element_property(self._element_id, "--fill", f"{self._fill * 100.0}%")


def STFillGauge_Create():
    return _STFillGauge()


class _STWarpButton(_STButton):
    def __init__(self, label, event_template, flags):
        super().__init__(label, event_template, flags)
        _backend.get().set_class(self._element_id, "bc-stbutton bc-stwarp-button")


def STWarpButton_CreateW(label, event=None, flags=0):
    return _STWarpButton(label, event, flags)
```

- [ ] **Step 3: Re-export from `App.py`**

Add the new factory functions to the `App.py` import block.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/sdk_ui/test_buttons.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/sdk_ui/buttons.py App.py tests/sdk_ui/test_buttons.py
git commit -m "feat(sdk_ui): remaining button + widget variants (rounded, toggle, fill gauge, etc)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

### Task 4.2: `TGFrame_Create` and remaining stylized variants

**Files:**
- Modify: `engine/sdk_ui/primitives.py` (add TGFrame)
- Modify: `engine/sdk_ui/stylized.py` (real frame children handling)
- Modify: `App.py`

- [ ] **Step 1: Add tests**

In `tests/sdk_ui/test_primitives.py`:

```python
def test_tgframe_create(fake):
    import App
    f = App.TGFrame_Create()
    assert "bc-tgframe" in fake.elements[f._element_id].cls
```

- [ ] **Step 2: Implement TGFrame**

In `engine/sdk_ui/primitives.py`:

```python
class _TGFrame(TGUIObject):
    pass


def TGFrame_Create():
    return _TGFrame(css_class="bc-tgframe")
```

Re-export from `App.py`.

- [ ] **Step 3: Run tests and commit**

```bash
uv run pytest tests/sdk_ui/test_primitives.py -v
git add engine/sdk_ui/primitives.py App.py tests/sdk_ui/test_primitives.py
git commit -m "feat(sdk_ui): TGFrame_Create"
```

### Task 4.3: `STTopLevelMenu` + radio-group semantics

**Files:**
- Create: `engine/sdk_ui/menus.py`
- Create: `tests/sdk_ui/test_menus.py`

`STTopLevelMenu` is the main bridge menu container — vertical stack of buttons with radio-group selection (one selected at a time). SDK code AddChild's `STButton`s into it; the menu tracks which is selected and applies a `bc-selected` class.

- [ ] **Step 1: Write the failing test**

`tests/sdk_ui/test_menus.py`:

```python
import App
from engine.sdk_ui import _backend


def test_top_level_menu_create(_sdk_ui_fake_backend):
    m = App.STTopLevelMenu_CreateW("ScienceMenu")
    assert "bc-sttoplevel-menu" in _sdk_ui_fake_backend.elements[m._element_id].cls


def test_buttons_in_menu_are_radio_grouped(_sdk_ui_fake_backend):
    m = App.STTopLevelMenu_CreateW("ScienceMenu")
    e1 = App.TGEvent_Create(); e1.SetDestination(m)
    e2 = App.TGEvent_Create(); e2.SetDestination(m)
    b1 = App.STButton_CreateW("Scan", e1, App.STBSF_SIZE_TO_TEXT)
    b2 = App.STButton_CreateW("Probe", e2, App.STBSF_SIZE_TO_TEXT)
    m.AddChild(b1, 0.0, 0.0)
    m.AddChild(b2, 0.0, 0.05)

    # Click b1 → b1 has bc-selected, b2 doesn't.
    _sdk_ui_fake_backend.fire_click(b1._element_id)
    assert "bc-selected" in _sdk_ui_fake_backend.elements[b1._element_id].cls
    assert "bc-selected" not in _sdk_ui_fake_backend.elements[b2._element_id].cls

    # Click b2 → selection moves.
    _sdk_ui_fake_backend.fire_click(b2._element_id)
    assert "bc-selected" not in _sdk_ui_fake_backend.elements[b1._element_id].cls
    assert "bc-selected" in _sdk_ui_fake_backend.elements[b2._element_id].cls


def test_st_character_menu_create(_sdk_ui_fake_backend):
    m = App.STCharacterMenu_CreateW("Picard")
    assert "bc-stcharacter-menu" in _sdk_ui_fake_backend.elements[m._element_id].cls


def test_st_menu_create(_sdk_ui_fake_backend):
    m = App.STMenu_CreateW("Generic")
    assert "bc-stmenu" in _sdk_ui_fake_backend.elements[m._element_id].cls


def test_st_target_menu_create(_sdk_ui_fake_backend):
    m = App.STTargetMenu_CreateW("Target")
    assert "bc-sttarget-menu" in _sdk_ui_fake_backend.elements[m._element_id].cls
```

- [ ] **Step 2: Implement**

`engine/sdk_ui/menus.py`:

```python
"""Menu composites — radio-group selection of child buttons.

STTopLevelMenu is the bridge-menu container used by Bridge/*MenuHandlers.py.
Adds the bc-selected class to the most recently clicked child STButton
within the menu's subtree; clears it from siblings. The menu intercepts
button clicks by hooking AddChild — when a button is added, the menu
wraps its existing on_click to also drive the selection.
"""
from __future__ import annotations
from typing import Optional

from engine.sdk_ui import _backend
from engine.sdk_ui.base import TGUIObject
from engine.sdk_ui.buttons import _STButton


class _STTopLevelMenu(TGUIObject):
    def __init__(self, css_class: str, name: str) -> None:
        super().__init__(css_class=css_class)
        self._name = name
        self._selected: Optional[_STButton] = None

    def AddChild(self, child, x=0.0, y=0.0, z=0):
        super().AddChild(child, x, y, z)
        if isinstance(child, _STButton):
            # Wrap the existing click handler to drive radio-group selection.
            backend = _backend.get()
            original = child._on_click

            def wrapped():
                self._select(child)
                original()
            backend.on_click(child._element_id, wrapped)

    def _select(self, child: _STButton) -> None:
        backend = _backend.get()
        if self._selected is not None and self._selected is not child:
            self._strip_selected_class(self._selected)
        self._selected = child
        self._add_selected_class(child)

    def _add_selected_class(self, child: _STButton) -> None:
        b = _backend.get()
        cur = b.elements[child._element_id].cls if hasattr(b, "elements") else "bc-stbutton"
        classes = set(cur.split())
        classes.add("bc-selected")
        b.set_class(child._element_id, " ".join(sorted(classes)))

    def _strip_selected_class(self, child: _STButton) -> None:
        b = _backend.get()
        cur = b.elements[child._element_id].cls if hasattr(b, "elements") else "bc-stbutton"
        classes = set(cur.split())
        classes.discard("bc-selected")
        b.set_class(child._element_id, " ".join(sorted(classes)))


def STTopLevelMenu_CreateW(name: str):
    return _STTopLevelMenu("bc-sttoplevel-menu", name)


def STTopLevelMenu_CreateNull(name: str):
    return _STTopLevelMenu("bc-sttoplevel-menu bc-null", name)


class _STCharacterMenu(_STTopLevelMenu):
    pass


def STCharacterMenu_CreateW(name: str):
    return _STCharacterMenu("bc-stcharacter-menu bc-sttoplevel-menu", name)


class _STMenu(_STTopLevelMenu):
    pass


def STMenu_Create(name: str):
    return _STMenu("bc-stmenu", name)


def STMenu_CreateW(name: str):
    return _STMenu("bc-stmenu", name)


class _STTargetMenu(_STTopLevelMenu):
    pass


def STTargetMenu_CreateW(name: str):
    return _STTargetMenu("bc-sttarget-menu bc-sttoplevel-menu", name)
```

Re-export from `App.py`:

```python
from engine.sdk_ui.menus import (
    STTopLevelMenu_CreateW, STTopLevelMenu_CreateNull,
    STCharacterMenu_CreateW,
    STMenu_Create, STMenu_CreateW,
    STTargetMenu_CreateW,
)
```

- [ ] **Step 3: Run tests and commit**

```bash
uv run pytest tests/sdk_ui/test_menus.py -v
git add engine/sdk_ui/menus.py App.py tests/sdk_ui/test_menus.py
git commit -m "feat(sdk_ui): menu composites with radio-group selection"
```

### Task 4.4–4.9: Bridge handler smoke tests (one per crew role)

**Files:**
- Create: `tests/sdk_ui/test_smoke_bridge_data.py`
- Create: `tests/sdk_ui/test_smoke_bridge_engineer.py`
- Create: `tests/sdk_ui/test_smoke_bridge_helm.py`
- Create: `tests/sdk_ui/test_smoke_bridge_science.py`
- Create: `tests/sdk_ui/test_smoke_bridge_tactical.py`
- Create: `tests/sdk_ui/test_smoke_bridge_xo.py`

Each follows the same pattern as the GameOverScreen smoke test (Task 1.12): install minimal App-global stubs, import the handler module, call `CreateMenus()`, find a button by label, fire a click, verify it routes.

- [ ] **Steps per file (repeat for each crew role)**

Template (`test_smoke_bridge_science.py`):

```python
"""Smoke: Bridge/ScienceMenuHandlers.py constructs and dispatches."""
import sys, types
import pytest
import App
from engine.sdk_ui import _backend


@pytest.fixture
def stub_app_globals(monkeypatch):
    # Add stubs as AttributeErrors surface; this is the iterative-fix part.
    class _Tac:
        def AddChild(self, *a, **kw): pass
        def GetWidth(self): return 1.0
        def GetHeight(self): return 1.0
        def MoveToFront(self, *a, **kw): pass
        def SetFocus(self, *a, **kw): pass
    class _TopWin:
        def GetTacticalControlWindow(self): return _Tac()
        def AddChild(self, *a, **kw): pass
        def GetWidth(self): return 1.0
        def GetHeight(self): return 1.0
    monkeypatch.setattr(App, "TopWindow_GetTopWindow", lambda: _TopWin(), raising=False)
    monkeypatch.setattr(App, "TacticalControlWindow_GetTacticalControlWindow",
                        lambda: _Tac(), raising=False)


def test_science_menus_construct(stub_app_globals):
    import Bridge.ScienceMenuHandlers as mod
    mod.CreateMenus()


def test_science_first_button_dispatches(stub_app_globals, monkeypatch):
    import Bridge.ScienceMenuHandlers as mod
    mod.CreateMenus()
    # Find any STButton and click it.
    backend = _backend.get()
    btn_eids = [eid for eid, e in backend.elements.items()
                if "bc-stbutton" in e.cls and e.text]
    assert btn_eids, "no buttons constructed"
    backend.fire_click(btn_eids[0])
    # If we got here without exception, dispatch worked.
```

Run each and fix any new App-globals it needs. Typical missing items: `App.g_kRootWindow`, `App.g_kPlayerStrings`, `App.g_kSetManager`, `App.GraphicsModeInfo_GetCurrentMode`. Stub with minimal no-ops.

- [ ] **Per role, after PASS, commit**

```bash
git add tests/sdk_ui/test_smoke_bridge_science.py
git commit -m "test(sdk_ui): smoke Bridge/ScienceMenuHandlers.CreateMenus"
```

Repeat for Data, Engineer, Helm, Tactical, XO.

**End of Slice 4.**

---

## Slice 5 — Engine-Owned Target List + Visual Polish

**Done when:** target list is engine-owned (created by C++ at tactical window init); `TargetListController` accesses it via `App.g_kTacticalWindow.GetTargetList()`; Stage 2 (subsystem expansion) works; visual polish lands.

### Task 5.1: Engine-owned target-list element (registration model)

**Files:**
- Modify: `native/src/ui/include/ui/UiSystem.h`, `UiSystem.cc` (registry slot)
- Modify: `native/src/host/host_bindings.cc` (`get_target_list_element` + `register_target_list_element`)

**Architectural note.** Cross-panel reparenting isn't supported (the reparent binding from Task 1.3 is in-panel only). To keep everything in the shared `sdk-ui` panel, the engine doesn't create a separate panel for the target list. Instead:

1. Python's shim creates the target-list element as a child of the shared `sdk-ui` panel's `active` div (regular `append_div` flow).
2. Python registers that element id with the engine via a new `register_target_list_element(eid)` binding.
3. The engine stores the id in `UiSystem` so future C++ tick code can target it directly.
4. Python code accessing `App.g_kTacticalWindow.GetTargetList()` looks up the registered element via `get_target_list_element()` and returns a `TGUIObject` wrapper around it.

The "engine-owned" property is registration-based, not allocation-based. The advantage: zero cross-panel complexity; the trade-off: the engine doesn't create the element at boot — it's created on first GetTargetList() call. SDK code that references the target list always does so after the bridge has constructed, so this ordering is fine.

- [ ] **Step 1: Add registry slot to UiSystem**

In `native/src/ui/include/ui/UiSystem.h`, add to the public section:

```cpp
    int  target_list_element_id() const { return target_list_eid_; }
    void register_target_list_element(int eid) { target_list_eid_ = eid; }
```

And add to the private section:

```cpp
    int target_list_eid_ = 0;
```

- [ ] **Step 2: Add the bindings**

In `native/src/host/host_bindings.cc`, after the existing UI bindings:

```cpp
    m.def("register_target_list_element",
          [](int eid) {
              if (!g_ui_system) return;
              g_ui_system->register_target_list_element(eid);
          },
          "Register a Python-created element id as the global target-list "
          "for engine-side 60Hz updates (Slice 5 follow-on work).");

    m.def("get_target_list_element",
          []() -> int {
              if (!g_ui_system) return 0;
              return g_ui_system->target_list_element_id();
          },
          "Return the registered target-list element id, or 0 if none.");
```

- [ ] **Step 3: Update FakeNativeBackend**

In `engine/sdk_ui/_fake_backend.py`, add:

```python
def register_target_list_element(self, eid: int) -> None:
    self._record("register_target_list_element", eid)
    self._target_list_eid = eid

def get_target_list_element(self) -> int:
    self._record("get_target_list_element")
    return getattr(self, "_target_list_eid", 0)
```

- [ ] **Step 4: Build, run**

Run: `cmake --build build -j && uv run python -c "import _dauntless_host as h; print(h.get_target_list_element())"`
Expected: prints `0`.

- [ ] **Step 5: Commit**

```bash
git add native/src/ui/include/ui/UiSystem.h native/src/host/host_bindings.cc engine/sdk_ui/_fake_backend.py
git commit -m "feat(native/ui): target-list element registration slot + get/register bindings"
```

### Task 5.2: `g_kTacticalWindow.GetTargetList()` and controller wiring

**Files:**
- Modify: `engine/sdk_ui/target_list.py`
- Modify: `App.py`

- [ ] **Step 1: Create the tactical-window façade with the GetTargetList getter**

In `engine/sdk_ui/target_list.py`, add at the top:

```python
import App as _App
from engine.sdk_ui import _backend
from engine.sdk_ui.base import TGUIObject


class _TacticalWindow:
    """Stand-in for App.g_kTacticalWindow. Owns the GetTargetList accessor.

    The first GetTargetList() call creates the target-list element (a
    standard TGPane positioned top-right) and registers it with the engine
    via register_target_list_element. Subsequent calls return the same
    element.
    """
    _target_list: TGUIObject | None = None

    def GetTargetList(self) -> TGUIObject:
        if self._target_list is None:
            tl = _App.TGPane_Create(0.20, 0.60)
            b = _backend.get()
            b.set_element_property(tl._element_id, "position", "absolute")
            b.set_element_property(tl._element_id, "right", "0%")
            b.set_element_property(tl._element_id, "top", "0%")
            b.set_class(tl._element_id, "bc-tgpane bc-target-list")
            b.register_target_list_element(tl._element_id)
            _TacticalWindow._target_list = tl
        return _TacticalWindow._target_list


g_kTacticalWindow = _TacticalWindow()


def reset_target_list_for_tests() -> None:
    """Test-only — drop the singleton between cases."""
    _TacticalWindow._target_list = None
```

- [ ] **Step 2: Re-export from `App.py`**

```python
from engine.sdk_ui.target_list import g_kTacticalWindow
```

- [ ] **Step 3: Update TargetListController to use the engine-owned target list**

In `engine/sdk_ui/target_list.py`, replace the controller's `__init__`:

```python
class TargetListController:
    def __init__(self, player):
        self._player = player
        # Use the engine-owned target list element instead of constructing
        # our own panel.
        self._panel = _App.g_kTacticalWindow.GetTargetList()
        self._unsubscribe = ship_lifecycle.subscribe(self._on_event)
        self._rows = {}
        for ship in ship_lifecycle.live_snapshot():
            self._add_row(ship)
```

- [ ] **Step 4: Add a regression test**

`tests/sdk_ui/test_engine_target_list.py`:

```python
import App
from engine.sdk_ui import _backend, target_list as tl


def test_get_target_list_creates_and_registers(_sdk_ui_fake_backend):
    tl.reset_target_list_for_tests()
    panel = App.g_kTacticalWindow.GetTargetList()
    assert panel._element_id > 0
    # The id is registered with the engine.
    assert _sdk_ui_fake_backend.get_target_list_element() == panel._element_id


def test_get_target_list_is_idempotent(_sdk_ui_fake_backend):
    tl.reset_target_list_for_tests()
    a = App.g_kTacticalWindow.GetTargetList()
    b = App.g_kTacticalWindow.GetTargetList()
    assert a is b
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/sdk_ui/test_engine_target_list.py tests/sdk_ui/ -v`
Expected: PASS.

- [ ] **Step 6: Boot the engine**

Run: `./build/dauntless`
Expected: target list appears in top-right, populated from ship lifecycle.

- [ ] **Step 7: Commit**

```bash
git add engine/sdk_ui/target_list.py App.py tests/sdk_ui/test_engine_target_list.py
git commit -m "feat(sdk_ui): g_kTacticalWindow.GetTargetList() — engine-registered target list

TargetListController now retrieves the target-list element via the
tactical-window facade. First GetTargetList call creates the TGPane and
registers its id with the engine for future C++ updates.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

### Task 5.3: Stage 2 — subsystem expansion

Per [target-list-from-scene-design.md](../specs/2026-05-11-target-list-from-scene-design.md), Stage 2 reveals one button per populated subsystem when a row is expanded.

**Files:**
- Modify: `engine/sdk_ui/target_list.py`

- [ ] **Step 1: Add the helper**

```python
def populated_subsystems(ship):
    """Walk the standard Get*Subsystem getters; return [(label, subsystem)]."""
    candidates = [
        ("Shields",  "GetShields"),
        ("Phasers",  "GetPhasers"),
        ("Torpedoes","GetTorpedoes"),
        ("Engines",  "GetEngines"),
        ("Warp Core","GetWarpCore"),
        ("Sensors",  "GetSensors"),
    ]
    out = []
    for label, getter in candidates:
        if hasattr(ship, getter):
            sub = getattr(ship, getter)()
            if sub is not None:
                out.append((label, sub))
    return out
```

- [ ] **Step 2: Add subsystem buttons under each row**

In `_add_row`, after creating the row:

```python
for sub_label, subsystem in populated_subsystems(ship):
    sub_ev = App.TGEvent_Create()
    sub_ev.SetDestination(row)
    sub_ev.SetEventType(App.ET_TARGET_SELECTED)
    sub_ev.SetPayload((ship, subsystem))
    sub_btn = App.STButton_CreateW(sub_label, sub_ev, App.STBSF_SIZE_TO_TEXT)
    row.AddChild(sub_btn, 0.05, 0.0)
```

And update the handler to route to `SetTargetSubsystem` if the payload is a tuple.

- [ ] **Step 3: Run tests and commit**

```bash
uv run pytest tests/ -v
git add engine/sdk_ui/target_list.py
git commit -m "feat(sdk_ui): target-list Stage 2 — subsystem expansion"
```

### Task 5.4: Visual polish pass

**Files:**
- Modify: `native/assets/ui/sdk_ui.rcss`

- [ ] **Step 1: Iterate on styling**

Open `native/assets/ui/sdk_ui.rcss` and refine until the bridge UI looks polished. Areas:

- LCARS-inspired frame decoration (border-radius corners, accent strips)
- Button hover states + selection emphasis
- Affiliation-tinted backgrounds for target list rows
- Typography (font sizes, line-height)
- Spacing and padding hierarchy

Iterate by running the engine (`./build/dauntless`), tweaking the .rcss, restarting. Style work isn't TDD — it's iterative manual verification against the manual checklist (next task).

- [ ] **Step 2: Commit progressive polish**

Multiple commits — one per visible improvement, e.g.:
```
style(sdk_ui): LCARS-style frame corners on STStylizedWindow
style(sdk_ui): affiliation-tinted target list rows
style(sdk_ui): button hover + selected emphasis
```

### Task 5.5: Manual smoke checklist

**Files:**
- Create: `tests/manual/bridge_ui_smoke.md`

- [ ] **Step 1: Write the checklist**

`tests/manual/bridge_ui_smoke.md`:

```markdown
# Bridge UI Manual Smoke Checklist

Run after any UI-impacting change. Builds `./build/dauntless` and verifies:

## Boot
- [ ] Engine starts; default mission loads.
- [ ] Target list visible in top-right; rows for each non-player ship.

## Target list interaction
- [ ] Click a row → ship becomes the player's target.
- [ ] Row stays highlighted when targeted.
- [ ] Click row again → expands to show subsystem buttons.
- [ ] Click subsystem → targeting subsystem (verify via existing in-game indicator).

## Bridge menus (open via F1-F6 keys for crew positions per BC convention)
- [ ] Science menu opens, buttons readable.
- [ ] Engineer / Helm / Tactical / Data / XO menus open.
- [ ] Click a button → handler fires (look for in-game effect or log).

## Theme
- [ ] Background colours look intentional (not placeholder grey).
- [ ] Affiliation tinting visible (friendly/enemy distinction in colours).

## Regression checks
- [ ] Mission swap clears + rebuilds target list without artifacts.
- [ ] No console errors during normal gameplay.
```

- [ ] **Step 2: Run through it once and commit**

```bash
git add tests/manual/bridge_ui_smoke.md
git commit -m "docs(tests): manual smoke checklist for bridge UI"
```

**End of Slice 5. Project complete.**

---

## Final verification

After Slice 5:

- [ ] `uv run pytest -v` — all unit + smoke tests pass.
- [ ] `cmake --build build -j` — clean native build.
- [ ] `./build/dauntless` — engine boots, target list works, no console errors.
- [ ] `tests/manual/bridge_ui_smoke.md` — every box checked.

If all four pass, the SDK UI shim project is shippable.
