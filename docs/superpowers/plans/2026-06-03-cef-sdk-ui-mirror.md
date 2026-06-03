# CEF SDK-UI mirror Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render three SDK UI primitives (`SubtitleWindow`, `STStylizedWindow`, `TGCreditAction`) in the CEF overlay as dauntless-styled elements, driven by a single `SDKMirrorPanel` that walks `_TopWindow._children` and `_main_windows`.

**Architecture:** Each SDK primitive becomes a Python shim with a `_snapshot()` method returning JSON-serialisable state. A new `SDKMirrorPanel(Panel)` registered with the existing `PanelRegistry` walks the TopWindow tree each tick, emits a deduped `setSdkMirror({entries})` JS call, and routes click events from CEF back to a no-op logger (v1 deferred). CEF side renders entries into two semantic slots in `hello.html`. SDK pixel coordinates are accepted at the shim API but ignored at render time — dauntless re-style means slot CSS decides layout.

**Tech Stack:** Python 3 (CPython embedded via `_dauntless_host`), the existing `engine.ui.panel.Panel` base class + `PanelRegistry` pump, pytest for unit/integration tests, vanilla HTML/CSS/JS in `native/assets/ui-cef/`, `dauntlessEvent` IPC channel via `OnBeforeBrowse`.

**Spec:** [docs/superpowers/specs/2026-06-03-cef-sdk-ui-mirror-design.md](../specs/2026-06-03-cef-sdk-ui-mirror-design.md)

**Important deviation from spec:** The spec proposed a new `engine/appc/sdk_ui/` package. The existing codebase already has `engine/appc/windows.py` (TacticalControlWindow) and `engine/appc/actions.py` (TGCreditAction already present at line 271). Following the codebase pattern, the new shims live in those existing modules; the mirror panel is a new sibling file `engine/appc/sdk_mirror_panel.py`. Test file names adopted accordingly.

**Branch:** `cef-sdk-ui-mirror` (already cut from main with the spec commit; all task commits land on this branch).

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `engine/appc/windows.py` | edit (add classes) | `_SubtitleWindow` (singleton, state machine, text composition), `_STStylizedWindow` (per-instance, title + visibility), `SubtitleWindow_Cast`, `STStylizedWindow_CreateW`, `SubtitleWindow` exported class carrying `SM_*` constants |
| `engine/appc/actions.py` | edit (`TGCreditAction`) | Add `Play()` that delegates to `host._add_text(text, duration)`; duration extraction from `*args` |
| `engine/appc/sdk_mirror_panel.py` | new | `SDKMirrorPanel(Panel)` — walks TopWindow tree, dedup-on-JSON, `_log_unrecognised_once`, click logger |
| `engine/appc/top_window.py` | edit | Seed `_main_windows[MWT_SUBTITLE]` with `_SubtitleWindow()` in `__init__`; ensure `reset_for_tests` re-seeds and resets `_STStylizedWindow._counter` |
| `App.py` | edit | Import and re-export `SubtitleWindow`, `SubtitleWindow_Cast`, `STStylizedWindow_CreateW`; TGCreditAction routing already in place |
| `engine/host_loop.py` | edit | Construct `SDKMirrorPanel()`, `registry.register(sdk_mirror)` next to `target_list_view`/`sensors_panel` |
| `native/assets/ui-cef/hello.html` | edit | Add `<div id="sdk-subtitle">` and `<div id="sdk-stylized-stack">` slots; link new CSS + JS |
| `native/assets/ui-cef/css/sdk_mirror.css` | new | Slot styling matching ship-display / sensors aesthetic; z-indexes |
| `native/assets/ui-cef/js/sdk_mirror.js` | new | `setSdkMirror(payload)` routes by type; click handler emits `dauntlessEvent('sdk-mirror/click:<id>')` |
| `tests/unit/test_subtitle_window.py` | new | `_SubtitleWindow` state machine + snapshot pruning |
| `tests/unit/test_stylized_window.py` | new | `_STStylizedWindow` construction + visibility + counter reset |
| `tests/unit/test_credit_action_play.py` | new | `TGCreditAction.Play` delegation + idempotency |
| `tests/unit/test_sdk_mirror_panel.py` | new | Snapshot dedup, unrecognised-child logging, invalidate |
| `tests/integration/test_sdk_mirror_round_trip.py` | new | TGCreditAction → mirror payload assertion (monkeypatched `time.monotonic`) |

---

## Task 1: `_SubtitleWindow` shim in `engine/appc/windows.py`

**Files:**
- Modify: `engine/appc/windows.py` (append new class + factory)
- Test: `tests/unit/test_subtitle_window.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_subtitle_window.py`:

```python
"""Unit tests for the _SubtitleWindow SDK shim (engine/appc/windows.py)."""
from engine.appc.windows import _SubtitleWindow, SubtitleWindow_Cast, SubtitleWindow


def test_initial_state_hidden_and_empty():
    sw = _SubtitleWindow()
    assert sw._visible is False
    assert sw._active_texts == []
    assert sw._id == "subtitle-0"


def test_set_on_off_toggle():
    sw = _SubtitleWindow()
    sw.SetOn()
    assert sw.IsOn() is True
    sw.SetOff()
    assert sw.IsOn() is False


def test_set_visible_alias_matches_set_on():
    sw = _SubtitleWindow()
    sw.SetVisible()
    assert sw.IsOn() is True


def test_set_position_for_mode_stores_int():
    sw = _SubtitleWindow()
    sw.SetPositionForMode(SubtitleWindow.SM_TACTICAL)
    assert sw._mode == SubtitleWindow.SM_TACTICAL


def test_add_text_appends_with_expiry(monkeypatch):
    sw = _SubtitleWindow()
    monkeypatch.setattr("engine.appc.windows.time.monotonic", lambda: 100.0)
    sw._add_text("hello", 5.0)
    assert sw._active_texts == [("hello", 105.0)]


def test_snapshot_returns_none_when_hidden_and_empty():
    sw = _SubtitleWindow()
    assert sw._snapshot(now=0.0) is None


def test_snapshot_returns_dict_when_visible():
    sw = _SubtitleWindow()
    sw.SetOn()
    snap = sw._snapshot(now=0.0)
    assert snap == {
        "type": "subtitle", "id": "subtitle-0",
        "visible": True, "mode": SubtitleWindow.SM_TACTICAL, "lines": [],
    }


def test_snapshot_prunes_expired_text(monkeypatch):
    sw = _SubtitleWindow()
    monkeypatch.setattr("engine.appc.windows.time.monotonic", lambda: 0.0)
    sw._add_text("expired", 1.0)
    sw._add_text("alive", 10.0)
    snap = sw._snapshot(now=5.0)
    assert snap["lines"] == ["alive"]
    assert sw._active_texts == [("alive", 10.0)]


def test_snapshot_visible_true_when_text_active_even_if_set_off(monkeypatch):
    sw = _SubtitleWindow()
    monkeypatch.setattr("engine.appc.windows.time.monotonic", lambda: 0.0)
    sw._add_text("hello", 5.0)
    snap = sw._snapshot(now=1.0)
    assert snap["visible"] is True
    assert snap["lines"] == ["hello"]


def test_subtitle_window_class_exports_sm_constants():
    assert SubtitleWindow.SM_BRIDGE == 0
    assert SubtitleWindow.SM_TACTICAL == 1
    assert SubtitleWindow.SM_FELIX == 2
    assert SubtitleWindow.SM_NONFELIX == 3
    assert SubtitleWindow.SM_MAP == 4
    assert SubtitleWindow.SM_CINEMATIC == 5
    assert SubtitleWindow.SM_END_CINEMATIC == 6
    assert SubtitleWindow.SM_SPECIAL_FELIX == 7


def test_cast_returns_argument_if_subtitle_window():
    sw = _SubtitleWindow()
    assert SubtitleWindow_Cast(sw) is sw


def test_cast_returns_none_for_none():
    assert SubtitleWindow_Cast(None) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_subtitle_window.py -v`
Expected: ImportError or AttributeError — `_SubtitleWindow`, `SubtitleWindow_Cast`, `SubtitleWindow` not yet exported from `engine.appc.windows`.

- [ ] **Step 3: Implement `_SubtitleWindow`, `SubtitleWindow`, `SubtitleWindow_Cast`**

Append to `engine/appc/windows.py`:

```python
import time


# ── SubtitleWindow ──────────────────────────────────────────────────────────
# Singleton main window that hosts mission-objective / cinematic banner text.
# TGCreditAction.Play() calls _add_text(text, duration); the mirror panel
# snapshots (and prunes expired entries) once per tick.
# Spec: docs/superpowers/specs/2026-06-03-cef-sdk-ui-mirror-design.md

class _SubtitleWindow:
    # SM_* constants are duplicated on the exported SubtitleWindow class
    # below — SDK code accesses them as App.SubtitleWindow.SM_TACTICAL.
    _SM_BRIDGE, _SM_TACTICAL, _SM_FELIX, _SM_NONFELIX = 0, 1, 2, 3
    _SM_MAP, _SM_CINEMATIC, _SM_END_CINEMATIC, _SM_SPECIAL_FELIX = 4, 5, 6, 7

    def __init__(self):
        self._id = "subtitle-0"
        self._visible = False
        self._mode = self._SM_TACTICAL
        self._active_texts: list[tuple[str, float]] = []

    def SetOn(self) -> None:    self._visible = True
    def SetOff(self) -> None:   self._visible = False
    def SetVisible(self) -> None: self._visible = True  # SDK alias (MissionLib.TextBanner)
    def IsOn(self) -> bool:     return self._visible

    def SetPositionForMode(self, mode: int) -> None:
        self._mode = int(mode)

    def _add_text(self, text: str, duration_s: float) -> None:
        self._active_texts.append((str(text), time.monotonic() + float(duration_s)))

    def _snapshot(self, now: float) -> dict | None:
        self._active_texts = [(t, e) for (t, e) in self._active_texts if e > now]
        if not self._visible and not self._active_texts:
            return None
        return {
            "type": "subtitle",
            "id": self._id,
            "visible": self._visible or bool(self._active_texts),
            "mode": self._mode,
            "lines": [t for (t, _) in self._active_texts],
        }


class SubtitleWindow:
    """SDK-facing class exposing SM_* constants.

    SDK code reads App.SubtitleWindow.SM_TACTICAL etc.; the actual instances
    are _SubtitleWindow. The two are kept separate so the SM_* surface is
    a stable class attribute namespace rather than an instance attribute set.
    """
    SM_BRIDGE         = _SubtitleWindow._SM_BRIDGE
    SM_TACTICAL       = _SubtitleWindow._SM_TACTICAL
    SM_FELIX          = _SubtitleWindow._SM_FELIX
    SM_NONFELIX       = _SubtitleWindow._SM_NONFELIX
    SM_MAP            = _SubtitleWindow._SM_MAP
    SM_CINEMATIC      = _SubtitleWindow._SM_CINEMATIC
    SM_END_CINEMATIC  = _SubtitleWindow._SM_END_CINEMATIC
    SM_SPECIAL_FELIX  = _SubtitleWindow._SM_SPECIAL_FELIX


def SubtitleWindow_Cast(obj):
    """SDK cast helper; returns obj if it walks like a SubtitleWindow else None."""
    if obj is None: return None
    if isinstance(obj, _SubtitleWindow): return obj
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_subtitle_window.py -v`
Expected: 11 passed.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/windows.py tests/unit/test_subtitle_window.py
git commit -m "feat(appc): _SubtitleWindow shim with timed text composition"
```

---

## Task 2: `_STStylizedWindow` shim in `engine/appc/windows.py`

**Files:**
- Modify: `engine/appc/windows.py` (append new class + factory)
- Test: `tests/unit/test_stylized_window.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_stylized_window.py`:

```python
"""Unit tests for the _STStylizedWindow SDK shim (engine/appc/windows.py)."""
import pytest

