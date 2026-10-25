# Home Stations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every station in the design's table is present whenever its home region's set is built. A mission asking for one gets the existing station back. A Quick Battle puts every real object back as it was when the battle ends.

**Architecture:** `engine/systems/owners.py` is a small registry. A world system that places objects into a region registers as an owner and tags each object it places (spec §4a). Home stations are the first owner; patrols come later. `engine/systems/home_stations.py` covers the station side:
- the station table, a checked-in JSON beside it;
- reading each placement point from the SDK at run time;
- placing stations from the existing region hook;
- answering `is_standing`;
- wrapping `loadspacehelper.CreateShip` so a mission reuses the station.

`engine/quickbattle/sim_restore.py` wraps three Quick Battle SDK functions:
- it records which objects are real when a battle starts (owned objects always are);
- it keeps owned objects in their own set;
- when the battle ends, it rebuilds anything the battle changed. An owned object is rebuilt by its owner.

**Tech Stack:** Python 3.11 engine over the SDK's Python scripts; pytest, headless.

**Spec:** `docs/superpowers/specs/2026-10-25-home-stations-design.md`

## Global Constraints

- **No BC coordinate in Dauntless data or tests.** Placement points are read from the SDK files at run time. Tests compare against positions read independently from the SDK, never against typed numbers.
- `home_stations.json`: unknown keys, missing keys, a duplicate (set, name) pair and a `format` other than 1 are all rejected with a `ValueError` that names the problem.
- `is_standing(station)` is the only gate on placing a station.
- Stations join no mission group (not friendly, enemy or neutral).
- A station's name and ship script match the mission's `CreateShip` exactly (spec §3 table).
- Read engine flags with `obj.__dict__.get(...)`, never `getattr`, so a `TGObject.__getattr__` stub can never read as truthy.
- SDK loader post-exec filter: change **both** twins, `tools/mission_harness.py` and `tests/conftest.py`.
- Never spell `game` or `sdk` as a path segment, and never capture a path at import (`tests/unit/test_path_indirection.py`).
- Run only the focused test files named in each task: `uv run pytest <files> -q`, from the worktree. Never a whole suite, never `scripts/check_tests.sh`.
- Banned git: `checkout -- <path>`, `restore`, `stash`, `clean`, `reset --hard`, `add -A`, `add .`. Stage explicit paths. If a commit message contains "reset", "restore", "checkout", "stash", "clean" or `--`, write it to a file and use `git commit -F`.
- Never launch the game.
- End commit messages with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

## Review Focus

1. **A region's `Initialize` runs again while its old set exists** (Quick Battle region change, a second visit). Expect exactly one station in the new set. Pinned in Task 2.
2. **A mission placement file fails to import or lacks the point.** Expect the region to build, one `[home-stations]` line, and the other stations still placed. Pinned in Task 2.
3. **Two stations share the name `Outpost`** (Cebalrai2, Prendel3). Destroying one must not stop the other being placed. Pinned in Task 2.
4. **A dead hull from a battle shares its name with the station rebuilt in its place.** The hulk cap's later eviction must not remove the new station. Pinned in Task 4.
5. **A battle starts after the player picks a "dupe" region** (Sol1, Cebalrai1, Vesuvi5, Vesuvi6, Belaruz4). BC renames the player's set to `<name>Dupe`. The station stays in that set object, and nothing raises. Pinned in Task 5.

---

### Task 1: Station table and placement-point reader

**Files:**
- Create: `engine/systems/home_stations.json`
- Create: `engine/systems/home_stations.py`
- Test: `tests/unit/test_home_stations_table.py`

**Interfaces:**
- Produces:
  - `Station`: frozen dataclass with `set_name: str`, `name: str`, `script: str` (the `ships.<script>` leaf), `point: str`, `point_module: str`.
  - `load_table(path) -> tuple[Station, ...]`: raises `ValueError`.
  - `table() -> tuple[Station, ...]`: loads the JSON beside the module and caches it. The path is computed inside the function.
  - `stations_for_set(set_name: str) -> tuple[Station, ...]`: rows in file order.
  - `read_point(station: Station, pSet) -> tuple[TGPoint3, TGMatrix3] | None`: returns copies of the point's world location and rotation, or `None` if the point is not found.

- [ ] **Step 1: Write the data file.** Format: `{"format": 1, "stations": [{"set", "name", "script", "point", "point_module"}, ...]}`. One row per spec §3 row, in the spec's order. `point_module` is the dotted module that defines the point:
  - region points: `Systems.Starbase12.Starbase12`, `Systems.DryDock.DryDock`, `Systems.Biranu.Biranu2`, `Systems.Savoy.Savoy1`;
  - mission points: `Maelstrom.Episode1.E1M1.Dock_P` (rows `Dry Dock2`, `Dry Dock3`, `Station`), `Maelstrom.Episode4.E4M5.E4M5_Chambana1_P`, `Maelstrom.Episode4.E4M6.E4M6_Cebalrai2_P`, `Maelstrom.Episode7.E7M3.Ascella3_P`, `Maelstrom.Episode7.E7M6.E7M6_P`, `Maelstrom.Episode5.E5M2.Prendel3_P`, `Maelstrom.Episode7.E7M2.E7M2_Albirea_P`.

