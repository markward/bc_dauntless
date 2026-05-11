# UI Components Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship two reusable UI primitives — `UiButton` and `UiCollapsibleList` — plus the `UiPanel` scaffolding that holds them, all themable per the four-affiliation × four-menu-level palettes sourced from `LoadInterface.py`. Produce a small demo panel rendered live by the host.

**Architecture:** Thin C++ DOM primitives (panel + element-tree mutations) exposed via pybind11; Python composes the component classes on top. All component state (selection, expansion, theming) lives Python-side; the C++ layer is dumb shuttle code. A fake-DOM shim mirrors the binding contract so component logic is fully testable in pure Python with no native build needed.

**Tech Stack:** Python 3, pybind11, RmlUi (RML + RCSS), GLFW, OpenGL via the existing native renderer. Tests with pytest. Build with CMake.

**Reference spec:** [`docs/superpowers/specs/2026-05-11-ui-components-design.md`](../specs/2026-05-11-ui-components-design.md)

---

## File map

**New Python files:**
- `engine/ui/__init__.py` — public exports
- `engine/ui/theme.py` — affiliation + menu-level registries
- `engine/ui/_dom.py` — fake DOM for tests
- `engine/ui/bindings.py` — facade: real C++ when available, fake DOM otherwise
- `engine/ui/button.py` — `UiButton`
- `engine/ui/collapsible.py` — `UiCollapsibleList`
- `engine/ui/panel.py` — `UiPanel`

**New test files:**
- `tests/ui/__init__.py`
- `tests/ui/conftest.py` — fake-DOM fixture
- `tests/ui/test_theme.py`
- `tests/ui/test_dom.py`
- `tests/ui/test_button.py`
- `tests/ui/test_collapsible.py`
- `tests/ui/test_panel.py`

**New native files:**
- `native/assets/ui/components.rcss`
- `native/assets/ui/panel.rml`
- `native/src/ui/include/ui/PanelDocument.h`
- `native/src/ui/PanelDocument.cc`

**Modified native files:**
- `native/src/ui/UiSystem.cc` + header — register panel documents on demand
- `native/src/ui/CMakeLists.txt` — compile `PanelDocument.cc`
- `native/src/host/host_bindings.cc` + header — new `m.def` for panel/element primitives

**Modified Python files:**
- `engine/renderer.py` — re-export new bindings

---

## Phase 1 — Theme registries (pure Python)

### Task 1: Theme types and defaults

**Files:**
- Create: `engine/ui/__init__.py` (empty for now)
- Create: `engine/ui/theme.py`
- Create: `tests/ui/__init__.py` (empty)
- Create: `tests/ui/test_theme.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/ui/test_theme.py
from engine.ui import theme


def test_affiliation_defaults_match_load_interface():
    assert theme.get_affiliation("friendly") == ( 80, 112, 230)
    assert theme.get_affiliation("enemy")    == (216,  43,  43)
    assert theme.get_affiliation("neutral")  == (255, 255, 175)
    assert theme.get_affiliation("unknown")  == (127, 127, 127)


def test_menu_level_defaults_match_load_interface():
    p = theme.get_menu_palette(3)
    assert p.normal      == (207,  96, 159)
    assert p.highlighted == (246, 147, 204)
    assert p.selected    == (103,  48,  79)


def test_unknown_affiliation_raises():
    import pytest
    with pytest.raises(KeyError):
        theme.get_affiliation("badwhatever")


def test_unknown_menu_level_raises():
    import pytest
    with pytest.raises(KeyError):
        theme.get_menu_palette(99)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/ui/test_theme.py -v`
Expected: FAIL — `engine.ui` doesn't exist yet.

- [ ] **Step 3: Create empty package and theme module**

```python
# engine/ui/__init__.py
"""Reusable UI components for the open_stbc renderer.

See docs/superpowers/specs/2026-05-11-ui-components-design.md for the design.
"""
```

```python
# engine/ui/theme.py
"""Color registries for Button and CollapsibleList components.

Defaults mirror sdk/Build/scripts/LoadInterface.py — the same RGB values
the original game sets in App.g_kRadar*Color and App.g_kSTMenu{1..4}*.
Both registries are mutable at runtime, so callers can match BC's
`ResetAffiliationColors()` style API or apply per-mission tints.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

RGB = Tuple[int, int, int]


@dataclass(frozen=True)
class MenuPalette:
    normal:      RGB
    highlighted: RGB
    selected:    RGB


_AFFILIATION_DEFAULTS: dict[str, RGB] = {
    "friendly": ( 80, 112, 230),
    "enemy":    (216,  43,  43),
    "neutral":  (255, 255, 175),
    "unknown":  (127, 127, 127),
}

_MENU_LEVEL_DEFAULTS: dict[int, MenuPalette] = {
    1: MenuPalette(normal=(216,  94,  86), highlighted=(254, 120,  86), selected=(127, 60,  43)),
    2: MenuPalette(normal=(147, 103, 255), highlighted=(173, 132, 255), selected=( 86, 66, 127)),
    3: MenuPalette(normal=(207,  96, 159), highlighted=(246, 147, 204), selected=(103, 48,  79)),
    4: MenuPalette(normal=(144, 103, 144), highlighted=(175, 144, 175), selected=( 72, 51,  72)),
}

_affiliation: dict[str, RGB] = dict(_AFFILIATION_DEFAULTS)
_menu_levels: dict[int, MenuPalette] = dict(_MENU_LEVEL_DEFAULTS)


def get_affiliation(name: str) -> RGB:
    return _affiliation[name]


def get_menu_palette(level: int) -> MenuPalette:
    return _menu_levels[level]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/ui/test_theme.py -v`
Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/ui/__init__.py engine/ui/theme.py tests/ui/__init__.py tests/ui/test_theme.py
git commit -m "feat(ui): theme registry with LoadInterface defaults"
```

---

### Task 2: Theme mutation and reset

**Files:**
- Modify: `engine/ui/theme.py`
- Modify: `tests/ui/test_theme.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/ui/test_theme.py`:

```python
def test_set_affiliation_overrides_default():
    try:
        theme.set_affiliation("enemy", (200, 200, 200))
        assert theme.get_affiliation("enemy") == (200, 200, 200)
    finally:
        theme.reset_affiliations()


def test_reset_affiliations_restores_defaults():
    theme.set_affiliation("enemy", (1, 2, 3))
    theme.reset_affiliations()
    assert theme.get_affiliation("enemy") == (216, 43, 43)


def test_set_menu_palette_overrides_default():
    try:
        p = theme.MenuPalette(normal=(1,2,3), highlighted=(4,5,6), selected=(7,8,9))
        theme.set_menu_palette(3, p)
        assert theme.get_menu_palette(3) is p
    finally:
        theme.reset_menu_palettes()


def test_reset_menu_palettes_restores_defaults():
    p = theme.MenuPalette(normal=(1,2,3), highlighted=(4,5,6), selected=(7,8,9))
    theme.set_menu_palette(3, p)
    theme.reset_menu_palettes()
    assert theme.get_menu_palette(3).normal == (207, 96, 159)


def test_set_affiliation_unknown_name_raises():
    import pytest
    with pytest.raises(KeyError):
        theme.set_affiliation("noplease", (0, 0, 0))


def test_set_menu_palette_unknown_level_raises():
    import pytest
    p = theme.MenuPalette(normal=(0,0,0), highlighted=(0,0,0), selected=(0,0,0))
    with pytest.raises(KeyError):
        theme.set_menu_palette(99, p)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/ui/test_theme.py -v`
Expected: 6 new tests FAIL — `set_affiliation`, `reset_affiliations`, `set_menu_palette`, `reset_menu_palettes` not defined.

- [ ] **Step 3: Add mutation/reset functions**

Append to `engine/ui/theme.py`:

```python
def set_affiliation(name: str, rgb: RGB) -> None:
    if name not in _AFFILIATION_DEFAULTS:
        raise KeyError(name)
    _affiliation[name] = rgb


def set_menu_palette(level: int, palette: MenuPalette) -> None:
    if level not in _MENU_LEVEL_DEFAULTS:
        raise KeyError(level)
    _menu_levels[level] = palette


def reset_affiliations() -> None:
    _affiliation.clear()
    _affiliation.update(_AFFILIATION_DEFAULTS)


def reset_menu_palettes() -> None:
    _menu_levels.clear()
    _menu_levels.update(_MENU_LEVEL_DEFAULTS)


def known_affiliations() -> tuple[str, ...]:
    return tuple(_AFFILIATION_DEFAULTS)


def known_menu_levels() -> tuple[int, ...]:
    return tuple(_MENU_LEVEL_DEFAULTS)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/ui/test_theme.py -v`
Expected: all 10 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/ui/theme.py tests/ui/test_theme.py
git commit -m "feat(ui): theme mutation and reset helpers"
```

---

## Phase 2 — Fake DOM (test infrastructure)

### Task 3: FakeDom record-and-playback shim

**Files:**
- Create: `engine/ui/_dom.py`
- Create: `tests/ui/test_dom.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/ui/test_dom.py
from engine.ui._dom import FakeDom


def test_create_panel_returns_increasing_ids():
    dom = FakeDom()
    p1 = dom.create_panel("targets", "top-right", 20.0, 60.0)
    p2 = dom.create_panel("nav",     "top-left",  15.0, 40.0)
    assert p1 != p2
    assert dom.panel_root(p1) is not None
    assert dom.panel_root(p2) is not None


def test_append_div_attaches_to_parent():
    dom = FakeDom()
    p = dom.create_panel("p", "top-right", 20.0, 60.0)
    root = dom.panel_root(p)
    a = dom.append_div(root, "bc-button")
    b = dom.append_div(root, "bc-button selected")
    assert dom.element(a).classes == ["bc-button"]
    assert dom.element(b).classes == ["bc-button", "selected"]
    assert dom.children(root) == [a, b]


def test_set_text_updates_node():
    dom = FakeDom()
    p = dom.create_panel("p", "top-right", 20.0, 60.0)
    e = dom.append_div(dom.panel_root(p), "")
    dom.set_text(e, "Shield Generator")
    assert dom.element(e).text == "Shield Generator"


def test_set_class_replaces_class_list():
    dom = FakeDom()
    p = dom.create_panel("p", "top-right", 20.0, 60.0)
    e = dom.append_div(dom.panel_root(p), "bc-button")
    dom.set_class(e, "bc-button selected")
    assert dom.element(e).classes == ["bc-button", "selected"]


def test_on_click_records_callback_and_fires():
    dom = FakeDom()
    p = dom.create_panel("p", "top-right", 20.0, 60.0)
    e = dom.append_div(dom.panel_root(p), "")
    received = []
    dom.on_click(e, lambda: received.append("clicked"))
    dom.fire_click(e)
    assert received == ["clicked"]


def test_remove_element_detaches_from_parent():
    dom = FakeDom()
    p = dom.create_panel("p", "top-right", 20.0, 60.0)
    root = dom.panel_root(p)
    a = dom.append_div(root, "")
    b = dom.append_div(root, "")
    dom.remove_element(a)
    assert dom.children(root) == [b]


def test_set_visible_toggles_flag():
    dom = FakeDom()
    p = dom.create_panel("p", "top-right", 20.0, 60.0)
    e = dom.append_div(dom.panel_root(p), "")
    assert dom.element(e).visible is True
    dom.set_visible(e, False)
    assert dom.element(e).visible is False


def test_set_panel_css_var_records_value():
    dom = FakeDom()
    p = dom.create_panel("p", "top-right", 20.0, 60.0)
    dom.set_panel_css_var(p, "--aff-color", "rgb(216,43,43)")
    assert dom.panel_css_vars(p) == {"--aff-color": "rgb(216,43,43)"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/ui/test_dom.py -v`
