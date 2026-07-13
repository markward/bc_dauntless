# Warp collision suppression — design

**Date:** 2026-07-13
**Status:** approved (revised 2026-07-13 after SDK-interface + stub-heatmap audit)

## Problem

A ship engaging inter-system warp can ram objects on the way out and on the way
in. The flythrough warp drives the ship at `100 × MaxSpeed` (≈630 GU/s for a
Galaxy) through two windows where it is still a normal collidable body:

- **Align** (`engine/appc/warp.py:494`, up to 8 s): the ship is still in the
  *source* system set, turning onto the warp heading and — over the last 1 s
  (`_T_ENTER_BOOST`, `engine/warp_vfx.py:24`) — ramping from cruise to warp
  speed. Player control is removed, so the player cannot steer around anything.
- **Exit decel** (`_T_EXIT_DECEL = 2 s`, `engine/warp_vfx.py:25`): the ship
  arrives in the *destination* system at full warp speed and glides down to 0.

Collision damage is quadratic in closing speed (`_ke_damage`,
`engine/appc/collisions.py:108`), so any contact in these windows is an instant
kill. The sphere broadphase can also tunnel clean through a body at that step
size (~10 GU/frame vs. typical ship radii), so contacts are erratic rather than
merely lethal.

The transit itself is already safe: `_WarpDepartAction`
(`engine/appc/warp.py:356`) parks the ship alone in an empty `_WarpTransit` set
at burst.

## What BC does, and why suppression is behaviour-equivalent

BC never has a ship moving at warp speed inside a populated set. `WarpSequence`
hides the ship (`sdk/Build/scripts/WarpSequence.py:102`), *teleports* it into a
dedicated warp set (`:106`, `WarpSequence_GetWarpSet()` at `:44`), teleports it
out to the destination placement (`:196`), and sets it to impulse on arrival
(`:305`). The high-speed portion happens where the ship is the only body. BC
also deconflicts warp-in paths geometrically — `CheckWarpInPath` (`:614-721`)
moves the exit point rather than disabling collisions, and the multiplayer path
rejection-samples against `IsLocationEmptyTG` (`:170-184`).

So BC's *outcome* is "a warping ship never collides with anything" — achieved by
the ship not being there. Our flythrough deliberately flies the ship through
populated sets (that divergence pre-dates this work), so suppression restores
BC's outcome by the only means available once the ship genuinely is there.

Supporting evidence that this is idiomatic: Totally Games' own scripters reached
for collision-off around warp-capable ships by hand — `E2M0.py:724`,
`E2M2.py:503`, `E2M6.py:491-494`, re-enabled at `E2M0.py:3031`, `E2M2.py:2601`.

## SDK-interface audit — verdict

**The collision contract is untouched.** `CanCollide()`
(`engine/appc/objects.py:656`) is the only collision getter we implement; it
reads `_collisions_on`, which this design leaves alone. The other Appc collision
getters (`ObjectClass_GetCollisionFlags`, `ShipClass_IsCollisionDamageDisabled`,
`ProximityManager_GetPlayerCollisionsEnabled`) are unimplemented here **and have
zero callers across all 1228 SDK files** — the observable surface is empty. Appc
exposes no warp-collision primitive at all, so there is no engine call we are
bypassing. No shipped mission depends on a ship colliding during or around a
warp (the nearest thing, E7M2's scripted Vor'cha ram, is an in-set AI ram
unrelated to warp).

**The audit did find one thing the first draft got wrong**, which the revised
solution below fixes: the first draft nominated `WarpVFX` as the canonical
"am I in warp?" state, when the SDK already has a canonical, script-observable
answer — `WarpEngineSubsystem.GetWarpState()` — that our engine leaves
permanently lying at `WES_NOT_WARPING`.

## Solution

Two parts, in order.

### Part 1 — drive the SDK warp state machine

`WarpEngineSubsystem` (`engine/appc/subsystems.py:1225`) already carries the
eight `WES_*` constants and `GetWarpState`/`SetWarpState`, but **nothing in the
engine ever calls `SetWarpState`** — the state is initialised to
`WES_NOT_WARPING` (`subsystems.py:1245`) and never moves. Four SDK sites read it
and therefore always get "not warping":

- `sdk/Build/scripts/Conditions/ConditionInRange.py:209` — uses the unstretched
  cloned-model radius for a warping ship; currently never does
- `sdk/Build/scripts/Bridge/HelmMenuHandlers.py:2465` — a "ship is warping,
  don't bother" early-return that never fires