- [ ] **Step 2: Write the failing tests**

```python
import json
import math

import pytest

from engine.systems import home_stations as hs

ROW = {"set": "S", "name": "N", "script": "FedStarbase", "point": "P",
       "point_module": "Systems.Starbase12.Starbase12"}


def _write(tmp_path, doc):
    p = tmp_path / "t.json"
    p.write_text(json.dumps(doc))
    return p


def test_table_holds_the_thirteen_stations():
    rows = hs.table()
    assert len(rows) == 13
    assert len({(s.set_name, s.name) for s in rows}) == 13
    sb = hs.stations_for_set("Starbase12")
    assert [(s.name, s.script, s.point, s.point_module) for s in sb] == [
        ("Starbase 12", "FedStarbase", "Starbase12 Location",
         "Systems.Starbase12.Starbase12")]
    assert [s.name for s in hs.stations_for_set("DryDock")] == [
        "Dry Dock", "Dry Dock2", "Dry Dock3", "Station"]
    assert hs.stations_for_set("Belaruz1") == ()


@pytest.mark.parametrize("doc, word", [
    ({"format": 1, "stations": [dict(ROW, colour="red")]}, "colour"),
    ({"format": 1, "stations": [{k: v for k, v in ROW.items() if k != "point"}]}, "point"),
    ({"format": 1, "stations": [ROW, ROW]}, "duplicate"),
    ({"format": 2, "stations": [ROW]}, "format"),
    ({"format": 1, "stations": [ROW], "extra": 1}, "extra"),
])
def test_bad_tables_are_rejected(tmp_path, doc, word):
    with pytest.raises(ValueError, match=word):
        hs.load_table(_write(tmp_path, doc))
```

Plus, using `tests.helpers.fresh_world._fresh_world()` in a fixture:
- `test_read_point_from_a_region_file`: run `Systems.Starbase12.Starbase12.Initialize()`, then call `read_point` on the Starbase 12 row with the `Starbase12` set. The location must equal `hm.placement_location("Starbase12", "Starbase12 Location")` (`tests.helpers.headless_mission`) within 1e-4 on each axis.
- `test_read_point_from_a_mission_file_matches_the_sdk_and_leaves_no_trace`: run `Systems.DryDock.DryDock.Initialize()`. Snapshot `dict(engine.appc.placement._waypoint_registry)` and `{n: dict(s._objects) for n, s in App.g_kSetManager._sets.items()}`. Call `read_point` on the `Dry Dock2` row with the `DryDock` set. Both snapshots must be unchanged. Oracle: create a set `"OracleScratch"` with `App.SetClass_Create()` + `App.g_kSetManager.AddSet`, then run `Maelstrom.Episode1.E1M1.Dock_P.LoadPlacements("OracleScratch")`. The location and every rotation column must equal that set's `DryDock2` waypoint within 1e-4.
- `test_read_point_missing_point_is_none`: give `read_point` a `Station` whose `point` is `"No Such Point"`. It returns `None`.

- [ ] **Step 3: Run to verify they fail**

Run: `uv run pytest tests/unit/test_home_stations_table.py -q`
Expected: FAIL, `ModuleNotFoundError: engine.systems.home_stations`.

- [ ] **Step 4: Implement `load_table`, `table`, `stations_for_set`, `read_point`**

`read_point` has two branches:
- **Region point.** When `station.point_module == pSet.GetRegionModule()`, read the set's own `Waypoint`/`PlacementObject` named `station.point`.
- **Mission point.** Otherwise, import `point_module` with `importlib.import_module`, snapshot `placement._waypoint_registry`, and call `LoadPlacements("__dauntless_home_station_probe__")`. No set has that name, so `Waypoint_Create` adds the points to no set; they land only in the registry. Read the point from the registry, then restore the registry exactly (clear + update), in a `finally`.

Return copies (`TGPoint3`/`TGMatrix3` built from the values), never the waypoint's own objects.

- [ ] **Step 5: Run to verify they pass**

Run: `uv run pytest tests/unit/test_home_stations_table.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add engine/systems/home_stations.json engine/systems/home_stations.py tests/unit/test_home_stations_table.py
git commit -m "feat(stations): home station table and SDK placement-point reader"
```

---

### Task 2: Owners; place stations when their region is built; `is_standing`

**Files:**
- Create: `engine/systems/owners.py`
- Test: `tests/unit/test_owners.py`
- Modify: `engine/systems/home_stations.py`
- Modify: `engine/systems/region_hooks.py` (the `Initialize` wrapper in `on_region_module_exec`)
- Modify: `engine/host_loop.py:4838` (`_reset_system_loader_state`)
- Modify: `tests/conftest.py` (`_reset_leakable_engine_globals`, line ~927)
- Test: `tests/integration/test_home_stations_regions.py`

