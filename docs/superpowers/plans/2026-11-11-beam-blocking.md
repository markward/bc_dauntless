# Beam Blocking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A phaser beam stops on the first ship, station, asteroid, planet or sun in its path; a ship/rock in the way takes the normal hit, a planet just stops the beam.

**Architecture:** One pure "first blocker along a beam" resolver per language. Python (`engine/appc/beam_blockers.py`) is the reference and the `DAUNTLESS_NATIVE_COMBAT=0` path. C++ (`native/src/combat/src/beam_block.cc`) is a statement-by-statement port, used by both the K2 kernel (damage) and the beam feed (drawing). The K2 walk gains one state after the bubble: if a blocker is found, the contact's target, distance, point, normal, tier, bubble and shields answer become the blocker's. A planet drops the contact. Anything the native side cannot answer becomes a new ASK, `blocker`, which Python answers with the reference function.

**Tech Stack:** Python 3.11, C++17, pybind11 (`native/src/host/host_bindings.cc`), pytest, gtest/ctest.

**Spec:** `docs/superpowers/specs/2026-11-11-beam-blocking-design.md` (read it first; this plan argues from it).

## Global Constraints

- Work in the worktree `.claude/worktrees/beam-blocking` on branch `feat/beam-blocking`, created from LOCAL `main` (`git worktree add .claude/worktrees/beam-blocking -b feat/beam-blocking main`). Setup: `cp <main>/settings.json .`, `mkdir -p mods && cp -Rc <main>/mods/. mods/`, `uv sync --extra dev` (never `--active`), and a fresh Debug configure. Pin the uv 3.11 interpreter: `U=~/.local/share/uv/python/cpython-3.11.15-macos-aarch64-none; cmake -B build -S . -DCMAKE_BUILD_TYPE=Debug -DPython3_EXECUTABLE=$PWD/.venv/bin/python3 -DPython3_ROOT_DIR=$U -DPython3_FIND_FRAMEWORK=NEVER -DPython3_FIND_STRATEGY=LOCATION`, plus `-DFETCHCONTENT_SOURCE_DIR_<DEP>=<main>/build/_deps/<dep>-src` for CEF, GOOGLETEST, NLOHMANN_JSON, OPENAL_SOFT, PYBIND11. Then `cmake --build build -j`.
- ⛔ Never run either gate or a whole pytest directory. Run only the focused test files named in each task, plus the cheap tree guards `tests/docs tests/unit/test_path_indirection.py tests/unit/test_install_write_guard.py tests/unit/test_gate_tiers.py`. Never pass pytest an empty file list.
- ⛔ No destructive git (`checkout -- / restore / stash / clean / reset --hard / add -A / add .`). Stage explicit paths. If a commit message contains "reset", "restore", "checkout", "stash", "clean" or `--`, write it to a file and `git commit -F`.
- ⛔ Never launch the game (`./build/dauntless`), headless or not. The live check and the perf capture are Mark's.
- Units: everything in GU. Never name a variable `*_m` / `*_mps`.
- The native port is **Python-exact**: same operand order, same double arithmetic, `#pragma clang fp contract(off)` as the existing combat files. A change to the native walk updates its header contract comment and `docs/reference/engine/native-combat/k2-beams-map.md` in the same commit.
- A field the kernel reads MUST be a `Native*` descriptor (CLAUDE.md, native combat row).
- Every commit ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Decisions this plan makes (beyond the spec)

