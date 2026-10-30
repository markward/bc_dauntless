# Passive subsystem state — design

Date: 2026-10-30. Branch: `perf/passive-state` (off main `886a42291`).

## 1. Why

Every game tick the engine walks every ship and steps every weapon bank,
torpedo tube, shield generator, power plant, repair bay, cloak and
articulated part, whether or not anything about it is changing. Mark's
framing: stepping every weapon every tick "feels like pushing a rock up a
hill. There needs to be a design which does more of this stuff passively."

The measurements agree that most of that work recomputes nothing:

- Weapon charging (`host_loop._advance_weapons`, `sim.weapons`) costs
  ~0.62 ms per game tick in the 64-ship stress fight. At 100 ships, 709 of
  790 `UpdateCharge` calls per tick were for banks already full and idle (the
  comment in `EnergyWeapon.UpdateCharge`, `engine/appc/weapon_subsystems.py`).
  The early-out made each of those cheap; the walk that reaches them still
  runs.
- Per-ship upkeep (`engine/core/loop.py:_update_ship_subsystems`,
  `gl.subsystems`) costs ~1.0 ms per tick at 64 ships. In the 2026-10-29
  profile (`~/Documents/dauntless-perf/pyprof3-cs64-20261029-2239.gl.subsystems.prof`)
  31 of its 45 s were the power plant (`PowerSubsystem.Update` →
  `_pump_consumers` → `_update_power` for ~9 consumers per ship per tick), 6 s
  articulation, the rest the walk itself plus shields, cloak and repair.

The simulation at 64 ships is ~11.6 ms of each 16.7 ms tick (headless Debug,
`~/Documents/dauntless-perf/mounts-cs64-bridge-20261030-1153.log`). The
upkeep above is ~1.6 ms of that.

The point is architectural, not just the 1.6 ms: **upkeep cost should scale
with how many things are changing, not with how many things exist.** A
quiet scene full of ships, stations and parked fleets should cost almost
nothing in upkeep.

## 2. Goals

1. A subsystem whose per-tick update would leave its state unchanged is not
   visited on that tick. It re-enters the per-tick walk ("wakes") when
   anything its update reads is changed.
2. The power plant does its work once per power interval (1.0 s of game
   time, `PowerSubsystem.POWER_INTERVAL`) whenever the interval's supply
   covers its demand, instead of once per tick.
3. **The contract holds bit for bit.** Every value the SDK or the engine can
   read — `GetChargeLevel`, `GetNumReady`, battery levels, power
   percentages, shield face charges, repair conditions — is identical, to
   the last bit, to what the per-tick model gives at that tick. Every event
   (`ET_TORPEDO_RELOAD`, `ET_POWER_FRACTION_CHANGED`, `ET_REPAIR_COMPLETED`,
   `ET_SUBSYSTEM_POWER_CHANGED`, the depletion `StopFiring`, the warp-core
   breach) fires on the same tick, in the same order relative to the rest of
   the tick.
4. Measured win: `sim.weapons` + `gl.subsystems` per game tick in the 64-ship
   headless capture drop by at least half (estimate: ~1.6 → ~0.5 ms; this is
   an estimate until measured).

## 3. Non-goals

- AI, motion, collision, sensors, rendering. They have their own levers.
- Any change to a gameplay rule or a measured BC constant: the 0.5 s shield
  cadence (`SHIELD_CHARGE_PERIOD_S`, BC 0x0056A230), the 1.0 s power
  interval, the torpedo reload integrator, the bank depletion latch, the
  repair formula (stbc-oracle bible §16). This design moves WHEN code runs,
  never WHAT it computes.
- A native (C++) port. Everything here is Python.
- Closed-form "value = anchor + rate × time" evaluation of ramps (a charging
  bank, a reloading tube). It would save more, but it cannot be bit-exact
  (summing an increment n times rounds differently from multiplying by n).
  Deferred; see §9.

## 4. Anti-goals (would make this a failure even if it ran faster)

- **A second copy of a rule.** No sleeping, waking or replay path may
  re-derive what a subsystem's update computes. Wherever state has to be
  brought forward, it is brought forward by calling the SAME per-tick
  function the per-tick model calls, in the same order.
