# Tau Ceti shuttle service — design

Status: draft for Mark's review (his answers folded in), 2026-10-26. Phase 1 of the living galaxy
(memory: living-galaxy vision). Builds on home stations
(`docs/engine/home-stations.md`) and its owner tags (`engine/systems/owners.py`).

## 1. Intent

Mark wants the galaxy to carry on around the player: ships with somewhere to
be and something to do, eventually trade routes, patrols, named ships on
duty and distress calls. This is the first, smallest proof: Federation
shuttles "running people backward and forward between the dry docks and the
star base" in Tau Ceti (Mark). It is meant to prove the theory, so it should
be built on mechanisms the later systems can reuse (owners, a readable
record), not as a one-off.

## 2. Goals

- G1. **Ten shuttles** (Mark) run a round trip between Starbase 12 (region set
  `Starbase12`) and the Dry Docks (region set `DryDock`), both regions of Tau
  Ceti.
- G2. The round trip (Mark):
  1. **Docked inside Starbase 12 for about 10 minutes.**
  2. Leave the bay.
  3. Fly out at **intercept speed** (`ShipClass.IN_SYSTEM_WARP_SPEED_GUPS`,
     400 GU/s, no flash).
  4. **Warp, with the flash, to the Dry Docks region.**
  5. Fly to **one dry dock picked at random**, **circle it twice**.
  6. Warp back to the Starbase 12 region.
  7. Fly in and **enter the starbase**; back to step 1.
- G3. **Part of the region definitions, in every mode** (Mark: "No need for it
  to be free roam only… missions wouldn't be negatively impacted by it so
  let's just make it part of the region definitions"): campaign missions,
  free roam and Quick Battle alike, placed when the Tau Ceti regions are built,
  like home stations.
- G4. A destroyed shuttle: **nothing for now** (Mark). It stays gone.
  "Eventually this should result in a distress signal resulting in allied
  patrol ships coming in to defend them" (Mark), so each loss is recorded
  where later systems can read it.

## 3. Non-goals

- Distress calls, patrols, responders (later projects; G4 only leaves the
  hook).
- Shuttles anywhere but Tau Ceti; any other ship type or route.
- A persistent world: what the service did while the player was elsewhere is
  not remembered (world state is a later project).
- Hailing or talking to shuttles.

## 4. Anti-goals

- A shuttle hijacking the player's camera, view or fade. BC's own
  `AI/Compound/DockWithStarbase.py` does exactly this (it runs
  `MissionLib.StartCutscene`, forces the cinematic window and a camera sweep
  even for a non-player ship), so it must **not** be used.
- Ten shuttles moving in lockstep.
- A visible cost: the service must not noticeably slow the game (measured,
  §8).
- Breaking a campaign mission (see §6 for the one known interaction).

## 5. Behaviour

### 5.1 Shuttles
- BC's stock Federation shuttle (SDK `ships/Shuttle.py`).
- Names **"SB12 Shuttle 1" … "SB12 Shuttle 10"** (Mark, 2026-10-26; first draft "TC Shuttle"). Distinct from E1M1's
  own "Shuttle1"–"Shuttle3" in the DryDock set, and unique (sets are
  name-keyed).
- Each carries an owner tag (`owners.tag(obj, "tau_ceti_shuttles", <index>)`),
  so Quick Battle never treats it as a battle ship and lets the owner rebuild
  it (§6).
- In no mission group (as home stations): neither friend nor enemy to any
  mission's logic (my call).

### 5.2 Where each step happens
Both Tau Ceti region sets exist together whenever the player is anywhere in
Tau Ceti (`system_loader.ensure_loaded` builds every region of the system),
and the engine simulates ships in every set, not only the player's
(`ship_iter.iter_ships`). So both ends of the route run at the same time and
the player sees whichever end they are at; distant ships are never drawn
(render scope).

- **Docked (step 1).** A docked shuttle is out of the world: removed from its
  set and held by the service, so it costs no AI or motion and shows in no
  target list. Docking ends with that removal; undocking starts by putting it
  back at the bay's exit start.
- **Entering the bay (step 7).** A cutscene-free sequence of our own: fly
  BC's model points "Docking Entry Start" → "Docking Entry End" on Starbase
  12's hardpoint at impulse (BC's FollowWaypoints), then dock (above).