- `sdk/Build/scripts/Maelstrom/Episode6/E6M3/E6M3.py:2009`
- `sdk/Build/scripts/WarpSequence.py:638` — `CheckWarpInPath` deconfliction

The flythrough drives the ship's warp subsystem through the BC states:

| when | state |
|---|---|
| `_WarpVfxBeginAction` (align start) | `WES_WARP_INITIATED` |
| `_WarpDepartAction` (burst, `t = t_align`) | `WES_WARPING` |
| `_ArriveFinalizeAction` (arrival, exit decel begins) | `WES_DEWARP_ENDING` |
| WarpVFX manager deactivates (decel tail done) | `WES_NOT_WARPING` |

**`TransitionToState` must become real.** It is currently an unimplemented stub
(stub heatmap rank 136) — and that is load-bearing, because the SDK's own NPC
warp-in, `Actions/EffectScriptActions.py:225-226` (`WarpEnterSet`), does:

```python
pWarp.SetWarpState(App.WarpEngineSubsystem.WES_WARPING)
pWarp.TransitionToState(App.WarpEngineSubsystem.WES_DEWARP_INITIATED)
```

With `TransitionToState` a silent no-op, an SDK-warped-in NPC would be left at
`WES_WARPING` **forever** — and under Part 2 that means permanently
non-collidable. So `TransitionToState(s)` sets the state *and* schedules
completion: a subsystem in any `WES_DEWARP_*` state auto-advances to
`WES_NOT_WARPING` after `GetWarpEffectTime()` seconds (default when unset: the
engine's own `_T_EXIT_DECEL`). That completion is driven by a
`tick_warp_states(dt)` called from the host loop immediately **before**
`tick_collisions` (`engine/host_loop.py:6302`), so the collision predicate never
reads a stale state within a frame.

This is the engine owning the FSM, exactly as the C++ engine does — the SDK sets
a state and expects the engine to run it to completion.

### Part 2 — the collision predicate

`collisions._collisions_enabled(obj)` (`engine/appc/collisions.py:53`) gains one
condition: a **`ShipClass`** whose warp subsystem reports a state other than
`WES_NOT_WARPING` is not collidable. Because `_collisions_enabled` filters the
object out of `resolve_collisions` entirely (`collisions.py:318`), one predicate
removes every pair the warping ship is in. No per-pair work, no physics or
native change.

The SDK's `SetCollisionsOn` / `_collisions_on` flag (`objects.py:647`) stays
untouched. The two compose: a mission that turns collisions off keeps them off;
warp suppression is an independent engine-owned overlay, and a mission calling
`SetCollisionsOn(TRUE)` mid-warp cannot un-suppress the warp.

Deriving from the FSM rather than from `WarpVFX` makes the predicate **per-ship**
(no singleton limitation), makes it the same state BC's own `CheckWarpInPath`
uses to identify warping ships, and covers SDK-scripted NPC warps for free.

## Stub traps — both are fatal if missed

1. **The predicate MUST be `isinstance(obj, ShipClass)`-guarded, never
   duck-typed.** A `Planet` has no `GetWarpEngineSubsystem`, so
   `TGObject.__getattr__` returns a truthy `_Stub`; calling it returns a `_Stub`;
   `GetWarpState()` returns a `_Stub`; and `_Stub.__ne__(0)` is `True`
   (`App.py:1955`). A duck-typed predicate would silently make **every planet,
   moon and sun in the game non-collidable**. `collisions._resolve_body`
   (`collisions.py:85`) already imports `ShipClass` for exactly this kind of
   discrimination — follow it.
2. **Read the subsystem defensively.** `GetWarpEngineSubsystem()` can legitimately
   return `None` (ships built without one). Treat missing subsystem as
   "not warping", and use `is None` checks, not truthiness.

## Release condition

Suppression lifts when the ship's warp state returns to `WES_NOT_WARPING`, which
for the flythrough is the frame the WarpVFX manager deactivates — by
construction the end of the exit-decel glide, where the ship is at 0 GU/s and
back in the impulse regime. No separate speed test is needed.

## Leak safety

Warp state is stored state, so it *can* leak where the derived-predicate draft
could not. Three paths close that:

- the host-loop `tick_warp_states` sync forces `WES_NOT_WARPING` whenever the
  WarpVFX manager is inactive but the flythrough ship still reads a warp state
- `_WarpVfxEndAction` (`engine/appc/warp.py:221`) is the existing belt-and-braces
  stop and clears the state
- the mission-swap teardown that already stops the manager
  (`engine/host_loop.py:3650`) clears it too

A ship left in a `WES_DEWARP_*` state by an SDK script self-heals via the
`GetWarpEffectTime()` completion in Part 1.

## Scope

- **In:** the flythrough inter-system warp (`engine/appc/warp.py:489`), plus the
  `WarpEngineSubsystem` FSM it drives.
- **Out — unaffected by construction:** the hard-cut (non-flythrough) warp path
  (`warp.py:538`) never flies the ship at warp speed. It should still leave the
  warp state at `WES_NOT_WARPING`.
- **Out — known follow-up:** `InSystemWarp` (`engine/appc/ships.py:485`) — AI
  hyper-cruise and the player's Ctrl+I dev boost — also runs at `100 × MaxSpeed`
  and stays collidable. AI *avoidance* already stands down during it
  (`engine/appc/collision_avoidance.py:465`) but collision *resolution* does not.

## Adjacent bugs found during the audit (NOT fixed here)

Filed so they are not lost; each is a separate change.

1. **`ship_motion.py:168,185`** — `getattr(ship, "_drift_velocity", None)` returns
   a truthy `_Stub` on a ship that never drifted, so `if drift is not None:`
   passes and `ship._current_speed = drift.Length()` assigns a `_Stub` (whose
   arithmetic collapses to `0`). Every NPC ship takes one frame of corrupted
   `_current_speed`. Stub heatmap ranks 51-52, 33 hits over 9/11 runs. Fix: the
   `obj.__dict__.get(...)` pattern documented at `collisions.py:50`.
2. **`collision_avoidance.py:125`** — calls `obj.GetVelocity()` on planets, which
   is unimplemented (heatmap ranks 7-10, 4924 hits), so avoidance mis-predicts
   planet motion. `collisions._resolve_body` dodges this by forcing planets to
   zero velocity; avoidance should do the same.
3. **Blast radius not in the original design:** every SDK warp-in NPC
   (`loadspacehelper.py:124-127` → `EffectScriptActions.CreateEndWarpSequence` →
   `InitiateDewarp`) now gets ~2 s of non-collidability at mission load, where
   it previously got none. Almost certainly desirable, but it is a real
   behaviour delta across every mission that spawns ships with a warp-in.
4. **`GetWarpState()` non-zero while `GetWarpSequence()` is `None`** — a pairing
   BC never produces (we never call `SetWarpSequence`). Inert today
   (`ConditionWarpingToSet.py:63` and `AI/PlainAI/FollowThroughWarp.py:122,143`
   read only the sequence), but a trap for whoever next wires
   `FollowThroughWarp`.
5. **The dewarp completion timer ticks on wall-clock `_player_dt`, while the SDK
   half of the same FSM (`CreateEndWarpSequence`'s `GetWarpEffectTime()/2`
   delays) runs on GAME time (`g_kTimerManager`).** Under any
   game-time/real-time divergence the engine's auto-complete fires early or
   late relative to the SDK's own explicit clear. Not fatal (the SDK always
   clears explicitly, and `SetWarpState(0)` cancels the pending timer), but the
   FSM should tick on the clock its other half runs on.
