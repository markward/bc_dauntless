# Layered damage production, phase 3: tears that vent, rock craters, ships that break apart — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild on the new damage records the three things only the old carve did:
- venting and debris when a hull tears;
- craters in asteroids;
- whole sections of a ship breaking off.

After this, nothing the player sees depends on the voxel carve, so phase 4 can remove it.

**Architecture:**
- **Venting (Task 1).** `HullDamageStore::add` reports how the record it touched changed. When a Surface record's wear first crosses the breach wear, the binding pushes a `BreachEvent`, so the existing venting and debris emitters fire as they do for internal blasts.
- **Rock craters (Task 2):**
  - Rocks draw through the plating program in a rock mode, with no panels, ribs or members, just a cut where wear passes breach.
  - Their holes get the stencil mark and an interior draw in a rock mode. The view ray marches the damage field from the cut to the crater wall, which is shaded with the rock's own base texture, as the old breach pass did.
  - Beyond 20 GU a rock crater is painted, not cut.
- **Severance (Tasks 3–4):**
  - The structure-part detector's per-voxel labels are kept.
  - A native split check floods the parts' surviving voxels from the main body, where a voxel survives when its interior wear is below deck break. A part that is no longer reached comes off whole.
  - The parent stops drawing that part, and a chunk instance draws only that part. Both use a part mask in the plating program.
  - The existing `hull_breakup` / `debris_chunk` Python flow spawns it and destroys the subsystems inside it.

**Tech Stack:** C++20, GLSL 410 core, pybind11, Python 3, GoogleTest, pytest, CMake (Debug tree `build/`).

**Spec:** `docs/superpowers/specs/2026-10-21-layered-hull-damage-production-design.md`:
- goal 4 (rock craters, no panels, ribs or rooms; far craters painted);
- goal 5 (a chunk is a whole detected structure part; parent hides it, chunk shows only it; subsystems inside destroyed);
- §6 (venting and debris re-driven from tear events).

## Global Constraints

- **Git.** Worktree `.claude/worktrees/damage-redesign`, branch `spike/damage-redesign`.
  - Never run `git checkout --`, `restore`, `stash`, `clean`, `reset --hard` or `add -A/.`.
  - Stage explicit paths. Commit with `git commit -F <file>`, ending `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
  - Never touch `main`. Mark: no merge to main until the old carve is gone (phase 4).
- **Tests.** Focused tests only, with explicit lists; never a whole suite or the gate.
  - GL: `DAUNTLESS_GAME_DIR="/Users/mward/Documents/Star Trek Bridge Commander/game" build/native/tests/renderer/renderer_tests --gtest_filter=...`.
  - Pytest: `env -u VIRTUAL_ENV uv run pytest -q -p no:cacheprovider <files>`.
- **`opaque.frag` rules.**
  - It is optimizer-fragile on this Mac: no new samplers, no early `return` in PLATING main.
  - Its plating discard stays ONE statement.
  - Every hunk against `1fca3177d` is inside `#ifdef PLATING`, so the stock program is unchanged.
  - Run `HullClipTest.*` and `ScuffTest.*` after any edit.
- **Shader edits.** `cmake -B build -S .` before `cmake --build build -j`. Rebuild `dauntless` and `_dauntless_host`.
- **Units.** Body frame = model units; GU in Python and the host APIs. Convert at the bindings as `damage_decal_add` does, through `to_body_frame` / `radius_to_model`.
- **The look of an undamaged ship and of a damaged, unsevered ship must not change,** apart from venting and debris now appearing at torpedo tears.
- **Visible damage only.** The exception is the existing rule that subsystems inside a severed piece are destroyed, through `hull_breakup._destroy_subsystems_inside`.

## Review Focus

1. **A record that crosses breach twice:** it grows past breach, then merges with more wear. It vents once, not on every later hit. Pinned in Task 1 (`TearVentsOnceWhenWearFirstCrossesBreach`).
2. **A rock hit from inside its own crater:** the camera is near the surface, so the march starts inside the damage. It must not draw rooms, panels or space where rock should be. Pinned in Task 2 (`RockCraterShowsRockNotRoomsNotSpace`).
3. **A severed part's subsystems are destroyed exactly once,** and a part already severed is never severed again. Pinned in Task 4 (`SeveredPartSpawnsOnceAndKillsItsSubsystems`).
4. **An articulated ship** (node overrides) never takes structure-part severance; it keeps `part_severance`. Pinned in Task 3 (`ArticulatedInstanceNeverStructureSevers`).
5. **A ship below `damage_geometry.breakables_allowed_for`** (radius ≤ 0.6 GU) and a rock never sever. Pinned in Task 4 (`SmallShipsAndRocksNeverSever`).