- **Re-valuing banked progress.** `TorpedoTube.UpdateReload`'s docstring
  records the bug class: an earlier scheme re-valued a whole elapsed reload
  against the current power factor, snapping half-loaded tubes back or
  finishing them early. Nothing here may apply an input's new value to time
  that passed under its old value.
- **"Usually on time."** An event that fires a tick late only sometimes is a
  failure, not a rounding error.
- **Removing the per-tick path.** It stays, behind a switch, as the
  reference the passive path is tested against (§7).

## 5. Facts the design rests on (from the code, 2026-10-30)

- Weapons and combat now run once per game tick inside the frame loop
  (`host_loop.run`, `for _tick_i in range(_sim_ticks_this_frame)`, merged
  2026-10-30), and `GameLoop.tick` runs `_update_ship_subsystems` once per
  tick. Both are per tick; neither is per frame.
- `EnergyWeapon.UpdateCharge`: while not firing and `max − charge <= 0` it
  returns before reading anything else. While firing it drains, runs the
  beam-on countdown and latches `_depleted` + `StopFiring()` at zero.
- `TorpedoTube.UpdateReload`: returns immediately when
  `num_ready >= max_ready`; otherwise banks each cooling slot's progress as
  `factor × (now − _reload_advanced_at[slot])` on the game clock (it ignores
  its `dt`), and posts `ET_TORPEDO_RELOAD` (Destination = the tube, no
  Source) on completion.
- `ShieldClass.Update`: adds `dt` to `_charge_accum` EVERY tick, full or
  not; once it reaches 0.5 s it resets the accumulator to 0 unconditionally
  and runs the per-face regen with the accumulated time. So a full,
  undamaged generator is not a fixed point — its accumulator phase moves —
  and the phase decides on which tick the first regen step after damage
  lands.
- `RepairSubsystem.Update`: returns immediately with an empty queue.
- `PowerSubsystem.Update`: accumulates `_interval_elapsed`; at ≥ 1.0 s it
  resets it to 0.0 (not `-=`, so every interval sums the same ticks), adds
  `output × elapsed` to the batteries if the reactor is not offline, and
  seeds the main/backup conduit budgets as `min(battery, rated capacity ×
  elapsed)`. Then EVERY tick `_pump_consumers` walks
  `ship._powered_consumers` in attach order (= BC draw priority), each
  consumer's `_update_power(dt, power)` drawing `normal_power × dt × wanted%`
  through `_draw` (modes MAIN_FIRST / BACKUP_FIRST / BACKUP_ONLY /
  DIRECT_MAIN), which debits conduit budget and battery and sets the
  consumer's `_power_factor` (= `GetNormalPowerPercentage`) and
  `_efficiency`. Then it drives the two `FloatRangeWatcher`s with each
  battery's fraction (`ET_POWER_FRACTION_CHANGED` for
  `Conditions/ConditionPowerBelow.py`). Weapon systems want power only while
  a child weapon is firing (`_wants_power` → `_any_child_firing`), so demand
  changes whenever a bank starts or stops.
- SDK use of charge and readiness (excluding `App.py`): reads in
  `Conditions/ConditionPulseReady.py`, `AI/PlainAI/PhaserSweep.py`,
  `Conditions/ConditionTorpsReady.py`, `Bridge/TacticalCharacterHandlers.py`,
  `Bridge/TacticalMenuHandlers.py`, and `GetNumAvailableTorpsToType` in 9
  files; writes only in `loadspacehelper.py:235-239` (keeps the charge
  percentage across a property rescale) and `Actions/ShipScriptActions.py:362,369`
  (sets every bank to full). The SDK never calls `UpdateCharge`,
  `UpdateReload`, `SetNumReady`, `IncNumReady`, `DecNumReady` or
  `ReloadTorpedo`, but they are SDK surface and mods may.
- There is no save/load for engine subsystems yet: no subsystem defines
  `__getstate__`, and `PowerSubsystem` carries a `TODO(save)` for
  `_breach_fired` (`engine/appc/subsystems.py`). Ships ARE rebuilt in
  place by mission swaps, Quick Battle restore (`engine/quickbattle/sim_restore.py`)
  and set changes.
- The host runs a frame's N GameLoop ticks first (`advance_ticks`), then N
  weapons/combat steps; the headless harness (`headless_mission._sim_tick`)
  runs `GameLoop.tick` only, never weapons or combat. AI uses the unseeded
  module-level `random` (`ai_driver.py`, `collision_avoidance.py`), so two
  runs of the same mission are not reproducible.

