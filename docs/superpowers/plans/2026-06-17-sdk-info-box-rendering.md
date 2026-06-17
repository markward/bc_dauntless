# SDK Info-Box Rendering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render every `MissionLib.SetupInfoBoxFromParagraph` info box (tactical-view help, Scan, Hail, Orbit, …) as a dauntless-styled CEF modal with a working Close button, and make `TGParagraph` hold its real content.

**Architecture:** Two-tier mirror pattern — SDK builds a `_STStylizedWindow → TGPane → TGParagraph + STButton` tree on `TacticalControlWindow`; a new `InfoBoxPanel` observes it once per tick and emits a JSON snapshot to CEF; CEF Close clicks route back through the existing `STButton.SendActivationEvent → g_kEventManager → box.ProcessEvent` event path. `TGParagraph` gains an ordered segment stream so body text + inline key glyphs survive; `_STStylizedWindow.ProcessEvent` is wired to actually dispatch its registered handlers.

**Tech Stack:** Python 3 (headless shims under `engine/appc/`, panels under `engine/ui/`), pytest, CEF off-screen overlay (HTML/CSS/JS under `native/assets/ui-cef/`).

## Global Constraints

- **No LCARS / BC-font fidelity.** Dauntless re-style; SDK `(x, y)` coords accepted but ignored at render time.
- **Production path byte-identical when not loaded.** Panel is always-on (info boxes are gameplay UI), but renders nothing when no box is visible.
- **Reuse existing infra.** Event dispatch via `App.g_kEventManager` + `STButton.SendActivationEvent` (as `crew_menu_panel` does); stable CEF ids; `_resolve_handler` for `"module.func"` resolution.
- **Single source for `WC_*` values.** Defined once in `engine/appc/tg_ui/widgets.py`, re-exported through `tg_ui/__init__.py` and `App.py`.
- **WC values (verbatim):** `WC_BACKSPACE=8`, `WC_TAB=9`, `WC_LINEFEED=10`, `WC_RETURN=13`, `WC_SPACE=32`, `WC_CURSOR=0xE000`.
- **TGPF flag values (verbatim, already landed):** `TGPF_READ_ONLY=0x01`, `TGPF_INSERT_MODE=0x02`, `TGPF_WORD_WRAP=0x04`, `TGPF_RECALC_BOUNDS=0x08`, `TGPF_FLAGS_MASK=0x0F`.
- **Run tests with:** `uv run pytest <path> -v`.

---

### Task 1: `WC_*` wide-char constants

**Files:**
- Modify: `engine/appc/tg_ui/widgets.py` (add constants + `wc_to_str` near top, after `ensure_widget_id`)
- Modify: `engine/appc/tg_ui/__init__.py` (re-export)
- Modify: `App.py` (re-export in the existing `from engine.appc.tg_ui.widgets import (...)` block, ~line 24)
- Test: `tests/unit/test_wc_constants.py`

**Interfaces:**
- Produces: module constants `WC_BACKSPACE, WC_TAB, WC_LINEFEED, WC_RETURN, WC_SPACE, WC_CURSOR` (ints) and `wc_to_str(wc: int) -> str` in `engine.appc.tg_ui.widgets`; same names accessible as `App.WC_*`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_wc_constants.py
"""WC_* wide-char constants and wc_to_str mapping."""
import App
from engine.appc.tg_ui.widgets import wc_to_str


def test_wc_constant_values():
    assert App.WC_BACKSPACE == 8
    assert App.WC_TAB == 9
    assert App.WC_LINEFEED == 10
    assert App.WC_RETURN == 13
    assert App.WC_SPACE == 32
    assert App.WC_CURSOR == 0xE000


def test_wc_to_str_control_codes():
    assert wc_to_str(App.WC_RETURN) == "\n"
    assert wc_to_str(App.WC_LINEFEED) == "\n"
    assert wc_to_str(App.WC_SPACE) == " "
    assert wc_to_str(App.WC_TAB) == "\t"
    assert wc_to_str(App.WC_BACKSPACE) == ""
    assert wc_to_str(App.WC_CURSOR) == ""


def test_wc_to_str_printable():
    assert wc_to_str(ord("W")) == "W"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_wc_constants.py -v`
Expected: FAIL — `AttributeError: module 'App' has no attribute 'WC_BACKSPACE'` / `ImportError: cannot import name 'wc_to_str'`.

- [ ] **Step 3: Add constants + helper to widgets.py**

In `engine/appc/tg_ui/widgets.py`, immediately after the `ensure_widget_id` function (before `class TGPane`), add:

```python
# ── Wide-char (WC_*) constants ────────────────────────────────────────────────
# SDK paragraph code points. BC's Appc exports a full table; the shim defines
# only what scripts reference (faithful Unicode code points). WC_CURSOR marks an
# inline child-widget insertion point — BC's real value is engine-internal and
# never displayed, so a Unicode Private-Use-Area sentinel is used.
WC_BACKSPACE = 8
WC_TAB = 9
WC_LINEFEED = 10
WC_RETURN = 13
WC_SPACE = 32
WC_CURSOR = 0xE000