6. **Suppression can leave a ship embedded in a body:** if the exit glide ends
   inside a planet/starbase, collisions resume with the ship overlapping and at
   rest — `_respond_pair` returns `None` for any non-approaching pair, so there
   is no de-penetration: the ship silently sits inside the body. BC avoided
   this with `CheckWarpInPath` geometric deconfliction (`WarpSequence.py:614-
   721`), which we do not implement.

## Tests

Part 1 (FSM):
- The flythrough drives `WES_WARP_INITIATED → WES_WARPING → WES_DEWARP_ENDING →
  WES_NOT_WARPING`, and ends at `WES_NOT_WARPING`.
- `TransitionToState(WES_DEWARP_INITIATED)` auto-completes to `WES_NOT_WARPING`
  after `GetWarpEffectTime()`, so the SDK `WarpEnterSet` path terminates.
- A mission swap mid-warp leaves the ship at `WES_NOT_WARPING`.
- The hard-cut warp path never leaves a non-zero warp state.

Part 2 (collisions):
- `resolve_collisions` skips a ship whose warp state is non-zero, and still
  collides a *different* ship in the same set.
- **A `Planet` in the same set stays collidable** (the `_Stub` duck-typing trap).
- `CanCollide()` reads `TRUE` throughout the warp (the SDK flag is not stomped).
- A ship with `SetCollisionsOn(0)` stays non-collidable after warp ends
  (composition, not override).
- Integration: playing a flythrough `WarpSequence` makes the ship
  non-collidable; running it to completion restores collidability.