**Interfaces:**
- Consumes: Task 1's `Station`, `stations_for_set`, `read_point`.
- Produces, in `owners.py`:
  - `Owner`: a Protocol with `name: str`, `rebuild(old, record) -> object | None` and `after_rebuild(new, record) -> None`. `record` is Task 6's `sim_restore.Record`; until Task 6, an owner receives it opaquely.
  - `register(owner) -> None`: keyed by `owner.name`. Registering the same name again replaces the entry, so a module reload is safe.
  - `get(name: str) -> Owner | None`.
  - `tag(obj, owner_name: str, key) -> None`: the only writer of `obj.__dict__["_dauntless_owner"] = (owner_name, key)`.
  - `owner_of(obj) -> tuple[Owner, object] | None`: reads `obj.__dict__.get("_dauntless_owner")`. Returns None when the object is untagged or its owner name is not registered.
- Produces, in `home_stations.py`:
  - `OWNER_NAME = "home_stations"`, plus a registered owner instance. Its `rebuild` is Step 3's single-station placement, given the record's set and the transform the record holds. Its `after_rebuild` calls `forget_destroyed`.
  - `place_for_set(pSet, set_name: str) -> list`: the station objects it created.
  - `home_station_of(obj) -> Station | None`: the key when `owner_of(obj)` is the home-stations owner.
  - `mark_home(obj, station: Station) -> None`: calls `owners.tag(obj, OWNER_NAME, station)`.
  - `is_standing(station: Station) -> bool`.
  - `forget_destroyed(station: Station) -> None`.
  - `reset() -> None`: clears the destroyed record and the point cache. It never unregisters the owner.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_owners.py`:
- `test_tag_and_owner_of`: register a test `Owner`, tag a plain `App.ShipClass_Create("X")` with it under key `7`. `owner_of` returns `(that owner, 7)`.
- `test_untagged_and_unregistered_are_none`: an untagged object, and an object tagged with an unregistered owner name, both give `owner_of(...) is None`.
- `test_a_stub_attribute_never_reads_as_owned`: on a `TGObject` whose `__getattr__` returns a stub, `owner_of` is None. This proves the read goes through `__dict__`.

Region tests:

All tests build sets with `tests.helpers.mapped_regions.load_region(system, region)`. The (system, region) pairs: `("TauCeti","Starbase12")`, `("TauCeti","DryDock")`, `("Chambana","Chambana1")`, `("Cebalrai","Cebalrai2")`, `("Ascella","Ascella3")`, `("Alioth","Alioth6")`, `("Prendel","Prendel3")`, `("Biranu","Biranu2")`, `("Savoy","Savoy1")`, `("Albirea","Albirea3")`. The tests:

- `test_every_station_is_placed_with_its_script_at_its_point`: parametrised over the ten regions. For each row of `stations_for_set(region)`, `App.ShipClass_GetObject(pSet, row.name)` must:
  - exist;
  - have `GetScript() == "ships." + row.script`;
  - have `home_station_of(obj) == row`;
  - have a world location equal to the Task 1 oracle within 1e-4. The oracle is the set's waypoint for region points, or an `"OracleScratch"` `LoadPlacements` for mission points.

  It must also be in none of `MissionLib.GetMission()`'s friendly, enemy and neutral groups.
- `test_no_station_sits_inside_a_planet`: parametrised the same way, as a guard; it passes at the start. For every planet in the set (`GetClassObjectList(App.CT_PLANET)`), the distance from the planet to the station is greater than `planet.GetRadius() + station.GetRadius()`. If this guard ever fails, stop and report BLOCKED: a map change needs a decision from Mark.
- `test_rebuilding_a_region_gives_one_station` (Review Focus 1): call `load_region("TauCeti","Starbase12")` twice. The live `Starbase12` set holds exactly one object named `"Starbase 12"`. The first station's `GetContainingSet()` is not the new set.
- `test_a_destroyed_station_is_not_placed_again_until_reset`: load Starbase12, then destroy the station with `ship_death.begin(st)` followed by `ship_death.advance(ship_death.MAX_THROES_DURATION + 0.1)`. Check `is_standing(row) is False`. Reload the region: the set holds no `"Starbase 12"`. After `home_stations.reset()`, a reload places it again.
- `test_two_outposts_are_independent` (Review Focus 3): destroy Cebalrai2's `Outpost` as above. Loading Prendel3 still places its `Outpost`.
- `test_a_bad_point_module_skips_only_that_station` (Review Focus 2): monkeypatch `home_stations.table` to return the real table with the `Dry Dock2` row's `point_module` set to `"Maelstrom.NoSuchModule_P"`. Load DryDock. `Dry Dock`, `Dry Dock3` and `Station` are placed, `Dry Dock2` is not, and `capfd` shows exactly one line starting `[home-stations]` that names `Dry Dock2`.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_owners.py tests/integration/test_home_stations_regions.py -q`
Expected: FAIL. `owners` doesn't exist, the stations are absent, and `place_for_set`/`is_standing` don't exist yet.

- [ ] **Step 3: Implement**

`place_for_set` loops over `stations_for_set(set_name)` in order. For each row, inside its own `try`:
1. Skip it if `not is_standing(row)`.
2. Skip it if `pSet.GetObject(row.name)` is not None.
3. Call `read_point`; skip it if the result is None.
4. Call `loadspacehelper.CreateShip(row.script, pSet, row.name, "", 0, 0)`. Pass no placement name and `bGrabPreloaded=0`, so a station never takes a mission's precreated ship.
5. Call `SetTranslate(loc)`, `SetMatrixRotation(rot)`, `UpdateNodeOnly()`, then `mark_home`.

