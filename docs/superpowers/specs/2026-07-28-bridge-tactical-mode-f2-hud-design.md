# Bridge Tactical Mode — F2 tactical HUD + Orders/Tactics/Maneuvers

**Date:** 2026-07-28
**Status:** Design approved, pre-implementation

## Problem

When the player opens the Tactical officer's menu on the bridge (F2), our engine shows
*only* the Felix drop-down (Report / Manual Aim / Phasers Only / Target At Will). In stock
Bridge Commander, talking to Tactical on the bridge enters a "bridge-tactical" mode that
additionally surfaces the full tactical HUD and the **Orders / Tactics / Maneuvers** command
panes.

Two gaps cause this:

1. **HUD hidden on the bridge.** The five reimplemented HUD panels (`target_list_view`,
   `sensors_panel`, both `ship_display_*`, `weapons_display`) are gated exterior-view-only —
   `_tactical_hud_visible` keys off `is_exterior` alone
   (`engine/host_loop.py:1993-2000`, writes at `:6499-6503`).
2. **Orders/Tactics/Maneuvers do not exist** in our engine at all. The SDK builds them
   (`sdk/Build/scripts/Bridge/TacticalMenuHandlers.py:542` `CreateOrdersStatusDisplay`), but we
   have no projection of them.

There is also a **latent AI bug** that makes the order buttons meaningless even once shown:
issuing any order except **Stop** silently no-ops (see Component 2).

## SDK ground truth

Bridge-tactical is a **superset** of the plain bridge, not a subset. Per
`sdk/Build/scripts/Tactical/Interface/TacticalControlWindow.py`:

- `SetupBridgeTactical()` (`:591`) makes the Felix drop-down pane visible (`:603`) and shows the
  Orders (`:623`), Tactics (`:624`), and Maneuvers (`:625`) panes; sets `g_bIsInBridgeTactical = 1`
  (`:618`). It never hides radar / shields / weapons / target list — those are **persistent**.
- `SetupBridgeNone()` (`:872`) hides the drop-down (`HideTacticalMenu`, `:873`).
- `SetupTacticalTactical()` (`:980`) also shows Orders/Tactics/Maneuvers (`:1006-1008`);
  `SetupTacticalNone()` (`:1378`) hides them (`:1400-1402`) and the drop-down (`:1385-1386`).

So: the HUD panels are persistent in the external tactical view and appear on the bridge only
in bridge-tactical mode; the **Orders/Tactics/Maneuvers panes are visible whenever the Tactical
menu is open, in either view**.

## Scope

**In:** show the HUD on F2 (bridge), build the Orders/Tactics/Maneuvers panel, and fix the AI
bug enough that issuing an order installs an AI that **visibly changes the ship's behavior**.

**Out (follow-up):** full weapon-fire combat fidelity under player orders (Attack actually
destroying the target with tuned weapons behavior); the two secondary AI gaps noted below.

## Design decision: menu-gated, SDK-faithful

Chosen behavior: F2 enters bridge-tactical mode *while the Tactical menu is open*; closing the
menu (ESC / re-press / talking to another officer) restores the clean bridge. This matches
`g_bIsInBridgeTactical` semantics without resurrecting the stub `TacticalControlWindow` into a
real window manager — we adopt the *concept* (a mode flag driving our CEF panels), not a literal
port of the C++ `kSetupFunctions` state machine.

---

## Component 1 — Bridge-tactical mode flag + HUD visibility

**File:** `engine/host_loop.py`.

Compute once per tick, immediately before the visibility block at `~:6494`:

```
bridge_tactical_active = (view_mode.is_bridge
                          and crew_menu_panel.open_menu_label() == "Tactical")
```

`open_menu_label()` (`engine/ui/crew_menu_panel.py:416-423`) returns the open top-level menu's
label; the Tactical station's label is the literal `"Tactical"`
(`engine/ui/crew_menu_hotkeys.py:39,50`). This cleanly distinguishes Tactical from Helm / XO
(`"Commander"`) / Science / Engineer (`"Engineering"`).

Thread the flag into `_tactical_hud_visible` (`:1993-2000`) as a new keyword and change the gate:

```
return (is_exterior or bridge_tactical_active) and not spv_open and not cutscene_active
```

