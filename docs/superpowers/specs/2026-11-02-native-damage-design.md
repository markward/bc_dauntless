# Native damage (roadmap D) — design

**Status:** built 2026-11-03 (§10); not live-verified; unmerged. Roadmap workstream D, the next phase on the threading path (presentation RNG → **D** → kernels off the lock (I) → AI ↔ combat pipeline (J)).
**Branch:** `ws/combat-native-damage`, off `project/combat_threading` (`e2b100f2c`), worktree `.claude/worktrees/native-combat-k3`.
**Input maps:** `docs/reference/engine/native-combat/damage-map.md` (DM, the line-by-line walk and the bit-exactness hazards §7) and `damage-map-refresh.md` (DR, the current state, handler scan, death, numbers).
**Governing rule (Mark):** the sim runs without checking in with Python; pick the reading of the original scripts that allows it.

## 1. Why

Damage is the last Python a kernel checks in with mid-step: every K2 damage pulse hands a record back to Python, inside the walk, and every K3 hit runs `combat.apply_hit` after the step (DR §1). One hit is a synchronous Python chain: shield face, hull, overlapping subsystems, the `SetCondition` side effects (watchers, subsystem events, repair queue, zero crossings, death), presentation, then `ET_WEAPON_HIT`, with every handler running inside the hit (DR §2-§3). Until damage is native and its effects are queued, combat cannot leave the Python thread (I) or be pipelined against AI (J).

Cost is not the reason: `apply_hit` is 0.09 ms per tick in the 64-ship fight, 0.52 hits per tick (DR §9). The reason is the check-in.

## 2. Mark's rulings (2026-11-02)