- **Planet surface = mesh trace** on the planet's renderer instance (`session.planet_instances`), which puts the beam's end on the drawn surface (it includes the geosphere centre offset for free). With no instance (headless), a ray–sphere entry about `GetWorldLocation()` with `collisions.world_radius`. Broadphase bound for a planet: `world_radius × PLANET_BOUND_SLACK`, `PLANET_BOUND_SLACK = 1.02`, which covers the ≤0.9% centre offset.
- **Shielded blocker's hull point** (spec §4.3.2): the mesh tier of `_resolve_hit_point` along the same ray if it hits, else the bubble point itself, with normal None. This skips the torpedo pattern's sphere tier. That tier would put the point on an inflated sphere, which is worse.
- **A planet-blocked pulse is lost.** The dwell was consumed by the bank, and nothing receives it.
- **Candidate order** is deterministic: `ships_list` order, then planets in the `planet_instances` iteration order. A candidate replaces the best only when strictly nearer, so the target wins ties, and among equal blockers the earlier one wins.
- **The spec's asset-backed tests 3 and 11** become fake-trace tests (`install_trace_hooks` in gtest; a monkeypatched `host_io.ray_trace_mesh` in Python). Real meshes are covered by Mark's live check.

## Review Focus

1. **A blocker that is also a firing ship's own target elsewhere.** Its mirror row is reused by two contacts in one step. The pulse on it must land in walk order, the same as two banks on one target do today. Covered by Task 5 `test_two_banks_one_blocker_native_equals_python`.
2. **A blocker that dies mid-step** (an earlier pulse kills it). Later banks this step must not block on a dead object: `IsDead()` / `_dead` is read live per candidate, never cached. Covered by Task 2 `test_dead_blocker_stops_blocking_same_step`.
3. **A beam fired from inside another ship's bubble** (escort hugging the shooter). `shield_bubble_entry` returns None when the origin is inside. The candidate then falls to the mesh rule and must not block on the bubble. Covered by Task 1 `test_emitter_inside_candidate_bubble_uses_mesh_only`.
4. **Player's beam blocked by a friendly in a mission with friendly fire armed.** It must count exactly once per pulse, never per frame: resting contacts raise no `WeaponHitEvent`. Covered by Task 2 `test_friendly_fire_counts_pulses_not_frames`.
5. **Cross-region candidates in one star system** (a ship in another region set at a non-zero offset). It must never block, since candidates are same-set only. Covered by Task 1 `test_other_set_never_blocks`.

---

### Task 1: Python reference resolver

**Files:**
- Create: `engine/appc/beam_blockers.py`
- Test: `tests/unit/test_beam_blockers.py`

