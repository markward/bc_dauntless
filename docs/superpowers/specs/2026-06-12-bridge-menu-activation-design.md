# Bridge menu runtime activation — design

**Date:** 2026-06-12
**Status:** Spec draft, awaiting user review.
**Motivation:** The TG widget tree + CrewMenuPanel (merged earlier today,
[spec](2026-06-12-tg-widget-tree-crew-menus-design.md)) is proven end-to-end by
integration tests but inert in the live app: `tools/mission_harness.py:421`
pre-stubs `Bridge.HelmMenuHandlers` (a relic of when the real module couldn't
import), and the project-root `LoadBridge.py` shim's `CreateCharacterMenus()` is
a `pass` stub, so the SDK sequence that builds the five bridge menus
(`sdk/Build/scripts/LoadBridge.py:131-161`, invoked from `Load()` at line 187)
never runs. A live experiment during verification confirmed the real
`HelmMenuHandlers.CreateMenus()` now runs cleanly in-process and the HELM menu
renders. Separately, `TacticalControlWindow.GetTacticalMenu` is a silent stub
with a known crash path (`TacticalControlHandlers.py:183` →
`STButton_Cast(stub)` → `None.SetChosen`).

---

## Goals

1. **All five bridge menus build at runtime:** `LoadBridge.Load()` (root shim)
   triggers `CreateCharacterMenus()` exactly where SDK line 187 does; Tactical,
   Helm, Science, XO, and Engineer menus are constructed by the real, unmodified
   SDK `Bridge/*MenuHandlers.CreateMenus()` and appear in the CrewMenuPanel bar.
2. **Pre-stub lifted:** neither `tools/mission_harness.py` nor
   `tests/conftest.py` installs `_StubModule("Bridge.HelmMenuHandlers")` any
   more; the real module loads everywhere.
3. **Real TacticalControlWindow menu API:** `FindMenu`, `GetMenuParentPane`,
   `SetTacticalMenu`/`GetTacticalMenu` replace silent `_Stub` fall-throughs;
   the `GetTacticalMenu` crash path is closed.
4. **Faithful epilogue:** the SDK's Tactical-hide block (FindMenu +
   GetMenuParentPane + SetNotVisible) and `SetupBridgeNone()` run after the five
   handlers, as in stock BC.

## Non-goals

- **No real SDK `LoadBridge.Load()`.** The root shim keeps owning bridge-set
  creation; only `CreateCharacterMenus` becomes real. Bridge NIF interiors,
  viewscreen, and character configuration stay engine-side.
- **No menu *behaviour* beyond what already works.** Buttons whose handlers hit
  unimplemented engine surfaces keep silently no-opping through the established
  stub discipline; this spec only activates construction.
- **No warp execution** (unchanged non-goal from the parent spec).
- **No speculative gap-fixes.** Only symbols actually demanded by the four
  newly-exercised handlers (Tactical/Science/XO/Engineer) and the epilogue
  chains get cited state-sinks, same triage discipline as the Helm work.

---

## Design

### Activation path (root `LoadBridge.py` shim)

`Load()` gains a final `CreateCharacterMenus()` call (mirrors SDK
`LoadBridge.py:187`). `CreateCharacterMenus()` mirrors SDK lines 131-161:

1. For each of `Bridge.TacticalMenuHandlers`, `Bridge.HelmMenuHandlers`,
   `Bridge.ScienceMenuHandlers`, `Bridge.XOMenuHandlers`,
   `Bridge.EngineerMenuHandlers` (SDK order): import and call `CreateMenus()`,
   each wrapped in try/except → `logging.exception` + continue. A broken menu
   must not kill mission load; tests keep the gaps loud (see Testing).
2. After the handler loop: `tcw.SetTacticalMenu(tcw.FindMenu(tgl("Tactical")))`
   — stands in for what the original C++ engine set internally
   (`Appc.TacticalControlWindow_SetTacticalMenu` has no Python caller in the
   1228 SDK files; it was engine-driven).
