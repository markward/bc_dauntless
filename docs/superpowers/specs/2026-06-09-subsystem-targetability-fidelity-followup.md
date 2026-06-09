# Subsystem Targetability Fidelity — Follow-up (deferred)

**Date:** 2026-06-09
**Status:** Deferred backlog item — design notes for a future prompt
**Parent work:** `docs/superpowers/specs/2026-06-09-faithful-hardpoint-subsystem-loading-design.md`

## Why this is deferred

The parent work ("Faithful Hardpoint Subsystem Loading") builds engine pods, tractor
emitters, the bridge, and object emitters into the ship's subsystem tree, makes the
targetable ones player-targetable + damageable, and shows them in the viewer. It does
**not** touch enemy-AI targeting.

That is safe today only because of an accident: `ShipSubsystem.IsTargetable()`
(`engine/appc/subsystems.py:920`) is **hardcoded to return `1`**, ignoring the
`_targetable` flag. The SDK AI loop (`sdk/.../AI/Preprocessors.py:949` `GetTargetableSubsystems`)
only recurses into children of subsystems that report `IsTargetable() == 0`. Because every
subsystem currently reports `1`, the AI never recurses into children — so the new leaves
are invisible to the AI, and enemy behavior is unchanged.

In **stock BC**, aggregators like "Phasers" / "Impulse Engines" / "Tractors" are
`Targetable=0`, and the AI recurses through them to rate and target the individual
banks / pods / emitters. Our hardcoded `IsTargetable()` makes the AI target the
aggregators instead and never reach the leaves. This is a fidelity gap, not just for the
new subsystems but for the existing phaser banks and torpedo tubes too.

## What the overhaul entails

### 1. Honor the hardpoint flag in `IsTargetable()`

`engine/appc/subsystems.py:920` — change `ShipSubsystem.IsTargetable()` from the hardcoded
`return 1` to `return self._targetable`.

### 2. Copy the targetable flag onto every subsystem during construction

`ShipClass.SetupProperties` (`engine/appc/ships.py:623`) currently copies `GetTargetable()`
onto the **hull only** (the hull branch). Every other branch (sensor, shield, impulse,
warp, weapon systems, power, repair) and the child pass must copy
`prop.GetTargetable() -> sub.SetTargetable(...)`, or the flip in step 1 will make
untouched subsystems default to `_targetable = 0` (their `ShipSubsystem.__init__` default)
and vanish from both AI and any targetability-filtered consumer.

**This is the dangerous step.** Audit every subsystem-construction branch and confirm the
flag is set from the property. Add a regression test asserting each top-level subsystem's
`IsTargetable()` matches its hardpoint `Targetable` value (e.g. Galaxy: Hull=1, Sensor=1,
Shield=1, Power=1, Phasers=0, Torpedoes=0, Impulse Engines=0, Warp Engines=0, Tractors=0,
and the leaves: banks=1, tubes=1, pods=1, nacelles=1, tractor emitters=1).

### 3. Consequences to verify

- **AI** (`Preprocessors.py:831,953`): enemy ships will now recurse through the
  non-targetable aggregators and rate/target individual leaves — the stock-BC behavior.
  Re-run the AI smoke/combat integration tests; expect targeting-distribution changes.
- **Player target menu**: once `IsTargetable()` honors the flag, decide whether the menu
  should filter non-targetable aggregators out of the *clickable* set (keeping them as
  expandable parents but not directly targetable) to match BC. The parent work already
  makes them expandable parents; this step would make the parent row non-clickable while
  children remain clickable.
- **Combat** (`engine/appc/combat.py`): confirm damage attribution does not rely on
  aggregators being targetable.
- **`MissionLib.HideSubsystem`** (`sdk/.../MissionLib.py:2166`) toggles the *property's*
  `IsTargetable`; ensure subsystem and property targetability stay coherent (the subsystem
  reads its own `_targetable`, not the property's, after step 1 — decide whether
  `IsTargetable()` should defer to the bound property instead, which would make
  `HideSubsystem` work transparently).

### 4. Suggested test surface

- Unit: `IsTargetable()` returns the flag value; `SetupProperties` copies the flag for
  every subsystem type.
- Integration (real Galaxy hardpoint): per-subsystem targetable matrix as above.
- AI: a combat scenario asserting an enemy can select a leaf subsystem (e.g. a phaser bank)
  as its target subsystem.

## Recommended sequencing

Do this **after** the parent work merges, as its own plan, because step 2 is a
broad, cross-cutting change with real AI-regression risk and deserves isolated review.