## 6. The design

### 6.1 Sleep: an object whose update is a no-op is not visited

Each kind of per-tick object gets a **fixed-point predicate**: a cheap test
that is true only when its per-tick update, run now, would change nothing
observable. While it holds, the object sleeps — it is out of the per-tick
walk. The walks (`_advance_weapons`, `_update_ship_subsystems`) iterate an
**awake set** instead of every ship's every subsystem.

Because a sleeping object's update would have been a no-op, skipping it is
exact by construction. There is no catch-up and no formula — the only
correctness risk is missing a wake (§6.3), and §7 makes that risk testable.

| Object | Asleep when | Its update while asleep would… |
|---|---|---|
| Energy weapon bank | not firing and `max − charge <= 0` | return at the headroom early-out |
| Torpedo tube | `num_ready >= max_ready` | return at its first line |
| Repair bay | queue empty | return at its first line |
| Cloak | no transition in progress (builder confirms the exact idle condition from `CloakingSubsystem.Update`) | change nothing |
| Articulated parts | ship has no rig, or every part is at its target pose (builder confirms from `articulation.tick_ship`) | change nothing |
| Shield generator | every face at max and no face can change (see 6.2) | only advance `_charge_accum` — handled by 6.2 |

A sleeping object stays registered with its ship; it just isn't stepped.
When it wakes it rejoins the awake set and is stepped from the NEXT tick
(or the current tick — see 6.3 ordering).

### 6.2 Shields: sleep with the accumulator phase kept

A full shield generator still advances `_charge_accum` every tick, and the
phase matters. It sleeps anyway, recording the tick it fell asleep and its
`_charge_accum` at that moment. On waking, before anything else touches it,
its accumulator is brought forward by running the same accumulate-and-reset
arithmetic once per slept tick (float `+= dt`, reset to 0.0 at ≥ 0.5) — the
same operations, in the same order, as the per-tick model. No regen happens
during that catch-up, because the generator was at a fixed point for charge.
This is the one sanctioned replay in phase 1, and it replays only the
accumulator, not the rule. (The builder may compute the accumulator's
periodic pattern once and index into it, provided the result is bit-identical
to the loop; a test pins it.)

### 6.3 Wake: every change to an input wakes the objects that read it

An object wakes when anything its update reads changes. Each kind lists its
inputs, and every mutator of an input calls a wake. Known mutators (the
builder must complete this list by searching the code — §7 makes a missed
one fail a test):

- **Energy bank:** starting to fire (`Fire`, `StartFiring`, the held-weapon
  pump), `SetChargeLevel`, `SetMaxCharge` / any property swap or rescale
  (`loadspacehelper`'s `fOFactor` path), anything that lowers charge. Power
  and condition changes do NOT wake a full idle bank, because its update
  returns before reading them — but they must wake a bank that is awake
  anyway, which needs nothing (it is stepped each tick).
- **Torpedo tube:** a launch (the decrement of `num_ready`), `SetNumReady`,
  `DecNumReady`, `IncNumReady`, `ReloadTorpedo`, max-ready or ammo changes.
  The reload clock (`_reload_advanced_at`) for the slot that starts cooling
  must be stamped exactly as the per-tick model stamps it today; the
  builder verifies whether that happens at launch or on the first awake
  `UpdateReload`, and keeps it identical.
- **Repair bay:** anything that adds to the queue (damage paths,
  `AddToRepairList`, SDK calls).
- **Shield generator:** any change to a face's charge or max (hits,
  `SetCurShields`/`SetMaxShields`-style SDK setters, property changes),
  disable/enable, destruction.
- **Cloak / articulation:** whatever starts a transition or sets a target
  pose.
- **Any object:** its ship dying, being removed, changing set, or being
  rebuilt (Quick Battle restore, mission swap, set change); see 6.6.

**Ordering within a tick.** Today, within one tick, `_update_ship_subsystems`
runs after AI and motion, and the weapons/combat step runs after the
GameLoop tick. An object woken during tick k must be stepped at exactly the
point in tick k (or not) that the per-tick model would have stepped it. The
rule: a wake that happens BEFORE the object's walk in tick k means it is
stepped in tick k's walk; a wake AFTER its walk means it is first stepped in
tick k+1 — which is exactly what the per-tick model does, since the walk in
tick k ran over it while it was still a no-op. The builder must keep walk
order among awake objects the same as today's order (ship order, then
subsystem order), because consumers and events depend on it.

