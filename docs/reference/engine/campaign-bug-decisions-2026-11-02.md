# Campaign bugs from the combat event inventory: decisions (2026-11-02)

Bugs found by the combat event inventory (`docs/reference/engine/native-combat/event-inventory.md` §7, branch `ws/combat-effect-queue`), each decided by Mark one at a time on 2026-11-02. Bugs 2 and 3 were built with native damage (D, unmerged); bug 1 is not built. Bug 4 was found later, while building D, and is not decided. SDK citations are relative to the SDK scripts root.

| # | Bug | Decision | Status |
|---|---|---|---|
| 1 | `ET_WEAPON_FIRED` has no target pointer; pulse weapons never post it | Fix both | Decided; recorded in `event-emitter-gaps.md` #14 |
| 2 | `SetConditionPercentage` is a no-op on every subsystem | Implement; post the same events as weapon damage | Decided |
| 3 | E3M1: an invincible player takes no collision damage | **Closed by the invincibility ruling** (native-damage M1: invincible = cannot die, damage lands). The 0.1% plan is dropped: it made the drill unwinnable | Re-decided 2026-11-02; built with native damage (D) |
| 4 | Extra hull entries are children of the main hull, so `MissionLib.SetConditionPercentage` on a hull skips the hull | Open | Found 2026-11-02 (native damage, Task 1); **awaiting Mark** |

## 2. `SetConditionPercentage` is a no-op on every subsystem

**Broken:** BC's `ShipSubsystem.SetConditionPercentage(fraction)` (`App.py:5665`) sets a subsystem's condition to a fraction of its maximum. Ours does not exist; the call resolves to a `__getattr__` stub that does nothing (`docs/stub_heatmap.md` ranks it for PhaserBank, TorpedoTube, ShipSubsystem and others). The SDK reaches it through `MissionLib.SetConditionPercentage` (`MissionLib.py:2293-2301`, walks a subsystem's children) and `MissionLib.DamageShip` (`MissionLib.py` ~5228-5278, randomly pre-damages a ship's systems).

**Affected:** 15 mission scripts call it (Episode 2: E2M0, E2M1, E2M2; Episode 3: E3M2, E3M4, E3M5; E4M6; E6M2; Episode 7: `Episode7.py`, E7M1, E7M2, E7M3, E7M6; Episode 8: E8M1, E8M2), plus five missions through `DamageShip`. Examples: E2M0's Geronimo should arrive damaged in stages (`DamageShip("USS Geronimo", 0.1, 0.2, 1)` up to 0.4-0.5) and arrives intact; Episode 7's 10% torpedo-launcher kill (`Episode7.py:116`); E7M2's systems at 50% and 80% (`E7M2.py:1641-1669`); E8M2's cloak kill; E3M5's 15% clamp.

**Decision (Mark):** implement `SetConditionPercentage` on every subsystem: condition = fraction × max condition, through the same path as any other condition change, so a script-set condition **posts the same events as weapon damage** (subsystem destroyed/disabled/operational) and updates the subsystem's state the same way. Then a headless pass over the 15 missions checks each scripted effect lands.

**Interaction:** these calls run inside mission handlers, so once real they change ship state mid-dispatch (event-inventory rule R6). Roadmap decision 9 covers the queued case: the change lands the next tick.

## 3. E3M1: an invincible player takes no collision damage

**Broken:** E3M1 keeps the player invincible except to collisions. `PlayerCollisionHandler` (`Maelstrom/Episode3/E3M1/E3M1.py:843-853`) turns invincibility off, calls `CallNextHandler`, then turns it back on unless the player is dying; its header comment says this is to "apply the damage immediately". So BC applies collision damage as the chain's default, inside `CallNextHandler`. We post the collision events, let every handler run, then apply the impact damage (`engine/appc/collisions.py` `_respond_pair`), by which time invincibility is back on and the damage is skipped (`combat.apply_hit`'s immunity gate).

**First proposal (superseded the same day):** make collision damage the default effect at the end of each ship's `ET_OBJECT_COLLISION` chain. Dropped: it would have made collisions a gating event for one mission's sake.

**What the mission does (read 2026-11-02):** `g_bSimulationMode` is a plain global in E3M1's script, used by no other SDK file. `StartSimulation` (called from `AcceptChallenge`, `TriggerKlingons`, and the end of `BOPCutscene` before `StartKlingonAttack`) sets it, makes the player invincible and installs `PlayerCollisionHandler`; `EndSimulation` (start of `BOPCutscene`, `BOPYouWin`, `BOPYouLose`) clears it, clears the player's invincibility and removes the handler. The other combatants (Geronimo, Ran Kuf, Bird of Prey) are made invincible at creation and when knocked out of the drill (`EndShipSimulation`), and never made vulnerable again. While the flag is on it also gates the player's fire handlers and MacCray's battle lines.

