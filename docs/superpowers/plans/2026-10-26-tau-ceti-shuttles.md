# Tau Ceti Shuttle Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ten Federation shuttles run between Starbase 12 and the Dry Docks in Tau Ceti, in every game mode: docked 10 minutes in the starbase bay, intercept speed out, NPC warp between regions, two circles of a random dry dock, back into the bay.

**Architecture:** One new module, `engine/systems/shuttle_service.py`, owns the roster of ten shuttle records and a per-shuttle phase machine. It is ticked once per game tick from `GameLoop.tick`, places its lane waypoints from the region hook (beside home stations), registers as an owner (`engine/systems/owners.py`), and drives each flying shuttle by giving it BC's own PlainAI scripts (`Intercept`, `FollowWaypoints`, `CircleObject`, `Warp`) or `AI.Compound.UndockFromStarbase` for the current leg, advancing the phase when the leg completes. Docked shuttles are out of every set.

**Tech Stack:** Python 3 engine shim (`engine/appc`), BC SDK scripts, pytest.

**Spec:** `docs/superpowers/specs/2026-10-26-tau-ceti-shuttles-design.md`

## Global Constraints

- `COUNT = 10`; names `"TC Shuttle 1"` … `"TC Shuttle 10"`; ship script `"Shuttle"` (SDK `ships/Shuttle.py`); owner name `"tau_ceti_shuttles"`, owner key = the index 1–10.
- `DOCK_S = 600.0` (10 minutes, game time). Start: all docked, shuttle *i* (1-based) with `(i - 1) * 60.0` s of dock time left.
- `CIRCLES = 2` full turns (720° of accumulated bearing around the chosen dock).
- `LANE_GU = 2000.0`: each region's lane waypoint `"TC Shuttle Lane"` sits 2,000 GU from the region's anchor home station ("Starbase 12" in `Starbase12`, "Dry Dock" in `DryDock`) along that station's world forward (`GetWorldRotation().GetCol(1)`), facing away from it. Departures fly to it; warps arrive at it. Never "Player Start".
- Regions: home `"Starbase12"` (module `Systems.Starbase12.Starbase12`), far `"DryDock"` (module `Systems.DryDock.DryDock`), system id `"tauceti"` (`sector_model.system_id_for_set`).
- Dry docks to circle: home stations `"Dry Dock"`, `"Dry Dock2"`, `"Dry Dock3"` in `DryDock`, standing and alive; choice from the service's own `random.Random` (seedable for tests).
- Starbase 12 bay points: hardpoint `"Docking Entry Start"`/`"Docking Entry End"` (enter) and `"Docking Exit Start"`/`"Docking Exit End"` (leave). Never use `AI.Compound.DockWithStarbase` (it takes the player's camera).
- Collisions between a shuttle and Starbase 12 are off while it is on a bay leg (entering or leaving) and back on after.
- In no mission group. In every mode (campaign, free roam, Quick Battle).
- Paused (every shuttle docked, timers frozen) while the player is not in `tauceti`; restarted as at start when the player is back.
- Losses: recorded `(index, set name, game time, killer name or None)` until mission change; never for a loss during a Quick Battle.
- Project rules: focused test files only, never the whole suite or the gate; never launch the game without asking Mark; stage explicit paths; never `git checkout -- / restore / stash / clean / reset --hard / add -A`.

## Review Focus

1. The player docking at Starbase 12 while shuttles use the bay: BC's player docking moves objects within 300 GU of "Docking Entry" — a shuttle mid-approach must re-approach, never stick or raise.
2. A dry dock destroyed while a shuttle circles or flies to it: the shuttle picks another standing dock, or leaves if none.
3. Starbase 12 destroyed: shuttles bound for it wait at the Starbase 12 lane point; docked ones stay docked; nothing raises.
4. A mission change mid-cycle: the roster resets with the sets (no stale objects held), and the region hook rebuilds the service.
5. AI tick cost: only flying shuttles hold an AI; docked ones are in no set (Task 1 asserts it).

---

### Task 1: The roster, lanes, staggered start and docking out of the world

**Files:**
- Create: `engine/systems/shuttle_service.py`
- Modify: `engine/systems/region_hooks.py` (call `shuttle_service.on_region_built(pSet, set_name)` after `_add_arrival_points`, never raising — same try/print shape)
- Modify: `engine/core/loop.py` (`shuttle_service.tick(TICK_DELTA)` right after `warp_state.tick_warp_states`, under `_prof.scope("gl.shuttles")`)
- Modify: `engine/host_loop.py` mission-swap reset (beside `home_stations.reset()`), `tests/conftest.py` autouse reset (beside `_home_stations.reset()`)
- Test: `tests/unit/test_shuttle_service.py`

**Interfaces:**
- Produces:
  - constants from Global Constraints (`COUNT`, `DOCK_S`, `CIRCLES`, `LANE_GU`, `LANE_NAME = "TC Shuttle Lane"`, `OWNER_NAME`)
  - `class Phase(enum.Enum)`: `DOCKED, UNDOCKING, DEPARTING, WARPING_OUT, TO_DOCK, CIRCLING, LEAVING_DOCKS, WARPING_BACK, APPROACHING, ENTERING, WAITING, LOST`
  - `@dataclass Shuttle`: `index: int`, `name: str`, `phase: Phase`, `ship` (object or None), `timer: float`, `dock_name: str | None`, `bearing_accum: float`
  - `roster() -> list[Shuttle]`, `reset() -> None`, `on_region_built(pSet, set_name) -> None`, `tick(dt: float) -> None`, `set_rng(rng: random.Random) -> None`
  - `_dock(shuttle) -> None` (remove from its set, drop its AI, phase DOCKED, timer = DOCK_S) and `_launch(shuttle) -> None` (create or re-add the ship at Starbase 12's "Docking Exit Start", owner-tag it, phase UNDOCKING)

- [ ] **Step 1: Write the failing tests** (fixture: `_fresh_world()`, `shuttle_service.reset()`, build both Tau Ceti regions via `Systems.Starbase12.Starbase12.Initialize()` and `Systems.DryDock.DryDock.Initialize()`, a player ship placed in `Starbase12` and set as player):

```python
def test_both_regions_get_a_lane_point(...)        # "TC Shuttle Lane" in each set, 2000 GU from its anchor station (abs 1e-3), forward away from it
def test_ten_shuttles_start_docked_and_staggered(...)  # 10 records, names "TC Shuttle 1".."10", all DOCKED, timers [0, 60, ..., 540]
def test_docked_shuttles_are_in_no_set(...)        # no set holds any "TC Shuttle N"
def test_the_first_launches_on_the_first_tick(...) # tick(1/60): shuttle 1 UNDOCKING, in Starbase12, owner_of == ("tau_ceti_shuttles", 1); others DOCKED
def test_one_launch_a_minute(...)                  # advance 125 s of ticks: shuttles 1-3 launched, 4-10 docked
def test_paused_outside_tau_ceti(...)              # player moved to a non-Tau Ceti set: every shuttle DOCKED and in no set; timers frozen while away; back in Tau Ceti: restarted staggered as at start
def test_region_built_twice_keeps_one_roster(...)  # Initialize Starbase12 again: still 10 records, one lane point
def test_reset_forgets_everything(...)
def test_in_no_mission_group(...)                  # a launched shuttle's name in neither friendly, enemy nor neutral group
```

- [ ] **Step 2: Run** `uv run pytest tests/unit/test_shuttle_service.py -q` — expected: FAIL (module missing).

- [ ] **Step 3: Implement.** The service starts (roster built, staggered) the first time both Tau Ceti regions exist; `on_region_built` only adds the lane point and, for a set replaced while running, docks the shuttles that were in the old set object. Ship creation: `loadspacehelper.CreateShip("Shuttle", pSet, name, "", 0, 0)` (BC's CreateShip, as `home_stations._build` does), then `SetTranslate`/`SetMatrixRotation` from the exit-start point. Phases past UNDOCKING may be placeholders that just dock the shuttle again in this task.

- [ ] **Step 4: Run** the Step 2 command plus `uv run pytest tests/unit/test_region_map_on_initialize.py tests/unit/test_arrival_points.py -q` — expected: all pass.

- [ ] **Step 5: Commit** the five files explicitly ("feat(shuttles): Tau Ceti shuttle roster, lanes and staggered docking").

### Task 2: The Starbase 12 legs

**Files:**
- Modify: `engine/systems/shuttle_service.py`
- Test: `tests/unit/test_shuttle_service.py`

**Interfaces:**
- Consumes: Task 1's roster, `_dock`, `_launch`, lane points.
- Produces: the phase transitions UNDOCKING → DEPARTING → WARPING_OUT → (arrival in DryDock: TO_DOCK, Task 3) and (arrival in Starbase12) APPROACHING → ENTERING → DOCKED; `_give_ai(shuttle, ai) -> None` (SetAI, remember the leg); a leg ends when the shuttle's AI reports done or the leg's own completion test (below) holds.

Legs:
- UNDOCKING: `AI.Compound.UndockFromStarbase.CreateAI(ship, <Starbase 12>)`, collisions with Starbase 12 off; done → collisions on, DEPARTING.
- DEPARTING: PlainAI `Intercept` at the region's lane point, `SetInterceptDistance(100.0)`, `SetInSystemWarpDistance(150.0)`; done → WARPING_OUT.
- WARPING_OUT: PlainAI `Warp`, `SetDestinationSetName("Systems.DryDock.DryDock")`, `SetDestinationPlacementName(LANE_NAME)`; done when the ship is in `DryDock` and not warping (`warp_state`) → TO_DOCK.
- APPROACHING (arrived in Starbase12 at its lane point): `Intercept` at Starbase 12 with the same distances, ending within 300 GU of "Docking Entry Start"; → ENTERING.
- ENTERING: collisions with Starbase 12 off; `FollowWaypoints` through "Docking Entry" → "Docking Entry End" (the waypoints made the way `DockWithStarbase.MakeWaypoints` makes them, without anything else from that module); reaching the end → `_dock`.
- Starbase 12 missing or dead when a shuttle needs it: WAITING at the Starbase 12 lane point (Review Focus 3), re-checked each tick.

- [ ] **Step 1: Write the failing tests** (same fixture; time advanced with ticks of 1/60 s through the real `GameLoop.tick` or `hm.tick`):

```python
def test_a_shuttle_undocks_and_reaches_the_lane(...)        # within 120 s of launch: phase WARPING_OUT or later, it passed within 150 GU of the Starbase12 lane point
def test_the_bay_legs_never_collide_with_the_starbase(...)  # no collision damage to shuttle or Starbase 12 over a full undock + enter
def test_a_shuttle_warps_to_the_dry_docks_lane(...)         # ends in DryDock within 300 GU of its lane point, phase TO_DOCK
def test_an_arriving_shuttle_enters_the_bay_and_docks(...)  # shuttle placed at the Starbase12 lane in APPROACHING: within 300 s it is DOCKED, in no set, timer DOCK_S
def test_starbase_destroyed_shuttles_wait(...)              # Review Focus 3
def test_player_docking_pushes_a_shuttle_and_it_recovers(...) # Review Focus 1: a shuttle in ENTERING moved 300 GU off by BC's docking clear: it re-approaches and docks, no raise
```

- [ ] **Step 2: Run** `uv run pytest tests/unit/test_shuttle_service.py -q` — expected: the new tests FAIL.
- [ ] **Step 3: Implement** the legs above.
- [ ] **Step 4: Run** the Step 2 command — expected: all pass.
- [ ] **Step 5: Commit** ("feat(shuttles): undock, depart, warp and enter the Starbase 12 bay").

### Task 3: The Dry Docks legs

**Files:**
- Modify: `engine/systems/shuttle_service.py`
- Test: `tests/unit/test_shuttle_service.py`

**Interfaces:**
- Consumes: Task 2's WARPING_OUT → TO_DOCK hand-over and `_give_ai`.
- Produces: TO_DOCK → CIRCLING → LEAVING_DOCKS → WARPING_BACK → (arrival in Starbase12) APPROACHING.

Legs:
- TO_DOCK: choose `dock_name` with the service RNG among standing, live dry docks; `Intercept` at it (`SetInterceptDistance` = 2 × the dock's `GetRadius()`, at least 60 GU; `SetInSystemWarpDistance(150.0)`); done → CIRCLING with `bearing_accum = 0`.
- CIRCLING: PlainAI `CircleObject` on the dock, `SetRoughDistances(1.5 × radius, 2.0 × radius)` (floors 40 / 60 GU); each tick add the absolute change of the shuttle's bearing around the dock (in the dock's frame, wrapped to ±π) to `bearing_accum`; at `CIRCLES × 2π` → LEAVING_DOCKS.
- LEAVING_DOCKS: `Intercept` at the DryDock lane point (100 / 150 GU as Task 2); done → WARPING_BACK.
- WARPING_BACK: `Warp` to `"Systems.Starbase12.Starbase12"`, placement LANE_NAME; in `Starbase12` and not warping → APPROACHING.
- The chosen dock destroyed or gone mid-leg: choose again; none left → LEAVING_DOCKS (Review Focus 2).

- [ ] **Step 1: Write the failing tests:**

```python
def test_the_dock_is_chosen_at_random(...)      # seeded RNG: over 30 arrivals all three docks chosen; a dead dock never chosen
def test_circles_twice_then_leaves(...)         # in CIRCLING: phase changes to LEAVING_DOCKS only once bearing_accum >= 4*pi (accumulated from real motion), and the shuttle stayed between 0.8x near and 1.2x far of the dock throughout
def test_warps_back_to_starbase_12(...)         # LEAVING_DOCKS -> ... -> APPROACHING in Starbase12 near its lane point
def test_a_destroyed_dock_mid_circle(...)       # Review Focus 2
```

- [ ] **Step 2: Run** `uv run pytest tests/unit/test_shuttle_service.py -q` — expected: new tests FAIL.
- [ ] **Step 3: Implement** the legs.
- [ ] **Step 4: Run** the Step 2 command — expected: all pass.
- [ ] **Step 5: Commit** ("feat(shuttles): circle a random dry dock twice and return").

### Task 4: Losses, Quick Battle, owner rebuild, missions

**Files:**
- Modify: `engine/systems/shuttle_service.py`, `engine/host_loop.py` (QB load block: `shuttle_service.install(_QB)` right after `free_roam_death.install(_QB)`, before spawn's hooks)
- Test: `tests/unit/test_shuttle_service.py`, `tests/integration/test_shuttle_service_modes.py` (new)

**Interfaces:**
- Produces:
  - `@dataclass Loss`: `index: int`, `name: str`, `set_name: str`, `game_time: float`, `killer: str | None`; `losses() -> list[Loss]`
  - the owner (`owners.register`) with `rebuild(old, record)` → the shuttle record goes DOCKED (returns None or the docked placeholder per the owners contract — read `engine/systems/owners.py` and `home_stations._HomeStationsOwner`), `after_rebuild` no-op
  - `install(qb) -> bool`: wraps `qb.StartSimulation2` and `qb.EndSimulation` (marker `_dauntless_shuttle_service_orig`, sim_restore's `_wrap` convention) to note battle start and, at battle end, dock every shuttle damaged or destroyed during the battle and drop their battle losses
- A shuttle's death (`ship_lifecycle` destroyed event, as home stations subscribe) → phase LOST, `ship` None, a `Loss` appended unless a battle is running; LOST shuttles never launch again until `reset()`.

- [ ] **Step 1: Write the failing tests.** Unit: `test_a_destroyed_shuttle_is_lost_and_recorded` (killer = the firing ship's name for a player phaser kill via `combat.apply_hit`), `test_a_lost_shuttle_never_relaunches`, `test_reset_on_mission_change_brings_all_ten_back`. Integration (the `world` fixture of `tests/integration/test_quickbattle_setup_e2e.py`): `test_a_battle_in_tau_ceti_restores_shuttles_docked_and_records_nothing`, `test_free_roam_warp_to_starbase_12_finds_the_service_running`, `test_e1m1_loads_and_runs_60s_with_the_service` (hm.load the E1M1 mission; tick 60 s; no exception, no GameOver).
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_shuttle_service.py tests/integration/test_shuttle_service_modes.py -q` — expected: new tests FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the Step 2 command plus `tests/integration/test_home_stations_quickbattle.py tests/integration/test_station_hostility_free_roam.py -q` — expected: all pass.
- [ ] **Step 5: Commit** ("feat(shuttles): losses, Quick Battle restore and every mode").

### Task 5: A full round trip, docs, and the cost capture

**Files:**
- Test: `tests/integration/test_shuttle_round_trip.py` (new)
- Modify: `docs/engine/home-stations.md` (new section "Tau Ceti shuttle service"), `CLAUDE.md` (Home stations row: one clause)

- [ ] **Step 1: Write the test** `test_a_shuttle_completes_a_round_trip`: free-roam world at Starbase 12; follow shuttle 1 through every phase in order DOCKED → UNDOCKING → … → ENTERING → DOCKED within 20 minutes of game time, recording the phase sequence; assert the sequence and that it circled one of the three docks.
- [ ] **Step 2: Run** it — expected: PASS (it pins Tasks 1–4 together); if it fails, fix the cause in `shuttle_service.py`.
- [ ] **Step 3: Write the docs** (the rule, constants, phases, modes, losses, "Not live-verified").
- [ ] **Step 4: Run** `uv run pytest tests/docs tests/integration/test_shuttle_round_trip.py -q` — expected: pass.
- [ ] **Step 5: Commit** ("docs(shuttles): Tau Ceti shuttle service").
- [ ] **Step 6: Cost capture — ASK MARK FIRST.** Do not launch the game. Report to the controller the exact capture commands (profiler on, free roam at Starbase 12, service on vs off, scene line) for Mark to run or approve.