_WC_TO_STR = {
    WC_BACKSPACE: "",
    WC_TAB: "\t",
    WC_LINEFEED: "\n",
    WC_RETURN: "\n",
    WC_SPACE: " ",
    WC_CURSOR: "",
}


def wc_to_str(wc) -> str:
    """Map a WC_* code point to its display string (control codes → '' or
    whitespace; printable code points → the character)."""
    wc = int(wc)
    if wc in _WC_TO_STR:
        return _WC_TO_STR[wc]
    try:
        return chr(wc)
    except (ValueError, OverflowError):
        return ""
```

- [ ] **Step 4: Re-export from tg_ui/__init__.py**

In `engine/appc/tg_ui/__init__.py`, extend the `from engine.appc.tg_ui.widgets import (...)` block to add a new line before `ensure_widget_id,`:

```python
    WC_BACKSPACE, WC_TAB, WC_LINEFEED, WC_RETURN, WC_SPACE, WC_CURSOR, wc_to_str,
```

- [ ] **Step 5: Re-export from App.py**

In `App.py`, in the existing `from engine.appc.tg_ui.widgets import (...)` block (the one importing `TGParagraph`), add a line:

```python
    WC_BACKSPACE, WC_TAB, WC_LINEFEED, WC_RETURN, WC_SPACE, WC_CURSOR,
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_wc_constants.py -v`
Expected: PASS (3 tests).

- [ ] **Step 7: Commit**

```bash
git add engine/appc/tg_ui/widgets.py engine/appc/tg_ui/__init__.py App.py tests/unit/test_wc_constants.py
git commit -m "feat(spv): WC_* wide-char constants + wc_to_str for TGParagraph"
```

---

### Task 2: `TGParagraph` content stream

**Files:**
- Modify: `engine/appc/tg_ui/widgets.py:134-148` (the `TGParagraph` class body)
- Test: `tests/unit/test_tg_paragraph_segments.py`

**Interfaces:**
- Consumes: `wc_to_str`, `WC_RETURN`, `WC_SPACE` from Task 1 (same module).
- Produces: `TGParagraph` with `_segments: list[tuple[str, object]]`; methods `AppendStringW(s)`, `AppendString(s)` (alias), `AppendChar(wc)`, `AddChild(child, x, y, *_)`, `iter_segments() -> list`, `GetText() -> str`, `SetText(s)`, `SetStringW(s)` (alias). Segment kinds: `("text", str)`, `("char", int)`, `("child", TGParagraph)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_tg_paragraph_segments.py
"""TGParagraph ordered segment stream."""
import App
from engine.appc.tg_ui.widgets import TGParagraph, TGParagraph_CreateW


def test_constructor_text_is_first_segment():
    p = TGParagraph("Hello")
    assert p.iter_segments() == [("text", "Hello")]
    assert p.GetText() == "Hello"


def test_empty_constructor_has_no_segments():
    p = TGParagraph()
    assert p.iter_segments() == []
    assert p.GetText() == ""


def test_append_string_and_char_preserve_order():
    p = TGParagraph("A")
    p.AppendChar(App.WC_RETURN)
    p.AppendStringW("B")
    assert p.iter_segments() == [("text", "A"), ("char", 13), ("text", "B")]
    assert p.GetText() == "A\nB"


def test_add_child_records_segment_and_tgpane_child():
    parent = TGParagraph("Press ")
    glyph = TGParagraph("W")
    parent.AddChild(glyph)
    parent.AppendStringW(" to go")
    segs = parent.iter_segments()
    assert segs[0] == ("text", "Press ")
    assert segs[1] == ("child", glyph)
    assert segs[2] == ("text", " to go")
    # GetText flattens the child inline
    assert parent.GetText() == "Press W to go"
    # TGPane container contract still satisfied (child also in _children)
    assert glyph in [c for (c, _x, _y) in parent.GetChildren()]


def test_set_text_resets_segments():
    p = TGParagraph("A")
    p.AppendStringW("B")
    p.SetText("C")
    assert p.iter_segments() == [("text", "C")]
    assert p.GetText() == "C"


