# Manual Aim ("mouse pick fire", H key) — design

**Status:** implemented by docs/superpowers/plans/2026-09-15-manual-aim-pick-fire.md; awaiting live verification (see §Live verification).
**Fidelity tier:** SDK-derived UI/state chain (TIER SDK) + five stated
assumptions for the C++-only per-frame pick (the clean-room reference is
silent — `search_reference("MousePickFire")` = measured no-match, 2026-09-15).

## What BC does (SDK evidence)

BC's "manual targeting mode" is the SDK's **"Manual Aim"** button / the engine's
**mouse pick fire** flag.

| Piece | SDK site |
|---|---|
| `H` → `ET_INPUT_TOGGLE_PICK_FIRE` | `DefaultKeyboardBinding.py:154` (`WC_H`, `KS_KEYDOWN`) |
| Toggle handler | `TacticalControlHandlers.py:175 TogglePickFire` — registered on the **TacticalControlWindow** by `TacticalControlHandlers.Initialize` (`:35`); flips the "Manual Aim" `STButton` chosen state, then `pTacWindow.SetMousePickFire(pFireButton.IsChosen())`, then `Bridge.TacticalMenuHandlers.UpdateOrders(0)`. Gated on `pMenu.IsCompletelyVisible() or pTop.IsTacticalVisible()` |
| Button | `Bridge/TacticalMenuHandlers.py:362` — choosable, **AutoChoose** `STButton` labelled TGL `"Manual Aim"`, event `ET_FIRE`, on Felix's Tactical top-level menu. `.Fire` handler (`:1025`) → `UpdateManualAim()` (`:1069`) syncs chosen → `SetMousePickFire` |
| Flag | `TacticalControlWindow.SetMousePickFire / GetMousePickFire` (C++-owned) |
| Fire path | `TacticalControlHandlers.py:129` / `TacticalInterfaceHandlers.py:362`: `pSystem.StartFiring(pShip.GetTarget(), pShip.GetTargetOffsetTG())` — Python never computes an aim point |
| Offset surface | `ShipClass.GetTargetOffsetTG()`, `ShipClass.UseTargetOffsetTG(bool)`, `ET_TARGET_OFFSET_CHANGED`, `StartFiringEvent.GetOffset()`; no Python-visible setter |
| Fallback rule | E3M1 `FixTargeting` (`E3M1.py:2465`): `pPlayer.UseTargetOffsetTG(0)` — "Fix the targeted location to match the targeted subsystem" |
| Drop rule | `BridgeHandlers.DropOutOfManualFireMode` (`:1061`): **only if `IsBridgeVisible()`** → `SetMousePickFire(0)` + `ResetPickFireButton()`. Called from bridge `GotFocus` (`:336`) and `DropMenusTurnBack` (cutscene start, `:1052`) |
| AI coupling | `CheckFiring` (`:1689`): Manual Aim ON ⇒ player fire-at-will preprocessors `SetEnabled(0)`. **Inert in Dauntless** either way — `PreprocessingAI.GetPreprocessingInstance` never returns an `OptimizedFireScript`, so `g_lPlayerFireAIs` stays empty (see `engine/appc/ai.py:304`) |

The per-frame loop *cursor → ray → hull hit → target-local offset* lives
entirely in `Appc` and is invisible to the SDK.

## Assumptions (educated guesses — verify live, each is a one-line change)

1. **Offset = hull-surface hit point in target-local (unscaled) space.** Every
   SDK offset producer is a target-local point (`SetTargetOffset(pSubsystem.
   GetPosition())`, `AI/Preprocessors.py:462`); our torpedo/pulse aim already
   applies `pos + R·(offset·scale)` (`weapon_subsystems.py:2593`).
2. **Only the currently targeted ship is picked.** No retarget on hover.
3. **Cursor off the target hull ⇒ revert immediately** to
   `UseTargetOffsetTG(0)` semantics (locked subsystem, else centre). No hold.
4. **Aim is live only in the exterior (tactical) view.** The flag may be set
   from the bridge (Felix's menu), but no pick runs there.
5. **Update every frame, no smoothing, no `ET_TARGET_OFFSET_CHANGED` emission**
   (its only SDK listener is commented out, `Camera.py:720`).
6. **H also toggles the flag on the bridge with Felix's menu closed.** BC gates
   on `pMenu.IsCompletelyVisible() or pTop.IsTacticalVisible()`; our
   `STMenu.IsCompletelyVisible` is `IsVisible()` (always true headless), so
   the gate always passes. Harmless: the pick is gated on the exterior view,
   and the flag is dropped again when the bridge regains focus.
7. **Chosen rows render for every chosen `STButton`, not only Manual Aim** —
   "Target At Will" (chosen at creation) and the Destroy/Disable order
   buttons show the tint + check from boot. BC draws chosen buttons
   highlighted, so this is faithful, but it is a visible change beyond this
   feature.

## Dauntless design

- `engine/manual_aim.py` (new): `cursor_ray()` (inverse of
  `ship_property_viewer.project`), `note_camera()` (render side, data only),
  `update()` (sim side; the ONLY game-state mutation), `register_toggle_handler()`,
  `drop_mode()`.
- `ShipClass`: `_use_target_offset` / `_manual_target_offset`;
  `UseTargetOffsetTG(v)`, `set_manual_target_offset(p)`,
  `is_using_target_offset()`; `GetTargetOffsetTG()` returns the manual offset
  while in use. `SetTarget` to a different object clears it.
- Phaser tick + drawn beam share one `_phaser_aim_point(ship, target)` helper
  in `host_loop.py` (was two copies of the subsystem-else-centre rule).
- `WeaponSystem.update_weapons` reads the offset **live** from the parent ship
  while manual aim is on (torpedoes/pulse fired mid-hold follow the cursor).
- H is an `input_map` action (`manual_aim`, default `H`, remappable) forwarded
  through `_poll_fire_keys` → `OnKeyDown(App.WC_H)` → SDK binding →
  `TogglePickFire`. **No C++ change**: the poller reads GLFW code 72 from
  `input_map`, not a `KEY_H` export.
- `STButton.SetAutoChoose` becomes real: a CEF crew-menu click on an
  auto-choose button flips `IsChosen()` before its activation event (BC order:
  the `.Fire` handler comment reads "If Manual Aim is now Off…"). Rows carry
  `chosen` and render a check glyph. Side effect: "Phasers Only" and "Target At
  Will" also start toggling (their consumers are the inert `CheckFiring` /
  `CheckSubsystemTargeting`).
- Engine-side twin of `DropOutOfManualFireMode` (BridgeHandlers is stubbed):
  called from `_TopWindow.StartCutscene` and whenever a view flip lands on the
  bridge.

## Out of scope

Bridge-viewscreen cursor aiming; retarget-on-hover; `ET_TARGET_OFFSET_CHANGED`;
making `CheckFiring` live (separate `OptimizedFireScript` gap).

## Live verification (Mark)

Tactical view, target locked: press `H` → Felix's "Manual Aim" shows chosen;
hold fire with the cursor over the target's nacelle → beam lands on the nacelle;
move the cursor off the hull → beam returns to the locked subsystem / centre;
SPACE to bridge → mode drops, button unchosen. Optional fidelity pass: an
`appc_logger`-style snippet logging `GetTargetOffsetTG()` + cursor per tick in
the original game settles assumptions 1–3.
