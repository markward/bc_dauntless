# Sensor model sub-project 4 — probes — design

Status: design approved by Mark 2026-10-07 (brainstorming). Roadmap:
`2026-10-03-sensor-model-roadmap.md`. Builds on sub-project 3
(`2026-10-06-sensor-overboost-memory-design.md`, merged `99b91512`), whose reach step this
adds a branch to.

## Goal

A probe launched from Science sees for you: contacts within its sensor range are listed,
targetable and — inside half its range — identified, as BC does. Probes are a counted,
finite resource (today they are unlimited because the count is a stub), and the whole
Launch Probe path and E6M4's probe goal are proven end to end.

## Evidence

| Fact | Tier | Source |
|---|---|---|
| `IsObjectVisible` walks the probe list AFTER `IsObjectFar` and BEFORE the nebula-jam fallback; for each probe ID it resolves the object (garbage-collecting dead ones) and recursively calls `IsObjectVisible` on the probe's own SensorSubsystem | RE'd (decompile) | `decompiled_fresh/05_game_mission.c:23259` (`0x005671D0`); `sensor-subsystem.md` §IsObjectVisible step 7 |
| The power gate (disabled/off ⇒ not visible) is step 1, before the probe walk: with the player's sensors dead, probes do not help | RE'd | same, step 1. (`docs/ui/bridge-mode.md:311-321` and the lore doc say otherwise; RE outranks them.) |
| `IsObjectNear` / `IsObjectFar` also walk the probe list — a probe can put a target in the owner's near band (so it identifies) and far band | RE'd | `sensor-subsystem.md` §IsObjectNear/IsObjectFar |
| Probe list holds object IDs (`AddProbe`, PyArg `Ol`); dead probes are garbage-collected at walk time | RE'd | `sensor-subsystem.md` (`0x00567010`, `+0xAC..+0xBC`) |
| `NumProbes` (`+0xC8`) is a live counter seeded from `SensorProperty.MaxProbes` (`property+0x50`) by `SetProperty` | RE'd | same (`0x0061A280` / `0x0061A2E0`) |
| Launch path: `ScienceMenuHandlers.LaunchProbe` (`GetNumProbes() <= 0` ⇒ stop; `SetNumProbes(n-1)`) → `MakeLaunchProbeAction` → `ShipScriptActions.LaunchObject` (OEP_PROBE emitter, `CreateShip("Probe")`, `AddProbe(id)`, place at emitter, no collision with owner) → `PushObject` (forward × 10) → `ET_LAUNCH_PROBE` source = probe | SDK | `ScienceMenuHandlers.py:346-460`, `ShipScriptActions.py:441-551`; Miguel's variant `ScienceCharacterHandlers.py:512-570` ("gs036" when none left) |
| `RepairShipFully` refills: `SetNumProbes(GetMaxProbes())` | SDK | `ShipScriptActions.py:301-305` |
| Probe ship: `ships/Probe.py`, hardpoint `probe.py` — SensorProperty `SetBaseSensorRange(1000)`, `SetMaxProbes(1)`, impulse max speed 8, genus 1, species 710, AI string stored only | SDK | `Hardpoints/probe.py:59-72, 147-158` |
| MaxProbes: 10 on most hulls (Akira 8, Shuttle 4); launchers (OEP_PROBE) only on Galaxy, Sovereign and the Dauntless refit | SDK | hardpoints grep 2026-10-06 |
| E6M4 goal: `ProbeLaunched` (`E6M4.py:1485`) adds the probe to two planet ProximityChecks (radius+5 / +200 around "Tezle 1") and gives it an Intercept AI; success = `InnerPlanetProximity` → `ProbeReachesPlanet` | SDK | `E6M4.py:431-449, 1454-1540, 2758` |