Any failure prints one `[home-stations] <set>/<name> not placed: <Type>: <msg>` line and moves on.

Steps 4-5 are one private function, `_build(row, pSet, loc, rot)`. Both `place_for_set` and the owner's `rebuild` use it, so a battle rebuild and a region build make the same object. Register the owner at module import.

`is_standing` is False only when `(set_name, name)` is in the module's destroyed record. The record is filled by an `engine.appc.ship_lifecycle` subscriber, registered once at module import. On `"destroyed"`, it records the ship's station when `home_station_of(ship)` is set **and** the ship is still in a set (`GetContainingSet()` is not None).

In `region_hooks`, the wrapper calls `home_stations.place_for_set(pSet, set_name)` right after `apply_map.apply_to_set`. Its own exceptions are caught there and printed as one line: placing a station must never break a region. Update the module docstring's ordering paragraph.

Add `home_stations.reset()` to `host_loop._reset_system_loader_state` (both the dev swap and `mission_change` reach it) and to `tests/conftest.py`'s `_reset_leakable_engine_globals`.

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/unit/test_owners.py tests/integration/test_home_stations_regions.py tests/unit/test_home_stations_table.py -q`
Expected: PASS.

- [ ] **Step 5: Run the region hook's own tests**

Run: `uv run pytest tests/unit/test_region_map_on_initialize.py tests/unit/test_system_loader.py tests/unit/test_ensure_system_loaded_wiring.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add engine/systems/owners.py engine/systems/home_stations.py engine/systems/region_hooks.py engine/host_loop.py tests/conftest.py tests/unit/test_owners.py tests/integration/test_home_stations_regions.py
git commit -m "feat(stations): owner tags; place home stations when their region is built"
```

---

### Task 3: A mission's `CreateShip` reuses the station

**Files:**
- Modify: `engine/systems/home_stations.py`
- Modify: `engine/appc/sdk_overrides.py` (`on_sdk_module_exec`)
- Modify: `tools/mission_harness.py:515` and `tests/conftest.py:558` (both loader filters)
- Test: `tests/unit/test_home_stations_reuse.py`, `tests/integration/test_home_stations_campaign.py`

**Interfaces:**
- Consumes: `home_station_of`, `place_for_set`.
- Produces:
  - `reusable(pcScript: str, pSet, name: str)`: returns the ship or None. It returns the ship when `pSet` holds an object named `name` for which all of these hold:
    - `home_station_of` is set;
    - `GetScript() == "ships." + pcScript`;
    - `engine.appc.ship_death._out_of_action(obj)` is False.
  - `install_create_ship_hook(module) -> bool`: wraps `module.CreateShip` and is idempotent through a `_dauntless_home_station_orig` attribute on the wrapper.

- [ ] **Step 1: Write the failing unit tests** (on a set from `load_region("TauCeti","Starbase12")`)

```python
def test_create_ship_returns_the_home_station_and_places_it(sb12):
    import loadspacehelper
    pSet, station = sb12
    wp = App.Waypoint_Create("Elsewhere", "Starbase12", None)
    wp.SetTranslateXYZ(*_offset_from(station, 50.0))   # helper: station location + 50 GU on x
    got = loadspacehelper.CreateShip("FedStarbase", pSet, "Starbase 12", "Elsewhere", 1)
    assert got is station
    assert _close(station.GetWorldLocation(), wp.GetWorldLocation())
    assert sum(1 for n in pSet._objects if n == "Starbase 12") == 1


@pytest.mark.parametrize("script, name", [("Galaxy", "Starbase 12"), ("FedStarbase", "Other")])
def test_anything_else_takes_bcs_path(sb12, script, name):
    import loadspacehelper
    pSet, station = sb12
    got = loadspacehelper.CreateShip(script, pSet, name, "")
    assert got is not station
