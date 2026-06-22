# Warp Gating — Block Warp on Damage / Hazards (Design)

**Date:** 2026-06-22
**Status:** Approved for planning
**Author:** brainstormed with Mark

## Goal

Prevent engaging warp when the SDK's `WarpPressed` would refuse it: warp/impulse
subsystems unavailable, or the ship inside a nebula, asteroid field, or near a
starbase. On a blocked attempt, surface the authentic Helm-officer line (or a
subtitle), exactly as BC does, and do not warp. Conform to `WarpPressed`'s gate
logic, order, and authored `CantWarp*` dialogue.

This builds on the shipped Stage-1 hard-cut warp (`[[project_warp_mechanism_sdk]]`,
merged 424e12f3). Stage 1 deliberately bypassed SDK `WarpPressed` (its
camera/control work is deferred to later stages); this spec reintroduces the
**gate portion** of `WarpPressed` as our own point-in-time checks, since gates
are pure predicates + dialogue with no camera/control coupling.

## Background — the SDK gate (ground truth)

`sdk/Build/scripts/Bridge/HelmMenuHandlers.py:WarpPressed` (lines 726-846) runs
these checks in order, returning (no warp) on the first failure:

1. No player → silent return.
2. No impulse-engine subsystem → `CallNextHandler` (proceeds; not a block).
3. Impulse engines off (`GetPowerPercentageWanted() == 0.0`) → XO speaks
   `"EngineeringNeedPowerToEngines"`; return.
4. Warp engine **disabled** (`pWarpEngines.IsDisabled()`) → Helm speaks
   `"CantWarp1"`; return.
5. Warp engine **off** (`not pWarpEngines.IsOn()`) → Helm speaks `"CantWarp5"`;
   return.
6. No warp-engine subsystem → silent return.
7. In a **nebula** (`pSet.GetNebula().IsObjectInNebula(pShip)`) → `"CantWarp2"`;
   return.
8. In an **asteroid field** (`pSet.GetClassObjectList(CT_ASTEROID_FIELD)` →
   `AsteroidField.IsShipInside(pShip)`) → `"CantWarp4"`; return.
9. Near a **starbase** (`GetSet("Starbase12")` contains the ship AND
   `AI.Compound.DockWithStarbase.IsInViewOfInsidePoints(pShip, pStarbase)`) →
   `"CantWarp3"`; return.

Each blocked check either plays a Helm `CharacterAction(AT_SAY_LINE, <key>)`, or
— when no Helm character exists — a 3.0s `SubtitleAction` for the same TGL key
from `data/TGL/Bridge Crew General.tgl`.

`WarpStop1-4` are a SEPARATE mission-veto mechanism (a mission refusing to let
the player leave), not these physical/environmental gates — out of scope here.

### Why point-in-time, not event-driven

The SDK has a richer nebula model — `ET_ENTERED_NEBULA`/`ET_EXITED_NEBULA`
broadcast events and `Conditions/ConditionInNebula.py` maintaining membership
(used by dynamic music, mission AI). **`WarpPressed` does not use any of that**;
it does a direct point-in-time `IsObjectInNebula` test at the instant of warp.
This spec mirrors `WarpPressed`: point-in-time geometry only. The event-driven
nebula membership system (and nebula environmental damage) is a separate, larger
feature, explicitly out of scope.

### Engine feasibility (verified)

- Ready (real engine state): `ImpulseEngineSubsystem.GetPowerPercentageWanted`,
  `WarpEngineSubsystem.IsDisabled`/`IsOn`; `CharacterAction` `AT_SAY_LINE`;
  `SubtitleAction_Create`.
- Absent → this spec builds them: `MetaNebula_Create`/`AddNebulaSphere`/
  `IsObjectInNebula`, `Set.GetNebula`, `CT_NEBULA` registration;
  `AsteroidFieldPlacement_Create`, `AsteroidField`/`IsShipInside`/
  `AsteroidField_Cast`, `CT_ASTEROID_FIELD`.
- Available for starbase: `host.ray_trace_mesh` → `renderer::ray_trace_instance`
  (combat/projectiles already use it) covers `LineCollides`. Residual unknown:
  loading the starbase model's named "Inside Visibility N" points
  (`GetPositionOrientationFromProperty`).

## Architecture

