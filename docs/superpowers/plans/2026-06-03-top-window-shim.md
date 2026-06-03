# TopWindow Shim Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the `_NamedStub`-routed `App.TopWindow_GetTopWindow()` with a real `_TopWindow` class in `engine/appc/top_window.py`, fixing the latent cutscene-piloting bug (`AllowKeyboardInput(0)` no-ops today) by gating `ET_KEYBOARD_EVENT` at the input trampoline.

**Architecture:** Pure-Python shim. New module `engine/appc/top_window.py` holds the `_TopWindow` class, a module-level singleton, and gate-query helpers (`keyboard_input_enabled()` / `mouse_input_enabled()`). `engine/appc/input.py` consults the keyboard gate in its dispatch trampoline. `App.py` instantiates the singleton, exports real integer `MWT_*` enums, and routes `TopWindow_GetTopWindow()` to it. `engine/host_loop.reset_sdk_globals` calls `top_window.reset_for_tests()` so flags don't bleed across missions.

**Tech Stack:** Python 3.13, pytest, the existing `App`/`engine/appc` event pipeline. No C++ changes (the `_dauntless_host.window_size()` binding already exists).

**Spec:** [docs/superpowers/specs/2026-06-03-top-window-shim-design.md](../specs/2026-06-03-top-window-shim-design.md)

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `engine/appc/top_window.py` | **new** | `_TopWindow` class, `_the_top_window` singleton, `keyboard_input_enabled()` / `mouse_input_enabled()` helpers, `reset_for_tests()` |
| `engine/appc/input.py` | modify | Consult `keyboard_input_enabled()` in `_OnKeyboardEvent_Dispatch`; drop events when gated off |
| `App.py` | modify | Add `MWT_*` integer enums; define `TopWindow_GetTopWindow()` returning the singleton |
| `engine/host_loop.py` | modify | Call `top_window.reset_for_tests()` from `reset_sdk_globals` |
| `tests/unit/test_top_window.py` | **new** | Direct unit tests for `_TopWindow` state, methods, and helpers |
| `tests/integration/test_input_gate_through_event_bus.py` | **new** | End-to-end: gate flip honoured by `g_kEventManager` broadcast |

---

## Task 1: Module skeleton + singleton + reset hook

**Files:**
- Create: `engine/appc/top_window.py`
- Test: `tests/unit/test_top_window.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_top_window.py`:

```python
"""Unit tests for the TopWindow shim (engine/appc/top_window.py)."""
import pytest


def test_singleton_exists():
    from engine.appc import top_window
    assert top_window._the_top_window is not None


def test_factory_returns_singleton():
    from engine.appc import top_window
    a = top_window.TopWindow_GetTopWindow()
    b = top_window.TopWindow_GetTopWindow()
    assert a is b
    assert a is top_window._the_top_window


def test_reset_for_tests_replaces_singleton_with_default_state():
    from engine.appc import top_window
    tw = top_window._the_top_window
    tw._cutscene_active = True
    top_window.reset_for_tests()
    new_tw = top_window._the_top_window
    assert new_tw is not tw
    assert new_tw._cutscene_active is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_top_window.py -v`
Expected: All three FAIL with `ModuleNotFoundError: No module named 'engine.appc.top_window'`.

- [ ] **Step 3: Write the minimal implementation**

Create `engine/appc/top_window.py`:

```python
"""SDK TopWindow shim.

Replaces the _NamedStub previously returned for App.TopWindow_GetTopWindow.
Owns input-gate flags, cutscene/fade/view state, the SDK UI children
list (for a future CEF mirror), and FindMainWindow lookups.

See docs/superpowers/specs/2026-06-03-top-window-shim-design.md.
"""


class _TopWindow:
    def __init__(self):
        self._keyboard_input_enabled: bool = True
        self._mouse_input_enabled: bool = True
        self._cutscene_active: bool = False
        self._fade_active: bool = False
        self._bridge_visible: bool = False
        self._tactical_visible: bool = True
        self._edit_mode: bool = False
        self._options_disabled: bool = False
        self._last_rendered_set = None
        self._children: list[tuple[object, float, float]] = []
        self._main_windows: dict[int, object] = {}


_the_top_window = _TopWindow()


def TopWindow_GetTopWindow():
    return _the_top_window


def reset_for_tests() -> None:
    """Re-initialise the singleton so cutscene/fade/view flags don't
    bleed across missions or pytest runs. Called from
    engine/host_loop.reset_sdk_globals."""
    global _the_top_window
    _the_top_window = _TopWindow()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_top_window.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/top_window.py tests/unit/test_top_window.py
git commit -m "feat(appc): TopWindow shim skeleton + singleton + reset hook"
```

---

## Task 2: Input-gate methods + helpers

**Files:**
- Modify: `engine/appc/top_window.py`
- Test: `tests/unit/test_top_window.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_top_window.py`:

```python
def test_keyboard_input_default_enabled():
    from engine.appc import top_window
    top_window.reset_for_tests()
    assert top_window.keyboard_input_enabled() is True


def test_allow_keyboard_input_flips_flag():
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    tw.AllowKeyboardInput(0)
    assert top_window.keyboard_input_enabled() is False
    assert tw.IsKeyboardInputAllowed() is False
    tw.AllowKeyboardInput(1)
    assert top_window.keyboard_input_enabled() is True
    assert tw.IsKeyboardInputAllowed() is True


def test_allow_mouse_input_flips_flag():
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    tw.AllowMouseInput(0)
    assert top_window.mouse_input_enabled() is False
    assert tw.IsMouseInputAllowed() is False
    tw.AllowMouseInput(1)
    assert top_window.mouse_input_enabled() is True
    assert tw.IsMouseInputAllowed() is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_top_window.py -v`
Expected: 3 new tests FAIL with `AttributeError: module 'engine.appc.top_window' has no attribute 'keyboard_input_enabled'` (and similar for the new methods).

- [ ] **Step 3: Add the methods and helpers**

Append to the `_TopWindow` class in `engine/appc/top_window.py` (just before the `_the_top_window = _TopWindow()` line):

```python
    # ── Input gate ─────────────────────────────────────────────
    def AllowKeyboardInput(self, enabled) -> None:
        self._keyboard_input_enabled = bool(enabled)

    def IsKeyboardInputAllowed(self) -> bool:
        return self._keyboard_input_enabled

    def AllowMouseInput(self, enabled) -> None:
        self._mouse_input_enabled = bool(enabled)

    def IsMouseInputAllowed(self) -> bool:
        return self._mouse_input_enabled
```

Append at the end of `engine/appc/top_window.py` (after `reset_for_tests`):

```python
def keyboard_input_enabled() -> bool:
    """Module-level helper consulted by engine/appc/input.py's keyboard
    dispatch trampoline. Defined as a function (not a constant) so the
    flag is read at event-dispatch time, not at import time."""
    return _the_top_window._keyboard_input_enabled


def mouse_input_enabled() -> bool:
    """Reserved for a future mouse-event trampoline. No consumer today."""
    return _the_top_window._mouse_input_enabled
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_top_window.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/top_window.py tests/unit/test_top_window.py
git commit -m "feat(appc): TopWindow input-gate flags + module helpers"
```

---

## Task 3: Wire keyboard gate into input trampoline

**Files:**
- Modify: `engine/appc/input.py:161-165`
- Test: `tests/unit/test_top_window.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_top_window.py`:

```python
def test_input_dispatch_drops_event_when_gated_off():
    """The trampoline must consult keyboard_input_enabled() and skip
    KeyboardBinding.OnKeyboardEvent when gated off."""
    from engine.appc import top_window
    from engine.appc import input as appc_input
    from engine.appc.events import TGKeyboardEvent

    top_window.reset_for_tests()

    # Stand up a recording binding in place of the singleton so we can
    # observe whether the trampoline forwarded the event.
    received = []

    class RecordingBinding:
        def OnKeyboardEvent(self, obj, evt):
            received.append(evt)

    saved = appc_input.g_kKeyboardBinding
    appc_input.g_kKeyboardBinding = RecordingBinding()
    try:
        evt = TGKeyboardEvent()
        # Gate ON (default) — event should reach the binding.
        appc_input._OnKeyboardEvent_Dispatch(None, evt)
        assert len(received) == 1

        # Gate OFF — event should be dropped.
        top_window.TopWindow_GetTopWindow().AllowKeyboardInput(0)
        appc_input._OnKeyboardEvent_Dispatch(None, evt)
        assert len(received) == 1  # unchanged

        # Gate back ON — event flows again.
        top_window.TopWindow_GetTopWindow().AllowKeyboardInput(1)
        appc_input._OnKeyboardEvent_Dispatch(None, evt)
        assert len(received) == 2
    finally:
        appc_input.g_kKeyboardBinding = saved
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_top_window.py::test_input_dispatch_drops_event_when_gated_off -v`
Expected: FAIL with `assert len(received) == 1` after the gate-off push, because the trampoline currently forwards unconditionally.

- [ ] **Step 3: Add the gate to the trampoline**

Edit `engine/appc/input.py`. Change the bottom of the file from:

```python
def _OnKeyboardEvent_Dispatch(obj, evt):
    """Trampoline so AddBroadcastPythonFuncHandler can resolve a qualified
    name and reach the singleton's bound method."""
    if g_kKeyboardBinding is not None:
        g_kKeyboardBinding.OnKeyboardEvent(obj, evt)
```

to:

```python
def _OnKeyboardEvent_Dispatch(obj, evt):
    """Trampoline so AddBroadcastPythonFuncHandler can resolve a qualified
    name and reach the singleton's bound method.

    Consults engine.appc.top_window.keyboard_input_enabled() so SDK code
    that calls TopWindow.AllowKeyboardInput(0) during a cutscene actually
    suppresses keyboard events instead of being a silent no-op."""
    # Local import — top_window depends on nothing in input, and
    # input is imported by App.py before top_window is registered as
    # a TopWindow_GetTopWindow factory; the symbol is module-level so
    # the lookup is one attribute read per event (cheap).
    from engine.appc.top_window import keyboard_input_enabled
    if not keyboard_input_enabled():
        return
    if g_kKeyboardBinding is not None:
        g_kKeyboardBinding.OnKeyboardEvent(obj, evt)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_top_window.py -v`
Expected: 7 passed.

Then run the wider input test suite to make sure no regression:

Run: `uv run pytest tests/unit/test_app.py tests/unit/test_app_ammo_constants.py -v`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/input.py tests/unit/test_top_window.py
git commit -m "feat(appc): gate keyboard dispatch on TopWindow.AllowKeyboardInput"
```

---

## Task 4: Cutscene state

**Files:**
- Modify: `engine/appc/top_window.py`
- Test: `tests/unit/test_top_window.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_top_window.py`:

```python
def test_cutscene_default_off():
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    assert tw.IsCutsceneMode() is False


def test_start_cutscene_flips_flag():
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    tw.StartCutscene()
    assert tw.IsCutsceneMode() is True


def test_end_cutscene_clears_flag():
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    tw.StartCutscene()
    tw.EndCutscene()
    assert tw.IsCutsceneMode() is False


def test_end_cutscene_accepts_fade_time():
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    tw.StartCutscene()
    tw.EndCutscene(2.5)   # SDK passes a fade-out duration
    assert tw.IsCutsceneMode() is False


def test_abort_cutscene_clears_flag():
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    tw.StartCutscene()
    tw.AbortCutscene()
    assert tw.IsCutsceneMode() is False


def test_cutscene_does_not_touch_input_flags():
    """MissionLib calls AllowKeyboardInput(0) explicitly around
    StartCutscene/EndCutscene; the cutscene methods must NOT
    auto-toggle the input gate or we'd double-gate."""
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    assert tw.IsKeyboardInputAllowed() is True
    tw.StartCutscene()
    assert tw.IsKeyboardInputAllowed() is True   # unchanged
    tw.EndCutscene()
    assert tw.IsKeyboardInputAllowed() is True   # unchanged
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_top_window.py -k cutscene -v`
Expected: 6 FAIL with `AttributeError: '_TopWindow' object has no attribute 'IsCutsceneMode'`.

- [ ] **Step 3: Add the cutscene methods**

Append to the `_TopWindow` class in `engine/appc/top_window.py`:

```python
    # ── Cutscene ───────────────────────────────────────────────
    def StartCutscene(self) -> None:
        self._cutscene_active = True

    def EndCutscene(self, fTime: float = 0.0) -> None:
        # fTime is the fade-out duration; we don't render fades.
        self._cutscene_active = False

    def AbortCutscene(self) -> None:
        self._cutscene_active = False

    def IsCutsceneMode(self) -> bool:
        return self._cutscene_active
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_top_window.py -v`
Expected: 13 passed.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/top_window.py tests/unit/test_top_window.py
git commit -m "feat(appc): TopWindow cutscene state"
```

---

## Task 5: Fade state

**Files:**
- Modify: `engine/appc/top_window.py`
- Test: `tests/unit/test_top_window.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_top_window.py`:

```python
def test_fade_default_off():
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    assert tw.IsFading() is False


def test_fade_out_sets_flag():
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    tw.FadeOut(1.5)
    assert tw.IsFading() is True


def test_fade_in_clears_flag():
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    tw.FadeOut(1.5)
    tw.FadeIn(1.5)
    assert tw.IsFading() is False


def test_abort_fade_clears_flag():
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    tw.FadeOut(1.5)
    tw.AbortFade()
    assert tw.IsFading() is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_top_window.py -k fade -v`
Expected: 4 FAIL with `AttributeError: '_TopWindow' object has no attribute 'IsFading'`.

- [ ] **Step 3: Add the fade methods**

Append to the `_TopWindow` class in `engine/appc/top_window.py`:

```python
    # ── Fade ───────────────────────────────────────────────────
    def FadeOut(self, fTime: float = 0.0) -> None:
        self._fade_active = True

    def FadeIn(self, fTime: float = 0.0) -> None:
        self._fade_active = False

    def AbortFade(self) -> None:
        self._fade_active = False

    def IsFading(self) -> bool:
        return self._fade_active
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_top_window.py -v`
Expected: 17 passed.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/top_window.py tests/unit/test_top_window.py
git commit -m "feat(appc): TopWindow fade state"
```

---

## Task 6: View state

**Files:**
- Modify: `engine/appc/top_window.py`
- Test: `tests/unit/test_top_window.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_top_window.py`:

```python
def test_view_state_defaults():
    """Dauntless has no bridge view and renders the tactical scene by default."""
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    assert tw.IsBridgeVisible() is False
    assert tw.IsTacticalVisible() is True


