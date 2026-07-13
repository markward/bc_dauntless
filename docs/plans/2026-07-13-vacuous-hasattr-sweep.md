# Follow-up: the remaining vacuous-`hasattr` surface

Written 2026-07-13, out of the `TGObject.__getattr__` fix
(branch `fix/tgobject-getattr-stub-bug`). That change closed the
**underscore** half of the bug class by making `__getattr__` raise
`AttributeError` for our own private names, and fixed the two `IsDying`
sites. This is what it deliberately did **not** touch.

## The residue

`hasattr(obj, "SomeEngineCall")` is still **vacuously True** on every
`TGObject` for any non-underscore name — `__getattr__` hands back a truthy
`_Stub`. That is intentional (SDK scripts chain calls into unimplemented
engine methods), so `hasattr` simply cannot be used as a capability test
against engine surface. There are ~393 `hasattr(` sites in `engine/`.
Use `engine.core.ids.implements(obj, name)` (MRO lookup) at any site that
means "does this object support this call?".

Sweeping all 393 blind is not worth it — most are on objects that really do
implement the method, so the guard is merely redundant. Target the sites where
the receiver can be the *wrong kind of object*. The stub heatmap already names
them.

> **RESOLVED 2026-07-13** (branch `fix/ship-only-loops-non-ship-objects`), with
> one correction to §1: the consumer named below was **wrong**. See
> "What §1 actually was" at the bottom.

## 1. Ship-only loops iterate every set object (evidence: 12 heatmap rows)

`iter_ships` walks `pSet._objects.values()` — **every** object in the set:
waypoints, planets, light placements included. Two ship-only loops consume it
without filtering:

- `engine/host_loop.py:_advance_weapons` calls `ship.GetPhaserSystem()` /
  `GetPulseWeaponSystem()` / `GetTorpedoSystem()` / `GetTractorBeamSystem()`
  unconditionally → heatmap ranks 25–28, 40–43 (`Waypoint.*`), 53–56, 78–81
  (`LightPlacement.*`), 99–102, 115–118 (`Planet.*`). Each returns a `_Stub`,
  whose `GetNumChildSubsystems()` returns a `_Stub` that `range()` coerces to
  0 — so the loop body never runs and the bug is **latent**, paid only in
  wasted stub churn.
- `engine/appc/collision_avoidance.py:125` (`_world_velocity`) calls
  `obj.GetVelocity()` on any obj → ranks 7–10 (`Planet.GetVelocity[.x/.y/.z]`,
  4,924 hits). It is wrapped in `try/except`, but the `_Stub` does not raise —
  it yields `_Stub` components, so the planet's velocity reads as a stub rather
  than zero. Whether that perturbs an avoidance prediction is **unverified**;
  the arithmetic operators collapse to 0, so it most likely does not.

Fix: filter the iterator at the consumer (`isinstance(obj, ShipClass)`), or add
an `iter_ship_objects()` that does. Prefer fixing the consumers — `iter_ships`'
"every set object" semantics are relied on elsewhere.

## 2. `_step_ship_motion`'s immobility gate is accidentally correct

`engine/appc/ship_motion.py:134`:

    if getattr(ship, "IsImmobile", None) is not None and ship.IsImmobile():
        return

`IsImmobile` is defined on `ShipClass` only (`engine/appc/ships.py:605`). For a
waypoint or planet the `getattr` yields a truthy `_Stub`, `_Stub()` is truthy,
and the function returns — so **inert objects skip motion integration for the
wrong reason**. It gives the right answer today; it stops doing so the moment
anyone makes `_Stub` falsy or narrows the gate. Rewrite as
`implements(ship, "IsImmobile") and ship.IsImmobile()`.

## 3. `DamageableObject.IsDying` is only defined on `ShipClass`

Real BC puts `IsDying`/`IsDead` on `DamageableObject`
(`sdk/Build/scripts/App.py:5363`); our shim defines them on `ShipClass`
(`engine/appc/ships.py:1306`). So a non-`ShipClass` `DamageableObject` gets the
stub, and the `hasattr(self, "IsDying") and not self.IsDying()` guards in
`engine/appc/objects.py:758,776` and `engine/appc/subsystems.py:1755` read as
False for it. No live evidence of such an object today (no heatmap row), so this
is latent. Moving the flags up to `DamageableObject` would match BC and remove
the question.

## Sequencing

1 is the one with live hit counts behind it; 2 and 3 are hardening. None is
urgent — all three are latent as far as the evidence goes.

## What §1 actually was (written 2026-07-13, after the fix)

`_advance_weapons` was **never** the culprit, and `iter_ships` has not walked
non-ships since `c3c17f34` (2026-05-12) — it already filters
`isinstance(obj, ShipClass)`, and `_advance_weapons` consumes it via
`_all_ships_for_tick`. The above was inferred, not traced.

The real source of all 24 `{Waypoint,LightPlacement,Planet}.Get*System[.GetNum
ChildSubsystems]` rows is **`engine/appc/warp.py:_silence_ship_weapons`**, called
from `_WarpDepartAction` / `_ArriveFinalizeAction` on `src._objects.values()` —
every member of the source set, on every warp. Its own `hasattr(wsys,
"GetNumChildSubsystems")`-then-call pattern is what produced the exact 2:1 ratio
between the chained rows (108/54) and the getter rows. Fixed with an
`isinstance(ship, ShipClass)` gate in the function, so both call sites are
covered.

`Planet.GetVelocity` (§1's second bullet) had a **second** source the plan
missed: `engine/ui/reticle_text.py:58` reads the *target's* velocity, and a
planet is targetable. Both are fixed with `implements()`.

**Empirical answer to the open question** — does the stub velocity perturb an
avoidance prediction? **No.** `TGPoint3.__init__` calls `float()` on each
component and `_Stub.__float__` returns `0.0`, so the planet's velocity was
already coerced to exactly the zero vector that `collisions._resolve_body`
forces for planets. It was pure churn, not a wrong number — and the same is true
of the reticle's 0 kph readout. Both are pinned by tests now.

## Follow-up: `hasattr(target, "IsDead")` on a targetable non-ship

Five sites read a *target* — which can be a planet — through a vacuous
`hasattr`: `engine/host_loop.py:607`, `engine/appc/tractor.py:127`,
`engine/appc/weapon_subsystems.py:312,1287,1526`. A planet is an `ObjectClass`,
so `IsDead()` returns a truthy `_Stub`, i.e. **a targeted planet reads as
dead**. Moving `IsDying`/`IsDead` up to `DamageableObject` (§3, done) does not
reach it — `Planet` is not damageable. No `Planet.IsDead` / `Waypoint.IsDead`
heatmap row exists across 16 runs, so nothing hits this today; it is latent.
Deliberately left alone rather than swept blind.
