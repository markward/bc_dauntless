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
