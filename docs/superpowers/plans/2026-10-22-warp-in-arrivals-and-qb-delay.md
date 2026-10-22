# Warp-in Arrivals + Quick Battle Warp-in Delay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make BC's own warp-in routine (`loadspacehelper.CreateShip(..., placement, 1)`) real — exit point, 2 s slide-in, procedural world-space flash — so ~103 campaign warp-ins and NPC set-to-set arrivals/departures get it, and give Quick Battle groups a warp-in delay whose late ships arrive through the same routine, count toward the win, get AI on arrival and are called out by the crew.

**Architecture:** Python owns all state on game time inside `GameLoop.tick` (warp-state ticks, the dewarp drive, flash records), so host and headless behave alike. A new native `WarpInFlashPass` draws flash records fed per frame through the combat render feed, with a CPU twin of its shape function pinned by ctest. Quick Battle splits the plan into "now" and "late" orders; late orders are pre-counted, scheduled on BC's timer manager, and spawned like E5M4's runtime-placement reinforcements.

**Tech Stack:** Python 3.11 (engine/, pytest), C++17 + OpenGL 4.1 / GLSL 410 (native/renderer, gtest/ctest), pybind11 host bindings, CEF HTML/JS (Quick Battle panel).

**Spec:** `docs/superpowers/specs/2026-10-22-warp-in-arrivals-and-qb-delay-design.md` — read it alongside this plan; section refs (§) below point into it.

## Global Constraints

