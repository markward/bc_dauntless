# Cinematic mode: focus-dependent keyboard routing

**Date:** 2026-08-18
**Status:** design approved, not yet implemented
**Branch:** `feat/camera-named-modes-bc-convention`

## Problem

BC binds `F9` to `ET_INPUT_TOGGLE_CINEMATIC_MODE` in every locale's
`Default*KeyboardBinding.py` (line 128). Entering cinematic mode gives the
player a six-camera rig on `F1`-`F6`
(`sdk/Build/scripts/CinematicInterfaceHandlers.py:154-159`):

| Key | Mode |
|---|---|
| F1 | DropAndWatch |
| F2 | Chase |
| F3 | Target |
| F4 | TorpCam |
| F5 | WideTarget |
| F6 | FreeOrbit |

None of it functions in Dauntless. Three blockers were identified; one is
already fixed:

1. `TopWindow.ToggleCinematicWindow()` is `pass` (`engine/appc/top_window.py:293`).
2. `_CinematicWindow` is a never-visible stand-in (`engine/appc/windows.py:417`)
   that exists only so `FindMainWindow(MWT_CINEMATIC).GetObjID()` does not crash.
3. ~~The six `ET_INPUT_CINEMATIC_*` constants were undefined~~ — **fixed in
   `26576a51`** (allocated 1102-1107).

The real obstacle behind 1 and 2 is that **`F1`-`F5` are already globally bound
to the bridge crew menus** (`engine/appc/input.py:492`, `ET_INPUT_TALK_TO_*`).
In BC that is not a conflict: the cinematic window owns those keys *while it
holds focus*, because BC routes keyboard input to the focused window first. Our
dispatch has no focus dependence.

## Constraint that shapes the design

`engine/appc/input.py:_resolve_destination` is already a hand-rolled substitute
for BC's window chain. Its docstring:

> BC bubbles keyboard-bound events up the window chain; our ProcessEvent
> dispatches on one object only. Scan the known keyboard consumers — default
> destination (TCW), its tactical menu, TopWindow — for the first that actually
> registered an instance handler for this event type.

So the seam exists. This design **keeps the single-destination model** and makes
the candidate list focus-aware. It deliberately does NOT build BC's real
bubbling chain with `SetHandled()` / `CallNextHandler()` veto semantics — that
divergence stays open and is out of scope here.

## Design

### 1. Focus model — reuse BC's

`TopWindow.GetFocus()` / `SetFocus()` already exist
(`engine/appc/top_window.py:210-213`). BC uses them for exactly this purpose:

```python
# Actions/CameraScriptActions.py:StartCinematicMode
pFocus = pTopWindow.GetFocus()
pCinematic = App.CinematicWindow_Cast(pTopWindow.FindMainWindow(App.MWT_CINEMATIC))
if pCinematic:
    if (not pFocus) or (pFocus.GetObjID() != pCinematic.GetObjID()):
        pTopWindow.ToggleCinematicWindow()
        pCinematic.SetInteractive(bInteractive)
```

No new concept is introduced. `ToggleCinematicWindow()` sets focus; routing
reads focus.

### 2. Routing — one insertion into the existing scan

`_resolve_destination` prepends the focused main window to its candidate list:

```
candidates = [
    focused_main_window,      # NEW
    tcw,
    tcw.GetTacticalMenu(),
    top._events,
]
# unchanged: first candidate with a handler for this event type wins
```

`_CinematicWindow` inherits `TGEventHandlerObject`, so it already carries the
`_handlers` dict the scan probes. No new mechanism.

**The safety property falls out of the existing scan, not a special case:** an
event type the focused window did not register falls straight through to
today's candidates. Bridge crew menus keep `F1`-`F5` whenever cinematic mode is
not focused, by construction.

**Deliberate narrowing:** only a focus value present in
`_TopWindow._main_windows.values()` becomes a candidate. QuickBattle's
`OpenConfigDialog` sets focus to config panes; those must not start capturing
keyboard events as a side effect of this change.

### 3. `_CinematicWindow` becomes real