---

### Task 1: Tears vent

**Files:**
- Modify:
  - `native/src/scenegraph/include/scenegraph/hull_damage.h`, `native/src/scenegraph/src/hull_damage.cc`.
  - `native/src/host/host_bindings.cc`: `hull_damage_add` and `hull_damage_add_body`.
- Test: `native/tests/scenegraph/hull_damage_test.cc`, `tests/host/test_hull_damage_bindings.py`

**Interfaces:**
- Produces:
  - `struct HullDamageAddResult { int index = -1; float wear_before = 0.0f; float wear_after = 0.0f; };`
  - `HullDamageAddResult HullDamageStore::add(...)` returns the slot the input landed in (merged or new) and that record's wear before and after. An ignored input gives index -1. A forced merge reports the slot the NEW input went into.
  - **Both wear bindings,** after a Surface (kind 1) add: when `wear_before < breach <= wear_after`, with `breach = dauntless_plating::g_params[16]`, push one `BreachEvent`:
    - at the record's `centre_body`;
    - radius `0.5 × reach`, model units;
    - normal = the record's normal;
    - the current `g_decal_game_time`;
    - a seed from the existing counter pattern.
  - Internal (kind 3) adds never push. Internal blasts already call `breach_burst`.
  - Rocks push as ships do. `breach_venting` already skips rocks; debris uses rock colours.
  - `_test_only_breach_events(iid)` returns the instance's active events, read-only, following the `_test_only_*` convention.

- [ ] **Step 1: Write the failing tests:**
  - **scenegraph:**
    - `AddReportsWearBeforeAndAfter`: a fresh add gives `{i, 0, w}`; a merge gives `{i, w0, w0 + w}`.
    - `IgnoredAddReportsNoIndex`.
  - **host** (`test_hull_damage_bindings.py`):
    - `test_tear_vents_once_when_wear_first_crosses_breach`: five Surface adds of wear 1 at one point with breach 4.5 give exactly one event, after the fifth.
    - `test_internal_adds_never_vent`.
- [ ] **Step 2: Build and run** `HullDamage*` and the host file. Expect FAIL.
- [ ] **Step 3: Implement.** Rebuild `dauntless` and `_dauntless_host`.
- [ ] **Step 4: Run** `HullDamage*:DamageDecal*`, the host file, and `tests/unit/test_hull_wear.py`. Expect PASS.
- [ ] **Step 5: Commit.**

### Task 2: Rock craters

**Files:**
- Modify:
  - `native/src/renderer/shaders/opaque.frag` (PLATING only): `uniform int u_plating_rock;`.
    - Rock mode skips `apply_plating` and the member branch.
    - Its hole test is wear past `plating_breach_at` with no member survival.
    - Its far paint is darkened, scorched rock, not wreck.
  - `native/src/renderer/frame.cc`:
    - set `u_plating_rock` from `inst.surface_is_rock`;
    - rocks join the near/far policy;
    - rocks are no longer skipped in `submit_plating_interior`;
    - pass the rock base texture (`find_base_texture_id`, as `breach_pass` does) and the scene lights to the interior draw.
  - `native/src/renderer/hull_interior_pass.{h,cc}`: a rock mode with its texture on unit 1, plus the directional lights.
  - `native/src/renderer/shaders/hull_interior.frag`: the rock branch.
- Test: `native/tests/renderer/hull_interior_test.cc`, `native/tests/renderer/plating_render_test.cc`

