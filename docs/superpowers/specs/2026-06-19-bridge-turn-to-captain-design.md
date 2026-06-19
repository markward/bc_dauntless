# Bridge Turn-to-Captain — Design

**Date:** 2026-06-19
**Status:** Approved design, pending implementation plan
**Scope:** When the player selects a bridge officer's station (opens its crew menu), the officer
turns to face the captain and breathes in the turned pose; deselecting turns them back and
resumes normal breathing. Idle ambient gestures are suppressed for the selected officer. Builds
on the merged bridge-character-animation + breathing systems.

## Problem

Selecting a station does nothing to the officer — they keep facing their console. In the original
game the officer turns to face the captain (and breathes "turned") while their menu is open, and
turns back when it closes. The trigger (`CharacterClass.MenuUp()`/`MenuDown()`) and the turn/back
animations are all SDK-defined; we currently stub `MenuUp`/`MenuDown` to a bare flag.

## Principle

SDK-driven and authentic. The trigger is repointed **up the tree to the SDK seam**
`CharacterClass.MenuUp()` / `MenuDown()` (where stock BC put the behavior — `BridgeHandlers` does
`if (pCharacter.MenuUp()): CharacterInteraction(...)`), NOT a bespoke hook in our CEF panel. The
clip choices come entirely from the officer's registered `<location>TurnCaptain` /
`<location>BackCaptain` / `<location>BreatheTurned` animations. The engine owns only the policy
that these fire on menu open/close and that idle is suppressed while a menu is up.

## SDK facts (verified 2026-06-19)

- `MenuUp()` is the stock trigger (`BridgeHandlers.py:612` and peers). It returns truthy when the
  menu came up. Our shim (`engine/appc/characters.py:557-558`) sets `_data["MenuUp"]` and exposes
  `IsMenuUp()` (`:553`) — the queryable state the C++ idle scheduler used to suppress idle.
- Every station registers `<location>TurnCaptain`, `<location>BackCaptain`, and
  `<location>BreatheTurned`, e.g.: `DBEngineerTurnCaptain → SmallAnimations.TurnAtETowardsCaptain`,
  `DBEngineerBackCaptain → CommonAnimations.StandingConsole`,
  `DBEngineerBreatheTurned → CommonAnimations.BreathingTurned`. (Some `BackCaptain` registrations
  are an explicit turn-back clip, e.g. `DBHelmBackCaptain → MediumAnimations.TurnBackAtHFromCaptain`;
  others are just the standing/seated breathe — both resume normal breathing uniformly.)
- Turn clip root handling differs by bridge: D-bridge `db_face_capt_e/s` (0.27s) are **root-less**
  upper-body turns; E-bridge `eb_face_capt_e/s` (0.60s) carry a Bip01 **root rotation + translation**
  (the seated officer swivels). All layer over the placement via `sample_pose_over_base`.
- Our CEF crew menu does NOT call `MenuUp` today (`crew_menu_panel.toggle_menu`); it resolves the
  owning officer via `crew_menu_hotkeys.resolve_character(label)` (used for speech acks). That
  resolution + the toggle's open/close detection are the wiring points.

## Architecture

```
CEF crew menu open/close ─▶ resolve_character(label).MenuUp()/MenuDown()   ← SDK seam (repointed)
                                  │ sets/clears IsMenuUp flag, returns truthy, queues a turn request
                                  ▼
   BridgeCharacterAnimController.update(renderer, anim_mgr) drains the request:
     open : capture TurnCaptain + BreatheTurned → set_idle(BreatheTurned) + submit(TurnCaptain)
     close: capture BackCaptain  + Breathe      → set_idle(Breathe)       + submit(BackCaptain)
                                  ▲
   IdleGestureScheduler skips officers where IsMenuUp() ── suppression (BC-authentic)
```

`MenuUp`/`MenuDown` are headless `CharacterClass` methods with no renderer, so they only RECORD
intent (flag + a controller request via the module registry, mirroring how `TGAnimAction` defers
to a controller). The controller's per-tick pump — which has the renderer — does the
renderer-dependent work. This keeps `MenuUp`/`MenuDown` as the single seam driving both the turn
and the suppression flag.

### Components

- `capture_registered_clip(character, suffix) -> {"clip_nif": str} | None` (in
  `engine/appc/bridge_placement.py`): resolve `<location>+suffix` → builder → clip NIF.
  `capture_breathing` is refactored to `capture_registered_clip(c, "Breathe")` (DRY).
