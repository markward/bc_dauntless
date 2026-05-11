# Ship Identity from Hardpoints — Design

**Date:** 2026-05-11
**Status:** Approved, pending implementation plan
**Touches:** [engine/appc/ships.py](../../../engine/appc/ships.py), [engine/appc/subsystems.py](../../../engine/appc/subsystems.py), new [tests/integration/test_e1m1_ship_identity.py](../../../tests/integration/test_e1m1_ship_identity.py)

## Goal

After `loadspacehelper.CreateShip(<type>, pSet, name, placement)` returns, the resulting `ShipClass` carries the full identity of its hardpoint template — every field the game inspects to answer "what kind of ship is this and what is it capable of." This applies to all eight ship types referenced by Maelstrom E1M1.

The current pipeline already creates a ShipClass, imports the right hardpoint module, registers templates with `g_kModelPropertyManager`, and calls `SetupProperties()`. What this spec broadens is **how many template fields actually land on the live ship**. Today `SetupProperties` propagates mass/inertia (ship-level) and a subset of propulsion + hull fields. This spec extends propagation to cover ship-level identity (affiliation, AI string, ship-name, etc.), full subsystem identity for hull/impulse/warp/sensor, a new `ShieldSubsystem` with per-face data, and minimum live state seeding (full hull condition, full shields, loaded torpedo tubes).

## Why this matters

E1M1 imports and runs through the harness without errors, but every gameplay decision the SDK code makes after CreateShip — affiliation checks, AI dispatch, sensor range, weapon presence, hull queries — currently bottoms out on `None` or default values because the property data never crosses from the template into the live ship. Identity-complete ships are the foundation for the AI and combat work that follows.

## Scope

**In scope.** `SetupProperties` is broadened to dispatch over these property types and write into the live ship + subsystems:

| Property type | Receiver | Fields propagated |
|---|---|---|
| `ShipProperty` | ship | Genus, Species, Affiliation, ShipName, AIString, DamageResolution, ModelFilename, Stationary, DeathExplosionSound, Mass, RotationalInertia |
| `HullProperty` (first only) | primary `HullSubsystem` | MaxCondition, Critical, Targetable, Primary, Radius, DisabledPercentage |
| `ImpulseEngineProperty` | `ImpulseEngineSubsystem` | MaxCondition, NormalPowerPerSecond, MaxSpeed, MaxAccel, MaxAngularVelocity, MaxAngularAccel |
| `WarpEngineProperty` | `WarpEngineSubsystem` | MaxCondition, NormalPowerPerSecond |
| `SensorProperty` | `SensorSubsystem` | MaxCondition, NormalPowerPerSecond, BaseSensorRange, MaxProbes |
| `ShieldProperty` | new `ShieldSubsystem` | MaxCondition, NormalPowerPerSecond, MaxShields[0..5], ShieldChargePerSecond[0..5] |
| `WeaponSystemProperty` (WST_PHASER) | `PhaserSystem` | MaxCondition, NormalPowerPerSecond, WeaponSystemType, SingleFire, AimedWeapon |
| `WeaponSystemProperty` (WST_TORPEDO) | `TorpedoSystem` | MaxCondition, NormalPowerPerSecond, WeaponSystemType |
| `WeaponSystemProperty` (WST_PULSE) | `PulseWeaponSystem` | MaxCondition, NormalPowerPerSecond, WeaponSystemType |
| `WeaponSystemProperty` (WST_TRACTOR) | `TractorBeamSystem` | MaxCondition, NormalPowerPerSecond, WeaponSystemType |
| `TorpedoTubeProperty` | `TorpedoSystem` | one `AddAmmoType(App.AT_ONE)` per tube (second pass) |

**Minimum live-state seeding.** After identity is written:
- Hull current condition = max.
- For each shield face: current = max.
- Each torpedo tube initialized loaded with default ammo (`App.AT_ONE`).

**Out of scope.** AI ticking; weapon firing; damage application; warp speed integration; per-emitter weapon arc geometry; renderer hooks for shield glow / engine sound; player-vs-AI control divergence; cloaking subsystem (not used by any E1M1 ship). These are addressed by later specs.

## ShipClass identity surface

New fields and accessors on `ShipClass`:

| Field | Accessor pair | Default |
|---|---|---|
| genus | `GetGenus / SetGenus` | 0 |
| species | `GetSpecies / SetSpecies` | 0 |
| affiliation | `GetAffiliation / SetAffiliation` | 0 |
| ship-name | `GetShipName / SetShipName` | "" |
| AI-string | `GetAIString / SetAIString` | "" |
| damage-resolution | `GetDamageResolution / SetDamageResolution` | 0.0 |
| model-filename | `GetModelFilename / SetModelFilename` | "" |
| stationary | `IsStationary / SetStationary` | False |
| death-explosion-sound | `GetDeathExplosionSound / SetDeathExplosionSound` | "" |

`ShipProperty` already returns these values via its data-bag `Get*` (auto-generated from `Set*`). `SetupProperties` reads via those getters and writes via the explicit setters. None-skip preserves the existing impulse/warp pattern; zero is treated as a real value.

**Affiliation note.** All SDK hardpoint `ShipProperty` templates set Affiliation(0) (neutral). Mission scripts override per-instance after CreateShip with `pShip.SetAffiliation(App.AFFILIATION_FEDERATION)` etc. So template propagation is lossless — the mission-script override comes later in the same code path.

**Ship-name vs. instance-name.** `Object.SetName(name)` is the per-instance handle ("Dauntless", "Nightingale"). `ShipProperty.GetShipName` is the *class* display name ("Galaxy"). Both are kept; the target panel continues to use `Object.GetName()`; the new `GetShipName()` is for future class-label UI and AI-string dispatch.

## Subsystem hierarchy changes

```
ShipSubsystem
├── HullSubsystem
├── PoweredSubsystem
│   ├── SensorSubsystem
│   ├── ImpulseEngineSubsystem
│   ├── WarpEngineSubsystem
│   ├── ShieldSubsystem                ← NEW
│   └── WeaponSystem                   ← reparented under PoweredSubsystem
│       ├── PhaserSystem
│       ├── TorpedoSystem
│       ├── PulseWeaponSystem
│       └── TractorBeamSystem
```

`WeaponSystem` reparents under `PoweredSubsystem` because every weapon system in BC has a power line; the previous lineage left torpedoes/phasers without `SetNormalPowerPerSecond`.

### Base-class promotion

`ShipSubsystem` gains `_critical: bool`, `_targetable: bool`, `_primary: bool`, `_disabled_percentage: float` (with getters/setters) so every subsystem inherits a uniform identity surface. The current hard-coded `GetDisabledPercentage() == 0.25` is replaced by the field with default 0.25.

### Per-subsystem field additions

- **`HullSubsystem`** — no new fields. Base-class promotion provides the rest.
- **`ImpulseEngineSubsystem`** — no new fields (already complete).
- **`WarpEngineSubsystem`** — no new fields (inherits power from `PoweredSubsystem`).
- **`SensorSubsystem`** — adds `_base_sensor_range: float`, `_max_probes: int` with matching accessors. Defaults 0.
- **`ShieldSubsystem` (new)** — subclass of `PoweredSubsystem`. Six-face slots indexed by `ShieldProperty.FRONT_SHIELDS…RIGHT_SHIELDS`:
  - `_max_shields: list[float]` length 6, default 0.0
  - `_current_shields: list[float]` length 6, default 0.0
  - `_charge_per_second: list[float]` length 6, default 0.0
  - Accessors: `GetMaxShields(face) / SetMaxShields(face, v)`, `GetCurrentShields(face) / SetCurrentShields(face, v)`, `GetShieldChargePerSecond(face) / SetShieldChargePerSecond(face, v)`. Setting a max also seeds current to that max if current was 0 (mirrors `HullSubsystem.SetMaxCondition` seeding).
  - `ShipClass` gains `_shield_subsystem` slot, `GetShieldSubsystem / SetShieldSubsystem`, instantiated by `ShipClass_Create`.
- **`PhaserSystem`** — adds `_weapon_system_type: int`, `_single_fire: int`, `_aimed_weapon: int` with matching accessors. Defaults 0.
- **`TorpedoSystem`** — no new fields beyond `WeaponSystem(PoweredSubsystem)` reparent. Tube count remains observable via existing `GetNumAmmoTypes()`.
- **`PulseWeaponSystem`**, **`TractorBeamSystem`** — no new fields.