**Interfaces:**
- Consumes: `combat._resolve_hit_point`, `combat.shields_block`, `combat.shield_bubble_entry`, `combat.bubble_bound_radius`, `combat.ray_sphere_entry` (or wherever `ray_sphere_entry` lives; import it as `_resolve_hit_point` does), `collisions.world_radius`, `frames.containing_set`.
- Produces:
  - `PLANET_BOUND_SLACK: float = 1.02`
  - `@dataclass(frozen=True) class Blocker: obj; kind: str  # "ship" | "planet"; dist: float; point: TGPoint3; normal: TGPoint3 | None; bubble: TGPoint3 | None; tier: str  # "mesh" | "sphere" | "bubble"`
  - `first_blocker(shooter, target, emitter: TGPoint3, aim_unit: TGPoint3, contact_dist: float, ships, planet_instances, ship_instances) -> Blocker | None`
  - `contact_distance(emitter: TGPoint3, impact_point: TGPoint3, bubble_entry: TGPoint3 | None) -> float`: the distance from the emitter to `bubble_entry` if not None, else to `impact_point`.
  - Module-level step context: `begin_step(ships_list, planet_instances) -> None`, `end_step() -> None`, `step_ships() -> list`, `step_planets() -> Mapping` (empty `{}` / `[]` outside a step).

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_beam_blockers.py`. Build ships with the project's existing headless helpers (look at `tests/unit/test_native_k2_dispatch.py` / `test_shield_face_from_hit_point.py` for how a ShipClass gets a position, a set and a seeded `_shield_hull_box`). Fake the mesh trace by monkeypatching `engine.host_io.ray_trace_mesh` with a function that hits a given iid at a given `t`. Shooter at (0,0,0), target at (0,100,0), aim (0,1,0), `contact_dist` 95.
  - `test_ship_in_line_blocks`: an unshielded ship at (0,50,0) whose fake trace hits at t=48. Result `kind == "ship"`, `obj is blocker`, `dist == pytest.approx(48)`, `tier == "mesh"`.
  - `test_graze_sphere_without_mesh_hit_does_not_block`: ship at (3,50,0), radius 5, trace returns None. Result `None`.
  - `test_no_instance_never_blocks`: ship in line, absent from `ship_instances`, shields down. Result `None`.
  - `test_shielded_blocker_blocks_at_bubble`: shields up, hull box seeded. Result `tier == "bubble"`, `bubble` equals `combat.shield_bubble_entry(blocker, emitter, aim, 95)`, `dist` = emitter→bubble.
  - `test_emitter_inside_candidate_bubble_uses_mesh_only`: candidate bubble encloses the emitter, trace None. Result `None`.
  - `test_behind_target_never_blocks`: ship at (0,150,0). Result `None`.
  - `test_shooter_and_target_excluded`: fake trace hits the shooter's and the target's iids at t=1. Result `None`.
  - `test_dead_and_hidden_excluded`: one dead ship and one `SetHidden(1)` ship in line. Result `None`.
  - `test_other_set_never_blocks`: ship in line but in another set. Result `None`.
  - `test_nearest_wins_and_tie_goes_to_earlier`: two blockers at t=40 and t=30. The t=30 one wins. Two at an equal t: the earlier in `ships` wins.
  - `test_planet_blocks_by_sphere_without_instance`: a `Planet` at (0,60,0), radius 5, not in `planet_instances`. Result `kind == "planet"`, `dist == pytest.approx(55)`.
  - `test_planet_blocks_by_mesh_with_instance`: the same planet in `planet_instances`, fake trace t=54. `dist == pytest.approx(54)`, `tier == "mesh"`.
  - `test_rock_blocks`: a `RockClass` in line with a mesh hit. `kind == "ship"`.
  - `test_step_context_empty_outside_step`: `step_ships() == []` and `step_planets() == {}` before `begin_step` and after `end_step`.
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_beam_blockers.py -q`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement `engine/appc/beam_blockers.py`.**
  - Broadphase per candidate, in this exact order (C++ copies it): skip `c is shooter or c is target`; skip a dead one (`hasattr(c, "IsDead") and c.IsDead()`); skip a hidden one (`c.IsHidden()`); skip one in another set (`frames.containing_set(c) is not frames.containing_set(shooter)`); then with `p = c.GetWorldLocation()`, `vx,vy,vz = p - emitter`, `t = vx*ax + vy*ay + vz*az`, `bound = combat.bubble_bound_radius(c)`, reject if `t < -bound or t > contact_dist + bound`, and reject if `(vx*vx + vy*vy + vz*vz) - t*t > bound*bound`.
  - Narrow per surviving ship: if `combat.shields_block(c)`, `b = combat.shield_bubble_entry(c, emitter, aim_unit, contact_dist)`. When b is not None and its distance is `< best`, take `point, normal` = the mesh tier of `combat._resolve_hit_point(ship_instances, c, emitter, aim_unit, contact_dist * 1.5, fallback_point=b)` if its normal is not None, else `(b, None)`, with `tier = "bubble"` and `dist` = |b − emitter|. Otherwise call `_resolve_hit_point(...)` and accept it only when the normal is not None (the mesh tier), with `dist` = |point − emitter| `< best`.
  - Planets (`planet_instances` items plus any planet passed with no instance: iterate `planet_rows`, below): the same set filter, then broadphase with `bound = world_radius(planet) * PLANET_BOUND_SLACK`. Narrow: with an iid, `_resolve_hit_point(planet_instances, planet, ...)` mesh tier only. Without one, `ray_sphere_entry(emitter, aim_unit, contact_dist, planet.GetWorldLocation(), world_radius(planet))`, accepting only a point (not the origin case).
  - `best` starts at `contact_dist`, and the comparison is strict `<`.
  - Planet enumeration helper: `planet_rows(shooter_set, planet_instances) -> list[(planet, iid | None)]`, which is every `Planet` (including `Sun`) object in `shooter_set._objects` order with its iid from `planet_instances`.