def test_force_bridge_visible_swaps_state():
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    tw.ForceBridgeVisible()
    assert tw.IsBridgeVisible() is True
    assert tw.IsTacticalVisible() is False


def test_force_tactical_visible_swaps_state():
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    tw.ForceBridgeVisible()
    tw.ForceTacticalVisible()
    assert tw.IsBridgeVisible() is False
    assert tw.IsTacticalVisible() is True


def test_toggle_bridge_and_tactical_swaps_both():
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    # Default: bridge=False, tactical=True
    tw.ToggleBridgeAndTactical()
    assert tw.IsBridgeVisible() is True
    assert tw.IsTacticalVisible() is False
    tw.ToggleBridgeAndTactical()
    assert tw.IsBridgeVisible() is False
    assert tw.IsTacticalVisible() is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_top_window.py -k "bridge or tactical or view" -v`
Expected: 4 FAIL with `AttributeError: '_TopWindow' object has no attribute 'IsBridgeVisible'`.

- [ ] **Step 3: Add the view-state methods**

Append to the `_TopWindow` class in `engine/appc/top_window.py`:

```python
    # ── View state (bridge vs tactical) ────────────────────────
    def IsBridgeVisible(self) -> bool:
        return self._bridge_visible

    def IsTacticalVisible(self) -> bool:
        return self._tactical_visible

    def ForceBridgeVisible(self) -> None:
        self._bridge_visible = True
        self._tactical_visible = False

    def ForceTacticalVisible(self) -> None:
        self._bridge_visible = False
        self._tactical_visible = True

    def ToggleBridgeAndTactical(self) -> None:
        self._bridge_visible, self._tactical_visible = (
            self._tactical_visible, self._bridge_visible,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_top_window.py -v`
Expected: 21 passed.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/top_window.py tests/unit/test_top_window.py
git commit -m "feat(appc): TopWindow bridge/tactical view state"
```

---

## Task 7: MWT_* enums + FindMainWindow

**Files:**
- Modify: `engine/appc/top_window.py`
- Test: `tests/unit/test_top_window.py`

`MWT_*` enums are defined in `top_window.py` (not `App.py` directly) so the values live next to the dict they key into. `App.py` re-exports them in Task 11.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_top_window.py`:

```python
def test_mwt_enums_are_distinct_integers():
    """The constants previously fell through to _NamedStub, whose __eq__
    returned isinstance(o, _Stub) — making MWT_CINEMATIC == MWT_BRIDGE
    nondeterministically truthy. Real ints fix that."""
    from engine.appc import top_window
    enums = [
        top_window.MWT_BRIDGE,
        top_window.MWT_TACTICAL,
        top_window.MWT_CONSOLE,
        top_window.MWT_EDITOR,
        top_window.MWT_OPTIONS,
        top_window.MWT_SUBTITLE,
        top_window.MWT_TACTICAL_MAP,
        top_window.MWT_CINEMATIC,
        top_window.MWT_MULTIPLAYER,
        top_window.MWT_CD_CHECK,
        top_window.MWT_MODAL_DIALOG,
    ]
    assert all(isinstance(v, int) for v in enums)
    assert len(set(enums)) == len(enums)   # all distinct


def test_find_main_window_returns_none_when_unregistered():
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    assert tw.FindMainWindow(top_window.MWT_CINEMATIC) is None
    assert tw.FindMainWindow(top_window.MWT_SUBTITLE) is None


def test_find_main_window_returns_registered_window():
    """Verify the lookup path — a future spec will land real backing
    windows; today no one registers, but the path must work."""
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    sentinel = object()
    tw._main_windows[top_window.MWT_CINEMATIC] = sentinel
    assert tw.FindMainWindow(top_window.MWT_CINEMATIC) is sentinel
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_top_window.py -k "mwt or find_main_window" -v`
Expected: 3 FAIL with `AttributeError: module 'engine.appc.top_window' has no attribute 'MWT_BRIDGE'`.

- [ ] **Step 3: Add the enums and FindMainWindow**

Append at the top of `engine/appc/top_window.py` (just after the docstring, before the `class _TopWindow` line):

```python
# ── Main-window-type enums ────────────────────────────────────
# Real Appc exposes these via SWIG; the integer values are arbitrary
# but must be distinct so dict lookups in _main_windows don't collapse.
MWT_BRIDGE        = 0
MWT_TACTICAL      = 1
MWT_CONSOLE       = 2
MWT_EDITOR        = 3
MWT_OPTIONS       = 4
MWT_SUBTITLE      = 5
MWT_TACTICAL_MAP  = 6
MWT_CINEMATIC     = 7
MWT_MULTIPLAYER   = 8
MWT_CD_CHECK      = 9
MWT_MODAL_DIALOG  = 10
```

Append to the `_TopWindow` class in `engine/appc/top_window.py`:

```python
    # ── Main windows ───────────────────────────────────────────
    def FindMainWindow(self, mwt):
        return self._main_windows.get(int(mwt))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_top_window.py -v`
Expected: 24 passed.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/top_window.py tests/unit/test_top_window.py
git commit -m "feat(appc): MWT_* enums + TopWindow.FindMainWindow"
```

---

## Task 8: Children tracking

**Files:**
- Modify: `engine/appc/top_window.py`
- Test: `tests/unit/test_top_window.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_top_window.py`:

```python
def test_children_empty_by_default():
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    assert tw.GetNumChildren() == 0
    assert tw.GetChildren() == []


def test_add_child_records_tuple():
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    label = object()
    tw.AddChild(label, 100, 200)
    assert tw.GetNumChildren() == 1
    assert tw.GetChildren() == [label]
    # Internal storage retains the position for the future CEF mirror.
    assert tw._children == [(label, 100.0, 200.0)]


def test_add_child_accepts_no_position():
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    tw.AddChild(object())
    assert tw.GetNumChildren() == 1


def test_add_child_accepts_extra_args():
    """Some SDK callers pass extra trailing args (e.g. z-order).
    The shim must accept them without raising."""
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    tw.AddChild(object(), 1.0, 2.0, 0)   # 4th arg used by MissionMenusShared.py
    assert tw.GetNumChildren() == 1


def test_remove_child_drops_matching_entries():
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    a, b = object(), object()
    tw.AddChild(a, 0, 0)
    tw.AddChild(b, 0, 0)
    tw.RemoveChild(a)
    assert tw.GetChildren() == [b]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_top_window.py -k "child" -v`
Expected: 5 FAIL with `AttributeError: '_TopWindow' object has no attribute 'GetNumChildren'`.

- [ ] **Step 3: Add the children methods**

Append to the `_TopWindow` class in `engine/appc/top_window.py`:

```python
    # ── Children (tracked but not rendered — see CEF mirror follow-up) ──
    def AddChild(self, child, x: float = 0.0, y: float = 0.0, *_extra) -> None:
        self._children.append((child, float(x), float(y)))

    def RemoveChild(self, child) -> None:
        self._children = [(c, x, y) for (c, x, y) in self._children if c is not child]

    def GetNumChildren(self) -> int:
        return len(self._children)

    def GetChildren(self) -> list:
        return [c for (c, _, _) in self._children]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_top_window.py -v`
Expected: 29 passed.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/top_window.py tests/unit/test_top_window.py
git commit -m "feat(appc): TopWindow child tracking (no render, CEF mirror hook)"
```

---

## Task 9: Geometry methods + window-size bridge

**Files:**
- Modify: `engine/appc/top_window.py`
- Test: `tests/unit/test_top_window.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_top_window.py`:

```python
def test_window_size_falls_back_when_host_not_initialised():
    """In pytest contexts _dauntless_host either isn't importable or
    raises RuntimeError because init() hasn't been called. The shim
    must fall back to a sensible default."""
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    # Default fallback per spec: 1920x1080
    assert tw.GetWidth() == 1920
    assert tw.GetHeight() == 1080


def test_window_size_uses_host_when_available(monkeypatch):
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()

    class FakeHost:
        @staticmethod
        def window_size():
            return (800, 600)

    import sys
    monkeypatch.setitem(sys.modules, "_dauntless_host", FakeHost)
    assert tw.GetWidth() == 800
    assert tw.GetHeight() == 600
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_top_window.py -k window_size -v`
Expected: 2 FAIL with `AttributeError: '_TopWindow' object has no attribute 'GetWidth'`.

- [ ] **Step 3: Add the geometry methods**

Append to the `_TopWindow` class in `engine/appc/top_window.py`:

```python
    # ── Geometry ───────────────────────────────────────────────
    def _window_size(self) -> tuple[int, int]:
        """Live window size from the C++ host. Falls back to 1920x1080
        when the host extension isn't loaded (pytest, harness) or
        hasn't initialised the window yet (very-early call)."""
        try:
            import _dauntless_host
            return _dauntless_host.window_size()
        except (ImportError, RuntimeError):
            return (1920, 1080)

    def GetWidth(self) -> int:
        return self._window_size()[0]

    def GetHeight(self) -> int:
        return self._window_size()[1]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_top_window.py -v`
Expected: 31 passed.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/top_window.py tests/unit/test_top_window.py
git commit -m "feat(appc): TopWindow GetWidth/GetHeight via _dauntless_host"
```

---

## Task 10: No-op / record-only surface

**Files:**
- Modify: `engine/appc/top_window.py`
- Test: `tests/unit/test_top_window.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_top_window.py`:

```python
def test_initialize_and_update_are_callable():
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    # Must not raise; have no observable side-effects yet.
    tw.Initialize()
    tw.Update()


def test_edit_mode_toggles():
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    assert tw.IsEditModeEnabled() is False
    tw.SetEditMode(1)
    assert tw.IsEditModeEnabled() is True
    tw.ToggleEditMode()
    assert tw.IsEditModeEnabled() is False
    tw.ToggleEditMode()
    assert tw.IsEditModeEnabled() is True


def test_disable_options_menu_sets_flag():
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    assert tw._options_disabled is False
    tw.DisableOptionsMenu()
    assert tw._options_disabled is True


def test_toggle_methods_are_callable():
    """Every Toggle*() method must accept zero args and not raise."""
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    tw.ToggleOptionsMenu()
    tw.ToggleConsole()
    tw.ToggleMapWindow()
    tw.ToggleCinematicWindow()
    tw.ToggleWireframe()


def test_show_bad_connection_text_callable():
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    tw.ShowBadConnectionText(1)
    tw.ShowBadConnectionText(0)


def test_last_rendered_set_round_trips():
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    assert tw.GetLastRenderedSet() is None
    sentinel = object()
    tw.SetLastRenderedSet(sentinel)
    assert tw.GetLastRenderedSet() is sentinel
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_top_window.py -k "initialize or edit_mode or options_menu or toggle_methods or bad_connection or last_rendered" -v`
Expected: 6 FAIL with `AttributeError: '_TopWindow' object has no attribute 'Initialize'` (and similar).

- [ ] **Step 3: Add the record-only surface**

Append to the `_TopWindow` class in `engine/appc/top_window.py`:

```python
    # ── Lifecycle (engine hooks — no-op for the Python shim) ───
    def Initialize(self) -> None:
        pass

    def Update(self) -> None:
        pass

    # ── Edit mode ──────────────────────────────────────────────
    def SetEditMode(self, enabled) -> None:
        self._edit_mode = bool(enabled)

    def IsEditModeEnabled(self) -> bool:
        return self._edit_mode

    def ToggleEditMode(self) -> None:
        self._edit_mode = not self._edit_mode

    # ── UI toggles (no UI to drive — record-only) ──────────────
    def ToggleOptionsMenu(self) -> None:
        pass

    def ToggleConsole(self) -> None:
        pass

    def ToggleMapWindow(self) -> None:
        pass

    def ToggleCinematicWindow(self) -> None:
        pass

    def ToggleWireframe(self) -> None:
        pass

    def DisableOptionsMenu(self) -> None:
        self._options_disabled = True

    def ShowBadConnectionText(self, show) -> None:
        pass

    # ── Active render set tracking ─────────────────────────────
    def SetLastRenderedSet(self, pSet) -> None:
        self._last_rendered_set = pSet

    def GetLastRenderedSet(self):
        return self._last_rendered_set
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_top_window.py -v`
Expected: 37 passed.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/top_window.py tests/unit/test_top_window.py
git commit -m "feat(appc): TopWindow lifecycle/edit/toggle/render-set methods"
```

---

## Task 11: Route App.TopWindow_GetTopWindow + export MWT_* enums

**Files:**
- Modify: `App.py`
- Test: `tests/unit/test_top_window.py`

This is the wire-up. Until now SDK code calling `App.TopWindow_GetTopWindow()` was getting a `_NamedStub`. After this task, it gets the real singleton.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_top_window.py`:

```python
def test_app_top_window_get_top_window_returns_real_singleton():
    """SDK code calls App.TopWindow_GetTopWindow() — that path must
    reach the real _TopWindow, not fall through to _NamedStub."""
    import App
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = App.TopWindow_GetTopWindow()
    assert tw is top_window._the_top_window


def test_app_mwt_enums_are_real_ints():
    """Previously these fell through to _NamedStub and compared
    equal to each other via _Stub.__eq__. Real ints fix that."""
    import App
    from engine.appc import top_window
    assert App.MWT_BRIDGE == top_window.MWT_BRIDGE
    assert App.MWT_CINEMATIC == top_window.MWT_CINEMATIC
    assert isinstance(App.MWT_BRIDGE, int)
    assert App.MWT_BRIDGE != App.MWT_CINEMATIC
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_top_window.py -k "app_top_window or app_mwt" -v`
Expected: 2 FAIL. First with `AssertionError: assert <App._NamedStub 'TopWindow_GetTopWindow()'> is <_TopWindow object>`. Second with `AssertionError: assert <App._NamedStub 'MWT_BRIDGE'> != <App._NamedStub 'MWT_CINEMATIC'>` (because `_Stub.__eq__` returns `isinstance(o, type(self))`).

- [ ] **Step 3: Wire the shim into App.py**

Edit `App.py`. Find the singleton block around line 491-495:

```python
g_kEventManager = TGEventManager()
g_kTimerManager = TGTimerManager(g_kEventManager)
g_kRealtimeTimerManager = TGTimerManager(g_kEventManager)
g_kInputManager, g_kKeyboardBinding = init_input_pipeline(g_kEventManager)
register_input_handlers(g_kEventManager)
```

Insert immediately after, *before* the `def TacticalControlWindow_GetTacticalControlWindow():` line:

```python
# ── TopWindow shim ─────────────────────────────────────────────────────────────
# See engine/appc/top_window.py and
# docs/superpowers/specs/2026-06-03-top-window-shim-design.md.
# TopWindow_GetTopWindow() must precede any SDK import that might call it
# at module-load time — keep this block at the singleton initialisation site.
from engine.appc.top_window import (
    TopWindow_GetTopWindow,
    MWT_BRIDGE, MWT_TACTICAL, MWT_CONSOLE, MWT_EDITOR, MWT_OPTIONS,
    MWT_SUBTITLE, MWT_TACTICAL_MAP, MWT_CINEMATIC, MWT_MULTIPLAYER,
    MWT_CD_CHECK, MWT_MODAL_DIALOG,
)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_top_window.py -v`
Expected: 39 passed.

Also run the broader unit suite for regression:

Run: `uv run pytest tests/unit/test_app.py -v`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add App.py tests/unit/test_top_window.py
git commit -m "feat(appc): route App.TopWindow_GetTopWindow + export MWT_* enums"
```

---

## Task 12: Hook reset_for_tests into reset_sdk_globals

**Files:**
- Modify: `engine/host_loop.py:1338-1380`
- Test: `tests/unit/test_top_window.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_top_window.py`:

```python
def test_reset_sdk_globals_resets_top_window_state():
    """A previous mission's cutscene/view/input flags must not bleed
    into the next mission. reset_sdk_globals() owns that contract."""
    from engine.host_loop import reset_sdk_globals
    from engine.appc import top_window

    # Dirty the state as if a prior mission had run.
    tw = top_window.TopWindow_GetTopWindow()
    tw.StartCutscene()
    tw.AllowKeyboardInput(0)
    tw.ForceBridgeVisible()

    reset_sdk_globals()

    fresh = top_window.TopWindow_GetTopWindow()
    assert fresh.IsCutsceneMode() is False
    assert fresh.IsKeyboardInputAllowed() is True
    assert fresh.IsBridgeVisible() is False
    assert fresh.IsTacticalVisible() is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_top_window.py::test_reset_sdk_globals_resets_top_window_state -v`
Expected: FAIL — one of the assertions trips because reset_sdk_globals doesn't touch top_window yet.

- [ ] **Step 3: Add the reset call**

Edit `engine/host_loop.py`. Find `reset_sdk_globals` (line 1338). Inside the function, after the `from engine.appc.input import register_input_handlers` line (around 1352), add:

```python
    from engine.appc import top_window
```

Then immediately after `register_input_handlers(App.g_kEventManager)` (around line 1364), add:

```python
    # Reset the TopWindow shim so cutscene/fade/view/input flags don't
    # bleed across missions or in-process swaps. See
    # docs/superpowers/specs/2026-06-03-top-window-shim-design.md.
    top_window.reset_for_tests()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_top_window.py -v`
Expected: 40 passed.

Then run the host-loop test for regression:

Run: `uv run pytest tests/host/test_host_loop_unit.py -v`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add engine/host_loop.py tests/unit/test_top_window.py
git commit -m "fix(host_loop): reset TopWindow shim between missions"
```

---

## Task 13: Integration test — gate end-to-end through the event bus

**Files:**
- Create: `tests/integration/test_input_gate_through_event_bus.py`

This validates the full chain: an SDK handler registered on `ET_KEYBOARD_EVENT` receives events when the gate is open and does not receive them when the gate is closed. Catches any future regression that bypasses the trampoline.

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_input_gate_through_event_bus.py`:

```python
"""Integration test for the TopWindow input gate.

Verifies that g_kEventManager broadcast dispatch consults
TopWindow.AllowKeyboardInput so SDK handlers registered for
ET_KEYBOARD_EVENT don't fire during a scripted cutscene.
"""


def test_keyboard_event_skipped_when_top_window_gate_off():
    import App
    from engine.appc import top_window
    from engine.appc.events import TGKeyboardEvent, ET_KEYBOARD_EVENT

    top_window.reset_for_tests()
    # Wipe broadcast handlers from any prior test so only the engine's
    # registered keyboard trampoline is in play.
    App.g_kEventManager._broadcast_handlers.clear()
    from engine.appc.input import register_input_handlers
    register_input_handlers(App.g_kEventManager)

    # Stub the keyboard binding so we can observe whether OnKeyboardEvent
    # was reached.
    from engine.appc import input as appc_input
    received = []

    class RecordingBinding:
        def OnKeyboardEvent(self, obj, evt):
            received.append(evt)

    saved = appc_input.g_kKeyboardBinding
    appc_input.g_kKeyboardBinding = RecordingBinding()
    try:
        # AddEvent dispatches synchronously (events.py:256-275): the
        # broadcast handlers fire inline. No ProcessEvents() needed.

        # Push one event with the gate OPEN — handler should fire.
        evt1 = TGKeyboardEvent()
        evt1.SetEventType(ET_KEYBOARD_EVENT)
        App.g_kEventManager.AddEvent(evt1)
        assert len(received) == 1

        # Close the gate; push another event — handler must NOT fire.
        App.TopWindow_GetTopWindow().AllowKeyboardInput(0)
        evt2 = TGKeyboardEvent()
        evt2.SetEventType(ET_KEYBOARD_EVENT)
        App.g_kEventManager.AddEvent(evt2)
        assert len(received) == 1  # unchanged

        # Re-open the gate; events flow again.
        App.TopWindow_GetTopWindow().AllowKeyboardInput(1)
        evt3 = TGKeyboardEvent()
        evt3.SetEventType(ET_KEYBOARD_EVENT)
        App.g_kEventManager.AddEvent(evt3)
        assert len(received) == 2
    finally:
        appc_input.g_kKeyboardBinding = saved
```

- [ ] **Step 2: Run test to verify it passes**

This test should pass on the first run because Tasks 3 and 11 already landed the gate and the wire-up. If it fails, debug the failure — the integration is what we're verifying.

Run: `uv run pytest tests/integration/test_input_gate_through_event_bus.py -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_input_gate_through_event_bus.py
git commit -m "test(appc): end-to-end TopWindow input gate through event bus"
```

---

## Task 14: Profile-delta verification

**Files:** none (verification step).

- [ ] **Step 1: Run the harness profile**

Run: `uv run python tools/gameloop_harness.py --profile`

Wait for the run to complete. The "Stub call profile" section appears at the bottom.

- [ ] **Step 2: Inspect the profile output**

Confirm:
- `TopWindow_GetTopWindow` does **NOT** appear in the top 50 rows.
- No new top-50 entries derived from TopWindow chained methods (`TopWindow_GetTopWindow().IsBridgeVisible`, etc.) appear — they should all resolve to real methods now.
- The total mission count at the top of the report is unchanged (no init/loop failures introduced).

If `TopWindow_GetTopWindow` still appears, something didn't wire correctly in Task 11 — check that `App.TopWindow_GetTopWindow` is the imported function, not falling through to `__getattr__`.

If unrelated stubs jumped to the top of the ranking, that's expected — we silenced the #1 entry, so the #2 entry becomes #1. No action.

- [ ] **Step 3: Record the result**

Add a one-line note in the commit message (no file change). If the profile output is interesting (e.g. new top entry is a clear next target), note it in your dev journal — not in the repo.

```bash
git commit --allow-empty -m "chore(appc): verify TopWindow_GetTopWindow removed from --profile top 50"
```

---

## Task 15: Manual cutscene playtest

**Files:** none (verification step).

The unit + integration tests prove the gate works at the Python level. This step proves it works end-to-end with the real C++ host, real keyboard input, and a real cutscene.

- [ ] **Step 1: Build**

Run: `cmake --build build -j`
Expected: clean build.

- [ ] **Step 2: Launch in developer mode**

Run: `./build/dauntless --developer`
Expected: window opens, dev mode active.

- [ ] **Step 3: Load a mission with a scripted cutscene**

Use the dev "Load Mission…" menu (from `engine/dev_mission_picker.py`). Pick a Maelstrom mission with a `StartCutscene` call in its `Initialize` or early-tick path — `Maelstrom/Episode7/E7M2` and `Maelstrom/Episode6/E6M1` are confirmed by grep. Wait for the in-mission cutscene to begin (the dialogue/subtitle pane indicates active cutscene).

- [ ] **Step 4: Attempt to pilot during the cutscene**

While the cutscene is active, hold the throttle key (W or whatever the binding is). Observe:
- Ship should **NOT** accelerate.
- Steering keys should **NOT** rotate the ship.

If the ship moves, the gate is leaking — return to Task 3 or Task 11 and debug. Most likely cause: a separate input pipeline bypasses `_OnKeyboardEvent_Dispatch` (e.g. direct calls into `KeyboardBinding.OnKeyboardEvent`).

- [ ] **Step 5: Confirm input resumes after the cutscene**

Wait for `EndCutscene` to fire (dialogue ends, gameplay resumes). Press throttle/steering — input should respond normally.

If input remains locked, `EndCutscene` isn't reaching the shim. Check that `MissionLib.EndCutscene` flows through `App.TopWindow_GetTopWindow().AllowKeyboardInput(1)`.

- [ ] **Step 6: Record success**

```bash
git commit --allow-empty -m "verify(appc): manual cutscene playtest — input gated during E7M2 cutscene"
```

---

## Done

After Task 15, the work is complete:
- `App.TopWindow_GetTopWindow` returns a real singleton.
- Every method the SDK declares on `TopWindow` is implemented (real semantics, no-op, or record-only as appropriate per spec).
- `AllowKeyboardInput(0)` actually suppresses keyboard events at the dispatch trampoline.
- `MWT_*` enums are distinct integers, fixing the latent `_NamedStub.__eq__` bug.
- `_children` is populated and ready for the future CEF UI-mirror project.
- `reset_sdk_globals` keeps state clean across missions.
- `--profile` no longer reports `TopWindow_GetTopWindow` in the top 50.

Open a PR with the 15 commits and the spec link in the description.
