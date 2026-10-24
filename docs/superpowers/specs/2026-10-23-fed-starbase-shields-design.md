# Fed Starbase shields — a deliberate departure from BC

**Status:** built on `feat/fed-starbase-shields`, unmerged, not live-verified.
Companion to `fix/reversed-weapon-arcs` (the starbase's phasers fire at all),
which reached main first in a050c72d9; the two are independent.

## Decision

The stock Federation Starbase gets shields. **This is a Dauntless departure,
not a fidelity fix**: the original game has none.

| Field (all six faces) | Stock BC | Dauntless |
| --- | --- | --- |
| `SetMaxShields` | 0 | 6000 |
| `SetShieldChargePerSecond` | 1.0 | 5.0 |
| `ShieldGenerator.SetNormalPowerPerSecond` | 1.0 | 600 |

Values are the Cardassian Starbase's, chosen by Mark 2026-10-23. For
comparison: Fed Outpost 5000/face, 8/s, 600; Space Facility 6000/face, 10/s,
200. The Fed Starbase hull is 220000 and its power plant outputs 5000.

**Scope: everywhere the stock Fed Starbase spawns** — Quick Battle and the
campaign (26 Maelstrom mission scripts reference `FedStarbase`). Mark chose this
over a Quick-Battle-only mechanism. No mission script reads or sets the
starbase's shields, so no scripted beat depends on the old zero. E7M1's
freighter collisions damage its hull by script (`SetConditionPercentage`), and
ship-to-ship collisions bypass shields in `collisions.py` (only a rock meets a
shield bubble), so that scene and docking are unchanged.

## Evidence that BC has none

- `ships/Hardpoints/fedstarbase.py` declares every face at `SetMaxShields 0`.
- stbc-oracle `mission-scenes.md` records Starbase_12 (FedStarbase) at red
  alert with all six faces at 0.00 in E3M1, E4M5, E4M6, E7M6 and E8M1.

## How it is applied

Through the machine-owned `engine/appc/hardpoint_overrides.py` (`_fedstarbase`),
written by `HardpointOverridesFileTarget.write` — the Ship Property Viewer's own
save path — never by hand. The override hook runs at the end of
`_SDKLoader.exec_module`, after the hardpoint registers its `Shield Generator`
template and before `LoadPropertySet`; `ShipClass.SetupProperties` then copies
each face's max and charge rate from the `ShieldProperty` onto the live
`ShieldSubsystem`. A mod that ships its own `fedstarbase.py` owns the ship and
skips the override (`sdk_overrides.on_sdk_module_exec`).

Writer fix this needed: `set_setter` de-duplicated by setter name, so six
`SetMaxShields(face, v)` calls collapsed into one. `SetMaxShields` and
`SetShieldChargePerSecond` are now keyed by their first (face) argument, like
the `SetGlowRegion*` / `SetLightEmitter*` index.

## Generator power

Raising the draw from 1/s to 600/s does **not** change shield regeneration:
`ShieldSubsystem.Update` reads only each face's max and charge rate, matching
the original's measured behaviour (regen identical at every alert level and at
50 % generator power, stbc-oracle bible §5.3 S5). The 600 makes the station's
power readout and battery draw consistent with the other stations. Total
normal draw becomes 1801/s (sensors 400, phasers 800, shields 600,
engineering 1) against a 5000 output.

## Tests

- `tests/unit/test_hardpoint_override_writer.py::test_shield_face_setters_are_keyed_by_face`
- `tests/integration/test_quickbattle_fed_starbase_shields.py` — an enemy Fed
  Starbase spawned from the Quick Battle setup panel has 6000 on every face,
  5/s, 600 power, and a 1000-point phaser hit on its front face is fully
  absorbed with the hull untouched.