**Interfaces:**
- **Interior shader rock mode.** `uniform int u_interior_rock;`, where 0 is a ship, 1 a rock with its own texture and 2 a rock with no texture (flat `vec3(0.30, 0.28, 0.25)`). Also `uniform sampler2D u_rock_tex;` on unit 1, bound on every draw (0 when unused), plus the directional-light uniforms breach_pass uses.
- **Crater march.**
  - From the cut point, step along the ray: `kCraterSteps = 20` steps of `max(reach_max, 1) / 10` model units, where `reach_max` is the largest record reach in the list.
  - Stop at the first step where `interior_wear(p) + tear noise < plating breach at p` (the same `plating_breach_at` rule, ported as a copy).
  - Refine with 4 bisection steps. The wall normal is the negative normalised gradient of `interior_wear` (central differences, h = 0.5 model units).
  - Shade:
    - texture: triplanar rock base texture (`p × 0.02` UV scale, weights from `|normal|^4`);
    - × 0.55 darken (the old `kRockInteriorDarken`), × a depth fade `exp(-t / 40)`;
    - lit by ambient plus directional lights, with no rooms, room light or fire;
    - scorch: × (1 − 0.5 × smoothstep(breach − 1, breach + 1, wear at the wall)).
  - Leaving the fill volume before reaching the wall (blown through) discards.
- **Far rock paint (opaque.frag).** `base.rgb` = the rock's own albedo × 0.35, with a soot noise. No fires and no lit windows.

- [ ] **Step 1: Write the failing tests** on a rock-flagged box with a synthetic fill:
  - `RockCraterShowsRockNotRoomsNotSpace`: with an Internal record at the face centre and a rock texture bound, the centre pixel is neither the clear colour nor any room colour. A red 1×1 rock texture gives a red-dominant pixel.
  - `RockHasNoPanelsOrRibs`: a near-damage pixel just outside the hole equals the same pixel with plating disabled, within ±3.
  - `FarRockCraterIsPaintedNotCut`: far policy gives a non-clear, dark centre; marks == 0.
  - `RockBlownThroughDiscards`: a record at the box centre with reach 60 gives the clear colour.
  - Update `FarRockHoleStaysSeeThrough` (phase 2), which this task supersedes. Rename it and invert its expectation per the spec. Say so in the commit.
- [ ] **Step 2: Reconfigure, build, run** `HullInterior*:PlatingRender*`. Expect FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `HullInterior*:PlatingRender*:PlatingDamage*:UnevenBreach*:HullClipTest.*:ScuffTest.*:DecalRenderTest.*:FrameTest.*:BreachPass*`. Expect PASS.
- [ ] **Step 5: Commit.**

### Task 3: Which parts have come away (native)

**Files:**
- Modify:
  - `native/src/renderer/structure_parts_cache.{h,cc}`: keep the segmentation (`vol`, `label`, `parts`), not just `parts`. `structure_parts_for` keeps its signature.
- Create:
  - `native/src/renderer/include/renderer/part_severance_check.h`, `native/src/renderer/part_severance_check.cc` (add to the renderer CMake).
- Test: `native/tests/renderer/part_severance_check_test.cc` (new; add to the tests CMake)

**Interfaces:**
- Produces:
  ```cpp
  namespace renderer {
  const voxel::StructureSegmentation* structure_segmentation_for(const std::filesystem::path& source); // nullptr until ready
  struct SeveredPart { int part = -1; int voxels = 0; glm::vec3 centroid_body{0}; glm::vec3 min_body{0}, max_body{0}; };
  // Parts no longer joined to the main body. A voxel survives when the
  // interior wear at its centre (all records, no facing; the same sum the
  // interior shader uses) is below deck_break. Main body = the part with the
  // most surviving voxels. Flood 6-connected surviving voxels from it; a part
  // is severed when fewer than kReachedFraction (0.05) of its surviving
  // voxels were reached and it has at least kMinPartVoxels (64) surviving.
  // Parts in `already_severed` are skipped.
  std::vector<SeveredPart> find_severed_parts(const voxel::StructureSegmentation&,
                                              const plating::DamageList&, float deck_break,
                                              std::uint32_t already_severed);
  }
  ```
  - Interior wear uses the list's `a.w` exactly as uploaded: Surface reach already × `params[7]`, Internal reach raw. That is the same field `hull_interior.frag`'s `interior_wear` sums, so a part comes off exactly where the interior shows it blown through.
- Articulated instances (any node overrides) are never checked: this is the caller's rule, pinned here through a helper `bool can_structure_sever(const scenegraph::Instance&)`.