```

Also add:
- `test_a_dying_station_is_not_reused`: start `ship_death.begin(station)`. `reusable("FedStarbase", pSet, "Starbase 12")` is None.
- `test_the_hook_is_installed_by_the_sdk_loader`: `import loadspacehelper`; `loadspacehelper.CreateShip` has the `_dauntless_home_station_orig` attribute.

The `_offset_from` helper builds its numbers from the station's own location; there are no literal coordinates.

- [ ] **Step 2: Write the failing campaign tests**

All three use `tests.helpers.headless_mission`, with `no_logged_failures`:
- `test_e1m1_reuses_starbase_and_dry_docks`: run `hm.load("Maelstrom.Episode1.E1M1.E1M1")`. For `("Starbase12","Starbase 12")`, `("DryDock","Dry Dock")`, `("DryDock","Dry Dock2")`, `("DryDock","Dry Dock3")` and `("DryDock","Station")`, the set holds exactly one object of that name, and `home_station_of` is set on it. Being marked proves it is the region hook's object, not a second one built by the mission.
- `test_e7m3_reuses_the_resupply_station_on_arrival`:
  1. Run `hm.load("Maelstrom.Episode7.E7M3.E7M3")` and capture `st = Ascella3.GetObject("Resupply Station")`; it must be marked.
  2. Move the player into Ascella3: `old.RemoveObjectFromSet("player")`, `ascella3.AddObjectToSet(player, "player")`.
  3. Run `hm.tick(1.0)`, which processes `ET_ENTERED_SET`, so E7M3's `EnterSet` runs its `CreateShip`.
  4. Assert that `mod.bAscella3Arrive` is true, that `Ascella3.GetObject("Resupply Station") is st` with exactly one of that name, and that `st` has an instance handler for `App.ET_SUBSYSTEM_COMPLETELY_DISABLED` naming `DisableSystemHandler`. Find that handler through the same handler table `AddPythonFuncHandlerForInstance` writes.
- `test_e8m2_moves_starbase_12_to_its_mission_point`: run `hm.load("Maelstrom.Episode8.E8M2.E8M2")`. `"Starbase 12"` is marked, and its location equals `hm.placement_location("Starbase12", "Starbase Location")` within 1e-4.

- [ ] **Step 3: Run to verify they fail**

Run: `uv run pytest tests/unit/test_home_stations_reuse.py tests/integration/test_home_stations_campaign.py -q`
Expected: FAIL, with no hook and duplicate or unmarked stations. If E8M2's load fails for an unrelated reason, report BLOCKED with the error.

- [ ] **Step 4: Implement**

The wrapper has BC's signature, `(pcScript, pSet, pcIdentifier, pcLocationName, iWarpFlash=0, bGrabPreloaded=1)`.
- If `reusable(...)` returns a station: call `PlaceObjectByName(pcLocationName)` when it is non-empty, call `UpdateNodeOnly()`, and return the station. The warp-flash argument is ignored.
- Otherwise call the original.

Routing:
- In `sdk_overrides.on_sdk_module_exec`: when `qualname == "loadspacehelper"`, call `_dispatch(home_stations.install_create_ship_hook, module)`. Update the docstring's routing table.
- In both loader twins, the filter becomes `_qual.startswith(("ships.", "Systems.")) or _qual == "loadspacehelper"`. Update both comments.

- [ ] **Step 5: Run to verify they pass**

Run: `uv run pytest tests/unit/test_home_stations_reuse.py tests/integration/test_home_stations_campaign.py tests/integration/test_home_stations_regions.py -q`
Expected: PASS.

- [ ] **Step 6: Run the campaign transition tests that load these missions**

Run: `uv run pytest tests/integration/test_campaign_warp_transitions.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add engine/systems/home_stations.py engine/appc/sdk_overrides.py tools/mission_harness.py tests/conftest.py tests/unit/test_home_stations_reuse.py tests/integration/test_home_stations_campaign.py
git commit -m "feat(stations): a mission's CreateShip reuses the home station"
```

---

### Task 4: Dead-hull removal never removes a namesake

**Files:**
- Modify: `engine/appc/ship_death.py` (`_remove`, new `forget`)
- Test: `tests/unit/test_ship_death_namesake.py`

**Interfaces:**
- Produces: `ship_death.forget(ship) -> None`, which drops every `_active` entry whose ship `is ship`. `_remove(ship)` removes the set's entry only when `pSet.GetObject(ship.GetName()) is ship`.

- [ ] **Step 1: Write the failing tests** (Review Focus 4)
- `test_evicting_a_hulk_leaves_its_namesake`: use a set with a ship `"A"`.
  1. Kill it to the hulk phase.
  2. Remove it from the set, then add a new ship under the same name `"A"`.
  3. Make 8 more hulks (`MAX_HULKS`), so the first is evicted.
  4. The set's `"A"` is still the new ship.
- `test_forget_drops_a_dying_ship`: `begin(ship)`, then `forget(ship)`. `ship_death._active` holds no entry for it, and `advance` never calls `SetDead` on it.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_ship_death_namesake.py -q`
Expected: FAIL. The new ship is removed, and `forget` doesn't exist.

- [ ] **Step 3: Implement both.** Keep `_remove`'s existing order: locks first, then the set, then the broadcast. The broadcast still runs for the old object.

- [ ] **Step 4: Run to verify they pass, then run the death tests by file**

Run: `uv run pytest tests/unit/test_ship_death_namesake.py tests/unit/test_ship_death.py tests/unit/test_ship_death_hulks.py tests/unit/test_rock_death.py tests/unit/test_ai_teardown_on_death.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/ship_death.py tests/unit/test_ship_death_namesake.py
git commit -m "fix(death): dead-hull removal never removes a namesake"
```

---

### Task 5: Quick Battle keeps owned objects in their own set

**Files:**
- Create: `engine/quickbattle/sim_restore.py`
- Modify: `engine/host_loop.py:7893-7905`. Call `sim_restore.install(_QB)` **before** `install_generate_ships_hook`, so that `spawn`'s idempotency marker stays on the outermost `EndSimulation`.
- Test: `tests/integration/test_home_stations_quickbattle.py`

**Interfaces:**
- Consumes: `owners.owner_of`, `owners.tag`, `owners.register`.
- Produces: `sim_restore.install(qb) -> bool`. It wraps `qb.ChangeRegion`, `qb.StartSimulation2` and `qb.EndSimulation`, each idempotent through a `_dauntless_sim_restore_orig` attribute. This task fills in only the `ChangeRegion` half; Task 6 adds the other two.

- [ ] **Step 1: Write the failing tests**