A single point-in-time gate evaluated only at warp-engage:

```
warp_gate(ship) -> GateResult(allowed: bool, deny_line: str|None, silent: bool)
```

It runs the six (non-silent-precondition) checks in WarpPressed's order and
short-circuits on the first failure. `on_warp_engage(button)` calls it before
`execute_warp`:

```
on_warp_engage(button):
    player = current player
    result = warp_gate(player)
    if not result.allowed:
        if result.deny_line is not None:
            _speak_deny(player, result.deny_line)   # Helm AT_SAY_LINE, else SubtitleAction
        return                                       # no warp
    execute_warp(button)                             # unchanged Stage-1 spine
```

Each check is an independent predicate so it can be unit-tested in isolation and
later reused (e.g. a HUD "cannot warp" indicator).

## Components

### `engine/appc/warp_gates.py` (new)

- `GateResult` (allowed, deny_line, silent) — small value object.
- `warp_gate(ship) -> GateResult` — ordered evaluation:
  1. `ship is None` → `GateResult(False, None, silent=True)`.
  2. impulse subsystem missing → `GateResult(True, ...)` (SDK `CallNextHandler` =
     proceed; not a block).
  3. impulse off (`GetPowerPercentageWanted() == 0.0`) →
     `GateResult(False, "EngineeringNeedPowerToEngines")`.
  4. warp subsystem missing → `GateResult(False, None, silent=True)`.
  5. warp `IsDisabled()` → `GateResult(False, "CantWarp1")`.
  6. warp not `IsOn()` → `GateResult(False, "CantWarp5")`.
  7. `_in_nebula(ship)` → `GateResult(False, "CantWarp2")`.
  8. `_in_asteroid_field(ship)` → `GateResult(False, "CantWarp4")`.
  9. `_near_starbase(ship)` → `GateResult(False, "CantWarp3")`.
  10. else `GateResult(True, None)`.
- Predicate helpers `_impulse_off`, `_warp_disabled`, `_warp_off`, `_in_nebula`,
  `_in_asteroid_field`, `_near_starbase` — each takes `ship`, returns bool,
  never raises (an un-evaluable check returns False = not blocking).
- `speak_deny(ship, line_key)` — Helm `CharacterAction(AT_SAY_LINE, line_key)` if
  a Helm character exists on the bridge set, else a 3.0s `SubtitleAction` for
  `line_key` from `data/TGL/Bridge Crew General.tgl`; mirrors WarpPressed's dual
  path. Any failure degrades to a silent block (never raises).

### `engine/appc/planet.py` (or a new `engine/appc/nebula.py`) — Nebula

- `MetaNebula` / `Nebula` class registered as `CT_NEBULA`:
  `MetaNebula_Create(r, g, b, visibility, sensor_density, internal_tex,
  external_tex)`; `AddNebulaSphere(x, y, z, radius)` (append to a sphere list);
  `IsObjectInNebula(obj)` (obj world-location inside ANY sphere);
  `GetNebulaSpheres()`; `GetName`/`SetName`; `SetupDamage(hull, shields)` stored
  but unused (the nebula-damage feature is out of scope).
- `SetClass.GetNebula()` returns the set's nebula (first `CT_NEBULA` object), and
  `GetClassObjectList(App.CT_NEBULA)` returns all — both populated when the
  destination `_S.py` `Initialize()` runs (which warp already triggers).
- `Nebula_Cast` for completeness (SDK pattern).

### `engine/appc/` — Asteroid field

- `AsteroidFieldPlacement_Create(name, set_name, ?)` — a placement (like
  `Waypoint_Create`) carrying position (`SetTranslateXYZ`) and `SetFieldRadius`;
  the other authored setters (`SetNumTilesPerAxis`, `SetNumAsteroidsPerTile`,
  `SetAsteroidSizeFactor`, `ConfigField`, `UpdateNodeOnly`) are accepted and
  stored/no-op (they drive asteroid *rendering*, not the gate).
- Materializes an `AsteroidField` object registered as `CT_ASTEROID_FIELD` with
  world position + field radius + `IsShipInside(ship)` (ship within radius).
- `AsteroidField_Cast`.

### Starbase check