from engine.appc.windows import _STStylizedWindow, STStylizedWindow_CreateW


@pytest.fixture(autouse=True)
def _reset_counter():
    _STStylizedWindow._counter = 0


def test_factory_returns_instance_with_title():
    w = STStylizedWindow_CreateW("Briefing")
    assert isinstance(w, _STStylizedWindow)
    assert w._title == "Briefing"


def test_id_increments_per_instance():
    a = STStylizedWindow_CreateW("A")
    b = STStylizedWindow_CreateW("B")
    assert a._id == "stylized-1"
    assert b._id == "stylized-2"


def test_initial_state_visible():
    w = STStylizedWindow_CreateW("X")
    assert w._visible is True
    assert w._children == []


def test_set_visible_toggle():
    w = STStylizedWindow_CreateW("X")
    w.SetNotVisible()
    assert w._visible is False
    w.SetVisible()
    assert w._visible is True


def test_add_child_records_without_x_y_validation():
    w = STStylizedWindow_CreateW("X")
    child = object()
    w.AddChild(child, 10.0, 20.0)
    assert child in w._children


def test_add_child_extra_args_accepted():
    w = STStylizedWindow_CreateW("X")
    # SDK call sites occasionally pass z or other extras; we accept *args.
    w.AddChild(object(), 0.0, 0.0, "extra", 99)


def test_get_obj_id_returns_python_id():
    w = STStylizedWindow_CreateW("X")
    assert w.GetObjID() == id(w)


def test_snapshot_shape():
    w = STStylizedWindow_CreateW("Mission Briefing")
    snap = w._snapshot()
    assert snap == {
        "type": "stylized",
        "id": "stylized-1",
        "visible": True,
        "title": "Mission Briefing",
    }


def test_snapshot_reflects_visibility():
    w = STStylizedWindow_CreateW("X")
    w.SetNotVisible()
    assert w._snapshot()["visible"] is False


def test_factory_accepts_extra_args_silently():
    # SDK signature is STStylizedWindow_CreateW(title, parent, x, y, w, h, ...).
    w = STStylizedWindow_CreateW("Title", None, 0.0, 0.0, 400, 300, 0)
    assert w._title == "Title"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_stylized_window.py -v`
Expected: ImportError — `_STStylizedWindow`, `STStylizedWindow_CreateW` not exported.

- [ ] **Step 3: Implement `_STStylizedWindow` + factory**

Append to `engine/appc/windows.py`:

```python
# ── STStylizedWindow ────────────────────────────────────────────────────────
# Centred LCARS-framed content panel in BC; dauntless re-styles as a centred
# modal panel via #sdk-stylized-stack. SDK pixel coords (parent/x/y/w/h) are
# accepted at the factory but ignored at render time — slot CSS decides layout.

class _STStylizedWindow:
    _counter = 0  # class-level; reset by top_window.reset_for_tests()

    def __init__(self, title: str = ""):
        type(self)._counter += 1
        self._id = f"stylized-{type(self)._counter}"
        self._title = str(title)
        self._visible = True
        self._children: list = []

    def AddChild(self, child, x: float = 0.0, y: float = 0.0, *_extra) -> None:
        self._children.append(child)

    def SetVisible(self) -> None:    self._visible = True
    def SetNotVisible(self) -> None: self._visible = False

    def GetObjID(self) -> int:
        # SDK identity hook used in profile (3 missions × 108 calls).
        return id(self)

    def _snapshot(self) -> dict:
        return {
            "type": "stylized",
            "id": self._id,
            "visible": self._visible,
            "title": self._title,
        }


def STStylizedWindow_CreateW(title="", *_extra) -> _STStylizedWindow:
    """SDK signature: STStylizedWindow_CreateW(title, parent, x, y, w, h, …).
    All args after the title are accepted and ignored — dauntless re-styles
    via slot CSS rather than SDK pixel coords."""
    return _STStylizedWindow(title)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_stylized_window.py -v`
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/windows.py tests/unit/test_stylized_window.py
git commit -m "feat(appc): _STStylizedWindow shim with per-instance id counter"
```

---

## Task 3: Wire `TGCreditAction.Play()` to host `_add_text`

**Files:**
- Modify: `engine/appc/actions.py:271-294` (TGCreditAction)
- Test: `tests/unit/test_credit_action_play.py` (new)