Expected: 8 tests FAIL — `FakeDom` not found.

- [ ] **Step 3: Implement FakeDom**

```python
# engine/ui/_dom.py
"""In-memory DOM that mirrors the C++ binding contract for unit tests.

The real binding layer in engine.ui.bindings forwards the same calls to the
_open_stbc_host extension; tests substitute this class in its place so the
component logic can be exercised without a native build, a window, or RmlUi.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class _Element:
    id: int
    parent: Optional[int]
    classes: list[str]      = field(default_factory=list)
    text: str               = ""
    visible: bool           = True
    children: list[int]     = field(default_factory=list)
    on_click: Optional[Callable[[], None]] = None


@dataclass
class _Panel:
    id: int
    name: str
    anchor: str
    width_vw: float
    height_vh: float
    root: int
    css_vars: dict[str, str] = field(default_factory=dict)


class FakeDom:
    """A minimal DOM-like store. All IDs are integers. Element 0 is unused."""

    def __init__(self) -> None:
        self._elements: dict[int, _Element] = {}
        self._panels:   dict[int, _Panel]   = {}
        self._next_id = 1  # IDs share a namespace; 0 reserved for "invalid"

    # ── Panel lifecycle ──────────────────────────────────────────────────────

    def create_panel(self, name: str, anchor: str,
                     width_vw: float, height_vh: float) -> int:
        pid = self._next_id; self._next_id += 1
        root_id = self._next_id; self._next_id += 1
        self._elements[root_id] = _Element(id=root_id, parent=None)
        self._panels[pid] = _Panel(id=pid, name=name, anchor=anchor,
                                   width_vw=width_vw, height_vh=height_vh,
                                   root=root_id)
        return pid

    def destroy_panel(self, panel_id: int) -> None:
        panel = self._panels.pop(panel_id)
        self._destroy_subtree(panel.root)

    def clear_panel(self, panel_id: int) -> None:
        root_id = self._panels[panel_id].root
        for child in list(self._elements[root_id].children):
            self._destroy_subtree(child)
        self._elements[root_id].children.clear()

    def panel_root(self, panel_id: int) -> int:
        return self._panels[panel_id].root

    def panel_css_vars(self, panel_id: int) -> dict[str, str]:
        return dict(self._panels[panel_id].css_vars)

    def set_panel_css_var(self, panel_id: int, name: str, value: str) -> None:
        self._panels[panel_id].css_vars[name] = value

    # ── Element mutation ─────────────────────────────────────────────────────

    def append_div(self, parent_id: int, class_names: str) -> int:
        eid = self._next_id; self._next_id += 1
        classes = [c for c in class_names.split() if c]
        self._elements[eid] = _Element(id=eid, parent=parent_id, classes=classes)
        self._elements[parent_id].children.append(eid)
        return eid

    def remove_element(self, element_id: int) -> None:
        el = self._elements[element_id]
        if el.parent is not None:
            self._elements[el.parent].children.remove(element_id)
        self._destroy_subtree(element_id)

    def set_class(self, element_id: int, class_names: str) -> None:
        self._elements[element_id].classes = [c for c in class_names.split() if c]

    def set_text(self, element_id: int, text: str) -> None:
        self._elements[element_id].text = text

    def set_visible(self, element_id: int, visible: bool) -> None:
        self._elements[element_id].visible = visible

    def on_click(self, element_id: int, callback: Callable[[], None]) -> None:
        self._elements[element_id].on_click = callback

    # ── Test introspection ───────────────────────────────────────────────────

    def element(self, element_id: int) -> _Element:
        return self._elements[element_id]

    def children(self, element_id: int) -> list[int]:
        return list(self._elements[element_id].children)

    def fire_click(self, element_id: int) -> None:
        cb = self._elements[element_id].on_click
        if cb is not None:
            cb()

    # ── Internal ─────────────────────────────────────────────────────────────

    def _destroy_subtree(self, root_id: int) -> None:
        for child in list(self._elements[root_id].children):
            self._destroy_subtree(child)
        self._elements.pop(root_id, None)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/ui/test_dom.py -v`
Expected: all 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/ui/_dom.py tests/ui/test_dom.py
git commit -m "feat(ui): FakeDom shim mirroring binding contract"
```

---

## Phase 3 — Bindings facade

### Task 4: Bindings module with FakeDom fallback

**Files:**
- Create: `engine/ui/bindings.py`
- Create: `tests/ui/conftest.py`

- [ ] **Step 1: Write the conftest fixture and a guard test**

```python
# tests/ui/conftest.py
"""Test fixtures for engine.ui — installs a FakeDom in place of the real
binding layer for all tests in this directory."""
import pytest

from engine.ui import bindings as bindings_module
from engine.ui._dom import FakeDom


@pytest.fixture
def fake_dom(monkeypatch) -> FakeDom:
    dom = FakeDom()
    monkeypatch.setattr(bindings_module, "_active_dom", dom)
    return dom
```

```python
# tests/ui/test_bindings.py
from engine.ui import bindings


def test_bindings_returns_active_dom(fake_dom):
    assert bindings.dom() is fake_dom


def test_create_panel_calls_into_dom(fake_dom):
    pid = bindings.create_panel("targets", "top-right", 20.0, 60.0)
    # FakeDom assigns sequential ids starting at 1
    assert pid > 0
    assert fake_dom.panel_root(pid) is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/ui/test_bindings.py -v`
Expected: FAIL — `engine.ui.bindings` not found.

- [ ] **Step 3: Implement the facade**

```python
# engine/ui/bindings.py
"""Facade over the panel-DOM bindings.

In production, `_active_dom` is set during init() to a wrapper around the
_open_stbc_host extension. In tests, the fake_dom fixture swaps in an
engine.ui._dom.FakeDom. Component code calls these module-level helpers and
remains ignorant of which backing implementation is in use.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

# Set by engine.ui.init() (production) or by the fake_dom fixture (tests).
# Typed as Any to avoid a hard import of the C++ binding module.
_active_dom: Optional[Any] = None


def dom() -> Any:
    if _active_dom is None:
        raise RuntimeError(
            "engine.ui bindings have no active DOM. Call engine.ui.init() "
            "after the renderer is up, or use the fake_dom test fixture."
        )
    return _active_dom


# ── Pass-through helpers (identical signatures to FakeDom) ──────────────────

def create_panel(name: str, anchor: str, width_vw: float, height_vh: float) -> int:
    return dom().create_panel(name, anchor, width_vw, height_vh)

def destroy_panel(panel_id: int) -> None:
    dom().destroy_panel(panel_id)

def clear_panel(panel_id: int) -> None:
    dom().clear_panel(panel_id)

def panel_root(panel_id: int) -> int:
    return dom().panel_root(panel_id)

def set_panel_css_var(panel_id: int, name: str, value: str) -> None:
    dom().set_panel_css_var(panel_id, name, value)

def append_div(parent_id: int, class_names: str) -> int:
    return dom().append_div(parent_id, class_names)

def remove_element(element_id: int) -> None:
    dom().remove_element(element_id)

def set_class(element_id: int, class_names: str) -> None:
    dom().set_class(element_id, class_names)

def set_text(element_id: int, text: str) -> None:
    dom().set_text(element_id, text)

def set_visible(element_id: int, visible: bool) -> None:
    dom().set_visible(element_id, visible)

def on_click(element_id: int, callback: Callable[[], None]) -> None:
    dom().on_click(element_id, callback)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/ui/test_bindings.py -v`
Expected: 2 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/ui/bindings.py tests/ui/conftest.py tests/ui/test_bindings.py
git commit -m "feat(ui): bindings facade with swappable DOM backend"
```

---

## Phase 4 — UiButton

### Task 5: UiButton basics — construction, label, destroy

**Files:**
- Create: `engine/ui/button.py`
- Create: `tests/ui/test_button.py`
- Modify: `engine/ui/__init__.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/ui/test_button.py
from engine.ui import UiButton, bindings


def test_button_renders_label_into_dom(fake_dom):
    pid = bindings.create_panel("p", "top-right", 20.0, 60.0)
    root = bindings.panel_root(pid)
    btn = UiButton(parent_element=root, label="Shield Generator", menu_level=3)
    el = fake_dom.element(btn.element_id)
    assert "bc-button" in el.classes
    assert "menu-3" in el.classes
    assert el.text == "Shield Generator"
    assert "selected" not in el.classes


def test_button_starts_selected_if_requested(fake_dom):
    pid = bindings.create_panel("p", "top-right", 20.0, 60.0)
    btn = UiButton(parent_element=bindings.panel_root(pid),
                   label="Warp Core", selected=True)
    el = fake_dom.element(btn.element_id)
    assert "selected" in el.classes


def test_button_set_label_updates_dom(fake_dom):
    pid = bindings.create_panel("p", "top-right", 20.0, 60.0)
    btn = UiButton(parent_element=bindings.panel_root(pid), label="A")
    btn.set_label("B")
    assert fake_dom.element(btn.element_id).text == "B"


def test_button_destroy_removes_from_dom(fake_dom):
    pid = bindings.create_panel("p", "top-right", 20.0, 60.0)
    root = bindings.panel_root(pid)
    btn = UiButton(parent_element=root, label="A")
    assert fake_dom.children(root) == [btn.element_id]
    btn.destroy()
    assert fake_dom.children(root) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/ui/test_button.py -v`
Expected: FAIL — `UiButton` not exported.

- [ ] **Step 3: Implement UiButton**

```python
# engine/ui/button.py
"""Radio-group child row. Click → exclusive selection within siblings."""
from __future__ import annotations

from typing import Callable, Optional

from . import bindings


class UiButton:
    def __init__(self, *,
                 parent_element: int,
                 label: str,
                 menu_level: int = 3,
                 selected: bool = False,
                 on_click: Optional[Callable[[], None]] = None):
        self._parent_element = parent_element
        self._label = label
        self._menu_level = menu_level
        self._selected = selected
        self._on_click = on_click
        self._destroyed = False

        self.element_id = bindings.append_div(parent_element, self._class_names())
        bindings.set_text(self.element_id, label)
        bindings.on_click(self.element_id, self._handle_click)

    # ── Public state mutators ────────────────────────────────────────────────

    @property
    def label(self) -> str: return self._label
    @property
    def menu_level(self) -> int: return self._menu_level
    @property
    def selected(self) -> bool: return self._selected

    def set_label(self, label: str) -> None:
        self._label = label
        bindings.set_text(self.element_id, label)

    def set_menu_level(self, level: int) -> None:
        self._menu_level = level
        bindings.set_class(self.element_id, self._class_names())

    def set_selected(self, selected: bool) -> None:
        # Radio-group exclusivity is enforced by the parent (Phase 4 Task 7).
        # This method only flips the local flag and updates DOM classes.
        if self._selected == selected:
            return
        self._selected = selected
        bindings.set_class(self.element_id, self._class_names())

    def destroy(self) -> None:
        if self._destroyed:
            return
        bindings.remove_element(self.element_id)
        self._destroyed = True

    # ── Internals ────────────────────────────────────────────────────────────

    def _class_names(self) -> str:
        parts = ["bc-button", f"menu-{self._menu_level}"]
        if self._selected:
            parts.append("selected")
        return " ".join(parts)

    def _handle_click(self) -> None:
        # Filled in by the parent when it adopts this button into a radio
        # group (Task 7). For now: fire the consumer callback directly.
        if self._on_click is not None:
            self._on_click()
```

```python
# engine/ui/__init__.py
"""Reusable UI components for the open_stbc renderer.