def test_createw_factory_builds_paragraph_with_flags():
    p = TGParagraph_CreateW("hi", 0.5, App.NiColorA_WHITE, "", 0.0,
                            TGParagraph.TGPF_READ_ONLY | TGParagraph.TGPF_WORD_WRAP)
    assert p.GetText() == "hi"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_tg_paragraph_segments.py -v`
Expected: FAIL — `AttributeError: 'TGParagraph' object has no attribute 'iter_segments'` (and `AppendChar`/`AppendStringW` missing).

- [ ] **Step 3: Rewrite the TGParagraph class body**

In `engine/appc/tg_ui/widgets.py`, replace the body of `class TGParagraph(TGPane):` from `def __init__` through `def SetColor` (keep the `TGPF_*` class constants and the docstring above them) with:

```python
    def __init__(self, text: str = "", scale: float = 1.0, color=None):
        super().__init__()
        # Ordered content stream: ("text", str) | ("char", int) | ("child", TGParagraph)
        self._segments: list = []
        if text:
            self._segments.append(("text", str(text)))
        self._scale = float(scale)
        self._color = color

    def AppendStringW(self, text) -> None:
        self._segments.append(("text", str(text)))

    # SDK also calls the non-W name in a few places.
    AppendString = AppendStringW

    def AppendChar(self, wc) -> None:
        self._segments.append(("char", int(wc)))

    def AddChild(self, child, x: float = 0.0, y: float = 0.0, *_extra) -> None:
        # Keep the TGPane container contract (child lands on _children) AND
        # record positionally in the segment stream so inline glyphs render
        # in call order relative to surrounding text.
        super().AddChild(child, x, y)
        self._segments.append(("child", child))

    def iter_segments(self) -> list:
        """dauntless-internal: the ordered (kind, value) content stream."""
        return list(self._segments)

    def GetText(self) -> str:
        out = []
        for kind, val in self._segments:
            if kind == "text":
                out.append(val)
            elif kind == "char":
                out.append(wc_to_str(val))
            elif kind == "child":
                out.append(val.GetText())
        return "".join(out)

    def SetText(self, text) -> None:
        self._segments = [("text", str(text))] if text else []

    # SDK W-variant setter name used by some callers.
    SetStringW = SetText

    def SetFont(self, *args) -> None:   pass
    def SetColor(self, color) -> None:  self._color = color
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_tg_paragraph_segments.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Run the existing widget/UI suites for regressions**

Run: `uv run pytest tests/unit/test_stylized_window.py tests/unit/test_top_window.py -v`
Expected: PASS (these construct paragraphs via `GetNameParagraph`; `GetText`/`SetText` remain compatible).

- [ ] **Step 6: Commit**

```bash
git add engine/appc/tg_ui/widgets.py tests/unit/test_tg_paragraph_segments.py
git commit -m "feat(spv): TGParagraph ordered segment stream (text/char/child)"
```

---

### Task 3: `_STStylizedWindow.ProcessEvent` wiring fix

**Files:**
- Modify: `engine/appc/windows.py` (add `ProcessEvent` to `_STStylizedWindow`, near its `AddPythonFuncHandlerForInstance` at ~line 306)
- Test: `tests/unit/test_st_stylized_window_process_event.py`

**Interfaces:**
- Consumes: `engine.appc.events._resolve_handler(qualified_name) -> callable|None`; `_STStylizedWindow._handler_registrations: list[tuple[int, str]]`.
- Produces: `_STStylizedWindow.ProcessEvent(event)` — invokes each registered `"module.func"` handler whose event type matches `event.GetEventType()`, calling `func(self, event)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_st_stylized_window_process_event.py
"""_STStylizedWindow dispatches its registered per-instance handlers."""
import sys
import types

import App
from engine.appc.windows import _STStylizedWindow


def _make_handler_module():
    mod = types.ModuleType("_tmp_infobox_handlers")
    mod.calls = []
    def on_close(obj, event):
        mod.calls.append((obj, event))
    mod.on_close = on_close
    sys.modules[mod.__name__] = mod
    return mod


def test_process_event_invokes_registered_handler():
    mod = _make_handler_module()
    try:
        w = _STStylizedWindow("X")
        w.AddPythonFuncHandlerForInstance(App.ET_INPUT_CLOSE_MENU,
                                          "_tmp_infobox_handlers.on_close")
        ev = App.TGEvent_Create()
        ev.SetEventType(App.ET_INPUT_CLOSE_MENU)
        ev.SetDestination(w)
        w.ProcessEvent(ev)
        assert len(mod.calls) == 1
        assert mod.calls[0][0] is w
    finally:
        del sys.modules["_tmp_infobox_handlers"]


def test_process_event_ignores_non_matching_type():
    mod = _make_handler_module()
    try:
        w = _STStylizedWindow("X")
        w.AddPythonFuncHandlerForInstance(App.ET_INPUT_CLOSE_MENU,
                                          "_tmp_infobox_handlers.on_close")
        ev = App.TGEvent_Create()
        ev.SetEventType(App.ET_INPUT_FIRE_PRIMARY)
        ev.SetDestination(w)
        w.ProcessEvent(ev)
        assert mod.calls == []
    finally:
        del sys.modules["_tmp_infobox_handlers"]


def test_process_event_with_no_handlers_is_inert():
    w = _STStylizedWindow("X")
    ev = App.TGEvent_Create()
    ev.SetEventType(App.ET_INPUT_CLOSE_MENU)
    ev.SetDestination(w)
    w.ProcessEvent(ev)  # must not raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_st_stylized_window_process_event.py -v`
