# Bridge Lighting Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the bridge-lighting baseline Mark accepted live on DBridge and EBridge — generated normals for normal-less set geometry, a ceiling downlight instead of lightmaps, SSAO with a Low/Medium/High setting, alert-level ambient, and a no-bloom ceiling on lit surfaces — as production code on `main`.

**Architecture:** Port and harden. The spike branch `spike/bridge-lighting` (worktree `.claude/worktrees/bridge-lighting-vfx`) is the reference implementation; each task writes its tests first, watches them fail, then brings across the spike's code with its spike-only shortcuts removed (env knobs, `MeshCpu` spike fields, provenance smuggled through `extra_uvs`, the legacy/flat lighting modes, the GPU probe). Normals are generated at load time only for models loaded with a new `interior` flag; the renderer's bridge pass gets one lighting path and a separate `BridgeAoPass`.

**Tech Stack:** C++20, OpenGL 4.1 core / GLSL 410, GoogleTest (`ctest`), Python 3 + pytest, CEF (JS) for panels.

**Spec:** `docs/superpowers/specs/2026-10-08-bridge-lighting-baseline-design.md` (read it first). Deviation from spec §8 item 9: the spike spec lives on the spike branch, so instead of editing it from here, Task 9 marks this production spec as implemented. Background and every rejected alternative: `docs/superpowers/specs/2026-10-07-bridge-lighting-vfx-spike-design.md` on branch `spike/bridge-lighting`.

## Global Constraints