See docs/superpowers/specs/2026-05-11-ui-components-design.md for the design.
"""
from . import bindings, theme
from .button import UiButton

__all__ = ["bindings", "theme", "UiButton"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/ui/test_button.py -v`
Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/ui/button.py engine/ui/__init__.py tests/ui/test_button.py
git commit -m "feat(ui): UiButton — construction, label, destroy"
```

---

### Task 6: UiButton click callback

**Files:**
- Modify: `tests/ui/test_button.py`

(`_handle_click` already calls `on_click` — these tests prove the wiring works.)

- [ ] **Step 1: Write the failing test**

Append to `tests/ui/test_button.py`:

```python
def test_button_click_fires_callback(fake_dom):
    pid = bindings.create_panel("p", "top-right", 20.0, 60.0)
    fired: list[str] = []
    btn = UiButton(parent_element=bindings.panel_root(pid), label="X",
                   on_click=lambda: fired.append("ok"))
    fake_dom.fire_click(btn.element_id)
    assert fired == ["ok"]


def test_button_no_callback_does_not_explode(fake_dom):
    pid = bindings.create_panel("p", "top-right", 20.0, 60.0)
    btn = UiButton(parent_element=bindings.panel_root(pid), label="X")
    fake_dom.fire_click(btn.element_id)  # must not raise
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `uv run pytest tests/ui/test_button.py -v`
Expected: all 6 PASS (the click handler is already wired from Task 5).

- [ ] **Step 3: Commit**

```bash
git add tests/ui/test_button.py
git commit -m "test(ui): verify button click fires on_click"
```

---

### Task 7: Radio-group parent (`_RadioGroup`)

The radio-group exclusivity belongs to whatever class *owns* a set of buttons (UiPanel for top-level, UiCollapsibleList for children). To avoid duplicating the logic, introduce a small mixin/helper class that those owners use.

**Files:**
- Modify: `engine/ui/button.py` (export `_RadioGroup`)
- Modify: `tests/ui/test_button.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/ui/test_button.py`:

```python
from engine.ui.button import _RadioGroup


def test_radio_group_selects_one_at_a_time(fake_dom):
    pid = bindings.create_panel("p", "top-right", 20.0, 60.0)
    root = bindings.panel_root(pid)
    group = _RadioGroup()
    a = UiButton(parent_element=root, label="A"); group.adopt(a)
    b = UiButton(parent_element=root, label="B"); group.adopt(b)
    c = UiButton(parent_element=root, label="C"); group.adopt(c)
    # Click A → only A selected
    fake_dom.fire_click(a.element_id)
    assert a.selected and not b.selected and not c.selected
    # Click B → only B
    fake_dom.fire_click(b.element_id)
    assert b.selected and not a.selected and not c.selected
    # Click B again → still only B; no toggle to unselected
    fake_dom.fire_click(b.element_id)
    assert b.selected


def test_radio_group_does_not_refire_when_clicking_selected(fake_dom):
    pid = bindings.create_panel("p", "top-right", 20.0, 60.0)
    root = bindings.panel_root(pid)
    group = _RadioGroup()
    fires: list[str] = []
    a = UiButton(parent_element=root, label="A",
                 on_click=lambda: fires.append("a"))
    group.adopt(a)
    fake_dom.fire_click(a.element_id)        # selects → fires
    fake_dom.fire_click(a.element_id)        # already selected → no fire
    assert fires == ["a"]


def test_radio_group_previously_selected_does_not_fire_on_deselect(fake_dom):
    pid = bindings.create_panel("p", "top-right", 20.0, 60.0)
    root = bindings.panel_root(pid)
    group = _RadioGroup()
    fires: list[str] = []
    a = UiButton(parent_element=root, label="A",
                 on_click=lambda: fires.append("a"))
    b = UiButton(parent_element=root, label="B",
                 on_click=lambda: fires.append("b"))
    group.adopt(a); group.adopt(b)
    fake_dom.fire_click(a.element_id)        # a fires
    fake_dom.fire_click(b.element_id)        # b fires; a's callback must NOT fire
    assert fires == ["a", "b"]


def test_radio_group_set_selected_programmatic_also_exclusive(fake_dom):
    pid = bindings.create_panel("p", "top-right", 20.0, 60.0)
    root = bindings.panel_root(pid)
    group = _RadioGroup()
    a = UiButton(parent_element=root, label="A")
    b = UiButton(parent_element=root, label="B")
    group.adopt(a); group.adopt(b)
    group.select(a)
    assert a.selected and not b.selected
    group.select(b)
    assert b.selected and not a.selected
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/ui/test_button.py -v`
Expected: 4 new tests FAIL — `_RadioGroup` not defined.

- [ ] **Step 3: Implement `_RadioGroup` and rewire UiButton**

Modify `engine/ui/button.py`. Add `_RadioGroup`:

```python
# Append to engine/ui/button.py

class _RadioGroup:
    """Coordinates exclusive selection across sibling UiButtons.

    Owners (UiPanel, UiCollapsibleList) construct one of these and call
    `adopt(button)` for each direct-child button they create. The group
    rewires each button's click handler so that selecting one deselects
    the others; callbacks fire only for the newly-selected button.
    """

    def __init__(self) -> None:
        self._members: list["UiButton"] = []

    def adopt(self, button: "UiButton") -> None:
        self._members.append(button)
        # Rewire the button's _handle_click through the group.
        consumer_cb = button._on_click
        button._handle_click = lambda b=button, cb=consumer_cb: self._on_click(b, cb)
        bindings.on_click(button.element_id, button._handle_click)

    def select(self, target: "UiButton") -> None:
        """Programmatic selection: same exclusivity, no callback fired."""
        for m in self._members:
            m.set_selected(m is target)

    def _on_click(self, clicked: "UiButton",
                  consumer_cb: Optional[Callable[[], None]]) -> None:
        if clicked.selected:
            return  # already selected — no state change, no refire
        for m in self._members:
            m.set_selected(m is clicked)
        if consumer_cb is not None:
            consumer_cb()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/ui/test_button.py -v`
Expected: all 10 PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/ui/button.py tests/ui/test_button.py
git commit -m "feat(ui): _RadioGroup helper enforces exclusive button selection"
```

---

## Phase 5 — UiCollapsibleList

### Task 8: UiCollapsibleList header rendering

**Files:**
- Create: `engine/ui/collapsible.py`
- Create: `tests/ui/test_collapsible.py`
- Modify: `engine/ui/__init__.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/ui/test_collapsible.py
from engine.ui import UiCollapsibleList, bindings


def test_collapsible_renders_header_with_title_and_arrow(fake_dom):
    pid = bindings.create_panel("p", "top-right", 20.0, 60.0)
    root = bindings.panel_root(pid)
    coll = UiCollapsibleList(parent_element=root, label="Bird of Prey-1",
                             affiliation="enemy", expanded=True)
    # Header has two children: arrow region and title region.
    header_classes = fake_dom.element(coll.header_element_id).classes
    assert "bc-collapsible-header" in header_classes
    assert "aff-enemy" in header_classes
    arrow_id, title_id = fake_dom.children(coll.header_element_id)
    assert "bc-arrow"  in fake_dom.element(arrow_id).classes
    assert "bc-title"  in fake_dom.element(title_id).classes
    assert fake_dom.element(title_id).text == "Bird of Prey-1"


def test_collapsible_menu_level_class_when_no_affiliation(fake_dom):
    pid = bindings.create_panel("p", "top-right", 20.0, 60.0)
    root = bindings.panel_root(pid)
    coll = UiCollapsibleList(parent_element=root, label="Subsystems",
                             menu_level=3)
    classes = fake_dom.element(coll.header_element_id).classes
    assert "menu-3" in classes
    assert not any(c.startswith("aff-") for c in classes)


def test_collapsible_set_label_updates_title_element(fake_dom):
    pid = bindings.create_panel("p", "top-right", 20.0, 60.0)
    coll = UiCollapsibleList(parent_element=bindings.panel_root(pid),
                             label="One", affiliation="friendly")
    coll.set_label("Two")
    title_id = fake_dom.children(coll.header_element_id)[1]
    assert fake_dom.element(title_id).text == "Two"


def test_collapsible_destroy_removes_subtree(fake_dom):
    pid = bindings.create_panel("p", "top-right", 20.0, 60.0)
    root = bindings.panel_root(pid)
    coll = UiCollapsibleList(parent_element=root, label="X",
                             affiliation="neutral")
    assert fake_dom.children(root) != []
    coll.destroy()
    assert fake_dom.children(root) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/ui/test_collapsible.py -v`
Expected: FAIL — `UiCollapsibleList` not exported.

- [ ] **Step 3: Implement UiCollapsibleList (header only — children come in Task 9)**

```python
# engine/ui/collapsible.py
"""Collapsible header (button + arrow) plus a list of child rows.