Use the `world` fixture from `tests.integration.test_quickbattle_setup_e2e`, plus a local helper `_into_region(system, region)`. The helper:
- calls `mapped_regions.load_region`;
- moves the player into that set (`RemoveObjectFromSet("player")` + `AddObjectToSet(player, "player")`);
- calls `player.PlaceObjectByName("Player Start")` and `UpdateNodeOnly()`;
- returns the set.

Note that the player's name in the set may be `"Player"` here; use `player.GetName()`.

The tests:
- `test_a_battle_at_starbase_12_includes_the_station`: `_into_region("TauCeti","Starbase12")`, add `"add:Warbird"`, then `_go`. `QB.g_pSet.GetName() == "Starbase12"`, and `"Starbase 12"` is in it and marked.
- `test_a_region_change_leaves_the_station_home`: `_into_region("TauCeti","Starbase12")`, save the station's location, set `QB.g_sSelectedRegion = "Belaruz1"`, add `"add:Warbird"`, then `_go`. The player is in `Belaruz1`. `"Starbase 12"` is in the `Starbase12` set at its saved location, and `Belaruz1` holds no `"Starbase 12"`.
- `test_a_dupe_region_change_keeps_the_station_in_its_set` (Review Focus 5): as above with `"Belaruz4"`. Save `old = starbase12 set object`. Afterwards the station's `GetContainingSet() is old`, and no exception was logged (`no_logged_failures`).
- `test_any_owned_object_stays_home`: register a test owner `"test_patrol"`. In Starbase12, create a ship with `loadspacehelper.CreateShip("Galor", pSet, "Patrol 1", "")` and `owners.tag` it with `"test_patrol"`. After a region change to `"Belaruz1"`, `"Patrol 1"` is still in `Starbase12`. This proves the rule reads the owner tag, not station-ness.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/integration/test_home_stations_quickbattle.py -q`
Expected: the first test passes already (Tasks 2-3), and the region-change tests FAIL because the station follows the player. Record that the first test passed before the change; it stays in the file as a guard.

- [ ] **Step 3: Implement the `ChangeRegion` wrapper**

1. Before calling the original, record `(object, its set object, location copy, rotation copy)` for every object in the player's containing set that has an owner (`owners.owner_of` is not None).
2. After the original, for each record whose object's containing set is not its saved set object:
   - remove the station from where it now is, only if that set's entry under its name is that station;
   - add it back to the saved set;
   - restore its location and rotation;
   - call `UpdateNodeOnly()`.

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/integration/test_home_stations_quickbattle.py tests/integration/test_quickbattle_setup_e2e.py tests/host/test_qb_late_arrivals.py tests/host/test_qb_spawn.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/quickbattle/sim_restore.py engine/host_loop.py tests/integration/test_home_stations_quickbattle.py
git commit -m "feat(quickbattle): owned objects stay in their region on a region change"
```

---

### Task 6: A battle ends with every real object as it began

**Files:**
- Modify: `engine/quickbattle/sim_restore.py`
- Modify: `engine/appc/subsystems.py:3284` (extract `iter_subsystems` from `repair_ship_fully`)
- Test: `tests/integration/test_home_stations_quickbattle.py`, `tests/unit/test_sim_restore_condition.py`

**Interfaces:**
- Consumes:
  - `owners.owner_of` and the `Owner` protocol (Task 2). The home-stations owner's `rebuild`/`after_rebuild` already re-tag the station and forget a battle-time destruction;
  - `ship_death.forget` (Task 4).
- Produces:
  - `subsystems.iter_subsystems(ship)`: yields the hull, every top-level subsystem `repair_ship_fully` reaches, and each one's children, in that order. `repair_ship_fully` is rewritten over it, with unchanged behaviour.
  - `sim_restore.condition_of(ship) -> dict`, with three keys:
    - `"subsystems"`: a list of `GetCondition()` values in `iter_subsystems` order;
    - `"shields"`: a list of `GetCurShields(face)` for faces 0-5, or `[]` when there is no shield subsystem;
    - `"ammo"`: a list of `GetAmmoType(slot).GetAvailable()` for each slot, or `[]`.
  - `sim_restore.apply_condition(ship, cond) -> None`: writes the same three back with `SetCondition`, `SetCurShields` and `SetAvailable`.
  - `sim_restore.Record`: a frozen dataclass with these fields:
    - `obj`, `pset`, `name: str`, `script: str` (leaf);
    - `location: TGPoint3`, `rotation: TGMatrix3` (copies);
    - `scale: float`, `condition: dict`;
    - `owner: str | None`, `key: object`.

    This is what an owner's `rebuild(old, record)` receives.

- [ ] **Step 1: Write the failing unit test.** Use a ship from `loadspacehelper.CreateShip("Galaxy", pSet, "G", "")`:
  1. Record `condition_of`.
  2. Damage the hull, one subsystem, shield face 0, and set torpedo slot 0's ammo to 0.
  3. Call `apply_condition(ship, before)`.
  4. `condition_of(ship) == before`.

  Also run the existing `repair_ship_fully` tests in `tests/unit/test_sensor_probes.py`, `tests/unit/test_developer_options_panel.py` and `tests/unit/test_repair_subsystem.py`; they must still pass.

