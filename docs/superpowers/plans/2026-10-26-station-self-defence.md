# Stations Defend Themselves Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In free roam and Quick Battle, a station the player damages twice (≥5 s apart) within a minute becomes the player's enemy until the player leaves the system; armed stations attack; and a free-roam death is final.

**Architecture:** One new module, `engine/systems/station_hostility.py`, listens to `ET_WEAPON_HIT` and `ET_ENTERED_SET` through broadcast handlers, keeps per-station hit counts and a register of hostile stations, and turns a station hostile by moving it into the mission's enemy group and giving armed ones BC's `AI.Compound.StarbaseAttack`. It is armed only by Quick Battle's load (`install(qb)`), and Quick Battle's `StartSimulation2`/`EndSimulation` are wrapped to clear it. A second small module, `engine/quickbattle/free_roam_death.py`, wraps Quick Battle's `ShipDestroyed` so a player killed outside a battle is not recreated.

**Tech Stack:** Python 3 engine shim (`engine/appc`), BC SDK scripts (QuickBattle, AI), pytest.

**Spec:** `docs/superpowers/specs/2026-10-26-station-self-defence-design.md`

## Global Constraints

- Active only in Quick Battle (which includes free roam). Any other mission: the handlers do nothing, not even count (spec §5.6).
- A station = `ship.IsStationary()` true, OR `home_stations.home_station_of(ship) is not None` (spec §5.1). Never genus.
- A hit = `ET_WEAPON_HIT` whose firing object is the current player, target a station, `GetWeaponType()` in `{WeaponHitEvent.PHASER, WeaponHitEvent.TORPEDO}`, `GetDamage() > 0`. Shield-only hits count (spec §5.2).
- `HIT_GAP_S = 5.0`, `WINDOW_S = 60.0`, game time (`App.g_kUtopiaModule.GetGameTime()`).
- A station already in the mission's enemy group is never touched.
- The enemy group is the REAL mission enemy group (wingmen join in). The station's attack AI targets `App.ObjectGroup_FromModule("QuickBattle.QuickBattle", "pFriendlies")` — names, not objects.
- Never register a station in `QuickBattle.g_kShips` or touch `g_iNumEnemies` (spec §6).
- System key of a set = `sector_model.system_id_for_set(name) or name`; the warp transit set (`warp._WARP_TRANSIT_SET_NAME`) is never a destination.
- Project rules: focused test files only, never the whole suite or the gate; stage with explicit paths; never `git checkout -- / restore / stash / clean / reset --hard / add -A`.

## Review Focus

1. A hostile station destroyed before the player leaves: the register drops it and leaving the system restores nothing on it, raising nothing.
2. The player dead with no ship in free roam (after Task 3): every handler in `station_hostility` copes with `GetPlayer()` returning the dead ship or `None`, and `host_loop` keeps ticking.
3. Tractor beams and collisions/rams never count as hits.
4. A mission swap (free roam → a campaign mission) while a station is hostile: `reset()` forgets everything without touching objects of torn-down sets, and the campaign mission's own `ET_WEAPON_HIT` handling is unaffected.
5. The player ship rebuilt under the same name (Quick Battle `RecreatePlayer`): hits from the new object still count, and the station's AI still targets it.

---

### Task 1: Hits, the register, and turning hostile

**Files:**
- Create: `engine/systems/station_hostility.py`
- Test: `tests/unit/test_station_hostility.py`