The header is composed of two elements (arrow + title) so the arrow can
be styled and clicked independently of the title region. The children
container is a separate sibling div whose `visible` flag is toggled by
the arrow.
"""
from __future__ import annotations

from typing import Callable, Optional

from . import bindings
from .button import _RadioGroup, UiButton


class UiCollapsibleList:
    def __init__(self, *,
                 parent_element: int,
                 label: str,
                 affiliation: Optional[str] = None,
                 menu_level: int = 3,
                 expanded: bool = True,
                 selected: bool = False,
                 on_click: Optional[Callable[[], None]] = None):
        self._parent_element = parent_element
        self._label = label
        self._affiliation = affiliation
        self._menu_level = menu_level
        self._expanded = expanded
        self._selected = selected
        self._on_click = on_click
        self._destroyed = False
        self._children: list[object] = []
        self._radio_group = _RadioGroup()

        # Wrapper: contains header + children container so destroy() can
        # tear the whole subtree down with one remove_element call.
        self._wrapper_id = bindings.append_div(parent_element, "bc-collapsible")
        self.header_element_id = bindings.append_div(self._wrapper_id,
                                                     self._header_classes())
        self._arrow_id = bindings.append_div(self.header_element_id, "bc-arrow")
        self._title_id = bindings.append_div(self.header_element_id, "bc-title")
        bindings.set_text(self._title_id, label)
        self._children_container_id = bindings.append_div(
            self._wrapper_id, "bc-collapsible-children")
        bindings.set_visible(self._children_container_id, expanded)

        bindings.on_click(self._arrow_id, self._toggle_expanded)
        bindings.on_click(self._title_id, self._handle_title_click)

    # ── Public state ─────────────────────────────────────────────────────────

    @property
    def label(self) -> str: return self._label
    @property
    def expanded(self) -> bool: return self._expanded
    @property
    def selected(self) -> bool: return self._selected

    def set_label(self, label: str) -> None:
        self._label = label
        bindings.set_text(self._title_id, label)

    def set_expanded(self, expanded: bool) -> None:
        if self._expanded == expanded:
            return
        self._expanded = expanded
        bindings.set_visible(self._children_container_id, expanded)
        bindings.set_class(self.header_element_id, self._header_classes())

    def set_affiliation(self, name: Optional[str]) -> None:
        self._affiliation = name
        bindings.set_class(self.header_element_id, self._header_classes())

    def set_menu_level(self, level: int) -> None:
        self._menu_level = level
        bindings.set_class(self.header_element_id, self._header_classes())

    def set_selected(self, selected: bool) -> None:
        if self._selected == selected:
            return
        self._selected = selected
        bindings.set_class(self.header_element_id, self._header_classes())

    def clear(self) -> None:
        for child in self._children:
            child.destroy()  # type: ignore[attr-defined]
        self._children.clear()
        self._radio_group = _RadioGroup()

    def destroy(self) -> None:
        if self._destroyed:
            return
        bindings.remove_element(self._wrapper_id)
        self._destroyed = True

    # ── Internals ────────────────────────────────────────────────────────────

    def _header_classes(self) -> str:
        parts = ["bc-collapsible-header"]
        if self._affiliation is not None:
            parts.append(f"aff-{self._affiliation}")
        else:
            parts.append(f"menu-{self._menu_level}")
        if self._expanded:
            parts.append("expanded")
        else:
            parts.append("collapsed")
        if self._selected:
            parts.append("selected")
        return " ".join(parts)

    def _toggle_expanded(self) -> None:
        self.set_expanded(not self._expanded)

    def _handle_title_click(self) -> None:
        if self._on_click is not None:
            self._on_click()
```

Update `engine/ui/__init__.py`:

```python
from . import bindings, theme
from .button import UiButton
from .collapsible import UiCollapsibleList

__all__ = ["bindings", "theme", "UiButton", "UiCollapsibleList"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/ui/test_collapsible.py -v`
Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/ui/collapsible.py engine/ui/__init__.py tests/ui/test_collapsible.py
git commit -m "feat(ui): UiCollapsibleList header (title + arrow) skeleton"
```

---

### Task 9: Expand / collapse behavior

**Files:**
- Modify: `tests/ui/test_collapsible.py`

The toggle logic is already implemented in Task 8 — these tests prove it.

- [ ] **Step 1: Write the failing tests**

Append to `tests/ui/test_collapsible.py`:

```python
def test_collapsible_starts_expanded_by_default(fake_dom):
    pid = bindings.create_panel("p", "top-right", 20.0, 60.0)
    coll = UiCollapsibleList(parent_element=bindings.panel_root(pid),
                             label="x", affiliation="enemy")
    # The children container is the second wrapper child
    wrapper = fake_dom.children(bindings.panel_root(pid))[0]
    children_container = fake_dom.children(wrapper)[1]
    assert fake_dom.element(children_container).visible is True


def test_collapsible_starts_collapsed_when_requested(fake_dom):
    pid = bindings.create_panel("p", "top-right", 20.0, 60.0)
    coll = UiCollapsibleList(parent_element=bindings.panel_root(pid),
                             label="x", affiliation="enemy", expanded=False)
    wrapper = fake_dom.children(bindings.panel_root(pid))[0]
    children_container = fake_dom.children(wrapper)[1]
    assert fake_dom.element(children_container).visible is False


def test_arrow_click_toggles_expansion(fake_dom):
    pid = bindings.create_panel("p", "top-right", 20.0, 60.0)
    coll = UiCollapsibleList(parent_element=bindings.panel_root(pid),
                             label="x", affiliation="enemy")
    arrow_id = fake_dom.children(coll.header_element_id)[0]
    assert coll.expanded
    fake_dom.fire_click(arrow_id)
    assert not coll.expanded
    fake_dom.fire_click(arrow_id)
    assert coll.expanded


def test_header_class_reflects_expanded_state(fake_dom):
    pid = bindings.create_panel("p", "top-right", 20.0, 60.0)
    coll = UiCollapsibleList(parent_element=bindings.panel_root(pid),
                             label="x", affiliation="enemy")
    assert "expanded" in fake_dom.element(coll.header_element_id).classes
    coll.set_expanded(False)
    assert "collapsed" in fake_dom.element(coll.header_element_id).classes
    assert "expanded" not in fake_dom.element(coll.header_element_id).classes


def test_title_click_does_not_toggle_expansion(fake_dom):
    pid = bindings.create_panel("p", "top-right", 20.0, 60.0)
    coll = UiCollapsibleList(parent_element=bindings.panel_root(pid),
                             label="x", affiliation="enemy")
    title_id = fake_dom.children(coll.header_element_id)[1]
    fake_dom.fire_click(title_id)
    assert coll.expanded  # unchanged
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `uv run pytest tests/ui/test_collapsible.py -v`
Expected: 9 total PASS (4 from Task 8 + 5 new).

- [ ] **Step 3: Commit**

```bash
git add tests/ui/test_collapsible.py
git commit -m "test(ui): verify collapsible expand/collapse + arrow vs title click"
```

---

### Task 10: Title click → `on_click` callback + selection

**Files:**
- Modify: `tests/ui/test_collapsible.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/ui/test_collapsible.py`:

```python
def test_title_click_fires_on_click_callback(fake_dom):
    pid = bindings.create_panel("p", "top-right", 20.0, 60.0)
    fired: list[str] = []
    coll = UiCollapsibleList(parent_element=bindings.panel_root(pid),
                             label="x", affiliation="enemy",
                             on_click=lambda: fired.append("hit"))
    title_id = fake_dom.children(coll.header_element_id)[1]
    fake_dom.fire_click(title_id)
    assert fired == ["hit"]


def test_arrow_click_does_not_fire_on_click(fake_dom):
    pid = bindings.create_panel("p", "top-right", 20.0, 60.0)
    fired: list[str] = []
    coll = UiCollapsibleList(parent_element=bindings.panel_root(pid),
                             label="x", affiliation="enemy",
                             on_click=lambda: fired.append("nope"))
    arrow_id = fake_dom.children(coll.header_element_id)[0]
    fake_dom.fire_click(arrow_id)
    assert fired == []


def test_set_selected_updates_header_class(fake_dom):
    pid = bindings.create_panel("p", "top-right", 20.0, 60.0)
    coll = UiCollapsibleList(parent_element=bindings.panel_root(pid),
                             label="x", affiliation="enemy")
    assert "selected" not in fake_dom.element(coll.header_element_id).classes
    coll.set_selected(True)
    assert "selected" in fake_dom.element(coll.header_element_id).classes
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `uv run pytest tests/ui/test_collapsible.py -v`
Expected: all 12 PASS — the wiring is already done in Task 8.

- [ ] **Step 3: Commit**

```bash
git add tests/ui/test_collapsible.py
git commit -m "test(ui): verify collapsible title-click and selection state"
```

---

### Task 11: Child rows — `.button()` and nested `.collapsible()`

**Files:**
- Modify: `engine/ui/collapsible.py`
- Modify: `tests/ui/test_collapsible.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/ui/test_collapsible.py`:

```python
from engine.ui import UiButton


def test_collapsible_button_factory_creates_child(fake_dom):
    pid = bindings.create_panel("p", "top-right", 20.0, 60.0)
    coll = UiCollapsibleList(parent_element=bindings.panel_root(pid),
                             label="x", affiliation="enemy")
    b = coll.button("Shield Generator")
    assert isinstance(b, UiButton)
    assert b.label == "Shield Generator"
    # Button is inside the children container
    wrapper = fake_dom.children(bindings.panel_root(pid))[0]
    children_container = fake_dom.children(wrapper)[1]
    assert b.element_id in fake_dom.children(children_container)


def test_collapsible_button_factory_returns_buttons_in_radio_group(fake_dom):
    pid = bindings.create_panel("p", "top-right", 20.0, 60.0)
    coll = UiCollapsibleList(parent_element=bindings.panel_root(pid),
                             label="x", affiliation="enemy")
    a = coll.button("A")
    b = coll.button("B")
    fake_dom.fire_click(a.element_id)
    assert a.selected and not b.selected
    fake_dom.fire_click(b.element_id)
    assert b.selected and not a.selected


def test_collapsible_nested_collapsible(fake_dom):
    pid = bindings.create_panel("p", "top-right", 20.0, 60.0)
    outer = UiCollapsibleList(parent_element=bindings.panel_root(pid),
                              label="o", affiliation="enemy")
    inner = outer.collapsible("Disruptor Cannons", menu_level=3)
    assert isinstance(inner, UiCollapsibleList)
    assert inner.label == "Disruptor Cannons"
    wrapper = fake_dom.children(bindings.panel_root(pid))[0]
    outer_children = fake_dom.children(wrapper)[1]
    # The inner collapsible's wrapper sits inside the outer's children container
    inner_wrapper_classes = [
        fake_dom.element(eid).classes for eid in fake_dom.children(outer_children)
    ]
    assert any("bc-collapsible" in cs for cs in inner_wrapper_classes)


def test_clear_destroys_all_children(fake_dom):
    pid = bindings.create_panel("p", "top-right", 20.0, 60.0)
    coll = UiCollapsibleList(parent_element=bindings.panel_root(pid),
                             label="x", affiliation="enemy")
    coll.button("A"); coll.button("B"); coll.collapsible("C")
    wrapper = fake_dom.children(bindings.panel_root(pid))[0]
    children_container = fake_dom.children(wrapper)[1]
    assert len(fake_dom.children(children_container)) == 3
    coll.clear()
    assert fake_dom.children(children_container) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/ui/test_collapsible.py -v`
Expected: 4 new tests FAIL — `coll.button` and `coll.collapsible` don't exist yet.

- [ ] **Step 3: Add the factory methods**

Append to `engine/ui/collapsible.py` inside the class body (place before `# ── Internals ─`):

```python
    # ── Children factories ───────────────────────────────────────────────────

    def button(self, label: str, *,
               menu_level: int = 3,
               selected: bool = False,
               on_click: Optional[Callable[[], None]] = None,
    ) -> UiButton:
        btn = UiButton(parent_element=self._children_container_id,
                       label=label, menu_level=menu_level,
                       selected=selected, on_click=on_click)
        self._radio_group.adopt(btn)
        self._children.append(btn)
        if selected:
            self._radio_group.select(btn)
        return btn

    def collapsible(self, label: str, *,
                    affiliation: Optional[str] = None,
                    menu_level: int = 3,
                    expanded: bool = True,
                    on_click: Optional[Callable[[], None]] = None,
    ) -> "UiCollapsibleList":
        child = UiCollapsibleList(parent_element=self._children_container_id,
                                  label=label, affiliation=affiliation,
                                  menu_level=menu_level, expanded=expanded,
                                  on_click=on_click)
        self._children.append(child)
        return child
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/ui/test_collapsible.py -v`
Expected: all 16 PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/ui/collapsible.py tests/ui/test_collapsible.py
git commit -m "feat(ui): collapsible factory methods for nested buttons + lists"
```

---

## Phase 6 — UiPanel

### Task 12: UiPanel lifecycle and factories

**Files:**
- Create: `engine/ui/panel.py`
- Create: `tests/ui/test_panel.py`
- Modify: `engine/ui/__init__.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/ui/test_panel.py
from engine.ui import UiPanel, UiButton, UiCollapsibleList, bindings


def test_panel_creates_panel_in_dom(fake_dom):
    panel = UiPanel(id="targets", anchor="top-right",
                    width_vw=20.0, height_vh=60.0)
    assert fake_dom.panel_root(panel.panel_id) is not None


def test_panel_button_factory_attaches_to_root(fake_dom):
    panel = UiPanel(id="targets")
    b = panel.button("Loose Button")
    assert isinstance(b, UiButton)
    assert b.element_id in fake_dom.children(fake_dom.panel_root(panel.panel_id))


def test_panel_collapsible_factory_attaches_to_root(fake_dom):
    panel = UiPanel(id="targets")
    c = panel.collapsible("Bird of Prey-1", affiliation="enemy")
    assert isinstance(c, UiCollapsibleList)
    root_children = fake_dom.children(fake_dom.panel_root(panel.panel_id))
    # The collapsible adds a wrapper to root
    assert len(root_children) == 1
    assert "bc-collapsible" in fake_dom.element(root_children[0]).classes


def test_panel_buttons_share_radio_group(fake_dom):
    panel = UiPanel(id="p")
    a = panel.button("A"); b = panel.button("B")
    fake_dom.fire_click(a.element_id)
    assert a.selected and not b.selected
    fake_dom.fire_click(b.element_id)
    assert b.selected and not a.selected


def test_panel_clear_removes_children(fake_dom):
    panel = UiPanel(id="p")
    panel.button("A"); panel.collapsible("B", affiliation="enemy")
    root = fake_dom.panel_root(panel.panel_id)
    assert len(fake_dom.children(root)) == 2
    panel.clear()
    assert fake_dom.children(root) == []


def test_panel_destroy_destroys_panel(fake_dom):
    panel = UiPanel(id="p")
    pid = panel.panel_id
    panel.destroy()
    import pytest
    with pytest.raises(KeyError):
        fake_dom.panel_root(pid)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/ui/test_panel.py -v`
Expected: FAIL — `UiPanel` not exported.

- [ ] **Step 3: Implement UiPanel**

```python
# engine/ui/panel.py
"""Root container for stackable UI components.