- [ ] **Step 4: Run** `uv run pytest tests/unit/test_beam_blockers.py -q`. Expected: PASS.
- [ ] **Step 5: Commit** `engine/appc/beam_blockers.py tests/unit/test_beam_blockers.py`, message `feat(beams): Python reference for the first object in a beam's path`.

### Task 2: Python phaser step uses the blocker

**Files:**
- Modify: `engine/host_loop.py` (`_advance_combat_step` signature and its `cb.phasers` block; `_phaser_step_bank` after the `bubble_entry` computation; the `_advance_combat` call in `run()` ~line 11119; `reset_mission_state` calls `beam_blockers.end_step()`)
- Test: `tests/integration/test_beam_blocking_python.py`

**Interfaces:**
- Consumes: Task 1 `first_blocker`, `contact_distance`, `begin_step`, `end_step`, `step_ships`, `step_planets`.
- Produces: `_advance_combat_step(ships, dt, ship_instances=None, ship_emitters=None, player=None, push_render_data=True, planet_instances=None)`, and the same keyword on `_advance_combat` (it forwards kwargs). `run()` passes `planet_instances=session.planet_instances`.

- [ ] **Step 1: Write the failing tests** in `tests/integration/test_beam_blocking_python.py`. Run with the native switch off: `monkeypatch.setattr(native_combat, "_switch", False)` (follow how existing tests force the Python K2 path; grep `_switch` in `tests/unit/test_native_k2_dispatch.py`). The scene: shooter, a shielded blocker with a seeded hull box (the bubble path works headless), and the target, all in a line in one set. The shooter's phaser bank is firing at the target. Drive `host_loop._advance_combat(ships, dt=1/60, ship_instances=<map>, planet_instances=...)` until one damage pulse lands. Capture `ET_WEAPON_HIT` with a broadcast handler.
  - `test_blocker_takes_pulse_target_takes_none`: the blocker's shield (or hull) total drops, the target's is unchanged, and every captured event has `GetDestination() is blocker` and `GetFiringObject() is shooter`.
  - `test_line_clears_next_pulse_hits_target`: move the blocker out of line (`SetTranslateXYZ`), run to the next pulse, and the target takes it.
  - `test_planet_blocks_silently`: a planet between them (no instance, sphere path). After a pulse there's no damage to anyone and no `ET_WEAPON_HIT`.
  - `test_dead_blocker_stops_blocking_same_step`: two banks on one ship. The first bank's pulse kills the blocker (set its hull condition to 1 first; follow how existing tests kill a ship via `apply_hit`). The second bank's pulse in the same step lands on the target.
  - `test_friendly_fire_counts_pulses_not_frames`: load MissionLib, set a mission whose friendly group contains the blocker, make the shooter the player, call `MissionLib.SetupFriendlyFire()`, and run 60 ticks. `App.g_kUtopiaModule.GetCurrentFriendlyFire()` equals the sum of the pulses' damage (not 60× anything), and `ET_FRIENDLY_FIRE_REPORT` was posted once the warning threshold was crossed (set `SetFriendlyFireWarningPoints` low enough).
  - `test_no_blocker_unchanged`: with no blocker, the target takes the same damage as with `beam_blockers.first_blocker` monkeypatched to always return None. This guards against accidentally changing the unblocked path.