- `CharacterClass.MenuUp()` / `MenuDown()`: set/clear the `MenuUp` flag, return truthy/falsy, and
  notify the character-anim controller (`get_controller().request_turn(self)` /
  `request_turn_back(self)`) when one is registered. Headless-safe (no controller → just the flag).
- `BridgeCharacterAnimController.request_turn(character)` / `request_turn_back(character)`: enqueue
  a pending turn; `update()` drains the queue, capturing clips, loading them, `set_idle`-swapping
  the default (BreatheTurned ↔ Breathe), and `submit`-ing the transient turn/back at a priority
  that preempts idle gestures.
- `crew_menu_panel`: `toggle_menu` resolves the previously-open and now-open officers and calls
  `MenuDown(old)` / `MenuUp(new)` across open / close / switch; `close_open_menu` and `invalidate`
  call `MenuDown` / clear.
- `IdleGestureScheduler`: skip officers where `character.IsMenuUp()`.

## Behavior

- **Open** (menu raised): `MenuUp()` → flag set, `request_turn`. Controller: `set_idle(BreatheTurned)`,
  `submit(TurnCaptain)`. Officer turns to face the captain, then loops `BreathingTurned`. Idle
  gestures suppressed (flag).
- **Close / switch**: `MenuDown()` → flag cleared, `request_turn_back`. Controller:
  `set_idle(Breathe)`, `submit(BackCaptain)`. Officer turns back, resumes normal breathing. Idle
  resumes. Switching A→B turns A back and B toward the captain.
- **Priority:** turn/back transients submit above idle (preempt a running gesture); same band as
  hit reactions (collision rare, acceptable).

## Error handling / edge cases

- Officer with no `TurnCaptain`/`BreatheTurned`/`BackCaptain` registration → that capture returns
  `None`; the controller degrades gracefully (swap the idle if available, skip the missing
  transient) — no crash, no freeze.
- `MenuUp`/`MenuDown` with no controller registered (headless tests) → just the flag; no error.
- Mission swap: `crew_menu_panel.invalidate` clears the open menu; the controller's `reset()`
  already clears idle/active state; officers are re-realised. No stale turned-officer leak.

## The one risk — E-bridge turn root motion

`eb_face_capt_e/s` carry a root rotation + translation. The layered sampler applies the clip's
root track; this is correct if authored station-relative, a displacement if origin-relative
(GUI-verify). If E-bridge officers slide when turning, the fix is a sampler option that keeps the
turn clip's root *rotation* but takes the root *translation* from the placement base. D-bridge
(root-less) is unaffected. Verify E-bridge in the GUI; do not block D-bridge on it.

## Testing

- `capture_registered_clip` resolves each suffix to the right clip; `None` when unregistered;
  refactored `capture_breathing` still passes its existing tests.
- Controller `request_turn` → `set_idle(breathe_turned)` + `submit(TurnCaptain, turn priority)`;
  `request_turn_back` → `set_idle(breathe)` + `submit(BackCaptain)`; missing-clip graceful paths
  (FakeRenderer, no GUI).
- `MenuUp()`/`MenuDown()` set/clear `IsMenuUp()`, return truthy/falsy, and notify the controller.
- `IdleGestureScheduler` skips `IsMenuUp()` officers.
- `crew_menu_panel.toggle_menu` issues `MenuDown(old)`/`MenuUp(new)` correctly across open, close,
  and switch.
- **GUI gate (Mark):** select a station → officer turns to face the captain and breathes-turned,
  no idle look-arounds; deselect → turns back and resumes normal breathing; switching officers
  turns the old one back.

## Out of scope

- Routing through the full stock `BridgeHandlers` mouse-handler path (we drive `MenuUp`/`MenuDown`
  from the CEF menu instead).
- Viewscreen `MenuUp` (the SDK also calls `pViewscreen.MenuUp()`; officers only here).

## Affected files (anticipated)

- `engine/appc/bridge_placement.py` — `capture_registered_clip` + refactor `capture_breathing`.
- `engine/appc/characters.py` — `MenuUp`/`MenuDown` notify the controller + return value.
- `engine/bridge_character_anim.py` — `request_turn` / `request_turn_back` + pending queue drained in `update`.
- `engine/bridge_idle_gestures.py` — skip `IsMenuUp()` officers.
- `engine/ui/crew_menu_panel.py` — `toggle_menu` / `close_open_menu` / `invalidate` drive `MenuUp`/`MenuDown`.
- `tests/` — capture suffixes, controller turn requests, MenuUp/MenuDown + suppression, crew-menu wiring.
- (Possible) `native/` — only if the E-bridge root-translation fallback is needed (deferred until GUI shows it).