**Context:** `TGCreditAction.__init__` already stashes args ([engine/appc/actions.py:278-287](engine/appc/actions.py#L278-L287)). What's missing is `Play()` — the action currently inherits from `TGTimedAction` which has no `Play()`. The SDK signature is `TGCreditAction_Create(text, subtitle_window, fX, fY, duration, fade_in, fade_out, font_size, justify_x, justify_y)` — duration is `args[4]`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_credit_action_play.py`:

```python
"""TGCreditAction.Play() delegates to its host SubtitleWindow."""
import pytest

from engine.appc.actions import TGCreditAction, TGCreditAction_Create
from engine.appc.windows import _SubtitleWindow


def test_play_calls_host_add_text():
    host = _SubtitleWindow()
    ca = TGCreditAction_Create("Disable the patrol", host, 0.5, 0.5, 5.0, 0.25, 0.5, 16)
    ca.Play()
    assert len(host._active_texts) == 1
    text, _expires = host._active_texts[0]
    assert text == "Disable the patrol"


def test_play_uses_duration_from_args():
    host = _SubtitleWindow()
    ca = TGCreditAction_Create("hi", host, 0.0, 0.0, 7.5)
    ca.Play()
    text, expires = host._active_texts[0]
    # Expiry is monotonic-now + 7.5; just check that 7.5 went through.
    # Approximate by reading the action's stored duration.
    assert ca._duration_s == 7.5


def test_play_is_idempotent():
    host = _SubtitleWindow()
    ca = TGCreditAction_Create("once", host, 0.0, 0.0, 3.0)
    ca.Play()
    ca.Play()
    assert len(host._active_texts) == 1


def test_play_with_short_args_uses_default_duration():
    # Short form: TGCreditAction_Create(text, subtitle_window).
    host = _SubtitleWindow()
    ca = TGCreditAction_Create("brief", host)
    ca.Play()
    assert host._active_texts[0][0] == "brief"
    assert ca._duration_s == 3.0  # default matches SDK MissionLib.TextBanner


def test_play_no_op_when_host_lacks_add_text():
    # If TGCreditAction is constructed against a non-subtitle host
    # (some SDK paths chain credit actions on TGPane), don't crash.
    class _Bare: pass
    ca = TGCreditAction_Create("x", _Bare(), 0.0, 0.0, 1.0)
    ca.Play()  # must not raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_credit_action_play.py -v`
Expected: All fail — `TGCreditAction` has no `Play` and no `_duration_s`.

- [ ] **Step 3: Implement `Play` + duration extraction**

Edit `engine/appc/actions.py`. Replace the `TGCreditAction` class body with:

```python
class TGCreditAction(TGTimedAction):
    JUSTIFY_LEFT   = 0
    JUSTIFY_RIGHT  = 1
    JUSTIFY_TOP    = 2
    JUSTIFY_BOTTOM = 3
    JUSTIFY_CENTER = 4

    _DEFAULT_DURATION_S = 3.0  # matches MissionLib.TextBanner default (fDuration=3.0)

    def __init__(self, *args):
        super().__init__()
        # SDK constructor is variadic — common forms:
        #   (text, subtitle_window, x, y, duration, fade_in, fade_out, font_size, jx, jy)
        #   (text, subtitle_window) — for short banners
        self._args = args
        self._text = args[0] if args else ""
        self._subtitle = args[1] if len(args) > 1 else None
        self._duration_s = float(args[4]) if len(args) > 4 else self._DEFAULT_DURATION_S
        self._color = _credit_default_color
        self._played = False

    def SetColor(self, r: float, g: float, b: float, a: float = 1.0) -> None:
        self._color = (float(r), float(g), float(b), float(a))

    def Play(self) -> None:
        # Idempotent: SDK sometimes chains Play through a TGSequence that
        # re-fires Play on the same action. Match TGSoundAction's discipline.
        if self._played: return
        self._played = True
        host = self._subtitle
        adder = getattr(host, "_add_text", None)
        if adder is None: return
        adder(self._text, self._duration_s)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_credit_action_play.py -v`
Expected: 5 passed.

- [ ] **Step 5: Regression check — actions module untouched**

Run: `uv run pytest tests/unit/test_actions.py -v`
Expected: all existing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/actions.py tests/unit/test_credit_action_play.py
git commit -m "feat(appc): TGCreditAction.Play forwards text+duration to host SubtitleWindow"
```

---

## Task 4: `SDKMirrorPanel` in `engine/appc/sdk_mirror_panel.py`

**Files:**
- Create: `engine/appc/sdk_mirror_panel.py`
- Test: `tests/unit/test_sdk_mirror_panel.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_sdk_mirror_panel.py`:

```python
"""SDKMirrorPanel: snapshot dedup, child walk, unrecognised logging, invalidate."""
import json
import logging
import pytest

from engine.appc import top_window
from engine.appc.sdk_mirror_panel import SDKMirrorPanel
from engine.appc.windows import (
    _SubtitleWindow, _STStylizedWindow, STStylizedWindow_CreateW,
)


@pytest.fixture(autouse=True)
def _reset_tw():
    _STStylizedWindow._counter = 0
    top_window.reset_for_tests()


def _seed_subtitle():
    sw = _SubtitleWindow()
    top_window._the_top_window._main_windows[top_window.MWT_SUBTITLE] = sw
    return sw


def test_name_is_sdk_mirror():
    assert SDKMirrorPanel().name == "sdk-mirror"


def test_empty_state_returns_none():
    _seed_subtitle()
    p = SDKMirrorPanel()
    assert p.render_payload() is None


def test_visible_subtitle_emits_payload():
    sw = _seed_subtitle()
    sw.SetOn()
    p = SDKMirrorPanel()
    out = p.render_payload()
    assert out is not None and out.startswith("setSdkMirror(") and out.endswith(");")
    body = json.loads(out[len("setSdkMirror("):-len(");")])
    assert body["entries"][0]["type"] == "subtitle"
    assert body["entries"][0]["visible"] is True


def test_dedup_returns_none_on_unchanged_state():
    sw = _seed_subtitle()
    sw.SetOn()
    p = SDKMirrorPanel()
    assert p.render_payload() is not None
    assert p.render_payload() is None  # second call: no change → None


def test_stylized_window_appears_in_payload():
    _seed_subtitle()
    w = STStylizedWindow_CreateW("Brief")
    top_window._the_top_window.AddChild(w, 0.0, 0.0)
    p = SDKMirrorPanel()
    out = p.render_payload()
    body = json.loads(out[len("setSdkMirror("):-len(");")])
    titles = [e["title"] for e in body["entries"] if e["type"] == "stylized"]
    assert titles == ["Brief"]


def test_unrecognised_child_logged_once(caplog):
    _seed_subtitle()
    class _Bare: pass
    obj = _Bare()
    top_window._the_top_window.AddChild(obj, 0.0, 0.0)
    p = SDKMirrorPanel()
    with caplog.at_level(logging.INFO, logger="engine.appc.sdk_mirror_panel"):
        p.render_payload()
        p.invalidate()
        p.render_payload()  # second walk
    matching = [r for r in caplog.records if "_Bare" in r.message]
    assert len(matching) == 1


def test_invalidate_forces_reemit():
    sw = _seed_subtitle()
    sw.SetOn()
    p = SDKMirrorPanel()
    assert p.render_payload() is not None
    assert p.render_payload() is None
    p.invalidate()
    assert p.render_payload() is not None


def test_dispatch_event_logs_click_and_returns_true(caplog):
    p = SDKMirrorPanel()
    with caplog.at_level(logging.INFO, logger="engine.appc.sdk_mirror_panel"):
        handled = p.dispatch_event("click:stylized-3/close")
    assert handled is True
    assert any("stylized-3/close" in r.message for r in caplog.records)


def test_dispatch_event_unhandled_returns_false():
    p = SDKMirrorPanel()
    assert p.dispatch_event("garbage") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_sdk_mirror_panel.py -v`
Expected: ImportError — module not yet created.

- [ ] **Step 3: Implement `SDKMirrorPanel`**

Create `engine/appc/sdk_mirror_panel.py`:

```python
"""SDKMirrorPanel — walks _TopWindow children + main windows, emits JSON
snapshot to CEF via setSdkMirror(...).

One panel registered against PanelRegistry; the only consumer of
_TopWindow._children for rendering purposes. SDK shims (_SubtitleWindow,
_STStylizedWindow, future TGIcon/STText/...) mutate their own state;
this panel observes via the children list once per tick.

Spec: docs/superpowers/specs/2026-06-03-cef-sdk-ui-mirror-design.md
"""
from __future__ import annotations

import json
import logging
import time
from typing import Optional

from engine.appc import top_window
from engine.ui.panel import Panel

_logger = logging.getLogger(__name__)


class SDKMirrorPanel(Panel):
    def __init__(self):
        super().__init__()
        self._last_pushed: Optional[str] = None
        self._logged_unrecognised: set[str] = set()

    @property
    def name(self) -> str:
        return "sdk-mirror"

    def render_payload(self) -> Optional[str]:
        now = time.monotonic()
        entries: list = []

        tw = top_window.TopWindow_GetTopWindow()

        sub = tw._main_windows.get(top_window.MWT_SUBTITLE)
        if sub is not None:
            snap = sub._snapshot(now)
            if snap is not None:
                entries.append(snap)

        for (child, _x, _y) in tw._children:
            if hasattr(child, "_snapshot"):
                entries.append(child._snapshot())
            else:
                self._log_unrecognised_once(type(child).__name__)

        payload = json.dumps({"entries": entries})
        if payload == self._last_pushed:
            return None
        self._last_pushed = payload
        return "setSdkMirror(" + payload + ");"

    def dispatch_event(self, action: str) -> bool:
        if action.startswith("click:"):
            _logger.info("sdk-mirror click %s (no dispatch — v1)", action[len("click:"):])
            return True
        return False

    def invalidate(self) -> None:
        self._last_pushed = None

    def _log_unrecognised_once(self, type_name: str) -> None:
        if type_name in self._logged_unrecognised:
            return
        self._logged_unrecognised.add(type_name)
        _logger.info("sdk-mirror: skipping unrecognised child type %s", type_name)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_sdk_mirror_panel.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/sdk_mirror_panel.py tests/unit/test_sdk_mirror_panel.py
git commit -m "feat(appc): SDKMirrorPanel walks TopWindow tree, emits deduped JSON snapshot"
```

---

## Task 5: Seed `MWT_SUBTITLE` and extend `reset_for_tests`

**Files:**
- Modify: `engine/appc/top_window.py` (lines 27-40 and 204-209)
- Test: `tests/unit/test_top_window.py` (add cases)

- [ ] **Step 1: Add failing test cases**

Append to `tests/unit/test_top_window.py`:

```python
def test_subtitle_window_seeded_after_init():
    from engine.appc import top_window
    from engine.appc.windows import _SubtitleWindow
    top_window.reset_for_tests()
    sub = top_window._the_top_window.FindMainWindow(top_window.MWT_SUBTITLE)
    assert isinstance(sub, _SubtitleWindow)


def test_reset_for_tests_replaces_subtitle_singleton():
    from engine.appc import top_window
    sub_before = top_window._the_top_window.FindMainWindow(top_window.MWT_SUBTITLE)
    top_window.reset_for_tests()
    sub_after = top_window._the_top_window.FindMainWindow(top_window.MWT_SUBTITLE)
    assert sub_after is not sub_before


def test_reset_for_tests_resets_stylized_counter():
    from engine.appc import top_window
    from engine.appc.windows import _STStylizedWindow, STStylizedWindow_CreateW
    STStylizedWindow_CreateW("A")
    STStylizedWindow_CreateW("B")
    assert _STStylizedWindow._counter == 2
    top_window.reset_for_tests()
    assert _STStylizedWindow._counter == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_top_window.py -v -k "subtitle_window_seeded or replaces_subtitle or stylized_counter"`
Expected: 3 fail — subtitle not seeded; counter not reset.

- [ ] **Step 3: Seed `MWT_SUBTITLE` in `_TopWindow.__init__`**

Edit `engine/appc/top_window.py`. In `_TopWindow.__init__`, replace the `self._main_windows: dict[int, object] = {}` line with:

```python
        from engine.appc.windows import _SubtitleWindow
        self._main_windows: dict[int, object] = {
            MWT_SUBTITLE: _SubtitleWindow(),
        }
```

The import is local (not module-top) to avoid a load-order cycle: `windows.py` does not import `top_window`, and we want to keep that one-way.

- [ ] **Step 4: Reset `_STStylizedWindow._counter` in `reset_for_tests`**

Edit `engine/appc/top_window.py:204-209`. Replace `reset_for_tests` with:

```python
def reset_for_tests() -> None:
    """Re-initialise the singleton so cutscene/fade/view flags don't
    bleed across missions or pytest runs. Called from
    engine/host_loop.reset_sdk_globals."""
    global _the_top_window
    from engine.appc.windows import _STStylizedWindow
    _STStylizedWindow._counter = 0
    _the_top_window = _TopWindow()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_top_window.py -v`
Expected: all (existing + 3 new) pass.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/top_window.py tests/unit/test_top_window.py
git commit -m "feat(appc): seed MWT_SUBTITLE singleton; reset stylized counter on test reset"
```

---

## Task 6: Route SDK factories in `App.py`

**Files:**
- Modify: `App.py` (add imports near other `engine.appc.windows` import + re-export)
- Test: `tests/unit/test_app.py` (add cases) — or new file if test_app is too large

- [ ] **Step 1: Locate existing `engine.appc.windows` import**

Check current state:
```bash
grep -n "from engine.appc.windows import\|from engine.appc.actions import" App.py | head
```
Expected: line 17 `from engine.appc.windows import TacticalControlWindow`.

- [ ] **Step 2: Add failing test**

Create `tests/unit/test_app_sdk_ui_routing.py`:

```python
"""App.py re-exports for the SDK UI shims."""
import App
from engine.appc.windows import _SubtitleWindow, _STStylizedWindow


def test_app_subtitle_window_class_exposes_sm_tactical():
    assert App.SubtitleWindow.SM_TACTICAL == 1


def test_app_subtitle_window_cast_returns_subtitle_instance():
    sw = _SubtitleWindow()
    assert App.SubtitleWindow_Cast(sw) is sw


def test_app_subtitle_window_cast_none_returns_none():
    assert App.SubtitleWindow_Cast(None) is None


def test_app_stylized_window_create_w_returns_instance():
    w = App.STStylizedWindow_CreateW("Title")
    assert isinstance(w, _STStylizedWindow)
    assert w._title == "Title"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_app_sdk_ui_routing.py -v`
Expected: AttributeError — `App.SubtitleWindow`, `App.SubtitleWindow_Cast`, `App.STStylizedWindow_CreateW` not defined.

- [ ] **Step 4: Extend the `engine.appc.windows` import in `App.py`**

Edit `App.py:17` from:
```python
from engine.appc.windows import TacticalControlWindow
```
to:
```python
from engine.appc.windows import (
    TacticalControlWindow,
    SubtitleWindow, SubtitleWindow_Cast,
    STStylizedWindow_CreateW,
)
```

(`TGCreditAction_Create` is already imported on line 68, no change needed.)

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_app_sdk_ui_routing.py -v`
Expected: 4 passed.

- [ ] **Step 6: Sanity regression**

Run: `uv run pytest tests/unit/test_app.py -v`
Expected: existing tests still pass; no `_NamedStub` regressions.

- [ ] **Step 7: Commit**

```bash
git add App.py tests/unit/test_app_sdk_ui_routing.py
git commit -m "feat(appc): route SubtitleWindow, SubtitleWindow_Cast, STStylizedWindow_CreateW through App.py"
```

---

## Task 7: Register `SDKMirrorPanel` in the host loop

**Files:**
- Modify: `engine/host_loop.py` (around line 2227 — `PanelRegistry` construction)
- Test: covered by integration test in Task 9 (registry mechanics are untestable in isolation without exercising the loop)

- [ ] **Step 1: Locate the PanelRegistry block**

```bash
grep -n "registry = PanelRegistry\|registry.register" engine/host_loop.py | head
```
Expected: ~line 2227 — `registry = PanelRegistry(legacy_handler=pause_menu.dispatch_event)` and following `registry.register(...)` lines.

- [ ] **Step 2: Add SDKMirrorPanel construction + registration**

Edit `engine/host_loop.py`. After the existing `registry.register(sensors_panel)` line, add:

```python
        from engine.appc.sdk_mirror_panel import SDKMirrorPanel
        sdk_mirror = SDKMirrorPanel()
        registry.register(sdk_mirror)
```

Position: the SDK mirror is not dev-gated (unlike the mission picker on lines 2230-2231); it always runs.

- [ ] **Step 3: Smoke test — host loop still constructs**

Run a fast harness mission to confirm no startup regression:
```bash
timeout 30 uv run python tools/gameloop_harness.py --missions Custom.Tutorial.Episode.M1Basic.M1Basic --ticks 600 2>&1 | tail -20
```
Expected: `PASS  Custom.Tutorial.Episode.M1Basic.M1Basic (600/600 ticks)`.

If the harness CLI doesn't support those flags, fall back to `uv run python tools/gameloop_harness.py --profile 2>&1 | head -50` and confirm M1Basic still PASSes.

- [ ] **Step 4: Commit**

```bash
git add engine/host_loop.py
git commit -m "feat(host_loop): register SDKMirrorPanel with PanelRegistry"
```

---

## Task 8: CEF DOM slots + CSS + JS

**Files:**
- Modify: `native/assets/ui-cef/hello.html`
- Create: `native/assets/ui-cef/css/sdk_mirror.css`
- Create: `native/assets/ui-cef/js/sdk_mirror.js`

No Python tests for this task — CEF assets are validated via Task 9's integration test (which exercises the Python payload string) and Task 10's manual playtest.

- [ ] **Step 1: Create `native/assets/ui-cef/css/sdk_mirror.css`**

```css
/* SDK UI mirror slots — receives JSON payloads from SDKMirrorPanel.
   #sdk-subtitle is a centred bottom-anchored strip for SubtitleWindow text.
   #sdk-stylized-stack is a centred column of dauntless modals for
   STStylizedWindow instances. SDK pixel coords are ignored; layout is
   dictated by these slot rules.
   Spec: docs/superpowers/specs/2026-06-03-cef-sdk-ui-mirror-design.md */

#sdk-subtitle {
  position: absolute;
  left: 50%;
  bottom: 12vh;
  transform: translateX(-50%);
  max-width: 60vw;
  padding: 12px 20px;
  background: rgba(20, 40, 80, 0.85);
  border: 1px solid #3a6bb8;
  border-radius: 4px;
  color: #e8f0ff;
  font-family: sans-serif;
  font-size: 14px;
  text-align: center;
  z-index: 50;
  pointer-events: none;
}

#sdk-stylized-stack {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  gap: 16px;
  pointer-events: none;
  z-index: 40;
}