Owns a panel handle in the binding layer and exposes button/collapsible
factories that attach directly to the panel's root element. A panel
maintains its own _RadioGroup for top-level button exclusivity.
"""
from __future__ import annotations

from typing import Callable, Literal, Optional

from . import bindings
from .button import _RadioGroup, UiButton
from .collapsible import UiCollapsibleList


Anchor = Literal["top-left", "top-right", "bottom-left", "bottom-right"]


class UiPanel:
    def __init__(self, *,
                 id: str,
                 anchor: Anchor = "top-right",
                 width_vw: float = 20.0,
                 height_vh: float = 60.0):
        self._id = id
        self._anchor = anchor
        self._width_vw = width_vw
        self._height_vh = height_vh
        self._children: list[object] = []
        self._radio_group = _RadioGroup()
        self._destroyed = False

        self.panel_id = bindings.create_panel(id, anchor, width_vw, height_vh)

    @property
    def root(self) -> int:
        return bindings.panel_root(self.panel_id)

    def button(self, label: str, *,
               menu_level: int = 3,
               selected: bool = False,
               on_click: Optional[Callable[[], None]] = None,
    ) -> UiButton:
        btn = UiButton(parent_element=self.root, label=label,
                       menu_level=menu_level, selected=selected,
                       on_click=on_click)
        self._radio_group.adopt(btn)
        self._children.append(btn)
        if selected:
            self._radio_group.select(btn)
        return btn

    def collapsible(self, label: str, *,
                    affiliation: Optional[str] = None,
                    menu_level: int = 3,
                    expanded: bool = True,
                    on_click: Optional[Callable[[], None]] = None,
    ) -> UiCollapsibleList:
        c = UiCollapsibleList(parent_element=self.root, label=label,
                              affiliation=affiliation, menu_level=menu_level,
                              expanded=expanded, on_click=on_click)
        self._children.append(c)
        return c

    def clear(self) -> None:
        for child in self._children:
            child.destroy()  # type: ignore[attr-defined]
        self._children.clear()
        self._radio_group = _RadioGroup()

    def destroy(self) -> None:
        if self._destroyed:
            return
        bindings.destroy_panel(self.panel_id)
        self._destroyed = True
```

Update `engine/ui/__init__.py`:

```python
from . import bindings, theme
from .button import UiButton
from .collapsible import UiCollapsibleList
from .panel import UiPanel

__all__ = ["bindings", "theme", "UiButton", "UiCollapsibleList", "UiPanel"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/ui/test_panel.py -v`
Expected: all 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/ui/panel.py engine/ui/__init__.py tests/ui/test_panel.py
git commit -m "feat(ui): UiPanel root container with button/collapsible factories"
```

---

## Phase 7 — Theme propagation to bindings

### Task 13: Push CSS custom properties on panel init + theme change

**Files:**
- Modify: `engine/ui/panel.py`
- Modify: `engine/ui/theme.py`
- Modify: `tests/ui/test_panel.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/ui/test_panel.py`:

```python
def test_panel_sets_initial_css_vars_from_theme(fake_dom):
    panel = UiPanel(id="p")
    vars_ = fake_dom.panel_css_vars(panel.panel_id)
    # Affiliation defaults present
    assert vars_["--aff-enemy-color"]    == "rgb(216,43,43)"
    assert vars_["--aff-friendly-color"] == "rgb(80,112,230)"
    # Menu-level 3 defaults present
    assert vars_["--menu-3-normal"]      == "rgb(207,96,159)"
    assert vars_["--menu-3-highlighted"] == "rgb(246,147,204)"
    assert vars_["--menu-3-selected"]    == "rgb(103,48,79)"


def test_theme_change_after_panel_creation_repushes_vars(fake_dom):
    from engine.ui import theme
    panel = UiPanel(id="p")
    theme.set_affiliation("enemy", (1, 2, 3))
    try:
        # Caller pushes — there's no auto-watch
        panel.refresh_theme()
        assert fake_dom.panel_css_vars(panel.panel_id)["--aff-enemy-color"] \
            == "rgb(1,2,3)"
    finally:
        theme.reset_affiliations()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/ui/test_panel.py -v`
Expected: 2 new tests FAIL — initial vars not set; `refresh_theme` missing.

- [ ] **Step 3: Add a small `theme.css_var_pairs()` helper, then call it from UiPanel**

Append to `engine/ui/theme.py`:

```python
def _rgb_css(rgb: RGB) -> str:
    return "rgb({},{},{})".format(*rgb)


def css_var_pairs() -> dict[str, str]:
    """Return the full set of CSS custom properties driven by the registries.

    Names follow the conventions used in components.rcss:
      --aff-<name>-color
      --menu-<level>-normal / highlighted / selected
    """
    out: dict[str, str] = {}
    for name, rgb in _affiliation.items():
        out["--aff-" + name + "-color"] = _rgb_css(rgb)
    for level, p in _menu_levels.items():
        out["--menu-" + str(level) + "-normal"]      = _rgb_css(p.normal)
        out["--menu-" + str(level) + "-highlighted"] = _rgb_css(p.highlighted)
        out["--menu-" + str(level) + "-selected"]    = _rgb_css(p.selected)
    return out
```

Modify `engine/ui/panel.py` — append `refresh_theme()` method and call it from `__init__`:

```python
# inside class UiPanel
    def refresh_theme(self) -> None:
        """Push the current theme registry values to the panel's CSS variables."""
        from . import theme
        for name, value in theme.css_var_pairs().items():
            bindings.set_panel_css_var(self.panel_id, name, value)
