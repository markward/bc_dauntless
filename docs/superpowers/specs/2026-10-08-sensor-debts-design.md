# Sensor model sub-project 5 — sensor debts — design

Status: design approved by Mark 2026-10-08 (brainstorming). Roadmap:
`2026-10-03-sensor-model-roadmap.md`, row 5. Builds on sub-project 4
(`2026-10-07-sensor-probes-design.md`, merged `0910936f`).

Bounded work: four small changes, no new subsystem. The spec is short on purpose.

## Goal

Pay off the three tuning/fidelity debts sub-projects 1–4 recorded, and correct the
roadmap's count of sensor-less hardpoints.

## Evidence

| Fact | Tier | Source |
|---|---|---|
| Every entry point into BC's global contact manager is gated on `GetParentShip() == GetPlayerShip()`; `ForceObjectIdentified` @0x005678B0 is one of them | RE'd | `STBC-Reverse-Engineering-1/docs/gameplay/sensor-subsystem.md` §"The Global Contact Manager" |
| All four SDK callers of `ForceObjectIdentified` pass the PLAYER's sensors: `MissionLib.py:2445` (`IdentifyObjects`, `GetPlayer()`), `E3M4.py:1500` and `E4M4.py:1077` (`MissionLib.GetPlayer()`), `HelmMenuHandlers.py:1056` (`SetupOrbitMenuFromSet`, `Game_GetCurrentPlayer()` at :1024). No engine module or mod under `mods/` calls it | SDK (grep 2026-10-08) | — |
| Of the stock hardpoints, 17 author no `SetBaseSensorRange`. Seven inherit a parent's via `ParentModule.LoadPropertySet(pObj)`: biranustation→spacefacility, bombfreighter→cardfreighter, enterprise→sovereign, e2m0warbird→warbird, geronimo→akira, rankuf→birdofprey, matankeldon→keldon | SDK | `ships/Hardpoints/*.py` |
| In OUR engine those seven get the parent's range (built headless via `loadspacehelper.CreateShip`, 2026-10-08): Enterprise 2400, Geronimo 2000, E2M0Warbird 3000, RanKuf 1600, MatanKeldon 800, BiranuStation 5000, BombFreighter 2000. CommArray and CommLight have NO sensor subsystem | tested (headless) | throwaway probe, not committed |
| The remaining 10 are asteroid, asteroid1-3, asteroidh1-3, amagon (rocks: genus 3, no AI, never observers) and commarray, commlight (E7M3 "Sensor Post"s, E5M4 satellites, E8M2 Tachyon Emitter, QuickBattle stations running StarbaseAI) | SDK | same |
| Base sensor ranges above 5000 GU: cardfacility and fedoutpost 10000, fedstarbase 12000. Galaxy is 2000 | SDK | hardpoints grep 2026-10-08 |

## Rules

1. **`ForceObjectIdentified` is player-only.** `SensorSubsystem.ForceObjectIdentified`
   returns without effect unless its owner ship is `sensor_contacts.current_player()`,
   the same gate `IdentifyObject` already has. No SDK caller is affected (Evidence row 2).
2. **Sensor-less observers see `sensorless_range_gu`** (Mark's ruling B, 2026-10-08). A
   new dial in `engine/appc/sensor_dials.py`, default **2000.0 GU** (a Galaxy's range),
   read at use by `effective_sensor_range` in both fallback cases (no sensor subsystem;
   `BaseSensorRange <= 0`). The constant `FALLBACK_RANGE_GU` is **deleted**, not aliased,
   so every importer fails loudly and is updated deliberately.
3. **The cloak bubble is capped by `cloak_bubble_cap_gu`** (Mark's ruling B, 2026-10-08:
   cloak stays a range contest, but a station must not out-reach your phasers). A new
   dial, default **30.0 GU**, applied to every observer as
   `min(cap, CLOAK_DETECTION_BASE_GU + r × CLOAK_RANGE_FACTOR)`, after condition and
   power scaling (so over-boost cannot exceed it). Probes obey it through `can_detect`.
   At normal power only the three >5000 GU hardpoints reach the cap, so "every observer"
   means "big stations" in practice; no station test is needed.
4. **Docs.** Roadmap "Later / parked" says 10 hardpoints (not "18 of 52"); row 5 status is
   updated as work lands. The ⚠️ note in `engine/appc/ai_sensor_gate.py`, the
   `FALLBACK_RANGE_GU` comment in `engine/cameras/dof.py`, the "AI-side
   ForceObjectIdentified" comment in `engine/appc/sensor_identification.py`, and the
   CLAUDE.md "Sensor tiers" row are brought in line. Nobody restates a bubble size in
   prose; tests compute it from the constants and the dial.

## Dials

| Name | Default | Step | Min | Max |
|---|---|---|---|---|
| `sensorless_range_gu` | 2000.0 | 250.0 | 250.0 | — |
| `cloak_bubble_cap_gu` | 30.0 | 1.0 | 1.0 | — |

Both are play-test values (Mark's rulings), not recovered BC numbers.

## Test fallout (expected, deliberate)

Many fixtures model no sensors and relied on 30000 GU meaning "fully sighted"
(`test_sensor_detection`, `test_cloak_target_visibility`, `test_cloak_detection_contest`,
`test_sensors_disabled_blanks_target_ui`, `test_perceived_by`, `test_sensor_visibility`,
`test_cloak_subsystem_suppression`, `tests/helpers/cloak_geometry.py`, and others). Each is
updated on its merits: a test about the fallback reads the dial; a test that only needs
its target in sight gets a real sensor subsystem or a target inside the new range. A
stale docstring citing 30000 is corrected, not left.

## Out of scope

Oracle measurements (parked until after first release); the nebula sensor-scale clamp;
a scripted `SetVelocity` on a ship that has an AI (ship motion, not sensors).

## As built

Commits, Tasks 1–3 (`git log --oneline main..HEAD`):

```
f9db25fa fix(sensors): ForceObjectIdentified is player-only, like BC's contact manager
ba270646 feat(sensors): sensor-less observers see the sensorless_range_gu dial (2000 GU), not 30000
8e28eef4 feat(sensors): cap the cloak bubble with the cloak_bubble_cap_gu dial (30 GU)
```

Deviations from this plan, with reason (controller ruling):

1. **Task 2 concealment-latch test observer at z=1000, not 1500.** In the hysteresis band,
   concealment scales range to about 1496 GU, so at 1500 range would have decided the
   test. Both invariants are asserted in `_scene`.
2. **Task 2 CommArray sensor-less test uses a bare `ShipClass()`.** `ShipClass_Create`
   installs a default `SensorSubsystem` (`engine/appc/ships.py:1946`), so a sensor-less
   fixture has to construct the object directly rather than through the factory.
3. **Task 3's `ai_sensor_gate` note says the three biggest stations "exceed" the cap** (the
   plan said "reach"). The five 5000-GU stations land exactly on the cap.

No other deviations.