- [ ] **Step 2: Write the failing battle tests** (same file and fixture as Task 5):
- `test_end_combat_and_restart_keep_the_station`:
  1. Battle at Starbase12 with `"add:Warbird"`.
  2. `QB.EndSimulation()` followed by `hl._process_object_deletions()`: `"Starbase 12"` is present, and every `Warbird` ship is gone.
  3. Start again with `_go`, then `QB.RestartSimulation(QB.g_pXO, App.TGEvent_Create())`, `App.g_kTimerManager.tick(3.0)` and `hl._fire_pending_preload_done()`: the station is still there.
- `test_damage_from_the_battle_is_undone`:
  1. `_into_region("TauCeti","Starbase12")`. Before starting, create a real rock with `loadspacehelper.CreateShip("Asteroidh1", pSet, "Test Rock", "")` placed 100 GU off the player's position.
  2. Record `condition_of` for the station and the rock, then `_go` with `"add:Warbird"`.
  3. Use `combat.apply_hit` to hit the station's hull past its shields from the Warbird, and the rock from the **player**.
  4. Call `QB.EndSimulation()` and `hl._process_object_deletions()`.
  5. The objects named `"Starbase 12"` and `"Test Rock"` have `condition_of` equal to the recorded values within 1e-6.
- `test_a_station_destroyed_in_battle_comes_back`:
  1. In a battle at Starbase12, kill the station with `ship_death.begin(st)` and advance through the throes. `is_standing` is False.
  2. Call `QB.EndSimulation()` and `hl._process_object_deletions()`.
  3. The set holds exactly one live, marked `"Starbase 12"` at its placement point, and `is_standing(row)` is True.
  4. Advance `ship_death` past enough new hulks to evict the old one: the new station survives.
- `test_owned_objects_follow_their_owner`: register a test owner `"test_patrol"` whose `rebuild` records each call and builds through `loadspacehelper.CreateShip(record.script, record.pset, record.name, "", 0, 0)`, and whose `after_rebuild` records each call. In a battle at Starbase12:
  - **(a)** After `_go`, create and tag `"Late Patrol"`. It appeared mid-battle, yet survives `EndSimulation` + `_process_object_deletions` untouched, and `rebuild` was not called for it.
  - **(b)** Create and tag `"Patrol 1"` before `_go`, then damage it during the battle. After `EndSimulation`, `rebuild` was called once with a `Record` whose `name == "Patrol 1"`, and `after_rebuild` once. The `"Patrol 1"` in the set is the object `rebuild` returned, with its pre-battle `condition_of`.
  - **(c)** The Warbird (unowned, created by the battle) is gone.

- [ ] **Step 3: Run to verify they fail**

Run: `uv run pytest tests/unit/test_sim_restore_condition.py tests/integration/test_home_stations_quickbattle.py -q`
Expected: FAIL. BC's `EndSimulation` deletes the station, and the functions are missing.

- [ ] **Step 4: Implement**