```

And in `__init__`, after `self.panel_id = bindings.create_panel(...)`:

```python
        self.refresh_theme()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/ui/test_panel.py tests/ui/test_theme.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/ui/theme.py engine/ui/panel.py tests/ui/test_panel.py
git commit -m "feat(ui): panels push theme css vars on init and refresh_theme"
```

---

## Phase 8 — RCSS + RML assets

### Task 14: Write `components.rcss`

**Files:**
- Create: `native/assets/ui/components.rcss`

This is a pure asset; there's no Python or C++ test that hits it directly. We commit it now so the C++ binding work (next phase) can load it.

- [ ] **Step 1: Create the stylesheet**

```rcss
/* native/assets/ui/components.rcss
 * Styles for UiPanel, UiButton, UiCollapsibleList.
 * Color values are populated per-panel via CSS custom properties pushed
 * from engine.ui.theme.css_var_pairs().
 */

:root {
    /* Fallback values — real values pushed at runtime per panel. */
    --aff-enemy-color:    rgb(216,  43,  43);
    --aff-friendly-color: rgb( 80, 112, 230);
    --aff-neutral-color:  rgb(255, 255, 175);
    --aff-unknown-color:  rgb(127, 127, 127);

    --menu-1-normal:      rgb(216,  94,  86);
    --menu-1-highlighted: rgb(254, 120,  86);
    --menu-1-selected:    rgb(127,  60,  43);
    --menu-2-normal:      rgb(147, 103, 255);
    --menu-2-highlighted: rgb(173, 132, 255);
    --menu-2-selected:    rgb( 86,  66, 127);
    --menu-3-normal:      rgb(207,  96, 159);
    --menu-3-highlighted: rgb(246, 147, 204);
    --menu-3-selected:    rgb(103,  48,  79);
    --menu-4-normal:      rgb(144, 103, 144);
    --menu-4-highlighted: rgb(175, 144, 175);
    --menu-4-selected:    rgb( 72,  51,  72);

    --row-height: 4.5vh;
}

body {
    margin: 0dp;
    padding: 0dp;
    width: 100%;
    height: 100%;
    font-family: antonio;
    color: #e8e8d0;
}

.bc-panel {
    background-color: #2c2c2c;
    padding: 8dp;
    border-radius: 4dp;
}

/* ── Collapsible header ─────────────────────────────────────────────────── */

.bc-collapsible {
    display: block;
}

.bc-collapsible-header {
    height: var(--row-height);
    display: flex;
    align-items: center;
    color: #e8e8d0;
    font-size: 14dp;
    font-weight: 600;
    letter-spacing: 2dp;
    text-transform: uppercase;
    padding-right: 12dp;
    border-left-width: 3dp;
    border-left-style: solid;
    cursor: pointer;
}

/* Affiliation variants drive bg + border color */
.bc-collapsible-header.aff-enemy {
    background-color: rgba(216, 43, 43, 0.2);
    border-left-color: var(--aff-enemy-color);
}
.bc-collapsible-header.aff-friendly {
    background-color: rgba(80, 112, 230, 0.2);
    border-left-color: var(--aff-friendly-color);
}
.bc-collapsible-header.aff-neutral {
    background-color: rgba(255, 255, 175, 0.2);
    border-left-color: var(--aff-neutral-color);
}
.bc-collapsible-header.aff-unknown {
    background-color: rgba(127, 127, 127, 0.2);
    border-left-color: var(--aff-unknown-color);
}

/* Menu-level variants for non-affiliated collapsibles */
.bc-collapsible-header.menu-1 {
    background-color: rgba(216, 94, 86, 0.2);
    border-left-color: var(--menu-1-normal);
}
.bc-collapsible-header.menu-2 {
    background-color: rgba(147, 103, 255, 0.2);
    border-left-color: var(--menu-2-normal);
}
.bc-collapsible-header.menu-3 {
    background-color: rgba(207, 96, 159, 0.2);
    border-left-color: var(--menu-3-normal);
}
.bc-collapsible-header.menu-4 {
    background-color: rgba(144, 103, 144, 0.2);
    border-left-color: var(--menu-4-normal);
}

.bc-arrow {
    width: 28dp;
    height: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    color: inherit;
}

.bc-title {
    flex: 1;
}

.bc-collapsible-children {
    display: block;
}

/* ── Button ─────────────────────────────────────────────────────────────── */

.bc-button {
    height: var(--row-height);
    display: flex;
    align-items: center;
    background-color: #3a3a3a;
    color: #e0e0d8;
    font-size: 14dp;
    border-left-width: 6dp;
    border-left-style: solid;
    padding-left: 31dp;
    padding-right: 12dp;
    cursor: pointer;
    transition: border-left-width 0.18s ease-out,
                padding-left      0.18s ease-out,
                background-color  0.18s ease-out,
                color             0.18s ease-out,
                border-left-color 0.18s ease-out;
}

.bc-button.menu-1 { border-left-color: var(--menu-1-normal); }
.bc-button.menu-2 { border-left-color: var(--menu-2-normal); }
.bc-button.menu-3 { border-left-color: var(--menu-3-normal); }
.bc-button.menu-4 { border-left-color: var(--menu-4-normal); }

.bc-button.selected {
    color: #ffffff;
    border-left-width: 9dp;
    padding-left: 28dp;
}

.bc-button.menu-1.selected {
    background-color: rgba(127, 60, 43, 0.55);
    border-left-color: var(--menu-1-highlighted);
}
.bc-button.menu-2.selected {
    background-color: rgba(86, 66, 127, 0.65);
    border-left-color: var(--menu-2-highlighted);
}
.bc-button.menu-3.selected {
    background-color: rgba(103, 48, 79, 0.65);
    border-left-color: var(--menu-3-highlighted);
}
.bc-button.menu-4.selected {
    background-color: rgba(72, 51, 72, 0.70);
    border-left-color: var(--menu-4-highlighted);
}
```

- [ ] **Step 2: Commit**

```bash
git add native/assets/ui/components.rcss
git commit -m "feat(ui): components.rcss — button + collapsible styling"
```

---

### Task 15: Write `panel.rml` shell

**Files:**
- Create: `native/assets/ui/panel.rml`

- [ ] **Step 1: Create the shell**

```xml
<rml>
<head>
    <title>Panel</title>
    <link type="text/rcss" href="components.rcss"/>
</head>
<body>
    <div id="root" class="bc-panel"></div>
</body>
</rml>
```

- [ ] **Step 2: Commit**

```bash
git add native/assets/ui/panel.rml
git commit -m "feat(ui): panel.rml static shell loaded per-instance"
```

---

## Phase 9 — C++ PanelDocument

### Task 16: PanelDocument header

**Files:**
- Create: `native/src/ui/include/ui/PanelDocument.h`

- [ ] **Step 1: Define the class**

```cpp
// native/src/ui/include/ui/PanelDocument.h
#pragma once

#include <filesystem>
#include <functional>
#include <string>
#include <unordered_map>

namespace Rml {
    class Context;
    class ElementDocument;
    class Element;
}

namespace ui {

/// One PanelDocument owns one Rml::ElementDocument loaded from panel.rml.
/// Python composes the body dynamically via the binding primitives below;
/// the PanelDocument tracks element handles by integer id so binding calls
/// don't need to leak Rml::Element pointers into Python.
class PanelDocument {
public:
    PanelDocument(Rml::Context* context,
                  const std::filesystem::path& rml_path,
                  const std::string& anchor,
                  float width_vw, float height_vh);
    ~PanelDocument();

    PanelDocument(const PanelDocument&) = delete;
    PanelDocument& operator=(const PanelDocument&) = delete;

    /// The opaque id of the document's root element (the <div id="root">).
    int root_element_id() const { return root_id_; }

    /// Element-tree mutation primitives. Each returns / accepts integer
    /// element ids that are unique within this PanelDocument.
    int  append_div(int parent_id, const std::string& class_names);
    void remove_element(int element_id);
    void set_class(int element_id, const std::string& class_names);
    void set_text(int element_id, const std::string& text);
    void set_visible(int element_id, bool visible);

    /// Register a click callback for an element. Pass nullptr to clear.
    /// The callback is invoked synchronously when the element receives a
    /// "click" event (RmlUi raises this on left-mouse-button-up).
    void on_click(int element_id, std::function<void()> callback);

    /// Set a CSS custom property on the document root (applies to all
    /// descendants via `var()` references in components.rcss).
    void set_css_var(const std::string& name, const std::string& value);

    /// Clear all body children. The root element itself stays.
    void clear();

private:
    Rml::ElementDocument* doc_       = nullptr;
    Rml::Element*         root_       = nullptr;
    int                   root_id_    = 0;

    int                   next_id_    = 1;
    std::unordered_map<int, Rml::Element*>            elements_;
    std::unordered_map<int, std::function<void()>>    click_cbs_;

    class ClickListener;  // forward decl; defined in .cc
    std::unique_ptr<ClickListener> click_listener_;

    void recursive_drop_subtree(int element_id);
};

}  // namespace ui
```

- [ ] **Step 2: Commit**

```bash
git add native/src/ui/include/ui/PanelDocument.h
git commit -m "feat(ui): PanelDocument header"
```

---

### Task 17: PanelDocument implementation

**Files:**
- Create: `native/src/ui/PanelDocument.cc`
- Modify: `native/src/ui/CMakeLists.txt`

- [ ] **Step 1: Implement the class**

```cpp
// native/src/ui/PanelDocument.cc
#include "ui/PanelDocument.h"

#include <RmlUi/Core/Context.h>
#include <RmlUi/Core/ElementDocument.h>
#include <RmlUi/Core/Element.h>
#include <RmlUi/Core/EventListener.h>
#include <RmlUi/Core/Event.h>

#include <cstdio>
#include <memory>
#include <stdexcept>