- **M1. Invincible means "cannot die".** `ShipClass.SetInvincible(1)`: damage lands, but the ship never begins dying; a critical subsystem may sit at 0. `SetHurtable(0)`: the ship takes no damage (today's immunity). `ShipSubsystem.SetInvincible(1)`: that subsystem takes no damage. This is the scripts' reading (E3M5 "set ship invincible so it won't actually blow up", E6M1, E3M1's drill, E8M2's Matan disable, E2M0's Warbird warp-out; DR §3.7) and replaces `IsImmuneToDamage = invincible or not hurtable`. Radiation follows the same flags.
- **M2. Hit events go to the tick boundary.** `ET_WEAPON_HIT`, `ET_SUBSYSTEM_DISABLED/DESTROYED/OPERATIONAL`, `ET_ADD_TO_REPAIR_LIST`, condition-watcher crossings and `ET_OBJECT_EXPLODING` become effect-queue kinds, delivered at the flush in emission order (decision 9; BC's own bus enqueues, DR §3.6). **The death splash is queued too, after its `ET_OBJECT_EXPLODING`**, so E2M2's "make the partner invincible" still runs before the splash.
- **M3. A critical subsystem at 0 kills**, unless the ship is invincible. This applies to every condition write (`DamageSystem`, `SetCondition`, `SetConditionPercentage`, severance), not only weapon damage: E3M5's `KillGonDev` sets the hull to 0 and makes the ship invincible "so it won't actually blow up".
- **M5. The death check runs at the tick boundary** (Mark, after Task 1's first attempt), for every write, hits and scripts alike. A ship whose critical subsystem is at 0 begins dying at the flush unless it is invincible by then. `KillGonDev` sets the hull to 0 *before* `SetInvincible(1)` (`E3M5.py:1060-1067`), so an in-write check would kill the derelict at creation. Consequences: a ship hit to 0 stays targetable, and takes further hits, for the rest of that tick; the C++ kernels never decide deaths, only write conditions.
- **M4. Campaign bug 2 is built in this phase; bug 3 is closed by M1** (decisions in `docs/reference/engine/campaign-bug-decisions-2026-11-02.md` on main).
  - Bug 2: `SetConditionPercentage` on every subsystem = fraction × max condition through the normal condition path, posting the same events.
  - Bug 3: the 0.1% "simulated weapons" plan is **dropped** (Mark, 2026-11-02). At 0.1%, shield regeneration beats the incoming fire 10-65×, so no drill ship drops below its knock-out threshold and E3M1 never ends: measured headless, the Geronimo's hull was untouched after 600 s, against under 25% in 15 s at full damage. The original drill needs damage to land and invincibility to stop destruction. Every drill ship, the player included, is made invincible. A ship is knocked out when hull, power or warp drops below 25% (player, Geronimo) or 50% (Klingons), and the script then repairs it (`EndShipSimulation`). That is M1. With M1, E3M1 runs as written: no listener, no scale, and its player-invincibility calls stay. Collisions damage an invincible player, which was the original complaint.

## 3. Goals

1. **One damage implementation in C++** (combat library), used by every caller when `DAUNTLESS_NATIVE_COMBAT=1`:
   - the hit: shields block, face choice, the absorption ramp, hull and overlapping subsystems, the immunity flags (M1), the dev cheats;
   - the condition chain: condition write, threshold state machine, watcher crossings, repair enqueue. The death check and zero crossings run at the boundary (M3, M5).
   
   Python's `combat.apply_hit` / `DamageSystem` / `SetCondition` stay as the reference with the switch off.
2. **K2 applies damage pulses in the kernel**: no CONTACT damage record, no Python inside the walk. The next bank on the same target sees the pulse's result (ruling P1, now by construction). **K3 applies its hits natively at `DONE`**, in today's order.
3. **Every effect of a hit is queued** (M2): its events, the death begin (cascade rolls, death script, `ET_OBJECT_EXPLODING`), the death splash, hit presentation (dispatch F1-F6) and appendage severance (F7). In-tick and native: the condition and shield writes and the immunity decisions. The death check runs at the flush (M5), and `SetDying` with it.
4. **Non-kernel callers use the same native function**, synchronously. These are collisions, `AddDamage` (the cascade, SDK, NanoFX), the death splash at delivery, scenery contact, radiation's `DamageSystem`, SDK `DamageSystem`/`DestroySystem`/`SetCondition`/`SetConditionPercentage`. Outside a tick their entries are held until the next boundary drain: the tick flush, or the frame-end drain after the host's post-step pass (ruling R8, which replaced end-of-call delivery so E3M5's `KillGonDev` survives and a collision kill keeps event-inventory R2's order).
5. **Bit-exact**: the native arm equals the Python reference by `.hex()` on every condition, face charge and death, and the queued entries are compared kind by kind, in order (DM §7 hazards H1-H15).

## 4. Design

### 4.1 Mirrored inputs (DR §7)

New mirror fields, pushed at every writer:
- **Shield faces:** `_current_shields`, `_max_shields`, `_ramp_fraction`, at the seven writers of DR §6 (in-place writes push explicitly; no restore path exists).
- **Ship:** `_invincible`, `_hurtable`, `_splash_damage`, `_splash_damage_radius`.
- **Subsystem:** `_invincible`, `_critical`.
- **Phaser bank:** `_max_damage`, `_max_damage_distance`, DRF.
- **Torpedo:** `_damage`, DRF.
- **Watchers:** each subsystem's two condition watchers' check presence and current value, as K0's `_watch_checks` / `_watch_value`.
- **Per-step context:** the player handle (always), god mode, double damage, NPC shields off.

### 4.2 The native hit

DM §2 in C++ with DM §7's hazards: `py_pow`, `py_min`/`py_max`, operand order, FMA off. Native counterparts exist for `shields_block`, the bubble entry, `subsystem_world_position` and mount order (DM §8). New native code:
- `_shield_face_from_hit_point`;
- `_splash_weight`;
- the ramp;
- `DamageSystem`;
- the threshold state machine;
- `classify`;
- `_phaser_damage_for_tick` × level.

The kernel keeps no Python object: it writes through the write log and appends queue entries.

### 4.3 Queue kinds (new)

In emission order within a hit, matching today's synchronous order so delivery order equals today's handler order minus nesting:

| Kind | Carries | Delivery |
|---|---|---|
| `COND_WATCH` | subsystem, which watcher (condition / combined), old, new | `_fire_crossed` against the checks registered at delivery (K0 `WATCH` precedent, ruling E3) |
| `SUBSYS_EVENT` | subsystem, DESTROYED / DISABLED / OPERATIONAL | posts the event; DESTROYED also `internal_blast.queue` |
| `REPAIR_ADD` | subsystem | `AddToRepairList` (append + `ET_ADD_TO_REPAIR_LIST`) |
| `ZERO_CROSS` | ship, plant / hull, killer | at delivery, the M5 check: if the ship is not invincible, `warp_core_breach.arm` / `subsystem_cascade.schedule` (ruling R5); then, if the subsystem is critical and the ship not invincible, dying or dead: the death |
| `DEATH` | — | (folded into `ZERO_CROSS` delivery: `ship_death.begin` / `rocks.death.begin` as today, cascade rolls on S1, death script, `ET_OBJECT_EXPLODING`, then appends `SPLASH`) |
| `SPLASH` | ship | `splash_damage.apply` → the native hit per victim (its own entries are appended and delivered in the same flush) |
| `HIT_PRESENT` | dispatch's inputs (F0-F7) | `hit_feedback.dispatch` minus the event; F1's shield flash may be native (`push_shield_hit`) |
| `WEAPON_HIT` | the `WeaponHitEvent` fields | posts `ET_WEAPON_HIT` |

The entries are delivered at the flush with decision 13's error handling. Entries appended during delivery are delivered in the same flush.

### 4.4 Behaviour changes (both switch states, once)

The Python reference changes with the native arm, as decision 12 did, so the differentials stay comparable. Each change below falls under M1 to M4 or decision 9:

- **Handlers run at the flush, not inside the hit** (M2). Consequences from the handler scan (DR §3.2), all accepted under decision 9:
  - E8M1's Kessok raises its shields a tick later.
  - E3M5's 15% clamp and E8M2's disable clamp land at the flush.
  - E2M0's scripted Sovereign damage, including its S1 draws, lands at the flush.
  - E2M2's partner is made invincible before the splash (M2), and under M1 takes the splash but survives.
- **A death begins at the flush** (M5), so the cascade's first blast lands a tick later for a K3 kill, as it already does for a K2 kill (DR §4.1 step 5). Its S1 rolls move to the flush; the order of S1 draws changes once.
- **Zero crossings land at the flush.** The cascade's 1.5 s delay and the breach's arming start a tick later for K3 kills; no damage moves.
- **Severance (F7) is decided at the flush**: later hits in the same tick still see the part's subsystems. Renderer-gated as today.
- **Invincible ships take damage** (M1). Mission beats that depend on it start working. That is the intent, and the mission tests in §6 check each one.

### 4.5 Not in this phase

- **Collisions per tick:** they still run per frame (off-path item); they call the native hit.
- **The cutscene rule** (decision 7, workstream H).
- **The never-posted subsystem events** (`COMPLETELY_DESTROYED`, `DAMAGED`, `STATE_CHANGED`, DR §3.3): recorded in `event-emitter-gaps.md`, not built.
- **Retiring the Python copies** (E).
- **Moving hit presentation to C++**, beyond F1 where it is free.

## 5. Rulings (mine; Mark may overturn)

- **R1.** (Withdrawn with bug 3's scale.)
- **R5. Zero crossings follow the death rule.** The hull cascade (`DestroySystem` on every subsystem 1.5 s later) and the breach arm happen only for a ship that is not invincible at the flush. Otherwise an invincible ship at hull 0 (E3M5's GonDev, E3M2's derelict Warbird) would lose every system. *If wrong:* an invincible hulk keeps its systems where BC strips them.
- **R6.** Dev mission `engine/dev_missions/vesuvi_dust_cloud.py` switches to `SetHurtable(0)`, so the B3 perf baseline keeps its no-damage player.
- **R2. A severed critical subsystem now kills** under M3; the old "severance bypass" is closed. *If wrong:* a ship dies when it loses a part carrying its hull-critical subsystem, where today it lives on at 0.
- **R4. Clearing invincibility does not kill retroactively.** A ship that sat at a critical 0 while invincible dies at the next condition write that leaves a critical subsystem at 0, not at the moment `SetInvincible(0)` is called. *If wrong:* E3M5's `KillGonDev` hulk, made vulnerable later, would need a hit to die rather than exploding on the flag change.
- **R3. The cascade's damaging point** keeps its S2 draw (presentation-RNG ruling); the native port needs a sim-side surface-point source only if the cascade itself moves to C++, which it does not here.

## 6. Testing

- **Falsifier first:** a differential that runs every caller (K2 pulses, K3 hits, collisions, `AddDamage`, splash chains, scripted `SetCondition` / `SetConditionPercentage`, radiation) with the switch on and off and compares state by `.hex()` and the queued entries in order. Written before the native code; it passes trivially on the Python reference and fails on any native divergence.
- **Kernel guard:** K2's damage-pulse record count is 0 in the fight (no Python inside the walk); K3 hands back no hit list.
- **Mission tests (headless where the harness reaches them):**
  - E8M2: Matan can be disabled by damage and never dies while invincible.
  - E3M5: the clamp holds at 15% across two same-tick hits once delivered.
  - E2M2: the partner survives its partner's splash.
  - E3M1: the drill ships take damage, are knocked out at their thresholds and are repaired; nobody dies; a collision damages the invincible player.
  - E3M5: GonDev survives its creation at hull 0.
  - E7M1/E7M2: a scripted hull 0 kills.
  - Bug 2's pass over the 15 missions.
- **Existing differentials** (K0-K3, step, falsifier) stay green.

## 10. Outcome

Built 2026-11-02/03 on `ws/combat-native-damage`:
- Task 1, the semantics: `8d95526db`.
- Task 2, hit effects queued: `552c9a899`, plus review fixes `ac21dc89a`.
- Task 3, the native hit for non-kernel callers: `4be286f4f`, `9dd21be87`, `48d767097`.
- Task 4, K2/K3 in-kernel: `569ed7521`, `bdb46187c`, `09edc2c8f`, `8b6160c9a`.
- Perf fix: `418fcb3ac`, `c1063ce77`.
- Test-isolation fix: `6c1fab927`.

- **The check-in is gone.** In the 64-ship fight, K2 hands back 0 damage records (0.381 per tick before) and K3 hands back 0 hits (0.108 per tick before). Every caller uses one C++ hit and condition chain when the switch is on. The kernels' compute is CPython-free; resolving held objects, applying writes and the memo forget stay in the binding, under the GIL.
- **Bit-exact.** A damage falsifier (`tests/integration/test_native_damage_differential.py`) runs every non-kernel caller both ways and compares every condition, face charge, ramp and `_dying` by `.hex()`, plus the queued entries in order. It was red first. A planted `std::sqrt` for `py_pow`, and the removal of any one of the seven shield-face pushes, each fail it. K0-K3, the step and the presentation falsifier stay green.
- **Mark's rulings as built:**
  - M1: only `SetHurtable(0)` blocks damage; `SetInvincible` blocks death.
  - M5: the death check runs at the boundary for every write, re-reading invincibility. E3M5's GonDev survives.
  - Bug 2: `SetConditionPercentage` lands in 14 of the 15 missions driven headless; the 15th fires on a 1-in-10 roll and shares the code path.
  - Bug 3 (E3M1) is closed by M1: the 0.1% plan was dropped after a probe showed the drill could never end. Mission tests pin E7M1/E7M2's scripted kills, GonDev, Matan's disable and E3M1's knock-outs.
- **Controller rulings added during the build:**
  - R7: zero crossings are queue entries emitted at the write, which restores event-inventory R2 (`ET_OBJECT_EXPLODING` before the killing hit's `ET_WEAPON_HIT`).
  - R8: damage effects outside a tick wait for a boundary; a frame-end drain follows the host's post-step pass.
  - R9: one death path; the reactor breach folds into the seam.
  - Review fixes: zero crossings are decided on the condition at the boundary; `REPAIR_ADD` only when not already queued; a frozen, natively encodable entry contract with one gone-object rule for both arms.
- **Benchmark (SIG-176, Debug, two runs each):** `sim` 9.265 → 9.304 ms per tick (inside spread); `sim.combat` 1.509 → 1.434; `sim.effects` 0.196 → 0.325, which now carries hit presentation, hit and subsystem events, and deaths. The first D build was slower (`sim.gameloop` +0.35 ms): a native condition write cost 11.3 µs against Python's 1.9, until the guards were cached on version tags (now 1.3 µs).
- **Found, not fixed:**
  - `ET_SUBSYSTEM_COMPLETELY_DESTROYED` / `_DAMAGED` / `_STATE_CHANGED` are never posted (`event-emitter-gaps.md` #15).
  - `MissionLib.SetConditionPercentage` sets a hull's children rather than the hull when it has children: E3M4's Berkeley hull stays at 100%, and E7M1's freighter dies through its cargo hold. That is the SDK's own walk; parked for Mark.
  - The death cascade's `[death cascade blast] AttributeError` on hand-built test ships (`GetShipProperty` is None) predates this phase.
  - A scripted kill in a multi-tick frame waits until that frame's combat flush (within decision 9).
  - A transiting player's repair-raise entries are dropped by the mission-change reset; no stock handler on them writes combat state.
  - `_deleted` is never cleared.
- **Final review: ready for live test** (0 critical, 1 important, 7 minor).
  - The important finding: a subclass patched after its rows were flagged kept its old native rules. Fixed in `4159415f8`: guard slot 0 watches every flagged class and the cloak class, and hands back to Python on a mismatch.
  - Also fixed: a NaN hull-box half-extent, and a `GetPosition()` that raises. The §6 mission tests now run with the switch both ways (`f4480e094`); all 8 beats run natively with no fallback.
  - Not done: `WeaponHitEvent.GetNormal()` returns a fresh point, not the caller's object. It would need a second held operand per entry.
  - Blunt but exact: once any flagged class stops matching, native damage hands every hit back for the rest of the session. No stock code does this.
- **No known-failing tests.** The disruptor test's `TypeError` was a stale spy (`projectiles.register` gained `kset`); fixed in `9e24002e3`. The order-polluted `test_subsystem_obj_type` passes alone.
- **Found in the harness:** `headless_mission.load` keeps a mission module's globals between loads. E7M1's `bStarbaseCollision` leaked from the off run into the on run. The mission test re-imports the module; the helper is unchanged.