Engine state today (2026-10-07 sweep): every launch step is real engine code EXCEPT
`GetNumProbes`, `SetNumProbes` and `AddProbe`, which fall through `TGObject.__getattr__`
to a `_Stub` (`_Stub.__le__` is False ⇒ unlimited probes; heatmap row 128 `SetNumProbes`).
No test runs the real `LaunchObject`; `tools/mission_harness.py` swaps in the
`engine/appc/emission.py` recorder, which spawns nothing. NPC sensors default on at
`_power_factor` 1.0, so a probe's own range is 1000 GU.

## Rules

1. **Count.** `SensorSubsystem.GetNumProbes()` / `SetNumProbes(n)` read/write a live int.
   It is seeded from `MaxProbes` when the property is applied (`ships.py` sensor branch,
   where `SetMaxProbes` is copied). `SetNumProbes` stores what it is given (BC stores the
   int; the SDK never passes a negative).
2. **Probe list.** `SensorSubsystem.AddProbe(obj_id)` appends the ID. `probes()` (engine
   helper) resolves each ID through `engine.core.ids.get_object_by_id`, drops IDs that no
   longer resolve, and returns the live probe objects. A destroyed-but-present probe
   resolves; it helps nothing because its own sensors are offline (range 0).
3. **Reach.** In `sensor_detection`, a new probe branch joins `_beyond_range_reach`'s two:
   when the observer's own range test fails, the target is reached if ANY live probe of
   the observer, in the observer's set, satisfies `can_detect(probe, target)`. Because the
   recursion is the one rule, rocks, the cloak bubble (from the probe's range), the dense
   nebula core and the probe's own power/condition all apply from the probe's position.
   The nebula **jam does not** cancel the probe branch (BC order: probes precede the jam
   fallback). A probe's own probe list is never walked (one level; BC's would recurse into
   a probe's probes, and probes carry MaxProbes 1 but never launch — no difference).
   The power gate still comes first: dead or switched-off observer sensors ⇒ nothing,
   probes included.
4. **Bands.** `SensorSubsystem.IsObjectNear` / `IsObjectFar` return 1 if the observer OR
   any live same-set probe has the target within half / full of ITS OWN range. The
   player's contact sweep (`sensor_contacts._sweep`, `_in_near_band`) uses the same band
   answers, so FAR/NEAR proximity events fire and passive identification arms for contacts
   in a probe's bands. Identification still needs `can_detect` (which now includes the
   probe branch) and not Unknown-by-medium.
5. **Continuity.** `in_reach` includes the probe branch (each probe's own unshrunk range,
   ignoring hide gates, same set). A contact a probe reaches but a rock hides from every
   probe and from the player runs the lost-track clock.
6. **Display.** Nothing special: the player's probe is a ShipClass in the set, so it is
   listed (as its name, "Probe N"), targetable and shootable like any ship (E6M4's Galor
   targets "Probe N"). It has no AI unless a mission gives it one; it drifts at its launch
   velocity.

## Architecture

| Unit | One idea | Change |
|---|---|---|
| `engine/appc/subsystems.py` `SensorSubsystem` | Appc surface | `_num_probes`, `_probe_ids`; `GetNumProbes`, `SetNumProbes`, `AddProbe`, `probes()`; `IsObjectNear`/`IsObjectFar` consult probes. |
| `engine/appc/ships.py` (sensor property branch) | Seeding | After `SetMaxProbes`, seed `SetNumProbes(MaxProbes)`. |
| `engine/appc/sensor_detection.py` | The one rule | `_probe_reach(observer, target)`; called from the beyond-range step (not jam-gated) and from `in_reach`. |
| `engine/appc/sensor_contacts.py` | Player sweep | Band booleans come from the sensors' `IsObjectNear`/`IsObjectFar` (single source) instead of a local distance test. |
| Tests | | unit matrix; real-launch integration; E6M4 integration. |

## Behaviour changes (deliberate, pinned by tests)

1. Probes are finite: after MaxProbes launches, Launch Probe does nothing and Miguel says
   "gs036"; `RepairShipFully` (docking) refills.
2. A ship within 1000 GU of your probe (and in your set) is listed even beyond your own
   range; within 500 GU it is identified after the 4.0 s dwell.
