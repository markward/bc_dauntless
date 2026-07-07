# E1M1 character walk-on — `CharacterAction AT_MOVE` movement primitive

**Date:** 2026-07-07
**Status:** Design — approved, pending spec review
**Branch:** `feat/character-walk-on`

## Problem

At the start of E1M1 (Episode 1 Mission 1), Picard and Saffi speak their opening
lines but **never render**. They should be walking onto the bridge from the
turbolift while the briefing plays. The dialogue is audible; the characters are
invisible for the entire scene.

### Root cause (verified against SDK + engine sources)

The E1M1 opening walk-on is driven entirely by `CharacterAction` with action
type `AT_MOVE`:

- Both characters start hidden in the turbolift. `E1M1.py:209-212` and
  `E1M1.py:693-694`: `SetStanding(1)` / `SetHidden(1)` / `SetLocation("DBL1M")`.
  There is **no `SetHidden(0)` anywhere in E1M1** — the reveal is implicit in the
  native move.
- `PicardWalkOn()` (`E1M1.py:1891`) builds the entrance:
  ```python
  pPicardWalkToP1 = App.CharacterAction_Create(g_pPicard, App.CharacterAction.AT_MOVE, "P1")
  pSaffiWalkToC2  = App.CharacterAction_Create(g_pSaffi,  App.CharacterAction.AT_MOVE, "C2")
  ```
- `AT_MOVE` resolves to `Appc.CharacterAction_AT_MOVE` (`App.py:4565`) — a
  **compiled-native action**. In stock BC it un-hides the character, plays a walk
  clip (which carries a moving root translation), opens the lift door, and ends
  by setting the character's location.

In Dauntless three gaps compound:

1. **`AT_MOVE` is a no-op.** `CharacterAction._do_play` (`engine/appc/ai.py:1199`)
   returns `0.0` for every non-speak action type. Only the four SPEAK/SAY types
   do anything (which is why dialogue plays but nothing moves).
2. **Hidden bridge characters are never placed.** `_place_one_character`
   (`engine/host_loop.py:4163`) early-returns on `placement["hidden"] and
   is_bridge`, so no render instance is ever created for Picard/Saffi.
3. **No bridge-side reveal.** Only comm-set characters get a per-frame
   `IsHidden()`→visibility sync (`_sync_comm_character_visibility`,
   `host_loop.py:4092`). Bridge characters have none.

Net: the two characters begin hidden and unplaced, and the mechanism that should
reveal + walk them (`AT_MOVE`) does nothing.

## The mechanism we are reproducing (SDK ground truth)

`AT_MOVE "P1"` from current location `"DBL1M"` composes the animation key
`"DBL1M" + "To" + "P1"` = `"DBL1MToP1"`, looks it up in the character's
`AddAnimation` registry, and runs the registered builder:

- `Picard.py:143`: `AddAnimation("DBL1MToP1", "...PicardAnimations.MoveFromL1ToP1")`
- `Saffi.py:133`: `AddAnimation("DBL1MToC2", "...MediumAnimations.MoveFromL1ToC2")`

`MoveFromL1ToP1` (`PicardAnimations.py:86`) returns a `TGSequence` that:
1. loads `db_L1toP_P.nif` and plays it as a `TGAnimAction` on the character's
   anim node (the walk — root translation L1→P1 baked into the clip),
2. fires a `LiftDoorAction` on `doorl1`,
3. on completion, sets location via a trailing
   `AT_SET_LOCATION_NAME "DBGuest1"`.

The **seated** transitions use the identical shape — e.g. `MoveFromP1ToP`
(`PicardAnimations.py:108`) loads `db_sit_P.nif`, plays it, and fires
`CS_SEATED`. Walk-on and sit-down are therefore **one mechanism** exercised with
different clips and end-poses, not two features.

### Why the native machinery already (mostly) exists

BC officers are positioned **entirely** by the Bip01 root translation baked into
their clip — `OFFICER_TRANSFORM` is identity (see
`project_bridge_character_animation_shipped`). The non-layered branch of
`update_animations` (`native/src/renderer/animation_update.cc:53-54`) plays a
full clip via `sample_pose` with the **root translation applied**, playing
through over time and settling at the last frame. So a walk clip's moving root
carries the character across the bridge with no new sampler math. The gap is only
that **no host binding starts an instance in that mode** — the existing entry
points force frozen-frame-0 (`set_instance_rest_pose`) or root-anchored gesture
(`play_instance_gesture` → `sample_pose_over_base`, which deliberately anchors the
root, `pose_sampler.cc:78-83`).

## Goals / scope

### In scope — the full `AT_MOVE` movement primitive