Expected: FAIL — the inherited `ProcessEvent` reads `self._handlers` (empty, because the override writes to `_handler_registrations`), so `mod.calls` stays empty.

- [ ] **Step 3: Add ProcessEvent to _STStylizedWindow**

In `engine/appc/windows.py`, inside `class _STStylizedWindow`, directly after the `AddPythonFuncHandlerForInstance` method (the one appending to `_handler_registrations`), add:

```python
    def ProcessEvent(self, event) -> None:
        # The base TGEventHandlerObject.ProcessEvent dispatches from _handlers,
        # but this class records handlers in _handler_registrations (kept as the
        # introspection surface for the future click-dispatch spec). Dispatch
        # from that list so the Close button's ET_INPUT_CLOSE_MENU event reaches
        # MissionLib.CloseInfoBox + the mission's own handler.
        from engine.appc.events import _resolve_handler
        etype = event.GetEventType()
        for reg_type, qualified_name in list(self._handler_registrations):
            if reg_type != etype:
                continue
            fn = _resolve_handler(qualified_name)
            if fn is not None:
                fn(self, event)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_st_stylized_window_process_event.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Run existing stylized-window suite for regressions**

Run: `uv run pytest tests/unit/test_stylized_window.py -v`
Expected: PASS (the `_handler_registrations` introspection test is unaffected).

- [ ] **Step 6: Commit**

```bash
git add engine/appc/windows.py tests/unit/test_st_stylized_window_process_event.py
git commit -m "fix(spv): _STStylizedWindow.ProcessEvent dispatches registered handlers"
```

---

### Task 4: `InfoBoxPanel` — observation + serialization

**Files:**
- Create: `engine/ui/info_box_panel.py`
- Test: `tests/unit/test_info_box_panel.py`

**Interfaces:**
- Consumes: `engine.ui.panel.Panel`; `engine.appc.windows._STStylizedWindow`, `TacticalControlWindow`; `engine.appc.characters.STButton`; `engine.appc.tg_ui.widgets.TGParagraph`, `wc_to_str`.
- Produces: `InfoBoxPanel(Panel)` with `name == "info-box"`, `render_payload() -> str|None` emitting `setInfoBoxes({"entries":[...]})`, `dispatch_event(action) -> bool` (Task 5), `invalidate()`. Module helpers `_find_first(widget, predicate)`, `_serialize_body(paragraph) -> list`, `_color_to_list(color) -> list|None`. Entry shape: `{"id": str, "title": str, "body": [{"kind":"text","text":str} | {"kind":"key","text":str,"color":[r,g,b,a]|None}], "button": {"id": str, "label": str} | None}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_info_box_panel.py
"""InfoBoxPanel observation + serialization."""
import json

import pytest

import App
from engine.appc.windows import _STStylizedWindow, TacticalControlWindow
from engine.appc.tg_ui.widgets import TGParagraph
from engine.appc.characters import STButton
from engine.ui.info_box_panel import InfoBoxPanel


@pytest.fixture(autouse=True)
def _clean_tcw():
    tcw = TacticalControlWindow.GetInstance()
    tcw._children.clear()
    _STStylizedWindow._counter = 0
    yield
    tcw._children.clear()


def _build_box(title="Tactical View Help", visible=True):
    box = _STStylizedWindow(title)
    pane = App.TGPane_Create(100.0, 100.0)
    body = TGParagraph("Use these keys:")
    body.AppendChar(App.WC_RETURN)
    glyph = TGParagraph("W")
    glyph.SetColor(App.NiColorA_WHITE)
    body.AddChild(glyph)
    body.AppendStringW(" accelerate")
    pane.AddChild(body)
    pane.AddChild(STButton("Close"))
    box.AddChild(pane)
    if not visible:
        box.SetNotVisible()
    TacticalControlWindow.GetInstance().AddChild(box)
    return box


