# Campaign bugs from the combat event inventory: decisions (2026-11-02)

Bugs found by the combat event inventory (`docs/reference/engine/native-combat/event-inventory.md` §7, branch `ws/combat-effect-queue`), each decided by Mark one at a time on 2026-11-02. **None is built yet**; each becomes a fix on a branch off main. SDK citations are relative to the SDK scripts root.

| # | Bug | Decision | Status |
|---|---|---|---|
| 1 | `ET_WEAPON_FIRED` has no target pointer; pulse weapons never post it | Fix both | Decided; recorded in `event-emitter-gaps.md` #14 |
| 2 | `SetConditionPercentage` is a no-op on every subsystem | Implement; post the same events as weapon damage | Decided |
| 3 | E3M1: an invincible player takes no collision damage | Collision damage becomes the default effect at the end of each ship's `ET_OBJECT_COLLISION` handler chain | Decided |

## 2. `SetConditionPercentage` is a no-op on every subsystem

**Broken:** BC's `ShipSubsystem.SetConditionPercentage(fraction)` (`App.py:5665`) sets a subsystem's condition to a fraction of its maximum. Ours does not exist; the call resolves to a `__getattr__` stub that does nothing (`docs/stub_heatmap.md` ranks it for PhaserBank, TorpedoTube, ShipSubsystem and others). The SDK reaches it through `MissionLib.SetConditionPercentage` (`MissionLib.py:2293-2301`, walks a subsystem's children) and `MissionLib.DamageShip` (`MissionLib.py` ~5228-5278, randomly pre-damages a ship's systems).

**Affected:** 15 mission scripts call it (Episode 2: E2M0, E2M1, E2M2; Episode 3: E3M2, E3M4, E3M5; E4M6; E6M2; Episode 7: `Episode7.py`, E7M1, E7M2, E7M3, E7M6; Episode 8: E8M1, E8M2), plus five missions through `DamageShip`. Examples: E2M0's Geronimo should arrive damaged in stages (`DamageShip("USS Geronimo", 0.1, 0.2, 1)` up to 0.4-0.5) and arrives intact; Episode 7's 10% torpedo-launcher kill (`Episode7.py:116`); E7M2's systems at 50% and 80% (`E7M2.py:1641-1669`); E8M2's cloak kill; E3M5's 15% clamp.

**Decision (Mark):** implement `SetConditionPercentage` on every subsystem: condition = fraction × max condition, through the same path as any other condition change, so a script-set condition **posts the same events as weapon damage** (subsystem destroyed/disabled/operational) and updates the subsystem's state the same way. Then a headless pass over the 15 missions checks each scripted effect lands.

**Interaction:** these calls run inside mission handlers, so once real they change ship state mid-dispatch (event-inventory rule R6). Roadmap decision 9 covers the queued case: the change lands the next tick.

## 3. E3M1: an invincible player takes no collision damage

**Broken:** E3M1 keeps the player invincible except to collisions. `PlayerCollisionHandler` (`Maelstrom/Episode3/E3M1/E3M1.py:843-853`) turns invincibility off, calls `CallNextHandler`, then turns it back on unless the player is dying; its header comment says this is to "apply the damage immediately". So BC applies collision damage as the chain's default, inside `CallNextHandler`. We post the collision events, let every handler run, then apply the impact damage (`engine/appc/collisions.py` `_respond_pair`), by which time invincibility is back on and the damage is skipped (`combat.apply_hit`'s immunity gate).

**Decision (Mark):** collision impact damage becomes the default effect at the end of each ship's `ET_OBJECT_COLLISION` handler chain (the same shape as `ET_ENVIRONMENT_DAMAGE`'s drain, which applies only when the chain passes).

**Consequences:** a handler that does not pass the event on cancels that ship's collision damage, so `ET_OBJECT_COLLISION` becomes a GATE event (event-inventory classes). E1M2 is unchanged in order: `ET_PLANET_COLLISION` is still posted first, and E1M2's `ObjectCollision` handler still runs before the damage (and so before any `ET_OBJECT_EXPLODING`); `test_moving_asteroid_hitting_haven_counts` and the Facility test beside it must stay green. Fits roadmap decision 10: when collisions move into the sim tick and later native, the event and its damage stay one unit.