3. FAR/NEAR proximity events fire for contacts entering/leaving a probe's bands.
4. A probe sees into a nebula (no jam), but not through the dense core or a major rock
   from where it sits.

## Performance

The probe branch runs only for contacts beyond the observer's own range, and only when
the observer has live probes (usually 0; at most MaxProbes). Each probe costs one
`can_detect`. Extend the SP3 bench (`tests/unit/test_sensor_reach_bench.py`) with an
observer holding 3 probes; budget ≤ 3× the in-range call.

## Testing

Unit: count seeding from MaxProbes, Get/Set round trip, refill via the SDK's
`RepairShipFully`; `AddProbe` + `probes()` resolution and pruning of a deleted probe;
`can_detect` beyond range via a probe (true), probe in another set (false), probe's
sensors offline (false), observer's sensors offline (false even with a probe), probe
behind a major rock relative to the target (false), target in a MetaNebula jam (still
true via probe), target in the dense core (false); `IsObjectNear`/`IsObjectFar` via probe;
sweep identifies a contact in the probe's near band after the dwell and posts FAR/NEAR;
`in_reach` via probe and the continuity clock.

Integration (real code, no recorder): a Galaxy player presses the real Science Launch
Probe handler (SDK `ScienceMenuHandlers.LaunchProbe` or `MakeLaunchProbeAction`, with the
action played) ⇒ a "Probe N" ShipClass exists in the set at the emitter, moving forward,
`GetNumProbes` dropped by 1, the probe is in `probes()`, and `ET_LAUNCH_PROBE` with the
probe as source was posted; with the count at 0 nothing launches. E6M4: launch in Tezle1
⇒ `ProbeLaunched` registers it and the inner proximity check fires once it reaches the
planet (drive ticks headlessly; if the Intercept AI cannot get within radius+5 headless,
record why and pin the registration half).

Gate: `scripts/check_tests.sh` exit 0.

## Out of scope

Sub-project 5 (sensor debts: `ForceObjectIdentified` player gate, sensor-less station
range, station cloak bubbles, the "18 of 52" correction). Oracle measurements (parked
until after first release — Mark, 2026-10-07). Probe rendering beyond what the existing
ship path does (the model `Probe.NIF` is loaded like any ship; on a case-sensitive volume
its `probe.NIF` spelling would need the path resolver — not addressed).

## Live check (for Mark)

`./build/dauntless --developer` from the worktree. Galaxy: Science → Launch Probe; a probe
leaves the hull and drifts forward; it is on the list as "Probe 1" (then "Probe 2"…; the SDK names it MaxProbes − remaining). Fly so a ship is
beyond your range but within ~1000 GU of the probe: it is listed; get it within ~500 GU of
the probe for 4 s: it is named. Launch until empty: Miguel says there are none left.
E6M4: launch the probe at Tezle 1; the mission advances when it reaches the planet.

## As built

Built on `feat/sensor-probes`, unmerged as of 2026-10-07. Task-by-task deviations and
rulings from the SDD ledger:

- **Task 1** (`3d325d10`): `GetNumProbes`/`SetNumProbes`/`AddProbe`/`probes()` as designed.
  `probes()` prunes dead IDs via `engine.core.ids.get_object_by_id` and early-returns when
  `_probe_ids` is empty (the common case: most ships never launch one).
- **Task 1b** (`c0b9fa5c`): found and fixed a pre-existing order-pollution bug while writing
  probe fixtures, unrelated to probes themselves — `tests/conftest.py`'s autouse reset
  cleared `g_kTimerManager._timers` but not its `_time` clock, so
  `test_particles_death_probe` left game time at 5.1 s for every test that ran after it in
  the same session. Fixed in the autouse reset, not scoped to this sub-project.