## SetupProperties dispatch

Two passes over `GetPropertySet().GetPropertyList()`:

**Pass 1** — for each property, dispatch by `isinstance` and copy fields onto the matching ship/subsystem receiver. `TorpedoTubeProperty` entries are ignored in this pass.

**Pass 2** — count `TorpedoTubeProperty` entries; if `TorpedoSystem` exists on the ship, call `AddAmmoType(App.AT_ONE)` once per tube.

Two passes avoid ordering coupling (tubes appear in the source list before the parent `TorpedoSystemProperty` in `galaxy.py`). Cost: ~30 entries, negligible.

`WeaponSystemProperty` dispatch is by `GetWeaponSystemType()`: WST_PHASER/WST_TORPEDO/WST_PULSE/WST_TRACTOR routes to the matching ship subsystem accessor.

`PhaserProperty`, `PulseWeaponProperty`, `TractorBeamProperty` (per-emitter templates) are no-ops in this spec. They remain readable via the property set for the future Phase 2 weapon-geometry work.

### Minimum live-state seeding

Performed by `SetupProperties` after Pass 1:
- Hull's `SetMaxCondition` already seeds current condition; existing behavior covers this.
- Shield's `SetMaxShields` does the same per face (new, matches the hull pattern).
- Tube seeding happens in Pass 2 by the `AddAmmoType` call.

## Verification

New file: [tests/integration/test_e1m1_ship_identity.py](../../../tests/integration/test_e1m1_ship_identity.py). Parametrized over E1M1's eight ship types: Galaxy, DryDock, FedStarbase, Shuttle, SpaceFacility, Nebula, Akira, FedOutpost.

### Fixture

Module-scoped `setup_sdk` (same pattern as `test_gameloop_harness.py` and the M2Objects tests). Per-test fixture clears `App.g_kModelPropertyManager` templates and creates an in-memory `SetClass` named `test_set`.

### Expected-value source