### 6.4 Power: plan the interval, replay it on demand

The power plant changes state every tick (each consumer's draw debits the
conduit budget and battery), so it never reaches a fixed point while
anything draws. It gets its own scheme, exact by replay:

- **At each interval boundary** (the tick on which `_interval_elapsed`
  reaches 1.0 s — a wake scheduled in a game-tick queue, see 6.5) the plant
  runs today's boundary code unchanged (battery top-up, conduit seeding),
  then **classifies the interval**: it is *steady* if, for every remaining
  tick of the interval, every consumer's current demand is met in full by
  `_draw` — i.e. the conduit budgets and batteries cover the summed demand
  of all ticks in the interval in priority order. Otherwise it is
  *constrained*.
- **Steady interval:** the plant and its consumers sleep. Every consumer's
  `_power_factor`, `_efficiency`, `_power_wanted` and `_power_received` are
  the same each tick of a steady interval, so they are set once. The
  battery and conduit counters, and `_power_dispensed`, are NOT advanced per
  tick; they are brought forward on demand by **replaying** the slept ticks:
  calling the same `_update_power` / `_draw` code, consumer by consumer in
  attach order, once per slept tick. The replay is bounded by the interval
  (≤ 60 ticks).
- **On demand** means: before any read of battery, conduit or dispensed
  state (`GetMainBatteryPower`, `GetBackupBatteryPower`,
  `GetAvailablePower`, `GetPowerDispensed`, the power display, `StealPower*`,
  `AddPower*`, the watchers), and before any demand change.
- **Demand changes** (a weapon system starting or stopping firing, a power
  slider, `TurnOn`/`TurnOff`, a consumer added or removed, damage to the
  plant or a conduit): replay to now, then re-classify the rest of the
  interval.
- **Constrained interval:** stepped per tick exactly as today.
- **Battery watchers:** a `FloatRangeWatcher` with no ranges registered
  needs no ticks. One with ranges must see the same per-tick fractions the
  per-tick model gives it, so a steady interval computes, at classification
  time, the first tick in the interval on which any registered range could be
  crossed, and schedules a wake there (replaying to that tick and evaluating
  the watcher tick by tick from then). The builder may simply treat "has
  registered ranges and the fraction can move" as constrained if that is
  simpler. Correctness first.
- **Warp-core breach** (`_breach_fired`, reactor destroyed): unchanged; a
  destroyed reactor is a demand/supply change that wakes the plant.

### 6.5 The tick queue

A per-game-loop min-heap of (game tick, sequence, object, reason) for wakes
that are due at a known future tick: power interval boundaries, watcher
crossings, and anything else a builder finds needs one. It is drained at the
point in the tick where the per-tick model would have stepped the woken
object (6.3 ordering). Ticks are integer tick counts, never float seconds,
so "due" is exact. It lives with the GameLoop so the headless harness
(`tests/helpers/headless_mission._sim_tick` → `GameLoop.tick`) and the host
share it. Pause (`sim_frozen`) runs no ticks and so drains nothing.

### 6.6 Rebuilds (and future save/load)

Sleep is derived state and must never need saving. Whenever a ship or a
subsystem is created or rebuilt (mission swap, Quick Battle restore, set
change, property swap), every object starts awake and falls asleep on its
first tick at a fixed point; a power plant starts in a constrained interval
(stepped) and re-classifies at its next boundary. That is the whole contract
a future save/load needs: restore the per-tick fields as today, start awake.
*(My call: there is no engine save/load to test against today, so this
design adds none; it only guarantees nothing here would need saving.)*

### 6.7 The switch

`DAUNTLESS_PASSIVE_STATE=0` runs the old per-tick walks unchanged. It is
read once when a mission's GameLoop starts, not mid-mission, so there is no
live hand-over between the two models; A/B is two launches. Default on once
phase 1 has passed its tests and Mark's live check. *(My call: a mid-mission
flip would need its own wake-everything / re-plan transition and tests for
no benefit Mark asked for.)*

## 7. Verification (decided)