- ⛔ Never run destructive git (`checkout -- / restore / stash / clean / reset --hard / add -A / add .`). Stage with explicit pathspecs. Tell every subagent the same.
- ⛔ Focused tests only: run the test files named in your task. Never a whole suite (`tests`, `tests/unit`, `tests/ui`), never `scripts/check_tests.sh` (the gate runs only on Mark's word at a main merge). An empty file list runs the whole suite — always name files.
- ⛔ Never launch the game (`./build/dauntless`) without asking Mark first.
- Build only from the worktree root: `cmake --build build -j --target dauntless renderer_tests` (a host-binding change needs the `dauntless` target). Never `cmake` inside `native/`, never change `CMAKE_BUILD_TYPE` (Debug).
- Paths: never spell `game`/`sdk` as a path segment; resolve via `engine.paths`. Never capture a path at import.
- Stub surface: probe with `engine.core.ids.implements(obj, name)`, never `hasattr`; never decide surface existence with a `def <Name>(` grep.
- GLSL: `#version 410 core`; no `#include` — the shape function is duplicated in GLSL with "MUST match" comments. Shader errors surface only at runtime.
- Units are GU end-to-end (`*_gu`, `*_gups`); never `*_m`.
- Rotation convention: column-vector, right-handed; forward = `GetWorldRotation().GetCol(1)`, up = `GetCol(2)`.
- No game-state mutation in the render feed builders.
- Quick Battle with no delays set must stay byte-identical (same spawn, placement, AI order).
- Stock particle output stays byte-identical (`tests/unit/test_stock_particle_output_unchanged.py`); the flash does not use the sprite library or any texture.
- The binding name must not collide with the existing screen-space `set_warp_flash_intensity`; the new surface is named **warp-in flash** everywhere (`warp_in_flash`, `WarpInFlash`).

## Review Focus

1. **Every group delayed** (no ship present at start) — the battle must arm (`bWonOrLost` 0), not be won instantly, and spawn everything later. `generate_ships` currently returns early when nothing was created. → Task 9 `test_all_groups_late_battle_arms_and_waits`.
2. **Battle ended or restarted before a timer fires** — nothing spawns into the dead or the new battle; the new battle's own arrivals still fire on time. → Task 9 `test_restart_before_arrival_spawns_only_new_battle`.
3. **Arriving ship destroyed mid-slide** (it is targetable) — the drive stops touching it, no exception, and the win count stays right. → Task 2 `test_dewarp_drive_releases_a_dead_ship`.
4. **Pause during slide or flash** — both freeze (zero game time). → Task 2 `test_dewarp_drive_frozen_by_zero_dt`, Task 3 `test_flash_does_not_age_at_zero_dt`.
5. **Typed delay values at the edges** (`0`, `600`, `-1`, `2.5`, `""`, `"abc"`) — accepted/reverted exactly as §6.4 says, in scenario, panel and presets. → Task 7 `test_warp_in_validation`, Task 8 `test_draft_warp_in_values`.

---

### Task 0: Worktree runtime setup (no code)

**Files:** none tracked.

- [ ] **Step 1:** From the worktree root `/Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/qb-warp-in`:
```bash
cp /Users/mward/Documents/Projects/bc_dauntless/settings.json .
mkdir -p mods && cp -Rc /Users/mward/Documents/Projects/bc_dauntless/mods/. mods/
uv sync --extra dev
U=~/.local/share/uv/python/cpython-3.11.15-macos-aarch64-none
cmake -B build -S . -DCMAKE_BUILD_TYPE=Debug -DPython3_EXECUTABLE=$PWD/.venv/bin/python3 -DPython3_ROOT_DIR=$U -DPython3_FIND_FRAMEWORK=NEVER -DPython3_FIND_STRATEGY=LOCATION
cmake --build build -j
```
- [ ] **Step 2:** Verify: `grep _Python3_INCLUDE_DIR build/CMakeCache.txt` shows the uv 3.11 path; `uv run pytest tests/unit/test_warp_engine_subsystem.py -q` passes.

---

### Task 1: Warp engine placement, exit point, region module, dials

**Files:**
- Create: `engine/appc/warp_in_dials.py`
- Modify: `engine/appc/subsystems.py` (WarpEngineSubsystem, ~1680-1780)
- Modify: `engine/appc/sets.py` (`SetRegionModule` :176; add `GetRegionModule`)
- Test: `tests/unit/test_warp_engine_subsystem.py`, `tests/unit/test_warp_in_dials.py` (create), `tests/unit/test_set_region_module.py` (create)

**Interfaces:**
- Produces:
  - `warp_in_dials.DEFAULTS: dict` = `{"slide_radii": 10.0, "core_radii": 1.5, "streak_radii": 8.0, "ring_radii": 3.0, "intensity": 4.0, "life_frac": 0.5, "tint_r": 0.75, "tint_g": 0.85, "tint_b": 1.0}`; `DIAL_ORDER = tuple(DEFAULTS)`; `get(name) -> float`; `current() -> dict`; `reset()`; `register()` → `dev_dial_groups.register_group("warp in", DIAL_ORDER, current, _step)`. Steps: radii 0.5, intensity 0.5, life_frac 0.05, tint 0.05; minimum 0 for all, tint max 1.
  - `WarpEngineSubsystem.SetPlacement(placement) -> None`, `GetPlacement() -> placement | None`, `GetWarpExitLocation() -> TGPoint3`, `GetWarpExitRotation() -> TGMatrix3`.
  - `SetClass.SetRegionModule(name: str) -> None`, `SetClass.GetRegionModule() -> str | None`.

- [ ] **Step 1: Write failing tests**
  - `test_warp_in_dials.py`: `test_defaults_and_order` (`DIAL_ORDER == tuple(DEFAULTS)`, `get("slide_radii") == 10.0`); `test_step_clamps_at_zero` (stepping `core_radii` down 10× ends at 0.0); `test_reset_restores_defaults`.
  - `test_warp_engine_subsystem.py`:
    - `test_placement_round_trip`: `SetPlacement(p)`; `GetPlacement() is p`; `SetPlacement(None)` clears.
    - `test_exit_point_is_behind_the_placement`: ship radius 2.0 (stub or real ship with a known radius), placement at (100, 0, 0) with identity rotation (forward = +Y): `GetWarpExitLocation()` == (100, −20, 0) (slide_radii 10 × radius 2) within 1e-5; `GetWarpExitRotation()` columns equal the placement's.
    - `test_exit_point_without_placement_is_the_ship`: returns the parent ship's world location and rotation.
    - `test_exit_methods_are_real_surface`: `implements(sub, "SetPlacement")`, `"GetWarpExitLocation"`, `"GetWarpExitRotation"` all true.
  - `test_set_region_module.py`: `test_round_trip` (`SetRegionModule("Systems.Vesuvi.Vesuvi4")` → `GetRegionModule()` returns it); `test_default_is_none`.
- [ ] **Step 2:** `uv run pytest tests/unit/test_warp_engine_subsystem.py tests/unit/test_warp_in_dials.py tests/unit/test_set_region_module.py -q` → FAIL.
- [ ] **Step 3: Implement.** Exit location = placement world location − placement forward (`GetCol(1)`) × `warp_in_dials.get("slide_radii")` × parent ship `GetRadius()` (read at use). Parent ship via the subsystem's existing `GetParentShip()` (subsystems.py:616). `SetRegionModule` stores `_region_module`; `GetRegionModule` returns it (defined method, so `SetClass.__getattr__` no longer stubs it).
- [ ] **Step 4:** Re-run the three files → PASS.
- [ ] **Step 5: Commit** `feat(warp-in): warp engine placement + exit point, SetClass region module, warp-in dials`.

---

### Task 2: Dewarp drive, hold heading + fire, warp ticks on game time

**Files:**
- Modify: `engine/appc/subsystems.py` (WarpEngineSubsystem dewarp drive)
- Modify: `engine/appc/warp_state.py` (`tick_warp_states` :76, add `is_arriving`)
- Modify: `engine/core/loop.py` (`GameLoop.tick`, call before `tick_all_ship_motion` :85)
- Modify: `engine/host_loop.py:12367` (remove the per-frame `tick_warp_states(_player_dt)` call; keep `sync_flythrough` where it is)
- Modify: `engine/appc/ship_motion.py` (`_step_ship_motion` early-out beside `_insystem_warp_transit` :205)
- Modify: `engine/appc/weapon_subsystems.py` (`_cloak_blocks_fire` :960 sites :1346, :2290; `Weapon.FireDumb` :1059)
- Test: `tests/unit/test_dewarp_drive.py` (create), `tests/host/test_warp_state_host_wiring.py`, `tests/host/test_scene_reconcile_ordering.py`, `tests/unit/test_warp_state.py`

**Interfaces:**
- Consumes: Task 1 `GetPlacement`, `GetWarpExitLocation/Rotation`.
- Produces:
  - `WarpEngineSubsystem.DEWARP_DRIVE_SECONDS = 2.0` (alias of `DEFAULT_DEWARP_SECONDS`); `is_dewarp_driving() -> bool`; `step_dewarp_drive(dt: float) -> None` (moves the parent ship).
  - `warp_state.is_arriving(ship) -> bool` — true while the ship's warp engine is driving.
  - `weapon_subsystems._dewarp_blocks_fire(weapon_system) -> bool`.

- [ ] **Step 1: Write failing tests** in `tests/unit/test_dewarp_drive.py` (fixture: ship from `test_warp_state._ship_with_warp` pattern, in a set, placement at (100,0,0) identity, radius 2):
  - `test_initiate_with_placement_starts_drive_at_exit_point`: `SetPlacement(p)`, `SetWarpState(WES_WARPING)`, `TransitionToState(WES_DEWARP_INITIATED)` → ship world location == exit point (100,−20,0); `is_dewarp_driving()`.
  - `test_drive_lands_exactly_on_placement_after_2s`: tick `warp_state.tick_warp_states(1/60)` 120×; location == (100,0,0) within 1e-4; velocity == 0; rotation == placement rotation; `not is_dewarp_driving()`; `GetPlacement() is None`.
  - `test_drive_is_monotonic`: the distance to the placement never increases across ticks.
  - `test_later_stage_calls_do_not_restart_drive`: at 1.5 s call `TransitionToState(WES_DEWARP_ENDING)`; drive still lands at 2.0 s.
  - `test_ai_setpoints_cannot_turn_or_move_during_drive`: set `_target_angular_velocity_setpoint` and `SetSpeed(5)` mid-drive, run `ship_motion.tick_all_ship_motion(1/60)` → rotation unchanged, position on the drive path.
  - `test_fire_held_during_drive_then_released`: `WeaponSystem.StartFiring(target)` on the ship's phaser system during the drive does not fire (no firing state set); after landing it fires. Also `Weapon.FireDumb` is a no-op during the drive.
  - `test_drive_start_silences_weapons`: a weapon system already firing when the drive starts is stopped (mirror `warp._silence_ship_weapons(ship)` :825).
  - `test_dewarp_drive_releases_a_dead_ship`: mark the ship dead mid-drive → next tick no position write, `is_dewarp_driving()` false, no exception.
  - `test_dewarp_drive_frozen_by_zero_dt`: `tick_warp_states(0.0)` ×10 leaves position unchanged.
  - `test_no_placement_keeps_old_behaviour`: dewarp without `SetPlacement` → no drive, state lands on `WES_NOT_WARPING` after 2.0 s as before.
  - `test_gameloop_ticks_warp_states`: `GameLoop().tick()` ×120 completes a pending dewarp (headless path).
- [ ] **Step 2:** Run `uv run pytest tests/unit/test_dewarp_drive.py -q` → FAIL.
- [ ] **Step 3: Implement.**
  - `TransitionToState(WES_DEWARP_INITIATED)` with a placement: record from = exit location, to = placement location, rotation = placement rotation, elapsed 0; snap the ship to `from` with that rotation, velocity 0; silence weapons. Other dewarp stages leave an active drive alone.
  - `step_dewarp_drive(dt)`: elapsed += dt; position = lerp(from, to, smoothstep(0, 1, elapsed/2.0)); velocity 0; angular velocity 0 (`ship._current_angular_velocity`); at elapsed ≥ 2.0 snap to `to`, clear drive and placement. If the parent ship is dead/dying or not in a set: clear without writing.
  - `tick_warp_states(dt)` calls `step_dewarp_drive` then `tick_transition` per ship.
  - `GameLoop.tick`: `warp_state.tick_warp_states(TICK_DELTA)` immediately before `tick_all_ship_motion`. Remove the host_loop.py:12367 call; update `test_warp_state_host_wiring.py` / `test_scene_reconcile_ordering.py` to pin the new home (warp ticks inside `GameLoop.tick`, before ship motion) and keep their before-collisions intent.
  - `_step_ship_motion`: `if warp_state.is_arriving(ship): return` beside the `_insystem_warp_transit` gate.
  - `_dewarp_blocks_fire` checked next to `_cloak_blocks_fire` at both `StartFiring` sites and at the top of `Weapon.FireDumb`.
- [ ] **Step 4:** Run `uv run pytest tests/unit/test_dewarp_drive.py tests/unit/test_warp_state.py tests/unit/test_warp_engine_subsystem.py tests/unit/test_warp_state_sequence.py tests/host/test_warp_state_host_wiring.py tests/host/test_scene_reconcile_ordering.py -q` → PASS.
- [ ] **Step 5: Commit** `feat(warp-in): dewarp slide on game time; arriving ships hold heading and fire`.

---

### Task 3: Warp-in flash records + App surface

**Files:**
- Create: `engine/appc/warp_in_flash.py`
- Modify: `App.py` (explicit import block near :279; remove nothing)
- Modify: `engine/core/loop.py` (advance flashes beside the warp ticks)
- Modify: `engine/host_loop.py` (mission reset beside `shockwaves.reset()` :7629)
- Modify: `tests/conftest.py` (`_reset_leakable_engine_globals`: `warp_in_flash.reset()`, `warp_in_dials.reset()`)
- Test: `tests/unit/test_warp_in_flash.py` (create)

**Interfaces:**
- Consumes: Task 1 dials (`life_frac`), `WarpEngineSubsystem_GetWarpEffectTime()`.
- Produces:
  - `WarpInFlash` record: `set_name: str`, `center: tuple[float,float,float]` (set-local GU), `forward: tuple` (unit), `radius: float`, `age: float`, `lifetime: float`.
  - `spawn(pSet, center, forward, radius, lifetime=None) -> WarpInFlash`; `advance(dt)` (ages, retires when `age >= lifetime`); `active() -> list[WarpInFlash]`; `spawned_count() -> int` (monotonic, for tests); `reset()`.
  - `WarpFlash_Create(pShip, fTime=None)` and `WarpFlash_CreateWithoutShip(pSet, pLocation, pRotation, fRadius, fTime=None)` — App-level; forward from `pRotation.GetCol(1)` / the ship's world rotation; default lifetime `GetWarpEffectTime() * life_frac`. `WarpFlash_Create` with a ship not in a set returns None and spawns nothing.

- [ ] **Step 1: Write failing tests** (`test_warp_in_flash.py`):
  - `test_create_without_ship_records_flash` — center/forward/radius copied; lifetime 1.5 (3.0 × 0.5).
  - `test_explicit_time_wins`.
  - `test_create_with_ship_uses_ship_pose`.
  - `test_flash_retires_after_lifetime` — `advance(1.0)` keeps it, `advance(0.6)` retires it.
  - `test_flash_does_not_age_at_zero_dt`.
  - `test_app_exports_are_real` — `App.WarpFlash_Create` / `App.WarpFlash_CreateWithoutShip` are these functions (not `_NamedStub`).
  - `test_gameloop_advances_flashes` — `GameLoop().tick()` ×90 retires a 1.5 s flash.
  - `test_sdk_warp_flash_enter_set_spawns` — with a set whose `SetRegionModule` names a fake module in `sys.modules` whose `GetSet()` returns it, call SDK `Actions.EffectScriptActions.WarpFlashEnterSet(None, name, ship_id)` → `spawned_count()` +1 at the exit point.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3: Implement** per Interfaces; flashes are plain records (not set objects, not targetable).
- [ ] **Step 4:** `uv run pytest tests/unit/test_warp_in_flash.py tests/unit/test_conftest_leak_resets.py -q` → PASS.
- [ ] **Step 5: Commit** `feat(warp-in): WarpFlash_Create / WarpFlash_CreateWithoutShip as game-time flash records`.

---

### Task 4: NPC set-to-set arrivals and departures in the player's set

**Files:**
- Modify: `engine/appc/warp.py` (`_PlacePlayerAction` :777-822, `_WarpDepartAction` :868)
- Test: `tests/unit/test_warp_state_sequence.py` (add cases)

**Interfaces:**
- Consumes: Task 1 `SetPlacement`; Task 2 dewarp drive; Task 3 `spawn`.
- Produces: nothing new.

- [ ] **Step 1: Write failing tests** (reuse the file's `_isolate` + `_player_in_set` fixtures):
  - `test_npc_arriving_in_player_set_flashes_and_slides` — NPC `WarpSequence_Create` into the player's set: after the place action, `spawned_count()` +1 at the exit point and the NPC is dewarp-driving toward its placement.
  - `test_npc_arriving_elsewhere_is_instant` — destination is not the player's set: no flash, no drive, placed instantly (today's behaviour).
  - `test_npc_departing_player_set_flashes` — `_WarpDepartAction` for an NPC in the player's set: one flash at its position with its forward, before it leaves the set.
  - `test_player_warp_unchanged` — the player's own warp spawns no warp-in flash.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3: Implement.** "Player's set" = `App.Game_GetCurrentPlayer().GetContainingSet()` read at use; gate on `not _is_current_player(ship)`. Arrival: after placing, `SetPlacement(App.PlacementObject_GetObject(dest, placement))` + `SetWarpState(WES_WARPING)` + `TransitionToState(WES_DEWARP_INITIATED)` (drive starts from the exit point) and `WarpFlash_CreateWithoutShip` at the exit point. Departure: `WarpFlash_Create(ship)` before removal from the source set. In-system NPC travel (dash/`_insystem_warp_transit`) is untouched.
- [ ] **Step 4:** `uv run pytest tests/unit/test_warp_state_sequence.py tests/unit/test_dewarp_drive.py -q` → PASS.
- [ ] **Step 5: Commit** `feat(warp-in): NPC set-to-set arrivals slide in and flash; departures flash`.

---

### Task 5: Native warp-in flash pass

**Files:**
- Create: `native/src/renderer/include/renderer/warp_in_flash_shape.h`, `native/src/renderer/warp_in_flash_shape.cc`
- Create: `native/src/renderer/include/renderer/warp_in_flash_pass.h`, `native/src/renderer/warp_in_flash_pass.cc`
- Create: `native/src/renderer/shaders/warp_in_flash.vert`, `native/src/renderer/shaders/warp_in_flash.frag`
- Modify: `native/src/renderer/include/renderer/frame.h` (descriptor beside `ShockwaveDescriptor` :176), `native/src/renderer/CMakeLists.txt` (`embed_shader` ×2, sources), `pipeline.h/.cc` (shader accessor)
- Modify: `native/src/host/host_bindings.cc` (globals ~:414, init ~:1145, shutdown ~:1238, `reset_frame_state` ~:990, draw in `render_space_vfx` right after shockwave ~:1886, `m.def`s ~:6120)
- Modify: `engine/host_io.py` (wrappers + `_REQUIRED_BINDINGS`), `engine/host_loop.py` (`_build_warp_in_flash_render_data` beside `_build_shockwave_render_data` :1883; push in `_push_combat_render_data` :1277; dial push per frame beside running-light dials :836; register dials in the dev block :10906)
- Test: `native/tests/renderer/warp_in_flash_shape_test.cc`, `native/tests/renderer/warp_in_flash_pass_test.cc` (register in `native/tests/renderer/CMakeLists.txt`), `tests/unit/test_host_io_binding_manifest.py` (existing), `tests/unit/test_warp_in_flash_feed.py` (create)

**Interfaces:**
- Consumes: Task 3 `active()` records; Task 1 dials.
- Produces:
  - C++: `struct WarpInFlashParams { float core_radii = 1.5f; float streak_radii = 8.0f; float ring_radii = 3.0f; float intensity = 4.0f; glm::vec3 tint{0.75f, 0.85f, 1.0f}; };`
  - `float warp_in_core(float r, float t, const WarpInFlashParams&)`, `float warp_in_ring(float r, float t, const WarpInFlashParams&)`, `float warp_in_streak(float along, float across, float t, const WarpInFlashParams&)` — distances in units of the flash radius, `t = age/lifetime`; all return 0 for `t >= 1`.
  - `struct WarpInFlashDescriptor { glm::vec3 world_center; glm::vec3 forward; float radius; float age; float lifetime; };`
  - `class WarpInFlashPass { void render(const scenegraph::Camera&, const std::vector<WarpInFlashDescriptor>&, const WarpInFlashParams&, Pipeline&); }`
  - Bindings: `set_warp_in_flashes(list[dict{world_center, forward, radius, age, lifetime}])` (replaces the list), `set_warp_in_flash_params(dict{core_radii, streak_radii, ring_radii, intensity, tint})`.
  - Python: `host_io.set_warp_in_flashes(items)`, `host_io.set_warp_in_flash_params(params)`.

Shape (header constants, `inline constexpr`, mirrored by name in the frag): `kCoreRise = 0.08`, `kCoreFalloff = 3.0`, `kRingRise = 0.05`, `kRingBand = 0.12`, `kStreakEnd = 0.9`, `kStreakThickness = 0.08`.
```
core(r,t)   = a·exp(−kCoreFalloff·(r/w)²),  a = smoothstep(0,kCoreRise,t)·(1−smoothstep(kCoreRise,1,t)),  w = core_radii·(0.4+0.6a)
ring(r,t)   = (1−t)²·smoothstep(0,kRingRise,t)·exp(−((r−ring_radii·t)/(kRingBand·ring_radii))²)
streak(x,y,t) = L>0 && 0≤x≤L ? sqrt(1−x/L)·exp(−(y/(kStreakThickness·core_radii))²)·(1−t) : 0,
                L = streak_radii·sin(π·clamp(t/kStreakEnd,0,1))      // one-sided, forward of the core
```
Draw per flash: a camera-facing billboard (core + ring, half-size `max(2·core_radii, 1.3·ring_radii)·radius`) and a ribbon along `forward` from the center (streak, `hit_vfx.vert:19-25` axis-ribbon basis). Colour = `tint · intensity · value`. State: `glEnable(GL_DEPTH_TEST)`, `GL_LEQUAL`, depth mask off, blend `(GL_ONE, GL_ONE)`, cull off; restore after. Drawn in `render_space_vfx` (main view and viewscreen RTT both, like shockwaves).

- [ ] **Step 1: Write failing ctests**
  - `warp_in_flash_shape_test.cc`: `CorePeaksEarly` (`warp_in_core(0, 0.08) > warp_in_core(0, 0.5)`), `RingRadiusGrows` (argmax r over [0,4] at t=0.3 < at t=0.6), `StreakIsOneSidedAndForward` (`warp_in_streak(-1,0,0.45) == 0`, `warp_in_streak(2,0,0.45) > 0`), `StreakRetractsByEnd` (`warp_in_streak(0.5,0,0.95) == 0`), `AllZeroAtEndOfLife` (each term at t=1.0 == 0), `ShaderMirrorsConstants` (read `shaders/warp_in_flash.frag` via the `render_origin_math_test.cc:136` `read_shader` pattern; each `"<name> = <value>"` above is present).
  - `warp_in_flash_pass_test.cc` (fixture as `HitVfxSparkPixelTest`, `GTEST_SKIP` without GL): `DrawsAdditively` (one flash at origin, t=0.1 → pixel sum > 0, `glGetError() == GL_NO_ERROR`); `HiddenByNearerDepth` (`glClearDepth` to a depth in front of the flash → pixel sum == 0).
- [ ] **Step 2:** `cmake --build build -j --target renderer_tests && ctest --test-dir build -R "WarpInFlash" --output-on-failure` → FAIL.
- [ ] **Step 3: Implement** the shape twin, pass, shaders, pipeline accessor, bindings (Interfaces). Python: `_build_warp_in_flash_render_data()` converts each `active()` record with `_frames.to_render(view, pSet, *center)` (skip `None`), forward passed unshifted; push in `_push_combat_render_data`; push `warp_in_dials` as params each frame; `warp_in_dials.register()` in the dev-mode dial block.
- [ ] **Step 4: Write + run Python feed tests** `tests/unit/test_warp_in_flash_feed.py`: `test_feed_skips_flashes_outside_viewed_set`, `test_feed_carries_age_and_lifetime`. Then `uv run pytest tests/unit/test_warp_in_flash_feed.py tests/unit/test_host_io_binding_manifest.py -q` and `cmake --build build -j --target dauntless renderer_tests && ctest --test-dir build -R "WarpInFlash" --output-on-failure` → PASS.
- [ ] **Step 5: Commit** `feat(warp-in): procedural warp-in flash pass (core, forward streak, ring) with CPU twin`.

---

### Task 6: Campaign warp-in end to end (headless)

**Files:**
- Test: `tests/integration/test_campaign_warp_in.py` (create)
- Modify: `docs/stub_heatmap_notes.md` (one note: the six warp-in names are implemented; heatmap rows clear on the next telemetry regeneration)

**Interfaces:** Consumes Tasks 1-4.

- [ ] **Step 1: Write the tests** (harness `tests.helpers.headless_mission as hm`, `hm.load("Maelstrom.Episode1.E1M2.E1M2")`):
  - `test_sdk_createship_with_flash_warps_in`: build `App.PlacementObject_Create("Test warp in", pSet.GetName(), None)` 300 GU ahead of the player, facing the player (E5M4:980-1018 pattern); `loadspacehelper.CreateShip("Galor", pSet, "Test Galor", "Test warp in", 1)`. Assert immediately: one flash spawned at the exit point. `hm.tick(1.0)`: ship strictly between exit point and placement, heading == placement's. `hm.tick(2.5)`: ship on the placement within 1e-3, flash retired, warp state `WES_NOT_WARPING`, ship impulse setpoint 0.2 (the SDK coast), weapons able to fire, and the "Exit Warp" sound was played once on the ship (capture via the `TGSoundAction` play seam).
  - `test_sdk_createship_flash_without_placement`: `CreateShip("Galor", pSet, "Test Galor 2", "", 1)` → one flash at the ship, no drive.
- [ ] **Step 2:** `uv run pytest tests/integration/test_campaign_warp_in.py -q` → PASS (Tasks 1-4 already make it pass; if it fails, the failure names the missing link — fix in the owning module with a unit test there).
- [ ] **Step 3: Commit** `test(warp-in): campaign CreateShip(...,1) warps in end to end`.

---

### Task 7: Quick Battle scenario + plan field

**Files:**
- Modify: `engine/quickbattle/scenario.py` (`Group` :43, `update_details` :118, `to_json` :172, `from_json` :197, `SpawnOrder` :342, `battle_plan` :380)
- Test: `tests/unit/test_qb_scenario.py`, `tests/unit/test_qb_battle_plan.py`, `tests/unit/test_qb_presets.py`

**Interfaces:**
- Produces: `Group.warp_in_min: int = 0`; `valid_warp_in(v) -> bool` (`type(v) is int and v >= 0`); `update_details(self, gid, allegiance, direction, distance, difficulty, warp_in_min=0) -> bool` (player group: `warp_in_min` must be 0 or the call returns False); JSON key `"warp_in_min"`; `SpawnOrder.warp_in_s: float = 0.0` (= `warp_in_min × 60.0`).

- [ ] **Step 1: Write failing tests:** `test_warp_in_round_trip` (5 → to_json → from_json → 5); `test_old_preset_without_key_loads_as_zero`; `test_warp_in_validation` (`from_json` raises `ValueError` for −1, 2.5, True, "3"; accepts 0 and 600); `test_player_group_cannot_be_delayed` (`update_details` on the player group with 3 → False; `from_json` with a delayed player group raises); `test_battle_plan_warp_in_seconds` (group at 2 → every order `warp_in_s == 120.0`, others 0.0); `test_same_setup_sees_delay` (two scenarios differing only in delay are not `same_setup`).
- [ ] **Step 2:** `uv run pytest tests/unit/test_qb_scenario.py tests/unit/test_qb_battle_plan.py tests/unit/test_qb_presets.py -q` → FAIL.
- [ ] **Step 3: Implement** per Interfaces (`gd.get("warp_in_min", 0)` + `_req(valid_warp_in(...), "bad warp-in")`).
- [ ] **Step 4:** Re-run + `tests/host/test_qb_spawn.py` → PASS.
- [ ] **Step 5: Commit** `feat(qb): per-group warp_in_min in scenario, presets and battle plan`.

---

### Task 8: Quick Battle panel + Warp-in stepper

**Files:**
- Modify: `engine/ui/quick_battle_setup_panel.py` (`_on_details` :544, `_on_draft` :553, `_on_draft_update` :563, payload :390, `_group_summary` :354)
- Modify: `native/assets/ui-cef/js/quick_battle_setup.js` (`renderDetails` :191, `qbsSeg` :207, `qbsClick` :603, `qbsRender` :728), `native/assets/ui-cef/css/quick_battle_setup.css`
- Test: `tests/unit/test_quick_battle_setup_panel.py`, `tests/unit/test_quick_battle_setup_page.py`

**Interfaces:**
- Consumes: Task 7 `update_details(..., warp_in_min)`, `Group.warp_in_min`.
- Produces: draft key `"warp_in"` (int); verb `draft:warp_in:<n>`; group payload key `"warp_in_min"`; summary suffix `" · warps in at N min"`, direction shown as `"Random"` when N > 0.

- [ ] **Step 1: Write failing Python tests** (`test_quick_battle_setup_panel.py`):
  - `test_draft_warp_in_values`: `draft:warp_in:0`/`5`/`600` accepted (draft holds int); `-1`, `2.5`, `""`, `abc` refused (return False, draft unchanged).
  - `test_draft_update_applies_warp_in`: details → `draft:warp_in:3` → `draft-update` → group `warp_in_min == 3`.
  - `test_player_group_warp_in_refused`.
  - `test_summary_shows_random_and_delay`: enemy group fore/standard at 5 → `"Enemy · Random · Standard (35 km) · warps in at 5 min"`; at 0 → today's summary unchanged.
  - `test_payload_carries_warp_in_min`.
- [ ] **Step 2:** `uv run pytest tests/unit/test_quick_battle_setup_panel.py -q` → FAIL.
- [ ] **Step 3: Implement Python** (int branch in `_on_draft`: `value.isdigit()` then `int(value)`; seed from `g.warp_in_min`; pass `warp_in_min=d["warp_in"]`).
- [ ] **Step 4: Implement JS/CSS.** Non-player groups get a **Warp-in** row after Distance: `−` / value / `+` using the `qbs-qty` look (− disabled at 0; each sends `draft:warp_in:<n±1>`). Value reads `Start` at 0, else `N min`. Clicking the value swaps in `<input class="qbs-delay" inputmode="numeric">`; on `change`: `/^\d+$/` → send `draft:warp_in:<n>`, else restore the previous value; blur commits via change; Esc is handled by the existing text-capture (no `keydown` listener — the page test forbids it). Extend the `qbsRender` editing guard and the `qbsClick` early-return to `.qbs-delay` (as for `.qbs-rename`). While the draft's `warp_in > 0`, the Direction segment renders disabled with a single "Random" label (stored direction kept).
- [ ] **Step 5: Page guard test** — add to `test_quick_battle_setup_page.py`: `test_warp_in_stepper_present` (JS contains `draft:warp_in:` and class `qbs-delay`; CSS defines `.qbs-delay`). Run `uv run pytest tests/unit/test_quick_battle_setup_panel.py tests/unit/test_quick_battle_setup_page.py -q` → PASS.
- [ ] **Step 6: Commit** `feat(qb): Warp-in stepper with type-in value on the group details`.

---

### Task 9: Quick Battle late spawn, win count, cleanup

**Files:**
- Create: `engine/quickbattle/late_arrivals.py`
- Modify: `engine/quickbattle/spawn.py` (`generate_ships` :248; factor `_resolve_position` out of `_place` :197 and `_apply_identity` out of the create loop, now-path behaviour unchanged; add `install_end_simulation_hook`)
- Modify: `engine/host_loop.py` (install beside :7833; teardown beside :13354 calls `late_arrivals.reset()`)
- Modify: `tests/conftest.py` (reset `late_arrivals`)
- Test: `tests/host/test_qb_late_arrivals.py` (create), `tests/integration/test_quickbattle_setup_e2e.py` (add), `tests/host/test_qb_spawn.py` (unchanged must pass)

**Interfaces:**
- Consumes: Task 7 `SpawnOrder.warp_in_s`; Task 6-proven `CreateShip(..., placement, 1)`.
- Produces:
  - `late_arrivals.schedule(qb, late_orders: list[tuple[int, SpawnOrder]], radii: dict[str, float]) -> None` — `int` is the order's 1-based index in `plan.orders` (naming).
  - `late_arrivals.on_timer(pObject, pEvent)` — handler; `pEvent.GetInt()` = delay key index.
  - `late_arrivals.cancel_all() -> None`; `late_arrivals.reset() -> None`; `late_arrivals.pending_enemy_count() -> int`.
  - `late_arrivals.set_rng(rng)` (tests; default `random.Random()`).
  - `late_arrivals.check_win(qb) -> None` — mirrors QuickBattle.py:3356-3360 (`g_iNumEnemies == 0 and bInSimulation and bWonOrLost == 0` → `bWonOrLost = 1`, `GenerateWinSequence()`, `BridgeHandlers.DropMenusTurnBack()`, `g_pXO.MenuUp()`).
  - `spawn.install_end_simulation_hook(qb) -> bool` — wraps `qb.EndSimulation`: `late_arrivals.cancel_all()` then the original; idempotent like `install_generate_ships_hook`.

Behaviour (spec §6.5, §6.6):
- `generate_ships`: now-orders (`warp_in_s == 0`) take today's path exactly; the `if not created: return` early-out applies to now-orders only, then late handling always runs. For each late order: probe ship `loadspacehelper.CreateShip(order.ship_file, None, "<name> probe", "")`, apply registry like the now path, `_seed_radius`, read `GetRadius()`, then delete via `ET_DELETE_OBJECT_PUBLIC` (loadspacehelper.py:109-113 pattern). Pre-count: enemy → `g_iNumEnemies += 1`, friendly → `g_iNumFriends += 1` (neutral none). Then `schedule`.
- `schedule`: one TGTimer per **distinct** `warp_in_s` (groups with equal delays arrive in one tick → one callout per side): `TGIntEvent` with `ET` from `App.Mission_GetNextEventType()` (allocated once per module load), destination `qb.g_pXO`, handler `"engine.quickbattle.late_arrivals.on_timer"` registered once per XO object; `SetTimerStart(GetGameTime() + delay)`, `SetDelay(0)`, `SetDuration(0)`; keep timer ids.
- `on_timer`: if not `qb.bInSimulation` → drop. Read `qb.g_pSet` and the player now; if either is missing → un-count those orders and `check_win`. Else per group: direction `rng.choice(scenario.DIRECTIONS)` relative to the player's current pose; `placement.group_positions(...)` with probe radii; nudge via `_resolve_position` seeded with the player and every ship currently in the set; per ship `PlacementObject_Create("QB warp in <gid> <n>", set_name, None)` + `SetTranslate` + `spawn._face(...)` + `UpdateNodeOnly`; `CreateShip(order.ship_file, set, name, placement_name, 1)`; `_apply_identity`; group names; `g_kShips` record; `g_iCurrentAILevel = order.ai_level`; `SetAI(__import__(ai).CreateAI(ship), 0, 0)`; proximity manager update. A ship that fails → log, un-count, `check_win`. Then Task 10's callout.

- [ ] **Step 1: Write failing tests** (`tests/host/test_qb_late_arrivals.py`, fixtures from `tests/host/test_qb_spawn.py` — `qb`, `_plan`, `_start`):
  - `test_no_delay_spawn_unchanged`: a no-delay plan yields the same ship names, positions and `g_kShips` as before (compare with the existing `test_qb_spawn` expectations).
  - `test_late_group_absent_then_arrives`: enemy group A at 0, enemy group B at 1 min → after start only A exists; `g_iNumEnemies == len(A)+len(B)`; tick game time 59 s → B absent; 61 s → B present, each at `distance_gu` ±1 from the player's position at 60 s, AI set, `g_kShips` has them, one flash per ship.
  - `test_killing_first_group_does_not_win`: destroy all of A via `QB.ShipDestroyed` → `bWonOrLost == 0`; after B arrives and is destroyed → won.
  - `test_all_groups_late_battle_arms_and_waits` (Review Focus 1).
  - `test_restart_before_arrival_spawns_only_new_battle` (Review Focus 2): start, `QB.RestartSimulation()` at 30 s → the old timer never spawns; the new battle's group arrives 60 s after the restart.
  - `test_end_simulation_cancels_pending`: `QB.EndSimulation()` before arrival → no timers left, nothing spawns at 61 s.
  - `test_failed_late_spawn_is_uncounted`: monkeypatch `CreateShip` to return None for B → `g_iNumEnemies` drops, A destroyed → win.
  - `test_random_direction_is_seeded`: `set_rng(random.Random(1))` twice → identical arrival positions.
- [ ] **Step 2:** `uv run pytest tests/host/test_qb_late_arrivals.py -q` → FAIL.
- [ ] **Step 3: Implement** per Interfaces/Behaviour.
- [ ] **Step 4:** Add `test_late_enemy_group_e2e` to `tests/integration/test_quickbattle_setup_e2e.py` (panel verbs incl. `draft:warp_in:1`, start, tick, destroy, win). Run `uv run pytest tests/host/test_qb_late_arrivals.py tests/host/test_qb_spawn.py tests/integration/test_quickbattle_setup_e2e.py tests/unit/test_conftest_leak_resets.py -q` → PASS.
- [ ] **Step 5: Commit** `feat(qb): late groups warp in on their delay; pre-counted for the win; cleaned up on End/Restart`.

---

### Task 10: Quick Battle crew callouts

**Files:**
- Modify: `engine/quickbattle/late_arrivals.py`
- Test: `tests/host/test_qb_late_arrivals.py` (add), `tests/unit/test_qb_callouts.py` (create)

**Interfaces:**
- Produces: `enemy_callout_key(n_arrived: int, enemies_already: bool) -> str | None` — `None` if `n_arrived == 0`; `"Incoming6"` if `enemies_already`; else `Incoming1..4` for 1-4, `"Incoming5"` for ≥5. `OTHER_CALLOUT_KEY = "gs025"`. `callout(qb, arrived: dict[str, int], enemies_already: bool) -> None` (keys `"enemy"`, `"other"`).

- [ ] **Step 1: Write failing tests:** `test_qb_callouts.py` — each row of spec §6.7's table; `0 → None`. Host tests — `test_late_enemies_into_quiet_battle_say_count_line` (all now-enemies dead, 2 arrive → Tactical says `Incoming2`); `test_late_enemies_while_fighting_say_incoming6`; `test_late_friendly_says_gs025_by_science`; `test_mixed_arrival_one_line_per_side`; `test_missing_character_skips_quietly`. Capture lines by monkeypatching `App.CharacterAction_Create` or via the `crew_speech.emit` seam.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3: Implement.** `enemies_already` = live enemies before this arrival (`g_iNumEnemies` − pending late enemies, arrivals included, > 0). Speaker: `qb.g_pTact` for enemies, `qb.g_pSci` for others; database argument `None` when the character has its own (`GetDatabase()`), else `qb.g_pGeneralDatabase`; `App.CharacterAction_Create(char, App.CharacterAction.AT_SAY_LINE, key, "Captain", 1, db)` played in a `TGSequence`. Missing character/database → log once, skip.
- [ ] **Step 4:** `uv run pytest tests/unit/test_qb_callouts.py tests/host/test_qb_late_arrivals.py -q` → PASS.
- [ ] **Step 5: Commit** `feat(qb): crew calls out late arrivals with BC's Incoming lines`.

---

### Task 11: Docs + hand-over

**Files:**
- Modify: `CLAUDE.md` (one table row "Warp-in arrivals", ≤1200 chars: the routine, the flash pass, game-time ticking in `GameLoop.tick`, hold heading/fire rule, QB late groups + callouts, dials `"warp in"`, ⚠️ not live-verified)
- Modify: `docs/superpowers/specs/2026-10-22-warp-in-arrivals-and-qb-delay-design.md` (Status line → "built, awaiting live check")

- [ ] **Step 1:** Write both edits; `uv run pytest tests/docs/test_doc_consistency.py -q` → PASS.
- [ ] **Step 2: Commit** `docs(warp-in): CLAUDE.md row; spec status`.
- [ ] **Step 3: Hand over to Mark** (do not launch): live check commands from spec §8 (`cd <worktree> && ./build/dauntless --developer`), and ask before running the §6.6 profiler measurement (`DAUNTLESS_MISSION=engine.dev_missions.combat_stress`, `DAUNTLESS_PROFILE_SPIKES=<path>`), whose result goes into `docs/engine/perf-register.md` as a signal.