def _entries(panel):
    js = panel.render_payload()
    assert js.startswith("setInfoBoxes(")
    return json.loads(js[len("setInfoBoxes("):-2])["entries"]


def test_visible_box_is_serialized():
    box = _build_box()
    entries = _entries(InfoBoxPanel())
    assert len(entries) == 1
    e = entries[0]
    assert e["id"] == box._id
    assert e["title"] == "Tactical View Help"
    assert e["button"]["label"] == "Close"
    assert e["button"]["id"] == box._id


def test_body_segments_and_key_chip():
    _build_box()
    body = _entries(InfoBoxPanel())[0]["body"]
    assert {"kind": "text", "text": "Use these keys:"} in body
    assert {"kind": "text", "text": "\n"} in body
    key = [s for s in body if s["kind"] == "key"]
    assert len(key) == 1
    assert key[0]["text"] == "W"
    assert key[0]["color"] == [1.0, 1.0, 1.0, 1.0]
    assert {"kind": "text", "text": " accelerate"} in body


def test_hidden_box_is_not_serialized():
    _build_box(visible=False)
    assert _entries(InfoBoxPanel()) == []


def test_dedup_returns_none_when_unchanged():
    _build_box()
    panel = InfoBoxPanel()
    assert panel.render_payload() is not None
    assert panel.render_payload() is None


def test_invalidate_forces_reemit():
    _build_box()
    panel = InfoBoxPanel()
    panel.render_payload()
    panel.invalidate()
    assert panel.render_payload() is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_info_box_panel.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.ui.info_box_panel'`.

- [ ] **Step 3: Create the panel**

```python
# engine/ui/info_box_panel.py
"""InfoBoxPanel — renders SDK info boxes (MissionLib.SetupInfoBoxFromParagraph)
as dauntless-styled CEF modals.

Observes _STStylizedWindow children parented to TacticalControlWindow, serializes
each visible one (title + body segment stream + Close button), and routes CEF
Close clicks back through STButton.SendActivationEvent — the same event path the
crew-menu panel uses.

Spec: docs/superpowers/specs/2026-06-17-sdk-info-box-rendering-design.md
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from engine.ui.panel import Panel
from engine.appc.tg_ui.widgets import TGParagraph, wc_to_str

_logger = logging.getLogger(__name__)


def _color_to_list(color):
    """Best-effort RGBA list from a TGColorA/NiColorA; None when absent."""
    if color is None:
        return None
    if hasattr(color, "r") and hasattr(color, "g") \
            and hasattr(color, "b") and hasattr(color, "a"):
        return [color.r, color.g, color.b, color.a]
    return None


def _find_first(widget, predicate):
    """Breadth-first search for the first descendant (incl. widget itself)
    matching predicate. Walks both TGPane (child, x, y) tuples and bare-child
    lists, so it works across the mixed STStylizedWindow/TGPane hierarchy."""
    queue = [widget]
    while queue:
        w = queue.pop(0)
        if w is None:
            continue
        if predicate(w):
            return w
        children = getattr(w, "_children", None)
        if children:
            for c in children:
                queue.append(c[0] if isinstance(c, tuple) else c)
    return None


def _serialize_body(paragraph) -> list:
    body = []
    for kind, val in paragraph.iter_segments():
        if kind == "text":
            if val:
                body.append({"kind": "text", "text": val})
        elif kind == "char":
            s = wc_to_str(val)
            if s:
                body.append({"kind": "text", "text": s})
        elif kind == "child":
            body.append({
                "kind": "key",
                "text": val.GetText(),
                "color": _color_to_list(getattr(val, "_color", None)),
            })
    return body


class InfoBoxPanel(Panel):
    def __init__(self):
        super().__init__()
        self._last_pushed: Optional[str] = json.dumps({"entries": []})
        self._boxes_by_id: dict = {}

    @property
    def name(self) -> str:
        return "info-box"

    def render_payload(self) -> Optional[str]:
        from engine.appc.windows import _STStylizedWindow, TacticalControlWindow
        from engine.appc.characters import STButton

        entries: list = []
        self._boxes_by_id = {}
        for (child, _x, _y) in TacticalControlWindow.GetInstance()._children:
            if not isinstance(child, _STStylizedWindow):
                continue
            if not child.IsVisible():
                continue
            self._boxes_by_id[child._id] = child
            paragraph = _find_first(child, lambda w: isinstance(w, TGParagraph))
            button = _find_first(child, lambda w: isinstance(w, STButton))
            entry = {
                "id": child._id,
                "title": child._title,
                "body": _serialize_body(paragraph) if paragraph is not None else [],
                "button": None,
            }
            if button is not None:
                entry["button"] = {"id": child._id, "label": button.GetLabel()}
            entries.append(entry)

        payload = json.dumps({"entries": entries})
        if payload == self._last_pushed:
            return None
        self._last_pushed = payload
        return "setInfoBoxes(" + payload + ");"

    def dispatch_event(self, action: str) -> bool:
        # Implemented in Task 5.
        return False

    def invalidate(self) -> None:
        self._last_pushed = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_info_box_panel.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add engine/ui/info_box_panel.py tests/unit/test_info_box_panel.py
git commit -m "feat(spv): InfoBoxPanel observes + serializes SDK info boxes"
```