#sdk-stylized-stack .sdk-stylized-window {
  pointer-events: auto;
  min-width: 360px;
  max-width: 60vw;
  background: rgba(10, 20, 40, 0.92);
  border: 1px solid #3a6bb8;
  border-radius: 6px;
}

#sdk-stylized-stack .sdk-stylized-window__header {
  padding: 10px 16px;
  color: #7fa8d8;
  font-size: 11px;
  letter-spacing: 1.5px;
  text-transform: uppercase;
  border-bottom: 1px solid #2a4a80;
}
```

- [ ] **Step 2: Create `native/assets/ui-cef/js/sdk_mirror.js`**

```javascript
// SDK UI mirror — Python pushes a JSON tree via setSdkMirror({entries});
// each entry is routed by entry.type into its semantic slot.
// Spec: docs/superpowers/specs/2026-06-03-cef-sdk-ui-mirror-design.md

function setSdkMirror(payload) {
  const entries = (payload && payload.entries) || [];
  renderSubtitle(entries.find(e => e.type === "subtitle"));
  renderStylizedStack(entries.filter(e => e.type === "stylized"));
}

function renderSubtitle(entry) {
  const el = document.getElementById("sdk-subtitle");
  if (!el) return;
  if (!entry || !entry.visible || !entry.lines || entry.lines.length === 0) {
    el.hidden = true;
    el.innerHTML = "";
    return;
  }
  el.hidden = false;
  el.innerHTML = entry.lines.map(escapeHtml).join("<br>");
}

