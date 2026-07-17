# Faithful `IsCompletelyVisible` — gate the power-display auto-rebalance

**Date:** 2026-07-17
**Status:** design approved, awaiting spec review

## Problem

`TGUIObject.IsCompletelyVisible()` is a real engine method inherited by every
UI widget (chain: `EngPowerDisplay → TGPane → TGUIObject → TGEventHandlerObject`;
bound once in `App.py:1297`). In the original engine it returns a cached flag
bit — `(flags >> 10) & 1` — meaning "this object AND every ancestor is visible
and not clipped." It is the same gate `TGPane::Render` uses, so a Python caller
asking `IsCompletelyVisible()` is asking the exact question the draw loop asks.

Dauntless never implemented it. It falls through `TGObject.__getattr__` to a
truthy `_Stub`, and the `_Stub` docstring is **wrong** — it claims to be "Falsy"
but `__bool__` returns `True` and there is no `__eq__`, so `_Stub() == 0` is
`False`. Verified live:

```
IsCompletelyVisible() -> <_Stub> | bool() = True | == 0 -> False
```

### Why it matters (not a benign no-op)

`Bridge/PowerDisplay.py:713` gates the whole power-display update on it:

```python
if (pPowerDisplay.IsCompletelyVisible() == 0) and not bForce:
    return
```

Because `_Stub() == 0` is `False`, **the gate never fires** and the full body
runs on every tick. The body is not just gauge layout — at line 749 it calls
`AdjustPower(...)`, which calls `SetPowerPercentageWanted` on impulse, warp,
shields, phasers, torpedoes, disruptors, and sensors, clamping each subsystem's
*requested* power percentage under a bandwidth deficit and syncing
torps/disruptors to the phaser percentage and warp to impulse.

The driver is `g_pPowerRefreshProcess`, a `LOW`-priority `TimeSliceProcess`
(`PowerDisplay.py:328`) that fires every refresh interval — this is the 4997-hit
entry ranked #4 on the stub heatmap.

Proven end-to-end with a real player set (unforced `Update()` reaches
`AdjustPower`):

```
children after Init: 24
child3 TGFrame_Cast -> TGFrame        # ruler guard passes
gate `==0` -> False                   # visibility gate does not fire
>>> AdjustPower reached on unforced Update(): True
```

### What BC actually intends

`RefreshTimer → Update()` is **unforced**, so in BC the periodic process is a
pure display refresh: when the engineering display is not on screen the
visibility gate fires and `AdjustPower` never runs. `AdjustPower` runs only when:

