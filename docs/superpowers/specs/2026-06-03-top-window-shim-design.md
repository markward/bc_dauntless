# TopWindow shim — design

**Date:** 2026-06-03
**Status:** Spec draft, awaiting user review.
**Motivation:** `App.TopWindow_GetTopWindow` is the #1 unimplemented stub in the gameloop harness profile (32 missions, 102 calls). The current `_NamedStub` no-ops `AllowKeyboardInput(0)` during scripted cutscenes, leaving a latent gameplay bug: **the player can pilot the ship while mission dialogue plays**. This spec replaces the stub with a real Python class living in `engine/appc/top_window.py`, fixes the cutscene-piloting bug, and gives every other TopWindow call site an honest answer.

---

## Goals

1. Fix the cutscene-piloting bug. `MissionLib.StartCutscene(...)` → `TopWindow.AllowKeyboardInput(0)` must actually suppress keyboard events from reaching SDK handlers until `EndCutscene` / `AbortCutscene` re-enables them.
2. Eliminate `TopWindow_GetTopWindow` from the top of the `--profile` report so the next unimplemented stub becomes visible.
3. Replace every TopWindow method the SDK declares with a real Python implementation. No silent `_NamedStub` fall-throughs from this object.
4. Track the SDK's children list (`AddChild` / `RemoveChild` / `GetNumChildren`) so a future "CEF SDK-UI mirror" project can consume it without retrofitting.

## Non-goals

- **No SDK UI rendering.** `_children` is recorded, never drawn. The CEF-mirror follow-up is a separate spec.
- **No mouse-event consumption.** `_mouse_input_enabled` is a real flag, but no `ET_MOUSE_EVENT` pipeline exists yet — the gate is reserved-but-inert.
- **No persistence.** TopWindow is process-scoped runtime state; not part of save-game state. No `__getstate__` / `__setstate__`.
- **No `MissionLib.StartCutscene` port.** The SDK wrapper at `MissionLib.py:891-908` already calls our shim; we only implement what it calls.
- **No real `MWT_*` backing windows.** `FindMainWindow` returns `None` for every key. Real backing windows (CinematicWindow, SubtitleWindow, etc.) are out of scope; SDK callers branch on `if pWnd is None` already.
- **No native renderer changes.** Pure Python shim. `_dauntless_host.window_size()` is consumed via the existing binding.

---

## Architecture

### File layout

| File | Status | Purpose |
|---|---|---|
| `engine/appc/top_window.py` | **new** | `_TopWindow` class, module-level singleton, gate-query helpers |
| `engine/appc/input.py` | edit | Trampoline consults `top_window.keyboard_input_enabled()` and drops events when False |
| `App.py` | edit | Import `_TopWindow`; replace the implicit `_NamedStub` route for `TopWindow_GetTopWindow` with a real factory; export `MWT_*` int enums |
| `tests/unit/test_top_window.py` | new | Direct unit tests for `_TopWindow` state and methods |
| `tests/integration/test_input_gate_through_event_bus.py` | new | End-to-end: gate flip is honoured by the event bus |

### Class shape

```python
# engine/appc/top_window.py
class _TopWindow:
    def __init__(self):
        self._keyboard_input_enabled: bool = True
        self._mouse_input_enabled: bool = True
        self._cutscene_active: bool = False
        self._fade_active: bool = False
        self._bridge_visible: bool = False     # dauntless has no bridge view yet
        self._tactical_visible: bool = True    # dauntless renders the tactical scene by default
        self._edit_mode: bool = False
        self._options_disabled: bool = False
        self._last_rendered_set = None
        self._children: list[tuple[object, float, float]] = []
        self._main_windows: dict[int, object] = {}   # MWT_* → window (always empty for now)

_the_top_window = _TopWindow()

def keyboard_input_enabled() -> bool:
    return _the_top_window._keyboard_input_enabled

def mouse_input_enabled() -> bool:
    return _the_top_window._mouse_input_enabled
```

### Surface