All five `.visible` writes (`:6499-6503`) already fan out from the one `_tac_visible` value, so a
single computation point drives every panel.

**No panel changes required.** All four panel families are view-independent: they read no camera /
reticle / cursor / view-mode state, and their data sources populate regardless of view
(`RebuildShipMenus` runs off the player spatial set at startup and every mission swap,
`engine/host_loop.py:5360-5382`). The only lever is the externally-set `_visible` flag
(`engine/ui/panel.py:27,35-40`). The cursor is already unlocked when a bridge crew menu is open
(`_apply_crew_menu_side_effects`, `:2381`), so clicks into the newly-shown panels work with no
extra plumbing.

---

## Component 2 — OptimizedFireScript fix

**Files:** `App.py` and/or `engine/appc/ai.py` (our shim — **not** the SDK script).

**Bug:** `sdk/Build/scripts/Bridge/TacticalMenuHandlers.py:1861` does
`isinstance(pScript, App.OptimizedFireScript)` inside `StartAI`. `OptimizedFireScript` is defined
nowhere in our tree, so `App.OptimizedFireScript` falls through App-module `__getattr__`
(`App.py:2152-2165`) to a `_NamedStub` **instance** (not a type). `isinstance(x, <instance>)`
raises `TypeError`, which fires on the first node of any `PreprocessingAI`-rooted tree — every
order except Stop — before `SetPlayerAI` (`:1872`) installs the AI. The exception is swallowed at
the button-click boundary (`engine/appc/characters.py:83-87`), so it is a silent no-op with a
dev-log line only. Stop works because `AI.Player.Stay.CreateAI` builds a lone `PlainAI` with no
preprocessing node, skipping `:1861`.

**Fix:** define `OptimizedFireScript` as a real class and relate our fire-preprocess script
instance to it so (a) `isinstance` returns a proper bool and (b) the `:1861` branch (which feeds
`CheckFiring`, `:1867`) engages weapons. The fire-preprocess surface is already wired
(`docs/engine/aieditor-ai-surface-and-gaps.md`: Fire Preprocess ✅, Select Target ✅), so this is
about giving that instance the right type identity.

**DoD:** a headless test issues each order (Attack/Destroy, Disable, Defend, Stop, a tactic, a
maneuver) and asserts `player.GetAI()` is non-None afterward (an AI tree installed), plus a
behavior check where cheap (Stop → `CompleteStop`, `engine/appc/ships.py:307`). Installed trees
are already ticked by `tick_all_ai` (`engine/appc/ai_driver.py:955`).

**Secondary AI gaps (out of scope, degrade gracefully):** `RandomAI` is never ticked, so
Defend's *no-target* idle loop is inert (with a target Defend works); collision-avoidance is
partial, so ships may clip obstacles on attack runs. Both are pre-existing and documented.

---

## Component 3 — TacticalOrdersPanel

**Files:** `engine/ui/tactical_orders_panel.py` (new), `native/assets/ui-cef/js/tactical_orders.js`
(new), `native/assets/ui-cef/css/*` + `index.html` mount, registration in `engine/host_loop.py`.

**Approach A — project the SDK widget tree** (same pattern as `target_list_view` over
`STTargetMenu`). The stock `CreateOrdersStatusDisplay` (`TacticalMenuHandlers.py:542`) already runs
inside `CreateMenus` against our widget shims and stores three panes in module globals:
`g_pOrdersStatusUI` (Orders — a 2-column `STButton` grid), `g_pTacticsStatusUIMenu` (Tactics —
`STCharacterMenu` popup), `g_pManeuversStatusUIMenu` (Maneuvers — `STCharacterMenu` popup). The
panel walks these each tick and projects to CEF.

**Projected model:**
- **Orders** (4): `OrderDestroy`, `OrderDisable`, `OrderStop` (default-chosen), `OrderDefense`
  (`g_lOrders`, `TacticalMenuHandlers.py:70-75`). When Manual Aim is on, Destroy/Disable collapse
  into a single **`OrderAttackManeuver`** button (relabel at `:1486`/`:1502`).