1. the engineering display is visible (per-tick refresh, gate passes), or
2. a forced `Update(1)` fires — at display (re)build (`PowerDisplay.py:307`) and
   two `TacticalControlWindow` relayout points (lines 800, 1277, "to avoid
   flashing").

So `AdjustPower` is a **UI-side auto-rebalance of requested percentages**, active
while the player is looking at engineering — not a background power governor.

### The regression risk, resolved

Dauntless already enforces the real power economy independently and every tick:
`PowerSubsystem.Update → _pump_consumers → _draw` (`subsystems.py:1933–2020`)
depletes conduit budget and battery per consumer, limiting each draw by the
conduit `min(...)`. `AdjustPower` does not gate this. The overlap is that a
subsystem's requested percentage (`GetPowerPercentageWanted`) feeds real output
(e.g. `subsystems.py:146`, impulse: `cur * GetPowerPercentageWanted()`), so
background `AdjustPower` currently auto-throttles *requested* percentages under
deficit. Making the gate faithful stops that background throttle; the actual
per-tick power draw is untouched.

## Goal

Implement `IsCompletelyVisible()` faithfully as an inherited widget method so the
power-display auto-rebalance runs only when the engineering display is on screen,
matching BC — without disturbing the engine-side power economy or the other six
`IsCompletelyVisible` callers.

## Non-goals

- No change to `PowerSubsystem` / the conduit-draw power economy.
- No change to `_Stub` numeric/bool behavior (only its stale docstring).
- Not driving real visibility state for tactical menus or other widgets. The
  mechanism lands on the base class (inherited, per the RE), but only the power
  display's leaf visibility is actively driven in this change.

## Design

### 1. Inherited mechanism on `TGPane`

Add `IsCompletelyVisible()` to `TGPane` (the concrete base our widgets inherit;
plays the role of the RE's `TGUIObject` vtable slot):

```
IsCompletelyVisible() == own _visible AND (parent is None or parent.IsCompletelyVisible())
```

`TGPane` does not currently track a parent back-reference — `AddChild` /
`InsertChild` set only `_local_left/_top`. Add `child._parent = self` there, and
clear it in `DeleteChild` / `KillChildren`. Where no parent is tracked the method
degrades to the widget's own `_visible`, which is correct for our headless tree
(ancestors above these widgets are either synthetic-always-visible or absent).
This reproduces the RE's "me AND every ancestor" semantics wherever a real chain
exists.

Return an `int` (`1`/`0`) to match the SDK's `== 0` / `== 1` comparisons.

### 2. Blast-radius check — the other six callers are unchanged

| caller | test | today (`_Stub`) | after (real widget, visible) | delta |
|---|---|---|---|---|
| `MissionLib.py:4415` | `IsCompletelyVisible() == 0` → return | `False` (`_Stub()==0`) | `1 == 0` → `False` | none |
| `TacticalControlHandlers.py:185` | `IsCompletelyVisible() or …` | truthy | `1` | none |
| `HelmMenuHandlers.py:407` | options window `== 0` | `_OptionsWindow` → `0` | unchanged (own method) | none |
| `PowerDisplay.py:713` | **the target** | gate never fires | gate fires when display hidden | **fixed** |
| `TacticalControlWindow.py:263` | `IsCompletelyVisible()` | truthy | `1` | none |
| `KeyboardConfig.py:516` | options window | `_OptionsWindow` → `0` | unchanged (own method) | none |

Only the power display changes, and only because we drive its flag (§3). Every
other site keeps returning a truthy value because nothing sets those widgets
not-visible.

### 3. Drive the power-display leaf visibility (pull model)

The CEF Engineering panel already owns the authoritative signal:
`EngineeringPowerPanel._is_engineering_open()` — true when the Engineering crew
menu is the open top-level station menu (`engineering_power_panel.py:55`). Reuse
it as the single source of truth (consistent with the codebase's existing
View-sync pull-model pattern) rather than a second push path.

Inject the same `is_engineering_open` callable into the `EngPowerDisplay`
singleton and derive its leaf visibility from it: when the callable is present,
the display's own-visibility answer is `1` iff engineering is open, else `0`;
when absent (bare unit contexts) it falls back to the base `_visible` flag so
existing construction paths are unaffected. Its synthetic `_parent_pane` stays
always-visible, so the chain-walk (§1) resolves to the leaf signal.

Net effect: display "completely visible" ⇔ engineering menu open ⇒ the per-tick
`RefreshTimer → Update()` runs `AdjustPower` exactly while the player is in
engineering, and skips it otherwise. Forced `Update(1)` paths still punch through
`bForce` as BC intends.

### 4. Housekeeping — fix the stale `_Stub` docstring

Correct the `_Stub` docstring in `App.py`: it is truthy (`__bool__` → `True`) and
has no `__eq__`, so `_Stub() == 0` is `False`. This lie is what made this path
read as a benign no-op. No behavior change to `_Stub`.

## Components touched

- `engine/appc/tg_ui/widgets.py` — `TGPane`: `_parent` back-ref in
  `AddChild`/`InsertChild`, cleared in `DeleteChild`/`KillChildren`; new
  `IsCompletelyVisible()`.
- `engine/appc/tg_ui/eng_power.py` — `EngPowerDisplay`: accept + store an
  `is_engineering_open` callable; leaf-visibility override.
- Host-loop wiring (where `EngineeringPowerPanel` is constructed with its live
  `is_engineering_open` check) — pass the same callable to the `EngPowerDisplay`
  singleton on creation/re-init.
- `App.py` — `_Stub` docstring correction only.

## Testing

Unit (pytest, real SDK loader + real player):

1. `Update()` reaches `AdjustPower` when `is_engineering_open()` → `True`.
2. `Update()` skips `AdjustPower` when `is_engineering_open()` → `False`
   (gate fires), and still runs it under `Update(1)` (`bForce`).
3. `TGPane.IsCompletelyVisible()` chain: hidden ancestor ⇒ `0`; all-visible
   chain ⇒ `1`; no-parent leaf ⇒ own `_visible`.
4. Regression guard: the other six-style call sites (truthy tests on a
   default-visible widget) still return a truthy `1`.

Full gate: `scripts/check_tests.sh` (pytest + ctest, diff vs
`tests/known_failures.txt`).

## Live verification

Mark verifies in-game himself (no checklist hand-off). Design note for that pass:
the observable delta is the *requested* power percentages under a bandwidth
deficit — with engineering **closed**, subsystems keep their full requested
percentage (the conduit draw starves them at the grid); with engineering
**open**, `AdjustPower` rebalances the requested percentages downward as BC does.
The real power economy (battery/conduit depletion, speeds, weapon starvation)
should look identical either way.

## Risks

- **Deficit reachability unknown.** If normal missions rarely exceed the 1%
  deficit threshold in `AdjustPower`, the change is effectively inert. If they do,
  ships under heavy simultaneous draw will keep requesting full power (starved at
  the conduit) instead of auto-reducing requests in the background. This is the
  BC-faithful behavior; Mark's live pass is where it gets eyeballed.
- **`_parent` staleness.** A widget re-parented or orphaned could carry a stale
  `_parent`. Mitigated by clearing on `DeleteChild`/`KillChildren`; only matters
  if `IsCompletelyVisible` is called on an orphan, which none of the seven
  callers do.