1. `AT_MOVE` dispatch: resolve the `<location>To<detail>` builder, extract walk
   clip + end-location, queue a movement request. Deferred completion.
2. Realize-and-reveal hidden bridge characters on demand.
3. Bridge-side per-frame `IsHidden()`→visibility sync.
4. Root-motion playback: a `play_instance_walk` renderer method + host binding
   that starts the existing `sample_pose` play-through branch.
5. Standing **and** seated end-states (walk-on to P1/C2, sit-down to seated
   marks) — the same primitive, both covered.
6. Orientation actions E1M1's opening actually invokes:
   `AT_WATCH_ME` / `AT_STOP_WATCHING_ME`, and `AT_SET_LOCATION_NAME` made real.
7. End-state handoff to the existing placement + breathe-idle path.

### Out of scope (with explicit follow-up tracking — see below)

- **Lift-door re-implementation.** The door already lifts today via the camera
  walk-on (bridge-node animation). This `AT_MOVE` path resolves the builder's
  `LiftDoorAction` and **no-ops it** to avoid double-driving. A GUI verify
  checkpoint confirms character/door timing; if it visibly breaks, revisit.
- **`AT_TURN` / `AT_GLANCE` family beyond what E1M1's opening uses.** Folded in
  only where E1M1 actually calls them; the broader family is a follow-on.
- Walk-on choreography for other missions/episodes (the primitive is general, but
  only E1M1 is verified here).

## Architecture

Seven components. The seam mirrors the shipped turn-to-captain flow: the headless
`CharacterAction` **queues** a request; a controller that has the renderer drains
it on the next update.

### 1. `AT_MOVE` dispatch (headless) — `engine/appc/ai.py`

`CharacterAction._do_play` gains an `AT_MOVE` branch (and the other in-scope
non-speak types). For `AT_MOVE` it calls a new helper (in `bridge_placement.py`,
alongside `capture_registered_clip`) that:

- resolves `_resolve_builder_sequence(character, "To" + detail)`,
- extracts the **walk clip NIF** (the `kind=="character"` `TGAnimAction`), the
  **end-location** (trailing `AT_SET_LOCATION_NAME` detail), and a **seated**
  flag (from the completion event's `CS_SEATED` vs `CS_STANDING`),
- returns `{"clip_nif", "end_location", "seated"}` or `None` (best-effort).

It then queues a walk request on the movement controller. **Completion is
deferred**: the `CharacterAction` does not self-complete on a guessed duration —
the controller fires `ET_ACTION_COMPLETED` (against `g_kTGActionManager`, keyed to
this action) when the walk clip settles, so the mission `TGSequence` advances
exactly when the walk finishes. This is faithful to BC's
`ET_CHARACTER_ANIMATION_DONE`-driven completion. Headless (no renderer / no
resolvable clip) → the action completes inline immediately so the mission never
stalls.

### 2. Movement controller — `engine/bridge_character_walk.py` (new)

A small controller mirroring `BridgeCharacterAnimController`:

- `request_move(character, clip_nif, end_location, seated, on_complete)` — queued;
  drained in `update(dt, *, renderer)` which has the renderer.
- On drain: realize the instance if absent (component 3), reveal it, start the
  root-motion clip (component 4), and record the pending completion + end-state.
- On settle (clip elapsed ≥ duration): set the character's location to
  `end_location`, hand off to placement + breathe idle (component 7), and fire the
  deferred completion event.
- `reset()` on mission swap. Kept separate from the anim controller because its
  lifecycle (one-shot root-motion + completion signalling) differs from the
  transient gesture/turn runner.

### 3. Realize + reveal — `engine/host_loop.py`

Extract the instance-building tail of `_place_one_character` (after the hidden
early-return) into a reusable `_realize_character_instance(controller, r,
character, set_name, is_bridge)` that creates the skinned instance and tags
`_render_instance`. The movement controller calls it for a walk target that has
no instance yet, posing it at its `DBL1M` turbolift frame-0 (`capture_placement`
already returns the `DB_L1toG1_M` frame-0 pose for that location). Then
`SetHidden(0)`.

Add `_sync_bridge_character_visibility` (mirror of the comm-set sync) driving
`r.set_visible(iid, not ch.IsHidden())` each frame for realized bridge
characters, so any `SetHidden` toggle is honored uniformly.

### 4. Root-motion playback — native + host binding

New renderer method `play_instance_walk(iid, clip_index)` that starts the
instance `animation` with `layer_over_rest=false, sample_at_start=false,
sample_at_end=false, loop=false`. Routes to the existing `sample_pose`
play-through branch (root translation applied, settles at end). Additive; no
sampler-math change. New host binding + `engine/renderer.py` wrapper. Requires a
`dauntless` rebuild (host binding change).

### 5. Orientation — `AT_WATCH_ME` / `AT_STOP_WATCHING_ME`

`AT_WATCH_ME` orients the character toward the captain/camera during the walk as
a light body-yaw overlay (a full turn clip layered over a moving-root walk would
fight the root anchor). `AT_STOP_WATCHING_ME` clears it. Implemented as a flag on
the movement/anim state consumed by the pose build; reuses the existing
camera-facing math from the ship-property-viewer / turn work where possible.

### 6. `AT_SET_LOCATION_NAME` made real

Currently a no-op action type. It sets the character's location name so the
end-state handoff (and any subsequent placement) resolves the new station. Both
the builder's trailing action and E1M1's explicit calls route through the same
`CharacterClass` location update.

### 7. End-state handoff — reuse existing placement path

When the walk settles, the controller sets the end-location and calls the
existing `capture_placement` / `capture_breathing` / `play_instance_idle`
machinery so the character transitions from "holding the walk's last frame" to
"standing/seated + breathing at the guest station." No new posing code. Seated
end-states reuse the same handoff with the seated placement clip.

## Data flow

```
SDK E1M1.PicardWalkOn (E1M1.py:1891)
  AT_MOVE "P1" / "C2"        AT_SAY_LINE (Entrance/Intro)
        │                          │
        ▼                          ▼
CharacterAction._do_play      crew_speech.emit  → dialogue (already works ✓)
  resolve <loc>To<detail> builder → {clip_nif, end_location, seated}
  movement_ctrl.request_move(...) ; defer completion
        │
        ▼   (next update, has renderer)
BridgeCharacterWalkController.update
  realize instance if absent (turbolift frame-0)  → SetHidden(0)
  play_instance_walk(iid, clip)                    → root motion L1→P1
        │  (clip settles)
        ▼
  SetLocation(end_location) → placement + breathe idle handoff
  fire ET_ACTION_COMPLETED → mission TGSequence advances
```

## Error handling

Every resolution step is best-effort and collapses to a no-op on failure —
consistent with the existing `capture_*` helpers: a bad builder import, missing
clip path, or headless renderer makes the walk silently not play rather than
crashing the mission. The dialogue path is untouched, so audio is never at risk.
The deferred completion always fires (immediately on the headless/failure path)
so a mission sequence can never stall waiting on a walk that will never run.

## Testing

- **Headless unit tests** — `AT_MOVE` dispatch: key composition
  (`DBL1MToP1` / `DBL1MToC2`), clip + end-location + seated extraction, request
  queued, completion deferred until the controller signals; the seated variant
  (`MoveFromP1ToP` → `db_sit_P`, `CS_SEATED`) resolves through the same path.
- **Controller tests** (`FakeRenderer`) — realize/reveal of a hidden bridge
  character, root-motion playback start, settle → location update + idle handoff,
  completion event fired. `AT_SET_LOCATION_NAME` updates location.
- **Native test** — `play_instance_walk` starts the play-through animation state
  (`layer_over_rest=false`, non-frozen, settles at duration).
- **Gate** — `scripts/check_tests.sh` (pytest + ctest) green; no new entries in
  `tests/known_failures.txt`.
- **GUI verify (final sign-off)** — E1M1 opening in-game: Picard walks to P1,
  Saffi to C2, both visible through the briefing, watch-me orientation reads
  right, they arrive and hand off to their stations; the later sit-down moves
  them to seated marks. The render path cannot be asserted headlessly — this
  matches how prior bridge-character work was signed off. **Door timing** is
  checked here (component out-of-scope but verified for regressions).

## Follow-ups to pick up after this plan (do not lose)

Tracked explicitly at the user's request — these were scoped **out** of this plan
and must be revisited once it lands:

1. **Lift-door coordination / ownership.** Today the door is driven by the camera
   walk-on path and this `AT_MOVE` path no-ops the builder's `LiftDoorAction`.
   Decide the long-term owner and confirm timing across all `AT_MOVE` callers, not
   just E1M1's opening.
2. **Full `AT_TURN` / `AT_GLANCE` CharacterAction family** — the in-scene
   choreography actions beyond `AT_WATCH_ME` and beyond what E1M1's opening uses.
3. **Crew-intro choreography completeness** — any E1M1 `CrewIntros` beats not
   covered by the walk-on + sit-down + watch-me set.
4. **Other-mission walk-ons** — the primitive is general; only E1M1 is verified
   here. Sweep other episodes that use `AT_MOVE` for regressions/coverage.

## Related memories

`project_bridge_camera_walkon`, `project_bridge_character_animation_shipped`,
`project_bridge_character_placement`, `project_bc_character_rigid_skinning`,
`project_view_sync_pull_model`, `feedback_sdk_drives_everything`.