- Work ONLY in worktree `/Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/bridge-lighting-prod`, branch `feat/bridge-lighting-baseline`. Never commit to `main`.
- **Banned git commands** (shared checkout, other sessions' uncommitted work): `git checkout -- <path>`, `git checkout .`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A`, `git add .`. Stage with explicit paths only. To mutate a file temporarily: `cp f /tmp/bak` → edit → test → `cp /tmp/bak f` → `diff f /tmp/bak`.
- Read spike source with `git show spike/bridge-lighting:<path>` — never check that branch out.
- Build (first time in this worktree): `cmake -B build -S . -DCMAKE_BUILD_TYPE=Debug && cmake --build build -j`. Never run cmake inside `native/`. Never change `CMAKE_BUILD_TYPE` of an existing build dir in place.
- **Shader edits need a reconfigure** (`cmake -B build -S .` then build): shaders are embedded at configure time. Shader compile errors only appear at RUNTIME — every shader change needs a GL test that compiles/links it.
- GLSL `#version 410 core`. Every new sampler gets an explicit texture unit; a sampler left on unit 0 silently breaks every draw.
- Never spell `game` or `sdk` as a path segment in `engine/`, `tools/`, `tests/conftest.py`, `native/src`; resolve via `engine.paths` / `test_support::game_root()`.
- Python tests: `uv run pytest <path> -q`. C++ tests: `ctest --test-dir build -R <regex> --output-on-failure`, or run the gtest binary directly (`build/native/tests/<suite>/<suite>_tests --gtest_filter=...`).
- Between tasks: `scripts/check_tests.sh` must be green; never add a line to `tests/known_failures.txt` — fix the failure.
- Values (spec §4, verbatim): `down_top 1.0`, `down_bottom 0.25`, `ao_radius 24`, `ao_strength 2.0`, `ao_bias 0.5`, `diffuse_max 0.88`, crease `40°`, presets Low 24 samples/half res, Medium 32/half (default), High 64/full; alert scale GREEN 1.5, YELLOW 1.0, RED 1.0, other 1.0.
- Commit message trailer: `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

## Review Focus

1. **A set model whose shapes are MIXED** (some authored normals, some none): authored normals must come through untouched while the others are generated — pinned in Task 2.
2. **A comm-set render right after a main-bridge render**: the comm draw must not bind or sample the main view's AO (stale texture, wrong camera) — pinned in Task 4.
3. **The window/viewport changes size between frames** (resize, render scale): AO targets must resize with no GL error and keep AO valid — pinned in Task 4.
4. **A hand-edited `settings.json` with `bridge_quality` out of range or the wrong type** (7, -1, "high"): boot must not crash and must land on a valid preset — pinned in Task 7.
5. **No player ship, or `GetAlertLevel` raising** (mission swap, cutscene): the bridge stays at ×1.0, no exception escapes the frame — pinned in Task 6.

---

### Task 1: `interior` load flag through the asset cache, bindings and set loader (no behaviour change)

**Files:**
- Modify: `native/src/assets/include/assets/cache.h` (new 7-arg `load` overload, doc)
- Modify: `native/src/assets/src/cache.cc` (6-arg overload forwards `interior=false`; key suffix; pass to context)
- Modify: `native/src/assets/src/model_build.h` (`ModelBuildContext::generate_missing_normals`)
- Modify: `native/src/host/host_bindings.cc` (`load_model_impl` param, `rep_key`, `py::arg`)
- Modify: `engine/renderer.py` (`load_model(..., interior=False)`)
- Modify: `engine/host_loop.py` (`realize_set`: the three set `load_model` calls pass `interior=True`)
- Modify: `tests/host/test_realize_set.py` and any other fake renderer whose `load_model` signature breaks (grep `def load_model(self` under `tests/`)
- Test: `native/tests/assets/cpu/cache_test.cc`, `tests/unit/test_renderer_load_model_interior.py` (create), `tests/host/test_realize_set.py`

**Interfaces:**
- Produces:
  - `assets::AssetCache::load(const fs::path&, const std::vector<fs::path>&, const std::vector<TextureReplacement>&, const std::vector<DecalRequest>&, float scale, bool geosphere, bool interior)`; the existing 6-arg overload == `interior=false`.
  - `assets::detail::ModelBuildContext::generate_missing_normals` (`bool`, default `false`). Task 2 reads it.
  - Python `engine.renderer.load_model(nif_path, texture_search_path, texture_replacements=None, decals=None, scale=1.0, geosphere=False, interior=False) -> int`.
  - Native `_h.load_model(..., geosphere=False, interior=False)`.

- [ ] **Step 1: Write the failing C++ cache-key test.** In `cache_test.cc`, next to `RegistryReplacementProducesDistinctVariant`, add (use the file's existing `game_data_present()` / path helpers; add a `dbridge_path()` helper beside `galaxy_path()` returning `test_support::game_root() / "data/Models/Sets/DBridge/Dbridge.NIF"` and `dbridge_tex_path()` = `.../Sets/DBridge/High`):

```cpp
TEST(AssetCacheTest, InteriorLoadIsADistinctCachedVariant) {
    if (!game_data_present()) GTEST_SKIP() << "game/ not installed";
    assets::AssetCache cache;
    auto plain    = cache.load(dbridge_path(), {dbridge_tex_path()}, {}, {}, 1.0f, false);
    auto interior = cache.load(dbridge_path(), {dbridge_tex_path()}, {}, {}, 1.0f, false, true);
    auto again    = cache.load(dbridge_path(), {dbridge_tex_path()}, {}, {}, 1.0f, false, true);
    EXPECT_NE(plain.get(), interior.get());
    EXPECT_EQ(interior.get(), again.get());
}
```

- [ ] **Step 2: Run it — expect a compile failure** (no 7-arg overload).
Run: `cmake --build build -j --target assets_tests 2>&1 | grep -m3 error`

- [ ] **Step 3: Implement.**
  - `model_build.h`, in `ModelBuildContext` after `decals`:
    ```cpp
    /// Generate smooth normals for every shape authored WITHOUT normals
    /// (spec 2026-10-08-bridge-lighting-baseline-design.md §3). Set only for
    /// interior-set models; false keeps build_model byte-identical.
    bool generate_missing_normals = false;
    ```
  - `cache.h`: add the 7-arg overload after the 6-arg one, documented like `geosphere` ("`interior` is folded into the cache key; the 6-argument overload is `interior = false`").
  - `cache.cc`: the 6-arg overload becomes `return load(..., scale, geosphere, /*interior=*/false);`; the body moves to the 7-arg one; the NIF key appends `+ std::string(interior ? "|interior" : "")` after the geosphere suffix; set `ctx.generate_missing_normals = interior;`. The glTF branch ignores `interior` (glTF meshes always carry normals).
  - `host_bindings.cc`: `load_model_impl(..., float scale, bool geosphere, bool interior)`; after the geosphere `rep_key` block add `if (interior) rep_key += "|interior";`; call `g_cache->load(..., scale, geosphere, interior)`; `py::arg("interior") = false` after `geosphere`.
  - `engine/renderer.py`: add `interior: bool = False` to `load_model`, document it ("load as an interior set: shapes authored without normals get generated ones (spec 2026-10-08-bridge-lighting-baseline-design.md)"), and pass `interior` through to `_h.load_model`.

- [ ] **Step 4: Run the C++ test — expect PASS** (or SKIP without BC content).
Run: `cmake --build build -j && build/native/tests/assets/assets_tests --gtest_filter='AssetCacheTest.Interior*'`

- [ ] **Step 5: Write the failing Python tests.**
  - Create `tests/unit/test_renderer_load_model_interior.py`:
    ```python
    import engine.renderer as renderer

    def test_load_model_forwards_interior_flag(monkeypatch):
        seen = {}
        def fake(nif, tex, reps, decals, scale, geosphere, interior):
            seen.update(geosphere=geosphere, interior=interior)
            return 7
        monkeypatch.setattr(renderer._h, "load_model", fake)
        assert renderer.load_model("x.nif", [], interior=True) == 7
        assert seen == {"geosphere": False, "interior": True}

    def test_load_model_interior_defaults_off(monkeypatch):
        seen = {}
        monkeypatch.setattr(renderer._h, "load_model",
                            lambda *a: seen.setdefault("interior", a[6]) or 1)
        renderer.load_model("x.nif", [])
        assert seen["interior"] is False
    ```
  - In `tests/host/test_realize_set.py`: change the fake's signature to `def load_model(self, nif_abs, tex_abs, *, interior=False):`, record `self.interior_flags.append(interior)` (init the list in `__init__`), and add:
    ```python
    def test_realize_set_loads_set_geometry_as_interior():
        r = _FakeRenderer()  # the file's existing fake class name
        # build controller + bridge set exactly as test_realize_set_loads_bridge_geometry_and_tags_instance does
        ...same setup lines as that test...
        hl.realize_set(controller, r, set_obj, is_bridge=True)
        assert r.interior_flags and all(r.interior_flags)
    ```
    Copy the setup lines verbatim from `test_realize_set_loads_bridge_geometry_and_tags_instance` (same file) — do not invent new helpers.

- [ ] **Step 6: Run — expect the realize_set test to FAIL** (`interior_flags` all False / empty).
Run: `uv run pytest tests/unit/test_renderer_load_model_interior.py tests/host/test_realize_set.py -q`

- [ ] **Step 7: Implement in `host_loop.py` `realize_set`:** the bridge-geometry `r.load_model(nif_abs, tex_abs)`, the comm-set `r.load_model(nif_abs, tex_abs)` and the viewscreen `r.load_model(vs_nif_abs, vs_tex)` each gain `interior=True`. Then `grep -rn "def load_model(self" tests/` and give every fake an `interior=False` keyword so no other host test breaks.

- [ ] **Step 8: Run the Python tests — expect PASS.**
Run: `uv run pytest tests/unit/test_renderer_load_model_interior.py tests/host -q`

- [ ] **Step 9: Gate, then commit.**
Run: `scripts/check_tests.sh`
```bash
git add native/src/assets/include/assets/cache.h native/src/assets/src/cache.cc native/src/assets/src/model_build.h native/src/host/host_bindings.cc engine/renderer.py engine/host_loop.py native/tests/assets/cpu/cache_test.cc tests/unit/test_renderer_load_model_interior.py tests/host/test_realize_set.py
git commit -m "feat(assets): interior load flag for set models (no behaviour change yet)"
```
(Add any other fake files you edited in Step 7 to the `git add`.)

---

### Task 2: T-junction repair + smooth normals for interior models, with a real provenance structure

**Files:**
- Create: `native/src/assets/src/normal_gen.h`, `native/src/assets/src/normal_gen.cc`
- Modify: `native/src/assets/CMakeLists.txt` (add `src/normal_gen.cc` after `src/mesh_build.cc`)
- Modify: `native/src/assets/src/model_build.cc` (defer upload; run generation when `ctx.generate_missing_normals`)
- Create: `native/tests/assets/cpu/normal_gen_test.cc`; Modify `native/tests/assets/CMakeLists.txt` (add `cpu/normal_gen_test.cc`)
- Test: also `native/tests/assets/gpu/model_smoke_test.cc` (DBridge integration)

**Interfaces:**
- Consumes: `ModelBuildContext::generate_missing_normals` (Task 1).
- Produces (all in `namespace assets::detail`, internal to the assets library):
  ```cpp
  inline constexpr float kSetNormalCreaseDeg = 40.0f;   // spec §3; mirrored in renderer/bridge_lighting_tuning.h's comment

  /// One shape handed to joint normal generation.
  struct NormalGenShape {
      MeshCpu*               mesh = nullptr;      // edited in place
      glm::mat4              to_model{1.0f};      // shape frame -> model space
      std::vector<glm::vec4> source_colours;      // NIF float colours, parallel to mesh->vertices; may be empty
  };

  void repair_t_junctions(MeshCpu& mesh, std::vector<glm::vec4>& source_colours);
  void generate_smooth_normals(MeshCpu& mesh, float crease_deg,
                               const std::vector<glm::vec4>& source_colours = {});
  void generate_normals_across_shapes(std::vector<NormalGenShape>& shapes, float crease_deg);
  ```
  Area weighting is the only weighting: the spike's `NormalWeight` enum and its Angle/AreaAngle paths are NOT ported. `MeshCpu` is NOT changed (no `needs_normals`, no `source_colors`).

- [ ] **Step 1: Bring the spike's tests across, adapted to the production interface.**
  `git show spike/bridge-lighting:native/tests/assets/cpu/normal_gen_test.cc > native/tests/assets/cpu/normal_gen_test.cc`, add it to `native/tests/assets/CMakeLists.txt`, then edit:
  - Delete `AreaAngleWeightingSitsBetweenTheTwo` and `AngleWeightingLetsTheBevelDragTheBigFace`; in `AreaWeightingKeepsABigFaceFlatBesideASmallBevel` drop the weight argument (area is the only mode).
  - Every `generate_smooth_normals(m, crease, colours, NormalWeight::...)` call loses its 4th argument.
  - Every `NormalGenAcross` test: replace `x.needs_normals = true; ... generate_normals_across_meshes(ptrs, mats, 40.0f, NormalWeight::Area)` with building `std::vector<NormalGenShape>` (`{&a, mat_a, {}}`, …) and calling `generate_normals_across_shapes(shapes, 40.0f)`. `MeshesThatHaveNormalsAreLeftAlone` becomes: a shape NOT passed in the vector is untouched (generation only sees what it is given — the caller decides).
  - Add the provenance test (it pins the fix for the spike's `extra_uvs` smuggling):
    ```cpp
    TEST(NormalGenAcross, ShapesKeepTheirOwnExtraUvSetCount) {
        // Shape a carries one extra UV set, shape b none. The joint pass must
        // hand each back with exactly its own channel count -- no padding, no
        // bookkeeping channels left behind.
        MeshCpu a = quad_xy(0.0f);  a.extra_uvs.push_back(std::vector<glm::vec2>(a.vertices.size(), {0.5f, 0.5f}));
        MeshCpu b = quad_xy(1.0f);
        std::vector<NormalGenShape> shapes{{&a, glm::mat4(1.0f), {}}, {&b, glm::mat4(1.0f), {}}};
        generate_normals_across_shapes(shapes, kSetNormalCreaseDeg);
        ASSERT_EQ(a.extra_uvs.size(), 1u);
        EXPECT_EQ(a.extra_uvs[0].size(), a.vertices.size());
        EXPECT_TRUE(b.extra_uvs.empty());
    }
    ```
    `quad_xy(x0)`: if the spike test file has no such helper, add one in its anonymous namespace — two triangles spanning `[x0, x0+1] × [0,1]` at z=0, normals zero, using the file's existing `at(...)` vertex helper.

- [ ] **Step 2: Run — expect compile failure** (`normal_gen.h` missing).
Run: `cmake --build build -j --target assets_tests 2>&1 | grep -m3 error`

- [ ] **Step 3: Bring the implementation across.**
  `git show spike/bridge-lighting:native/src/assets/src/normal_gen.h > native/src/assets/src/normal_gen.h` and the same for `normal_gen.cc`, add `src/normal_gen.cc` to `native/src/assets/CMakeLists.txt`, then make these production changes:
  1. Header: replace the spike declarations with the **Interfaces** block above (keep the rule documentation, retarget its spec reference to `docs/superpowers/specs/2026-10-08-bridge-lighting-baseline-design.md` §3, delete `NormalWeight`).
  2. `generate_smooth_normals`: remove the `weight` parameter and the Angle/AreaAngle branches; the contribution is the face area weight only.
  3. **Provenance.** In the spike, `generate_normals_across_meshes` concatenates all shapes into one `MeshCpu all` and smuggles per-vertex provenance through three extra `extra_uvs` channels (`ch_owner`, `ch_xy`, `ch_z`) after padding every shape's real channels to `max_extra`. Replace that with a parallel array owned by the joint pass:
     ```cpp
     struct VertexOrigin { std::uint32_t shape; glm::vec3 local_pos; };
     ```
     and thread it through the two places the spike duplicates or interpolates a vertex (vertex split in `generate_smooth_normals`, edge insertion in `repair_t_junctions`). Do it with ONE internal helper used by both, so every per-vertex array grows together:
     ```cpp
     // Every per-vertex channel the joint pass carries, grown in lockstep.
     struct VertexChannels {
         MeshCpu&                     mesh;
         std::vector<glm::vec4>&      source_colours;   // may be empty: stays empty
         std::vector<VertexOrigin>*   origins;          // nullptr outside the joint pass
         std::uint32_t duplicate(std::uint32_t v);                       // copy vertex v
         std::uint32_t interpolate(std::uint32_t a, std::uint32_t b, float t);  // a->b at t
     };
     ```
     `interpolate` must interpolate `VertexOrigin::local_pos` exactly as positions are (it is how a vertex inserted on a shared edge is mapped back into its owner's frame) and take `shape` from `a`. Each shape's real `extra_uvs` keep their own channel count: concatenate only up to the max count, and when splitting `all` back into shapes, copy back exactly `own_extra` channels (the spike already does this — keep it) and drop the padding.
     Keep the internal single-mesh entry points (`repair_t_junctions`, `generate_smooth_normals`) working with `origins == nullptr`.
  4. Remove every `std::getenv`, `fprintf(stderr, "[bridge-spike]...")` and `SPIKE` comment.

- [ ] **Step 4: Run the unit tests — expect PASS.**
Run: `cmake --build build -j --target assets_tests && build/native/tests/assets/assets_tests --gtest_filter='NormalGen*:TJunctionRepair*'`

- [ ] **Step 5: Write the failing model-level tests** in `native/tests/assets/gpu/model_smoke_test.cc` (it already has a `DBridgeIntegration` fixture with GL + content-root skips — reuse it):
```cpp
TEST_F(DBridgeIntegration, InteriorLoadGeneratesUnitNormalsForEveryShape) {
    assets::AssetCache::Config cfg; cfg.keep_cpu_data = true;
    assets::AssetCache cache(std::move(cfg));
    auto m = cache.load(dbridge_nif(), {dbridge_tex()}, {}, {}, 1.0f, false, /*interior=*/true);
    for (const auto& mesh : m->meshes) {
        const auto& cpu = *mesh.cpu_data();
        for (const auto& v : cpu.vertices)
            ASSERT_NEAR(glm::length(v.normal), 1.0f, 1e-3f) << mesh.shape_name();
    }
}

TEST_F(DBridgeIntegration, NonInteriorLoadLeavesNormalsAsAuthored) {
    assets::AssetCache::Config cfg; cfg.keep_cpu_data = true;
    assets::AssetCache cache(std::move(cfg));
    auto m = cache.load(dbridge_nif(), {dbridge_tex()}, {}, {}, 1.0f, false, /*interior=*/false);
    std::size_t nonzero = 0;
    for (const auto& mesh : m->meshes)
        for (const auto& v : mesh.cpu_data()->vertices)
            if (glm::length(v.normal) > 1e-6f) ++nonzero;
    EXPECT_EQ(nonzero, 0u) << "DBridge ships no normals; a non-interior load must not invent any";
}
```
Use whatever the fixture already names its DBridge path/texture-dir helpers (rename `dbridge_nif()` / `dbridge_tex()` to match).

Add the **Review Focus #1** test to `normal_gen_test.cc`:
```cpp
TEST(NormalGenAcross, AuthoredNormalsInAMixedModelAreUntouched) {
    // build_model passes only normal-less shapes; this pins the contract the
    // model builder relies on: a shape with normals that IS adjacent to
    // generated ones keeps its normals bit-for-bit.
    MeshCpu authored = quad_xy(0.0f);
    for (auto& v : authored.vertices) v.normal = glm::normalize(glm::vec3(0.3f, 0.0f, 1.0f));
    const MeshCpu before = authored;
    MeshCpu bare = quad_xy(1.0f);
    std::vector<NormalGenShape> shapes{{&bare, glm::mat4(1.0f), {}}};
    generate_normals_across_shapes(shapes, kSetNormalCreaseDeg);
    ASSERT_EQ(authored.vertices.size(), before.vertices.size());
    for (std::size_t i = 0; i < authored.vertices.size(); ++i)
        EXPECT_EQ(authored.vertices[i].normal, before.vertices[i].normal);
}
```

- [ ] **Step 6: Run — expect `InteriorLoadGeneratesUnitNormalsForEveryShape` to FAIL** (normals all zero; generation not wired).
Run: `cmake --build build -j && build/native/tests/assets/assets_tests --gtest_filter='DBridgeIntegration.*:NormalGenAcross.*'`

- [ ] **Step 7: Wire generation into `build_model` (`model_build.cc`).** Port the spike's deferred upload (`git show spike/bridge-lighting:native/src/assets/src/model_build.cc`, the `PendingMesh` block and the loop that uploads after generation; mesh indices recorded on nodes become `pending.size()`), with these production changes:
  - `PendingMesh` gains `bool has_authored_normals; std::vector<glm::vec4> source_colours;`, filled where the shape's `NiTriShapeData d` is in hand: `has_authored_normals = d.has_normals;` and, when `!d.has_normals && d.has_vertex_colors`, the float colours `{c.r, c.g, c.b, c.a}`.
  - After the shape loop, only `if (ctx.generate_missing_normals)`: build `std::vector<NormalGenShape>` from every pending entry with `!has_authored_normals` (`{&pm.cpu, pm.to_model, std::move(pm.source_colours)}`) and call `generate_normals_across_shapes(shapes, kSetNormalCreaseDeg)`.
  - Do NOT touch `mesh_build.cc` or `mesh.h` (the spike's `needs_normals` / `source_colors` are not ported).
  - No env knobs, no stderr prints.

- [ ] **Step 8: Run all asset tests — expect PASS.**
Run: `cmake --build build -j && build/native/tests/assets/assets_tests`

- [ ] **Step 9: Gate, then commit.**
Run: `scripts/check_tests.sh`
```bash
git add native/src/assets/src/normal_gen.h native/src/assets/src/normal_gen.cc native/src/assets/CMakeLists.txt native/src/assets/src/model_build.cc native/tests/assets/cpu/normal_gen_test.cc native/tests/assets/CMakeLists.txt native/tests/assets/gpu/model_smoke_test.cc
git commit -m "feat(assets): generate smooth normals for interior sets authored without them"
```

---

### Task 3: One downlight path in `bridge.frag`, the tuning header, the no-bloom ceiling; delete the lightmap path

**Files:**
- Create: `native/src/renderer/include/renderer/bridge_lighting_tuning.h`
- Modify: `native/src/renderer/shaders/bridge.vert`, `native/src/renderer/shaders/skinned_bridge.vert`, `native/src/renderer/shaders/bridge.frag`
- Modify: `native/src/renderer/bridge_pass.cc`, `native/src/renderer/include/renderer/bridge_pass.h` (doc comment: two sub-passes → base + characters)
- Delete: `native/src/renderer/shaders/lightmap.vert`, `native/src/renderer/shaders/lightmap.frag`; remove their `embed_shader` lines in `native/src/renderer/CMakeLists.txt`; remove `lightmap_` / `lightmap_shader()` from `pipeline.h` / `pipeline.cc`
- Modify: `native/src/assets/include/assets/material.h` + `native/src/assets/src/material_build.cc` (remove `lightmap_pass` and the block that sets it)
- Modify tests: `native/tests/renderer/pipeline_test.cc` (`BridgeAndLightmapShadersAvailable` → bridge only), `native/tests/renderer/bridge_pass_test.cc` (delete the `lightmap_pass` partition test; keep `SkipsNonBridgePassInstances` adapted), `native/tests/assets/cpu/material_build_test.cc` (delete the three `LightmapPassFlag*` tests), `native/tests/assets/gpu/model_smoke_test.cc` (`MaterialLightmapPassDistribution` → assert the Dark-slot count only)
- Create test: `native/tests/renderer/bridge_lighting_test.cc` (add to `native/tests/renderer/CMakeLists.txt`)
- Modify: `native/src/host/docs/deferred_work.md` (item 32: mark done, with this commit's subject)

**Interfaces:**
- Produces:
  ```cpp
  // renderer/bridge_lighting_tuning.h
  namespace renderer {
  struct BridgeLightingTuning {
      float down_top    = 1.0f;   // up-facing surfaces' share of the bridge ambient
      float down_bottom = 0.25f;  // down-facing (ceiling)
      float ao_radius   = 24.0f;  // view-space units (Mark's live pick, 2026-10-08)
      float ao_strength = 2.0f;   // (Mark's live pick)
      float ao_bias     = 0.5f;   // view-space units
      float diffuse_max = 0.88f;  // lit-surface ceiling; must stay < bloom threshold (bloom_pass.h, 0.9)
  };
  inline constexpr BridgeLightingTuning kBridgeLighting{};
  inline constexpr glm::vec3 kBridgeUp{0.0f, 0.0f, 1.0f};  // set instances draw with identity transforms
  // Crease angle for generated normals lives with the generator:
  // assets::detail::kSetNormalCreaseDeg (native/src/assets/src/normal_gen.h).

  /// CPU twin of bridge.frag's diffuse_ceiling (tests pin the GLSL to it).
  glm::vec3 diffuse_ceiling(glm::vec3 c, float diffuse_max);
  }
  ```
  `diffuse_ceiling` is `inline` in the header.
- Shader uniforms set by `BridgePass` (Task 4 adds the AO ones): `u_down_top`, `u_down_bottom`, `u_up`, `u_eye`, `u_diffuse_max`, `u_face_by_winding` (1 for bridge geometry, 0 for officers).

- [ ] **Step 1: Write the failing tests** in `native/tests/renderer/bridge_lighting_test.cc`:
```cpp
#include <gtest/gtest.h>
#include <renderer/bridge_lighting_tuning.h>
#include <renderer/bloom_pass.h>

using renderer::diffuse_ceiling;
using renderer::kBridgeLighting;

TEST(DiffuseCeiling, IdentityBelowTheKnee) {
    const glm::vec3 c{0.3f, 0.5f, 0.6f};   // max 0.6 < 0.7 * 0.88
    EXPECT_EQ(diffuse_ceiling(c, kBridgeLighting.diffuse_max), c);
}

TEST(DiffuseCeiling, NeverReachesTheBloomThreshold) {
    for (float b : {0.7f, 0.9f, 1.0f, 1.5f, 3.0f, 100.0f}) {
        const glm::vec3 out = diffuse_ceiling({b, b * 0.5f, b * 0.25f}, kBridgeLighting.diffuse_max);
        EXPECT_LT(std::max({out.r, out.g, out.b}), kBridgeLighting.diffuse_max) << b;
        EXPECT_LT(kBridgeLighting.diffuse_max, renderer::kBloomThreshold);
    }
}

TEST(DiffuseCeiling, HoldsHue) {
    const glm::vec3 in{2.0f, 1.0f, 0.5f};
    const glm::vec3 out = diffuse_ceiling(in, kBridgeLighting.diffuse_max);
    EXPECT_NEAR(out.g / out.r, 0.5f, 1e-5f);
    EXPECT_NEAR(out.b / out.r, 0.25f, 1e-5f);
}

TEST(DiffuseCeiling, ZeroCeilingDisables) {
    const glm::vec3 c{5.0f, 5.0f, 5.0f};
    EXPECT_EQ(diffuse_ceiling(c, 0.0f), c);
}
```
Add `inline constexpr float kBloomThreshold = 0.9f;` to `bloom_pass.h` (namespace `renderer`) and make `threshold_` default to it, so the ceiling and the threshold are pinned against one named value with no GL object constructed.

Then add GL frame tests to the same file, following the fixture pattern of `native/tests/renderer/explosion_light_frame_test.cc` (`renderer::Window` in a try/catch → `GTEST_SKIP`, `renderer::Pipeline`, a synthetic `assets::Model` built with `assets::upload_mesh`). Build two quads in one model, both with white 1×1 base textures (`BridgePass` uses its own white fallback when `Material` has no Base texture — use that: leave materials default) and authored normals: a FLOOR quad (normal +Z) and a CEILING quad (normal −Z), each filling one half of the view from a camera looking along +X. Render through `BridgePass::render` with `lighting.ambient = {0.6, 0.6, 0.6}` and read back:
```cpp
TEST_F(BridgeLightingFrame, FloorIsLitMoreThanCeiling) {
    auto [floor_px, ceiling_px] = render_floor_and_ceiling({0.6f, 0.6f, 0.6f});
    EXPECT_GT(floor_px, ceiling_px * 3);          // 1.0 vs 0.25 of ambient
}
TEST_F(BridgeLightingFrame, BrightAmbientNeverBlooms) {
    auto [floor_px, ceiling_px] = render_floor_and_ceiling({4.0f, 4.0f, 4.0f});
    EXPECT_LE(floor_px, static_cast<int>(255 * 0.88f) + 1);  // one 8-bit step of slack
}
TEST_F(BridgeLightingFrame, LightmapSlotIsIgnored) {
    // Same scene with a BLACK texture bound in the floor material's Dark stage:
    // the floor must be exactly as bright as without it.
    EXPECT_EQ(render_floor_with_dark_stage(black_1x1()), render_floor_with_dark_stage(0));
}
```
`render_floor_and_ceiling` returns the 8-bit red value at the centre of each half. For `LightmapSlotIsIgnored`, give the floor `Material` a `Dark` stage pointing at a 1×1 black texture added to `Model::textures` (`stages[Dark].texture_index`, `uv_set = 0`).

- [ ] **Step 2: Run — expect FAIL** (header missing; on main the frame renders `base × lightmap × max(ambient, emissive)`, so the floor/ceiling are equal and the black Dark stage darkens the floor).
Run: `cmake -B build -S . && cmake --build build -j --target renderer_tests 2>&1 | grep -m3 error`

- [ ] **Step 3: Implement.**
  - Create `bridge_lighting_tuning.h` (Interfaces block) with:
    ```cpp
    inline glm::vec3 diffuse_ceiling(glm::vec3 c, float diffuse_max) {
        if (diffuse_max <= 0.0f) return c;
        const float b = std::max({c.r, c.g, c.b});
        const float knee = 0.7f * diffuse_max;
        if (b <= knee) return c;
        const float range = diffuse_max - knee;
        const float r = knee + range * (1.0f - std::exp(-(b - knee) / range));
        return c * (r / b);
    }
    ```
  - `bridge.vert` / `skinned_bridge.vert`: take the spike versions (`git show spike/bridge-lighting:native/src/renderer/shaders/bridge.vert` etc.) and delete the `SPIKE` comments; they add `v_world` and `v_normal` (skinned: `layout(location = 1) in vec3 a_normal;`).
  - `bridge.frag`: rewrite `main()` as ONE path (keep every existing uniform and comment for `u_flip_v`, `u_viewscreen_brightness`, `u_viewscreen_flash`, face blend):
    ```glsl
    in vec3 v_world;
    in vec3 v_normal;
    uniform vec3  u_eye;
    uniform vec3  u_up;
    uniform float u_down_top;
    uniform float u_down_bottom;
    uniform float u_diffuse_max;
    uniform int   u_face_by_winding;  // 1: generated normals face by winding; 0: officers face the eye
    uniform int   u_unlit;            // viewscreen feed: full bright, unlit

    vec3 shading_normal() { /* spike's shading_normal(), verbatim */ }
    vec3 diffuse_ceiling(vec3 c) { /* spike's diffuse_ceiling(), verbatim; must match the C++ twin */ }

    void main() {
        // base sample, flip, face blend, alpha test: unchanged from main
        if (u_unlit != 0) {
            vec3 col = base.rgb * u_viewscreen_brightness;
            col = mix(col, vec3(1.0), clamp(u_viewscreen_flash, 0.0, 1.0));
            FragColor = vec4(col, 1.0);
            return;
        }
        vec3 n = shading_normal();
        float h = clamp(dot(n, u_up) * 0.5 + 0.5, 0.0, 1.0);
        vec3 received = u_ambient * mix(u_down_bottom, u_down_top, h);
        vec3 col = diffuse_ceiling(base.rgb * received) * u_viewscreen_brightness;
        col = mix(col, vec3(1.0), clamp(u_viewscreen_flash, 0.0, 1.0));
        FragColor = vec4(col, 1.0);
    }
    ```
    Remove `u_dark_map`, `v_uv1` use, `u_emissive`, `u_spike_light`, `u_spike_debug`, `u_emissive_gain`, `u_mesh_id`. (Debug views return in Task 8.)
  - `bridge_pass.cc`: set the new uniforms from `kBridgeLighting` / `kBridgeUp` / `camera.eye` for both shaders; `u_face_by_winding` = 1 for the base shader, 0 for the skinned shader; `u_unlit` = 1 exactly where main forced full emissive for the viewscreen override (find `viewscreen_override` / the emissive-forcing branch in `draw_mesh` and set `u_unlit` there instead, 0 otherwise). Remove the `want_lightmap_pass` parameter from `walk_bridge_meshes` and the second walk; stop binding unit 1 / `u_dark_map`. Remove every `lightmap_pass` reference.
  - Delete the lightmap shaders/pipeline members/material flag and update the four test files listed under **Files**. In `material_build.cc`, keep routing lightmaps to the `Dark` stage (ships share this code) — delete only the block that sets `lightmap_pass`.

- [ ] **Step 4: Reconfigure, build, run — expect PASS.**
Run: `cmake -B build -S . && cmake --build build -j && build/native/tests/renderer/renderer_tests --gtest_filter='DiffuseCeiling.*:BridgeLightingFrame.*:Pipeline*:BridgePass*:SkinnedBridge*:CommPass*:Viewscreen*'`
Expected: PASS (GL tests SKIP only if no GL context).

- [ ] **Step 5: Update `deferred_work.md` item 32** to "DONE (bridge lighting baseline): `lightmap_pass`, `lightmap.{vert,frag}` and `Pipeline::lightmap_shader()` removed."

- [ ] **Step 6: Gate, then commit.**
Run: `scripts/check_tests.sh`
```bash
git add native/src/renderer/include/renderer/bridge_lighting_tuning.h native/src/renderer/shaders/bridge.vert native/src/renderer/shaders/skinned_bridge.vert native/src/renderer/shaders/bridge.frag native/src/renderer/bridge_pass.cc native/src/renderer/include/renderer/bridge_pass.h native/src/renderer/CMakeLists.txt native/src/renderer/include/renderer/pipeline.h native/src/renderer/pipeline.cc native/src/renderer/include/renderer/bloom_pass.h native/src/assets/include/assets/material.h native/src/assets/src/material_build.cc native/tests/renderer/bridge_lighting_test.cc native/tests/renderer/CMakeLists.txt native/tests/renderer/pipeline_test.cc native/tests/renderer/bridge_pass_test.cc native/tests/assets/cpu/material_build_test.cc native/tests/assets/gpu/model_smoke_test.cc native/src/host/docs/deferred_work.md
git rm native/src/renderer/shaders/lightmap.vert native/src/renderer/shaders/lightmap.frag
git commit -m "feat(renderer): bridge ceiling downlight replaces lightmaps; lit surfaces never bloom"
```

---

### Task 4: `BridgeAoPass` — screen-space AO on received light (main bridge view only)

**Files:**
- Create: `native/src/renderer/include/renderer/bridge_ao_pass.h`, `native/src/renderer/bridge_ao_pass.cc`, `native/src/renderer/shaders/bridge_ao.frag`
- Modify: `native/src/renderer/CMakeLists.txt` (source + `embed_shader(SHADER_BRIDGE_AO_FS shaders/bridge_ao.frag bridge_ao_fs)`)
- Modify: `native/src/renderer/bridge_pass.cc`, `native/src/renderer/include/renderer/bridge_pass.h`, `native/src/renderer/shaders/bridge.frag`
- Test: `native/tests/renderer/bridge_ao_test.cc` (create; add to CMakeLists)

**Interfaces:**
- Consumes: `kBridgeLighting.ao_radius/ao_strength/ao_bias` (Task 3).
- Produces:
  ```cpp
  namespace renderer {
  struct BridgeAoSettings { int samples = 32; float resolution_scale = 0.5f; };  // Task 5 fills from presets
  class BridgeAoPass {
  public:
      BridgeAoPass(); ~BridgeAoPass();
      /// Render the normal+depth pre-pass via `draw_normals` (which must draw
      /// the bridge with u_output_normal = 1 into the currently bound FBO),
      /// then the AO kernel. Restores the caller's FBO and viewport.
      /// Returns false (and leaves AO invalid) if w or h < 8.
      bool render(const scenegraph::Camera& camera, int w, int h,
                  const BridgeAoSettings& s,
                  const std::function<void()>& draw_normals);
      std::uint32_t ao_texture() const;      // valid after a true render()
      std::uint32_t depth_texture() const;   // the pre-pass depth
      std::uint32_t raw_sampler() const;     // NEAREST, no compare: bind with depth_texture()
      int ao_width() const; int ao_height() const;
  };
  }
  ```
  `BridgePass` gains a member `BridgeAoPass ao_;` and a setter `void set_ao_settings(const BridgeAoSettings& s)` (Task 5 calls it).
- Shader (bridge.frag) uniforms: `u_ao` (unit **3**), `u_ao_depth` (unit **4**), `u_ao_on`, `u_ao_inv_proj`, `u_ao_screen`, `u_output_normal`. AO kernel uniforms: `u_depth`, `u_normal`, `u_view`, `u_proj`, `u_inv_proj`, `u_viewport`, `u_radius`, `u_strength`, `u_bias`, `u_samples`.

- [ ] **Step 1: Write the failing tests** in `bridge_ao_test.cc` (same synthetic-model fixture pattern as Task 3): an L-shaped CORNER (floor quad + wall quad meeting at x=0, authored normals) and a camera looking into the corner.
```cpp
TEST_F(BridgeAoFrame, InsideCornerIsDarkerThanOpenFloor) {
    const auto img = render_corner(/*ao_on=*/true);
    EXPECT_LT(img.near_corner, img.open_floor * 0.85);   // occluded
    EXPECT_GT(img.open_floor, render_corner(false).open_floor * 0.95);  // open floor ~unoccluded
}
TEST_F(BridgeAoFrame, CommSetRenderNeverBindsAo) {
    render_corner(true);                                  // main view: AO computed
    // Same model, tagged as a comm set, rendered with comm_set_id != 0:
    const auto comm = render_corner_as_comm_set();
    const auto plain = render_corner(false);
    EXPECT_EQ(comm.near_corner, plain.near_corner);       // no AO darkening at all
}
TEST_F(BridgeAoFrame, ResizeBetweenFramesKeepsAoValid) {   // Review Focus #3
    render_corner_at(256, 256, true);
    const auto small = render_corner_at(128, 96, true);
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
    EXPECT_LT(small.near_corner, small.open_floor * 0.85);
}
TEST(BridgeAoShader, CompilesAndLinksAtEverySampleCount) {
    // GL context required; skip without one. Draw a 1-frame AO at 24, 32 and 64
    // samples; glGetError must stay GL_NO_ERROR and ao_texture() non-zero.
}
```
`render_corner*` sample the centre of a 9×9 block next to the corner and on the far floor; `render_corner_as_comm_set` sets `world.set_comm_set_id(iid, 1)` (see `comm_pass_test.cc` for the exact call) and calls `pass.render(world, cam, *p, lookup, lighting, scenegraph::Pass::Bridge, 1)`. To toggle AO in tests, `BridgePass` needs a test seam: add `void set_ao_enabled(bool)` (default true) — it is also what Task 5's settings could later use; production never calls it with false.

- [ ] **Step 2: Run — expect compile failure** (no `bridge_ao_pass.h`).
Run: `cmake -B build -S . && cmake --build build -j --target renderer_tests 2>&1 | grep -m3 error`

- [ ] **Step 3: Implement.**
  - `bridge_ao.frag`: `git show spike/bridge-lighting:native/src/renderer/shaders/bridge_ao.frag`, then DELETE the 16-sample `KERNEL` table and the `n == 16` branch — the generated golden-angle cosine hemisphere is the only kernel; clamp `u_samples` to 4..64; remove `SPIKE` comments.
  - `bridge_ao_pass.cc`: move the spike's `BridgePass::render_ao` body here (`git show spike/bridge-lighting:native/src/renderer/bridge_pass.cc`, function `render_ao`) — lazy shader (`resolve_vs` + `bridge_ao_fs`), full-screen triangle VAO, raw sampler, `HdrTarget` pre-pass at w×h, `LdrTarget` AO target at `max(8, w*scale)` × `max(8, h*scale)`, save/restore FBO + viewport — with the pre-pass draw replaced by the `draw_normals` callback and radius/strength/bias from `kBridgeLighting`. Free GL objects in the destructor.
  - `bridge_pass.cc`: port the spike's AO plumbing in `render()` (`main_bridge`, viewport read, `set_ao_uniforms` lambda, unit 3/4 binding with `glBindSampler(4, ao_.raw_sampler())`, unbinding sampler 4 at the end) — the pre-pass is `ao_.render(camera, vp[2], vp[3], ao_settings_, [&]{ normal_pass_ = true; render(world, camera, pipeline, lookup, lighting, scenegraph::Pass::Bridge, 0); normal_pass_ = false; })`. Run AO only when `pass == Pass::Bridge && comm_set_id == 0 && !normal_pass_ && ao_enabled_`.
  - `bridge.frag`: port the spike's `ao_view_z`, `ao_term()` (4×4 depth-aware filter) and the normal-output early return; `received *= ao` (received light only; never the unlit feed).
  - Remove the spike's `GpuProbe` entirely (not ported).

- [ ] **Step 4: Reconfigure, build, run — expect PASS.**
Run: `cmake -B build -S . && cmake --build build -j && build/native/tests/renderer/renderer_tests --gtest_filter='BridgeAo*:BridgeLighting*:SkinnedBridge*:CommPass*'`

- [ ] **Step 5: Gate, then commit.**
Run: `scripts/check_tests.sh`
```bash
git add native/src/renderer/include/renderer/bridge_ao_pass.h native/src/renderer/bridge_ao_pass.cc native/src/renderer/shaders/bridge_ao.frag native/src/renderer/CMakeLists.txt native/src/renderer/bridge_pass.cc native/src/renderer/include/renderer/bridge_pass.h native/src/renderer/shaders/bridge.frag native/tests/renderer/bridge_ao_test.cc native/tests/renderer/CMakeLists.txt
git commit -m "feat(renderer): screen-space AO on bridge received light (BridgeAoPass)"
```

---

### Task 5: Bridge quality presets + `set_bridge_quality` / `bridge_quality` bindings

**Files:**
- Create: `native/src/renderer/include/renderer/bridge_quality.h`
- Modify: `native/src/host/host_bindings.cc` (two bindings + a `g_bridge_quality` global, default Medium, reset in the frame-state reset function next to `g_bridge_ambient_scale = 1.0f`)
- Modify: `engine/renderer.py` (wrappers + manifest entries)
- Test: `native/tests/renderer/bridge_lighting_test.cc` (preset table), `tests/host/test_bridge_bindings.py` (round trip), `tests/unit/test_renderer_binding_manifest.py` must stay green

**Interfaces:**
- Consumes: `BridgeAoSettings`, `BridgePass::set_ao_settings` (Task 4).
- Produces:
  ```cpp
  namespace renderer {
  enum class BridgeQuality : int { Low = 0, Medium = 1, High = 2 };
  inline constexpr BridgeQuality kDefaultBridgeQuality = BridgeQuality::Medium;
  BridgeAoSettings ao_settings_for(BridgeQuality q);  // Low {24,0.5} Medium {32,0.5} High {64,1.0}
  BridgeQuality clamp_bridge_quality(int v);          // <0 -> Low, >2 -> High
  }
  ```
  Python: `engine.renderer.set_bridge_quality(level: int) -> None`, `engine.renderer.bridge_quality() -> int`.

- [ ] **Step 1: Failing tests.**
```cpp
TEST(BridgeQuality, PresetsMatchTheSpec) {
    using renderer::BridgeQuality; using renderer::ao_settings_for;
    EXPECT_EQ(ao_settings_for(BridgeQuality::Low).samples, 24);
    EXPECT_FLOAT_EQ(ao_settings_for(BridgeQuality::Low).resolution_scale, 0.5f);
    EXPECT_EQ(ao_settings_for(BridgeQuality::Medium).samples, 32);
    EXPECT_FLOAT_EQ(ao_settings_for(BridgeQuality::Medium).resolution_scale, 0.5f);
    EXPECT_EQ(ao_settings_for(BridgeQuality::High).samples, 64);
    EXPECT_FLOAT_EQ(ao_settings_for(BridgeQuality::High).resolution_scale, 1.0f);
    EXPECT_EQ(renderer::kDefaultBridgeQuality, BridgeQuality::Medium);
}
TEST(BridgeQuality, NoPresetUsesSixteenSamples) {
    for (int q = 0; q <= 2; ++q)
        EXPECT_NE(renderer::ao_settings_for(static_cast<renderer::BridgeQuality>(q)).samples, 16);
}
TEST(BridgeQuality, OutOfRangeClamps) {
    EXPECT_EQ(renderer::clamp_bridge_quality(-3), renderer::BridgeQuality::Low);
    EXPECT_EQ(renderer::clamp_bridge_quality(9), renderer::BridgeQuality::High);
}
```
In `tests/host/test_bridge_bindings.py` (follow the file's existing host-module fixture):
```python
def test_bridge_quality_defaults_to_medium_and_round_trips(host):
    assert host.bridge_quality() == 1
    host.set_bridge_quality(2)
    assert host.bridge_quality() == 2
    host.set_bridge_quality(99)
    assert host.bridge_quality() == 2
    host.set_bridge_quality(1)
```

- [ ] **Step 2: Run — expect FAIL** (header / bindings missing).
Run: `cmake --build build -j --target renderer_tests 2>&1 | grep -m3 error; uv run pytest tests/host/test_bridge_bindings.py -q`

- [ ] **Step 3: Implement** `bridge_quality.h` (inline functions), the bindings:
```cpp
m.def("set_bridge_quality", [](int q) {
          g_bridge_quality = renderer::clamp_bridge_quality(q);
          if (g_bridge_pass) g_bridge_pass->set_ao_settings(renderer::ao_settings_for(g_bridge_quality));
      }, "Bridge rendering quality: 0 Low, 1 Medium (default), 2 High. Out-of-range clamps.");
m.def("bridge_quality", [] { return static_cast<int>(g_bridge_quality); });
```
and apply `ao_settings_for(g_bridge_quality)` wherever `g_bridge_pass` is constructed. `engine/renderer.py`: add `set_bridge_quality(level: int) -> None` and `bridge_quality() -> int` wrappers calling `_h.…`, and add both names to the REQUIRED manifest list (alphabetical position).

- [ ] **Step 4: Rebuild, run — expect PASS.**
Run: `cmake --build build -j && build/native/tests/renderer/renderer_tests --gtest_filter='BridgeQuality.*' && uv run pytest tests/host/test_bridge_bindings.py tests/unit/test_renderer_binding_manifest.py -q`

- [ ] **Step 5: Gate, then commit.**
```bash
scripts/check_tests.sh
git add native/src/renderer/include/renderer/bridge_quality.h native/src/host/host_bindings.cc engine/renderer.py native/tests/renderer/bridge_lighting_test.cc tests/host/test_bridge_bindings.py
git commit -m "feat(renderer): Low/Medium/High bridge quality presets (AO samples + resolution)"
```

---

### Task 6: Alert-level bridge ambient (`engine/bridge_lighting.py`)

**Files:**
- Create: `engine/bridge_lighting.py`, `tests/unit/test_bridge_lighting.py`
- Modify: `engine/host_loop.py` (the "Red-alert dim" block that sets `_bridge_dim` and calls `r.set_bridge_ambient_scale`)

**Interfaces:**
- Produces: `engine.bridge_lighting.ambient_scale_for_alert(level) -> float`; `engine.bridge_lighting.player_bridge_ambient_scale(player) -> float` (None-safe, exception-safe wrapper used by `host_loop`).

- [ ] **Step 1: Failing tests** (`tests/unit/test_bridge_lighting.py`):
```python
import pytest
from engine import bridge_lighting as bl

@pytest.mark.parametrize("level,scale", [(0, 1.5), (1, 1.0), (2, 1.0), (3, 1.0), (-1, 1.0)])
def test_ambient_scale_for_alert(level, scale):
    assert bl.ambient_scale_for_alert(level) == scale

def test_no_player_is_authored_ambient():            # Review Focus #5
    assert bl.player_bridge_ambient_scale(None) == 1.0

def test_alert_probe_raising_is_authored_ambient():  # Review Focus #5
    class Broken:
        def GetAlertLevel(self): raise RuntimeError("mid swap")
    assert bl.player_bridge_ambient_scale(Broken()) == 1.0

def test_green_player():
    class P:
        def GetAlertLevel(self): return 0
    assert bl.player_bridge_ambient_scale(P()) == 1.5

def test_host_loop_uses_the_module():
    import inspect, engine.host_loop as hl
    src = inspect.getsource(hl)
    assert "player_bridge_ambient_scale(" in src
    assert "_bridge_dim = 0.5" not in src
```

- [ ] **Step 2: Run — expect FAIL** (`ModuleNotFoundError`).
Run: `uv run pytest tests/unit/test_bridge_lighting.py -q`

- [ ] **Step 3: Implement** `engine/bridge_lighting.py`:
```python
"""Bridge-interior lighting rules that live on the Python side.

Spec: docs/superpowers/specs/2026-10-08-bridge-lighting-baseline-design.md §5.
"""
from engine import dev_mode

# Interior ambient multiplier per ShipClass alert level (GREEN 0, YELLOW 1,
# RED 2). Green is the brightly lit cruising bridge; x2.0 read too bright live
# (Mark, 2026-10-08). x1.0 is the SDK-authored bridge ambient.
_ALERT_AMBIENT_SCALE = {0: 1.5, 1: 1.0, 2: 1.0}


def ambient_scale_for_alert(level) -> float:
    return _ALERT_AMBIENT_SCALE.get(int(level), 1.0)


def player_bridge_ambient_scale(player) -> float:
    """The scale for the player's current alert level; 1.0 when there is no
    player or the probe fails (mission swap, cutscene)."""
    if player is None:
        return 1.0
    try:
        return ambient_scale_for_alert(player.GetAlertLevel())
    except Exception as e:  # noqa: BLE001 - never let a probe kill the frame
        dev_mode.log_swallowed("alert bridge-ambient probe", e)
        return 1.0
```
In `host_loop.py`, replace the whole red-alert block with:
```python
            # Alert-level bridge brightness (engine.bridge_lighting): sent as a
            # separate scale, not baked into the ambient, so the comm-set
            # viewscreen feed — another ship's room — keeps constant brightness.
            r.set_bridge_ambient_scale(_bridge_lighting.player_bridge_ambient_scale(player))
```
and add `from engine import bridge_lighting as _bridge_lighting` with the module's other `engine` imports.

- [ ] **Step 4: Run — expect PASS.**
Run: `uv run pytest tests/unit/test_bridge_lighting.py -q`

- [ ] **Step 5: Gate, then commit.**
```bash
scripts/check_tests.sh
git add engine/bridge_lighting.py tests/unit/test_bridge_lighting.py engine/host_loop.py
git commit -m "feat(bridge): alert-level interior ambient -- green x1.5, yellow/red x1.0"
```

---

### Task 7: "Bridge rendering" setting + configuration-panel control

**Files:**
- Modify: `engine/settings_store.py` (`SETTINGS` row), `engine/ui/configuration_panel.py`, `native/assets/ui-cef/js/configuration_panel.js`, `engine/host_loop.py` (`ConfigurationPanel(...)` construction)
- Test: `tests/unit/test_settings_store.py`, `tests/unit/test_configuration_panel.py`

**Interfaces:**
- Consumes: `r.set_bridge_quality`, `r.bridge_quality` (Task 5).
- Produces: settings key `bridge_quality` (section `graphics`, field `bridge_quality`, int 0..2, `reset_default=1`); `SettingsSnapshot.bridge_quality: int = 1`; `ConfigurationPanel(..., set_bridge_quality: Callable[[int], None], ...)`; panel action `bridge_quality:<0|1|2>`; focusable `("ctrl", "bridge_quality")` placed right after `("ctrl", "aa_mode")`.

- [ ] **Step 1: Failing tests.**
  - `test_settings_store.py` (use the file's existing fake ctx / store fixtures):
    ```python
    def test_bridge_quality_row():
        s = settings_store.setting_for("bridge_quality")
        assert (s.section, s.field, s.lo, s.hi, s.reset_default) == ("graphics", "bridge_quality", 0, 2, 1)

    def test_bridge_quality_applier_reaches_renderer(fake_ctx):
        settings_store.apply_setting(fake_ctx, "bridge_quality", 2)
        assert fake_ctx.r.calls[-1] == ("set_bridge_quality", 2)

    @pytest.mark.parametrize("bad", [7, -1, "high", None])          # Review Focus #4
    def test_bad_stored_bridge_quality_never_crashes_boot(tmp_path, fake_ctx, bad):
        store = settings_store.SettingsStore(tmp_path / "settings.json")
        store.set("graphics", "bridge_quality", bad)
        settings_store.apply_all(store, fake_ctx)            # must not raise
        applied = [v for name, v in fake_ctx.r.calls if name == "set_bridge_quality"]
        assert all(0 <= v <= 2 for v in applied)
        snap = settings_store.snapshot_for_panel(store, fake_ctx)
        assert 0 <= snap.bridge_quality <= 2
    ```
    Match `fake_ctx.r`'s recording style to whatever the file's existing fake does (if it records differently, assert in that style). If the existing fake renderer lacks `set_bridge_quality` / `bridge_quality`, add them to it.
  - `test_configuration_panel.py`: extend the file's panel-construction helper with `set_bridge_quality=…` (a recorder), then:
    ```python
    def test_bridge_quality_click_applies_and_persists(panel, recorded):
        assert panel.dispatch_event("bridge_quality:2")
        assert recorded.bridge_quality == [2]
        assert recorded.on_change[-1] == ("bridge_quality", 2)

    def test_bridge_quality_out_of_range_click_clamps(panel, recorded):
        panel.dispatch_event("bridge_quality:9")
        assert recorded.bridge_quality[-1] == 2

    def test_bridge_quality_in_payload(panel):
        panel.open()
        assert '"bridge_quality": 1' in panel.render_payload()
    ```
    and update `test_js_graphics_focusables_match_python` expectations by adding `bridge_quality` after `aa_mode` (it compares JS vs Python — it will fail until both change).

- [ ] **Step 2: Run — expect FAIL.**
Run: `uv run pytest tests/unit/test_settings_store.py tests/unit/test_configuration_panel.py -q`

- [ ] **Step 3: Implement.**
  - `settings_store.py`, after the `aa_mode` row:
    ```python
    Setting("bridge_quality", "graphics", "bridge_quality", int,
            lambda c: int(c.r.bridge_quality()),
            lambda c, v: c.r.set_bridge_quality(v),
            lo=0, hi=2, reset_default=1),
    ```
    If `_stored` / `apply_all` does not already reject a non-int or out-of-range stored value for rows with `lo`/`hi`, make it treat such a value as ABSENT (so the applier is not called and the native Medium default stands) — and confirm the existing `ai_difficulty` tests still pass.
  - `configuration_panel.py`: `SettingsSnapshot.bridge_quality: int = 1`; constructor param `set_bridge_quality: Callable[[int], None]` (after `set_aa_mode`), stored as `self._set_bridge_quality`; clamp in the snapshot copy (`max(0, min(2, int(...)))`); add `self._settings.bridge_quality` to the `render_payload` snapshot tuple AND `"bridge_quality"` to the payload's `settings`; `dispatch_event` branch mirroring `ai_difficulty:` (parse int, clamp 0..2, call setter, store, `_on_change("bridge_quality", level)`); keyboard left/right branch mirroring `ai_difficulty`; `_focusables` graphics list becomes `aa_mode, bridge_quality, dust, fov, …` and its docstring example likewise.
  - `configuration_panel.js`: `CP_GRAPHICS_STANDALONE = ['aa_mode', 'bridge_quality', 'dust', 'fov'];` and, directly after the Anti-aliasing row, a segmented row cloned from the AI Difficulty one:
    ```js
    // Bridge rendering — three-way segmented control (Low / Medium / High):
    // the bridge's ambient-occlusion quality. High is meant for gaming GPUs.
    const bqLabels = ['Low', 'Medium', 'High'];
    const bq = (typeof s.bridge_quality === 'number') ? s.bridge_quality : 1;
    html += '<div class="cp-row' + (isFoc('bridge_quality') ? ' cp-focused' : '') + '">'
          +     '<span class="cp-label">Bridge Rendering</span>'
          +     '<div class="cp-segmented">';
    for (let i = 0; i < bqLabels.length; ++i) {
        html += '<button class="cp-toggle' + (bq === i ? ' cp-toggle--on' : '') + '"'
              +    ' onclick="dauntlessEvent(\'configuration/bridge_quality:' + i + '\')">'
              +    bqLabels[i]
              + '</button>';
    }
    html += '</div></div>';
    ```
  - `host_loop.py` `ConfigurationPanel(...)`: `set_bridge_quality=lambda q: _settings.apply_setting(_settings_ctx, "bridge_quality", q),`.

- [ ] **Step 4: Run — expect PASS.**
Run: `uv run pytest tests/unit/test_settings_store.py tests/unit/test_configuration_panel.py tests/unit/test_configuration_panel_bridges.py -q`

- [ ] **Step 5: Gate, then commit.**
```bash
scripts/check_tests.sh
git add engine/settings_store.py engine/ui/configuration_panel.py native/assets/ui-cef/js/configuration_panel.js engine/host_loop.py tests/unit/test_settings_store.py tests/unit/test_configuration_panel.py
git commit -m "feat(settings): Bridge Rendering Low/Medium/High in the Graphics tab"
```

---

### Task 8: Developer-only bridge debug views

**Files:**
- Modify: `native/src/renderer/shaders/bridge.frag`, `native/src/renderer/bridge_pass.cc`, `native/src/renderer/include/renderer/bridge_pass.h`
- Modify: `native/src/host/host_bindings.cc` (binding), `engine/renderer.py` (wrapper + manifest)
- Modify: `engine/ui/developer_options_panel.py`, `native/assets/ui-cef/js/developer_options.js`
- Test: `native/tests/renderer/bridge_lighting_test.cc`, `tests/unit/test_developer_options_panel.py`, `tests/host/test_bridge_bindings.py`

**Interfaces:**
- Produces:
  ```cpp
  enum class BridgeDebugView : int { Off = 0, Normals = 1, LightOnly = 2, AoOnly = 3, TriangleId = 4, MeshId = 5 };
  void BridgePass::set_debug_view(BridgeDebugView v);   // uniform u_debug_view
  ```
  Native binding `set_bridge_debug_view(int)` — a no-op unless `dauntless::is_developer_mode()`; Python `engine.renderer.set_bridge_debug_view(view: int)`. Dev-options action `action:bridge_debug_view` cycling 0→5→0, row label "Bridge Debug View" in the Lighting tab, values `Off / Normals / Light Only / AO Only / Triangle ID / Mesh ID`.

- [ ] **Step 1: Failing tests.**
  - C++ (`bridge_lighting_test.cc`, `BridgeLightingFrame` fixture): with `set_debug_view(BridgeDebugView::Normals)` the floor quad (normal +Z) renders ≈ (128,128,255) ±2; with `LightOnly` a red base texture renders grey (r == g == b ±1); with `Off` it renders red.
  - Host (`test_bridge_bindings.py`): with developer mode off, `host.set_bridge_debug_view(1)` does not raise and has no effect (assert via whatever getter you add — add `bridge_debug_view()` returning the active value, 0 when not developer).
  - Python (`test_developer_options_panel.py`):
    ```python
    def test_bridge_debug_view_cycles(monkeypatch):
        calls = []
        monkeypatch.setattr(renderer, "set_bridge_debug_view", calls.append)
        p = DeveloperOptionsPanel()
        for expected in (1, 2, 3, 4, 5, 0):
            assert p.dispatch_event("action:bridge_debug_view")
            assert calls[-1] == expected
    ```
    `test_every_setting_is_in_the_render_snapshot` must keep passing: add the new field to the snapshot tuple AND to `settings` (`"bridge_debug_view": "Off"` etc.).

- [ ] **Step 2: Run — expect FAIL.**
Run: `cmake -B build -S . && cmake --build build -j --target renderer_tests 2>&1 | grep -m3 error; uv run pytest tests/unit/test_developer_options_panel.py -q`

- [ ] **Step 3: Implement.**
  - `bridge.frag`: `uniform int u_debug_view;` after `n` is known: 1 → `FragColor = vec4(n*0.5+0.5, 1)`; 2 → use `albedo = vec3(1)`; 3 → `FragColor = vec4(vec3(ao), 1)`; 4/5 → the spike's hash colouring of `gl_PrimitiveID` / `u_mesh_id` (port from `git show spike/bridge-lighting:native/src/renderer/shaders/bridge.frag`). Viewscreen (`u_unlit`) ignores debug views.
  - `bridge_pass.cc`: `set_debug_view` stores it; set `u_debug_view` on both shaders; set `u_mesh_id` per draw (an incrementing counter per `render()`, reset each frame — stable within a frame).
  - Binding + getter in `host_bindings.cc` (gate with `dauntless::is_developer_mode()`), wrappers in `engine/renderer.py` (+ manifest; mark `set_bridge_debug_view` REQUIRED).
  - Panel: `_ACTION_CONTROLS` gains `"bridge_debug_view"`; state `self._bridge_debug_view = 0`; names tuple `("Off", "Normals", "Light Only", "AO Only", "Triangle ID", "Mesh ID")`; dispatch `action:bridge_debug_view` → `(v + 1) % 6`, call `renderer.set_bridge_debug_view(v)`; focusables (lighting tab, appended); JS: lighting focusables + `_doValueRow('Bridge Debug View', 'bridge_debug_view', s.bridge_debug_view, isFoc('bridge_debug_view'))`.

- [ ] **Step 4: Rebuild, run — expect PASS.**
Run: `cmake -B build -S . && cmake --build build -j && build/native/tests/renderer/renderer_tests --gtest_filter='BridgeLighting*' && uv run pytest tests/unit/test_developer_options_panel.py tests/host/test_bridge_bindings.py tests/unit/test_renderer_binding_manifest.py -q`

- [ ] **Step 5: Gate, then commit.**
```bash
scripts/check_tests.sh
git add native/src/renderer/shaders/bridge.frag native/src/renderer/bridge_pass.cc native/src/renderer/include/renderer/bridge_pass.h native/src/host/host_bindings.cc engine/renderer.py engine/ui/developer_options_panel.py native/assets/ui-cef/js/developer_options.js native/tests/renderer/bridge_lighting_test.cc tests/unit/test_developer_options_panel.py tests/host/test_bridge_bindings.py
git commit -m "feat(dev): bridge debug views (normals, light, AO, triangle/mesh id) in Developer Options"
```

---

### Task 9: Docs

**Files:**
- Modify: `CLAUDE.md` (Key reference material table: one new row)
- Modify: the spike spec pointer — add to `docs/superpowers/specs/2026-10-08-bridge-lighting-baseline-design.md` a "Status: implemented on `feat/bridge-lighting-baseline`" line (the spike spec lives on the spike branch; do not edit it from here)
- Test: `uv run pytest tests/docs -q`

- [ ] **Step 1:** Add a CLAUDE.md row after "Ship-attached dynamic lights":
```
| Bridge lighting baseline — downlight + SSAO, no lightmaps | `native/src/renderer/{bridge_pass,bridge_ao_pass}.cc`, `renderer/bridge_lighting_tuning.h`, `renderer/bridge_quality.h`, `native/src/assets/src/normal_gen.{h,cc}`, `engine/bridge_lighting.py`, `docs/superpowers/specs/2026-10-08-bridge-lighting-baseline-design.md` | BC's bridge lightmaps are NOT rendered. Interior sets load with `interior=True`: shapes authored without normals get generated ones (T-junction repair, 40° crease, area weighting) — ships never do. `bridge.frag`: `ambient × mix(0.25, 1.0, up-facing) × AO`, then a soft ceiling under bloom's 0.9 threshold (**lit surfaces never bloom; only emitters do**). AO is main-view only (never the comm-set feed), presets Low/Medium/High = 24/32/64 samples, High at full res and meant for gaming GPUs. Alert ambient green ×1.5, yellow/red ×1.0. All tuning values are ONE header (rebuild to tune). Debug views: Developer Options → Lighting → Bridge Debug View. ⚠️ `Map 3.tga` (DBridge alcove) has a cove glow painted into its DIFFUSE — not a lightmap; deliberately left for the emitters phase. |
```
- [ ] **Step 2:** Run `uv run pytest tests/docs -q` — expect PASS.
- [ ] **Step 3: Commit.**
```bash
git add CLAUDE.md docs/superpowers/specs/2026-10-08-bridge-lighting-baseline-design.md
git commit -m "docs: bridge lighting baseline reference row"
```

---

## After Task 9 (not a subagent task)

1. Whole-branch review.
2. Give Mark plain launch commands for the worktree (`./build/dauntless --developer`, no `#` comments, no `DAUNTLESS_MISSION`) and the live checklist from spec §7: DBridge + EBridge at Medium match the spike; green/yellow/red; Bridge Rendering switches live and persists across relaunch.
3. Merge to `main` only on Mark's explicit OK.