- **Leaving the bay (step 2).** BC's `AI/Compound/UndockFromStarbase.py`
  (cutscene-free; uses the hardpoint's "Docking Exit Start"/"Docking Exit
  End"), then step 3.
- **Flying out (step 3).** Intercept speed to a departure point about
  **2,000 GU** from Starbase 12 (my call: far enough to read as leaving, ~5 s),
  then the warp.
- **Warp (steps 4 and 6).** BC's NPC warp (`WarpSequence` via the engine's
  NPC path), to an arrival point in the destination region **chosen for the
  shuttles**, not "Player Start" (which in DryDock is inside the dock;
  `arrival_points.py`). The flash shows when the departing or arriving end is
  the player's set (engine behaviour today). Transit time: the engine's own
  NPC warp timing (about 8 s between two Tau Ceti regions with the renderer
  on; an instant cut headless). There is no transit-time setting and none is
  added (my call; the first draft's 20 s is dropped).
- **Dry Docks (step 5).** Intercept speed towards a random one of the three
  Dry Docks (home stations "Dry Dock", "Dry Dock2", "Dry Dock3"; a destroyed
  one is not picked), slowing to impulse near it, then **two full circles** of
  it (BC's CircleObject), then fly out to the departure point and warp.
- **Arriving at Starbase 12.** From the arrival point, intercept speed
  towards the bay entrance, impulse for the final approach, then step 7.

### 5.3 Staggering and start
When the Tau Ceti regions are built (the region hook, same place as home
stations), all ten start **docked**, with their remaining dock time spread
evenly over 0–10 minutes (my call), so one leaves about every minute and the
fleet never moves together. Docked time each cycle is 10 minutes. Built again
(mission change), the service starts again the same way.

### 5.4 When the player is outside Tau Ceti
The service **pauses**: every shuttle is docked (taken out of the world)
until the player is back in Tau Ceti, where it restarts as in §5.3 (my call:
sets persist until a mission change, so otherwise ten ships would fly an
empty system for the rest of the session).

### 5.5 Destroyed shuttles
A destroyed shuttle stays gone until the mission changes (the same rule as
home stations' destroyed record). Each loss is recorded (which shuttle,
where, game time, who fired the killing hit when known) in a register other
systems can read, for the distress calls to come (G4).

### 5.6 Obstacles
Shuttles must reach the bay and circle the docks without the engine's
obstacle avoidance pushing them off course or into a loop: the builder makes
sure the bay approach and the circling are not defeated by
`AvoidObstacles`/collision avoidance (e.g. the target station excluded from
that shuttle's avoidance while on those legs). Shuttles colliding with the
station or each other is a failure. On the bay legs (entering and leaving),
collisions between the shuttle and Starbase 12 are off, as BC's own docking
does (my call).

## 6. Interactions that constrain the build

- **E1M1.** E1M1 ends the mission (GameOver) when any non-player ship dies in
  the DryDock set (SDK `E1M1.py:993-1000`); it already applies to its own
  three shuttles. A shuttle the player destroys there therefore ends E1M1, as
  shooting E1M1's own shuttles does (accepted, my call: friendly fire in the
  tutorial). An accident does the same: a TC shuttle colliding with E1M1's
  Shuttle1–3 or the Nightingale (in Dry Dock2), killing either ship, ends the
  tutorial. **Accepted** (Mark, 2026-10-26: "Accept the small risk and rely
  on normal obstacle avoidance"): no E1M1-specific rule. Nothing else in E1M1
  counts or iterates the set's ships.
- **Docking players.** BC's player docking clears objects within 300 GU of
  "Docking Entry" (`DockWithStarbase.py:70-103`). A shuttle on its bay
  approach then is pushed away; the service must cope (re-approach), never
  break.
- **Quick Battle.** A battle is a simulation (home stations' rule): when a
  battle ends, every shuttle damaged or destroyed during it comes back
  **docked**, wherever it was, and battle losses are **never** recorded in
  the loss register (my call). The service handles battle end itself rather
  than relying on `sim_restore`'s per-object snapshot, which only records
  objects in the battle set at the start and would duplicate a shuttle that
  simply moved on (one shuttle index, two objects). Owned objects stay in
  their own set on a region change.
- **A region rebuilt without a mission change** (Quick Battle's `ChangeRegion`
  re-running `Systems.DryDock.DryDock.Initialize()` or Starbase12's, which
  replaces the set): only the shuttles that were in the replaced set are
  docked again; the rest carry on (my call). A set a mission deletes outright
  (E8M2 deletes Starbase12) likewise docks its shuttles.
- **Station self-defence.** Shuttles are not stations; untouched by it.
- **Home stations.** If Starbase 12 is destroyed, shuttles bound for it stop
  at their arrival point and wait (my call) until a mission change rebuilds
  it; docked ones stay docked.

## 7. My calls (Mark to check)

- In no mission group (neutral/unknown in the target list).
- Departure point ~2,000 GU out; warp transit = the engine's NPC timing.
- Quick Battle: everything a battle touched comes back docked; battle losses
  unrecorded. A rebuilt region docks only its own shuttles.
- Collisions with Starbase 12 off on the bay legs.
- The loss register lives until the mission changes.
- All start docked, staggered over 10 minutes.
- Paused (all docked) while the player is outside Tau Ceti.
- E1M1: destroying a shuttle in the Dry Docks ends the tutorial (as its own).
- Starbase 12 destroyed: shuttles wait at the arrival point.

## 8. Cost

Measured, not assumed: a frame-profiler capture (`docs/engine/frame-profiler.md`)
of free roam at Starbase 12 with the service running versus not, reported
with the scene line. Docked shuttles cost nothing by construction (§5.2).
The capture needs a live launch: **ask Mark before launching** (Mark,
2026-10-26). The numbers are reported for Mark to judge; there is no fixed
pass mark.

## 9. Left to the builder

- Module layout (a new `engine/systems/` module beside `home_stations.py` is
  the natural home), the per-shuttle state machine, and how steps hand over
  (AI trees built from BC's PlainAI scripts vs engine-driven moves).
- The register's shape, provided another module can ask "which shuttles were
  lost, where and when".
- Tests: headless, on the real Tau Ceti regions, covering a full round trip
  (time-accelerated), staggering, pause/resume on leaving and returning, loss
  recording, the Quick Battle rebuild, and E1M1 loading with the service
  present.

## 10. Not live-verified

Nothing here has been tried in game.
