# Layered damage production, phase 1: the damage store and wear from every weapon — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move plating wear and holes out of the 24-slot scorch ring into a per-instance store that never evicts. Fill that store from the hull damage every weapon deals: torpedoes and bolts, phasers (slowly), big collisions, internal blasts and the death cascade.

**Architecture:**
- **The store.** `scenegraph::HullDamageStore` (64 records) lives on each `Instance`. It merges a new hit into a nearby record of the same kind. When full, it merges the two nearest records instead of dropping one.
- **Python side.** `engine/appc/hull_wear.py` turns hull damage dealt into wear and accumulates it across the scorch emit throttle. It flushes through a new `host_io.hull_damage_add`.
- **Renderer.** It builds the plating list from the store, once per instance per change, and shares it between the plating draw and `submit_plating_interior`.
- **The ring.** It keeps scorch, heat glow and scuffs only.

**Tech Stack:** C++20, GLSL 410 core, pybind11, Python 3, GoogleTest, pytest, CMake (Debug tree `build/` in the worktree).

**Spec:** `docs/superpowers/specs/2026-10-21-layered-hull-damage-production-design.md`. This plan covers:
- goal 2 (wear sources);
- goal 6 (damage never heals);
- §7 "the hull damage store" and "wear counts damage dealt";
- §3's "build the damage list once per instance per frame".

The store's shape comes from `2026-10-20-layered-hull-damage-productisation.md` §3.1.

**Roadmap (later plans, not this one):**
- **Phase 2:** the 20 GU near/far switch, far wreckage paint, the viewscreen rule, the lean mark path, cached uniform locations, the per-draw record subset, the deck-break subset, fill prefetch, parts at load plus disk cache, and the perf rule.
- **Phase 3:** rock craters, severance by structure part, and venting and debris from tear events.
- **Phase 4:** articulation, removing the old carve, dials into Developer Options, docs, the Release verdict, and Mark's live check.

## Global Constraints

- **Git.** Worktree `.claude/worktrees/damage-redesign`, branch `spike/damage-redesign`.
  - Never run `git checkout --`, `restore`, `stash`, `clean`, `reset --hard` or `add -A/.`.
  - Stage explicit paths. Commit with `git commit -F <file>`, ending `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
- **Tests.** Focused test files only: never a whole suite, never the gate.
  - Never run pytest with an empty or glob-built file list.
  - Pytest form: `env -u VIRTUAL_ENV uv run pytest -q -p no:cacheprovider <files>`.
  - GL tests: `DAUNTLESS_GAME_DIR="/Users/mward/Documents/Star Trek Bridge Commander/game" build/native/tests/renderer/renderer_tests --gtest_filter=...`.
- **Shader edits.** Any edit under `native/src/renderer/shaders/` needs `cmake -B build -S .` before `cmake --build build -j`.
  - Confirm with a grep in the matching `build/native/src/renderer/embedded_*.h`.
  - Also build `dauntless`.
- **`opaque.frag` rules.**
  - Never add a sampler to `opaque.frag`. Never `return` early from its PLATING main.
  - After any edit, run `HullClipTest.*` and `ScuffTest.*`.
  - Every hunk against `1fca3177d` stays inside `#ifdef PLATING`.
- **Units.** Body frame = model units; game distances are GU (1 GU = 175 m). Store reach is in body units, converted exactly as `damage_decal_add` converts its radius.
- **The live-tuned look must not change** for one photon torpedo hit after another: one stock photon's hull damage is 1 wear.
- **Visible damage only.** No change to hull or subsystem health, shields or gameplay damage numbers.

## Review Focus