- `SetInteractive(bool)` / `IsInteractive()` — real stored state. Current
  `IsInteractive()` returns a hardcoded `1`; BC's default is non-interactive
  (`StartCinematicMode(pAction, bInteractive = 0)`), but the F9 player path
  enters interactive. Keep the current `1` default so no existing OR-guard
  flips, and have `ToggleCinematicWindow` set it explicitly.
- `IsWindowActive()` returns whether this window currently holds TopWindow
  focus, replacing the hardcoded `0`.
- `CinematicInterfaceHandlers.Initialize(window)` runs **lazily on first
  toggle**, not at construction — the module imports `Camera`, which must not
  be pulled into App bootstrap.

### 4. `TopWindow.ToggleCinematicWindow()`

Focus the cinematic window if it is not focused; otherwise clear focus to
`None`.

No separate "cinematic active" flag is stored. Focus is the single source of
truth, exposed by a new `_TopWindow.is_cinematic_active()` that returns whether
`GetFocus()` is the `MWT_CINEMATIC` window. A second stored flag could disagree
with focus; a derived one cannot.

### 5. Visual

`host_loop._tactical_hud_visible` (`engine/host_loop.py:2381`) already gates on
named keyword flags (`spv_open`, `cutscene_active`). Add `cinematic_active` in
the same shape: the tactical HUD hides in cinematic mode. This is the visible
half of the feature.

The caller at `engine/host_loop.py:6990` passes
`cinematic_active=App.TopWindow_GetTopWindow().is_cinematic_active()`, alongside
the flags it already gathers there.

Letterbox is NOT applied — BC's cinematic mode is not a cutscene, and the
letterbox pass belongs to `StartCutscene..EndCutscene`.

## Explicitly out of scope

### Phase 2 — mouse-look (deferred, not dropped)

`CinematicInterfaceHandlers.HandleMouseMovement` rotates the rendered set's
active camera by mouse delta. This is the free-camera capability that motivated
the work, but it is a **separate routing problem** — mouse events, not keyboard
— and it needs `CameraObjectClass.Rotate` plus `GetWorldUpTG`/`GetWorldRightTG`.
It gets its own spec.

### Not planned here

- The camera-mode-name on-screen overlay (`UpdateCameraModeText`).
- The `ET_INPUT_ZOOM` / `ET_INPUT_SKIP_EVENTS` / quicksave-quickload entries in
  the same handler table.
- BC's real bubbling chain (see "Constraint" above).

## Known limitation on delivery

Of the six cinematic cameras, **only three exist**: `F2` Chase, `F3` Target,
`F5` WideTarget. `F1` DropAndWatch, `F4` TorpCam and `F6` FreeOrbit resolve to
mode classes that are not implemented, so those keys will do nothing.

`FreeOrbit` is the most valuable of the three missing ones and needs
`MapCameraMode`. This spec makes the *mode* work; the three mode classes are
separate follow-on work tracked against the camera-mode gap list.

## Testing

Unit tests, all in the existing files:

1. Routing picks the focused main window when it has a handler for the event type.
2. Routing falls through to the existing candidates when the focused window has
   no handler for that type.
3. **`F1` reaches the bridge crew menu when cinematic mode is unfocused, and the
   cinematic handler when focused.** This is the regression that matters — it is
   the only test that proves the bridge menus survive.
4. A focused non-main-window (a QuickBattle config pane) is NOT a routing
   candidate.
5. `ToggleCinematicWindow` focus round-trip: focus set, `IsWindowActive()` true,
   toggle again, focus cleared.
6. `_tactical_hud_visible(cinematic_active=True)` is `False`.

The gate (`scripts/check_tests.sh`) must stay at its baseline: 0 ctest failures,
1 known pytest failure.

## Risks

- **Bridge crew menus** (`F1`-`F5`) are live-verified and this change touches
  their dispatch path. Test 3 above is the guard. A live pass on the bridge is
  warranted before this is called done.
- The lazy `CinematicInterfaceHandlers.Initialize` import runs SDK code that has
  never executed in this engine; it may reach for absent surface. It must be
  failure-tolerant enough that a broken import cannot wedge the toggle, and any
  such gap should be recorded rather than swallowed silently.