3. Epilogue, also exception-wrapped: load `data/TGL/Bridge Menus.tgl`, hide the
   Tactical menu + its parent pane (`FindMenu`/`GetMenuParentPane`/
   `SetNotVisible`), unload the TGL, call
   `Tactical.Interface.TacticalControlWindow.SetupBridgeNone()`. The
   `SetupBridgeNone` import chain (`Tactical.Interface.TacticalControlWindow`,
   `StylizedWindow`) is triaged at implementation; if it raises, menus still
   work — the Tactical pane is just not pre-hidden.

**Idempotency:** module-level `_menus_created` flag; second `Load()` in the
same session skips menu construction (handler-internal registries like
`SortedRegionMenu_SetWarpButton` must not re-run). The flag is cleared by
`reset_sdk_globals` — the existing mission-swap reset that already unwires the
target menu (see `engine/appc/target_menu.py` docstrings); tests reset it
directly.

### Pre-stub lift

Remove the `_StubModule("Bridge.HelmMenuHandlers")` installation from
`tools/mission_harness.py:421-424` and the matching block in
`tests/conftest.py`. `MissionLib`'s attribute writes land on the real module
(modules accept attribute writes the same as the stub did). Existing
integration tests that pop/restore the stub tolerate its absence (their
`saved is None` branch).

### TacticalControlWindow menu API (`engine/appc/windows.py`)

- `FindMenu(label)` — first menu in `self._menus` whose `GetLabel() ==
  str(label)` (coerces TGString), else `None`. The 66 SDK call sites null-guard
  with `if pMenu:`; `None` for missing is the faithful contract.
- `GetMenuParentPane(label)` — locate the menu via `FindMenu`, return the
  `AddChild`-recorded child whose subtree contains it (panes are
  `_STStylizedWindow`s holding the menu in `_children`), else `None`. SDK call
  sites guard `if pPane != None:`.
- `SetTacticalMenu(menu)` / `GetTacticalMenu()` — stored reference, default
  `None`, set by `CreateCharacterMenus()` step 2.

### GetTacticalMenu crash-path closure

`TacticalControlHandlers.py:183` chains `GetTacticalMenu()
.IsCompletelyVisible()` → `GetButtonW(...)` → `STButton_Cast` → `SetChosen`.
With a real menu returned, the only stub left is `IsCompletelyVisible` —
`STMenu` gains a real `IsCompletelyVisible()` returning `IsVisible()`
(headless has no partial-scroll clipping, so visibility is the faithful
answer). Pre-activation (`GetTacticalMenu()` → `None`) is unreachable in
practice: the manual-aim keybinding only fires in tactical view, which exists
only after `Load()` has built the menus.

---

## Error handling

1. Per-handler try/except with `logging.exception`; construction continues.
2. Epilogue try/except with `logging.exception`; menus survive epilogue
   failure.
3. New shim symbols surfaced by triage follow the parent spec's rules: real
   classes/state-sinks with one-line SDK file:line citations, no `_NamedStub`
   leakage, loud `AttributeError` for non-TGObject classes.

## Testing

Focused subsets only (full pytest OOMs the host).

- **Unit:** `FindMenu`/`GetMenuParentPane`/`Set+GetTacticalMenu` round-trips
  (including missing-label `None`); `STMenu.IsCompletelyVisible` mirrors
  visibility; double-`Load()` builds menus once.
- **Integration (strict — no degraded pass):** with the pre-stub lifted,
  `LoadBridge.Load("GalaxyBridge")` builds **all five** top-level menus into
  `TacticalControlWindow.GetMenuList()`; `GetTacticalMenu()` returns the
  Tactical menu; the Tactical pane is hidden; the helm warp button is
  registered; `CrewMenuPanel.render_payload()` over the full five-menu tree is
  well-formed JSON with five top-level nodes.
- **Regression:** existing helm integration + round-trip tests pass with the
  conftest pre-stub gone; M1_Basic host-loop subprocess tests pass (they now
  exercise menu construction during mission start).

## Follow-ups unlocked

Tactical menu interaction (fire controls wiring), Science/XO/Engineer handler
behaviours as their engine surfaces land, warp execution (own spec).