- [ ] **Step 2: Run** `uv run pytest tests/integration/test_beam_blocking_python.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.** In `_advance_combat_step`, around the `cb.phasers` block: `beam_blockers.begin_step(ships_list, planet_instances or {})` before it, and `end_step()` in a `finally`. In `_phaser_step_bank`, after `bubble_entry`, when `aim_unit is not None`:
  - `b = beam_blockers.first_blocker(ship, target, emitter_pos, aim_unit, beam_blockers.contact_distance(emitter_pos, impact_point, bubble_entry), beam_blockers.step_ships(), beam_blockers.step_planets(), ship_instances)`.
  - If `b` is a planet, return (no contact).
  - If it's a ship, rebind `target, dist, impact_point, impact_normal, bubble_entry = b.obj, b.dist, b.point, b.normal, b.bubble` before `_phaser_contact`.
  - `_phaser_contact` itself is unchanged; its `shields_block` default evaluates the new target.
- [ ] **Step 4: Run** the new file plus `tests/unit/test_manual_aim.py tests/unit/test_weapons_disabled_blocks_fire.py`. Expected: PASS.
- [ ] **Step 5: Commit** `engine/host_loop.py tests/integration/test_beam_blocking_python.py`, message `feat(beams): phasers stop on the first object in their path (Python step)`.

### Task 3: Mirror `_hidden`

**Files:**
- Modify: `engine/appc/objects.py` (`_hidden` becomes the native-descriptor kind other mirrored ObjectRow fields use; follow `_dead`), `native/src/combat/include/dauntless/combat/mirror.h` (`ObjectRow::_hidden`, the field list near line 49), `native/src/combat/src/mirror.cc`, the binding's field table in `native/src/host/host_bindings.cc` (follow `_dead` end to end)
- Test: `tests/unit/test_native_combat_k2_mirror.py` (add a case)

**Interfaces:**
- Produces: `ObjectRow::_hidden` (`int64_t`, 0/1), kept current by `SetHidden`.

- [ ] **Step 1: Write the failing test** `test_hidden_is_mirrored`: register a ship, call `SetHidden(1)`, and the mirror's row reads `_hidden == 1` through the same accessor the existing `_dead` mirror test uses. Then `SetHidden(0)` reads 0.
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_native_combat_k2_mirror.py -q -k hidden`. Expected: FAIL.
- [ ] **Step 3: Implement**, mirroring `_dead` exactly. Rebuild `cmake --build build -j`.
- [ ] **Step 4: Run** the test file. Expected: PASS. Also run `tests/unit/test_native_k2_override_guard.py`.
- [ ] **Step 5: Commit**, message `feat(native-combat): mirror ObjectClass._hidden`.

### Task 4: C++ resolver `first_blocker`

**Files:**
- Modify: `native/src/combat/include/dauntless/combat/beam_trace.h`, `native/src/combat/src/beam_trace.cc` (split out a row-free core, below)
- Create: `native/src/combat/include/dauntless/combat/beam_block.h`, `native/src/combat/src/beam_block.cc`, add to `native/src/combat/CMakeLists.txt`
- Test: `native/tests/combat/beam_block_test.cc` (register it the way the neighbouring `beam_*` tests are)

**Interfaces:**
- Consumes: `resolve_hit_point`, `shields_block`, `shield_bubble_entry` (`beam_geometry.h`), `bubble_bound_radius` (`projectile_geometry.h`), `world_radius`, `ray_sphere_entry`, `ObjectRow::_hidden` (Task 3).
- Produces:
  ```cpp
  // beam_trace.h: the mesh trace on an iid with no mirror row behind it.
  std::optional<std::pair<Vec3, Vec3>> trace_instance_point(
      const TraceHooks& hooks, InstanceId iid, const Vec3& origin,
      const Vec3& dir, double max_dist, const std::optional<Vec3>& view_offset);

  // beam_block.h
  constexpr double kPlanetBoundSlack = 1.02;   // = beam_blockers.PLANET_BOUND_SLACK
  struct BeamPlanet { int64_t set = -1; Vec3 centre{}; double radius = 0.0;
                      std::optional<InstanceId> iid; bool iid_bad = false; };
  struct BeamBlockInputs {
      const Mirror& m; const TraceHooks& hooks;
      const std::unordered_map<int64_t, K2Context::Iid>& iids;  // or a local twin of Iid
      const std::unordered_map<int64_t, std::optional<Vec3>>& view_offsets;
      bool npc_shields_off; int64_t player;
      const std::vector<int64_t>& ships; const std::vector<BeamPlanet>& planets; };
  struct BeamBlocker { enum class Kind { Ship, Planet } kind; int64_t handle = -1;  // -1 for a planet
                       double dist; Vec3 point; std::optional<Vec3> normal;
                       std::optional<Vec3> bubble; enum class Tier { Mesh, Sphere, Bubble } tier; };
  // nullopt: nothing blocks. Throws NeedPython (a std::runtime_error subclass
  // declared here) when a candidate needs an answer only Python has: a
  // shields/bubble read the native code would ASK for, or a candidate's set
  // with no view-offset entry while it has an instance.
  std::optional<BeamBlocker> first_blocker(const BeamBlockInputs& in,
      int64_t shooter, int64_t target, const Vec3& emitter,
      const Vec3& aim_unit, double contact_dist);
  ```
  If `K2Context::Iid` would make `beam_block.h` include `k2_beams.h` (a cycle), move `Iid` into `beam_trace.h` as `InstanceRef` and alias it from `K2Context`.