namespace ui {

class PanelDocument::ClickListener : public Rml::EventListener {
public:
    explicit ClickListener(PanelDocument* owner) : owner_(owner) {}
    void ProcessEvent(Rml::Event& event) override {
        Rml::Element* target = event.GetCurrentElement();
        if (!target) return;
        // The element holds its id as an attribute "data-eid"
        const Rml::String& eid_str = target->GetAttribute<Rml::String>("data-eid", "");
        if (eid_str.empty()) return;
        int eid = std::atoi(eid_str.c_str());
        auto it = owner_->click_cbs_.find(eid);
        if (it != owner_->click_cbs_.end()) {
            it->second();
        }
    }
private:
    PanelDocument* owner_;
};

PanelDocument::PanelDocument(Rml::Context* context,
                             const std::filesystem::path& rml_path,
                             const std::string& anchor,
                             float width_vw, float height_vh)
    : click_listener_(std::make_unique<ClickListener>(this))
{
    doc_ = context->LoadDocument(rml_path.string());
    if (!doc_) {
        throw std::runtime_error("PanelDocument: failed to load " + rml_path.string());
    }

    // Apply anchor + size by setting inline style on the document body.
    Rml::Element* body = doc_->GetFirstChild();  // <body>
    if (body) {
        body->SetProperty("position", "absolute");
        body->SetProperty("width",  std::to_string(width_vw)  + "vw");
        body->SetProperty("height", std::to_string(height_vh) + "vh");
        if      (anchor == "top-left")     { body->SetProperty("left",  "0dp"); body->SetProperty("top",    "0dp"); }
        else if (anchor == "top-right")    { body->SetProperty("right", "0dp"); body->SetProperty("top",    "0dp"); }
        else if (anchor == "bottom-left")  { body->SetProperty("left",  "0dp"); body->SetProperty("bottom", "0dp"); }
        else if (anchor == "bottom-right") { body->SetProperty("right", "0dp"); body->SetProperty("bottom", "0dp"); }
    }

    root_ = doc_->GetElementById("root");
    if (!root_) {
        throw std::runtime_error("PanelDocument: panel.rml missing #root element");
    }
    root_id_ = next_id_++;
    elements_[root_id_] = root_;
    root_->SetAttribute<Rml::String>("data-eid", std::to_string(root_id_));

    doc_->Show();
}

PanelDocument::~PanelDocument() {
    if (doc_) {
        doc_->Close();
    }
}

int PanelDocument::append_div(int parent_id, const std::string& class_names) {
    auto parent_it = elements_.find(parent_id);
    if (parent_it == elements_.end()) {
        throw std::runtime_error("PanelDocument::append_div: invalid parent id");
    }
    Rml::ElementPtr el_ptr = doc_->CreateElement("div");
    Rml::Element* el = el_ptr.get();
    int eid = next_id_++;
    el->SetAttribute<Rml::String>("data-eid", std::to_string(eid));
    if (!class_names.empty()) {
        el->SetClassNames(class_names.c_str());
    }
    parent_it->second->AppendChild(std::move(el_ptr));
    elements_[eid] = el;
    return eid;
}

void PanelDocument::remove_element(int element_id) {
    auto it = elements_.find(element_id);
    if (it == elements_.end()) return;
    recursive_drop_subtree(element_id);
    Rml::Element* el = it->second;
    Rml::Element* parent = el->GetParentNode();
    if (parent) parent->RemoveChild(el);
    elements_.erase(it);
    click_cbs_.erase(element_id);
}

void PanelDocument::recursive_drop_subtree(int element_id) {
    auto it = elements_.find(element_id);
    if (it == elements_.end()) return;
    Rml::Element* el = it->second;
    for (int i = 0, n = el->GetNumChildren(); i < n; ++i) {
        Rml::Element* child = el->GetChild(i);
        if (!child) continue;
        const Rml::String& eid_str = child->GetAttribute<Rml::String>("data-eid", "");
        if (eid_str.empty()) continue;
        int child_eid = std::atoi(eid_str.c_str());
        recursive_drop_subtree(child_eid);
        elements_.erase(child_eid);
        click_cbs_.erase(child_eid);
    }
}

void PanelDocument::set_class(int element_id, const std::string& class_names) {
    auto it = elements_.find(element_id);
    if (it == elements_.end()) return;
    it->second->SetClassNames(class_names.c_str());
}

void PanelDocument::set_text(int element_id, const std::string& text) {
    auto it = elements_.find(element_id);
    if (it == elements_.end()) return;
    it->second->SetInnerRML(text.c_str());
}

void PanelDocument::set_visible(int element_id, bool visible) {
    auto it = elements_.find(element_id);
    if (it == elements_.end()) return;
    it->second->SetProperty("display", visible ? "block" : "none");
}

void PanelDocument::on_click(int element_id, std::function<void()> callback) {
    auto it = elements_.find(element_id);
    if (it == elements_.end()) return;
    Rml::Element* el = it->second;
    if (callback) {
        click_cbs_[element_id] = std::move(callback);
        el->AddEventListener("click", click_listener_.get());
    } else {
        click_cbs_.erase(element_id);
        el->RemoveEventListener("click", click_listener_.get());
    }
}

void PanelDocument::set_css_var(const std::string& name, const std::string& value) {
    if (!doc_) return;
    // RmlUi supports CSS custom properties via SetProperty; setting on the
    // document propagates to descendants.
    doc_->SetProperty(name.c_str(), value.c_str());
}

void PanelDocument::clear() {
    if (!root_) return;
    while (root_->GetNumChildren() > 0) {
        Rml::Element* child = root_->GetChild(0);
        if (!child) break;
        const Rml::String& eid_str = child->GetAttribute<Rml::String>("data-eid", "");
        int child_eid = eid_str.empty() ? 0 : std::atoi(eid_str.c_str());
        if (child_eid != 0) {
            recursive_drop_subtree(child_eid);
            elements_.erase(child_eid);
            click_cbs_.erase(child_eid);
        }
        root_->RemoveChild(child);
    }
}

}  // namespace ui
```

Add to `native/src/ui/CMakeLists.txt` — locate the existing `add_library(ui ...)` call and add `PanelDocument.cc` to the source list. Open the file and inspect — usually the existing list is `HudDocument.cc UiSystem.cc`. Add a third entry:

```cmake
add_library(ui
    HudDocument.cc
    UiSystem.cc
    PanelDocument.cc
)
```

(If the file uses target_sources or a glob, follow that pattern instead. The intent is: PanelDocument.cc compiles into the ui library.)

- [ ] **Step 2: Build to verify it compiles**

Run: `cd native && cmake --build build --target ui -j`
Expected: build succeeds without warnings or errors. If RmlUi headers are missing for any of the calls used above, address with the smallest possible additional include.

- [ ] **Step 3: Commit**

```bash
git add native/src/ui/PanelDocument.cc native/src/ui/CMakeLists.txt
git commit -m "feat(ui): PanelDocument implementation"
```

---

### Task 18: Wire UiSystem to host PanelDocuments

**Files:**
- Modify: `native/src/ui/include/ui/UiSystem.h`
- Modify: `native/src/ui/UiSystem.cc`

- [ ] **Step 1: Extend the header**

In `native/src/ui/include/ui/UiSystem.h`, add forward decl + methods:

```cpp
// Add near the existing forward-declarations
namespace ui { class PanelDocument; }

// Inside class UiSystem (public section), add:
public:
    /// Create a new PanelDocument. Returns a handle the bindings can use to
    /// reference it later. The system keeps ownership.
    int create_panel(const std::string& anchor, float width_vw, float height_vh);
    void destroy_panel(int panel_id);
    PanelDocument* get_panel(int panel_id);

// And in the private members, add the storage:
private:
    std::filesystem::path assets_root_;   // remembered for panel.rml lookup
    std::unordered_map<int, std::unique_ptr<PanelDocument>> panels_;
    int next_panel_id_ = 1;
```

(Include `<unordered_map>` and `<string>` if not already present. The `assets_root_` field is new — set it in the constructor.)

- [ ] **Step 2: Implement in UiSystem.cc**

Modify `native/src/ui/UiSystem.cc`:

1. Include `ui/PanelDocument.h` and `<unordered_map>` at the top.

2. In the constructor body, after the HudDocument is created, store the assets root:

```cpp
assets_root_ = assets_root;
```

3. Add the panel-management methods:

```cpp
int UiSystem::create_panel(const std::string& anchor,
                           float width_vw, float height_vh) {
    int id = next_panel_id_++;
    auto panel = std::make_unique<PanelDocument>(
        context_,
        assets_root_ / "panel.rml",
        anchor, width_vw, height_vh
    );
    panels_[id] = std::move(panel);
    return id;
}

void UiSystem::destroy_panel(int panel_id) {
    panels_.erase(panel_id);
}

PanelDocument* UiSystem::get_panel(int panel_id) {
    auto it = panels_.find(panel_id);
    return it == panels_.end() ? nullptr : it->second.get();
}
```

4. In the destructor, panels destruct automatically (unique_ptr).

- [ ] **Step 3: Build to verify**

Run: `cd native && cmake --build build --target ui -j`
Expected: build succeeds.

- [ ] **Step 4: Commit**

```bash
git add native/src/ui/include/ui/UiSystem.h native/src/ui/UiSystem.cc
git commit -m "feat(ui): UiSystem hosts PanelDocument instances"
```

---

## Phase 10 — pybind11 bindings

### Task 19: Expose panel + element primitives to Python

**Files:**
- Modify: `native/src/host/host_bindings.cc`
- Modify: `native/src/host/host_bindings.h` (if signatures live there)

- [ ] **Step 1: Locate the existing `PYBIND11_MODULE` block**

Run: `grep -n "PYBIND11_MODULE\|m.def(" /Users/mward/Documents/Projects/open_stbc/native/src/host/host_bindings.cc | head -30`

- [ ] **Step 2: Add the new `m.def` registrations**

Append to the bottom of the `PYBIND11_MODULE(_open_stbc_host, m)` block:

```cpp
    // ── UI panel + element primitives ───────────────────────────────────
    m.def("create_panel",
          [](const std::string& /*name*/, const std::string& anchor,
             float width_vw, float height_vh) -> int {
              if (!g_ui_system) {
                  throw std::runtime_error("create_panel: ui system not initialized");
              }
              return g_ui_system->create_panel(anchor, width_vw, height_vh);
          });

    m.def("destroy_panel", [](int panel_id) {
        if (!g_ui_system) return;
        g_ui_system->destroy_panel(panel_id);
    });

    m.def("clear_panel", [](int panel_id) {
        if (!g_ui_system) return;
        if (auto* p = g_ui_system->get_panel(panel_id)) p->clear();
    });

    m.def("panel_root", [](int panel_id) -> int {
        if (!g_ui_system) return 0;
        auto* p = g_ui_system->get_panel(panel_id);
        return p ? p->root_element_id() : 0;
    });

    m.def("set_panel_css_var",
          [](int panel_id, const std::string& name, const std::string& value) {
              if (!g_ui_system) return;
              if (auto* p = g_ui_system->get_panel(panel_id))
                  p->set_css_var(name, value);
          });

    m.def("append_div",
          [](int parent_id, const std::string& class_names) -> int {
              if (!g_ui_system) return 0;
              // Parent id is per-panel; we need to find which panel owns it.
              // Convention: parent_id is meaningful only to the panel that
              // returned it, so the binding caller (Python) is responsible
              // for keeping panel_id implicit by always working through
              // panel_root() first. We resolve by trying each panel.
              for (auto& [pid, panel] : g_ui_system->panels_for_bindings()) {
                  // Implementation guard — caller-supplied id must exist in
                  // exactly one panel. See PanelDocument::has_element below.
                  if (panel->has_element(parent_id)) {
                      return panel->append_div(parent_id, class_names);
                  }
              }
              throw std::runtime_error("append_div: parent_id not found in any panel");
          });

    m.def("remove_element", [](int element_id) {
        if (!g_ui_system) return;
        for (auto& [pid, panel] : g_ui_system->panels_for_bindings()) {
            if (panel->has_element(element_id)) { panel->remove_element(element_id); return; }
        }
    });

    m.def("set_class",
          [](int element_id, const std::string& class_names) {
              if (!g_ui_system) return;
              for (auto& [pid, panel] : g_ui_system->panels_for_bindings()) {
                  if (panel->has_element(element_id)) {
                      panel->set_class(element_id, class_names); return;
                  }
              }
          });

    m.def("set_text",
          [](int element_id, const std::string& text) {
              if (!g_ui_system) return;
              for (auto& [pid, panel] : g_ui_system->panels_for_bindings()) {
                  if (panel->has_element(element_id)) {
                      panel->set_text(element_id, text); return;
                  }
              }
          });

    m.def("set_visible",
          [](int element_id, bool visible) {
              if (!g_ui_system) return;
              for (auto& [pid, panel] : g_ui_system->panels_for_bindings()) {
                  if (panel->has_element(element_id)) {
                      panel->set_visible(element_id, visible); return;
                  }
              }
          });

    m.def("on_click",
          [](int element_id, py::object callback) {
              if (!g_ui_system) return;
              for (auto& [pid, panel] : g_ui_system->panels_for_bindings()) {
                  if (panel->has_element(element_id)) {
                      if (callback.is_none()) {
                          panel->on_click(element_id, nullptr);
                      } else {
                          panel->on_click(element_id, [callback]() {
                              py::gil_scoped_acquire gil;
                              callback();
                          });
                      }
                      return;
                  }
              }
          });