`TopWindow` inherits from `TGPane` in the SDK (`sdk/Build/scripts/App.py:7273`), so AddChild/GetWidth/GetHeight/etc. are inherited. For shim purposes we implement everything as flat methods on `_TopWindow` — no TGPane base class is needed because no SDK code introspects the class hierarchy.

| Method | Behaviour |
|---|---|
| **Input gate** | |
| `AllowKeyboardInput(b)` | `self._keyboard_input_enabled = bool(b)` |
| `IsKeyboardInputAllowed()` | `return self._keyboard_input_enabled` |
| `AllowMouseInput(b)` | `self._mouse_input_enabled = bool(b)` |
| `IsMouseInputAllowed()` | `return self._mouse_input_enabled` |
| **Cutscene** | |
| `StartCutscene()` | `self._cutscene_active = True` — do not touch input flags; MissionLib explicitly calls `AllowKeyboardInput(0)` and `AllowMouseInput(0)` itself ([MissionLib.py:891-892](sdk/Build/scripts/MissionLib.py#L891-L892)) |
| `EndCutscene(fTime=0)` | `self._cutscene_active = False` — `fTime` is fade-out duration; ignored (no fade renderer yet) |
| `AbortCutscene()` | `self._cutscene_active = False` |
| `IsCutsceneMode()` | `return self._cutscene_active` |
| **Fade** | |
| `FadeOut(fTime=0)` | `self._fade_active = True` |
| `FadeIn(fTime=0)` | `self._fade_active = False` |
| `AbortFade()` | `self._fade_active = False` |
| `IsFading()` | `return self._fade_active` |
| **View state** | |
| `IsBridgeVisible()` | `return self._bridge_visible` (initially False — no bridge view) |
| `IsTacticalVisible()` | `return self._tactical_visible` (initially True — dauntless renders the tactical scene) |
| `ForceBridgeVisible()` | `self._bridge_visible = True; self._tactical_visible = False` |
| `ForceTacticalVisible()` | `self._tactical_visible = True; self._bridge_visible = False` |
| `ToggleBridgeAndTactical()` | swap the two flags |
| **Main windows** | |
| `FindMainWindow(mwt: int)` | `return self._main_windows.get(int(mwt))` — always None today |
| **Children** | |
| `AddChild(child, x=0, y=0, *_)` | `self._children.append((child, float(x), float(y)))` |
| `RemoveChild(child)` | filter `_children` to drop tuples whose first element is `child` |
| `GetNumChildren()` | `return len(self._children)` |
| `GetChildren()` | `return [c for (c, _, _) in self._children]` |
| **Geometry** | |
| `GetWidth()` | `return self._window_size()[0]` — pulls from `_dauntless_host.window_size()` or falls back to 1920 |
| `GetHeight()` | `return self._window_size()[1]` — same, falls back to 1080 |
| **No-op surface (record-only)** | |
| `Initialize()`, `Update()` | pass — runtime hooks the C++ engine would use; nothing for us to do |
| `SetEditMode(b)`, `IsEditModeEnabled()`, `ToggleEditMode()` | store/return `self._edit_mode` |
| `ToggleOptionsMenu()`, `ToggleConsole()`, `ToggleMapWindow()`, `ToggleCinematicWindow()`, `ToggleWireframe()` | pass — UI toggles dauntless doesn't surface |
| `DisableOptionsMenu()` | `self._options_disabled = True` |
| `ShowBadConnectionText(b)` | pass — multiplayer-only |
| `SetLastRenderedSet(s)` / `GetLastRenderedSet()` | store/return `self._last_rendered_set` |
| **Factory** | |
| `TopWindow_GetTopWindow()` | module function returning `_the_top_window` singleton (exported via `App.py`) |

### MWT_* enums

The SDK exposes `MWT_BRIDGE`, `MWT_TACTICAL`, `MWT_CONSOLE`, `MWT_EDITOR`, `MWT_OPTIONS`, `MWT_SUBTITLE`, `MWT_TACTICAL_MAP`, `MWT_CINEMATIC`, `MWT_MULTIPLAYER`, `MWT_CD_CHECK`, `MWT_MODAL_DIALOG` as integer enums. The shim assigns sequential ints (0-10) and exports them via `App.py` so SDK code matching `App.MWT_CINEMATIC` against keys passed to `FindMainWindow` works. Values don't need to match the original Appc enum integers — no save-game or wire-format crosses the boundary.

**Latent bug this fixes:** today `App.MWT_*` access falls through to the `_NamedStub` fallback ([App.py:1088-1089](App.py#L1088-L1089)). `_Stub.__eq__` returns `isinstance(o, type(self))` ([App.py:1059](App.py#L1059)), meaning **every `MWT_*` stub compares equal to every other `MWT_*` stub**. Any dict keyed on these values would collapse, and any `if mwt == App.MWT_CINEMATIC` branch is currently a coin flip. No code path is observably broken today because `FindMainWindow` itself returns a `_NamedStub` that the caller discards — but the moment a real `FindMainWindow` ships (this spec), the enums must also be real ints or `_main_windows.get(mwt)` returns nondeterministic results.

---

## Input gating mechanics

### The gate point

`engine/appc/input._OnKeyboardEvent_Dispatch` ([input.py:161-165](engine/appc/input.py#L161-L165)) is the single funnel for every keyboard event reaching Python from the C++ host. Two-line check at the top:

```python
from engine.appc.top_window import keyboard_input_enabled

def _OnKeyboardEvent_Dispatch(obj, evt):
    if not keyboard_input_enabled():
        return
    if g_kKeyboardBinding is not None:
        g_kKeyboardBinding.OnKeyboardEvent(obj, evt)
```

### Why here, not at `KeyboardBinding.OnKeyboardEvent`

The trampoline is the boundary between the C++/event-system world and the SDK-handler world. Gating here means **no** SDK handler sees the event, which matches real Appc's behaviour (TopWindow consumes input before forwarding to the keyboard binding). It's also future-proof: any new keyboard subscriber attaching to `ET_KEYBOARD_EVENT` automatically inherits the gate.

### Import-order safety

`engine/appc/top_window.py` has no dependency on `engine/appc/input.py` or `App.py`. `input.py` imports `keyboard_input_enabled` from `top_window` at module load. `App.py` imports both. No circularity. The `_the_top_window` singleton is constructed at `top_window.py` module-import time, before anything queries the gate.

### Mouse gating

`_mouse_input_enabled` is stored and queryable via `mouse_input_enabled()`, but no `ET_MOUSE_EVENT` exists. SDK code's `AllowMouseInput(0)` calls flip the flag honestly; nothing consumes it yet. When mouse events get wired (separate spec), whatever trampoline they use will consult `mouse_input_enabled()` the same way.

---

## Window-size bridge

`_dauntless_host.window_size()` already exists ([host_bindings.cc:945-952](native/src/host/host_bindings.cc#L945-L952)). It throws `runtime_error` if `init()` wasn't called (i.e., in pytest contexts where the C++ window isn't initialised).

```python
def _window_size(self) -> tuple[int, int]:
    try:
        import _dauntless_host
        return _dauntless_host.window_size()
    except (ImportError, RuntimeError):
        return (1920, 1080)   # headless / test fallback

def GetWidth(self):  return self._window_size()[0]
def GetHeight(self): return self._window_size()[1]
```

Called per-invocation (not cached) so live window resize is reflected. SDK callers hit this ~2x per mission — negligible cost.

---

## Risks and mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| `IsBridgeVisible()` flipping from truthy (stub) to `False` (real) changes a BridgeHandlers branch that was silently working | Low — the one caller at [BridgeHandlers.py:1066](sdk/Build/scripts/BridgeHandlers.py#L1066) gates a render path dauntless never hits today | Document and audit; rely on the harness regression suite to catch ordering changes |
| `FindMainWindow(MWT_*)` returning `None` surprises callers that expected a truthy `_NamedStub` | Medium — ~25 call sites across the SDK | Audited: every caller either does `if pWnd is None: return` or passes the result to a `*_Cast` helper that handles None. No call site dereferences the result unconditionally. |
| The gate function lookup is hot — fires on every keyboard event | Low — keyboard rate is < 100 Hz, function call is one attribute read | Don't optimise. If profiling later shows a hot spot, inline the flag read. |
| Singleton state leaks across tests | Medium — pytest reuses the module | Add a `reset_for_tests()` helper that re-initialises `_the_top_window`'s state; call from a conftest fixture or the existing `reset_sdk_globals` chain in `engine/host_loop.py` |

---

## Verification plan

| Layer | What | How |
|---|---|---|
| Unit (`tests/unit/test_top_window.py`) | Input gate flip | `tw.AllowKeyboardInput(0)` → `keyboard_input_enabled() is False`; `AllowKeyboardInput(1)` → `True`. Same for mouse via `mouse_input_enabled()`. |
| Unit | Cutscene state | `StartCutscene()` → `IsCutsceneMode() is True`; `EndCutscene()` → `False`; `AbortCutscene()` → `False`. Cutscene does **not** toggle input flags by itself. |
| Unit | Fade state | `FadeOut()` → `IsFading() is True`; `FadeIn()` → `False`; `AbortFade()` → `False`. |
| Unit | View state | `ForceBridgeVisible()` → `IsBridgeVisible()` True and `IsTacticalVisible()` False; `ToggleBridgeAndTactical()` swaps both. |
| Unit | Children tracking | `AddChild(stub, 10, 20)` → `GetNumChildren() == 1`, `GetChildren()` contains `stub`; `RemoveChild(stub)` → `0`. |
| Unit | FindMainWindow | empty dict → returns `None` for every `MWT_*`. |
| Unit | Geometry fallback | When `_dauntless_host` not importable, returns `(1920, 1080)`. With a mocked binding returning `(800, 600)`, returns those values. |
| Integration (`tests/integration/test_input_gate_through_event_bus.py`) | End-to-end gate | Use `App.g_kEventManager`, register a recording SDK handler on `ET_KEYBOARD_EVENT`, push event, assert handler called once. Flip `AllowKeyboardInput(0)`, push again, assert handler call count unchanged. Flip back, push, assert count incremented. |
| Profile delta | Stub removed | `uv run python tools/gameloop_harness.py --profile` after the change. Confirm `TopWindow_GetTopWindow` no longer appears in the top 50 rows. Profile should show one fewer mission-shared stub at the top. |
| Manual playtest | Cutscene-piloting bug fixed | Build (`cmake --build build -j`), launch (`./build/dauntless`), load a mission that triggers a scripted cutscene (m01_strange_new_world has dialog within ~30s of start). Hold throttle key during the cutscene. Confirm the ship does not accelerate, then confirm throttle resumes working once dialogue ends. |

---

## Test reset hook

`engine/host_loop.reset_sdk_globals` is called at the start of each harness mission and by `mission_harness.setup_sdk()`. Add a `top_window.reset_for_tests()` call to that reset chain so the cutscene/fade/view flags don't bleed across missions or test runs.

```python
# engine/appc/top_window.py
def reset_for_tests():
    global _the_top_window
    _the_top_window = _TopWindow()
```

---

## Follow-up — CEF SDK-UI mirror

Out of scope for this spec. The hooks needed by that future work are landed here:

- `_TopWindow._children` is a real list. CEF mirror walks it.
- `AddChild` / `RemoveChild` provide the observable mutation surface.
- `GetWidth` / `GetHeight` return live window dimensions so CEF can position overlays correctly.

When that project starts, the next step is its own brainstorm covering: (1) how the children dict serialises to CEF (JSON over the existing IPC?), (2) which SDK UI primitives to make real classes (`TGIcon`, `STText`, `StylizedWindow`, etc.) and in what order, (3) how the BC LCARS bitmaps reach CEF (file:// URLs vs extracted assets vs Base64 data URIs).