**Decision (Mark):** treat simulation mode as "weapons are simulated", not "the player is invincible":
1. **An engine listener on `g_bSimulationMode`.** The engine learns when E3M1 sets or clears it. The SDK's `global g_bSimulationMode; g_bSimulationMode = TRUE` writes the module dict directly (no attribute hook fires), so the listener comes from the SDK load-time transform pipeline (the AST rewrite every SDK module already goes through), not from polling or editing the script.
2. **While it is on, every weapon hit deals 0.1% of its normal damage**, from any ship. Not 0: a zero-damage hit would skip `apply_hit` (phaser pulses do when damage ≤ 0), post no `ET_WEAPON_HIT`, and break hit-counting handlers (E3M1's own `AmagonHit` counts phaser hits). Shields, subsystems and hull all see the 0.1%.
3. **E3M1's calls making the player invincible are ignored** (`MakePlayerInvincible`, and `PlayerCollisionHandler`'s re-arm). In Mark's words: never needed if the developers had thought about what they really wanted. The other ships' invincibility is kept.
4. **Collisions are unchanged** (events, then damage, no veto). With the player no longer invincible, a crash during the drill does real damage through the normal path; `PlayerCollisionHandler` still runs and its toggling becomes harmless.

**To check when built:** the drill's outcome (how it decides that a ship is knocked out) is unaffected by 0.1% damage; the Klingon attack after the Bird of Prey cutscene, which re-enters simulation mode, plays as before; E1M2's ordering tests stay green (collisions untouched).

### 3a. Re-decided (Mark, 2026-11-02, native-damage phase): the 0.1% plan is dropped

Building it showed the drill cannot end at 0.1%. A drill ship is knocked out only by real damage: hull, power or warp below 25% (player, Geronimo) or 50% (Klingons), via `ConditionSystemBelow` in `GeronimoAttackAI.py`, `RanKufAI.py` and `BOPAI.py`. At 0.1%, shield regeneration (12-24 per second per face) beats the incoming fire 10-65×. Measured headless, the Geronimo's hull was untouched after 600 s of nonstop fire, against below 25% in 15 s at full damage.

The original design is a live-fire exercise in which nobody can die. Every drill ship, the player included, is made invincible; a ship is knocked out by damage; `EndShipSimulation` then repairs, reloads and parks it. That needs invincible to mean "cannot die", which the native-damage phase adopts for every mission (spec `docs/superpowers/specs/2026-11-02-native-damage-design.md` M1, on `project/combat_threading`). With it E3M1 runs as written. There is no simulation-mode listener and no damage scale, and its player-invincibility calls stay. A collision damages the invincible player, which closes the original complaint.

## 4. Extra hull entries are children of the main hull, so the SDK's condition helper skips the hull

**Broken:** some ships' hardpoint files declare more than one `HullProperty`: the Nebula has a critical, non-primary "Bridge" (`ships/Hardpoints/nebula.py:968-973`), and E7M1's BombFreighter has a critical, non-primary "Cargo Hold" (`ships/Hardpoints/bombfreighter.py:15-20`). Since 2026-06-09 (`599144566`, "attach secondary hull (bridge) under primary hull") our engine makes the first one the hull and attaches every other one as a **child** of it (`engine/appc/ships.py`, the `HullProperty` branch of property setup; its comment: "so they are damageable + viewer-visible").

`MissionLib.SetConditionPercentage(pSubsystem, fPercent)` (`MissionLib.py:2293-2301`) sets a subsystem itself only when it has no children; otherwise it sets only its children. That suits a weapon system and its banks. On our hull it means the hull is never set:
- **E3M4** `MissionLib.SetConditionPercentage(pBerkeley.GetHull(), .75)` (`Maelstrom/Episode3/E3M4/E3M4.py:189`): the Berkeley should arrive at 75% hull. Its Bridge goes to 75% and the hull bar shows 100%.
- **E7M1** `StarbaseCollision` (`Maelstrom/Episode7/E7M1/E7M1.py:1872-1876`) sets the freighter's hull to 0 to destroy it. Only the Cargo Hold goes to 0; because it is critical the freighter still dies (native-damage M3), by the wrong route, with its hull bar at 100%.

**Not caused by the combat work.** Before native damage the subsystem setter was a stub, so neither call did anything. D made it real (bug 2) and exposed the parenting.

**Evidence on BC:** whether BC's ships parent extra hull entries under the hull is **not established**; no clean-room read has been done. The mission authors evidently expected the hull itself to change, which suggests BC's hull has no children (**inferred**).

**Options (for Mark):**
- **A.** Stop parenting extra hull entries under the hull: attach them to the ship beside it, keeping what the parenting was for (damageable, shown in the viewer, out of the AI loop). Recommended, after a clean-room check of BC's structure.
- **B.** Keep the parenting and leave the two missions as they behave now.

**To check when built:** E3M4's Berkeley shows 75% hull; E7M1's freighter dies through its hull; the Nebula's Bridge and the freighter's Cargo Hold still take damage, still show in the Ship Property Viewer, and a critical one at 0 still kills.