1. **Sweeping phaser fire must not grow one record over the whole hull.** A beam walked across the hull must leave a trail of records, not one ever-growing record that strips everything. Pinned in Task 1 (`SweepDoesNotGrowOneRecordOverTheHull`).
2. **Shots the shields fully absorb, god mode, and light phaser fire leave no wear.** These gates exist today for the scorch and the carve and must hold for wear. Pinned in Task 2 (`test_no_wear_when_shields_absorb_everything`, `test_no_wear_in_god_mode`, `test_light_phaser_fire_leaves_no_wear`).
3. **A volley inside the scorch emit throttle (0.2 s) still counts every hit.** Pinned in Task 2 (`test_throttled_hits_still_accumulate_wear`).
4. **A long death cascade or a DamageTool script never overflows the store.** It merges, keeps all wear, and keeps every internal hole. Pinned in Task 1 (`FullStoreMergesNearestPairNeverEvicts`, `InternalHolesSurviveTwoHundredHits`).
5. **A scaled ship (`SetScale`) gets wear at the same body-frame size as a scorch at the same hit.** Pinned in Task 2 (`test_wear_reach_matches_scorch_reach`).

---

### Task 1: `HullDamageStore`, merge-not-evict

**Files:**
- Create: `native/src/scenegraph/include/scenegraph/hull_damage.h`, `native/src/scenegraph/src/hull_damage.cc` (add to the scenegraph CMake target)
- Modify: `native/src/scenegraph/include/scenegraph/instance.h` (member next to `decals`)
- Test: `native/tests/scenegraph/hull_damage_test.cc` (add to the scenegraph tests CMake)

**Interfaces:**
- Produces:
  ```cpp
  namespace scenegraph {
  enum class HullDamageKind : std::uint8_t { Surface = 1, Internal = 3 };  // = shader c.x
  struct HullDamageRecord {
      glm::vec3 centre_body{0.0f};
      glm::vec3 normal_body{0.0f};   // unit for Surface, zero for Internal
      float reach = 0.0f;            // body units
      float wear = 0.0f;
      HullDamageKind kind = HullDamageKind::Surface;
      bool active = false;
  };
  class HullDamageStore {
  public:
      static constexpr std::size_t kCapacity = 64;
      static constexpr float kMergeFactor = 0.5f;   // centre distance <= 0.5 x the larger reach
      static constexpr float kMaxMergeGrowth = 1.5f; // a voluntary merge never grows reach past 1.5x the larger input
      void add(const glm::vec3& centre_body, const glm::vec3& normal_body,
               float reach, float wear, HullDamageKind kind);
      std::span<const HullDamageRecord> records() const;  // all kCapacity slots
      std::size_t count() const;
      std::uint32_t revision() const;   // +1 on every add that changed the store
      void clear();
  };
  }
  ```
  - `Instance::hull_damage` is a `HullDamageStore`.
- **Merge rule.**
  - A merged record has:
    - summed wear;
    - a wear-weighted centroid;
    - for Surface, the normalised wear-weighted normal;
    - the enclosing reach, `max over inputs of (|c_i - c| + r_i)`.
  - **Voluntary merge.** On add, merge into the nearest active record of the same kind when its centre lies within `kMergeFactor × max(reach_new, reach_existing)`, and the merged reach is ≤ `kMaxMergeGrowth × max(reach_new, reach_existing)`. Otherwise use a free slot.
  - **Forced merge.** When no slot is free, first merge the two nearest active records of any one kind. This merge has no growth cap. Then insert.
  - Wear ≤ 0 or reach ≤ 0 is ignored, and the revision does not change.

- [ ] **Step 1: Write the failing tests** in `hull_damage_test.cc`:
  - `ZeroWearOrReachIsIgnored`: count 0, revision 0.
  - `NearbySameKindMerges`: two Surface adds 1 mu apart, reach 10, wear 1. Count 1, wear 2, centre at the midpoint.
  - `KindsNeverMerge`: a Surface and an Internal at the same point. Count 2.
  - `SweepDoesNotGrowOneRecordOverTheHull`: 40 Surface hits, reach 10, wear 0.1, along the x axis every 4 mu. No record's reach exceeds 15, and count > 1.
  - `FullStoreMergesNearestPairNeverEvicts`: 64 Surface records 100 mu apart, wear 1. Add a 65th far away. Count 64 and total wear 65.
  - `InternalHolesSurviveTwoHundredHits`: one Internal record (wear 10, reach 30) at the origin, then 200 Surface hits, reach 10, wear 1, scattered on a 400 mu grid away from it. An Internal record with wear ≥ 10 and centre within 1 mu of the origin still exists.
  - `RevisionCountsChanges`: two real adds, revision 2.