**Interfaces:**
- Produces:
  - `HIT_GAP_S: float = 5.0`, `WINDOW_S: float = 60.0`
  - `@dataclass Hostility`: `station` (object), `name: str`, `system: str`, `since: float`, `prior_groups: tuple[str, ...]` (subset of `("friendly", "neutral")`), `prior_ai: tuple[str, int] | None` (QB AI module leaf name and AI level, from `QuickBattle.g_kShips[obj_id]`; `None` = no AI, the home-station case)
  - `activate() -> None` — sets the module active and registers the two broadcast handlers once (a second call does not double-register)
  - `deactivate() -> None`, `reset() -> None` (forget hits and register, deactivate; restores nothing)
  - `is_station(ship) -> bool`
  - `on_weapon_hit(pObject, pEvent) -> None` (broadcast handler, qualified name `engine.systems.station_hostility.on_weapon_hit`; ends with `pObject.CallNextHandler(pEvent)` when `pObject` has it)
  - `is_hostile(station) -> bool`, `hostile_stations(system: str | None = None) -> list[Hostility]` (dead/dying stations pruned on read)
  - `_game_time() -> float` (module function, so tests monkeypatch it)

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_station_hostility.py`. Fixture: `_fresh_world()`, `reset()`, a set with a player ship (`Game.SetPlayer`), a `FedStarbase` and a `DryDock` built with `loadspacehelper.CreateShip`, a `SpaceFacility` marked with `home_stations.mark_home`, the mission's groups empty, `activate()`. Hits go through the real `combat.apply_hit(station, 50.0, point, player, weapon_type=...)`; time through a monkeypatched `_game_time`.

```python
def test_one_sweep_never_turns_a_station(...):      # hits at t=0,0.5,...,4.5 -> not hostile
def test_two_hits_five_seconds_apart_turn_it(...):  # t=0, t=5 -> hostile, in enemy group
def test_hits_more_than_a_minute_apart_do_not(...): # t=0, t=61 -> not hostile; t=66 -> hostile
def test_shield_only_hits_count(...)                # station shields up, IsHullHit()==0 both times
def test_tractor_and_collision_never_count(...)     # weapon_type "tractor" / "collision" x3, 10 s apart
def test_npc_fire_never_counts(...)                 # source = another ship
def test_spacefacility_counts_as_a_station(...)     # IsStationary()==0 but a home station
def test_an_enemy_station_is_untouched(...)         # pre-added to enemy group: no register entry, AI unchanged
def test_armed_station_gets_starbase_attack(...)    # FedStarbase: GetAI() not None, its script module "StarbaseAttack"
def test_unarmed_station_gets_no_ai(...)            # DryDock: hostile, GetAI() is None
def test_prior_groups_are_recorded(...)             # station first in friendly group -> removed, prior_groups == ("friendly",)
def test_inactive_does_nothing(...)                 # deactivate(); two hits -> not hostile, no counts
def test_activate_twice_registers_once(...)         # handler list for ET_WEAPON_HIT holds our name once
def test_hits_from_a_rebuilt_player_count(...)      # Review Focus 5: second hit from a new ShipClass with the player's name, set as player
def test_no_player_is_harmless(...)                 # Review Focus 2: GetPlayer() None -> no raise, nothing counted
```

- [ ] **Step 2: Run** `uv run pytest tests/unit/test_station_hostility.py -q` — expected: FAIL (module missing).

- [ ] **Step 3: Implement** `engine/systems/station_hostility.py`. Counting: keep counted hit times per station object id; a hit counts only if `t - last_counted >= HIT_GAP_S` (or none yet); once two counted hits lie within `WINDOW_S`, turn hostile. Turning hostile (spec §5.3, in order): register entry; remove the name from friendly/neutral groups (record which), add to enemy group; if any of `GetPhaserSystem()`, `GetTorpedoSystem()`, `GetPulseWeaponSystem()` is not None, record `prior_ai` from `QuickBattle.g_kShips` when the station's id is there, then `station.SetAI(AI.Compound.StarbaseAttack.CreateAI(station, App.ObjectGroup_FromModule("QuickBattle.QuickBattle", "pFriendlies")))`. Mission groups via the current mission (`App.Game_GetCurrentGame().GetCurrentEpisode().GetCurrentMission()`). Register both handlers with `App.g_kEventManager.AddBroadcastPythonFuncHandler(event_type, mission, qualified_name)`; `on_entered_set` may be a stub here (Task 2 fills it). Docstring at the top states the rule and cites the spec.

- [ ] **Step 4: Run** `uv run pytest tests/unit/test_station_hostility.py -q` — expected: all pass.

- [ ] **Step 5: Commit** `git add engine/systems/station_hostility.py tests/unit/test_station_hostility.py` then `git commit -F <msg file>` ("feat(stations): a station attacked twice within a minute turns hostile").

### Task 2: Ending hostility, and wiring into Quick Battle

**Files:**
- Modify: `engine/systems/station_hostility.py`
- Modify: `engine/host_loop.py` (QB load block near `_qb_sim_restore.install(_QB)` ≈ line 7912; mission-swap reset next to `home_stations.reset()` ≈ line 4848)
- Modify: `tests/conftest.py` (autouse reset next to `_home_stations.reset()` ≈ line 1102)
- Test: `tests/unit/test_station_hostility.py`, `tests/integration/test_station_hostility_free_roam.py` (new)

**Interfaces:**
- Consumes: Task 1's register, `activate()`, `reset()`.
- Produces:
  - `on_entered_set(pObject, pEvent) -> None` (qualified `engine.systems.station_hostility.on_entered_set`)
  - `end_in_system(system: str) -> None` — restores every hostile station of that system: groups back, enemy group membership removed, AI back (`prior_ai` → `__import__("QuickBattle." + module).CreateAI(station)` with `QuickBattle.g_iCurrentAILevel` set to the level first; `None` → `SetAI(None)`); hit counts for those stations cleared; dead stations skipped
  - `end_all() -> None` — `end_in_system` for every system in the register
  - `install(qb) -> bool` — `activate()`, then wraps `qb.StartSimulation2` and `qb.EndSimulation` so each calls `end_all()` BEFORE the original; wrappers carry `_dauntless_station_hostility_orig` (sim_restore's `_wrap` convention), never installed twice

- [ ] **Step 1: Write the failing tests.** Unit, in `test_station_hostility.py`:

```python
def test_entering_a_set_in_another_system_restores(...)   # hostile FedStarbase in "Starbase12" (tauceti); player enters a "Savoy1" set -> not hostile, out of enemy group, back in its prior group, GetAI() is None
def test_entering_another_region_of_the_system_keeps_it(...)  # player enters "DryDock" (tauceti) -> still hostile
def test_entering_the_warp_set_keeps_it(...)
def test_restoring_brings_back_a_quick_battle_ai(...)     # station in g_kShips with ("StarbaseFriendlyAI", ..., "Friendly", 2): restored AI comes from QuickBattle.StarbaseFriendlyAI
def test_a_destroyed_hostile_station_is_dropped(...)      # Review Focus 1: destroy it, leave the system, nothing raises, register empty
def test_reset_forgets_without_restoring(...)             # Review Focus 4: after reset(), station still in enemy group, register empty, inactive
def test_install_wraps_once_and_clears_on_end_and_start(...)  # fake qb module with StartSimulation2/EndSimulation recording calls
```

Integration, `tests/integration/test_station_hostility_free_roam.py`, using the `world` fixture from `tests/integration/test_quickbattle_setup_e2e.py` and `tests/helpers/headless_mission.py` (warp exactly as `test_home_stations_free_roam._warp_to_starbase_12`):

```python
def test_starbase_12_fires_back(world):           # warp to Starbase 12; two player phaser hits 6 s apart via combat.apply_hit; hm.tick(15.0); player's shields or hull below their starting values; station in mission enemy group
def test_the_dry_docks_keep_it_hostile(world)     # then in-system Set Course to Systems.DryDock.DryDock (as tests/integration/test_in_system_warp_e2e.py does); still hostile
def test_leaving_tau_ceti_ends_it(world)          # then warp to another system (hm.first_offered_course(exclude_set=...)); station back out of the enemy group, GetAI() is None
def test_a_campaign_mission_never_counts(...)     # Review Focus 4: load a campaign mission (hm.load("Maelstrom.Episode1.E1M1.E1M1")); two player hits on Starbase 12 in its set -> not hostile
```

- [ ] **Step 2: Run** `uv run pytest tests/unit/test_station_hostility.py tests/integration/test_station_hostility_free_roam.py -q` — expected: the new tests FAIL.

- [ ] **Step 3: Implement** `on_entered_set` (player only; destination set name from the player's containing set; ignore the warp transit set; `end_in_system` for every registered system whose key differs from the new set's, and drop the hit counts of every station outside the new set's system, hostile or not — spec §5.2 "counts reset when the player leaves the system"; add `test_leaving_clears_part_counts`: one hit, leave, return, one more hit 6 s later → not hostile), `end_in_system`, `end_all`, `install(qb)`. In `host_loop.py` call `station_hostility.install(_QB)` right after `_qb_sim_restore.install(_QB)` (comment: why there), and `station_hostility.reset()` in the mission-swap block beside `home_stations.reset()` (same try/`dev_mode.log_swallowed` shape). Add `station_hostility.reset()` to the conftest autouse reset beside `_home_stations.reset()`.

- [ ] **Step 4: Run** the Step 2 command plus `uv run pytest tests/integration/test_home_stations_free_roam.py tests/integration/test_home_stations_quickbattle.py -q` — expected: all pass.

- [ ] **Step 5: Commit** the four files explicitly ("feat(stations): hostility ends when the player leaves the system").

### Task 3: A free-roam death is final

**Files:**
- Create: `engine/quickbattle/free_roam_death.py`
- Modify: `engine/host_loop.py` (QB load block, beside Task 2's install)
- Test: `tests/integration/test_free_roam_death.py`

**Interfaces:**
- Produces: `install(qb) -> bool` — wraps `qb.ShipDestroyed` (registered by name, `QuickBattle.QuickBattle.ShipDestroyed`, so the module attribute is what dispatch finds). Wrapper: when the destroyed ship is the current player's and `qb.bInSimulation` is false, return without calling BC's body (no `RecreatePlayer`, no forced bridge view); otherwise call the original. Marker `_dauntless_free_roam_death_orig`; never installed twice.

- [ ] **Step 1: Write the failing tests** with the `world` fixture:

```python
def test_dying_in_free_roam_leaves_no_ship(world):    # kill the player (hull damage via combat.apply_hit until dead); hm.tick(10.0) raises nothing; no ShipClass other than the dead one carries the player's name in any set; QuickBattle.RecreatePlayer was not called (monkeypatched counter)
def test_dying_in_a_battle_still_ends_it(world):     # start a battle as test_home_stations_quickbattle does; kill the player; BC's ET_END_SIMULATION timer is queued (original ran)
def test_an_npc_death_runs_bc_as_before(world):      # a battle ship destroyed: g_kShips entry removed (original ran)
def test_install_twice_wraps_once(...)
```

- [ ] **Step 2: Run** `uv run pytest tests/integration/test_free_roam_death.py -q` — expected: FAIL.

- [ ] **Step 3: Implement** `free_roam_death.py` (docstring quotes Mark's ruling from spec §5.5) and call `free_roam_death.install(_QB)` in the QB load block. If ticking after the death raises anywhere in `host_loop` (Review Focus 2), fix that call site to tolerate a dead player rather than skipping the death.

- [ ] **Step 4: Run** the Step 2 command plus `tests/integration/test_station_hostility_free_roam.py` — expected: all pass.

- [ ] **Step 5: Commit** explicitly ("feat(quickbattle): a free-roam death is final").

### Task 4: Docs

**Files:**
- Modify: `docs/engine/home-stations.md` (new section "Stations defend themselves"), `CLAUDE.md` (Home stations row: one clause naming `station_hostility.py` and `free_roam_death.py`)
- Test: `uv run pytest tests/docs -q`

- [ ] **Step 1:** Write the section: the rule, the constants, what ends it, the free-roam death rule, "not live-verified".
- [ ] **Step 2: Run** `uv run pytest tests/docs -q` — expected: pass.
- [ ] **Step 3: Commit** both files explicitly ("docs(stations): stations defend themselves").