- **Tactics** (7): AtWill / Left / Right / Fore / Aft / Top / Bottom (`g_lTactics`, `:90-98`).
- **Maneuvers** (4): AtWill / Close / Maintain / Separate (`g_lManeuvers`, `:103-108`).
- Each item carries `enabled` / `chosen` / `label` read straight off the widgets. **Availability
  comes free** — `UpdateOrderMenus` (`:1429`) already computes `SetEnabled`/`SetDisabled`/
  `SetChosen`/`SetName` from the `g_dAIs` table (`:133-191`): no target → Tactics/Maneuvers
  disabled; per-order valid tactics; per-(order,tactic) valid maneuvers.

**Layout:** `.bc-panel`(s) in the tactical column, BC's left-to-right order **Orders | Maneuvers |
Tactics** (`:650-695`).

**Click routing:** a click emits `ET_MANEUVER` with the item's `EST_*` subtype
(`:29-51`) to the SDK tactical menu — exactly as `CreateBridgeMenuButton(... App.ET_MANEUVER,
eSubType, pEventDest)` does — driving `Maneuver` (`:1121`) → `UpdateOrders` (`:1168`) → `StartAI`.

**Visibility:** shown whenever `open_menu_label() == "Tactical"` (either view), hidden under
SPV / cutscene, matching `SetupBridgeTactical` + `SetupTacticalTactical` vs `*None`.

**Fallback B (per-widget):** Task 3 first verifies the SDK O/T/M widget construction
(`STCharacterMenu`, `STSubPane`, popup `.Open()`/`.Close()`, `STButton` grid) runs clean against
our shims. Any widget that turns out stubbed is implemented (small), rather than abandoning the
projection model. Unknown widget types are logged-once + skipped (as the crew menu does).

**Registration/reset:** register on the `PanelRegistry` alongside the other tactical panels
(`engine/host_loop.py:~6197-6292`); reset per mission swap with the rest.

---

## Data flow

```
F2 → ET_INPUT_TALK_TO_TACTICAL → CrewMenuPanel raises Tactical drop-down (MenuUp)
   → next tick: bridge_tactical_active = True
       → HUD panels visible (Component 1)
       → TacticalOrdersPanel visible (Component 3)
   → click an order row
       → ET_MANEUVER(EST_*) → SDK Maneuver → UpdateOrders → StartAI
           → (Component 2 fix) AI tree installed on player
           → tick_all_ai drives the ship
       → UpdateOrderMenus recomputes widget enabled/chosen/label
           → panel reflects new state next tick
   → menu closes → bridge_tactical_active = False → HUD + panel hide → clean bridge
```

## Edge cases

- **No target:** Tactics/Maneuvers disabled (from widgets); Orders still shown.
- **Multiplayer:** SDK disables the buttons / hides the panes; preserve that.
- **Broken-attach fallback** (Tactical station left unattached): flag logic tolerates a
  label-only open (no crash if the officer doesn't own the menu).
- **SPV open / cutscene:** HUD and Orders panel stay hidden (existing guards).
- **Unknown widget type in the O/T/M panes:** log-once + skip.

## Testing

- **Unit:** `_tactical_hud_visible` across `bridge_tactical_active` × `is_exterior` × `spv` ×
  `cutscene`; `bridge_tactical_active` computation (label == "Tactical", bridge vs exterior).
- **Unit:** `TacticalOrdersPanel` snapshot — order/tactic/maneuver projection, enabled/chosen/
  label, Manual-Aim Destroy/Disable → AttackManeuver collapse, click → `ET_MANEUVER(EST_*)`.
- **Integration:** Component 2 — per-order AI-install assertion (`player.GetAI()` non-None); Stop →
  `CompleteStop`.
- **Gate:** `scripts/check_tests.sh` (pytest + ctest).
- **Live (`--developer` → mission → F2 on bridge):** HUD + Orders/Tactics/Maneuvers appear;
  issuing an order changes ship behavior; closing the menu restores the bridge. Required because
  green tests cannot see panel visibility or CEF asset paths.

## Plan tasks

1. **Bridge-tactical flag + HUD visibility gate** — re-show the five existing panels on F2.
   Independent; fast visible win; de-risks the mode plumbing.
2. **OptimizedFireScript fix + headless order-install test** — unblock the AI path.
3. **TacticalOrdersPanel** — SDK widget projection + CEF render + `ET_MANEUVER` wiring +
   visibility. Depends on #2 for meaningful behavior; includes the Fallback-B widget verification.