---

### Task 5: `InfoBoxPanel.dispatch_event` + close round-trip

**Files:**
- Modify: `engine/ui/info_box_panel.py` (replace the `dispatch_event` stub)
- Test: `tests/integration/test_info_box_close_round_trip.py`

**Interfaces:**
- Consumes: `STButton.SendActivationEvent()` (fires `self._event` via `App.g_kEventManager.AddEvent`); `_STStylizedWindow.ProcessEvent` (Task 3); `self._boxes_by_id` populated by `render_payload` (Task 4).
- Produces: `dispatch_event("close:<box_id>") -> True` — finds the box's `STButton` and calls `SendActivationEvent()`; stale id logged + dropped (still returns `True`); non-`close:` actions return `False`.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_info_box_close_round_trip.py
"""CEF close click → real SDK close event → box hidden + handler ran."""
import sys
import types

import pytest

import App
from engine.appc.windows import _STStylizedWindow, TacticalControlWindow
from engine.appc.tg_ui.widgets import TGParagraph
from engine.appc.characters import STButton
from engine.ui.info_box_panel import InfoBoxPanel


@pytest.fixture(autouse=True)
def _clean_tcw():
    tcw = TacticalControlWindow.GetInstance()
    tcw._children.clear()
    _STStylizedWindow._counter = 0
    yield
    tcw._children.clear()


def _close_handler_module():
    mod = types.ModuleType("_tmp_infobox_close")
    mod.closed = []

    def CloseInfoBox(box, event):
        box.SetNotVisible()
        mod.closed.append(box)

    mod.CloseInfoBox = CloseInfoBox
    sys.modules[mod.__name__] = mod
    return mod


def _build_box():
    # Mirrors MissionLib.SetupInfoBoxFromParagraph structure.
    box = _STStylizedWindow("Tactical View Help")
    pane = App.TGPane_Create(100.0, 100.0)
    pane.AddChild(TGParagraph("body"))
    close_event = App.TGEvent_Create()
    close_event.SetEventType(App.ET_INPUT_CLOSE_MENU)
    close_event.SetDestination(box)
    pane.AddChild(STButton("Close", close_event))
    box.AddChild(pane)
    box.AddPythonFuncHandlerForInstance(App.ET_INPUT_CLOSE_MENU,
                                        "_tmp_infobox_close.CloseInfoBox")
    box.SetVisible()
    TacticalControlWindow.GetInstance().AddChild(box)
    return box


def test_close_click_hides_box_and_runs_handler():
    mod = _close_handler_module()
    try:
        box = _build_box()
        panel = InfoBoxPanel()
        panel.render_payload()                     # populates _boxes_by_id
        assert panel.dispatch_event("close:" + box._id) is True
        assert mod.closed == [box]                 # SDK close handler ran
        assert box.IsVisible() == 0                 # box hidden
        panel.invalidate()
        # Box no longer serialized once hidden.
        import json
        js = panel.render_payload()
        assert json.loads(js[len("setInfoBoxes("):-2])["entries"] == []
    finally:
        del sys.modules["_tmp_infobox_close"]


def test_stale_close_id_dropped():
    panel = InfoBoxPanel()
    panel.render_payload()
    assert panel.dispatch_event("close:nonexistent") is True


def test_non_close_action_not_handled():
    panel = InfoBoxPanel()
    assert panel.dispatch_event("expand:1") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_info_box_close_round_trip.py -v`
Expected: FAIL — `dispatch_event` returns `False` for `close:` (stub), so the first assert fails.

- [ ] **Step 3: Implement dispatch_event**

In `engine/ui/info_box_panel.py`, replace the `dispatch_event` stub body with:

```python
    def dispatch_event(self, action: str) -> bool:
        if action.startswith("close:"):
            box_id = action[len("close:"):]
            box = self._boxes_by_id.get(box_id)
            if box is None:
                # Box rebuilt/removed between frames — drop; next snapshot
                # repairs the UI.
                _logger.info("info-box: stale close id %s dropped", box_id)
                return True
            from engine.appc.characters import STButton
            button = _find_first(box, lambda w: isinstance(w, STButton))
            if button is not None:
                button.SendActivationEvent()
            return True
        return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/integration/test_info_box_close_round_trip.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Run the full info-box unit + integration set**