A table at the top of the file declares per-ship expectation dicts. Values are sourced **directly from the hardpoint files** — the test module reads each `ships/Hardpoints/<name>.py` at module load time, parses out the relevant `Set*` calls, and verifies the hand-coded expectations against the parsed values. If a hardpoint file is updated upstream, the verification step fails loudly rather than letting the test drift. (Alternative considered: hand-code values only. Rejected — too easy to drift from SDK truth. Alternative considered: parse the hardpoint file and compute expectations dynamically. Rejected — hides what's being asserted from a reader of the test.)

Format:

```python
GALAXY_EXPECTATIONS = {
    "script": "Galaxy",
    "ship_property_name": "Galaxy",
    "genus": 1, "species": 101, "affiliation": 0,
    "mass": 120.0, "rotational_inertia": 15000.0,
    "ship_name": "Dauntless", "ai_string": "FedAttack",
    "stationary": 0,
    "has_impulse": True,  "impulse_max_speed": 6.3, ...,
    "has_warp": True,
    "has_sensor": True,   "sensor_base_range": 2000.0, "sensor_max_probes": 10,
    "has_shields": True,  "shield_max_front": 8000.0, ...,
    "has_phasers": True,  "phaser_max_condition": 4000.0,
    "has_torpedoes": True, "torpedo_tube_count": 6,
}
```

Stations (DryDock, FedStarbase, SpaceFacility, FedOutpost) omit propulsion subsystems by setting `has_impulse / has_warp` False; the test loops skip those branches. The `stationary` flag is per-ship and not derivable from "is a station" — DryDock and FedStarbase use `stationary: 1`, but SpaceFacility and FedOutpost use `stationary: 0`. Each expectation dict carries its ship's actual flag value.

### Per-ship test body

```python
@pytest.mark.parametrize("expected", E1M1_EXPECTATIONS, ids=lambda e: e["script"])
def test_e1m1_ship_identity(setup_sdk, expected):
    pSet = App.SetClass_Create()
    App.g_kSetManager.AddSet(pSet, "test_set")
    import loadspacehelper
    ship = loadspacehelper.CreateShip(
        expected["script"], pSet, expected["script"] + "_test", None
    )
    assert ship is not None

    # Ship-level identity
    assert ship.GetGenus()        == expected["genus"]
    assert ship.GetAffiliation()  == expected["affiliation"]
    assert ship.GetShipName()     == expected["ship_name"]
    assert ship.GetAIString()     == expected["ai_string"]
    assert ship.GetMass()         == expected["mass"]
    # ... etc

    # Subsystem identity (conditional)
    hull = ship.GetHull()
    assert hull is not None
    assert hull.GetMaxCondition() == expected["hull_max_condition"]
    assert hull.GetCondition()    == expected["hull_max_condition"]  # seeded

    if expected.get("has_impulse"):
        ies = ship.GetImpulseEngineSubsystem()
        assert ies.GetMaxSpeed() == expected["impulse_max_speed"]
        # ...

    if expected.get("has_shields"):
        ss = ship.GetShieldSubsystem()
        assert ss.GetMaxShields(ShieldProperty.FRONT_SHIELDS) == expected["shield_max_front"]
        assert ss.GetCurrentShields(ShieldProperty.FRONT_SHIELDS) == expected["shield_max_front"]
        # ...

    if expected.get("has_torpedoes"):
        ts = ship.GetTorpedoSystem()
        assert ts.GetNumAmmoTypes() == expected["torpedo_tube_count"]
        for i in range(expected["torpedo_tube_count"]):
            assert ts.GetAmmoType(i) == App.AT_ONE
```

### Three derived "active state" checks

1. `hull.GetCondition() == hull.GetMaxCondition()` for every ship.
2. For ships with shields: `shield.GetCurrentShields(face) == shield.GetMaxShields(face)` for all six faces.
3. For ships with torpedoes: tube count matches expectation and each populated slot is `App.AT_ONE`.

### What the test does not do

- Does not start a game loop or tick.
- Does not exercise mission `Initialize` (separate harness tests already do).
- Does not assert per-emitter weapon geometry.
- Does not load a NIF — pure logic-layer.

### CI cost

Estimated <2 s total, comparable to the existing M2Objects tests.

## File touchpoints

- [engine/appc/ships.py](../../../engine/appc/ships.py) — `ShipClass` new fields + accessors; `SetupProperties` extended with two passes; `ShipClass_Create` instantiates new `ShieldSubsystem`.
- [engine/appc/subsystems.py](../../../engine/appc/subsystems.py) — `ShipSubsystem` base-class field promotion; new `ShieldSubsystem`; `WeaponSystem` reparented under `PoweredSubsystem`; `SensorSubsystem` and `PhaserSystem` field additions.
- [engine/appc/properties.py](../../../engine/appc/properties.py) — no changes; data-bag covers all new getters.
- [tests/integration/test_e1m1_ship_identity.py](../../../tests/integration/test_e1m1_ship_identity.py) — new, parametrized over eight E1M1 ship types.

## Risks and considerations

**Existing test regressions.** `WeaponSystem` reparenting under `PoweredSubsystem` changes the MRO; existing M2Objects and harness tests must continue to pass. Mitigation: the existing tests don't instantiate `WeaponSystem` directly and don't isinstance-check `PoweredSubsystem`, so the MRO change is observation-only at the test layer.

**Hardpoint file format drift.** The verification step at module load parses `Set*` calls. If a hardpoint file uses a syntax this parser doesn't handle, the test fails loudly with a helpful message; that's a feature, not a bug, but the parser must be small and well-defined (extract a fixed list of setter names; ignore the rest).

**Stations.** Stations in E1M1 lack propulsion subsystems (no `ImpulseEngineProperty`, no `WarpEngineProperty`) but otherwise carry the same property mix as proper ships (hull, shields, sensors, often phasers and torpedoes). Their expectation dicts set `has_impulse / has_warp: False`. E1M1 has no asteroids; non-E1M1 ship types (asteroids, freighters, etc.) are out of scope for this spec's parametrized list.

**Default ammo `App.AT_ONE`.** Stock photon torpedo. M2Objects and E1M1 both use this default; later missions (E2M0) override per-ship with `SetAmmoType(App.AT_TWO, 0)`. The override path uses the existing `SetAmmoType` API and is unaffected by this spec.

**`SetupProperties` is called by `loadspacehelper.CreateShip` once.** If the SDK ever calls it twice on the same ship, Pass 2 would double-load torpedo tubes. Guard: Pass 2 checks `len(torpedo_system._ammo_by_slot) == 0` before adding. Cheap and explicit.