- [ ] **Step 1: Write the failing gtests** in `beam_block_test.cc`. Build a `Mirror` with rows the way `beam_geometry_test`/`k2` tests do. Install fake `TraceHooks` whose `trace` hits a chosen iid at a chosen t. Port Task 1's cases one for one: `ShipInLineBlocks`, `GrazeDoesNotBlock`, `NoInstanceNeverBlocks`, `ShieldedBlocksAtBubble`, `EmitterInsideBubbleMeshOnly`, `BehindTargetNever`, `ShooterAndTargetExcluded`, `DeadAndHiddenExcluded`, `OtherSetNever`, `NearestWinsTieEarlier`, `PlanetSphereNoInstance`, `PlanetMesh`. Use the same numbers as Task 1, and EXPECT_EQ on doubles where Task 1's arithmetic is exact.
- [ ] **Step 2: Build and run** `cmake --build build -j && ctest --test-dir build -R BeamBlock --output-on-failure`. Expected: FAIL (it doesn't compile, or the tests fail).
- [ ] **Step 3: Implement** `trace_instance_point` by lifting `resolve_hit_point`'s mesh branch, so `resolve_hit_point` calls it (no behaviour change). Then implement `first_blocker` as a statement-by-statement port of Task 1, with the same candidate order and the same broadphase expression order. `shields_block` for a candidate is beam_feed's `feed_shields_block` rule: no real `GetShields` → false. If it isn't a ShipClass, or the native shields read can't answer → throw `NeedPython`.
- [ ] **Step 4: Run** `ctest --test-dir build -R "BeamBlock|BeamTrace|K2" --output-on-failure`. Expected: PASS (the existing `resolve_hit_point` tests still pass).
- [ ] **Step 5: Commit**, message `feat(native-combat): first_blocker, the C++ port of the beam blocker`.

### Task 5: K2 kernel blocks, with a `blocker` ASK

**Files:**
- Modify: `native/src/combat/include/dauntless/combat/k2_beams.h` (header contract: a new section "THE BLOCKER"; `K2Query::blocker`; `K2Answer` gains `int64_t handle = -1; int32_t blocker_kind = 0 /* 0 none, 1 ship, 2 planet */; double dist = 0.0; std::optional<Vec3> bubble;`; `K2Context` gains `std::vector<BeamPlanet> planets;`), `native/src/combat/src/k2_beams.cc` (states `BLOCK`, `BLOCK_ANSWER` after `BUBBLE`/`BUBBLE_ANSWER`, before the contact), `native/src/host/host_bindings.cc` (context `planets` parse; ASK `blocker` record args and answer parse), `engine/appc/native_combat.py` (`_K2Context` sends `planets`; `_k2_answer` handles `"blocker"`; `k2_phasers` takes `planet_instances`), `engine/host_loop.py` (the `cb.phasers` block passes `planet_instances` to `k2_phasers`), `docs/reference/engine/native-combat/k2-beams-map.md`
- Test: `tests/unit/test_native_k2_blocker.py`

**Interfaces:**
- Consumes: Task 4 `first_blocker`, `BeamPlanet`, `NeedPython`. Task 1 `first_blocker` (the ASK's answer), `planet_rows`.
- Produces:
  - `native_combat.k2_phasers(ships, dt, ship_instances, planet_instances=None) -> bool`.
  - `native_combat._k2_planet_rows(ships, planet_instances) -> list[tuple]`: one `(set_handle, cx, cy, cz, radius, iid_or_None)` per planet in every set any of `ships` is in, in `beam_blockers.planet_rows` order.
  - ASK `blocker` record: `(ASK, "blocker", ship, target, emitter_xyz, aim_xyz, contact_dist, writes)`. The answer is `None`, `("planet", dist)` or `("ship", handle, dist, point_xyz, normal_xyz|None, bubble_xyz|None, tier)`.
- Walk semantics, at `BLOCK` (only when `aim_unit` is known):
  - `contact_dist` = |bubble − emitter| if the bubble is set, else |impact − emitter|.
  - Call `first_blocker`. `NeedPython` → ASK `blocker`.
  - Ship → replace the contact's `target` with the blocker handle, and `dist`, `impact`, `normal`, `tier` (the CONTACT/rest tier string becomes `"mesh"` when the blocker has a normal, else `"sphere"`: the string only tells Python how to rebuild the point's identity, and a blocker's point is always a new point, never the fallback or the origin), `bubble` and `shields_block` (re-evaluated for the blocker, native or ASK `shields_block`) with the blocker's.
  - Planet → no contact, no rest, no pulse (the dwell taken this tick is dropped). Go to BANK_NEXT.
  - The damage pulse, the rest and the CONTACT record then run unchanged on the substituted values. The pulse's `dmg_target_representable` check runs on the blocker.
  - Pinning: CONTACT already pins its `target` handle, which is now the blocker.

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_native_k2_blocker.py`, modelled on `tests/unit/test_native_k2_dispatch.py`'s fixtures. Headless, the native trace never hits, so use shielded blockers with seeded hull boxes and planets with no instance. Each test runs the same seeded scene twice, native (`_switch` True) and Python (`_switch` False), and compares, with `==`, the ordered list of `(event destination id, firing object id, damage)` from captured `ET_WEAPON_HIT`s plus every ship's shield and hull totals:
  - `test_shielded_blocker_native_equals_python`
  - `test_planet_blocker_native_equals_python`
  - `test_two_banks_one_blocker_native_equals_python`: two shooters' beams cross one blocker in the same step.
  - `test_blocker_ask_path`: make one candidate unanswerable natively (a non-ShipClass object with a real `GetShields`, the case `feed_shields_block` skips). Native still equals Python, and `native_combat.counts()` shows the `blocker` ASK was taken (follow how the dispatch tests read ASK counts).
  - `test_no_blocker_records_unchanged`: with no blocker in the line, the record stream equals the pre-change stream (compare against `first_blocker` monkeypatched in the binding-free sense: run once with the blocker ship moved far off the line).
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_native_k2_blocker.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** per the walk semantics above. Update the k2_beams.h contract comment (a THE BLOCKER section, the ASK list, the RECORDS answer layout) and k2-beams-map.md in the same commit.
- [ ] **Step 4: Run** `cmake --build build -j`, then `uv run pytest tests/unit/test_native_k2_blocker.py tests/unit/test_native_k2_dispatch.py tests/unit/test_native_k2_bindings.py tests/unit/test_native_k2_override_guard.py tests/integration/test_beam_blocking_python.py -q` and `ctest --test-dir build -R "K2|BeamBlock" --output-on-failure`. Expected: PASS.
- [ ] **Step 5: Run the differential** `uv run pytest tests/integration/test_native_combat_step_differential.py -q`. Expected: PASS (bit-identical native vs Python with whatever lines the combat_stress ships happen to form).
- [ ] **Step 6: Commit**, message `feat(native-combat): K2 phasers stop on the first object in their path`.

### Task 6: The drawn beam ends on the blocker

**Files:**
- Modify: `native/src/combat/include/dauntless/combat/beam_feed.h` (`BeamFeedCtx` gains `std::vector<BeamPlanet> planets;`), `native/src/combat/src/beam_feed.cc` (`beam_endpoint` gains a `ship` parameter and the ship list; after it computes today's endpoint, it calls `first_blocker` with `contact_dist` = |endpoint − emitter| and returns the blocker's bubble if set, else its point; `NeedPython` → keep today's endpoint and count a new `BeamSkip::Blocker`), `native/src/host/host_bindings.cc` (feed ctx `planets`), `engine/appc/native_combat.py` (`beam_feed` sends `_k2_planet_rows`; `_BEAM_SKIPS` gains `"blocker"` at the matching position), `engine/host_loop.py` (`_push_combat_render_data` passes `session.planet_instances` through to the feed)
- Test: `native/tests/combat/beam_feed_test.cc` (or the existing feed test file), `tests/unit/test_beam_feed_blocker.py`

**Interfaces:**
- Consumes: Task 4 `first_blocker`, Task 5 `_k2_planet_rows`.
- Produces: `native_combat.beam_feed(..., planet_instances=None)` (add the keyword to whatever its current signature is).

- [ ] **Step 1: Write the failing tests.** gtest `BeamFeed.EndsOnShieldedBlocker` and `BeamFeed.EndsOnPlanet`: the outer descriptor's end equals the blocker's bubble entry / planet sphere entry (render offset zero), to 1e-9. Python `test_beam_feed_blocker.py::test_feed_end_matches_damage_contact`: in the Task 2 scene, the beam feed's end point for the blocked bank equals the `impact`/`bubble` the Python step passed to `_phaser_contact` (spy on it), to 1e-6.
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement** as described in Files.
- [ ] **Step 4: Run** the new tests plus the existing beam feed tests (`ctest -R BeamFeed`, `uv run pytest tests/unit/test_beam_feed_blocker.py tests/unit/test_native_beam_geometry.py -q`). Expected: PASS.
- [ ] **Step 5: Commit**, message `feat(beams): the drawn beam ends on whatever blocks it`.

### Task 7: Documentation and hand-off

**Files:**
- Modify: `CLAUDE.md` (a new table row, "Beam blocking", after the Native combat row), `docs/superpowers/specs/2026-11-11-beam-blocking-design.md` (Status line: built on `feat/beam-blocking`, not live-verified; record this plan's "Decisions" list under a new §10 "Decisions made while planning")
- Test: `tests/docs` (the doc-consistency guards)

- [ ] **Step 1: Write the CLAUDE.md row.** It covers the paths (`engine/appc/beam_blockers.py`, `native/src/combat/src/beam_block.cc`, the K2 BLOCK state, the beam feed), the rule (first ship/rock/planet; planets stop silently; hidden, dead and other-set objects never block; tractors unchanged), ⚠️ "Python reference and C++ port must change together", ⚠️ the `blocker` ASK, and "⚠️ Not live-verified".
- [ ] **Step 2: Run** `uv run pytest tests/docs tests/unit/test_path_indirection.py tests/unit/test_install_write_guard.py tests/unit/test_gate_tiers.py -q`. Expected: PASS.
- [ ] **Step 3: Commit**, message `docs(beams): CLAUDE.md row and spec status for beam blocking`.
- [ ] **Step 4: Hand Mark the live check and perf capture** (do not run them). Live: `cd .claude/worktrees/beam-blocking && ./build/dauntless --developer`, then Quick Battle: fly through a beam between two AI ships, fire past an ally, fire at a ship behind a planet. Perf: the frame-profiler capture on `DAUNTLESS_MISSION=engine.dev_missions.combat_stress`, before and after, comparing the `cb.phasers` and beam-feed rows, to record as a signal in `docs/reference/engine/perf-register.md`.