Run: `uv run pytest tests/unit/test_info_box_panel.py tests/integration/test_info_box_close_round_trip.py tests/unit/test_tg_paragraph_segments.py tests/unit/test_st_stylized_window_process_event.py tests/unit/test_wc_constants.py -v`
Expected: PASS (all).

- [ ] **Step 6: Commit**

```bash
git add engine/ui/info_box_panel.py tests/integration/test_info_box_close_round_trip.py
git commit -m "feat(spv): InfoBoxPanel close dispatch routes through real SDK event"
```

---

### Task 6: CEF slot + host-loop registration + manual verification

**Files:**
- Create: `native/assets/ui-cef/js/info_box.js`
- Create: `native/assets/ui-cef/css/info_box.css`
- Modify: `native/assets/ui-cef/index.html` (add slot div ~after line 265; add `<link>` ~after line 14; add `<script>` ~after line 278)
- Modify: `engine/host_loop.py` (register `InfoBoxPanel` ~after the `crew_menu_panel` registration at line 2739)

**Interfaces:**
- Consumes: `InfoBoxPanel` (Task 4/5); CEF globals `dauntlessEvent(name)`; PanelRegistry routing (prefix `info-box`, action `close:<id>`).
- Produces: `setInfoBoxes(payload)` JS global rendering the `#sdk-infobox` slot; a registered `InfoBoxPanel` instance in the host loop.

- [ ] **Step 1: Create info_box.js**

```javascript
// native/assets/ui-cef/js/info_box.js
// Renders SDK info boxes (MissionLib.SetupInfoBoxFromParagraph) into
// #sdk-infobox. Payload: {entries:[{id,title,body[],button}]}. Close clicks
// fire info-box/close:<id> back to InfoBoxPanel.dispatch_event.
// Spec: docs/superpowers/specs/2026-06-17-sdk-info-box-rendering-design.md
function setInfoBoxes(payload) {
    var slot = document.getElementById("sdk-infobox");
    if (!slot) { return; }
    var data = (typeof payload === "string") ? JSON.parse(payload) : payload;
    var entries = (data && data.entries) || [];
    slot.innerHTML = "";

    entries.forEach(function (entry) {
        var modal = document.createElement("div");
        modal.className = "info-box-modal";

        var title = document.createElement("div");
        title.className = "info-box-title";
        title.textContent = entry.title || "";
        modal.appendChild(title);

        var body = document.createElement("div");
        body.className = "info-box-body";
        (entry.body || []).forEach(function (seg) {
            if (seg.kind === "key") {
                var chip = document.createElement("span");
                chip.className = "info-box-key";
                chip.textContent = seg.text;
                if (seg.color) {
                    chip.style.color = "rgba(" +
                        Math.round(seg.color[0] * 255) + "," +
                        Math.round(seg.color[1] * 255) + "," +
                        Math.round(seg.color[2] * 255) + "," +
                        seg.color[3] + ")";
                }
                body.appendChild(chip);
            } else {
                // Preserve newlines from the segment stream.
                seg.text.split("\n").forEach(function (line, i) {
                    if (i > 0) { body.appendChild(document.createElement("br")); }
                    body.appendChild(document.createTextNode(line));
                });
            }
        });
        modal.appendChild(body);

        if (entry.button) {
            var btn = document.createElement("button");
            btn.className = "info-box-close";
            btn.textContent = entry.button.label || "Close";
            btn.onclick = function () {
                dauntlessEvent("info-box/close:" + entry.button.id);
            };
            modal.appendChild(btn);
        }

        slot.appendChild(modal);
    });
}
```

- [ ] **Step 2: Create info_box.css**