- [ ] **Step 1: Write the failing tests** on a synthetic segmentation (two parts joined by a one-voxel-thick bridge):
  - `IntactShipSeversNothing`.
  - `BlownBridgeSeversTheSmallerPart`: one Internal record over the bridge, wear 10, deck break 6. The result is the small part, with the right voxel count and bounds.
  - `AlreadySeveredPartIsNotReported`.
  - `TinyPartBelowMinimumNeverSevers`.
  - `ArticulatedInstanceNeverStructureSevers` (through `can_structure_sever`).
- [ ] **Step 2: Build and run** `PartSeverance*`. Expect FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `PartSeverance*:PlatingRender*:HullInterior*`. Expect PASS.
- [ ] **Step 5: Commit.**

### Task 4: Breaking off, drawn and spawned

**Files:**
- Modify:
  - `native/src/scenegraph/include/scenegraph/instance.h`: `std::uint32_t severed_parts = 0;` and `int only_part = -1;`.
  - `native/src/renderer/shaders/opaque.frag` (PLATING only): `uniform int u_part_hidden_mask; uniform int u_part_only;`. A pixel is hidden when `plating_part(p_body)` is in the mask, or when `u_part_only >= 0` and the part differs. The plating discard becomes the single statement `if (hidden || (cut != (u_plating_mark != 0))) discard;`.
  - `native/src/renderer/frame.cc`: an instance with `severed_parts != 0` or `only_part >= 0` draws every mesh with the plating program (no stock split), with an empty list if it has no records. Its mark and interior draws apply the same mask.
  - `native/src/host/host_bindings.cc`: `hull_split_parts(iid) -> list[dict]`.
    - It runs `find_severed_parts` for a non-rock, non-articulated instance whose segmentation is ready.
    - Per severed part, it creates a chunk instance, copying render state as `hull_split_detached` does, and its records.
    - It sets `only_part` on the chunk, ORs the bit into the parent's `severed_parts`, and returns `{part, instance_id, voxels, total_voxels, centroid, bounds_min, bounds_max, radius_gu}` in body-frame GU.
  - `engine/host_io.py` with its manifest entry.
  - `engine/appc/hull_breakup.py`: `after_wear(ship, iid, ship_instances=None, now=None)`, with the same throttle and `drain` as `after_carve`, calling `host_io.hull_split_parts`. Its component path reuses `_destroy_subsystems_inside` and `debris_chunk.spawn`, mass by voxel fraction.
  - `engine/appc/hull_wear.py` and `engine/appc/internal_blast.py`: call `hull_breakup.after_wear` after wear reaches the store.
- Test: `native/tests/renderer/plating_render_test.cc`, `tests/unit/test_hull_breakup_parts.py` (new), `tests/host/test_hull_damage_bindings.py`

- [ ] **Step 1: Write the failing tests:**
  - **GL:**
    - `SeveredPartIsHiddenOnTheParent`: a two-part model with part 1 in `severed_parts`. Its pixels are the clear colour; part 0 is unchanged.
    - `ChunkDrawsOnlyItsPart`: `only_part = 1` draws only part 1's pixels.
    - `MarkSkipsHiddenParts`: no stencil on hidden pixels.
  - **pytest:**
    - `test_after_wear_spawns_a_chunk_per_severed_part`, with fake host_io and debris_chunk.
    - `SeveredPartSpawnsOnceAndKillsItsSubsystems`: a subsystem inside the part bounds goes to condition 0 once; a second check spawns nothing.
    - `SmallShipsAndRocksNeverSever`.
  - **host:** `test_hull_split_parts_returns_nothing_for_an_intact_ship`.
- [ ] **Step 2: Reconfigure, build, run** the GL filter, the pytest files and the host file. Expect FAIL.
- [ ] **Step 3: Implement.** Rebuild `dauntless` and `_dauntless_host`.
- [ ] **Step 4: Run** `PlatingRender*:PlatingDamage*:HullInterior*:UnevenBreach*:PartSeverance*:HullClipTest.*:ScuffTest.*:DecalRenderTest.*:FrameTest.*`, the pytest files (plus `test_hull_wear.py` and `test_internal_blast.py`) and the host file. Expect PASS.
- [ ] **Step 5: Commit.**

**Known limits, stated for Mark's live check:**
- The hidden region follows the fitted part shapes (`plating_part`), not the voxel labels, so the break line is a smooth shape boundary.
- Shadows and other passes still draw a severed part on the parent until phase 4 reviews them.
