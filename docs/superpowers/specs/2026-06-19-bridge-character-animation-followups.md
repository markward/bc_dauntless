# Bridge Character Animation — Queued Follow-ups

**Date:** 2026-06-19
**Status:** Queued (next project). Findings captured so they need not be re-investigated.
**Context:** The bridge-character-animation branch (placement rest-pose fix + idle gestures +
hit reactions + gesture timing, all layered over the placement pose via `sample_pose_over_base`)
is complete and merged. These two behaviors are authentic BC that we do NOT yet implement; both
reuse the layering + character-anim-controller infrastructure already built.

## 1. Continuous "breathing" idle (default state)

**Authentic behavior:** Bridge officers continuously play a subtle looping breathing idle as their
default state; the `AddRandomAnimation` gestures play *over* it occasionally. We currently freeze
them on a static placement frame between gestures.

**SDK facts:**
- Each character registers a breathe idle, e.g. (Brex):
  - `AddAnimation("DBEngineerBreathe", "Bridge.Characters.CommonAnimations.StandingConsole")`
  - `AddAnimation("DBEngineerBreatheTurned", "Bridge.Characters.CommonAnimations.BreathingTurned")`
  - Seated stations use `SeatedS` etc. (`AddAnimation("EBEngineerBreathe", "...CommonAnimations.SeatedS")`).
- Clips (verified): `standing_console.nif` 2.467s, `standing.nif` 2.467s, `breathing.nif` 12.133s.
  All **root-less** (no Bip01 translation) and partial (38–41 tracks) — i.e. they layer over the
  placement pose exactly like gestures.

**Implementation sketch (reuses existing infra):**
- The native layered sampler already supports looping: an `AnimationState` with
  `loop=true` + `layer_over_rest=true` loops a clip layered over the placement base. (Verify
  `update_animations`' loop `t = fmod(elapsed, dur)` runs before the layered sampling branch — it does.)
- Add a looping-layered play path (small extension of `play_instance_gesture`, e.g.
  `play_instance_idle(iid, clip_index)` setting `loop=true, layer_over_rest=true`).
- Capture each officer's breathe clip (resolve the registered `…Breathe` key → module func →
  clip NIF, mirroring `capture_placement`). Standing → `StandingConsole`, seated → `SeatedS`.
- Make the default/rest state the breathing loop instead of the static frame: on placement,
  start the breathing loop; the controller's AT_DEFAULT returns to the breathing loop (not
  `restore_rest_pose`'s static frame). Keep the static placement frame as the layering base.

**Open design question:** how faithfully to resolve the per-character/per-station breathe clip
(named-key lookup vs a station→clip table).

## 2. Turn-to-captain on station select

**Authentic behavior:** Selecting a station (opening its menu) makes the officer turn to face the
captain; closing the menu turns them back. We currently only set a flag.

**SDK facts:**
- Trigger: `BridgeHandlers` calls `pCharacter.MenuUp()` when a station menu opens
  (`BridgeHandlers.py:612, 692, 738, 784, 831, 884, 942, 973`, …) and `MenuDown()` via
  `DropMenusTurnBack()` (`BridgeHandlers.py:1016`) when it closes.
- Registered turn animations per character/station, e.g. (Brex):
  - `AddAnimation("DBEngineerTurnCaptain", "Bridge.Characters.SmallAnimations.TurnAtETowardsCaptain")`
  - `AddAnimation("DBEngineerBackCaptain", "Bridge.Characters.CommonAnimations.StandingConsole")`
  - E-bridge: `EBTurnAtETowardsCaptain` / `EBTurnBackAtEFromCaptain` (`SmallAnimations.py`).
- Our `MenuUp`/`MenuDown` currently just set `_data["MenuUp"]` (`engine/appc/characters.py:557-558`)
  — no animation.

**Implementation sketch (reuses existing infra):**
- Make `MenuUp()` submit the officer's `…TurnCaptain` registered animation to the
  `BridgeCharacterAnimController` (resolve-by-key, like hit reactions resolve `…ReactLeft`);
  `MenuDown()` submits `…BackCaptain` (or AT_DEFAULT back to breathing once #1 lands).
- The SDK already calls `MenuUp()`/`MenuDown()` at the right moments through our crew-menu system,
  so the hook point is those two methods.
- **Check during implementation:** whether the turn clips carry a Bip01 root *rotation* track. If
  the turn rotates the whole body, the layered sampler will apply it (good); if the turn is meant
  to rotate the root in place, confirm the placement-base root rotation composes correctly.

## Shared notes

- Both behaviors are partial root-less (or root-rotation-only) clips → the existing
  `sample_pose_over_base` layering applies. No new sampler needed; mostly capture + wiring +
  a looping-layered play path.
- Sequencing/priority with the existing controller: breathing = the default loop (lowest priority);
  turn-to-captain and hit reactions preempt; idle gestures sit between. Revisit the priority ladder
  when #1 introduces a persistent default loop (today AT_DEFAULT restores a static frame).