- **`StartSimulation2` wrapper.** Before calling the original, store `pre_sim`: the ids (`id(obj)`) of every object in every set. Walk `App.g_kSetManager._sets` → `_objects`, as `host_loop._process_object_deletions` does.
- **`ChangeRegion` wrapper (Task 5's).** Also store `pre_change` (same walk) before calling the original. After it, when `qb.bInSimulation`, take the snapshot. Its target is `qb.g_pSet`. It covers every `CT_DAMAGEABLE_OBJECT` there that:
  - is not the player;
  - **and** is owned (`owners.owner_of` is not None), or was in `pre_sim`, or is absent from `pre_change` (it was built by the region's own `Initialize`).

  What it leaves out are the battle's own unowned ships, which were created after `pre_sim` and before `pre_change`. Each object becomes one `Record`.
- **`EndSimulation` wrapper.** Call the original first: BC's sweep flags everything except the player, and `RecreatePlayer` runs. Then:
  - **Owned objects not in the snapshot** (they appeared mid-battle): `SetDeleteMe(0)`, nothing else.
  - **Each record, alive, still in its set, `condition_of` unchanged:** `SetDeleteMe(0)`.
  - **Each record otherwise (changed or destroyed):** rebuild it.
    1. Call `ship_death.forget(old)`. If the set's entry under its name is the old object, call `RemoveObjectFromSet(name)` and then `engine.appc.objects.broadcast_object_deleted(old)`.
    2. **Owned:** `new = owner.rebuild(old, record)`. **Unowned:** `new = loadspacehelper.CreateShip(script, set, name, "", 0, 0)`, then restore its location and rotation, call `SetScale` when the scale is not 1.0, and call `UpdateNodeOnly()`.
    3. If `new` is None, print one `[sim-restore]` line and go to the next record.
    4. Call `apply_condition(new, record.condition)`. For an owned record, then call `owner.after_rebuild(new, record)`.

  Clear the snapshot after restoring it. `reset()` clears it too; call `sim_restore.reset()` from `host_loop`'s swap drain beside `_qb_late.reset()`.

- [ ] **Step 5: Run to verify they pass**

Run: `uv run pytest tests/unit/test_sim_restore_condition.py tests/integration/test_home_stations_quickbattle.py tests/integration/test_quickbattle_setup_e2e.py tests/host/test_qb_late_arrivals.py tests/host/test_qb_spawn.py tests/integration/test_quickbattle_fed_starbase_shields.py tests/unit/test_repair_subsystem.py tests/unit/test_sensor_probes.py tests/unit/test_developer_options_panel.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add engine/quickbattle/sim_restore.py engine/appc/subsystems.py engine/host_loop.py tests/unit/test_sim_restore_condition.py tests/integration/test_home_stations_quickbattle.py
git commit -m "feat(quickbattle): a battle ends with every real object as it began"
```

---

### Task 7: Free roam: warp to Starbase 12, dock, repair

**Files:**
- Test: `tests/integration/test_home_stations_free_roam.py`
- Modify (only if Step 3's test fails): `engine/host_loop.py`. The QuickBattle load path calls a new `home_stations.free_roam_docking_defaults()`, which sets `Systems.Starbase12.Starbase12_S`'s `g_bRepairsEnabled = 1`, `g_idGraffAction = App.NULL_ID` and `g_bFadeGraffEnd = 1`, but only if that module is already imported.

- [ ] **Step 1: Write the tests** (on the `world` fixture)
- `test_warping_to_starbase_12_finds_the_station_and_the_dock_button`:
  1. Run `hm.plot_course(hm.the_warp_button(), "Systems.Starbase12.Starbase12")`, then `hm.warp_and_wait(button, player)`.
  2. The player is in `Starbase12`, and `"Starbase 12"` is there and marked.
  3. Run `hm.tick(1.0)`: `Bridge.BridgeUtils.GetDockButton()` is enabled.
- `test_docking_repairs_the_player`:
  1. After the warp above, set the player's hull to half its maximum.
  2. Call `Systems.Starbase12.Starbase12_S.DockStarbase()`, then use `hm.tick_until` until the hull is back at maximum, bounded at 300 s.
  3. If docking cannot complete headless (the AI never reaches the station), stop and report BLOCKED with how far it got. Do not weaken the assertion.
- `test_free_roam_starts_with_repairs_enabled`: set `Starbase12_S.g_bRepairsEnabled = 0` and `g_idGraffAction` to a live action's id. Load Quick Battle again through `controller.loader.load_quickbattle()`. Both are back at their defaults.

- [ ] **Step 2: Run them**

Run: `uv run pytest tests/integration/test_home_stations_free_roam.py -q`
Expected: the first two PASS (Tasks 2-3 already make them true; they are the end-to-end proof). To confirm they test something, comment out the `place_for_set` call in `region_hooks` (back up and restore by copy, as CLAUDE.md describes), see both FAIL, and restore it with a `diff` that proves the file is byte-identical. The third test either passes (already reset; note why in the commit message) or FAILS.

- [ ] **Step 3: Only if the third test failed,** add `free_roam_docking_defaults()` and call it from the QuickBattle load path beside `sim_restore.install`. Re-run: PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_home_stations_free_roam.py engine/systems/home_stations.py engine/host_loop.py
git commit -m "test(stations): free roam warps to Starbase 12, docks and repairs"
```

---

### Task 8: Documentation

**Files:**
- Modify: `CLAUDE.md`. Add a "Home stations" row to the Key reference table, beside the Quick Battle rows. It names `engine/systems/home_stations.{py,json}`, `engine/quickbattle/sim_restore.py` and the spec, and covers these points:
  - stations are placed by the region hook and gated by `is_standing`;
  - `engine/systems/owners.py`: anything a world system places carries an owner tag. Quick Battle never treats an owned object as a battle object, keeps it in its set, and lets its owner rebuild it. Patrols are meant to be the next owner;
  - a mission's `CreateShip` reuses the station (marked, same script, alive);
  - ⚠️ a battle restores real objects by **rebuilding** what changed, so pre-battle scars are lost on a rebuilt object;
  - ⚠️ the Prendel outpost reappears in E6M4 until world state lands;
  - not live-verified.
- Modify: the spec's `Status:` line → `built on feat/home-stations, not live-verified`.

- [ ] **Step 1: Make both edits, then run** `uv run pytest tests/docs/test_doc_consistency.py -q`. Expected: PASS.
- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md docs/superpowers/specs/2026-10-25-home-stations-design.md
git commit -m "docs(stations): home stations reference row and status"
```

---

## Decisions this plan makes (not in the spec)

- **Rebuild, not repaint.** The renderer has no way to clear one ship's hull wear, so the battle restore rebuilds any real object whose condition changed. The rebuild applies the pre-battle condition numbers. Visible scars from before the battle are lost on a rebuilt object, and a rebuilt rock starts at rest.
- **Real versus simulated objects.** An owned object is always real (spec §4a). For an unowned object, timing decides: it is real if it appeared before `StartSimulation2` or during the region's `Initialize`. There is no list of what the simulation created. Late arrivals and break-up pieces are new and unowned, so BC's own sweep still deletes them.
- **Owners live in `engine/systems/owners.py`,** keyed by name. Registering the same name again replaces the entry, so the registry survives a module reload.
- **Mission placement points never become waypoints in the home set.** The station is placed from the read point directly, so a mission that later loads the same placement file never collides with a leftover point.
- **A failure to place a station prints one line and never breaks the region.**