```

The above references `panel->has_element(eid)` and `g_ui_system->panels_for_bindings()`. Add both:

In `native/src/ui/include/ui/PanelDocument.h`, in the public section:

```cpp
    bool has_element(int element_id) const {
        return elements_.find(element_id) != elements_.end();
    }
```

In `native/src/ui/include/ui/UiSystem.h`, in the public section:

```cpp
    // Iterator access for bindings — keep internal to the binding layer.
    auto& panels_for_bindings() { return panels_; }
```

- [ ] **Step 3: Build the extension**

Run: `cd native && cmake --build build --target _open_stbc_host -j`
Expected: build succeeds.

- [ ] **Step 4: Smoke-import the extension from Python**

Run: `uv run python -c "import _open_stbc_host as h; print(hasattr(h, 'create_panel'))"`
Expected output: `True`

- [ ] **Step 5: Commit**

```bash
git add native/src/host/host_bindings.cc \
        native/src/ui/include/ui/UiSystem.h \
        native/src/ui/include/ui/PanelDocument.h
git commit -m "feat(ui): pybind11 bindings for panel + element primitives"
```

---

## Phase 11 — Production binding wire-up

### Task 20: Auto-bind to `_open_stbc_host` when present

**Files:**
- Modify: `engine/ui/bindings.py`
- Modify: `engine/ui/__init__.py`

The bindings facade currently has `_active_dom = None` until tests/init sets one. Production code should call `engine.ui.init()` to set it to the real `_open_stbc_host` module.

- [ ] **Step 1: Add init() to the facade**

Append to `engine/ui/bindings.py`:

```python
def init() -> None:
    """Bind to the real _open_stbc_host extension.

    Must be called after engine.renderer.init() (the C++ host_bindings::init
    creates the UiSystem). Idempotent.
    """
    global _active_dom
    import _open_stbc_host as _h
    _active_dom = _RealDom(_h)


class _RealDom:
    """Wrapper exposing the FakeDom-compatible surface over _open_stbc_host."""

    def __init__(self, mod) -> None:
        self._m = mod

    def create_panel(self, name, anchor, width_vw, height_vh):
        return self._m.create_panel(name, anchor, width_vw, height_vh)

    def destroy_panel(self, pid):           self._m.destroy_panel(pid)
    def clear_panel(self, pid):             self._m.clear_panel(pid)
    def panel_root(self, pid):              return self._m.panel_root(pid)
    def set_panel_css_var(self, pid, n, v): self._m.set_panel_css_var(pid, n, v)
    def append_div(self, parent, cls):      return self._m.append_div(parent, cls)
    def remove_element(self, eid):          self._m.remove_element(eid)
    def set_class(self, eid, cls):          self._m.set_class(eid, cls)
    def set_text(self, eid, text):          self._m.set_text(eid, text)
    def set_visible(self, eid, vis):        self._m.set_visible(eid, vis)
    def on_click(self, eid, cb):            self._m.on_click(eid, cb)
```

- [ ] **Step 2: Re-export from `engine/ui/__init__.py`**

```python
from . import bindings, theme
from .bindings import init
from .button import UiButton
from .collapsible import UiCollapsibleList
from .panel import UiPanel

__all__ = ["init", "bindings", "theme", "UiButton", "UiCollapsibleList", "UiPanel"]
```

- [ ] **Step 3: Verify tests still pass**

Run: `uv run pytest tests/ui/ -v`
Expected: all PASS — `_RealDom` only gets activated by `engine.ui.init()`, which tests don't call.

- [ ] **Step 4: Commit**

```bash
git add engine/ui/bindings.py engine/ui/__init__.py
git commit -m "feat(ui): engine.ui.init() binds facade to _open_stbc_host"
```

---

## Phase 12 — Live smoke test

### Task 21: Demo panel in host loop

**Files:**
- Modify: `engine/host_loop.py`

The goal is to confirm the panel actually renders in the live build. We add a small demo panel (Bird of Prey-1 + a few subsystems + a collapsed Galaxy) that appears next to the existing HUD.

- [ ] **Step 1: Add the demo panel to `run()`**

In `engine/host_loop.py`, inside `run()`, after `r.init(...)` and before the main `while not r.should_close()` loop, add:

```python
        # Demo UI panel — proves the components render. Remove once a real
        # consumer (mission picker, targets panel) replaces it.
        from engine import ui
        ui.init()
        demo_panel = ui.UiPanel(id="demo", anchor="top-right",
                                width_vw=18.0, height_vh=55.0)
        bop = demo_panel.collapsible("Bird of Prey-1", affiliation="enemy",
                                     expanded=True)
        bop.button("Shield Generator")
        bop.button("Warp Core", selected=True)
        bop.collapsible("Disruptor Cannons", menu_level=3, expanded=False)
        bop.button("Torpedoes")
        bop.button("Impulse Engines")
        bop.collapsible("Warp Engines", menu_level=3, expanded=False)
        bop.button("Cloaking Device")
        bop.button("Sensor Array")
        demo_panel.collapsible("USS Yamato", affiliation="friendly",
                               expanded=False)
        demo_panel.collapsible("Tellarite Caravan", affiliation="neutral",
                               expanded=False)
        demo_panel.collapsible("Subspace Echo 47", affiliation="unknown",
                               expanded=False)
```

- [ ] **Step 2: Build and run the host**

Run: `cd native && cmake --build build -j` then `uv run python -m engine.host_loop`
Expected: the renderer opens; the demo panel sits in the top-right and shows the Bird of Prey collapsible expanded over subsystem rows, with Warp Core highlighted in blue-tinted bg + thicker left border, and three additional collapsed rows below.

Click a different subsystem — it should become selected; Warp Core deselects. Click the arrow on a collapsed parent (Disruptor Cannons / Warp Engines / Galaxy / Tellarite / Subspace) — children should appear (empty in this demo).

If the panel isn't visible or text is wrong, debug *before* claiming success — eyeball check, not pixel-grep.

- [ ] **Step 3: Commit**

```bash
git add engine/host_loop.py
git commit -m "feat(ui): demo UI panel in host loop proves end-to-end rendering"
```

---

## Phase 13 — Documentation hook

### Task 22: Add CLAUDE.md cross-reference

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add a new section to the project's CLAUDE.md**

Open `CLAUDE.md` and locate the table of key reference material. Add a row:

```markdown
| UI components | `engine/ui/`, `docs/superpowers/specs/2026-05-11-ui-components-design.md` | Reusable Button + CollapsibleList; theme registries mirror LoadInterface.py |
```

If the table is structured differently in CLAUDE.md, follow the established pattern. The goal is one short line pointing at the new package + the design spec.

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: cross-reference UI component package + design spec"
```

---

## Closing checklist

After Task 22:

- [ ] Run the full test suite: `uv run pytest -v` — every existing test should still pass.
- [ ] Visual smoke test: launch the host loop and confirm the demo panel matches the visual contract in section 3 of the spec (left border 6px → 9px on select, content x-position fixed, affiliation colors correct, transitions feel smooth).
- [ ] If anything looks wrong on the visual side, fix `components.rcss` — that's where the visual contract lives. Re-test.
- [ ] Mention in the final commit message that this completes the spec at `docs/superpowers/specs/2026-05-11-ui-components-design.md`.

## Self-review notes

- **Spec coverage:** every section of the spec (theme registries, component API, visual contract, behavior, C++ bindings, testing, RML/RCSS) maps to at least one task. The "out of scope" items in spec §10 are explicitly *not* tasks.
- **Type consistency:** `UiButton`, `UiCollapsibleList`, `UiPanel`, `MenuPalette`, `_RadioGroup` names are stable across tasks. The binding contract (`append_div / remove_element / set_class / set_text / set_visible / on_click / set_panel_css_var / create_panel / destroy_panel / clear_panel / panel_root`) appears identically in FakeDom (Task 3), the Python facade (Task 4), the C++ PanelDocument (Tasks 16-17), and the pybind11 binding (Task 19). The `_RealDom` wrapper (Task 20) re-uses those same names.
- **TDD cycle:** every Python task follows "write failing test → run → implement → run → commit." C++ tasks are build-verified rather than unit-tested (consistent with existing native code patterns); visual verification happens in Task 21.
- **Open items from spec §11:** `--row-height` default 4.5vh is locked in components.rcss; arrow region is 28dp fixed-width; theme mutations apply retroactively via `set_panel_css_var` (CSS variable updates re-evaluate on next frame in RmlUi). All three answered during plan-writing.