Whole games are not reproducible run to run (unseeded AI randomness, §5),
so the bit-exact guarantee is checked INSIDE one run, where nothing else
varies. *(My call: making the whole game deterministic is its own project;
these in-run checks test the same property more directly.)*

- **Sleep audit.** A test/dev mode that, each tick, also runs each sleeping
  object's per-tick update and asserts it changed nothing (a snapshot of its
  fields before and after). Exact for phase 1 by definition: a sleeper whose
  update would have changed something is a missed wake, reported with the
  object and the field.
- **Shadow power plant (phase 2).** In the same mode, each passive plant is
  shadowed by a copy stepped per tick the old way; every tick its batteries,
  conduit counters, dispensed total and every consumer's factor/efficiency/
  wanted/received are compared with `==`, and so are the watcher events.
- **Seeded unit differentials.** Small hand-built scenes (doubles and real
  subsystems, no AI) driven by seeded random event sequences — fire, stop,
  damage, repair, slider, on/off, property rescale, `SetChargeLevel`,
  launches, ship rebuilds — run in both modes; every SDK-visible getter is
  compared every tick with `==` (never approx), and the event logs (type,
  source, destination, tick, order) must be identical. These drive the
  real `_advance_weapons` and `_update_ship_subsystems` in the host's order
  (all GameLoop ticks of a frame, then the weapons/combat steps), with frame
  schedules of 1 tick per frame and 6 per frame.
- **Whole-scene audit run.** The `combat_stress` mission (16 and 64 ships)
  through the real `host_loop.run()` with the fake frame clock
  (`tests/host/test_frame_rate_independence.py`'s `_frame_clock` seam) for a
  fixed number of frames, with the sleep audit and shadow plant on: zero
  audit or shadow mismatches.
- **Frame-rate independence** (`tests/host/test_frame_rate_independence.py`)
  keeps passing.
- **Measurement.** The 64-ship headless capture (same command as
  `mounts-cs64-bridge-20261030-1153.log`, 1,500 frames) before and after;
  report `sim.weapons` and `gl.subsystems` per tick. Then Mark's live check.

## 8. Phases

1. Sleep for banks, tubes, repair, cloak, articulation, shields (6.1-6.3,
   6.6, 6.7, 7). Expected: most of `sim.weapons` and the non-power part of
   `gl.subsystems`.
2. Power interval planning and replay (6.4, 6.5). Expected: most of the
   power plant's ~2/3 of `gl.subsystems`.
3. (Not part of this design.) Closed-form ramps — see §9.

Each phase lands with its tests and a measurement before the next starts.

**Phase 1 scope (2026-10-30, while planning).** Narrowed to weapons (energy
banks, pulse weapons, tractors, torpedo tubes) and articulation for ships
with no rig. In the 2026-10-29 profile of `gl.subsystems` (22,488 ticks)
shields cost 0.97 s, cloak 0.60 s and repair 0.15 s against the power plant's
30.8 s and articulation's 6.4 s: about 4% together, too little to justify a
wake path each. Their per-tick updates already return early when idle. They
stay stepped. The tick queue (6.5) is not needed until phase 2. Plan:
`docs/superpowers/plans/2026-10-30-passive-subsystem-state-phase1.md`.

**Status (2026-10-30).** Phase 1 Tasks 1-3 have landed: the sleep core
(`engine/appc/passive_state.py`), sleeping weapons
(`engine/appc/passive_weapons.py`) and the no-rig articulation skip. Task 4
ran `combat_stress` (16 ships) under the audit with no failures
(`tests/host/test_passive_state_scene_audit.py`).

## 9. Left for later / decisions not taken here

- **Closed-form ramps** (a charging bank or reloading tube described as a
  line in time, read by formula). Not bit-exact; needs Mark's ruling on
  whether rounding-level differences are acceptable before anyone builds
  it.
- Motion and AI "sleep" (ships at constant velocity, idle AI) — same
  philosophy, separate design.

## 10. Left to the builder

- Data structures for the awake sets and the tick queue.
- How each object kind registers its fixed-point predicate and wake hooks
  (a small mixin or per-class methods), as long as the per-tick update
  function itself stays the single source of each rule.
- Completing the mutator inventory in 6.3 by code search, and the exact
  idle conditions for cloak and articulation.
- The audit's snapshot mechanism.
- Profiler scopes for the new walks and the replay.