```css
/* native/assets/ui-cef/css/info_box.css
   Centred dauntless-styled modal stack for SDK info boxes. Re-style, not LCARS. */
#sdk-infobox {
    position: absolute;
    top: 0; left: 0; right: 0; bottom: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 16px;
    pointer-events: none;       /* slot is transparent; modals re-enable */
    z-index: 40;                /* above 3D scene + mirror, below pause menu */
}
.info-box-modal {
    pointer-events: auto;
    min-width: 340px;
    max-width: 560px;
    background: rgba(8, 18, 30, 0.92);
    border: 1px solid #2f6f9f;
    border-radius: 6px;
    box-shadow: 0 4px 24px rgba(0, 0, 0, 0.5);
    color: #cfe6f5;
    font-family: sans-serif;
    padding: 14px 18px 16px;
}
.info-box-title {
    font-size: 16px;
    font-weight: 600;
    color: #8fd0ff;
    border-bottom: 1px solid #2f6f9f;
    padding-bottom: 6px;
    margin-bottom: 10px;
}
.info-box-body {
    font-size: 13px;
    line-height: 1.5;
}
.info-box-key {
    display: inline-block;
    border: 1px solid #5a93bf;
    border-radius: 3px;
    padding: 0 5px;
    margin: 0 2px;
    font-weight: 600;
    background: rgba(47, 111, 159, 0.25);
}
.info-box-close {
    margin-top: 14px;
    padding: 5px 16px;
    background: rgba(47, 111, 159, 0.4);
    color: #e6f3ff;
    border: 1px solid #5a93bf;
    border-radius: 4px;
    cursor: pointer;
    font-size: 13px;
}
.info-box-close:hover { background: rgba(90, 147, 191, 0.6); }
```

- [ ] **Step 3: Wire the slot into index.html**

In `native/assets/ui-cef/index.html`:

After the `<link rel="stylesheet" href="css/reticle_text.css">` line (~line 15), add:
```html
    <link rel="stylesheet" href="css/info_box.css">
```

After the `<div id="sdk-stylized-stack" class="sdk-mirror"></div>` line (~line 265), add:
```html
    <!-- #sdk-infobox: centred modal stack for MissionLib info boxes.
         Spec: docs/superpowers/specs/2026-06-17-sdk-info-box-rendering-design.md -->
    <div id="sdk-infobox"></div>
```

After the `<script src="js/ship_property_viewer.js"></script>` line (~line 278), add:
```html
    <script src="js/info_box.js"></script>
```

- [ ] **Step 4: Register the panel in the host loop**

In `engine/host_loop.py`, immediately after the `registry.register(crew_menu_panel)` block (the `crew_menu_hotkeys.wire(...)` try/except ends ~line 2748), add:

```python
        from engine.ui.info_box_panel import InfoBoxPanel
        info_box_panel = InfoBoxPanel()
        registry.register(info_box_panel)
```

- [ ] **Step 5: Rebuild (CEF assets are copied at configure time)**

Run: `cmake -B build -S . && cmake --build build -j`
Expected: build succeeds; `native/assets/ui-cef/*` (incl. the new `info_box.js`/`.css` and edited `index.html`) are staged into the runtime asset dir.

- [ ] **Step 6: Manual verification — load E1M1**

Run: `./build/dauntless --developer`
Then load `Maelstrom.Episode1.E1M1.E1M1` (via the dev "Load Mission…" picker).
Expected:
- No `AttributeError` in the console during mission init (the original crash is gone).
- When the tactical-view help box opens, a centred modal shows the title "Tactical View Help", body text with the movement keys as bordered chips, and a "Close" button.
- Clicking **Close** dismisses the modal and it does not reappear (the mission's `TacticalInfoBoxClosed` flag is set).

- [ ] **Step 7: Commit**

```bash
git add native/assets/ui-cef/js/info_box.js native/assets/ui-cef/css/info_box.css native/assets/ui-cef/index.html engine/host_loop.py
git commit -m "feat(spv): render SDK info boxes in CEF + register InfoBoxPanel"
```

---

## Self-Review

**Spec coverage:**
- Goal 1 (TGParagraph real content) → Task 2. ✅
- Goal 2 (render visible info boxes) → Tasks 4, 6. ✅
- Goal 3 (close loop) → Tasks 3, 5, 6. ✅
- Goal 4 (unblock loading) → Task 6 Step 6 (manual E1M1) + Task 1 (TGPF/WC). ✅
- `WC_*` constants → Task 1. ✅
- Segment stream model → Task 2. ✅
- `InfoBoxPanel` (observe/serialize/dispatch/invalidate) → Tasks 4, 5. ✅
- Wiring fix → Task 3. ✅
- CEF slot + re-style → Task 6. ✅
- Non-goals (no LCARS, no general click router, no save/load, no ESC) → respected; nothing implements them.

**Placeholder scan:** No TBD/TODO; every code step shows full code.

**Type consistency:** Entry shape (`id`/`title`/`body`/`button`) identical across Tasks 4, 5, 6. `dispatch_event("close:<id>")` action string matches the JS `dauntlessEvent("info-box/close:" + id)` (PanelRegistry strips the `info-box/` prefix). `_find_first`/`_serialize_body`/`_color_to_list` defined in Task 4, reused in Task 5. `wc_to_str` defined Task 1, used in Tasks 2 and 4. Box id is `_STStylizedWindow._id` everywhere.