function renderStylizedStack(entries) {
  const stack = document.getElementById("sdk-stylized-stack");
  if (!stack) return;

  // Upsert visible entries by id.
  for (const entry of entries) {
    if (!entry.visible) continue;
    const domId = "sdk-stylized-" + entry.id;
    let node = document.getElementById(domId);
    if (!node) {
      node = document.createElement("div");
      node.id = domId;
      node.className = "sdk-stylized-window";
      node.onclick = () => dauntlessEvent("sdk-mirror/click:" + entry.id);
      stack.appendChild(node);
    }
    node.innerHTML =
      '<div class="sdk-stylized-window__header">' +
      escapeHtml(entry.title) +
      '</div>';
  }

  // Prune DOM nodes whose IDs are absent or marked invisible in the payload.
  const visibleIds = new Set(
    entries.filter(e => e.visible).map(e => "sdk-stylized-" + e.id)
  );
  for (const child of Array.from(stack.children)) {
    if (!visibleIds.has(child.id)) stack.removeChild(child);
  }
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c =>
    ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
}
```

- [ ] **Step 3: Edit `native/assets/ui-cef/hello.html`**

Add the CSS link in the `<head>` block. Find the existing block:
```html
    <link rel="stylesheet" href="css/sensors.css">
```
Append immediately after it:
```html
    <link rel="stylesheet" href="css/sdk_mirror.css">
