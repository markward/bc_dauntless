# Warp collision suppression — design

**Date:** 2026-07-13
**Status:** approved, ready for implementation plan

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
at burst. That mirrors what BC does — the original engine never disables
collisions for warp, it moves the ship into a dedicated warp set
(`sdk/Build/scripts/WarpSequence.py:44,105`). Our gap is the two windows either
side of that.

## Solution

Make the warping ship non-collidable for the whole flythrough — align, transit,
and exit decel — as a **derived predicate**, not a stored flag.

`WarpVFX` already is the canonical "am I in warp?" state
(`engine/warp_vfx.py`). It gains knowledge of *which* ship it is animating:

- `WarpVFX.start(...)` takes the ship and records it.
- `WarpVFX.warping_ship()` returns that ship while active, `None` otherwise.

`collisions._collisions_enabled(obj)` (`engine/appc/collisions.py:53`) gains one
condition: an object is not collidable while the WarpVFX manager is active and
animating that object. Because `_collisions_enabled` filters the object out of
`resolve_collisions` entirely (`engine/appc/collisions.py:318`), one predicate
removes every pair the warping ship is in. No per-pair work, no physics or
native change.

### Why derived, not a flag

A flag set at engage and cleared on arrival can leak: an aborted or interrupted
warp strands a permanently non-collidable ship. With a derived predicate there
is nothing to restore, so no abort path can leak. Both existing teardown paths
un-suppress for free:

- mission swap mid-warp already stops the manager (`engine/host_loop.py:3650`)
- `_WarpVfxEndAction` (`engine/appc/warp.py:221`) is the belt-and-braces stop

### Composition with the SDK flag

BC's `SetCollisionsOn` / `_collisions_on` (`engine/appc/objects.py:647`) is left
untouched. The two compose: a mission that turns collisions off keeps them off;
warp suppression is an independent engine-owned overlay. A mission script
calling `SetCollisionsOn(TRUE)` mid-warp cannot un-suppress the warp.

### Release condition

Suppression is live for exactly `WarpVFX.is_active()` and lifts on the frame the
animator deactivates. That frame is, by construction, the end of the exit-decel
glide — the ship is at 0 GU/s, i.e. back in the impulse regime. No separate
speed test is needed.

## Scope

- **In:** the flythrough inter-system warp (`WarpSequence_Create`'s flythrough
  branch, `engine/appc/warp.py:489`).
- **Out — unaffected by construction:** the hard-cut (non-flythrough) warp path
  (`engine/appc/warp.py:538`) never starts the animator and never flies the ship
  at warp speed, so it needs no suppression.
- **Out — known follow-up:** `InSystemWarp` (`engine/appc/ships.py:485`), the
  AI hyper-cruise and the player's Ctrl+I dev boost, also runs at
  `100 × MaxSpeed` and remains fully collidable. AI *avoidance* steering already
  stands down during it (`engine/appc/collision_avoidance.py:465`) but collision
  *resolution* does not. Same class of bug, deliberately not fixed here.

## Limitation

`WarpVFX` is a singleton, so only one ship can be in flythrough warp at a time.
That is already true today; this predicate inherits the constraint rather than
introducing it. In practice flythrough warps are player set-changes. If NPC
flythrough warps ever run concurrently, this needs per-ship clocks.

## Tests

- `resolve_collisions` skips the ship the WarpVFX manager is animating, and
  still collides a *different* ship in the same set.
- Suppression lifts when the manager deactivates, and the SDK `CanCollide()`
  flag reads `TRUE` throughout (proving the SDK flag was not stomped).
- A ship with `SetCollisionsOn(0)` stays non-collidable after warp ends
  (composition, not override).
- Integration: playing a flythrough `WarpSequence` makes the ship
  non-collidable; running the sequence to completion restores it; a mission swap
  mid-warp restores it.