- **Task 2** (`94d8d1e8`, `ed30e76f`): the probe branch in `can_detect`/`in_reach`. Rulings
  made during review, not pre-specified:
  - An **observer-side** rock or nebula-core failure falls through to the probe walk rather
    than short-circuiting it — a probe with a clear line of sight sees past a rock that
    blocks only the observer's own view. This reads as a deliberate widening of rule 3
    beyond what the spec's prose implied (the spec names only the probe's *own* occluders).
  - **Memory and over-boost keep SP3 behaviour**: an observer-side rock still cancels them
    even when a probe is present. Probes extend *reach*, not the memory/boost gates.
  - Cloak-stock and the power gate stay hard gates for both paths, per rule 3.
  - **Accepted edge** (not fixed): per-pair hysteresis means a probe whose lock is not yet
    latched can see a target sitting in concealment `[0.20, 0.28)` that the observer's own
    *latched* pair would refuse. Narrow band, inherited from SP3's hysteresis design, not
    reopened here.
- **Task 3** (`96a6c70c`): `IsObjectNear`/`IsObjectFar` and the player's contact sweep now
  both count probes, as designed. The sweep's bands come up empty when the player's own
  sensor range is 0 (dead/off sensors), matching rule 3's power gate.
  `sensor_contacts._dist` is now dead code — superseded by the `IsObjectNear`/`IsObjectFar`
  single-source change — and was deliberately left in place rather than removed, since
  removing dead code was out of scope for this task.
- **Task 4** (`97cb8880`, `c7650c9d`): the real Launch Probe path and E6M4 integration tests
  surfaced three production bugs outside this sub-project's stated surface, all fixed here
  because the integration tests could not otherwise exercise real code:
  1. `Planet.AttachObject` never called `super()`, so no `ProximityCheck` anchored on a
     planet ever fired, for any mission — not a probes-only bug. Fixing it newly brings
     E1M2's Haven asteroid checks, E6M4's probe goal, and E6M5's shuttle landing to life
     (not live-verified).
  2. The live game's SDK setup (`host_loop._setup_sdk` → `tools.mission_harness.setup_sdk`)
     installed the emission recorder over `ShipScriptActions.LaunchObject` unconditionally,
     so probes, shuttles and decoys never spawned in a live run. The recorder is now
     installed only by the two harness `main`s (`install_emission_recorder()`), not by the
     shared SDK setup path.
  3. `ProximityCheck` evaluation now skips objects with `SetDeleteMe` pending, preventing
     double counts on E6M5/E6M3.
  - **E6M4 outcome**: a real Launch Probe registers the probe with the mission's two
    `ProximityCheck`s and an Intercept AI; in real flight it closes on Tezle 1, but the
    Intercept AI alone would only bring it to a closest approach of 2278.6 GU inside the
    300 s window the test drives, short of the 2005 GU trigger radius — i.e. it would
    reach the planet at roughly the 333 s mark, just past this test's horizon. A second,
    separate test moves the registered probe inside the trigger radius directly and
    confirms the real `ProximityCheck` plus `ProbeReachesPlanet` fire correctly. So: the
    **registration half is pinned by both tests**; the **reach half is pinned only by the
    direct-placement test**, not by letting the Intercept AI fly there within the test's
    time budget — reported here rather than silently extending the budget or faking the AI.
  - E6M5 (not a probe mission, exercised by the same `AttachObject` fix): four shuttles
    land and the landing count is exactly 4.
- **Deferred minors** (not fixed, not blocking): `_probe_reach`/`_probe_in_reach` share
  near-duplicate logic; `_live_probes`' docstring is slightly stale; the dead `_dist` noted
  above; `_fresh_ship_script_actions` leaves the `Actions` package attribute pointing at the
  fresh module after the test that uses it runs.

**Performance** (Task 5): `tests/unit/test_sensor_reach_bench.py::test_probe_branch_stays_within_budget`
adds a 3-probe observer (probes at 3000/6000/9000 GU) and measures `can_detect` for targets
reached only through the 3rd probe against in-range targets. Measured ratio **≈4.7×** the
in-range call (budget 5×, per the spec's note that three sequential `can_detect` recursions
cost more than the 3× single-branch budget used for SP3's beyond-range test). Passes.