```

Add the slots. Find the closing tag of `<div id="tactical-bottom-row">` (around line 172). After that closing `</div>`, before the `<script>` block, insert:

```html
    <!-- SDK UI mirror slots — receive payloads from SDKMirrorPanel.
         #sdk-subtitle: bottom-anchored mission-objective/banner strip.
         #sdk-stylized-stack: centred dauntless-styled modal stack.
         Spec: docs/superpowers/specs/2026-06-03-cef-sdk-ui-mirror-design.md -->
    <div id="sdk-subtitle" class="sdk-mirror" hidden></div>
    <div id="sdk-stylized-stack" class="sdk-mirror"></div>
```

Add the JS include. Find the last `<script src="...">` line in the existing block. After it, add:

```html
    <script src="js/sdk_mirror.js"></script>
```

- [ ] **Step 4: Smoke-rebuild — confirm assets load**

Per [CLAUDE.md](../../CLAUDE.md), CEF asset edits sometimes need a cmake reconfigure. To be safe:

```bash
cmake -B build -S . && cmake --build build -j
```
Expected: build succeeds.

- [ ] **Step 5: Commit**

```bash
git add native/assets/ui-cef/css/sdk_mirror.css \
        native/assets/ui-cef/js/sdk_mirror.js \
        native/assets/ui-cef/hello.html
git commit -m "feat(ui-cef): SDK UI mirror slots, CSS, and JS payload router"
```

---

## Task 9: Integration round-trip test

**Files:**
- Create: `tests/integration/test_sdk_mirror_round_trip.py`

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_sdk_mirror_round_trip.py`:

```python
"""End-to-end: TGCreditAction.Play → SDKMirrorPanel payload contains text.

Uses monkeypatched time.monotonic so expiry is deterministic.
"""
import json
import pytest

from engine.appc import top_window
from engine.appc.actions import TGCreditAction_Create
from engine.appc.sdk_mirror_panel import SDKMirrorPanel
from engine.appc.windows import _STStylizedWindow, STStylizedWindow_CreateW


@pytest.fixture(autouse=True)
def _reset_tw():
    _STStylizedWindow._counter = 0
    top_window.reset_for_tests()


def _decode(payload: str) -> dict:
    assert payload.startswith("setSdkMirror(")
    assert payload.endswith(");")
    return json.loads(payload[len("setSdkMirror("):-len(");")])


def test_credit_action_text_reaches_mirror_payload(monkeypatch):
    fake_now = [100.0]
    monkeypatch.setattr("engine.appc.windows.time.monotonic", lambda: fake_now[0])
    monkeypatch.setattr("engine.appc.sdk_mirror_panel.time.monotonic", lambda: fake_now[0])

    subtitle = top_window._the_top_window.FindMainWindow(top_window.MWT_SUBTITLE)
    panel = SDKMirrorPanel()

    # Pre-play: nothing visible, payload is None.
    assert panel.render_payload() is None

    # Play a 5-second banner.
    TGCreditAction_Create("Disable the patrol", subtitle, 0.0, 0.0, 5.0).Play()

    out = panel.render_payload()
    body = _decode(out)
    subtitle_entry = next(e for e in body["entries"] if e["type"] == "subtitle")
    assert subtitle_entry["lines"] == ["Disable the patrol"]

    # Same state → next render returns None.
    assert panel.render_payload() is None

    # Advance time past expiry; payload should re-emit without the text.
    fake_now[0] = 110.0
    out2 = panel.render_payload()
    body2 = _decode(out2)
    subtitle_entries = [e for e in body2["entries"] if e["type"] == "subtitle"]
    # With subtitle still off (only set on by SetOn — TGCreditAction didn't
    # touch _visible) and no active texts, the subtitle entry is absent.
    assert subtitle_entries == []


def test_stylized_window_and_subtitle_coexist_in_payload(monkeypatch):
    monkeypatch.setattr("engine.appc.windows.time.monotonic", lambda: 0.0)
    monkeypatch.setattr("engine.appc.sdk_mirror_panel.time.monotonic", lambda: 0.0)
    subtitle = top_window._the_top_window.FindMainWindow(top_window.MWT_SUBTITLE)
    subtitle.SetOn()

    w = STStylizedWindow_CreateW("Mission Briefing")
    top_window._the_top_window.AddChild(w, 100.0, 50.0)

    panel = SDKMirrorPanel()
    body = _decode(panel.render_payload())
    types = {e["type"] for e in body["entries"]}
    assert types == {"subtitle", "stylized"}
    stylized = next(e for e in body["entries"] if e["type"] == "stylized")
    assert stylized["title"] == "Mission Briefing"
    assert stylized["id"] == "stylized-1"
```