- `_near_starbase(ship)`: only when `GetSet("Starbase12")` exists and contains
  the ship. Reads the starbase instance's "Inside Visibility N" points
  (`GetPositionOrientationFromProperty`-equivalent), transforms each to world,
  and tests `LineCollides(point, ship_world_loc)` via `host.ray_trace_mesh`
  against the starbase instance — in view of any inside point ⇒ blocked.
- **Live-only**: requires the renderer + the starbase render instance. Headless /
  no renderer / inside-points unavailable ⇒ the check returns False (does NOT
  block — can't evaluate ⇒ allow). **Fallback** (only if inside-points can't be
  loaded but a starbase instance + a bounding radius are): block within that
  radius of the starbase. The fallback is a clearly-marked approximation;
  faithful inside-points/LineCollides is the primary path.

### `engine/host_loop.py`

- `on_warp_engage(button)` calls `warp_gate(player)` and routes a denial through
  `speak_deny` before (conditionally) calling `execute_warp`. The host supplies
  the renderer handle the starbase check needs (via the existing warp-hooks
  configuration or a small accessor) so `warp_gates` stays renderer-agnostic.

## Error handling & edge cases

- No player / no impulse subsystem / no warp subsystem → silent block (no line),
  matching WarpPressed's silent returns. (Impulse-missing = proceed per SDK.)
- Impulse-off uses the XO line `"EngineeringNeedPowerToEngines"`, distinct from
  the Helm `CantWarp*` lines.
- No nebula / no asteroid field in the set → that check passes (empty list).
- No renderer / headless / inside-points unavailable → starbase check passes
  (don't block what we can't evaluate); proximity fallback only when applicable.
- `warp_gate` and every predicate NEVER raise — an un-evaluable or erroring check
  is treated as non-blocking, so a gate bug can never wedge warp permanently
  shut. `speak_deny` failures degrade to a silent block.

## Testing

**Unit — `tests/unit/test_warp_gates.py`:**
- warp disabled → `(False, "CantWarp1")`; warp off → `(False, "CantWarp5")`;
  impulse off → `(False, "EngineeringNeedPowerToEngines")`; all-clear →
  `(True, None)`.
- Ordering: with multiple conditions true, the first in WarpPressed order wins.
- Silent preconditions: no warp subsystem → `(False, None, silent=True)`.

**Geometry units:**
- `MetaNebula_Create` + `AddNebulaSphere`: a ship inside any sphere →
  `IsObjectInNebula` True, outside all → False; registered as `CT_NEBULA`
  reachable via `Set.GetNebula` and `GetClassObjectList(CT_NEBULA)`.
- `AsteroidFieldPlacement_Create` + `SetFieldRadius`: `AsteroidField.IsShipInside`
  True inside radius, False outside; reachable via
  `GetClassObjectList(CT_ASTEROID_FIELD)` + `AsteroidField_Cast`.

**Integration — `tests/integration/`:**
- `on_warp_engage` with a blocking condition (e.g. warp disabled, or ship inside
  a nebula sphere) does NOT load the destination set (warp suppressed) and routes
  the expected line through `speak_deny` (spy).
- All-clear → warp proceeds (existing end-to-end direct-spine path).
- Starbase: `_near_starbase` with a fake `ray_trace_mesh` (mock host) — in-view
  inside-point → blocked; all inside-points occluded → allowed.

**Live human gate (Mark):** attempt warp (a) with the warp engine damaged, (b)
inside a nebula, (c) inside an asteroid field, (d) near Starbase 12 — confirm the
Helm line/subtitle fires and no warp happens; then clear each condition and
confirm warp works.

## Out of scope

- The event-driven nebula membership system (`ET_ENTERED_NEBULA`/`ET_EXITED_NEBULA`,
  `ConditionInNebula`) and nebula environmental damage.
- `WarpStop1-4` mission-veto warp interrupts.
- Asteroid-field and nebula *rendering* (the gate uses geometry only; visuals are
  the existing/other VFX work).
- Re-routing the warp trigger back through SDK `WarpPressed` (its camera/control
  work stays deferred to later stages).

## Related

`[[project_warp_mechanism_sdk]]`, `[[project_two_set_course_branches]]`,
`[[feedback_sdk_drives_everything]]`, `engine/appc/warp.py`,
`engine/appc/combat.py` (ray_trace_mesh usage), `data/TGL/Bridge Crew General.tgl`.