- [ ] **Step 2: Build and run** `build/native/tests/scenegraph/scenegraph_tests --gtest_filter='HullDamage*'` (find the exact binary name in the tests CMake). Expect FAIL: not defined.
- [ ] **Step 3: Implement** the header, the source, and the `Instance` member.
- [ ] **Step 4: Run** the same filter. Expect PASS.
- [ ] **Step 5: Commit.**

### Task 2: Wear from hull damage dealt, into the store

**Files:**
- Create: `engine/appc/hull_wear.py`
- Modify:
  - `native/src/host/host_bindings.cc`: the `hull_damage_add` binding, beside `damage_decal_add`.
  - `engine/host_io.py`: `hull_damage_add`, beside `damage_decal_add`.
  - `engine/appc/hit_feedback.py`: step 4 of the hit path, the decal emit.
  - `engine/appc/internal_blast.py`, `engine/appc/visible_damage.py`: their Internal decal adds.
  - `engine/appc/plating_dials.py`: only if a dial moves.
- Test: `tests/unit/test_hull_wear.py` (new), `tests/unit/test_internal_blast.py`, `tests/unit/test_visible_damage.py`

**Interfaces:**
- Consumes: `HullDamageStore::add`, `HullDamageKind` (Task 1).
- Produces:
  - **Binding.** `_dauntless_host.hull_damage_add(iid, rel_point, world_normal, radius, wear, kind)`. It converts point, normal and radius to the body frame exactly as `damage_decal_add` does. `kind` is 1 (Surface) or 3 (Internal); other values are ignored.
  - **host_io.** `host_io.hull_damage_add(instance_id, world_point, world_normal, radius, wear, kind) -> None`. It is a no-op without a host or instance.
  - **`hull_wear.py` constants, all dials:**
    - `REFERENCE_DAMAGE = 500.0`, the stock photon's hull damage, equal to 1 wear;
    - `PROJECTILE_MIN = 0.25` and `PROJECTILE_MAX = 1.5`;
    - `PHASER_RATE = 1.0`, applied to phaser hull damage per tick, with no minimum per tick;
    - `COLLISION_MIN_HULL_DAMAGE = 100.0`: impacts (`decal_dent == 1`) at or above it add wear; grinds and smaller impacts never do;
    - `COLLISION_MAX = 1.5`.
  - **`hull_wear.py` functions:**
    - `wear_for_hit(weapon_type: str | None, absorbed_hull: float, decal_dent: float = 0.0) -> float`:
      - phaser: `absorbed_hull / REFERENCE_DAMAGE * PHASER_RATE`, capped at `PROJECTILE_MAX`;
      - collision: 0 below the threshold or for a grind, else `min(absorbed_hull / REFERENCE_DAMAGE, COLLISION_MAX)`;
      - everything else (torpedo, disruptor, pulse, unknown): `clamp(absorbed_hull / REFERENCE_DAMAGE, PROJECTILE_MIN, PROJECTILE_MAX)`;
      - always 0 when `absorbed_hull <= 0`.
    - `accumulate(ship, iid, world_point, world_normal, radius, wear) -> None`: adds to a per-ship pending total, keeping the latest point, normal and radius.
    - `flush(ship) -> None`: sends the pending total through `host_io.hull_damage_add(..., kind=1)` and clears it.
    - `reset() -> None`, called on mission swap wherever `hit_feedback`'s throttle state is reset.
  - `hit_feedback`:
    - On every hit that passes today's scorch gates (`persist_decal`, `absorbed_hull > 0`, normal present, instance present), it calls `hull_wear.accumulate` with `wear_for_hit(...)`. The radius is the same `vis_r * decal_radius_scale(wclass)` the scorch uses.
    - Phaser wear also needs `allow_hull_carve` (light phaser fire stays cosmetic, as today).
    - It calls `flush` at the moment it emits the throttled scorch decal (`DECAL_EMIT_INTERVAL`), so a volley inside the window is summed, not dropped.
  - Internal blasts and `AddDamage` call `host_io.hull_damage_add(..., kind=3)` with today's wear and radius, in place of their Internal decal adds.

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_hull_wear.py`:
  - `test_photon_hit_is_one_wear`: `wear_for_hit("torpedo", 500.0) == 1.0`.
  - `test_heavy_torpedo_is_capped`: `wear_for_hit("torpedo", 1400.0) == 1.5`.
  - `test_light_bolt_has_a_floor`: `wear_for_hit("disruptor", 50.0) == 0.25`.
  - `test_phaser_tick_is_proportional`: `wear_for_hit("phaser", 0.28) == pytest.approx(0.28 / 500.0)`.
  - `test_small_collision_and_grind_never_wear`: `("collision", 99.0, 1.0)` → 0, and `("collision", 400.0, 0.0)` → 0.
  - `test_big_collision_wears`: `("collision", 250.0, 1.0)` → 0.5.
  - **Fake host_io.** Patch `host_io.hull_damage_add` to record calls. The hit_feedback tests below use the same fake.
  - `test_throttled_hits_still_accumulate_wear`: three photon hits on one ship inside 0.2 s through the hit_feedback path give ONE `hull_damage_add` call with wear 3.0.
  - `test_no_wear_when_shields_absorb_everything`: `absorbed_hull = 0` → no call.
  - `test_no_wear_in_god_mode`: `persist_decal=False` → no call.
  - `test_light_phaser_fire_leaves_no_wear`: a phaser hit with `allow_hull_carve=False` → no call.
  - `test_wear_reach_matches_scorch_reach`: the radius passed to `hull_damage_add` equals the radius passed to `damage_decal_add` for the same torpedo hit.
  - `test_internal_blast.py`: the existing exit-point tests now expect `hull_damage_add(..., kind=3)` with the old wear and hole radius, and no Internal decal add.
  - `test_visible_damage.py`: the carving-off `AddDamage` test now expects `hull_damage_add(..., kind=3)`.
- [ ] **Step 2: Run** `env -u VIRTUAL_ENV uv run pytest -q -p no:cacheprovider tests/unit/test_hull_wear.py tests/unit/test_internal_blast.py tests/unit/test_visible_damage.py`. Expect FAIL.
- [ ] **Step 3: Implement** the binding, the host_io wrapper, `hull_wear.py`, and the three call-site changes. Rebuild `dauntless`.
- [ ] **Step 4: Run** the same command, plus `tests/unit/test_visible_damage_budget.py tests/unit/test_plating_dials.py tests/unit/test_damage_preview_impulse_steps.py`. Expect PASS.
- [ ] **Step 5: Commit.**

### Task 3: The renderer reads the store; the ring forgets wear

**Files:**
- Modify:
  - `native/src/renderer/include/renderer/plating_damage.h`, `native/src/renderer/plating_damage.cc`: `build_damage_list` from the store.
  - `native/src/renderer/frame.cc`, `native/src/renderer/include/renderer/frame.h`: the shared list, and both call sites.
  - `native/src/renderer/hull_interior_pass.cc`: array size only, if it uploads by count.
  - `native/src/renderer/shaders/opaque.frag` (PLATING only), `native/src/renderer/shaders/hull_interior.frag`: `MAX_DMG` 24 → 64.
  - `native/src/scenegraph/include/scenegraph/damage_decals.h`, `native/src/scenegraph/src/damage_decals.cc`: drop `wear` and `WeaponClass::Internal`.
  - `native/src/host/host_bindings.cc`: the decal binding accepts classes 0–2 again.
- Test:
  - `native/tests/renderer/plating_damage_test.cc`, `native/tests/renderer/plating_render_test.cc`, `native/tests/renderer/hull_interior_test.cc`: their rings become stores.
  - `native/tests/renderer/plating_gl_fixture.h`.
  - `native/tests/scenegraph/damage_decals_test.cc`.

**Interfaces:**
- Consumes: `HullDamageStore` (Task 1). Task 2 fills it at runtime.
- Produces:
  - **`renderer::plating`.**
    - `kMaxDamage = 64`, with `static_assert(kMaxDamage >= scenegraph::HullDamageStore::kCapacity)`.
    - `DamageList build_damage_list(const scenegraph::HullDamageStore&, const float* params)`, with the same rules as today: Surface reach × `params[7]`, the `torn_possible` floor unchanged.
    - The ring overloads are removed.
  - **`FrameSubmitter`.** `const plating::DamageList& plating_list_for(const scenegraph::Instance&)`.
    - It caches per instance id.
    - It rebuilds only when that instance's `hull_damage.revision()` or any of the `kParamCount` plating params differ from the cached copy.
    - `submit_opaque_in_pass` and `submit_plating_interior` both use it.
    - `int FrameSubmitter::plating_list_builds() const` counts rebuilds, for tests.
  - **GLSL.** `MAX_DMG = 64` in both shaders. Uploads send only `count` entries.
  - **`DamageDecalRing`.** No `wear` field, no `Internal` class. A Scorch merge still adds intensity.

- [ ] **Step 1: Write the failing tests:**
  - `plating_damage_test.cc`: port every list test from a ring to a store, plus:
    - `SixtyFourRecordsAllReachTheList`: 64 Surface records → `count == 64`.
    - `SurfaceReachTakesTheReachMultiplier`: reach 10, `params[7] = 0.4` → `a.w == 4`.
  - `plating_render_test.cc`, `PlatingListIsBuiltOncePerChange`:
    - Two consecutive frames of `submit_opaque_in_pass` + `submit_plating_interior` on one damaged quad: `plating_list_builds()` goes up by 1, not 4.
    - After one more `hull_damage.add`, the next frame goes up by 1 more.
  - The existing plating render and interior tests, with their fixtures building `Instance::hull_damage` instead of decal-ring Internal/Scorch wear, keep their current assertions.
  - `damage_decals_test.cc`: drop the wear and Internal tests. A Scorch merge still raises intensity.
- [ ] **Step 2: Reconfigure, build, run** `--gtest_filter='PlatingDamage*:PlatingRender*:HullInterior*:UnevenBreach*'` and the scenegraph `DamageDecal*` filter. Expect FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the GL filter `PlatingDamage*:PlatingRender*:HullInterior*:UnevenBreach*:HullClipTest.*:ScuffTest.*:DecalRenderTest.*:FrameTest.*`, the scenegraph `DamageDecal*:HullDamage*` filter, and the Task 2 pytest files. Expect PASS.
  - Check `git diff 1fca3177d -- native/src/renderer/shaders/opaque.frag`: every hunk is inside `#ifdef PLATING`.
- [ ] **Step 5: Commit.**

### Task 4: Measure, and confirm the look held

**Files:**
- Modify: `docs/reference/engine/perf-register.md`, and the design spec's goal 6 status line only if something is found.

- [ ] **Step 1: Captures (machine idle).**
  - Run the DP command from `perf-register.md` twice:
    - GPU focus `space.opaque,space.carve_stencil,space.breach,space.hull_interior`;
    - CPU-only (no GPU timing).
  - Both at the default distance, with `DAUNTLESS_DEV_SCREENSHOT=<png> DAUNTLESS_DEV_SCREENSHOT_AFTER_S=15`.
  - Record `uptime` with each.
- [ ] **Step 2: Record** new C- and SIG- rows against C-105 and C-107. Give `space.opaque` and `space.hull_interior`, GPU and CPU, per window (undamaged / alive / dying).
  - Say whether the store and the shared list moved them.
  - Look at the screenshot against C-105's. Say whether the impulse damage looks the same; if it is too small to tell, say so.
- [ ] **Step 3: Commit** the docs.