- [ ] **Step 2: Run test to verify it fails — then passes (sanity)**

Run: `uv run pytest tests/integration/test_sdk_mirror_round_trip.py -v`
Expected: all 2 pass (everything is already implemented after Tasks 1-5; this is a regression-net integration test).

If it fails, the failure is informative — investigate before moving on.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_sdk_mirror_round_trip.py
git commit -m "test(appc): end-to-end SDK mirror round trip with monkeypatched time"
```

---

## Task 10: Verification — profile delta + manual playtest

**Files:** No code changes. Verification only.

- [ ] **Step 1: Run the harness profile**

```bash
uv run python tools/gameloop_harness.py --profile 2>&1 | tee /tmp/cef-sdk-ui-mirror-profile.txt | head -60
```

Expected: `STStylizedWindow_CreateW`, `SubtitleWindow_Cast`, `TGCreditAction_Create` (and their derivative rows like `.AddChild`, `.GetObjID`, `.Play`) no longer appear in the top 50 stub-method rows. The next unimplemented primitive (probably `SortedRegionMenu_Cast` or `STText_Create`) takes the top.

If `TGCreditAction_Create` still appears: confirm `TGCreditAction.__init__` no longer goes through `_NamedStub` (it shouldn't — the symbol is already exported from `engine.appc.actions`). The presence of `TGCreditAction_Create` in the profile would indicate the profile counts a different path.

- [ ] **Step 2: Build the C++ host**

```bash
cmake -B build -S . && cmake --build build -j
```
Expected: build succeeds; `build/dauntless` exists.

- [ ] **Step 3: Launch and load M1Basic**

```bash
./build/dauntless --developer
```

In the running app: use the developer pause-menu → "Load Mission…" → pick `Custom.Tutorial.Episode.M1Basic.M1Basic`. Watch the bottom of the screen for ~15 seconds.

Expected: a dauntless-styled subtitle strip appears near the bottom with the tutorial's mission-objective text (whatever M1Basic fires via `TextBanner` / `SubtitledLine`). Text disappears after its `fDuration` (default 3-5 seconds per banner).

**If the subtitle doesn't appear:**
- Run with `RUST_LOG=info` equivalent for our Python logger (or check stderr for `sdk-mirror: skipping unrecognised child type ...` messages — that will reveal the next missing primitive)
- Confirm via `tools/gameloop_harness.py --profile` whether M1Basic actually hits `TGCreditAction_Create`. If it routes through `SubtitleAction_Create` instead (deferred to a follow-up spec), pick a different mission

- [ ] **Step 4: Load a mission with an STStylizedWindow**

In the same dauntless session: load `Maelstrom.Episode1.E1M1.E1M1` via the dev mission picker. Watch for a centred dauntless-styled panel with a title (the briefing window's title).

Expected: a centred modal appears with a title bar. The panel may have no body text (we don't recurse into stylized window children in v1 — that's a follow-up).

If no panel appears: re-check whether E1M1 actually calls `STStylizedWindow_CreateW` at mission start. The profile output from Step 1 confirms which missions exercise it; pick any mission that contributes to those 10 missions × 45 calls.

- [ ] **Step 5: Click the stylized panel**

Click on the visible stylized panel. Expected: nothing visibly happens (clicks are stubbed in v1). Check the stderr / log for a line like `sdk-mirror click stylized-N (no dispatch — v1)`.

If the click handler doesn't fire: inspect the panel's HTML via the CEF inspector (if available) and confirm `onclick` was wired by `sdk_mirror.js`.

- [ ] **Step 6: Final regression sweep**

Run a focused regression on the touched modules (avoid full `uv run pytest` — per CLAUDE.md memory it OOMs the host):

```bash
uv run pytest tests/unit/test_subtitle_window.py \
              tests/unit/test_stylized_window.py \
              tests/unit/test_credit_action_play.py \
              tests/unit/test_sdk_mirror_panel.py \
              tests/unit/test_top_window.py \
              tests/unit/test_app_sdk_ui_routing.py \
              tests/unit/test_actions.py \
              tests/integration/test_sdk_mirror_round_trip.py \
              tests/integration/test_input_gate_through_event_bus.py \
              -v
```

Expected: all green.

- [ ] **Step 7: Commit verification artifacts (optional)**

If the profile diff is striking, save the head of the profile to the spec's history:

```bash
git add /tmp/cef-sdk-ui-mirror-profile.txt # only if you want it tracked — skip otherwise
# OR
git commit --allow-empty -m "verify(appc): SDK UI mirror — Subtitle/STStylized/TGCreditAction removed from profile top 50"
```

The empty commit form is conventional in this repo (see commit `c2e7680 verify(appc): TopWindow shim host-startup smoke`).

- [ ] **Step 8: Branch ready for review**

```bash
git log --oneline main..HEAD
```

Expected: ~10 commits on `cef-sdk-ui-mirror` covering spec + each task. Branch is ready for `superpowers:finishing-a-development-branch`.
